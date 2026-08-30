"""Application settings — env-based via pydantic-settings (NFR-OPS-03: no secrets in repo)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration comes from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "frac-backend"
    app_env: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Placeholders for later tasks (XC-02, BE-02). Values are injected via env;
    # never commit real credentials.
    database_url: str | None = None
    redis_url: str | None = None

    # AWS S3 (media bucket, XC-03). The bucket itself is provisioned MANUALLY
    # by a human (see infra/terraform/README.md) — this app only ever reads
    # these env vars, it never provisions or assumes bucket existence at
    # import time. `aws_secret_access_key` is a SecretStr so it never ends up
    # in logs/repr (consistent with the no-secrets-in-logs intent of
    # core/logging.py and core/problem.py not echoing internals to clients).
    aws_region: str | None = None
    aws_s3_bucket_name: str | None = None
    aws_s3_prefix: str = ""
    aws_access_key_id: str | None = None
    aws_secret_access_key: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
