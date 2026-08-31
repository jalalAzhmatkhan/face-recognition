import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { forgotPassword, PasswordResetError } from '../lib/authToken'

/** Forgot-password entry point, reachable at `/forgot-password` (top-level
 * sibling of `/login`, outside `AuthGuard` — same reasoning as `/login`
 * itself). Always shows the identical success message regardless of
 * whether the email matched an account (NFR-SEC-04, mirrors the backend's
 * `auth_service.request_password_reset`), so this screen can never be used
 * to enumerate registered emails. */
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await forgotPassword(email)
      setSubmitted(true)
    } catch (err) {
      setError(
        err instanceof PasswordResetError
          ? err.message
          : 'Gagal mengirim tautan reset password, silakan coba lagi.',
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
        <h1>Lupa Password</h1>

        {submitted ? (
          <p role="status" style={{ color: 'var(--text-secondary)', margin: 0 }}>
            Jika email terdaftar, tautan reset password telah dikirim. Silakan periksa kotak
            masuk kamu.
          </p>
        ) : (
          <>
            <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
              Masukkan email akun kamu, kami akan mengirim tautan untuk membuat password baru.
            </p>

            <div
              style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}
            >
              <label
                htmlFor="forgot-password-email"
                style={{ font: 'var(--text-small)', color: 'var(--text-secondary)' }}
              >
                Email
              </label>
              <input
                id="forgot-password-email"
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
              {submitting ? 'Mengirim…' : 'Kirim Tautan Reset'}
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
