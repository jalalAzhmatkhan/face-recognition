import type { AccessEventPayload } from '../live-monitoring/types'

const CSV_HEADER = [
  'occurred_at',
  'device',
  'decision',
  'matched_user',
  'similarity',
  'liveness_score',
  'model_version',
  'latency_ms',
  'door_command_issued',
]

function csvEscape(value: string): string {
  if (/[",\n]/.test(value)) return `"${value.replace(/"/g, '""')}"`
  return value
}

/**
 * "Export CSV metadata-only" (screen-plan S-42) -- deliberately excludes
 * `frame_media_id`/anything that could be used to fetch actual captured
 * imagery, exporting only the same decision/score/device/user metadata
 * already visible in the table. `deviceNames`/`userNames` resolve ids to
 * display names (falling back to the raw id when unresolved) so the
 * export is human-readable, not a job for whoever opens the CSV to cross-
 * reference ids by hand.
 */
export function buildAccessLogCsv(
  events: AccessEventPayload[],
  deviceNames: Map<string, string>,
  userNames: Map<string, string>,
): string {
  const rows = events.map((event) => [
    event.occurred_at,
    deviceNames.get(event.device_id) ?? event.device_id,
    event.decision,
    event.matched_user_id ? (userNames.get(event.matched_user_id) ?? event.matched_user_id) : '',
    event.similarity === null ? '' : String(event.similarity),
    event.liveness_score === null ? '' : String(event.liveness_score),
    event.model_version ?? '',
    event.latency_ms === null ? '' : String(event.latency_ms),
    String(event.door_command_issued),
  ])
  return [CSV_HEADER, ...rows].map((row) => row.map(csvEscape).join(',')).join('\n')
}

/** Triggers a browser download of `content` as `filename` via a throwaway
 * Blob URL -- no backend CSV-export endpoint exists (this is the first CSV
 * export anywhere in this frontend), so the export is built entirely from
 * whatever rows are already loaded client-side (see `AccessLogPage`'s "this
 * page only" caveat next to the export button). */
export function downloadCsv(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
