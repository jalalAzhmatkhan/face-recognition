import type { QualityAssessment } from './types'

/**
 * Real (non-stub) blur/lighting heuristics computed from a canvas frame's
 * ImageData:
 *  - Blur: variance of the Laplacian of the grayscale image. A sharp image
 *    has strong edges -> high-variance Laplacian response; a blurry image
 *    is smooth -> low variance. This is the standard, cheap
 *    "variance of Laplacian" blur metric.
 *  - Lighting: mean grayscale brightness (0-255).
 */

export interface QualityThresholds {
  minBlurVariance: number
  minBrightness: number
  maxBrightness: number
}

/**
 * Built-in defaults. Deliberately NOT `as const`: these are overridable at
 * runtime by the System Parameter menu
 * (`GET /system-parameters/enrollment-quality`), and `as const` narrowed
 * them to the literal types `60`/`60`/`200`, so assigning a fetched value
 * was a type error under the build config — the override could not
 * typecheck at all.
 */
export const QUALITY_THRESHOLDS: QualityThresholds = {
  minBlurVariance: 60,
  minBrightness: 60,
  maxBrightness: 200,
}

function toGrayscale(imageData: ImageData): Float32Array {
  const { data, width, height } = imageData
  const gray = new Float32Array(width * height)
  for (let i = 0, p = 0; i < data.length; i += 4, p += 1) {
    // Standard luma weights.
    gray[p] = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]
  }
  return gray
}

export function laplacianVariance(imageData: ImageData): number {
  const { width, height } = imageData
  if (width < 3 || height < 3) return 0
  const gray = toGrayscale(imageData)

  const laplacian: number[] = []
  for (let y = 1; y < height - 1; y += 1) {
    for (let x = 1; x < width - 1; x += 1) {
      const idx = y * width + x
      const value =
        4 * gray[idx] -
        gray[idx - 1] -
        gray[idx + 1] -
        gray[idx - width] -
        gray[idx + width]
      laplacian.push(value)
    }
  }
  if (laplacian.length === 0) return 0

  const mean = laplacian.reduce((a, b) => a + b, 0) / laplacian.length
  const variance =
    laplacian.reduce((a, b) => a + (b - mean) ** 2, 0) / laplacian.length
  return variance
}

export function averageBrightness(imageData: ImageData): number {
  const gray = toGrayscale(imageData)
  if (gray.length === 0) return 0
  let sum = 0
  for (const value of gray) sum += value
  return sum / gray.length
}

export function assessQuality(
  imageData: ImageData,
  thresholds: QualityThresholds = QUALITY_THRESHOLDS,
): QualityAssessment {
  const blurVariance = laplacianVariance(imageData)
  const brightness = averageBrightness(imageData)

  const isBlurry = blurVariance < thresholds.minBlurVariance
  const isTooDark = brightness < thresholds.minBrightness
  const isTooBright = brightness > thresholds.maxBrightness

  return {
    blurVariance,
    brightness,
    isBlurry,
    isTooDark,
    isTooBright,
    status: isBlurry || isTooDark || isTooBright ? 'poor' : 'ok',
  }
}
