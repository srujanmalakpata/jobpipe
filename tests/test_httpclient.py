"""PoliteClient behaviour: retries, backoff, Retry-After, conditional requests, rate limit."""

from __future__ import annotations

import httpx
import pytest

from jobpipe.config import FetchPolicy
from jobpipe.httpclient import FetchError, PoliteClient, ResponseCache, parse_retry_after

URL = "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"


class FakeTime:
    """Monotonic clock that only advances when the client sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


def make_client(handler, *, policy=None, cache=None, fake=None) -> tuple[PoliteClient, FakeTime]:
    fake = fake or FakeTime()
    client = PoliteClient(
        policy or FetchPolicy(min_interval_seconds=0.0, max_attempts=4),
        transport=httpx.MockTransport(handler),
        cache=cache,
        sleep=fake.sleep,
        clock=fake.clock,
        jitter=lambda: 0.5,  # equal-jitter midpoint: delay = 0.75 * exp
    )
    return client, fake


def scripted(*responses):
    """Handler returning the given responses in order; records requests."""
    queue = list(responses)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


def test_success_first_try_sends_user_agent():
    handler = scripted(httpx.Response(200, json={"jobs": []}))
    client, fake = make_client(handler)
    result = client.get(URL)
    assert (result.status, result.attempts, result.body) == (200, 1, b'{"jobs":[]}')
    assert fake.sleeps == []
    assert "jobpipe" in handler.seen[0].headers["User-Agent"]


def test_retries_5xx_with_exponential_backoff():
    handler = scripted(httpx.Response(503), httpx.Response(502), httpx.Response(200, json=[]))
    client, fake = make_client(handler)
    result = client.get(URL)
    assert result.attempts == 3
    # base 1s: exp = 1, 2 -> with jitter 0.5 the delay is 0.75 * exp
    assert fake.sleeps == [0.75, 1.5]


def test_retry_after_header_is_honoured():
    handler = scripted(
        httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json=[])
    )
    client, fake = make_client(handler)
    assert client.get(URL).attempts == 2
    assert fake.sleeps == [7.0]


def test_transport_errors_are_retried():
    handler = scripted(httpx.ConnectTimeout("slow"), httpx.Response(200, json=[]))
    client, _ = make_client(handler)
    assert client.get(URL).attempts == 2


def test_non_retryable_status_fails_fast():
    handler = scripted(httpx.Response(404, json={"error": "nope"}))
    client, fake = make_client(handler)
    with pytest.raises(FetchError) as info:
        client.get(URL)
    assert (info.value.status, info.value.attempts) == (404, 1)
    assert fake.sleeps == []


def test_gives_up_after_max_attempts():
    handler = scripted(*[httpx.Response(500)] * 3)
    client, fake = make_client(handler, policy=FetchPolicy(min_interval_seconds=0, max_attempts=3))
    with pytest.raises(FetchError, match="gave up after 3 attempts") as info:
        client.get(URL)
    assert info.value.status == 500
    assert len(fake.sleeps) == 2  # no pointless sleep after the final attempt


def test_backoff_is_capped():
    client, _ = make_client(scripted(), policy=FetchPolicy(backoff_cap_seconds=5.0))
    assert client.backoff_delay(10) == pytest.approx(3.75)  # 0.75 * cap


def test_conditional_request_reuses_cached_body_on_304(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    body = b'{"jobs":[{"id":1}]}'
    first = scripted(httpx.Response(200, content=body, headers={"ETag": '"v1"'}))
    client, _ = make_client(first, cache=cache)
    assert client.get(URL).status == 200
    assert "If-None-Match" not in first.seen[0].headers

    second = scripted(httpx.Response(304))
    client, _ = make_client(second, cache=cache)
    result = client.get(URL)
    assert second.seen[0].headers["If-None-Match"] == '"v1"'
    assert (result.status, result.body, result.not_modified) == (304, body, True)


def test_last_modified_validator_is_replayed(tmp_path):
    cache = ResponseCache(tmp_path / "cache")
    stamp = "Mon, 07 Sep 2026 10:00:00 GMT"
    client, _ = make_client(
        scripted(httpx.Response(200, json=[], headers={"Last-Modified": stamp})), cache=cache
    )
    client.get(URL)
    handler = scripted(httpx.Response(200, json=[]))
    client, _ = make_client(handler, cache=cache)
    client.get(URL)
    assert handler.seen[0].headers["If-Modified-Since"] == stamp


def test_rate_limit_spaces_requests_to_the_same_host():
    handler = scripted(*[httpx.Response(200, json=[])] * 3)
    client, fake = make_client(handler, policy=FetchPolicy(min_interval_seconds=2.0))
    client.get(URL)
    fake.now += 0.5  # half a second of "work" between calls
    client.get(URL)
    client.get("https://api.lever.co/v0/postings/acme?mode=json")  # other host: no wait
    assert fake.sleeps == [1.5]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5", 5.0),
        (" 0 ", 0.0),
        ("100000", 300.0),
        ("Wed, 21 Oct 2026 07:28:00 GMT", None),
        (None, None),
    ],
)
def test_parse_retry_after(value, expected):
    assert parse_retry_after(value) == expected


def test_non_transport_httpx_error_fails_fast_without_retry():
    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": str(request.url)})

    client, fake = make_client(loop)
    with pytest.raises(FetchError, match="TooManyRedirects") as info:
        client.get(URL)
    assert info.value.attempts == 1
    assert fake.sleeps == []
