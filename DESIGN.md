# jobpipe design

## Goals and non-goals

**Goals:** an ELT pipeline supporting:
idempotent extraction, raw-data retention, dimensional modelling, incremental models,
lifecycle (SCD2-style) tracking, data-quality tests, orchestration, infrastructure as code
and CI. It must run fully offline and be reproducible.

**Non-goals:** a scraper (only documented public JSON APIs are used), distributed scale,
dashboards-as-a-service, or a real cloud deployment.

## Key decisions

### 1. ELT with a bronze lake, not ETL

The extractor writes provider payloads **verbatim** into JSONL and does nothing else
except check them against a contract. All normalisation happens in SQL (dbt).

- *Rationale:* model fixes, including skill-regex corrections, can rebuild from bronze
  without re-fetching. Raw historical responses cannot be recreated later.
- *Alternative:* normalise in Python and load clean rows. It is simpler at first, but any
  mapping bug is baked into stored data, and history cannot be rebuilt.
- *Trade-off:* staging has to parse JSON in SQL (`json_extract_string`) and keeps the
  provider quirks visible there (Greenhouse double-escapes its HTML; Lever splits the
  description across three fields).

### 2. Hive-partitioned JSONL + a manifest per board snapshot

`bronze/postings/source=greenhouse/board=x/snapshot_date=2026-08-03/part-0.jsonl`. One
partition (source, board, day) is the unit of idempotency: re-landing it replaces its
files instead of adding rows. Each *file* is replaced atomically (`write tmp; os.replace`);
the partition as a whole is not (see crash safety below).

A missing posting is evidence of closure only after a successful fetch. Every attempt
writes a manifest with `status` (`ok` / `failed` / `contract_failed`), and the lifecycle
model only uses `ok` snapshots. Its invariants are:

- a failed fetch can never close postings (tested with an injected HTTP 500);
- a later failure never overwrites an earlier successful snapshot of the same day.

Snapshot handling requires evidence of whether a posting is still listed:

- **Listed but unparseable is still listed.** A record that fails the contract (while the
  board as a whole stays under the 20% reject gate) is quarantined, but its id goes into
  the manifest's `rejected_posting_ids`. The lifecycle model counts it as observed, so one
  bad record does not close a posting and reopen it a week later. Spell attributes come
  from the last *parsed* observation; an island made only of rejects is dropped.
- **A collapse in volume is suspect.** A 200 with an empty or truncated list is valid
  JSON, but it would close the whole board. If the count drops by more than
  `max_drop_ratio` (80% by default; a board can override it in the boards file) against
  the previous successful snapshot (of at least 10 postings), the snapshot is
  `contract_failed`. A board that really shrank is accepted for one run with
  `--accept-drop source:board`, so the guard stays on for every other board and for the
  next run. The baseline is always the last *ok* snapshot, so without that flag a board
  that genuinely shrank would keep failing.
- **A partial snapshot can be withdrawn.** A truncation smaller than the guard lands as
  `ok`. A same-day re-run cannot replace it with a failure (a later failure never
  overwrites a good day), so `pipeline invalidate --board s:b --date D --reason ...` marks
  that day `contract_failed`, moves its postings file to `rejects/` as evidence, and the
  next `dbt build` recomputes the board without it.
- **Failures keep their evidence.** Contract failures write their rejects (with field
  errors) to `bronze/rejects/`, and an unusable envelope keeps the raw body as
  `response.body`, so a `contract_failed` board can be debugged from disk.

Crash safety is per file, not per partition: postings are written before the manifest, so
a crash in between leaves new postings next to the old manifest.
`assert_bronze_reconciles_with_manifests` fails on that state, and re-running the day
repairs it.

JSONL rather than Parquet for bronze: payloads are nested and change shape over time, and
JSONL keeps them byte-for-byte as received. DuckDB reads it with explicit column types
and Hive partition columns. A `snapshot_date` filter could skip files, but no model uses
one yet (see decision 4). Parquet would be the right choice for silver/gold if the data
outgrew DuckDB's in-memory scans.

### 3. Fixture mode goes through the real HTTP client

