"""Report step: render the analytics marts as static Markdown + HTML.

The report is a pure function of the warehouse contents (no wall-clock timestamps), so
re-running the pipeline on the same bronze data reproduces it byte for byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from jinja2 import Environment, select_autoescape

from jobpipe.paths import DataPaths

REQUIRED_RELATIONS = (
    "staging.stg_bronze__extract_manifests",
    "core.fct_postings",
    "core.dim_company",
    "analytics.mart_weekly_postings_flow",
    "analytics.mart_time_to_close",
    "analytics.mart_skill_demand",
    "analytics.mart_remote_share",
    "analytics.mart_entry_level_share",
)


class ReportError(RuntimeError):
    """The warehouse is missing or has not been built yet."""


@dataclass(frozen=True)
class Table:
    title: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    note: str = ""
    share_columns: tuple[str, ...] = ()  # rendered as percentages with a bar in HTML


@dataclass(frozen=True)
class ReportData:
    headline: dict[str, Any]
    tables: list[Table]


def _query(con: duckdb.DuckDBPyConnection, sql: str) -> tuple[list[str], list[tuple]]:
    rel = con.execute(sql)
    columns = [d[0] for d in rel.description]
    return columns, rel.fetchall()


def _check_built(con: duckdb.DuckDBPyConnection, warehouse: Path) -> None:
    present = {
        f"{schema}.{name}"
        for schema, name in con.execute(
            "select table_schema, table_name from information_schema.tables"
        ).fetchall()
    }
    missing = [r for r in REQUIRED_RELATIONS if r not in present]
    if missing:
        raise ReportError(
            f"{warehouse} has no {', '.join(missing)}; run `pipeline transform` first "
            "(or `pipeline run`)"
        )


def collect(warehouse: Path) -> ReportData:
    if not warehouse.exists():
        raise ReportError(
            f"no warehouse at {warehouse}; run `pipeline transform` first (or `pipeline run`)"
        )
    # Not read_only: when dbt ran in this same process, DuckDB refuses a second connection
    # to the file with a different configuration. The report only issues SELECTs.
    con = duckdb.connect(str(warehouse))
    try:
        _check_built(con, warehouse)
        (modes, first, last, boards, ok, failed, rejected) = con.execute(
            """
            select string_agg(distinct fetch_mode, ', ' order by fetch_mode),
                   min(snapshot_date), max(snapshot_date), count(distinct company_key),
                   count(*) filter (where status = 'ok'), count(*) filter (where status <> 'ok'),
                   coalesce(sum(reject_count), 0)
            from staging.stg_bronze__extract_manifests
            """
        ).fetchone()
        (postings, spells, open_now) = con.execute(
            "select count(distinct posting_key), count(*), count(*) filter (where is_open)"
            " from core.fct_postings"
        ).fetchone()
        headline = {
            "fetch_modes": modes,
            "first_snapshot": first,
            "last_snapshot": last,
            "boards": boards,
            "ok_snapshots": ok,
            "failed_snapshots": failed,
            "rejected_records": rejected,
            "distinct_postings": postings,
            "spells": spells,
            "open_postings": open_now,
        }

        tables: list[Table] = []

        def add(title: str, sql: str, note: str = "", shares: tuple[str, ...] = ()) -> None:
            cols, rows = _query(con, sql)
            tables.append(Table(title, cols, rows, note, shares))

        add(
            "Extraction health by board",
            """select company_name, source, board, ok_snapshots, failed_snapshots,
                      rejected_records, postings_seen
               from core.dim_company order by company_name""",
            "Failed snapshots never close postings; contract rejects are quarantined in bronze.",
        )
        add(
            "Postings opened and closed per week",
            """select week_start, boards_observed, listed_postings, opened, reopened, closed,
                      net_change
               from analytics.mart_weekly_postings_flow order by week_start""",
            "The first week opens nothing by construction: postings already listed when "
            "observation began are left-censored.",
        )
        add(
            "Time to close (days, snapshot resolution)",
            """select role_family, closed_spells, still_open_spells, median_days_to_close,
                      mean_days_to_close, p75_days_to_close
               from analytics.mart_time_to_close
               order by role_family = 'all_roles' desc, closed_spells desc, role_family""",
            "Measured first_seen -> closed_at. Still-open spells are right-censored, so "
            "these figures understate how long the longest-lived postings stay up.",
        )
        add(
            "Top skills across all postings",
            """select skill, category, postings_with_skill, share_of_postings, open_with_skill,
                      share_of_open
               from analytics.mart_skill_demand where role_family = 'all_roles'
               order by postings_with_skill desc, skill limit 15""",
            "Keyword matches against the seed vocabulary (transform/seeds/skill_vocabulary.csv).",
            ("share_of_postings", "share_of_open"),
        )
        add(
            "Top 3 skills per role family",
            """select role_family, rank_in_family, skill, postings_with_skill, share_of_postings
               from analytics.mart_skill_demand
               where role_family <> 'all_roles' and rank_in_family <= 3
               order by role_family, rank_in_family, skill""",
            shares=("share_of_postings",),
        )
        add(
            "Remote share of listed postings",
            """select week_start, listed_postings, remote_postings, hybrid_postings,
                      onsite_postings, remote_share, hybrid_share
               from analytics.mart_remote_share order by week_start""",
            shares=("remote_share", "hybrid_share"),
        )
        add(
            "Entry-level share of listed postings (interns, co-ops, junior, new grad)",
            """select week_start, listed_postings, intern_postings, entry_level_postings,
                      entry_level_share
               from analytics.mart_entry_level_share where role_family = 'all_roles'
               order by week_start""",
            shares=("entry_level_share",),
        )
        return ReportData(headline, tables)
    finally:
        con.close()


def _fmt(value: Any, share: bool = False) -> str:
    if value is None:
        return "-"
    if share:
        return f"{float(value) * 100:.1f}%"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _cells(table: Table, row: tuple) -> list[str]:
    return [_fmt(v, c in table.share_columns) for c, v in zip(table.columns, row, strict=True)]


def _md_cell(text: str) -> str:
    """Make a value safe inside a Markdown table cell (pipes split cells, newlines rows)."""
    return " ".join(text.replace("\\", "\\\\").replace("|", "\\|").split())


def mode_banner(fetch_modes: str | None) -> tuple[str, str] | None:
    """(css class, text) of the banner describing where the data came from, if any."""
    modes = set((fetch_modes or "").split(", ")) - {""}
    if modes == {"fixture"}:
        return "banner", "Fixture mode: every company and posting in this report is synthetic."
    if len(modes) > 1:
        return "banner warn", (
            f"Warning: mixed fetch modes ({', '.join(sorted(modes))}). This warehouse combines "
            "synthetic fixture boards with real ones, so totals and weekly figures mix both. "
            "Rebuild live data in its own --data-dir."
        )
    return None


def render_markdown(data: ReportData) -> str:
    h = data.headline
    lines = [
        "# jobpipe report",
        "",
        f"Data from **{h['boards']} boards**, snapshots **{h['first_snapshot']}** to "
        f"**{h['last_snapshot']}** (fetch mode: {h['fetch_modes']}).",
        "",
        f"- Distinct postings: {h['distinct_postings']} ({h['spells']} listing spells, "
        f"{h['open_postings']} open at the latest snapshot)",
        f"- Board snapshots: {h['ok_snapshots']} ok, {h['failed_snapshots']} failed; "
        f"extract-contract rejects: {h['rejected_records']}",
        "",
    ]
    banner = mode_banner(h["fetch_modes"])
    if banner:
        lines += [f"> {banner[1]}", ""]
    for table in data.tables:
        lines += [f"## {table.title}", ""]
        if table.note:
            lines += [f"_{table.note}_", ""]
        lines.append("| " + " | ".join(_md_cell(c) for c in table.columns) + " |")
        lines.append("|" + "---|" * len(table.columns))
        lines += [
            "| " + " | ".join(_md_cell(c) for c in _cells(table, row)) + " |" for row in table.rows
        ]
        lines.append("")
    return "\n".join(lines)


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>jobpipe report</title>
<style>
  :root { --fg: #1f2328; --muted: #57606a; --line: #d0d7de; --bar: #2f81f7; --bg: #ffffff; }
  @media (prefers-color-scheme: dark) {
    :root { --fg: #e6edf3; --muted: #8d96a0; --line: #30363d; --bar: #4493f8; --bg: #0d1117; }
  }
  body { font: 15px/1.5 system-ui, sans-serif; color: var(--fg); background: var(--bg);
         max-width: 980px; margin: 0 auto; padding: 24px 16px; }
  h1 { margin-bottom: 4px; } h2 { margin-top: 32px; font-size: 1.15rem; }
  .muted, .note { color: var(--muted); }
  .banner { border: 1px solid var(--line); padding: 8px 12px; border-radius: 6px; }
  .warn { border-color: #d29922; }
  .scroll { overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
  th, td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left; }
  td.share { min-width: 120px; }
  .bar { display: inline-block; height: 8px; background: var(--bar); border-radius: 2px;
         margin-right: 6px; vertical-align: middle; }
</style>
</head>
<body>
<h1>jobpipe report</h1>
<p class="muted">{{ h.boards }} boards, snapshots {{ h.first_snapshot }} to {{ h.last_snapshot }}
 (fetch mode: {{ h.fetch_modes }}). {{ h.distinct_postings }} distinct postings,
 {{ h.spells }} listing spells, {{ h.open_postings }} open at the latest snapshot.
 {{ h.ok_snapshots }} ok / {{ h.failed_snapshots }} failed board snapshots;
 extract-contract rejects: {{ h.rejected_records }}.</p>
{% if banner %}
<p class="{{ banner[0] }}">{{ banner[1] }}</p>
{% endif %}
{% for t in tables %}
<h2>{{ t.title }}</h2>
{% if t.note %}<p class="note">{{ t.note }}</p>{% endif %}
<div class="scroll"><table>
<thead><tr>{% for c in t.columns %}<th>{{ c }}</th>{% endfor %}</tr></thead>
<tbody>
{% for row in t.rows %}<tr>
{% for c, v in zip(t.columns, row) %}{% if c in t.share_columns and v is not none %}
<td class="share"><span class="bar" style="width: {{ '%.0f' % (v * 80) }}px"></span>
{{- fmt(v, True) }}</td>
{% else %}<td>{{ fmt(v) }}</td>{% endif %}{% endfor %}
</tr>{% endfor %}
</tbody></table></div>
{% endfor %}
</body>
</html>
"""


def render_html(data: ReportData) -> str:
    env = Environment(autoescape=select_autoescape(default=True), trim_blocks=True)
    template = env.from_string(HTML_TEMPLATE)
    return template.render(
        h=data.headline,
        tables=data.tables,
        banner=mode_banner(data.headline["fetch_modes"]),
        fmt=_fmt,
        zip=zip,
    )


def write_report(paths: DataPaths) -> tuple[Path, Path]:
    data = collect(paths.warehouse)
    paths.reports.mkdir(parents=True, exist_ok=True)
    md_path = paths.reports / "report.md"
    html_path = paths.reports / "report.html"
    md_path.write_text(render_markdown(data), encoding="utf-8")
    html_path.write_text(render_html(data), encoding="utf-8")
    return md_path, html_path
