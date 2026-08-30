import { Link } from 'react-router-dom'

/** S-90 error/404 (screen-plan §2): calm page, CTA back to Dashboard. */
export default function NotFoundPage() {
  return (
    <section style={{ textAlign: 'center', padding: 'var(--space-16) 0' }}>
      <h1>Halaman tidak ditemukan</h1>
      <p style={{ color: 'var(--text-secondary)' }}>
        Alamat yang kamu tuju tidak ada atau sudah dipindahkan.
      </p>
      <Link to="/">Kembali ke Dashboard</Link>
    </section>
  )
}
