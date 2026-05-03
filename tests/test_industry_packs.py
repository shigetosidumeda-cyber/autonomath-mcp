"""Smoke + envelope-shape tests for the Wave 23 industry pack wrappers.

Covers the three wrappers shipped in
``jpintel_mcp.mcp.autonomath_tools.industry_packs``:

  - pack_construction (JSIC D)
  - pack_manufacturing (JSIC E)
  - pack_real_estate (JSIC K)

The contract every industry pack must hold:

  * ``programs`` (list) with ≥ 5 rows for the happy path
  * ``saiketsu_citations`` (list) — corpus is thin (~140 saiketsu rows),
    so this list MAY be empty for narrow industry × tax_type intersections.
    We assert ≥ 0 with at least one cohort returning ≥ 1 (manufacturing
    + real_estate consistently surface 1+ — construction corpus is currently
    too thin to guarantee).
  * ``tsutatsu_references`` (list) — should return ≥ 1 for every cohort
    given the 3,221-row 通達 corpus.
  * ``_disclaimer`` (str) — §52 + §47条の2 fence.
  * ``_next_calls`` (list) with ≥ 1 compounding hint.
  * ``totals`` dict with the three counts.
  * ``industry_label`` (str) + ``jsic_major`` (str) + ``input`` dict.

Skips module-wide if jpintel.db or autonomath.db is missing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_AM_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_JPI_DB = _REPO_ROOT / "data" / "jpintel.db"
_DEFAULT_GRAPH = _REPO_ROOT / "graph.sqlite"

# tests/conftest.py sets JPINTEL_DB_PATH to a tmp test fixture for the wider
# suite. The industry pack wrappers are read-only over the *production*
# jpintel.db corpus (10,790 programs) — so we point them back at the real
# DB explicitly here. AUTONOMATH_DB_PATH is left at production already.
_AM_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_AM_DB)))
_JPI_DB = _DEFAULT_JPI_DB  # always production, ignore conftest override
_GRAPH = Path(os.environ.get("AUTONOMATH_GRAPH_DB_PATH", str(_DEFAULT_GRAPH)))

if not _AM_DB.exists() or not _JPI_DB.exists() or not _GRAPH.exists():
    pytest.skip(
        f"autonomath.db ({_AM_DB}) / jpintel.db ({_JPI_DB}) / "
        f"graph.sqlite ({_GRAPH}) missing; skipping industry_packs suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_AM_DB)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH)
# Capture conftest's tmp jpintel.db path BEFORE we override — the
# autouse session-scoped fixture below restores it after this module's
# tests run, so unrelated tests later in the suite still see the seeded
# tmp DB and don't accidentally hit the production corpus / accumulate
# rate-limit state across suites.
_PRIOR_JPINTEL_DB_PATH = os.environ.get("JPINTEL_DB_PATH")
# Override conftest's tmp jpintel.db path with the production corpus —
# the industry pack wrapper opens jpintel.db read-only via JPINTEL_DB_PATH.
os.environ["JPINTEL_DB_PATH"] = str(_JPI_DB)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_INDUSTRY_PACKS_ENABLED", "1")


@pytest.fixture(scope="module", autouse=True)
def _restore_jpintel_db_path_after_module():
    """Restore JPINTEL_DB_PATH after this module's tests run.

    Without this, the production-corpus override leaks into later tests
    that share the pytest process — test_endpoint_smoke.py expects the
    seeded tmp DB and otherwise hits the production corpus, accumulating
    rate-limit state and failing on 429. The module-cached
    ``jpintel_mcp.config.settings`` instance also has to be replaced so
    later db.session.connect() calls re-read the restored env var.
    """
    yield
    if _PRIOR_JPINTEL_DB_PATH is None:
        os.environ.pop("JPINTEL_DB_PATH", None)
    else:
        os.environ["JPINTEL_DB_PATH"] = _PRIOR_JPINTEL_DB_PATH
    # The module-level Settings() singleton holds the production
    # jpintel.db path captured at this module's import time. Mutate the
    # PATH ATTRIBUTE in place (not the binding) so every consumer that
    # did `from jpintel_mcp.config import settings` keeps the same
    # object identity but sees the restored db_path. Rebinding the
    # module attribute (`_cfg.settings = _cfg.Settings()`) would break
    # downstream tests that monkeypatch attributes on the original
    # `settings` instance — they'd patch a stale binding.
    try:
        from jpintel_mcp.config import settings as _live_settings
        if _PRIOR_JPINTEL_DB_PATH is not None:
            _live_settings.db_path = Path(_PRIOR_JPINTEL_DB_PATH)
        else:
            _live_settings.db_path = Path("./data/jpintel.db")
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _use_production_jpintel_db_for_industry_packs(_reset_anon_rate_limit):
    """Keep this module on the production corpus after global test resets."""

    os.environ["JPINTEL_DB_PATH"] = str(_JPI_DB)
    try:
        from jpintel_mcp.config import settings as _live_settings

        _live_settings.db_path = _JPI_DB
    except Exception:
        pass
    yield


# Import the server module first to break the circular import
# autonomath_tools<->server (same convention as test_wave22_tools.py).
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.industry_packs import (  # noqa: E402
    _PACK_DEFINITIONS,
    _pack_construction_impl,
    _pack_manufacturing_impl,
    _pack_real_estate_impl,
)

# ---------------------------------------------------------------------------
# Shared envelope assertions
# ---------------------------------------------------------------------------


def _assert_envelope_shape(res: dict, expected_pack_key: str, expected_jsic: str) -> None:
    """Every industry pack response must hold this shape."""
    assert isinstance(res, dict), f"{expected_pack_key}: result is not dict"
    # Top-level keys
    for key in (
        "pack_key", "industry_label", "jsic_major", "input",
        "programs", "saiketsu_citations", "tsutatsu_references",
        "totals", "as_of_jst", "_disclaimer", "_next_calls",
    ):
        assert key in res, f"{expected_pack_key}: missing top-level key {key!r}"

    assert res["pack_key"] == expected_pack_key
    assert res["jsic_major"] == expected_jsic

    # Disclaimer envelope (§52 / §47条の2 fence)
    assert isinstance(res["_disclaimer"], str)
    assert len(res["_disclaimer"]) > 50, "disclaimer too short — check envelope"
    assert "税理士法" in res["_disclaimer"] or "§52" in res["_disclaimer"]

    # _next_calls compounding mechanism
    assert isinstance(res["_next_calls"], list)
    assert len(res["_next_calls"]) >= 1, "expected ≥1 next_calls hint"
    for hint in res["_next_calls"]:
        assert "tool" in hint
        assert "args" in hint
        assert "rationale" in hint

    # Programs / citations / refs are lists
    assert isinstance(res["programs"], list)
    assert isinstance(res["saiketsu_citations"], list)
    assert isinstance(res["tsutatsu_references"], list)

    # Totals match the lists
    totals = res["totals"]
    assert totals["programs"] == len(res["programs"])
    assert totals["saiketsu_citations"] == len(res["saiketsu_citations"])
    assert totals["tsutatsu_references"] == len(res["tsutatsu_references"])


# ---------------------------------------------------------------------------
# Pack definitions sanity
# ---------------------------------------------------------------------------


def test_pack_definitions_are_complete() -> None:
    """All 3 packs must be defined with the expected JSIC majors."""
    assert set(_PACK_DEFINITIONS.keys()) == {"construction", "manufacturing", "real_estate"}
    assert _PACK_DEFINITIONS["construction"]["jsic_major"] == "D"
    assert _PACK_DEFINITIONS["manufacturing"]["jsic_major"] == "E"
    assert _PACK_DEFINITIONS["real_estate"]["jsic_major"] == "K"

    for key, defn in _PACK_DEFINITIONS.items():
        assert defn["name_keywords"], f"{key}: name_keywords is empty"
        assert defn["tax_types"], f"{key}: tax_types is empty"
        assert defn["tsutatsu_prefixes"], f"{key}: tsutatsu_prefixes is empty"


# ---------------------------------------------------------------------------
# Happy-path tests — one per industry, 東京都 / 30 emp / ¥100M revenue
# ---------------------------------------------------------------------------


def test_pack_construction_happy_path() -> None:
    res = _pack_construction_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_envelope_shape(res, expected_pack_key="construction", expected_jsic="D")

    # Programs ≥ 5 (corpus has 36 construction programs per industries/D/index.html)
    assert len(res["programs"]) >= 5, (
        f"construction pack returned only {len(res['programs'])} programs, expected ≥5"
    )
    # 通達 ≥ 1 (法基通 / 消基通 corpus is rich enough for this)
    assert len(res["tsutatsu_references"]) >= 1, (
        "construction pack returned 0 tsutatsu — corpus too thin or filter mis-configured"
    )
    # saiketsu_citations: thin construction corpus (~21 法人税/消費税 saiketsu),
    # so we cannot gate on count. Instead assert the field is a list (shape only).
    assert isinstance(res["saiketsu_citations"], list)


def test_pack_manufacturing_happy_path() -> None:
    res = _pack_manufacturing_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_envelope_shape(res, expected_pack_key="manufacturing", expected_jsic="E")

    # Programs ≥ 5 (corpus has 71 manufacturing programs per industries/E/)
    assert len(res["programs"]) >= 5, (
        f"manufacturing pack returned only {len(res['programs'])} programs, expected ≥5"
    )
    # 通達 ≥ 1
    assert len(res["tsutatsu_references"]) >= 1, (
        "manufacturing pack returned 0 tsutatsu"
    )
    # saiketsu ≥ 1 — manufacturing keywords (省エネ/事業再構築/設備) consistently
    # match the 法人税 saiketsu corpus.
    assert len(res["saiketsu_citations"]) >= 1, (
        "manufacturing pack returned 0 saiketsu — investigate keyword fence"
    )


def test_pack_real_estate_happy_path() -> None:
    res = _pack_real_estate_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_envelope_shape(res, expected_pack_key="real_estate", expected_jsic="K")

    # Programs ≥ 5 — note JSIC K corpus shows 9 in industries/K/, but the
    # name-keyword fence (住宅 / 空き家 / 不動産) overlaps with JSIC D corpus
    # (housing-related), giving ≥10 hits in practice.
    assert len(res["programs"]) >= 5, (
        f"real_estate pack returned only {len(res['programs'])} programs, expected ≥5"
    )
    # 通達 ≥ 1 (所基通 + 相基通 corpus has 住宅借入金特別控除・不動産関連)
    assert len(res["tsutatsu_references"]) >= 1, (
        "real_estate pack returned 0 tsutatsu"
    )
    # saiketsu ≥ 1 — 所得税・相続税 corpus is rich (54 rows combined).
    assert len(res["saiketsu_citations"]) >= 1, (
        "real_estate pack returned 0 saiketsu"
    )


# ---------------------------------------------------------------------------
# Optional-arg defaults — every arg may be None, pack still composes
# ---------------------------------------------------------------------------


def test_pack_construction_no_filters() -> None:
    """Every arg None — pack still returns ≥5 programs nationwide."""
    res = _pack_construction_impl()
    _assert_envelope_shape(res, expected_pack_key="construction", expected_jsic="D")
    assert len(res["programs"]) >= 5


def test_pack_manufacturing_no_filters() -> None:
    res = _pack_manufacturing_impl()
    _assert_envelope_shape(res, expected_pack_key="manufacturing", expected_jsic="E")
    assert len(res["programs"]) >= 5


def test_pack_real_estate_no_filters() -> None:
    res = _pack_real_estate_impl()
    _assert_envelope_shape(res, expected_pack_key="real_estate", expected_jsic="K")
    assert len(res["programs"]) >= 5


# ---------------------------------------------------------------------------
# Each program row carries the expected fields
# ---------------------------------------------------------------------------


def test_program_rows_have_primary_fields() -> None:
    res = _pack_manufacturing_impl(prefecture="東京都")
    assert res["programs"], "no programs for 東京都 + manufacturing — corpus regression?"
    first = res["programs"][0]
    for key in (
        "unified_id", "primary_name", "tier",
        "authority_level", "program_kind", "source_url",
    ):
        assert key in first, f"program row missing {key!r}: {first}"


# ---------------------------------------------------------------------------
# Citation rows have source_url (primary-source policy)
# ---------------------------------------------------------------------------


def test_saiketsu_citations_carry_source_url() -> None:
    """When saiketsu_citations is non-empty, every row must carry source_url."""
    res = _pack_manufacturing_impl()
    for row in res["saiketsu_citations"]:
        assert row.get("source_url"), f"saiketsu row missing source_url: {row}"
        assert row.get("title"), f"saiketsu row missing title: {row}"


def test_tsutatsu_references_carry_source_url() -> None:
    res = _pack_construction_impl()
    for row in res["tsutatsu_references"]:
        assert row.get("source_url"), f"tsutatsu row missing source_url: {row}"
        assert row.get("code"), f"tsutatsu row missing code: {row}"
