"""Pipeline configuration via environment variables (pydantic-settings).

Everything is env-driven with prefix ``TRN_`` and nested delimiter ``__``,
e.g. ``TRN_S3__BUCKET=frac-media``, ``TRN_MLFLOW__TRACKING_URI=...``,
``TRN_DB__DSN=postgresql://...``. No credentials live in code or defaults:
AWS auth comes from the standard credential chain (env/instance role), DB
DSN and MLflow URI are injected by the environment.
"""

from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class S3Settings(BaseModel):
    """S3 access (media + dataset manifests + MLflow artifacts). TSD SS4.

    The bucket is provisioned MANUALLY by a human (see
    infra/terraform/README.md) — this service only reads config, it never
    provisions anything. `bucket`/`region` here are the ai-training-side
    equivalent of the root/backend `AWS_S3_BUCKET_NAME`/`AWS_REGION` env
    vars, just TRN_-namespaced (`TRN_S3__BUCKET`, `TRN_S3__REGION`).
    Credentials are NOT duplicated here on purpose: boto3 picks up
    `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` from the standard credential
    chain (plain env vars, no `TRN_` prefix) rather than pydantic-settings,
    so secrets never round-trip through this Settings object/logs.
    """

    bucket: str = "frac-media"
    region: str = "ap-southeast-1"
    endpoint_url: str = ""  # override for localstack/minio in dev
    dataset_prefix: str = "datasets/"
    enrollment_prefix: str = "enrollment/"


class MLflowSettings(BaseModel):
    """Experiment tracking + model registry (TR-06)."""

    tracking_uri: str = ""
    experiment_name: str = "face-recognition"
    registry_embedder_name: str = "adaface-embedder"
    registry_detector_name: str = "scrfd-detector"
    registry_liveness_name: str = "minifasnet-liveness"


class DBSettings(BaseModel):
    """Postgres access with the restricted ai-training role.

    Read-only on business tables + write on ``face_embeddings`` (TSD SS4).
    DSN is injected via ``TRN_DB__DSN`` - never committed.
    """

    dsn: str = ""
    embedding_dim: int = 512


class TrainingSettings(BaseModel):
    """Core training/eval knobs (defaults are placeholders until TR-06)."""

    device: str = "cuda"  # "cuda" | "cpu"
    batch_size: int = 128
    seed: int = 42
    # Metric priority is fixed by project rule: Recall -> F1 -> Precision.
    target_recall: float = 0.98
    max_far: float = 0.001


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRN_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    s3: S3Settings = S3Settings()
    mlflow: MLflowSettings = MLflowSettings()
    db: DBSettings = DBSettings()
    training: TrainingSettings = TrainingSettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
