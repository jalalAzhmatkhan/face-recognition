import type { ConnectionStatus } from './types'

const STATUS_META: Record<ConnectionStatus, { label: string; colorVar: string; pulse: boolean }> = {
  connecting: { label: 'Menghubungkan…', colorVar: 'var(--text-muted)', pulse: true },
  live: { label: 'Live', colorVar: 'var(--success)', pulse: true },
  reconnecting: { label: 'Terputus — mencoba ulang…', colorVar: 'var(--warning)', pulse: true },
  disconnected: { label: 'Terputus', colorVar: 'var(--danger)', pulse: false },
}

/** Live-feed connection status dot + label (screen-plan S-40: "indikator
 * koneksi SSE (live dot pulsing / 'terputus — mencoba ulang…')"). */
export default function ConnectionIndicator({ status }: { status: ConnectionStatus }) {
  const meta = STATUS_META[status]
  return (
    <span
      role="status"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 'var(--space-2)',
        font: 'var(--text-small)',
        color: 'var(--text-secondary)',
      }}
    >
      <span
        aria-hidden="true"
        className={meta.pulse ? 'live-dot live-dot--pulsing' : 'live-dot'}
        style={{ background: meta.colorVar }}
      />
      {meta.label}
    </span>
  )
}
