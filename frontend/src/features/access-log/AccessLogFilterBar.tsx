import { decisionMeta } from '../live-monitoring/decisionMeta'
import type { AccessDecision, DeviceSummary } from '../live-monitoring/types'
import { ACCESS_DECISIONS } from '../live-monitoring/types'

interface AccessLogFilterBarProps {
  deviceId: string
  onDeviceIdChange: (value: string) => void
  devices: DeviceSummary[] | null
  decision: AccessDecision | ''
  onDecisionChange: (value: AccessDecision | '') => void
  dateFrom: string
  onDateFromChange: (value: string) => void
  dateTo: string
  onDateToChange: (value: string) => void
}

/**
 * S-42 filter row: device, keputusan, rentang tanggal. Mirrors
 * `live-monitoring/FilterBar.tsx`'s device/decision dropdown shape (same
 * CSS classes, reused rather than duplicated) minus the SSE connection
 * indicator, plus two native `<input type="date">` fields for the
 * date-range filter live-monitoring doesn't need.
 *
 * **No user filter** (task-breakdown mentions "filter ... user", but `GET
 * /access-events` has no `matched_user_id` query parameter at all -- see
 * `AccessLogPage`'s module docstring for the full gap note). Omitted
 * entirely rather than shipping a text input that can't actually filter
 * anything server-side.
 */
export default function AccessLogFilterBar({
  deviceId,
  onDeviceIdChange,
  devices,
  decision,
  onDecisionChange,
  dateFrom,
  onDateFromChange,
  dateTo,
  onDateToChange,
}: AccessLogFilterBarProps) {
  return (
    <div className="live-monitoring-filterbar">
      <label className="live-monitoring-filterbar__field">
        <span>Device</span>
        <select
          value={deviceId}
          onChange={(e) => onDeviceIdChange(e.target.value)}
          disabled={!devices || devices.length === 0}
        >
          <option value="">Semua device</option>
          {(devices ?? []).map((device) => (
            <option key={device.id} value={device.id}>
              {device.name}
            </option>
          ))}
        </select>
      </label>
      <label className="live-monitoring-filterbar__field">
        <span>Keputusan</span>
        <select
          value={decision}
          onChange={(e) => onDecisionChange(e.target.value as AccessDecision | '')}
        >
          <option value="">Semua keputusan</option>
          {ACCESS_DECISIONS.map((d) => (
            <option key={d} value={d}>
              {decisionMeta(d).label}
            </option>
          ))}
        </select>
      </label>
      <label className="live-monitoring-filterbar__field">
        <span>Dari tanggal</span>
        <input type="date" value={dateFrom} onChange={(e) => onDateFromChange(e.target.value)} />
      </label>
      <label className="live-monitoring-filterbar__field">
        <span>Sampai tanggal</span>
        <input type="date" value={dateTo} onChange={(e) => onDateToChange(e.target.value)} />
      </label>
    </div>
  )
}
