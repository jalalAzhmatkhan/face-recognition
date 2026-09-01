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
