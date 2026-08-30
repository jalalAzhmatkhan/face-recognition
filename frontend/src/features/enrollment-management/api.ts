import type {
  EnrollmentListResponse,
  EnrollmentResponse,
  EnrollmentState,
  RevocationResponse,
} from './types'
import { getAccessToken } from './authToken'

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

async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getAccessToken()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
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

export interface ListEnrollmentsParams {
  userId?: string
  state?: EnrollmentState
  limit?: number
  offset?: number
}

/** Exported separately from `listEnrollments` so the query-string building
 * (the part worth asserting on) is testable without mocking fetch. */
export function buildListQuery(params: ListEnrollmentsParams): string {
  const search = new URLSearchParams()
  if (params.userId) search.set('user_id', params.userId)
  if (params.state) search.set('state', params.state)
  search.set('limit', String(params.limit ?? 20))
  search.set('offset', String(params.offset ?? 0))
  return search.toString()
}

export async function listEnrollments(
  params: ListEnrollmentsParams = {},
): Promise<EnrollmentListResponse> {
  const response = await authFetch(`/api/v1/enrollments?${buildListQuery(params)}`)
  return (await response.json()) as EnrollmentListResponse
}

export async function getEnrollment(id: string): Promise<EnrollmentResponse> {
  const response = await authFetch(`/api/v1/enrollments/${id}`)
  return (await response.json()) as EnrollmentResponse
}

export async function createEnrollment(userId: string): Promise<EnrollmentResponse> {
  const response = await authFetch('/api/v1/enrollments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId }),
  })
  return (await response.json()) as EnrollmentResponse
}

export async function grantConsent(
  id: string,
  consentVersion: string,
): Promise<EnrollmentResponse> {
  const response = await authFetch(`/api/v1/enrollments/${id}/consent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consent_version: consentVersion }),
  })
  return (await response.json()) as EnrollmentResponse
}

/** Only `target_state: "CAPTURING"` is accepted by the backend's generic
 * `/transition` endpoint (see `backend/app/routers/enrollments.py`
 * `MANUALLY_TRIGGERABLE_TARGETS`) — this wraps that one legal use. */
export async function startRecapture(id: string): Promise<EnrollmentResponse> {
  const response = await authFetch(`/api/v1/enrollments/${id}/transition`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_state: 'CAPTURING' }),
  })
  return (await response.json()) as EnrollmentResponse
}

export async function cancelEnrollment(id: string): Promise<EnrollmentResponse> {
  const response = await authFetch(`/api/v1/enrollments/${id}/cancel`, { method: 'POST' })
  return (await response.json()) as EnrollmentResponse
}

/** ADMIN-only, ENROLLED-only (BE-08). Returns 202 — the synchronous part
 * (state -> REVOKED) is done, embeddings/media cleanup is async. */
export async function revokeEnrollment(id: string): Promise<RevocationResponse> {
  const response = await authFetch(`/api/v1/enrollments/${id}`, { method: 'DELETE' })
  return (await response.json()) as RevocationResponse
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

/** Turns an error thrown by any function above into a message fit for
 * display, per task instructions ("Tangani error API (409/404/403/422)
 * dengan pesan jelas"). Falls back to the backend's own `detail` (RFC 9457
 * problem+json, see `backend/app/core/problem.py`) when we have one. */
export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = problemDetail(error.body)
    switch (error.status) {
      case 401:
        return detail ?? 'Sesi kamu telah berakhir. Silakan login ulang.'
      case 403:
        return detail ?? 'Kamu tidak memiliki izin untuk melakukan aksi ini.'
      case 404:
        return detail ?? 'Data enrollment yang dimaksud tidak ditemukan.'
      case 409:
        return detail ?? 'Aksi ini tidak bisa dilakukan pada status sesi saat ini.'
      case 422:
        return detail ?? 'Data yang dikirim tidak valid, silakan periksa kembali.'
      default:
        return detail ?? `Terjadi kesalahan tak terduga (status ${error.status}).`
    }
  }
  if (error instanceof Error) return error.message
  return 'Terjadi kesalahan tak terduga.'
}
