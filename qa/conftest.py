"""Konfigurasi global QA harness.

Base URL tiap service dikonfigurasi via environment variable sehingga harness
bisa jalan di dev lokal, Docker Compose, maupun CI tanpa perubahan kode:

- QA_BACKEND_BASE_URL    (default: http://localhost:8000)
- QA_FRONTEND_BASE_URL   (default: http://localhost:5173)
- QA_INFERENCE_BASE_URL  (default: http://localhost:8001)
- QA_HTTP_TIMEOUT_S      (default: 10.0)
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from pydantic import HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class QASettings(BaseSettings):
    """Konfigurasi base-URL service, dibaca dari env dengan prefix QA_."""

    model_config = SettingsConfigDict(env_prefix="QA_", extra="ignore")

    backend_base_url: HttpUrl = HttpUrl("http://localhost:8000")
    frontend_base_url: HttpUrl = HttpUrl("http://localhost:5173")
    inference_base_url: HttpUrl = HttpUrl("http://localhost:8001")
    http_timeout_s: float = 10.0


@pytest.fixture(scope="session")
def qa_settings() -> QASettings:
    """Konfigurasi QA yang tervalidasi (Pydantic) dari environment."""
    return QASettings()


@pytest.fixture(scope="session")
def backend_base_url(qa_settings: QASettings) -> str:
    return str(qa_settings.backend_base_url).rstrip("/")


@pytest.fixture(scope="session")
def frontend_base_url(qa_settings: QASettings) -> str:
    return str(qa_settings.frontend_base_url).rstrip("/")


@pytest.fixture(scope="session")
def inference_base_url(qa_settings: QASettings) -> str:
    return str(qa_settings.inference_base_url).rstrip("/")


@pytest.fixture()
def backend_client(
    backend_base_url: str, qa_settings: QASettings
) -> Iterator[httpx.Client]:
    """HTTP client menuju service backend."""
    with httpx.Client(
        base_url=backend_base_url, timeout=qa_settings.http_timeout_s
    ) as client:
        yield client


@pytest.fixture()
def inference_client(
    inference_base_url: str, qa_settings: QASettings
) -> Iterator[httpx.Client]:
    """HTTP client menuju service ai-inference."""
    with httpx.Client(
        base_url=inference_base_url, timeout=qa_settings.http_timeout_s
    ) as client:
        yield client
