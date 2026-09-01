import { describe, expect, it } from 'vitest'
import {
  computeConditionFlagBreakdown,
  computeDeviceClassBreakdown,
  computeRejectStageBreakdown,
} from './edgeCaseAggregation'
import type { AccessEventSample } from './types'

function event(overrides: Partial<AccessEventSample> = {}): AccessEventSample {
  return {
    id: 'evt-1',
    decision: 'DENIED',
    reject_stage: null,
    condition_flags: null,
    device_class: null,
    ...overrides,
  }
}

describe('computeRejectStageBreakdown', () => {
  it('buckets GRANTED decisions into a synthetic "granted" row', () => {
    const rows = computeRejectStageBreakdown([
      event({ decision: 'GRANTED', reject_stage: null }),
      event({ decision: 'GRANTED', reject_stage: null }),
      event({ decision: 'DENIED', reject_stage: 'liveness' }),
    ])
    const granted = rows.find((r) => r.key === 'granted')
    const liveness = rows.find((r) => r.key === 'liveness')
    expect(granted).toEqual({ key: 'granted', count: 2, pct: 66.7 })
    expect(liveness).toEqual({ key: 'liveness', count: 1, pct: 33.3 })
  })

  it('includes every canonical reject stage even with zero count', () => {
    const rows = computeRejectStageBreakdown([event({ decision: 'GRANTED' })])
    const keys = rows.map((r) => r.key)
    expect(keys).toEqual(['granted', 'detection', 'liveness', 'quality_gate', 'threshold', 'policy'])
  })

  it('excludes non-GRANTED rows with no reject_stage from the denominator', () => {
    const rows = computeRejectStageBreakdown([
      event({ decision: 'DENIED', reject_stage: null }),
      event({ decision: 'DENIED', reject_stage: 'threshold' }),
    ])
    const threshold = rows.find((r) => r.key === 'threshold')
    expect(threshold).toEqual({ key: 'threshold', count: 1, pct: 100 })
  })

  it('returns all-zero rows for an empty sample without dividing by zero', () => {
    const rows = computeRejectStageBreakdown([])
    expect(rows.every((r) => r.count === 0 && r.pct === 0)).toBe(true)
  })
})

describe('computeConditionFlagBreakdown', () => {
  it('counts each flag independently (a row can set multiple flags)', () => {
    const rows = computeConditionFlagBreakdown([
      event({ condition_flags: { masked: true, dark: true } }),
      event({ condition_flags: { masked: true } }),
      event({ condition_flags: { sunglasses: true } }),
      event({ condition_flags: null }),
    ])
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]))
    expect(byKey.masked).toEqual({ key: 'masked', count: 2, pct: 50 })
    expect(byKey.dark).toEqual({ key: 'dark', count: 1, pct: 25 })
    expect(byKey.sunglasses).toEqual({ key: 'sunglasses', count: 1, pct: 25 })
    expect(byKey.blurry).toEqual({ key: 'blurry', count: 0, pct: 0 })
    expect(byKey.low_res).toEqual({ key: 'low_res', count: 0, pct: 0 })
  })
})

describe('computeDeviceClassBreakdown', () => {
  it('folds null device_class into "unknown" so percentages sum to 100', () => {
    const rows = computeDeviceClassBreakdown([
      event({ device_class: 'door_entry' }),
      event({ device_class: 'attendance' }),
      event({ device_class: null }),
      event({ device_class: 'unknown' }),
    ])
    const byKey = Object.fromEntries(rows.map((r) => [r.key, r]))
    expect(byKey.door_entry).toEqual({ key: 'door_entry', count: 1, pct: 25 })
    expect(byKey.attendance).toEqual({ key: 'attendance', count: 1, pct: 25 })
    expect(byKey.unknown).toEqual({ key: 'unknown', count: 2, pct: 50 })
  })
})
