"""Smoke + envelope-shape tests for the Wave 22 composition tools.

Covers the five tools shipped in
``jpintel_mcp.mcp.autonomath_tools.wave22_tools``:

  - match_due_diligence_questions
  - prepare_kessan_briefing
  - forecast_program_renewal
  - cross_check_jurisdiction
  - bundle_application_kit

The contract every Wave 22 tool must hold:

  * ``results`` (list) + ``total`` / ``limit`` / ``offset`` paginated envelope
  * ``_next_calls`` list with at least 1 compounding hint
  * ``corpus_snapshot_id`` + ``corpus_checksum`` for auditor reproducibility
  * ``_disclaimer`` field for the four §52/§72/§1 sensitive tools
    (forecast_program_renewal is the one statistical-only tool — no disclaimer)
  * Migration 102 applied → dd_question_templates table populated
    with at least 60 rows.

Skips module-wide if autonomath.db is missing (same convention as
test_annotation_tools.py).
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
        "not present; skipping wave22 suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE22_ENABLED", "1")

# server import first to break the autonomath_tools<->server circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.wave22_tools import (  # noqa: E402
    _bundle_application_kit_impl,
    _cross_check_jurisdiction_impl,
    _forecast_renewal_impl,
    _kessan_briefing_impl,
    _match_dd_questions_impl,
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
def known_program_id() -> str:
    """A program canonical_id present in am_entities."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT canonical_id FROM am_entities "
            "WHERE record_kind = 'program' AND primary_name LIKE '%補助%' "
            "LIMIT 1"
        ).fetchone()
        if not row:
            row = con.execute(
                "SELECT canonical_id FROM am_entities "
                "WHERE record_kind = 'program' LIMIT 1"
            ).fetchone()
        if not row:
            pytest.skip("am_entities has no program rows")
        return row[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Envelope-shape helpers
# ---------------------------------------------------------------------------


def _assert_envelope_shape(out: dict, *, with_disclaimer: bool = True) -> None:
    """Every Wave 22 result must carry the same minimal envelope."""
    assert isinstance(out, dict), f"expected dict, got {type(out)}"
    assert "results" in out, f"results missing: {list(out)[:5]}"
    assert isinstance(out["results"], list), "results must be list"
    for k in ("total", "limit", "offset"):
        assert k in out, f"{k} missing"
        assert isinstance(out[k], int), f"{k} must be int"
    # Reproducibility pair
    assert "corpus_snapshot_id" in out, "corpus_snapshot_id missing"
    assert "corpus_checksum" in out, "corpus_checksum missing"
    assert isinstance(out["corpus_checksum"], str)
    assert out["corpus_checksum"].startswith("sha256:")
    # Compound multiplier hint
    assert "_next_calls" in out, "_next_calls missing"
    assert isinstance(out["_next_calls"], list)
    assert len(out["_next_calls"]) >= 1, "expected >=1 next-call"
    for nc in out["_next_calls"]:
        assert "tool" in nc and "rationale" in nc and "compound_mult" in nc
    if with_disclaimer:
        assert "_disclaimer" in out, "_disclaimer missing on sensitive tool"
        assert isinstance(out["_disclaimer"], str)
        assert len(out["_disclaimer"]) >= 50


# ---------------------------------------------------------------------------
# Migration 102 sanity check
# ---------------------------------------------------------------------------


def test_migration_102_dd_question_templates_loaded() -> None:
    """dd_question_templates must carry at least 60 seeded rows across
    7 categories (credit / enforcement / invoice_compliance /
    industry_specific / lifecycle / tax / governance)."""
    con = sqlite3.connect(_DB_PATH)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM dd_question_templates"
        ).fetchone()
        assert row is not None
        assert row[0] >= 60, f"expected >=60 question templates, got {row[0]}"
        cats = {
            r[0] for r in con.execute(
                "SELECT DISTINCT question_category FROM dd_question_templates"
            ).fetchall()
        }
        expected = {
            "credit", "enforcement", "invoice_compliance",
            "industry_specific", "lifecycle", "tax", "governance",
        }
        missing = expected - cats
        assert not missing, f"missing categories: {missing}"
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 1) match_due_diligence_questions
# ---------------------------------------------------------------------------


def test_match_dd_questions_happy_path(known_houjin_bangou: str) -> None:
    out = _match_dd_questions_impl(
        houjin_bangou=known_houjin_bangou,
        deck_size=30,
    )
    _assert_envelope_shape(out, with_disclaimer=True)
    # Must return >=20 questions on a real 法人番号 (universal high-severity
    # alone covers >20 rows).
    assert out["total"] >= 20, f"deck too small: {out['total']}"
    # by_category breakdown surfaces the 7 categories.
    assert "by_category" in out
    assert isinstance(out["by_category"], dict)
    assert len(out["by_category"]) >= 5  # at least 5 of 7 categories surface
    # Target context populated.
    assert out["target"]["houjin_bangou"] == known_houjin_bangou
    # _next_calls compounding hints.
    next_tools = {nc["tool"] for nc in out["_next_calls"]}
    # The compounding hint should propose at least one Wave 22 cross-tool.
    assert "cross_check_jurisdiction" in next_tools or \
           "prepare_kessan_briefing" in next_tools