Fixtures are served by an `httpx` transport, so fixture runs use the same
`PoliteClient`, retry loop, contract and bronze writer as live runs; only the network
layer is swapped. The tests inject `httpx.MockTransport` the same way, plus a fake clock
and sleeper, so retry and backoff behaviour is asserted exactly and instantly. An autouse
fixture makes any real network call raise.

Fixtures are **generated** by `scripts/generate_fixtures.py` (deterministic seed) instead
of being hand-written or recorded from real boards. That gives realistic volume without
committing anyone's real postings, and it scripts the edge cases the tests need.

### 4. Two incremental facts with different strategies

| Model | Grain | Strategy | Detects new work by |
|---|---|---|---|
| `fct_posting_daily` | posting x snapshot | `delete+insert` on `(company_key, snapshot_date)`, i.e. partition overwrite | manifest `(board, day, landing_id)` not yet loaded |
| `fct_postings` | posting spell | `delete+insert` on `company_key`, i.e. recompute a whole board | md5 watermark of the board's `ok` `(snapshot_date, landing_id)` list changed |

`landing_id` is `extracted_at` plus a sha256 **content hash** of the landed posting lines
and rejected ids, written into the manifest by the extractor. Fixture runs pin
`extracted_at` to noon of the snapshot date, so a timestamp alone cannot detect edited
fixtures or different responses re-landed under the same timestamp. The content hash
ensures those partitions are reprocessed. An integration test edits a landed fixture
(a retitle plus a swapped id, same count) and checks that the incremental result equals
`--full-refresh`.

Appending rows newer than `max(snapshot_date)` breaks on same-day re-runs (live
re-lands) and **late or backfilled days**. Spells come from gaps-and-islands over the
*sequence* of successful snapshots. A backfilled day can merge two spells or split one, so the affected board has to be
recomputed from its full history. The watermark makes that happen automatically. The
integration test lands the six fixture days one run at a time, out of order, and asserts
the result equals a single full build.

**Empty partitions.** dbt's `delete+insert` deletes only the keys present in the
new batch. If a day is re-landed with zero postings (or a recomputed board yields zero
spells), the batch has no rows for it and stale rows survive without a pre-hook.
Each fact has a pre-hook (`transform/macros/lifecycle.sql`) that first
deletes every loaded row that no longer matches the current bronze state: daily rows whose
`(board, day, landing_id)` is not the current ok landing, and spells whose board
watermark changed. A singular test reconciles `fct_posting_daily` with the deduplicated
bronze partitions, and an integration test re-lands a day as empty and compares the
incremental result with `--full-refresh`.

**Reconciliation compares content, not counts.** `assert_daily_fact_reconciles_with_bronze`
compares `fct_posting_daily` row by row (symmetric `EXCEPT ALL` over every stored column)
with what a full rebuild would produce from the current ok bronze partitions, and reports
the (board, day) partitions that differ. Counting rows per partition misses a retitle,
a swapped id or a reclassification.

**Incremental saves writes, not scans.** The staging views read the whole bronze lake on
every run and classify every historical posting; only the facts' writes are incremental.
At this size a repeat run is a few seconds faster than a fresh one, and most of that is
dbt's partial-parse cache (measured in [VERIFICATION.md](VERIFICATION.md)), not less SQL.
Incremental staging keyed on pending manifests, or pending dates pushed into `read_json`
as a partition filter, could reduce scans at larger scale.

*Trade-off:* recomputing a board is O(postings x snapshots of that board). That is fine
here. A bounded recompute window (only spells touching changed dates) or a merge on
spell keys could reduce work at larger scale.

*Known gap:* changing the role-family rules or the seniority macro does not reprocess
already-loaded partitions of `fct_posting_daily`. The reconciliation test above fails,
names the partitions, and the CLI prints a `--full-refresh` hint (an integration test edits a rule and checks exactly this). Skill
vocabulary changes need nothing: the skill bridge and mart are plain tables rebuilt every
run. Putting a rules checksum into `landing_id` would make it automatic, at the cost of
reprocessing every partition whenever a rule changes.

### 5. SCD2-style "spells" instead of dbt snapshots

