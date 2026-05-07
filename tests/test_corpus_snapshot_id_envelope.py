"""W3-13 audit: corpus_snapshot_id presence on every wave22 / wave24 /
industry_pack tool envelope.

Wave22 contract (auditor reproducibility, 公認会計士法 §47条の2):
``corpus_snapshot_id`` + ``corpus_checksum`` MUST appear at the top
level of every customer-facing response body, including:

  - 5  wave22 composition tool impls (already wired pre-2026-05-04 on
        the happy path — this test pins both happy AND error paths).
  - 12 wave24_tools_first_half impls (#97-#108).
  - 12 wave24_tools_second_half impls (#109-#120).
  -  3 industry_packs impls (pack_construction / pack_manufacturing /
        pack_real_estate).

Plus the central ``envelope_wrapper.build_envelope`` (used by every
``with_envelope``-decorated tool) — that contract is pinned by a
direct ``build_envelope(...)`` call.

Test design
-----------

* Each impl is invoked with a deliberately-invalid argument so the
  fast-fail ``make_error`` branch is exercised (no DB row needed).
* Both ``corpus_snapshot_id`` and ``corpus_checksum`` must be present
  and stringy. Their values may be either the live snapshot pair (if
  autonomath.db is reachable) or the deterministic fallback
  ``("1970-01-01T00:00:00Z", "sha256:0000000000000000")`` — both forms
  satisfy the auditor reproducibility contract because the fallback is
  itself deterministic and recognisable.
* Every impl is tested in isolation. The test does NOT walk through
  the @mcp.tool decorator (which would trigger session bookkeeping);
  it imports the underscore-prefixed `_*_impl` symbol directly.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_AM_DB = _REPO_ROOT / "autonomath.db"
_DEFAULT_GRAPH = _REPO_ROOT / "graph.sqlite"
_DEFAULT_JPI_DB = _REPO_ROOT / "data" / "jpintel.db"

# We do NOT need a live autonomath.db for the snapshot fields to appear
# (the helper degrades to the deterministic fallback pair). However the
# wave22 / wave24 / industry_pack modules import `connect_autonomath`
# at module-import time and that path resolves env vars at first call,
# so set the env var to the most likely real DB if it exists, else a
# tmpfs path that lets the helper fall through gracefully.
os.environ.setdefault("AUTONOMATH_DB_PATH", str(_DEFAULT_AM_DB))
os.environ.setdefault("AUTONOMATH_GRAPH_DB_PATH", str(_DEFAULT_GRAPH))
os.environ.setdefault("JPINTEL_DB_PATH", str(_DEFAULT_JPI_DB))
os.environ.setdefault("AUTONOMATH_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE22_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE24_FIRST_HALF_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_WAVE24_SECOND_HALF_ENABLED", "1")
os.environ.setdefault("AUTONOMATH_INDUSTRY_PACKS_ENABLED", "1")

# server import first to break the autonomath_tools<->server circular
# import (same convention as test_wave22_tools.py / test_industry_packs.py).
from jpintel_mcp.mcp import server  # noqa: F401, E402
from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import (  # noqa: E402
    build_envelope,
)
from jpintel_mcp.mcp.autonomath_tools.industry_packs import (  # noqa: E402
    _pack_construction_impl,
    _pack_manufacturing_impl,
    _pack_real_estate_impl,
)
from jpintel_mcp.mcp.autonomath_tools.snapshot_helper import (  # noqa: E402
    _reset_cache_for_tests as _reset_snapshot_cache,
)
from jpintel_mcp.mcp.autonomath_tools.wave22_tools import (  # noqa: E402
    _bundle_application_kit_impl,
    _cross_check_jurisdiction_impl,
    _forecast_renewal_impl,
    _kessan_briefing_impl,
    _match_dd_questions_impl,
)
from jpintel_mcp.mcp.autonomath_tools.wave24_tools_first_half import (  # noqa: E402
    _find_combinable_programs_impl,
    _find_similar_case_studies_impl,
    _forecast_enforcement_risk_impl,
    _get_houjin_360_snapshot_history_impl,
    _get_program_adoption_stats_impl,
    _get_program_calendar_12mo_impl,
    _get_program_narrative_impl,
    _get_tax_amendment_cycle_impl,
    _infer_invoice_buyer_seller_impl,
    _match_programs_by_capital_impl,
    _predict_rd_tax_credit_impl,
    _recommend_programs_for_houjin_impl,
)
from jpintel_mcp.mcp.autonomath_tools.wave24_tools_second_half import (  # noqa: E402
    _find_adopted_companies_by_program_impl,
    _find_complementary_subsidies_impl,
    _find_emerging_programs_impl,
    _find_programs_by_jsic_impl,
    _get_compliance_risk_score_impl,
    _get_houjin_subsidy_history_impl,
    _get_industry_program_density_impl,
    _get_program_application_documents_impl,
    _get_program_keyword_analysis_impl,
    _get_program_renewal_probability_impl,
    _score_application_probability_impl,
    _simulate_tax_change_impact_impl,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ---------------------------------------------------------------------------
# Shared assertion
# ---------------------------------------------------------------------------


def _assert_snapshot_pair(out: dict, *, where: str) -> None:
    """Pin the corpus_snapshot_id + corpus_checksum contract."""
    assert isinstance(out, dict), f"{where}: result is not a dict ({type(out)})"
    assert "corpus_snapshot_id" in out, (
        f"{where}: corpus_snapshot_id missing — keys={sorted(out.keys())[:20]}"
    )
    assert "corpus_checksum" in out, (
        f"{where}: corpus_checksum missing — keys={sorted(out.keys())[:20]}"
    )
    snap_id = out["corpus_snapshot_id"]
    checksum = out["corpus_checksum"]
    assert isinstance(snap_id, str) and snap_id, (
        f"{where}: corpus_snapshot_id must be non-empty string, got {snap_id!r}"
    )
    assert isinstance(checksum, str) and checksum, (
        f"{where}: corpus_checksum must be non-empty string, got {checksum!r}"
    )
    # Either a live "sha256:" prefix OR the deterministic fallback —
    # both satisfy the auditor reproducibility contract.
    assert checksum.startswith("sha256:"), (
        f"{where}: corpus_checksum must look like 'sha256:<hex>', got {checksum!r}"
    )


@pytest.fixture(autouse=True)
def _drop_snapshot_cache() -> None:
    """Drop the process-local cache before every test so each test
    sees a fresh compute path. Cheaper than env-var twiddling."""
    _reset_snapshot_cache()


# ---------------------------------------------------------------------------
# Central envelope contract
# ---------------------------------------------------------------------------


def test_build_envelope_carries_snapshot_pair() -> None:
    """Every with_envelope-decorated tool funnels through build_envelope,
    so the central function alone covers the entire 'envelope' surface
    above the per-impl plumbing tested below."""
    env = build_envelope(
        tool_name="search_programs",
        results=[],
        query_echo="snapshot test",
        latency_ms=1.0,
    )
    _assert_snapshot_pair(env, where="build_envelope (empty)")

    env = build_envelope(
        tool_name="search_programs",
        results=[{"id": "x"}],
        query_echo="snapshot test",
        latency_ms=1.0,
    )
    _assert_snapshot_pair(env, where="build_envelope (rich)")

    env = build_envelope(
        tool_name="search_programs",
        results=[],
        query_echo="snapshot test",
        latency_ms=1.0,
        error={"code": "internal", "message": "x"},
    )
    _assert_snapshot_pair(env, where="build_envelope (error)")


# ---------------------------------------------------------------------------
# Wave22 (5 impls)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("impl", "kwargs", "label"),
    [
        (_match_dd_questions_impl, {"houjin_bangou": ""}, "wave22.match_dd_questions"),
        (_kessan_briefing_impl, {"houjin_bangou": ""}, "wave22.prepare_kessan_briefing"),
        (_forecast_renewal_impl, {"program_id": ""}, "wave22.forecast_program_renewal"),
        (_cross_check_jurisdiction_impl, {}, "wave22.cross_check_jurisdiction"),
        (_bundle_application_kit_impl, {"program_id": ""}, "wave22.bundle_application_kit"),
    ],
)
def test_wave22_impls_carry_snapshot_pair(
    impl: Callable[..., dict[str, Any]],
    kwargs: dict[str, Any],
    label: str,
) -> None:
    out = impl(**kwargs)
    _assert_snapshot_pair(out, where=label)


# ---------------------------------------------------------------------------
# Wave24 first_half (12 impls, #97-#108)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("impl", "kwargs", "label"),
    [
        (
            _recommend_programs_for_houjin_impl,
            {"houjin_bangou": ""},
            "wave24.recommend_programs_for_houjin",
        ),
        (_find_combinable_programs_impl, {"program_id": ""}, "wave24.find_combinable_programs"),
        (_get_program_calendar_12mo_impl, {"program_id": ""}, "wave24.get_program_calendar_12mo"),
        (_forecast_enforcement_risk_impl, {}, "wave24.forecast_enforcement_risk"),
        (_find_similar_case_studies_impl, {"case_id": ""}, "wave24.find_similar_case_studies"),
        (
            _get_houjin_360_snapshot_history_impl,
            {"houjin_bangou": ""},
            "wave24.get_houjin_360_snapshot_history",
        ),
        (_get_tax_amendment_cycle_impl, {"tax_ruleset_id": ""}, "wave24.get_tax_amendment_cycle"),
        (
            _infer_invoice_buyer_seller_impl,
            {"houjin_bangou": ""},
            "wave24.infer_invoice_buyer_seller",
        ),
        (_match_programs_by_capital_impl, {"capital_yen": -1}, "wave24.match_programs_by_capital"),
        (_get_program_adoption_stats_impl, {"program_id": ""}, "wave24.get_program_adoption_stats"),
        (_get_program_narrative_impl, {"program_id": ""}, "wave24.get_program_narrative"),
        (_predict_rd_tax_credit_impl, {"houjin_bangou": ""}, "wave24.predict_rd_tax_credit"),
    ],
)
def test_wave24_first_half_impls_carry_snapshot_pair(
    impl: Callable[..., dict[str, Any]],
    kwargs: dict[str, Any],
    label: str,
) -> None:
    out = impl(**kwargs)
    _assert_snapshot_pair(out, where=label)


# ---------------------------------------------------------------------------
# Wave24 second_half (12 impls, #109-#120)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("impl", "kwargs", "label"),
    [
        (_find_programs_by_jsic_impl, {}, "wave24b.find_programs_by_jsic"),
        (
            _get_program_application_documents_impl,
            {"program_id": ""},
            "wave24b.get_program_application_documents",
        ),
        (
            _find_adopted_companies_by_program_impl,
            {"program_id": ""},
            "wave24b.find_adopted_companies_by_program",
        ),
        (
            _score_application_probability_impl,
            {"houjin_bangou": "", "program_id": ""},
            "wave24b.score_application_probability",
        ),
        (
            _get_compliance_risk_score_impl,
            {"houjin_bangou": ""},
            "wave24b.get_compliance_risk_score",
        ),
        (
            _simulate_tax_change_impact_impl,
            {"houjin_bangou": ""},
            "wave24b.simulate_tax_change_impact",
        ),
        (
            _find_complementary_subsidies_impl,
            {"program_id": ""},
            "wave24b.find_complementary_subsidies",
        ),
        (
            _get_program_keyword_analysis_impl,
            {"program_id": ""},
            "wave24b.get_program_keyword_analysis",
        ),
        (_get_industry_program_density_impl, {}, "wave24b.get_industry_program_density"),
        (_find_emerging_programs_impl, {"days": 0}, "wave24b.find_emerging_programs"),
        (
            _get_program_renewal_probability_impl,
            {"program_id": ""},
            "wave24b.get_program_renewal_probability",
        ),
        (
            _get_houjin_subsidy_history_impl,
            {"houjin_bangou": ""},
            "wave24b.get_houjin_subsidy_history",
        ),
    ],
)
def test_wave24_second_half_impls_carry_snapshot_pair(
    impl: Callable[..., dict[str, Any]],
    kwargs: dict[str, Any],
    label: str,
) -> None:
    out = impl(**kwargs)
    _assert_snapshot_pair(out, where=label)


# ---------------------------------------------------------------------------
# Industry packs (3 impls)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("impl", "label"),
    [
        (_pack_construction_impl, "industry_pack.construction"),
        (_pack_manufacturing_impl, "industry_pack.manufacturing"),
        (_pack_real_estate_impl, "industry_pack.real_estate"),
    ],
)
def test_industry_pack_impls_carry_snapshot_pair(
    impl: Callable[..., dict[str, Any]],
    label: str,
) -> None:
    # Industry packs require a DB to assemble the pack body. If
    # autonomath.db / jpintel.db is missing we still get a make_error
    # envelope — and that envelope must also carry the snapshot pair,
    # which is exactly what this test is asserting. Either branch
    # satisfies the contract.
    out = impl(prefecture=None, employee_count=None, revenue_yen=None)
    _assert_snapshot_pair(out, where=label)


# ---------------------------------------------------------------------------
# W5-4 graceful-empty branches that previously bypassed _finalize / _attach
# ---------------------------------------------------------------------------


def test_cross_check_jurisdiction_unknown_shogo_carries_snapshot_pair() -> None:
    """W5-4 fix: shogo with no houjin_master row used to return a bare
    dict bypassing _attach_snapshot. Pin both keys on that branch."""
    out = _cross_check_jurisdiction_impl(
        shogo="__no_such_corp_W5_4_audit__",
    )
    _assert_snapshot_pair(out, where="wave22.cross_check_jurisdiction (empty shogo)")


def test_cross_check_jurisdiction_unknown_houjin_carries_snapshot_pair() -> None:
    """W5-4 fix: valid-format houjin_bangou absent from jpi_houjin_master
    used to bypass _attach_snapshot."""
    out = _cross_check_jurisdiction_impl(
        houjin_bangou="9999999999999",
    )
    _assert_snapshot_pair(out, where="wave22.cross_check_jurisdiction (empty houjin)")


def test_bundle_application_kit_unknown_program_carries_snapshot_pair() -> None:
    """W5-4 fix: unknown program_id used to bypass _attach_snapshot."""
    out = _bundle_application_kit_impl(
        program_id="__no_such_program_W5_4_audit__",
    )
    _assert_snapshot_pair(out, where="wave22.bundle_application_kit (empty program_id)")


def test_get_industry_program_density_fallback_carries_snapshot_pair() -> None:
    """W5-4 fix: when am_region_program_density is missing, the fallback
    table return path used to bypass _finalize. Single-letter jsic_major
    drives the path; either the happy fallback OR the _empty_envelope
    miss path returns the snapshot pair."""
    out = _get_industry_program_density_impl(jsic_major="D")
    _assert_snapshot_pair(out, where="wave24b.get_industry_program_density (fallback)")
