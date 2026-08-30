/**
 * Small self-contained relative-time formatter ("2 menit lalu") for the
 * device status panel's last-heartbeat display. The project has no
 * date-fns/dayjs dependency (checked `frontend/package.json`), so per task
 * instructions this is a simple hand-written util rather than a new
 * dependency — heartbeat freshness only needs coarse granularity, not
 * calendar-aware formatting.
 */
export function formatRelativeTime(iso: string | null, now: Date = new Date()): string {
  if (!iso) return 'belum pernah'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'belum pernah'

  const diffMs = now.getTime() - then
  if (diffMs < 1000) return 'baru saja'

  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec} detik lalu`

  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin} menit lalu`

  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour} jam lalu`

  const diffDay = Math.floor(diffHour / 24)
  return `${diffDay} hari lalu`
}

/** Compact local time for a feed item ("14:32:05"), per task instructions
 * ("waktu (format lokal ringkas)"). */
export function formatEventTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('id-ID')
  } catch {
    return iso
  }
}
