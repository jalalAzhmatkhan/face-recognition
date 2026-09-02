import type {
  ClockPosition,
  FrameSample,
  HeadPose,
  SectorState,
} from './types'
import { CAPTURE_POSITIONS, CLOCK_POSITIONS } from './types'

/**
 * Clock-position <-> head-pose mapping and the sector-coverage reducer.
 *
 * Per FSD-AI.md ASM-03 (CORRECTED 2026-08-30) the "rotation" is a sweep of
 * head yaw/pitch, not a body/camera turn: 12 o'clock = head tilted up,
 * moving clockwise mixes yaw (left/right) and pitch (up/down), the face is
 * always visible. This module treats each clock position as one point on a
 * circle in (yaw, pitch) space and maps a detected pose to the nearest
 * CAPTURED position — there is no "back of head" case, and no auto-pass: a
 * sector only advances when a pose sample actually lands near it.
 *
 * Capture targets the four cardinals (see `types.ts::CAPTURE_POSITIONS`), so
 * each one owns a 90-degree quadrant. The full 1..12 vocabulary is kept for
 * the stored data model and for already-enrolled sessions.
 */

/** Practical head-pose range for the sweep (degrees). Narrower than a full
 * head turn, per the ASM-03 correction. Note these cancel out of the clock
 * geometry itself — `describePose` divides by them and the gains below
 * multiply back — so they set the reported DEGREES, not the sensitivity. */
export const POSE_RANGE = {
  maxYawDeg: 25,
  maxPitchDeg: 20,
} as const

/** How many consecutive qualifying frames are required before a sector is
 * confirmed "done" (debounces flicker / a single lucky frame). */
export const FRAMES_TO_CONFIRM = 5

/**
 * Per-axis correction for `headPose.ts`'s estimator, ADMIN-tunable via the
 * System Parameter menu (`enrollment_capture_quality`).
 *
 * Why gains are needed at all: `estimateHeadPose` measures how far the nose
 * sits off the face's midlines, so its output is roughly
 * `protrusion x tan(angle)` — and the nose only protrudes about a third of
 * the eye-to-chin half-height. Reaching this module's radius gate on pitch
 * alone therefore took ~59 degrees of neck extension, which is past what
 * most people can manage and past where the landmark model stays reliable.
 * Sideways the head turns far enough that the same insensitivity was
 * survivable, so in practice ONLY the yaw-dominant positions (2,3,4,8,9,10)
 * ever confirmed — reported live, and the reason these gains exist.
 *
 * `pitchGain > yawGain` because a head pitches through a much smaller
 * comfortable range than it turns. With these defaults and the 0.40 radius
 * gate, 12/6 need roughly 19 degrees of pitch and 3/9 roughly 31 degrees of
 * yaw — "agak mendongak"/"agak menoleh", as opposed to the 59 and 64 degrees
 * the ungained version demanded.
 *
 * These are estimator-specific, NOT physical: ai-training's `cv2.solvePnP`
 * reports true degrees and applies no gain (see `resolve_qc_settings`).
 */
export interface PoseSensitivity {
  yawGain: number
  pitchGain: number
  /** Minimum distance from neutral (0..1, AFTER the gains) before a sample
   * counts as being at a clock position rather than still near centre. */
  minPoseRadius: number
}

export const DEFAULT_POSE_SENSITIVITY: PoseSensitivity = {
  yawGain: 2.5,
  pitchGain: 3.5,
  // Lowered from 0.55 when the capture set dropped to four cardinals. The
  // old value existed to keep neighbouring 30-degree sectors apart; with a
  // whole quadrant per target that separation is free, and 0.55 was asking
  // for ~39 degrees of yaw to register "agak menoleh". At 0.40 the cardinals
  // need roughly 19 degrees of pitch or 31 of yaw, which is what "agak"
  // means. Sitting still is still nowhere near it.
  minPoseRadius: 0.4,
}

function angleForClock(position: ClockPosition): number {
  // 12 -> 0 rad (straight up), clockwise positive, matching a clock face.
  const normalized = position % 12 // 12 -> 0
  return (normalized / 12) * 2 * Math.PI
}

