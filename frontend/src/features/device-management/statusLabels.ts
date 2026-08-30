import type { DeviceStatus } from './types'

/** Bahasa Indonesia labels for the device status enum (FR-USR-04). */
export const STATUS_LABELS: Record<DeviceStatus, string> = {
  ONLINE: 'Online',
  OFFLINE: 'Offline',
  DISABLED: 'Nonaktif',
}

/** Colors keyed off design tokens (`src/styles/tokens.css`), same semantic
 * mapping style as `user-management/statusLabels.ts`. */
export const STATUS_COLOR_VARS: Record<DeviceStatus, { bg: string; fg: string }> = {
  ONLINE: { bg: 'var(--success-subtle-bg)', fg: 'var(--success)' },
  OFFLINE: { bg: 'var(--danger-subtle-bg)', fg: 'var(--danger)' },
  DISABLED: { bg: 'var(--bg-sunken)', fg: 'var(--text-muted)' },
}

export function statusLabel(status: DeviceStatus): string {
  return STATUS_LABELS[status] ?? status
}
