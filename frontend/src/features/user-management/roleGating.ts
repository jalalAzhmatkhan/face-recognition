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
 * VIEWER, not just disabled. Also used for "Mulai Re-enroll" (EC-FE-03):
 * same underlying action (`POST` a new enrollment session, same wizard),
 * just a different label/entry point when `reenroll_due` is set. */
export function canStartEnrollment(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

/**
 * EC-FE-03 (TSD-edge-cases.md D-4.4): `identity_similarity_flags` pairs are
 * ADMIN-only per the task's acceptance criteria — this mirrors how
 * `device-management/roleGating.ts` restricts its most sensitive view to
 * ADMIN alone (unlike the ADMIN+OPERATOR read access every other user-facing
 * list in this feature gets). Kept separate from `WRITE_ROLES` above since
 * this is a *read* gate, not a write one.
 */
const SIMILARITY_FLAGS_READ_ROLES: readonly StaffRole[] = ['ADMIN']

export function canViewIdentitySimilarityFlags(role: StaffRole | null): boolean {
  return role !== null && SIMILARITY_FLAGS_READ_ROLES.includes(role)
}
