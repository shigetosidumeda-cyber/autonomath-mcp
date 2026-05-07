"""Smoke test for the 7 post-manifest tools' sample_arguments fixture.

Companion to ``tests/fixtures/7_post_manifest_tools.json`` (Option B
fixture composition for the 7 tools landed post the v0.3.4 manifest
hold-at-139 boundary, see CLAUDE.md "Wave hardening 2026-05-07").

Each test loads the sample_arguments from the fixture, calls the
tool's underlying ``_*_impl`` (Pydantic schema layer is exercised at
MCP-register time; this asserts the impl accepts the args and returns
a well-formed dict envelope without raising). Some tools intentionally
collapse to a ``db_unavailable`` error envelope on hosts where the
DEEP-39/44/45 ETL has not yet landed — that is still a valid envelope
and the test treats it as PASS.

Constraints honoured (per task brief):
  * NO LLM call inside the tools or the test. Pure SQLite + Python.
  * NO destructive overwrite of existing fixtures.
  * Pydantic schema would accept these args (verified by the same
    Annotated[...] Field constraints used at the MCP register layer).

Run:
    .venv/bin/pytest tests/test_post_manifest_tools_sample_args.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "7_post_manifest_tools.json"


def _load_fixture() -> list[dict[str, Any]]:
    with FIXTURE.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sample_args(tool_name: str) -> dict[str, Any]:
    for row in _load_fixture():
        if row["name"] == tool_name:
            return row["sample_arguments"]
    pytest.fail(f"tool {tool_name!r} not in fixture {FIXTURE}")
    return {}  # unreachable


@pytest.fixture(autouse=True, scope="module")
def _autonomath_env() -> None:
    """Ensure AUTONOMATH_ENABLED is on so tool gates don't short-circuit."""
    os.environ["AUTONOMATH_ENABLED"] = "1"
    os.environ.setdefault("AUTONOMATH_SNAPSHOT_ENABLED", "1")
    os.environ.setdefault("AUTONOMATH_SHIHOSHOSHI_PACK_ENABLED", "1")
    os.environ.setdefault("AUTONOMATH_KOKKAI_ENABLED", "1")
    os.environ.setdefault("AUTONOMATH_MUNICIPALITY_ENABLED", "1")
    os.environ.setdefault("AUTONOMATH_PUBCOMMENT_ENABLED", "1")


def _assert_well_formed_envelope(label: str, body: Any) -> None:
    """Common envelope contract — every post-manifest tool returns a dict
    with at minimum ``_billing_unit`` (success) OR ``error`` (collapse).

    Both shapes are acceptable: the smoke test verifies that the impl
    survives the dummy arg without raising and returns a dict. The
    detailed shape contract is exercised by each tool's dedicated test
    file (test_time_machine_query.py / test_shihoshoshi_dd_pack.py /
    test_kokkai_search.py / test_municipality_search.py /
    test_pubcomment_status.py).
    """
    assert isinstance(body, dict), f"{label}: expected dict, got {type(body).__name__}"
    has_billing = "_billing_unit" in body
    has_error = "error" in body
    assert has_billing or has_error, (
        f"{label}: envelope missing both _billing_unit and error keys: {sorted(body.keys())}"
    )


# ---------------------------------------------------------------------------
# Fixture arity + structure
# ---------------------------------------------------------------------------


def test_fixture_loads_and_has_7_rows() -> None:
    rows = _load_fixture()
    assert len(rows) == 7, f"fixture arity drift: got {len(rows)}, want 7"
    names = {r["name"] for r in rows}
    expected = {
        "query_at_snapshot_v2",
        "query_program_evolution",
        "shihoshoshi_dd_pack_am",
        "search_kokkai_utterance",
        "search_shingikai_minutes",
        "search_municipality_subsidies",
        "get_pubcomment_status",
    }
    assert names == expected, f"name set mismatch: {names ^ expected}"


def test_fixture_rows_carry_required_keys() -> None:
    required = {
        "name",
        "spec",
        "module",
        "impl",
        "law",
        "fence",
        "wave",
        "manifest_state",
        "sample_arguments",
    }
    for row in _load_fixture():
        missing = required - set(row.keys())
        assert not missing, f"{row.get('name')!r} missing keys: {missing}"


# ---------------------------------------------------------------------------
# 7 per-tool smoke tests
# ---------------------------------------------------------------------------


def test_query_at_snapshot_v2_sample_args() -> None:
    from jpintel_mcp.mcp.autonomath_tools.time_machine_tools import (
        _query_at_snapshot_impl,
    )

    body = _query_at_snapshot_impl(**_sample_args("query_at_snapshot_v2"))
    _assert_well_formed_envelope("query_at_snapshot_v2", body)


def test_query_program_evolution_sample_args() -> None:
    from jpintel_mcp.mcp.autonomath_tools.time_machine_tools import (
        _query_program_evolution_impl,
    )

    body = _query_program_evolution_impl(**_sample_args("query_program_evolution"))
    _assert_well_formed_envelope("query_program_evolution", body)
    # Sanity: the 12-month grid surfaces a months list (success path).
    if "error" not in body:
        assert isinstance(body.get("months"), list), "months must be a list"
        assert len(body["months"]) == 12, "must surface 12 monthly pivots"


def test_shihoshoshi_dd_pack_am_sample_args() -> None:
    from jpintel_mcp.mcp.autonomath_tools.shihoshoshi_tools import (
        _shihoshoshi_dd_pack_impl,
    )

    body = _shihoshoshi_dd_pack_impl(**_sample_args("shihoshoshi_dd_pack_am"))
    _assert_well_formed_envelope("shihoshoshi_dd_pack_am", body)
    # Sanity: §3 disclaimer must surface on success path.
    if "error" not in body:
        assert "_disclaimer" in body, "司法書士 §3 disclaimer required"
        assert "司法書士法" in body["_disclaimer"], "§3 fence text missing"


def test_search_kokkai_utterance_sample_args() -> None:
    from jpintel_mcp.mcp.autonomath_tools.kokkai_tools import (
        _search_kokkai_utterance_impl,
    )

    body = _search_kokkai_utterance_impl(**_sample_args("search_kokkai_utterance"))
    _assert_well_formed_envelope("search_kokkai_utterance", body)


def test_search_shingikai_minutes_sample_args() -> None:
    from jpintel_mcp.mcp.autonomath_tools.kokkai_tools import (
        _search_shingikai_minutes_impl,
    )

    body = _search_shingikai_minutes_impl(**_sample_args("search_shingikai_minutes"))
    _assert_well_formed_envelope("search_shingikai_minutes", body)


def test_search_municipality_subsidies_sample_args() -> None:
    from jpintel_mcp.mcp.autonomath_tools.municipality_tools import (
        _search_municipality_subsidies_impl,
    )

    body = _search_municipality_subsidies_impl(**_sample_args("search_municipality_subsidies"))
    _assert_well_formed_envelope("search_municipality_subsidies", body)


def test_get_pubcomment_status_sample_args() -> None:
    from jpintel_mcp.mcp.autonomath_tools.pubcomment_tools import (
        _get_pubcomment_status_impl,
    )

    body = _get_pubcomment_status_impl(**_sample_args("get_pubcomment_status"))
    _assert_well_formed_envelope("get_pubcomment_status", body)
