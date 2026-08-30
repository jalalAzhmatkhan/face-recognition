import type { EnrollmentState } from './types'

/** Bahasa Indonesia labels for the enrollment state machine (FSD-AI.md §8). */
export const STATE_LABELS: Record<EnrollmentState, string> = {
  CREATED: 'Dibuat',
  CONSENTED: 'Consent Diberikan',
  CAPTURING: 'Sedang Capture',
  CAPTURED: 'Capture Selesai',
  QC_RUNNING: 'QC Berjalan',
  REJECTED_QUALITY: 'Ditolak (Kualitas)',
  QC_PASSED: 'QC Lolos',
  EMBEDDING: 'Ekstraksi Embedding',
  ENROLLED: 'Terdaftar',
  CANCELLED: 'Dibatalkan',
  REVOKED: 'Dicabut',
}

/** Colors keyed off design tokens (`src/styles/tokens.css`) — semantic
 * mapping: success = terminal-good, danger = terminal-bad/rejected,
 * warning = in-progress QC, info = consented/passed, ml (purple) = the
 * ML-heavy embedding step, accent = active capture, neutral = inert. */
export const STATE_COLOR_VARS: Record<EnrollmentState, { bg: string; fg: string }> = {
  CREATED: { bg: 'var(--bg-sunken)', fg: 'var(--text-secondary)' },
  CONSENTED: { bg: 'var(--info-subtle-bg)', fg: 'var(--info)' },
  CAPTURING: { bg: 'var(--accent-subtle-bg)', fg: 'var(--accent)' },
  CAPTURED: { bg: 'var(--accent-subtle-bg)', fg: 'var(--accent)' },
  QC_RUNNING: { bg: 'var(--warning-subtle-bg)', fg: 'var(--warning)' },
  REJECTED_QUALITY: { bg: 'var(--danger-subtle-bg)', fg: 'var(--danger)' },
  QC_PASSED: { bg: 'var(--info-subtle-bg)', fg: 'var(--info)' },
  EMBEDDING: { bg: 'var(--accent-subtle-bg)', fg: 'var(--ml)' },
  ENROLLED: { bg: 'var(--success-subtle-bg)', fg: 'var(--success)' },
  CANCELLED: { bg: 'var(--bg-sunken)', fg: 'var(--text-muted)' },
  REVOKED: { bg: 'var(--danger-subtle-bg)', fg: 'var(--danger)' },
}

export function stateLabel(state: EnrollmentState): string {
  return STATE_LABELS[state] ?? state
}
