"""Smoke + envelope-shape tests for the P12 §4.8 corporate-layer tools.

Covers the three tools shipped in
``jpintel_mcp.mcp.autonomath_tools.corporate_layer_tools``:

  - get_houjin_360_am
  - list_edinet_disclosures
  - search_invoice_by_houjin_partial

The contract every corporate-layer tool must hold:

  * ``results`` (list) + ``total`` / ``limit`` / ``offset`` paginated envelope
  * ``_next_calls`` list with at least 1 compounding hint
  * ``corpus_snapshot_id`` + ``corpus_checksum`` for auditor reproducibility
  * ``_disclaimer`` field on the two §52 sensitive surfaces
    (list_edinet_disclosures is pointer-only — no disclaimer)

Skips module-wide if autonomath.db is missing (same convention as
test_wave22_tools.py).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date
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
        "not present; skipping corporate_layer suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_CORPORATE_LAYER_ENABLED", "1")

# server import first to break the autonomath_tools<->server circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.corporate_layer_tools import (  # noqa: E402
    _get_houjin_360_impl,
    _invoice_is_active,
    _list_edinet_disclosures_impl,
    _search_invoice_by_houjin_partial_impl,
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
def known_invoice_name() -> str:
    """A normalized_name fragment present in jpi_invoice_registrants."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT normalized_name FROM jpi_invoice_registrants "
            "WHERE normalized_name IS NOT NULL "
            "  AND length(normalized_name) > 4 "
            "LIMIT 1"
        ).fetchone()
        if not row:
            pytest.skip("jpi_invoice_registrants has no name rows")
        # Use first 3 chars as the partial search seed — almost always
        # produces a hit because we picked the seed from the table itself.
        return row[0][:3]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Envelope-shape helpers
# ---------------------------------------------------------------------------


def _assert_envelope_shape(out: dict, *, with_disclaimer: bool = True) -> None:
    """Every corporate-layer result must carry the same minimal envelope."""
    assert isinstance(out, dict), f"expected dict, got {type(out)}"
    assert "results" in out, f"results missing: {list(out)[:5]}"
    assert isinstance(out["results"], list), "results must be list"
    for k in ("total", "limit", "offset"):
        assert k in out, f"{k} missing"
        assert isinstance(out[k], int), f"{k} must be int"
    assert "_next_calls" in out, "_next_calls missing"
    assert isinstance(out["_next_calls"], list), "_next_calls must be list"
    assert len(out["_next_calls"]) >= 1, "must have ≥1 compound hint"
    for nc in out["_next_calls"]:
        assert isinstance(nc, dict)
        assert "tool" in nc
        assert "rationale" in nc
        assert "compound_mult" in nc
    assert "corpus_snapshot_id" in out, "corpus_snapshot_id missing"
    assert "corpus_checksum" in out, "corpus_checksum missing"
    assert out["corpus_checksum"].startswith("sha256:"), "checksum prefix"
    if with_disclaimer:
        assert "_disclaimer" in out, "_disclaimer missing for sensitive tool"
        assert isinstance(out["_disclaimer"], str)
        assert len(out["_disclaimer"]) > 30


# ---------------------------------------------------------------------------
# 1) get_houjin_360_am
# ---------------------------------------------------------------------------


class TestGetHoujin360Am:
    def test_happy_path_known_bangou(self, known_houjin_bangou: str) -> None:
        out = _get_houjin_360_impl(houjin_bangou=known_houjin_bangou)
        assert "error" not in out, f"unexpected error: {out.get('error')}"
        _assert_envelope_shape(out, with_disclaimer=True)
        assert out["houjin_bangou"] == known_houjin_bangou
        # master_info should be present when the bangou is from jpi_houjin_master
        assert out["master_info"] is not None
        assert out["master_info"]["houjin_bangou"] == known_houjin_bangou
        # Counts are integers (may be 0 — no row required)
        assert isinstance(out["enforcement_count"], int)
        assert isinstance(out["adoption_count"], int)
        assert isinstance(out["related_programs_count"], int)

    def test_with_t_prefix(self, known_houjin_bangou: str) -> None:
        """T-prefix should be stripped transparently."""
        out = _get_houjin_360_impl(houjin_bangou=f"T{known_houjin_bangou}")
        assert "error" not in out
        assert out["houjin_bangou"] == known_houjin_bangou

    def test_invalid_bangou(self) -> None:
        out = _get_houjin_360_impl(houjin_bangou="not-13-digits")
        assert "error" in out
        assert out["error"]["code"] == "invalid_enum"

    def test_missing_arg(self) -> None:
        out = _get_houjin_360_impl(houjin_bangou="")
        assert "error" in out
        assert out["error"]["code"] == "missing_required_arg"


# ---------------------------------------------------------------------------
# 2) list_edinet_disclosures
# ---------------------------------------------------------------------------


