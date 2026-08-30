"""Evaluation harness: Recall -> F1 -> Precision + latency_ms - TR-07.

Frozen benchmark (held-out identities + impostor set, versioned in S3).
Report order is fixed by project rule: Recall (primary) -> F1 -> Precision,
plus inference latency in ms. Gate: Recall >= 0.98 @ FAR <= 0.1% (ASM-07).

This module is split into three layers (see the TR-07 task brief):

1. Pure scoring math - `ai_training.evaluation.scoring` (no S3/DB/torch).
2. Latency timing - `ai_training.evaluation.latency` (no S3/DB/torch;
   works against `StubEmbedder` too).
3. Orchestration - `evaluate_candidate` below. THIS is the only place in
   the evaluation package that touches S3/Postgres/torch/MLflow, and it
   does so via lazy imports inside the function body (module-level imports
   here stay light on purpose, mirroring `align_face`/`quality.pipeline`:
   "not covered by automated tests, verify live").

Benchmark/gallery-probe split rule (`_split_gallery_and_probes`):
`benchmark_id` IS a TR-04 dataset snapshot id - `evaluate_candidate` calls
`ai_training.data.snapshots.load_snapshot` to read that manifest, then
applies a NEW split on top of it (TR-04 knows nothing about
gallery/probe): group `snapshot.media` by `user_id`, then for each
identity:

- >= 2 media: the first `settings.evaluation.gallery_media_per_identity`
  entries (capped at `len(media) - 1`, so at least one media always stays
  a probe) become gallery templates; the remainder become GENUINE probes
  (`true_identity == user_id`).
- exactly 1 media: that identity is held out entirely - its one media
  becomes an IMPOSTOR probe (`true_identity is None`), never enters the
  gallery, and is expected to end up UNKNOWN.

Limitations, documented rather than silently glossed over: this is a
simple split-by-count, not an academic k-fold/cross-validation protocol,
and "first N media" follows whatever order
`ai_training.db.dataset_repo.find_enrolled_media` returned (not guaranteed
chronological) - acceptable for a regression-style promotion gate, not a
rigorous scientific benchmark methodology.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np
from pydantic import BaseModel

from ai_training.evaluation.latency import measure_embedding_latency_ms
from ai_training.evaluation.scoring import (
    Gallery,
    Probe,
    compute_identification_metrics,
    find_threshold_for_fpir_budget,
    identify_probe,
)

if TYPE_CHECKING:
    from ai_training.config import Settings
    from ai_training.data.snapshots import DatasetSnapshot, MediaEntry
    from ai_training.embedding.embedder import EmbedderInterface

logger = logging.getLogger(__name__)


class EvalReport(BaseModel):
    """Metric report in project priority order.

    Existing fields (`recall`, `f1`, `precision`, `latency_ms_p95`, `far`,
    `model_version`) are the TR-01 contract for BE-13/FE-09 and are kept
    verbatim. New TR-07 fields are additive only. `far` is populated with
    the same value as `fpir` (in this open-set 1:N identification protocol
    FPIR IS the false-accept rate that matters operationally - there is no
    separate 1:1 verification FAR computed by this harness).
    """

    recall: float
    f1: float
    precision: float
    latency_ms_p95: float
    far: float
    model_version: str
    # TR-07 additions.
    latency_ms_p50: float = 0.0
    threshold: float = 0.0
    benchmark_id: str = ""
    fpir: float = 0.0
    fnir_at_fpir_budget: float = 0.0
    # BE-13 addition (additive, defaults to ""): the MLflow run id created by
    # `_log_to_mlflow`, so a caller (ai_training.worker.tasks.run_training_evaluation_job)
    # can persist it onto `training_jobs.mlflow_run_id` / `models.mlflow_run_id`
    # without re-deriving or guessing one. Stays "" when MLflow logging is
    # unconfigured/unavailable/fails — see `_log_to_mlflow`'s best-effort
    # contract, unchanged by this addition.
    mlflow_run_id: str = ""


def _split_gallery_and_probes(
    snapshot: DatasetSnapshot, gallery_media_per_identity: int
) -> tuple[dict[str, list[MediaEntry]], list[tuple[str | None, MediaEntry]]]:
    """See module docstring for the split rule this implements."""
    by_identity: dict[str, list[MediaEntry]] = {}
    for entry in snapshot.media:
        by_identity.setdefault(entry.user_id, []).append(entry)

    gallery_entries: dict[str, list[MediaEntry]] = {}
    probes: list[tuple[str | None, MediaEntry]] = []
    for user_id, media in by_identity.items():
        if len(media) < 2:
            # Held out entirely: impostor probe(s), never enter the gallery.
            for entry in media:
                probes.append((None, entry))
            continue
        gallery_count = max(1, min(gallery_media_per_identity, len(media) - 1))
        gallery_entries[user_id] = media[:gallery_count]
        for entry in media[gallery_count:]:
            probes.append((user_id, entry))
    return gallery_entries, probes


def _decode_media_to_frames(media_bytes: bytes, kind: str, settings: Settings) -> list[Any]:
    """Decode one media object's bytes into a list of candidate BGR frames.

    Videos are sampled at `settings.qc.sample_fps` via the SAME decoder
    TR-02's QC pipeline uses (`quality.pipeline.extract_frames`) - no
    second video-decode implementation. Images are decoded directly with
    `cv2.imdecode` (single-frame "video").
    """
    if kind == "video":
        from ai_training.quality.pipeline import extract_frames

        return extract_frames(media_bytes, fps_sample=settings.qc.sample_fps)

    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - depends on extras
        raise RuntimeError(
            "evaluate_candidate image decode requires the 'ml' extra (uv sync --extra ml): "
            "opencv-python-headless."
        ) from exc
    buffer = np.frombuffer(media_bytes, dtype=np.uint8)
    frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    return [frame] if frame is not None else []


def _embed_media_entry(
    entry: MediaEntry,
    settings: Settings,
    embedder: EmbedderInterface,
    s3_client: Any,
) -> tuple[list[float], Any] | None:
    """Download + detect + align + embed ONE media entry.

    Returns `(embedding_vector, aligned_crop)` so orchestration can reuse
    the aligned crop for latency measurement without a second decode, or
    `None` if no face could be detected in any decoded frame (skipped, not
    fatal - mirrors `extract_gallery_embeddings`'s "extremely unlikely but
    not fatal" handling of the same situation).
    """
    from ai_training.embedding.alignment import align_face
    from ai_training.quality.pose import detect_face_and_landmarks

    response = s3_client.get_object(Bucket=settings.s3.bucket, Key=entry.s3_key)
    media_bytes = response["Body"].read()

    frames = _decode_media_to_frames(media_bytes, entry.kind, settings)
    for frame in frames:
        if frame is None:
            continue
        detection = detect_face_and_landmarks(
            frame, model_path=settings.qc.face_landmarker_model_path or None
        )
        if detection is None:
            continue
        aligned = align_face(frame, detection.alignment_landmarks_5pt())
        vector = embedder.embed(aligned)
        return vector, aligned
    return None


def _log_to_mlflow(
    settings: Settings,
    *,
    model_version: str,
    benchmark_id: str,
    threshold: float,
    report: EvalReport,
) -> str:
    """Best-effort MLflow run logging (FR-TRN-03 gap closed by TR-07 - see
    task brief). Never raises: a broken/unconfigured tracking backend must
    not prevent `evaluate_candidate` from returning a locally-useful
    `EvalReport`, same "best-effort, non-fatal" spirit as this project's
    other secondary side effects (e.g. backend's SSE publish).

    Returns the created MLflow run id, or "" whenever nothing was actually
    logged (untracked/unconfigured/mlflow not installed/logging failed) -
    BE-13 addition so `evaluate_candidate` can populate
    `EvalReport.mlflow_run_id`."""
    if not settings.mlflow.tracking_uri:
        logger.warning(
            "evaluate_candidate: TRN_MLFLOW__TRACKING_URI not configured; skipping MLflow logging"
        )
        return ""
    try:
        import mlflow
    except ImportError:
        logger.warning(
            "evaluate_candidate: mlflow not installed (uv sync --extra ml); "
            "skipping MLflow logging"
        )
        return ""

    import json
    import sys
    import tempfile
    from pathlib import Path

    # MLflow's own run-lifecycle code (`end_run` -> `_log_url`) prints a
    # "View run ... at: ..." line containing a running-person emoji. On a
    # default Windows console, stdout is opened with the cp1252 codepage
    # (not UTF-8), so that print raises UnicodeEncodeError -- discovered
    # live: this crashed INSIDE `with mlflow.start_run():`'s __exit__,
    # after params/metrics/artifacts had already been logged successfully,
    # leaving the run stuck in status=RUNNING forever (never marked
    # FINISHED) even though evaluate_candidate's own try/except below
    # swallowed the exception and returned a valid EvalReport. Widening
    # stdout's error handling (replace unencodable characters instead of
    # raising) fixes this without needing PYTHONIOENCODING set externally.
    # Guarded because `reconfigure` doesn't exist on every stream type
    # (e.g. some captured/piped stdouts in test runners).
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    try:
        mlflow.set_tracking_uri(settings.mlflow.tracking_uri)
        mlflow.set_experiment(settings.mlflow.experiment_name)
        with mlflow.start_run() as run:
            run_id = run.info.run_id
            mlflow.log_params(
                {
                    "benchmark_id": benchmark_id,
                    "model_version": model_version,
                    "threshold": threshold,
                    "fpir_budget": settings.evaluation.fpir_budget,
                }
            )
            mlflow.log_metrics(
                {
                    "recall": report.recall,
                    "precision": report.precision,
                    "f1": report.f1,
                    "fnir": report.fnir_at_fpir_budget,
                    "fpir": report.fpir,
                    "latency_ms_p50": report.latency_ms_p50,
                    "latency_ms_p95": report.latency_ms_p95,
                }
            )
            with tempfile.TemporaryDirectory() as tmp_dir:
                report_path = Path(tmp_dir) / "eval_report.json"
                report_path.write_text(json.dumps(report.model_dump(), indent=2))
                mlflow.log_artifact(str(report_path))
        return run_id
    except Exception:  # noqa: BLE001 - tracking must never break evaluation
        logger.exception("evaluate_candidate: MLflow logging failed (non-fatal)")
        return ""


def evaluate_candidate(settings: Settings, model_version: str, benchmark_id: str) -> EvalReport:
    """Run the frozen (TR-04 snapshot) open-set 1:N identification
    benchmark against a candidate model and return an `EvalReport`.

    Not covered by automated tests without infra (needs real S3 +
    Postgres-backed snapshot content, and the configured embedder backend)
    - same status as `quality.pipeline.run_quality_check` /
    `embedding.extractor.extract_gallery_embeddings`. The pure math
    (`evaluation.scoring`) and timing (`evaluation.latency`) layers this
    function orchestrates ARE fully unit-tested; verify this function
    live against a real snapshot + `TRN_EMBEDDER__BACKEND=adaface`.
    """
    from ai_training.data.snapshots import load_snapshot
    from ai_training.embedding.embedder import build_embedder
    from ai_training.storage import build_s3_client

    snapshot = load_snapshot(settings, benchmark_id)
    gallery_entries, probe_entries = _split_gallery_and_probes(
        snapshot, settings.evaluation.gallery_media_per_identity
    )

    embedder = build_embedder(settings)
    s3_client = build_s3_client(settings)

    gallery: Gallery = {}
    for user_id, entries in gallery_entries.items():
        vectors = []
        for entry in entries:
            embedded = _embed_media_entry(entry, settings, embedder, s3_client)
            if embedded is not None:
                vectors.append(np.asarray(embedded[0], dtype=np.float64))
        if vectors:
            gallery[user_id] = vectors

    probes: list[Probe] = []
    aligned_crops_for_latency: list[Any] = []
    for true_identity, entry in probe_entries:
        embedded = _embed_media_entry(entry, settings, embedder, s3_client)
        if embedded is None:
            continue
        vector, aligned_crop = embedded
        probes.append((true_identity, np.asarray(vector, dtype=np.float64)))
        aligned_crops_for_latency.append(aligned_crop)

    genuine_scores: list[float] = []
    impostor_scores: list[float] = []
    for true_identity, embedding in probes:
        _predicted, score = identify_probe(embedding, gallery, threshold=float("-inf"))
        if true_identity is not None:
            genuine_scores.append(score)
        else:
            impostor_scores.append(score)

    threshold = find_threshold_for_fpir_budget(
        genuine_scores, impostor_scores, settings.evaluation.fpir_budget
    )
    id_metrics = compute_identification_metrics(probes, gallery, threshold)

    if aligned_crops_for_latency:
        latency = measure_embedding_latency_ms(embedder, aligned_crops_for_latency)
        latency_p50 = latency["latency_ms_p50"]
        latency_p95 = latency["latency_ms_p95"]
    else:
        logger.warning("evaluate_candidate: no usable probe crops; latency not measured")
        latency_p50 = 0.0
        latency_p95 = 0.0

    report = EvalReport(
        recall=id_metrics["recall"],
        f1=id_metrics["f1"],
        precision=id_metrics["precision"],
        latency_ms_p95=latency_p95,
        far=id_metrics["fpir"],
        model_version=model_version,
        latency_ms_p50=latency_p50,
        threshold=threshold,
        benchmark_id=benchmark_id,
        fpir=id_metrics["fpir"],
        fnir_at_fpir_budget=id_metrics["fnir"],
    )

    report.mlflow_run_id = _log_to_mlflow(
        settings,
        model_version=model_version,
        benchmark_id=benchmark_id,
        threshold=threshold,
        report=report,
    )
    return report
