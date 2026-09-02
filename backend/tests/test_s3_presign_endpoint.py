"""The presign client addresses the object store at the endpoint the BROWSER
can reach, which is not always the one this process uses.

Under docker-compose the backend resolves MinIO as `minio:9000` while the
browser only sees `localhost:9000`. A presigned URL is consumed by the
browser, and SigV4 signs the Host header — so the URL has to be signed for
the browser's hostname, and cannot be rewritten afterwards. Getting this
wrong is invisible server-side: presign returns 201 with a perfectly
well-formed URL that the browser then cannot use, surfacing only as
"Failed to fetch".
"""

from __future__ import annotations

from app.core.aws import build_s3_client
from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "aws_region": "ap-southeast-1",
        "aws_s3_bucket_name": "frac-media",
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test-secret",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


def test_presign_client_uses_the_public_endpoint_when_set() -> None:
    settings = _settings(
        aws_s3_endpoint_url="http://minio:9000",
        aws_s3_public_endpoint_url="http://localhost:9000",
    )

    assert "localhost:9000" in build_s3_client(settings, for_presign=True).meta.endpoint_url
    # ...while ordinary server-side calls keep using the compose-internal
    # name, which is the only one THIS process can resolve.
    assert "minio:9000" in build_s3_client(settings).meta.endpoint_url


def test_a_presigned_url_is_signed_for_the_browser_host() -> None:
    settings = _settings(
        aws_s3_endpoint_url="http://minio:9000",
        aws_s3_public_endpoint_url="http://localhost:9000",
    )
    client = build_s3_client(settings, for_presign=True)

    url = client.generate_presigned_url(
        "put_object", Params={"Bucket": "frac-media", "Key": "a/b.jpg"}, ExpiresIn=300
    )

    assert url.startswith("http://localhost:9000/")
    # Signed, not merely pointed: a host swap after signing would produce a
    # URL S3 rejects, which is why this is a separate client.
    assert "X-Amz-Signature=" in url


def test_both_clients_match_when_no_public_endpoint_is_configured() -> None:
    # Real AWS S3: one endpoint for everyone, so the split must be a no-op.
    settings = _settings(aws_s3_endpoint_url="http://minio:9000")

    assert (
        build_s3_client(settings, for_presign=True).meta.endpoint_url
        == build_s3_client(settings).meta.endpoint_url
    )


def test_staging_and_prod_still_resolve_real_aws() -> None:
    settings = _settings()

    for client in (build_s3_client(settings), build_s3_client(settings, for_presign=True)):
        assert "amazonaws.com" in client.meta.endpoint_url


def test_a_custom_endpoint_forces_path_style_addressing() -> None:
    # MinIO cannot do virtual-hosted-style (`bucket.host/key`). The presign
    # client has to make that choice off its OWN endpoint, not the internal
    # one, or it would sign a URL MinIO refuses to route.
    settings = _settings(
        aws_s3_endpoint_url="http://minio:9000",
        aws_s3_public_endpoint_url="http://localhost:9000",
    )
    client = build_s3_client(settings, for_presign=True)

    url = client.generate_presigned_url(
        "put_object", Params={"Bucket": "frac-media", "Key": "a/b.jpg"}, ExpiresIn=300
    )

    assert url.startswith("http://localhost:9000/frac-media/a/b.jpg")
