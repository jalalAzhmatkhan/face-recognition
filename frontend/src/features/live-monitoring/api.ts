import type {
  AccessDecision,
  AccessEventListResponse,
  DeviceListResponse,
  TodaySummary,
} from './types'
import { ACCESS_DECISIONS, EMPTY_TODAY_SUMMARY } from './types'
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
 * Same reactive-refresh-on-401 pattern as `enrollment-management/api.ts` and
 * `user-management/api.ts` (see `lib/authToken.ts::refreshAccessToken` for
 * why reactive was chosen). Duplicated here rather than extracted, matching
 * the existing precedent of one copy per feature (see `lib/authToken.ts`'s
 * own docstring on this) — the SSE client (`sseClient.ts`) needs its own
 * variant anyway since `EventSource` can't carry an Authorization header,
 * so there is no single shared helper this could fully replace.
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

export interface ListAccessEventsParams {
  deviceId?: string
  decision?: AccessDecision
  from?: string
  to?: string
  limit?: number
  offset?: number
}

/** Exported separately so the query-string building is testable without
 * mocking fetch (mirrors `enrollment-management/api.ts::buildListQuery`). */
export function buildAccessEventsQuery(params: ListAccessEventsParams): string {
  const search = new URLSearchParams()
  if (params.deviceId) search.set('device_id', params.deviceId)
  if (params.decision) search.set('decision', params.decision)
  if (params.from) search.set('from', params.from)
  if (params.to) search.set('to', params.to)
  search.set('limit', String(params.limit ?? 50))
  search.set('offset', String(params.offset ?? 0))
  return search.toString()
}

export async function listAccessEvents(
  params: ListAccessEventsParams = {},
): Promise<AccessEventListResponse> {
  const response = await authFetch(`/api/v1/access-events?${buildAccessEventsQuery(params)}`)
  return (await response.json()) as AccessEventListResponse
}

/** Start of "today" in ISO-8601, local time — the boundary `GET
 * /access-events?from=...` uses for the snapshot count below. */
export function startOfTodayIso(now: Date = new Date()): string {
  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  return start.toISOString()
}

/**
 * MVP snapshot for the "ringkasan hari ini" panel (task instructions
 * explicitly call this out as such, not real server-side aggregation):
 * one `GET /access-events?decision=X&from=<today>&limit=1` per decision,
 * reading only `total` from each response. The UI then increments these
 * locally as matching SSE events arrive — see `LiveMonitoringPage.tsx`.
 */
export async function fetchTodaySummary(
  deviceId?: string,
  now: Date = new Date(),
): Promise<TodaySummary> {
  const from = startOfTodayIso(now)
  const entries = await Promise.all(
    ACCESS_DECISIONS.map(async (decision) => {
      const data = await listAccessEvents({ deviceId, decision, from, limit: 1 })
      return [decision, data.total] as const
    }),
  )
  return { ...EMPTY_TODAY_SUMMARY, ...Object.fromEntries(entries) } as TodaySummary
}

export interface ListDevicesParams {
  status?: string
  doorGroup?: string
  limit?: number
  offset?: number
}

export function buildDevicesQuery(params: ListDevicesParams): string {
  const search = new URLSearchParams()
  if (params.status) search.set('status', params.status)
  if (params.doorGroup) search.set('door_group', params.doorGroup)
  search.set('limit', String(params.limit ?? 100))
  search.set('offset', String(params.offset ?? 0))
  return search.toString()
}

/** `GET /devices` is ADMIN/OPERATOR only (backend `devices.py` READ_ROLES
 * deliberately excludes VIEWER, unlike most staff-read endpoints) —
 * `LiveMonitoringPage` only calls this when `getCurrentRole()` is one of
 * those two, so a VIEWER session never fires a request that's guaranteed
 * to 403. */
export async function listDevices(
  params: ListDevicesParams = {},
): Promise<DeviceListResponse> {
  const response = await authFetch(`/api/v1/devices?${buildDevicesQuery(params)}`)
  return (await response.json()) as DeviceListResponse
}

/** Builds the absolute URL for `GET /stream/access-events` — split out from
 * `sseClient.ts` so the query-string logic is unit-testable without
 * touching `fetch`/`ReadableStream`. */
export function buildAccessEventStreamUrl(params: {
  deviceId?: string
  decision?: AccessDecision
}): string {
  const search = new URLSearchParams()
  if (params.deviceId) search.set('device_id', params.deviceId)
  if (params.decision) search.set('decision', params.decision)
  const qs = search.toString()
  return `${API_BASE_URL}/api/v1/stream/access-events${qs ? `?${qs}` : ''}`
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

/** Mirrors `enrollment-management/api.ts::describeApiError` — same
 * per-status Indonesian copy, falling back to the backend's RFC 9457
 * `detail` when present. */
export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = problemDetail(error.body)
    switch (error.status) {
      case 401:
        return detail ?? 'Sesi kamu telah berakhir. Silakan login ulang.'
      case 403:
        return detail ?? 'Kamu tidak memiliki izin untuk melihat data ini.'
      case 404:
        return detail ?? 'Data yang dimaksud tidak ditemukan.'
      default:
        return detail ?? `Terjadi kesalahan tak terduga (status ${error.status}).`
    }
  }
  if (error instanceof Error) return error.message
  return 'Terjadi kesalahan tak terduga.'
}