dbt snapshots append forward from the current state of the source at each run. Even with
`strategy='timestamp'` and `snapshot_date` as `updated_at`, a late or backfilled day cannot
split or merge spells that were already written, and hard deletes (`invalidate_hard_deletes`)
are stamped with the run time, so they cannot tell a failed fetch from a real closure.
Recomputing a board's spells from its full snapshot sequence reproduces history exactly,
in any landing order. So the lifecycle is modelled explicitly: `first_seen`, `last_seen`, `closed_at`
(next successful snapshot), `spell_number` for re-openings, `is_left_censored`.
Attributes are taken as of the spell's last observation, so a mid-spell retitle does not
create a new spell. That choice favours "how long was this job listed" over full
attribute history; per-attribute SCD2 rows would be the extension.

### 6. Rules as seeds, tested with executable examples

Skill vocabulary, role-family rules and geography aliases are CSV seeds, editable without
touching SQL. Regex is easy to get wrong, so `skill_pattern_cases.csv` holds examples
("go-to-market" must not match Go, "you will excel in this role" must not match Excel,
"unity in diversity" must not match Unity, "series c funded" must not match C) and a
singular dbt test fails if any pattern disagrees. `title_classification_cases.csv` does
the same for role families and seniority. The seniority macro checks intern / co-op
first, then staff / principal / director, then senior / lead, then entry keywords, so
"Senior Associate" is senior and "Associate Director" is staff_plus rather than entry
level (which would have inflated the entry-level share), while "Senior ... Intern" is an
intern. `geo_location_cases.csv` does the same for location parsing, including the
ambiguous two-letter codes ("Toronto, CA" is Canada, "San Francisco, CA" is California). The synthetic
fixtures build titles from the same keywords the classifier looks for, so these case
files, not the end-to-end tests, are what actually test classification.

In the single live run, an overly broad "Go" pattern matched "go onsite" and "go to market",
and "Accessibility" matched the EEO boilerplate
"our hiring process is accessible to everyone". Tightening the patterns (and adding
those phrases as test cases) cut Go matches from 275 to 164 postings and Accessibility
from 381 to 5. Adding geo aliases cut unknown-country postings from 787 to 118 (on
the code of that time; location parsing has been rewritten since). These are one
point-in-time sample that was not kept, so they cannot be reproduced from the repository.

### 7. Statistics: censoring is explicit

The weekly flow mart does not count left-censored spells as "opened" (their opening is not
observed), and `mart_time_to_close` reports closed, still-open and excluded counts next to
median, mean and p75. `days_to_close` is an upper bound at snapshot resolution; the
censoring counts document the bias in those estimates.

### 8. Orchestration: one CLI, no scheduler

`pipeline run` = extract -> `dbt build` (in-process via `dbtRunner`) -> report, with exit
codes (0 ok, 1 dbt failed, 2 nothing extracted). Airflow or Dagster would be overkill for
three steps on one machine; cron or a CI schedule calling `pipeline run --live` is the
natural deployment. The steps are idempotent, so a scheduler's retries are safe.

### 9. Cloud option: validated, not applied

`infra/gcp` declares a GCS bronze bucket (uniform access, public-access prevention,
versioning, Nearline after 30 days, noncurrent versions deleted after 30 days; deleting
live bronze is opt-in and off by default, because bronze is the only copy of history), a
BigQuery `job_market_raw` dataset with day-partitioned, clustered `bronze_postings` and
`bronze_manifests` tables, and one dataset per dbt layer (`job_market`,
`job_market_staging`, `_intermediate`, `_core`, `_analytics`, `_reference`). On BigQuery,
`generate_schema_name` writes each layer to `<dataset>_<layer>`, so dbt only ever writes
to datasets Terraform declared. The service account gets object admin on the bucket,
`bigquery.dataEditor` on exactly those datasets and `bigquery.jobUser` on the project, and
no key (use impersonation or workload identity federation). Dialect-specific SQL goes
through `adapter.dispatch` macros (`json_str`, `regex_contains`, `week_start`,
`days_between`, `to_utc_timestamp`).

