import type { StaffRole } from '../../lib/authToken'

/**
 * Pure role -> allowed-actions logic for the user management UI (FE-03 task
 * instructions). Kept side-effect-free and framework-free so it is
 * trivially unit-testable without rendering anything, mirroring
 * `enrollment-management/roleGating.ts` from FE-05.
 *
 * Mirrors the backend's own RBAC (`backend/app/routers/users.py` per BE-04
 * spec):
 *  - READ_ROLES = ADMIN, OPERATOR, VIEWER (GET /users, GET /users/{id})
 *  - WRITE_ROLES = ADMIN, OPERATOR (POST/PATCH/DELETE)
 * There is no state machine here (unlike enrollments) — user status itself
 * doesn't gate which actions are legal, only role does.
 */

const WRITE_ROLES: readonly StaffRole[] = ['ADMIN', 'OPERATOR']

export function canCreateUser(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

export function canEditUser(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

export function canChangeUserStatus(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

export function canOffboardUser(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

/** "Mulai Enrollment" is a write action (creates an enrollment session for
 * the user), so it follows the same write-role gate — hidden entirely for
 * VIEWER, not just disabled. */
export function canStartEnrollment(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}
