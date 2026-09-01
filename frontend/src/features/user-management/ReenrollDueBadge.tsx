import type { UserResponse } from './types'
import { isReenrollDue } from './types'

/**
 * EC-FE-03: badge shown next to a user's status when `reenroll_due` is true
 * (A-5 in `documentation/tsd/TSD-edge-cases.md` — enrollment older than the
 * policy window, or a low moving-average genuine score). Visually modeled
 * after `UserStatusBadge` (same tokens/shape) but uses the `warning` tone
 * unconditionally since "due for re-enroll" only ever has one state to show
 * — there's no separate "not due" badge, the badge simply doesn't render.
 *
 * Renders nothing when `reenroll_due` is falsy OR absent — the latter is the
 * case for every user today, since `UserResponse` from the backend doesn't
 * send this field yet (see the GAP comment on `UserResponse` in `./types`).
 * `reenroll_due_reason`, when present, is shown as a `title` tooltip.
 */
export default function ReenrollDueBadge({
  user,
}: {
  user: Pick<UserResponse, 'reenroll_due' | 'reenroll_due_reason'>
}) {
  if (!isReenrollDue(user)) return null

  return (
    <span
      title={user.reenroll_due_reason ?? undefined}
      style={{
        display: 'inline-block',
        padding: '2px 10px',
        borderRadius: 'var(--radius-full)',
        font: 'var(--text-caption)',
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
        background: 'var(--warning-subtle-bg)',
        color: 'var(--warning)',
        whiteSpace: 'nowrap',
      }}
    >
      Perlu Re-enroll
    </span>
  )
}
