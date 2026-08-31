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


@lru_cache
def get_settings() -> Settings:
    return Settings()
