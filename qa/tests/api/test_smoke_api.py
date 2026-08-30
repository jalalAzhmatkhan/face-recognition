"""Smoke test API — butuh service hidup, ditandai marker `live` (skip by default)."""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.api, pytest.mark.live]


def test_backend_healthz(backend_client: httpx.Client) -> None:
    """Backend menjawab healthcheck (BE-01)."""
    response = backend_client.get("/healthz")
    assert response.status_code == 200


def test_inference_healthz(inference_client: httpx.Client) -> None:
    """AI inference service menjawab healthcheck (IN-01)."""
    response = inference_client.get("/healthz")
    assert response.status_code == 200
