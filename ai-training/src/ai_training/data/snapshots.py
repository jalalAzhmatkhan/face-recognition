"""Dataset snapshot builder (TR-04).

A snapshot is a versioned JSON manifest in S3 listing enrollment media keys
plus filters - never a copy of the media itself (TSD SS4:
`datasets/{snapshot_id}/manifest.json`, single private bucket).

Reproducibility ("`load_snapshot(id)` always returns the same manifest"):
`snapshot_id` is a fresh UUID minted once per `build_snapshot()` call, and
the manifest is written to S3 keyed by that id and never rewritten in
place - once `datasets/{snapshot_id}/manifest.json` exists it is treated as
immutable, so re-fetching it by id is deterministic regardless of what the
underlying DB rows look like later (a user re-enrolling, more media
arriving, etc. only affects a *new* snapshot id, not this one).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ai_training.config import Settings
from ai_training.db.connection import get_connection
from ai_training.db.dataset_repo import MediaRecord, find_enrolled_media
from ai_training.storage import build_s3_client


class MediaEntry(BaseModel):
    """One media object referenced by a snapshot - S3 reference only, never
    the bytes themselves (TSD SS4).

    `user_id`/`session_id` are optional since EC-TR-05: a `source=
    "event_frame"` entry (a door-camera frame, see
    `ai_training.db.dataset_repo` module docstring) has no enrollment
    session, and no identity at all when it was never matched."""

    s3_key: str
    kind: str
    user_id: str | None
    session_id: str | None
    source: str = "enrollment"


class DatasetSnapshot(BaseModel):
    snapshot_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    filters: dict[str, str] = Field(default_factory=dict)
    # Flat S3-key list (the field FR-TRN-01/TR-04 asks for verbatim).
    media_keys: list[str] = Field(default_factory=list)
    # Richer per-item metadata, e.g. so TR-05's EDA can filter to `kind ==
    # "video"` without guessing from the file extension.
    media: list[MediaEntry] = Field(default_factory=list)
    media_bucket: str = ""
    user_ids: list[str] = Field(default_factory=list)
    session_ids: list[str] = Field(default_factory=list)
    total_media_count: int = 0


def _manifest_key(snapshot_id: str) -> str:
    return f"datasets/{snapshot_id}/manifest.json"


def _dedupe_preserve_order(values: list[str | None]) -> list[str]:
    # `None` (an unmatched EC-TR-05 event-frame probe's user_id/session_id)
    # is deliberately dropped here, not deduped-and-kept-as-one-entry: it
    # doesn't refer to one real user/session, so it must never appear in
    # `user_ids`/`session_ids` at all.
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value is not None and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _build_manifest(
    filters: dict[str, str], records: list[MediaRecord], default_bucket: str
) -> DatasetSnapshot:
    # TSD SS4 documents a single private bucket; if that ever stops being
    # true this still doesn't lose data (each MediaEntry keeps its own key),
    # it just means `media_bucket` is a best-effort single value rather than
    # a per-record fact.
    bucket = records[0].s3_bucket if records else default_bucket
    return DatasetSnapshot(
        snapshot_id=str(uuid.uuid4()),
        filters=filters,
        media_keys=[record.s3_key for record in records],
        media=[
            MediaEntry(
                s3_key=record.s3_key,
                kind=record.kind,
                user_id=record.user_id,
                session_id=record.session_id,
                source=record.source,
            )
            for record in records
        ],
        media_bucket=bucket,
        user_ids=_dedupe_preserve_order([record.user_id for record in records]),
        session_ids=_dedupe_preserve_order([record.session_id for record in records]),
        total_media_count=len(records),
    )


def build_snapshot(
    settings: Settings,
    filters: dict[str, str] | None = None,
    *,
    s3_client: Any = None,
) -> DatasetSnapshot:
    """Build and upload a dataset snapshot manifest to S3.

    1. Queries `media_objects` FINALIZED under `enrollment_sessions`
       ENROLLED (see `ai_training.db.dataset_repo.find_enrolled_media` for
       supported `filters` keys).
    2. Mints a fresh `snapshot_id` (UUID4).
    3. Uploads the manifest to `datasets/{snapshot_id}/manifest.json` in
       `settings.s3.bucket` (never local disk - TSD SS4 / repo rule #1).

    `s3_client` is an injection point for tests (mirrors `downloader` in
    `ai_training.worker.tasks`); production callers leave it `None` and get
    a real `boto3` client built via `ai_training.storage.build_s3_client`.
    """
    filters = filters or {}
    conn = get_connection(settings.db.dsn)
    try:
        with conn.cursor() as cursor:
            records = find_enrolled_media(cursor, filters)
    finally:
        conn.close()

    manifest = _build_manifest(filters, records, settings.s3.bucket)

    client = s3_client if s3_client is not None else build_s3_client(settings)
    client.put_object(
        Bucket=settings.s3.bucket,
        Key=_manifest_key(manifest.snapshot_id),
        Body=manifest.model_dump_json(indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return manifest


def load_snapshot(
    settings: Settings, snapshot_id: str, *, s3_client: Any = None
) -> DatasetSnapshot:
    """Read back the manifest previously written by `build_snapshot()`.

    Deterministic by id (see module docstring): always returns the exact
    JSON that was uploaded for this `snapshot_id`.
    """
    client = s3_client if s3_client is not None else build_s3_client(settings)
    response = client.get_object(Bucket=settings.s3.bucket, Key=_manifest_key(snapshot_id))
    body = response["Body"].read()
    return DatasetSnapshot.model_validate_json(body)
