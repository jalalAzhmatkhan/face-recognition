import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import EnrollmentConsentCopy from '../../components/EnrollmentConsentCopy'
import ProgressRing from './ProgressRing'
import {
  completeEnrollment,
  buildPresignRequestBody,
  getAccessToken,
  getEnrollmentQualityParams,
  grantConsent,
  presignMedia,
  uploadToS3,
} from './apiClient'
import { computeSha256 } from './checksum'
import {
  countDone,
  createInitialTrackerState,
  DEFAULT_POSE_SENSITIVITY,
  describePose,
  isCaptureComplete,
  nextTargetPosition,
  updateSectorState,
} from './clockSectors'
import type { PoseBreakdown, PoseSensitivity, SectorTrackerState } from './clockSectors'
import {
  admitFrame,
  BURST_SIZE,
  createEmptyBurstBuffer,
  flattenBurstBuffer,
  shouldAdmit,
} from './burstBuffer'
import type { BurstBuffer } from './burstBuffer'
import { detectFace, loadFaceDetectionModels } from './faceDetector'
import { averagePose, calibrateToNeutral, estimateHeadPose } from './headPose'
import { assessQuality, QUALITY_THRESHOLDS } from './imageQuality'
import { runConcurrent } from './uploadQueue'
import {
  CAPTURE_POSITION_LABEL,
  CAPTURE_POSITIONS,
  CLOCK_POSITIONS,
  CURRENT_CONSENT_VERSION,
} from './types'
import type { ClockPosition, HeadPose, QualityStatus } from './types'
import './EnrollmentCapturePage.css'

type WizardStep =
  | 'consent'
  | 'preflight'
  | 'countdown'
  | 'sweep'
  | 'review'
  | 'uploading'
  | 'done'

const SAMPLE_INTERVAL_MS = 150
/** How many sweep-frame uploads are in flight at once. Each one is a
 * presign round-trip plus a PUT, and there are up to 12 x BURST_SIZE of
 * them; fully serial is needlessly slow, unbounded would hammer both our
 * API and the browser's connection pool. */
const UPLOAD_CONCURRENCY = 4
const COUNTDOWN_START_S = 3
/** How many recent preflight pose samples are averaged into the neutral
 * baseline (see `headPose.ts::calibrateToNeutral`). At SAMPLE_INTERVAL_MS
 * this is the last ~0.75 s before the frontal photo is taken. */
/**
 * How many recent poses are averaged into the neutral baseline.
 *
 * Sized to cover the whole 3s countdown at SAMPLE_INTERVAL_MS (~20 frames)
 * rather than the ~0.75s the old value of 5 covered. The baseline has to be
 * GOOD, not merely present: the estimator's usable pitch swing is only about
 * +-8 degrees and it sits on a structural +6.6 degree offset (a frontal face
 * reads "tilted up", because the nose tip sits above the eye/chin midpoint),
 * and `pitchGain` then multiplies whatever is left over by 3.5. A baseline
 * off by two degrees is therefore worth ~0.35 of normalised pitch — enough
 * to rotate the entire dial. Averaging a longer, purposeful window is the
 * cheapest way to keep that error small.
 */
const NEUTRAL_SAMPLE_COUNT = 20

/**
 * S-30 Enrollment capture wizard (FR-ENR-02/03/04).
 *
 * Motion model per FSD-AI.md ASM-03 (CORRECTED 2026-08-30): the subject's
 * body stays facing the camera the whole time; only head yaw/pitch sweeps
 * through the 12 clock positions. Every position must show a detected
 * face — there is no back-of-head / auto-pass sector.
 *
 * Capture shape (changed 2026-09-02, was one `rotation.webm` of the whole
 * sweep): the frontal photo, then a short BURST of stills auto-captured per
 * clock position as the subject's head reaches it — no recording, no
 * shutter button during the sweep. Positions may be reached in any order,
 * which is what the video path could never police: with a video, a subject
 * who jumped 12->1->2->3 then straight to 11->10->9 still produced one
 * artifact the server had to decompose and guess at, whereas each still
 * here carries the position it was captured for. See `burstBuffer.ts` for
 * why a burst rather than a single still.
 *
 * Media never touches local storage: the frontal photo and every sweep
 * frame live only as in-memory Blobs until they are uploaded straight to S3
 * via BE-06's presigned URLs, after which they are dropped.
 *
 * EC-FE-02 (TSD-edge-cases.md A-2) matched-condition + preflight reject:
 * the consent step shows the matched-condition instruction text and gates
 * "Saya Setuju & Mulai" behind an explicit confirmation checkbox ("saya
 * sudah melepas masker/sunglasses"). This is a deliberately minimal
 * client-side gate, NOT a real-time ML detector — EC-IN-03's
 * masked/sunglasses classifier is a server-side PyTorch/ONNX model
 * (`ai_inference.pipeline.mask_sunglasses`) with no synchronous HTTP
 * endpoint the browser can call before upload, and loading it client-side
 * via onnxruntime-web is out of scope for this task. There is also no
 * server-side signal this page can currently consume after upload: EC-TR-02's
 * `qc_report` (`ai_training/src/ai_training/quality/report.py`) has no
 * masked/sunglasses field — that classifier's only wired integration point
 * is the `/recognize` (EC-IN-03) path, not the enrollment QC pipeline. If a
 * masked/sunglasses signal is later added to `qc_report`, this page can
 * surface it the same way it already surfaces `REJECTED_QUALITY`.
 *
 * EC-FE-05 (TSD-edge-cases.md ASM-EC-05, backend constant in
 * `backend/app/models/consent.py`): the consent step also now shows three
 * additional clauses (synthetic masked template, door-camera event-frame
 * calibration/probe use, adaptive probe-buffer refresh) and, on clicking
 * "Saya Setuju & Mulai", sends `CURRENT_CONSENT_VERSION` ("v1.2") to
 * `POST /enrollments/{id}/consent`. That call is intentionally best-effort:
 * the backend only accepts a new consent grant while the session is
 * `CREATED`, but most sessions reach this wizard already past that state
 * (operator flow: grant consent + recapture on `EnrollmentDetailPage.tsx`
 * moves the session to CAPTURING *before* navigating here) — ASM-EC-05
 * states re-consent must never block an existing user's capture, so any
 * failure here (409 "already consented" included) is swallowed and camera
 * start proceeds regardless.
 */
