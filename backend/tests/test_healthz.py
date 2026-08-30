"""Smoke tests: /healthz and RFC 9457 problem+json error shape."""

from fastapi.testclient import TestClient

from app.main import create_app

client = TestClient(create_app(), raise_server_exceptions=False)


def test_healthz_returns_200_ok() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "frac-backend"


def test_unknown_route_returns_problem_json() -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == 404
    assert body["title"] == "Not Found"
    assert body["instance"] == "/does-not-exist"
