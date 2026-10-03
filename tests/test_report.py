"""Report rendering (pure functions over ReportData)."""

from __future__ import annotations

from jobpipe.report import ReportData, Table, _fmt, mode_banner, render_html, render_markdown

HEADLINE = {
    "fetch_modes": "live",
    "first_snapshot": "2026-10-03",
    "last_snapshot": "2026-10-03",
    "boards": 1,
    "ok_snapshots": 1,
    "failed_snapshots": 0,
    "rejected_records": 0,
    "distinct_postings": 2,
    "spells": 2,
    "open_postings": 2,
}


def sample(name: str = "Acme", modes: str = "live") -> ReportData:
    return ReportData(
        {**HEADLINE, "fetch_modes": modes},
        [
            Table(
                "Top skills",
                ["company", "skill", "share"],
                [(name, "SQL", 0.5), (name, "Python", None)],
                note="a note",
                share_columns=("share",),
            )
        ],
    )


def test_format_values():
    assert _fmt(None) == "-"
    assert _fmt(0.1234, share=True) == "12.3%"
    assert _fmt(2.25) == "2.2"
    assert _fmt(14) == "14"


def test_markdown_table_and_no_fixture_banner_for_live_data():
    md = render_markdown(sample())
    assert "| company | skill | share |" in md
    assert "| Acme | SQL | 50.0% |" in md
    assert "| Acme | Python | - |" in md
    assert "synthetic" not in md


def test_html_escapes_provider_text():
    html = render_html(sample("<script>alert(1)</script>"))
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert 'class="bar" style="width: 40px"' in html


def test_markdown_cells_cannot_break_the_table():
    md = render_markdown(sample("Pipe | Co\nLine two"))
    assert "| Pipe \\| Co Line two | SQL | 50.0% |" in md


def test_banner_depends_on_exact_fetch_modes():
    assert "synthetic" in render_markdown(sample(modes="fixture"))
    assert mode_banner("live") is None
    mixed = render_markdown(sample(modes="fixture, live"))
    assert "every company and posting in this report is synthetic" not in mixed
    assert "Warning: mixed fetch modes (fixture, live)" in mixed
    assert "mixed fetch modes" in render_html(sample(modes="fixture, live"))
