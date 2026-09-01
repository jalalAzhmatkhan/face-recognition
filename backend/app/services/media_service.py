"""Enrollment media presign + completion business logic (BE-06, TSD §4/§6/§7,
FR-ENR-02/04/05).

Design decisions (see BE-06 task instructions for the full rationale):

- **Media bytes never touch this service** (NFR-PRF-03). This module only
  ever generates a presigned S3 PUT URL and later reads S3 object METADATA
  back via `head_object` — it never streams/reads/writes media bytes
  itself.
- **Tracking "expected" media between presign and complete**: a
  `MediaObject` row is created at presign time with `status=PENDING`,
  recording the client's *claimed* `content_type`/`size`/`sha256` for the
  S3 key it is about to upload to. `POST /enrollments/{id}/complete` reads
  each PENDING row for the session, does an S3 HEAD on its `s3_key`, and
  only on success overwrites `checksum`/`size`/`content_type` with the
  HEAD response and flips `status` to `FINALIZED`. A PENDING row with no
  matching S3 object (or a mismatched one) is exactly what `/complete`
  reports as a 422 validation failure — it never touches session state.
- **Checksum enforcement**: the presigned PUT URL is generated with an
  S3 `ChecksumSHA256` condition baked into the signature (via
  `generate_presigned_url("put_object", Params={..., "ChecksumSHA256": ...})`).
  When the uploading client sends the matching `x-amz-checksum-sha256`
  header, this is exactly what the contract asks S3 to itself reject on
  mismatch — SigV4 validation fails closed before S3 ever stores wrong
  bytes under the expected key. If the installed botocore version does not
  support this parameter on a presigned PUT (older versions), presign
  generation retries without it and logs a warning (see
  `generate_presigned_put_url`); the ALTERNATE MITIGATION in that case is
  the HEAD-based post-hoc verification `complete_enrollment` always
  performs regardless — checking that the actually-uploaded object's size
  and content-type match what was claimed at presign time, and comparing
  the S3-reported `ChecksumSHA256` (when S3 does return one, i.e. when the
  upload included the checksum header) against the claimed sha256. This
  cannot fully replace client-side checksum-enforced-by-S3 for a botocore
  version that lacks the parameter, but it still catches corrupted/
  substituted uploads that don't match the size/type the client itself
  declared.
"""

import base64
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from botocore.exceptions import ClientError

from app.core.config import Settings
from app.models.enrollment_session import EnrollmentSession
from app.models.enums import EnrollmentState, MediaKind, MediaObjectStatus, MediaVariant
from app.models.media_object import MediaObject
from app.repositories.audit_logs import AuditLogRepository
from app.repositories.enrollments import EnrollmentSessionRepository
from app.repositories.media_objects import MediaObjectRepository
from app.services import enrollment_service
from app.services import qc_queue as qc_queue_service

logger = logging.getLogger(__name__)

# --- Presigned URL TTL (TSD §6: "presigned URLs TTL ≤ 5 min") -------------

PRESIGN_TTL_SECONDS = 300

# --- Content-type allow-list + size bounds (FR-ENR-02/04/05) --------------
#
# Photo: a single frontal still. Even a high-resolution (e.g. 4000x3000)
# JPEG/PNG frame from a webcam/phone camera comfortably fits well under
# 15 MB; 15 MB is chosen as a generous ceiling that still rejects an
# obviously-wrong upload (e.g. a multi-frame file or an unrelated document)
# without needing to know the exact camera resolution in advance. 1 KB is
# the floor — anything smaller cannot be a real photo.
PHOTO_CONTENT_TYPES: dict[str, str] = {"image/jpeg": "jpg", "image/png": "png"}
PHOTO_MIN_SIZE_BYTES = 1 * 1024
PHOTO_MAX_SIZE_BYTES = 15 * 1024 * 1024

# Video: FR-ENR-02 targets a 10-20 s head-orientation clip, >=720p, >=24fps.
# A well-encoded VP8/VP9 WebM at 720p-1080p typically sits in the 1-8 Mbps
# range, i.e. roughly 1.25-20 MB for a 20 s clip. 250 MB is a deliberately
# generous ceiling (>10x that estimate) to tolerate higher-resolution
# cameras, less efficient encoder settings, or a slightly longer capture,
# while still rejecting a clearly-wrong upload (e.g. an unrelated large
# file). 50 KB is the floor — a real >=720p/>=24fps/10s clip cannot be
# smaller than that even at extreme compression.
VIDEO_CONTENT_TYPES: dict[str, str] = {"video/webm": "webm"}
VIDEO_MIN_SIZE_BYTES = 50 * 1024
VIDEO_MAX_SIZE_BYTES = 250 * 1024 * 1024


