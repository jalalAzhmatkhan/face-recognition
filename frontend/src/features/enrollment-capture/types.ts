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

/**
 * The positions enrollment actually captures: the four cardinals.
 *
 * Reduced from all 12 on 2026-09-02, after repeated live testing. The
 * browser's landmark-ratio estimator resolves the DOMINANT axis and its sign
 * reliably, but the yaw-to-pitch RATIO — which is the only thing separating
 * one diagonal from its neighbours — is not conditioned well enough to place
 * a pose inside a 30-degree sector. Aiming at jam 4/5 kept landing on jam
 * 1/2. Four targets 90 degrees apart need only the dominant axis and its
 * sign, which is exactly the part the estimator gets right.
 *
 * `ClockPosition` deliberately still spans 1..12: the stored vocabulary
 * (`media_objects.clock_position`, ai-training's pose buckets, every already
 * enrolled session) is unchanged, so legacy 12-position data stays valid and
 * widening the capture set again later needs no migration.
 *
 * Trade-off accepted with the user: the gallery gets 4 pose buckets per
 * subject instead of 12, so multi-view coverage — and with it some Recall
 * headroom on extreme poses — is narrower than the original design. Four
 * well-separated views is still genuine multi-view coverage, and a capture
 * users can complete beats one they cannot.
 */
export const CAPTURE_POSITIONS: ClockPosition[] = [12, 3, 6, 9]

/** Instruction shown for each captured position. */
export const CAPTURE_POSITION_LABEL: Record<number, string> = {
  12: 'agak mendongak (ke atas)',
  3: 'agak menoleh ke kanan',
  6: 'agak menunduk (ke bawah)',
  9: 'agak menoleh ke kiri',
}

/** Per-sector visual/logical state. No "auto-pass" state exists by design. */
export type SectorStatus = 'pending' | 'active' | 'done' | 'poor'

export type SectorState = Record<ClockPosition, SectorStatus>

export interface HeadPose {
  /** Degrees. Negative = subject's head turned to their own left (the
   * left side of the MIRRORED on-screen preview the subject actually
   * watches — see `headPose.ts::estimateHeadPose`'s yaw comment). */
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
  /** Which of the 12 sweep positions this photo captures (backend migration
   * `e4b9d2f6a8c3`). Omitted for the frontal preflight photo — that one is
   * the neutral-pose reference, and the backend finds it by looking for the
   * earliest photo with NO position. Rejected by the backend on
   * `kind: 'video'`. */
  clock_position?: ClockPosition
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

export interface ConsentRequestBody {
  consent_version: string
}

export interface ConsentResponse {
  id: string
  state: string
}

/**
 * Single source of truth (FE side) for the consent clause version this
 * wizard sends in `POST /enrollments/{id}/consent`.
 *
 * EC-FE-05 (task-breakdown.md "EC-4. Keputusan Susulan"): bumped from the
 * prior `"v1.0"` to add the three clauses now shown on the consent step
 * (synthetic masked template, door-camera event-frame calibration/probe
 * use, adaptive probe-buffer refresh) per ASM-EC-05
 * (`documentation/tsd/TSD-edge-cases.md`).
 *
 * Bumped again to `"v1.2"` (2026-09-02): enrollment no longer records a
 * video of the head sweep, it takes a burst of still photos at each of the
 * 12 clock positions (FR-ENR-02). The v1.1 text promised "foto wajah dan
 * video orientasi kepala", which is no longer what happens — see
 * `components/EnrollmentConsentCopy.tsx` for the updated wording.
 *
 * MUST match the backend constant `CURRENT_CONSENT_VERSION` in
 * `backend/app/models/consent.py` (EC-BE-09) — duplicated here rather than
 * imported, since there is no shared frontend/backend constants module in
 * this codebase yet.
 */
export const CURRENT_CONSENT_VERSION = 'v1.2'
