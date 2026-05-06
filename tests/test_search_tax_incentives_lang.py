"""W3-12 UC5 (Foreign FDI) acceptance tests for `search_tax_incentives`.

Backstop for the lang + foreign_capital_eligibility wiring landed against
migrations 090 (am_law_article.body_en) + 092 (foreign_capital_eligibility).
The tool used to silently ignore both args; this suite locks in:

  * lang='en' surfaces name_en / body_en when present in raw_json and
    falls back transparently with `lang_resolved='ja'` otherwise.
  * foreign_capital_eligibility=True restricts the result set to rows
    that are reachable to a foreign-owned KK (the 'excluded' bucket
    is dropped; 'silent' is kept per the Japanese statutory default).
  * meta echoes both knobs so callers can verify the gate fired.
  * The combined call lang='en' + foreign_capital_eligibility=True
    returns 200 (envelope shape preserved) with only FDI-eligible rows.

These tests run against the real ~9.4 GB autonomath.db at the repo root
(skip module-wide if missing — same convention as test_autonomath_tools.py).
"""

from __future__ import annotations

import os
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
        "not present; skipping the FDI lang suite. Set "
        "AUTONOMATH_DB_PATH / AUTONOMATH_GRAPH_DB_PATH to point at a snapshot.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")

# `jpintel_mcp.mcp.server` must be imported FIRST to break the circular
# import between autonomath_tools/tools.py and server.py (same dance as
# test_autonomath_tools.py).
from jpintel_mcp.mcp import server  # noqa: F401, E402

from jpintel_mcp.mcp.autonomath_tools.tools import (  # noqa: E402
    search_tax_incentives,
)


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------


def _assert_paginated_envelope(res: dict) -> None:
    assert isinstance(res, dict)
    assert "total" in res
    assert "results" in res
    assert isinstance(res["results"], list)
    assert "meta" in res


# ---------------------------------------------------------------------------
# 1. lang default = 'ja'
# ---------------------------------------------------------------------------


def test_search_tax_incentives_default_lang_ja():
    """Baseline: no args → meta.lang='ja', no FDI filter, rows surfaced.

    The minimal-shape default must stay byte-for-byte compatible with
    pre-W3-12 callers — so `lang_resolved` is intentionally NOT surfaced
    on minimal rows when lang='ja' (only meta.lang carries the signal).
    """
    res = search_tax_incentives(limit=5)
    _assert_paginated_envelope(res)
    assert res["meta"]["lang"] == "ja"
    assert res["meta"]["foreign_capital_eligibility_filter"] is False
    if res["results"]:
        for r in res["results"]:
            assert "name" in r
            # Strict minimal shape: 4 keys exactly when lang='ja'.
            assert set(r.keys()) == {"id", "name", "score", "source_url"}


# ---------------------------------------------------------------------------
# 2. lang='en' surfaces english fields with graceful fallback
# ---------------------------------------------------------------------------


def test_search_tax_incentives_lang_en_returns_200_envelope():
    """lang='en' must not crash and must echo lang in meta + each row."""
    res = search_tax_incentives(lang="en", limit=10)
    _assert_paginated_envelope(res)
    assert res["meta"]["lang"] == "en"
    # Each row carries lang_resolved ∈ {'ja','en'} when lang != default.
    # 'ja' indicates graceful fallback (no name_en/body_en in raw_json).
    for r in res["results"]:
        assert r.get("lang_resolved") in {"ja", "en"}


def test_search_tax_incentives_lang_en_full_shape_exposes_translation():
    """fields='full' + lang='en' surfaces name_en / body_en + lang_resolved."""
    res = search_tax_incentives(lang="en", fields="full", limit=10)
    _assert_paginated_envelope(res)
    for r in res["results"]:
        # Full shape must expose all translation hooks (may be None).
        assert "name_en" in r
        assert "body_en" in r
        assert "name_ja" in r
        assert "lang" in r
        assert r["lang"] == "en"
        # If name_en is present, name should equal name_en (resolved).
        if r.get("name_en"):
            assert r["name"] == r["name_en"]
            assert r["lang_resolved"] == "en"


# ---------------------------------------------------------------------------
# 3. foreign_capital_eligibility filter
# ---------------------------------------------------------------------------


def test_search_tax_incentives_fdi_filter_drops_excluded():
    """foreign_capital_eligibility=True must drop 'excluded' rows.

    'silent' is kept (Japanese statutory non-discrimination default) so
    `total` may still be large; we assert no row carries 'excluded'.
    """
    res = search_tax_incentives(
        foreign_capital_eligibility=True,
        fields="full",
        limit=20,
    )
    _assert_paginated_envelope(res)
    assert res["meta"]["foreign_capital_eligibility_filter"] is True
    for r in res["results"]:
        assert r.get("foreign_capital_eligibility") != "excluded"


def test_search_tax_incentives_fdi_filter_smaller_or_equal_than_unfiltered():
    """FDI=True must produce total <= unfiltered total."""
    base = search_tax_incentives(limit=1)
    fdi = search_tax_incentives(foreign_capital_eligibility=True, limit=1)
    assert fdi["total"] <= base["total"]


# ---------------------------------------------------------------------------
# 4. Combined: lang='en' + foreign_capital_eligibility=True
# ---------------------------------------------------------------------------


def test_search_tax_incentives_lang_en_and_fdi_true_returns_200():
    """The W3-12 UC5 happy path: foreign FDI cohort + EN response."""
    res = search_tax_incentives(
        lang="en",
        foreign_capital_eligibility=True,
        fields="full",
        limit=20,
    )
    _assert_paginated_envelope(res)
    assert res["meta"]["lang"] == "en"
    assert res["meta"]["foreign_capital_eligibility_filter"] is True
    # Every returned row must satisfy BOTH constraints.
    for r in res["results"]:
        assert r["lang"] == "en"
        assert r.get("foreign_capital_eligibility") != "excluded"
