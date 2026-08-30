import { useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, LoginError } from '../lib/authToken'

/** S-01 Login (screen-plan §2). FE-02: real email+password login against
 * `POST /auth/login` (BE-03) — the earlier SSO-disabled placeholder is
 * gone now that the backend endpoint exists. */
export default function LoginPage() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login({ email, password })
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof LoginError ? err.message : 'Gagal login, silakan coba lagi.')
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
        <h1>FRAC Console</h1>
        <p style={{ color: 'var(--text-secondary)', margin: 0 }}>
          Face Recognition Access Control
        </p>

        <div style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
          <label htmlFor="login-email" style={{ font: 'var(--text-small)', color: 'var(--text-secondary)' }}>
            Email
          </label>
          <input
            id="login-email"
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
          <label htmlFor="login-password" style={{ font: 'var(--text-small)', color: 'var(--text-secondary)' }}>
            Password
          </label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
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
          {submitting ? 'Masuk…' : 'Masuk'}
        </button>

        <p
          style={{
            font: 'var(--text-small)',
            color: 'var(--text-muted)',
            margin: 0,
          }}
        >
          Sistem ini memproses data biometrik dan tunduk pada UU PDP.
        </p>
      </form>
    </div>
  )
}
