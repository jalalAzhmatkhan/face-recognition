import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BootstrapAdminError, bootstrapAdmin, getSetupStatus } from '../lib/authToken'

/**
 * First-run "create ADMIN account" screen. Reachable at `/setup` — declared
 * as a top-level sibling of `/login` in `routes.tsx`, outside `AuthGuard`,
 * so it works with zero staff accounts and no token at all.
 *
 * Self-disabling: `GET /auth/setup-status` reports `needs_setup: true` only
 * while zero ADMIN accounts exist anywhere (backend-enforced —
 * `POST /auth/bootstrap-admin` itself would reject a second attempt with
 * 409 even if this redirect were somehow bypassed). Once an ADMIN exists,
 * this page redirects to `/login` instead of rendering the form.
 */
export default function SetupAdminPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const setupStatusQuery = useQuery({
    queryKey: ['auth', 'setup-status'],
    queryFn: getSetupStatus,
    retry: false,
  })

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await bootstrapAdmin({ email, password })
      navigate('/', { replace: true })
    } catch (err) {
      setError(
        err instanceof BootstrapAdminError ? err.message : 'Gagal membuat akun ADMIN, silakan coba lagi.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  // Don't render the form (or flash it) while we don't yet know the
  // setup-status, or once we know it's no longer needed -- redirect instead,
  // matching AuthGuard's own "return null while checking" convention.
  // Navigation itself happens in an effect (not during render) since
  // triggering a route change mid-render is unsafe in React.
  const shouldRedirectToLogin =
    setupStatusQuery.isError || setupStatusQuery.data?.needs_setup === false

  useEffect(() => {
    if (shouldRedirectToLogin) navigate('/login', { replace: true })
  }, [shouldRedirectToLogin, navigate])

  if (setupStatusQuery.isLoading || shouldRedirectToLogin) return null

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: 'var(--space-6)',
      }}
    >
      <form
        onSubmit={handleSubmit}
        noValidate
        style={{
          width: 'min(400px, 100%)',
          background: 'var(--bg-surface)',
          border: 'var(--border-w) solid var(--border-default)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-md)',
          padding: 'var(--space-8)',
          textAlign: 'center',
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
        }}
      >
        <h1>Setup Awal FRAC Console</h1>
        <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
          Belum ada akun ADMIN. Buat akun ADMIN pertama untuk mulai menggunakan aplikasi ini.
        </p>

        <div style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
          <label htmlFor="setup-email" style={{ font: 'var(--text-small)', color: 'var(--text-secondary)' }}>
            Email
          </label>
          <input
            id="setup-email"
            name="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            style={{
              minHeight: 'var(--touch-target)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-default)',
              padding: '0 var(--space-3)',
              font: 'var(--text-body)',
            }}
          />
        </div>

        <div style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
          <label htmlFor="setup-password" style={{ font: 'var(--text-small)', color: 'var(--text-secondary)' }}>
            Password
          </label>
          <input
            id="setup-password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            style={{
              minHeight: 'var(--touch-target)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-default)',
              padding: '0 var(--space-3)',
              font: 'var(--text-body)',
            }}
          />
          <span style={{ font: 'var(--text-caption)', color: 'var(--text-muted)' }}>
            Minimal 8 karakter.
          </span>
        </div>

        {error && (
          <p role="alert" style={{ font: 'var(--text-small)', color: 'var(--danger, crimson)', margin: 0 }}>
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting}
          style={{
            minHeight: 'var(--touch-target)',
            borderRadius: 'var(--radius-md)',
            border: 'none',
            background: 'var(--accent)',
            color: 'var(--text-inverse)',
            font: 'var(--text-body)',
            fontWeight: 600,
            opacity: submitting ? 0.6 : 1,
          }}
        >
          {submitting ? 'Membuat akun…' : 'Buat Akun ADMIN'}
        </button>

        <p
          style={{
            font: 'var(--text-small)',
            color: 'var(--text-muted)',
            margin: 0,
          }}
        >
          Halaman ini hanya bisa diakses satu kali, sebelum akun ADMIN pertama dibuat.
        </p>
      </form>
    </div>
  )
}
