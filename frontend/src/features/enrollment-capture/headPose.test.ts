import { describe, expect, it } from 'vitest'
import { POSE_RANGE, resolveClockPosition } from './clockSectors'
import { averagePose, calibrateToNeutral, estimateHeadPose } from './headPose'
import type { Landmarks68, Point2D } from './types'

/** Build a synthetic, roughly face-shaped 68-point landmark set with the
 * nose tip placed at a controllable offset, so we can assert the sign and
 * rough magnitude of the resulting yaw/pitch without a real detector. */
function buildLandmarks(noseOffset: { x: number; y: number }): Landmarks68 {
  const points: Point2D[] = new Array(68).fill(null).map(() => ({ x: 0, y: 0 }))

  // Jaw edges (0, 16) — face width reference, centered at x=100.
  points[0] = { x: 60, y: 100 }
  points[16] = { x: 140, y: 100 }
  // Chin (8) and nose bridge/tip.
  points[8] = { x: 100, y: 160 }
  points[27] = { x: 100, y: 90 }
  // Baseline nose sits exactly on the eye-line/chin midpoint (125) and the
  // jaw-edge midline (100), i.e. a perfectly frontal face at offset (0, 0).
  points[30] = { x: 100 + noseOffset.x, y: 125 + noseOffset.y }
  // Eyes (36-41 left, 42-47 right), centered around y=90.
  for (let i = 36; i < 42; i += 1) points[i] = { x: 80, y: 90 }
  for (let i = 42; i < 48; i += 1) points[i] = { x: 120, y: 90 }

  return points
}

describe('estimateHeadPose', () => {
  it('returns near-zero yaw/pitch for a centered nose (frontal face)', () => {
    const pose = estimateHeadPose(buildLandmarks({ x: 0, y: 0 }))
    expect(pose).not.toBeNull()
    expect(pose!.yaw).toBeCloseTo(0, 1)
    expect(pose!.pitch).toBeCloseTo(0, 1)
  })

  it('produces positive pitch when the nose sits closer to the eyes (head up)', () => {
    const pose = estimateHeadPose(buildLandmarks({ x: 0, y: -20 }))
    expect(pose!.pitch).toBeGreaterThan(0)
  })

  it('produces negative pitch when the nose sits closer to the chin (head down)', () => {
    const pose = estimateHeadPose(buildLandmarks({ x: 0, y: 20 }))
    expect(pose!.pitch).toBeLessThan(0)
  })

  it('produces nonzero, opposite-sign yaw for left vs. right RAW nose offsets, matching the MIRRORED on-screen direction', () => {
    // Regression: yaw is negated relative to the raw landmark offset
    // because the wizard displays a mirrored preview (see estimateHeadPose's
    // yaw comment) -- a nose offset of x:-20 in the raw, un-mirrored frame
    // is what a subject turning toward their own on-screen RIGHT (positive
    // yaw, clock positions 1-5) actually produces, and vice versa.
    const onScreenRight = estimateHeadPose(buildLandmarks({ x: -20, y: 0 }))
    const onScreenLeft = estimateHeadPose(buildLandmarks({ x: 20, y: 0 }))
    expect(onScreenRight!.yaw).toBeGreaterThan(0)
    expect(onScreenLeft!.yaw).toBeLessThan(0)
    expect(onScreenLeft!.yaw).toBeCloseTo(-onScreenRight!.yaw, 5)
  })

  it('regression: turning toward the on-screen right resolves to the RIGHT of the ring, never the mirrored left', () => {
    // Raw nose offset (x:-20, up y:-20) is what a subject turning toward
    // their own on-screen upper-right actually produces in the un-mirrored
    // landmark data -- see estimateHeadPose's yaw comment for the full
    // mirroring explanation. Before that fix this resolved to the left half
    // of the ring. Now that capture snaps to the four cardinals it must land
    // on 12 or 3, and in particular never on 9.
    const pose = estimateHeadPose(buildLandmarks({ x: -20, y: -20 }))
    expect(pose).not.toBeNull()
    expect([12, 3]).toContain(resolveClockPosition(pose!))
  })

  it('returns null when fewer than 68 landmarks are provided', () => {
    expect(estimateHeadPose([{ x: 0, y: 0 }])).toBeNull()
  })

  it('clamps extreme offsets to the configured pose range', () => {
    const pose = estimateHeadPose(buildLandmarks({ x: 1000, y: 1000 }))
    expect(Math.abs(pose!.yaw)).toBeLessThanOrEqual(25)
    expect(Math.abs(pose!.pitch)).toBeLessThanOrEqual(20)
  })
})

describe('averagePose', () => {
  it('returns null for no samples', () => {
    expect(averagePose([])).toBeNull()
  })

  it('averages yaw and pitch independently', () => {
    expect(
      averagePose([
        { yaw: 0, pitch: 4 },
        { yaw: 10, pitch: 8 },
      ]),
    ).toEqual({ yaw: 5, pitch: 6 })
  })

  it('lets one outlier sample move the baseline only fractionally', () => {
    const steady = Array.from({ length: 4 }, () => ({ yaw: 0, pitch: 6 }))
    const withBlink = averagePose([...steady, { yaw: 0, pitch: 20 }])
    expect(withBlink!.pitch).toBeCloseTo(8.8, 5)
  })
})

describe('calibrateToNeutral', () => {
  it('is a no-op when no baseline was measured', () => {
    const pose = { yaw: 3, pitch: 7 }
    expect(calibrateToNeutral(pose, null)).toEqual(pose)
  })

  it('re-centres a pose on the measured neutral', () => {
    // The whole point: a subject sitting still measures a POSITIVE pitch,
    // so their neutral must read as (0, 0) after calibration.
    const neutral = { yaw: 1, pitch: 6.4 }
    expect(calibrateToNeutral(neutral, neutral)).toEqual({ yaw: 0, pitch: 0 })
  })

  it('makes downward pitch reachable by the same margin as upward', () => {
    const neutral = { yaw: 0, pitch: 6.4 }
    const up = calibrateToNeutral({ yaw: 0, pitch: 6.4 + 11 }, neutral)
    const down = calibrateToNeutral({ yaw: 0, pitch: 6.4 - 11 }, neutral)
    expect(up.pitch).toBeCloseTo(11, 5)
    expect(down.pitch).toBeCloseTo(-11, 5)
    // 12 o'clock and 6 o'clock now cost the same head movement -- before
    // calibration the same +-11 swing put 12 well past its threshold while
    // leaving 6 short of it.
    expect(Math.abs(up.pitch)).toBeCloseTo(Math.abs(down.pitch), 5)
  })

  it('saturates a mis-measured baseline at one full axis range', () => {
    // Subject was tilted hard when the photo was taken: the offset applied
    // must saturate rather than running away.
    const wild = { yaw: 999, pitch: -999 }
    const calibrated = calibrateToNeutral({ yaw: 0, pitch: 0 }, wild)
    expect(calibrated.yaw).toBeCloseTo(-POSE_RANGE.maxYawDeg, 5)
    expect(calibrated.pitch).toBeCloseTo(POSE_RANGE.maxPitchDeg, 5)
  })

  it('does not truncate a large but genuine baseline', () => {
    // Regression guard for the bug the server-side twin of this function
    // shipped with first: a cap of half the range left ~half of a real
    // (large) estimator bias in place, which looks like a fix but leaves
    // the bottom of the clock just as unreachable.
    const largeButReal = { yaw: 0, pitch: POSE_RANGE.maxPitchDeg * 0.97 }
    expect(calibrateToNeutral(largeButReal, largeButReal).pitch).toBeCloseTo(0, 5)
  })
})
