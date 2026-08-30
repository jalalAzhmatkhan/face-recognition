import { useEffect, useState } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { refreshAccessToken } from '../lib/authToken'
import { evaluateAuthGuard } from './authGuardLogic'

/**
 * Page-level auth guard for FE-02 (FR-USR-02, NFR-SEC-04).
 *
 * Scope note: FR-USR-02 defines three staff roles (ADMIN/OPERATOR/VIEWER),
 * but per the current screen plan NO route is admin/operator-only at the
 * page level — every role may *view* every shell screen, and the
 * fine-grained "VIEWER can't see admin actions" requirement is satisfied
 * per-button/per-action by each feature's own `roleGating.ts` (FE-03/04/05,
 * already implemented). So this guard deliberately does ONLY one thing —
 * "is there a usable session at all" — and does NOT branch on role. If a
 * genuinely role-restricted page is ever added, that's a new guard (or a
 * parameterized variant of this one), not a change to this file's job.
 */
/**
 * Guards every route nested under it: redirects to `/login` when there is
 * no token at all, or when the access token is expired and a refresh
 * attempt (triggered here, since there is nothing to react to yet — no
 * request has been made) does not succeed. Once inside, in-flight API
 * calls rely on the reactive 401-retry in each feature's `authFetch`
 * instead (see `lib/authToken.ts` refreshAccessToken docstring).
 */
export default function AuthGuard() {
  const [status, setStatus] = useState<'allow' | 'checking' | 'deny'>(() => {
    const decision = evaluateAuthGuard()
    return decision === 'refresh' ? 'checking' : decision
  })

  useEffect(() => {
    if (status !== 'checking') return
    let cancelled = false
    refreshAccessToken().then((token) => {
      if (cancelled) return
      setStatus(token ? 'allow' : 'deny')
    })
    return () => {
      cancelled = true
    }
  }, [status])

  if (status === 'checking') return null
  if (status === 'deny') return <Navigate to="/login" replace />
  return <Outlet />
}
