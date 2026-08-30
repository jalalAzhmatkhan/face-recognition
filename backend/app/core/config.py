"""Application settings — env-based via pydantic-settings (NFR-OPS-03: no secrets in repo)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration comes from environment variables (or a local .env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "frac-backend"
    app_env: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # Placeholders for later tasks (XC-02, BE-02, XC-03). Values are injected via env;
    # never commit real credentials.
    database_url: str | None = None
    redis_url: str | None = None
    s3_bucket: str | None = None
    aws_region: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
