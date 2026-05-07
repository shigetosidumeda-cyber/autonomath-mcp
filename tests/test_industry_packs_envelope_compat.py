"""Canonical envelope contract guard for the Wave 23 industry packs.

W5-5 NO-GO blocker #7: MASTER_PLAN_v1 §10.7/10.8 mandates that every
MCP tool envelope carry the canonical pagination contract:

    total : int   — total number of result rows (post-filter, pre-page)
    limit : int   — max rows the caller asked for (or actual page size)
    offset: int   — first-row index in the paginated stream (0 = head)
    results: list — the result rows themselves

The 3 industry packs (``pack_construction`` / ``pack_manufacturing`` /
``pack_real_estate``) historically returned 3 cohort-specific lists
(``programs`` / ``saiketsu_citations`` / ``tsutatsu_references``) and a
``totals`` dict — the canonical 4 fields were missing, so any caller
that walks the envelope generically (downstream paging, audit logger,
billing pipeline) silently failed.

This module pins the alias-add fix:

  * ``total / limit / offset / results`` MUST exist on every pack response.
  * ``results`` MUST be the flattened discriminated union of the 3
    cohort lists, with each row tagged by a ``kind`` field
    (``program`` / ``saiketsu_citation`` / ``tsutatsu_reference``).
  * The 3 original fields (``programs`` / ``saiketsu_citations`` /
    ``tsutatsu_references``) MUST still exist (back-compat with all the
    existing happy-path tests in ``test_industry_packs.py``).
  * ``_billing_unit`` (already verified by ``test_industry_packs_billing``)
    MUST still exist — re-asserted here for full §10.7/10.8 envelope
    completeness.

Skips module-wide if jpintel.db / autonomath.db / graph.sqlite are
missing (mirrors the production-corpus pinning convention used by
``test_industry_packs.py`` and ``test_industry_packs_billing.py``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_AM_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_JPI_DB = _REPO_ROOT / "data" / "jpintel.db"
_DEFAULT_GRAPH = _REPO_ROOT / "graph.sqlite"

_AM_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_DEFAULT_AM_DB)))
_JPI_DB = _DEFAULT_JPI_DB
_GRAPH = Path(os.environ.get("AUTONOMATH_GRAPH_DB_PATH", str(_DEFAULT_GRAPH)))

if not _AM_DB.exists() or not _JPI_DB.exists() or not _GRAPH.exists():
    pytest.skip(
        f"autonomath.db ({_AM_DB}) / jpintel.db ({_JPI_DB}) / "
        f"graph.sqlite ({_GRAPH}) missing; skipping envelope_compat suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_AM_DB)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH)
_PRIOR_JPINTEL_DB_PATH = os.environ.get("JPINTEL_DB_PATH")
os.environ["JPINTEL_DB_PATH"] = str(_JPI_DB)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_INDUSTRY_PACKS_ENABLED", "1")


@pytest.fixture(scope="module", autouse=True)
def _restore_jpintel_db_path_after_module():
    """Mirror test_industry_packs.py: pin production corpus for this
    module, restore for downstream tests."""
    yield
    if _PRIOR_JPINTEL_DB_PATH is None:
        os.environ.pop("JPINTEL_DB_PATH", None)
    else:
        os.environ["JPINTEL_DB_PATH"] = _PRIOR_JPINTEL_DB_PATH
    try:
        from jpintel_mcp.config import settings as _live_settings

        if _PRIOR_JPINTEL_DB_PATH is not None:
            _live_settings.db_path = Path(_PRIOR_JPINTEL_DB_PATH)
        else:
            _live_settings.db_path = Path("./data/jpintel.db")
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _use_production_jpintel_db(_reset_anon_rate_limit):
    os.environ["JPINTEL_DB_PATH"] = str(_JPI_DB)
    try:
        from jpintel_mcp.config import settings as _live_settings

        _live_settings.db_path = _JPI_DB
    except Exception:
        pass
    yield


# Import the server first to break the autonomath_tools<->server cycle.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.industry_packs import (  # noqa: E402
    _pack_construction_impl,
    _pack_manufacturing_impl,
    _pack_real_estate_impl,
)

# ---------------------------------------------------------------------------
# Shared canonical-envelope assertion helper
# ---------------------------------------------------------------------------


_VALID_KINDS = {"program", "saiketsu_citation", "tsutatsu_reference"}


def _assert_canonical_envelope(res: dict, tool_name: str) -> None:
    """Every industry-pack response MUST carry the §10.7/10.8 canonical
    envelope (total / limit / offset / results) AND the legacy 3-list
    fields AND the _billing_unit + _next_calls + _disclaimer fields."""
    assert isinstance(res, dict), f"{tool_name}: result not a dict"

    # --- Canonical envelope (the W5-5 NO-GO blocker #7 fix) ---------------
    for key in ("total", "limit", "offset", "results"):
        assert key in res, (
            f"{tool_name}: canonical envelope missing {key!r} — "
            "MASTER_PLAN_v1 §10.7/10.8 contract violation"
        )

    total = res["total"]
    limit = res["limit"]
    offset = res["offset"]
    results = res["results"]

    assert isinstance(total, int) and not isinstance(
        total, bool
    ), f"{tool_name}: total must be int (got {type(total).__name__}={total!r})"
    assert isinstance(limit, int) and not isinstance(
        limit, bool
    ), f"{tool_name}: limit must be int (got {type(limit).__name__}={limit!r})"
    assert isinstance(offset, int) and not isinstance(
        offset, bool
    ), f"{tool_name}: offset must be int (got {type(offset).__name__}={offset!r})"
    assert isinstance(
        results, list
    ), f"{tool_name}: results must be list (got {type(results).__name__})"

    assert total >= 0, f"{tool_name}: total must be ≥0 (got {total})"
    assert limit >= 0, f"{tool_name}: limit must be ≥0 (got {limit})"
    assert (
        offset == 0
    ), f"{tool_name}: offset must be 0 for unpaginated pack envelope (got {offset})"
    assert total == len(results), (
        f"{tool_name}: total ({total}) must equal len(results) "
        f"({len(results)}) on unpaginated envelope"
    )

    # Each result row must be a dict carrying a ``kind`` discriminator.
    for i, row in enumerate(results):
        assert isinstance(
            row, dict
        ), f"{tool_name}: results[{i}] is not a dict ({type(row).__name__})"
        assert (
            row.get("kind") in _VALID_KINDS
        ), f"{tool_name}: results[{i}].kind={row.get('kind')!r} not in {_VALID_KINDS}"

    # --- Legacy 3-list fields (back-compat) -------------------------------
    for key in ("programs", "saiketsu_citations", "tsutatsu_references"):
        assert key in res, f"{tool_name}: legacy field {key!r} missing — back-compat broken"
        assert isinstance(res[key], list), f"{tool_name}: legacy {key} must remain a list"

    # Discriminated counts must reconcile with legacy lists.
    n_program = sum(1 for r in results if r["kind"] == "program")
    n_saiketsu = sum(1 for r in results if r["kind"] == "saiketsu_citation")
    n_tsutatsu = sum(1 for r in results if r["kind"] == "tsutatsu_reference")
    assert n_program == len(res["programs"]), (
        f"{tool_name}: results 'program' count ({n_program}) != "
        f"len(programs) ({len(res['programs'])})"
    )
    assert n_saiketsu == len(res["saiketsu_citations"]), (
        f"{tool_name}: results 'saiketsu_citation' count ({n_saiketsu}) != "
        f"len(saiketsu_citations) ({len(res['saiketsu_citations'])})"
    )
    assert n_tsutatsu == len(res["tsutatsu_references"]), (
        f"{tool_name}: results 'tsutatsu_reference' count ({n_tsutatsu}) != "
        f"len(tsutatsu_references) ({len(res['tsutatsu_references'])})"
    )

    # --- Billing + envelope completeness ---------------------------------
    assert "_billing_unit" in res, f"{tool_name}: _billing_unit missing"
    bu = res["_billing_unit"]
    assert (
        isinstance(bu, int) and not isinstance(bu, bool) and bu >= 1
    ), f"{tool_name}: _billing_unit must be int ≥1 (got {bu!r})"
    assert "_next_calls" in res, f"{tool_name}: _next_calls missing"
    assert "_disclaimer" in res, f"{tool_name}: _disclaimer missing"


# ---------------------------------------------------------------------------
# Per-pack canonical envelope tests (3 happy-path cohorts)
# ---------------------------------------------------------------------------


def test_pack_construction_canonical_envelope() -> None:
    res = _pack_construction_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_canonical_envelope(res, "pack_construction")


def test_pack_manufacturing_canonical_envelope() -> None:
    res = _pack_manufacturing_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_canonical_envelope(res, "pack_manufacturing")


def test_pack_real_estate_canonical_envelope() -> None:
    res = _pack_real_estate_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_canonical_envelope(res, "pack_real_estate")


# ---------------------------------------------------------------------------
# No-filter (national) canonical envelope tests
# ---------------------------------------------------------------------------


def test_pack_construction_canonical_envelope_no_filters() -> None:
    res = _pack_construction_impl()
    _assert_canonical_envelope(res, "pack_construction (no filters)")


def test_pack_manufacturing_canonical_envelope_no_filters() -> None:
    res = _pack_manufacturing_impl()
    _assert_canonical_envelope(res, "pack_manufacturing (no filters)")


def test_pack_real_estate_canonical_envelope_no_filters() -> None:
    res = _pack_real_estate_impl()
    _assert_canonical_envelope(res, "pack_real_estate (no filters)")
