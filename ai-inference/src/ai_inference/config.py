"""Service configuration via environment variables (pydantic-settings).

No credentials are hardcoded anywhere; everything is env-driven
(prefix ``INF_``), e.g. ``INF_MLFLOW_TRACKING_URI=http://mlflow:5000``.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the inference service."""

    model_config = SettingsConfigDict(env_prefix="INF_", env_file=".env", extra="ignore")

    # Service
    service_name: str = "ai-inference"
    host: str = "0.0.0.0"
    port: int = 8100

    # MLflow model registry (TSD SS1.2: INF loads models from MLflow)
    mlflow_tracking_uri: str = ""
    # Registered model names in the MLflow registry (per ratified recommendation:
    # MediaPipe Face Landmarker detector (substituted for SCRFD -- see
    # IN-03/TR-02 licensing note below), AdaFace embedder, MiniFASNet liveness).
    detector_model_name: str = "mediapipe-face-landmarker"
    embedder_model_name: str = "adaface-embedder"
    liveness_model_name: str = "minifasnet-liveness"
    # "production" alias by default; pin an explicit version to override.
    model_stage_or_version: str = "production"

    # Loader backend: "stub" (no downloads, for dev/CI), or "mlflow"/"adaface"
    # (both select AdaFaceModelLoader -- see models/loader.py module docstring
    # for why "mlflow" is kept only as a backward-compatible alias, not because
    # anything is actually loaded from an MLflow registry).
    model_loader: str = "stub"

    # Decision parameters (tuned later on validation curves - TSD SS5)
    similarity_threshold: float = 0.35
    device: str = "cpu"  # "cpu" | "cuda"

    # --- IN-03: /recognize pipeline ---------------------------------------
    # Postgres DSN using the read-only `ai_inference_ro` role (backend
    # migration b7c4e1a2d9f0): SELECT-only on `models` (find the PRODUCTION
    # version) and `face_embeddings` (ANN gallery search). No other table
    # access -- see backend/README.md "DB role: ai_inference_ro".
    db_dsn: str = ""
    # LIMIT for the pgvector top-k ANN query in ai_inference.gallery.search_top_k,
    # before per-user max-fusion collapse (recommendations.md SS4). A user can
    # have ~13 templates (multiple pose buckets), so this must comfortably
    # exceed (num_candidate_users * templates_per_user) to avoid truncating a
    # real match's best template out of the result set.
    ann_top_k: int = 50
    # Top1 - top2 (different users) margin required, IN ADDITION to
    # top1 >= similarity_threshold, to GRANT. 0.0 = margin not enforced yet
    # (recommendations.md SS5: tighten this during threshold calibration).
    margin_threshold: float = 0.0
    # Multi-frame temporal voting (recommendations.md SS5): a user must be the
    # per-frame winner in at least this many submitted frames for the final
    # decision to be GRANTED for that user.
    min_frames_for_grant: int = 2

    # --- IN-04: passive liveness / anti-spoofing (PAD) --------------------
    # Per-frame liveness score (from `ai_training.liveness.detector`, real
    # backend selected via TRN_LIVENESS__BACKEND=minifasnet on the
    # ai-training side, see training_bridge.build_training_settings) below
    # which a frame is flagged spoof-suspect. Same "tune later against real
    # data" status as `similarity_threshold` above -- NOT YET calibrated
    # against real print/replay attack data (recommendations.md §8 point 2:
    # FAS carries a real domain gap, calibration against this deployment's
    # own capture hardware/lighting is required before production, not
    # optional). 0.5 is a placeholder midpoint, not a validated operating
    # point.
    liveness_threshold: float = 0.5

    # --- IN-06: access-event emission (TSD SS1.3, FR-INF-04) --------------
    # Base URL of the `backend/` Core API this service reports decisions to,
    # e.g. "http://localhost:8000". Empty (the default) means event emission
    # is a no-op -- see `ai_inference.events.emit_access_event_background`
    # docstring for why that's a silent skip rather than a buffered failure.
    backend_base_url: str = ""
    # Path of BE-10's ingest endpoint, mounted under the backend's own
    # `API_V1_PREFIX` (default `/api/v1`, see backend/.env.example) -- kept
    # configurable here rather than hardcoded in case that prefix changes.
    backend_access_events_path: str = "/api/v1/access-events"
    # Short timeout so a slow/unresponsive backend can never meaningfully
    # delay the retry loop or (transitively) the next `/recognize` request --
    # this call already runs off the hot path via BackgroundTasks, but an
    # unbounded timeout would still let a stuck backend pile up in-flight
    # background tasks indefinitely.
    access_event_timeout_seconds: float = 2.0
    # Bound on the in-memory fallback buffer (TSD SS1.3: "local fallback
    # buffer in memory"). Once full, the OLDEST buffered event is evicted to
    # make room for the newest -- see `ai_inference.events` module docstring
    # for why this is a deliberate, observable trade-off (not silent data
    # loss) rather than an attempt at a durable/unbounded outbox.
    access_event_buffer_max_size: int = 1000
    # How often the background retry loop (`ai_inference.events.run_flush_loop`,
    # started from the app lifespan) attempts to drain the fallback buffer.
    access_event_retry_interval_seconds: float = 5.0

    # --- IN-07: atomic model+gallery switch (TSD, FR-TRN-06) --------------
    # TTL for `ai_inference.model_switch.ProductionVersionCache`, bounding
    # how long a promotion in backend can take to be NOTICED by this
    # process (see that module's docstring for why "noticed" -- not
    # "reloaded" -- is the correct word: there is no weight hot-swap here,
    # only a fail-secure guard once the mismatch is detected). Mirrors
    # backend's own cached-policy-snapshot TTL (<=30s) for the same
    # "bounded staleness beats a DB round trip per request" trade-off.
    production_version_cache_ttl_seconds: float = 5.0

    # --- IN-08: drift & model monitoring (FR-MON-04) ----------------------
    # There is no Alertmanager/Grafana deployed anywhere in this monorepo
    # (see ai_inference.monitoring module docstring) -- these thresholds
    # drive in-process Gauges that ARE the alert surface. NOT calibrated
    # against real production traffic (same "tune later" status as
    # `similarity_threshold`/`liveness_threshold` above).
    #
    # Number of recent /recognize outcomes kept per rolling-window detector
    # (unknown-rate, latency SLO) and the size of BOTH the frozen baseline
    # window and the rolling window for score-distribution drift.
    monitoring_window_size: int = 100
    # Minimum samples in a rolling window before evaluating it at all --
    # avoids a noisy/meaningless rate or percentile off a near-empty window
    # right after process startup.
    monitoring_min_samples: int = 20
    # Population Stability Index threshold for score-distribution drift.
    # >0.2 is the standard industry "significant shift" cutoff (0.1-0.2 is
    # "moderate", <0.1 is "no significant change") -- see
    # `ai_inference.monitoring`'s PSI implementation.
    score_drift_psi_threshold: float = 0.2
    # Fraction of UNKNOWN decisions in the rolling window above which an
    # unknown-rate spike is flagged. 0.5 is a conservative placeholder
    # (more than half of recent attempts failing to match anyone is
    # unambiguously worth an operator's attention) pending real-traffic
    # calibration.
    unknown_rate_alert_threshold: float = 0.5
    # p95 decision latency (ms) above which a latency SLO breach is
    # flagged -- matches NFR-PRF-01's 300ms budget (IN-05).
    latency_slo_p95_ms: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
