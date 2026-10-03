"""A small, polite HTTP client for public job-board APIs.

Requests are rate-limited per host, then use cached ``ETag`` / ``Last-Modified`` validators
to reuse the stored payload on a 304. The rate limit is one request per
``min_interval_seconds``. Responses with 429/5xx and transport errors are retried with
capped exponential backoff plus jitter. ``Retry-After`` (delta-seconds form, capped at
300 s) sets a floor on the delay. Other 4xx and other httpx errors, including redirect
loops and undecodable bodies, fail fast as a ``FetchError``.

Time, sleeping and randomness are injected so tests run instantly and deterministically.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from jobpipe import __version__
from jobpipe.config import FetchPolicy

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 300.0
USER_AGENT = f"jobpipe/{__version__} (analytics project; public postings only)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int  # 200, or 304 when the cached body was reused
    body: bytes
    attempts: int

    @property
    def not_modified(self) -> bool:
        return self.status == 304


class FetchError(RuntimeError):
    """The request failed permanently (non-retryable status or retries exhausted)."""

    def __init__(self, url: str, message: str, *, status: int | None, attempts: int):
        super().__init__(f"{url}: {message}")
        self.url = url
        self.status = status
        self.attempts = attempts


@dataclass(frozen=True)
class CachedResponse:
    etag: str | None
    last_modified: str | None
    body: bytes


class ResponseCache:
    """On-disk validator cache: one metadata JSON + one body file per URL."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _paths(self, url: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(url.encode()).hexdigest()[:32]
        return self.directory / f"{digest}.meta.json", self.directory / f"{digest}.body"

    def get(self, url: str) -> CachedResponse | None:
        meta_path, body_path = self._paths(url)
        if not (meta_path.exists() and body_path.exists()):
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return CachedResponse(meta.get("etag"), meta.get("last_modified"), body_path.read_bytes())

    def put(self, url: str, response: CachedResponse) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        meta_path, body_path = self._paths(url)
        _atomic_write(body_path, response.body)
        meta = {"url": url, "etag": response.etag, "last_modified": response.last_modified}
        _atomic_write(meta_path, json.dumps(meta, indent=2).encode())


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header (delta-seconds form only; HTTP-dates are ignored)."""
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return max(0.0, min(seconds, MAX_RETRY_AFTER_SECONDS))


class PoliteClient:
    def __init__(
        self,
        policy: FetchPolicy,
        *,
        transport: httpx.BaseTransport | None = None,
        cache: ResponseCache | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
    ):
        self.policy = policy
        self.cache = cache
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter
        self._last_request_at: dict[str, float] = {}
        self._http = httpx.Client(
            transport=transport,
            timeout=policy.timeout_seconds,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- politeness -----------------------------------------------------------------------

    def _wait_for_slot(self, host: str) -> None:
        last = self._last_request_at.get(host)
        if last is not None:
            remaining = self.policy.min_interval_seconds - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request_at[host] = self._clock()

    def backoff_delay(self, attempt: int, retry_after: float | None = None) -> float:
        """Delay before retry number ``attempt`` (1-based): capped exponential, equal jitter.

        ``retry_after`` is a floor, not an override: the delay is the larger of the two."""
        exp = min(
            self.policy.backoff_cap_seconds,
            self.policy.backoff_base_seconds * 2 ** (attempt - 1),
        )
        delay = exp / 2 + self._jitter() * exp / 2
        return max(delay, retry_after) if retry_after is not None else delay

    # -- request --------------------------------------------------------------------------

    def get(self, url: str) -> FetchResult:
        host = urlsplit(url).netloc
        cached = self.cache.get(url) if self.cache else None
        headers: dict[str, str] = {}
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

        last_error = "no attempt made"
        last_status: int | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            self._wait_for_slot(host)
            retry_after: float | None = None
            try:
                response = self._http.get(url, headers=headers)
            except httpx.TransportError as exc:
                last_error, last_status = f"{type(exc).__name__}: {exc}", None
            except httpx.HTTPError as exc:
                # TooManyRedirects, DecodingError, ...: retrying will not help.
                raise FetchError(
                    url, f"{type(exc).__name__}: {exc}", status=None, attempts=attempt
                ) from exc
            else:
                if response.status_code == 304 and cached is not None:
                    return FetchResult(url, 304, cached.body, attempt)
                if response.status_code == 200:
                    self._remember(url, response)
                    return FetchResult(url, 200, response.content, attempt)
                last_status = response.status_code
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in RETRYABLE_STATUS:
                    raise FetchError(url, last_error, status=last_status, attempts=attempt)
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
            if attempt < self.policy.max_attempts:
                self._sleep(self.backoff_delay(attempt, retry_after))
        raise FetchError(
            url,
            f"gave up after {self.policy.max_attempts} attempts ({last_error})",
            status=last_status,
            attempts=self.policy.max_attempts,
        )

    def _remember(self, url: str, response: httpx.Response) -> None:
        if self.cache is None:
            return
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")
        if etag or last_modified:
            self.cache.put(url, CachedResponse(etag, last_modified, response.content))
