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

    # --- EC-IN-02: quality gates (C-1 size, C-3 FIQA) + explicit voting
    # window (C-4) -- TSD-edge-cases.md D-3. ------------------------------
    # SHIP LOG-ONLY (task brief): every gate threshold below is ALWAYS
    # computed and logged (`ai_inference.pipeline.quality_gates`,
    # `condition_flags["skipped_quality_gate"]`, the
    # `inference_quality_gate_frames_total` metric) regardless of this
    # flag. Only reading `quality_gate_enforcing == True` lets a gate's
    # outcome actually change `run_recognition`'s candidates/decision --
    # default False means this task changes ZERO pipeline behavior out of
    # the box. TSD D-3 C-1's documented enforce criterion: flip this to
    # True only once the logged legitimate-frame skip rate has been under
    # 1-2% for 1-2 weeks per device_class (device_class-scoped aggregation
    # is a D-5 dependency not yet implemented -- until then, judge this
    # from the un-scoped `inference_quality_gate_frames_total` counter).
    quality_gate_enforcing: bool = False
    # C-1: shortest bbox side (px) below which a frame is unusable for
    # ANYTHING past detection (TSD D-3/REC 10.1's literal "deteksi >=64px").
    # Distinct from (stricter than) `condition_flags.LOW_RES_MIN_PX`
    # (80px), which stays the MATCHING-stage floor
    # (`ai_inference.pipeline.quality_gates.MIN_FACE_PX_MATCHING`).
    quality_gate_min_face_px_detection: float = 64.0
    # C-3: AdaFace feature-norm floor below which a frame is FIQA-gated out
    # of voting (skip, never a hard reject) -- see
    # `ai_inference.pipeline.quality_gates` module docstring: NOT YET
    # calibrated against real logged data, a placeholder like every other
    # threshold in this file.
    quality_gate_fiqa_min_feature_norm: float = 15.0

    # --- EC-IN-03: masked/sunglasses classifier (TSD-edge-cases.md C-2/
    # OQ-4) -- replaces EC-IN-01's placeholder landmark-intensity heuristic
    # in `condition_flags.masked`/`condition_flags.sunglasses` when a model
    # is configured and loads successfully; see
    # `ai_inference.pipeline.mask_sunglasses` module docstring for the
    # fail-safe (never-crash, fall back to the heuristic) contract. ------
    # Filesystem path to the exported ONNX model
    # (`ai_training.classifiers.mask_sunglasses.export_onnx`'s output).
    # Empty by default (no model shipped in this sandbox/repo yet) -- an
    # empty path is a normal, expected "not configured" state, not an
    # error: `load_classifier` logs a warning and this service falls back
    # to the EC-IN-01 heuristic for every frame, same as today.
    mask_sunglasses_model_path: str = ""
    # Crop size (px) the model was exported for -- MUST match the `img_size`
    # `export_onnx` was called with (TSD-edge-cases.md C-2's 64-96px range;
    # `ai_training.classifiers.mask_sunglasses.DEFAULT_IMG_SIZE` is 96).
    mask_sunglasses_img_size: int = 96
    # Sigmoid-probability cutoffs for the model's 2 independent multi-label
    # outputs (`ai_training.classifiers.mask_sunglasses.LABEL_NAMES`).
    # 0.5 is the standard uncalibrated midpoint -- NOT yet calibrated
    # against real validation data (same "tune later" status as
    # `similarity_threshold`/`liveness_threshold` above), pending a real
    # trained checkpoint + EC-TR-01's benchmark slice harness.
    mask_sunglasses_masked_threshold: float = 0.5
    mask_sunglasses_sunglasses_threshold: float = 0.5

    # --- EC-IN-04: dual-mode (normal/masked) decision threshold + 3-layer
    # resolution (TSD-edge-cases.md D-4.1/D-4.2, OQ-3/OQ-6) -----------------
    # Master feature flag: default False means `run_recognition`'s decision
    # path is BYTE-FOR-BYTE identical to pre-EC-IN-04 behavior -- a single
    # `similarity_threshold`/`margin_threshold`/`min_frames_for_grant` from
    # this Settings object (env), no masked-template gallery filter, no
    # `recognition_configs` DB read. Flip to True only once the masked/
    # normal FNIR@FPIR curves below have been validated against EC-TR-01's
    # benchmark harness (task acceptance criteria) -- same "ship OFF, prove
    # it, then enable" convention as `quality_gate_enforcing` above.
    dual_mode_threshold_enabled: bool = False
    # --- "masked" mode's per-field defaults (OQ-6 layer 1, ARTEFACT
    # DEFAULT). GAP, documented here rather than silently faked: there is no
    # MLflow-model-artefact-metadata reading mechanism anywhere in this
    # codebase yet (`ai_inference.model_switch.ProductionVersionCache` only
    # caches a `models.version` STRING, never artefact metadata/tags) -- the
    # TSD's OQ-6 decision ("default per-mode = metadata artefak model")
    # therefore cannot be implemented for real in this task without building
    # a whole new MLflow-client-reading subsystem, out of scope per the task
    # brief ("JANGAN bikin sistem baru besar2an di luar scope"). These env
    # vars stand in for that missing layer 1 for now -- same "tune later
    # against real data, not yet calibrated" status as every other threshold
    # in this file -- and are consumed as `artefact_defaults` by
    # `ai_inference.pipeline.recognize`'s 3-layer resolution, which still
    # applies `recognition_configs` (layer 2, DB override) and falls back to
    # `similarity_threshold` (layer 3, env) as documented at each field
    # below. A looser threshold than `similarity_threshold` is the expected
    # DIRECTION for masked mode (D-4/OQ-3: masked-vs-masked template
    # matching or the interim masked-vs-normal fallback both cope with
    # reduced usable facial area) -- 0.30 vs the normal-mode 0.35 default is
    # a placeholder gap of the same rough magnitude REC/NIST IR 8311
    # discussions use, NOT a calibrated value.
    similarity_threshold_masked: float = 0.30
    margin_threshold_masked: float = 0.0
    min_frames_for_grant_masked: int = 2

    # --- EC-IN-06: per-device_class `recognition_configs` resolution,
    # DECOUPLED from `dual_mode_threshold_enabled` (TSD-edge-cases.md D-5) --
    # A device_class-scoped operator override (BE-04's `recognition_configs`
    # table) should be adoptable on its own, WITHOUT also opting into the
    # masked/normal dual-mode experiment above (which is gated separately,
    # pending its own EC-TR-01 benchmark validation) -- the two features
    # ship independently and this flag governs only "read `recognition_
    # configs`/resolve `device_class` at all", never the masked-vs-normal
    # MODE choice itself (that stays exclusively `dual_mode_threshold_
    # enabled`'s job, see `ai_inference.pipeline.recognize`).
    #
    # Default False: `run_recognition`'s decision path is BYTE-FOR-BYTE
    # identical to before this flag existed -- no device_class lookup, no
    # `recognition_configs` DB read, same as `dual_mode_threshold_enabled=
    # False`'s existing "zero regression by default" contract. Once True (a
    # device WITHOUT a `device_class` set, or with a class but no matching
    # `recognition_configs` row) resolves to the exact same
    # `similarity_threshold`/`margin_threshold`/`min_frames_for_grant`
    # values as before -- only a device whose class HAS a configured
    # override sees a different effective threshold.
    device_class_config_resolution_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
