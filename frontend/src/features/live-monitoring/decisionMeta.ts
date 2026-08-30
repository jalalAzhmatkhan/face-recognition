import type { AccessDecision } from './types'

export interface DecisionMeta {
  label: string
  icon: string
  colorVar: string
  bgVar: string
  /** 'strong' gets a bolder border in `AccessEventItem` so SPOOF_SUSPECTED
   * reads as visually distinct from a plain DENIED, per task instructions
   * ("styling danger yang jelas beda dari DENIED biasa"). */
  emphasis: 'default' | 'strong'
}

const DECISION_META: Record<AccessDecision, DecisionMeta> = {
  GRANTED: {
    label: 'Diizinkan',
    icon: '✓',
    colorVar: 'var(--success)',
    bgVar: 'var(--success-subtle-bg)',
    emphasis: 'default',
  },
  DENIED: {
    label: 'Ditolak',
    icon: '✕',
    colorVar: 'var(--danger)',
    bgVar: 'var(--danger-subtle-bg)',
    emphasis: 'default',
  },
  UNKNOWN: {
    label: 'Tidak dikenali',
    icon: '?',
    colorVar: 'var(--warning)',
    bgVar: 'var(--warning-subtle-bg)',
    emphasis: 'default',
  },
  SPOOF_SUSPECTED: {
    label: 'Dicurigai spoof',
    icon: '⚠',
    colorVar: 'var(--danger)',
    bgVar: 'var(--danger-subtle-bg)',
    emphasis: 'strong',
  },
}

export function decisionMeta(decision: AccessDecision): DecisionMeta {
  return DECISION_META[decision]
}
