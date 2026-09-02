import { describe, expect, it } from 'vitest'
import { estimateHeadPose } from './headPose'
import { describePose } from './clockSectors'
import type { Landmarks68, Point2D } from './types'

/**
 * `estimateHeadPose` against a projected 3D face, rather than against
 * hand-written landmark coordinates.
 *
 * These tests exist because the estimator's behaviour is genuinely hard to
 * reason about — its sign convention was argued from geometry twice during
 * debugging and got the wrong answer once. Rotating a real anthropometric
 * model by a known angle and projecting it is the only way to check the
 * signs without a camera and a human neck.
 *
 * The model constants are the ones ai-training already feeds to `solvePnP`
 * (`ai_training/quality/pose.py::_GENERIC_3D_FACE_MODEL`, in its Y-down /
 * Z-away-from-camera form), extended with the jaw-edge and eye-centre
 * points this estimator reads. They are approximate anthropometry, so these
 * tests assert SIGNS, ORDERING and MONOTONICITY — never exact degrees.
 */

interface P3 {
  x: number
  y: number
  z: number
}

/** Image convention: X right, Y DOWN, Z AWAY from camera. Origin at the
 * nose tip. Note that in the RAW (un-mirrored) camera frame the subject's
 * right side appears at NEGATIVE x. */
const MODEL = {
  noseTip: { x: 0, y: 0, z: 0 },
  chin: { x: 0, y: 63.6, z: 12.5 },
  subjectRightEye: { x: -35, y: -32.7, z: 26 },
  subjectLeftEye: { x: 35, y: -32.7, z: 26 },
  subjectRightJaw: { x: -75, y: -10, z: 60 },
  subjectLeftJaw: { x: 75, y: -10, z: 60 },
} satisfies Record<string, P3>

/**
 * @param yawDeg   positive = subject turns to THEIR OWN RIGHT
 * @param pitchDeg positive = subject tilts their head UP (mendongak)
 * @param rollDeg  positive = subject tips their head toward their own right shoulder
 */
function rotate(p: P3, yawDeg: number, pitchDeg: number, rollDeg: number): P3 {
  let { x, y, z } = p

  // Pitch about X: the face normal points at -Z here, so tilting UP rotates
  // it toward -Y.
  const rx = (pitchDeg * Math.PI) / 180
  let ny = y * Math.cos(rx) + z * Math.sin(rx)
  let nz = -y * Math.sin(rx) + z * Math.cos(rx)
  y = ny
  z = nz

  // Yaw about Y. Negated so positive means the subject's own right: their
  // right side is at negative x, and turning right brings it toward the
  // camera.
  const ry = (-yawDeg * Math.PI) / 180
  const nx = x * Math.cos(ry) - z * Math.sin(ry)
  nz = x * Math.sin(ry) + z * Math.cos(ry)
  x = nx
  z = nz

  // Roll in the image plane.
  const rz = (rollDeg * Math.PI) / 180
  ny = x * Math.sin(rz) + y * Math.cos(rz)
  const nx2 = x * Math.cos(rz) - y * Math.sin(rz)
  x = nx2
  y = ny

  return { x, y, z }
}

const CAMERA_DISTANCE = 600
const FOCAL = 600

function project(p: P3): Point2D {
  const depth = CAMERA_DISTANCE + p.z
  return { x: (FOCAL * p.x) / depth, y: (FOCAL * p.y) / depth }
}

/** A 68-point array with the indices `estimateHeadPose` actually reads
 * (0, 8, 16, 30, 36-41, 42-47) populated from the projected model. */
function landmarksFor(yawDeg: number, pitchDeg: number, rollDeg = 0): Landmarks68 {
  const at = (key: keyof typeof MODEL) => project(rotate(MODEL[key], yawDeg, pitchDeg, rollDeg))

  const points: Point2D[] = Array.from({ length: 68 }, () => ({ x: 0, y: 0 }))
  // Indices 0 and 16 are the two ends of the jaw contour; 0 is on the image
  // LEFT, which is the subject's right.
  points[0] = at('subjectRightJaw')
  points[16] = at('subjectLeftJaw')
  points[8] = at('chin')
  points[30] = at('noseTip')
  for (let i = 36; i < 42; i += 1) points[i] = at('subjectRightEye')
  for (let i = 42; i < 48; i += 1) points[i] = at('subjectLeftEye')
  return points
}

function poseAt(yawDeg: number, pitchDeg: number, rollDeg = 0) {
  const pose = estimateHeadPose(landmarksFor(yawDeg, pitchDeg, rollDeg))
  if (pose === null) throw new Error('estimateHeadPose returned null for a valid face')
  return pose
}

