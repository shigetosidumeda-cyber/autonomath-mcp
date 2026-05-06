"""W7-5/6: graceful empty-envelope contract tests for Wave 22 + composition.

Replaces the legacy ``seed_not_found`` error envelope returned when a
houjin_bangou / shogo / program_id / target_id is not found in the
underlying corpora. The new contract: emit a well-formed envelope with
``results=[], _billing_unit=1, _next_calls=[]`` and a ``data_quality``
caveat string so the calling agent can keep walking instead of dead-ending.

Tools covered:
  * ``_track_amendment_lineage_impl`` (composition_tools.py)
  * ``_cross_check_jurisdiction_impl`` (wave22_tools.py)
  * ``_bundle_application_kit_impl`` (wave22_tools.py)
  * ``_kessan_briefing_impl`` envelope must carry ``_billing_unit`` (W4-11
    miss caught by W5-5 NO-GO blocker #6)

Skips module-wide if autonomath.db is missing (same convention as
test_wave22_tools.py).
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
        "not present; skipping wave22 graceful-empty suite.",
        allow_module_level=True,
    )

os.environ["AUTONOMATH_DB_PATH"] = str(_DB_PATH)
os.environ["AUTONOMATH_GRAPH_DB_PATH"] = str(_GRAPH_PATH)
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE22_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_COMPOSITION_ENABLED", "1")

# server import first to break the autonomath_tools<->server circular import.
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.composition_tools import (  # noqa: E402
    _track_amendment_lineage_impl,
)
from jpintel_mcp.mcp.autonomath_tools.wave22_tools import (  # noqa: E402
    _bundle_application_kit_impl,
    _cross_check_jurisdiction_impl,
    _kessan_briefing_impl,
)


# ---------------------------------------------------------------------------
# Sentinels guaranteed not to exist
# ---------------------------------------------------------------------------

# 13-digit numeric houjin_bangou that never collides with any real 法人番号:
# the first digit of a real number is the check digit (1-9), 0000... is
# specifically reserved as illegal by the 法人番号公表サイト spec.
_NONEXISTENT_HOUJIN = "0000000000000"
_NONEXISTENT_SHOGO = "存在しない会社株式会社_W7_test_sentinel"
_NONEXISTENT_PROGRAM_ID = "prog:nonexistent::w7_test_sentinel"
_NONEXISTENT_TARGET_ID = "law:nonexistent::w7_test_sentinel"


# ---------------------------------------------------------------------------
# Envelope-shape helper for graceful empty path
# ---------------------------------------------------------------------------


def _assert_graceful_empty_envelope(out: dict) -> None:
    """All four covered tools must satisfy the W7-5/6 graceful-empty contract."""
    assert isinstance(out, dict), f"expected dict, got {type(out).__name__}"
    # Not an error envelope
    assert "error" not in out, (
        f"graceful empty path must NOT return error envelope; got keys={list(out)[:8]}"
    )
    # Required pagination shape
    assert "results" in out and isinstance(out["results"], list)
    assert out["results"] == [], f"results must be [] on empty path, got {out['results']!r}"
    assert out.get("total") == 0, f"total must be 0, got {out.get('total')!r}"
    assert "limit" in out and isinstance(out["limit"], int)
    assert "offset" in out and isinstance(out["offset"], int)
    # Billing must be charged exactly 1 unit (graceful empty is still a query)
    assert out.get("_billing_unit") == 1, (
        f"_billing_unit must be 1 on graceful empty, got {out.get('_billing_unit')!r}"
    )
    # _next_calls must exist (may be empty list)
    assert "_next_calls" in out and isinstance(out["_next_calls"], list)
    # data_quality.caveat must explain why the envelope is empty
    assert "data_quality" in out and isinstance(out["data_quality"], dict)
    assert "caveat" in out["data_quality"]
    assert isinstance(out["data_quality"]["caveat"], str)
    assert len(out["data_quality"]["caveat"]) >= 10


# ---------------------------------------------------------------------------
# 1) _track_amendment_lineage_impl (composition_tools)
# ---------------------------------------------------------------------------


def test_track_amendment_lineage_unknown_target_returns_graceful_empty() -> None:
    out = _track_amendment_lineage_impl(
        target_kind="program",
        target_id=_NONEXISTENT_TARGET_ID,
    )
    _assert_graceful_empty_envelope(out)


def test_track_amendment_lineage_unknown_law_target_returns_graceful_empty() -> None:
    out = _track_amendment_lineage_impl(
        target_kind="law",
        target_id=_NONEXISTENT_TARGET_ID,
    )
    _assert_graceful_empty_envelope(out)


# ---------------------------------------------------------------------------
# 2) _cross_check_jurisdiction_impl (wave22_tools)
# ---------------------------------------------------------------------------


def test_cross_check_jurisdiction_unknown_houjin_returns_graceful_empty() -> None:
    out = _cross_check_jurisdiction_impl(houjin_bangou=_NONEXISTENT_HOUJIN)
    _assert_graceful_empty_envelope(out)


def test_cross_check_jurisdiction_unknown_shogo_returns_graceful_empty() -> None:
    out = _cross_check_jurisdiction_impl(shogo=_NONEXISTENT_SHOGO)
    _assert_graceful_empty_envelope(out)


# ---------------------------------------------------------------------------
# 3) _bundle_application_kit_impl (wave22_tools)
# ---------------------------------------------------------------------------


def test_bundle_application_kit_unknown_program_returns_graceful_empty() -> None:
    out = _bundle_application_kit_impl(
        program_id=_NONEXISTENT_PROGRAM_ID,
        profile={},
    )
    _assert_graceful_empty_envelope(out)


# ---------------------------------------------------------------------------
# 4) _kessan_briefing_impl envelope must carry _billing_unit (W4-11 miss)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def known_houjin_bangou_for_kessan() -> str:
    """A real 13-digit 法人番号 so prepare_kessan_briefing reaches the
    success-envelope path (we want to verify _billing_unit on the success
    envelope, not the validation-error path).
    """
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


def test_kessan_briefing_envelope_carries_billing_unit(
    known_houjin_bangou_for_kessan: str,
) -> None:
    out = _kessan_briefing_impl(
        houjin_bangou=known_houjin_bangou_for_kessan,
        cadence="monthly",
    )
    assert isinstance(out, dict)
    # Success envelope (not error)
    assert "error" not in out, f"expected success envelope, got error: {out.get('error')!r}"
    # The W4-11-missed field
    assert "_billing_unit" in out, (
        f"_billing_unit MUST be present on prepare_kessan_briefing envelope "
        f"(W5-5 NO-GO blocker #6). Keys present: {list(out)[:15]}"
    )
    assert out["_billing_unit"] == 1, f"_billing_unit must be 1, got {out['_billing_unit']!r}"
