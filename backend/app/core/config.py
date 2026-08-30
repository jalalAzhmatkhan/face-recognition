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

    # Staff AuthN/AuthZ (BE-03, NFR-SEC-04). Local email+password JWT auth
    # against `staff_accounts` — `oidc_sub` stays in the schema (nullable) as
    # prep for a future external-OIDC federation phase, but is NOT used here.
    # `jwt_secret_key` MUST be overridden per-environment via env/secret
    # manager; the value in `.env.example` is a placeholder only.
    jwt_secret_key: SecretStr = SecretStr("changeme-generate-a-real-secret")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 60 * 24 * 7  # 7 days


@lru_cache
def get_settings() -> Settings:
    return Settings()
