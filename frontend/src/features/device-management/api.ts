import type {
  CreateDeviceBody,
  DeviceListResponse,
  DeviceResponse,
  DeviceStatus,
  DeviceWithCredential,
  UpdateDeviceBody,
} from './types'
import { getAccessToken, refreshAccessToken } from '../../lib/authToken'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

/**
 * Same reactive-refresh-on-401 pattern duplicated in every other feature's
 * `api.ts` (`user-management`, `enrollment-management`, `live-monitoring`)
 * — see `lib/authToken.ts::refreshAccessToken`'s docstring for why reactive
 * was chosen, and `live-monitoring/api.ts`'s docstring for why this copy
 * isn't consolidated into a shared helper yet.
 */
async function authFetch(
  path: string,
  init: RequestInit = {},
  isRetry = false,
): Promise<Response> {
  const token = getAccessToken()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })

  if (response.status === 401 && !isRetry) {
    const refreshed = await refreshAccessToken()
    if (refreshed) return authFetch(path, init, true)
  }

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      /* no JSON body */
    }
    throw new ApiError(
      `Request to ${path} failed with ${response.status}`,
      response.status,
      body,
    )
  }
  return response
}

export interface ListDevicesParams {
  status?: DeviceStatus
  doorGroup?: string
  limit?: number
  offset?: number
}

/** Exported separately from `listDevices` so the query-string building (the
 * part worth asserting on) is testable without mocking fetch. Mirrors
 * `enrollment-management/api.ts::buildListQuery`.
 *
 * Design note (reuse vs duplication with `live-monitoring/api.ts`): that
 * module already has its own `listDevices`/`buildDevicesQuery`, used only
 * for the small read-only S-40 device status panel. This feature needs full
 * CRUD (create/patch/disable/rotate) plus the one-time `credential` field on
 * create/rotate responses, which don't belong on live-monitoring's
 * `DeviceSummary` type at all. Rather than force both features to share one
 * generic module (which would mean either bloating live-monitoring's types
 * with fields it never uses, or a cross-feature import that couples S-40 to
 * S-60's CRUD surface), this keeps its own copy here — consistent with the
 * project's existing precedent of one `api.ts`/types copy per feature (see
 * `live-monitoring/types.ts`'s own docstring on this). `live-monitoring`
 * keeps using its existing `listDevices` unchanged. */
export function buildListQuery(params: ListDevicesParams): string {
  const search = new URLSearchParams()
  if (params.status) search.set('status', params.status)
  if (params.doorGroup) search.set('door_group', params.doorGroup)
  search.set('limit', String(params.limit ?? 20))
  search.set('offset', String(params.offset ?? 0))
  return search.toString()
}

export async function listDevices(params: ListDevicesParams = {}): Promise<DeviceListResponse> {
  const response = await authFetch(`/api/v1/devices?${buildListQuery(params)}`)
  return (await response.json()) as DeviceListResponse
}

/** `POST /devices` — ADMIN only (BE-09). Response includes the one-time
 * bootstrap `credential`. */
export async function createDevice(body: CreateDeviceBody): Promise<DeviceWithCredential> {
  const response = await authFetch('/api/v1/devices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as DeviceWithCredential
}

/** `PATCH /devices/{id}` — ADMIN only. Response never includes `credential`
 * (BE-09 contract: it only ever appears on the create/rotate responses). */
export async function updateDevice(id: string, body: UpdateDeviceBody): Promise<DeviceResponse> {
  const response = await authFetch(`/api/v1/devices/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as DeviceResponse
}

/** `DELETE /devices/{id}` — ADMIN only. Backend alias for setting
 * `status=DISABLED`, NOT a hard delete (mirrors
 * `user-management/api.ts::offboardUser`'s equivalent note for users). */
export async function disableDevice(id: string): Promise<DeviceResponse> {
  const response = await authFetch(`/api/v1/devices/${id}`, { method: 'DELETE' })
  return (await response.json()) as DeviceResponse
}

/** `POST /devices/{id}/rotate-credential` — ADMIN only. Invalidates the old
 * credential immediately and returns a new one-time `credential`, same
 * shape as the create response. */
export async function rotateDeviceCredential(id: string): Promise<DeviceWithCredential> {
  const response = await authFetch(`/api/v1/devices/${id}/rotate-credential`, {
    method: 'POST',
  })
  return (await response.json()) as DeviceWithCredential
}

export interface HeartbeatResult {
  status: DeviceStatus
  last_heartbeat_at: string | null
}

/**
 * `POST /devices/{id}/heartbeat` — the DEVICE-authenticated endpoint (BE-09),
 * called with a device credential (`<credential_id>.<secret>`, minted once at
 * create/rotate time), not a staff JWT. Deliberately does NOT go through
 * `authFetch`: that helper attaches the staff access token and reacts to a
 * 401 by refreshing/retrying the *staff* session, which is meaningless (and
 * would be actively wrong) for a device-credential call — a bad/expired
 * device credential should just fail, not trigger a staff token refresh.
 * Mirrors `scripts/device_simulator.py::send_heartbeat` — this is the
 * in-browser equivalent of that CLI simulator, used by
 * `ActivateDeviceDialog` so an operator can bring a device ONLINE from the
 * UI without physical hardware or a terminal.
 */
export async function sendDeviceHeartbeat(
  deviceId: string,
  credential: string,
): Promise<HeartbeatResult> {
  const response = await fetch(`${API_BASE_URL}/api/v1/devices/${deviceId}/heartbeat`, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${credential}`,
    },
  })

  if (!response.ok) {
    let body: unknown = null
    try {
      body = await response.json()
    } catch {
      /* no JSON body */
    }
    throw new ApiError(
      `Heartbeat request for device ${deviceId} failed with ${response.status}`,
      response.status,
      body,
    )
  }
  return (await response.json()) as HeartbeatResult
}

interface ProblemBody {
  detail?: string
}

function problemDetail(body: unknown): string | null {
  if (body && typeof body === 'object' && typeof (body as ProblemBody).detail === 'string') {
    return (body as ProblemBody).detail as string
  }
  return null
}

/** Mirrors `user-management/api.ts::describeApiError` — same per-status
 * Indonesian copy, falling back to the backend's RFC 9457 `detail` when
 * present. */
export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = problemDetail(error.body)
    switch (error.status) {
      case 401:
        return detail ?? 'Sesi kamu telah berakhir. Silakan login ulang.'
      case 403:
        return detail ?? 'Kamu tidak memiliki izin untuk melakukan aksi ini.'
      case 404:
        return detail ?? 'Data device yang dimaksud tidak ditemukan.'
      case 409:
        return detail ?? 'Aksi ini tidak bisa dilakukan pada status device saat ini.'
      case 422:
        return detail ?? 'Data yang dikirim tidak valid, silakan periksa kembali.'
      default:
        return detail ?? `Terjadi kesalahan tak terduga (status ${error.status}).`
    }
  }
  if (error instanceof Error) return error.message
  return 'Terjadi kesalahan tak terduga.'
}
