"""Enrollment revocation — synchronous, security-critical half (BE-08,
FR-ENR-09, NFR-SEC-03, ASM-12, TSD ~L207/L264: "User deletion job (FR-ENR-09)
deletes objects + embeddings + tombstones the user, and is audited.").

`DELETE /enrollments/{id}` (ADMIN only, see router) is the only entry point.
Everything in this module runs inside the endpoint's own request/DB
transaction and MUST complete before the physical cleanup job is even
dispatched:

- ENROLLED -> REVOKED on the enrollment session, via the same
  `enrollment_service.transition_session` every other transition in this
  codebase goes through (state-machine-validated: `fsm` only allows this
  edge from ENROLLED — see app/services/enrollment_state_machine.py — so an
  attempt from any other state raises `fsm.IllegalTransitionError`, mapped
  by the router to 409, exactly like `/cancel` and `/transition`).
- `user.status = OFFBOARDED` (if not already), so FR-USR-01 ("a non-active
  user is never granted access") is enforced *immediately* and does not wait
  for the async job's embeddings/media deletion (which has a separate 24h
  SLA). This is what makes "the user is unrecognized" true the instant this
  endpoint returns, even though the biometric data itself is deleted later.
- One `enrollment.revoke_initiated` audit entry (NFR-SEC-05) — deliberately
  distinct from the generic `enrollment.transition`/`enrollment.cancel`
  audit actions other transitions use, since revocation is the
  security-relevant event QA-09/audit review needs to find quickly.

The actual embeddings/media hard-delete + user tombstone is
`app/worker/tasks.py::revoke_enrollment_cleanup`, dispatched via
`app/services/revocation_queue.py` at the end of this function (best-effort,
same broker-down-tolerant pattern as `qc_queue.enqueue_qc_job` — see that
module's docstring).
"""

import uuid

from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, UserStatus
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.enrollments import EnrollmentSessionRepository
from app.repositories.users import UserRepository
from app.services import enrollment_service
from app.services import revocation_queue as revocation_queue_service

REVOKE_INITIATED_ACTION = "enrollment.revoke_initiated"


def revoke_enrollment(
    enrollment_repo: EnrollmentSessionRepository,
    user_repo: UserRepository,
    audit_repo: AuditLogRepository,
    *,
    session_id: uuid.UUID,
    actor: str,
) -> EnrollmentSession:
    """Handle `DELETE /enrollments/{id}` (FR-ENR-09).

    Raises `enrollment_service.EnrollmentNotFoundError` (-> 404) or
    `enrollment_state_machine.IllegalTransitionError` (-> 409, when the
    session is not currently ENROLLED) — both already handled by the router
    for the other transition endpoints, reused here rather than duplicated.
    """
    session = enrollment_service.transition_session(
        enrollment_repo,
        audit_repo,
        session_id=session_id,
        target_state=EnrollmentState.REVOKED,
        actor=actor,
        audit_action=REVOKE_INITIATED_ACTION,
    )

    user = user_repo.get(session.user_id)
    if user is not None and user.status != UserStatus.OFFBOARDED:
        user.status = UserStatus.OFFBOARDED
        user_repo.update(user)

    # Dispatch AFTER the transition + offboard above have committed (both
    # repos commit per-call, see app/repositories/*.py) — a broker outage
    # here must never roll back or block the synchronous security effect.
    revocation_queue_service.enqueue_revocation_cleanup(session.id)

    return session
