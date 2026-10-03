"""``pipeline`` command: extract -> dbt build -> report.

Fixture mode is the default everywhere. Network access to real job boards only happens with
an explicit ``--live`` flag, and live data goes to its own directory (``data/live``) so it is
never mixed with the synthetic fixture lake by accident.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from jobpipe.bronze import BronzeStore
from jobpipe.config import ConfigError, accept_drops, load_config
from jobpipe.extract import BoardOutcome, extract_fixtures, extract_live
from jobpipe.paths import CONFIG_DIR, FIXTURES_DIR, DataPaths
from jobpipe.report import ReportError, write_report
from jobpipe.transform import run_dbt

log = logging.getLogger("jobpipe")

EXIT_OK = 0
EXIT_DBT_FAILED = 1
EXIT_NOTHING_EXTRACTED = 2
EXIT_USAGE = 3  # bad configuration, mixed fetch modes, missing warehouse, ...

DRIFT_TEST = "assert_daily_fact_reconciles_with_bronze"


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="where bronze, the DuckDB warehouse and reports live (default: $JOBPIPE_DATA_DIR, "
        "else ./data, or ./data/live with --live)",
    )


def resolve_data_dir(args: argparse.Namespace) -> Path:
    if args.data_dir is not None:
        return args.data_dir
    if "JOBPIPE_DATA_DIR" in os.environ:
        return Path(os.environ["JOBPIPE_DATA_DIR"])
    return Path("data/live") if getattr(args, "live", False) else Path("data")


def _add_extract_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--live",
        action="store_true",
        help="fetch from the real public APIs (default: replay committed synthetic fixtures)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="boards YAML (default: config/boards.fixtures.yaml, or "
        "config/boards.live.example.yaml with --live)",
    )
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES_DIR)
    parser.add_argument(
        "--date",
        dest="dates",
        action="append",
        type=date.fromisoformat,
        help="fixture mode only: land just this snapshot date (repeatable)",
    )
    parser.add_argument(
        "--accept-drop",
        metavar="SOURCE:BOARD",
        action="append",
        default=[],
        help="this run only: accept a sharp posting-count drop on this board (repeatable)",
    )
    parser.add_argument(
        "--allow-mixed",
        action="store_true",
        help="allow landing live and fixture data in the same data directory",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="land raw postings in bronze")
    _add_common(p_extract)
    _add_extract_args(p_extract)

    p_transform = sub.add_parser("transform", help="dbt build (seeds, models, tests)")
    _add_common(p_transform)
    p_transform.add_argument("--full-refresh", action="store_true")

    p_report = sub.add_parser("report", help="render marts to Markdown + HTML")
    _add_common(p_report)

    p_run = sub.add_parser("run", help="extract -> transform -> report")
    _add_common(p_run)
    _add_extract_args(p_run)
    p_run.add_argument("--full-refresh", action="store_true")

    p_invalidate = sub.add_parser(
        "invalidate",
        help="mark one landed board snapshot as untrustworthy (e.g. a partial response)",
    )
    _add_common(p_invalidate)
    p_invalidate.add_argument("--board", required=True, metavar="SOURCE:BOARD")
    p_invalidate.add_argument("--date", required=True, type=date.fromisoformat)
    p_invalidate.add_argument("--reason", required=True)
    return parser


class UsageError(Exception):
    """A problem the user must fix before the command can run (exit code 3)."""


def _extract(args: argparse.Namespace, paths: DataPaths) -> list[BoardOutcome]:
    default_config = "boards.live.example.yaml" if args.live else "boards.fixtures.yaml"
    config = accept_drops(load_config(args.config or CONFIG_DIR / default_config), args.accept_drop)
    store = BronzeStore(paths.bronze)
    mode = "live" if args.live else "fixture"
    others = store.fetch_modes() - {mode}
    if others and not args.allow_mixed:
        raise UsageError(
            f"{paths.bronze} already holds {', '.join(sorted(others))} data; landing {mode} "
            "data there would mix real and synthetic postings in one warehouse. Use another "
            "--data-dir (live mode defaults to data/live), or pass --allow-mixed."
        )
    if args.live:
        if args.dates:
            raise SystemExit("--date only applies to fixture mode; live snapshots are 'today'")
        log.warning("LIVE mode: fetching %d public job boards", len(config.boards))
        outcomes = extract_live(config, store, cache_dir=paths.http_cache)
    else:
        outcomes = extract_fixtures(config, args.fixtures_dir, store, dates=args.dates)
    landed = [o for o in outcomes if o.ok and not o.kept_previous]
    kept = [o for o in outcomes if o.kept_previous]
    summary = (
        f"extract: {sum(o.ok for o in outcomes)}/{len(outcomes)} board snapshots ok, "
        f"{sum(o.posting_count for o in landed)} postings landed, "
        f"{sum(o.reject_count for o in outcomes if not o.kept_previous)} rejected"
    )
    if kept:
        summary += (
            f", {len(kept)} kept an earlier good snapshot "
            f"({sum(o.posting_count for o in kept)} postings)"
        )
    print(f"{summary} -> {paths.bronze}")
    for o in outcomes:
        if not o.ok or o.kept_previous:
            print(f"  ! {o.board.key} {o.snapshot_date}: {o.status} {o.error or ''}".rstrip())
    return outcomes


def _transform(paths: DataPaths, full_refresh: bool, verbose: bool) -> bool:
    outcome = run_dbt(paths, "build", full_refresh=full_refresh, quiet=not verbose)
    print(outcome.summary())
    for failure in outcome.failures:
        print(f"  ! {failure}")
    if any(f.startswith(DRIFT_TEST) for f in outcome.failures):
        print(
            "  hint: fct_posting_daily no longer matches a rebuild from bronze (typically a "
            "changed role-family or seniority rule); re-run with --full-refresh"
        )
    return outcome.success


def _report(paths: DataPaths) -> None:
    md, html = write_report(paths)
    print(f"report: {md}\n        {html}")


def _invalidate(args: argparse.Namespace, paths: DataPaths) -> None:
    source, sep, board = args.board.partition(":")
    if not sep:
        raise UsageError("--board must look like SOURCE:BOARD, e.g. greenhouse:acme")
    try:
        manifest = BronzeStore(paths.bronze).invalidate(source, board, args.date, args.reason)
    except FileNotFoundError as exc:
        raise UsageError(str(exc)) from exc
    print(
        f"invalidated {args.board} {args.date}: now {manifest.status}. Run `pipeline transform` "
        "to recompute the board without it."
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    paths = DataPaths.at(resolve_data_dir(args))
    try:
        return _dispatch(args, paths)
    except (UsageError, ConfigError, ReportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE


def _dispatch(args: argparse.Namespace, paths: DataPaths) -> int:
    if args.command == "extract":
        outcomes = _extract(args, paths)
        return EXIT_OK if any(o.ok for o in outcomes) else EXIT_NOTHING_EXTRACTED
    if args.command == "transform":
        return EXIT_OK if _transform(paths, args.full_refresh, args.verbose) else EXIT_DBT_FAILED
    if args.command == "report":
        _report(paths)
        return EXIT_OK
    if args.command == "invalidate":
        _invalidate(args, paths)
        return EXIT_OK

    # run
    outcomes = _extract(args, paths)
    if not any(o.ok for o in outcomes):
        print("no board was extracted successfully; skipping transform")
        return EXIT_NOTHING_EXTRACTED
    if not _transform(paths, args.full_refresh, args.verbose):
        return EXIT_DBT_FAILED
    _report(paths)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
