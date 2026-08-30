"""Dataset snapshot builder stub (TR-04).

A snapshot is a versioned JSON manifest in S3 listing enrollment media keys
plus filters - never a copy of the media itself (TSD SS4).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from ai_training.config import Settings


class DatasetSnapshot(BaseModel):
    snapshot_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    filters: dict[str, str] = Field(default_factory=dict)
    media_keys: list[str] = Field(default_factory=list)


def build_snapshot(settings: Settings, filters: dict[str, str] | None = None) -> DatasetSnapshot:
    """Build and upload a dataset snapshot manifest to S3.

    Implemented in TR-04: list enrollment objects (lazy ``boto3``), apply
    filters, write ``datasets/{snapshot_id}/manifest.json``.
    """
    raise NotImplementedError("Dataset snapshot building lands with TR-04.")
