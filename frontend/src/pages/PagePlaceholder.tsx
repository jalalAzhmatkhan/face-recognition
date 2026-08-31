interface PagePlaceholderProps {
  title: string
  description: string
}

/** Reusable page header: title + a descriptive card underneath. */
export default function PagePlaceholder({ title, description }: PagePlaceholderProps) {
  return (
    <section className="page-placeholder">
      <header style={{ marginBottom: 'var(--space-4)' }}>
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
