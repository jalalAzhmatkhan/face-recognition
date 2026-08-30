"""Shared `boto3` S3 client construction (TR-04/TR-05).

Factored out of `ai_training.worker.tasks._default_download_video` so
`ai_training.data.snapshots` and `ai_training.eda.report` don't each
re-invent it. Threads `settings.s3.region`/`endpoint_url` through
explicitly rather than a bare `boto3.client("s3")` - see that function's
docstring for the MinIO/S3-compatible-endpoint bug this avoids repeating.
`boto3` itself stays a lazy import (part of the `ml` extra) so this module
is importable without it installed.
"""

from __future__ import annotations

from typing import Any

from ai_training.config import Settings


def build_s3_client(settings: Settings) -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "S3 access requires the 'ml' extra (uv sync --extra ml): boto3."
        ) from exc
    return boto3.client(
        "s3",
        region_name=settings.s3.region or None,
        endpoint_url=settings.s3.endpoint_url or None,
    )
