import type { ModelStage } from './types'

const STAGE_COLOR_VARS: Record<ModelStage, { bg: string; fg: string }> = {
  CANDIDATE: { bg: 'var(--info-subtle-bg)', fg: 'var(--info)' },
  PRODUCTION: { bg: 'var(--success-subtle-bg)', fg: 'var(--success)' },
  RETIRED: { bg: 'var(--bg-sunken)', fg: 'var(--text-secondary)' },
}

const STAGE_LABELS: Record<ModelStage, string> = {
  CANDIDATE: 'Candidate',
  PRODUCTION: 'Produksi',
  RETIRED: 'Retired',
}

/** Stage badge for the `models` table/cards — one distinct color per stage
 * (screen-plan S-50: "stage badge success" for PRODUCTION rows). */
export default function StageBadge({ stage }: { stage: ModelStage }) {
  const colors = STAGE_COLOR_VARS[stage]
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
      {STAGE_LABELS[stage]}
    </span>
  )
}
