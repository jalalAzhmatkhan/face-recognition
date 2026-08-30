"""Integration tests for `/api/v1/training/jobs/*` and `/api/v1/models/*`
(BE-13, TSD §7, FR-TRN-02/05/06).

Same no-real-DB/Redis approach as test_access_policies_router.py: every
repository dependency is overridden with an in-memory fake, `get_current_staff`
is overridden directly, and the Celery dispatch
(`app.services.training_queue.enqueue_training_job`) is monkeypatched so no
real Redis broker is needed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import CurrentStaff, get_current_staff
from app.main import create_app
from app.models.enums import ModelStage, StaffRole, TrainingJobStatus
from app.models.model_registry import ModelVersion
from app.models.training_job import TrainingJob
from app.routers.training import (
    get_audit_log_repository,
    get_model_version_repository,
    get_training_job_repository,
)
from app.services import training_queue


class FakeTrainingJobRepository:
    def __init__(self, jobs: list[TrainingJob] | None = None) -> None:
        self._by_id: dict[uuid.UUID, TrainingJob] = {j.id: j for j in (jobs or [])}

    def get(self, job_id: uuid.UUID) -> TrainingJob | None:
        return self._by_id.get(job_id)

    def create(self, job: TrainingJob) -> TrainingJob:
        job.id = job.id or uuid.uuid4()
        job.created_at = job.created_at or datetime.now(UTC)
        self._by_id[job.id] = job
        return job


class FakeModelVersionRepository:
    def __init__(self, models: list[ModelVersion] | None = None) -> None:
        self._by_version: dict[str, ModelVersion] = {m.version: m for m in (models or [])}

    def get(self, version: str) -> ModelVersion | None:
        return self._by_version.get(version)

    def list(self, *, stage: ModelStage | None = None) -> list[ModelVersion]:
        items = list(self._by_version.values())
        if stage is not None:
            items = [m for m in items if m.stage == stage]
        return sorted(items, key=lambda m: m.version)

    def get_current_production(self) -> ModelVersion | None:
        for m in self._by_version.values():
            if m.stage == ModelStage.PRODUCTION:
                return m
        return None

    def update(self, model: ModelVersion) -> ModelVersion:
        self._by_version[model.version] = model
        return model


class FakeAuditLogRepository:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def record(self, *, actor: str, action: str, entity: str, payload=None):
        entry = {"actor": actor, "action": action, "entity": entity, "payload": payload}
        self.entries.append(entry)
        return entry


def _make_model(
    version: str,
    *,
    stage: ModelStage = ModelStage.CANDIDATE,
    recall: float | None = 0.99,
    latency_ms_p95: int | None = 120,
) -> ModelVersion:
    return ModelVersion(
        version=version,
        mlflow_run_id=f"run-{version}",
        stage=stage,
        recall=recall,
        f1=0.9,
        precision=0.9,
        latency_ms_p95=latency_ms_p95,
        promoted_by=None,
        promoted_at=None,
    )


@pytest.fixture(autouse=True)
def _no_real_celery_dispatch(monkeypatch: pytest.MonkeyPatch):
    """Never touch a real Redis broker from these tests."""
    calls: list[dict] = []

    def _fake_enqueue(job_id, model_version, benchmark_id):
        calls.append(
            {"job_id": job_id, "model_version": model_version, "benchmark_id": benchmark_id}
        )

    monkeypatch.setattr(training_queue, "enqueue_training_job", _fake_enqueue)
    return calls


@pytest.fixture
def job_repo() -> FakeTrainingJobRepository:
    return FakeTrainingJobRepository()


@pytest.fixture
def model_repo() -> FakeModelVersionRepository:
    return FakeModelVersionRepository()


@pytest.fixture
def audit_repo() -> FakeAuditLogRepository:
    return FakeAuditLogRepository()


def _client(
    job_repo: FakeTrainingJobRepository,
    model_repo: FakeModelVersionRepository,
    audit_repo: FakeAuditLogRepository,
    role: StaffRole,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_training_job_repository] = lambda: job_repo
    app.dependency_overrides[get_model_version_repository] = lambda: model_repo
    app.dependency_overrides[get_audit_log_repository] = lambda: audit_repo
    app.dependency_overrides[get_current_staff] = lambda: CurrentStaff(
        id=uuid.uuid4(), email=f"{role.value.lower()}@example.com", role=role
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_client(job_repo, model_repo, audit_repo) -> TestClient:
    return _client(job_repo, model_repo, audit_repo, StaffRole.ADMIN)


@pytest.fixture
def operator_client(job_repo, model_repo, audit_repo) -> TestClient:
    return _client(job_repo, model_repo, audit_repo, StaffRole.OPERATOR)


@pytest.fixture
def viewer_client(job_repo, model_repo, audit_repo) -> TestClient:
    return _client(job_repo, model_repo, audit_repo, StaffRole.VIEWER)


# --- POST /training/jobs ----------------------------------------------------


def test_create_job_succeeds_for_admin(
    admin_client: TestClient, audit_repo: FakeAuditLogRepository, _no_real_celery_dispatch
) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"model_version": "adaface-v2", "benchmark_id": "snap-1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["model_version"] == "adaface-v2"
    assert body["benchmark_id"] == "snap-1"
    assert any(e["action"] == "training.job_created" for e in audit_repo.entries)
    assert len(_no_real_celery_dispatch) == 1


def test_create_job_denied_for_operator(operator_client: TestClient) -> None:
    response = operator_client.post(
        "/api/v1/training/jobs",
        json={"model_version": "adaface-v2", "benchmark_id": "snap-1"},
    )
    assert response.status_code == 403


def test_create_job_denied_for_viewer(viewer_client: TestClient) -> None:
    response = viewer_client.post(
        "/api/v1/training/jobs",
        json={"model_version": "adaface-v2", "benchmark_id": "snap-1"},
    )
    assert response.status_code == 403


def test_create_job_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/v1/training/jobs",
        json={"model_version": "adaface-v2", "benchmark_id": "snap-1"},
    )
    assert response.status_code == 401


# --- GET /training/jobs/{id} -------------------------------------------------


def test_get_job_found_for_operator(
    operator_client: TestClient, job_repo: FakeTrainingJobRepository
) -> None:
    job = job_repo.create(
        TrainingJob(
            model_version="adaface-v2",
            benchmark_id="snap-1",
            status=TrainingJobStatus.RUNNING,
            triggered_by=uuid.uuid4(),
        )
    )
    response = operator_client.get(f"/api/v1/training/jobs/{job.id}")
    assert response.status_code == 200
    assert response.json()["status"] == "RUNNING"


def test_get_job_returns_404_for_unknown_id(admin_client: TestClient) -> None:
    response = admin_client.get(f"/api/v1/training/jobs/{uuid.uuid4()}")
    assert response.status_code == 404


def test_get_job_denied_for_viewer(
    viewer_client: TestClient, job_repo: FakeTrainingJobRepository
) -> None:
    job = job_repo.create(
        TrainingJob(
            model_version="adaface-v2",
            benchmark_id="snap-1",
            status=TrainingJobStatus.PENDING,
            triggered_by=uuid.uuid4(),
        )
    )
    response = viewer_client.get(f"/api/v1/training/jobs/{job.id}")
    assert response.status_code == 403


def test_get_job_exposes_error_message_when_failed(
    admin_client: TestClient, job_repo: FakeTrainingJobRepository
) -> None:
    job = job_repo.create(
        TrainingJob(
            model_version="adaface-v2",
            benchmark_id="snap-1",
            status=TrainingJobStatus.FAILED,
            triggered_by=uuid.uuid4(),
            error_message="benchmark snapshot not found",
        )
    )
    response = admin_client.get(f"/api/v1/training/jobs/{job.id}")
    assert response.status_code == 200
    assert response.json()["error_message"] == "benchmark snapshot not found"


# --- GET /models -------------------------------------------------------------


def test_list_models_allowed_for_viewer(
    viewer_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1")
    response = viewer_client.get("/api/v1/models")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_list_models_filters_by_stage(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1", stage=ModelStage.CANDIDATE)
    model_repo._by_version["v2"] = _make_model("v2", stage=ModelStage.PRODUCTION)
    response = admin_client.get("/api/v1/models", params={"stage": "PRODUCTION"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["version"] == "v2"


def test_get_model_returns_404_for_unknown_version(admin_client: TestClient) -> None:
    response = admin_client.get("/api/v1/models/does-not-exist")
    assert response.status_code == 404


# --- POST /models/{version}/promote ------------------------------------------


def test_promote_requires_confirmation(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1")
    response = admin_client.post("/api/v1/models/v1/promote", json={})
    assert response.status_code == 422


def test_promote_denied_for_operator(
    operator_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1")
    response = operator_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 403


def test_promote_returns_404_for_unknown_version(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/models/does-not-exist/promote", json={"confirm": True}
    )
    assert response.status_code == 404


def test_promote_rejects_non_candidate_stage(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1", stage=ModelStage.RETIRED)
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 409
    assert "CANDIDATE" in response.json()["detail"]


def test_promote_rejects_latency_over_budget(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1", latency_ms_p95=500)
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 409
    assert "latency" in response.json()["detail"].lower()


def test_promote_succeeds_as_first_promotion_without_baseline(
    admin_client: TestClient,
    model_repo: FakeModelVersionRepository,
    audit_repo: FakeAuditLogRepository,
) -> None:
    model_repo._by_version["v1"] = _make_model("v1", recall=0.5, latency_ms_p95=250)
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "PRODUCTION"
    assert model_repo._by_version["v1"].stage == ModelStage.PRODUCTION
    assert any(e["action"] == "model.promoted" for e in audit_repo.entries)


def test_promote_rejects_recall_regression(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model(
        "v1", stage=ModelStage.PRODUCTION, recall=0.99, latency_ms_p95=100
    )
    model_repo._by_version["v2"] = _make_model(
        "v2", stage=ModelStage.CANDIDATE, recall=0.80, latency_ms_p95=100
    )
    response = admin_client.post("/api/v1/models/v2/promote", json={"confirm": True})
    assert response.status_code == 409
    assert "recall" in response.json()["detail"].lower()


def test_promote_succeeds_and_retires_previous_production(
    admin_client: TestClient,
    model_repo: FakeModelVersionRepository,
    audit_repo: FakeAuditLogRepository,
) -> None:
    model_repo._by_version["v1"] = _make_model(
        "v1", stage=ModelStage.PRODUCTION, recall=0.90, latency_ms_p95=100
    )
    model_repo._by_version["v2"] = _make_model(
        "v2", stage=ModelStage.CANDIDATE, recall=0.95, latency_ms_p95=100
    )
    response = admin_client.post("/api/v1/models/v2/promote", json={"confirm": True})
    assert response.status_code == 200
    assert model_repo._by_version["v2"].stage == ModelStage.PRODUCTION
    assert model_repo._by_version["v1"].stage == ModelStage.RETIRED
    promoted_entry = next(e for e in audit_repo.entries if e["action"] == "model.promoted")
    assert promoted_entry["payload"]["retired_version"] == "v1"
