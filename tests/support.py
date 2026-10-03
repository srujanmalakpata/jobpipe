"""Helpers shared by tests (kept out of conftest so they can be imported normally)."""

from __future__ import annotations

from jobpipe.paths import FIXTURES_DIR

FIXTURE_DATES = ["2026-08-03", "2026-08-10", "2026-08-17", "2026-08-24", "2026-08-31", "2026-09-07"]


def fixture_body(snapshot: str, source: str, board: str) -> bytes:
    """A committed (synthetic) provider response, as the API would have returned it."""
    return (FIXTURES_DIR / snapshot / source / f"{board}.json").read_bytes()
