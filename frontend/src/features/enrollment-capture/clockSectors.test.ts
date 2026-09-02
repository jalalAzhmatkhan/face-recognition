import { describe, expect, it } from 'vitest'
import {
  createInitialSectorState,
  createInitialTrackerState,
  DEFAULT_POSE_SENSITIVITY,
  describePose,
  FRAMES_TO_CONFIRM,
  isCaptureComplete,
  countDone,
  nextTargetPosition,
  POSE_RANGE,
  resolveClockPosition,
  SWEEP_ORDER,
  targetPoseForClock,
  updateSectorState,
} from './clockSectors'
import { CLOCK_POSITIONS } from './types'
import type { ClockPosition, FrameSample } from './types'

/**
 * What `headPose.ts` actually reports for a head rotated by `deg`, so these
 * tests exercise realistic estimator output rather than idealised targets.
 *
 * `estimateHeadPose` measures how far the nose sits off the face's midlines,
 * which geometrically works out to `protrusion x tan(angle)` where
 * `protrusion` is the nose's forward projection expressed as a fraction of
 * the half-width (yaw) or half eye-to-chin height (pitch). Both are around a
 * third, which is precisely why the raw signal is so weak — a 30 degree
 * head tilt only moves the reading by ~0.19 of full scale.
 */
const NOSE_PROTRUSION_YAW = 0.27
const NOSE_PROTRUSION_PITCH = 0.33

function poseAt(yawDeg: number, pitchDeg: number) {
  const toFraction = (deg: number, protrusion: number) =>
    protrusion * Math.tan((deg * Math.PI) / 180)
  return {
    yaw: toFraction(yawDeg, NOSE_PROTRUSION_YAW) * POSE_RANGE.maxYawDeg,
    pitch: toFraction(pitchDeg, NOSE_PROTRUSION_PITCH) * POSE_RANGE.maxPitchDeg,
  }
}

/** Head angles a person can actually hold. Neck extension/flexion tops out
 * far short of how far the head turns sideways, which is the asymmetry the
 * per-axis gains exist to compensate for. */
const COMFORTABLE_YAW_DEG = 40
const COMFORTABLE_PITCH_DEG = 30

describe('pose sensitivity — every clock position must be reachable', () => {
  /** Head angles (yaw, pitch) that aim at each clock position, at angles a
   * real neck can hold. */
  function realisticPoseFor(position: ClockPosition) {
    const angle = ((position % 12) / 12) * 2 * Math.PI
    return poseAt(
      Math.sin(angle) * COMFORTABLE_YAW_DEG,
      Math.cos(angle) * COMFORTABLE_PITCH_DEG,
    )
  }

  it('resolves all 12 positions from head angles a person can actually hold', () => {
    const resolved = CLOCK_POSITIONS.map((position) =>
      resolveClockPosition(realisticPoseFor(position)),
    )
    expect(resolved).toEqual(CLOCK_POSITIONS)
  })

  it('shows the reported asymmetry once the gains are removed', () => {
    // Ungained (gain 1) is what shipped, and it was reported live as "only
    // jam 2, 3, 4, 8, 9, 10 terdeteksi" — the yaw-dominant half of the dial.
    // Asserted as the asymmetry rather than that exact set: which diagonals
    // squeak past the gate depends on the nose-protrusion constants above,
    // which are approximations. The direction of the effect is not.
    const ungained = { yawGain: 1, pitchGain: 1, minPoseRadius: 0.55 }

    // A hard sideways turn still registers, because the head turns far.
    expect(resolveClockPosition(poseAt(65, 0), ungained)).toBe(3)
    expect(resolveClockPosition(poseAt(-65, 0), ungained)).toBe(9)

    // Tilting further than any neck actually goes still does not.
    expect(resolveClockPosition(poseAt(0, 45), ungained)).toBeNull()
    expect(resolveClockPosition(poseAt(0, -45), ungained)).toBeNull()
  })

  it('needs roughly 25 degrees of pitch for 12 o\'clock, not 59', () => {
    // The number that made this a bug: at gain 1 the radius gate demanded
    // more neck extension than most people have.
    const pitchNeeded = (gain: number) => {
      for (let deg = 1; deg <= 89; deg += 1) {
        const pose = poseAt(0, deg)
        const sens = { ...DEFAULT_POSE_SENSITIVITY, pitchGain: gain }
        if (describePose(pose, sens).position === 12) return deg
      }
      return Infinity
    }

    expect(pitchNeeded(1)).toBeGreaterThan(55)
    expect(pitchNeeded(DEFAULT_POSE_SENSITIVITY.pitchGain)).toBeLessThanOrEqual(27)
  })

  it('keeps 6 o\'clock as reachable as 12 (the symmetric complaint)', () => {
    expect(resolveClockPosition(poseAt(0, COMFORTABLE_PITCH_DEG))).toBe(12)
    expect(resolveClockPosition(poseAt(0, -COMFORTABLE_PITCH_DEG))).toBe(6)
  })

  it('still rejects a head that has barely moved', () => {
    // Raising sensitivity must not turn "sitting still" into a position.
    expect(resolveClockPosition(poseAt(0, 0))).toBeNull()
    expect(resolveClockPosition(poseAt(5, 5))).toBeNull()
  })
})

