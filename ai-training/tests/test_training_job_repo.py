"""Raw-SQL `training_jobs`/`models` write-back helpers (BE-13) against a
mocked DB-API cursor — same convention as test_db_repo.py: no real Postgres."""

import json
from unittest.mock import MagicMock

from ai_training.db.training_job_repo import (
    get_model_stage,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    upsert_model_metrics,
    upsert_model_slice_gate_report,
)


def test_mark_job_running_updates_status() -> None:
    cursor = MagicMock()
    mark_job_running(cursor, "job-1")
    cursor.execute.assert_called_once()
    args, _ = cursor.execute.call_args
    assert "SET status = 'RUNNING'" in args[0]
    assert args[1] == ("job-1",)


def test_mark_job_succeeded_sets_mlflow_run_id_and_completed_at() -> None:
    cursor = MagicMock()
    mark_job_succeeded(cursor, "job-1", mlflow_run_id="run-abc")
    args, _ = cursor.execute.call_args
    assert "SUCCEEDED" in args[0]
    assert "completed_at = now()" in args[0]
    assert args[1] == ("run-abc", "job-1")


def test_mark_job_failed_sets_error_message() -> None:
    cursor = MagicMock()
    mark_job_failed(cursor, "job-1", error_message="boom")
    args, _ = cursor.execute.call_args
    assert "FAILED" in args[0]
    assert args[1] == ("boom", "job-1")


def test_get_model_stage_returns_none_when_no_row() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    assert get_model_stage(cursor, "v1") is None


def test_get_model_stage_returns_value() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = ("PRODUCTION",)
    assert get_model_stage(cursor, "v1") == "PRODUCTION"


def test_upsert_model_metrics_inserts_as_candidate_when_no_existing_row() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = None  # no existing row
    upsert_model_metrics(
        cursor,
        version="v1",
        mlflow_run_id="run-1",
        recall=0.99,
        f1=0.95,
        precision=0.9,
        latency_ms_p95=123.6,
    )
    # 1 SELECT (get_model_stage) + 1 INSERT
    assert cursor.execute.call_count == 2
    insert_call = cursor.execute.call_args_list[1]
    assert "INSERT INTO models" in insert_call[0][0]
    assert "CANDIDATE" in insert_call[0][0]
    # latency rounded to nearest int for the Integer column.
    assert insert_call[0][1][-1] == 124


def test_upsert_model_metrics_updates_without_touching_stage_when_row_exists() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = ("PRODUCTION",)  # existing row, already promoted
    upsert_model_metrics(
        cursor,
        version="v1",
        mlflow_run_id="run-2",
        recall=0.5,
        f1=0.5,
        precision=0.5,
        latency_ms_p95=10.0,
    )
    assert cursor.execute.call_count == 2
    update_call = cursor.execute.call_args_list[1]
    assert "UPDATE models SET" in update_call[0][0]
    assert "stage" not in update_call[0][0].lower()


def test_upsert_model_slice_gate_report_writes_json_blob() -> None:
    cursor = MagicMock()
    report = {"passes": False, "failed_slices": ["dark"], "per_slice": {}}
    upsert_model_slice_gate_report(cursor, version="v1", slice_gate_report=report)

    cursor.execute.assert_called_once()
    args, _ = cursor.execute.call_args
    assert "UPDATE models SET slice_gate_report" in args[0]
    assert args[1][0] == json.dumps(report)
    assert args[1][1] == "v1"
