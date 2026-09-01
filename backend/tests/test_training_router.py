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
from app.models.enums import ModelKind, ModelStage, StaffRole, TrainingJobStatus, TrainingJobType
from app.models.model_registry import ModelVersion
from app.models.training_job import TrainingJob
from app.routers.training import (
    get_audit_log_repository,
    get_model_version_repository,
    get_training_job_repository,
)
from app.services import gallery_queue, training_queue


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

    def _filtered(
        self,
        *,
        status: TrainingJobStatus | None = None,
        model_version: str | None = None,
    ) -> list[TrainingJob]:
        items = sorted(self._by_id.values(), key=lambda j: j.created_at, reverse=True)
        if status is not None:
            items = [j for j in items if j.status == status]
        if model_version is not None:
            items = [j for j in items if j.model_version == model_version]
        return items

    def list(
        self,
        *,
        status: TrainingJobStatus | None = None,
        model_version: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TrainingJob]:
        return self._filtered(status=status, model_version=model_version)[offset : offset + limit]

    def count(
        self, *, status: TrainingJobStatus | None = None, model_version: str | None = None
    ) -> int:
        return len(self._filtered(status=status, model_version=model_version))


class FakeModelVersionRepository:
    def __init__(self, models: list[ModelVersion] | None = None) -> None:
        self._by_version: dict[str, ModelVersion] = {m.version: m for m in (models or [])}

    def get(self, version: str) -> ModelVersion | None:
        return self._by_version.get(version)

    def list(
        self, *, stage: ModelStage | None = None, model_kind: ModelKind | None = None
    ) -> list[ModelVersion]:
        items = list(self._by_version.values())
        if stage is not None:
            items = [m for m in items if m.stage == stage]
        if model_kind is not None:
            items = [m for m in items if m.model_kind == model_kind]
        return sorted(items, key=lambda m: m.version)

    def get_current_production(self, *, model_kind: ModelKind) -> ModelVersion | None:
        for m in self._by_version.values():
            if m.stage == ModelStage.PRODUCTION and m.model_kind == model_kind:
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
    model_kind: ModelKind = ModelKind.EMBEDDER,
    recall: float | None = 0.99,
    latency_ms_p95: int | None = 120,
    slice_gate_report: dict | None = None,
) -> ModelVersion:
    return ModelVersion(
        version=version,
        mlflow_run_id=f"run-{version}",
        stage=stage,
        model_kind=model_kind,
        recall=recall,
        f1=0.9,
        precision=0.9,
        latency_ms_p95=latency_ms_p95,
        slice_gate_report=slice_gate_report,
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


@pytest.fixture(autouse=True)
def _no_real_gallery_dispatch(monkeypatch: pytest.MonkeyPatch):
    """Never touch a real Redis broker for the TR-08 gallery-reembed dispatch
    either — same rationale as `_no_real_celery_dispatch` above."""
    calls: list[str] = []

    def _fake_enqueue(model_version):
        calls.append(model_version)

    monkeypatch.setattr(gallery_queue, "enqueue_gallery_reembed", _fake_enqueue)
    return calls


@pytest.fixture(autouse=True)
def _no_real_backfill_masked_dispatch(monkeypatch: pytest.MonkeyPatch):
    """Never touch a real Redis broker for the D-4.5 backfill dispatch
    either (EC-TR-03 wired `create_training_job` to call this for
    `job_type=BACKFILL_MASKED_TEMPLATES`) — same rationale as
    `_no_real_celery_dispatch`/`_no_real_gallery_dispatch` above."""
    calls: list[uuid.UUID] = []

    def _fake_enqueue(job_id):
        calls.append(job_id)

    monkeypatch.setattr(training_queue, "enqueue_backfill_masked_templates_job", _fake_enqueue)
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
    """Pre-EC-BE-03 request shape (no `job_type` field at all) must still
    work identically: zero regression for existing clients."""
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"model_version": "adaface-v2", "benchmark_id": "snap-1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PENDING"
    assert body["job_type"] == "EVALUATION"
    assert body["model_version"] == "adaface-v2"
    assert body["benchmark_id"] == "snap-1"
    assert body["snapshot_id"] is None
    assert body["params"] is None
    assert any(e["action"] == "training.job_created" for e in audit_repo.entries)
    assert len(_no_real_celery_dispatch) == 1


# --- EC-BE-03: job_type + params validation ---------------------------------


def test_create_evaluation_job_still_requires_model_version_and_benchmark_id(
    admin_client: TestClient,
) -> None:
    """Explicit `job_type=EVALUATION` behaves exactly like the implicit
    default — both required fields still enforced."""
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"job_type": "EVALUATION", "benchmark_id": "snap-1"},
    )
    assert response.status_code == 422