describe('describePose', () => {
  it('caps the radius without rotating the angle', () => {
    // Per-axis clamping would push a saturated 1 o'clock pose to exactly 45
    // degrees -- the 1/2 boundary. Scaling the vector radially must not.
    const huge = describePose({ yaw: 25, pitch: 20 }, {
      yawGain: 10,
      pitchGain: 10,
      minPoseRadius: 0.55,
    })
    expect(huge.radius).toBeCloseTo(1, 6)
    expect(huge.angleDeg).toBeCloseTo(
      (Math.atan2(1, 1) * 180) / Math.PI,
      6,
    )
  })

  it('reports the radius that failed the gate, so a near miss is visible', () => {
    const breakdown = describePose(poseAt(0, 10))
    expect(breakdown.position).toBeNull()
    expect(breakdown.angleDeg).toBeNull()
    expect(breakdown.radius).toBeGreaterThan(0)
    expect(breakdown.radius).toBeLessThan(DEFAULT_POSE_SENSITIVITY.minPoseRadius)
  })

  it('passes the calibrated degrees through untouched for display', () => {
    const breakdown = describePose({ yaw: -7.5, pitch: 4 })
    expect(breakdown.yawDeg).toBe(-7.5)
    expect(breakdown.pitchDeg).toBe(4)
  })

  it('agrees with resolveClockPosition', () => {
    for (const position of CLOCK_POSITIONS) {
      const pose = targetPoseForClock(position)
      expect(describePose(pose).position).toBe(resolveClockPosition(pose))
    }
  })
})

describe('targetPoseForClock / resolveClockPosition', () => {
  it('round-trips every clock position through its target pose', () => {
    for (const position of CLOCK_POSITIONS) {
      const pose = targetPoseForClock(position)
      expect(resolveClockPosition(pose)).toBe(position)
    }
  })

  it('treats a near-neutral pose as no position (not 12 o\'clock)', () => {
    expect(resolveClockPosition({ yaw: 0, pitch: 0 })).toBeNull()
    expect(resolveClockPosition({ yaw: 1, pitch: 1 })).toBeNull()
  })

  it('has no back-of-head case — every position maps within the pose range', () => {
    for (const position of CLOCK_POSITIONS) {
      const pose = targetPoseForClock(position)
      expect(Math.abs(pose.yaw)).toBeLessThanOrEqual(25)
      expect(Math.abs(pose.pitch)).toBeLessThanOrEqual(20)
    }
  })
})

