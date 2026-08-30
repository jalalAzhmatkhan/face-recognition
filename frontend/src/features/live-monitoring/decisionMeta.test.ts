import { describe, expect, it } from 'vitest'
import { decisionMeta } from './decisionMeta'
import { ACCESS_DECISIONS } from './types'

describe('decisionMeta', () => {
  it('returns a label/icon/color for every known decision', () => {
    for (const decision of ACCESS_DECISIONS) {
      const meta = decisionMeta(decision)
      expect(meta.label).toBeTruthy()
      expect(meta.icon).toBeTruthy()
      expect(meta.colorVar).toMatch(/^var\(--/)
    }
  })

  it('gives SPOOF_SUSPECTED strong emphasis, distinct from DENIED', () => {
    expect(decisionMeta('SPOOF_SUSPECTED').emphasis).toBe('strong')
    expect(decisionMeta('DENIED').emphasis).toBe('default')
  })
})
