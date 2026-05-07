"""Billing-pipeline contract tests for the Wave 23 industry packs +
the Wave 22 ``cross_check_jurisdiction`` tool.

Wave22 / Wave24 establish a billing pipeline that ``grep``s the tool
envelope for ``_billing_unit`` and counts the integer value as the
metered request count. Tools that omit the field silently bill 0 — a
revenue regression that does not surface in unit tests.

This file is the contract guard: every industry-pack response and the
``cross_check_jurisdiction`` response MUST carry ``_billing_unit`` as a
positive int (default 1). Coverage:

  * pack_construction      (industry_packs)
  * pack_manufacturing     (industry_packs)
  * pack_real_estate       (industry_packs)
  * cross_check_jurisdiction (wave22_tools)

Also verifies that the envelope_wrapper.build_envelope path does not
strip / override ``_billing_unit`` — the wrap target tools propagate
the field unchanged through the legacy_extras pull-through.
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
        f"graph.sqlite ({_GRAPH}) missing; skipping billing suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_AM_DB)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH)
_PRIOR_JPINTEL_DB_PATH = os.environ.get("JPINTEL_DB_PATH")
os.environ["JPINTEL_DB_PATH"] = str(_JPI_DB)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_INDUSTRY_PACKS_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE22_ENABLED", "1")


@pytest.fixture(scope="module", autouse=True)
def _restore_jpintel_db_path_after_module():
    """Same restore pattern as test_industry_packs.py — keep production
    corpus pinned for this module, restore for downstream tests."""
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


# Import the server module first to break the autonomath_tools<->server
# circular import (same convention as test_industry_packs.py).
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.industry_packs import (  # noqa: E402
    _pack_construction_impl,
    _pack_manufacturing_impl,
    _pack_real_estate_impl,
)
from jpintel_mcp.mcp.autonomath_tools.wave22_tools import (  # noqa: E402
    _cross_check_jurisdiction_impl,
)

# ---------------------------------------------------------------------------
# Shared assertion helper
# ---------------------------------------------------------------------------


def _assert_billing_unit(res: dict, tool_name: str) -> None:
    """``_billing_unit`` MUST be a positive int (default 1) on every
    success-path envelope. Billing pipeline (Wave22/24) ``grep``s for it
    and silently drops to 0 when missing — the contract guard."""
    assert isinstance(res, dict), f"{tool_name}: result not a dict"
    assert "_billing_unit" in res, (
        f"{tool_name}: envelope missing '_billing_unit' — billing "
        "pipeline will silently bill 0 requests"
    )
    val = res["_billing_unit"]
    assert isinstance(val, int) and not isinstance(
        val, bool
    ), f"{tool_name}: _billing_unit must be int (got {type(val).__name__}={val!r})"
    assert val >= 1, f"{tool_name}: _billing_unit must be ≥1 (got {val})"


# ---------------------------------------------------------------------------
# Wave 23 industry packs — _billing_unit on success path
# ---------------------------------------------------------------------------


def test_pack_construction_emits_billing_unit() -> None:
    res = _pack_construction_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_billing_unit(res, "pack_construction")
    assert res["_billing_unit"] == 1


def test_pack_manufacturing_emits_billing_unit() -> None:
    res = _pack_manufacturing_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_billing_unit(res, "pack_manufacturing")
    assert res["_billing_unit"] == 1


def test_pack_real_estate_emits_billing_unit() -> None:
    res = _pack_real_estate_impl(
        prefecture="東京都",
        employee_count=30,
        revenue_yen=100_000_000,
    )
    _assert_billing_unit(res, "pack_real_estate")
    assert res["_billing_unit"] == 1


def test_pack_construction_billing_unit_when_no_filters() -> None:
    """Default (no filter) call still emits ``_billing_unit``."""
    res = _pack_construction_impl()
    _assert_billing_unit(res, "pack_construction")


def test_pack_manufacturing_billing_unit_when_no_filters() -> None:
    res = _pack_manufacturing_impl()
    _assert_billing_unit(res, "pack_manufacturing")


def test_pack_real_estate_billing_unit_when_no_filters() -> None:
    res = _pack_real_estate_impl()
    _assert_billing_unit(res, "pack_real_estate")


# ---------------------------------------------------------------------------
# Wave 22 cross_check_jurisdiction — _billing_unit on success path
# ---------------------------------------------------------------------------


def _pick_existing_houjin_bangou() -> str | None:
    """Pull a real 13-digit 法人番号 from jpi_houjin_master so the success
    path is exercised. Returns None if the table is empty (test skips)."""
    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{_AM_DB}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return None
    try:
        row = conn.execute(
            """
            SELECT houjin_bangou FROM jpi_houjin_master
             WHERE houjin_bangou IS NOT NULL
               AND length(houjin_bangou) = 13
             LIMIT 1
            """,
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return row["houjin_bangou"] if row else None


def test_cross_check_jurisdiction_emits_billing_unit() -> None:
    hb = _pick_existing_houjin_bangou()
    if hb is None:
        pytest.skip("jpi_houjin_master empty — cannot exercise success path")
    res = _cross_check_jurisdiction_impl(houjin_bangou=hb)
    if res.get("error"):
        # seed_not_found / db_unavailable etc. — _billing_unit is NOT
        # required on the error path (the error envelope itself is the
        # billing-pipeline cue). Re-skip on those rather than misreport.
        pytest.skip(f"cross_check_jurisdiction error path: {res['error']}")
    _assert_billing_unit(res, "cross_check_jurisdiction")
    assert res["_billing_unit"] == 1


# ---------------------------------------------------------------------------
# Envelope_wrapper does NOT override _billing_unit
# ---------------------------------------------------------------------------


def test_envelope_wrapper_preserves_billing_unit() -> None:
    """``build_envelope`` (and ``with_envelope`` decorator path) must not
    strip ``_billing_unit`` when the wrapped tool emits it. Contract:
    the field flows through ``_coerce_results`` → ``legacy_extras`` →
    surfaces on the final envelope unchanged.

    Even though the 3 industry packs + cross_check_jurisdiction are NOT
    currently wrapped via ``@with_envelope`` (they register as bare
    ``@mcp.tool``), this guard pre-empts a regression: if any future
    refactor moves them under the wrapper, ``_billing_unit`` must
    survive the trip.
    """
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
        with_envelope,
    )

    @with_envelope("synthetic_billing_test")
    def fake_tool(*, query: str = "") -> dict:
        return {
            "results": [{"id": "x"}],
            "total": 1,
            "limit": 1,
            "offset": 0,
            "_billing_unit": 1,
            "_next_calls": [],
        }

    out = fake_tool(query="probe")
    assert isinstance(out, dict)
    # The wrapper rebuilds the envelope but pulls through any extras via
    # _coerce_results — _billing_unit must be on the final envelope.
    assert "_billing_unit" in out, (
        "envelope_wrapper.build_envelope dropped '_billing_unit' — "
        "billing pipeline contract violation"
    )
    assert out["_billing_unit"] == 1


def test_envelope_wrapper_preserves_billing_unit_with_value_2() -> None:
    """Same guard with ``_billing_unit=2`` (Wave24 has tools that bill 2
    per call). The wrapper must not coerce the value back to 1."""
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (
        with_envelope,
    )

    @with_envelope("synthetic_billing_two")
    def fake_two(*, query: str = "") -> dict:
        return {
            "results": [],
            "total": 0,
            "limit": 1,
            "offset": 0,
            "_billing_unit": 2,
            "_next_calls": [],
        }

    out = fake_two(query="probe")
    assert (
        out.get("_billing_unit") == 2
    ), f"envelope_wrapper coerced _billing_unit (expected 2, got {out.get('_billing_unit')!r})"
