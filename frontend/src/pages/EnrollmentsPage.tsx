import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PagePlaceholder from './PagePlaceholder'

/**
 * S-30/S-31 placeholder. The session list/detail (S-31) lands in FE-05;
 * for now this only provides an entry point into the FE-04 capture wizard
 * for a known enrollment session id.
 */
export default function EnrollmentsPage() {
  const navigate = useNavigate()
  const [sessionId, setSessionId] = useState('')

  return (
    <>
      <PagePlaceholder
        screenId="S-30/S-31"
        title="Enrollment"
        description="Daftar & status sesi enrollment akan diimplementasikan pada FE-05."
      />
      <section
        style={{
          marginTop: 'var(--space-6)',
          background: 'var(--bg-surface)',
          border: 'var(--border-w) solid var(--border-default)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-sm)',
          padding: 'var(--space-8)',
          display: 'flex',
          flexDirection: 'column',
          gap: 'var(--space-4)',
        }}
      >
        <h2 style={{ margin: 0 }}>Mulai Capture Enrollment</h2>
        <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
          Masukkan ID sesi enrollment untuk membuka wizard capture 360°
          (FE-04).
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            if (sessionId.trim()) {
              navigate(`/enrollments/${sessionId.trim()}/capture`)
            }
          }}
          style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap' }}
        >
          <label htmlFor="enrollment-session-id" style={{ display: 'none' }}>
            ID Sesi Enrollment
          </label>
          <input
            id="enrollment-session-id"
            name="sessionId"
            value={sessionId}
            onChange={(event) => setSessionId(event.target.value)}
            placeholder="ID sesi enrollment"
            style={{
              minHeight: 'var(--touch-target)',
              padding: '0 var(--space-3)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--border-default)',
              flex: '1 1 240px',
            }}
          />
          <button
            type="submit"
            disabled={!sessionId.trim()}
            style={{
              minHeight: 'var(--touch-target)',
              minWidth: 'var(--touch-target)',
              padding: '0 var(--space-6)',
              borderRadius: 'var(--radius-md)',
              border: 'var(--border-w) solid var(--accent)',
              background: 'var(--accent)',
              color: 'var(--text-inverse)',
              cursor: sessionId.trim() ? 'pointer' : 'not-allowed',
              opacity: sessionId.trim() ? 1 : 0.5,
            }}
          >
            Buka Capture
          </button>
        </form>
      </section>
    </>
  )
}