class TestListEdinetDisclosures:
    def test_happy_path_houjin_bangou(self, known_houjin_bangou: str) -> None:
        out = _list_edinet_disclosures_impl(houjin_bangou=known_houjin_bangou)
        assert "error" not in out, f"unexpected error: {out.get('error')}"
        # No disclaimer — pointer-only tool, NOT sensitive.
        _assert_envelope_shape(out, with_disclaimer=False)
        assert out["houjin_bangou"] == known_houjin_bangou
        assert out["sec_code"] is None
        # Pointer envelope has at least the human URL + API doc URL.
        assert len(out["results"]) >= 2
        kinds = {r["kind"] for r in out["results"]}
        assert "edinet_search_human" in kinds
        assert "edinet_documents_api" in kinds
        for r in out["results"]:
            assert r["license"] == "public_domain"
            assert "edinet" in r["url"].lower()

    def test_happy_path_sec_code(self) -> None:
        out = _list_edinet_disclosures_impl(sec_code="7203")
        assert "error" not in out
        assert out["sec_code"] == "7203"
        # Search URL includes the sec_code as ekey.
        human = next(r for r in out["results"] if r["kind"] == "edinet_search_human")
        assert "7203" in human["url"]
        for next_call in out["_next_calls"]:
            if next_call["tool"] == "get_houjin_360_am":
                assert next_call["args"].get("houjin_bangou")

    def test_missing_arg(self) -> None:
        out = _list_edinet_disclosures_impl()
        assert "error" in out
        assert out["error"]["code"] == "missing_required_arg"

    def test_invalid_sec_code(self) -> None:
        out = _list_edinet_disclosures_impl(sec_code="XYZ")
        assert "error" in out
        assert out["error"]["code"] == "invalid_enum"

    def test_no_live_http_inside_tool(self, known_houjin_bangou: str) -> None:
        """Pointer-only contract — must NOT call EDINET API at runtime."""
        out = _list_edinet_disclosures_impl(houjin_bangou=known_houjin_bangou)
        assert out["data_quality"]["live_fetch_inside_tool"] is False


# ---------------------------------------------------------------------------
# 3) search_invoice_by_houjin_partial
# ---------------------------------------------------------------------------


class TestSearchInvoiceByHoujinPartial:
    def test_active_status_respects_future_registered_date(self) -> None:
        today = date(2026, 5, 4)
        assert _invoice_is_active("2026-05-04", None, None, today=today) is True
        assert _invoice_is_active("2026-05-05", None, None, today=today) is False
        assert _invoice_is_active("2026-05-01", "2026-05-04", None, today=today) is False
        assert _invoice_is_active("2026-05-01", None, "2026-05-04", today=today) is False

    def test_happy_path_known_name(self, known_invoice_name: str) -> None:
        out = _search_invoice_by_houjin_partial_impl(
            name_query=known_invoice_name,
            limit=10,
        )
        assert "error" not in out, f"unexpected error: {out.get('error')}"
        _assert_envelope_shape(out, with_disclaimer=True)
        assert out["name_query"] == known_invoice_name
        # PDL v1.0 attribution must be present on every 2xx response.
        assert "attribution" in out
        assert out["attribution"]["license"].startswith("公共データ利用規約")
        # Should match at least 1 row when seed came from the table.
        assert out["total"] >= 1
        for m in out["results"]:
            assert "invoice_registration_number" in m
            assert m["invoice_registration_number"].startswith("T")
            # active_only is True by default, so revoked / expired must be None.
            assert m["revoked_date"] is None
            assert m["expired_date"] is None

    def test_short_query_rejected(self) -> None:
        out = _search_invoice_by_houjin_partial_impl(name_query="A")
        assert "error" in out
        assert out["error"]["code"] == "invalid_enum"

    def test_missing_arg(self) -> None:
        out = _search_invoice_by_houjin_partial_impl(name_query="")
        assert "error" in out
        assert out["error"]["code"] == "missing_required_arg"

    def test_limit_caps_at_50(self, known_invoice_name: str) -> None:
        out = _search_invoice_by_houjin_partial_impl(
            name_query=known_invoice_name,
            limit=999,  # Should be clamped to 50.
        )
        assert "error" not in out
        assert out["limit"] == 50

    def test_inactive_when_active_only_false(self, known_invoice_name: str) -> None:
        # Just verify the toggle is honored without asserting anything about
        # the actual counts (corpus may have 0 inactive matches).
        out = _search_invoice_by_houjin_partial_impl(
            name_query=known_invoice_name,
            active_only=False,
        )
        assert "error" not in out
        assert out["active_only"] is False


# ---------------------------------------------------------------------------
# Tool-count gate (P12 §4.8 acceptance criterion).
# ---------------------------------------------------------------------------


class TestCorporateLayerToolCount:
    """Verifies the §4.8 acceptance criterion: corporate-layer +3 at default gates."""

    def test_three_tools_registered(self) -> None:
        from jpintel_mcp.mcp.server import mcp as _mcp

        tool_names = {t.name for t in _mcp._tool_manager.list_tools()}
        for n in (
            "get_houjin_360_am",
            "list_edinet_disclosures",
            "search_invoice_by_houjin_partial",
        ):
            assert n in tool_names, f"{n} not registered"
