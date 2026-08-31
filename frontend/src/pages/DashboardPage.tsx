import { useQuery } from '@tanstack/react-query'
import {
  describeApiError,
  fetchDailyDecisionCounts,
  fetchEnrollmentFunnel,
  fetchProductionModel,
  fetchTodayCounts,
} from '../features/dashboards/api'
import StatCard from '../features/dashboards/StatCard'
import GrantsDeniesChart from '../features/dashboards/GrantsDeniesChart'
import ProductionModelPanel from '../features/dashboards/ProductionModelPanel'
import EnrollmentFunnelPanel from '../features/dashboards/EnrollmentFunnelPanel'
import '../features/dashboards/Dashboards.css'

const TREND_DAYS = 14
const LATENCY_BUDGET_MS = 300

/**
 * S-02 Dashboard — FE-07 scope. All roles (ADMIN/OPERATOR/VIEWER) can read
 * every backend call this page makes (`GET /access-events`, `/models`,
 * `/enrollments` are all staff-read for all three roles), so unlike FE-06's
 * device panel this page needs no per-card role gating.
 *
 * There is no backend aggregation endpoint for any of these 5 metrics (see
 * `features/dashboards/api.ts` module docstring on each function) — every
 * number here comes from real `GET .../?...&limit=1` calls read for their
 * `.total` field, satisfying FR-MON-02 ("semua metrik tampil dari data
 * nyata") without a new backend contract.
 *
 * **Scope note**: the screen-plan's wireframe (S-02) also describes an
 * "alert aktif" panel (spoof/drift/device offline, FR-MON-04) alongside the
 * enrollment funnel. That panel is deliberately NOT built here — FE-07's
 * own task description and acceptance criteria only cite FR-MON-02 (these
 * 5 metrics), and IN-08's drift/unknown-rate/latency-SLO alerts are
 * Prometheus gauges inside `ai-inference` with no bridge to any backend API
 * this frontend could read yet. Building that panel with only
 * spoof-suspected events + device status (the parts that ARE reachable)
 * would silently under-deliver what the wireframe implies; leaving it out
 * entirely is the more honest call until a real IN-08-to-backend bridge
 * exists.
 */
export default function DashboardPage() {
  const todayQuery = useQuery({
    queryKey: ['dashboards', 'today-counts'],
    queryFn: () => fetchTodayCounts(),
    refetchInterval: 60_000,
  })

  const trendQuery = useQuery({
    queryKey: ['dashboards', 'trend', TREND_DAYS],
    queryFn: () => fetchDailyDecisionCounts(TREND_DAYS),
    refetchInterval: 60_000,
  })

  const modelQuery = useQuery({
    queryKey: ['dashboards', 'production-model'],
    queryFn: () => fetchProductionModel(),
  })

  const funnelQuery = useQuery({
    queryKey: ['dashboards', 'enrollment-funnel'],
    queryFn: () => fetchEnrollmentFunnel(),
  })

  const today = todayQuery.data
  const todayTotal = today
    ? today.GRANTED + today.DENIED + today.UNKNOWN + today.SPOOF_SUSPECTED
    : 0
  const unknownRatePct =
    today && todayTotal > 0 ? Math.round((today.UNKNOWN / todayTotal) * 1000) / 10 : null

  const latencyP95 = modelQuery.data?.latency_ms_p95 ?? null
  const latencyTone = latencyP95 === null ? 'default' : latencyP95 > LATENCY_BUDGET_MS ? 'danger' : 'success'

  const hasLoadError =
    todayQuery.isError || trendQuery.isError || modelQuery.isError || funnelQuery.isError
  const firstError =
    todayQuery.error ?? trendQuery.error ?? modelQuery.error ?? funnelQuery.error

  return (
    <div className="dashboard-page">
      <header className="dashboard-page__header">
        <h1>Dashboard</h1>
      </header>

      {hasLoadError && (
        <p role="alert" style={{ color: 'var(--danger)' }}>
          {describeApiError(firstError)}
        </p>
      )}

      <div className="dashboard-stats-row">
        <StatCard
          label="Grants hari ini"
          value={String(today?.GRANTED ?? 0)}
          tone="success"
          isLoading={todayQuery.isLoading}
        />
        <StatCard
          label="Denies hari ini"
          value={String(today?.DENIED ?? 0)}
          tone="danger"
          isLoading={todayQuery.isLoading}
        />
        <StatCard
          label="Unknown rate"
          value={unknownRatePct === null ? '—' : `${unknownRatePct}%`}
          sublabel={todayTotal === 0 ? 'Belum ada percobaan akses hari ini' : undefined}
          tone="warning"
          isLoading={todayQuery.isLoading}
        />
        <StatCard
          label="Latency p95"
          value={latencyP95 === null ? '—' : `${latencyP95} ms`}
          sublabel={`Budget ${LATENCY_BUDGET_MS} ms (model produksi)`}
          tone={latencyTone}
          isLoading={modelQuery.isLoading}
        />
      </div>

      <div className="dashboard-row">
        <GrantsDeniesChart data={trendQuery.data ?? []} isLoading={trendQuery.isLoading} />
        <ProductionModelPanel model={modelQuery.data ?? null} isLoading={modelQuery.isLoading} />
      </div>

      <div className="dashboard-row dashboard-row--funnel">
        <EnrollmentFunnelPanel
          stages={funnelQuery.data ?? []}
          isLoading={funnelQuery.isLoading}
        />
      </div>
    </div>
  )
}