What is still missing before `dbt build --target bigquery` could work. None of it has been
run; these are known incompatibilities, and the list may be incomplete:

- **Loading:** staging reads bronze with DuckDB's `read_json` (`bronze_read()`, with
  `hive_partitioning`, `TIMESTAMPTZ`, `JSON` and `VARCHAR[]` column types). On BigQuery it
  would become `source()`s on the two raw tables, filled from GCS by a `bq load` step that
  does not exist yet.
- **Aggregates:** `count(*) filter (where ...)` / `max(...) filter (where ...)` (BigQuery
  has no `FILTER`; use `countif` / `if` inside the aggregate) in `fct_postings`,
  `dim_company`, every analytics mart and `macros/geo.sql`; `median` and `quantile_cont`
  in `mart_time_to_close` (BigQuery: `approx_quantiles` or analytic `percentile_cont`);
  `arg_max` / `arg_min` in `dim_company`, `dim_location`, `mart_skill_demand` and
  `macros/geo.sql` (BigQuery: `max_by` / `min_by` or `array_agg(... limit 1)`); `bool_or`
  in `mart_skill_demand` (`logical_or`); `md5` in `int_postings__classified` and the
  watermark (BigQuery returns BYTES, so wrap it in `to_hex`).
- **Functions and syntax:** `regexp_replace(..., 'g')` with a 4th flags argument in
  `macros/text.sql`; `concat_ws`, the JSONPath wildcard `$.lists[*].content` with
  `array_to_string`, and `epoch_ms` in `stg_lever__postings`; `string_split_regex`, list
  indexing, `len` and the `range()` table function in `macros/geo.sql`; `split_part` in
  `dim_location`; `unnest` in the select list in `stg_bronze__unparsed_postings`; the `[]`
  list literal in `stg_bronze__extract_manifests`; `union all by name` in
  `int_postings__unioned` (use explicit column lists); `select * exclude (...)` in two
  marts (BigQuery spells it `except`); `except all` in
  `assert_daily_fact_reconciles_with_bronze` (BigQuery only has `except distinct`); the
  `timestamptz` cast in `to_utc_timestamp`.
- **Probably fine, unverified:** `qualify` (BigQuery accepts it, historically only
  alongside `where` / `group by` / `having`), `group by grouping sets`, `string_agg ...
  order by`, `is distinct from`, and the correlated `delete` statements in the pre-hooks.

Already portable: the `adapter.dispatch` macros above, and string casts written as
`{{ dbt.type_string() }}` (STRING on BigQuery). The cheapest way to make this list
mechanical would be a CI job that runs `dbt compile` and parses every compiled model with
a BigQuery SQL parser; that check is not implemented.

## Alternatives considered

| Choice | Alternative | Rationale |
|---|---|---|
| DuckDB | PostgreSQL / SQLite | DuckDB reads JSONL lakes directly, is columnar, and needs no server |
| dbt-core | hand-written SQL scripts | dbt gives lineage, tests, incremental materialisations, docs |
| JSONL bronze | Parquet bronze | Raw fidelity for nested, drifting payloads (Parquet is a good silver format) |
| pydantic contract | JSON Schema files | Same checks with less code; errors point to fields |
| In-process dbtRunner | `subprocess dbt` | Faster and easier to test; the report needs a non-read-only connection because of it |
| Regex skills | NLP / embeddings | Explainable and testable; NLP or embeddings would add model dependencies |

## Possible extensions

1. Kaplan-Meier time-to-close (handles right-censoring) and confidence intervals.
2. A rules checksum in `landing_id` (so rule changes reprocess automatically instead of
   failing the reconciliation test); dbt unit tests for the gaps-and-islands SQL;
   incremental staging so repeat runs stop rescanning all of bronze.
3. Port the remaining DuckDB-only SQL behind dispatch macros, load bronze to GCS + BigQuery,
   and run the `bigquery` target in a GCP project with CI using workload identity.
4. A schedule (GitHub Actions cron) for small live runs with alerting on `failed` manifests.
5. Lever pagination (`skip`/`limit`) for very large boards; Greenhouse `updated_at`-based
   change detection.
