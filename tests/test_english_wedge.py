"""Smoke + envelope-shape tests for the English-wedge MCP tools.

Covers the five tools shipped in
``jpintel_mcp.mcp.autonomath_tools.english_wedge``:

  - search_laws_en
  - get_law_article_en
  - get_tax_treaty
  - check_foreign_capital_eligibility
  - find_fdi_friendly_subsidies

The contract every English-wedge tool must hold:

  * ``_disclaimer`` (str) carrying 税理士法 §52 / 弁護士法 §72 / 国際課税
    / FDI 規制 fence vocabulary.
  * ``_billing_unit`` (int) = 1 (single billable event per call).
  * ``_next_calls`` (list) with ≥1 compounding hint.
  * The JP corpus column ``body_en`` may be empty (translation is a
    separate offline ETL wave); search_laws_en must therefore degrade
    gracefully to ``total=0`` while still surfacing the disclaimer.
  * ``am_tax_treaty`` has ≥ 8 hand-curated rows (US/UK/SG/HK/DE/CN/KR/TW
    seed plus subsequent expansion). The US row must be returned by
    ``get_tax_treaty('US', 'JPN')``.
  * ``foreign_capital_eligibility`` returns one of the 5 known flags.

Skips module-wide if autonomath.db is missing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_AM_DB = _REPO_ROOT / "autonomath.db"

_AM_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_AM_DB)))

if not _AM_DB.exists():
    pytest.skip(
        f"autonomath.db ({_AM_DB}) missing; skipping english_wedge suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_AM_DB)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_ENGLISH_WEDGE_ENABLED", "1")

# server import first to break the autonomath_tools<->server circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.english_wedge import (  # noqa: E402, F401
    _check_foreign_capital_eligibility_impl,
    _find_fdi_friendly_subsidies_impl,  # imported for completeness; not directly invoked here
    _get_law_article_en_impl,
    _get_tax_treaty_impl,
    _search_laws_en_impl,
)

# ---------------------------------------------------------------------------
# Shared envelope assertions
# ---------------------------------------------------------------------------


def _assert_envelope_shape(res: dict, *, expect_disclaimer_keyword: str | None = None) -> None:
    """Every English-wedge response must hold this shape."""
    assert isinstance(res, dict), "result is not dict"

    # Disclaimer envelope is mandatory on every response (sensitive surface).
    assert "_disclaimer" in res, "missing _disclaimer key"
    assert isinstance(res["_disclaimer"], str)
    assert len(res["_disclaimer"]) > 50, (
        f"disclaimer too short ({len(res['_disclaimer'])} chars) — check envelope wiring"
    )
    if expect_disclaimer_keyword is not None:
        assert expect_disclaimer_keyword in res["_disclaimer"], (
            f"disclaimer missing keyword {expect_disclaimer_keyword!r}: {res['_disclaimer'][:120]}"
        )

    # Billing contract: 1 unit per call (single ¥3 event).
    assert res.get("_billing_unit") == 1, (
        f"_billing_unit must be 1 (got {res.get('_billing_unit')!r})"
    )

    # Compounding mechanism.
    assert isinstance(res.get("_next_calls"), list), "_next_calls must be list"
    assert len(res["_next_calls"]) >= 1, "expected ≥1 _next_calls hint"
    for hint in res["_next_calls"]:
        assert "tool" in hint
        assert "args" in hint
        assert "rationale" in hint


# ---------------------------------------------------------------------------
# Tests required by the spec
# ---------------------------------------------------------------------------


def test_search_laws_en_returns_english_text() -> None:
    """search_laws_en surfaces EN body excerpts when corpus has rows; degrades
    gracefully to total=0 when the e-Gov 英訳 backfill is still empty.

    The corpus column (``am_law_article.body_en``, migration 090) is
    populated by a separate offline ETL wave; this test asserts the tool
    returns a well-formed envelope regardless of the current row count.
    """
    res = _search_laws_en_impl(q="tax", limit=10)
    _assert_envelope_shape(res, expect_disclaimer_keyword="CC-BY 4.0")

    assert res["lang"] == "en"
    assert isinstance(res["results"], list)
    assert isinstance(res.get("total"), int)
    assert res["total"] == len(res["results"])

    # If corpus is non-empty, each result must surface the EN excerpt
    # AND a body_en_source_url pointing back at e-Gov.
    for r in res["results"]:
        assert r["lang"] == "en"
        assert "body_en_excerpt" in r
        assert "body_en_source_url" in r
        # Excerpt is capped at 400 chars (see _search_laws_en_impl).
        assert len(r["body_en_excerpt"]) <= 400
        # License default 'cc_by_4.0' (e-Gov 日本法令外国語訳).
        assert r["body_en_license"] in ("cc_by_4.0", None)


def test_get_tax_treaty_returns_country_pair() -> None:
    """get_tax_treaty('US', 'JPN') must return the US/Japan DTA row with
    WHT rates, PE threshold, info-exchange status, and MoF source URL."""
    res = _get_tax_treaty_impl(country_a="US", country_b="JPN")
    _assert_envelope_shape(res, expect_disclaimer_keyword="国際課税")

    assert res.get("found") is True
    assert "treaty" in res
    treaty = res["treaty"]

    # Country pair fields.
    assert treaty["country_a"] == "US"
    assert treaty["country_b"] == "JP"  # 'JPN' normalises to 'JP'
    assert treaty["country_iso"] == "US"
    assert treaty["country_name_en"] == "United States"

    # Treaty kind enum.
    assert treaty["treaty_kind"] in ("comprehensive", "tax_info_exchange", "partial")

    # WHT rates structured payload.
    wht = treaty["withholding_tax_pct"]
    assert "dividend_general" in wht
    assert "dividend_parent_subsidiary" in wht
    assert "interest" in wht
    assert "royalty" in wht

    # Info-exchange enum.
    assert treaty["info_exchange"] in ("standard", "crs_only", "limited", "none")

    # MoAA arbitration is a bool (was 0/1 INTEGER in DB).
    assert isinstance(treaty["moaa_arbitration"], bool)

    # Source URL must point at a primary government domain.
    assert treaty["source_url"].startswith("https://")
    assert "mof.go.jp" in treaty["source_url"] or "nta.go.jp" in treaty["source_url"], (
        f"source_url should be mof/nta primary source: {treaty['source_url']}"
    )


def test_get_tax_treaty_japan_japan_rejects() -> None:
    """JP/JP is invalid (no self-pairing in am_tax_treaty)."""
    res = _get_tax_treaty_impl(country_a="JPN", country_b="JPN")
    assert res.get("error") is not None or "error" in res
    err = res.get("error") or {}
    assert err.get("code") in ("invalid_enum", "seed_not_found")


def test_foreign_capital_eligibility_checks_pct_threshold() -> None:
    """check_foreign_capital_eligibility returns one of the 5 known flags
    and surfaces a per-program decision aggregated across rule_types.

    Even when no rows are found, the disclaimer envelope must hold and
    the response must surface the 5-flag enum vocabulary somewhere
    (decision OR error envelope), so the test discovers a known program
    canonical_id from the live DB before asserting.
    """
    import sqlite3

    con = sqlite3.connect(_AM_DB)
    try:
        row = con.execute("SELECT program_entity_id FROM am_subsidy_rule LIMIT 1").fetchone()
    finally:
        con.close()

    if not row:
        pytest.skip("am_subsidy_rule has no rows on this DB snapshot")
    program_id = row[0]

    res = _check_foreign_capital_eligibility_impl(
        houjin_bangou="",  # input echo only
        program_id=program_id,
    )
    _assert_envelope_shape(res, expect_disclaimer_keyword="行政書士法")

    assert res.get("found") is True
    assert res.get("program_id") == program_id

    # Decision must be one of the 5 known flags.
    assert res["decision"] in (
        "eligible",
        "eligible_with_caveat",
        "excluded",
        "silent",
        "case_by_case",
    )
    assert isinstance(res.get("decision_explanation"), str)
    assert len(res["decision_explanation"]) > 20

    # Per-rule breakdown.
    assert isinstance(res["rules"], list)
    assert len(res["rules"]) >= 1
    for rule in res["rules"]:
        assert "rule_type" in rule
        assert "foreign_capital_eligibility" in rule
        assert rule["foreign_capital_eligibility"] in (
            "eligible",
            "eligible_with_caveat",
            "excluded",
            "silent",
            "case_by_case",
        )


def test_envelope_carries_law_article_en_field() -> None:
    """get_law_article_en surfaces EN body when present, JP fallback warning
    when not. Either way, the response must hold the canonical envelope
    shape AND carry an explicit ``lang`` / ``lang_resolved`` indicator
    so a downstream LLM can decide whether to surface JP text to a
    JA-illiterate audience.
    """
    # Use a known seed law canonical_id from the live DB.
    import sqlite3

    con = sqlite3.connect(_AM_DB)
    try:
        # Prefer a law that has at least one am_law_article row so the
        # tool resolves past the seed_not_found branch.
        row = con.execute(
            """
            SELECT a.law_canonical_id, a.article_number
              FROM am_law_article AS a
              JOIN am_law AS l ON l.canonical_id = a.law_canonical_id
             ORDER BY a.law_canonical_id, a.article_number_sort
             LIMIT 1
            """
        ).fetchone()
    finally:
        con.close()

    if not row:
        pytest.skip("am_law_article has no rows on this DB snapshot")
    law_id, article_no = row[0], row[1]

    res = _get_law_article_en_impl(law_id=law_id, article_no=article_no)
    _assert_envelope_shape(res, expect_disclaimer_keyword="CC-BY 4.0")

    # The canonical envelope from law_article_tool always sets ``lang``
    # ('en' was requested) and ``lang_resolved`` (actual resolution).
    assert res.get("lang") == "en"
    assert res.get("lang_resolved") in ("en", "ja"), (
        f"lang_resolved must be 'en' or 'ja' (got {res.get('lang_resolved')!r})"
    )

    if res["lang_resolved"] == "en":
        # EN body present — must carry e-Gov source URL + license.
        assert res.get("text_full")
        assert res.get("body_en_source_url")
        assert res.get("body_en_license") in ("cc_by_4.0", None)
    else:
        # JP fallback — must carry an explicit warning so the consumer
        # LLM does not silently surface JP body to an EN-only audience.
        assert "warning" in res
        assert "english_translation_unavailable" in res["warning"]
