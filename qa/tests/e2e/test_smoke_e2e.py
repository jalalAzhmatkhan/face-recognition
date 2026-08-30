"""Smoke test E2E (Playwright) — butuh frontend hidup, marker `live` (skip by default).

Prasyarat: `uv run playwright install chromium` (lihat qa/README.md).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

pytestmark = [pytest.mark.e2e, pytest.mark.live]


def test_frontend_loads(page: Page, frontend_base_url: str) -> None:
    """Frontend shell termuat tanpa error navigasi (FE-01)."""
    response = page.goto(frontend_base_url)
    assert response is not None
    assert response.ok
