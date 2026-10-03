"""Bronze landing zone: raw provider payloads as Hive-partitioned JSONL.

Layout (partition columns are encoded in the path, not repeated in each line)::

    <bronze>/postings/source=<s>/board=<b>/snapshot_date=<YYYY-MM-DD>/part-0.jsonl
    <bronze>/manifests/source=<s>/board=<b>/snapshot_date=<YYYY-MM-DD>/manifest.jsonl
    <bronze>/rejects/source=<s>/board=<b>/snapshot_date=<YYYY-MM-DD>/rejects.jsonl
    <bronze>/rejects/source=<s>/board=<b>/snapshot_date=<YYYY-MM-DD>/response.body

``rejects.jsonl`` holds every record that failed the contract, with its field errors; it is
written for successful snapshots *and* for ``contract_failed`` ones, so the errors behind a
failed board are always on disk. ``response.body`` keeps the raw response when the whole
envelope was unusable (not JSON, wrong top-level shape).

One (source, board, snapshot_date) partition is the unit of idempotency: landing it again
atomically replaces the previous files, so re-running a day never duplicates rows. Each file
is replaced atomically, but a partition is several files: postings are written before the
manifest, so a crash in between leaves new postings next to the old manifest. The dbt test
``assert_bronze_reconciles_with_manifests`` flags that state; re-running the day repairs it.

The manifest is what lets the warehouse tell "posting disappeared" from "we failed to look":
a posting is only considered closed when a later manifest for its board says ``status=ok``.
It also lists the ids of records that failed the contract (``rejected_posting_ids``): those
postings were still listed, just unparseable, so they must not count as closed either.

``content_hash`` (sha256 of the landed posting lines and the rejected ids) is what the
incremental dbt models compare to decide whether a partition changed. ``extracted_at`` alone
is not enough: fixture runs pin it to noon of the snapshot date, so an edited fixture would
otherwise be re-landed with the same timestamp and never reprocessed.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jobpipe.sources.base import RawPosting, Reject

STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_CONTRACT_FAILED = "contract_failed"


@dataclass(frozen=True)
class Manifest:
    company: str
    extracted_at: str  # ISO-8601 UTC
    status: str
    fetch_mode: str  # "live" | "fixture"
    http_status: int | None
    posting_count: int
    reject_count: int
    attempts: int
    url: str
    error: str | None = None
    rejected_posting_ids: tuple[str, ...] = ()
    content_hash: str | None = None  # set for ok snapshots, see the module docstring


def content_hash(posting_lines: list[str], rejected_posting_ids: tuple[str, ...]) -> str:
    """Fingerprint of what an ok snapshot contributes to the warehouse."""
    digest = hashlib.sha256()
    for line in posting_lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    digest.update(b"rejected:" + ",".join(rejected_posting_ids).encode("utf-8"))
    return digest.hexdigest()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line)
            fh.write("\n")
    os.replace(tmp, path)


class BronzeStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def partition(self, kind: str, source: str, board: str, snapshot_date: date) -> Path:
        return (
            self.root
            / kind
            / f"source={source}"
            / f"board={board}"
            / f"snapshot_date={snapshot_date.isoformat()}"
        )

    def manifest_path(self, source: str, board: str, snapshot_date: date) -> Path:
        return self.partition("manifests", source, board, snapshot_date) / "manifest.jsonl"

    def read_manifest(self, source: str, board: str, snapshot_date: date) -> Manifest | None:
        path = self.manifest_path(source, board, snapshot_date)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8").strip())
        data["rejected_posting_ids"] = tuple(data.get("rejected_posting_ids") or ())
        return Manifest(**data)

    def previous_ok_manifest(self, source: str, board: str, before: date) -> Manifest | None:
        """The board's most recent successful manifest strictly before ``before``."""
        board_dir = self.root / "manifests" / f"source={source}" / f"board={board}"
        days = sorted(
            (
                date.fromisoformat(p.name.split("=", 1)[1])
                for p in board_dir.glob("snapshot_date=*")
            ),
            reverse=True,
        )
        for day in days:
            if day >= before:
                continue
            manifest = self.read_manifest(source, board, day)
            if manifest is not None and manifest.status == STATUS_OK:
                return manifest
        return None

    def land_success(
        self,
        *,
        source: str,
        board: str,
        snapshot_date: date,
        extracted_at: datetime,
        postings: list[tuple[str, RawPosting]],
        rejects: list[Reject],
        manifest: Manifest,
    ) -> None:
        """Replace the partition's postings, rejects and manifest (manifest written last).

        The manifest's ``content_hash`` is computed here from the exact lines written."""
        stamp = extracted_at.isoformat()
        posting_lines = [
            _dumps(
                {
                    "company": manifest.company,
                    "extracted_at": stamp,
                    "posting_id": posting_id,
                    "payload": payload,
                }
            )
            for posting_id, payload in postings
        ]
        _atomic_write_lines(
            self.partition("postings", source, board, snapshot_date) / "part-0.jsonl",
            posting_lines,
        )
        self._write_diagnostics(source, board, snapshot_date, stamp, rejects, raw_body=None)
        manifest = replace(
            manifest, content_hash=content_hash(posting_lines, manifest.rejected_posting_ids)
        )
        self._write_manifest(source, board, snapshot_date, manifest)

    def land_failure(
        self,
        *,
        source: str,
        board: str,
        snapshot_date: date,
        manifest: Manifest,
        rejects: list[Reject] | None = None,
        raw_body: bytes | None = None,
    ) -> bool:
        """Record a failed fetch, keeping whatever explains it (contract rejects with their
        field errors, or the raw body of an unusable response).

        Returns False (and writes nothing) if a successful snapshot for the same day already
        exists: a later failure must not erase good data."""
        existing = self.read_manifest(source, board, snapshot_date)
        if existing is not None and existing.status == STATUS_OK:
            return False
        stale = self.partition("postings", source, board, snapshot_date) / "part-0.jsonl"
        if stale.exists():
            stale.unlink()
        self._write_diagnostics(
            source, board, snapshot_date, manifest.extracted_at, rejects or [], raw_body
        )
        self._write_manifest(source, board, snapshot_date, manifest)
        return True

    def _write_diagnostics(
        self,
        source: str,
        board: str,
        snapshot_date: date,
        stamp: str,
        rejects: list[Reject],
        raw_body: bytes | None,
    ) -> None:
        """Replace the partition's rejects file and raw-body file (removing stale ones)."""
        folder = self.partition("rejects", source, board, snapshot_date)
        rejects_path = folder / "rejects.jsonl"
        if rejects:
            _atomic_write_lines(
                rejects_path,
                [
                    _dumps(
                        {
                            "extracted_at": stamp,
                            "index": r.index,
                            "posting_id": r.posting_id,
                            "error": r.error,
                            "payload": r.payload,
                        }
                    )
                    for r in rejects
                ],
            )
        elif rejects_path.exists():
            rejects_path.unlink()
        body_path = folder / "response.body"
        if raw_body is not None:
            folder.mkdir(parents=True, exist_ok=True)
            tmp = body_path.with_name(body_path.name + ".tmp")
            tmp.write_bytes(raw_body)
            os.replace(tmp, body_path)
        elif body_path.exists():
            body_path.unlink()

    def _write_manifest(
        self, source: str, board: str, snapshot_date: date, manifest: Manifest
    ) -> None:
        _atomic_write_lines(
            self.manifest_path(source, board, snapshot_date), [_dumps(asdict(manifest))]
        )

    def fetch_modes(self) -> set[str]:
        """Every fetch mode ("live", "fixture") that has landed anything in this lake."""
        return {
            json.loads(path.read_text(encoding="utf-8"))["fetch_mode"]
            for path in (self.root / "manifests").glob("*/*/*/manifest.jsonl")
        }

    def invalidate(self, source: str, board: str, snapshot_date: date, reason: str) -> Manifest:
        """Operator override: mark a landed snapshot as untrustworthy after the fact.

        Used when an ``ok`` snapshot turns out to be partial (e.g. a truncated list that
        slipped under the drop guard). The postings file is moved next to the rejects as
        ``invalidated-postings.jsonl`` (evidence is kept, nothing is deleted) and the
        manifest becomes ``contract_failed``, so the warehouse stops using that day: it can
        no longer close postings, and the next ``dbt build`` recomputes the board."""
        current = self.read_manifest(source, board, snapshot_date)
        if current is None:
            raise FileNotFoundError(f"no snapshot for {source}:{board} on {snapshot_date}")
        postings = self.partition("postings", source, board, snapshot_date) / "part-0.jsonl"
        if postings.exists():
            evidence = self.partition("rejects", source, board, snapshot_date)
            evidence.mkdir(parents=True, exist_ok=True)
            os.replace(postings, evidence / "invalidated-postings.jsonl")
        manifest = replace(
            current,
            status=STATUS_CONTRACT_FAILED,
            posting_count=0,
            content_hash=None,
            error=(
                f"invalidated by operator ({current.status}, {current.posting_count} postings "
                f"landed): {reason}"
            ),
        )
        self._write_manifest(source, board, snapshot_date, manifest)
        return manifest
