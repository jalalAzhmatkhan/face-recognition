import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  buildListQuery,
  createUser,
  describeApiError,
  getUser,
  listUsers,
  offboardUser,
  setUserStatus,
  updateUser,
} from './api'

const ACCESS_TOKEN_KEY = 'frac_access_token'

const sampleUser = {
  id: 'user-1',
  external_ref: 'EMP-001',
  full_name: 'Budi Santoso',
  status: 'ACTIVE',
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z',
}

describe('buildListQuery', () => {
  it('applies default limit/offset with no filters', () => {
    expect(buildListQuery({})).toBe('limit=20&offset=0')
  })

  it('includes status when provided, and a custom limit/offset', () => {
    const query = buildListQuery({ status: 'SUSPENDED', limit: 10, offset: 20 })
    const params = new URLSearchParams(query)
    expect(params.get('status')).toBe('SUSPENDED')
    expect(params.get('limit')).toBe('10')
    expect(params.get('offset')).toBe('20')
  })

  it('omits status entirely when not given (no empty query param)', () => {
    expect(buildListQuery({})).not.toContain('status')
  })
})

describe('authenticated user-management requests', () => {
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

  it('listUsers GETs /users with the bearer token and query string', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [sampleUser], total: 1, limit: 20, offset: 0 }), {
        status: 200,
      }),
    )
    const result = await listUsers({ status: 'ACTIVE' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/users?')
    expect(url).toContain('status=ACTIVE')
    expect(init.method ?? 'GET').toBe('GET')
    expect(init.headers.get('Authorization')).toBe('Bearer test-token')
    expect(result.total).toBe(1)
  })

  it('getUser GETs /users/{id}', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(sampleUser), { status: 200 }))
    await getUser('user-1')
    const [url] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/users/user-1')
  })

  it('createUser POSTs {external_ref, full_name} to /users', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(sampleUser), { status: 201 }))
    await createUser({ external_ref: 'EMP-001', full_name: 'Budi Santoso' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.endsWith('/api/v1/users')).toBe(true)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ external_ref: 'EMP-001', full_name: 'Budi Santoso' })
  })

  it('updateUser PATCHes only the given fields to /users/{id}', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleUser, full_name: 'Budi S.' }), { status: 200 }),
    )
    await updateUser('user-1', { full_name: 'Budi S.' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/users/user-1')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ full_name: 'Budi S.' })
  })

  it('setUserStatus PATCHes {status} to /users/{id}', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleUser, status: 'SUSPENDED' }), { status: 200 }),
    )
    await setUserStatus('user-1', 'SUSPENDED')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/users/user-1')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ status: 'SUSPENDED' })
  })

  it('offboardUser DELETEs /users/{id} (backend alias for status=OFFBOARDED, not a hard delete)', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleUser, status: 'OFFBOARDED' }), { status: 200 }),
    )
    const result = await offboardUser('user-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/users/user-1')
    expect(init.method).toBe('DELETE')
    expect(result.status).toBe('OFFBOARDED')
  })

  it('throws ApiError with status/body on a non-2xx response', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'external_ref already exists' }), { status: 409 }),
    )
    await expect(createUser({ external_ref: 'EMP-001', full_name: 'Budi' })).rejects.toMatchObject(
      { status: 409 },
    )
  })

  it('FE-02: on a 401, refreshes once and retries the original request', async () => {
    window.localStorage.setItem('frac_refresh_token', 'ref-1')
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'fresh-token' }), { status: 200 }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify(sampleUser), { status: 200 }))

    const result = await getUser('user-1')

    expect(fetchMock).toHaveBeenCalledTimes(3)
    const refreshCall = fetchMock.mock.calls[1]
    expect(refreshCall[0]).toContain('/api/v1/auth/refresh')
    const retryCall = fetchMock.mock.calls[2]
    expect(retryCall[0]).toContain('/api/v1/users/user-1')
    expect(retryCall[1].headers.get('Authorization')).toBe('Bearer fresh-token')
    expect(result.id).toBe('user-1')
    window.localStorage.removeItem('frac_refresh_token')
  })

  it('FE-02: propagates the original 401 when refresh also fails', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }))
    await expect(getUser('user-1')).rejects.toMatchObject({ status: 401 })
  })
})

describe('describeApiError', () => {
  it('surfaces the backend detail message for 409/404/403/422', () => {
    expect(describeApiError(new ApiError('x', 409, { detail: 'Duplicate detail' }))).toBe(
      'Duplicate detail',
    )
    expect(describeApiError(new ApiError('x', 404, { detail: 'Not found detail' }))).toBe(
      'Not found detail',
    )
    expect(describeApiError(new ApiError('x', 403, { detail: 'Forbidden detail' }))).toBe(
      'Forbidden detail',
    )
    expect(describeApiError(new ApiError('x', 422, { detail: 'Invalid detail' }))).toBe(
      'Invalid detail',
    )
  })

  it('falls back to a generic Indonesian message per status when there is no detail', () => {
    expect(describeApiError(new ApiError('x', 409, null))).toMatch(/external ref/i)
    expect(describeApiError(new ApiError('x', 404, null))).toMatch(/tidak ditemukan/i)
    expect(describeApiError(new ApiError('x', 403, null))).toMatch(/izin/i)
    expect(describeApiError(new ApiError('x', 422, null))).toMatch(/tidak valid/i)
  })

  it('falls back gracefully for a non-ApiError value', () => {
    expect(describeApiError(new Error('boom'))).toBe('boom')
    expect(describeApiError('not an error')).toMatch(/tak terduga/i)
  })
})
