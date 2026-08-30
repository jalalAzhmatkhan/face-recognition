import { describe, expect, it } from 'vitest'
import { humanizeReason, humanizeReasons, REASON_TRANSLATIONS } from './reasonHumanizer'

describe('humanizeReason', () => {
  it('returns a non-empty Bahasa Indonesia string for every defined reason code', () => {
    for (const code of Object.keys(REASON_TRANSLATIONS)) {
      const text = humanizeReason(code)
      expect(typeof text).toBe('string')
      expect(text.length).toBeGreaterThan(0)
      // Sanity: translated text must not just echo the machine code back.
      expect(text).not.toBe(code)
    }
  })

  it('maps the two session-level video reasons exactly as specified', () => {
    expect(humanizeReason('video_missing')).toBe(
      'Video tidak ditemukan, silakan rekam ulang.',
    )
    expect(humanizeReason('video_undecodable')).toBe(
      'Video rusak/tidak bisa dibaca, silakan rekam ulang.',
    )
  })

  it('falls back gracefully for an unrecognized reason code', () => {
    const text = humanizeReason('some_future_reason_code')
    expect(typeof text).toBe('string')
    expect(text.length).toBeGreaterThan(0)
    expect(text).toContain('some_future_reason_code')
  })

  it('never throws and never returns empty on an empty/whitespace code', () => {
    expect(humanizeReason('')).toBeTruthy()
    expect(humanizeReason('   ')).toBeTruthy()
  })
})

describe('humanizeReasons', () => {
  it('maps each reason in a list', () => {
    const result = humanizeReasons(['video_missing', 'blurry'])
    expect(result).toHaveLength(2)
    expect(result[0]).toContain('Video tidak ditemukan')
  })

  it('returns an empty array for null/undefined/empty input', () => {
    expect(humanizeReasons(null)).toEqual([])
    expect(humanizeReasons(undefined)).toEqual([])
    expect(humanizeReasons([])).toEqual([])
  })
})
