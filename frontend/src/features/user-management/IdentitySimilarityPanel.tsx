/**
 * EC-FE-03 (TSD-edge-cases.md D-4.4, ADMIN-only per task acceptance
 * criteria): shows high-similarity identity pairs involving a user so an
 * operator can see who they've been flagged as a lookalike of.
 *
 * GAP (backend): `identity_similarity_flags` (EC-BE-04) has a model +
 * repository only — confirmed by grepping `backend/app/routers/` there is NO
 * HTTP router exposing it. There is nothing to fetch. Per this task's
 * instructions (frontend-only scope; adding a backend endpoint is out of
 * scope for this role/task), this renders a placeholder explaining the gap
 * instead of a real list, and does NOT attempt to call any endpoint.
 *
 * Follow-up: once a backend task adds a read endpoint for
 * `identity_similarity_flags` (e.g. `GET /users/{id}/similarity-flags`),
 * replace this placeholder with a query using that endpoint and the
 * `IdentitySimilarityFlag` type already defined in `./types`.
 */
export default function IdentitySimilarityPanel() {
  return (
    <div
      style={{
        border: 'var(--border-w) solid var(--border-default)',
        borderRadius: 'var(--radius-md)',
        padding: 'var(--space-4)',
        background: 'var(--bg-sunken)',
        color: 'var(--text-secondary)',
      }}
    >
      <p style={{ margin: 0 }}>
        Menunggu endpoint backend. <code>identity_similarity_flags</code> (EC-BE-04) belum
        memiliki HTTP router untuk membaca pasangan high-similarity — tampilan pasangan
        similarity untuk user ini akan muncul di sini setelah endpoint tersedia.
      </p>
    </div>
  )
}
