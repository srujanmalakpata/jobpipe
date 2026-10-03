"""Board configuration: which public job boards to extract and how politely to fetch them."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields, replace
from pathlib import Path

import yaml

SUPPORTED_SOURCES = ("greenhouse", "lever", "ashby")

# Board tokens end up in a URL path and in a Hive partition directory name, so only allow
# the characters real provider tokens use (no '/', '?', '#', '=', spaces, dots, ...).
BOARD_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Bound provider load and retry duration; unbounded 2**attempt can also overflow a float.
MAX_ATTEMPTS_CEILING = 10


class ConfigError(ValueError):
    """Raised when a boards file is malformed."""


@dataclass(frozen=True)
class FetchPolicy:
    """Politeness, resilience and data-quality settings shared by every request.

    ``max_drop_ratio``: if a board's posting count falls by more than this fraction compared
    with its previous successful snapshot (and that snapshot had at least
    ``drop_check_min_postings`` postings), the response is treated as suspect
    (``contract_failed``) instead of closing most of the board. ``None`` disables the check,
    e.g. to accept a board that really did close almost everything. A board can override it
    in the boards file, and ``--accept-drop`` disables it for one board for one run.
    """

    min_interval_seconds: float = 1.0
    max_attempts: int = 4
    backoff_base_seconds: float = 1.0
    backoff_cap_seconds: float = 30.0
    timeout_seconds: float = 20.0
    max_reject_ratio: float = 0.2
    max_drop_ratio: float | None = 0.8
    drop_check_min_postings: int = 10


def _coerce_policy(path: Path, defaults: dict[str, object]) -> FetchPolicy:
    """Build a FetchPolicy from YAML values, checking types and ranges up front."""
    values: dict[str, object] = {}
    for f in fields(FetchPolicy):
        if f.name not in defaults:
            continue
        raw = defaults[f.name]
        if raw is None and f.name == "max_drop_ratio":
            values[f.name] = None
            continue
        want = int if f.name in {"max_attempts", "drop_check_min_postings"} else float
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ConfigError(f"{path}: defaults.{f.name} must be a number, got {raw!r}")
        if want is int and int(raw) != raw:
            raise ConfigError(f"{path}: defaults.{f.name} must be a whole number, got {raw!r}")
        values[f.name] = want(raw)
    policy = FetchPolicy(**values)
    if not 1 <= policy.max_attempts <= MAX_ATTEMPTS_CEILING:
        raise ConfigError(
            f"{path}: defaults.max_attempts must be between 1 and {MAX_ATTEMPTS_CEILING}"
        )
    if policy.timeout_seconds <= 0:
        raise ConfigError(f"{path}: defaults.timeout_seconds must be > 0")
    if min(policy.min_interval_seconds, policy.drop_check_min_postings) < 0:
        raise ConfigError(f"{path}: interval and drop-check settings must be >= 0")
    if not 0 <= policy.backoff_base_seconds <= policy.backoff_cap_seconds:
        raise ConfigError(
            f"{path}: backoff must satisfy 0 <= backoff_base_seconds <= backoff_cap_seconds"
        )
    for name in ("max_reject_ratio", "max_drop_ratio"):
        _check_ratio(path, f"defaults.{name}", getattr(policy, name))
    return policy


def _check_ratio(path: Path, name: str, ratio: object) -> None:
    if ratio is None:
        return
    if isinstance(ratio, bool) or not isinstance(ratio, int | float) or not 0 <= ratio <= 1:
        raise ConfigError(f"{path}: {name} must be between 0 and 1 (or null), got {ratio!r}")


@dataclass(frozen=True)
class BoardConfig:
    """One company job board on one provider.

    ``overrides_drop_ratio`` / ``max_drop_ratio``: a per-board replacement for the policy's
    drop guard (``max_drop_ratio: null`` on a board disables it for that board only)."""

    source: str
    board: str
    company: str
    overrides_drop_ratio: bool = False
    max_drop_ratio: float | None = None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.board}"

    def drop_ratio(self, policy: FetchPolicy) -> float | None:
        """The drop-guard threshold that applies to this board."""
        return self.max_drop_ratio if self.overrides_drop_ratio else policy.max_drop_ratio


@dataclass(frozen=True)
class PipelineConfig:
    boards: tuple[BoardConfig, ...]
    policy: FetchPolicy


def load_config(path: Path) -> PipelineConfig:
    """Parse a boards YAML file (see config/boards.fixtures.yaml) into typed config."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or not isinstance(raw.get("boards"), list):
        raise ConfigError(f"{path}: expected a mapping with a 'boards' list")

    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ConfigError(f"{path}: 'defaults' must be a mapping")
    unknown = set(defaults) - set(FetchPolicy.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"{path}: unknown defaults {sorted(unknown)}")
    policy = _coerce_policy(Path(path), defaults)

    boards: list[BoardConfig] = []
    seen: set[str] = set()
    for i, entry in enumerate(raw["boards"]):
        try:
            board = BoardConfig(
                source=str(entry["source"]).strip().lower(),
                board=str(entry["board"]).strip(),
                company=str(entry.get("company") or entry["board"]).strip(),
                overrides_drop_ratio="max_drop_ratio" in entry,
                max_drop_ratio=entry.get("max_drop_ratio"),
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ConfigError(f"{path}: boards[{i}] needs 'source' and 'board'") from exc
        _check_ratio(Path(path), f"boards[{i}].max_drop_ratio", board.max_drop_ratio)
        if board.max_drop_ratio is not None:
            board = replace(board, max_drop_ratio=float(board.max_drop_ratio))
        if board.source not in SUPPORTED_SOURCES:
            raise ConfigError(
                f"{path}: boards[{i}] source {board.source!r} not in {SUPPORTED_SOURCES}"
            )
        if not BOARD_TOKEN.fullmatch(board.board):
            raise ConfigError(f"{path}: boards[{i}] has an invalid board token {board.board!r}")
        if board.key in seen:
            raise ConfigError(f"{path}: duplicate board {board.key}")
        seen.add(board.key)
        boards.append(board)
    return PipelineConfig(boards=tuple(boards), policy=policy)


def accept_drops(config: PipelineConfig, board_keys: list[str]) -> PipelineConfig:
    """Disable the drop guard for the named boards (``source:board``), for one run only."""
    known = {b.key for b in config.boards}
    unknown = sorted(set(board_keys) - known)
    if unknown:
        raise ConfigError(f"--accept-drop: {unknown} not in the configured boards")
    boards = tuple(
        replace(b, overrides_drop_ratio=True, max_drop_ratio=None) if b.key in board_keys else b
        for b in config.boards
    )
    return replace(config, boards=boards)
