"""XC-04: /metrics exposes Prometheus exposition format and observes requests."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app(), raise_server_exceptions=False)


def test_metrics_endpoint_returns_prometheus_exposition() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_metrics_observes_prior_requests() -> None:
    client.get("/healthz")
    response = client.get("/metrics")
    body = response.text
    assert "backend_http_requests_total" in body
    assert 'route="/healthz"' in body
    assert "backend_http_request_duration_seconds" in body
