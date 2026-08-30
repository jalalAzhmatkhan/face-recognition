import ConnectionIndicator from './ConnectionIndicator'
import { decisionMeta } from './decisionMeta'
import type { AccessDecision, ConnectionStatus, DeviceSummary } from './types'
import { ACCESS_DECISIONS } from './types'

interface FilterBarProps {
  deviceId: string
  onDeviceIdChange: (value: string) => void
  devices: DeviceSummary[] | null
  decision: AccessDecision | ''
  onDecisionChange: (value: AccessDecision | '') => void
  connectionStatus: ConnectionStatus
}

/** Top filter row (screen-plan S-40: "filter device & keputusan; indikator
 * koneksi SSE"). Changing either filter is wired by `LiveMonitoringPage` to
 * reconnect the SSE stream with new query params and reset the feed. */
export default function FilterBar({
  deviceId,
  onDeviceIdChange,
  devices,
  decision,
  onDecisionChange,
  connectionStatus,
}: FilterBarProps) {
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
      <div className="live-monitoring-filterbar__spacer" />
      <ConnectionIndicator status={connectionStatus} />
    </div>
  )
}
