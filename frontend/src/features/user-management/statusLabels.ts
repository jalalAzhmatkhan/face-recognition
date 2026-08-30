import type { UserStatus } from './types'

/** Bahasa Indonesia labels for the user status enum (FR-USR-01). */
export const STATUS_LABELS: Record<UserStatus, string> = {
  ACTIVE: 'Aktif',
  SUSPENDED: 'Ditangguhkan',
  OFFBOARDED: 'Nonaktif',
}

/** Colors keyed off design tokens (`src/styles/tokens.css`), same semantic
 * mapping style as `enrollment-management/stateLabels.ts`: success = can
 * access, warning = temporarily blocked but reversible, neutral/danger =
 * permanently offboarded. */
export const STATUS_COLOR_VARS: Record<UserStatus, { bg: string; fg: string }> = {
  ACTIVE: { bg: 'var(--success-subtle-bg)', fg: 'var(--success)' },
  SUSPENDED: { bg: 'var(--warning-subtle-bg)', fg: 'var(--warning)' },
  OFFBOARDED: { bg: 'var(--bg-sunken)', fg: 'var(--text-muted)' },
}

export function statusLabel(status: UserStatus): string {
  return STATUS_LABELS[status] ?? status
}
