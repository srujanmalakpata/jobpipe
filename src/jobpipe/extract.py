"""Extract step: fetch each configured board once per snapshot and land it in bronze."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from pathlib import Path

import httpx

from jobpipe.bronze import (
    STATUS_CONTRACT_FAILED,
    STATUS_FAILED,
    STATUS_OK,
    BronzeStore,
    Manifest,
)
from jobpipe.config import BoardConfig, FetchPolicy, PipelineConfig
from jobpipe.contracts import EnvelopeError
from jobpipe.fixtures import FixtureTransport, fixture_dates
from jobpipe.httpclient import FetchError, PoliteClient, ResponseCache
from jobpipe.sources import SOURCES
from jobpipe.sources.base import Reject

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BoardOutcome:
    board: BoardConfig
    snapshot_date: date
    status: str
    http_status: int | None
    posting_count: int
    reject_count: int
    error: str | None = None
    kept_previous: bool = False

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK


def extract_board(
    client: PoliteClient,
    board: BoardConfig,
    *,
    snapshot_date: date,
    extracted_at: datetime,
    store: BronzeStore,
    policy: FetchPolicy,
    fetch_mode: str,
) -> BoardOutcome:
    source = SOURCES[board.source]
    url = source.url(board.board)
    base = Manifest(
        company=board.company,
        extracted_at=extracted_at.isoformat(),
        status=STATUS_FAILED,
        fetch_mode=fetch_mode,
        http_status=None,
        posting_count=0,
        reject_count=0,
        attempts=0,
        url=url,
    )

    def fail(
        status: str,
        error: str,
        http_status: int | None,
        attempts: int,
        rejects: list[Reject] | None = None,
        raw_body: bytes | None = None,
    ) -> BoardOutcome:
        manifest = replace(
            base,
            status=status,
            error=error,
            http_status=http_status,
            attempts=attempts,
            reject_count=len(rejects or []),
        )
        written = store.land_failure(
            source=board.source,
            board=board.board,
            snapshot_date=snapshot_date,
            manifest=manifest,
            rejects=rejects,
            raw_body=raw_body,
        )
        log.warning("%s %s: %s (%s)", board.key, snapshot_date, status, error)
        if written:
            return BoardOutcome(
                board, snapshot_date, status, http_status, 0, len(rejects or []), error
            )
        # An earlier run already landed a good snapshot for this day; it stays in place.
        kept = store.read_manifest(board.source, board.board, snapshot_date)
        assert kept is not None
        return BoardOutcome(
            board,
            snapshot_date,
            STATUS_OK,
            kept.http_status,
            kept.posting_count,
            kept.reject_count,
            error,
            kept_previous=True,
        )

    try:
        result = client.get(url)
    except FetchError as exc:
        return fail(STATUS_FAILED, str(exc), exc.status, exc.attempts)

    try:
        parsed = source.parse(result.body)
    except EnvelopeError as exc:
        return fail(
            STATUS_CONTRACT_FAILED, str(exc), result.status, result.attempts, raw_body=result.body
        )

    if parsed.reject_ratio > policy.max_reject_ratio:
        # Too much of the response is unusable: treat the board as not observed today rather
        # than risk "closing" every posting that failed validation.
        error = f"{len(parsed.rejects)} of {len(parsed.rejects) + len(parsed.postings)} " + (
            f"postings failed the contract (> {policy.max_reject_ratio:.0%})"
        )
        return fail(STATUS_CONTRACT_FAILED, error, result.status, result.attempts, parsed.rejects)

    observed = len(parsed.postings) + len(parsed.rejects)
    drop_error = _suspicious_drop(store, board, snapshot_date, observed, policy)
    if drop_error:
        # A 200 with an empty or truncated list would otherwise close most of the board.
        return fail(
            STATUS_CONTRACT_FAILED,
            drop_error,
            result.status,
            result.attempts,
            parsed.rejects,
            raw_body=result.body,
        )

    manifest = replace(
        base,
        status=STATUS_OK,
        http_status=result.status,
        attempts=result.attempts,
        posting_count=len(parsed.postings),
        reject_count=len(parsed.rejects),
        rejected_posting_ids=tuple(
            sorted({r.posting_id for r in parsed.rejects if r.posting_id is not None})
        ),
    )
    store.land_success(
        source=board.source,
        board=board.board,
        snapshot_date=snapshot_date,
        extracted_at=extracted_at,
        postings=parsed.postings,
        rejects=parsed.rejects,
        manifest=manifest,
    )
    log.info(
        "%s %s: %d postings, %d rejected (HTTP %s%s)",
        board.key,
        snapshot_date,
        len(parsed.postings),
        len(parsed.rejects),
        result.status,
        ", not modified: cached body reused" if result.not_modified else "",
    )
    return BoardOutcome(
        board, snapshot_date, STATUS_OK, result.status, len(parsed.postings), len(parsed.rejects)
    )


def _suspicious_drop(
    store: BronzeStore, board: BoardConfig, snapshot_date: date, observed: int, policy: FetchPolicy
) -> str | None:
    """Error text if ``observed`` postings is a suspiciously sharp drop, else None."""
    max_drop = board.drop_ratio(policy)
    if max_drop is None:
        return None
    previous = store.previous_ok_manifest(board.source, board.board, snapshot_date)
    if previous is None:
        return None
    baseline = previous.posting_count + previous.reject_count
    if baseline < policy.drop_check_min_postings:
        return None
    if observed >= baseline * (1 - max_drop):
        return None
    return (
        f"posting count dropped from {baseline} on {previous.extracted_at[:10]} to {observed} "
        f"(more than {max_drop:.0%}); if the board really closed these postings, re-run the "
        f"day with --accept-drop {board.key}"
    )


def extract_snapshot(
    client: PoliteClient,
    config: PipelineConfig,
    *,
    snapshot_date: date,
    extracted_at: datetime,
    store: BronzeStore,
    fetch_mode: str,
) -> list[BoardOutcome]:
    """Fetch every board once. One board failing never stops the others."""
    outcomes = []
    for board in config.boards:
        try:
            outcome = extract_board(
                client,
                board,
                snapshot_date=snapshot_date,
                extracted_at=extracted_at,
                store=store,
                policy=config.policy,
                fetch_mode=fetch_mode,
            )
        except Exception as exc:  # e.g. a disk error while landing: isolate it to this board
            log.exception("%s %s: unexpected error", board.key, snapshot_date)
            error = f"{type(exc).__name__}: {exc}"
            outcome = BoardOutcome(board, snapshot_date, STATUS_FAILED, None, 0, 0, error)
            try:  # best effort: record the failure so the warehouse sees "not observed"
                store.land_failure(
                    source=board.source,
                    board=board.board,
                    snapshot_date=snapshot_date,
                    manifest=Manifest(
                        company=board.company,
                        extracted_at=extracted_at.isoformat(),
                        status=STATUS_FAILED,
                        fetch_mode=fetch_mode,
                        http_status=None,
                        posting_count=0,
                        reject_count=0,
                        attempts=0,
                        url=SOURCES[board.source].url(board.board),
                        error=error,
                    ),
                )
            except Exception:
                log.exception("%s %s: could not record the failure", board.key, snapshot_date)
        outcomes.append(outcome)
    return outcomes


def extract_live(
    config: PipelineConfig,
    store: BronzeStore,
    *,
    cache_dir: Path,
    now: datetime | None = None,
    transport: httpx.BaseTransport | None = None,
) -> list[BoardOutcome]:
    """Hit the real public APIs. Only reachable through the CLI's explicit ``--live`` flag.

    ``transport`` exists for tests, which substitute a mock so no network is touched.
    """
    now = now or datetime.now(UTC)
    client = PoliteClient(config.policy, cache=ResponseCache(cache_dir), transport=transport)
    with client:
        return extract_snapshot(
            client,
            config,
            snapshot_date=now.date(),
            extracted_at=now.replace(microsecond=0),
            store=store,
            fetch_mode="live",
        )


def extract_fixtures(
    config: PipelineConfig,
    fixtures_dir: Path,
    store: BronzeStore,
    *,
    dates: list[date] | None = None,
) -> list[BoardOutcome]:
    """Replay committed synthetic responses, one snapshot per fixture date directory.

    ``extracted_at`` is pinned to noon UTC of the snapshot date so fixture runs are
    byte-for-byte reproducible (and incremental dbt runs see re-landed data as unchanged).
    """
    available = fixture_dates(fixtures_dir)
    wanted = available if dates is None else [d for d in available if d in set(dates)]
    missing = set(dates or []) - set(available)
    if missing:
        raise ValueError(f"no fixture snapshot for {sorted(str(d) for d in missing)}")
    outcomes: list[BoardOutcome] = []
    for snapshot_date in wanted:
        transport = FixtureTransport(Path(fixtures_dir) / snapshot_date.isoformat(), config.boards)
        client = PoliteClient(config.policy, transport=transport, sleep=lambda _s: None)
        with client:
            outcomes += extract_snapshot(
                client,
                config,
                snapshot_date=snapshot_date,
                extracted_at=datetime.combine(snapshot_date, time(12, 0), tzinfo=UTC),
                store=store,
                fetch_mode="fixture",
            )
    return outcomes
