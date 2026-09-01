import { describe, expect, it } from 'vitest'
import {
  createInitialSectorState,
  createInitialTrackerState,
  FRAMES_TO_CONFIRM,
  isCaptureComplete,
  countDone,
  nextTargetPosition,
  resolveClockPosition,
  SWEEP_ORDER,
  targetPoseForClock,
  updateSectorState,
} from './clockSectors'
import { CLOCK_POSITIONS } from './types'
import type { FrameSample } from './types'

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
