"""Tests for rule_engine_check — R9 unified rule engine MCP tool.

Covers the 3 mandatory cases from the design doc
(analysis_wave18/_r9_unified_rule_engine_2026-04-25.md):

  1. program A + program B 併給可否 — compat_matrix resolves the verdict
  2. rules conflict (one corpus says deny, another says allow) →
     error.code='rules_conflict' with both rule_ids surfaced
  3. unknown bucket (the 4,849 compat:unknown rows) → judgment='unknown'
     + reason explicit

Run:

    .venv/bin/python -m pytest tests/test_rule_engine.py -x --tb=short
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))

if not _DB_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) not present; skipping rule_engine tests. "
        "Set AUTONOMATH_DB_PATH to point at a snapshot.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_RULE_ENGINE_ENABLED", "1")

# server must be imported first to break circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.rule_engine_tool import (  # noqa: E402
    _rule_engine_check_impl,
)


# ---------------------------------------------------------------------------
# Test data discovery — find real (program_a_id, program_b_id) pairs by status
# from the live am_compat_matrix so the tests stay correct as data evolves.
# ---------------------------------------------------------------------------


def _find_pair_with_status(status: str) -> tuple[str, str]:
    conn = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT program_a_id, program_b_id FROM am_compat_matrix "
            "WHERE compat_status = ? LIMIT 1",
            (status,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        pytest.skip(f"no am_compat_matrix row with status={status!r}")
    return row[0], row[1]


# ---------------------------------------------------------------------------
# Case 1 — program A + B 併給可否, compat_matrix resolves the verdict.
# ---------------------------------------------------------------------------


def test_rule_engine_compat_pair_resolution_incompatible():
    """A pair flagged compat_status='incompatible' must yield judgment='deny'
    with at least one am_compat_matrix evidence row.
    """
    pa, pb = _find_pair_with_status("incompatible")
    res = _rule_engine_check_impl(program_id=pa, alongside_programs=[pb])

    # No error envelope expected (this is a clean DENY, not a conflict).
    assert res.get("error") is None or res["error"].get("code") != "rules_conflict"
    assert res["judgment"] == "deny", (
        f"expected judgment=deny for incompatible pair {pa!r}+{pb!r}, "
        f"got {res['judgment']!r}"
    )
    # Evidence must include at least one am_compat_matrix row.
    sources = {ev["source"] for ev in res["evidence"]}
    assert "am_compat_matrix" in sources, (
        f"expected am_compat_matrix in evidence sources, got {sources}"
    )
    # confidence high for deny verdicts.
    assert res["confidence"] == 1.0
    # data_quality must surface the partial-coverage number.
    dq = res["data_quality"]
    assert "exclusion_join_coverage_pct" in dq
    assert isinstance(dq["exclusion_join_coverage_pct"], (int, float))
    assert 0.0 <= dq["exclusion_join_coverage_pct"] <= 100.0
    assert dq["rules_total_corpus"] == 49247
    # disclaimer present.
    assert "_disclaimer" in res
    assert "景表法" in res["_disclaimer"] or "社労士" in res["_disclaimer"]


def test_rule_engine_compat_pair_resolution_compatible():
    """A pair flagged compat_status='compatible' must yield judgment='allow'."""
    pa, pb = _find_pair_with_status("compatible")
    res = _rule_engine_check_impl(program_id=pa, alongside_programs=[pb])

    # The pair could be 'compatible' in compat_matrix yet 'case_by_case' in another
    # row of the same matrix for an inverse direction, but since PK is (a,b),
    # the lookup for our specific pair stabilises on 'compatible'.
    assert res["judgment"] in ("allow", "review"), (
        f"expected allow/review for compatible pair, got {res['judgment']!r}"
    )
    sources = {ev["source"] for ev in res["evidence"]}
    assert "am_compat_matrix" in sources


# ---------------------------------------------------------------------------
# Case 2 — rules conflict: one corpus deny, another allow → rules_conflict.
# ---------------------------------------------------------------------------


def test_rule_engine_rules_conflict_returns_explicit_error():
    """Construct a synthetic conflict by stubbing the unified-rule fetch with
    two rows for the same (program_id, pair_id) where one says deny (exclude)
    and one says allow (compat:compatible). The engine must NOT silently merge —
    it must return error.code='rules_conflict' with BOTH rule_ids in evidence.
    """
    pa = "program:test:pair_a"
    pb = "program:test:pair_b"

    # Build two synthetic sqlite3.Row-like dicts. We use a tiny class so
    # ``row["col"]`` access works the same as for sqlite3.Row.
    class _FakeRow(dict):
        def __getitem__(self, key):  # type: ignore[override]
            return super().__getitem__(key)

    deny_row = _FakeRow({
        "rule_id": "exclusion:fake-deny-001",
        "source_table": "jpi_exclusion_rules",
        "scope_program_id": pa,
        "pair_program_id": pb,
        "kind": "exclude",
        "severity": "critical",
        "message_ja": "synthetic-deny: A and B forbidden",
        "source_url": "https://example.test/deny",
    })
    allow_row = _FakeRow({
        "rule_id": "compat:fake-allow-001",
        "source_table": "am_compat_matrix",
        "scope_program_id": pa,
        "pair_program_id": pb,
        "kind": "compat:compatible",
        "severity": "info",
        "message_ja": "synthetic-allow: A and B OK",
        "source_url": "https://example.test/allow",
    })

    def fake_fetch(conn, program_id, pair_id):
        if pair_id == pb:
            return [deny_row, allow_row]
        return []

    with patch(
        "jpintel_mcp.mcp.autonomath_tools.rule_engine_tool._fetch_rules_for_pair",
        side_effect=fake_fetch,
    ):
        res = _rule_engine_check_impl(
            program_id=pa, alongside_programs=[pb]
        )

    # Conflict must surface.
    err = res.get("error")
    assert isinstance(err, dict), f"expected error envelope, got {res}"
    assert err.get("code") == "rules_conflict", (
        f"expected code=rules_conflict, got {err}"
    )
    # judgment label set to 'conflict' on the top level.
    assert res.get("judgment") == "conflict"
    # Both rule_ids must be present in the evidence — never silently merged.
    rule_ids = {ev["rule_id"] for ev in res.get("evidence", [])}
    assert "exclusion:fake-deny-001" in rule_ids, (
        f"deny rule_id missing from conflict evidence: {rule_ids}"
    )
    assert "compat:fake-allow-001" in rule_ids, (
        f"allow rule_id missing from conflict evidence: {rule_ids}"
    )
    # _disclaimer must mention 景表法 or 人 review.
    assert "_disclaimer" in res
    msg = res["_disclaimer"]
    assert "review" in msg.lower() or "社労士" in msg or "景表法" in msg


# ---------------------------------------------------------------------------
# Case 3 — unknown bucket: judgment='unknown' + explicit reason.
# ---------------------------------------------------------------------------


def test_rule_engine_unknown_bucket_returns_unknown_with_reason():
    """A pair where compat_matrix.compat_status='unknown' (the 4,849-row dark
    bucket) must yield judgment='unknown' AND a non-empty reason explaining why.
    """
    pa, pb = _find_pair_with_status("unknown")
    res = _rule_engine_check_impl(program_id=pa, alongside_programs=[pb])

    # Must NOT be a hard error envelope.
    err = res.get("error")
    if err is not None:
        # Acceptable: subsystem_unavailable / db_unavailable; never rules_conflict here.
        assert err.get("code") != "rules_conflict"

    assert res["judgment"] == "unknown", (
        f"expected unknown for compat:unknown pair, got {res['judgment']!r}"
    )
    # reason must be present and explicit (not empty / not None).
    assert res.get("reason"), (
        f"unknown verdict must surface reason, got reason={res.get('reason')!r}"
    )
    # confidence is low for unknown.
    assert res["confidence"] <= 0.5
    # The unknown evidence row must be in the trace.
    has_unknown = any(
        ev["rule_kind"] == "compat:unknown" for ev in res["evidence"]
    )
    assert has_unknown, (
        "expected at least one compat:unknown rule in evidence trace"
    )


# ---------------------------------------------------------------------------
# Bonus: missing program_id → error envelope (smoke test for the input guard).
# ---------------------------------------------------------------------------


def test_rule_engine_missing_program_id_returns_error():
    res = _rule_engine_check_impl(program_id="")
    err = res.get("error")
    assert isinstance(err, dict)
    assert err.get("code") == "missing_required_arg"
    assert err.get("field") == "program_id"
