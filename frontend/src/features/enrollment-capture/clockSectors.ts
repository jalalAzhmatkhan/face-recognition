import type {
  ClockPosition,
  FrameSample,
  HeadPose,
  SectorState,
} from './types'
import { CLOCK_POSITIONS } from './types'

/**
 * Clock-position <-> head-pose mapping and the sector-coverage reducer.
 *
 * Per FSD-AI.md ASM-03 (CORRECTED 2026-08-30) the "rotation" is a sweep of
 * head yaw/pitch, not a body/camera turn: 12 o'clock = head tilted up,
 * moving clockwise mixes yaw (left/right) and pitch (up/down), the face is
 * always visible. This module treats each clock position as one point on a
 * circle in (yaw, pitch) space and maps a detected pose to the nearest
 * position — there is no "back of head" case, and no auto-pass: a sector
 * only advances when a pose sample actually lands near it.
 */

/** Practical head-pose range for the 12-position sweep (degrees). Narrower
 * than a full head turn, per the ASM-03 correction. */
export const POSE_RANGE = {
  maxYawDeg: 25,
  maxPitchDeg: 20,
} as const

/** How many consecutive qualifying frames are required before a sector is
 * confirmed "done" (debounces flicker / a single lucky frame). */
export const FRAMES_TO_CONFIRM = 5

/** Minimum fraction of the max pose range a sample must reach before it is
 * considered "at" a clock position rather than still near neutral/center. */
const MIN_POSE_RADIUS_FRACTION = 0.55

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

/**
 * Resolve a detected head pose to the nearest clock position, or null when
 * the pose is too close to neutral to belong to any position (e.g. subject
 * hasn't started moving yet).
 */
export function resolveClockPosition(pose: HeadPose): ClockPosition | null {
  const normYaw = pose.yaw / POSE_RANGE.maxYawDeg
  const normPitch = pose.pitch / POSE_RANGE.maxPitchDeg
  const radius = Math.hypot(normYaw, normPitch)
  if (radius < MIN_POSE_RADIUS_FRACTION) return null

  // atan2(x, y) with y=pitch, x=yaw gives angle measured clockwise from
  // "up" (pitch axis), matching angleForClock's convention.
  let angle = Math.atan2(normYaw, normPitch)
  if (angle < 0) angle += 2 * Math.PI

  const raw = Math.round((angle / (2 * Math.PI)) * 12)
  const position = raw === 0 ? 12 : (raw as ClockPosition)
  return CLOCK_POSITIONS.includes(position) ? position : null
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

/** "Selesai" is only enabled once every one of the 12 sectors is "done" —
 * nothing is ever skipped or auto-completed. */
export function isCaptureComplete(status: SectorState): boolean {
  return CLOCK_POSITIONS.every((position) => status[position] === 'done')
}

export function countDone(status: SectorState): number {
  return CLOCK_POSITIONS.filter((position) => status[position] === 'done')
    .length
}
