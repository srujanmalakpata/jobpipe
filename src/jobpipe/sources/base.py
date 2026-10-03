"""Shared adapter machinery: envelope unwrapping + per-record contract validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from jobpipe.contracts import EnvelopeError, validation_message

RawPosting = dict[str, Any]


@dataclass(frozen=True)
class Reject:
    """A posting that failed the contract; quarantined to bronze/rejects, never loaded."""

    index: int
    posting_id: str | None
    error: str
    payload: Any


@dataclass(frozen=True)
class ParsedResponse:
    postings: list[tuple[str, RawPosting]] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)

    @property
    def reject_ratio(self) -> float:
        total = len(self.postings) + len(self.rejects)
        return len(self.rejects) / total if total else 0.0


@dataclass(frozen=True)
class Source:
    """A public job-board provider.

    ``unwrap`` turns the decoded JSON body into the list of raw posting objects (raising
    EnvelopeError if the top-level shape is wrong); ``record_model`` is the per-posting contract.
    """

    name: str
    url_template: str
    unwrap: Callable[[Any], list[Any]]
    record_model: type[BaseModel]

    def url(self, board: str) -> str:
        return self.url_template.format(board=board)

    def parse(self, body: bytes) -> ParsedResponse:
        try:
            decoded = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EnvelopeError(f"{self.name}: response is not JSON ({exc})") from exc
        items = self.unwrap(decoded)

        postings: list[tuple[str, RawPosting]] = []
        rejects: list[Reject] = []
        for index, item in enumerate(items):
            raw_id = item.get("id") if isinstance(item, dict) else None
            posting_id = None if raw_id is None else str(raw_id)
            try:
                if not isinstance(item, dict):
                    raise TypeError(f"expected an object, got {type(item).__name__}")
                self.record_model.model_validate(item)
            except (ValidationError, TypeError) as exc:
                message = validation_message(exc) if isinstance(exc, ValidationError) else str(exc)
                rejects.append(Reject(index, posting_id, message, item))
                continue
            assert posting_id is not None  # guaranteed by the contract's required id
            # Duplicates are kept: bronze stays a faithful copy and staging deduplicates.
            postings.append((posting_id, item))
        return ParsedResponse(postings=postings, rejects=rejects)
