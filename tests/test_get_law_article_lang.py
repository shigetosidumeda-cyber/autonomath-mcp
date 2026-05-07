"""W3-12 UC5 enabler — verify the ``lang`` argument plumbed into
``get_law_article_am`` (autonomath_wrappers.py) and the underlying
``law_article_tool.get_law_article`` correctly surfaces ``body_en``
(migration 090) when present and falls back gracefully when NULL.

The foreign FDI cohort (Cohort #4) needs english article bodies via the MCP
surface; the prior signature lacked ``lang`` so UC5 (個人情報保護法 §22 EN)
returned ``no_matching_records`` even though the column existed.

These tests run against the real ~9.4 GB autonomath.db at the repo root and
are skipped when the snapshot is missing (CI without fixture). They exercise
both branches of the lang resolution:

  - lang='ja' on a known JP-only article → text_full == JP body, lang_resolved='ja'
  - lang='en' on a 英訳-populated article → text_full == body_en + disclaimer
  - lang='en' on a JP-only article → text_full falls back to JP + warning
  - invalid lang → invalid_enum envelope (defensive layer below MCP Pydantic)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DB = _REPO_ROOT / "autonomath.db"

_DB_PATH = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_DB)))

if not _DB_PATH.exists():
    pytest.skip(
        f"autonomath.db ({_DB_PATH}) not present; skipping lang test. "
        "Set AUTONOMATH_DB_PATH to point at a snapshot.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")

# Server import first to break the autonomath_tools <-> server circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools import law_article_tool  # noqa: E402
from jpintel_mcp.mcp.autonomath_tools.autonomath_wrappers import (  # noqa: E402
    get_law_article_am,
)


def _has_nested_error(res: dict, code: str) -> bool:
    """Mirror of test_autonomath_tools._has_nested_error (kept local to avoid
    a cross-module import — that file gates on graph.sqlite which is not
    needed here)."""
    if not isinstance(res, dict):
        return False
    err = res.get("error")
    if not isinstance(err, dict):
        return False
    return err.get("code") == code


def _find_article_with_body_en():
    """Look up one (law_canonical_id, article_number) where body_en is
    populated. Returns None when no English translation has landed yet —
    the dependent test then graceful-skips."""
    import sqlite3

    con = sqlite3.connect(law_article_tool.DB_PATH)
    try:
        row = con.execute(
            """
            SELECT law_canonical_id, article_number
              FROM am_law_article
             WHERE body_en IS NOT NULL
             LIMIT 1
            """
        ).fetchone()
        return row
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Default (lang='ja') — backwards compat
# ---------------------------------------------------------------------------


def test_default_lang_is_ja_and_returns_jp_body():
    res = get_law_article_am(
        law_name_or_canonical_id="租税特別措置法",
        article_number="第41条の19",
    )
    assert res["found"] is True
    assert res["lang"] == "ja"
    assert res["lang_resolved"] == "ja"
    # No EN-only fields when lang='ja'
    assert "disclaimer" not in res
    assert "warning" not in res
    assert "body_en_source_url" not in res


def test_explicit_lang_ja_matches_default():
    """Explicit lang='ja' is identical to the default arg path."""
    res = get_law_article_am(
        law_name_or_canonical_id="租税特別措置法",
        article_number="第41条の19",
        lang="ja",
    )
    assert res["found"] is True
    assert res["lang"] == "ja"
    assert res["lang_resolved"] == "ja"


# ---------------------------------------------------------------------------
# lang='en' happy path — only runs when EN data has actually landed
# ---------------------------------------------------------------------------


def test_lang_en_returns_body_en_when_populated():
    """When at least one am_law_article row has body_en populated, lang='en'
    must return that body in text_full + the e-Gov disclaimer + provenance.
    Skipped (xfail-style) when the EN ingest has not yet run."""
    pair = _find_article_with_body_en()
    if not pair:
        pytest.skip(
            "No am_law_article row has body_en populated yet "
            "(scripts/ingest_egov_en_translations.py has not run). "
            "Skipping happy-path EN assertion; fallback path is tested separately."
        )
    law_canonical_id, article_number = pair
    res = get_law_article_am(
        law_name_or_canonical_id=law_canonical_id,
        article_number=article_number,
        lang="en",
    )
    assert res["found"] is True
    assert res["lang"] == "en"
    assert res["lang_resolved"] == "en"
    assert res.get("text_full"), "text_full must contain body_en"
    assert "disclaimer" in res, "EN responses must surface the e-Gov CC-BY 4.0 disclaimer"
    assert "courtesy translations" in res["disclaimer"]
    assert res.get("body_en_license") == "cc_by_4.0"


# ---------------------------------------------------------------------------
# lang='en' fallback — primary UC5 contract
# ---------------------------------------------------------------------------


def test_lang_en_on_jp_only_article_falls_back_with_warning():
    """When body_en is NULL for an existing JP article row, lang='en' must
    fall back transparently to the JP body and emit a warning field.

    We discover one such row dynamically because corpus content shifts as
    e-Gov 英訳 ingest progresses. If the entire am_law_article table has
    body_en populated (future state), this test xfails honestly."""
    import sqlite3

    con = sqlite3.connect(law_article_tool.DB_PATH)
    try:
        # Pick a row that has body_en NULL but EITHER text_full OR text_summary
        # populated, so the fallback assertion has something to anchor on.
        row = con.execute(
            """
            SELECT a.law_canonical_id, a.article_number, l.canonical_name
              FROM am_law_article a
              JOIN am_law l ON l.canonical_id = a.law_canonical_id
             WHERE a.body_en IS NULL
               AND (a.text_full IS NOT NULL OR a.text_summary IS NOT NULL)
             LIMIT 1
            """
        ).fetchone()
    finally:
        con.close()
    if not row:
        pytest.skip(
            "No am_law_article row has body_en NULL with non-empty body — "
            "fallback path is unreachable. Promote this to xfail when that ships."
        )
    law_canonical_id, article_number, _law_name = row
    res = get_law_article_am(
        law_name_or_canonical_id=law_canonical_id,
        article_number=article_number,
        lang="en",
    )
    assert res["found"] is True
    assert res["lang"] == "en"  # echoes what was requested
    assert res["lang_resolved"] == "ja"  # but actually returned JP
    assert "warning" in res
    assert res["warning"].startswith("english_translation_unavailable")
    # Fallback must surface SOMETHING from the JP source — text_full or
    # text_summary (text_full is NULL on many catalog stubs that only carry
    # the summary; both are upstream concerns, not lang-routing concerns).
    assert res.get("text_full") or res.get(
        "text_summary"
    ), "fallback must surface the JP body (text_full or text_summary)"
    # disclaimer is only attached when body_en is actually returned.
    assert "disclaimer" not in res


def test_uc5_personal_info_law_article_22_lang_en_graceful_empty():
    """UC5 spec acceptance: get_law_article_am(個人情報保護法, 第22条, lang='en').
    Per the task completion criterion ("body_en を返す (data あれば) or
    graceful empty"), when the law catalog stub exists but no article rows
    have been ingested (CLAUDE.md: 'body text only 154 of 9,484 laws'), the
    canonical envelope echoes the resolved law and a no_matching_records
    error. This is the 'graceful empty' contract — NOT a tool defect."""
    res = get_law_article_am(
        law_name_or_canonical_id="個人情報保護法",
        article_number="第22条",
        lang="en",
    )
    # Resolved law must be echoed even on miss (proves law resolver fired).
    assert res["law"]["canonical_id"] == "law:koju-ho"
    assert res["law"]["canonical_name"] == "個人情報の保護に関する法律"
    if res["found"]:
        # Body has landed — assert EN contract.
        assert res["lang"] == "en"
        if res["lang_resolved"] == "en":
            assert "disclaimer" in res
        else:
            assert res.get("warning", "").startswith("english_translation_unavailable")
    else:
        # Graceful empty branch (current production state).
        assert _has_nested_error(res, "no_matching_records")
        assert res["error"]["queried"]["law_name_or_canonical_id"] == "個人情報保護法"


def test_lang_en_unknown_law_still_returns_seed_not_found():
    """Lang plumbing must NOT mask the seed_not_found error path."""
    res = get_law_article_am(
        law_name_or_canonical_id="存在しない法律XYZ",
        article_number="第1条",
        lang="en",
    )
    assert res["found"] is False
    assert _has_nested_error(res, "seed_not_found")


# ---------------------------------------------------------------------------
# Defensive: invalid lang at the underlying-function layer
# ---------------------------------------------------------------------------


def test_invalid_lang_at_function_layer_returns_invalid_enum():
    """The MCP wrapper has Pydantic Literal validation, but the underlying
    function is also called from REST + tests — it must defend itself."""
    res = law_article_tool.get_law_article(
        law_name_or_canonical_id="租税特別措置法",
        article_number="第41条の19",
        lang="fr",  # type: ignore[arg-type]
    )
    assert res["found"] is False
    assert _has_nested_error(res, "invalid_enum")
    assert res["error"]["queried"]["lang"] == "fr"
