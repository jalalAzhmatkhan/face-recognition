import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  dateKey,
  describeApiError,
  fetchDailyDecisionCounts,
  fetchEnrollmentFunnel,
  fetchProductionModel,
  fetchRecentAccessEventSample,
  fetchTodayCounts,
  startOfDayIso,
} from './api'

const ACCESS_TOKEN_KEY = 'frac_access_token'

describe('startOfDayIso', () => {
  it('returns midnight local time N days before now', () => {
    const now = new Date('2026-08-31T15:42:00')
    const today = new Date(startOfDayIso(0, now))
    expect(today.getHours()).toBe(0)
    expect(today.getDate()).toBe(31)

    const yesterday = new Date(startOfDayIso(1, now))
    expect(yesterday.getDate()).toBe(30)
  })
})

describe('dateKey', () => {
  it('formats as YYYY-MM-DD for the given offset', () => {
    const now = new Date('2026-08-05T10:00:00')
    expect(dateKey(0, now)).toBe('2026-08-05')
    expect(dateKey(5, now)).toBe('2026-07-31')
  })
})

describe('authenticated dashboard requests', () => {
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

  it('fetchTodayCounts issues one request per decision and reads totals', async () => {
    fetchMock.mockImplementation((url: string) => {
      const params = new URLSearchParams(url.split('?')[1])
      const decision = params.get('decision')
      const totals: Record<string, number> = {
        GRANTED: 8,
        DENIED: 1,
        UNKNOWN: 1,
        SPOOF_SUSPECTED: 0,
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({ items: [], total: totals[decision ?? ''] ?? 0, limit: 1, offset: 0 }),
          { status: 200 },
        ),
      )
    })
    const counts = await fetchTodayCounts()
    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(counts).toEqual({ GRANTED: 8, DENIED: 1, UNKNOWN: 1, SPOOF_SUSPECTED: 0 })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/access-events?')
    expect(init.headers.get('Authorization')).toBe('Bearer test-token')
  })

  it('fetchDailyDecisionCounts issues 2 requests per day, oldest first', async () => {
    fetchMock.mockImplementation(
      () =>
        new Response(JSON.stringify({ items: [], total: 3, limit: 1, offset: 0 }), {
          status: 200,
        }),
    )
    const rows = await fetchDailyDecisionCounts(3, new Date('2026-08-05T12:00:00'))
    expect(fetchMock).toHaveBeenCalledTimes(6)
    expect(rows.map((r) => r.dateIso)).toEqual(['2026-08-03', '2026-08-04', '2026-08-05'])
    expect(rows[0]).toEqual({ dateIso: '2026-08-03', granted: 3, denied: 3 })
  })

  it('fetchProductionModel returns the first item or null', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              version: 'adaface-v2',
              mlflow_run_id: 'run-1',
              stage: 'PRODUCTION',
              recall: 0.99,
              f1: 0.98,
              precision: 0.97,
              latency_ms_p95: 210,
              promoted_by: 'staff-1',
              promoted_at: '2026-08-01T00:00:00Z',
            },
          ],
        }),
        { status: 200 },
      ),
    )
    const model = await fetchProductionModel()
    expect(model?.version).toBe('adaface-v2')
    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/models?stage=PRODUCTION')
  })

  it('fetchProductionModel returns null when there is no production model', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ items: [] }), { status: 200 }))
    expect(await fetchProductionModel()).toBeNull()
  })

  it('fetchEnrollmentFunnel issues one request per happy-path state', async () => {
    fetchMock.mockImplementation((url: string) => {
      const params = new URLSearchParams(url.split('?')[1])
      const state = params.get('state')
      const totals: Record<string, number> = { CREATED: 10, ENROLLED: 4 }
      return Promise.resolve(
        new Response(
          JSON.stringify({ items: [], total: totals[state ?? ''] ?? 0, limit: 1, offset: 0 }),
          { status: 200 },
        ),
      )
    })
    const stages = await fetchEnrollmentFunnel()
    expect(fetchMock).toHaveBeenCalledTimes(8)
    expect(stages[0]).toEqual({ state: 'CREATED', count: 10 })
    expect(stages[stages.length - 1]).toEqual({ state: 'ENROLLED', count: 4 })
    expect(stages.some((s) => s.state === 'CANCELLED')).toBe(false)
    expect(stages.some((s) => s.state === 'REVOKED')).toBe(false)
  })

  it('fetchRecentAccessEventSample requests a bounded page with no decision filter', async () => {
    const items = [
      {
        id: 'evt-1',
        decision: 'DENIED',
        reject_stage: 'liveness',
        condition_flags: { dark: true },
        device_class: 'door_entry',
      },
    ]
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items, total: 1, limit: 200, offset: 0 }), { status: 200 }),
    )
    const result = await fetchRecentAccessEventSample()
    expect(result).toEqual(items)
    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/access-events?limit=200')
    expect(url).not.toContain('decision=')
  })

  it('throws ApiError with status/body on a non-2xx response', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Role not permitted' }), { status: 403 }),
    )
    await expect(fetchProductionModel()).rejects.toMatchObject({ status: 403 })
  })
})

describe('describeApiError', () => {
  it('surfaces the backend detail message for 403', () => {
    expect(describeApiError(new ApiError('x', 403, { detail: 'Forbidden detail' }))).toBe(
      'Forbidden detail',
    )
  })

  it('falls back to a generic Indonesian message when there is no detail', () => {
    expect(describeApiError(new ApiError('x', 500, null))).toMatch(/status 500/i)
  })

  it('falls back gracefully for a non-ApiError value', () => {
    expect(describeApiError(new Error('boom'))).toBe('boom')
    expect(describeApiError('not an error')).toMatch(/tak terduga/i)
  })
})
