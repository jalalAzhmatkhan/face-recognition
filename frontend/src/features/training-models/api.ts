import type {
  CreateTrainingJobBody,
  ModelPromoteBody,
  ModelPromoteResponse,
  ModelStage,
  ModelVersionListResponse,
  TrainingJobListResponse,
  TrainingJobResponse,
  TrainingJobStatus,
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
 * `api.ts` (`device-management`, `user-management`, `enrollment-management`,
 * `live-monitoring`) — see `lib/authToken.ts::refreshAccessToken`'s
 * docstring for why reactive was chosen, and `live-monitoring/api.ts`'s
 * docstring for why this copy isn't consolidated into a shared helper yet.
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

export interface ListModelsParams {
  stage?: ModelStage
}

/** Exported separately from `listModels` so the query-string building (the
 * part worth asserting on) is testable without mocking fetch. Mirrors
 * `device-management/api.ts::buildListQuery`. */
export function buildModelsQuery(params: ListModelsParams): string {
  const search = new URLSearchParams()
  if (params.stage) search.set('stage', params.stage)
  return search.toString()
}

/** `GET /models` — BE-13 allows ADMIN/OPERATOR/VIEWER to read this, but the
 * whole S-50/51/52 feature is gated ADMIN-only in the frontend per
 * screen-plan (see `roleGating.ts` for why). */
export async function listModels(
  params: ListModelsParams = {},
): Promise<ModelVersionListResponse> {
  const query = buildModelsQuery(params)
  const response = await authFetch(`/api/v1/models${query ? `?${query}` : ''}`)
  return (await response.json()) as ModelVersionListResponse
}

/** `GET /training/jobs/{id}` — ADMIN/OPERATOR at the backend. */
export async function getTrainingJob(id: string): Promise<TrainingJobResponse> {
  const response = await authFetch(`/api/v1/training/jobs/${encodeURIComponent(id)}`)
  return (await response.json()) as TrainingJobResponse
}

export interface ListTrainingJobsParams {
  status?: TrainingJobStatus
  model_version?: string
  limit?: number
  offset?: number
}

/** Exported separately so the query-string building is testable without
 * mocking fetch, mirrors `buildModelsQuery`/`device-management`'s
 * `buildListQuery`. */
export function buildTrainingJobsQuery(params: ListTrainingJobsParams): string {
  const search = new URLSearchParams()
  if (params.status) search.set('status', params.status)
  if (params.model_version) search.set('model_version', params.model_version)
  search.set('limit', String(params.limit ?? 20))
  search.set('offset', String(params.offset ?? 0))
  return search.toString()
}

/** `GET /training/jobs` (BE-15) — ADMIN/OPERATOR, newest first. Closes the
 * gap FE-09 originally worked around with a browser-localStorage-only list
 * (see git history / task-breakdown.md's BE-15 entry) — this is now the
 * real server-side training-run history. */
export async function listTrainingJobs(
  params: ListTrainingJobsParams = {},
): Promise<TrainingJobListResponse> {
  const query = buildTrainingJobsQuery(params)
  const response = await authFetch(`/api/v1/training/jobs?${query}`)
  return (await response.json()) as TrainingJobListResponse
}

/** `POST /training/jobs` — ADMIN only (FR-TRN-02, manual trigger). */
export async function createTrainingJob(
  body: CreateTrainingJobBody,
): Promise<TrainingJobResponse> {
  const response = await authFetch('/api/v1/training/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as TrainingJobResponse
}

/** `POST /models/{version}/promote` — ADMIN only (FR-TRN-05). Every caller
 * in this feature always sends `confirm: true` explicitly right before the
 * operator clicks the final confirm-dialog button — never as a default or
 * implicit body. */
export async function promoteModel(
  version: string,
  body: ModelPromoteBody,
): Promise<ModelPromoteResponse> {
  const response = await authFetch(`/api/v1/models/${encodeURIComponent(version)}/promote`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as ModelPromoteResponse
}

interface ProblemBody {
  detail?: string
  reasons?: unknown
}

function problemDetail(body: unknown): string | null {
  if (body && typeof body === 'object' && typeof (body as ProblemBody).detail === 'string') {
    return (body as ProblemBody).detail as string
  }
  return null
}

/**
 * Extracts the RFC 9457 `reasons` array BE-13 attaches to a 409 promotion-
 * gate failure. Server side: `training_service.PromotionGateError.reasons`
 * gets mapped by the router to `ProblemError(status_code=409, ...,
 * extra={"reasons": exc.reasons})` (`backend/app/routers/training.py::
 * promote_model`) — i.e. the problem+json body has BOTH a human-joined
 * `detail` string AND this separate `reasons` array of the individual gate
 * failure messages. This lets the UI show each reason as its own list item
 * instead of one run-on sentence. Returns null when the error isn't a 409
 * with a well-formed `reasons` array, so callers fall back to `detail`.
 */
export function promotionGateReasons(error: unknown): string[] | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const body = error.body
  if (!body || typeof body !== 'object') return null
  const reasons = (body as ProblemBody).reasons
  if (!Array.isArray(reasons) || reasons.length === 0) return null
  if (!reasons.every((reason) => typeof reason === 'string')) return null
  return reasons as string[]
}

/** Mirrors `device-management/api.ts::describeApiError` — same per-status
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
        return detail ?? 'Data yang dimaksud tidak ditemukan.'
      case 409:
        return detail ?? 'Aksi ini tidak bisa dilakukan pada status saat ini.'
      case 422:
        return detail ?? 'Data yang dikirim tidak valid, silakan periksa kembali.'
      default:
        return detail ?? `Terjadi kesalahan tak terduga (status ${error.status}).`
    }
  }
  if (error instanceof Error) return error.message
  return 'Terjadi kesalahan tak terduga.'
}
