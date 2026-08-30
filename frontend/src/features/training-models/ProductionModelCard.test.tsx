import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import ProductionModelCard from './ProductionModelCard'
import type { ModelVersionResponse } from './types'

afterEach(() => cleanup())

const productionModel: ModelVersionResponse = {
  version: 'facenet-v2',
  mlflow_run_id: 'run-1',
  stage: 'PRODUCTION',
  recall: 0.95,
  f1: 0.9,
  precision: 0.88,
  latency_ms_p95: 120,
  promoted_by: 'staff-1',
  promoted_at: '2026-08-30T09:00:00Z',
}

describe('ProductionModelCard', () => {
  it('shows the honest empty state when there is no production model', () => {
    render(<ProductionModelCard model={null} />)
    expect(
      screen.getByText(/belum ada model produksi.*pretrained bawaan/i),
    ).toBeInTheDocument()
    expect(screen.queryByText('facenet-v2')).not.toBeInTheDocument()
  })

  it('renders version, recall, and other metrics when a production model exists', () => {
    render(<ProductionModelCard model={productionModel} />)
    expect(screen.getByText('facenet-v2')).toBeInTheDocument()
    expect(screen.getByText('0.9500')).toBeInTheDocument()
    expect(screen.getByText('0.9000')).toBeInTheDocument()
    expect(screen.getByText('0.8800')).toBeInTheDocument()
    expect(screen.getByText('120 ms')).toBeInTheDocument()
  })
})
