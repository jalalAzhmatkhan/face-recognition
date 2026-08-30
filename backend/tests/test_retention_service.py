"""Unit tests for app/services/retention_service.py (BE-14, ASM-10, NFR-SEC-03).

Pure unit tests, no live Postgres/S3/Redis — fake repos in the same style as
tests/test_worker_tasks.py (FakeEnrollmentRepo/FakeAuditRepo/FakeS3Client).
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError

from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, MediaKind, MediaObjectStatus
from app.models.media_object import MediaObject
from app.services import retention_service


class FakeEnrollmentRepo:
    def __init__(self, sessions: list[EnrollmentSession]) -> None:
        self._sessions = {s.id: s for s in sessions}

    def get(self, session_id: uuid.UUID) -> EnrollmentSession | None:
        return self._sessions.get(session_id)


class FakeMediaRepo:
    def __init__(self, media: list[MediaObject]) -> None:
        self._media = list(media)
        self.updated: list[MediaObject] = []
        self.deleted: list[MediaObject] = []

    def list_finalized_without_retention(self, *, kinds) -> list[MediaObject]:
        kinds = set(kinds)
        return [
            m
            for m in self._media
            if m.status == MediaObjectStatus.FINALIZED
            and m.retention_expires_at is None
            and m.kind in kinds
        ]

    def list_expired(self, *, now: datetime) -> list[MediaObject]:
        return [
            m
            for m in self._media
            if m.retention_expires_at is not None and m.retention_expires_at <= now
        ]

    def update(self, media: MediaObject) -> MediaObject:
        self.updated.append(media)
        return media

    def delete(self, media: MediaObject) -> None:
        self._media = [m for m in self._media if m.id != media.id]
        self.deleted.append(media)


class FakeAuditRepo:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor, action, entity, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


class FakeS3Client:
    def __init__(
        self, *, missing_keys: set[str] | None = None, boom_keys: set[str] | None = None
    ) -> None:
        self.deleted_objects: list[tuple[str, str]] = []
        self._missing_keys = missing_keys or set()
        self._boom_keys = boom_keys or set()

    def delete_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803 - mirrors boto3
        if Key in self._boom_keys:
            raise TimeoutError("simulated S3 timeout")
        if Key in self._missing_keys:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "Not Found"}, "ResponseMetadata": {}},
                "DeleteObject",
            )
        self.deleted_objects.append((Bucket, Key))
        return {}


def _session(state: EnrollmentState, *, updated_at: datetime | None = None) -> EnrollmentSession:
    now = updated_at or datetime.now(UTC)
    return EnrollmentSession(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        state=state,
        qc_report=None,
        created_by=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )


def _media(
    session_id: uuid.UUID,
    *,
    kind: MediaKind = MediaKind.PHOTO,
    status: MediaObjectStatus = MediaObjectStatus.FINALIZED,
    retention_expires_at: datetime | None = None,
    created_at: datetime | None = None,
) -> MediaObject:
    return MediaObject(
        id=uuid.uuid4(),
        session_id=session_id,
        kind=kind,
        s3_bucket="test-bucket",
        s3_key=f"media/{session_id}/{uuid.uuid4()}.jpg",
        checksum="a" * 64,
        size=1024,
        content_type="image/jpeg",
        status=status,
        created_at=created_at or datetime.now(UTC),
        retention_expires_at=retention_expires_at,
    )


# --- backfill_retention_expiry ----------------------------------------------


def test_backfill_sets_expiry_for_photo_video_on_enrolled_session() -> None:
    enrolled_at = datetime(2026, 1, 1, tzinfo=UTC)
    session = _session(EnrollmentState.ENROLLED, updated_at=enrolled_at)
    photo = _media(session.id, kind=MediaKind.PHOTO)
    video = _media(session.id, kind=MediaKind.VIDEO)

    media_repo = FakeMediaRepo([photo, video])
    enrollment_repo = FakeEnrollmentRepo([session])

    result = retention_service.backfill_retention_expiry(
        media_repo, enrollment_repo, raw_media_days=90, event_frame_days=30
    )

    assert result.raw_media_set == 2
    assert result.event_frame_set == 0
    assert result.skipped_not_enrolled == 0
    assert photo.retention_expires_at == enrolled_at + timedelta(days=90)
    assert video.retention_expires_at == enrolled_at + timedelta(days=90)
    assert len(media_repo.updated) == 2


def test_backfill_sets_expiry_for_event_frame_from_created_at() -> None:
    created_at = datetime(2026, 2, 1, tzinfo=UTC)
    session = _session(EnrollmentState.CREATED)  # irrelevant for EVENT_FRAME
    frame = _media(session.id, kind=MediaKind.EVENT_FRAME, created_at=created_at)

    media_repo = FakeMediaRepo([frame])
    enrollment_repo = FakeEnrollmentRepo([session])

    result = retention_service.backfill_retention_expiry(
        media_repo, enrollment_repo, raw_media_days=90, event_frame_days=30
    )

    assert result.event_frame_set == 1
    assert result.raw_media_set == 0
    assert frame.retention_expires_at == created_at + timedelta(days=30)


def test_backfill_does_not_overwrite_already_set_expiry() -> None:
    session = _session(EnrollmentState.ENROLLED)
    existing_expiry = datetime(2099, 1, 1, tzinfo=UTC)
    photo = _media(session.id, kind=MediaKind.PHOTO, retention_expires_at=existing_expiry)

    media_repo = FakeMediaRepo([photo])
    enrollment_repo = FakeEnrollmentRepo([session])

    result = retention_service.backfill_retention_expiry(
        media_repo, enrollment_repo, raw_media_days=90, event_frame_days=30
    )

    # FakeMediaRepo's list_finalized_without_retention already filters on
    # retention_expires_at IS NULL, so this asserts the repo-level filter is
    # what the service relies on for idempotency.
    assert result.raw_media_set == 0
    assert photo.retention_expires_at == existing_expiry
    assert media_repo.updated == []


@pytest.mark.parametrize(
    "state",
    [
        EnrollmentState.CREATED,
        EnrollmentState.CAPTURING,
        EnrollmentState.QC_RUNNING,
        EnrollmentState.EMBEDDING,
        EnrollmentState.REVOKED,
    ],
)
def test_backfill_skips_raw_media_when_session_not_enrolled(state: EnrollmentState) -> None:
    session = _session(state)
    photo = _media(session.id, kind=MediaKind.PHOTO)

    media_repo = FakeMediaRepo([photo])
    enrollment_repo = FakeEnrollmentRepo([session])

    result = retention_service.backfill_retention_expiry(
        media_repo, enrollment_repo, raw_media_days=90, event_frame_days=30
    )

    assert result.raw_media_set == 0
    assert result.skipped_not_enrolled == 1
    assert photo.retention_expires_at is None
    assert media_repo.updated == []


def test_backfill_skips_raw_media_when_session_missing() -> None:
    media_repo = FakeMediaRepo([_media(uuid.uuid4(), kind=MediaKind.PHOTO)])
    enrollment_repo = FakeEnrollmentRepo([])

    result = retention_service.backfill_retention_expiry(
        media_repo, enrollment_repo, raw_media_days=90, event_frame_days=30
    )

    assert result.raw_media_set == 0
    assert result.skipped_not_enrolled == 1


# --- purge_expired_media -----------------------------------------------------


def test_purge_deletes_expired_media_and_audits() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    session_id = uuid.uuid4()
    expired = _media(session_id, retention_expires_at=past)

    media_repo = FakeMediaRepo([expired])
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client()

    result = retention_service.purge_expired_media(media_repo, audit_repo, s3_client)

    assert result.purged == 1
    assert result.failed == 0
    assert (expired.s3_bucket, expired.s3_key) in s3_client.deleted_objects
    assert media_repo.deleted == [expired]
    assert len(audit_repo.entries) == 1
    entry = audit_repo.entries[0]
    assert entry["action"] == retention_service.RETENTION_PURGED_ACTION
    assert entry["actor"] == retention_service.RETENTION_PURGE_ACTOR
    assert entry["payload"]["media_id"] == str(expired.id)
    assert entry["payload"]["session_id"] == str(session_id)
    assert entry["payload"]["kind"] == expired.kind.value


def test_purge_does_not_touch_media_not_yet_expired() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    not_expired = _media(uuid.uuid4(), retention_expires_at=future)

    media_repo = FakeMediaRepo([not_expired])
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client()

    result = retention_service.purge_expired_media(media_repo, audit_repo, s3_client)

    assert result.purged == 0
    assert media_repo.deleted == []
    assert s3_client.deleted_objects == []
    assert audit_repo.entries == []


def test_purge_ignores_media_with_no_retention_set() -> None:
    no_retention = _media(uuid.uuid4(), retention_expires_at=None)

    media_repo = FakeMediaRepo([no_retention])
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client()

    result = retention_service.purge_expired_media(media_repo, audit_repo, s3_client)

    assert result.purged == 0
    assert media_repo.deleted == []


def test_purge_handles_missing_s3_object_gracefully() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    expired = _media(uuid.uuid4(), retention_expires_at=past)

    media_repo = FakeMediaRepo([expired])
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client(missing_keys={expired.s3_key})

    result = retention_service.purge_expired_media(media_repo, audit_repo, s3_client)

    # 404 on S3 delete is treated as success, not a failure — DB row + audit
    # log are still written.
    assert result.purged == 1
    assert result.failed == 0
    assert media_repo.deleted == [expired]
    assert len(audit_repo.entries) == 1


def test_purge_one_item_failure_does_not_stop_the_batch() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    boom = _media(uuid.uuid4(), retention_expires_at=past)
    ok = _media(uuid.uuid4(), retention_expires_at=past)

    media_repo = FakeMediaRepo([boom, ok])
    audit_repo = FakeAuditRepo()
    s3_client = FakeS3Client(boom_keys={boom.s3_key})

    result = retention_service.purge_expired_media(media_repo, audit_repo, s3_client)

    assert result.purged == 1
    assert result.failed == 1
    assert result.failed_media_ids == [boom.id]
    assert media_repo.deleted == [ok]
    assert len(audit_repo.entries) == 1
    assert audit_repo.entries[0]["payload"]["media_id"] == str(ok.id)


def test_purge_reraises_non_404_s3_client_error_as_a_failure() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    expired = _media(uuid.uuid4(), retention_expires_at=past)

    media_repo = FakeMediaRepo([expired])
    audit_repo = FakeAuditRepo()

    class PermissionDeniedS3Client:
        def delete_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
            raise ClientError(
                {"Error": {"Code": "403", "Message": "Forbidden"}, "ResponseMetadata": {}},
                "DeleteObject",
            )

    result = retention_service.purge_expired_media(
        media_repo, audit_repo, PermissionDeniedS3Client()
    )

    assert result.purged == 0
    assert result.failed == 1
    assert media_repo.deleted == []
    assert audit_repo.entries == []
