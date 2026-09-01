"""Raw-SQL `training_jobs` / `models` write-back (BE-13, FR-TRN-02/03/05).

Same convention as every other `ai_training/db/*` module (TR-02/TR-03): a
DB-API `Cursor`-shaped object, so tests pass a mock/fake cursor instead of a
real Postgres connection. Writes go through the `ai_training_embeddings_write`
Postgres role, widened by backend migration 7e2c4a91f3d0 to cover
`training_jobs` and `models` (previously `face_embeddings`/
`enrollment_sessions`/`media_objects`/`audit_logs` only).
"""

from __future__ import annotations

import json

from ai_training.db.enrollment_repo import Cursor


def mark_job_running(cursor: Cursor, job_id: str) -> None:
    cursor.execute(
        "UPDATE training_jobs SET status = 'RUNNING' WHERE id = %s",
        (job_id,),
    )


def mark_job_succeeded(cursor: Cursor, job_id: str, *, mlflow_run_id: str) -> None:
    cursor.execute(
        "UPDATE training_jobs SET status = 'SUCCEEDED', completed_at = now(), "
        "mlflow_run_id = %s WHERE id = %s",
        (mlflow_run_id, job_id),
    )


def mark_job_failed(cursor: Cursor, job_id: str, *, error_message: str) -> None:
    cursor.execute(
        "UPDATE training_jobs SET status = 'FAILED', completed_at = now(), "
        "error_message = %s WHERE id = %s",
        (error_message, job_id),
    )


def get_model_stage(cursor: Cursor, version: str) -> str | None:
    cursor.execute("SELECT stage FROM models WHERE version = %s", (version,))
    row = cursor.fetchone()
    return row[0] if row else None


def upsert_model_metrics(
    cursor: Cursor,
    *,
    version: str,
    mlflow_run_id: str,
    recall: float,
    f1: float,
    precision: float,
    latency_ms_p95: float,
) -> None:
    """Insert-or-update the `models` row for `version` with fresh metrics.

    Upsert rule (per BE-13 task instructions): if no row exists yet, insert
    one with `stage='CANDIDATE'` (a freshly-evaluated model always starts as
    a candidate). If a row ALREADY exists — e.g. this is a re-evaluation of
    a model that has since been promoted or retired — its `stage` is left
    untouched; only the metric columns + `mlflow_run_id` are refreshed. This
    worker must never silently downgrade a PRODUCTION/RETIRED model back to
    CANDIDATE just because someone re-ran an evaluation job against it.
    `latency_ms_p95` is stored as an integer (`models.latency_ms_p95` is
    `Integer` — see app/models/model_registry.py) via `round()`, matching
    the ORM column type rather than truncating.
    """
    existing_stage = get_model_stage(cursor, version)
    latency_ms_p95_int = round(latency_ms_p95)
    if existing_stage is None:
        cursor.execute(
            "INSERT INTO models "
            "(version, mlflow_run_id, stage, recall, f1, precision, latency_ms_p95) "
            "VALUES (%s, %s, 'CANDIDATE', %s, %s, %s, %s)",
            (version, mlflow_run_id, recall, f1, precision, latency_ms_p95_int),
        )
    else:
        cursor.execute(
            "UPDATE models SET mlflow_run_id = %s, recall = %s, f1 = %s, precision = %s, "
            "latency_ms_p95 = %s WHERE version = %s",
            (mlflow_run_id, recall, f1, precision, latency_ms_p95_int, version),
        )


def upsert_model_slice_gate_report(
    cursor: Cursor,
    *,
    version: str,
    slice_gate_report: dict,
) -> None:
    """Persist an EC-QA-01 `SliceRegressionGateReport` (already
    `.model_dump(mode="json")`-ed to a plain dict by the caller) onto the
    `models` row for `version`, into the `slice_gate_report` JSONB column
    (backend migration — see `backend/migrations/versions/`, additive per
    TSD-EC D-10 convention).

    Unlike `upsert_model_metrics`, this NEVER inserts a new `models` row —
    a slice gate report is only meaningful for a model version that already
    has (or is being evaluated alongside) overall metrics; if no row exists
    yet this silently no-ops via a 0-rowcount UPDATE, matching the "backend
    only ever reads this table, ai-training worker writes it" ownership
    split documented in `app/repositories/model_versions.py` without
    inventing a second insert path for the same table.

    **Caller is responsible for using the SAME evaluation mode (`e2e` or
    `per_stage`) for both the candidate report going in here and whatever
    baseline it was compared against** — this function has no way to check
    that consistency itself, it only serializes+writes the dict it's given.
    """
    cursor.execute(
        "UPDATE models SET slice_gate_report = %s WHERE version = %s",
        (json.dumps(slice_gate_report), version),
    )
