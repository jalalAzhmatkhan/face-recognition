import type { EnrollmentState, StaffRole } from './types'
import { TERMINAL_STATES } from './types'

/**
 * Pure role/state -> allowed-actions logic for the enrollment management UI
 * (FE-05 task instructions). Kept side-effect-free and framework-free so it
 * is trivially unit-testable without rendering anything.
 *
 * Mirrors the backend's own RBAC (`backend/app/routers/enrollments.py`):
 *  - WRITE_ROLES = ADMIN, OPERATOR (create/consent/transition/cancel)
 *  - REVOKE_ROLES = ADMIN only (stricter, DELETE /enrollments/{id})
 *  - READ_ROLES = ADMIN, OPERATOR, VIEWER (VIEWER never gets a write action)
 * This module only decides what to *show*; the backend remains the sole
 * enforcement point.
 */

const WRITE_ROLES: readonly StaffRole[] = ['ADMIN', 'OPERATOR']

export type EnrollmentAction = 'consent' | 'recapture' | 'resume_capture' | 'cancel' | 'revoke'

/** Create-enrollment button (S-30 "Buat enrollment baru"). */
export function canCreateEnrollment(role: StaffRole | null): boolean {
  return role !== null && WRITE_ROLES.includes(role)
}

/** Consent form — only while the session is freshly CREATED. */
export function canGrantConsent(state: EnrollmentState, role: StaffRole | null): boolean {
  return state === 'CREATED' && role !== null && WRITE_ROLES.includes(role)
}

/** Re-capture — start/restart the capture wizard. Legal from CONSENTED
 * (first capture) or REJECTED_QUALITY (retry after a failed QC), per the
 * `MANUALLY_TRIGGERABLE_TARGETS` allow-list in the backend router. */
export function canRecapture(state: EnrollmentState, role: StaffRole | null): boolean {
  return (
    (state === 'CONSENTED' || state === 'REJECTED_QUALITY') &&
    role !== null &&
    WRITE_ROLES.includes(role)
  )
}

/** Resume capture — re-open the capture wizard for a session that is
 * ALREADY `CAPTURING` (e.g. the browser was closed/backed-out of mid
 * capture, or the camera never started) without calling the
 * `/transition` endpoint: the backend's state machine only allows
 * CAPTURING as a *target* from CONSENTED/REJECTED_QUALITY, not from
 * CAPTURING itself (`enrollment_state_machine.py`'s `_TRANSITIONS` has
 * no CAPTURING -> CAPTURING edge), so re-triggering the transition would
 * 409. The wizard page itself doesn't require any particular source
 * state, so simply navigating back into it is enough to let the
 * operator retry. */
export function canResumeCapture(state: EnrollmentState, role: StaffRole | null): boolean {
  return state === 'CAPTURING' && role !== null && WRITE_ROLES.includes(role)
}

/** Cancel — allowed from any non-terminal state. ENROLLED has no `/cancel`
 * edge in the backend state machine even though it isn't in
 * `TERMINAL_STATES` (it still has exactly one legal outgoing edge, to
 * REVOKED, but only via `DELETE /enrollments/{id}` — see `canRevoke` —
 * never via `/cancel`). Found live: without this, "Batalkan Sesi" rendered
 * on an ENROLLED session and hit the backend's 409 on click instead of
 * never being shown. */
export function canCancel(state: EnrollmentState, role: StaffRole | null): boolean {
  return (
    !TERMINAL_STATES.includes(state) &&
    state !== 'ENROLLED' &&
    role !== null &&
    WRITE_ROLES.includes(role)
  )
}

/** Revoke — ENROLLED only, ADMIN only (stricter than every other action:
 * hidden entirely for OPERATOR/VIEWER, not just disabled). */
export function canRevoke(state: EnrollmentState, role: StaffRole | null): boolean {
  return state === 'ENROLLED' && role === 'ADMIN'
}

/** All actions that should be visible for a given (state, role)
 * combination, in the order they should appear. VIEWER always yields an
 * empty array — every action above requires at least OPERATOR. */
export function visibleActions(state: EnrollmentState, role: StaffRole | null): EnrollmentAction[] {
  const actions: EnrollmentAction[] = []
  if (canGrantConsent(state, role)) actions.push('consent')
  if (canRecapture(state, role)) actions.push('recapture')
  if (canResumeCapture(state, role)) actions.push('resume_capture')
  if (canRevoke(state, role)) actions.push('revoke')
  if (canCancel(state, role)) actions.push('cancel')
  return actions
}
