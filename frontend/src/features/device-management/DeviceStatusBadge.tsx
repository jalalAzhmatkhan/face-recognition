import type { DeviceStatus } from './types'
import { STATUS_COLOR_VARS, statusLabel } from './statusLabels'

interface DeviceStatusBadgeProps {
  status: DeviceStatus
  /** True when the backend computed the heartbeat as stale (see
   * `Settings.device_heartbeat_stale_after_seconds`). Only meaningful
   * combined with `status`:
   *  - ONLINE  + !is_stale -> genuinely alive (plain green badge)
   *  - ONLINE  + is_stale  -> DB still says ONLINE but the last heartbeat is
   *    old enough to be suspicious ("kemungkinan sudah mati tapi belum
   *    'resmi' OFFLINE di DB" per task instructions) — shown as an amber
   *    variant of the ONLINE badge plus an explicit caption, NOT as a plain
   *    OFFLINE badge, since the DB status genuinely is still ONLINE.
   *  - OFFLINE / DISABLED  -> `is_stale` carries no extra meaning (OFFLINE
   *    already implies a lapsed heartbeat; DISABLED is intentional, not a
   *    heartbeat problem) so it's ignored in both those cases.
   */
  isStale: boolean
}

export default function DeviceStatusBadge({ status, isStale }: DeviceStatusBadgeProps) {
  const staleOnline = status === 'ONLINE' && isStale
  const colors = staleOnline
    ? { bg: 'var(--warning-subtle-bg)', fg: 'var(--warning)' }
    : (STATUS_COLOR_VARS[status] ?? { bg: 'var(--bg-sunken)', fg: 'var(--text-secondary)' })

  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 2 }}>
      <span
        style={{
          display: 'inline-block',
          padding: '2px 10px',
          borderRadius: 'var(--radius-full)',
          font: 'var(--text-caption)',
          textTransform: 'uppercase',
          letterSpacing: '0.04em',
          background: colors.bg,
          color: colors.fg,
          whiteSpace: 'nowrap',
        }}
      >
        {statusLabel(status)}
      </span>
      {staleOnline && (
        <span style={{ font: 'var(--text-caption)', color: 'var(--warning)' }}>
          terakhir online lama
        </span>
      )}
    </span>
  )
}
