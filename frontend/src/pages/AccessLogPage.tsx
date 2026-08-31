import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import AccessEventDrawer from '../features/live-monitoring/AccessEventDrawer'
import { describeApiError, listAccessEvents, listDevices } from '../features/live-monitoring/api'
import type { AccessDecision, AccessEventPayload } from '../features/live-monitoring/types'
import AccessLogFilterBar from '../features/access-log/AccessLogFilterBar'
import AccessLogTable from '../features/access-log/AccessLogTable'
import { buildAccessLogCsv, downloadCsv } from '../features/access-log/csvExport'
import { getCurrentRole } from '../lib/authToken'
import '../features/live-monitoring/LiveMonitoring.css'
import '../features/access-log/AccessLog.css'

const PAGE_SIZE = 50

function toFromIso(dateStr: string): string | undefined {
  if (!dateStr) return undefined
  const d = new Date(`${dateStr}T00:00:00`)
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString()
}

function toToIso(dateStr: string): string | undefined {
  if (!dateStr) return undefined
  const d = new Date(`${dateStr}T23:59:59.999`)
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString()
}

/**
 * S-42 Access Log (FE-11) — server-side filtered/paginated history of
 * `GET /access-events`, complementing FE-06's live SSE feed for "audit
 * tanpa live-stream" (FR-INF-04/FR-MON-02). Row click reuses FE-10's S-41
 * drawer (`AccessEventDrawer`) verbatim, imported from `live-monitoring/`
 * rather than duplicated — that module's `useUserName`/`decisionMeta`/
 * `AccessEventPayload` are the SAME shared contract between the SSE feed
 * and this REST list (see `live-monitoring/types.ts`'s own docstring),
 * and `useUserName.ts` already sets a precedent of importing across
 * `features/*` for exactly this reason.
 *
 * **Known gaps, by design, not oversights**:
 * - **No user filter.** The task-breakdown mentions filtering by "user",
 *   but `GET /access-events` has no `matched_user_id` query parameter at
 *   all (confirmed against `backend/app/routers/access_events.py` and its
 *   repository) — omitted rather than shipping a text input that
 *   can't actually filter anything server-side.
 * - **CSV export covers only the currently loaded page**, not the entire
 *   filtered result set — there is no backend CSV-export endpoint, and
 *   fetching every page of a wide filter (up to 200/request, offset-only
 *   pagination over a table partitioned by month) just to export it
 *   client-side would be an unbounded, possibly very slow operation for a
 *   feature this task doesn't ask to build. The export button's own label
 *   says "halaman ini" so this is disclosed, not hidden.
 */
