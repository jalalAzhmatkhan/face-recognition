"""Integration tests for `/api/v1/enrollments/*` via FastAPI TestClient (BE-05).

No real DB: repositories are overridden with in-memory fakes and
`get_current_staff` is overridden directly, mirroring the pattern in
test_users_router.py.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentStaff, get_current_staff
from app.main import create_app
from app.models.consent import CURRENT_CONSENT_VERSION, Consent
from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, StaffRole, UserStatus
from app.models.user import User
from app.routers.enrollments import (
    get_audit_log_repository,
    get_consent_repository,
    get_enrollment_repository,
    get_user_repository_dep,
)


class FakeEnrollmentRepository:
    def __init__(self, sessions: list[EnrollmentSession] | None = None) -> None:
        self._by_id: dict[uuid.UUID, EnrollmentSession] = {s.id: s for s in (sessions or [])}

    def get(self, session_id: uuid.UUID) -> EnrollmentSession | None:
        return self._by_id.get(session_id)

    def list(
        self,
        *,
        user_id: uuid.UUID | None = None,
        state: EnrollmentState | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EnrollmentSession]:
        items = list(self._by_id.values())
        if user_id is not None:
            items = [s for s in items if s.user_id == user_id]
        if state is not None:
            items = [s for s in items if s.state == state]
        items.sort(key=lambda s: s.created_at)
        return items[offset : offset + limit]

    def count(
        self, *, user_id: uuid.UUID | None = None, state: EnrollmentState | None = None
    ) -> int:
        items = list(self._by_id.values())
        if user_id is not None:
            items = [s for s in items if s.user_id == user_id]
        if state is not None:
            items = [s for s in items if s.state == state]
        return len(items)

    def create(self, enrollment: EnrollmentSession) -> EnrollmentSession:
        now = datetime.now(UTC)
        enrollment.id = enrollment.id or uuid.uuid4()
        enrollment.created_at = now
        enrollment.updated_at = now
        self._by_id[enrollment.id] = enrollment
        return enrollment

    def update(self, enrollment: EnrollmentSession) -> EnrollmentSession:
        enrollment.updated_at = datetime.now(UTC)
        self._by_id[enrollment.id] = enrollment
        return enrollment


class FakeConsentRepository:
    def __init__(self) -> None:
        self.consents: list[Consent] = []

    def get(self, consent_id: uuid.UUID) -> Consent | None:
        return next((c for c in self.consents if c.id == consent_id), None)

    def list_for_user(self, user_id: uuid.UUID) -> list[Consent]:
        return [c for c in self.consents if c.user_id == user_id]

    def create(self, consent: Consent) -> Consent:
        consent.id = consent.id or uuid.uuid4()
        self.consents.append(consent)
        return consent


class FakeUserRepository:
    def __init__(self, users: list[User] | None = None) -> None:
        self._by_id: dict[uuid.UUID, User] = {u.id: u for u in (users or [])}

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._by_id.get(user_id)

    def update(self, user: User) -> User:
        self._by_id[user.id] = user
        return user


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor: str, action: str, entity: str, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _make_user(status: UserStatus = UserStatus.ACTIVE) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid.uuid4(),
        external_ref=f"EMP-{uuid.uuid4().hex[:6]}",
        full_name="Test Person",
        status=status,
        created_at=now,
        updated_at=now,
    )


def _make_session(user_id: uuid.UUID, state: EnrollmentState = EnrollmentState.CREATED):
    now = datetime.now(UTC)
    return EnrollmentSession(
        id=uuid.uuid4(),
        user_id=user_id,
        state=state,
        qc_report=None,
        created_by=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def active_user() -> User:
    return _make_user(UserStatus.ACTIVE)


@pytest.fixture
def suspended_user() -> User:
    return _make_user(UserStatus.SUSPENDED)


@pytest.fixture
def user_repo(active_user: User, suspended_user: User) -> FakeUserRepository:
    return FakeUserRepository([active_user, suspended_user])


@pytest.fixture
def enrollment_repo() -> FakeEnrollmentRepository:
    return FakeEnrollmentRepository()


@pytest.fixture
def consent_repo() -> FakeConsentRepository:
    return FakeConsentRepository()


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


def _client(
    enrollment_repo: FakeEnrollmentRepository,
    consent_repo: FakeConsentRepository,
    user_repo: FakeUserRepository,
    audit_repo: FakeAuditLogRepository,
    role: StaffRole,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_enrollment_repository] = lambda: enrollment_repo
    app.dependency_overrides[get_consent_repository] = lambda: consent_repo
    app.dependency_overrides[get_user_repository_dep] = lambda: user_repo
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repo
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email=f"{role.value.lower()}@example.com", role=role
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(enrollment_repo, consent_repo, user_repo, audit_repo) -> TestClient:
    return _client(enrollment_repo, consent_repo, user_repo, audit_repo, StaffRole.ADMIN)


@pytest.fixture
def operator_client(enrollment_repo, consent_repo, user_repo, audit_repo) -> TestClient:
    return _client(enrollment_repo, consent_repo, user_repo, audit_repo, StaffRole.OPERATOR)


@pytest.fixture
def viewer_client(enrollment_repo, consent_repo, user_repo, audit_repo) -> TestClient:
    return _client(enrollment_repo, consent_repo, user_repo, audit_repo, StaffRole.VIEWER)


# --- POST /enrollments (create) ------------------------------------------


def test_create_enrollment_succeeds_for_active_user(
    admin_client: TestClient, active_user: User, audit_repo: FakeAuditLogRepository
) -> None:
    response = admin_client.post("/api/v1/enrollments", json={"user_id": str(active_user.id)})
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(active_user.id)
    assert body["state"] == "CREATED"
    assert any(e["action"] == "enrollment.create" for e in audit_repo.entries)


def test_create_enrollment_succeeds_for_operator(
    operator_client: TestClient, active_user: User
) -> None:
    response = operator_client.post("/api/v1/enrollments", json={"user_id": str(active_user.id)})
    assert response.status_code == 201


def test_create_enrollment_denied_for_viewer(viewer_client: TestClient, active_user: User) -> None:
    response = viewer_client.post("/api/v1/enrollments", json={"user_id": str(active_user.id)})
    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


def test_create_enrollment_rejects_unknown_user(admin_client: TestClient) -> None:
    response = admin_client.post("/api/v1/enrollments", json={"user_id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")


def test_create_enrollment_rejects_non_active_user(
    admin_client: TestClient, suspended_user: User
) -> None:
    response = admin_client.post("/api/v1/enrollments", json={"user_id": str(suspended_user.id)})
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_create_enrollment_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/v1/enrollments", json={"user_id": str(uuid.uuid4())})
    assert response.status_code == 401


# --- GET /enrollments / /enrollments/{id} --------------------------------


def test_list_enrollments_filters_by_state(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CREATED))
    enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CANCELLED))

    response = viewer_client.get("/api/v1/enrollments", params={"state": "CANCELLED"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["state"] == "CANCELLED"


def test_list_enrollments_filters_by_user_id(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id))
    enrollment_repo.create(_make_session(uuid.uuid4()))

    response = viewer_client.get("/api/v1/enrollments", params={"user_id": str(active_user.id)})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(session.id)


def test_get_enrollment_returns_detail(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id))
    response = viewer_client.get(f"/api/v1/enrollments/{session.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(session.id)


def test_get_enrollment_returns_404_for_unknown_id(viewer_client: TestClient) -> None:
    response = viewer_client.get(f"/api/v1/enrollments/{uuid.uuid4()}")
    assert response.status_code == 404


# --- POST /enrollments/{id}/consent ---------------------------------------


def test_grant_consent_transitions_created_to_consented(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    consent_repo: FakeConsentRepository,
    audit_repo: FakeAuditLogRepository,
    active_user: User,
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CREATED))
    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/consent", json={"consent_version": "v1.0"}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "CONSENTED"
    assert len(consent_repo.consents) == 1
    assert consent_repo.consents[0].consent_version == "v1.0"
    assert any(e["action"] == "enrollment.consent_granted" for e in audit_repo.entries)


def test_grant_consent_denied_for_viewer(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CREATED))
    response = viewer_client.post(
        f"/api/v1/enrollments/{session.id}/consent", json={"consent_version": "v1.0"}
    )
    assert response.status_code == 403


def test_grant_consent_rejects_when_not_created(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CONSENTED))
    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/consent", json={"consent_version": "v1.0"}
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_grant_consent_returns_404_for_unknown_session(admin_client: TestClient) -> None:
    response = admin_client.post(
        f"/api/v1/enrollments/{uuid.uuid4()}/consent", json={"consent_version": "v1.0"}
    )
    assert response.status_code == 404


# --- EC-BE-09: consent_version bump (append-only, not blocking) -----------


def test_current_consent_version_was_bumped_from_v1_0() -> None:
    """Documents the exact old -> new value for EC-FE-05 to reference.

    EC-BE-09 bumps the consent clause version to cover synthetic
    masked/occlusion templates (EC-TR-02/03/06), event-frame `recent`/probe
    calibration templates (EC-TR-08), and the `template_candidates` buffer
    (EC-TR-09/EC-BE-07). The version string itself lives in exactly one
    place: `app.models.consent.CURRENT_CONSENT_VERSION`.
    """
    # v1.2 (2026-09-02): enrollment records per-position PHOTOS, not a
    # video, so what the subject consents to being recorded changed --
    # see the constant's own docstring.
    assert CURRENT_CONSENT_VERSION == "v1.2"
    assert CURRENT_CONSENT_VERSION not in {"v1.0", "v1.1"}


def test_grant_consent_stores_new_current_version(
    admin_client: TestClient,
    consent_repo: FakeConsentRepository,
    enrollment_repo: FakeEnrollmentRepository,
    active_user: User,
) -> None:
    """A consent granted after this release, using the new version string,
    is accepted and stored as-is (append-only create, BE-05 mechanism)."""
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CREATED))
    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/consent",
        json={"consent_version": CURRENT_CONSENT_VERSION},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "CONSENTED"
    assert len(consent_repo.consents) == 1
    assert consent_repo.consents[0].consent_version == CURRENT_CONSENT_VERSION


def test_old_consent_version_row_is_not_mutated_by_new_grant(
    admin_client: TestClient,
    consent_repo: FakeConsentRepository,
    enrollment_repo: FakeEnrollmentRepository,
    active_user: User,
) -> None:
    """Append-only versioning: an existing v1.0 consent row for a user is
    left untouched when a *different* enrollment session for that same user
    later grants consent under the new version — both rows coexist, and the
    audit trail can tell old vs new apart purely by `consent_version` per
    row (AC: "audit trail versi lama vs baru bisa dibedakan by
    consent_version per row")."""
    old_consent = Consent(
        id=uuid.uuid4(),
        user_id=active_user.id,
        consent_version="v1.0",
        granted_at=datetime.now(UTC),
        revoked_at=None,
    )
    consent_repo.consents.append(old_consent)

    new_session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CREATED))
    response = admin_client.post(
        f"/api/v1/enrollments/{new_session.id}/consent",
        json={"consent_version": CURRENT_CONSENT_VERSION},
    )
    assert response.status_code == 200

    versions_for_user = sorted(
        c.consent_version for c in consent_repo.list_for_user(active_user.id)
    )
    assert versions_for_user == sorted(["v1.0", CURRENT_CONSENT_VERSION])
    # The pre-existing v1.0 row itself was never rewritten in place.
    assert old_consent.consent_version == "v1.0"
    assert old_consent.revoked_at is None


