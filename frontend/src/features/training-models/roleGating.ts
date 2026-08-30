import type { StaffRole } from '../../lib/authToken'

/**
 * Pure role -> access logic for the training & model management UI (FE-09
 * task instructions, screen-plan S-50/S-51/S-52), framework-free so it is
 * trivially unit-testable. Mirrors the pattern of
 * `device-management/roleGating.ts`.
 *
 * IMPORTANT DIVERGENCE FROM THE BACKEND (documented per task instructions):
 * BE-13's `GET /models` and `GET /training/jobs/{id}` actually allow
 * ADMIN/OPERATOR (and VIEWER for `/models`) to read — see
 * `backend/app/routers/training.py`'s own docstring, which also explains
 * that TSD §7's "ADMIN/ML" access level collapses to ADMIN-only here since
 * this project has no separate ML staff role. `documentation/uiux/
 * screen-plan.md` explicitly scopes S-50/51/52 to access level "A"
 * (ADMIN(+ML)) though — a deliberately stricter UX than what the backend
 * would technically allow. This module follows the SCREEN-PLAN's intent,
 * not the backend's more permissive read ceiling: the entire feature is
 * gated ADMIN-only in the frontend, and any other role (including OPERATOR,
 * which CAN technically call `GET /training/jobs/{id}`) sees the same
 * "Tidak Ada Akses" treatment `device-management` uses for VIEWER.
 */

const ALLOWED_ROLES: readonly StaffRole[] = ['ADMIN']

export function canAccessTrainingModels(role: StaffRole | null): boolean {
  return role !== null && ALLOWED_ROLES.includes(role)
}
