import type { ClockPosition } from './types'
import { CLOCK_POSITIONS } from './types'

/**
 * Per-clock-position frame buffer for the photo sweep (FR-ENR-02).
 *
 * Replaces the single `rotation.webm`: instead of recording the whole
 * sweep and letting the server decompose it, the wizard keeps a short
 * BURST of stills per clock position and uploads those.
 *
 * WHY a burst and not one still per position: `extract_gallery_embeddings`
 * (ai-training) averages k=3 frames per pose bucket. A single still would
 * collapse that averaging to one sample, losing both the sharpness
 * selection and the noise averaging that make the gallery template stable —
 * a quality regression versus the video path, not a wash. BURST_SIZE is
 * matched to that k.
 *
 * WHY sharpest-wins rather than first-N: a subject arriving at a position
 * is still decelerating, so the first frames that resolve to it are the
 * most motion-blurred ones. Every frame offered here has already passed the
 * live quality gate, so this is choosing among acceptable frames, not
 * rescuing bad ones.
 */

/** Frames kept per clock position. Matches `extract_gallery_embeddings`'
 * k=3 pose-bucket averaging (see module docstring); also bounds the upload
 * at 12 x 3 = 36 objects plus the frontal photo. */
export const BURST_SIZE = 3

export interface BurstFrame {
  blob: Blob
  /** Variance-of-Laplacian of the frame this blob was encoded from; higher
   * = sharper. Same metric the live gate uses (`imageQuality.ts`), so no
   * extra computation is needed to rank frames. */
  sharpness: number
}

export type BurstBuffer = Record<ClockPosition, BurstFrame[]>

export function createEmptyBurstBuffer(): BurstBuffer {
  const buffer = {} as BurstBuffer
  for (const position of CLOCK_POSITIONS) buffer[position] = []
  return buffer
}

/**
 * Whether a frame of this sharpness would earn a slot — checked BEFORE
 * encoding, so a frame that would just be discarded never costs a
 * `canvas.toBlob` on the sampling loop's critical path.
 */
export function shouldAdmit(
  buffer: BurstFrame[],
  sharpness: number,
  size: number = BURST_SIZE,
): boolean {
  if (buffer.length < size) return true
  return buffer.some((frame) => sharpness > frame.sharpness)
}

/**
 * Fold a frame into one position's buffer, keeping the `size` sharpest.
 * Returns the ORIGINAL array reference when the frame doesn't make the cut,
 * so callers can cheaply tell whether anything changed.
 */
export function admitFrame(
  buffer: BurstFrame[],
  frame: BurstFrame,
  size: number = BURST_SIZE,
): BurstFrame[] {
  if (buffer.length < size) return [...buffer, frame]

  let worstIndex = 0
  for (let i = 1; i < buffer.length; i += 1) {
    if (buffer[i].sharpness < buffer[worstIndex].sharpness) worstIndex = i
  }
  if (frame.sharpness <= buffer[worstIndex].sharpness) return buffer

  const next = [...buffer]
  next[worstIndex] = frame
  return next
}

/** Positions that have at least one frame buffered, in clockwise sweep
 * order starting at 12 — the order they are uploaded in, so a partially
 * failed upload leaves a contiguous prefix of the sweep rather than holes
 * scattered around the dial. */
export function capturedPositions(buffer: BurstBuffer): ClockPosition[] {
  const order: ClockPosition[] = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
  return order.filter((position) => buffer[position].length > 0)
}

/** Every buffered frame paired with its position, in upload order. */
export function flattenBurstBuffer(
  buffer: BurstBuffer,
): Array<{ position: ClockPosition; frame: BurstFrame }> {
  return capturedPositions(buffer).flatMap((position) =>
    buffer[position].map((frame) => ({ position, frame })),
  )
}
