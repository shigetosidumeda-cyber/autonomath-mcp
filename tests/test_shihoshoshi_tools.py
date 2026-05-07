"""Smoke + envelope-shape tests for the DEEP-30 司法書士 cohort tool.

Covers the single tool shipped in
``jpintel_mcp.mcp.autonomath_tools.shihoshoshi_tools``:

  - shihoshoshi_dd_pack_am

The contract this tool must hold:

  * ``results`` (list) + ``total`` / ``limit`` / ``offset`` paginated envelope
  * ``commercial_registration`` + ``jurisdiction_check`` +
    ``enforcement_history`` + ``boundary_warnings`` 4-section payload
  * ``_disclaimer`` carrying §3 + §52 + §72 + §1 fence text
  * ``_next_calls`` ≥ 1 compounding hint
  * ``corpus_snapshot_id`` + ``corpus_checksum`` (auditor reproducibility)
  * NO LLM call (verified by absence of any anthropic / openai import)

Skips module-wide if autonomath.db is missing (same convention as
test_wave22_tools.py / test_corporate_layer_tools.py).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_GRAPH = _REPO_ROOT / "graph.sqlite"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))
_GRAPH_PATH = Path(os.environ.get("AUTONOMATH_GRAPH_DB_PATH", str(_DEFAULT_GRAPH)))

if not _DB_PATH.exists() or not _GRAPH_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) or graph.sqlite ({_GRAPH_PATH}) "
        "not present; skipping shihoshoshi suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_SHIHOSHOSHI_PACK_ENABLED", "1")

# server import first to break the autonomath_tools<->server circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.shihoshoshi_tools import (  # noqa: E402
    _shihoshoshi_dd_pack_impl,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def known_houjin_bangou() -> str:
    """A 13-digit 法人番号 present in jpi_houjin_master."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT houjin_bangou FROM jpi_houjin_master "
            "WHERE houjin_bangou IS NOT NULL "
            "  AND length(houjin_bangou) = 13 "
            "LIMIT 1"
        ).fetchone()
        if not row:
            pytest.skip("jpi_houjin_master has no 13-digit rows")
        return row[0]
    finally:
        con.close()