describe('estimateHeadPose sign conventions', () => {
  it('reports positive yaw when the subject turns to their own right', () => {
    // Positive yaw must mean the RIGHT half of the clock (3 o'clock), which
    // is also the right half of the mirrored preview the subject watches.
    expect(poseAt(30, 0).yaw).toBeGreaterThan(0)
    expect(poseAt(-30, 0).yaw).toBeLessThan(0)
  })

  it('reports increasing pitch as the subject looks further up', () => {
    const down = poseAt(0, -30).pitch
    const level = poseAt(0, 0).pitch
    const up = poseAt(0, 30).pitch
    expect(down).toBeLessThan(level)
    expect(level).toBeLessThan(up)
  })

  it('is monotonic in yaw', () => {
    const yaws = [-40, -20, 0, 20, 40].map((deg) => poseAt(deg, 0).yaw)
    for (let i = 1; i < yaws.length; i += 1) {
      expect(yaws[i]).toBeGreaterThan(yaws[i - 1])
    }
  })
})

describe('estimateHeadPose conditioning — why the neutral baseline matters', () => {
  it('reads a frontal face as tilted UP, not level', () => {
    // The nose tip sits above the eye/chin midpoint, so a perfectly frontal
    // face measures a substantial positive pitch. Everything downstream is
    // relative to this, which is exactly why `calibrateToNeutral` exists.
    expect(poseAt(0, 0).pitch).toBeGreaterThan(4)
    expect(poseAt(0, 0).yaw).toBeCloseTo(0, 1)
  })

  it('has a usable pitch swing no larger than the frontal offset itself', () => {
    // The number that makes calibration accuracy critical: the structural
    // offset is about as large as the entire signal, so a baseline captured
    // while the subject looked somewhere other than the camera rotates the
    // whole dial. Guards against anyone "simplifying" the calibration away.
    const level = poseAt(0, 0).pitch
    const swing = Math.max(poseAt(0, 40).pitch - level, level - poseAt(0, -40).pitch)
    expect(swing).toBeLessThan(level * 2)
  })

  it('an uncalibrated down-and-right pose is misread as the TOP of the dial', () => {
    // The reported bug: aiming at jam 4/5 lit up jam 1/2. Without the
    // neutral subtraction the frontal offset dominates the small downward
    // movement, so the angle stays in the upper half.
    const uncalibrated = describePose(poseAt(20, -20)).position
    expect(uncalibrated).not.toBeNull()
    expect([1, 2, 3]).toContain(uncalibrated)
  })

  it('resolves the same pose correctly once the neutral offset is removed', () => {
    const neutral = poseAt(0, 0)
    const raw = poseAt(20, -20)
    const calibrated = { yaw: raw.yaw - neutral.yaw, pitch: raw.pitch - neutral.pitch }

    // Down-and-right, so the lower or right cardinal -- emphatically not the
    // top of the dial it landed on uncalibrated.
    expect([3, 6]).toContain(describePose(calibrated).position)
  })

  it('resolves each captured direction from the movement its label describes', () => {
    // The four instructions the wizard gives, taken literally.
    const neutral = poseAt(0, 0)
    const calibratedAt = (yaw: number, pitch: number) => {
      const raw = poseAt(yaw, pitch)
      return describePose({
        yaw: raw.yaw - neutral.yaw,
        pitch: raw.pitch - neutral.pitch,
      }).position
    }

    expect(calibratedAt(0, 25)).toBe(12) // agak mendongak
    expect(calibratedAt(35, 0)).toBe(3) // agak menoleh ke kanan
    expect(calibratedAt(0, -25)).toBe(6) // agak menunduk
    expect(calibratedAt(-35, 0)).toBe(9) // agak menoleh ke kiri
  })

  it('still resolves correctly when the subject drifts well off the cardinal', () => {
    // The whole reason for dropping to four targets: a sloppy "up and a bit
    // to the right" must still be jam 12, where a 30-degree sector would
    // have called it jam 1 or 2.
    const neutral = poseAt(0, 0)
    const calibratedAt = (yaw: number, pitch: number) => {
      const raw = poseAt(yaw, pitch)
      return describePose({
        yaw: raw.yaw - neutral.yaw,
        pitch: raw.pitch - neutral.pitch,
      }).position
    }

    expect(calibratedAt(20, 30)).toBe(12)
    expect(calibratedAt(-20, 30)).toBe(12)
    expect(calibratedAt(20, -30)).toBe(6)
    expect(calibratedAt(35, 15)).toBe(3)
    expect(calibratedAt(-35, -15)).toBe(9)
  })
})