class SessionNotCapturingError(Exception):
    """Presign/complete were requested while the session is not CAPTURING."""

    def __init__(self, session_id: uuid.UUID, current_state: EnrollmentState) -> None:
        self.session_id = session_id
        self.current_state = current_state
        super().__init__(
            f"Enrollment session '{session_id}' is in state {current_state.value}, "
            "expected CAPTURING"
        )


class MediaValidationError(Exception):
    """`content_type`/`size` failed the per-`kind` allow-list/bounds check."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class MediaCompletionError(Exception):
    """One or more expected media objects are missing/mismatched in S3.

    `reasons` is a list of machine-readable dicts (`code`, `detail`, and
    `media_id` where applicable), returned verbatim in the 422 problem+json
    `extra` payload so the frontend can tell the operator exactly what to
    re-capture/re-upload.
    """

    def __init__(self, reasons: list[dict[str, Any]]) -> None:
        self.reasons = reasons
        super().__init__("Enrollment media completion validation failed")


@dataclass(frozen=True)
class PresignResult:
    media: MediaObject
    upload_url: str
    expires_at: datetime


def validate_media_request(kind: str, content_type: str, size: int) -> str:
    """Validate `content_type`/`size` against the per-`kind` allow-list.

    Returns the file extension to use for the S3 key. Raises
    `MediaValidationError` (-> 422 at the router) on any violation.
    """
    if kind == MediaKind.PHOTO.value:
        allowed = PHOTO_CONTENT_TYPES
        min_size, max_size = PHOTO_MIN_SIZE_BYTES, PHOTO_MAX_SIZE_BYTES
    else:
        allowed = VIDEO_CONTENT_TYPES
        min_size, max_size = VIDEO_MIN_SIZE_BYTES, VIDEO_MAX_SIZE_BYTES

    if content_type not in allowed:
        raise MediaValidationError(
            f"content_type '{content_type}' is not allowed for kind '{kind}'; "
            f"allowed: {sorted(allowed)}"
        )
    if not (min_size <= size <= max_size):
        raise MediaValidationError(
            f"size {size} bytes is out of bounds for kind '{kind}' "
            f"(expected {min_size}-{max_size} bytes)"
        )
    return allowed[content_type]


def _sha256_hex_to_b64(sha256_hex: str) -> str:
    return base64.b64encode(bytes.fromhex(sha256_hex)).decode("ascii")


def generate_presigned_put_url(
    s3_client: Any,
    *,
    bucket: str,
    key: str,
    content_type: str,
    sha256_hex: str,
    ttl_seconds: int = PRESIGN_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Generate a presigned S3 PUT URL, TTL-bounded and checksum-constrained.

    See module docstring for the checksum-enforcement design and its
    documented fallback when the installed botocore doesn't support
    `ChecksumSHA256` on a presigned PUT.
    """
    checksum_b64 = _sha256_hex_to_b64(sha256_hex)
    params = {
        "Bucket": bucket,
        "Key": key,
        "ContentType": content_type,
        "ChecksumSHA256": checksum_b64,
    }
    try:
        url = s3_client.generate_presigned_url("put_object", Params=params, ExpiresIn=ttl_seconds)
    except Exception:  # noqa: BLE001 - documented compatibility fallback, see module docstring
        logger.warning(
            "generate_presigned_url rejected ChecksumSHA256 param; falling back to a "
            "presigned URL without baked-in checksum enforcement (mitigated by the "
            "HEAD-based verification in complete_enrollment)",
            exc_info=True,
        )
        params.pop("ChecksumSHA256")
        url = s3_client.generate_presigned_url("put_object", Params=params, ExpiresIn=ttl_seconds)
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    return url, expires_at


