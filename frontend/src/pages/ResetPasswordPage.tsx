import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { PasswordResetError, resetPassword } from '../lib/authToken'

/** Reset-password screen, reachable at `/reset-password?token=...` (top-level
 * sibling of `/login`, outside `AuthGuard`) — the link emailed by
 * `ForgotPasswordPage`'s flow. The token itself is validated entirely by the
 * backend on submit; this page has no way (and no need) to check it upfront. */
export default function ResetPasswordPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    if (password !== confirmPassword) {
      setError('Konfirmasi password tidak cocok.')
      return
    }

    setSubmitting(true)
    try {
      await resetPassword(token, password)
      setSubmitted(true)
    } catch (err) {
      setError(
        err instanceof PasswordResetError
          ? err.message
          : 'Gagal mereset password, silakan coba lagi.',
      )
    } finally {
      setSubmitting(false)
    }
  }

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
        <h1>Reset Password</h1>

        {submitted ? (
          <>
            <p role="status" style={{ color: 'var(--text-secondary)', margin: 0 }}>
              Password berhasil direset. Silakan login dengan password baru kamu.
            </p>
            <button
              type="button"
              onClick={() => navigate('/login', { replace: true })}
              style={{
                minHeight: 'var(--touch-target)',
                borderRadius: 'var(--radius-md)',
                border: 'none',
                background: 'var(--accent)',
                color: 'var(--text-inverse)',
                font: 'var(--text-body)',
                fontWeight: 600,
              }}
            >
              Ke Halaman Login
            </button>
          </>
        ) : !token ? (
          <p role="alert" style={{ font: 'var(--text-small)', color: 'var(--danger, crimson)', margin: 0 }}>
            Tautan reset password tidak valid. Silakan minta tautan baru.
          </p>
        ) : (
          <>
            <div
              style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}
            >
              <label
                htmlFor="reset-password-new"
                style={{ font: 'var(--text-small)', color: 'var(--text-secondary)' }}
              >
                Password Baru
              </label>
              <input
                id="reset-password-new"
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

            <div
              style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}
            >
              <label
                htmlFor="reset-password-confirm"
                style={{ font: 'var(--text-small)', color: 'var(--text-secondary)' }}
              >
                Konfirmasi Password Baru
              </label>
              <input
                id="reset-password-confirm"
                name="confirmPassword"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                style={{
                  minHeight: 'var(--touch-target)',
                  borderRadius: 'var(--radius-md)',
                  border: 'var(--border-w) solid var(--border-default)',
                  padding: '0 var(--space-3)',
                  font: 'var(--text-body)',
                }}
              />
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
              {submitting ? 'Menyimpan…' : 'Reset Password'}
            </button>
          </>
        )}

        <Link to="/login" style={{ font: 'var(--text-small)', color: 'var(--text-secondary)' }}>
          Kembali ke halaman login
        </Link>
      </form>
    </div>
  )
}
