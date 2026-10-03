"""Provider adapters against recorded (synthetic) responses: envelopes and the contract."""

from __future__ import annotations

import json

import pytest

from jobpipe.contracts import EnvelopeError
from jobpipe.sources import SOURCES
from support import fixture_body


def test_urls_match_public_endpoints():
    assert SOURCES["greenhouse"].url("acme") == (
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
    )
    assert SOURCES["lever"].url("acme") == "https://api.lever.co/v0/postings/acme?mode=json"
    assert (
        SOURCES["ashby"]
        .url("acme")
        .startswith("https://api.ashbyhq.com/posting-api/job-board/acme")
    )


@pytest.mark.parametrize(
    ("source", "board"),
    [("greenhouse", "mapleledger"), ("lever", "auroralabs"), ("ashby", "glaciergames")],
)
def test_recorded_responses_parse_cleanly(source, board):
    body = fixture_body("2026-08-03", source, board)
    decoded = json.loads(body)
    items = decoded if isinstance(decoded, list) else decoded["jobs"]
    parsed = SOURCES[source].parse(body)
    assert parsed.rejects == []
    assert len(parsed.postings) == len(items)
    assert all(isinstance(pid, str) and pid for pid, _ in parsed.postings)
    # payloads are kept verbatim for bronze
    assert parsed.postings[0][1] == items[0]


def test_blank_title_is_rejected_not_fatal():
    parsed = SOURCES["ashby"].parse(fixture_body("2026-08-10", "ashby", "glaciergames"))
    assert len(parsed.rejects) == 1
    reject = parsed.rejects[0]
    assert reject.posting_id == "00000000-0000-4000-8000-00000000bad1"
    assert "title" in reject.error
    assert 0 < parsed.reject_ratio < 0.2


def test_duplicates_within_a_response_are_kept_for_staging_to_handle():
    parsed = SOURCES["greenhouse"].parse(
        fixture_body("2026-08-17", "greenhouse", "northwindrobotics")
    )
    ids = [pid for pid, _ in parsed.postings]
    assert len(ids) == len(set(ids)) + 1


def test_record_without_id_or_with_wrong_types_is_rejected():
    body = json.dumps(
        {
            "jobs": [
                {"title": "No id", "updated_at": "2026-08-01T00:00:00Z", "absolute_url": "u"},
                {"id": 7, "title": "Bad date", "updated_at": "yesterday", "absolute_url": "u"},
                "not an object",
                {
                    "id": 8,
                    "title": "Fine",
                    "updated_at": "2026-08-01T00:00:00Z",
                    "absolute_url": "u",
                },
            ]
        }
    ).encode()
    parsed = SOURCES["greenhouse"].parse(body)
    assert [pid for pid, _ in parsed.postings] == ["8"]
    assert [r.posting_id for r in parsed.rejects] == [None, "7", None]
    assert "updated_at" in parsed.rejects[1].error


@pytest.mark.parametrize(
    ("source", "body"),
    [
        ("lever", b'{"ok": false, "error": "Document not found"}'),
        ("greenhouse", b'{"status": 404}'),
        ("ashby", b"[]"),
        ("greenhouse", b"<html>maintenance</html>"),
    ],
)
def test_wrong_envelope_raises(source, body):
    with pytest.raises(EnvelopeError):
        SOURCES[source].parse(body)


@pytest.mark.parametrize(
    ("source", "body"),
    [
        (
            "greenhouse",
            {
                "jobs": [
                    {
                        "id": 1,
                        "title": "  ",
                        "updated_at": "2026-08-01T00:00:00Z",
                        "absolute_url": "https://example.invalid/1",
                    }
                ]
            },
        ),
        ("lever", [{"id": "a", "text": "\t", "createdAt": 1, "hostedUrl": "https://x.invalid"}]),
    ],
)
def test_whitespace_title_is_rejected_for_every_provider(source, body):
    parsed = SOURCES[source].parse(json.dumps(body).encode())
    assert parsed.postings == []
    assert "blank" in parsed.rejects[0].error


def test_listed_posting_with_blank_title_is_a_reject_with_its_id():
    """Scripted fixture: the Aurora ML posting is still listed on 08-31 but unparseable."""
    parsed = SOURCES["lever"].parse(fixture_body("2026-08-31", "lever", "auroralabs"))
    assert [r.posting_id for r in parsed.rejects] == ["34665405-180d-4b72-bbcb-2334675254e0"]
    assert parsed.reject_ratio < 0.2
