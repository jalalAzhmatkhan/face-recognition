import type {
  CompleteResponse,
  MediaKind,
  PresignRequestBody,
  PresignResponse,
} from './types'

/**
 * No shared API client/auth-header convention exists yet elsewhere in the
 * app (FE-02 login is still a placeholder). This module establishes a
 * minimal one for FE-04's own needs: a bearer token is read from
 * localStorage under `frac_access_token` (the same key name FE-02 should
 * write to once real login lands) and attached to every request.
 */
const ACCESS_TOKEN_KEY = 'frac_access_token'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export function getAccessToken(): string | null {
  try {
    return window.localStorage.getItem(ACCESS_TOKEN_KEY)
  } catch {
    return null
  }
}

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

export function buildPresignRequestBody(
  kind: MediaKind,
  file: { contentType: string; size: number; sha256Hex: string },
): PresignRequestBody {
  return {
    kind,
    content_type: file.contentType,
    size: file.size,
    sha256: file.sha256Hex,
  }
}

export async function presignMedia(
  enrollmentId: string,
  body: PresignRequestBody,
): Promise<PresignResponse> {
  const response = await authFetch(
    `/api/v1/enrollments/${enrollmentId}/media/presign`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  )
  return (await response.json()) as PresignResponse
}

/**
 * PUT the blob directly to S3 using the presigned URL — bytes never pass
 * through our backend. The `x-amz-checksum-sha256` header MUST be the
 * base64 of the exact same digest whose hex form was sent at presign
 * time, or S3 rejects the upload.
 */
export async function uploadToS3(
  uploadUrl: string,
  blob: Blob,
  checksumBase64: string,
  contentType: string,
): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: 'PUT',
    headers: {
      'Content-Type': contentType,
      'x-amz-checksum-sha256': checksumBase64,
    },
    body: blob,
  })
  if (!response.ok) {
    throw new ApiError(
      `Upload to S3 failed with ${response.status}`,
      response.status,
      await response.text().catch(() => null),
    )
  }
}

export async function completeEnrollment(
  enrollmentId: string,
): Promise<CompleteResponse> {
  const response = await authFetch(
    `/api/v1/enrollments/${enrollmentId}/complete`,
    { method: 'POST' },
  )
  return (await response.json()) as CompleteResponse
}
