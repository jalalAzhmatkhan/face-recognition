import type { AccessEventSample } from './types'
import {
  computeConditionFlagBreakdown,
  computeDeviceClassBreakdown,
  computeRejectStageBreakdown,
} from './edgeCaseAggregation'
import { RECENT_ACCESS_EVENT_SAMPLE_SIZE } from './api'

const REJECT_STAGE_LABELS: Record<string, string> = {
  granted: 'Granted',
  detection: 'Deteksi wajah gagal',
  liveness: 'Liveness gagal',
  quality_gate: 'Quality gate (blur/gelap/kecil)',
  threshold: 'Di bawah threshold',
  policy: 'Ditolak kebijakan',
}

const CONDITION_FLAG_LABELS: Record<string, string> = {
  masked: 'Bermasker',
  dark: 'Gelap',
  blurry: 'Blur',
  low_res: 'Resolusi rendah',
  sunglasses: 'Kacamata hitam',
}

const DEVICE_CLASS_LABELS: Record<string, string> = {
  door_entry: 'Pintu Akses',
  attendance: 'Absensi',
  unknown: 'Belum Diklasifikasi',
}

function BreakdownList({
  rows,
  labels,
  emptyHint,
}: {
  rows: { key: string; count: number; pct: number }[]
  labels: Record<string, string>
  emptyHint: string
}) {
  const hasAny = rows.some((r) => r.count > 0)
  if (!hasAny) {
    return <p className="dashboard-panel__empty-hint">{emptyHint}</p>
  }
  return (
    <ul className="dashboard-funnel">
      {rows.map((row) => (
        <li key={row.key} className="dashboard-funnel__row">
          <span className="dashboard-funnel__label">{labels[row.key] ?? row.key}</span>
          <span className="dashboard-funnel__bar-track">
            <span className="dashboard-funnel__bar-fill" style={{ width: `${row.pct}%` }} />
          </span>
          <span className="dashboard-funnel__count mono">
            {row.count} ({row.pct}%)
          </span>
        </li>
      ))}
    </ul>
  )
}

/**
 * EC-FE-01 (TSD-edge-cases.md D-1) — reject-stage funnel + condition-flag +
 * device-class breakdown, computed CLIENT-SIDE from a bounded recent sample
 * of `GET /access-events` (see `api.ts::fetchRecentAccessEventSample`'s
 * docstring for why: the backend has no aggregation endpoint for any of
 * these three dimensions yet). Placed on the main Dashboard next to the
 * existing enrollment funnel — this page is already the project's
 * established "aggregate real access-event data client-side, disclose the
 * limitation" pattern (see `DashboardPage.tsx`'s own docstring), so this is
 * more natural here than adding a third distinct aggregation style to Live
 * Monitoring, which is built around a live per-event feed rather than
 * summary panels.
 */
export default function EdgeCaseFunnelPanel({
  events,
  isLoading,
}: {
  events: AccessEventSample[]
  isLoading: boolean
}) {
  if (isLoading) {
    return <div className="dashboard-panel dashboard-panel--skeleton" aria-busy="true" />
  }

  if (events.length === 0) {
    return (
      <section className="dashboard-panel" aria-label="Distribusi reject stage & kondisi">
        <h3 className="dashboard-panel__title">Distribusi Reject Stage &amp; Kondisi</h3>
        <p className="dashboard-panel__empty-hint">Belum ada access event untuk dianalisis.</p>
      </section>
    )
  }

  const rejectRows = computeRejectStageBreakdown(events)
  const flagRows = computeConditionFlagBreakdown(events)
  const deviceClassRows = computeDeviceClassBreakdown(events)

  return (
    <section className="dashboard-panel" aria-label="Distribusi reject stage & kondisi">
      <h3 className="dashboard-panel__title">Distribusi Reject Stage &amp; Kondisi</h3>
      <p className="dashboard-panel__hint">
        Dihitung dari {events.length} access event terbaru (maks. {RECENT_ACCESS_EVENT_SAMPLE_SIZE}
        ) — belum agregasi server-side penuh, lihat catatan implementasi EC-FE-01.
      </p>

      <div className="dashboard-panel__section">
        <h4 className="dashboard-panel__subtitle">Per Reject Stage</h4>
        <BreakdownList
          rows={rejectRows}
          labels={REJECT_STAGE_LABELS}
          emptyHint="Tidak ada data reject stage pada sampel ini."
        />
      </div>

      <div className="dashboard-panel__section">
        <h4 className="dashboard-panel__subtitle">Per Flag Kondisi</h4>
        <BreakdownList
          rows={flagRows}
          labels={CONDITION_FLAG_LABELS}
          emptyHint="Tidak ada flag kondisi pada sampel ini."
        />
      </div>

      <div className="dashboard-panel__section">
        <h4 className="dashboard-panel__subtitle">Per Device Class</h4>
        <BreakdownList
          rows={deviceClassRows}
          labels={DEVICE_CLASS_LABELS}
          emptyHint="Tidak ada data device class pada sampel ini."
        />
      </div>
    </section>
  )
}
