"""Unit tests for app/services/media_service.py (BE-06).

Covers: content-type/size allow-list validation, S3 key generation
(photo_{n}/rotation), presign flow against a mocked boto3 client (no real
AWS/MinIO), and the complete-flow validation logic (missing/mismatched
media -> 422-equivalent `MediaCompletionError`, success -> two chained
state transitions + finalized MediaObject rows).
"""

import base64
import hashlib
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, MediaKind, MediaObjectStatus
from app.models.media_object import MediaObject
from app.services import media_service


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_b64(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


# --- validate_media_request ------------------------------------------------


def test_validate_photo_accepts_jpeg_and_png() -> None:
    assert media_service.validate_media_request("photo", "image/jpeg", 2_000_000) == "jpg"
    assert media_service.validate_media_request("photo", "image/png", 2_000_000) == "png"


def test_validate_photo_rejects_disallowed_content_type() -> None:
    with pytest.raises(media_service.MediaValidationError):
        media_service.validate_media_request("photo", "image/gif", 2_000_000)


def test_validate_photo_rejects_oversized() -> None:
    with pytest.raises(media_service.MediaValidationError):
        media_service.validate_media_request(
            "photo", "image/jpeg", media_service.PHOTO_MAX_SIZE_BYTES + 1
        )


def test_validate_photo_rejects_undersized() -> None:
    with pytest.raises(media_service.MediaValidationError):
        media_service.validate_media_request("photo", "image/jpeg", 10)


def test_validate_video_accepts_webm() -> None:
    assert media_service.validate_media_request("video", "video/webm", 5_000_000) == "webm"


def test_validate_video_rejects_disallowed_content_type() -> None:
    with pytest.raises(media_service.MediaValidationError):
        media_service.validate_media_request("video", "video/mp4", 5_000_000)


def test_validate_video_rejects_oversized() -> None:
    with pytest.raises(media_service.MediaValidationError):
        media_service.validate_media_request(
            "video", "video/webm", media_service.VIDEO_MAX_SIZE_BYTES + 1
        )


# --- request_presign: key generation, session-state gating -----------------


class FakeEnrollmentRepo:
    def __init__(self, session: EnrollmentSession) -> None:
        self._session = session

    def get(self, session_id: uuid.UUID) -> EnrollmentSession | None:
        return self._session if session_id == self._session.id else None

    def update(self, session: EnrollmentSession) -> EnrollmentSession:
        self._session = session
        return session


class FakeMediaRepo:
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


class FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor, action, entity, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


class FakeSettings:
    aws_s3_bucket_name = "frac-media"
    aws_s3_prefix = "face-recognition/"


def _session(state: EnrollmentState = EnrollmentState.CAPTURING) -> EnrollmentSession:
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
def mock_s3() -> MagicMock:
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://example.test/presigned"
    return client


def test_presign_photo_key_uses_incrementing_index(mock_s3: MagicMock) -> None:
    session = _session()
    enrollment_repo = FakeEnrollmentRepo(session)
    media_repo = FakeMediaRepo()
    audit_repo = FakeAuditRepo()

    r1 = media_service.request_presign(
        enrollment_repo,
        media_repo,
        audit_repo,
        mock_s3,
        FakeSettings(),
        session_id=session.id,
        kind="photo",
        content_type="image/jpeg",
        size=1_000_000,
        sha256=_sha256_hex(b"a"),
        actor="staff-1",
    )
    r2 = media_service.request_presign(
        enrollment_repo,
        media_repo,
        audit_repo,
        mock_s3,
        FakeSettings(),
        session_id=session.id,
        kind="photo",
        content_type="image/png",
        size=1_000_000,
        sha256=_sha256_hex(b"b"),
        actor="staff-1",
    )

    base = f"face-recognition/enrollment/{session.user_id}/{session.id}"
    assert r1.media.s3_key == f"{base}/photo_1.jpg"
    assert r2.media.s3_key == f"{base}/photo_2.png"
    assert r1.media.status == MediaObjectStatus.PENDING
    assert any(e["action"] == "enrollment.media_presigned" for e in audit_repo.entries)


def test_presign_video_key_is_fixed_and_replaces_pending_row(mock_s3: MagicMock) -> None:
    session = _session()
    enrollment_repo = FakeEnrollmentRepo(session)
    media_repo = FakeMediaRepo()
    audit_repo = FakeAuditRepo()

    first = media_service.request_presign(
        enrollment_repo,
        media_repo,
        audit_repo,
        mock_s3,
        FakeSettings(),
        session_id=session.id,
        kind="video",
        content_type="video/webm",
        size=5_000_000,
        sha256=_sha256_hex(b"v1"),
        actor="staff-1",
    )
    base = f"face-recognition/enrollment/{session.user_id}/{session.id}"
    assert first.media.s3_key == f"{base}/rotation.webm"
    assert len(media_repo.items) == 1

    second = media_service.request_presign(
        enrollment_repo,
        media_repo,
        audit_repo,
        mock_s3,
        FakeSettings(),
        session_id=session.id,
        kind="video",
        content_type="video/webm",
        size=6_000_000,
        sha256=_sha256_hex(b"v2"),
        actor="staff-1",
    )
    # Retry replaces the old PENDING row rather than accumulating a second one.
    assert len(media_repo.items) == 1
    assert media_repo.items[0].id == second.media.id
    assert media_repo.items[0].size == 6_000_000


# --- EC-BE-02: variant defaulting ------------------------------------------


def test_presign_without_variant_defaults_to_default(mock_s3: MagicMock) -> None:
    """`PresignRequest.variant` is optional (EC-BE-02) — a caller that omits
    it entirely (every pre-EC-BE-02 caller) still succeeds, and the stored
    `MediaObject.variant` becomes `MediaVariant.DEFAULT`, not NULL/None."""
    from app.models.enums import MediaVariant

    session = _session()
    result = media_service.request_presign(
        FakeEnrollmentRepo(session),
        FakeMediaRepo(),
        FakeAuditRepo(),
        mock_s3,
        FakeSettings(),
        session_id=session.id,
        kind="photo",
        content_type="image/jpeg",
        size=1_000_000,
        sha256=_sha256_hex(b"a"),
        actor="staff-1",
    )
    assert result.media.variant == MediaVariant.DEFAULT


def test_presign_with_explicit_variant_is_stored(mock_s3: MagicMock) -> None:
    from app.models.enums import MediaVariant

    session = _session()
    result = media_service.request_presign(
        FakeEnrollmentRepo(session),
        FakeMediaRepo(),
        FakeAuditRepo(),
        mock_s3,
        FakeSettings(),
        session_id=session.id,
        kind="photo",
        content_type="image/jpeg",
        size=1_000_000,
        sha256=_sha256_hex(b"a"),
        actor="staff-1",
        variant="no_glasses",
    )
    assert result.media.variant == MediaVariant.NO_GLASSES


@pytest.mark.parametrize(
    "state",
    [
        EnrollmentState.CREATED,
        EnrollmentState.CONSENTED,
        EnrollmentState.CAPTURED,
        EnrollmentState.QC_RUNNING,
    ],
)
def test_presign_rejected_when_not_capturing(mock_s3: MagicMock, state: EnrollmentState) -> None:
    session = _session(state)
    enrollment_repo = FakeEnrollmentRepo(session)
    media_repo = FakeMediaRepo()
    audit_repo = FakeAuditRepo()

    with pytest.raises(media_service.SessionNotCapturingError):
        media_service.request_presign(
            enrollment_repo,
            media_repo,
            audit_repo,
            mock_s3,
            FakeSettings(),
            session_id=session.id,
            kind="photo",
            content_type="image/jpeg",
            size=1_000_000,
            sha256=_sha256_hex(b"a"),
            actor="staff-1",
        )


def test_generate_presigned_put_url_bakes_in_checksum() -> None:
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://example.test/put"
    url, expires_at = media_service.generate_presigned_put_url(
        client,
        bucket="frac-media",
        key="enrollment/u/s/photo_1.jpg",
        content_type="image/jpeg",
        sha256_hex=_sha256_hex(b"payload"),
        ttl_seconds=300,
    )
    assert url == "https://example.test/put"
    kwargs = client.generate_presigned_url.call_args.kwargs
    assert kwargs["Params"]["ChecksumSHA256"] == _sha256_b64(b"payload")
    assert kwargs["ExpiresIn"] == 300
    assert expires_at > datetime.now(UTC)


def test_generate_presigned_put_url_falls_back_without_checksum_param() -> None:
    client = MagicMock()
    # First call (with ChecksumSHA256) raises, simulating an old botocore
    # that rejects the param; second call (fallback) succeeds.
    client.generate_presigned_url.side_effect = [TypeError("unexpected keyword"), "https://ok"]
    url, _ = media_service.generate_presigned_put_url(
        client,
        bucket="frac-media",
        key="k",
        content_type="image/jpeg",
        sha256_hex=_sha256_hex(b"x"),
    )
    assert url == "https://ok"
    assert client.generate_presigned_url.call_count == 2
    second_kwargs = client.generate_presigned_url.call_args_list[1].kwargs
    assert "ChecksumSHA256" not in second_kwargs["Params"]


# --- complete_enrollment -----------------------------------------------


def _pending_media(session_id, kind, *, content_type, size, checksum_hex, s3_key) -> MediaObject:
    now = datetime.now(UTC)
    return MediaObject(
        id=uuid.uuid4(),
        session_id=session_id,
        kind=kind,
        s3_bucket="frac-media",
        s3_key=s3_key,
        checksum=checksum_hex,
        size=size,
        content_type=content_type,
        status=MediaObjectStatus.PENDING,
        created_at=now,
    )


def test_complete_rejects_when_no_photo() -> None:
    session = _session(EnrollmentState.CAPTURING)
    enrollment_repo = FakeEnrollmentRepo(session)
    media_repo = FakeMediaRepo()
    media_repo.items.append(
        _pending_media(
            session.id,
            MediaKind.VIDEO,
            content_type="video/webm",
            size=10,
            checksum_hex=_sha256_hex(b"v"),
            s3_key="k/rotation.webm",
        )
    )
    audit_repo = FakeAuditRepo()
    s3_client = MagicMock()

    with pytest.raises(media_service.MediaCompletionError) as excinfo:
        media_service.complete_enrollment(
            enrollment_repo,
            media_repo,
            audit_repo,
            s3_client,
            session_id=session.id,
            actor="staff-1",
        )
    codes = {r["code"] for r in excinfo.value.reasons}
    assert "missing_photo" in codes
    assert session.state == EnrollmentState.CAPTURING  # untouched


def test_complete_rejects_when_object_missing_in_s3() -> None:
    session = _session(EnrollmentState.CAPTURING)
    enrollment_repo = FakeEnrollmentRepo(session)
    media_repo = FakeMediaRepo()
    media_repo.items.append(
        _pending_media(
            session.id,
            MediaKind.PHOTO,
            content_type="image/jpeg",
            size=10,
            checksum_hex=_sha256_hex(b"p"),
            s3_key="k/photo_1.jpg",
        )
    )
    media_repo.items.append(
        _pending_media(
            session.id,
            MediaKind.VIDEO,
            content_type="video/webm",
            size=10,
            checksum_hex=_sha256_hex(b"v"),
            s3_key="k/rotation.webm",
        )
    )
    audit_repo = FakeAuditRepo()
    s3_client = MagicMock()
    s3_client.head_object.side_effect = ClientError(
        {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadObject"
    )

    with pytest.raises(media_service.MediaCompletionError) as excinfo:
        media_service.complete_enrollment(
            enrollment_repo,
            media_repo,
            audit_repo,
            s3_client,
            session_id=session.id,
            actor="staff-1",
        )
    codes = {r["code"] for r in excinfo.value.reasons}
    assert "object_not_found" in codes
    assert session.state == EnrollmentState.CAPTURING


def test_complete_rejects_size_mismatch() -> None:
    session = _session(EnrollmentState.CAPTURING)
    enrollment_repo = FakeEnrollmentRepo(session)
    media_repo = FakeMediaRepo()
    photo = _pending_media(
        session.id,
        MediaKind.PHOTO,
        content_type="image/jpeg",
        size=999,
        checksum_hex=_sha256_hex(b"p"),
        s3_key="k/photo_1.jpg",
    )
    video = _pending_media(
        session.id,
        MediaKind.VIDEO,
        content_type="video/webm",
        size=999,
        checksum_hex=_sha256_hex(b"v"),
        s3_key="k/rotation.webm",
    )
    media_repo.items.extend([photo, video])
    audit_repo = FakeAuditRepo()
    s3_client = MagicMock()
    s3_client.head_object.return_value = {"ContentLength": 111, "ContentType": "image/jpeg"}

    with pytest.raises(media_service.MediaCompletionError) as excinfo:
        media_service.complete_enrollment(
            enrollment_repo,
            media_repo,
            audit_repo,
            s3_client,
            session_id=session.id,
            actor="staff-1",
        )
    codes = {r["code"] for r in excinfo.value.reasons}
    assert "size_mismatch" in codes


def test_complete_succeeds_and_transitions_to_qc_running() -> None:
    session = _session(EnrollmentState.CAPTURING)
    enrollment_repo = FakeEnrollmentRepo(session)
    media_repo = FakeMediaRepo()
    photo_bytes, video_bytes = b"photo-bytes", b"video-bytes"
    photo = _pending_media(
        session.id,
        MediaKind.PHOTO,
        content_type="image/jpeg",
        size=len(photo_bytes),
        checksum_hex=_sha256_hex(photo_bytes),
        s3_key="k/photo_1.jpg",
    )
    video = _pending_media(
        session.id,
        MediaKind.VIDEO,
        content_type="video/webm",
        size=len(video_bytes),
        checksum_hex=_sha256_hex(video_bytes),
        s3_key="k/rotation.webm",
    )
    media_repo.items.extend([photo, video])
    audit_repo = FakeAuditRepo()

    def head_object(**kwargs):
        if kwargs["Key"] == "k/photo_1.jpg":
            return {
                "ContentLength": len(photo_bytes),
                "ContentType": "image/jpeg",
                "ChecksumSHA256": _sha256_b64(photo_bytes),
            }
        return {
            "ContentLength": len(video_bytes),
            "ContentType": "video/webm",
            "ChecksumSHA256": _sha256_b64(video_bytes),
        }

    s3_client = MagicMock()
    s3_client.head_object.side_effect = head_object

    result = media_service.complete_enrollment(
        enrollment_repo,
        media_repo,
        audit_repo,
        s3_client,
        session_id=session.id,
        actor="staff-1",
    )

    assert result.state == EnrollmentState.QC_RUNNING
    assert session.state == EnrollmentState.QC_RUNNING
    assert photo.status == MediaObjectStatus.FINALIZED
    assert video.status == MediaObjectStatus.FINALIZED
    actions = [e["action"] for e in audit_repo.entries]
    assert "enrollment.captured" in actions
    assert "enrollment.qc_running" in actions
    assert "enrollment.media_completed" in actions


@pytest.mark.parametrize(
    "state",
    [EnrollmentState.CREATED, EnrollmentState.CONSENTED, EnrollmentState.CAPTURED],
)
def test_complete_rejected_when_not_capturing(state: EnrollmentState) -> None:
    session = _session(state)
    enrollment_repo = FakeEnrollmentRepo(session)
    media_repo = FakeMediaRepo()
    audit_repo = FakeAuditRepo()
    s3_client = MagicMock()

    with pytest.raises(media_service.SessionNotCapturingError):
        media_service.complete_enrollment(
            enrollment_repo,
            media_repo,
            audit_repo,
            s3_client,
            session_id=session.id,
            actor="staff-1",
        )
