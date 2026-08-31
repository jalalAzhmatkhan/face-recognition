/**
 * Shared JWT/localStorage helpers for the staff console.
 *
 * FE-04 (`enrollment-capture/apiClient.ts`) and FE-05
 * (`enrollment-management/authToken.ts`) each established their own copy of
 * this exact logic, both documenting that "no shared convention exists
 * yet". FE-03 needs the same thing a third time (role-gating the users
 * list/detail screens), so rather than duplicate it again this pulls it out
 * into one place, per FE-03 task instructions. The two earlier copies are
 * left as-is for this task (touching another feature's already-merged
 * files is out of scope here and adds needless merge risk); new features
 * should import from here, and consolidating the older copies onto this
 * module is a good small follow-up.
 */

const ACCESS_TOKEN_KEY = 'frac_access_token'
const REFRESH_TOKEN_KEY = 'frac_refresh_token'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

export function getAccessToken(): string | null {
  try {
    return window.localStorage.getItem(ACCESS_TOKEN_KEY)
  } catch {
    return null
  }
}

export function getRefreshToken(): string | null {
  try {
    return window.localStorage.getItem(REFRESH_TOKEN_KEY)
  } catch {
    return null
  }
}

function setAccessToken(token: string): void {
  try {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, token)
  } catch {
    /* localStorage unavailable (private mode / SSR) — nothing we can do */
  }
}

export interface TokenPair {
  access_token: string
  refresh_token: string
}

/** Persists both tokens after a successful `/auth/login` (FE-02). */
export function setTokens(tokens: TokenPair): void {
  setAccessToken(tokens.access_token)
  try {
    window.localStorage.setItem(REFRESH_TOKEN_KEY, tokens.refresh_token)
  } catch {
    /* localStorage unavailable */
  }
}

/** Wipes both tokens — used on logout and whenever refresh fails. */
export function clearTokens(): void {
  try {
    window.localStorage.removeItem(ACCESS_TOKEN_KEY)
    window.localStorage.removeItem(REFRESH_TOKEN_KEY)
  } catch {
    /* localStorage unavailable */
  }
}

export interface DecodedTokenPayload {
  sub?: string
  role?: string
  exp?: number
  [key: string]: unknown
}

/**
 * Decodes the payload segment of a JWT for UI role-gating purposes ONLY.
 * This performs NO signature verification and NO expiry check — the
 * backend is the sole source of truth for authorization on every request;
 * this only decides which buttons the console shows/hides. Never trust
 * this decoding for anything security-critical.
 */
export function decodeJwtPayload(token: string): DecodedTokenPayload | null {
  const parts = token.split('.')
  if (parts.length < 2) return null
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4)
    const binary = atob(padded)
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0))
    const json = new TextDecoder('utf-8').decode(bytes)
    const parsed: unknown = JSON.parse(json)
    if (parsed === null || typeof parsed !== 'object') return null
    return parsed as DecodedTokenPayload
  } catch {
    return null
  }
}

/** Staff console RBAC roles (FR-USR-02). */
export type StaffRole = 'ADMIN' | 'OPERATOR' | 'VIEWER'

export const STAFF_ROLES: StaffRole[] = ['ADMIN', 'OPERATOR', 'VIEWER']

function isStaffRole(value: unknown): value is StaffRole {
  return typeof value === 'string' && (STAFF_ROLES as string[]).includes(value)
}

/** The role claim of the currently stored access token, or null if there
 * is no token, it is malformed, or the role claim is missing/unrecognized. */
export function getCurrentRole(): StaffRole | null {
  const token = getAccessToken()
  if (!token) return null
  const payload = decodeJwtPayload(token)
  return isStaffRole(payload?.role) ? payload.role : null
}

/**
 * Whether the currently stored access token is missing, malformed, or
 * expired (optionally treating a token as expired `bufferSeconds` before
 * its actual `exp`, e.g. to leave headroom for in-flight requests).
 *
 * This is used for the FE-02 page-level route guard (`AuthGuard.tsx`) to
 * decide, at navigation time, whether the console should even try to show
 * a shell route. It is NOT how individual API calls decide whether to
 * refresh — see the "reactive vs proactive" note on `refreshAccessToken`
 * below for why per-request refresh is handled differently.
 */
export function isAccessTokenExpired(bufferSeconds = 0): boolean {
  const token = getAccessToken()
  if (!token) return true
  const payload = decodeJwtPayload(token)
  if (typeof payload?.exp !== 'number') return true
  const nowSeconds = Date.now() / 1000
  return payload.exp <= nowSeconds + bufferSeconds
}

/**
 * Calls `POST /auth/refresh` with the stored refresh token and, on
 * success, overwrites the stored access token. The refresh token itself
 * is NOT rotated by the backend (BE-03), so it is left untouched.
 *
 * Returns the new access token on success, or `null` on any failure
 * (missing refresh token, network error, 401 because the refresh token is
 * invalid/expired/wrong-type) — and clears both stored tokens in that
 * failure case, since a refresh token that the backend rejects can never
 * succeed later either.
 *
 * Strategy note (proactive vs reactive refresh): this app uses REACTIVE
 * refresh — callers invoke this only after a request already came back
 * 401 (see the `authFetch` helpers in enrollment-capture/apiClient.ts,
 * enrollment-management/api.ts and user-management/api.ts, plus the
 * route guard's expired-token path). We picked reactive over proactively
 * refreshing a few minutes before `exp` because it needs no background
 * timer/interceptor plumbing, can't race a proactive refresh against a
 * request that's already in flight, and degrades safely: worst case is
 * one extra round trip (the 401) before the retry, which is cheap given
 * how infrequently access tokens expire (15 min).
 */
