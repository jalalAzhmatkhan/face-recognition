import type { DeviceSummary } from './types'

function isConcerning(device: DeviceSummary): boolean {
  // DISABLED is an intentional admin action, not an unexpected outage —
  // excluded here so disabling a device doesn't itself trigger a
  // fail-secure scare.
  return device.status === 'DISABLED' ? false : device.status !== 'ONLINE' || device.is_stale
}

/** Fail-secure banner (screen-plan S-40 / FR-INF-05: "Device offline →
 * banner fail-secure + link prosedur override"). No real override-procedure
 * page exists yet, so per task instructions this stays a plain, honest
 * notice rather than a dead/fake link. */
export default function OfflineDeviceBanner({ devices }: { devices: DeviceSummary[] }) {
  const offline = devices.filter(isConcerning)
  if (offline.length === 0) return null

  return (
    <div className="alert-banner alert-banner--warning" role="alert" data-testid="offline-banner">
      <strong>
        {offline.length === 1
          ? `Device "${offline[0].name}" sedang offline atau tidak mengirim heartbeat.`
          : `${offline.length} device sedang offline atau tidak mengirim heartbeat.`}
      </strong>{' '}
      Sistem fail-secure: pintu terkait tidak akan membuka otomatis. Prosedur override manual
      belum tersedia di console ini — hubungi tim operasional gedung.
    </div>
  )
}
