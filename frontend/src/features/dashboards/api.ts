import type {
  AccessDecision,
  AccessEventListResponse,
  AccessEventSample,
  AccessEventSampleResponse,
  DailyDecisionCount,
  EnrollmentFunnelStage,
  EnrollmentListResponse,
  ModelVersionListResponse,
  ModelVersionResponse,
  TodayCounts,
} from './types'
import { ACCESS_DECISIONS, EMPTY_TODAY_COUNTS, ENROLLMENT_FUNNEL_STATES } from './types'
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

/** Same reactive-refresh-on-401 pattern duplicated in every other feature's
 * `api.ts` — see `live-monitoring/api.ts`'s docstring for why this copy
 * isn't consolidated into a shared helper yet. */
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

/** Start of a given day, local time, as ISO-8601 — `daysAgo=0` is today.
 * Mirrors `live-monitoring/api.ts::startOfTodayIso`. */
export function startOfDayIso(daysAgo: number, now: Date = new Date()): string {
  const start = new Date(now)
  start.setHours(0, 0, 0, 0)
  start.setDate(start.getDate() - daysAgo)
  return start.toISOString()
}

/** `YYYY-MM-DD` for the day `daysAgo` days before `now`, local time — used
 * as `DailyDecisionCount.dateIso` (chart x-axis labels). */
export function dateKey(daysAgo: number, now: Date = new Date()): string {
  const d = new Date(now)
  d.setDate(d.getDate() - daysAgo)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** There is no backend aggregation endpoint for any of FE-07's metrics (no
 * group-by-day, no unknown-rate, no funnel) — every count here is a real
 * `GET /access-events?...&limit=1` call read for its `.total` field only,
 * same technique `live-monitoring/api.ts::fetchTodaySummary` established.
 * This satisfies FR-MON-02 ("semua metrik tampil dari data nyata") without
 * inventing a new backend contract; the trade-off is request volume (see
 * `fetchDailyDecisionCounts`/`fetchEnrollmentFunnel` below). */
async function countAccessEvents(params: {
  decision?: AccessDecision
  from?: string
  to?: string
}): Promise<number> {
  const search = new URLSearchParams()
  if (params.decision) search.set('decision', params.decision)
  if (params.from) search.set('from', params.from)
  if (params.to) search.set('to', params.to)
  search.set('limit', '1')
  const response = await authFetch(`/api/v1/access-events?${search.toString()}`)
  const data = (await response.json()) as AccessEventListResponse
  return data.total
}

/** Today's counts per decision (stat cards row 1: Grants/Denies/Unknown
 * rate). One request per decision, same shape as
 * `live-monitoring/api.ts::fetchTodaySummary`. */
export async function fetchTodayCounts(now: Date = new Date()): Promise<TodayCounts> {
  const from = startOfDayIso(0, now)
  const entries = await Promise.all(
    ACCESS_DECISIONS.map(async (decision) => {
      const total = await countAccessEvents({ decision, from })
      return [decision, total] as const
    }),
  )
  return { ...EMPTY_TODAY_COUNTS, ...Object.fromEntries(entries) } as TodayCounts
}

/** 14-day (or however many `days`) GRANTED/DENIED trend, oldest-first, for
 * the line chart. `days * 2` count-only requests (GRANTED + DENIED per
 * day) — UNKNOWN/SPOOF_SUSPECTED are deliberately excluded from the trend
 * line, matching the screen-plan's literal "grafik garis grants/denies"
 * (unknown rate already has its own stat card). */
export async function fetchDailyDecisionCounts(
  days: number,
  now: Date = new Date(),
): Promise<DailyDecisionCount[]> {
  const dayOffsets = Array.from({ length: days }, (_, i) => days - 1 - i) // oldest first
  const rows = await Promise.all(
    dayOffsets.map(async (daysAgo) => {
      const from = startOfDayIso(daysAgo, now)
      const to = startOfDayIso(daysAgo - 1, now)
      const [granted, denied] = await Promise.all([
        countAccessEvents({ decision: 'GRANTED', from, to }),
        countAccessEvents({ decision: 'DENIED', from, to }),
      ])
      return { dateIso: dateKey(daysAgo, now), granted, denied }
    }),
  )
  return rows
}

/** `GET /models?stage=PRODUCTION` — 0 or 1 row (BE-13's `promote_model`
 * retires the previous PRODUCTION model on every promotion, see
 * `ProductionModelCard.tsx`'s comment on the training-models feature for
 * the same invariant). `null` when there is no production model yet
 * (honest empty state, never fabricated). */
export async function fetchProductionModel(): Promise<ModelVersionResponse | null> {
  const response = await authFetch('/api/v1/models?stage=PRODUCTION')
  const data = (await response.json()) as ModelVersionListResponse
  return data.items[0] ?? null
}

async function countEnrollments(state: string): Promise<number> {
  const response = await authFetch(
    `/api/v1/enrollments?${new URLSearchParams({ state, limit: '1' }).toString()}`,
  )
  const data = (await response.json()) as EnrollmentListResponse
  return data.total
}

/** Enrollment funnel (screen-plan "CREATED→ENROLLED, FR-MON-02"): one
 * count-only request per happy-path state (see
 * `ENROLLMENT_FUNNEL_STATES`). */
export async function fetchEnrollmentFunnel(): Promise<EnrollmentFunnelStage[]> {
  const counts = await Promise.all(
    ENROLLMENT_FUNNEL_STATES.map(async (state) => ({ state, count: await countEnrollments(state) })),
  )
  return counts
}

/** Largest page `GET /access-events` allows (backend `limit: le=200`). */
export const RECENT_ACCESS_EVENT_SAMPLE_SIZE = 200

/**
 * EC-FE-01 (TSD-edge-cases.md D-1) — reject-stage / condition-flag /
 * device-class distribution panel. **Known gap**: `GET /access-events` has
 * NO aggregation/group-by query params for `reject_stage`,
 * `condition_flags`, or `device_class` (confirmed against
 * `backend/app/routers/access_events.py` — only `device_id`, `decision`,
 * `from`, `to` exist). Building a real backend aggregation endpoint is out
 * of scope for this task (frontend-only), so as an interim Gelombang-0
 * measure this reads the `RECENT_ACCESS_EVENT_SAMPLE_SIZE` most recent
 * events (one plain list call, no decision filter so GRANTED is included
 * too) and the breakdown panels aggregate CLIENT-SIDE from that sample.
 * This is disclosed in the panel's own copy — it is a recent-sample view,
 * not a full-history aggregate, and will silently miss older events once
 * event volume exceeds this page size.
 */
export async function fetchRecentAccessEventSample(
  limit: number = RECENT_ACCESS_EVENT_SAMPLE_SIZE,
): Promise<AccessEventSample[]> {
  const search = new URLSearchParams()
  search.set('limit', String(limit))
  const response = await authFetch(`/api/v1/access-events?${search.toString()}`)
  const data = (await response.json()) as AccessEventSampleResponse
  return data.items
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

/** Mirrors `live-monitoring/api.ts::describeApiError` — same per-status
 * Indonesian copy, falling back to the backend's RFC 9457 `detail`. */
export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = problemDetail(error.body)
    switch (error.status) {
      case 401:
        return detail ?? 'Sesi kamu telah berakhir. Silakan login ulang.'
      case 403:
        return detail ?? 'Kamu tidak memiliki izin untuk melihat data ini.'
      default:
        return detail ?? `Terjadi kesalahan tak terduga (status ${error.status}).`
    }
  }
  if (error instanceof Error) return error.message
  return 'Terjadi kesalahan tak terduga.'
}