export async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    clearTokens()
    return null
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!response.ok) {
      clearTokens()
      return null
    }
    const data = (await response.json()) as { access_token: string }
    setAccessToken(data.access_token)
    return data.access_token
  } catch {
    clearTokens()
    return null
  }
}

export interface LoginCredentials {
  email: string
  password: string
}

/** Thrown by `login()`. `message` is always the generic, non-leaking copy
 * NFR-SEC-04 / FR-USR-02 call for ("don't reveal which part was wrong"). */
export class LoginError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'LoginError'
    this.status = status
  }
}

/** `POST /auth/login`. On success, stores both tokens via `setTokens` and
 * resolves with nothing further to do (caller just navigates on). On
 * failure, throws `LoginError` with a message safe to show as-is. */
export async function login({ email, password }: LoginCredentials): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  } catch {
    throw new LoginError('Tidak dapat terhubung ke server. Coba lagi.', 0)
  }

  if (!response.ok) {
    // 401 message is intentionally generic — never hints at which field
    // (email vs password) was wrong, or whether the account exists.
    const message =
      response.status === 401
        ? 'Email atau password salah.'
        : 'Gagal login, silakan coba lagi.'
    throw new LoginError(message, response.status)
  }

  const data = (await response.json()) as TokenPair
  setTokens(data)
}

/** Thrown by `forgotPassword()`/`resetPassword()`. */
export class PasswordResetError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'PasswordResetError'
    this.status = status
  }
}

async function postPasswordResetRequest(
  path: string,
  body: Record<string, string>,
  fallbackMessage: string,
): Promise<{ message: string }> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new PasswordResetError('Tidak dapat terhubung ke server. Coba lagi.', 0)
  }

  if (!response.ok) {
    let detail: string | undefined
    try {
      const problemBody = (await response.json()) as { detail?: string }
      detail = problemBody.detail
    } catch {
      /* no JSON body */
    }
    throw new PasswordResetError(detail ?? fallbackMessage, response.status)
  }

  return (await response.json()) as { message: string }
}

/** `POST /auth/forgot-password` — always succeeds from the caller's
 * perspective (NFR-SEC-04: identical response whether or not the email
 * matched an account). Never throws for an unknown email; only a genuine
 * network/server failure throws. */
export async function forgotPassword(email: string): Promise<{ message: string }> {
  return postPasswordResetRequest(
    '/api/v1/auth/forgot-password',
    { email },
    'Gagal mengirim tautan reset password, silakan coba lagi.',
  )
}

/** `POST /auth/reset-password` — throws `PasswordResetError` (400) when the
 * token is malformed/unknown/expired/already used. */
export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<{ message: string }> {
  return postPasswordResetRequest(
    '/api/v1/auth/reset-password',
    { token, new_password: newPassword },
    'Gagal mereset password, silakan coba lagi.',
  )
}

export interface SetupStatus {
  needs_setup: boolean
}

/** `GET /auth/setup-status` — unauthenticated, used by `SetupAdminPage` to
 * decide whether the first-run "create ADMIN account" screen should even be
 * shown (only while zero ADMIN accounts exist anywhere). */
export async function getSetupStatus(): Promise<SetupStatus> {
  const response = await fetch(`${API_BASE_URL}/api/v1/auth/setup-status`, {
    headers: { Accept: 'application/json' },
  })
  if (!response.ok) {
    throw new Error(`GET /auth/setup-status failed with ${response.status}`)
  }
  return (await response.json()) as SetupStatus
}

/** Thrown by `bootstrapAdmin()`. */
export class BootstrapAdminError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'BootstrapAdminError'
    this.status = status
  }
}

/** `POST /auth/bootstrap-admin` — creates the very first ADMIN account.
 * Fails with 409 once any ADMIN already exists (self-disabling by design,
 * see `backend/app/services/auth_service.py::bootstrap_admin`). On success,
 * stores both tokens via `setTokens` exactly like `login()` does, so the
 * caller can navigate straight into the console. */
export async function bootstrapAdmin({ email, password }: LoginCredentials): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/auth/bootstrap-admin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ email, password }),
    })
  } catch {
    throw new BootstrapAdminError('Tidak dapat terhubung ke server. Coba lagi.', 0)
  }

  if (!response.ok) {
    let detail: string | undefined
    try {
      const body = (await response.json()) as { detail?: string }
      detail = body.detail
    } catch {
      /* no JSON body */
    }
    const message =
      response.status === 409
        ? (detail ?? 'Akun ADMIN sudah pernah dibuat sebelumnya.')
        : response.status === 422
          ? (detail ?? 'Data yang dikirim tidak valid — password minimal 8 karakter.')
          : (detail ?? 'Gagal membuat akun ADMIN, silakan coba lagi.')
    throw new BootstrapAdminError(message, response.status)
  }

  const data = (await response.json()) as TokenPair
  setTokens(data)
}
