import type {
  CreateUserBody,
  UpdateUserBody,
  UserListResponse,
  UserResponse,
  UserStatus,
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
 * FE-02 note: on a 401 we make ONE reactive attempt to refresh the access
 * token (see `lib/authToken.ts::refreshAccessToken` for why reactive was
 * chosen over proactive) and retry the original request ONCE with the new
 * token. If refresh also fails, the original 401 propagates unchanged so
 * existing callers/tests see the same behavior as before this was added.
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

export interface ListUsersParams {
  status?: UserStatus
  limit?: number
  offset?: number
}

/** Exported separately from `listUsers` so the query-string building (the
 * part worth asserting on) is testable without mocking fetch. */
export function buildListQuery(params: ListUsersParams): string {
  const search = new URLSearchParams()
  if (params.status) search.set('status', params.status)
  search.set('limit', String(params.limit ?? 20))
  search.set('offset', String(params.offset ?? 0))
  return search.toString()
}

export async function listUsers(params: ListUsersParams = {}): Promise<UserListResponse> {
  const response = await authFetch(`/api/v1/users?${buildListQuery(params)}`)
  return (await response.json()) as UserListResponse
}

export async function getUser(id: string): Promise<UserResponse> {
  const response = await authFetch(`/api/v1/users/${id}`)
  return (await response.json()) as UserResponse
}

export async function createUser(body: CreateUserBody): Promise<UserResponse> {
  const response = await authFetch('/api/v1/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as UserResponse
}

export async function updateUser(id: string, body: UpdateUserBody): Promise<UserResponse> {
  const response = await authFetch(`/api/v1/users/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as UserResponse
}

/** Quick status-change actions on the list/detail screens — all thin
 * wrappers around `updateUser` since the backend only exposes a single
 * PATCH for status changes (no dedicated suspend/reactivate endpoints). */
export async function setUserStatus(id: string, status: UserStatus): Promise<UserResponse> {
  return updateUser(id, { status })
}

/** `DELETE /users/{id}` — backend alias for `PATCH status=OFFBOARDED`, NOT
 * a hard delete (see BE-04). Kept as its own function so call sites read as
 * intent ("offboard this user") rather than a generic status PATCH, and so
 * a future divergence between the two backend paths doesn't require
 * touching every call site. */
export async function offboardUser(id: string): Promise<UserResponse> {
  const response = await authFetch(`/api/v1/users/${id}`, { method: 'DELETE' })
  return (await response.json()) as UserResponse
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
 * display (409/404/403/422), falling back to the backend's own `detail`
 * (RFC 9457 problem+json) when present. Mirrors
 * `enrollment-management/api.ts::describeApiError`. */
export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = problemDetail(error.body)
    switch (error.status) {
      case 401:
        return detail ?? 'Sesi kamu telah berakhir. Silakan login ulang.'
      case 403:
        return detail ?? 'Kamu tidak memiliki izin untuk melakukan aksi ini.'
      case 404:
        return detail ?? 'Data user yang dimaksud tidak ditemukan.'
      case 409:
        return detail ?? 'External ref ini sudah digunakan oleh user lain.'
      case 422:
        return detail ?? 'Data yang dikirim tidak valid, silakan periksa kembali.'
      default:
        return detail ?? `Terjadi kesalahan tak terduga (status ${error.status}).`
    }
  }
  if (error instanceof Error) return error.message
  return 'Terjadi kesalahan tak terduga.'
}
