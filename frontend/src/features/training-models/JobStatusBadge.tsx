import type { TrainingJobStatus } from './types'

const STATUS_COLOR_VARS: Record<TrainingJobStatus, { bg: string; fg: string }> = {
  PENDING: { bg: 'var(--bg-sunken)', fg: 'var(--text-secondary)' },
  RUNNING: { bg: 'var(--info-subtle-bg)', fg: 'var(--info)' },
  SUCCEEDED: { bg: 'var(--success-subtle-bg)', fg: 'var(--success)' },
  FAILED: { bg: 'var(--danger-subtle-bg)', fg: 'var(--danger)' },
}

const STATUS_LABELS: Record<TrainingJobStatus, string> = {
  PENDING: 'Pending',
  RUNNING: 'Berjalan',
  SUCCEEDED: 'Selesai',
  FAILED: 'Gagal',
}

/** Training job status badge (S-50 session-jobs table + S-51 header). */
export default function JobStatusBadge({ status }: { status: TrainingJobStatus }) {
  const colors = STATUS_COLOR_VARS[status]
  return (
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
      {STATUS_LABELS[status]}
    </span>
  )
}
