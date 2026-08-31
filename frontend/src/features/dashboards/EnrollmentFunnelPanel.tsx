import { Link } from 'react-router-dom'
import type { EnrollmentFunnelStage, EnrollmentState } from './types'

const STAGE_LABELS: Record<EnrollmentState, string> = {
  CREATED: 'Dibuat',
  CONSENTED: 'Consent',
  CAPTURING: 'Merekam',
  CAPTURED: 'Selesai Rekam',
  QC_RUNNING: 'QC Berjalan',
  REJECTED_QUALITY: 'Ditolak QC',
  QC_PASSED: 'Lolos QC',
  EMBEDDING: 'Embedding',
  ENROLLED: 'Terdaftar',
  CANCELLED: 'Dibatalkan',
  REVOKED: 'Dicabut',
}

/** Enrollment funnel panel (screen-plan S-02, baris 3: "CREATED→ENROLLED,
 * FR-MON-02"). Bar widths are relative to the FIRST stage's count (the
 * funnel's starting cohort) rather than the max across all stages — a
 * later stage can never exceed an earlier one in a real funnel, so the
 * first stage IS the max by construction whenever there's any data at all. */
export default function EnrollmentFunnelPanel({
  stages,
  isLoading,
}: {
  stages: EnrollmentFunnelStage[]
  isLoading: boolean
}) {
  if (isLoading) {
    return <div className="dashboard-panel dashboard-panel--skeleton" aria-busy="true" />
  }

  const total = stages[0]?.count ?? 0

  return (
    <section className="dashboard-panel" aria-label="Enrollment funnel">
      <h3 className="dashboard-panel__title">Enrollment Funnel</h3>
      {total === 0 ? (
        <div className="dashboard-funnel__empty">
          <p className="dashboard-panel__empty-hint">Belum ada sesi enrollment.</p>
          <Link to="/users" className="dashboard-funnel__empty-cta">
            Tambah user pertama
          </Link>
        </div>
      ) : (
        <ul className="dashboard-funnel">
          {stages.map((stage) => {
            const widthPct = total > 0 ? Math.round((stage.count / total) * 100) : 0
            return (
              <li key={stage.state} className="dashboard-funnel__row">
                <span className="dashboard-funnel__label">{STAGE_LABELS[stage.state]}</span>
                <span className="dashboard-funnel__bar-track">
                  <span
                    className="dashboard-funnel__bar-fill"
                    style={{ width: `${widthPct}%` }}
                  />
                </span>
                <span className="dashboard-funnel__count mono">{stage.count}</span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
