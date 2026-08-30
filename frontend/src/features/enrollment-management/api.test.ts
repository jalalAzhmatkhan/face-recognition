import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  buildListQuery,
  cancelEnrollment,
  createEnrollment,
  describeApiError,
  getEnrollment,
  grantConsent,
  listEnrollments,
  revokeEnrollment,
  startRecapture,
} from './api'

const ACCESS_TOKEN_KEY = 'frac_access_token'

const sampleEnrollment = {
  id: 'enroll-1',
  user_id: 'user-1',
  state: 'CREATED',
  qc_report: null,
  created_by: 'staff-1',
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z',
}

describe('buildListQuery', () => {
  it('applies default limit/offset with no filters', () => {
    expect(buildListQuery({})).toBe('limit=20&offset=0')
  })

  it('includes user_id and state when provided, and a custom limit/offset', () => {
    const query = buildListQuery({
      userId: 'user-1',
      state: 'ENROLLED',
      limit: 10,
      offset: 20,
    })
    const params = new URLSearchParams(query)
    expect(params.get('user_id')).toBe('user-1')
    expect(params.get('state')).toBe('ENROLLED')
    expect(params.get('limit')).toBe('10')
    expect(params.get('offset')).toBe('20')
  })

  it('omits user_id/state entirely when not given (no empty query params)', () => {
    const query = buildListQuery({})
    expect(query).not.toContain('user_id')
    expect(query).not.toContain('state')
  })
})

describe('authenticated enrollment-management requests', () => {
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

  it('listEnrollments GETs /enrollments with the bearer token and query string', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ items: [sampleEnrollment], total: 1, limit: 20, offset: 0 }),
        { status: 200 },
      ),
    )
    const result = await listEnrollments({ state: 'CREATED' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments?')
    expect(url).toContain('state=CREATED')
    expect(init.method ?? 'GET').toBe('GET')
    expect(init.headers.get('Authorization')).toBe('Bearer test-token')
    expect(result.total).toBe(1)
  })

  it('getEnrollment GETs /enrollments/{id}', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(sampleEnrollment), { status: 200 }))
    await getEnrollment('enroll-1')
    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments/enroll-1')
    expect(url).not.toContain('/consent')
  })

  it('createEnrollment POSTs {user_id} to /enrollments', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(sampleEnrollment), { status: 201 }))
    await createEnrollment('user-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments')
    expect(url.endsWith('/enrollments')).toBe(true)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ user_id: 'user-1' })
  })

  it('grantConsent POSTs {consent_version} to /enrollments/{id}/consent', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleEnrollment, state: 'CONSENTED' }), { status: 200 }),
    )
    await grantConsent('enroll-1', 'v1.0')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments/enroll-1/consent')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ consent_version: 'v1.0' })
  })

  it('startRecapture POSTs {target_state: "CAPTURING"} to /enrollments/{id}/transition', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleEnrollment, state: 'CAPTURING' }), { status: 200 }),
    )
    await startRecapture('enroll-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments/enroll-1/transition')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ target_state: 'CAPTURING' })
  })

  it('cancelEnrollment POSTs to /enrollments/{id}/cancel with no body', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleEnrollment, state: 'CANCELLED' }), { status: 200 }),
    )
    await cancelEnrollment('enroll-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments/enroll-1/cancel')
    expect(init.method).toBe('POST')
    expect(init.body).toBeUndefined()
  })

  it('revokeEnrollment DELETEs /enrollments/{id}', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ id: 'enroll-1', state: 'REVOKED' }), { status: 202 }),
    )
    const result = await revokeEnrollment('enroll-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/enrollments/enroll-1')
    expect(init.method).toBe('DELETE')
    expect(result.state).toBe('REVOKED')
  })

  it('throws ApiError with status/body on a non-2xx response', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Role not permitted' }), { status: 403 }),
    )
    await expect(cancelEnrollment('enroll-1')).rejects.toMatchObject({
      status: 403,
    })
  })
})

describe('describeApiError', () => {
  it('surfaces the backend detail message for 409/404/403/422', () => {
    expect(
      describeApiError(new ApiError('x', 409, { detail: 'Conflict detail' })),
    ).toBe('Conflict detail')
    expect(
      describeApiError(new ApiError('x', 404, { detail: 'Not found detail' })),
    ).toBe('Not found detail')
    expect(
      describeApiError(new ApiError('x', 403, { detail: 'Forbidden detail' })),
    ).toBe('Forbidden detail')
    expect(
      describeApiError(new ApiError('x', 422, { detail: 'Invalid detail' })),
    ).toBe('Invalid detail')
  })

  it('falls back to a generic Indonesian message per status when there is no detail', () => {
    expect(describeApiError(new ApiError('x', 409, null))).toMatch(/status sesi/i)
    expect(describeApiError(new ApiError('x', 404, null))).toMatch(/tidak ditemukan/i)
    expect(describeApiError(new ApiError('x', 403, null))).toMatch(/izin/i)
    expect(describeApiError(new ApiError('x', 422, null))).toMatch(/tidak valid/i)
  })

  it('falls back gracefully for a non-ApiError value', () => {
    expect(describeApiError(new Error('boom'))).toBe('boom')
    expect(describeApiError('not an error')).toMatch(/tak terduga/i)
  })
})