/** Target (yaw, pitch) for a clock position, at full pose radius. */
export function targetPoseForClock(position: ClockPosition): HeadPose {
  const angle = angleForClock(position)
  return {
    yaw: Math.sin(angle) * POSE_RANGE.maxYawDeg,
    pitch: Math.cos(angle) * POSE_RANGE.maxPitchDeg,
  }
}

/** Everything the clock geometry derives from one pose sample. Returned as
 * a whole so the dev-only debug overlay can show exactly why a position did
 * or did not register, instead of leaving "nothing lights up" unexplained. */
export interface PoseBreakdown {
  /** Neutral-calibrated estimator output, in its nominal degrees. */
  yawDeg: number
  pitchDeg: number
  /** After normalising by POSE_RANGE and applying the sensitivity gains. */
  normYaw: number
  normPitch: number
  /** Distance from neutral; must reach `minPoseRadius` to resolve. */
  radius: number
  /** Clockwise from 12, in degrees. `null` when the radius gate fails. */
  angleDeg: number | null
  position: ClockPosition | null
}

/**
 * Full geometry for one pose sample. `resolveClockPosition` is the thin
 * wrapper the capture loop uses; this exists so the same numbers can be
 * displayed and unit-tested without duplicating the maths.
 */
export function describePose(
  pose: HeadPose,
  sensitivity: PoseSensitivity = DEFAULT_POSE_SENSITIVITY,
): PoseBreakdown {
  // Gain first, then cap the RADIUS rather than each axis. Clamping the
  // axes independently would rotate the result whenever one of them
  // saturated -- with a pitch gain above 1, an honest 1 o'clock pose
  // saturates both axes and lands at exactly 45 degrees, i.e. on the 1/2
  // boundary. Scaling the vector back along its own direction caps the
  // magnitude at 1 while leaving the angle untouched.
  //
  // Clamping the raw fraction BEFORE the gain would be worse still: it
  // would discard exactly the signal the gain exists to recover.
  const gainedYaw = (pose.yaw / POSE_RANGE.maxYawDeg) * sensitivity.yawGain
  const gainedPitch = (pose.pitch / POSE_RANGE.maxPitchDeg) * sensitivity.pitchGain
  const gainedRadius = Math.hypot(gainedYaw, gainedPitch)
  const scale = gainedRadius > 1 ? 1 / gainedRadius : 1
  const normYaw = gainedYaw * scale
  const normPitch = gainedPitch * scale
  const radius = Math.min(gainedRadius, 1)

  if (radius < sensitivity.minPoseRadius) {
    return {
      yawDeg: pose.yaw,
      pitchDeg: pose.pitch,
      normYaw,
      normPitch,
      radius,
      angleDeg: null,
      position: null,
    }
  }

  // atan2(x, y) with y=pitch, x=yaw gives angle measured clockwise from
  // "up" (pitch axis), matching angleForClock's convention.
  let angle = Math.atan2(normYaw, normPitch)
  if (angle < 0) angle += 2 * Math.PI

  // Snap to the nearest CAPTURE position rather than to one of twelve
  // 30-degree sectors. Each cardinal owns a 90-degree quadrant, so the
  // classification reduces to "which axis dominates, and what sign is it"
  // -- the part this estimator measures reliably. Placing a pose inside a
  // 30-degree sector additionally required the yaw-to-pitch RATIO to be
  // accurate, which it is not (see CAPTURE_POSITIONS' docstring).
  const quadrant = Math.round(angle / (Math.PI / 2)) % 4
  const candidate = QUADRANT_POSITION[quadrant]
  return {
    yawDeg: pose.yaw,
    pitchDeg: pose.pitch,
    normYaw,
    normPitch,
    radius,
    angleDeg: (angle * 180) / Math.PI,
    position: candidate ?? null,
  }
}

