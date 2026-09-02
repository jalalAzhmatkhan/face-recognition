import { describe, expect, it } from 'vitest'
import { averagePose, calibrateToNeutral } from './headPose'
import { describePose } from './clockSectors'
import type { HeadPose } from './types'

/**
 * The neutral-baseline measurement, as arithmetic.
 *
 * These pin the rules the capture page's sampling loop implements, because
 * the previous version of that loop produced NO baseline at all in practice
 * and nothing said so — the debug readout just showed "BELUM DIUKUR" while
 * every direction quietly misresolved. A null baseline is not a small
 * degradation: it leaves the estimator's structural +6.6 degree pitch offset
 * in place, and the tests below show exactly what that does.
 */

const MIN_NEUTRAL_SAMPLES = 5
const NEUTRAL_SAMPLE_COUNT = 20

/** The loop's rule: latch once MIN samples are in hand, keep refining, stop
 * at a full window. Mirrors `EnrollmentCapturePage`'s `sampleFrame`. */
function measure(poses: HeadPose[]) {
  let window: HeadPose[] = []
  let neutral: HeadPose | null = null
  let measuring = true
  for (const pose of poses) {
    if (!measuring) break
    window = [...window, pose].slice(-NEUTRAL_SAMPLE_COUNT)
    if (window.length >= MIN_NEUTRAL_SAMPLES) neutral = averagePose(window)
    if (window.length >= NEUTRAL_SAMPLE_COUNT) measuring = false
  }
  return { neutral, measuring, samples: window.length }
}

const frontal = (): HeadPose => ({ yaw: 0, pitch: 6.6 })

describe('neutral measurement', () => {
  it('latches a baseline well before the window is full', () => {
    // A full window would need every one of 20 consecutive frames to contain
    // a detectable face. Requiring that is how the measurement ended up
    // producing nothing at all.
    const { neutral, samples } = measure(Array.from({ length: 6 }, frontal))
    expect(neutral).not.toBeNull()
    expect(samples).toBe(6)
  })

  it('produces nothing when too few frames had a face, rather than a bad guess', () => {
    const { neutral } = measure(Array.from({ length: MIN_NEUTRAL_SAMPLES - 1 }, frontal))
    expect(neutral).toBeNull()
  })

  it('stops measuring once the window is full', () => {
    const { measuring } = measure(Array.from({ length: NEUTRAL_SAMPLE_COUNT + 5 }, frontal))
    expect(measuring).toBe(false)
  })

  it('averages away a single wobbly frame', () => {
    const poses = [...Array.from({ length: 9 }, frontal), { yaw: 20, pitch: -20 }]
    const { neutral } = measure(poses)
    expect(neutral!.pitch).toBeGreaterThan(3)
    expect(Math.abs(neutral!.yaw)).toBeLessThan(3)
  })
})

describe('what a missing baseline does to detection', () => {
  // Numbers from headPoseGeometry.test.ts: a frontal face reads about +6.6
  // pitch, and looking down ~25 degrees only subtracts about 5 of that.
  const lookingDown: HeadPose = { yaw: -1.5, pitch: 1.6 }

  it('misreads "menunduk" when uncalibrated, exactly as reported', () => {
    // Still POSITIVE pitch, so the pose sits in the upper half; the small
    // leftward yaw is then free to win the quadrant. Reported live as
    // "menunduk terdeteksi sebagai jam 9".
    const resolved = describePose(calibrateToNeutral(lookingDown, null)).position
    expect(resolved).not.toBe(6)
  })

  it('reads it as jam 6 once the baseline is subtracted', () => {
    const neutral = measure(Array.from({ length: 10 }, frontal)).neutral
    expect(neutral).not.toBeNull()

    const resolved = describePose(calibrateToNeutral(lookingDown, neutral)).position
    expect(resolved).toBe(6)
  })

  it('does not call a frontal face jam 12 once calibrated', () => {
    // Reported live: sitting still, looking straight ahead, registered as
    // jam 12 and got captured. Uncalibrated it must, arithmetically: +6.6
    // pitch x 3.5 gain = 1.16 normalised, well past the 0.40 radius gate.
    const neutral = measure(Array.from({ length: 10 }, frontal)).neutral

    expect(describePose(calibrateToNeutral(frontal(), null)).position).toBe(12)
    expect(describePose(calibrateToNeutral(frontal(), neutral)).position).toBeNull()
  })

  it('leaves a small unintentional drift below the gate', () => {
    // Calibration alone is not enough — the radius gate still has to reject
    // someone who is merely not perfectly still.
    const neutral = measure(Array.from({ length: 10 }, frontal)).neutral
    for (const drift of [
      { yaw: 0, pitch: 8.4 },
      { yaw: 2, pitch: 5 },
      { yaw: -2.5, pitch: 7.5 },
    ]) {
      expect(describePose(calibrateToNeutral(drift, neutral)).position).toBeNull()
    }
  })

  it('keeps a genuinely leftward look on jam 9 after calibration', () => {
    // The fix must not simply bias everything downward: a real left turn is
    // still a left turn.
    const neutral = measure(Array.from({ length: 10 }, frontal)).neutral
    const lookingLeft: HeadPose = { yaw: -8, pitch: 6.4 }

    expect(describePose(calibrateToNeutral(lookingLeft, neutral)).position).toBe(9)
  })
})