def test_create_finetune_embedder_job_requires_augmentations(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"job_type": "FINETUNE_EMBEDDER", "params": {}},
    )
    assert response.status_code == 422


def test_create_finetune_embedder_job_succeeds_with_augmentations(
    admin_client: TestClient, _no_real_celery_dispatch
) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={
            "job_type": "FINETUNE_EMBEDDER",
            "params": {"augmentations": ["mask_mlfw", "occlusion_ocfr"]},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "FINETUNE_EMBEDDER"
    assert body["model_version"] is None
    assert body["benchmark_id"] is None
    assert body["params"] == {"augmentations": ["mask_mlfw", "occlusion_ocfr"]}
    # B-1 scope: no Celery task exists yet for this job_type, so nothing is
    # dispatched (only EVALUATION dispatches today).
    assert len(_no_real_celery_dispatch) == 0


def test_create_finetune_liveness_job_requires_dataset_ref(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"job_type": "FINETUNE_LIVENESS", "params": {}},
    )
    assert response.status_code == 422


def test_create_finetune_liveness_job_succeeds_with_dataset_ref(
    admin_client: TestClient, _no_real_celery_dispatch
) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={
            "job_type": "FINETUNE_LIVENESS",
            "params": {"dataset_ref": "pad/collection-1"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "FINETUNE_LIVENESS"
    assert body["params"] == {"dataset_ref": "pad/collection-1"}
    assert len(_no_real_celery_dispatch) == 0


def test_create_gallery_reembed_job_requires_model_version(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"job_type": "GALLERY_REEMBED"},
    )
    assert response.status_code == 422


def test_create_gallery_reembed_job_succeeds_with_model_version(
    admin_client: TestClient, _no_real_celery_dispatch
) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"job_type": "GALLERY_REEMBED", "model_version": "adaface-v3"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "GALLERY_REEMBED"
    assert body["model_version"] == "adaface-v3"
    assert len(_no_real_celery_dispatch) == 0


def test_create_backfill_masked_templates_job_succeeds_with_no_fields(
    admin_client: TestClient, _no_real_celery_dispatch, _no_real_backfill_masked_dispatch
) -> None:
    """No required fields beyond job_type itself (D-4.5). EC-TR-03 wired
    this job_type to dispatch `run_backfill_masked_templates_job` (unlike
    GALLERY_REEMBED/FINETUNE_*, which still persist a row with no
    dispatch) — verified via `_no_real_backfill_masked_dispatch` instead of
    `_no_real_celery_dispatch` (that one is EVALUATION-only)."""
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"job_type": "BACKFILL_MASKED_TEMPLATES"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["job_type"] == "BACKFILL_MASKED_TEMPLATES"
    assert body["model_version"] is None
    assert body["benchmark_id"] is None
    assert len(_no_real_celery_dispatch) == 0
    assert len(_no_real_backfill_masked_dispatch) == 1
    assert str(_no_real_backfill_masked_dispatch[0]) == body["id"]


def test_create_job_with_snapshot_id_is_persisted(
    admin_client: TestClient, _no_real_celery_dispatch
) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={
            "job_type": "BACKFILL_MASKED_TEMPLATES",
            "snapshot_id": "3f5b9c1a-0000-4000-8000-000000000001",
        },
    )
    assert response.status_code == 201
    assert response.json()["snapshot_id"] == "3f5b9c1a-0000-4000-8000-000000000001"