/** Quadrant index (0 = up, 1 = right, 2 = down, 3 = left) to clock position. */
const QUADRANT_POSITION: Record<number, ClockPosition> = { 0: 12, 1: 3, 2: 6, 3: 9 }

/**
 * Resolve a detected head pose to the nearest clock position, or null when
 * the pose is too close to neutral to belong to any position (e.g. subject
 * hasn't started moving yet).
 */
export function resolveClockPosition(
  pose: HeadPose,
  sensitivity: PoseSensitivity = DEFAULT_POSE_SENSITIVITY,
): ClockPosition | null {
  return describePose(pose, sensitivity).position
}

export function createInitialSectorState(): SectorState {
  const state = {} as SectorState
  for (const position of CLOCK_POSITIONS) state[position] = 'pending'
  return state
}

export interface SectorTrackerState {
  status: SectorState
  streaks: Record<ClockPosition, number>
}

export function createInitialTrackerState(): SectorTrackerState {
  const streaks = {} as Record<ClockPosition, number>
  for (const position of CLOCK_POSITIONS) streaks[position] = 0
  return { status: createInitialSectorState(), streaks }
}

/**
 * Pure reducer: fold one sampled frame into the sector tracker.
 *
 * Rules (no auto-pass, ever):
 * - No face in frame, or pose doesn't resolve to a position -> any
 *   currently-"active" sector reverts to "pending" (lost coverage).
 * - Face + resolved position + poor quality -> that sector is marked
 *   "poor" (unless already confirmed "done"); does not count toward the
 *   confirm streak.
 * - Face + resolved position + ok quality -> streak for that position
 *   increments; once it reaches FRAMES_TO_CONFIRM the sector becomes
 *   "done" (sticky — a later bad frame elsewhere does not undo it).
 *   Below the threshold it is shown as "active".
 * - Any other sector that was "active" (but not the one just sampled)
 *   reverts to "pending" — only one sector is "in progress" at a time.
 */
export function updateSectorState(
  prev: SectorTrackerState,
  frame: FrameSample,
): SectorTrackerState {
  const status = { ...prev.status }
  const streaks = { ...prev.streaks }

  const demoteOtherActive = (except: ClockPosition | null) => {
    for (const position of CLOCK_POSITIONS) {
      if (position === except) continue
      if (status[position] === 'active') status[position] = 'pending'
    }
  }

  if (!frame.faceInFrame || frame.clockPosition === null) {
    demoteOtherActive(null)
    return { status, streaks }
  }

  const position = frame.clockPosition
  demoteOtherActive(position)

  if (frame.quality === 'poor') {
    streaks[position] = 0
    if (status[position] !== 'done') status[position] = 'poor'
    return { status, streaks }
  }

  if (status[position] === 'done') {
    return { status, streaks }
  }

  streaks[position] += 1
  status[position] =
    streaks[position] >= FRAMES_TO_CONFIRM ? 'done' : 'active'
  return { status, streaks }
}

/** "Selesai" is only enabled once every CAPTURE position is "done" —
 * nothing is ever skipped or auto-completed. */
export function isCaptureComplete(status: SectorState): boolean {
  return CAPTURE_POSITIONS.every((position) => status[position] === 'done')
}

export function countDone(status: SectorState): number {
  return CAPTURE_POSITIONS.filter((position) => status[position] === 'done').length
}

/** Clockwise sweep order starting at 12 (FSD-AI.md ASM-03: "mulai jam 12
 * lalu berputar searah jarum jam"), over the captured cardinals. Used ONLY
 * to pick which position the directional guide animation (`ProgressRing`'s
 * `targetPosition` prop) points at next — it does not gate
 * `updateSectorState`, which still accepts a sample landing on any position
 * regardless of order. */
export const SWEEP_ORDER: ClockPosition[] = [...CAPTURE_POSITIONS]

/** The next position the directional guide should point at: the first
 * not-yet-`done` position in sweep order, or `null` once all are done
 * (nothing left to point at). */
export function nextTargetPosition(status: SectorState): ClockPosition | null {
  return SWEEP_ORDER.find((position) => status[position] !== 'done') ?? null
}