def request_presign(
    enrollment_repo: EnrollmentSessionRepository,
    media_repo: MediaObjectRepository,
    audit_repo: AuditLogRepository,
    s3_client: Any,
    settings: Settings,
    *,
    session_id: uuid.UUID,
    kind: str,
    content_type: str,
    size: int,
    sha256: str,
    actor: str,
    variant: str | None = None,
) -> PresignResult:
    """Handle `POST /enrollments/{id}/media/presign` (FR-ENR-02/04, TSD §7).

    Only legal while the session is CAPTURING. For `kind="photo"`, each call
    issues the *next* `photo_{n}` key (n starting at 1) — FR-ENR-02 requires
    >=1 photo, and multiple presign calls are how the frontend uploads
    several stills. For `kind="video"`, the key is always
    `rotation.{ext}` (one head-orientation-sweep video per session per TSD
    §4); a still-PENDING video row from an earlier, not-yet-completed
    presign call is replaced rather than accumulated, since only the most
    recent attempt can still land at that exact S3 key.

    `variant` (EC-BE-02, TSD-edge-cases.md D-4.1) is optional — a caller
    that omits it (every pre-EC-BE-02 caller, and most current ones) gets
    `MediaVariant.DEFAULT` on the stored row. This keyword defaults to
    `None` precisely so existing callers of this function keep working
    unchanged.
    """
    session = enrollment_repo.get(session_id)
    if session is None:
        raise enrollment_service.EnrollmentNotFoundError(str(session_id))
    if session.state != EnrollmentState.CAPTURING:
        raise SessionNotCapturingError(session_id, session.state)

    ext = validate_media_request(kind, content_type, size)
    media_kind = MediaKind(kind)
    bucket = settings.aws_s3_bucket_name or ""
    prefix = settings.aws_s3_prefix or ""

    if media_kind is MediaKind.PHOTO:
        existing = media_repo.list_for_session(session_id, kind=MediaKind.PHOTO)
        n = len(existing) + 1
        s3_key = f"{prefix}enrollment/{session.user_id}/{session_id}/photo_{n}.{ext}"
    else:
        # One video per session (TSD §4 literal path `rotation.webm`): drop
        # any earlier PENDING video row for this session before recording
        # the new one, since a retry targets the same logical slot.
        for old in media_repo.list_for_session(session_id, kind=MediaKind.VIDEO):
            media_repo.delete(old)
        s3_key = f"{prefix}enrollment/{session.user_id}/{session_id}/rotation.{ext}"

    media = MediaObject(
        session_id=session_id,
        kind=media_kind,
        s3_bucket=bucket,
        s3_key=s3_key,
        checksum=sha256,
        size=size,
        content_type=content_type,
        status=MediaObjectStatus.PENDING,
        variant=MediaVariant(variant) if variant else MediaVariant.DEFAULT,
    )
    media = media_repo.create(media)

    upload_url, expires_at = generate_presigned_put_url(
        s3_client,
        bucket=bucket,
        key=s3_key,
        content_type=content_type,
        sha256_hex=sha256,
        ttl_seconds=PRESIGN_TTL_SECONDS,
    )

    audit_repo.record(
        actor=actor,
        action="enrollment.media_presigned",
        entity=f"enrollment_session:{session_id}",
        payload={"media_id": str(media.id), "kind": kind, "s3_key": s3_key},
    )

    return PresignResult(media=media, upload_url=upload_url, expires_at=expires_at)


def head_media_object(s3_client: Any, *, bucket: str, key: str) -> dict[str, Any] | None:
    """S3 HEAD the object; `None` if it does not exist. Re-raises any other
    `ClientError` (permissions, transient errors, etc.) — those are not
    "media missing", they're operational failures the 500 handler should see.
    """
    try:
        return s3_client.head_object(Bucket=bucket, Key=key, ChecksumMode="ENABLED")
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")
        http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if error_code in ("404", "NoSuchKey", "NotFound") or http_status == 404:
            return None
        raise


