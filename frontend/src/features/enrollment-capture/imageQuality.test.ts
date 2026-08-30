import { describe, expect, it } from 'vitest'
import {
  assessQuality,
  averageBrightness,
  laplacianVariance,
  QUALITY_THRESHOLDS,
} from './imageQuality'

/** Build a minimal object satisfying the ImageData shape our pure
 * functions read (data/width/height) — avoids depending on jsdom having a
 * real ImageData/canvas implementation available. */
function makeImageData(
  width: number,
  height: number,
  pixel: (x: number, y: number) => number,
): ImageData {
  const data = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const value = pixel(x, y)
      const idx = (y * width + x) * 4
      data[idx] = value
      data[idx + 1] = value
      data[idx + 2] = value
      data[idx + 3] = 255
    }
  }
  return { data, width, height, colorSpace: 'srgb' } as ImageData
}

describe('averageBrightness', () => {
  it('reports the flat gray value for a uniform image', () => {
    const image = makeImageData(10, 10, () => 128)
    expect(averageBrightness(image)).toBeCloseTo(128, 5)
  })

  it('reports near-zero for a black image and near-255 for white', () => {
    expect(averageBrightness(makeImageData(4, 4, () => 0))).toBeCloseTo(0, 5)
    expect(averageBrightness(makeImageData(4, 4, () => 255))).toBeCloseTo(
      255,
      5,
    )
  })
})

describe('laplacianVariance', () => {
  it('is zero (or near-zero) for a perfectly flat/blurry image', () => {
    const flat = makeImageData(20, 20, () => 128)
    expect(laplacianVariance(flat)).toBeCloseTo(0, 5)
  })

  it('is high for a sharp checkerboard pattern', () => {
    const checkerboard = makeImageData(20, 20, (x, y) =>
      (x + y) % 2 === 0 ? 255 : 0,
    )
    expect(laplacianVariance(checkerboard)).toBeGreaterThan(1000)
  })
})

describe('assessQuality', () => {
  it('flags a flat, blurry frame as poor', () => {
    const flat = makeImageData(20, 20, () => 128)
    const result = assessQuality(flat)
    expect(result.isBlurry).toBe(true)
    expect(result.status).toBe('poor')
  })

  it('flags a dark frame as poor even if sharp', () => {
    const dark = makeImageData(20, 20, (x, y) =>
      (x + y) % 2 === 0 ? 20 : 10,
    )
    const result = assessQuality(dark)
    expect(result.isTooDark).toBe(true)
    expect(result.status).toBe('poor')
  })

  it('flags a bright, sharp checkerboard as ok when within thresholds', () => {
    const image = makeImageData(20, 20, (x, y) =>
      (x + y) % 2 === 0 ? 200 : 140,
    )
    const result = assessQuality(image, QUALITY_THRESHOLDS)
    expect(result.status).toBe('ok')
  })
})
