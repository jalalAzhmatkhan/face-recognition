"""Smoke tests for the inference service scaffold (IN-01)."""

from fastapi.testclient import TestClient

from ai_inference.config import Settings
from ai_inference.main import create_app
from ai_inference.models import ModelKind, StubModelLoader, build_model_loader


def make_client() -> TestClient:
    return TestClient(create_app(Settings(model_loader="stub")))


def test_healthz_ok() -> None:
    with make_client() as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # All three pipeline models are (stub-)loaded at startup.
    assert set(body["models"]) == {"detector", "embedder", "liveness"}


def test_metrics_ok() -> None:
    with make_client() as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "inference_stage_latency_seconds" in resp.text
    assert "inference_model_loads_total" in resp.text


def test_stub_loader_never_needs_heavy_deps() -> None:
    loader = build_model_loader(Settings(model_loader="stub"))
    assert isinstance(loader, StubModelLoader)
    model = loader.load(ModelKind.EMBEDDER)
    assert model.version.startswith("stub-")
    assert loader.loaded_versions()[ModelKind.EMBEDDER] == model.version
