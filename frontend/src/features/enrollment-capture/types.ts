/**
 * Shared types for the enrollment capture wizard (FE-04).
 *
 * Motion model per FSD-AI.md ASM-03 (CORRECTED 2026-08-30): only head
 * orientation (yaw + pitch) sweeps through the 12 clock positions. The
 * body/camera never move and the face is visible to the camera at every
 * position — there is NO back-of-head / auto-pass segment.
 */

/** Clock-face position, 1..12 (12 = head tilted up, straight ahead). */
export type ClockPosition = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12

export const CLOCK_POSITIONS: ClockPosition[] = [
  1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,
]

/** Per-sector visual/logical state. No "auto-pass" state exists by design. */
export type SectorStatus = 'pending' | 'active' | 'done' | 'poor'

export type SectorState = Record<ClockPosition, SectorStatus>

export interface HeadPose {
  /** Degrees. Negative = subject's head turned to camera-left. */
  yaw: number
  /** Degrees. Positive = head tilted up. */
  pitch: number
}

export interface Point2D {
  x: number
  y: number
}

/** A minimal 68-point landmark set (iBUG/300-W ordering), as produced by
 * face-api.js / @vladmandic/face-api's faceLandmark68(Tiny)Net. */
export type Landmarks68 = Point2D[]

export interface QualityMetrics {
  /** Variance of the Laplacian of the grayscale frame; lower = blurrier. */
  blurVariance: number
  /** Mean grayscale intensity, 0-255. */
  brightness: number
}

export type QualityStatus = 'ok' | 'poor'

export interface QualityAssessment extends QualityMetrics {
  status: QualityStatus
  isBlurry: boolean
  isTooDark: boolean
  isTooBright: boolean
}

/** One sampled video frame, already reduced to the facts the sector
 * tracker cares about. Produced by the detection loop; consumed by the
 * pure `updateSectorState` reducer so that reducer stays unit-testable
 * without a camera. */
export interface FrameSample {
  faceInFrame: boolean
  clockPosition: ClockPosition | null
  quality: QualityStatus
}

export type MediaKind = 'photo' | 'video'

export interface PresignRequestBody {
  kind: MediaKind
  content_type: string
  size: number
  sha256: string
}

export interface PresignResponse {
  upload_url: string
  s3_key: string
  expires_at: string
}

export interface CompleteResponse {
  id: string
  state: string
}
