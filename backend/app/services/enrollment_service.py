"""Enrollment session business logic (BE-05, FR-ENR-01/08).

Layering per app/main.py docstring: routers (HTTP) -> services (business
logic) -> repositories (data access). This module owns:
  - FR-ENR-01: a session may only be created for a user that exists AND is
    ACTIVE.
  - FR-ENR-08: consent is recorded (versioned, who/when) and is the only
    path from CREATED -> CONSENTED; capture (CONSENTED -> CAPTURING) is
    unreachable without it because the state machine
    (app/services/enrollment_state_machine.py) only allows CAPTURING from
    CONSENTED or REJECTED_QUALITY.
  - Writing an `audit_logs` entry for session creation, consent, every
    state transition, and cancellation (TSD audit requirement / NFR-SEC-05).
"""

import uuid
from datetime import UTC, datetime

from app.models.consent import Consent
from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, UserStatus
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.consents import ConsentRepository
from app.repositories.enrollments import EnrollmentSessionRepository
from app.repositories.users import UserRepository
from app.services import enrollment_state_machine as fsm


class UserNotFoundError(Exception):
    """No user exists with the given id."""


class UserNotActiveError(Exception):
    """User exists but is not ACTIVE (FR-ENR-01)."""

    def __init__(self, user_id: uuid.UUID, status: UserStatus) -> None:
        self.user_id = user_id
        self.status = status
        super().__init__(f"User '{user_id}' is not ACTIVE (status={status.value})")


class EnrollmentNotFoundError(Exception):
    """No enrollment session exists with the given id."""


class InvalidConsentStateError(Exception):
    """Consent can only be granted while the session is CREATED."""

    def __init__(self, session_id: uuid.UUID, current_state: EnrollmentState) -> None:
        self.session_id = session_id
        self.current_state = current_state
        super().__init__(
            f"Session '{session_id}' is in state {current_state.value}, expected CREATED"
        )


def create_session(
    enrollment_repo: EnrollmentSessionRepository,
    user_repo: UserRepository,
    audit_repo: AuditLogRepository,
    *,
    user_id: uuid.UUID,
    created_by: uuid.UUID,
    actor: str,
) -> EnrollmentSession:
    user = user_repo.get(user_id)
    if user is None:
        raise UserNotFoundError(str(user_id))
    if user.status != UserStatus.ACTIVE:
        raise UserNotActiveError(user_id, user.status)

    session = EnrollmentSession(
        user_id=user_id, state=EnrollmentState.CREATED, created_by=created_by
    )
    session = enrollment_repo.create(session)

    audit_repo.record(
        actor=actor,
        action="enrollment.create",
        entity=f"enrollment_session:{session.id}",
        payload={"user_id": str(user_id), "state": EnrollmentState.CREATED.value},
    )
    return session


def get_session(
    enrollment_repo: EnrollmentSessionRepository, session_id: uuid.UUID
) -> EnrollmentSession:
    session = enrollment_repo.get(session_id)
    if session is None:
        raise EnrollmentNotFoundError(str(session_id))
    return session


def list_sessions(
    enrollment_repo: EnrollmentSessionRepository,
    *,
    user_id: uuid.UUID | None = None,
    state: EnrollmentState | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[EnrollmentSession], int]:
    items = enrollment_repo.list(user_id=user_id, state=state, limit=limit, offset=offset)
    total = enrollment_repo.count(user_id=user_id, state=state)
    return items, total


def grant_consent(
    enrollment_repo: EnrollmentSessionRepository,
    consent_repo: ConsentRepository,
    audit_repo: AuditLogRepository,
    *,
    session_id: uuid.UUID,
    consent_version: str,
    actor: str,
) -> EnrollmentSession:
    """Record a versioned consent entry; transition CREATED -> CONSENTED.

    Consent precedes everything else in the flow (FR-ENR-08), so on a
    CREATED session this records the grant AND advances the state.

    On a session that has already moved on, the grant is still RECORDED but
    the state is left alone. That is not a loosening of the gate, it fixes a
    hole in it: the operator flow (`EnrollmentDetailPage`'s consent +
    recapture) drives a session to CAPTURING before the wizard ever opens,
    so the wizard's own consent step -- the one the subject actually reads
    and ticks, at the CURRENT clause version -- always hit a 409 and its
    grant was silently dropped by the caller's catch-all. ASM-EC-05 requires
    re-consent never to block an existing user's capture; it does not
    require throwing the record away. `consents` is append-only per user, so
    recording an additional, newer-version grant is strictly more complete.

    Re-granting a version the user already has on record is a no-op rather
    than a duplicate row -- the wizard fires this on every camera start.

    A terminal session (CANCELLED/REVOKED) still conflicts: consent for a
    revoked enrollment is meaningless, and silently accepting it would let a
    revoked subject look consented.
    """
    session = enrollment_repo.get(session_id)
    if session is None:
        raise EnrollmentNotFoundError(str(session_id))
    if session.state in fsm.TERMINAL_STATES:
        raise InvalidConsentStateError(session_id, session.state)

    existing = next(
        (
            row
            for row in consent_repo.list_for_user(session.user_id)
            if row.consent_version == consent_version
        ),
        None,
    )
    consent = existing or consent_repo.create(
        Consent(
            user_id=session.user_id,
            consent_version=consent_version,
            granted_at=datetime.now(UTC),
        )
    )

    previous_state = session.state
    if session.state == EnrollmentState.CREATED:
        fsm.validate_transition(session.state, EnrollmentState.CONSENTED)
        session.state = EnrollmentState.CONSENTED
        session = enrollment_repo.update(session)

    # Audited in both cases. A grant recorded against an in-flight session
    # transitions nothing, but it is still a consent event and the audit log
    # is the compliance record (FR-ENR-08) -- `from`/`to` being equal is the
    # honest description of what happened.
    audit_repo.record(
        actor=actor,
        action="enrollment.consent_granted",
        entity=f"enrollment_session:{session.id}",
        payload={
            "consent_id": str(consent.id),
            "consent_version": consent_version,
            "already_on_record": existing is not None,
            "from": previous_state.value,
            "to": session.state.value,
        },
    )
    return session


def transition_session(
    enrollment_repo: EnrollmentSessionRepository,
    audit_repo: AuditLogRepository,
    *,
    session_id: uuid.UUID,
    target_state: EnrollmentState,
    actor: str,
    audit_action: str = "enrollment.transition",
) -> EnrollmentSession:
    """Generic state-machine-validated transition, shared by the manual
    `/transition` and `/cancel` endpoints (and reusable by BE-06/07/08 job
    code operating outside the HTTP layer)."""
    session = enrollment_repo.get(session_id)
    if session is None:
        raise EnrollmentNotFoundError(str(session_id))

    fsm.validate_transition(session.state, target_state)

    previous_state = session.state
    session.state = target_state
    session = enrollment_repo.update(session)

    audit_repo.record(
        actor=actor,
        action=audit_action,
        entity=f"enrollment_session:{session.id}",
        payload={"from": previous_state.value, "to": session.state.value},
    )
    return session


def cancel_session(
    enrollment_repo: EnrollmentSessionRepository,
    audit_repo: AuditLogRepository,
    *,
    session_id: uuid.UUID,
    actor: str,
) -> EnrollmentSession:
    return transition_session(
        enrollment_repo,
        audit_repo,
        session_id=session_id,
        target_state=EnrollmentState.CANCELLED,
        actor=actor,
        audit_action="enrollment.cancel",
    )
