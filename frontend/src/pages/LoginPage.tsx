/**
 * S-01 Login (screen-plan §2). Placeholder — SSO/OIDC wiring lands in FE-02.
 */
export default function LoginPage() {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        padding: 'var(--space-6)',
      }}
    >
      <div
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
        <button
          type="button"
          disabled
          style={{
            minHeight: 'var(--touch-target)',
            borderRadius: 'var(--radius-md)',
            border: 'none',
            background: 'var(--accent)',
            color: 'var(--text-inverse)',
            font: 'var(--text-body)',
            fontWeight: 600,
            opacity: 0.6,
          }}
        >
          Masuk dengan SSO (segera)
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
      </div>
    </div>
  )
}
