import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  buildAccessEventStreamUrl,
  buildAccessEventsQuery,
  buildDevicesQuery,
  describeApiError,
  fetchTodaySummary,
  listAccessEvents,
  listDevices,
  startOfTodayIso,
} from './api'

const ACCESS_TOKEN_KEY = 'frac_access_token'

describe('buildAccessEventsQuery', () => {
  it('applies default limit/offset with no filters', () => {
    expect(buildAccessEventsQuery({})).toBe('limit=50&offset=0')
  })

  it('includes device_id/decision/from/to when provided', () => {
    const query = buildAccessEventsQuery({
      deviceId: 'device-1',
      decision: 'DENIED',
      from: '2026-08-30T00:00:00.000Z',
      to: '2026-08-30T23:59:59.000Z',
      limit: 10,
      offset: 5,
    })
    const params = new URLSearchParams(query)
    expect(params.get('device_id')).toBe('device-1')
    expect(params.get('decision')).toBe('DENIED')
    expect(params.get('from')).toBe('2026-08-30T00:00:00.000Z')
    expect(params.get('to')).toBe('2026-08-30T23:59:59.000Z')
    expect(params.get('limit')).toBe('10')
    expect(params.get('offset')).toBe('5')
  })
})

describe('buildDevicesQuery', () => {
  it('applies default limit/offset with no filters', () => {
    expect(buildDevicesQuery({})).toBe('limit=100&offset=0')
  })

  it('includes status and door_group when provided', () => {
    const params = new URLSearchParams(buildDevicesQuery({ status: 'ONLINE', doorGroup: 'lobby' }))
    expect(params.get('status')).toBe('ONLINE')
    expect(params.get('door_group')).toBe('lobby')
  })
})

describe('buildAccessEventStreamUrl', () => {
  it('has no query string when no filters given', () => {
    expect(buildAccessEventStreamUrl({})).toMatch(/\/api\/v1\/stream\/access-events$/)
  })

  it('includes device_id and decision when given', () => {
    const url = buildAccessEventStreamUrl({ deviceId: 'device-1', decision: 'GRANTED' })
    expect(url).toContain('device_id=device-1')
    expect(url).toContain('decision=GRANTED')
  })
})

describe('startOfTodayIso', () => {
  it('returns midnight local time for the given date', () => {
    const now = new Date('2026-08-30T15:42:00')
    const iso = startOfTodayIso(now)
    const parsed = new Date(iso)
    expect(parsed.getHours()).toBe(0)
    expect(parsed.getMinutes()).toBe(0)
    expect(parsed.getSeconds()).toBe(0)
  })
})

describe('authenticated live-monitoring requests', () => {
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

  it('listAccessEvents GETs /access-events with the bearer token', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 3, limit: 1, offset: 0 }), { status: 200 }),
    )
    const result = await listAccessEvents({ decision: 'GRANTED' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/access-events?')
    expect(url).toContain('decision=GRANTED')
    expect(init.headers.get('Authorization')).toBe('Bearer test-token')
    expect(result.total).toBe(3)
  })

  it('listDevices GETs /devices with the bearer token', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, limit: 100, offset: 0 }), {
        status: 200,
      }),
    )
    await listDevices()
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/devices?')
    expect(init.headers.get('Authorization')).toBe('Bearer test-token')
  })

  it('fetchTodaySummary issues one request per decision and sums totals', async () => {
    fetchMock.mockImplementation((url: string) => {
      const params = new URLSearchParams(url.split('?')[1])
      const decision = params.get('decision')
      const totals: Record<string, number> = {
        GRANTED: 10,
        DENIED: 2,
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
    const summary = await fetchTodaySummary()
    expect(fetchMock).toHaveBeenCalledTimes(4)
    expect(summary).toEqual({ GRANTED: 10, DENIED: 2, UNKNOWN: 1, SPOOF_SUSPECTED: 0 })
  })

  it('throws ApiError with status/body on a non-2xx response', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Role not permitted' }), { status: 403 }),
    )
    await expect(listDevices()).rejects.toMatchObject({ status: 403 })
  })
})

describe('describeApiError', () => {
  it('surfaces the backend detail message for 403', () => {
    expect(describeApiError(new ApiError('x', 403, { detail: 'Forbidden detail' }))).toBe(
      'Forbidden detail',
    )
  })

  it('falls back to a generic Indonesian message when there is no detail', () => {
    expect(describeApiError(new ApiError('x', 403, null))).toMatch(/izin/i)
    expect(describeApiError(new ApiError('x', 500, null))).toMatch(/status 500/i)
  })

  it('falls back gracefully for a non-ApiError value', () => {
    expect(describeApiError(new Error('boom'))).toBe('boom')
    expect(describeApiError('not an error')).toMatch(/tak terduga/i)
  })
})