def complete_enrollment(
    enrollment_repo: EnrollmentSessionRepository,
    media_repo: MediaObjectRepository,
    audit_repo: AuditLogRepository,
    s3_client: Any,
    *,
    session_id: uuid.UUID,
    actor: str,
) -> EnrollmentSession:
    """Handle `POST /enrollments/{id}/complete` (FR-ENR-05, TSD §7).

    Validates, via S3 HEAD (never by trusting the client or the PENDING
    row's claimed metadata alone), that >=1 photo and exactly 1 video exist
    and match what was claimed at presign time. On success: finalizes the
    `MediaObject` rows (metadata overwritten from the HEAD response),
    performs CAPTURING -> CAPTURED -> QC_RUNNING (two state-machine
    transitions in one call, per BE-06 instructions), enqueues the QC job
    (`app/services/qc_queue.py` — BE-07 integration seam), and returns the
    session. On any failure, raises `MediaCompletionError` and the session
    state is left completely untouched (no partial transition, no partial
    finalization) — the router maps that to a 422 problem+json response
    listing every reason found.
    """
    session = enrollment_repo.get(session_id)
    if session is None:
        raise enrollment_service.EnrollmentNotFoundError(str(session_id))
    if session.state != EnrollmentState.CAPTURING:
        raise SessionNotCapturingError(session_id, session.state)

    # A PENDING row whose presigned PUT URL has already expired (TTL, see
    # PRESIGN_TTL_SECONDS) can never be fulfilled -- the client cannot
    # possibly still upload to it. Without this filter, any abandoned
    # presign call (a retried photo capture after a failed/slow upload,
    # a browser refresh mid-enrollment, etc.) would permanently block
    # /complete forever, since every PENDING row is otherwise required
    # (found live: a single retried photo presign broke completion).
    # Stale rows are simply excluded from the requirement here; sweeping
    # them from the table is a retention/cleanup concern (BE-14), not
    # this endpoint's job.
    now = datetime.now(UTC)
    pending_all = media_repo.list_for_session(session_id, status=MediaObjectStatus.PENDING)
    pending = [
        m for m in pending_all if now - m.created_at <= timedelta(seconds=PRESIGN_TTL_SECONDS)
    ]
    photos = [m for m in pending if m.kind == MediaKind.PHOTO]
    videos = [m for m in pending if m.kind == MediaKind.VIDEO]

    reasons: list[dict[str, Any]] = []
    if len(photos) < 1:
        reasons.append(
            {
                "code": "missing_photo",
                "detail": "At least 1 photo is required before completing enrollment (FR-ENR-02).",
            }
        )
    if len(videos) != 1:
        reasons.append(
            {
                "code": "video_count_mismatch",
                "detail": (
                    "Exactly 1 head-orientation video is required before completing "
                    f"enrollment (FR-ENR-02); found {len(videos)}."
                ),
            }
        )

    verified: list[tuple[MediaObject, dict[str, Any]]] = []
    if not reasons:
        for media in (*photos, *videos):
            head = head_media_object(s3_client, bucket=media.s3_bucket, key=media.s3_key)
            if head is None:
                reasons.append(
                    {
                        "code": "object_not_found",
                        "detail": (
                            f"Expected S3 object not found: s3://{media.s3_bucket}/{media.s3_key}"
                        ),
                        "media_id": str(media.id),
                    }
                )
                continue

            actual_size = head.get("ContentLength")
            if actual_size is None or int(actual_size) != int(media.size):
                reasons.append(
                    {
                        "code": "size_mismatch",
                        "detail": (
                            f"S3 object size ({actual_size}) does not match the size "
                            f"claimed at presign time ({media.size}) for "
                            f"s3://{media.s3_bucket}/{media.s3_key}."
                        ),
                        "media_id": str(media.id),
                    }
                )
                continue

            actual_content_type = head.get("ContentType")
            if actual_content_type is not None and actual_content_type != media.content_type:
                reasons.append(
                    {
                        "code": "content_type_mismatch",
                        "detail": (
                            f"S3 object content-type ({actual_content_type}) does not "
                            f"match the content-type claimed at presign time "
                            f"({media.content_type}) for s3://{media.s3_bucket}/{media.s3_key}."
                        ),
                        "media_id": str(media.id),
                    }
                )
                continue

            actual_checksum_b64 = head.get("ChecksumSHA256")
            if actual_checksum_b64 is not None and actual_checksum_b64 != _sha256_hex_to_b64(
                media.checksum
            ):
                reasons.append(
                    {
                        "code": "checksum_mismatch",
                        "detail": (
                            "S3-stored checksum does not match the sha256 claimed at "
                            f"presign time for s3://{media.s3_bucket}/{media.s3_key}."
                        ),
                        "media_id": str(media.id),
                    }
                )
                continue

            verified.append((media, head))

    if reasons:
        raise MediaCompletionError(reasons)

    for media, head in verified:
        media.size = int(head.get("ContentLength", media.size))
        media.content_type = head.get("ContentType") or media.content_type
        checksum_b64 = head.get("ChecksumSHA256")
        if checksum_b64 is not None:
            media.checksum = base64.b64decode(checksum_b64).hex()
        media.status = MediaObjectStatus.FINALIZED
        media_repo.update(media)

    enrollment_service.transition_session(
        enrollment_repo,
        audit_repo,
        session_id=session_id,
        target_state=EnrollmentState.CAPTURED,
        actor=actor,
        audit_action="enrollment.captured",
    )
    session = enrollment_service.transition_session(
        enrollment_repo,
        audit_repo,
        session_id=session_id,
        target_state=EnrollmentState.QC_RUNNING,
        actor=actor,
        audit_action="enrollment.qc_running",
    )

    audit_repo.record(
        actor=actor,
        action="enrollment.media_completed",
        entity=f"enrollment_session:{session_id}",
        payload={"photo_count": len(photos), "video_count": len(videos)},
    )

    qc_queue_service.enqueue_qc_job(session_id)

    return session
