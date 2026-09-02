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
from datetime import UTC, datetime, timedelta

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


def test_presign_without_variant_field_defaults_to_default(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
) -> None:
    """EC-BE-02: a presign request body without `variant` (every
    pre-EC-BE-02 caller) still succeeds (201), and the stored row defaults
    to `MediaVariant.DEFAULT` rather than staying NULL."""
    from app.models.enums import MediaVariant

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
    assert media_repo.items[0].variant == MediaVariant.DEFAULT


def test_presign_with_explicit_variant_field_is_stored(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
) -> None:
    from app.models.enums import MediaVariant

    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/media/presign",
        json={
            "kind": "photo",
            "content_type": "image/jpeg",
            "size": 2_000_000,
            "sha256": _sha256_hex(b"photo-bytes"),
            "variant": "glasses",
        },
    )
    assert response.status_code == 201, response.text
    assert media_repo.items[0].variant == MediaVariant.GLASSES


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


# --- Per-clock-position photo capture (video -> photos migration) ----------


def _put_photo(moto_s3, key: str, body: bytes) -> None:
    moto_s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=body,
        ContentType="image/jpeg",
        ChecksumAlgorithm="SHA256",
    )


def _photo_row(session, key: str, body: bytes, *, clock_position: int | None, age_s: int = 0):
    return MediaObject(
        id=uuid.uuid4(),
        session_id=session.id,
        kind=MediaKind.PHOTO,
        s3_bucket=BUCKET,
        s3_key=key,
        checksum=_sha256_hex(body),
        size=len(body),
        content_type="image/jpeg",
        status=MediaObjectStatus.PENDING,
        clock_position=clock_position,
        created_at=datetime.now(UTC) - timedelta(seconds=age_s),
    )


