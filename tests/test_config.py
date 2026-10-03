from pathlib import Path

import pytest

from jobpipe.config import ConfigError, load_config


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "boards.yaml"
    path.write_text(text)
    return path


def test_fixture_config_loads(fixture_config):
    assert len(fixture_config.boards) == 5
    assert {b.source for b in fixture_config.boards} == {"greenhouse", "lever", "ashby"}
    assert fixture_config.policy.min_interval_seconds == 0.0


def test_defaults_and_company_fallback(tmp_path):
    config = load_config(write(tmp_path, "boards:\n  - {source: Lever, board: acme}\n"))
    (board,) = config.boards
    assert (board.source, board.board, board.company, board.key) == (
        "lever",
        "acme",
        "acme",
        "lever:acme",
    )
    assert config.policy.max_attempts == 4


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("boards:\n  - {source: workday, board: acme}\n", "not in"),
        ("boards:\n  - {source: lever, board: ../etc}\n", "invalid board token"),
        ("boards:\n  - {source: lever, board: 'a?b=1'}\n", "invalid board token"),
        ("boards:\n  - {source: lever, board: 'a b'}\n", "invalid board token"),
        ("boards:\n  - {source: lever, board: 'a#b'}\n", "invalid board token"),
        ("boards:\n  - {source: lever, board: 'a\\b'}\n", "invalid board token"),
        ("defaults: {timeout_seconds: fast}\nboards: []\n", "must be a number"),
        ("defaults: {max_attempts: 2.5}\nboards: []\n", "whole number"),
        ("defaults: {max_attempts: 0}\nboards: []\n", "max_attempts must be between 1 and 10"),
        ("defaults: {max_attempts: 2000}\nboards: []\n", "max_attempts must be between 1 and 10"),
        ("defaults: {backoff_cap_seconds: -1}\nboards: []\n", "backoff must satisfy"),
        (
            "defaults: {backoff_base_seconds: 5, backoff_cap_seconds: 2}\nboards: []\n",
            "backoff must satisfy",
        ),
        ("defaults: {drop_check_min_postings: -1}\nboards: []\n", "must be >= 0"),
        ("boards:\n  - {source: lever, board: a, max_drop_ratio: 1.5}\n", "between 0 and 1"),
        ("boards:\n  - {source: lever, board: a, max_drop_ratio: lots}\n", "between 0 and 1"),
        ("defaults: {max_reject_ratio: 2}\nboards: []\n", "between 0 and 1"),
        ("defaults: [1, 2]\nboards: []\n", "'defaults' must be a mapping"),
        ("boards:\n  - {source: lever, board: a}\n  - {source: lever, board: a}\n", "duplicate"),
        ("defaults: {speed: 3}\nboards: []\n", "unknown defaults"),
        ("boards:\n  - {source: lever}\n", "needs 'source' and 'board'"),
        ("nothing: here\n", "'boards' list"),
    ],
)
def test_invalid_configs_are_rejected(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text))


def test_policy_values_are_coerced_and_drop_check_can_be_disabled(tmp_path):
    config = load_config(
        write(
            tmp_path,
            "defaults: {timeout_seconds: 30, max_attempts: 3.0, max_drop_ratio: null}\n"
            "boards:\n  - {source: ashby, board: Acme_Co-2}\n",
        )
    )
    assert config.policy.timeout_seconds == 30.0 and isinstance(
        config.policy.timeout_seconds, float
    )
    assert config.policy.max_attempts == 3 and isinstance(config.policy.max_attempts, int)
    assert config.policy.max_drop_ratio is None
    assert config.boards[0].board == "Acme_Co-2"


def test_board_level_drop_ratio_overrides_the_default(tmp_path):
    config = load_config(
        write(
            tmp_path,
            "defaults: {max_drop_ratio: 0.8}\n"
            "boards:\n"
            "  - {source: lever, board: a}\n"
            "  - {source: lever, board: b, max_drop_ratio: 0.3}\n"
            "  - {source: lever, board: c, max_drop_ratio: null}\n",
        )
    )
    assert [b.drop_ratio(config.policy) for b in config.boards] == [0.8, 0.3, None]
