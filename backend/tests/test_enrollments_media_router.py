"""Integration tests for `/api/v1/enrollments/{id}/media/presign` and
`/api/v1/enrollments/{id}/complete` (BE-06).

No real DB and no real AWS/MinIO: repositories are in-memory fakes (mirrors
test_enrollments_router.py) and the S3 client is a `moto`-mocked boto3
client (an in-process fake S3, not a network call) so presign/HEAD go
through real boto3 code paths without touching any real cloud service.
"""

import base64
import hashlib
import uuid
from datetime import UTC, datetime

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws

from app.core.config import Settings
from app.dependencies.auth import CurrentStaff, get_current_staff
from app.main import create_app
from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, MediaKind, MediaObjectStatus, StaffRole
from app.models.media_object import MediaObject
from app.routers.enrollments import (
    get_audit_log_repository,
    get_enrollment_repository,
    get_media_object_repository,
    get_s3_client_dependency,
    get_settings_dependency,
)

BUCKET = "frac-media"
PREFIX = "face-recognition/"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


class FakeEnrollmentRepository:
    def __init__(self, sessions: list[EnrollmentSession] | None = None) -> None:
        self._by_id: dict[uuid.UUID, EnrollmentSession] = {s.id: s for s in (sessions or [])}

    def get(self, session_id: uuid.UUID) -> EnrollmentSession | None:
        return self._by_id.get(session_id)

    def update(self, enrollment: EnrollmentSession) -> EnrollmentSession:
        enrollment.updated_at = datetime.now(UTC)
        self._by_id[enrollment.id] = enrollment
        return enrollment


class FakeMediaObjectRepository:
    def __init__(self) -> None:
        self.items: list[MediaObject] = []

    def list_for_session(self, session_id, *, kind=None, status=None):
        items = [m for m in self.items if m.session_id == session_id]
        if kind is not None:
            items = [m for m in items if m.kind == kind]
        if status is not None:
            items = [m for m in items if m.status == status]
        return items

    def create(self, media: MediaObject) -> MediaObject:
        media.id = media.id or uuid.uuid4()
        media.created_at = datetime.now(UTC)
        self.items.append(media)
        return media

    def update(self, media: MediaObject) -> MediaObject:
        return media

    def delete(self, media: MediaObject) -> None:
        self.items.remove(media)


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor, action, entity, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _make_session(state: EnrollmentState = EnrollmentState.CAPTURING) -> EnrollmentSession:
    now = datetime.now(UTC)
    return EnrollmentSession(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        state=state,
        qc_report=None,
        created_by=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def moto_s3():
    with mock_aws():
        client = boto3.client("s3", region_name="ap-southeast-1")
        client.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"},
        )
        yield client


@pytest.fixture
def enrollment_repo() -> FakeEnrollmentRepository:
    return FakeEnrollmentRepository()


@pytest.fixture
def media_repo() -> FakeMediaObjectRepository:
    return FakeMediaObjectRepository()


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


def _client(
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
    audit_repo: FakeAuditLogRepository,
    s3_client,
    role: StaffRole,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_enrollment_repository] = lambda: enrollment_repo
    app.dependency_overrides[get_media_object_repository] = lambda: media_repo
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repo
    app.dependency_overrides[get_s3_client_dependency] = lambda: s3_client
    app.dependency_overrides[get_settings_dependency] = lambda: Settings(
        aws_s3_bucket_name=BUCKET, aws_s3_prefix=PREFIX
    )
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email=f"{role.value.lower()}@example.com", role=role
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(enrollment_repo, media_repo, audit_repo, moto_s3) -> TestClient:
    return _client(enrollment_repo, media_repo, audit_repo, moto_s3, StaffRole.ADMIN)


@pytest.fixture
def viewer_client(enrollment_repo, media_repo, audit_repo, moto_s3) -> TestClient:
    return _client(enrollment_repo, media_repo, audit_repo, moto_s3, StaffRole.VIEWER)


# --- POST /enrollments/{id}/media/presign ---------------------------------


