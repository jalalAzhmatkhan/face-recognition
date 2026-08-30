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
    """Postgres access with the restricted ai-training role(s).

    TSD §4/§6 and backend/README.md describe TWO distinct Postgres roles for
    ai-training: `ai_training_ro` (SELECT-only on business tables, no access
    to `face_embeddings`/`audit_logs`) and `ai_training_embeddings_write`
    (SELECT/INSERT/UPDATE on `face_embeddings` ONLY).

    KNOWN GAP (documented, not silently worked around — see TR-02/TR-03
    implementation notes in ai_training/worker/tasks.py): the enrollment QC
    + embedding worker also needs to UPDATE
    `enrollment_sessions.state`/`qc_report` and INSERT into `audit_logs`,
    which neither existing role grants. A single `dsn` field is kept here
    (rather than inventing a `dsn_ro`/`dsn_embeddings_write` split that
    would still be incomplete) so the worker is fully wired end-to-end
    today; the operator must point `TRN_DB__DSN` at a role with the
    additional grants (or widen `ai_training_embeddings_write` in a future
    backend migration — out of scope for this task, no migrations were run
    here) before running this against a real database.
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


class QCSettings(BaseModel):
    """Enrollment quality-check thresholds (TR-02, FR-ENR-06).

    Defaults are placeholders pending calibration against real pilot
    enrollment recordings (same "tune later against real data" status as
    `TrainingSettings.target_recall`/`max_far` above) — they are chosen to
    be plausible for a webcam-quality capture, not derived from a dataset.

    Pose ranges implement the ASM-03 correction (2026-08-30, FSD-AI.md): the
    enrollment motion is head yaw/pitch only, body+camera fixed, no
    back-of-head segment. `yaw_range_deg`/`pitch_range_deg` are the
    amplitude of the (yaw, pitch) sweep mapped onto the 12 clock positions
    (see `ai_training.quality.pose`) — kept within the corrected "realistic
    head turn" envelope (~30-45 deg yaw, ~20-30 deg pitch) rather than the
    old (incorrect) full-profile 90 deg assumption.
    """

    sample_fps: float = 6.0
    blur_variance_min: float = 80.0
    brightness_min: float = 40.0
    brightness_max: float = 215.0
    face_ratio_min: float = 0.12
    pose_tolerance_deg: float = 15.0
    yaw_range_deg: float = 35.0
    pitch_range_deg: float = 25.0
    # Fraction of the 12 clock positions that must have >=1 passing frame
    # for the session to be QC PASS. Not 100%: ASM-03 says every position
    # should in principle show a valid face, but a small allowance covers
    # camera/lighting variance without a hard all-12-or-nothing gate. Tune
    # once real capture data exists.
    min_pass_ratio: float = 0.75
    # Path to the official MediaPipe Face Landmarker `.task` model bundle
    # (Apache-2.0, published by Google at
    # https://storage.googleapis.com/mediapipe-models/face_landmarker/...)
    # -- unrelated to the SCRFD/AdaFace/MiniFASNet licensing question
    # (documentation/research/recommendations.md): this is a generic
    # landmark detector, not a proprietary face-recognition embedding
    # model, and Google explicitly distributes it for free reuse. Default
    # assumes the repo-relative `ai-training/models/face_landmarker.task`
    # this project bundles (self-hosted, no runtime download -- same
    # pattern as FE-04's self-hosted face-api weights).
    face_landmarker_model_path: str = ""


class EmbedderSettings(BaseModel):
    """Selects the embedding backend (TR-03/TR-06).

    `backend="stub"` remains the DEFAULT on purpose (unchanged by TR-06):
    `AdaFaceEmbedder` needs a real ~250MB pretrained checkpoint on disk
    (see `adaface_weights_path` below), which test/CI environments do not
    have and should not need in order to run. Real matching requires an
    operator to explicitly opt in via `TRN_EMBEDDER__BACKEND=adaface` in
    an environment that has run the download step.

    `adaface_arch`/`adaface_weights_path` configure `AdaFaceEmbedder`
    (`ai_training.embedding.embedder`). Per
    `documentation/research/recommendations.md` §2 ("AdaFace IR-101
    (WebFace12M) untuk akurasi maksimal"), the project's chosen weights are
    IR-101 trained on WebFace12M — hence `adaface_arch` defaults to
    `"ir_101"` (upstream naming; architecturally `num_layers=100`, see
    `ai_training.embedding.adaface_net`). `adaface_weights_path=""` (the
    default) resolves to the repo-bundled-by-convention (but NOT
    git-committed — `*.ckpt` is gitignored, files are large and not owned
    by this repo) path `ai-training/models/adaface_ir101_webface12m.ckpt`,
    fetched on demand with `uv run ai-training download-adaface-weights`
    (see `ai_training.download_adaface_weights` for the exact Google Drive
    source and checksum-free-but-size-sanity-checked download mechanics).
    """

    backend: str = "stub"
    stub_version: str = "stub-v1"
    adaface_arch: str = "ir_101"
    adaface_weights_path: str = ""


class EvaluationSettings(BaseModel):
    """Open-set 1:N identification benchmark knobs (TR-07).

    `fpir_budget` is the security budget from
    `documentation/research/recommendations.md` SS5 ("Threshold Tuning"):
    the operating threshold is the SMALLEST tau that keeps FPIR (impostor
    probes wrongly accepted under any identity) at or below this fraction
    - see `ai_training.evaluation.scoring.find_threshold_for_fpir_budget`.
    Default 0.01 (<=1%) is a placeholder pending calibration against a real
    frozen benchmark, same "tune later against real data" status as
    `TrainingSettings.target_recall`/`max_far` above.

    `gallery_media_per_identity` controls the TR-07 gallery/probe split
    applied on top of a TR-04 dataset snapshot (see
    `ai_training.evaluation.metrics` module docstring for the full split
    rule): for an identity with >=2 media in the snapshot, this many of its
    media (capped at len(media) - 1, so at least one always remains a
    genuine probe) become gallery templates; the rest are genuine probes.
    An identity with exactly 1 media becomes an impostor probe instead
    (held out of the gallery entirely).
    """

    fpir_budget: float = 0.01
    gallery_media_per_identity: int = 1


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRN_", env_nested_delimiter="__", env_file=".env", extra="ignore"
    )

    s3: S3Settings = S3Settings()
    mlflow: MLflowSettings = MLflowSettings()
    db: DBSettings = DBSettings()
    training: TrainingSettings = TrainingSettings()
    qc: QCSettings = QCSettings()
    embedder: EmbedderSettings = EmbedderSettings()
    evaluation: EvaluationSettings = EvaluationSettings()
    # Celery broker/result-backend (TR-02/TR-03 worker). Deliberately a
    # plain top-level field (mirrors backend's `Settings.redis_url`, see
    # backend/app/worker/celery_app.py) rather than nested under a `redis`
    # block, so the analogy to backend's config is obvious at a glance.
    # MUST be pointed at the SAME Redis instance as backend's `REDIS_URL`
    # for `run_enrollment_qc.delay(...)` dispatches to reach this worker —
    # there is no automatic sharing between the two separate projects/env
    # namespaces (`TRN_REDIS_URL` here vs `REDIS_URL` in backend/).
    redis_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
