import { getAccessToken, getRefreshToken, isAccessTokenExpired } from '../lib/authToken'

/**
 * Pure decision logic for FE-02's page-level auth guard (`AuthGuard.tsx`).
 * Split into its own module (rather than living in the component file) so
 * it can be unit-tested without mounting React, and so the component file
 * only exports the component (`react-refresh/only-export-components`).
 */
export type AuthGuardDecision = 'allow' | 'refresh' | 'deny'

export function evaluateAuthGuard(): AuthGuardDecision {
  if (!getAccessToken() && !getRefreshToken()) return 'deny'
  if (!isAccessTokenExpired()) return 'allow'
  return getRefreshToken() ? 'refresh' : 'deny'
}