def test_presign_photo_succeeds_while_capturing(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    audit_repo: FakeAuditLogRepository,
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/media/presign",
        json={
            "kind": "photo",
            "content_type": "image/jpeg",
            "size": 2_000_000,
            "sha256": _sha256_hex(b"photo-bytes"),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["s3_key"] == f"{PREFIX}enrollment/{session.user_id}/{session.id}/photo_1.jpg"
    assert body["upload_url"]
    assert body["expires_at"]
    assert any(e["action"] == "enrollment.media_presigned" for e in audit_repo.entries)


def test_presign_rejects_disallowed_content_type(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/media/presign",
        json={
            "kind": "photo",
            "content_type": "image/gif",
            "size": 2_000_000,
            "sha256": _sha256_hex(b"x"),
        },
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_presign_rejects_when_session_not_capturing(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository
) -> None:
    session = _make_session(EnrollmentState.CREATED)
    enrollment_repo._by_id[session.id] = session

    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/media/presign",
        json={
            "kind": "photo",
            "content_type": "image/jpeg",
            "size": 2_000_000,
            "sha256": _sha256_hex(b"x"),
        },
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


def test_presign_returns_404_for_unknown_session(admin_client: TestClient) -> None:
    response = admin_client.post(
        f"/api/v1/enrollments/{uuid.uuid4()}/media/presign",
        json={
            "kind": "photo",
            "content_type": "image/jpeg",
            "size": 2_000_000,
            "sha256": _sha256_hex(b"x"),
        },
    )
    assert response.status_code == 404


def test_presign_denied_for_viewer(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    response = viewer_client.post(
        f"/api/v1/enrollments/{session.id}/media/presign",
        json={
            "kind": "photo",
            "content_type": "image/jpeg",
            "size": 2_000_000,
            "sha256": _sha256_hex(b"x"),
        },
    )
    assert response.status_code == 403


def test_presign_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        f"/api/v1/enrollments/{uuid.uuid4()}/media/presign",
        json={"kind": "photo", "content_type": "image/jpeg", "size": 1000, "sha256": "a" * 64},
    )
    assert response.status_code == 401


# --- POST /enrollments/{id}/complete ---------------------------------------


def test_complete_succeeds_with_photo_and_video_uploaded(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
    audit_repo: FakeAuditLogRepository,
    moto_s3,
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    photo_key = f"{PREFIX}enrollment/{session.user_id}/{session.id}/photo_1.jpg"
    video_key = f"{PREFIX}enrollment/{session.user_id}/{session.id}/rotation.webm"
    photo_bytes, video_bytes = b"photo-bytes", b"video-bytes" * 100

    # Simulate the frontend's direct-to-S3 PUT that would normally follow
    # the presigned URL (this test drives moto's S3 directly, exactly as
    # boto3 would after a real presigned PUT).
    moto_s3.put_object(
        Bucket=BUCKET,
        Key=photo_key,
        Body=photo_bytes,
        ContentType="image/jpeg",
        ChecksumAlgorithm="SHA256",
    )
    moto_s3.put_object(
        Bucket=BUCKET,
        Key=video_key,
        Body=video_bytes,
        ContentType="video/webm",
        ChecksumAlgorithm="SHA256",
    )

    media_repo.items.append(
        MediaObject(
            id=uuid.uuid4(),
            session_id=session.id,
            kind=MediaKind.PHOTO,
            s3_bucket=BUCKET,
            s3_key=photo_key,
            checksum=_sha256_hex(photo_bytes),
            size=len(photo_bytes),
            content_type="image/jpeg",
            status=MediaObjectStatus.PENDING,
            created_at=datetime.now(UTC),
        )
    )
    media_repo.items.append(
        MediaObject(
            id=uuid.uuid4(),
            session_id=session.id,
            kind=MediaKind.VIDEO,
            s3_bucket=BUCKET,
            s3_key=video_key,
            checksum=_sha256_hex(video_bytes),
            size=len(video_bytes),
            content_type="video/webm",
            status=MediaObjectStatus.PENDING,
            created_at=datetime.now(UTC),
        )
    )

    response = admin_client.post(f"/api/v1/enrollments/{session.id}/complete")
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "QC_RUNNING"
    assert session.state == EnrollmentState.QC_RUNNING
    assert all(m.status == MediaObjectStatus.FINALIZED for m in media_repo.items)
    actions = [e["action"] for e in audit_repo.entries]
    assert "enrollment.captured" in actions
    assert "enrollment.qc_running" in actions
    assert "enrollment.media_completed" in actions


def test_complete_returns_422_when_video_missing_from_s3(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
    moto_s3,
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    photo_key = f"{PREFIX}enrollment/{session.user_id}/{session.id}/photo_1.jpg"
    video_key = f"{PREFIX}enrollment/{session.user_id}/{session.id}/rotation.webm"
    photo_bytes = b"photo-bytes"

    # Only the photo actually landed in S3 — video presign was requested
    # but the upload never completed, so its HEAD must fail with 404.
    moto_s3.put_object(
        Bucket=BUCKET,
        Key=photo_key,
        Body=photo_bytes,
        ContentType="image/jpeg",
        ChecksumAlgorithm="SHA256",
    )

    media_repo.items.append(
        MediaObject(
            id=uuid.uuid4(),
            session_id=session.id,
            kind=MediaKind.PHOTO,
            s3_bucket=BUCKET,
            s3_key=photo_key,
            checksum=_sha256_hex(photo_bytes),
            size=len(photo_bytes),
            content_type="image/jpeg",
            status=MediaObjectStatus.PENDING,
            created_at=datetime.now(UTC),
        )
    )
    media_repo.items.append(
        MediaObject(
            id=uuid.uuid4(),
            session_id=session.id,
            kind=MediaKind.VIDEO,
            s3_bucket=BUCKET,
            s3_key=video_key,
            checksum=_sha256_hex(b"video-bytes"),
            size=11,
            content_type="video/webm",
            status=MediaObjectStatus.PENDING,
            created_at=datetime.now(UTC),
        )
    )

    response = admin_client.post(f"/api/v1/enrollments/{session.id}/complete")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    codes = {r["code"] for r in body["reasons"]}
    assert "object_not_found" in codes
    # State must be untouched on failure.
    assert session.state == EnrollmentState.CAPTURING


def test_complete_rejects_when_session_not_capturing(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository
) -> None:
    session = _make_session(EnrollmentState.CAPTURED)
    enrollment_repo._by_id[session.id] = session

    response = admin_client.post(f"/api/v1/enrollments/{session.id}/complete")
    assert response.status_code == 409


def test_complete_returns_404_for_unknown_session(admin_client: TestClient) -> None:
    response = admin_client.post(f"/api/v1/enrollments/{uuid.uuid4()}/complete")
    assert response.status_code == 404


def test_complete_denied_for_viewer(
    viewer_client: TestClient, enrollment_repo: FakeEnrollmentRepository
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    response = viewer_client.post(f"/api/v1/enrollments/{session.id}/complete")
    assert response.status_code == 403
