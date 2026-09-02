import type { HeadPose, Landmarks68 } from './types'
import { POSE_RANGE } from './clockSectors'

/**
 * Lightweight geometric yaw/pitch estimation from 68-point face landmarks
 * (iBUG/300-W ordering, as returned by @vladmandic/face-api's
 * faceLandmark68Net/faceLandmark68TinyNet). This intentionally avoids a
 * full solvePnP/3D pose-estimation model per FE-04 scope ("simple
 * geometric algorithm from landmarks is enough") — it only needs to be
 * accurate enough to bucket a pose into one of 12 clock sectors.
 *
 * Landmark indices used:
 *  - 0, 16: left/right jaw edge (face width reference)
 *  - 27: nose bridge top, 30: nose tip
 *  - 8: chin
 *  - 36-41: left eye, 42-47: right eye
 */
function mean(points: Landmarks68): { x: number; y: number } {
  const sum = points.reduce(
    (acc, p) => ({ x: acc.x + p.x, y: acc.y + p.y }),
    { x: 0, y: 0 },
  )
  return { x: sum.x / points.length, y: sum.y / points.length }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/** How far a measured neutral baseline may shift the clock: ONE full axis
 * range, which is the largest shift the geometry can express, so a
 * mis-measured baseline (subject tilted while the frontal photo was taken)
 * saturates instead of running away.
 *
 * Deliberately not a tighter cap: ai-training's solvePnP estimator has a
 * genuine neutral bias of ~97% of its pitch range, and an over-tight cap
 * there removed only part of the bias while looking like a working fix
 * (see `ai-training/tests/test_neutral_pose_offset.py`). Keeping both sides
 * on the same rule avoids re-learning that the hard way here. */
const MAX_NEUTRAL_YAW_DEG = POSE_RANGE.maxYawDeg
const MAX_NEUTRAL_PITCH_DEG = POSE_RANGE.maxPitchDeg

/**
 * Mean of several pose samples, or `null` for an empty list.
 *
 * Averaging a handful of consecutive preflight frames (rather than trusting
 * one) keeps a single blink/wobble from poisoning the neutral baseline.
 */
export function averagePose(poses: HeadPose[]): HeadPose | null {
  if (poses.length === 0) return null
  const sum = poses.reduce(
    (acc, pose) => ({ yaw: acc.yaw + pose.yaw, pitch: acc.pitch + pose.pitch }),
    { yaw: 0, pitch: 0 },
  )
  return { yaw: sum.yaw / poses.length, pitch: sum.pitch / poses.length }
}

/**
 * Re-express a pose RELATIVE to the subject's own neutral (straight-at-the-
 * camera) reading — the fix for "jam 4-8 tidak terdeteksi".
 *
 * `clockSectors.ts`'s geometry assumes a neutral face measures `(0, 0)`, but
 * this estimator does not deliver that: the nose tip of a real, frontal face
 * sits roughly a third of the way ABOVE the eye-line/chin midpoint, so
 * `estimateHeadPose` reports a POSITIVE (upward) pitch — around a third of
 * `maxPitchDeg` — for someone sitting perfectly still. ai-training's
 * independent solvePnP estimator has the same bias, only larger (a real
 * frontal portrait measured +24.3 of a +-25 range, recorded in
 * `ai_training/quality/pose.py`'s own comments).
 *
 * Two things follow from an uncorrected bias, and both bite the BOTTOM half
 * of the clock specifically:
 *  - the radius gate becomes lopsided (reaching 12 o'clock needs a fraction
 *    of the head movement that reaching 6 o'clock does), and
 *  - the measured ANGLE is rotated upward, so a subject genuinely aiming at
 *    5 o'clock gets classified into 4 or 3 — the sector lights up, just the
 *    wrong one.
 *
 * Subtracting a per-subject, per-session baseline (captured at the moment
 * the frontal photo is taken, see `EnrollmentCapturePage`) removes both,
 * without hand-tuning per-sector thresholds and without assuming anything
 * about a particular face, camera height, or estimator.
 */
export function calibrateToNeutral(pose: HeadPose, neutral: HeadPose | null): HeadPose {
  if (neutral === null) return pose
  return {
    yaw: pose.yaw - clamp(neutral.yaw, -MAX_NEUTRAL_YAW_DEG, MAX_NEUTRAL_YAW_DEG),
    pitch: pose.pitch - clamp(neutral.pitch, -MAX_NEUTRAL_PITCH_DEG, MAX_NEUTRAL_PITCH_DEG),
  }
}

export function estimateHeadPose(landmarks: Landmarks68): HeadPose | null {
  if (landmarks.length < 68) return null

  const leftEdge = landmarks[0]
  const rightEdge = landmarks[16]
  const nose = landmarks[30]
  const chin = landmarks[8]
  const leftEye = mean(landmarks.slice(36, 42))
  const rightEye = mean(landmarks.slice(42, 48))
  const eyeLineY = (leftEye.y + rightEye.y) / 2

  const faceWidth = rightEdge.x - leftEdge.x
  const faceHeight = chin.y - eyeLineY
  if (faceWidth <= 0 || faceHeight <= 0) return null

  // Yaw: how far the nose sits off the horizontal midline of the two jaw
  // edges, as a fraction of half the face width. Negated (nose offset
  // subtracted from midX, not the other way around) because `landmarks`
  // come from the RAW, un-mirrored camera frame (`faceDetector.ts` runs
  // detection on the canvas drawn straight from `<video>`), while the
  // wizard's `<video>` preview -- and the clock-position ring overlaid on
  // top of it -- is displayed mirrored (`scaleX(-1)` in
  // EnrollmentCapturePage.css) so the subject sees a natural "look in a
  // mirror" self-view. Without the negation, a subject turning their head
  // toward what they SEE as the ring's 1 o'clock (upper-right on their
  // mirrored screen) produces raw-frame yaw whose sign matches the
  // OPPOSITE side of the clock (found live: turning toward the on-screen 1
  // o'clock position lit up 11 o'clock instead, and vice versa for every
  // other left/right pair).
  const midX = (leftEdge.x + rightEdge.x) / 2
  const yawFraction = (midX - nose.x) / (faceWidth / 2)
  const yaw = clamp(yawFraction, -1, 1) * POSE_RANGE.maxYawDeg

  // Pitch: how far the nose sits off the vertical midline between the eye
  // line and the chin. Nose closer to the eyes (smaller offset, negative
  // direction in image coords) means the head is tilted up.
  const midY = (eyeLineY + chin.y) / 2
  const pitchFraction = -(nose.y - midY) / (faceHeight / 2)
  const pitch = clamp(pitchFraction, -1, 1) * POSE_RANGE.maxPitchDeg

  return { yaw, pitch }
}
