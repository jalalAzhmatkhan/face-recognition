import type {
  ClockPosition,
  CompleteResponse,
  ConsentResponse,
  MediaKind,
  PresignRequestBody,
  PresignResponse,
} from './types'
import { refreshAccessToken } from '../../lib/authToken'

/**
 * No shared API client/auth-header convention exists yet elsewhere in the
 * app (FE-04 note, now historical: FE-02 has since landed real login,
 * writing to this same localStorage key). A bearer token is read from
 * localStorage under `frac_access_token` and attached to every request.
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

export function buildPresignRequestBody(
  kind: MediaKind,
  file: {
    contentType: string
    size: number
    sha256Hex: string
    clockPosition?: ClockPosition
  },
): PresignRequestBody {
  const body: PresignRequestBody = {
    kind,
    content_type: file.contentType,
    size: file.size,
    sha256: file.sha256Hex,
  }
  // Omitted entirely rather than sent as null: the backend treats a missing
  // clock_position as "frontal preflight photo" and rejects the field
  // outright on kind: 'video'.
  if (file.clockPosition !== undefined) body.clock_position = file.clockPosition
  return body
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

/**
 * EC-FE-05: record the subject's consent grant from the wizard's own
 * consent step, sending `CURRENT_CONSENT_VERSION` (see `./types`). Backend
 * only accepts this while the session is `CREATED` (BE-05/EC-BE-09) — a
 * session reached via the operator's manual consent + recapture flow
 * (`EnrollmentDetailPage.tsx`) will already be past that state by the time
 * this wizard loads, so callers MUST treat a conflict here as non-fatal
 * (ASM-EC-05: a failed re-consent must never block capture from starting).
 */
export async function grantConsent(
  enrollmentId: string,
  consentVersion: string,
): Promise<ConsentResponse> {
  const response = await authFetch(`/api/v1/enrollments/${enrollmentId}/consent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consent_version: consentVersion }),
  })
  return (await response.json()) as ConsentResponse
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

/**
 * `GET /system-parameters/enrollment-quality` — the ADMIN-configurable
 * sharpness/brightness gate (System Parameter menu,
 * `pages/SystemParametersPage.tsx`), open to every authenticated staff
 * role including whoever is running this capture wizard. Callers MUST
 * treat any failure here as non-fatal and fall back to
 * `imageQuality.QUALITY_THRESHOLDS` (see `EnrollmentCapturePage.tsx`) — a
 * settings-service hiccup must never block enrollment capture.
 */
export interface EnrollmentQualityParams {
  min_blur_variance: number
  min_brightness: number
  max_brightness: number
  /** Head-pose sensitivity (see `clockSectors.ts::PoseSensitivity`). Optional
   * because a deployment whose backend predates these fields simply omits
   * them, and the wizard then keeps its built-in defaults. */
  yaw_gain?: number
  pitch_gain?: number
  min_pose_radius?: number
}

export async function getEnrollmentQualityParams(): Promise<EnrollmentQualityParams> {
  const response = await authFetch('/api/v1/system-parameters/enrollment-quality')
  return (await response.json()) as EnrollmentQualityParams
}
