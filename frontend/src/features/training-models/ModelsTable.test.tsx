import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ModelsTable from './ModelsTable'
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

function renderTable(models: ModelVersionResponse[]) {
  return render(
    <MemoryRouter>
      <ModelsTable models={models} />
    </MemoryRouter>,
  )
}

describe('ModelsTable', () => {
  it('shows the honest empty state when there are no models', () => {
    renderTable([])
    expect(screen.getByRole('heading', { name: 'Belum Ada Model' })).toBeInTheDocument()
  })

  it('shows a "Review" link only for CANDIDATE rows, not PRODUCTION/RETIRED', () => {
    renderTable([
      model({ version: 'candidate-1', stage: 'CANDIDATE' }),
      model({ version: 'production-1', stage: 'PRODUCTION' }),
      model({ version: 'retired-1', stage: 'RETIRED' }),
    ])

    const reviewLinks = screen.getAllByRole('link', { name: 'Review' })
    expect(reviewLinks).toHaveLength(1)
    expect(reviewLinks[0]).toHaveAttribute('href', '/models/candidate-1/promote')
  })
})
