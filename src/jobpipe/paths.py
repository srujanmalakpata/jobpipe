"""Data paths: one directory holds bronze, the warehouse and reports."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project_path(env_var: str, default: Path) -> Path:
    return Path(os.environ.get(env_var, default)).resolve()


DBT_PROJECT_DIR = _project_path("JOBPIPE_DBT_PROJECT_DIR", PROJECT_ROOT / "transform")
FIXTURES_DIR = _project_path("JOBPIPE_FIXTURES_DIR", PROJECT_ROOT / "fixtures" / "responses")
CONFIG_DIR = _project_path("JOBPIPE_CONFIG_DIR", PROJECT_ROOT / "config")


@dataclass(frozen=True)
class DataPaths:
    root: Path

    @classmethod
    def at(cls, root: Path | str) -> DataPaths:
        return cls(Path(root).resolve())

    @property
    def bronze(self) -> Path:
        return self.root / "bronze"

    @property
    def warehouse(self) -> Path:
        return self.root / "warehouse.duckdb"

    @property
    def http_cache(self) -> Path:
        return self.root / "state" / "http_cache"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def dbt_target(self) -> Path:
        return self.root / "dbt" / "target"

    @property
    def dbt_logs(self) -> Path:
        return self.root / "dbt" / "logs"
