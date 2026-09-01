import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
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
  isCaptureComplete,
  resolveClockPosition,
  updateSectorState,
} from './clockSectors'
import type { SectorTrackerState } from './clockSectors'
import { detectFace, loadFaceDetectionModels } from './faceDetector'
import { estimateHeadPose } from './headPose'
import { assessQuality, QUALITY_THRESHOLDS } from './imageQuality'
import { CURRENT_CONSENT_VERSION } from './types'
import type { QualityStatus } from './types'
import './EnrollmentCapturePage.css'

type WizardStep =
  | 'consent'
  | 'preflight'
  | 'video'
  | 'review'
  | 'uploading'
  | 'done'

const MIN_DURATION_S = 10
const MAX_DURATION_S = 30
const SAMPLE_INTERVAL_MS = 150

/**
 * S-30 Enrollment capture wizard (FR-ENR-02/03/04).
 *
 * Motion model per FSD-AI.md ASM-03 (CORRECTED 2026-08-30): the subject's
 * body stays facing the camera the whole time; only head yaw/pitch sweeps
 * through the 12 clock positions. Every position must show a detected
 * face — there is no back-of-head / auto-pass sector.
 *
 * Media never touches local storage: the photo and the recorded webm live
 * only as in-memory Blobs in React state until they are uploaded straight
 * to S3 via BE-06's presigned URLs, after which they are dropped.
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
 * "Saya Setuju & Mulai", sends `CURRENT_CONSENT_VERSION` ("v1.1") to
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
  const [videoBlob, setVideoBlob] = useState<Blob | null>(null)
  const [uploadStatus, setUploadStatus] = useState<{
    photo: 'idle' | 'uploading' | 'done' | 'error'
    video: 'idle' | 'uploading' | 'done' | 'error'
  }>({ photo: 'idle', video: 'idle' })
  const [uploadError, setUploadError] = useState<string | null>(null)
  // System Parameter menu override (pages/SystemParametersPage.tsx) --
  // starts at the built-in defaults and is replaced once (if) the fetch
  // below succeeds, so this wizard is fully usable even before the first
  // frame samples if the settings service is briefly unavailable.
  const [qualityThresholds, setQualityThresholds] = useState(QUALITY_THRESHOLDS)

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const recordedChunksRef = useRef<Blob[]>([])
  const sampleTimerRef = useRef<number | null>(null)
  const elapsedTimerRef = useRef<number | null>(null)
  const sectorsDone = countDone(tracker.status)
  const canFinishVideo = isCaptureComplete(tracker.status)

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
      .then((params) =>
        setQualityThresholds({
          minBlurVariance: params.min_blur_variance,
          minBrightness: params.min_brightness,
          maxBrightness: params.max_brightness,
        }),
      )
      .catch(() => {
        // Keep QUALITY_THRESHOLDS -- see effect docstring above.
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
    if ((step === 'preflight' || step === 'video') && video && stream && video.srcObject !== stream) {
      video.srcObject = stream
      void video.play()
    }
  }, [step])

  // Continuous face/quality sampling while camera is live (preflight + video steps).
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

    if (step !== 'video') return

    const pose = detection.landmarks
      ? estimateHeadPose(detection.landmarks)
      : null
    const clockPosition = pose ? resolveClockPosition(pose) : null

    setTracker((prev) =>
      updateSectorState(prev, {
        faceInFrame: detection.faceInFrame,
        clockPosition,
        quality: qualityAssessment.status,
      }),
    )
  }, [step, qualityThresholds])

  useEffect(() => {
    if (step !== 'preflight' && step !== 'video') return
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
    canvas.toBlob(
      (blob) => {
        if (blob) setPhotoBlob(blob)
      },
      'image/jpeg',
      0.92,
    )
  }, [])

  const finishVideoCaptureRef = useRef<() => void>(() => {})

  const finishVideoCapture = useCallback(() => {
    if (elapsedTimerRef.current !== null) {
      window.clearInterval(elapsedTimerRef.current)
      elapsedTimerRef.current = null
    }
    const recorder = recorderRef.current
    if (!recorder || recorder.state === 'inactive') return
    recorder.onstop = () => {
      const blob = new Blob(recordedChunksRef.current, { type: 'video/webm' })
      recordedChunksRef.current = []
      setVideoBlob(blob)
      setStep('review')
    }
    recorder.stop()
  }, [])
  useEffect(() => {
    finishVideoCaptureRef.current = finishVideoCapture
  }, [finishVideoCapture])

  const startVideoCapture = useCallback(() => {
    const stream = streamRef.current
    if (!stream) return
    recordedChunksRef.current = []
    setTracker(createInitialTrackerState())
    setElapsedS(0)

    const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' })
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) recordedChunksRef.current.push(event.data)
    }
    recorder.start(1000)
    recorderRef.current = recorder

    elapsedTimerRef.current = window.setInterval(() => {
      setElapsedS((prev) => {
        const next = prev + 1
        if (next >= MAX_DURATION_S) finishVideoCaptureRef.current()
        return next
      })
    }, 1000)

    setStep('video')
  }, [])

  const retryVideoCapture = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state !== 'inactive') {
      recorderRef.current.onstop = null
      recorderRef.current.stop()
    }
    recordedChunksRef.current = []
    setVideoBlob(null)
    setTracker(createInitialTrackerState())
    setElapsedS(0)
    startVideoCapture()
  }, [startVideoCapture])

  const retakePhoto = useCallback(() => setPhotoBlob(null), [])

  const videoPreviewUrl = useMemo(
    () => (videoBlob ? URL.createObjectURL(videoBlob) : null),
    [videoBlob],
  )
  useEffect(() => {
    return () => {
      if (videoPreviewUrl) URL.revokeObjectURL(videoPreviewUrl)
    }
  }, [videoPreviewUrl])

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
    async (kind: 'photo' | 'video', blob: Blob, contentType: string) => {
      const digest = await computeSha256(blob)
      const presigned = await presignMedia(
        enrollmentId ?? '',
        buildPresignRequestBody(kind, {
          contentType,
          size: blob.size,
          sha256Hex: digest.hex,
        }),
      )
      await uploadToS3(presigned.upload_url, blob, digest.base64, contentType)
    },
    [enrollmentId],
  )

  const startUpload = useCallback(async () => {
    if (!photoBlob || !videoBlob || !enrollmentId) return
    setStep('uploading')
    setUploadError(null)
    stopCamera()

    try {
      setUploadStatus((prev) => ({ ...prev, photo: 'uploading' }))
      await uploadOne('photo', photoBlob, 'image/jpeg')
      setUploadStatus((prev) => ({ ...prev, photo: 'done' }))

      setUploadStatus((prev) => ({ ...prev, video: 'uploading' }))
      await uploadOne('video', videoBlob, 'video/webm')
      setUploadStatus((prev) => ({ ...prev, video: 'done' }))

      await completeEnrollment(enrollmentId)
      setStep('done')
    } catch (error) {
      setUploadError(
        error instanceof Error ? error.message : 'Upload gagal, coba lagi.',
      )
      setUploadStatus((prev) => ({
        photo: prev.photo === 'done' ? 'done' : 'error',
        video: prev.video === 'done' ? 'done' : 'error',
      }))
    }
  }, [photoBlob, videoBlob, enrollmentId, uploadOne, stopCamera])

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

      {(step === 'preflight' || step === 'video') && (
        <div className="capture-stage">
          <div className="capture-viewport">
            <video ref={videoRef} className="capture-viewport__video" muted playsInline />
            {step === 'video' && (
              <div className="capture-ring-overlay">
                <ProgressRing status={tracker.status} />
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
            {step === 'video' && (
              <div className="capture-rec-indicator">
                <span className="capture-rec-dot" /> REC{' '}
                <span className="mono">
                  {String(Math.floor(elapsedS / 60)).padStart(2, '0')}:
                  {String(elapsedS % 60).padStart(2, '0')}
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
              {step === 'video' && (
                <li data-ok={canFinishVideo}>
                  {sectorsDone}/12 posisi jam tercakup
                </li>
              )}
            </ul>

            {step === 'preflight' && !photoBlob && (
              <button
                type="button"
                className="btn btn--primary"
                disabled={!faceInFrame || quality !== 'ok' || !modelsReady}
                onClick={capturePhoto}
              >
                Ambil Foto Frontal
              </button>
            )}

            {step === 'preflight' && photoBlob && (
              <div>
                {photoPreviewUrl && (
                  <img src={photoPreviewUrl} alt="Pratinjau foto frontal" className="capture-thumb" />
                )}
                <div className="capture-actions">
                  <button type="button" className="btn" onClick={retakePhoto}>
                    Ulangi Foto
                  </button>
                  <button type="button" className="btn btn--primary" onClick={startVideoCapture}>
                    Lanjut ke Video 360°
                  </button>
                </div>
              </div>
            )}

            {step === 'video' && (
              <div className="capture-actions">
                <button type="button" className="btn" onClick={retryVideoCapture}>
                  Ulangi Rekam
                </button>
                <button
                  type="button"
                  className="btn btn--primary"
                  disabled={!canFinishVideo || elapsedS < MIN_DURATION_S}
                  onClick={finishVideoCapture}
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
            {videoPreviewUrl && (
              <video src={videoPreviewUrl} controls className="capture-thumb" />
            )}
          </div>
          <p>{sectorsDone}/12 posisi jam tercakup. QC akhir dilakukan di server.</p>
          <div className="capture-actions">
            <button type="button" className="btn" onClick={retryVideoCapture}>
              Rekam Ulang Video
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
            <li>Foto: {uploadStatus.photo}</li>
            <li>Video: {uploadStatus.video}</li>
          </ul>
          {uploadError && (
            <>
              <p role="alert" className="capture-error">{uploadError}</p>
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
