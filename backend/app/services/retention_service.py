"""Retention automation (BE-14, ASM-10, NFR-SEC-03).

ASM-10 (FSD-AI.md): "Retention default: raw enrollment media retained 90 days
after successful embedding extraction then lifecycle-deleted; embeddings
retained while user is active. Configurable." NFR-SEC-03: "... deletion of a
user cascades to embeddings, media, and (via lifecycle) backups per retention
policy."

Two independent jobs, both idempotent and safe to run repeatedly on a
schedule (Celery Beat, see app/worker/celery_app.py):

1. `backfill_retention_expiry` — "lifecycle verification": for every
   FINALIZED `media_objects` row that doesn't have `retention_expires_at`
   set yet, compute and set it. Never overwrites an already-set value, so
   running it twice (or every hour, per the beat schedule) is a no-op for
   rows already processed.
2. `purge_expired_media` — the actual lifecycle deletion: for every
   `media_objects` row whose `retention_expires_at` has passed, delete the
   S3 object, delete the DB row, and write one `audit_logs` entry per
   deleted item (acceptance criteria: "media kadaluarsa terhapus otomatis +
   teraudit").

### Anchor timestamp for PHOTO/VIDEO (raw enrollment media)

ASM-10 says the 90-day clock starts "after successful embedding extraction".
There is no dedicated "embedding extraction completed at" timestamp anywhere
in the schema. What we do have is `enrollment_sessions.updated_at`
(`TimestampMixin`, ORM `onupdate=func.now()`) at the moment `state ==
ENROLLED` — reaching `ENROLLED` IS the terminal step that follows successful
embedding extraction (see EnrollmentState docstring in app/models/enums.py),
so `updated_at` at that point is used as a **proxy/anchor** for "when this
session finished enrolling".

This is APPROXIMATE, for two compounding reasons:
  - the transition to `ENROLLED` is actually performed by the `ai-training/`
    worker (TR-02/TR-03) via **raw SQL directly against the DB**, not via
    `app/services/enrollment_state_machine.py` — so it is not guaranteed
    that raw SQL path sets `updated_at` the same way the ORM would;
  - even if it does, `updated_at` reflects the *last* update to the row, not
    necessarily *the* update that flipped state to ENROLLED — any later
    write to the same row (by any process) would push the anchor forward.

Both failure modes point the same direction: `updated_at` can end up LATER
than the true "embedding extraction completed" moment, never earlier. That
makes the anchor's error one-sided and safe for a privacy/retention feature:
media may be retained a bit LONGER than the ASM-10 default, but is never
purged EARLIER than intended. Tightening this (e.g. a dedicated
`embeddings_extracted_at` column populated by ai-training) is out of scope
for BE-14 — see the task's "di luar scope" notes.

### Anchor timestamp for EVENT_FRAME (door-camera frames)

EVENT_FRAME media (`AccessEvent.frame_media_id`) is conceptually independent
of any enrollment session — a door-camera capture has nothing to do with
enrollment lifecycle. Its retention clock therefore anchors on
`media_objects.created_at` (when the frame object itself was recorded), not
on any enrollment session field.

**Known schema gap (out of scope for BE-14, noted here for whoever picks up
IN-06):** `media_objects.session_id` is currently `NOT NULL` (a mandatory FK
to `enrollment_sessions`), which is incompatible with an EVENT_FRAME that
has no enrollment session at all. No code today actually inserts EVENT_FRAME
rows (`ai-inference/` — the would-be producer, IN-06 — doesn't exist yet), so
there is no live data to migrate; but `session_id` will need to become
nullable before IN-06 can create real EVENT_FRAME rows. The cleanup logic
below is written generically against `kind == EVENT_FRAME` so it needs no
changes once that schema fix lands — it simply starts seeing real rows.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from botocore.exceptions import ClientError

from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, MediaKind
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.media_objects import MediaObjectRepository

logger = logging.getLogger(__name__)


class _EnrollmentSessionLookup(Protocol):
    """Minimal shape retention_service needs from EnrollmentSessionRepository
    (kept as a Protocol so tests can pass a lightweight fake, same style as
    the Fake*Repo classes in tests/test_worker_tasks.py)."""

    def get(self, session_id: uuid.UUID) -> EnrollmentSession | None: ...


RETENTION_PURGED_ACTION = "media.retention_purged"
RETENTION_PURGE_ACTOR = "system:retention-job"

RAW_MEDIA_KINDS: tuple[MediaKind, ...] = (MediaKind.PHOTO, MediaKind.VIDEO)


@dataclass
class BackfillResult:
    """Outcome of one `backfill_retention_expiry` run, for logging/tests."""

    raw_media_set: int = 0
    event_frame_set: int = 0
    skipped_not_enrolled: int = 0

    @property
    def total_set(self) -> int:
        return self.raw_media_set + self.event_frame_set


@dataclass
class PurgeResult:
    """Outcome of one `purge_expired_media` run, for logging/tests."""

    purged: int = 0
    failed: int = 0
    failed_media_ids: list[uuid.UUID] = field(default_factory=list)


def backfill_retention_expiry(
    media_repo: MediaObjectRepository,
    enrollment_repo: _EnrollmentSessionLookup,
    *,
    raw_media_days: int,
    event_frame_days: int,
) -> BackfillResult:
    """Set `retention_expires_at` on FINALIZED media that doesn't have it yet.

    Idempotent: only ever touches rows where `retention_expires_at IS NULL`
    (`MediaObjectRepository.list_finalized_without_retention`), so calling
    this repeatedly (as the Celery Beat schedule does, hourly by default)
    never re-computes or overwrites an already-set expiry.
    """
    result = BackfillResult()

    # --- Raw enrollment media (PHOTO/VIDEO): anchor = enrollment session's
    # updated_at, only for sessions that reached ENROLLED. See module
    # docstring for the full anchor-timestamp rationale/caveats.
    raw_media = media_repo.list_finalized_without_retention(kinds=RAW_MEDIA_KINDS)
    for media in raw_media:
        session = enrollment_repo.get(media.session_id)
        if session is None or session.state != EnrollmentState.ENROLLED:
            # Not enrolled yet (or session vanished) — nothing to anchor on.
            # Leave retention_expires_at NULL; a later run picks it up once
            # (if) the session reaches ENROLLED.
            result.skipped_not_enrolled += 1
            continue
        media.retention_expires_at = session.updated_at + timedelta(days=raw_media_days)
        media_repo.update(media)
        result.raw_media_set += 1

    # --- Event-frame media: anchor = the media row's own created_at.
    event_frames = media_repo.list_finalized_without_retention(kinds=(MediaKind.EVENT_FRAME,))
    for media in event_frames:
        media.retention_expires_at = media.created_at + timedelta(days=event_frame_days)
        media_repo.update(media)
        result.event_frame_set += 1

    logger.info(
        "retention_service.backfill_retention_expiry: raw_media_set=%d event_frame_set=%d "
        "skipped_not_enrolled=%d",
        result.raw_media_set,
        result.event_frame_set,
        result.skipped_not_enrolled,
    )
    return result


def purge_expired_media(
    media_repo: MediaObjectRepository,
    audit_repo: AuditLogRepository,
    s3_client: Any,
    *,
    now: datetime | None = None,
) -> PurgeResult:
    """Delete every `media_objects` row whose retention has expired.

    Per-item try/except (retry-safe per acceptance criteria): one media
    failing to delete (S3 timeout, unexpected error) does not abort the
    batch — it's logged, counted as failed, and the loop continues onto the
    next item. A missing S3 object (already deleted manually or by a prior
    partial run) is treated as success, not failure — see
    `_delete_s3_object_if_present`.
    """
    now = now or datetime.now(UTC)
    result = PurgeResult()

    expired = media_repo.list_expired(now=now)

    for media in expired:
        try:
            _delete_s3_object_if_present(s3_client, bucket=media.s3_bucket, key=media.s3_key)
            media_id = media.id
            session_id = media.session_id
            kind = media.kind
            retention_expires_at = media.retention_expires_at
            media_repo.delete(media)
            audit_repo.record(
                actor=RETENTION_PURGE_ACTOR,
                action=RETENTION_PURGED_ACTION,
                entity=f"media_object:{media_id}",
                payload={
                    "media_id": str(media_id),
                    "session_id": str(session_id),
                    "kind": kind.value,
                    "retention_expires_at": (
                        retention_expires_at.isoformat() if retention_expires_at else None
                    ),
                },
            )
            result.purged += 1
        except Exception:  # noqa: BLE001 - one failure must not sink the batch
            logger.exception(
                "retention_service.purge_expired_media: failed to purge media_id=%s "
                "(will retry on the next scheduled run)",
                media.id,
            )
            result.failed += 1
            result.failed_media_ids.append(media.id)

    logger.info(
        "retention_service.purge_expired_media: purged=%d failed=%d",
        result.purged,
        result.failed,
    )
    return result


def _delete_s3_object_if_present(s3_client: Any, *, bucket: str, key: str) -> None:
    """Delete an S3 object, tolerating "already gone" as success.

    Mirrors the graceful-404 handling pattern in
    app/services/media_service.py::head_media_object — a NoSuchKey/404 from
    S3 (e.g. the object was already removed by a manual op or a previous
    partial retention run) is not an error for a *deletion* job; any other
    `ClientError` (permissions, transient failure) re-raises so the caller's
    per-item try/except records it as a real failure to retry later.
    """
    try:
        s3_client.delete_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if error_code in ("404", "NoSuchKey", "NotFound") or http_status == 404:
            logger.warning(
                "retention_service: S3 object already absent bucket=%s key=%s "
                "(treating delete as success)",
                bucket,
                key,
            )
            return
        raise
