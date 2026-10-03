"""Transform step: run ``dbt build`` (seeds, models, tests) against the DuckDB warehouse."""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from jobpipe.paths import DBT_PROJECT_DIR, DataPaths


@dataclass(frozen=True)
class DbtOutcome:
    success: bool
    statuses: Counter[str] = field(default_factory=Counter)
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        counts = ", ".join(f"{k}={v}" for k, v in sorted(self.statuses.items()))
        return f"dbt {'succeeded' if self.success else 'FAILED'} ({counts})"


def dbt_environment(paths: DataPaths) -> dict[str, str]:
    """Environment variables the dbt project reads via env_var()."""
    return {
        "JOBPIPE_DUCKDB_PATH": str(paths.warehouse),
        "JOBPIPE_BRONZE_DIR": str(paths.bronze),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }


def run_dbt(
    paths: DataPaths,
    command: str = "build",
    *,
    full_refresh: bool = False,
    extra_args: list[str] | None = None,
    quiet: bool = True,
    project_dir: Path = DBT_PROJECT_DIR,
) -> DbtOutcome:
    """Invoke dbt in-process. Bronze must already exist (run extract first)."""
    from dbt.cli.main import dbtRunner  # imported lazily: dbt import is slow

    paths.root.mkdir(parents=True, exist_ok=True)
    os.environ.update(dbt_environment(paths))
    args = [
        command,
        "--project-dir",
        str(project_dir),
        "--profiles-dir",
        str(project_dir),
        "--target-path",
        str(paths.dbt_target),
        "--log-path",
        str(paths.dbt_logs),
        "--no-use-colors",
    ]
    if quiet:
        args.insert(0, "--quiet")
    if full_refresh:
        args.append("--full-refresh")
    args += extra_args or []

    result = dbtRunner().invoke(args)
    statuses: Counter[str] = Counter()
    failures: list[str] = []
    for node_result in getattr(result.result, "results", None) or []:
        status = str(node_result.status)
        statuses[status] += 1
        if status in {"error", "fail"}:
            failures.append(f"{node_result.node.name}: {node_result.message}")
    if result.exception is not None:
        failures.append(f"dbt raised {type(result.exception).__name__}: {result.exception}")
    return DbtOutcome(bool(result.success), statuses, failures)
