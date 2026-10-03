"""Greenhouse Job Board API (public, unauthenticated GET)."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jobpipe.contracts import EnvelopeError, GreenhouseEnvelope, GreenhouseJob
from jobpipe.sources.base import Source


def _unwrap(decoded: Any) -> list[Any]:
    try:
        return GreenhouseEnvelope.model_validate(decoded).jobs
    except ValidationError as exc:
        raise EnvelopeError(
            f"greenhouse: unexpected envelope ({exc.error_count()} errors)"
        ) from exc


GREENHOUSE = Source(
    name="greenhouse",
    url_template="https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
    unwrap=_unwrap,
    record_model=GreenhouseJob,
)
