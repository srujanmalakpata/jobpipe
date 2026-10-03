"""Provider adapters. Each one knows a URL shape and a response contract, nothing else."""

from __future__ import annotations

from jobpipe.sources.ashby import ASHBY
from jobpipe.sources.base import ParsedResponse, Reject, Source
from jobpipe.sources.greenhouse import GREENHOUSE
from jobpipe.sources.lever import LEVER

SOURCES: dict[str, Source] = {s.name: s for s in (GREENHOUSE, LEVER, ASHBY)}

__all__ = ["SOURCES", "ParsedResponse", "Reject", "Source"]