def test_presign_positioned_photo_keys_by_position_and_burst_index(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session
    body = {
        "kind": "photo",
        "content_type": "image/jpeg",
        "size": 2000,
        "sha256": "b" * 64,
        "clock_position": 5,
    }

    first = admin_client.post(f"/api/v1/enrollments/{session.id}/media/presign", json=body)
    second = admin_client.post(f"/api/v1/enrollments/{session.id}/media/presign", json=body)

    assert first.status_code == 201, first.text
    assert first.json()["s3_key"].endswith("photo_pos_05_1.jpg")
    # A burst (and a re-shot position) appends candidates rather than
    # overwriting the first frame.
    assert second.json()["s3_key"].endswith("photo_pos_05_2.jpg")
    assert [m.clock_position for m in media_repo.items] == [5, 5]


def test_presign_frontal_photo_numbering_ignores_sweep_frames(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session
    base = {"kind": "photo", "content_type": "image/jpeg", "size": 2000, "sha256": "c" * 64}

    admin_client.post(
        f"/api/v1/enrollments/{session.id}/media/presign", json={**base, "clock_position": 7}
    )
    frontal = admin_client.post(f"/api/v1/enrollments/{session.id}/media/presign", json=base)

    # Sweep frames must not push the frontal photo's index along -- QC looks
    # up the neutral reference as the earliest position-less photo.
    assert frontal.json()["s3_key"].endswith("photo_1.jpg")


def test_presign_rejects_clock_position_on_a_video(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/media/presign",
        json={
            "kind": "video",
            "content_type": "video/webm",
            "size": 100_000,
            "sha256": "d" * 64,
            "clock_position": 3,
        },
    )
    assert response.status_code == 422


def test_presign_rejects_out_of_range_clock_position(
    admin_client: TestClient, enrollment_repo: FakeEnrollmentRepository
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session

    response = admin_client.post(
        f"/api/v1/enrollments/{session.id}/media/presign",
        json={
            "kind": "photo",
            "content_type": "image/jpeg",
            "size": 2000,
            "sha256": "e" * 64,
            "clock_position": 13,
        },
    )
    assert response.status_code == 422


def test_complete_succeeds_with_positioned_photos_and_no_video(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
    audit_repo: FakeAuditLogRepository,
    moto_s3,
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session
    prefix = f"{PREFIX}enrollment/{session.user_id}/{session.id}"

    frontal_key = f"{prefix}/photo_1.jpg"
    frontal_bytes = b"frontal-bytes"
    _put_photo(moto_s3, frontal_key, frontal_bytes)
    media_repo.items.append(_photo_row(session, frontal_key, frontal_bytes, clock_position=None))

    for position in range(1, 13):
        key = f"{prefix}/photo_pos_{position:02d}_1.jpg"
        body = f"sweep-{position}".encode()
        _put_photo(moto_s3, key, body)
        media_repo.items.append(_photo_row(session, key, body, clock_position=position))

    response = admin_client.post(f"/api/v1/enrollments/{session.id}/complete")

    assert response.status_code == 202, response.text
    assert session.state == EnrollmentState.QC_RUNNING
    assert all(m.status == MediaObjectStatus.FINALIZED for m in media_repo.items)
    completed = next(e for e in audit_repo.entries if e["action"] == "enrollment.media_completed")
    assert completed["payload"]["video_count"] == 0
    assert completed["payload"]["sweep_photo_count"] == 12
    assert completed["payload"]["positions_captured"] == list(range(1, 13))


def test_complete_rejects_mixing_positioned_photos_with_a_video(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
    moto_s3,
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session
    prefix = f"{PREFIX}enrollment/{session.user_id}/{session.id}"

    frontal_key, frontal_bytes = f"{prefix}/photo_1.jpg", b"frontal-bytes"
    sweep_key, sweep_bytes = f"{prefix}/photo_pos_01_1.jpg", b"sweep-bytes"
    video_key, video_bytes = f"{prefix}/rotation.webm", b"video-bytes" * 100
    _put_photo(moto_s3, frontal_key, frontal_bytes)
    _put_photo(moto_s3, sweep_key, sweep_bytes)
    moto_s3.put_object(
        Bucket=BUCKET,
        Key=video_key,
        Body=video_bytes,
        ContentType="video/webm",
        ChecksumAlgorithm="SHA256",
    )

    media_repo.items.append(_photo_row(session, frontal_key, frontal_bytes, clock_position=None))
    media_repo.items.append(_photo_row(session, sweep_key, sweep_bytes, clock_position=1))
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

    assert response.status_code == 422
    codes = {r["code"] for r in response.json()["reasons"]}
    assert "mixed_capture_shape" in codes
    assert session.state == EnrollmentState.CAPTURING


def test_complete_rejects_a_frontal_photo_with_no_sweep_and_no_video(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
    moto_s3,
) -> None:
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session
    key, body = f"{PREFIX}enrollment/{session.user_id}/{session.id}/photo_1.jpg", b"frontal"
    _put_photo(moto_s3, key, body)
    media_repo.items.append(_photo_row(session, key, body, clock_position=None))

    response = admin_client.post(f"/api/v1/enrollments/{session.id}/complete")

    assert response.status_code == 422
    codes = {r["code"] for r in response.json()["reasons"]}
    assert "missing_capture" in codes


def test_complete_keeps_an_uploaded_frame_whose_presign_url_already_expired(
    admin_client: TestClient,
    enrollment_repo: FakeEnrollmentRepository,
    media_repo: FakeMediaObjectRepository,
    audit_repo: FakeAuditLogRepository,
    moto_s3,
) -> None:
    """Per-position capture uploads progressively, so the earliest positions
    are minutes old by the time /complete runs. A row whose object really is
    in S3 must be finalized regardless of its presign TTL -- dropping it on
    age alone would silently discard coverage the subject did record."""
    session = _make_session(EnrollmentState.CAPTURING)
    enrollment_repo._by_id[session.id] = session
    prefix = f"{PREFIX}enrollment/{session.user_id}/{session.id}"

    frontal_key, frontal_bytes = f"{prefix}/photo_1.jpg", b"frontal-bytes"
    old_key, old_bytes = f"{prefix}/photo_pos_01_1.jpg", b"uploaded-long-ago"
    _put_photo(moto_s3, frontal_key, frontal_bytes)
    _put_photo(moto_s3, old_key, old_bytes)

    media_repo.items.append(_photo_row(session, frontal_key, frontal_bytes, clock_position=None))
    media_repo.items.append(_photo_row(session, old_key, old_bytes, clock_position=1, age_s=3600))
    # ...while a genuinely abandoned presign (object never landed, URL long
    # expired) is still excluded rather than blocking completion forever.
    media_repo.items.append(
        _photo_row(
            session,
            f"{prefix}/photo_pos_02_1.jpg",
            b"never-uploaded",
            clock_position=2,
            age_s=3600,
        )
    )

    response = admin_client.post(f"/api/v1/enrollments/{session.id}/complete")

    assert response.status_code == 202, response.text
    finalized = {m.s3_key for m in media_repo.items if m.status == MediaObjectStatus.FINALIZED}
    assert old_key in finalized
    completed = next(e for e in audit_repo.entries if e["action"] == "enrollment.media_completed")
    assert completed["payload"]["positions_captured"] == [1]