export default function EnrollmentCapturePage() {
  const { id: enrollmentId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isAuthenticated = Boolean(getAccessToken())

  const [step, setStep] = useState<WizardStep>('consent')
  const [matchedConditionConfirmed, setMatchedConditionConfirmed] = useState(false)
  const [modelsReady, setModelsReady] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [faceInFrame, setFaceInFrame] = useState(false)
  const [quality, setQuality] = useState<QualityStatus>('poor')
  const [tracker, setTracker] = useState<SectorTrackerState>(
    createInitialTrackerState,
  )
  const [elapsedS, setElapsedS] = useState(0)
  const [photoBlob, setPhotoBlob] = useState<Blob | null>(null)
  const [uploadStatus, setUploadStatus] = useState<{
    photo: 'idle' | 'uploading' | 'done' | 'error'
    frames: 'idle' | 'uploading' | 'done' | 'error'
  }>({ photo: 'idle', frames: 'idle' })
  const [framesUploaded, setFramesUploaded] = useState(0)
  const [uploadError, setUploadError] = useState<string | null>(null)
  // 3-2-1 countdown shown right before recording actually starts (initial
  // start AND every retry) so the subject isn't caught off guard the
  // instant they land on the 'video' step -- see the 'countdown' step
  // effect below.
  const [countdownValue, setCountdownValue] = useState(COUNTDOWN_START_S)
  // System Parameter menu override (pages/SystemParametersPage.tsx) --
  // starts at the built-in defaults and is replaced once (if) the fetch
  // below succeeds, so this wizard is fully usable even before the first
  // frame samples if the settings service is briefly unavailable.
  const [qualityThresholds, setQualityThresholds] = useState(QUALITY_THRESHOLDS)
  // Head-pose sensitivity, same System Parameter row as the thresholds above
  // and the same best-effort fallback.
  const [poseSensitivity, setPoseSensitivity] = useState<PoseSensitivity>(
    DEFAULT_POSE_SENSITIVITY,
  )
  // Dev-only live pose readout (see the debug panel in the JSX). Held in
  // state so it re-renders, but ONLY populated while `import.meta.env.DEV`
  // is set -- in production the sampling loop never touches it.
  const [poseDebug, setPoseDebug] = useState<
    (PoseBreakdown & { raw: HeadPose; neutral: HeadPose | null }) | null
  >(null)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  // Captured sweep frames, keyed by clock position. A ref, not state: the
  // sampling loop writes to it every SAMPLE_INTERVAL_MS and re-rendering on
  // each admitted frame would be wasted work -- `burstCounts` below is the
  // cheap render-visible projection of it.
  const burstRef = useRef<BurstBuffer>(createEmptyBurstBuffer())
  const [burstCounts, setBurstCounts] = useState<Record<ClockPosition, number>>(
    () => {
      const counts = {} as Record<ClockPosition, number>
      for (const position of CLOCK_POSITIONS) counts[position] = 0
      return counts
    },
  )
  const sampleTimerRef = useRef<number | null>(null)
  const elapsedTimerRef = useRef<number | null>(null)
  // Neutral-pose calibration (see `headPose.ts::calibrateToNeutral` for WHY
  // this exists): `recentNeutralPosesRef` is a rolling window of the last
  // few poses seen while the subject was framing up for the frontal photo,
  // and `neutralPoseRef` freezes their average at the instant that photo is
  // taken. Refs, not state: they feed the sampling loop only and must never
  // trigger a re-render (the loop runs every SAMPLE_INTERVAL_MS).
  const recentNeutralPosesRef = useRef<HeadPose[]>([])
  const neutralPoseRef = useRef<HeadPose | null>(null)
  const sectorsDone = countDone(tracker.status)
  const canFinishSweep = isCaptureComplete(tracker.status)
  const totalFrames = CLOCK_POSITIONS.reduce(
    (sum, position) => sum + burstCounts[position],
    0,
  )
  // Directional guidance animation ("animasi arahan") -- which not-yet-done
  // position ProgressRing's pulsing chevron should point at next.
  const targetPosition = nextTargetPosition(tracker.status)
  // Load face-detection models once, up front.
  useEffect(() => {
    loadFaceDetectionModels()
      .then(() => setModelsReady(true))
      .catch(() => setCameraError('Gagal memuat model deteksi wajah.'))
  }, [])

  // System Parameter menu override for the live sharpness/brightness gate
  // (see `qualityThresholds` state above). Best-effort: a failed fetch
  // silently keeps `QUALITY_THRESHOLDS`, never blocks/errors the wizard --
  // this is a quality-gate tuning knob, not a security control.
  useEffect(() => {
    getEnrollmentQualityParams()
      .then((params) => {
        setQualityThresholds({
          minBlurVariance: params.min_blur_variance,
          minBrightness: params.min_brightness,
          maxBrightness: params.max_brightness,
        })
        // Each pose field falls back individually: a backend older than
        // these fields omits them, and a partially-populated row must not
        // drag the others to `undefined`.
        setPoseSensitivity({
          yawGain: params.yaw_gain ?? DEFAULT_POSE_SENSITIVITY.yawGain,
          pitchGain: params.pitch_gain ?? DEFAULT_POSE_SENSITIVITY.pitchGain,
          minPoseRadius:
            params.min_pose_radius ?? DEFAULT_POSE_SENSITIVITY.minPoseRadius,
        })
      })
      .catch(() => {
        // Keep QUALITY_THRESHOLDS / DEFAULT_POSE_SENSITIVITY -- see docstring.
      })
  }, [])

  const stopCamera = useCallback(() => {
    if (sampleTimerRef.current !== null) {
      window.clearInterval(sampleTimerRef.current)
      sampleTimerRef.current = null
    }
    if (elapsedTimerRef.current !== null) {
      window.clearInterval(elapsedTimerRef.current)
      elapsedTimerRef.current = null
    }
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  useEffect(() => stopCamera, [stopCamera])

  const startCamera = useCallback(async () => {
    if (enrollmentId) {
      try {
        await grantConsent(enrollmentId, CURRENT_CONSENT_VERSION)
      } catch {
        // Best-effort — see the module docstring: a session that already
        // has consent on record (the common case) 409s here, and
        // ASM-EC-05 says that must never block capture from starting.
      }
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
      })
      streamRef.current = stream
      setCameraError(null)
      setStep('preflight')
    } catch {
      setCameraError(
        'Tidak dapat mengakses kamera. Periksa izin kamera pada browser.',
      )
    }
  }, [enrollmentId])

  // The <video> element only exists in the DOM once `step` is 'preflight'/
  // 'video' (see the JSX below), but the stream is acquired one step
  // earlier while still on 'consent' -- so `videoRef.current` was always
  // null at the point `startCamera` used to try assigning `srcObject`
  // directly, and the camera light would turn on with nothing ever
  // rendered. Attach the already-acquired stream here instead, once the
  // <video> element has actually mounted.
  useEffect(() => {
    const video = videoRef.current
    const stream = streamRef.current
    if (
      (step === 'preflight' || step === 'countdown' || step === 'sweep') &&
      video &&
      stream &&
      video.srcObject !== stream
    ) {
      video.srcObject = stream
      void video.play()
    }
  }, [step])

  /** Encode the canvas' current contents as a JPEG blob. Promisified
   * `toBlob` (not `toDataURL`) so the bytes are never materialised as a
   * base64 string. */
  const encodeCanvasJpeg = useCallback(
    (canvas: HTMLCanvasElement): Promise<Blob | null> =>
      new Promise((resolve) => {
        canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.92)
      }),
    [],
  )

  // Continuous face/quality sampling while camera is live (preflight + sweep steps).
  const sampleFrame = useCallback(async () => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || video.videoWidth === 0) return

    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
    const qualityAssessment = assessQuality(imageData, qualityThresholds)
    setQuality(qualityAssessment.status)

    const detection = await detectFace(canvas)
    setFaceInFrame(detection.faceInFrame)

    const pose = detection.landmarks
      ? estimateHeadPose(detection.landmarks)
      : null

    // Neutral-baseline candidates. Collected on the countdown step as well
    // as preflight, because the countdown is the better moment: it tells the
    // subject in as many words to look straight at the CAMERA, and it lasts
    // long enough to average ~20 frames. Preflight only gives whatever the
    // subject happened to be doing at the instant they clicked the shutter —
    // usually looking at the screen (below the camera on a laptop), which
    // bakes a downward tilt into the baseline and rotates the whole dial
    // upward once `pitchGain` multiplies it.
    if ((step === 'preflight' || step === 'countdown') && pose) {
      recentNeutralPosesRef.current = [
        ...recentNeutralPosesRef.current,
        pose,
      ].slice(-NEUTRAL_SAMPLE_COUNT)
    }

    // Dev-only pose readout. Computed on BOTH preflight and sweep so the
    // neutral baseline can be sanity-checked before the sweep even starts
    // (a frontal face should read close to 0/0 once calibrated).
    if (import.meta.env.DEV) {
      const debugPose = pose ? calibrateToNeutral(pose, neutralPoseRef.current) : null
      setPoseDebug(
        debugPose && pose
          ? {
              ...describePose(debugPose, poseSensitivity),
              raw: pose,
              neutral: neutralPoseRef.current,
            }
          : null,
      )
    }

    if (step !== 'sweep') return

    const calibratedPose = pose ? calibrateToNeutral(pose, neutralPoseRef.current) : null
    const clockPosition = calibratedPose
      ? describePose(calibratedPose, poseSensitivity).position
      : null

    setTracker((prev) =>
      updateSectorState(prev, {
        faceInFrame: detection.faceInFrame,
        clockPosition,
        quality: qualityAssessment.status,
      }),
    )

    // THIS is the capture: a frame that shows a face, passes the live
    // quality gate and resolves to a clock position IS a usable still for
    // that position, so keep it. No shutter button and no dependence on
    // whether the sector has been CONFIRMED yet -- the tracker's
    // FRAMES_TO_CONFIRM streak is a UI/debounce concern, while every frame
    // admitted here is independently valid. `shouldAdmit` is checked before
    // encoding so a frame that would lose its slot never costs a
    // `toBlob` on this loop.
    if (
      !detection.faceInFrame ||
      clockPosition === null ||
      qualityAssessment.status !== 'ok'
    ) {
      return
    }
    const buffer = burstRef.current[clockPosition]
    if (!shouldAdmit(buffer, qualityAssessment.blurVariance)) return

    const blob = await encodeCanvasJpeg(canvas)
    if (!blob) return
    const next = admitFrame(buffer, {
      blob,
      sharpness: qualityAssessment.blurVariance,
    })
    burstRef.current[clockPosition] = next
    setBurstCounts((prev) =>
      prev[clockPosition] === next.length
        ? prev
        : { ...prev, [clockPosition]: next.length },
    )
  }, [step, qualityThresholds, poseSensitivity, encodeCanvasJpeg])

  useEffect(() => {
    if (step !== 'preflight' && step !== 'countdown' && step !== 'sweep') return
    sampleTimerRef.current = window.setInterval(() => {
      void sampleFrame()
    }, SAMPLE_INTERVAL_MS)
    return () => {
      if (sampleTimerRef.current !== null) {
        window.clearInterval(sampleTimerRef.current)
        sampleTimerRef.current = null
      }
    }
  }, [step, sampleFrame])

  const capturePhoto = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    // Freeze the subject's straight-at-the-camera pose as this session's
    // neutral baseline, at the exact instant the frontal photo is taken —
    // every clock position from here on is measured RELATIVE to it. `null`
    // (no pose sampled yet) simply means no calibration, i.e. the previous
    // uncalibrated behaviour.
    neutralPoseRef.current = averagePose(recentNeutralPosesRef.current)
    canvas.toBlob(
      (blob) => {
        if (blob) setPhotoBlob(blob)
      },
      'image/jpeg',
      0.92,
    )
  }, [])

  /** Drop every buffered sweep frame and reset the tracker/counters that
   * mirror it. Used by both "start the sweep" and "redo the sweep" — the
   * blobs are simply dereferenced, nothing was ever written to disk or
   * uploaded at this point. */
  const resetSweep = useCallback(() => {
    burstRef.current = createEmptyBurstBuffer()
    const counts = {} as Record<ClockPosition, number>
    for (const position of CLOCK_POSITIONS) counts[position] = 0
    setBurstCounts(counts)
    setTracker(createInitialTrackerState())
    setElapsedS(0)
  }, [])

  // Deliberately leaves the elapsed timer running: "Ulangi posisi ini" on
  // the review step drops straight back into 'sweep', and stopping the
  // clock here would freeze the readout for the rest of the session. It is
  // cleared by `stopCamera` (upload, cancel, unmount) like every other
  // timer this page owns.
  const finishSweepCapture = useCallback(() => setStep('review'), [])

  /** Re-zero the clock against wherever the head is right now. The subject
   * must be looking straight at the camera when this runs. */
  const recalibrateNeutral = useCallback(() => {
    const measured = averagePose(recentNeutralPosesRef.current)
    if (measured !== null) neutralPoseRef.current = measured
  }, [])

  const startSweepCapture = useCallback(() => {
    if (!streamRef.current) return
    // Re-zero from the countdown window, which just spent 3 seconds telling
    // the subject to look at the camera. Falls back to the baseline frozen
    // at photo time when the countdown produced no usable pose.
    recalibrateNeutral()
    resetSweep()
    if (elapsedTimerRef.current !== null) {
      window.clearInterval(elapsedTimerRef.current)
    }

    // Purely drives the elapsed mm:ss readout. There is no maximum
    // duration and no minimum: with per-position capture, "how long the
    // subject has been sweeping" says nothing about coverage — the frame
    // count per position does, and that is what gates "Selesai".
    elapsedTimerRef.current = window.setInterval(() => {
      setElapsedS((prev) => prev + 1)
    }, 1000)

    setStep('sweep')
  }, [resetSweep, recalibrateNeutral])

  // Reset the countdown to COUNTDOWN_START_S exactly once, on the render
  // where `step` transitions TO 'countdown' (initial start or a retry) --
  // a render-time adjustment (React's own idiom for "reset state when a
  // value changes", see https://react.dev/learn/you-might-not-need-an-effect
  // #adjusting-some-state-when-a-prop-changes) rather than an effect,
  // matching this file's own `EnrollmentDetailPage.tsx`-style convention.
  const [prevStep, setPrevStep] = useState<WizardStep>(step)
  if (step !== prevStep) {
    setPrevStep(step)
    if (step === 'countdown') setCountdownValue(COUNTDOWN_START_S)
  }

  // Drives the 'countdown' step: ticks COUNTDOWN_START_S down to 0 once per
  // second, then hands off to `startSweepCapture` -- that callback's only
  // dependency is `resetSweep`, which itself has none, so its identity is
  // stable across renders and referencing it directly here is safe.
  useEffect(() => {
    if (step !== 'countdown') return
    // Start the neutral window empty so the baseline comes from the
    // countdown itself (where the subject is told to look at the camera)
    // rather than from stale preflight frames taken while they were looking
    // at the screen, which sits below the camera on a laptop and tilts the
    // baseline downward.
    recentNeutralPosesRef.current = []
    const id = window.setInterval(() => {
      setCountdownValue((prev) => {
        if (prev <= 1) {
          window.clearInterval(id)
          startSweepCapture()
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => window.clearInterval(id)
  }, [step, startSweepCapture])

  const retrySweepCapture = useCallback(() => {
    resetSweep()
    setStep('countdown')
  }, [resetSweep])

  /** Redo ONE clock position without touching the other eleven — the whole
   * point of capturing per position rather than as a single video. Drops
   * that position's frames and un-confirms its sector, so the sampling loop
   * starts collecting for it again the moment the subject looks there. */
  const retakePosition = useCallback((position: ClockPosition) => {
    burstRef.current[position] = []
    setBurstCounts((prev) => ({ ...prev, [position]: 0 }))
    setTracker((prev) => ({
      status: { ...prev.status, [position]: 'pending' },
      streaks: { ...prev.streaks, [position]: 0 },
    }))
  }, [])

  // Retaking the photo invalidates the neutral baseline it was measured
  // alongside — the next `capturePhoto` re-freezes a fresh one.
  const retakePhoto = useCallback(() => {
    neutralPoseRef.current = null
    recentNeutralPosesRef.current = []
    setPhotoBlob(null)
  }, [])

  // "Batal" on the frontal-photo and video-recording steps: discards
  // whatever has been captured so far (photo and/or video, neither is ever
  // uploaded until 'uploading', see startUpload below) and returns to the
  // Enrollment list -- the session itself is left exactly as-is server-side
  // (still CAPTURING), resumable later via EnrollmentDetailPage.tsx's
  // "Lanjutkan / Coba Lagi Capture", same as backing out of the browser
  // already allowed; this is just a discoverable, in-wizard way to do it
  // instead of a browser back button.
  const cancelCapture = useCallback(() => {
    if (
      !window.confirm(
        'Batalkan capture ini? Foto yang sudah diambil akan dihapus.',
      )
    ) {
      return
    }
    stopCamera()
    burstRef.current = createEmptyBurstBuffer()
    setPhotoBlob(null)
    navigate('/enrollments')
  }, [stopCamera, navigate])

  const photoPreviewUrl = useMemo(
    () => (photoBlob ? URL.createObjectURL(photoBlob) : null),
    [photoBlob],
  )
  useEffect(() => {
    return () => {
      if (photoPreviewUrl) URL.revokeObjectURL(photoPreviewUrl)
    }
  }, [photoPreviewUrl])

  const uploadOne = useCallback(
    async (
      kind: 'photo' | 'video',
      blob: Blob,
      contentType: string,
      clockPosition?: ClockPosition,
    ) => {
      const digest = await computeSha256(blob)
      const presigned = await presignMedia(
        enrollmentId ?? '',
        buildPresignRequestBody(kind, {
          contentType,
          size: blob.size,
          sha256Hex: digest.hex,
          clockPosition,
        }),
      )
      await uploadToS3(presigned.upload_url, blob, digest.base64, contentType)
    },
    [enrollmentId],
  )

  // Upload progress that must SURVIVE a failed attempt, so "Coba Lagi"
  // resumes instead of restarting. With 36-odd sweep frames a restart is
  // not merely slow: every re-uploaded frame mints another presigned key
  // and another PENDING row, leaving duplicate objects in S3 for QC to sift
  // through. `null` in `pendingFramesRef` means "no attempt started yet".
  const pendingFramesRef = useRef<ReturnType<typeof flattenBurstBuffer> | null>(
    null,
  )
  const photoUploadedRef = useRef(false)
  const [framesToUpload, setFramesToUpload] = useState(0)

  const startUpload = useCallback(async () => {
    if (!photoBlob || !enrollmentId) return
    if (pendingFramesRef.current === null) {
      const snapshot = flattenBurstBuffer(burstRef.current)
      if (snapshot.length === 0) return
      pendingFramesRef.current = snapshot
      setFramesToUpload(snapshot.length)
      setFramesUploaded(0)
    }
    const frames = pendingFramesRef.current

    setStep('uploading')
    setUploadError(null)
    stopCamera()

    const fail = (error: unknown) => {
      setUploadError(
        error instanceof Error ? error.message : 'Upload gagal, coba lagi.',
      )
      setUploadStatus((prev) => ({
        photo: prev.photo === 'done' ? 'done' : 'error',
        frames: prev.frames === 'done' ? 'done' : 'error',
      }))
    }

    // The frontal photo goes FIRST and alone. It is the neutral-pose
    // reference the server looks up as the earliest position-less photo
    // (ai-training `get_frontal_photo`), and uploading it before any sweep
    // frame keeps that ordering unambiguous.
    if (!photoUploadedRef.current) {
      setUploadStatus((prev) => ({ ...prev, photo: 'uploading' }))
      try {
        await uploadOne('photo', photoBlob, 'image/jpeg')
      } catch (error) {
        fail(error)
        return
      }
      photoUploadedRef.current = true
    }
    setUploadStatus((prev) => ({ ...prev, photo: 'done' }))

    setUploadStatus((prev) => ({ ...prev, frames: 'uploading' }))
    const { pending, error } = await runConcurrent(
      frames,
      UPLOAD_CONCURRENCY,
      ({ position, frame }) =>
        uploadOne('photo', frame.blob, 'image/jpeg', position),
      () => setFramesUploaded((done) => done + 1),
    )
    pendingFramesRef.current = pending
    if (error !== null) {
      fail(error)
      return
    }
    setUploadStatus((prev) => ({ ...prev, frames: 'done' }))

    try {
      await completeEnrollment(enrollmentId)
    } catch (completionError) {
      fail(completionError)
      return
    }
    setStep('done')
  }, [photoBlob, enrollmentId, uploadOne, stopCamera])

  if (!enrollmentId) {
    return <p role="alert">ID sesi enrollment tidak ditemukan pada URL.</p>
  }

  if (!isAuthenticated) {
    return (
      <section className="capture-page">
        <p role="alert">
          Anda perlu login untuk membuka capture enrollment.{' '}
          <Link to="/login">Masuk</Link>
        </p>
      </section>
    )
  }

  return (
    <section className="capture-page">
      <canvas ref={canvasRef} style={{ display: 'none' }} />
      <header className="capture-page__header">
        <p className="mono capture-page__eyebrow">Sesi {enrollmentId}</p>
        <h1>Enrollment — Capture 360°</h1>
      </header>

      {step === 'consent' && (
        <div className="capture-card">
          <EnrollmentConsentCopy />
          <label className="capture-checkbox">
            <input
              type="checkbox"
              checked={matchedConditionConfirmed}
              onChange={(event) => setMatchedConditionConfirmed(event.target.checked)}
            />
            Saya sudah melepas masker dan kacamata hitam (sunglasses)
          </label>
          <div className="capture-actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={!matchedConditionConfirmed}
              onClick={startCamera}
            >
              Saya Setuju &amp; Mulai
            </button>
          </div>
          {cameraError && <p role="alert" className="capture-error">{cameraError}</p>}
        </div>
      )}

      {(step === 'preflight' || step === 'countdown' || step === 'sweep') && (
        <div className="capture-stage">
          <div className="capture-viewport">
            <video ref={videoRef} className="capture-viewport__video" muted playsInline />
            {step === 'sweep' && (
              <div className="capture-ring-overlay">
                <ProgressRing status={tracker.status} targetPosition={targetPosition} />
              </div>
            )}
            <div
              className={
                faceInFrame && quality === 'ok'
                  ? 'capture-face-guide capture-face-guide--ok'
                  : 'capture-face-guide capture-face-guide--bad'
              }
              aria-hidden="true"
            />
            {step === 'sweep' && (
              <div className="capture-rec-indicator">
                <span className="capture-rec-dot" /> {totalFrames} foto{' '}
                <span className="mono">
                  {String(Math.floor(elapsedS / 60)).padStart(2, '0')}:
                  {String(elapsedS % 60).padStart(2, '0')}
                </span>
              </div>
            )}
            {step === 'countdown' && (
              <div className="capture-countdown-overlay" role="status">
                <span key={countdownValue} className="capture-countdown-number mono">
                  {countdownValue > 0 ? countdownValue : 'Mulai!'}
                </span>
                <span className="capture-countdown-text">
                  Lihat lurus ke <strong>kamera</strong> (bukan ke layar) — posisi
                  ini dipakai sebagai titik netral arah jam.
                </span>
              </div>
            )}
          </div>

          <aside className="capture-checklist">
            {!modelsReady && <p>Memuat model deteksi wajah…</p>}
            <ul>
              <li data-ok={faceInFrame}>{faceInFrame ? '✔' : '✕'} Wajah terdeteksi</li>
              <li data-ok={quality === 'ok'}>
                {quality === 'ok' ? '✔' : '✕'} Pencahayaan &amp; ketajaman baik
              </li>
              {step === 'sweep' && (
                <li data-ok={canFinishSweep}>
                  {sectorsDone}/{CAPTURE_POSITIONS.length} arah tercakup ({totalFrames} foto)
                </li>
              )}
            </ul>

            {step === 'sweep' && targetPosition !== null && (
              <p className="capture-target-hint">
                Selanjutnya:{' '}
                <strong>{CAPTURE_POSITION_LABEL[targetPosition]}</strong>
                {burstCounts[targetPosition] > 0 && (
                  <> — {burstCounts[targetPosition]}/{BURST_SIZE} foto</>
                )}
              </p>
            )}

            {/* Dev-only pose readout. Shows the calibrated estimator output
                and every intermediate the clock geometry derives from it, so
                "position X never lights up" can be diagnosed on the spot:
                whether the face is even detected, whether the radius reaches
                the gate, and which sector the angle lands in. Stripped from
                production builds by the `import.meta.env.DEV` guard. */}
            {import.meta.env.DEV && (
              <div className="capture-pose-debug" data-testid="pose-debug">
                <strong>Pose (dev)</strong>
                {poseDebug === null ? (
                  <p className="mono">wajah / landmark tidak terdeteksi</p>
                ) : (
                  <dl className="mono">
                    {/* raw and netral are shown because the clock is measured
                        RELATIVE to netral. A frontal face reads about +6.6
                        pitch structurally, so if netral did not capture that,
                        every position is skewed toward the top of the dial. */}
                    <div>
                      <dt>raw</dt>
                      <dd>
                        {poseDebug.raw.yaw.toFixed(1)}° / {poseDebug.raw.pitch.toFixed(1)}°
                      </dd>
                    </div>
                    <div>
                      <dt>netral</dt>
                      <dd data-ok={poseDebug.neutral !== null}>
                        {poseDebug.neutral === null
                          ? 'BELUM DIUKUR'
                          : `${poseDebug.neutral.yaw.toFixed(1)}° / ${poseDebug.neutral.pitch.toFixed(1)}°`}
                      </dd>
                    </div>
                    <div>
                      <dt>yaw</dt>
                      <dd>{poseDebug.yawDeg.toFixed(1)}°</dd>
                    </div>
                    <div>
                      <dt>pitch</dt>
                      <dd>{poseDebug.pitchDeg.toFixed(1)}°</dd>
                    </div>
                    <div>
                      <dt>norm</dt>
                      <dd>
                        {poseDebug.normYaw.toFixed(2)} / {poseDebug.normPitch.toFixed(2)}
                      </dd>
                    </div>
                    <div>
                      <dt>radius</dt>
                      <dd data-ok={poseDebug.radius >= poseSensitivity.minPoseRadius}>
                        {poseDebug.radius.toFixed(2)} / {poseSensitivity.minPoseRadius}
                      </dd>
                    </div>
                    <div>
                      <dt>sudut</dt>
                      <dd>
                        {poseDebug.angleDeg === null
                          ? '—'
                          : `${poseDebug.angleDeg.toFixed(0)}°`}
                      </dd>
                    </div>
                    <div>
                      <dt>jam</dt>
                      <dd data-ok={poseDebug.position !== null}>
                        {poseDebug.position ?? 'belum'}
                      </dd>
                    </div>
                    <div>
                      <dt>gain</dt>
                      <dd>
                        y {poseSensitivity.yawGain} / p {poseSensitivity.pitchGain}
                      </dd>
                    </div>
                  </dl>
                )}
              </div>
            )}

            {step === 'preflight' && !photoBlob && (
              <div className="capture-actions">
                <button type="button" className="btn" onClick={cancelCapture}>
                  Batal
                </button>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={!faceInFrame || quality !== 'ok' || !modelsReady}
                  onClick={capturePhoto}
                >
                  Ambil Foto Frontal
                </button>
              </div>
            )}

            {step === 'preflight' && photoBlob && (
              <div>
                {photoPreviewUrl && (
                  <img src={photoPreviewUrl} alt="Pratinjau foto frontal" className="capture-thumb" />
                )}
                <div className="capture-actions">
                  <button type="button" className="btn" onClick={cancelCapture}>
                    Batal
                  </button>
                  <button type="button" className="btn" onClick={retakePhoto}>
                    Ulangi Foto
                  </button>
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={() => setStep('countdown')}
                  >
                    Lanjut ke Capture 360°
                  </button>
                </div>
              </div>
            )}

            {step === 'sweep' && (
              <div className="capture-actions">
                <button type="button" className="btn" onClick={cancelCapture}>
                  Batal
                </button>
                {/* Re-zero without restarting. The clock is measured
                    RELATIVE to a neutral reading, and that reading is only
                    as good as where the head happened to be when it was
                    taken — if the whole dial feels rotated (aiming at jam 4
                    lights up jam 2), looking at the camera and pressing this
                    fixes it in place. */}
                <button type="button" className="btn" onClick={recalibrateNeutral}>
                  Set Titik Netral
                </button>
                <button type="button" className="btn" onClick={retrySweepCapture}>
                  Ulangi Semua
                </button>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={!canFinishSweep}
                  onClick={finishSweepCapture}
                >
                  Selesai
                </button>
              </div>
            )}
          </aside>
        </div>
      )}

      {step === 'review' && (
        <div className="capture-card">
          <h2>Review</h2>
          <div className="capture-review-grid">
            {photoPreviewUrl && <img src={photoPreviewUrl} alt="Foto frontal" className="capture-thumb" />}
          </div>
          <p>
            {sectorsDone}/{CAPTURE_POSITIONS.length} arah tercakup, total {totalFrames} foto. QC
            akhir dilakukan di server.
          </p>
          <ul className="capture-position-list">
            {CAPTURE_POSITIONS.map((position) => (
              <li key={position} data-ok={burstCounts[position] > 0}>
                {CAPTURE_POSITION_LABEL[position]}: {burstCounts[position]}/{BURST_SIZE} foto{' '}
                <button
                  type="button"
                  className="btn btn--small"
                  onClick={() => {
                    retakePosition(position)
                    setStep('sweep')
                  }}
                >
                  Ulangi posisi ini
                </button>
              </li>
            ))}
          </ul>
          <div className="capture-actions">
            <button type="button" className="btn" onClick={retrySweepCapture}>
              Ulangi Semua Posisi
            </button>
            <button type="button" className="btn btn--primary" onClick={() => void startUpload()}>
              Unggah &amp; Selesaikan
            </button>
          </div>
        </div>
      )}

      {step === 'uploading' && (
        <div className="capture-card">
          <h2>Mengunggah…</h2>
          <ul>
            <li>Foto frontal: {uploadStatus.photo}</li>
            <li>
              Foto posisi jam: {uploadStatus.frames} ({framesUploaded}/
              {framesToUpload})
            </li>
          </ul>
          {uploadError && (
            <>
              <p role="alert" className="capture-error">{uploadError}</p>
              <p>
                Mencoba lagi hanya mengunggah foto yang belum berhasil terkirim.
              </p>
              <button type="button" className="btn btn--primary" onClick={() => void startUpload()}>
                Coba Lagi
              </button>
            </>
          )}
        </div>
      )}

      {step === 'done' && (
        <div className="capture-card">
          <h2>Berhasil diunggah</h2>
          <p>Sesi telah masuk antrean pemeriksaan kualitas (QC_RUNNING).</p>
          <Link to="/enrollments" className="btn btn--primary">
            Kembali ke Daftar Enrollment
          </Link>
        </div>
      )}
    </section>
  )
}
