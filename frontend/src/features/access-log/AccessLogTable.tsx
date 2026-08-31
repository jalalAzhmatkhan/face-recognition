import { decisionMeta } from '../live-monitoring/decisionMeta'
import { formatEventTime } from '../live-monitoring/relativeTime'
import { useUserName } from '../live-monitoring/useUserName'
import type { AccessEventPayload } from '../live-monitoring/types'

function formatMetric(value: number | null, digits: number): string {
  return value === null ? '—' : value.toFixed(digits)
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('id-ID')
  } catch {
    return iso
  }
}

function AccessLogRow({
  event,
  deviceName,
  onSelect,
}: {
  event: AccessEventPayload
  deviceName: string | null
  onSelect: (event: AccessEventPayload) => void
}) {
  const meta = decisionMeta(event.decision)
  const { name: userName, isLoading: userLoading } = useUserName(event.matched_user_id)

  return (
    <tr
      className="access-log-table__row"
      role="button"
      tabIndex={0}
      onClick={() => onSelect(event)}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect(event)
        }
      }}
    >
      <td className="mono access-log-table__time">
        {formatDate(event.occurred_at)} {formatEventTime(event.occurred_at)}
      </td>
      <td>{deviceName ?? event.device_id}</td>
      <td style={{ color: meta.colorVar, fontWeight: 600 }}>
        <span aria-hidden="true">{meta.icon}</span> {meta.label}
      </td>
      <td>{userLoading ? '…' : (userName ?? '—')}</td>
      <td className="mono">{formatMetric(event.similarity, 4)}</td>
      <td className="mono">{formatMetric(event.liveness_score, 4)}</td>
      <td className="mono">{event.model_version ?? '—'}</td>
      <td className="mono">{event.latency_ms === null ? '—' : `${event.latency_ms} ms`}</td>
    </tr>
  )
}

/**
 * S-42 dense table ("tabel padat, `text.small`, mono untuk skor"). Row
 * click opens the SAME S-41 drawer FE-06's feed already opens
 * (`AccessEventDrawer`, imported by `AccessLogPage` -- this component only
 * forwards the click via `onSelectEvent`, it doesn't render the drawer
 * itself).
 */
export default function AccessLogTable({
  events,
  deviceNames,
  isLoading,
  onSelectEvent,
}: {
  events: AccessEventPayload[]
  deviceNames: Map<string, string>
  isLoading: boolean
  onSelectEvent: (event: AccessEventPayload) => void
}) {
  if (isLoading) {
    return (
      <table className="access-log-table access-log-table--skeleton" aria-busy="true">
        <tbody>
          {[0, 1, 2, 3, 4].map((i) => (
            <tr key={i}>
              <td colSpan={8} className="access-log-table__skeleton-cell" />
            </tr>
          ))}
        </tbody>
      </table>
    )
  }

  if (events.length === 0) {
    return null // empty state handled by the page (empty-filter vs empty-data)
  }

  return (
    <div className="access-log-table-wrap">
      <table className="access-log-table">
        <thead>
          <tr>
            <th>Waktu</th>
            <th>Device</th>
            <th>Keputusan</th>
            <th>Matched User</th>
            <th>Similarity</th>
            <th>Liveness</th>
            <th>Model</th>
            <th>Latency</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => (
            <AccessLogRow
              key={event.id}
              event={event}
              deviceName={deviceNames.get(event.device_id) ?? null}
              onSelect={onSelectEvent}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}
