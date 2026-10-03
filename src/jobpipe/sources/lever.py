"""Lever Postings API (public, unauthenticated GET). The body is a bare JSON array."""

from __future__ import annotations

from typing import Any

from jobpipe.contracts import EnvelopeError, LeverPosting
from jobpipe.sources.base import Source


def _unwrap(decoded: Any) -> list[Any]:
    if not isinstance(decoded, list):
        # Lever answers unknown companies with {"ok": false, "error": "Document not found"}.
        raise EnvelopeError(f"lever: expected a JSON array, got {type(decoded).__name__}")
    return decoded


LEVER = Source(
    name="lever",
    url_template="https://api.lever.co/v0/postings/{board}?mode=json",
    unwrap=_unwrap,
    record_model=LeverPosting,
)
