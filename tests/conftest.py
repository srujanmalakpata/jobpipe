from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from jobpipe.config import PipelineConfig, load_config
from jobpipe.paths import CONFIG_DIR, FIXTURES_DIR


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any test reaches for the real network transport."""

    def refuse(self, request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"network access attempted in tests: {request.url}")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture(scope="session")
def fixture_config() -> PipelineConfig:
    return load_config(CONFIG_DIR / "boards.fixtures.yaml")