def test_old_consent_version_still_unblocks_capture_transition(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    """A user whose only consent record predates this version bump (still
    `v1.0`, no re-consent performed after release) must not be blocked from
    proceeding: the state-machine gate only cares that a CONSENTED session
    exists (see `enrollment_service.grant_consent`), never which specific
    `consent_version` string was recorded (AC: "user existing tanpa
    re-consent tidak diblokir aksesnya")."""
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CREATED))
    consent_response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/consent", json={"consent_version": "v1.0"}
    )
    assert consent_response.status_code == 200
    assert consent_response.json()["state"] == "CONSENTED"

    transition_response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/transition", json={"target_state": "CAPTURING"}
    )
    assert transition_response.status_code == 200
    assert transition_response.json()["state"] == "CAPTURING"


# --- POST /enrollments/{id}/transition ------------------------------------


def test_transition_to_capturing_blocked_before_consent(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    """Consent gating (FR-ENR-08): CAPTURING is unreachable from CREATED."""
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CREATED))
    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/transition", json={"target_state": "CAPTURING"}
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_transition_to_capturing_succeeds_after_consent(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    audit_repo: FakeAuditLogRepository,
    active_user: User,
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CONSENTED))
    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/transition", json={"target_state": "CAPTURING"}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "CAPTURING"
    assert any(e["action"] == "enrollment.transition" for e in audit_repo.entries)


