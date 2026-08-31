export type StatCardTone = 'default' | 'success' | 'danger' | 'warning'

/** One of the row-1 stat cards (screen-plan S-02: Grants/Denies/Unknown
 * rate/Latency p95). `value` is pre-formatted by the caller (e.g. "12",
 * "4.2%", "185 ms") so this component stays display-only. */
export default function StatCard({
  label,
  value,
  sublabel,
  tone = 'default',
  isLoading = false,
}: {
  label: string
  value: string
  sublabel?: string
  tone?: StatCardTone
  isLoading?: boolean
}) {
  if (isLoading) {
    return (
      <div className="dashboard-stat-card dashboard-stat-card--skeleton" aria-busy="true" />
    )
  }

  return (
    <div className={`dashboard-stat-card dashboard-stat-card--${tone}`}>
      <p className="dashboard-stat-card__label">{label}</p>
      <p className="dashboard-stat-card__value">{value}</p>
      {sublabel && <p className="dashboard-stat-card__sublabel">{sublabel}</p>}
    </div>
  )
}
