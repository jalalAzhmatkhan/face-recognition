import { describe, expect, it } from 'vitest'
import { resolveClockPosition } from './clockSectors'
import { estimateHeadPose } from './headPose'
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

  it('regression: turning toward the on-screen upper-right resolves to clock position 1-2, never the mirrored 10-11', () => {
    // Raw nose offset (x:-20, up y:-20) is what a subject turning toward
    // their own on-screen upper-right (where the ring draws 1/2 o'clock on
    // the mirrored preview) actually produces in the un-mirrored landmark
    // data -- see estimateHeadPose's yaw comment for the full mirroring
    // explanation. Before that fix this resolved to 10/11 instead.
    const pose = estimateHeadPose(buildLandmarks({ x: -20, y: -20 }))
    expect(pose).not.toBeNull()
    const position = resolveClockPosition(pose!)
    expect([1, 2]).toContain(position)
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