export default function AccessLogPage() {
  const role = getCurrentRole()
  const canSeeDevices = role === 'ADMIN' || role === 'OPERATOR'
  const queryClient = useQueryClient()

  const [deviceFilter, setDeviceFilter] = useState('')
  const [decisionFilter, setDecisionFilter] = useState<AccessDecision | ''>('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedEvent, setSelectedEvent] = useState<AccessEventPayload | null>(null)
  const [reviewedSpoofIds, setReviewedSpoofIds] = useState<Set<string>>(new Set())

  const hasActiveFilter = Boolean(deviceFilter || decisionFilter || dateFrom || dateTo)

  function resetToFirstPage<T>(setter: (value: T) => void) {
    return (value: T) => {
      setOffset(0)
      setter(value)
    }
  }

  const devicesQuery = useQuery({
    queryKey: ['devices', 'access-log'],
    queryFn: () => listDevices({ limit: 200 }),
    enabled: canSeeDevices,
  })

  const listQuery = useQuery({
    queryKey: [
      'access-events',
      'log',
      { deviceId: deviceFilter, decision: decisionFilter, from: dateFrom, to: dateTo, offset },
    ],
    queryFn: () =>
      listAccessEvents({
        deviceId: deviceFilter || undefined,
        decision: decisionFilter || undefined,
        from: toFromIso(dateFrom),
        to: toToIso(dateTo),
        limit: PAGE_SIZE,
        offset,
      }),
  })

  const deviceNames = new Map<string, string>()
  for (const device of devicesQuery.data?.items ?? []) deviceNames.set(device.id, device.name)

  const events = listQuery.data?.items ?? []
  const total = listQuery.data?.total ?? 0
  const hasPrev = offset > 0
  const hasNext = offset + PAGE_SIZE < total

  function markReviewed(id: string): void {
    setReviewedSpoofIds((prev) => new Set(prev).add(id))
  }

  function handleExportCsv(): void {
    const userNames = new Map<string, string>()
    for (const event of events) {
      if (!event.matched_user_id) continue
      const cached = queryClient.getQueryData<{ full_name: string }>(['user', event.matched_user_id])
      if (cached?.full_name) userNames.set(event.matched_user_id, cached.full_name)
    }
    const csv = buildAccessLogCsv(events, deviceNames, userNames)
    const dateStamp = new Date().toISOString().slice(0, 10)
    downloadCsv(`access-log-${dateStamp}.csv`, csv)
  }

  return (
    <section className="access-log-page">
      <header className="access-log-page__header">
        <h1>Access Log</h1>
      </header>

      <AccessLogFilterBar
        deviceId={deviceFilter}
        onDeviceIdChange={resetToFirstPage(setDeviceFilter)}
        devices={canSeeDevices ? (devicesQuery.data?.items ?? []) : []}
        decision={decisionFilter}
        onDecisionChange={resetToFirstPage(setDecisionFilter)}
        dateFrom={dateFrom}
        onDateFromChange={resetToFirstPage(setDateFrom)}
        dateTo={dateTo}
        onDateToChange={resetToFirstPage(setDateTo)}
      />

      <div className="access-log-page__section">
        <div className="access-log-page__toolbar">
          <p className="access-log-page__export-hint">
            {total > 0 ? `${total} event ditemukan` : null}
          </p>
          <div>
            <button type="button" onClick={handleExportCsv} disabled={events.length === 0}>
              Export CSV (halaman ini)
            </button>
          </div>
        </div>

        {listQuery.isLoading && (
          <AccessLogTable
            events={[]}
            deviceNames={deviceNames}
            isLoading
            onSelectEvent={setSelectedEvent}
          />
        )}

        {listQuery.isError && (
          <p role="alert" style={{ color: 'var(--danger)' }}>
            {describeApiError(listQuery.error)}
          </p>
        )}

        {!listQuery.isLoading && !listQuery.isError && events.length === 0 && (
          <div className="access-log-empty">
            <p className="access-log-empty__title">
              {hasActiveFilter ? 'Tidak ada hasil untuk filter ini' : 'Belum ada access event'}
            </p>
            <p className="access-log-empty__hint">
              {hasActiveFilter
                ? 'Coba ubah atau hapus filter untuk melihat event lain.'
                : 'Event akses akan muncul di sini setelah ada percobaan akses.'}
            </p>
          </div>
        )}

        {!listQuery.isLoading && !listQuery.isError && events.length > 0 && (
          <AccessLogTable
            events={events}
            deviceNames={deviceNames}
            isLoading={false}
            onSelectEvent={setSelectedEvent}
          />
        )}

        <div className="access-log-page__pagination">
          <span className="access-log-page__pagination-count">
            {total > 0
              ? `Menampilkan ${offset + 1}-${Math.min(offset + PAGE_SIZE, total)} dari ${total}`
              : null}
          </span>
          <div className="access-log-page__pagination-buttons">
            <button
              type="button"
              disabled={!hasPrev}
              onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}
            >
              Sebelumnya
            </button>
            <button
              type="button"
              disabled={!hasNext}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Berikutnya
            </button>
          </div>
        </div>
      </div>

      {selectedEvent && (
        <AccessEventDrawer
          event={selectedEvent}
          deviceName={deviceNames.get(selectedEvent.device_id) ?? null}
          reviewed={reviewedSpoofIds.has(selectedEvent.id)}
          onMarkReviewed={markReviewed}
          onClose={() => setSelectedEvent(null)}
        />
      )}
    </section>
  )
}
