"""boto3 S3 client factory (BE-06, XC-03, TSD §4/§6).

Centralizes S3 client construction so every consumer (presigned-URL
generation, HEAD-based upload verification) builds the client the same way,
honoring the dev/test-only `AWS_S3_ENDPOINT_URL` escape hatch (MinIO, see
docker-compose.dev.yml) without ever touching real AWS when it is unset.
"""

from functools import lru_cache
from typing import Any

import boto3
from botocore.client import Config as BotoConfig

from app.core.config import Settings, get_settings


def build_s3_client(settings: Settings) -> Any:
    """Build a boto3 S3 client from `Settings`.

    - `aws_s3_endpoint_url` is `None` in staging/prod: boto3 uses its own
      endpoint resolution for `aws_region` (real AWS S3), matching the
      "app never provisions/assumes a specific endpoint" rule already
      documented on `Settings.aws_s3_bucket_name`.
    - When set (dev/test only, e.g. `http://localhost:9000` for MinIO),
      boto3 is pointed at that endpoint AND switched to path-style bucket
      addressing (`s3={"addressing_style": "path"}`) — MinIO does not
      support virtual-hosted-style addressing (`bucket.host.com/key`) the
      way AWS S3 does, only `host.com/bucket/key`.
    """
    boto_config = BotoConfig(
        signature_version="s3v4",
        s3=(
            {"addressing_style": "path"}
            if settings.aws_s3_endpoint_url is not None
            else {}
        ),
    )
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        endpoint_url=settings.aws_s3_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=(
            settings.aws_secret_access_key.get_secret_value()
            if settings.aws_secret_access_key is not None
            else None
        ),
        config=boto_config,
    )


@lru_cache
def get_s3_client() -> Any:
    """Process-wide cached client (mirrors `get_settings()`'s own caching).

    FastAPI routes depend on this via `Depends(get_s3_client)` and tests
    override it directly with a mock/fake — see
    `app/routers/enrollments.py` and `backend/tests/test_media_service.py`
    / `backend/tests/test_enrollments_media_router.py`. No real AWS/MinIO
    call is ever made from automated tests.
    """
    return build_s3_client(get_settings())
