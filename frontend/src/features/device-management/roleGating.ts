import type { StaffRole } from '../../lib/authToken'

/**
 * Pure role -> allowed-actions logic for the device management UI (FE-08
 * task instructions), framework-free so it is trivially unit-testable.
 * Mirrors the pattern of `user-management/roleGating.ts` /
 * `enrollment-management/roleGating.ts`.
 *
 * Mirrors the backend's own RBAC (`backend/app/routers/devices.py`, BE-09,
 * NOT to be modified by this task):
 *  - READ_ROLES  = ADMIN, OPERATOR  (GET /devices) — VIEWER is deliberately
 *    excluded here, unlike most other staff-read screens (e.g. users,
 *    enrollments) which do allow VIEWER read access. This is the one
 *    screen in the console VIEWER cannot open at all.
 *  - WRITE_ROLES = ADMIN only        (POST/PATCH/DELETE/rotate-credential)
 *    — unlike users/enrollments, OPERATOR does NOT get write access here:
 *    device credentials gate physical door hardware, so BE-09 restricts
 *    mutation to ADMIN alone.
 */

const READ_ROLES: readonly StaffRole[] = ['ADMIN', 'OPERATOR']
const WRITE_ROLES: readonly StaffRole[] = ['ADMIN']

export function canReadDevices(role: StaffRole | null): boolean {
  return role !== null && READ_ROLES.includes(role)
}

export function canCreateDevice(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

export function canEditDevice(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

export function canRotateDeviceCredential(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

export function canDisableDevice(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}
