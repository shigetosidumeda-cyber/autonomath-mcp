"""Tier A smoke tests - 5 hand-verified seeds against the live DB.

Per memory ``feedback_no_fake_data``: only 5 of the eventual 30 seeds are
LLM-curated. The 25 remaining (TA003-TA004, TA007-TA029) are gated to user
hand curation - LLM gold-answer fabrication = customer 詐欺 risk.

These tests run the ``gold_sql`` from ``tier_a_seed.yaml`` directly against
the live DBs and assert the gold value matches. They DO NOT exercise the
MCP server (that's done by ``run_eval.py``); they exclusively validate the
seed data integrity, which is the load-bearing invariant.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

THIS_DIR = Path(__file__).resolve().parent

with (THIS_DIR / "tier_a_seed.yaml").open(encoding="utf-8") as _fh:
    _SEEDS = yaml.safe_load(_fh)["questions"]


# Map seed IDs to which DB their gold_sql targets.
_DB_FOR_SEED = {
    "TA001": "autonomath_db_ro",
    "TA002": "autonomath_db_ro",
    "TA005": "autonomath_db_ro",
    "TA006": "autonomath_db_ro",
    "TA030": "jpintel_db_ro",
}


@pytest.mark.parametrize("seed", _SEEDS, ids=lambda s: s["id"])
def test_tier_a_gold_sql_matches_gold_value(
    seed: dict, autonomath_db_ro, jpintel_db_ro
) -> None:
    """Each Tier A gold_sql, executed live, must return gold_value."""
    db_fixture_name = _DB_FOR_SEED.get(seed["id"])
    assert db_fixture_name, f"unmapped seed id: {seed['id']}"
    conn = {"autonomath_db_ro": autonomath_db_ro, "jpintel_db_ro": jpintel_db_ro}[
        db_fixture_name
    ]
    rows = list(conn.execute(seed["gold_sql"]))
    assert rows, f"{seed['id']}: gold_sql returned 0 rows"
    actual = rows[0][seed["gold_field"]]
    expected = seed["gold_value"]
    # Numeric coercion: SQLite REAL columns surface as float (e.g. 240.0),
    # but YAML ints stay int. Compare numerically when both look numeric.
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        assert float(actual) == float(expected), (
            f"{seed['id']}: expected {seed['gold_field']}={expected!r}, "
            f"got {actual!r}"
        )
    else:
        assert str(actual) == str(expected), (
            f"{seed['id']}: expected {seed['gold_field']}={expected!r}, "
            f"got {actual!r}"
        )


def test_tier_a_seed_count_minimum() -> None:
    """At least 5 seeds wired so harness has signal at all."""
    assert len(_SEEDS) >= 5, f"only {len(_SEEDS)} seeds wired (need >= 5)"


def test_tier_a_seed_schema() -> None:
    """Every seed declares the fields run_eval.py expects."""
    required = {
        "id",
        "question",
        "tool",
        "arguments",
        "gold_value",
        "gold_field",
        "gold_sql",
        "gold_source_url",
    }
    for seed in _SEEDS:
        missing = required - set(seed.keys())
        assert not missing, f"{seed.get('id', '?')}: missing fields {missing}"
