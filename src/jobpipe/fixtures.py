"""Serve committed, synthetic API responses through the real HTTP stack.

Fixture mode does not bypass the client: requests go through ``PoliteClient`` exactly as in
live mode, but an ``httpx`` transport answers them from ``fixtures/responses/<date>/``:

    <date>/<source>/<board>.json    -> 200 with that body
    <date>/<source>/<board>.status  -> that HTTP status (e.g. 500) with an empty JSON body
    (neither)                       -> 404, like an unknown board
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from jobpipe.config import BoardConfig
from jobpipe.sources import SOURCES


class FixtureTransport(httpx.BaseTransport):
    def __init__(self, snapshot_dir: Path, boards: tuple[BoardConfig, ...]):
        self.snapshot_dir = Path(snapshot_dir)
        self._routes = {SOURCES[b.source].url(b.board): b for b in boards}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        board = self._routes.get(str(request.url))
        if board is None:
            return httpx.Response(404, json={"error": "unknown fixture url"}, request=request)
        base = self.snapshot_dir / board.source / board.board
        status_file = base.with_suffix(".status")
        if status_file.exists():
            status = int(status_file.read_text().strip())
            return httpx.Response(status, json={"error": "fixture status"}, request=request)
        body_file = base.with_suffix(".json")
        if not body_file.exists():
            return httpx.Response(404, json={"error": "Document not found"}, request=request)
        return httpx.Response(
            200,
            content=body_file.read_bytes(),
            headers={"Content-Type": "application/json"},
            request=request,
        )


def fixture_dates(fixtures_dir: Path) -> list[date]:
    """Snapshot dates available under ``fixtures_dir`` (directories named YYYY-MM-DD)."""
    out = []
    for child in Path(fixtures_dir).iterdir():
        if child.is_dir():
            try:
                out.append(date.fromisoformat(child.name))
            except ValueError:
                continue
    return sorted(out)
