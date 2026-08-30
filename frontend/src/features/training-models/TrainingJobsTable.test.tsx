import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import TrainingJobsTable from './TrainingJobsTable'
import type { TrainingJobResponse } from './types'

afterEach(() => cleanup())

function job(overrides: Partial<TrainingJobResponse>): TrainingJobResponse {
  return {
    id: 'job-1',
    model_version: 'facenet-v2',
    benchmark_id: 'snapshot-1',
    status: 'PENDING',
    triggered_by: 'staff-1',
    created_at: '2026-08-30T08:00:00Z',
    completed_at: null,
    error_message: null,
    mlflow_run_id: null,
    ...overrides,
  }
}

function renderTable(jobs: TrainingJobResponse[]) {
  return render(
    <MemoryRouter>
      <TrainingJobsTable jobs={jobs} />
    </MemoryRouter>,
  )
}

describe('TrainingJobsTable', () => {
  it('shows an honest empty state when there are no jobs', () => {
    renderTable([])
    expect(screen.getByText(/belum ada job training/i)).toBeInTheDocument()
  })

  it('renders one row per job with a Detail link to /models/jobs/:id', () => {
    renderTable([
      job({ id: 'job-a', model_version: 'facenet-v1' }),
      job({ id: 'job-b', model_version: 'facenet-v2', status: 'SUCCEEDED' }),
    ])

    const detailLinks = screen.getAllByRole('link', { name: 'Detail' })
    expect(detailLinks).toHaveLength(2)
    expect(detailLinks[0]).toHaveAttribute('href', '/models/jobs/job-a')
    expect(detailLinks[1]).toHaveAttribute('href', '/models/jobs/job-b')
  })

  it('shows a dash for a null model_version instead of crashing', () => {
    renderTable([job({ model_version: null })])
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})
