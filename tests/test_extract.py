"""Extract orchestration: fixture replay, failure isolation, contract gate, live path (mocked)."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from jobpipe import cli
from jobpipe.bronze import STATUS_CONTRACT_FAILED, STATUS_FAILED, BronzeStore
from jobpipe.config import BoardConfig, ConfigError, FetchPolicy, PipelineConfig, accept_drops
from jobpipe.extract import extract_fixtures, extract_live
from support import fixture_body


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(root)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def test_fixture_extract_lands_every_board(tmp_path, fixture_config, fixtures_dir):
    store = BronzeStore(tmp_path)
    outcomes = extract_fixtures(fixture_config, fixtures_dir, store, dates=[date(2026, 8, 10)])
    assert len(outcomes) == 5 and all(o.ok for o in outcomes)
    glacier = next(o for o in outcomes if o.board.board == "glaciergames")
    assert glacier.reject_count == 1
    m = store.read_manifest("ashby", "glaciergames", date(2026, 8, 10))
    assert (m.status, m.fetch_mode, m.reject_count) == ("ok", "fixture", 1)
    assert m.extracted_at == "2026-08-10T12:00:00+00:00"


def test_one_failing_board_does_not_stop_the_others(tmp_path, fixture_config, fixtures_dir):
    store = BronzeStore(tmp_path)
    outcomes = extract_fixtures(fixture_config, fixtures_dir, store, dates=[date(2026, 8, 24)])
    failed = [o for o in outcomes if not o.ok]
    assert [o.board.board for o in failed] == ["tidewaterlogistics"]
    assert failed[0].http_status == 500
    m = store.read_manifest("lever", "tidewaterlogistics", date(2026, 8, 24))
    assert m.status == STATUS_FAILED
    assert m.attempts == fixture_config.policy.max_attempts
    assert "HTTP 500" in m.error


def test_fixture_extract_is_byte_for_byte_idempotent(tmp_path, fixture_config, fixtures_dir):
    store = BronzeStore(tmp_path)
    extract_fixtures(fixture_config, fixtures_dir, store)
    first = tree_digest(tmp_path)
    extract_fixtures(fixture_config, fixtures_dir, store)
    assert tree_digest(tmp_path) == first
    assert len({p.parent.name for p in tmp_path.glob("manifests/*/*/*/manifest.jsonl")}) == 6


def test_unknown_fixture_date_is_an_error(tmp_path, fixture_config, fixtures_dir):
    with pytest.raises(ValueError, match="no fixture snapshot"):
        extract_fixtures(
            fixture_config, fixtures_dir, BronzeStore(tmp_path), dates=[date(2020, 1, 1)]
        )


def test_too_many_rejects_fails_the_board_instead_of_closing_postings(tmp_path):
    bad = json.dumps({"jobs": [{"id": i, "title": ""} for i in range(3)]}).encode()
    config = PipelineConfig(
        boards=(BoardConfig("greenhouse", "acme", "Acme"),),
        policy=FetchPolicy(min_interval_seconds=0, max_reject_ratio=0.2),
    )
    store = BronzeStore(tmp_path)
    (outcome,) = extract_live(
        config,
        store,
        cache_dir=tmp_path / "cache",
        now=datetime(2026, 9, 7, 15, tzinfo=UTC),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=bad)),
    )
    assert outcome.status == STATUS_CONTRACT_FAILED
    assert outcome.reject_count == 3
    assert "failed the contract" in outcome.error


def test_live_path_with_mocked_http_uses_conditional_requests(tmp_path):
    """The --live code path end to end, with every provider mocked (no network)."""
    bodies = {
        "boards-api.greenhouse.io": fixture_body("2026-09-07", "greenhouse", "mapleledger"),
        "api.lever.co": fixture_body("2026-09-07", "lever", "auroralabs"),
        "api.ashbyhq.com": fixture_body("2026-09-07", "ashby", "glaciergames"),
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.headers.get("If-None-Match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=bodies[request.url.host], headers={"ETag": '"v1"'})

    config = PipelineConfig(
        boards=(
            BoardConfig("greenhouse", "acme-gh", "Acme GH"),
            BoardConfig("lever", "acme-lv", "Acme LV"),
            BoardConfig("ashby", "acme-ab", "Acme AB"),
        ),
        policy=FetchPolicy(min_interval_seconds=0),
    )
    store = BronzeStore(tmp_path / "bronze")
    now = datetime(2026, 10, 3, 9, 30, tzinfo=UTC)
    run = lambda: extract_live(  # noqa: E731
        config, store, cache_dir=tmp_path / "cache", now=now, transport=httpx.MockTransport(handler)
    )

    first = run()
    assert [o.http_status for o in first] == [200, 200, 200]
    assert {r.url.path for r in requests} == {
        "/v1/boards/acme-gh/jobs",
        "/v0/postings/acme-lv",
        "/posting-api/job-board/acme-ab",
    }
    m = store.read_manifest("lever", "acme-lv", date(2026, 10, 3))
    assert (m.fetch_mode, m.extracted_at) == ("live", "2026-10-03T09:30:00+00:00")

    second = run()
    assert [o.http_status for o in second] == [304, 304, 304]
    assert [o.posting_count for o in second] == [o.posting_count for o in first]


def test_cli_refuses_date_with_live(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["extract", "--live", "--date", "2026-08-03", "--data-dir", str(tmp_path)])


def test_cli_extract_fixture_mode(tmp_path, capsys):
    code = cli.main(["extract", "--date", "2026-08-24", "--data-dir", str(tmp_path)])
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "4/5 board snapshots ok" in out
    assert "lever:tidewaterlogistics 2026-08-24: failed" in out


def test_cli_returns_2_when_nothing_was_extracted(tmp_path, fixture_config):
    config_path = tmp_path / "boards.yaml"
    config_path.write_text("boards:\n  - {source: lever, board: nosuchboard}\n")
    code = cli.main(["run", "--config", str(config_path), "--data-dir", str(tmp_path / "data")])
    assert code == cli.EXIT_NOTHING_EXTRACTED


# --- failure diagnostics and guards ---------------------------------------------------------


def gh_job(i: int, title: str = "Software Engineer") -> dict:
    return {
        "id": i,
        "title": title,
        "updated_at": "2026-08-01T00:00:00Z",
        "absolute_url": f"https://example.invalid/{i}",
    }


def two_boards(**policy) -> PipelineConfig:
    return PipelineConfig(
        boards=(BoardConfig("greenhouse", "acme", "Acme"), BoardConfig("lever", "beta", "Beta")),
        policy=FetchPolicy(min_interval_seconds=0, **policy),
    )


def live(config, store, tmp_path, handler, day=date(2026, 9, 7)):
    return extract_live(
        config,
        store,
        cache_dir=tmp_path / "cache",
        now=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
        transport=httpx.MockTransport(handler),
    )


def gh_or_lever(gh_body: bytes, lever_body: bytes = b"[]"):
    def handler(request: httpx.Request) -> httpx.Response:
        body = gh_body if request.url.host == "boards-api.greenhouse.io" else lever_body
        return httpx.Response(200, content=body)

    return handler


def test_contract_failed_board_keeps_field_errors_on_disk(tmp_path):
    body = json.dumps({"jobs": [gh_job(i, "") for i in range(5)]}).encode()
    store = BronzeStore(tmp_path / "bronze")
    live(two_boards(), store, tmp_path, gh_or_lever(body))
    m = store.read_manifest("greenhouse", "acme", date(2026, 9, 7))
    assert (m.status, m.reject_count) == (STATUS_CONTRACT_FAILED, 5)
    rejects = store.partition("rejects", "greenhouse", "acme", date(2026, 9, 7))
    errors = [json.loads(line)["error"] for line in (rejects / "rejects.jsonl").open()]
    assert len(errors) == 5 and all("title" in e for e in errors)


def test_unusable_envelope_keeps_the_raw_body(tmp_path):
    store = BronzeStore(tmp_path / "bronze")
    live(two_boards(), store, tmp_path, gh_or_lever(b'{"positions": []}'))
    m = store.read_manifest("greenhouse", "acme", date(2026, 9, 7))
    assert m.status == STATUS_CONTRACT_FAILED and "envelope" in m.error
    raw = store.partition("rejects", "greenhouse", "acme", date(2026, 9, 7)) / "response.body"
    assert raw.read_bytes() == b'{"positions": []}'


def test_manifest_lists_ids_of_listed_but_rejected_postings(tmp_path):
    jobs = [gh_job(i) for i in range(1, 8)] + [gh_job(99, " ")]
    store = BronzeStore(tmp_path / "bronze")
    (gh, _) = live(two_boards(), store, tmp_path, gh_or_lever(json.dumps({"jobs": jobs}).encode()))
    assert (gh.status, gh.posting_count, gh.reject_count) == ("ok", 7, 1)
    m = store.read_manifest("greenhouse", "acme", date(2026, 9, 7))
    assert m.rejected_posting_ids == ("99",)


def test_non_transport_httpx_error_is_isolated_to_its_board(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "boards-api.greenhouse.io":  # a redirect loop on one board
            return httpx.Response(302, headers={"Location": str(request.url)})
        return httpx.Response(200, json=[])

    store = BronzeStore(tmp_path / "bronze")
    gh, lever = live(two_boards(), store, tmp_path, handler)
    assert gh.status == STATUS_FAILED and "TooManyRedirects" in gh.error
    assert lever.ok
    assert store.read_manifest("greenhouse", "acme", date(2026, 9, 7)).status == STATUS_FAILED


def test_unexpected_error_while_landing_is_isolated_to_its_board(tmp_path, monkeypatch):
    store = BronzeStore(tmp_path / "bronze")
    real = store.land_success

    def flaky(**kwargs):
        if kwargs["board"] == "acme":
            raise OSError("disk full")
        return real(**kwargs)

    monkeypatch.setattr(store, "land_success", flaky)
    body = json.dumps({"jobs": [gh_job(1)]}).encode()
    gh, lever = live(two_boards(), store, tmp_path, gh_or_lever(body))
    assert (gh.status, gh.error) == (STATUS_FAILED, "OSError: disk full")
    assert lever.ok
    assert store.read_manifest("greenhouse", "acme", date(2026, 9, 7)).status == STATUS_FAILED


def test_sharp_drop_versus_previous_snapshot_is_not_trusted(tmp_path):
    store = BronzeStore(tmp_path / "bronze")
    full = json.dumps({"jobs": [gh_job(i) for i in range(1, 21)]}).encode()
    live(two_boards(), store, tmp_path, gh_or_lever(full), day=date(2026, 8, 31))

    empty = json.dumps({"jobs": []}).encode()
    gh, _ = live(two_boards(), store, tmp_path, gh_or_lever(empty))
    assert gh.status == STATUS_CONTRACT_FAILED
    assert "dropped from 20" in gh.error
    raw = store.partition("rejects", "greenhouse", "acme", date(2026, 9, 7)) / "response.body"
    assert raw.read_bytes() == empty

    # a board that really closed everything can be accepted explicitly, for one run ...
    gh, _ = live(
        accept_drops(two_boards(), ["greenhouse:acme"]), store, tmp_path, gh_or_lever(empty)
    )
    assert (gh.status, gh.posting_count) == ("ok", 0)
    with pytest.raises(ConfigError, match="not in the configured boards"):
        accept_drops(two_boards(), ["greenhouse:nope"])


def test_drop_guard_can_be_overridden_per_board(tmp_path):
    full = json.dumps({"jobs": [gh_job(i) for i in range(1, 21)]}).encode()
    half = json.dumps({"jobs": [gh_job(i) for i in range(1, 11)]}).encode()

    def config(**override) -> PipelineConfig:
        gh = BoardConfig("greenhouse", "acme", "Acme", **override)
        return PipelineConfig((gh,), FetchPolicy(min_interval_seconds=0))

    store = BronzeStore(tmp_path / "strict")
    live(config(), store, tmp_path, gh_or_lever(full), day=date(2026, 8, 31))
    strict = config(overrides_drop_ratio=True, max_drop_ratio=0.3)
    (gh,) = live(strict, store, tmp_path, gh_or_lever(half))
    assert gh.status == STATUS_CONTRACT_FAILED and "more than 30%" in gh.error

    store = BronzeStore(tmp_path / "default")
    live(config(), store, tmp_path, gh_or_lever(full), day=date(2026, 8, 31))
    (gh,) = live(config(), store, tmp_path, gh_or_lever(half))
    assert gh.ok  # a 50% drop is within the global 80% guard


def test_small_boards_and_first_snapshots_skip_the_drop_check(tmp_path):
    store = BronzeStore(tmp_path / "bronze")
    few = json.dumps({"jobs": [gh_job(i) for i in range(1, 4)]}).encode()
    live(two_boards(), store, tmp_path, gh_or_lever(few), day=date(2026, 8, 31))
    gh, _ = live(two_boards(), store, tmp_path, gh_or_lever(b'{"jobs": []}'))
    assert gh.ok  # 3 -> 0 is below drop_check_min_postings


def test_failure_after_a_good_run_reports_the_kept_snapshot(tmp_path, capsys):
    data = tmp_path / "data"
    assert cli.main(["extract", "--date", "2026-08-10", "--data-dir", str(data)]) == cli.EXIT_OK
    capsys.readouterr()
    # same day again, but every request now fails: the good snapshot must survive
    broken = tmp_path / "broken"
    (broken / "2026-08-10").mkdir(parents=True)
    code = cli.main(
        ["extract", "--date", "2026-08-10", "--data-dir", str(data), "--fixtures-dir", str(broken)]
    )
    assert code == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "5/5 board snapshots ok, 0 postings landed" in out
    assert "5 kept an earlier good snapshot" in out
    store = BronzeStore(data / "bronze")
    assert store.read_manifest("greenhouse", "mapleledger", date(2026, 8, 10)).status == "ok"


# --- live / fixture separation and operator tools --------------------------------------------


def test_live_mode_defaults_to_its_own_data_dir(monkeypatch):
    monkeypatch.delenv("JOBPIPE_DATA_DIR", raising=False)
    parser = cli.build_parser()
    assert cli.resolve_data_dir(parser.parse_args(["run"])) == Path("data")
    assert cli.resolve_data_dir(parser.parse_args(["run", "--live"])) == Path("data/live")
    assert cli.resolve_data_dir(parser.parse_args(["run", "--live", "--data-dir", "x"])) == Path(
        "x"
    )
    monkeypatch.setenv("JOBPIPE_DATA_DIR", "/data")
    assert cli.resolve_data_dir(parser.parse_args(["run", "--live"])) == Path("/data")


def test_cli_refuses_to_mix_live_and_fixture_data(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    store = BronzeStore(data / "bronze")
    body = json.dumps({"jobs": [gh_job(1)]}).encode()
    live(two_boards(), store, tmp_path, gh_or_lever(body))  # a (mocked) live landing
    assert store.fetch_modes() == {"live"}

    code = cli.main(["extract", "--date", "2026-08-03", "--data-dir", str(data)])
    assert code == cli.EXIT_USAGE
    assert "already holds live data" in capsys.readouterr().err
    assert store.fetch_modes() == {"live"}  # nothing landed

    flag = ["--allow-mixed", "--date", "2026-08-03", "--data-dir", str(data)]
    assert cli.main(["extract", *flag]) == cli.EXIT_OK
    assert store.fetch_modes() == {"live", "fixture"}


def test_cli_invalidate_marks_a_landed_day(tmp_path, capsys):
    data = tmp_path / "data"
    assert cli.main(["extract", "--date", "2026-08-10", "--data-dir", str(data)]) == cli.EXIT_OK
    args = ["invalidate", "--data-dir", str(data), "--date", "2026-08-10", "--reason", "partial"]
    assert cli.main([*args, "--board", "greenhouse:mapleledger"]) == cli.EXIT_OK
    assert "now contract_failed" in capsys.readouterr().out
    m = BronzeStore(data / "bronze").read_manifest("greenhouse", "mapleledger", date(2026, 8, 10))
    assert m.status == STATUS_CONTRACT_FAILED and "partial" in m.error

    assert cli.main([*args, "--board", "greenhouse:nosuchboard"]) == cli.EXIT_USAGE
    assert cli.main([*args, "--board", "no-colon"]) == cli.EXIT_USAGE


def test_cli_report_without_a_warehouse_says_what_to_do(tmp_path, capsys):
    assert cli.main(["report", "--data-dir", str(tmp_path)]) == cli.EXIT_USAGE
    assert "run `pipeline transform` first" in capsys.readouterr().err
    assert not (tmp_path / "warehouse.duckdb").exists()  # no empty file left behind
