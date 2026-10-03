"""Bronze landing: Hive layout, atomic partition overwrite, failure never erases good data."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from jobpipe.bronze import STATUS_CONTRACT_FAILED, STATUS_FAILED, STATUS_OK, BronzeStore, Manifest
from jobpipe.sources.base import Reject

DAY = date(2026, 9, 7)
STAMP = datetime(2026, 9, 7, 12, tzinfo=UTC)


def manifest(status=STATUS_OK, count=2, rejects=0) -> Manifest:
    return Manifest(
        company="Acme",
        extracted_at=STAMP.isoformat(),
        status=status,
        fetch_mode="fixture",
        http_status=200 if status == STATUS_OK else 500,
        posting_count=count,
        reject_count=rejects,
        attempts=1,
        url="https://example.invalid",
    )


def land(store, postings, rejects=()):
    store.land_success(
        source="lever",
        board="acme",
        snapshot_date=DAY,
        extracted_at=STAMP,
        postings=postings,
        rejects=list(rejects),
        manifest=manifest(count=len(postings), rejects=len(rejects)),
    )


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_layout_is_hive_partitioned(tmp_path):
    store = BronzeStore(tmp_path)
    land(store, [("a", {"id": "a"}), ("b", {"id": "b"})])
    part = tmp_path / "postings/source=lever/board=acme/snapshot_date=2026-09-07/part-0.jsonl"
    rows = lines(part)
    assert [r["posting_id"] for r in rows] == ["a", "b"]
    assert rows[0] == {
        "company": "Acme",
        "extracted_at": "2026-09-07T12:00:00+00:00",
        "payload": {"id": "a"},
        "posting_id": "a",
    }
    assert store.read_manifest("lever", "acme", DAY).posting_count == 2
    assert store.fetch_modes() == {"fixture"}
    assert not list(tmp_path.rglob("*.tmp"))


def test_relanding_a_partition_replaces_it(tmp_path):
    store = BronzeStore(tmp_path)
    land(store, [("a", {"id": "a"})], [Reject(1, "x", "title: bad", {"id": "x"})])
    rejects = tmp_path / "rejects/source=lever/board=acme/snapshot_date=2026-09-07/rejects.jsonl"
    assert lines(rejects)[0]["error"] == "title: bad"

    land(store, [("b", {"id": "b"})])
    part = store.partition("postings", "lever", "acme", DAY) / "part-0.jsonl"
    assert [r["posting_id"] for r in lines(part)] == ["b"]
    assert not rejects.exists()


def test_failure_does_not_overwrite_a_successful_day(tmp_path):
    store = BronzeStore(tmp_path)
    land(store, [("a", {"id": "a"})])
    written = store.land_failure(
        source="lever", board="acme", snapshot_date=DAY, manifest=manifest(STATUS_FAILED, 0)
    )
    assert written is False
    assert store.read_manifest("lever", "acme", DAY).status == STATUS_OK


def test_failure_is_recorded_when_no_good_data_exists(tmp_path):
    store = BronzeStore(tmp_path)
    assert store.land_failure(
        source="lever", board="acme", snapshot_date=DAY, manifest=manifest(STATUS_FAILED, 0)
    )
    assert store.read_manifest("lever", "acme", DAY).status == STATUS_FAILED
    assert not (store.partition("postings", "lever", "acme", DAY) / "part-0.jsonl").exists()


def test_failure_keeps_rejects_and_raw_body_and_clears_stale_ones(tmp_path):
    store = BronzeStore(tmp_path)
    folder = store.partition("rejects", "lever", "acme", DAY)
    store.land_failure(
        source="lever",
        board="acme",
        snapshot_date=DAY,
        manifest=manifest(STATUS_CONTRACT_FAILED, 0, rejects=1),
        rejects=[Reject(0, "x", "text: must not be blank", {"id": "x"})],
        raw_body=b'{"unexpected": true}',
    )
    assert lines(folder / "rejects.jsonl")[0]["error"] == "text: must not be blank"
    assert (folder / "response.body").read_bytes() == b'{"unexpected": true}'

    # a later failure without diagnostics replaces them instead of leaving stale files
    store.land_failure(
        source="lever", board="acme", snapshot_date=DAY, manifest=manifest(STATUS_FAILED, 0)
    )
    assert not (folder / "rejects.jsonl").exists()
    assert not (folder / "response.body").exists()


def test_manifest_round_trips_rejected_ids_and_finds_previous_ok(tmp_path):
    store = BronzeStore(tmp_path)
    earlier = date(2026, 8, 31)
    store.land_success(
        source="lever",
        board="acme",
        snapshot_date=earlier,
        extracted_at=STAMP,
        postings=[("a", {"id": "a"})],
        rejects=[],
        manifest=Manifest(**{**manifest().__dict__, "rejected_posting_ids": ("z",)}),
    )
    store.land_failure(
        source="lever", board="acme", snapshot_date=DAY, manifest=manifest(STATUS_FAILED, 0)
    )
    assert store.read_manifest("lever", "acme", earlier).rejected_posting_ids == ("z",)
    assert store.previous_ok_manifest("lever", "acme", date(2026, 9, 14)).extracted_at == (
        STAMP.isoformat()
    )
    assert store.previous_ok_manifest("lever", "acme", earlier) is None


def test_content_hash_changes_with_content_not_with_relanding(tmp_path):
    store = BronzeStore(tmp_path)
    land(store, [("a", {"id": "a", "title": "Analyst"})])
    first = store.read_manifest("lever", "acme", DAY).content_hash
    land(store, [("a", {"id": "a", "title": "Analyst"})])
    assert store.read_manifest("lever", "acme", DAY).content_hash == first  # idempotent

    # same timestamp, same count, different content: the hash must differ
    land(store, [("a", {"id": "a", "title": "Senior Analyst"})])
    retitled = store.read_manifest("lever", "acme", DAY).content_hash
    land(store, [("b", {"id": "b", "title": "Analyst"})])
    swapped = store.read_manifest("lever", "acme", DAY).content_hash
    assert len({first, retitled, swapped}) == 3


def test_invalidate_keeps_evidence_and_marks_the_day_failed(tmp_path):
    store = BronzeStore(tmp_path)
    land(store, [("a", {"id": "a"}), ("b", {"id": "b"})])
    manifest = store.invalidate("lever", "acme", DAY, "truncated list")
    assert (manifest.status, manifest.posting_count, manifest.content_hash) == (
        STATUS_CONTRACT_FAILED,
        0,
        None,
    )
    assert "truncated list" in manifest.error and "2 postings" in manifest.error
    assert store.read_manifest("lever", "acme", DAY) == manifest
    assert not (store.partition("postings", "lever", "acme", DAY) / "part-0.jsonl").exists()
    evidence = store.partition("rejects", "lever", "acme", DAY) / "invalidated-postings.jsonl"
    assert [r["posting_id"] for r in lines(evidence)] == ["a", "b"]

    with pytest.raises(FileNotFoundError):
        store.invalidate("lever", "acme", date(2020, 1, 1), "nothing there")
