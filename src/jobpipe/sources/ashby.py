"""Ashby public job-board API (public, unauthenticated GET)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jobpipe.contracts import AshbyEnvelope, AshbyJob, EnvelopeError
from jobpipe.sources.base import Source


def _unwrap(decoded: Any) -> list[Any]:
    try:
        return AshbyEnvelope.model_validate(decoded).jobs
    except ValidationError as exc:
        raise EnvelopeError(f"ashby: unexpected envelope ({exc.error_count()} errors)") from exc


ASHBY = Source(
    name="ashby",
    url_template="https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true",
    unwrap=_unwrap,
    record_model=AshbyJob,
)
