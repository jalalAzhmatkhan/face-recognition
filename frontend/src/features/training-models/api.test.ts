import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  buildModelsQuery,
  buildTrainingJobsQuery,
  createTrainingJob,
  describeApiError,
  getTrainingJob,
  listModels,
  listTrainingJobs,
  promoteModel,
  promotionGateReasons,
} from './api'

const ACCESS_TOKEN_KEY = 'frac_access_token'

const sampleModel = {
  version: 'facenet-v2',
  mlflow_run_id: 'run-1',
  stage: 'CANDIDATE',
  recall: 0.95,
  f1: 0.9,
  precision: 0.88,
  latency_ms_p95: 120,
  promoted_by: null,
  promoted_at: null,
}

const sampleJob = {
  id: 'job-1',
  model_version: 'facenet-v2',
  benchmark_id: 'snapshot-1',
  status: 'PENDING',
  triggered_by: 'staff-1',
  created_at: '2026-08-30T08:00:00Z',
  completed_at: null,
  error_message: null,
  mlflow_run_id: null,
}

describe('buildModelsQuery', () => {
  it('returns an empty string when no stage filter is given', () => {
    expect(buildModelsQuery({})).toBe('')
  })

  it('includes stage when provided', () => {
    expect(buildModelsQuery({ stage: 'PRODUCTION' })).toBe('stage=PRODUCTION')
  })
})

describe('buildTrainingJobsQuery', () => {
  it('always includes limit/offset with defaults', () => {
    expect(buildTrainingJobsQuery({})).toBe('limit=20&offset=0')
  })

  it('includes status and model_version when provided', () => {
    expect(buildTrainingJobsQuery({ status: 'FAILED', model_version: 'facenet-v2' })).toBe(
      'status=FAILED&model_version=facenet-v2&limit=20&offset=0',
    )
  })

  it('honors an explicit limit/offset', () => {
    expect(buildTrainingJobsQuery({ limit: 5, offset: 10 })).toBe('limit=5&offset=10')
  })
})

describe('authenticated training-models requests', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, 'test-token')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    vi.unstubAllGlobals()
  })

  it('listModels GETs /models without a query string when no stage is given', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ items: [sampleModel] }), { status: 200 }))
    const result = await listModels()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.endsWith('/api/v1/models')).toBe(true)
    expect(init.headers.get('Authorization')).toBe('Bearer test-token')
    expect(result.items).toHaveLength(1)
  })

  it('listModels GETs /models?stage=... when a stage filter is given', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }))
    await listModels({ stage: 'PRODUCTION' })
    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/models?stage=PRODUCTION')
  })

  it('getTrainingJob GETs /training/jobs/{id}', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(sampleJob), { status: 200 }))
    const result = await getTrainingJob('job-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/training/jobs/job-1')
    expect(init.method ?? 'GET').toBe('GET')
    expect(result.status).toBe('PENDING')
  })

  it('listTrainingJobs GETs /training/jobs with the built query string', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [sampleJob], total: 1, limit: 20, offset: 0 }), {
        status: 200,
      }),
    )
    const result = await listTrainingJobs({ status: 'PENDING' })
    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/training/jobs?status=PENDING&limit=20&offset=0')
    expect(result.total).toBe(1)
    expect(result.items).toHaveLength(1)
  })

  it('createTrainingJob POSTs {model_version, benchmark_id} to /training/jobs', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(sampleJob), { status: 201 }))
    const result = await createTrainingJob({ model_version: 'facenet-v2', benchmark_id: 'snapshot-1' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.endsWith('/api/v1/training/jobs')).toBe(true)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ model_version: 'facenet-v2', benchmark_id: 'snapshot-1' })
    expect(result.id).toBe('job-1')
  })

  it('promoteModel POSTs {confirm} to /models/{version}/promote', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          version: 'facenet-v2',
          stage: 'PRODUCTION',
          promoted_by: 'staff-1',
          promoted_at: '2026-08-30T09:00:00Z',
        }),
        { status: 200 },
      ),
    )
    const result = await promoteModel('facenet-v2', { confirm: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/models/facenet-v2/promote')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ confirm: true })
    expect(result.stage).toBe('PRODUCTION')
  })

  it('FE-02: on a 401, refreshes once and retries the original request', async () => {
    window.localStorage.setItem('frac_refresh_token', 'ref-1')
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'fresh-token' }), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ items: [] }), { status: 200 }))

    const result = await listModels()

    expect(fetchMock).toHaveBeenCalledTimes(3)
    const retryCall = fetchMock.mock.calls[2]
    expect(retryCall[1].headers.get('Authorization')).toBe('Bearer fresh-token')
    expect(result.items).toEqual([])
    window.localStorage.removeItem('frac_refresh_token')
  })
})

describe('promotionGateReasons', () => {
  it('extracts the reasons array from a 409 promotion-gate error', () => {
    const error = new ApiError('x', 409, {
      detail: 'Candidate recall 0.10 is below current production recall 0.90; latency too high',
      reasons: ['Candidate recall 0.10 is below current production recall 0.90', 'latency too high'],
    })
    expect(promotionGateReasons(error)).toEqual([
      'Candidate recall 0.10 is below current production recall 0.90',
      'latency too high',
    ])
  })

  it('returns null for a 409 with no reasons array', () => {
    expect(promotionGateReasons(new ApiError('x', 409, { detail: 'conflict' }))).toBeNull()
  })

  it('returns null for a non-409 error even if it happens to carry a reasons array', () => {
    expect(promotionGateReasons(new ApiError('x', 422, { reasons: ['x'] }))).toBeNull()
  })

  it('returns null for a non-ApiError value', () => {
    expect(promotionGateReasons(new Error('boom'))).toBeNull()
  })

  it('returns null when reasons is present but not an array of strings', () => {
    expect(promotionGateReasons(new ApiError('x', 409, { reasons: [1, 2] }))).toBeNull()
    expect(promotionGateReasons(new ApiError('x', 409, { reasons: 'not-an-array' }))).toBeNull()
  })
})

describe('describeApiError', () => {
  it('surfaces the backend detail message for 409/404/403/422', () => {
    expect(describeApiError(new ApiError('x', 409, { detail: 'Gate failed' }))).toBe('Gate failed')
    expect(describeApiError(new ApiError('x', 404, { detail: 'Not found' }))).toBe('Not found')
    expect(describeApiError(new ApiError('x', 403, { detail: 'Forbidden' }))).toBe('Forbidden')
    expect(describeApiError(new ApiError('x', 422, { detail: 'Invalid' }))).toBe('Invalid')
  })

  it('falls back to a generic Indonesian message per status when there is no detail', () => {
    expect(describeApiError(new ApiError('x', 409, null))).toMatch(/status/i)
    expect(describeApiError(new ApiError('x', 404, null))).toMatch(/tidak ditemukan/i)
    expect(describeApiError(new ApiError('x', 403, null))).toMatch(/izin/i)
    expect(describeApiError(new ApiError('x', 422, null))).toMatch(/tidak valid/i)
  })

  it('falls back gracefully for a non-ApiError value', () => {
    expect(describeApiError(new Error('boom'))).toBe('boom')
    expect(describeApiError('not an error')).toMatch(/tak terduga/i)
  })
})
