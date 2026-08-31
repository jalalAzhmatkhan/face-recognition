import { Link } from 'react-router-dom'
import { decisionMeta } from './decisionMeta'
import { formatPreciseEventTime } from './relativeTime'
import { useUserName } from './useUserName'
import type { AccessEventPayload } from './types'

interface AccessEventDrawerProps {
  event: AccessEventPayload
  deviceName: string | null
  reviewed: boolean
  onMarkReviewed: (id: string) => void
  onClose: () => void
}

function formatMetric(value: number | null, digits: number): string {
  return value === null ? '—' : value.toFixed(digits)
}

/**
 * S-41 Access Event Detail drawer (FE-10) — opened from a feed row click
 * (FE-06). No separate `GET /access-events/{id}` endpoint exists (and none
 * is needed): the full `AccessEventResponse` shape is already present on
 * every row `GET /access-events`/the SSE stream returns, so this component
 * is populated entirely from the `event` object the caller already has in
 * memory — see task-breakdown.md's acceptance criteria ("detail lengkap 1
 * access event tampil akurat dari `GET /access-events`").
 *
 * Two contextual actions from the screen-plan, both with real limitations
 * worth being upfront about:
 * - "Lihat user": only rendered when `matched_user_id` is set, links to
 *   S-20 (`/users/:id`).
 * - "Tandai ditinjau": only for `SPOOF_SUSPECTED` events. Mirrors
 *   `AccessEventItem.tsx`'s existing session-only client state — there is
 *   still no backend column/endpoint for a persisted "reviewed" flag (see
 *   that component's identical caveat text), so marking reviewed here uses
 *   the SAME `reviewedSpoofIds`/`onMarkReviewed` the row's own inline
 *   action already uses (one shared piece of state, two UI entry points).
 *
 * "Frame event (presigned)" from the wireframe has NO backend support at
 * all yet — there is no endpoint that returns a presigned GET/download URL
 * for a `media_objects` row by id (only the enrollment upload PUT-presign
 * exists). Rather than silently omitting this section (which would look
 * like "there's no frame" even when one IS retained), it's rendered as an
 * honest "retained but not previewable yet" note when `frame_media_id` is
 * present, and omitted entirely when it isn't.
 */
export default function AccessEventDrawer({
  event,
  deviceName,
  reviewed,
  onMarkReviewed,
  onClose,
}: AccessEventDrawerProps) {
  const meta = decisionMeta(event.decision)
  const { name: userName, isLoading: userLoading } = useUserName(event.matched_user_id)
  const isSpoof = event.decision === 'SPOOF_SUSPECTED'

  return (
    <>
      <div
        role="presentation"
        className="access-event-drawer-overlay"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="access-event-drawer-title"
        className="access-event-drawer"
      >
        <div className="access-event-drawer__header">
          <div
            id="access-event-drawer-title"
            className="access-event-drawer__decision"
            style={{ color: meta.colorVar }}
          >
            <span aria-hidden="true">{meta.icon}</span> {meta.label}
          </div>
          <button
            type="button"
            className="access-event-drawer__close"
            onClick={onClose}
            aria-label="Tutup detail event"
          >
            ×
          </button>
        </div>

        <p className="access-event-drawer__time mono">
          {formatPreciseEventTime(event.occurred_at)}
        </p>

        <dl className="access-event-drawer__fields">
          <div>
            <dt>Device</dt>
            <dd>{deviceName ?? event.device_id}</dd>
          </div>
          <div>
            <dt>Matched user</dt>
            <dd>{userLoading ? 'Memuat…' : (userName ?? '—')}</dd>
          </div>
          <div>
            <dt>Similarity score</dt>
            <dd className="mono">{formatMetric(event.similarity, 4)}</dd>
          </div>
          <div>
            <dt>Liveness score</dt>
            <dd className="mono">{formatMetric(event.liveness_score, 4)}</dd>
          </div>
          <div>
            <dt>Model version</dt>
            <dd className="mono">{event.model_version ?? '—'}</dd>
          </div>
          <div>
            <dt>Latency</dt>
            <dd className="mono">{event.latency_ms === null ? '—' : `${event.latency_ms} ms`}</dd>
          </div>
        </dl>

        {event.frame_media_id && (
          <p className="access-event-drawer__frame-hint">
            Frame event tersimpan (diretensi) — pratinjau belum didukung, endpoint presigned view
            untuk frame belum ada di backend.
          </p>
        )}

        <div className="access-event-drawer__actions">
          {event.matched_user_id && (
            <Link to={`/users/${event.matched_user_id}`}>Lihat user</Link>
          )}
          {isSpoof &&
            (reviewed ? (
              <p className="access-event-drawer__reviewed-note">
                Ditandai ditinjau untuk sesi ini saja
              </p>
            ) : (
              <button type="button" onClick={() => onMarkReviewed(event.id)}>
                Tandai ditinjau
              </button>
            ))}
          {isSpoof && (
            <p className="access-event-drawer__reviewed-note">
              (belum tersimpan permanen — belum ada endpoint backend untuk ini)
            </p>
          )}
        </div>
      </div>
    </>
  )
}