def test_transition_to_capturing_succeeds_after_rejected_quality(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(
        _make_session(active_user.id, EnrollmentState.REJECTED_QUALITY)
    )
    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/transition", json={"target_state": "CAPTURING"}
    )
    assert response.status_code == 200
    assert response.json()["state"] == "CAPTURING"


def test_transition_rejects_out_of_scope_target(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    """QC/embedding-driven states are not reachable through this endpoint,
    even if the underlying state machine would otherwise allow the edge."""
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CAPTURED))
    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/transition", json={"target_state": "QC_RUNNING"}
    )
    assert response.status_code == 409


def test_transition_denied_for_viewer(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CONSENTED))
    response = viewer_client.post(
        f"/api/v1/enrollments/{session.id}/transition", json={"target_state": "CAPTURING"}
    )
    assert response.status_code == 403


def test_transition_returns_404_for_unknown_session(admin_client: TestClient) -> None:
    response = admin_client.post(
        f"/api/v1/enrollments/{uuid.uuid4()}/transition", json={"target_state": "CAPTURING"}
    )
    assert response.status_code == 404


def test_transition_rejects_invalid_state_enum(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CONSENTED))
    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/transition", json={"target_state": "NOT_A_STATE"}
    )
    assert response.status_code == 422


# --- POST /enrollments/{id}/cancel ----------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        EnrollmentState.CREATED,
        EnrollmentState.CONSENTED,
        EnrollmentState.CAPTURING,
        EnrollmentState.CAPTURED,
        EnrollmentState.QC_RUNNING,
        EnrollmentState.REJECTED_QUALITY,
        EnrollmentState.QC_PASSED,
        EnrollmentState.EMBEDDING,
    ],
)
def test_cancel_succeeds_from_any_non_terminal_state(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    audit_repo: FakeAuditLogRepository,
    active_user: User,
    state: EnrollmentState,
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, state))
    response = admin_client.post(f"/api/v1/enrollments/{session.id}/cancel")
    assert response.status_code == 200
    assert response.json()["state"] == "CANCELLED"
    assert any(e["action"] == "enrollment.cancel" for e in audit_repo.entries)


