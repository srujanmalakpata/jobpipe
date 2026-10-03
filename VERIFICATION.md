# jobpipe verification

- **Measurement date:** 2026-10-03. Clean-run setup excludes existing `.venv`, `data/`,
  dbt `target/`/`logs/`, caches, `__pycache__` and `infra/gcp/.terraform`.
- **Environment:** a shared 4-vCPU Linux container (x86_64, Ubuntu 24.04), running other
  concurrent jobs, so wall-clock times are noisy. Python 3.11.15, uv 0.8.17,
  dbt-core 1.12.5, dbt-duckdb 1.11.0, DuckDB 1.5.6, httpx 0.28.1, pydantic 2.13.5,
  pytest 8.4.2, ruff 0.16.10, Terraform 1.9.8 and 1.16.5 (google provider 6.50.0),
  Docker (local daemon).
- Commands use the project root unless noted. Results below record the tests and
  measurements on the date above; live and cloud coverage limits are explicit.

| # | Command | Result | Key output |
|---|---|---|---|
| 1 | `uv sync --frozen --extra dev` | PASS | project-local `.venv` from `uv.lock` (`Installed 69 packages`) |
| 2 | `uv run ruff check .` | PASS | `All checks passed!` |
| 3 | `uv run ruff format --check .` | PASS | `33 files already formatted` |
| 4 | `ruff check jobpipe` + `ruff format --check jobpipe` from the containing directory (ruff 0.16.7) | PASS | `All checks passed!`, `33 files already formatted` |
| 5 | `uv run pytest -q` | PASS | `107 passed in 229.40s` (90 unit + 17 integration) |
| 6 | `uv run pytest -q -m "not integration"` | PASS | `90 passed, 17 deselected in 1.06s` |
| 7 | `uv run pipeline run --data-dir <tmp>` (fixtures) | PASS | `extract: 29/30 board snapshots ok, 372 postings landed, 2 rejected`; injected `lever:tidewaterlogistics 2026-08-24: failed ... (HTTP 500)`; `dbt succeeded (pass=103, success=26)`. From `run_results.json`: 129 nodes = 7 seeds, 8 views, 9 tables, 2 incremental, 103 data tests (95 generic + 8 singular), 0 warn/error |
| 8 | Same command again on the same data dir, then `cmp` of the two reports (3 data dirs) | PASS | report byte-identical each time and across the 3 dirs, and identical to `docs/sample_report.md`; the integration test also asserts every core/mart table is unchanged |
| 9 | Timing: fresh `pipeline run`, then a repeat run, 3 times (fresh dirs) | PASS | fresh 23.2 / 27.1 / 27.2 s; repeat 16.0 / 17.8 / 19.0 s |
| 10 | Where the repeat-run gap comes from: `pipeline transform` on the built dir with and without dbt's `partial_parse.msgpack` (2 pairs) | PASS | 12.6 vs 15.8 s and 12.9 vs 21.9 s. Most of the gap is dbt's parse cache, not incremental processing: staging still rescans all of bronze. Other repeat-run measurements showed no gap; treat these timings as noisy |
| 11 | `python scripts/generate_fixtures.py` twice + `md5sum` diff of `fixtures/` | PASS | identical output, and identical to the committed files (31 files, 524 KB on disk) |
| 12 | Warehouse counts after the fixture run (DuckDB queries) | PASS | 115 distinct postings, 116 spells (1 reopen), 68 open at the last snapshot, 1 spell with an unparsed snapshot, 365 `fct_posting_daily` rows, 427 posting-skill pairs; 13 distinct locations (10 Canada, 3 United States, 0 Unknown) |
| 13 | Same timestamp, changed content: `pytest -k test_edited_fixture_with_same_timestamp_is_reprocessed` (retitles Maple Ledger 5200001 and swaps another id on the already-landed 2026-09-07, same count; data dir name contains a `'`) | PASS | incremental tables equal `--full-refresh`; `fct_postings` shows "Totally New Title Analyst"; the swapped-in id is in `fct_posting_daily`; dbt compiles with a quote in the bronze path |
| 14 | Mutation check for 13: `landing_id` without the content hash (temporary edit), same test | PASS (test failed as expected) | `pipeline run` exits 1: `assert_daily_fact_reconciles_with_bronze ... FAIL 2`. File restored afterwards |
| 15 | `pytest -k test_classification_rule_change_without_full_refresh_is_detected` (copy of the dbt project, analyst rule removed, incremental build) | PASS | build fails on `assert_daily_fact_reconciles_with_bronze`; `--full-refresh` clears it |
| 16 | Mutation check: pre-hooks disabled (temporary edit), `pytest -k empty` | PASS (test failed as expected) | `assert_daily_fact_reconciles_with_bronze: Got 1 result`; file restored afterwards |
| 17 | `pytest -k test_invalidating_a_partial_snapshot_recomputes_the_board` | PASS | after `pipeline invalidate` of Northwind 2026-08-24, posting 4100001 closes on 08-31 instead of 08-24; incremental equals `--full-refresh` |
| 18 | **Live, once (earlier code version):** `uv run pipeline -v run --live --data-dir <tmp>` with `config/boards.live.example.yaml` | PASS | 4/4 boards ok on the first attempt (Greenhouse airbnb 154, Greenhouse stripe 714, Lever palantir 319, Ashby ramp 157 postings; total 1,344), 0 contract rejects, all 4 responses carried an `ETag`; `dbt build` passed on the live data. The live payloads are not retained, and the live run is not repeated. Coverage of the current live-path changes (content hash, `data/live` default, mixed-mode guard, per-board drop guard) uses mocked HTTP only |
| 19 | Pattern calibration on that live bronze (no new network calls): `pipeline transform --full-refresh` after editing seeds | PASS | postings matching "Go" 275 -> 164; "Accessibility" 381 -> 5; country "Unknown" 787 -> 118; role family `other` 423 -> 141 (of 1,344). Point-in-time numbers on earlier code; not reproducible from the repo. The geo resolver has changed since, so the 118 no longer describes the current code |
| 20 | `terraform fmt -check -recursive && terraform init -backend=false -input=false && terraform validate` in `infra/gcp` (Terraform 1.16.5) | PASS | `Success! The configuration is valid.` (google provider v6.50.0) |
| 21 | Same with Terraform 1.9.8 (the version pinned in CI) | PASS | `Success! The configuration is valid.` |
| 22 | `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` and `actionlint` | PASS | jobs: `lint`, `test`, `dbt-build`, `terraform`, `docker`; actionlint reports nothing |
| 23 | `docker build --no-cache -t jobpipe:dev .` | PASS | built in 103 s; image 1.34 GB on disk (`DISK USAGE`, unpacked layers) / 349 MB content size, both per `docker images` |
| 24 | `docker run --rm --network none -v <tmp>:/data jobpipe:dev run` (2 runs) | PASS | `dbt succeeded (pass=103, success=26)` in 39.6 s and 32.7 s; the container's `report.md` is byte-identical to `docs/sample_report.md`. `docker run ... report` with an empty `/data` prints `error: no warehouse at /data/warehouse.duckdb; run \`pipeline transform\` first` |
| 25 | GitHub Actions workflow on GitHub | NOT_RUN | no hosted workflow run is recorded; the YAML parses and lints (row 22) and each job's commands pass locally (rows 2-3, 5, 7-8, 20-21, 23-24) |
| 26 | `dbt build --target bigquery` / BigQuery dispatch macros / BigQuery dataset naming | NOT_RUN | no GCP project, credentials or `dbt-bigquery` install; known incompatibilities are listed in [DESIGN.md, decision 9](DESIGN.md#9-cloud-option-validated-not-applied) |
| 27 | `terraform plan` / `apply` | NOT_RUN | validated, never deployed; no cloud account |
| 28 | Rendering the README Mermaid diagram | NOT_RUN | not rendered locally; GitHub renders Mermaid natively |

## Bugs found by testing and fixed

| Bug | Fix | Regression test |
|---|---|---|
| Incremental facts keyed only on `extracted_at` miss changed content under the same timestamp | Manifest `content_hash` contributes to `landing_id`; reconciliation compares rows, not counts | rows 13-14 |
| Reconciliation misses classification rule changes | Compare classification columns and report the affected partitions | row 15 |
| Live and fixture runs share `./data`; mixed data is labelled synthetic | Default live runs to `data/live`, guard mixed fetch modes and derive the banner from exact fetch modes | `test_live_mode_defaults_to_its_own_data_dir`, `test_cli_refuses_to_mix_live_and_fixture_data`, `test_banner_depends_on_exact_fetch_modes` |
| The drop guard lacks per-board configuration and recovery tools | Per-board `max_drop_ratio`, `--accept-drop` and `pipeline invalidate`. A same-day re-run with a stricter guard keeps the earlier `ok` snapshot by design | `test_board_level_drop_ratio_overrides_the_default`, `test_drop_guard_can_be_overridden_per_board`, `test_sharp_drop_versus_previous_snapshot_is_not_trusted`, row 17, `test_invalidate_keeps_evidence_and_marks_the_day_failed`, `test_cli_invalidate_marks_a_landed_day` |
| "Toronto, CA" resolves to California; "Bengaluru, IN" resolves to Indiana | Resolve ambiguous country/state codes using known cities | `assert_geo_resolution_behaves` over `seeds/geo_location_cases.csv` (20 cases, ambiguities included), rows 7 and 5 |
| Negative `backoff_cap_seconds` and unbounded `max_attempts` are accepted | Validate retry policy bounds at configuration load | `test_invalid_configs_are_rejected` |
| A quote in the bronze path breaks SQL | Escape bronze paths in SQL | row 13 (data dir contains `'`) |
| Markdown cells containing `\|` or newlines break tables; `report` before `transform` fails without guidance | Escape table cells and give a missing-warehouse message | `test_markdown_cells_cannot_break_the_table`, `test_cli_report_without_a_warehouse_says_what_to_do`, row 24 |

## Scripted scenarios proven by the integration tests

- Posting `greenhouse:northwindrobotics:4100001`: spell 2026-08-10 -> 2026-08-17, `closed_at`
  2026-08-24, `days_to_close` 14, not left-censored.
- Posting `greenhouse:mapleledger:5200001`: two spells (08-03..08-10 closed 08-17; 08-31..09-07 open).
- Aurora ML posting retitled mid-life: one spell, latest title "Senior Machine Learning Engineer".
- The same Aurora posting is listed with a blank title on 08-31 (a contract reject below the
  20% gate): it stays one spell 08-03..09-07, open, with `unparsed_snapshots = 1`.
- Tidewater HTTP 500 on 2026-08-24: zero postings closed on that date; a posting listed
  08-10..08-31 keeps one unbroken spell.
- The blank-title Ashby record is quarantined in `bronze/rejects/`, and the unlisted job is
  filtered out; neither reaches the warehouse.
- The provider-side duplicate is landed in bronze and deduplicated in the warehouse.
- `fct_postings` equals an independent Python oracle computed from the bronze files
  (including manifest reject ids).
- Six single-day runs **out of order** (08-17 landed after 08-24) give tables identical to
  one full build, and identical again after `--full-refresh`.
- A day re-landed as an empty board (mocked live run) gives the same incremental tables as
  `--full-refresh`.
- A landed fixture edited under the same timestamp, a classification rule change, and an
  invalidated day (rows 13, 15, 17).

## Unit-level checks

- `contract_failed` keeps `rejects.jsonl` with field errors; an unusable envelope keeps
  `response.body`; stale diagnostics are removed on re-landing.
- The manifest `content_hash` is stable across identical re-landings and differs for a
  retitle or a swapped id with the same count.
- A redirect loop (`TooManyRedirects`) fails fast without retries and only fails its own
  board; an `OSError` while landing one board does not stop the others.
- An empty 200 after a 20-posting snapshot is `contract_failed` (drop guard), and is
  accepted for one run with `--accept-drop`; small boards skip the check; a per-board
  `max_drop_ratio` of 0.3 rejects a 50% drop that the global 80% guard accepts.
- A same-day failure after a good run reports "kept an earlier good snapshot" with its
  posting count.
- Board tokens with `?`, `#`, `=`, spaces or backslashes, non-numeric policy values,
  `backoff_base > backoff_cap`, a negative cap, and `max_attempts` outside 1-10 are
  rejected at config load; whitespace-only titles are rejected for every provider.

## Measurement caveats

- All timings come from a shared container and are indicative only.
- Fixture data is synthetic. Only aggregate counts from the single live run are recorded;
  live payloads were never added to the repository, and those counts are a point-in-time
  snapshot from an earlier code version.
