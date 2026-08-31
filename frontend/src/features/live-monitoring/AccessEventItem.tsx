import { decisionMeta } from './decisionMeta'
import { formatEventTime } from './relativeTime'
import { useUserName } from './useUserName'
import type { AccessEventPayload } from './types'

interface AccessEventItemProps {
  event: AccessEventPayload
  deviceName: string | null
  isNew: boolean
  reviewed: boolean
  onMarkReviewed: (id: string) => void
  /** FE-10: opens the S-41 detail drawer for this event. */
  onSelect: (event: AccessEventPayload) => void
}

function formatMetric(value: number | null, digits: number, unit: string): string {
  if (value === null) return '—'
  return `${value.toFixed(digits)}${unit}`
}

/** One row in the live feed (screen-plan S-40 item spec: waktu, device,
 * keputusan ikon+warna+label, nama user, similarity & latency mono kecil).
 * `isNew` drives the slide-in + decaying highlight animation for freshly
 * arrived events (CSS transition only, per task instructions — no
 * animation library). */
export default function AccessEventItem({
  event,
  deviceName,
  isNew,
  reviewed,
  onMarkReviewed,
  onSelect,
}: AccessEventItemProps) {
  const meta = decisionMeta(event.decision)
  const { name: userName, isLoading: userLoading } = useUserName(event.matched_user_id)
  const isSpoof = event.decision === 'SPOOF_SUSPECTED'

  return (
    <li
      className={isNew ? 'access-event-item access-event-item--new' : 'access-event-item'}
      style={{
        borderLeft: `${meta.emphasis === 'strong' ? 'var(--border-w-strong)' : 'var(--border-w)'} solid ${meta.colorVar}`,
        background: meta.bgVar,
      }}
      data-decision={event.decision}
      data-testid="access-event-item"
    >
      <button
        type="button"
        className="access-event-item__row access-event-item__row--clickable"
        onClick={() => onSelect(event)}
      >
        <span className="mono access-event-item__time">{formatEventTime(event.occurred_at)}</span>
        <span className="access-event-item__device">{deviceName ?? event.device_id}</span>
        <span
          className="access-event-item__decision"
          style={{ color: meta.colorVar }}
        >
          <span aria-hidden="true">{meta.icon}</span> {meta.label}
        </span>
        <span className="access-event-item__user">
          {userLoading ? '…' : (userName ?? '—')}
        </span>
        <span className="mono access-event-item__metrics">
          {formatMetric(event.similarity, 2, '')} · {event.latency_ms ?? '—'}ms
        </span>
      </button>
      {isSpoof && (
        <div className="access-event-item__spoof-action">
          {reviewed ? (
            <span className="access-event-item__reviewed-note">
              Ditandai ditinjau untuk sesi ini saja
            </span>
          ) : (
            <button type="button" onClick={() => onMarkReviewed(event.id)}>
              Tandai ditinjau
            </button>
          )}
          <span className="access-event-item__reviewed-note">
            (belum tersimpan permanen — belum ada endpoint backend untuk ini)
          </span>
        </div>
      )}
    </li>
  )
}
