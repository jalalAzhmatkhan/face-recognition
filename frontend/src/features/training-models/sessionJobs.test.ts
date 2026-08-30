import { afterEach, describe, expect, it } from 'vitest'
import { addSessionTrainingJob, listSessionTrainingJobs } from './sessionJobs'

const STORAGE_KEY = 'frac_training_jobs_session'

afterEach(() => {
  window.localStorage.removeItem(STORAGE_KEY)
})

describe('listSessionTrainingJobs', () => {
  it('returns an empty array when nothing is stored', () => {
    expect(listSessionTrainingJobs()).toEqual([])
  })

  it('returns an empty array and does not throw for corrupted JSON', () => {
    window.localStorage.setItem(STORAGE_KEY, '{not json')
    expect(listSessionTrainingJobs()).toEqual([])
  })

  it('drops malformed entries but keeps well-formed ones', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: 'job-1', model_version: 'v1', benchmark_id: 'b1', created_at: '2026-08-30T08:00:00Z' },
        { id: 'job-2' /* missing fields */ },
        'not-an-object',
        null,
      ]),
    )
    const jobs = listSessionTrainingJobs()
    expect(jobs).toHaveLength(1)
    expect(jobs[0].id).toBe('job-1')
  })

  it('sorts newest-first by created_at', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify([
        { id: 'older', model_version: 'v1', benchmark_id: 'b1', created_at: '2026-08-01T00:00:00Z' },
        { id: 'newer', model_version: 'v1', benchmark_id: 'b1', created_at: '2026-08-30T00:00:00Z' },
      ]),
    )
    const jobs = listSessionTrainingJobs()
    expect(jobs.map((job) => job.id)).toEqual(['newer', 'older'])
  })
})

describe('addSessionTrainingJob', () => {
  it('persists a new job so it shows up in listSessionTrainingJobs', () => {
    addSessionTrainingJob({
      id: 'job-1',
      model_version: 'v1',
      benchmark_id: 'b1',
      created_at: '2026-08-30T08:00:00Z',
    })
    expect(listSessionTrainingJobs()).toHaveLength(1)
  })

  it('replaces an existing entry with the same id rather than duplicating it', () => {
    addSessionTrainingJob({
      id: 'job-1',
      model_version: 'v1',
      benchmark_id: 'b1',
      created_at: '2026-08-30T08:00:00Z',
    })
    addSessionTrainingJob({
      id: 'job-1',
      model_version: 'v2',
      benchmark_id: 'b2',
      created_at: '2026-08-30T09:00:00Z',
    })
    const jobs = listSessionTrainingJobs()
    expect(jobs).toHaveLength(1)
    expect(jobs[0].model_version).toBe('v2')
  })
})