@pytest.mark.parametrize(
    "state", [EnrollmentState.CANCELLED, EnrollmentState.REVOKED, EnrollmentState.ENROLLED]
)
def test_cancel_rejected_from_terminal_states(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    active_user: User,
    state: EnrollmentState,
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, state))
    response = admin_client.post(f"/api/v1/enrollments/{session.id}/cancel")
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_cancel_denied_for_viewer(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.CREATED))
    response = viewer_client.post(f"/api/v1/enrollments/{session.id}/cancel")
    assert response.status_code == 403


def test_cancel_returns_404_for_unknown_session(admin_client: TestClient) -> None:
    response = admin_client.post(f"/api/v1/enrollments/{uuid.uuid4()}/cancel")
    assert response.status_code == 404


# --- DELETE /enrollments/{id} (revoke, BE-08) ----------------------------
#
# Dispatch of the async cleanup job is NOT mocked here — same as
# test_enrollments_media_router.py's complete_enrollment tests, which let
# `qc_queue.enqueue_qc_job` attempt (and best-effort swallow the failure of)
# a real Celery dispatch with no broker present in CI. See
# app/services/revocation_queue.py for why that's safe.


def test_revoke_succeeds_from_enrolled_admin_only(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    user_repo: FakeUserRepository,
    audit_repo: FakeAuditLogRepository,
    active_user: User,
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.ENROLLED))

    response = admin_client.delete(f"/api/v1/enrollments/{session.id}")

    assert response.status_code == 202
    body = response.json()
    assert body == {"id": str(session.id), "state": "REVOKED"}
    assert enrollment_repo.get(session.id).state == EnrollmentState.REVOKED
    assert user_repo.get(active_user.id).status == UserStatus.OFFBOARDED
    assert any(e["action"] == "enrollment.revoke_initiated" for e in audit_repo.entries)


@pytest.mark.parametrize(
    "state",
    [
        EnrollmentState.CREATED,
        EnrollmentState.CONSENTED,
        EnrollmentState.CAPTURING,
        EnrollmentState.CAPTURED,
        EnrollmentState.QC_RUNNING,
        EnrollmentState.REJECTED_QUALITY,
        EnrollmentState.QC_PASSED,
        EnrollmentState.EMBEDDING,
        EnrollmentState.CANCELLED,
        EnrollmentState.REVOKED,
    ],
)
def test_revoke_rejected_unless_enrolled(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    active_user: User,
    state: EnrollmentState,
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, state))
    response = admin_client.delete(f"/api/v1/enrollments/{session.id}")
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_revoke_denied_for_operator(
    operator_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    """Revocation is stricter than every other write endpoint: ADMIN only,
    OPERATOR excluded (unlike create/consent/transition/cancel)."""
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.ENROLLED))
    response = operator_client.delete(f"/api/v1/enrollments/{session.id}")
    assert response.status_code == 403


def test_revoke_denied_for_viewer(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository, active_user: User
) -> None:
    session = enrollment_repo.create(_make_session(active_user.id, EnrollmentState.ENROLLED))
    response = viewer_client.delete(f"/api/v1/enrollments/{session.id}")
    assert response.status_code == 403


def test_revoke_returns_404_for_unknown_session(admin_client: TestClient) -> None:
    response = admin_client.delete(f"/api/v1/enrollments/{uuid.uuid4()}")
    assert response.status_code == 404