describe('updateSectorState', () => {
  function frame(overrides: Partial<FrameSample>): FrameSample {
    return { faceInFrame: true, clockPosition: 12, quality: 'ok', ...overrides }
  }

  it('starts every sector pending', () => {
    const state = createInitialSectorState()
    expect(Object.values(state).every((s) => s === 'pending')).toBe(true)
    expect(isCaptureComplete(state)).toBe(false)
  })

  it('never auto-passes a sector without a qualifying sample', () => {
    let tracker = createInitialTrackerState()
    // No face at all for a while — nothing should ever become "done".
    for (let i = 0; i < 20; i += 1) {
      tracker = updateSectorState(tracker, {
        faceInFrame: false,
        clockPosition: null,
        quality: 'poor',
      })
    }
    expect(isCaptureComplete(tracker.status)).toBe(false)
    expect(countDone(tracker.status)).toBe(0)
  })

  it('confirms a sector "done" only after FRAMES_TO_CONFIRM good samples', () => {
    let tracker = createInitialTrackerState()
    for (let i = 0; i < FRAMES_TO_CONFIRM - 1; i += 1) {
      tracker = updateSectorState(tracker, frame({}))
      expect(tracker.status[12]).toBe('active')
    }
    tracker = updateSectorState(tracker, frame({}))
    expect(tracker.status[12]).toBe('done')
  })

  it('marks a sector "poor" (not done) on bad quality, and resets its streak', () => {
    let tracker = createInitialTrackerState()
    tracker = updateSectorState(tracker, frame({}))
    tracker = updateSectorState(tracker, frame({ quality: 'poor' }))
    expect(tracker.status[12]).toBe('poor')
    // Needs a full fresh streak afterwards, not just one more good frame.
    tracker = updateSectorState(tracker, frame({}))
    expect(tracker.status[12]).toBe('active')
  })

  it('demotes losing face-in-frame to pending, not "done"', () => {
    let tracker = createInitialTrackerState()
    tracker = updateSectorState(tracker, frame({}))
    expect(tracker.status[12]).toBe('active')
    tracker = updateSectorState(tracker, {
      faceInFrame: false,
      clockPosition: null,
      quality: 'poor',
    })
    expect(tracker.status[12]).toBe('pending')
  })

  it('a confirmed "done" sector stays done even if tracking moves elsewhere', () => {
    let tracker = createInitialTrackerState()
    for (let i = 0; i < FRAMES_TO_CONFIRM; i += 1) {
      tracker = updateSectorState(tracker, frame({}))
    }
    expect(tracker.status[12]).toBe('done')
    tracker = updateSectorState(tracker, frame({ clockPosition: 3 }))
    expect(tracker.status[12]).toBe('done')
  })

  it('"Selesai" is enabled only once all 12 sectors are done', () => {
    let tracker = createInitialTrackerState()
    for (const position of CLOCK_POSITIONS.slice(0, 11)) {
      for (let i = 0; i < FRAMES_TO_CONFIRM; i += 1) {
        tracker = updateSectorState(tracker, frame({ clockPosition: position }))
      }
    }
    expect(isCaptureComplete(tracker.status)).toBe(false)
    expect(countDone(tracker.status)).toBe(11)

    for (let i = 0; i < FRAMES_TO_CONFIRM; i += 1) {
      tracker = updateSectorState(tracker, frame({ clockPosition: 12 }))
    }
    expect(isCaptureComplete(tracker.status)).toBe(true)
    expect(countDone(tracker.status)).toBe(12)
  })
})

describe('nextTargetPosition', () => {
  it('points at 12 first, before anything is confirmed', () => {
    expect(nextTargetPosition(createInitialSectorState())).toBe(12)
  })

  it('advances to the next position in sweep order once the current one is done', () => {
    const status = createInitialSectorState()
    status[12] = 'done'
    expect(nextTargetPosition(status)).toBe(1)
    status[1] = 'done'
    expect(nextTargetPosition(status)).toBe(2)
  })

  it('skips over already-done positions even out of sweep order', () => {
    const status = createInitialSectorState()
    status[1] = 'done'
    status[2] = 'done'
    // 12 (first in sweep order) is still pending, so it's still the target.
    expect(nextTargetPosition(status)).toBe(12)
  })

  it('is unaffected by "active"/"poor" — only "done" advances the target', () => {
    const status = createInitialSectorState()
    status[12] = 'active'
    expect(nextTargetPosition(status)).toBe(12)
    status[12] = 'poor'
    expect(nextTargetPosition(status)).toBe(12)
  })

  it('returns null once every position is done', () => {
    const status = createInitialSectorState()
    for (const position of CLOCK_POSITIONS) status[position] = 'done'
    expect(nextTargetPosition(status)).toBeNull()
  })

  it('sweep order starts at 12 and is otherwise clockwise 1..11', () => {
    expect(SWEEP_ORDER).toEqual([12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
  })
})
