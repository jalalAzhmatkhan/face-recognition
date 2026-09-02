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
    #: Dev/test ONLY. The endpoint a BROWSER must use to reach the same
    #: object store, when that differs from the one this process uses.
    #:
    #: With MinIO in docker-compose the two genuinely differ: the backend
    #: container reaches it at `http://minio:9000` (compose DNS), while the
    #: browser can only reach it at `http://localhost:9000`. A presigned URL
    #: is consumed by the BROWSER, so it has to be signed for the browser's
    #: hostname — and the host is part of the SigV4 signature, so rewriting
    #: it after signing invalidates the URL. Hence a second endpoint rather
    #: than a string replace.
    #:
    #: Unset in staging/prod, where both sides address real S3 identically.
    aws_s3_public_endpoint_url: str | None = None

    # --- Which object store to talk to ------------------------------------
    #
    # One switch instead of remembering to set (or unset) two endpoint URLs
    # consistently. Getting that pairing wrong does not fail loudly: the
    # presign call still returns 201 with a well-formed URL, and only the
    # browser's PUT fails.
    #
    #   "s3"    -> real AWS S3. boto3 resolves the endpoint from `aws_region`
    #              and uses virtual-hosted addressing. The default, so a
    #              deployment pointed at a real bucket cannot be hijacked by
    #              a dev-oriented default.
    #   "minio" -> the docker-compose MinIO, using the two endpoints below.
    #
    # `aws_s3_endpoint_url` / `aws_s3_public_endpoint_url` still override
    # either mode, for anything else S3-compatible.
    media_storage_backend: Literal["s3", "minio"] = "s3"
    #: How THIS process reaches MinIO (compose DNS name).
    minio_endpoint_url: str = "http://minio:9000"
    #: How the BROWSER reaches the same MinIO (published port on the host).
    #: Separate because SigV4 signs the Host header — see
    #: `aws_s3_public_endpoint_url`.
    minio_public_endpoint_url: str = "http://localhost:9000"

    @property
    def uses_minio(self) -> bool:
        return self.media_storage_backend == "minio"

    @property
    def resolved_s3_endpoint_url(self) -> str | None:
        """Endpoint for this process's own S3 calls. `None` means "let boto3
        resolve real AWS", which is what `"s3"` mode wants."""
        if self.aws_s3_endpoint_url:
            return self.aws_s3_endpoint_url
        return self.minio_endpoint_url if self.uses_minio else None

    @property
    def resolved_s3_public_endpoint_url(self) -> str | None:
        """Endpoint the BROWSER will use, i.e. the one presigned URLs are
        signed for. `None` means "same as above"."""
        if self.aws_s3_public_endpoint_url:
            return self.aws_s3_public_endpoint_url
        return self.minio_public_endpoint_url if self.uses_minio else None

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

    # Re-enrollment-due policy (EC-BE-05, TSD-edge-cases.md A-5). Two
    # independent criteria (either sets the flag) evaluated by a Celery Beat
    # job (see app/worker/celery_app.py / app/services/reenroll_due_service.py):
    #  - `reenroll_due_max_age_months`: enrollment age criterion — TSD A-5
    #    says "> 24 bulan" verbatim, kept configurable per-deployment.
    #  - `reenroll_due_score_window_days`: window over which the moving
    #    average of GENUINE `access_events.similarity` scores is computed.
    #    TSD A-5 says "dari log funnel D-1" without pinning an exact window;
    #    90 days is chosen (not 30) so the average isn't dominated by a
    #    short unlucky streak (e.g. a week of bad lighting) while still
    #    reacting within one quarter — same order of magnitude as
    #    `retention_event_frame_days` above.
    #  - `reenroll_due_score_margin`: the "+margin" in TSD A-5's "moving-
    #    average skor genuine < τ+margin" — how far ABOVE the matching
    #    threshold τ a user's average score must stay before they're
    #    considered drifting toward the threshold. 0.05 mirrors the
    #    `margin_threshold`-scale values already used for high-similarity
    #    gating (D-4.4) in this codebase's design docs.
    #  - `reenroll_due_min_events_for_score`: minimum GENUINE accept events
    #    in the window before the score criterion is evaluated at all — a
    #    single unlucky low-score accept must not flag a user; not specified
    #    by the TSD, chosen conservatively.
    #  - `reenroll_due_similarity_threshold_fallback`: last-resort τ when no
    #    `recognition_configs` GLOBAL/`normal`-mode override AND no caller-
    #    supplied artefact default exists (backend has no MLflow client and
    #    does not share ai-inference's env — see
    #    app/services/reenroll_due_service.py). Mirrors ai-inference's own
    #    `similarity_threshold` default (`ai-inference/src/ai_inference/
    #    config.py`, 0.35) purely as a same-ballpark placeholder, not a
    #    shared source of truth.
    #  - `reenroll_due_check_interval_seconds`: Celery Beat cadence. Daily by
    #    default — this is a slow-moving policy signal (age/rolling-average),
    #    not a hot path, so sub-daily scheduling would just waste DB cycles.
    reenroll_due_max_age_months: int = 24
    reenroll_due_score_window_days: int = 90
    reenroll_due_score_margin: float = 0.05
    reenroll_due_min_events_for_score: int = 5
    reenroll_due_similarity_threshold_fallback: float = 0.35
    reenroll_due_check_interval_seconds: int = 24 * 60 * 60  # daily

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
