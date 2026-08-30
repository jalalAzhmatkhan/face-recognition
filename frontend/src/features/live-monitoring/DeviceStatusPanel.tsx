import { formatRelativeTime } from './relativeTime'
import type { DeviceSummary } from './types'

interface DeviceStatusPanelProps {
  devices: DeviceSummary[] | null
  isLoading: boolean
  /** `GET /devices` is ADMIN/OPERATOR only (backend RBAC) — VIEWER sessions
   * never issue the request at all (see `LiveMonitoringPage`), so this flag
   * lets the panel show an honest "not available for your role" message
   * instead of a spinner that never resolves. */
  allowedForRole: boolean
}

function isOnline(device: DeviceSummary): boolean {
  return device.status === 'ONLINE' && !device.is_stale
}

/** "Panel device (online/offline dot + heartbeat terakhir)" (screen-plan
 * S-40). Data comes from `GET /devices`, polled — devices have no
 * live-push channel, so this is `refetchInterval`, not SSE. */
export default function DeviceStatusPanel({
  devices,
  isLoading,
  allowedForRole,
}: DeviceStatusPanelProps) {
  return (
    <section className="side-panel" aria-label="Status device">
      <h3>Status device</h3>
      {!allowedForRole ? (
        <p className="side-panel__hint">
          Panel ini memerlukan role ADMIN atau OPERATOR.
        </p>
      ) : isLoading ? (
        <p className="side-panel__hint">Memuat…</p>
      ) : !devices || devices.length === 0 ? (
        <p className="side-panel__hint">Belum ada device terdaftar.</p>
      ) : (
        <ul className="device-status-list">
          {devices.map((device) => (
            <li key={device.id} className="device-status-list__item">
              <span
                aria-hidden="true"
                className={`live-dot ${isOnline(device) ? 'live-dot--pulsing' : ''}`}
                style={{
                  background: isOnline(device) ? 'var(--success)' : 'var(--text-muted)',
                }}
              />
              <span className="device-status-list__name">{device.name}</span>
              <span className="device-status-list__heartbeat mono">
                {formatRelativeTime(device.last_heartbeat_at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
