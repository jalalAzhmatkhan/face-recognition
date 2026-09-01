import type { StaffRole } from '../../lib/authToken'

/**
 * Pure role -> access logic for the "System Parameter" admin menu, mirrors
 * `training-models/roleGating.ts`.
 *
 * DIVERGENCE FROM THE BACKEND (deliberate, per explicit product decision):
 * `GET /system-parameters/enrollment-quality` actually allows ADMIN/
 * OPERATOR/VIEWER to read (the Enrollment capture wizard needs the current
 * effective thresholds for every role that can perform enrollment) — but
 * the admin MENU/PAGE itself is ADMIN-only in the frontend, same
 * "stricter UX than the backend's read ceiling" pattern
 * `training-models/roleGating.ts` already uses for Models & Training.
 */

const ALLOWED_ROLES: readonly StaffRole[] = ['ADMIN']

export function canAccessSystemParameters(role: StaffRole | null): boolean {
  return role !== null && ALLOWED_ROLES.includes(role)
}
