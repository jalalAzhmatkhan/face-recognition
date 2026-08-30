import type { EnrollmentState } from './types'
import { STATE_COLOR_VARS, stateLabel } from './stateLabels'

export default function StateBadge({ state }: { state: EnrollmentState }) {
  const colors = STATE_COLOR_VARS[state] ?? {
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
      {stateLabel(state)}
    </span>
  )
}
