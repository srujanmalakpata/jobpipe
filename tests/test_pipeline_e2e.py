"""End-to-end: fixtures -> bronze -> dbt build (all data tests) -> marts -> report.

These tests run the real dbt project against a throwaway DuckDB file per data directory.
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import httpx
import pytest

from jobpipe import cli
from jobpipe.bronze import BronzeStore
from jobpipe.config import BoardConfig, FetchPolicy, PipelineConfig
from jobpipe.extract import extract_live
from jobpipe.paths import DBT_PROJECT_DIR, FIXTURES_DIR, DataPaths
from jobpipe.transform import run_dbt
from support import FIXTURE_DATES

pytestmark = pytest.mark.integration

COMPARED_TABLES = [
    "core.fct_posting_daily",
    "core.fct_postings",
    "core.dim_company",
    "core.dim_location",
    "core.bridge_posting_skill",
    "analytics.mart_weekly_postings_flow",
    "analytics.mart_time_to_close",
    "analytics.mart_skill_demand",
    "analytics.mart_remote_share",
    "analytics.mart_entry_level_share",
]


def run(data_dir: Path, *extra: str) -> int:
    return cli.main(["run", "--data-dir", str(data_dir), *extra])


def query(paths: DataPaths, sql: str, params: list | None = None) -> list[tuple]:
    con = duckdb.connect(str(paths.warehouse))
    try:
        return con.execute(sql, params or []).fetchall()
    finally:
        con.close()


def snapshot_tables(paths: DataPaths) -> dict[str, list[tuple]]:
    return {t: sorted(query(paths, f"select * from {t}"), key=repr) for t in COMPARED_TABLES}


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> DataPaths:
    data_dir = tmp_path_factory.mktemp("full")
    assert run(data_dir) == cli.EXIT_OK
    return DataPaths.at(data_dir)


def spell(paths: DataPaths, where: str) -> list[tuple]:
    return query(
        paths,
        "select spell_number, first_seen, last_seen, closed_at, is_left_censored, days_to_close,"
        f" title from core.fct_postings where {where} order by spell_number",
    )


# --- scripted fixture scenarios ---------------------------------------------------------


def test_closed_posting_lifecycle(built):
    assert spell(built, "posting_key = 'greenhouse:northwindrobotics:4100001'") == [
        (
            1,
            date(2026, 8, 10),
            date(2026, 8, 17),
            date(2026, 8, 24),
            False,
            14,
            "Software Engineering Intern (Winter 2027)",
        ),
    ]


def test_reopened_posting_gets_a_second_spell(built):
    rows = spell(built, "posting_key = 'greenhouse:mapleledger:5200001'")
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [
        (1, date(2026, 8, 3), date(2026, 8, 10), date(2026, 8, 17)),
        (2, date(2026, 8, 31), date(2026, 9, 7), None),
    ]
    assert rows[0][4] is True  # already listed at the first snapshot -> left-censored


def test_retitled_posting_keeps_one_spell_with_latest_title(built):
    rows = spell(
        built,
        "company_key = 'lever:auroralabs' and posting_key in (select posting_key from"
        " core.fct_posting_daily where title = 'Machine Learning Engineer')",
    )
    assert len(rows) == 1
    assert rows[0][6] == "Senior Machine Learning Engineer"
    assert rows[0][3] is None


def test_failed_fetch_never_closes_postings(built):
    assert query(
        built,
        "select count(*) from core.fct_postings"
        " where company_key = 'lever:tidewaterlogistics' and closed_at = '2026-08-24'",
    ) == [(0,)]
    # scripted posting listed 08-10..08-31 across the failed 08-24 fetch: one unbroken spell
    rows = spell(
        built,
        "company_key = 'lever:tidewaterlogistics' and title = 'Data Engineer'"
        " and first_seen = '2026-08-10'",
    )
    assert [(r[1], r[2], r[3]) for r in rows] == [
        (date(2026, 8, 10), date(2026, 8, 31), date(2026, 9, 7)),
    ]


def test_listed_but_rejected_posting_keeps_one_unbroken_spell(built):
    """08-31: the Aurora ML posting is still listed but fails the contract (blank title).
    It must not close on 08-31 and reopen on 09-07."""
    key = "lever:auroralabs:34665405-180d-4b72-bbcb-2334675254e0"
    assert query(
        built,
        "select snapshot_date from staging.stg_bronze__unparsed_postings where posting_key = ?",
        [key],
    ) == [(date(2026, 8, 31),)]
    assert query(
        built,
        "select spell_number, first_seen, last_seen, closed_at, unparsed_snapshots, title"
        " from core.fct_postings where posting_key = ?",
        [key],
    ) == [(1, date(2026, 8, 3), date(2026, 9, 7), None, 1, "Senior Machine Learning Engineer")]
    # the snapshot fact only holds parsed rows, so that day is missing there
    assert (date(2026, 8, 31),) not in query(
        built, "select snapshot_date from core.fct_posting_daily where posting_key = ?", [key]
    )


def test_quarantined_and_unlisted_postings_never_reach_the_warehouse(built):
    rejects = list(built.bronze.glob("rejects/*/*/*/rejects.jsonl"))
    assert len(rejects) == 2  # the Ashby record below and the Aurora one above
    assert query(
        built,
        "select count(*) from core.fct_posting_daily where posting_id = "
        "'00000000-0000-4000-8000-00000000bad1' or title = 'Internal Playtest Coordinator'",
    ) == [(0,)]


def test_provider_duplicates_are_deduplicated(built):
    landed = query(
        built,
        "select count(*) from staging.stg_bronze__postings"
        " where board = 'northwindrobotics' and snapshot_date = '2026-08-17'",
    )[0][0]
    loaded = query(
        built,
        "select count(*) from core.fct_posting_daily"
        " where board = 'northwindrobotics' and snapshot_date = '2026-08-17'",
    )[0][0]
    assert landed == loaded + 1


def test_skill_extraction_examples(built):
    skills = {
        row[0]
        for row in query(
            built,
            "select skill from core.bridge_posting_skill"
            " where posting_key = 'greenhouse:northwindrobotics:4100001'",
        )
    }
    # Greenhouse HTML is double-escaped; C++ must survive entity decoding.
    assert {"Python", "C++", "ROS", "Git"} <= skills
    # Sales postings say "go-to-market"; that must not count as the Go language.
    go_to_market = query(
        built,
        "select count(*) from core.fct_postings where role_family = 'sales_business'",
    )[0][0]
    assert go_to_market > 0
    assert (
        query(
            built,
            "select distinct b.skill from core.bridge_posting_skill b join core.fct_postings f"
            " using (posting_key) where f.role_family = 'sales_business' and b.skill = 'Go'",
        )
        == []
    )


# --- independent oracle -----------------------------------------------------------------


def oracle_spells(bronze: Path) -> set[tuple]:
    """Recompute lifecycle spells in plain Python straight from bronze files.

    A posting is "present" on a successful snapshot if it was landed there or was listed but
    rejected by the contract (manifest ``rejected_posting_ids``). A spell is a run of
    consecutive successful snapshots with the posting present; runs made only of rejected
    records are dropped (nothing to describe them with).
    """
    ok_dates: dict[str, list[date]] = defaultdict(list)
    unparsed: dict[str, set[date]] = defaultdict(set)
    for path in bronze.glob("manifests/*/*/*/manifest.jsonl"):
        source, board, day = (p.split("=", 1)[1] for p in path.parent.parts[-3:])
        manifest = json.loads(path.read_text())
        if manifest["status"] == "ok":
            ok_dates[f"{source}:{board}"].append(date.fromisoformat(day))
            for posting_id in manifest.get("rejected_posting_ids", []):
                unparsed[f"{source}:{board}:{posting_id}"].add(date.fromisoformat(day))
    parsed: dict[str, set[date]] = defaultdict(set)
    for path in bronze.glob("postings/*/*/*/part-0.jsonl"):
        source, board, day = (p.split("=", 1)[1] for p in path.parent.parts[-3:])
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if source == "ashby" and row["payload"].get("isListed") is False:
                continue
            parsed[f"{source}:{board}:{row['posting_id']}"].add(date.fromisoformat(day))

    spells = set()
    for posting_key, parsed_days in parsed.items():
        present = parsed_days | unparsed[posting_key]
        run: list[date] = []
        for day in [*sorted(ok_dates[posting_key.rsplit(":", 1)[0]]), None]:
            if day is not None and day in present:
                run.append(day)
                continue
            if run and parsed_days & set(run):
                spells.add((posting_key, run[0], run[-1], day))
            run = []
    return spells


def test_lifecycle_matches_python_oracle(built):
    warehouse = set(
        query(built, "select posting_key, first_seen, last_seen, closed_at from core.fct_postings")
    )
    expected = oracle_spells(built.bronze)
    assert len(expected) > 100
    assert warehouse == expected


def test_weekly_flow_matches_lifecycle(built):
    rows = query(
        built,
        "select sum(opened), sum(closed), sum(reopened) from analytics.mart_weekly_postings_flow",
    )
    spells = query(
        built,
        "select count(*) filter (where not is_left_censored),"
        " count(*) filter (where closed_at is not null),"
        " count(*) filter (where spell_number > 1) from core.fct_postings",
    )
    assert rows == spells


# --- idempotency and incremental correctness --------------------------------------------


def test_rerun_is_idempotent(built):
    before = snapshot_tables(built)
    report_before = (built.reports / "report.md").read_bytes()
    assert run(built.root) == cli.EXIT_OK
    assert snapshot_tables(built) == before
    assert (built.reports / "report.md").read_bytes() == report_before


def test_incremental_out_of_order_runs_equal_full_build(built, tmp_path):
    """Land snapshots one run at a time - including a late, backfilled day - and check the
    incremental models converge to exactly what a single full build produces."""
    order = ["2026-08-03", "2026-08-10", "2026-08-24", "2026-08-17", "2026-08-31", "2026-09-07"]
    assert sorted(order) == FIXTURE_DATES
    for day in order:
        assert run(tmp_path, "--date", day) == cli.EXIT_OK
    incremental = DataPaths.at(tmp_path)
    assert snapshot_tables(incremental) == snapshot_tables(built)

    assert run(tmp_path, "--full-refresh") == cli.EXIT_OK
    assert snapshot_tables(incremental) == snapshot_tables(built)


def test_report_is_rendered(built):
    md = (built.reports / "report.md").read_text()
    html = (built.reports / "report.html").read_text()
    assert "every company and posting in this report is synthetic" in md
    for heading in (
        "Postings opened and closed per week",
        "Time to close",
        "Top skills",
        "Remote share",
        "Entry-level share",
    ):
        assert heading in md and heading in html
    assert html.startswith("<!doctype html>")


def test_relanding_a_day_as_empty_matches_a_full_refresh(tmp_path):
    """delete+insert alone keeps rows for a partition re-landed with zero postings; the
    pre-hooks must remove them so the incremental state equals a full rebuild."""
    config = PipelineConfig(
        boards=(BoardConfig("greenhouse", "acme", "Acme"),),
        policy=FetchPolicy(min_interval_seconds=0, max_drop_ratio=None),
    )
    paths = DataPaths.at(tmp_path)
    store = BronzeStore(paths.bronze)

    def land(when: datetime, ids: list[int]) -> None:
        jobs = [
            {
                "id": i,
                "title": "Software Engineer",
                "updated_at": "2026-08-01T00:00:00Z",
                "absolute_url": f"https://example.invalid/{i}",
            }
            for i in ids
        ]
        body = json.dumps({"jobs": jobs}).encode()
        (outcome,) = extract_live(
            config,
            store,
            cache_dir=paths.http_cache,
            now=when,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)),
        )
        assert outcome.ok

    def build(full_refresh: bool = False) -> dict[str, list[tuple]]:
        outcome = run_dbt(paths, full_refresh=full_refresh)
        assert outcome.success, outcome.failures
        return {
            "daily": query(
                paths, "select posting_key, snapshot_date from core.fct_posting_daily order by all"
            ),
            "spells": query(
                paths,
                "select posting_key, first_seen, last_seen, closed_at"
                " from core.fct_postings order by all",
            ),
        }

    land(datetime(2026, 8, 3, 9, tzinfo=UTC), [1, 2, 3])
    land(datetime(2026, 8, 10, 9, tzinfo=UTC), [1, 2, 3])
    build()
    land(datetime(2026, 8, 10, 15, tzinfo=UTC), [])  # same day, later run: board now empty
    incremental = build()
    assert incremental == build(full_refresh=True)
    assert [row[1] for row in incremental["daily"]] == [date(2026, 8, 3)] * 3
    assert {row[3] for row in incremental["spells"]} == {date(2026, 8, 10)}


def test_edited_fixture_with_same_timestamp_is_reprocessed(tmp_path):
    """Fixture runs pin extracted_at, so only the manifest content hash reveals an edited
    response. Retitle one posting and swap another's id (same count) on an already-landed
    day: the incremental result must equal --full-refresh. The data dir contains a quote,
    which the bronze path in the dbt SQL must survive."""
    fixtures = tmp_path / "fixtures"
    shutil.copytree(FIXTURES_DIR, fixtures)
    data_dir = tmp_path / "it's data"
    paths = DataPaths.at(data_dir)
    args = ("--fixtures-dir", str(fixtures))
    assert run(data_dir, *args) == cli.EXIT_OK

    edited = fixtures / "2026-09-07" / "greenhouse" / "mapleledger.json"
    body = json.loads(edited.read_text())
    assert body["jobs"][0]["id"] == 5200001
    body["jobs"][0]["title"] = "Totally New Title Analyst"
    swapped_out = body["jobs"][1]["id"]
    body["jobs"][1]["id"] = 5299999
    edited.write_text(json.dumps(body))

    assert run(data_dir, *args) == cli.EXIT_OK
    incremental = snapshot_tables(paths)
    assert query(
        paths,
        "select title from core.fct_postings where posting_key = ? and is_open",
        ["greenhouse:mapleledger:5200001"],
    ) == [("Totally New Title Analyst",)]
    assert query(
        paths,
        "select posting_id from core.fct_posting_daily where board = 'mapleledger'"
        " and snapshot_date = '2026-09-07' and posting_id in (?, '5299999') order by 1",
        [str(swapped_out)],
    ) == [("5299999",)]

    assert run(data_dir, *args, "--full-refresh") == cli.EXIT_OK
    assert snapshot_tables(paths) == incremental


def test_classification_rule_change_without_full_refresh_is_detected(built, tmp_path, capsys):
    """Role/seniority values are stored in the incremental daily fact. Changing a rule must
    not silently leave old values: the reconciliation test fails and names the partitions,
    and --full-refresh repairs it."""
    project = tmp_path / "transform"
    shutil.copytree(
        DBT_PROJECT_DIR, project, ignore=shutil.ignore_patterns("target", "logs", "dbt_packages")
    )
    paths = DataPaths.at(tmp_path / "data")
    shutil.copytree(built.bronze, paths.bronze)
    assert run_dbt(paths, project_dir=project).success

    rules = project / "seeds" / "role_family_rules.csv"
    rules.write_text(rules.read_text().replace(r"\banalyst\b|", ""))  # analysts -> other
    outcome = run_dbt(paths, project_dir=project)
    assert not outcome.success
    drift = [f for f in outcome.failures if f.startswith(cli.DRIFT_TEST)]
    assert drift, outcome.failures

    repaired = run_dbt(paths, project_dir=project, full_refresh=True)
    assert not any(f.startswith(cli.DRIFT_TEST) for f in repaired.failures)


def test_invalidating_a_partial_snapshot_recomputes_the_board(built, tmp_path):
    """An ok-but-partial snapshot closed a posting. After `pipeline invalidate`, that day no
    longer closes anything, and the incremental result equals a full refresh."""
    shutil.copytree(built.root / "bronze", tmp_path / "bronze")
    paths = DataPaths.at(tmp_path)
    assert run_dbt(paths).success
    key = "greenhouse:northwindrobotics:4100001"
    closed = "select closed_at from core.fct_postings where posting_key = ?"
    assert query(paths, closed, [key]) == [(date(2026, 8, 24),)]

    args = ["invalidate", "--data-dir", str(tmp_path), "--board", "greenhouse:northwindrobotics"]
    assert cli.main([*args, "--date", "2026-08-24", "--reason", "test"]) == cli.EXIT_OK
    outcome = run_dbt(paths)
    assert outcome.success, outcome.failures
    assert query(paths, closed, [key]) == [(date(2026, 8, 31),)]
    incremental = snapshot_tables(paths)
    assert run_dbt(paths, full_refresh=True).success
    assert snapshot_tables(paths) == incremental
