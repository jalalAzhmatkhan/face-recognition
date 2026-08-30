import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import GateChecklist from './GateChecklist'
import { computePromotionGateChecks } from './gateChecks'
import type { ModelVersionResponse } from './types'

afterEach(() => cleanup())

function model(overrides: Partial<ModelVersionResponse>): ModelVersionResponse {
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

describe('GateChecklist', () => {
  it('shows both gates passing (✓) when candidate beats production and is within latency budget', () => {
    const checks = computePromotionGateChecks(
      model({ recall: 0.95, latency_ms_p95: 100 }),
      model({ recall: 0.9 }),
    )
    render(<GateChecklist checks={checks} />)
    expect(screen.getByText(/Recall ≥ produksi ✓/)).toBeInTheDocument()
    expect(screen.getByText(/Latency p95 ≤ 300 ms ✓/)).toBeInTheDocument()
  })

  it('shows a failing gate (✗) with its reason when recall regresses', () => {
    const checks = computePromotionGateChecks(
      model({ recall: 0.5 }),
      model({ recall: 0.9 }),
    )
    render(<GateChecklist checks={checks} />)
    expect(screen.getByText(/Recall ≥ produksi ✗/)).toBeInTheDocument()
    expect(screen.getByText(/di bawah produksi/i)).toBeInTheDocument()
  })

  it('shows the "no baseline" note as a pass when there is no production model', () => {
    const checks = computePromotionGateChecks(model({ recall: 0.1 }), null)
    render(<GateChecklist checks={checks} />)
    expect(screen.getByText(/Recall ≥ produksi ✓/)).toBeInTheDocument()
    expect(screen.getByText(/promosi pertama/i)).toBeInTheDocument()
  })
})
