import { decisionMeta } from './decisionMeta'
import type { TodaySummary } from './types'
import { ACCESS_DECISIONS } from './types'

/** "Panel ringkas hari ini" (screen-plan S-40): grant/deny/unknown/spoof
 * counts, seeded from `fetchTodaySummary` and incremented locally by
 * `LiveMonitoringPage` as SSE events arrive. */
export default function TodaySummaryPanel({
  summary,
  isLoading,
}: {
  summary: TodaySummary
  isLoading: boolean
}) {
  return (
    <section className="side-panel" aria-label="Ringkasan hari ini">
      <h3>Ringkasan hari ini</h3>
      {isLoading ? (
        <p className="side-panel__hint">Memuat…</p>
      ) : (
        <dl className="today-summary">
          {ACCESS_DECISIONS.map((decision) => {
            const meta = decisionMeta(decision)
            return (
              <div key={decision} className="today-summary__row">
                <dt style={{ color: meta.colorVar }}>
                  <span aria-hidden="true">{meta.icon}</span> {meta.label}
                </dt>
                <dd className="mono">{summary[decision]}</dd>
              </div>
            )
          })}
        </dl>
      )}
    </section>
  )
}
