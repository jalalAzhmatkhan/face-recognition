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
    # Dev/test-only escape hatch (BE-06): point boto3 at an S3-compatible
    # endpoint (e.g. MinIO from docker-compose.dev.yml, http://localhost:9000)
    # instead of real AWS. MUST stay unset in staging/prod so boto3 falls
    # back to AWS's own endpoint resolution for `aws_region`.
    aws_s3_endpoint_url: str | None = None

    # Staff AuthN/AuthZ (BE-03, NFR-SEC-04). Local email+password JWT auth
    # against `staff_accounts` — `oidc_sub` stays in the schema (nullable) as
    # prep for a future external-OIDC federation phase, but is NOT used here.
    # `jwt_secret_key` MUST be overridden per-environment via env/secret
    # manager; the value in `.env.example` is a placeholder only.
    jwt_secret_key: SecretStr = SecretStr("changeme-generate-a-real-secret")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # CORS (frontend runs on a different origin, e.g. http://localhost:5173
    # in dev). Deny-by-default (NFR-SEC-04): empty by default, so CORS
    # middleware is only added at all when this is explicitly configured —
    # never a permissive "*" fallback. Comma-separated list of exact origins.
    cors_allow_origins: str = ""

    # Device heartbeat staleness (BE-09, FR-USR-04). v1 simplification: there
    # is no Celery-beat/scheduled-task infra yet (app/worker/ only has
    # on-demand tasks — see app/worker/tasks.py) to auto-transition a
    # stale device's `status` row to OFFLINE, so `GET /devices` instead
    # computes an `is_stale` field per-response by comparing
    # `last_heartbeat_at` against this threshold "now". A real
    # auto-transition (heartbeat monitor job flipping ONLINE -> OFFLINE) is
    # a follow-up once scheduled-task infra exists.
    device_heartbeat_stale_after_seconds: int = 90

    # Policy cache (BE-10, TSD §2.2, FR-INF-05): TTL for the per-user Redis
    # snapshot (`policy_snapshot:{user_id}`) consumed on the recognition hot
    # path. Kept <= 30s per TSD so a stale policy/status change becomes
    # effective quickly even when no proactive refresh fires for some reason;
    # policy/user-status writes ALSO proactively refresh this cache (see
    # app/services/policy_cache.py) so the TTL is a worst-case bound, not the
    # typical propagation delay.
    policy_cache_ttl_seconds: int = 30

    # Retention automation (BE-14, ASM-10, NFR-SEC-03). Two independent
    # retention windows, both configurable via env so a deployment can
    # tighten/loosen them without a code change:
    #  - `retention_raw_media_days`: ASM-10's documented default (90 days)
    #    for "raw enrollment media" (kind PHOTO/VIDEO) counted from when the
    #    owning enrollment session finished enrolling (see
    #    app/services/retention_service.py for the exact anchor timestamp
    #    and why it's an approximation).
    #  - `retention_event_frame_days`: separate, shorter window for door-camera
    #    EVENT_FRAME media, which is conceptually independent of any
    #    enrollment session. No FSD/TSD value is specified for this one yet —
    #    30 days is a placeholder default, same spirit as the QC thresholds in
    #    ai-training/src/ai_training/config.py, and should be recalibrated
    #    once IN-06 (event emission, the actual producer of EVENT_FRAME rows)
    #    ships and privacy/ops give a real number.
    retention_raw_media_days: int = 90
    retention_event_frame_days: int = 30

    # Celery Beat schedule intervals (BE-14) — first use of Celery Beat in
    # this project (see app/worker/celery_app.py docstring for the
    # operational note on how to actually start the beat process).
    retention_backfill_interval_seconds: int = 60 * 60  # hourly
    retention_purge_interval_seconds: int = 6 * 60 * 60  # every 6 hours

    # Model promotion gate (BE-13, FR-TRN-05, NFR-PRF-01): a CANDIDATE model
    # may only be promoted to PRODUCTION if its measured p95 inference
    # latency (ai_training.evaluation.metrics.EvalReport.latency_ms_p95) is
    # at/under this budget, in milliseconds. Config-able per task
    # instructions, but 300ms is the NFR-PRF-01 default and should not be
    # loosened without a documented NFR change.
    promotion_latency_budget_ms: int = 300

    # Forgot-password email (BE-03 follow-up). Dev/test points at MailHog
    # (docker-compose.dev.yml's `mailhog` service: SMTP on 1025, web UI on
    # 8025) which accepts any message without real delivery — see README.
    # `frontend_base_url` is used to build the reset-password link embedded
    # in the email (`{frontend_base_url}/reset-password?token=...`); the
    # backend has no other way to know where the SPA is served from.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from_address: str = "noreply@frac.local"
    smtp_use_tls: bool = False
    frontend_base_url: str = "http://localhost:5173"
    password_reset_token_expire_minutes: int = 30

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
