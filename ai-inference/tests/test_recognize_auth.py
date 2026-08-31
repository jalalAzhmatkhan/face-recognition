"""Endpoint-level tests for `/recognize` device auth (IN-02, NFR-SEC-04).

Uses `app.dependency_overrides` to replace `get_current_device_id` outright
-- no real DB/psycopg/ml extra needed, matches the FastAPI-recommended
testing pattern the auth dependency was deliberately designed for (see
`ai_inference/auth_dependency.py` docstring). Must pass on base CI (no `ml`
extra): with no override, the real dependency short-circuits to 401 before
ever touching `settings.db_dsn`/`gallery.get_connection`, since these tests
send no Authorization header at all.
"""

from fastapi.testclient import TestClient

from ai_inference.auth_dependency import get_current_device_id
from ai_inference.config import Settings
from ai_inference.main import create_app

VALID_FRAME = "not-a-real-base64-frame-but-unreachable-before-auth"


def make_client() -> TestClient:
    return TestClient(create_app(Settings(model_loader="stub")))


def test_recognize_without_bearer_token_is_401() -> None:
    with make_client() as client:
        resp = client.post("/recognize", json={"frames_base64": [VALID_FRAME]})
    assert resp.status_code == 401


def test_recognize_with_malformed_bearer_token_is_401() -> None:
    with make_client() as client:
        resp = client.post(
            "/recognize",
            json={"frames_base64": [VALID_FRAME]},
            headers={"Authorization": "Bearer not-a-valid-device-token"},
        )
    assert resp.status_code == 401


def test_recognize_auth_override_lets_request_past_auth() -> None:
    """With auth overridden to succeed, the request should fail LATER in the
    pipeline (no real embedder/DB configured for the stub loader) rather
    than being rejected for authentication -- proving the dependency is
    wired in without hardcoding a direct call that would bypass overrides."""
    app = create_app(Settings(model_loader="stub"))
    app.dependency_overrides[get_current_device_id] = lambda: "device-under-test"
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/recognize",
                json={"frames_base64": [VALID_FRAME]},
                headers={"Authorization": "Bearer irrelevant-because-overridden"},
            )
    finally:
        app.dependency_overrides.clear()
    # Stub loader has no real embedder configured -> 500 from the existing
    # "requires a real embedder" guard, NOT 401/403 -- i.e. auth passed.
    assert resp.status_code == 500
    assert resp.status_code not in (401, 403)