def test_match_dd_questions_invalid_houjin_bangou() -> None:
    out = _match_dd_questions_impl(houjin_bangou="abc")
    assert out.get("error", {}).get("code") in (
        "missing_required_arg", "invalid_enum",
    )


# ---------------------------------------------------------------------------
# 2) prepare_kessan_briefing
# ---------------------------------------------------------------------------


def test_prepare_kessan_briefing_happy_path(known_houjin_bangou: str) -> None:
    out = _kessan_briefing_impl(
        houjin_bangou=known_houjin_bangou,
        cadence="quarterly",
    )
    _assert_envelope_shape(out, with_disclaimer=True)
    assert out["fiscal_year"] >= 2025
    assert out["cadence"] == "quarterly"
    assert "fy_window" in out
    assert "amendment_diffs_count" in out
    assert "tax_changes_in_window" in out
    assert isinstance(out["tax_changes_in_window"], list)


def test_prepare_kessan_briefing_invalid_fy() -> None:
    out = _kessan_briefing_impl(
        houjin_bangou="3450001000777",
        fiscal_year="not-a-year",  # type: ignore[arg-type]
    )
    assert out.get("error", {}).get("code") in (
        "invalid_enum", "missing_required_arg",
    )


# ---------------------------------------------------------------------------
# 3) forecast_program_renewal
# ---------------------------------------------------------------------------


def test_forecast_program_renewal_happy_path(known_program_id: str) -> None:
    out = _forecast_renewal_impl(program_id=known_program_id)
    # forecast_program_renewal is NOT sensitive — no _disclaimer required.
    _assert_envelope_shape(out, with_disclaimer=False)
    # Probability is None when 0 rounds, else float in [0, 1].
    p = out.get("renewal_probability")
    if p is not None:
        assert 0.0 <= p <= 1.0
    # Signals dict, when present, has the four expected components.
    if "signals" in out:
        for k in (
            "frequency_signal", "recency_signal",
            "pipeline_signal", "snapshot_signal",
        ):
            assert k in out["signals"]


def test_forecast_program_renewal_unknown_program() -> None:
    out = _forecast_renewal_impl(program_id="program:does:not:exist:abc")
    # Should still return a valid envelope (with explanation) — not error.
    _assert_envelope_shape(out, with_disclaimer=False)
    assert out["total"] == 0
    assert out["renewal_probability"] is None


# ---------------------------------------------------------------------------
# 4) cross_check_jurisdiction
# ---------------------------------------------------------------------------


def test_cross_check_jurisdiction_happy_path(known_houjin_bangou: str) -> None:
    out = _cross_check_jurisdiction_impl(houjin_bangou=known_houjin_bangou)
    _assert_envelope_shape(out, with_disclaimer=True)
    assert out["houjin_bangou"] == known_houjin_bangou
    assert "registered" in out
    assert "operational" in out
    assert "mismatch_count" in out
    # results == mismatch list (paginated envelope contract).
    assert out["total"] == len(out["results"])


def test_cross_check_jurisdiction_missing_args() -> None:
    out = _cross_check_jurisdiction_impl()
    assert out.get("error", {}).get("code") == "missing_required_arg"


# ---------------------------------------------------------------------------
# 5) bundle_application_kit
# ---------------------------------------------------------------------------


def test_bundle_application_kit_happy_path(known_program_id: str) -> None:
    out = _bundle_application_kit_impl(
        program_id=known_program_id,
        profile={"company_name": "テスト株式会社"},
    )
    _assert_envelope_shape(out, with_disclaimer=True)
    assert out["program_id"] == known_program_id
    assert "program" in out
    assert "document_checklist" in out
    assert "certifications" in out
    assert "similar_cases" in out
    assert "cover_letter_text" in out
    assert isinstance(out["cover_letter_text"], str)
    # The kit must NOT generate a real DOCX — only a placeholder.
    assert "docx_placeholder" in out
    assert out["docx_placeholder"]["scaffold_only"] is True
    # Cover letter must reference the profile name we passed.
    assert "テスト株式会社" in out["cover_letter_text"]


def test_bundle_application_kit_unknown_program() -> None:
    out = _bundle_application_kit_impl(
        program_id="program:does:not:exist:xyz",
    )
    assert out.get("error", {}).get("code") == "seed_not_found"
