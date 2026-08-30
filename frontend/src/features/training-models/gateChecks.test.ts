import { describe, expect, it } from 'vitest'
import {
  compareHigherIsBetter,
  compareLowerIsBetter,
  computePromotionGateChecks,
  LATENCY_BUDGET_MS,
} from './gateChecks'
import type { ModelVersionResponse } from './types'

function model(overrides: Partial<ModelVersionResponse> = {}): ModelVersionResponse {
  return {
    version: 'v1',
    mlflow_run_id: 'run-1',
    stage: 'CANDIDATE',
    recall: 0.9,
    f1: 0.85,
    precision: 0.8,
    latency_ms_p95: 100,
    promoted_by: null,
    promoted_at: null,
    ...overrides,
  }
}

describe('compareHigherIsBetter', () => {
  it('is "up" when candidate is higher', () => {
    expect(compareHigherIsBetter(0.9, 0.8).direction).toBe('up')
  })
  it('is "down" when candidate is lower', () => {
    expect(compareHigherIsBetter(0.7, 0.8).direction).toBe('down')
  })
  it('is "flat" when equal', () => {
    expect(compareHigherIsBetter(0.8, 0.8).direction).toBe('flat')
  })
  it('is "unknown" when either side is missing', () => {
    expect(compareHigherIsBetter(null, 0.8).direction).toBe('unknown')
    expect(compareHigherIsBetter(0.8, null).direction).toBe('unknown')
  })
})

describe('compareLowerIsBetter', () => {
  it('is "up" (improvement) when candidate latency is lower', () => {
    expect(compareLowerIsBetter(100, 200).direction).toBe('up')
  })
  it('is "down" (regression) when candidate latency is higher', () => {
    expect(compareLowerIsBetter(300, 200).direction).toBe('down')
  })
  it('is "flat" when equal', () => {
    expect(compareLowerIsBetter(200, 200).direction).toBe('flat')
  })
  it('is "unknown" when either side is missing', () => {
    expect(compareLowerIsBetter(null, 200).direction).toBe('unknown')
  })
})

describe('computePromotionGateChecks', () => {
  it('passes both gates with no baseline (first-ever promotion) and a good latency', () => {
    const candidate = model({ recall: 0.5, latency_ms_p95: 100 })
    const checks = computePromotionGateChecks(candidate, null)
    expect(checks.recall.passed).toBe(true)
    expect(checks.recall.note).toMatch(/promosi pertama/i)
    expect(checks.latency.passed).toBe(true)
    expect(checks.allPassed).toBe(true)
  })

  it('fails the recall gate when candidate recall regresses vs production', () => {
    const candidate = model({ recall: 0.5 })
    const production = model({ recall: 0.9 })
    const checks = computePromotionGateChecks(candidate, production)
    expect(checks.recall.passed).toBe(false)
    expect(checks.allPassed).toBe(false)
  })

  it('passes the recall gate when candidate recall matches or exceeds production', () => {
    const candidate = model({ recall: 0.9 })
    const production = model({ recall: 0.9 })
    expect(computePromotionGateChecks(candidate, production).recall.passed).toBe(true)
  })

  it('fails the latency gate above the budget, passes at exactly the budget', () => {
    const overBudget = model({ latency_ms_p95: LATENCY_BUDGET_MS + 1 })
    expect(computePromotionGateChecks(overBudget, null).latency.passed).toBe(false)

    const atBudget = model({ latency_ms_p95: LATENCY_BUDGET_MS })
    expect(computePromotionGateChecks(atBudget, null).latency.passed).toBe(true)
  })

  it('fails the latency gate when latency is unknown (null)', () => {
    const unknownLatency = model({ latency_ms_p95: null })
    expect(computePromotionGateChecks(unknownLatency, null).latency.passed).toBe(false)
  })

  it('treats a null candidate recall as failing against any real production baseline', () => {
    const candidate = model({ recall: null })
    const production = model({ recall: 0.1 })
    expect(computePromotionGateChecks(candidate, production).recall.passed).toBe(false)
  })
})
