"""Smoke test security — deny-by-default (NFR-SEC-04). Marker `live` (skip by default)."""

from __future__ import annotations

import httpx
import pytest

pytestmark = [pytest.mark.security, pytest.mark.live]


def test_users_endpoint_requires_auth(backend_client: httpx.Client) -> None:
    """Endpoint terlindungi tanpa kredensial harus ditolak (401/403), bukan 200."""
    response = backend_client.get("/users")
    assert response.status_code in (401, 403)
