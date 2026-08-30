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
    # SCRFD detector, AdaFace embedder, MiniFASNet liveness).
    detector_model_name: str = "scrfd-detector"
    embedder_model_name: str = "adaface-embedder"
    liveness_model_name: str = "minifasnet-liveness"
    # "production" alias by default; pin an explicit version to override.
    model_stage_or_version: str = "production"

    # Loader backend: "stub" (no downloads, for dev/CI) or "mlflow".
    model_loader: str = "stub"

    # Decision parameters (tuned later on validation curves - TSD SS5)
    similarity_threshold: float = 0.35
    device: str = "cpu"  # "cpu" | "cuda"


@lru_cache
def get_settings() -> Settings:
    return Settings()
