"""Sanity test murni: memastikan harness & fixture konfigurasi bekerja tanpa service hidup."""

from __future__ import annotations

import pytest

from conftest import QASettings


def test_default_settings_valid() -> None:
    """QASettings punya default yang valid tanpa env apa pun."""
    settings = QASettings()
    assert str(settings.backend_base_url).startswith("http://localhost:8000")
    assert str(settings.frontend_base_url).startswith("http://localhost:5173")
    assert str(settings.inference_base_url).startswith("http://localhost:8001")
    assert settings.http_timeout_s > 0


def test_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Base URL bisa dioverride via environment variable QA_*."""
    monkeypatch.setenv("QA_BACKEND_BASE_URL", "http://backend.internal:9000")
    monkeypatch.setenv("QA_HTTP_TIMEOUT_S", "3.5")
    settings = QASettings()
    assert str(settings.backend_base_url).startswith("http://backend.internal:9000")
    assert settings.http_timeout_s == 3.5


def test_base_url_fixtures_no_trailing_slash(
    backend_base_url: str, frontend_base_url: str, inference_base_url: str
) -> None:
    """Fixture base-URL menghasilkan string tanpa trailing slash."""
    for url in (backend_base_url, frontend_base_url, inference_base_url):
        assert url.startswith("http")
        assert not url.endswith("/")