@pytest.fixture(scope="module")
def enforced_houjin_bangou() -> str:
    """A 13-digit 法人番号 with at least 1 row in am_enforcement_detail."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT DISTINCT houjin_bangou FROM am_enforcement_detail "
            "WHERE houjin_bangou IS NOT NULL "
            "  AND length(houjin_bangou) = 13 "
            "LIMIT 1"
        ).fetchone()
        if not row:
            pytest.skip("am_enforcement_detail has no 13-digit houjin rows")
        return row[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Test 1: 1-call return — full 4-section envelope shape.
# ---------------------------------------------------------------------------


def test_one_call_returns_unified_envelope(known_houjin_bangou: str) -> None:
    """1-call envelope: 4 sections + reproducibility + _next_calls."""
    out = _shihoshoshi_dd_pack_impl(houjin_bangou=known_houjin_bangou)
    assert "error" not in out, f"unexpected error: {out.get('error')}"

    # Identifier echo
    assert out["houjin_bangou"] == known_houjin_bangou

    # Standard envelope keys
    assert "results" in out and isinstance(out["results"], list)
    for k in ("total", "limit", "offset"):
        assert k in out and isinstance(out[k], int)

    # 4 distinct sections per DEEP-30 spec
    assert "commercial_registration" in out
    assert "jurisdiction_check" in out
    assert "enforcement_history" in out
    assert "boundary_warnings" in out

    # Reproducibility pair
    assert "corpus_snapshot_id" in out
    assert "corpus_checksum" in out
    assert out["corpus_checksum"].startswith("sha256:")

    # _next_calls is the compound multiplier vector (≥ 1)
    assert "_next_calls" in out and isinstance(out["_next_calls"], list)
    assert len(out["_next_calls"]) >= 1
    for nc in out["_next_calls"]:
        assert "tool" in nc and "rationale" in nc and "compound_mult" in nc

    # results echoes the 4 sections at a glance
    kinds = {r["kind"] for r in out["results"]}
    assert {
        "commercial_registration",
        "jurisdiction_check",
        "enforcement_history",
        "boundary_warnings",
    } <= kinds


# ---------------------------------------------------------------------------
# Test 2: §3 fence — disclaimer must surface §3 + §52 + §72 + §1.
# ---------------------------------------------------------------------------


def test_disclaimer_carries_full_4_fence_text(known_houjin_bangou: str) -> None:
    """`_disclaimer` must surface §3 (司法書士) + §52 + §72 + §1 fence text."""
    out = _shihoshoshi_dd_pack_impl(houjin_bangou=known_houjin_bangou)
    assert "_disclaimer" in out
    d = out["_disclaimer"]
    assert isinstance(d, str)
    assert len(d) >= 80, f"disclaimer too short ({len(d)} chars)"

    # All four 業法 references must surface — the spec gates this
    # explicitly as the §3 boundary 警告.
    assert "§3" in d, "司法書士法 §3 fence missing"
    assert "§52" in d, "税理士法 §52 fence missing"
    assert "§72" in d, "弁護士法 §72 fence missing"
    assert "§1" in d, "行政書士法 §1 fence missing"

    # The §3 substantive prohibition must include 登記 / 供託 / 簡裁
    assert "登記" in d
    assert "供託" in d
    assert "簡裁" in d


# ---------------------------------------------------------------------------
# Test 3: 反社相当 enforcement — when houjin has enforcement rows, surface them.
# ---------------------------------------------------------------------------


def test_enforcement_history_section_for_houjin_with_processings(
    enforced_houjin_bangou: str,
) -> None:
    """enforcement_history surfaces fine/grant_refund/subsidy_exclude rows."""
    out = _shihoshoshi_dd_pack_impl(houjin_bangou=enforced_houjin_bangou)
    assert "error" not in out
    eh = out["enforcement_history"]
    assert eh["houjin_bangou"] == enforced_houjin_bangou
    # all_count is the corpus-level count for this houjin (always >= 1
    # because our fixture picked it from am_enforcement_detail)
    assert eh["all_count"] >= 1
    # The structured slice may be empty if all rows are non-fine kinds; it
    # must still be a list.
    assert isinstance(eh["fine_grant_refund_exclude"], list)
    assert isinstance(eh["recent_5y"], list)
    # Scope note must clarify the corpus boundary (no APPI / 反社 DB).
    assert "個人信用情報" in eh["scope_note"]


# ---------------------------------------------------------------------------
# Test 4: cross_check_jurisdiction integration — section is well-formed.
# ---------------------------------------------------------------------------


def test_cross_check_jurisdiction_integrated(known_houjin_bangou: str) -> None:
    """jurisdiction_check carries registered/invoice/operational + mismatches."""
    out = _shihoshoshi_dd_pack_impl(houjin_bangou=known_houjin_bangou)
    assert "error" not in out
    jc = out["jurisdiction_check"]
    # Registered jurisdiction is always present when master row exists.
    assert "registered" in jc
    assert "invoice_jurisdiction" in jc
    assert "operational" in jc
    assert "mismatches" in jc and isinstance(jc["mismatches"], list)
    assert "mismatch_count" in jc and isinstance(jc["mismatch_count"], int)
    # When the houjin resolves in jpi_houjin_master, the registered slice
    # must carry a prefecture (not None).
    if jc.get("houjin_resolved"):
        assert jc["registered"] is not None
        assert jc["registered"]["prefecture"] is not None


# ---------------------------------------------------------------------------
# Test 5: NO LLM verification — module imports zero LLM SDKs.
# ---------------------------------------------------------------------------


def test_zero_llm_imports_in_shihoshoshi_module() -> None:
    """The shihoshoshi_tools module + its impl path must not import any LLM SDK.

    We assert via static source inspection (the CI guard
    tests/test_no_llm_in_production.py applies the same check codebase-wide,
    but this in-module sentinel keeps the boundary explicit for the
    DEEP-30 surface).
    """
    src_path = (
        _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "shihoshoshi_tools.py"
    )
    src = src_path.read_text(encoding="utf-8")
    # No LLM SDK imports — match feedback_no_operator_llm_api hard rule.
    forbidden_imports = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import claude_agent_sdk",
        "from claude_agent_sdk",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    )
    for needle in forbidden_imports:
        assert needle not in src, f"forbidden LLM token {needle!r} found in shihoshoshi_tools.py"

    # Runtime confirmation: the impl response carries `llm_calls_made: 0`.
    # Use a known houjin if present, else a synthetic 13-digit; either path
    # exercises the same envelope assembly.
    out = _shihoshoshi_dd_pack_impl(houjin_bangou="0000000000000")
    assert "error" not in out, f"impl errored on synthetic input: {out.get('error')}"
    assert out["data_quality"]["llm_calls_made"] == 0


# ---------------------------------------------------------------------------
# Tool-count gate (DEEP-30 acceptance criterion): tool surfaces at default gates.
# ---------------------------------------------------------------------------


class TestShihoshoshiToolCount:
    """DEEP-30 acceptance: shihoshoshi_dd_pack_am at default gates."""

    def test_tool_registered(self) -> None:
        from jpintel_mcp.mcp.server import mcp as _mcp

        tool_names = {t.name for t in _mcp._tool_manager.list_tools()}
        assert (
            "shihoshoshi_dd_pack_am" in tool_names
        ), "shihoshoshi_dd_pack_am not registered at default gates"
