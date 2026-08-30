import type { StaffRole } from './types'
import { STAFF_ROLES } from './types'

/**
 * Same localStorage key FE-04's `enrollment-capture/apiClient.ts` reads
 * (and the key FE-02 login should write to). Duplicated here rather than
 * imported cross-feature — see that module's own docstring: there is no
 * shared API-client convention yet, each feature establishes what it needs
 * against the same key name.
 */
const ACCESS_TOKEN_KEY = 'frac_access_token'

export function getAccessToken(): string | null {
  try {
    return window.localStorage.getItem(ACCESS_TOKEN_KEY)
  } catch {
    return null
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