def test_create_job_rejects_unknown_job_type(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/v1/training/jobs",
        json={"job_type": "NOT_A_REAL_TYPE"},
    )
    assert response.status_code == 422


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
            job_type=TrainingJobType.EVALUATION,
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
            job_type=TrainingJobType.EVALUATION,
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
            job_type=TrainingJobType.EVALUATION,
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


# --- GET /training/jobs (BE-15) ---------------------------------------------


def test_list_jobs_shows_job_type(
    admin_client: TestClient, job_repo: FakeTrainingJobRepository
) -> None:
    """EC-BE-03 acceptance criterion: `GET /training/jobs` displays
    `job_type`, including for non-EVALUATION jobs."""
    job_repo.create(
        TrainingJob(
            job_type=TrainingJobType.GALLERY_REEMBED,
            model_version="adaface-v3",
            status=TrainingJobStatus.PENDING,
            triggered_by=uuid.uuid4(),
        )
    )
    response = admin_client.get("/api/v1/training/jobs")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["job_type"] == "GALLERY_REEMBED"


def test_list_jobs_newest_first_for_operator(
    operator_client: TestClient, job_repo: FakeTrainingJobRepository
) -> None:
    older = job_repo.create(
        TrainingJob(
            job_type=TrainingJobType.EVALUATION,
            model_version="adaface-v1",
            benchmark_id="snap-1",
            status=TrainingJobStatus.SUCCEEDED,
            triggered_by=uuid.uuid4(),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    newer = job_repo.create(
        TrainingJob(
            job_type=TrainingJobType.EVALUATION,
            model_version="adaface-v2",
            benchmark_id="snap-2",
            status=TrainingJobStatus.RUNNING,
            triggered_by=uuid.uuid4(),
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    response = operator_client.get("/api/v1/training/jobs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [str(newer.id), str(older.id)]


def test_list_jobs_filters_by_status(
    admin_client: TestClient, job_repo: FakeTrainingJobRepository
) -> None:
    job_repo.create(
        TrainingJob(
            job_type=TrainingJobType.EVALUATION,
            model_version="adaface-v1",
            benchmark_id="snap-1",
            status=TrainingJobStatus.FAILED,
            triggered_by=uuid.uuid4(),
        )
    )
    succeeded = job_repo.create(
        TrainingJob(
            job_type=TrainingJobType.EVALUATION,
            model_version="adaface-v2",
            benchmark_id="snap-2",
            status=TrainingJobStatus.SUCCEEDED,
            triggered_by=uuid.uuid4(),
        )
    )
    response = admin_client.get("/api/v1/training/jobs", params={"status": "SUCCEEDED"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(succeeded.id)


def test_list_jobs_filters_by_model_version(
    admin_client: TestClient, job_repo: FakeTrainingJobRepository
) -> None:
    job_repo.create(
        TrainingJob(
            job_type=TrainingJobType.EVALUATION,
            model_version="adaface-v1",
            benchmark_id="snap-1",
            status=TrainingJobStatus.SUCCEEDED,
            triggered_by=uuid.uuid4(),
        )
    )
    target = job_repo.create(
        TrainingJob(
            job_type=TrainingJobType.EVALUATION,
            model_version="adaface-v2",
            benchmark_id="snap-2",
            status=TrainingJobStatus.SUCCEEDED,
            triggered_by=uuid.uuid4(),
        )
    )
    response = admin_client.get(
        "/api/v1/training/jobs", params={"model_version": "adaface-v2"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == str(target.id)


def test_list_jobs_respects_limit_and_offset(
    admin_client: TestClient, job_repo: FakeTrainingJobRepository
) -> None:
    for i in range(5):
        job_repo.create(
            TrainingJob(
                job_type=TrainingJobType.EVALUATION,
                model_version=f"adaface-v{i}",
                benchmark_id="snap",
                status=TrainingJobStatus.SUCCEEDED,
                triggered_by=uuid.uuid4(),
                created_at=datetime(2026, 1, i + 1, tzinfo=UTC),
            )
        )
    response = admin_client.get("/api/v1/training/jobs", params={"limit": 2, "offset": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert len(body["items"]) == 2


def test_list_jobs_denied_for_viewer(viewer_client: TestClient) -> None:
    response = viewer_client.get("/api/v1/training/jobs")
    assert response.status_code == 403


def test_list_jobs_requires_authentication() -> None:
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/training/jobs")
    assert response.status_code == 401


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


def test_model_response_includes_model_kind(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1")
    response = admin_client.get("/api/v1/models/v1")
    assert response.status_code == 200
    assert response.json()["model_kind"] == "embedder"


# --- EC-BE-06: models.model_kind registry split -----------------------------


def test_list_models_filters_by_model_kind(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1", model_kind=ModelKind.EMBEDDER)
    model_repo._by_version["v2"] = _make_model("v2", model_kind=ModelKind.LIVENESS)
    response = admin_client.get("/api/v1/models", params={"model_kind": "liveness"})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["version"] for i in items] == ["v2"]


def test_list_models_returns_both_kinds_when_model_kind_omitted(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model("v1", model_kind=ModelKind.EMBEDDER)
    model_repo._by_version["v2"] = _make_model("v2", model_kind=ModelKind.LIVENESS)
    response = admin_client.get("/api/v1/models")
    assert response.status_code == 200
    assert {i["version"] for i in response.json()["items"]} == {"v1", "v2"}


def test_promote_liveness_candidate_skips_recall_regression_gate(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    """A LIVENESS candidate's Recall is meaningless (its real gate is
    BPCER@APCER, landing with EC-TR-07/EC-IN-05/EC-QA-03) - a low recall
    vs. the current LIVENESS production must never block promotion."""
    model_repo._by_version["v1"] = _make_model(
        "v1", model_kind=ModelKind.LIVENESS, stage=ModelStage.PRODUCTION, recall=0.99
    )
    model_repo._by_version["v2"] = _make_model(
        "v2", model_kind=ModelKind.LIVENESS, stage=ModelStage.CANDIDATE, recall=0.01
    )
    response = admin_client.post("/api/v1/models/v2/promote", json={"confirm": True})
    assert response.status_code == 200
    assert model_repo._by_version["v2"].stage == ModelStage.PRODUCTION


def test_promote_liveness_candidate_skips_slice_gate_report_check(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    """EC-QA-01's per-slice identification-Recall regression report has no
    meaning for a LIVENESS candidate; a failing report on one must never
    block its promotion."""
    failing_report = {"passes": False, "failed_slices": ["dark"], "per_slice": {}}
    model_repo._by_version["v1"] = _make_model(
        "v1",
        model_kind=ModelKind.LIVENESS,
        latency_ms_p95=100,
        slice_gate_report=failing_report,
    )
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 200


def test_promote_liveness_candidate_still_enforces_latency_budget(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["v1"] = _make_model(
        "v1", model_kind=ModelKind.LIVENESS, latency_ms_p95=999999
    )
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 409
    assert "latency" in response.json()["detail"].lower()


def test_promote_liveness_candidate_does_not_dispatch_gallery_reembed(
    admin_client: TestClient,
    model_repo: FakeModelVersionRepository,
    _no_real_gallery_dispatch,
) -> None:
    """Gallery re-embedding (TR-08/FR-TRN-06) only makes sense for a
    promoted EMBEDDER - a LIVENESS promotion has no embedding space to
    re-embed."""
    model_repo._by_version["v1"] = _make_model(
        "v1", model_kind=ModelKind.LIVENESS, latency_ms_p95=100
    )
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 200
    assert _no_real_gallery_dispatch == []


def test_promote_liveness_candidate_does_not_retire_embedder_production(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    """Each kind has its own independent PRODUCTION slot - promoting a
    LIVENESS candidate must never touch/retire an unrelated EMBEDDER
    PRODUCTION model, and vice versa."""
    model_repo._by_version["embedder-v1"] = _make_model(
        "embedder-v1", model_kind=ModelKind.EMBEDDER, stage=ModelStage.PRODUCTION, recall=0.9
    )
    model_repo._by_version["liveness-v1"] = _make_model(
        "liveness-v1", model_kind=ModelKind.LIVENESS, stage=ModelStage.CANDIDATE
    )
    response = admin_client.post("/api/v1/models/liveness-v1/promote", json={"confirm": True})
    assert response.status_code == 200
    assert model_repo._by_version["liveness-v1"].stage == ModelStage.PRODUCTION
    assert model_repo._by_version["embedder-v1"].stage == ModelStage.PRODUCTION


def test_promote_embedder_candidate_does_not_retire_liveness_production(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    model_repo._by_version["liveness-v1"] = _make_model(
        "liveness-v1", model_kind=ModelKind.LIVENESS, stage=ModelStage.PRODUCTION
    )
    model_repo._by_version["embedder-v1"] = _make_model(
        "embedder-v1", model_kind=ModelKind.EMBEDDER, stage=ModelStage.CANDIDATE, recall=0.9
    )
    response = admin_client.post("/api/v1/models/embedder-v1/promote", json={"confirm": True})
    assert response.status_code == 200
    assert model_repo._by_version["embedder-v1"].stage == ModelStage.PRODUCTION
    assert model_repo._by_version["liveness-v1"].stage == ModelStage.PRODUCTION


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


# --- EC-QA-01: per-slice no-regression-bertoleransi-CI gate -----------------


def test_promote_rejects_candidate_with_failing_slice_gate_report(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    """A candidate can pass the overall-Recall gate (3) while still
    regressing badly on one critical slice — EC-QA-01 gate 5 must catch
    that independently."""
    failing_report = {
        "passes": False,
        "failed_slices": ["dark"],
        "skipped_slices": [],
        "per_slice": {
            "dark": {
                "status": "fail",
                "reason": "Recall regressed 0.1000 on critical slice 'dark', "
                "exceeding tolerance 0.0200.",
            }
        },
    }
    model_repo._by_version["v1"] = _make_model(
        "v1", recall=0.99, latency_ms_p95=100, slice_gate_report=failing_report
    )
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "EC-QA-01" in detail
    assert "dark" in detail


def test_promote_succeeds_when_slice_gate_report_within_tolerance(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    passing_report = {
        "passes": True,
        "failed_slices": [],
        "skipped_slices": ["masked-riil", "hijab", "low-res", "per-demografi-utama"],
        "per_slice": {"dark": {"status": "pass"}},
    }
    model_repo._by_version["v1"] = _make_model(
        "v1", recall=0.99, latency_ms_p95=100, slice_gate_report=passing_report
    )
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 200
    assert model_repo._by_version["v1"].stage == ModelStage.PRODUCTION


def test_promote_not_blocked_when_slice_gate_report_absent(
    admin_client: TestClient, model_repo: FakeModelVersionRepository
) -> None:
    """`slice_gate_report is None` (harness has not produced one for this
    candidate yet) must never implicitly fail promotion."""
    model_repo._by_version["v1"] = _make_model(
        "v1", recall=0.99, latency_ms_p95=100, slice_gate_report=None
    )
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 200


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


def test_promote_dispatches_gallery_reembed_on_success(
    admin_client: TestClient,
    model_repo: FakeModelVersionRepository,
    _no_real_gallery_dispatch,
) -> None:
    """TR-08/FR-TRN-06: a successful promotion must dispatch gallery
    re-embedding for the newly-PRODUCTION version."""
    model_repo._by_version["v1"] = _make_model("v1", recall=0.9, latency_ms_p95=100)
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 200
    assert _no_real_gallery_dispatch == ["v1"]


def test_promote_does_not_dispatch_gallery_reembed_when_gate_fails(
    admin_client: TestClient,
    model_repo: FakeModelVersionRepository,
    _no_real_gallery_dispatch,
) -> None:
    model_repo._by_version["v1"] = _make_model("v1", recall=0.5, latency_ms_p95=500)
    response = admin_client.post("/api/v1/models/v1/promote", json={"confirm": True})
    assert response.status_code == 409
    assert _no_real_gallery_dispatch == []
