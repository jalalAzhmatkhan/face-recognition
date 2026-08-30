"""`run_training_evaluation_job_core` (BE-13) against a fake DB cursor and a
monkeypatched `evaluate_candidate` — never a real Postgres/S3/torch, per
project testing convention (mirrors test_worker_task_idempotency.py)."""

import ai_training.worker.tasks as tasks_module
from ai_training.config import Settings
from ai_training.evaluation.metrics import EvalReport
from ai_training.worker.tasks import run_training_evaluation_job_core


class FakeCursor:
    """Minimal DB-API-cursor-shaped fake tracking every executed statement."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, query: str, params: tuple = ()) -> None:
        self.executed.append((query, params))

    def fetchone(self):
        # get_model_stage's SELECT: pretend no existing `models` row.
        return None


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_succeeded_path_marks_running_then_succeeded_and_upserts_model(
    monkeypatch,
) -> None:
    fake_report = EvalReport(
        recall=0.99,
        f1=0.95,
        precision=0.92,
        latency_ms_p95=120.0,
        far=0.001,
        model_version="adaface-v2",
        benchmark_id="snap-1",
        mlflow_run_id="run-abc",
    )
    monkeypatch.setattr(
        "ai_training.evaluation.metrics.evaluate_candidate",
        lambda settings, model_version, benchmark_id: fake_report,
    )

    cursor = FakeCursor()
    outcome = run_training_evaluation_job_core(
        cursor, _settings(), "job-1", "adaface-v2", "snap-1"
    )

    assert outcome == "succeeded"
    queries = [q for q, _ in cursor.executed]
    assert any("SET status = 'RUNNING'" in q for q in queries)
    assert any("INSERT INTO models" in q for q in queries)
    assert any("SUCCEEDED" in q for q in queries)
    assert any("INSERT INTO audit_logs" in q for q in queries)
    # 3 audit log inserts expected: job_running, then job_succeeded (no
    # job_failed) -- 2 audit rows total.
    audit_actions = [
        params[2] for q, params in cursor.executed if q.startswith("INSERT INTO audit_logs")
    ]
    assert audit_actions == ["training.job_running", "training.job_succeeded"]


def test_failed_path_marks_failed_and_never_raises(monkeypatch) -> None:
    def _raise(settings, model_version, benchmark_id):
        raise RuntimeError("benchmark snapshot not found")

    monkeypatch.setattr("ai_training.evaluation.metrics.evaluate_candidate", _raise)

    cursor = FakeCursor()
    outcome = run_training_evaluation_job_core(
        cursor, _settings(), "job-1", "adaface-v2", "snap-missing"
    )

    assert outcome == "failed"
    queries = [q for q, _ in cursor.executed]
    assert any("FAILED" in q for q in queries)
    assert not any("INSERT INTO models" in q for q in queries)
    failed_query = next(q for q, _ in cursor.executed if "FAILED" in q)
    failed_params = next(p for q, p in cursor.executed if q == failed_query)
    assert "benchmark snapshot not found" in failed_params[0]


def test_proxy_task_in_backend_never_actually_evaluates() -> None:
    """Sanity check for BE-13's cross-service wiring decision: backend's own
    `run_training_evaluation_job` (app/worker/tasks.py) is a name-only proxy
    that must never run for real — this test lives in ai-training only to
    document/assert the module-name convention it depends on
    (`app.worker.tasks.run_training_evaluation_job`), without importing
    backend (a separate project/venv)."""
    assert tasks_module.run_training_evaluation_job.name == (
        "app.worker.tasks.run_training_evaluation_job"
    )
