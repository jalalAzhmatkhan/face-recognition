import { describe, expect, it } from 'vitest'
import {
  admitFrame,
  BURST_SIZE,
  capturedPositions,
  createEmptyBurstBuffer,
  flattenBurstBuffer,
  shouldAdmit,
} from './burstBuffer'
import type { BurstFrame } from './burstBuffer'
import { CLOCK_POSITIONS } from './types'

function frame(sharpness: number): BurstFrame {
  return { blob: new Blob([`${sharpness}`], { type: 'image/jpeg' }), sharpness }
}

describe('createEmptyBurstBuffer', () => {
  it('starts every clock position empty', () => {
    const buffer = createEmptyBurstBuffer()
    for (const position of CLOCK_POSITIONS) {
      expect(buffer[position]).toEqual([])
    }
  })

  it('hands out independent arrays per position', () => {
    const buffer = createEmptyBurstBuffer()
    buffer[3] = [frame(100)]
    expect(buffer[4]).toEqual([])
  })
})

describe('admitFrame', () => {
  it('fills up to BURST_SIZE in arrival order', () => {
    let buffer: BurstFrame[] = []
    for (const sharpness of [10, 20, 30]) {
      buffer = admitFrame(buffer, frame(sharpness))
    }
    expect(buffer.map((f) => f.sharpness)).toEqual([10, 20, 30])
    expect(buffer).toHaveLength(BURST_SIZE)
  })

  it('evicts the blurriest frame once full', () => {
    let buffer = [frame(10), frame(50), frame(30)]
    buffer = admitFrame(buffer, frame(40))
    expect(buffer.map((f) => f.sharpness).sort((a, b) => a - b)).toEqual([
      30, 40, 50,
    ])
  })

  it('keeps the buffer untouched when the new frame is the blurriest', () => {
    const buffer = [frame(10), frame(50), frame(30)]
    const next = admitFrame(buffer, frame(5))
    // Same reference, so the caller can skip the state update entirely.
    expect(next).toBe(buffer)
  })

  it('rejects a frame that merely ties the blurriest, avoiding pointless churn', () => {
    const buffer = [frame(10), frame(50), frame(30)]
    expect(admitFrame(buffer, frame(10))).toBe(buffer)
  })

  it('never grows past the requested size', () => {
    let buffer: BurstFrame[] = []
    for (let i = 0; i < 40; i += 1) buffer = admitFrame(buffer, frame(i))
    expect(buffer).toHaveLength(BURST_SIZE)
  })

  it('converges on the sharpest frames regardless of arrival order', () => {
    // A subject decelerating into a position produces its blurriest frames
    // FIRST -- the whole reason this is sharpest-wins and not first-N.
    let buffer: BurstFrame[] = []
    for (const sharpness of [5, 8, 12, 90, 20, 140, 60]) {
      buffer = admitFrame(buffer, frame(sharpness))
    }
    expect(buffer.map((f) => f.sharpness).sort((a, b) => a - b)).toEqual([
      60, 90, 140,
    ])
  })
})

describe('shouldAdmit', () => {
  it('is true while the buffer has room', () => {
    expect(shouldAdmit([frame(999)], 1)).toBe(true)
  })

  it('agrees with admitFrame once the buffer is full', () => {
    const buffer = [frame(10), frame(50), frame(30)]
    // It gates an expensive canvas.toBlob, so a disagreement would either
    // waste an encode or silently drop a frame that deserved a slot.
    for (const sharpness of [5, 10, 11, 30, 31, 500]) {
      const admitted = admitFrame(buffer, frame(sharpness)) !== buffer
      expect(shouldAdmit(buffer, sharpness)).toBe(admitted)
    }
  })
})

describe('capturedPositions', () => {
  it('lists only positions holding frames, in clockwise order from 12', () => {
    const buffer = createEmptyBurstBuffer()
    buffer[3] = [frame(1)]
    buffer[12] = [frame(1)]
    buffer[9] = [frame(1)]
    expect(capturedPositions(buffer)).toEqual([12, 3, 9])
  })

  it('is empty for a fresh buffer', () => {
    expect(capturedPositions(createEmptyBurstBuffer())).toEqual([])
  })
})

describe('flattenBurstBuffer', () => {
  it('pairs every frame with its position, in upload order', () => {
    const buffer = createEmptyBurstBuffer()
    buffer[12] = [frame(1), frame(2)]
    buffer[1] = [frame(3)]

    expect(
      flattenBurstBuffer(buffer).map(({ position, frame: f }) => [
        position,
        f.sharpness,
      ]),
    ).toEqual([
      [12, 1],
      [12, 2],
      [1, 3],
    ])
  })

  it('skips positions with nothing captured rather than emitting holes', () => {
    const buffer = createEmptyBurstBuffer()
    buffer[6] = [frame(1)]
    expect(flattenBurstBuffer(buffer)).toHaveLength(1)
  })
})
