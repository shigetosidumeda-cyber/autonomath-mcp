"""Smoke tests for the 10 Wave 51 dim K-S MCP tool wrappers (155 → 165 → 169).

Asserts:

* Each of the 5 ``wave51_dim_*`` modules registers the expected impl
  functions and (when settings.autonomath_enabled) the expected
  ``@mcp.tool`` decorated callables exist with the canonical names.
* Each impl returns a JPCIR-shaped dict with the canonical envelope
  keys (``tool_name`` / ``schema_version`` / ``_billing_unit=1`` /
  ``_disclaimer``).
* Validation errors emit a ``make_error`` envelope rather than raising.
* The 10 tools appear in the live FastMCP tool list, total == 169
  (165 dim K-S baseline + 4 Wave 51 chain wrappers landed 2026-05-16).

No LLM. No HTTP. No DB writes (audit log path overridden to /tmp).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Ensure audit log writes to a temp path; impl resolves env at call time.
os.environ.setdefault(
    "ANONYMIZED_QUERY_AUDIT_LOG_PATH",
    str(Path(tempfile.gettempdir()) / "wave51_test_audit.jsonl"),
)


def _common_envelope_checks(envelope: dict[str, Any], expected_tool_name: str) -> None:
    """Assert the canonical JPCIR-shaped envelope keys are present."""
    assert isinstance(envelope, dict)
    assert envelope.get("tool_name") == expected_tool_name, envelope.get("tool_name")
    assert "schema_version" in envelope or "composed_tool_name" in envelope
    assert envelope.get("_billing_unit") == 1
    assert isinstance(envelope.get("_disclaimer"), str)
    assert "§52" in envelope["_disclaimer"]


def test_dim_n_anonymized_aggregate_query_supported() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_n_anonymized import (
        _anonymized_aggregate_query_impl,
    )

    out = _anonymized_aggregate_query_impl(
        industry="agriculture",
        region="関東",
        size="sme",
        cohort_size=12,
        aggregates={"avg_revenue": 12345},
    )
    _common_envelope_checks(out, "anonymized_aggregate_query")
    primary = out["primary_result"]
    assert primary["k_anonymity_ok"] is True
    assert primary["k_anonymity_floor"] == 5


def test_dim_n_anonymized_aggregate_query_below_k_anonymity() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_n_anonymized import (
        _anonymized_aggregate_query_impl,
    )

    out = _anonymized_aggregate_query_impl(
        industry="agriculture",
        region="関東",
        size="sme",
        cohort_size=3,
        aggregates={"avg_revenue": 99999},
    )
    _common_envelope_checks(out, "anonymized_aggregate_query")
    primary = out["primary_result"]
    assert primary["k_anonymity_ok"] is False
    assert primary["aggregates"] == {}


def test_dim_o_sign_fact_returns_canonical_payload() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_o_explainable import (
        _sign_fact_impl,
    )

    out = _sign_fact_impl(
        fact_id="fact_001",
        source_doc="https://www.maff.go.jp/program/abc",
        extracted_at="2026-05-16T00:00:00Z",
        verified_by="cron_etl_v3",
        confidence=0.95,
    )
    _common_envelope_checks(out, "sign_fact")
    primary = out["primary_result"]
    assert primary["fact_id"] == "fact_001"
    assert isinstance(primary["canonical_payload_hex"], str)
    assert primary["canonical_payload_len"] > 0


def test_dim_o_sign_fact_invalid_confidence_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_o_explainable import (
        _sign_fact_impl,
    )

    out = _sign_fact_impl(
        fact_id="fact_001",
        source_doc="https://www.maff.go.jp/program/abc",
        extracted_at="2026-05-16T00:00:00Z",
        verified_by="cron_etl_v3",
        confidence=1.5,
    )
    assert "error" in out
    assert out["error"]["code"] == "invalid_input"


def test_dim_o_verify_fact_missing_pubkey_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_o_explainable import (
        _verify_fact_impl,
    )

    # Ensure env is clear so the impl returns subsystem_unavailable.
    os.environ.pop("AUTONOMATH_FACT_SIGN_PUBLIC_KEY", None)
    out = _verify_fact_impl(
        fact_id="fact_001",
        source_doc="https://www.maff.go.jp/program/abc",
        extracted_at="2026-05-16T00:00:00Z",
        verified_by="ed25519_sig",
        confidence=1.0,
        signature_hex="aa" * 64,
    )
    assert "error" in out
    assert out["error"]["code"] == "subsystem_unavailable"


def test_dim_p_composed_eligibility_audit_workpaper() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_p_composed import (
        _eligibility_audit_workpaper_impl,
    )

    out = _eligibility_audit_workpaper_impl(
        program_id="jp_subsidy_abc",
        entity_id="entity_001",
        fy_start="2026-04-01",
    )
    # Composed envelope uses composed_tool_name not tool_name.
    assert out.get("composed_tool_name") == "eligibility_audit_workpaper"
    assert out["_billing_unit"] == 1
    assert "§52" in out["_disclaimer"]
    assert out["compression_ratio"] == 4


def test_dim_p_composed_subsidy_eligibility_full() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_p_composed import (
        _subsidy_eligibility_full_impl,
    )

    out = _subsidy_eligibility_full_impl(
        entity_id="entity_001",
        industry_jsic="A",
        prefecture="北海道",
        program_id_hint="",
    )
    assert out["composed_tool_name"] == "subsidy_eligibility_full"
    assert out["compression_ratio"] == 5


def test_dim_p_composed_ma_due_diligence_pack() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_p_composed import (
        _ma_due_diligence_pack_impl,
    )

    out = _ma_due_diligence_pack_impl(
        target_houjin_bangou="1234567890123",
        industry_jsic="C",
        portfolio_id="",
    )
    assert out["composed_tool_name"] == "ma_due_diligence_pack"
    assert out["compression_ratio"] == 4


def test_dim_p_composed_invoice_compatibility_check() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_p_composed import (
        _invoice_compatibility_check_impl,
    )

    out = _invoice_compatibility_check_impl(
        houjin_bangou="T1234567890123",
        invoice_date="2026-05-16",
    )
    assert out["composed_tool_name"] == "invoice_compatibility_check"
    assert out["compression_ratio"] == 3


def test_dim_p_missing_required_arg_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_p_composed import (
        _eligibility_audit_workpaper_impl,
    )

    out = _eligibility_audit_workpaper_impl(
        program_id="",
        entity_id="",
        fy_start="",
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_dim_q_query_snapshot_as_of_v2_missing_returns_absent_envelope() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_q_time_machine_v2 import (
        _query_snapshot_as_of_v2_impl,
    )

    # Point at a fresh empty temp dir so registry yields no nearest hit.
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AUTONOMATH_SNAPSHOTS_ROOT"] = tmp
        try:
            out = _query_snapshot_as_of_v2_impl(
                dataset_id="programs",
                as_of="2026-05-16",
            )
        finally:
            os.environ.pop("AUTONOMATH_SNAPSHOTS_ROOT", None)
    _common_envelope_checks(out, "query_snapshot_as_of_v2")
    assert out["primary_result"]["snapshot"] is None


def test_dim_q_counterfactual_diff_v2_invalid_date_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_q_time_machine_v2 import (
        _counterfactual_diff_v2_impl,
    )

    out = _counterfactual_diff_v2_impl(
        dataset_id="programs",
        as_of_a="not-a-date",
        as_of_b="2026-05-16",
    )
    assert "error" in out
    assert out["error"]["code"] == "invalid_date_format"


def test_dim_r_recommend_partner_for_gap_hits_freee() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_r_federated import (
        _recommend_partner_for_gap_impl,
    )

    out = _recommend_partner_for_gap_impl(
        query_gap="freee の請求書 #1234 が必要",
        max_results=3,
    )
    _common_envelope_checks(out, "recommend_partner_for_gap")
    primary = out["primary_result"]
    assert primary["federation_size"] == 6
    assert primary["total_hits"] >= 1
    partner_ids = [p["partner_id"] for p in primary["partners"]]
    assert "freee" in partner_ids


def test_dim_r_recommend_partner_no_hit_returns_absent_envelope() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_r_federated import (
        _recommend_partner_for_gap_impl,
    )

    out = _recommend_partner_for_gap_impl(
        query_gap="zzz_nonexistent_phrase_zzz",
        max_results=3,
    )
    _common_envelope_checks(out, "recommend_partner_for_gap")
    assert out["primary_result"]["total_hits"] == 0


def test_dim_r_recommend_partner_empty_query_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_dim_r_federated import (
        _recommend_partner_for_gap_impl,
    )

    out = _recommend_partner_for_gap_impl(
        query_gap="",
        max_results=3,
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_mcp_tool_count_is_169() -> None:
    """End-to-end: every Wave 51 dim K-S MCP tool registers + 4 chain wrappers.

    Tool-count tracking:

    * 155 baseline (pre-Wave-51).
    * +10 dim K-S wrappers (Wave 51 tick 0, 2026-05-16) → 165.
    * +4 chain wrappers (Wave 51 chains, 2026-05-16) → 169.
    """
    import jpintel_mcp.mcp.autonomath_tools  # noqa: F401  — triggers @mcp.tool side effects
    from jpintel_mcp.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    expected_new = {
        "anonymized_aggregate_query",
        "sign_fact",
        "verify_fact",
        "eligibility_audit_workpaper_composed",
        "subsidy_eligibility_full_composed",
        "ma_due_diligence_pack_composed",
        "invoice_compatibility_check_composed",
        "query_snapshot_as_of_v2",
        "counterfactual_diff_v2",
        "recommend_partner_for_gap",
        # Wave 51 chain wrappers (4 cross-dim service composition chains).
        "evidence_with_provenance_chain",
        "session_aware_eligibility_check_chain",
        "federated_handoff_with_audit_chain",
        "temporal_compliance_audit_chain",
    }
    missing = expected_new - names
    assert not missing, f"Wave 51 tools not registered: {sorted(missing)}"
    assert len(tools) == 169, f"Expected 169 tools, got {len(tools)}"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
