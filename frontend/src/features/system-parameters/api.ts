import type { EnrollmentQualityParams, EnrollmentQualityParamsResponse } from './types'
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
 * `training-models`) — see `lib/authToken.ts::refreshAccessToken`'s
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

/** `GET /system-parameters/enrollment-quality` — ADMIN/OPERATOR/VIEWER can
 * all read this (the Enrollment capture wizard needs it for every role
 * that can perform enrollment). */
export async function getEnrollmentQualityParams(): Promise<EnrollmentQualityParamsResponse> {
  const response = await authFetch('/api/v1/system-parameters/enrollment-quality')
  return (await response.json()) as EnrollmentQualityParamsResponse
}

/** `PUT /system-parameters/enrollment-quality` — ADMIN only. */
export async function updateEnrollmentQualityParams(
  body: EnrollmentQualityParams,
): Promise<EnrollmentQualityParamsResponse> {
  const response = await authFetch('/api/v1/system-parameters/enrollment-quality', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as EnrollmentQualityParamsResponse
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

/** Mirrors `training-models/api.ts::describeApiError` — same per-status
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
      case 422:
        return detail ?? 'Data yang dikirim tidak valid, silakan periksa kembali.'
      default:
        return detail ?? `Terjadi kesalahan tak terduga (status ${error.status}).`
    }
  }
  if (error instanceof Error) return error.message
  return 'Terjadi kesalahan tak terduga.'
}
