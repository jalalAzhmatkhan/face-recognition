import type { DailyDecisionCount } from './types'

const VIEWBOX_WIDTH = 700
const VIEWBOX_HEIGHT = 200
const TOP_PADDING = 12
const BOTTOM_PADDING = 12

function formatShortDate(dateIso: string): string {
  const [, month, day] = dateIso.split('-')
  return `${day}/${month}`
}

function buildPoints(values: number[], max: number): string {
  const usableHeight = VIEWBOX_HEIGHT - TOP_PADDING - BOTTOM_PADDING
  const step = values.length > 1 ? VIEWBOX_WIDTH / (values.length - 1) : 0
  return values
    .map((value, index) => {
      const x = values.length > 1 ? index * step : VIEWBOX_WIDTH / 2
      const ratio = max > 0 ? value / max : 0
      const y = VIEWBOX_HEIGHT - BOTTOM_PADDING - ratio * usableHeight
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

/**
 * Hand-rolled SVG line chart (screen-plan S-02: "grafik garis grants/denies
 * 14 hari") — no charting library is installed anywhere in this frontend
 * (`package.json` has none), and this project has otherwise stayed
 * dependency-light, so a small inline SVG polyline matches existing
 * convention better than adding a new dependency for two lines.
 */
export default function GrantsDeniesChart({
  data,
  isLoading,
}: {
  data: DailyDecisionCount[]
  isLoading: boolean
}) {
  if (isLoading) {
    return <div className="dashboard-chart dashboard-chart--skeleton" aria-busy="true" />
  }

  const hasAnyData = data.some((row) => row.granted > 0 || row.denied > 0)
  if (data.length === 0 || !hasAnyData) {
    return (
      <div className="dashboard-chart dashboard-chart--empty">
        <p>Belum ada data akses dalam periode ini.</p>
      </div>
    )
  }

  const max = Math.max(1, ...data.map((row) => Math.max(row.granted, row.denied)))
  const grantedPoints = buildPoints(
    data.map((row) => row.granted),
    max,
  )
  const deniedPoints = buildPoints(
    data.map((row) => row.denied),
    max,
  )

  return (
    <div className="dashboard-chart">
      <svg
        className="dashboard-chart__svg"
        viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        role="img"
        aria-label="Grafik grants dan denies harian"
      >
        <polyline
          points={grantedPoints}
          fill="none"
          stroke="var(--success)"
          strokeWidth="2.5"
        />
        <polyline points={deniedPoints} fill="none" stroke="var(--danger)" strokeWidth="2.5" />
      </svg>
      <div className="dashboard-chart__legend">
        <span className="dashboard-chart__legend-item">
          <span className="dashboard-chart__swatch" style={{ background: 'var(--success)' }} />
          Grants
        </span>
        <span className="dashboard-chart__legend-item">
          <span className="dashboard-chart__swatch" style={{ background: 'var(--danger)' }} />
          Denies
        </span>
      </div>
      <div className="dashboard-chart__axis">
        <span>{formatShortDate(data[0].dateIso)}</span>
        <span>{formatShortDate(data[data.length - 1].dateIso)}</span>
      </div>
    </div>
  )
}
