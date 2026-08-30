interface PagePlaceholderProps {
  title: string
  screenId: string
  description: string
}

/**
 * Placeholder for screens from documentation/uiux/screen-plan.md.
 * Replaced by real implementations in FE-02..FE-09.
 */
export default function PagePlaceholder({
  title,
  screenId,
  description,
}: PagePlaceholderProps) {
  return (
    <section className="page-placeholder">
      <header style={{ marginBottom: 'var(--space-4)' }}>
        <p
          className="mono"
          style={{
            font: 'var(--text-caption)',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
            margin: 0,
            textTransform: 'uppercase',
            letterSpacing: '0.04em',
          }}
        >
          {screenId}
        </p>
        <h1>{title}</h1>
      </header>
      <div
        style={{
          background: 'var(--bg-surface)',
          border: 'var(--border-w) solid var(--border-default)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-sm)',
          padding: 'var(--space-8)',
          color: 'var(--text-secondary)',
        }}
      >
        <p style={{ margin: 0 }}>{description}</p>
      </div>
    </section>
  )
}
