import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  buildListQuery,
  createDevice,
  describeApiError,
  disableDevice,
  listDevices,
  rotateDeviceCredential,
  updateDevice,
} from './api'

const ACCESS_TOKEN_KEY = 'frac_access_token'

const sampleDevice = {
  id: 'device-1',
  name: 'Pintu Lobby',
  door_group: 'lobby',
  status: 'ONLINE',
  last_heartbeat_at: '2026-08-30T08:00:00Z',
  credential_rotated_at: '2026-08-01T00:00:00Z',
  is_stale: false,
}

describe('buildListQuery', () => {
  it('applies default limit/offset with no filters', () => {
    expect(buildListQuery({})).toBe('limit=20&offset=0')
  })

  it('includes status and door_group when provided, and a custom limit/offset', () => {
    const query = buildListQuery({ status: 'OFFLINE', doorGroup: 'lobby', limit: 10, offset: 20 })
    const params = new URLSearchParams(query)
    expect(params.get('status')).toBe('OFFLINE')
    expect(params.get('door_group')).toBe('lobby')
    expect(params.get('limit')).toBe('10')
    expect(params.get('offset')).toBe('20')
  })

  it('omits status/door_group entirely when not given (no empty query params)', () => {
    const query = buildListQuery({})
    expect(query).not.toContain('status')
    expect(query).not.toContain('door_group')
  })
})

describe('authenticated device-management requests', () => {
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

  it('listDevices GETs /devices with the bearer token and query string', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ items: [sampleDevice], total: 1, limit: 20, offset: 0 }), {
        status: 200,
      }),
    )
    const result = await listDevices({ status: 'ONLINE' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/devices?')
    expect(url).toContain('status=ONLINE')
    expect(init.method ?? 'GET').toBe('GET')
    expect(init.headers.get('Authorization')).toBe('Bearer test-token')
    expect(result.total).toBe(1)
  })

  it('createDevice POSTs {name, door_group} to /devices and returns the one-time credential', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleDevice, credential: 'boot-cred-abc' }), {
        status: 201,
      }),
    )
    const result = await createDevice({ name: 'Pintu Lobby', door_group: 'lobby' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url.endsWith('/api/v1/devices')).toBe(true)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({ name: 'Pintu Lobby', door_group: 'lobby' })
    expect(result.credential).toBe('boot-cred-abc')
  })

  it('updateDevice PATCHes only the given fields to /devices/{id}', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleDevice, name: 'Pintu Lobby 2' }), { status: 200 }),
    )
    await updateDevice('device-1', { name: 'Pintu Lobby 2' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/devices/device-1')
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body)).toEqual({ name: 'Pintu Lobby 2' })
  })

  it('disableDevice DELETEs /devices/{id} (backend alias for status=DISABLED, not a hard delete)', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleDevice, status: 'DISABLED' }), { status: 200 }),
    )
    const result = await disableDevice('device-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/devices/device-1')
    expect(init.method).toBe('DELETE')
    expect(result.status).toBe('DISABLED')
  })

  it('rotateDeviceCredential POSTs /devices/{id}/rotate-credential and returns a new one-time credential', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...sampleDevice, credential: 'new-cred-xyz' }), {
        status: 200,
      }),
    )
    const result = await rotateDeviceCredential('device-1')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toContain('/api/v1/devices/device-1/rotate-credential')
    expect(init.method).toBe('POST')
    expect(result.credential).toBe('new-cred-xyz')
  })

  it('throws ApiError with status/body on a non-2xx response', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'name already exists' }), { status: 409 }),
    )
    await expect(createDevice({ name: 'Pintu Lobby', door_group: 'lobby' })).rejects.toMatchObject(
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
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ items: [sampleDevice], total: 1, limit: 20, offset: 0 }), {
          status: 200,
        }),
      )

    const result = await listDevices()

    expect(fetchMock).toHaveBeenCalledTimes(3)
    const refreshCall = fetchMock.mock.calls[1]
    expect(refreshCall[0]).toContain('/api/v1/auth/refresh')
    const retryCall = fetchMock.mock.calls[2]
    expect(retryCall[0]).toContain('/api/v1/devices')
    expect(retryCall[1].headers.get('Authorization')).toBe('Bearer fresh-token')
    expect(result.total).toBe(1)
    window.localStorage.removeItem('frac_refresh_token')
  })

  it('FE-02: propagates the original 401 when refresh also fails', async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: 'expired' }), { status: 401 }))
    await expect(listDevices()).rejects.toMatchObject({ status: 401 })
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
    expect(describeApiError(new ApiError('x', 409, null))).toMatch(/status device/i)
    expect(describeApiError(new ApiError('x', 404, null))).toMatch(/tidak ditemukan/i)
    expect(describeApiError(new ApiError('x', 403, null))).toMatch(/izin/i)
    expect(describeApiError(new ApiError('x', 422, null))).toMatch(/tidak valid/i)
  })

  it('falls back gracefully for a non-ApiError value', () => {
    expect(describeApiError(new Error('boom'))).toBe('boom')
    expect(describeApiError('not an error')).toMatch(/tak terduga/i)
  })
})
