import type { UserStatus } from './types'
import { STATUS_COLOR_VARS, statusLabel } from './statusLabels'

/**
 * Visually identical to `enrollment-management/StateBadge.tsx` (same design
 * tokens/markup) but typed against `UserStatus` rather than
 * `EnrollmentState`. Not reused directly: the two badges key off unrelated
 * enums, and genericizing `StateBadge` would mean editing FE-05's already
 * merged module for a one-screen gain — not worth the merge risk for this
 * task. If a third status enum shows up, that's the point to extract a
 * shared `<Badge tone bg fg label>` primitive into `frontend/src/lib/`.
 */
export default function UserStatusBadge({ status }: { status: UserStatus }) {
  const colors = STATUS_COLOR_VARS[status] ?? {
    bg: 'var(--bg-sunken)',
    fg: 'var(--text-secondary)',
  }
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
      {statusLabel(status)}
    </span>
  )
}
