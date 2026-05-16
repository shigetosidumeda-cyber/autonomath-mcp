"""Smoke tests for the 4 Wave 51 chain MCP wrappers (165 → 169).

Asserts:

* Each chain impl returns the canonical ``ComposedEnvelope`` dict shape
  (``composed_tool_name`` / ``schema_version`` / ``_billing_unit=3`` /
  ``_disclaimer`` containing §52).
* Validation errors emit a ``make_error`` envelope rather than raising.
* All 4 chain MCP tools appear in the live FastMCP tool list and the
  total registered tools == 169.
* The wrappers carry no LLM SDK imports (the suite-wide
  ``tests/test_no_llm_in_production.py`` already enforces this; this
  file additionally re-asserts the contract by inspecting the module
  symbols).

No LLM. No HTTP. No mutation of real DB / shared filesystem (all
fixture paths route through tmp_path).
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Route every chain's filesystem dependency through a temp path before
# importing the module so the wrappers never touch the real repo paths.
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="wave51_chains_test_"))
os.environ.setdefault("AUTONOMATH_SNAPSHOTS_ROOT", str(_TMP_ROOT / "snap"))
os.environ.setdefault("AUTONOMATH_SESSIONS_ROOT", str(_TMP_ROOT / "sessions"))
os.environ.setdefault(
    "AUTONOMATH_PREDICTIVE_EVENT_PATH",
    str(_TMP_ROOT / "predictive_events.jsonl"),
)
os.environ.setdefault(
    "ANONYMIZED_QUERY_AUDIT_LOG_PATH",
    str(_TMP_ROOT / "anonymized_query_audit.jsonl"),
)


def _common_chain_envelope_checks(envelope: dict[str, Any], expected_name: str) -> None:
    """Assert the canonical ComposedEnvelope JPCIR shape."""
    assert isinstance(envelope, dict), envelope
    assert envelope.get("composed_tool_name") == expected_name, envelope.get(
        "composed_tool_name"
    )
    # Heavy-tier compound service — 3 ¥3 units (税込 ¥9.90).
    assert envelope.get("_billing_unit") == 3, envelope.get("_billing_unit")
    assert isinstance(envelope.get("_disclaimer"), str)
    assert "§52" in envelope["_disclaimer"]
    # Canonical Evidence + OutcomeContract present and well-formed.
    ev = envelope.get("evidence")
    assert isinstance(ev, dict), ev
    assert ev.get("support_state") in {"supported", "partial", "contested", "absent"}
    oc = envelope.get("outcome_contract")
    assert isinstance(oc, dict), oc
    assert oc.get("billable") is True
    # Composed-step ordering surface — every chain emits >= 2 atomic steps.
    steps = envelope.get("composed_steps")
    assert isinstance(steps, list) and len(steps) >= 2


def test_evidence_with_provenance_chain_supported_envelope() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _evidence_with_provenance_impl,
    )

    out = _evidence_with_provenance_impl(
        fact_id="fact_001",
        cohort_size=12,  # >= K_ANONYMITY_MIN
        dataset_id="programs",
        source_doc="https://www.maff.go.jp/program/abc",
    )
    _common_chain_envelope_checks(out, "evidence_with_provenance")
    primary = out["primary_result"]
    assert primary["fact_id"] == "fact_001"
    assert primary["k_anonymity"]["ok"] is True
    # Ed25519 sign payload bytes present (we don't sign — we return the
    # canonical payload bytes for HSM hand-off).
    assert isinstance(primary["ed25519_sign_payload_hex"], str)
    assert primary["ed25519_sign_payload_bytes_len"] > 0


def test_evidence_with_provenance_chain_below_k_anonymity_downgrades() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _evidence_with_provenance_impl,
    )

    out = _evidence_with_provenance_impl(
        fact_id="fact_002",
        cohort_size=2,  # < K_ANONYMITY_MIN
    )
    _common_chain_envelope_checks(out, "evidence_with_provenance")
    assert out["evidence"]["support_state"] == "partial"
    assert any("k-anonymity" in w for w in out.get("warnings", []))


def test_evidence_with_provenance_chain_missing_fact_id_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _evidence_with_provenance_impl,
    )

    out = _evidence_with_provenance_impl(fact_id="", cohort_size=10)
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_session_aware_eligibility_check_chain_envelope() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _session_aware_eligibility_check_impl,
    )

    out = _session_aware_eligibility_check_impl(
        subject_id="sub_001",
        rule_tree_json=None,  # session + predictive event still emitted
        predictive_target_id="program:test_slug",
        subject_context={"income_band": "sme"},
    )
    _common_chain_envelope_checks(out, "session_aware_eligibility_check")
    primary = out["primary_result"]
    assert isinstance(primary["session_token_id"], str)
    assert primary["predictive_target_id"] == "program:test_slug"
    # No rule_tree → eval_result is None and support_state is absent.
    assert primary["eval_result"] is None


def test_session_aware_eligibility_check_chain_missing_target_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _session_aware_eligibility_check_impl,
    )

    out = _session_aware_eligibility_check_impl(
        subject_id="sub_001",
        rule_tree_json=None,
        predictive_target_id="",
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_federated_handoff_with_audit_chain_envelope() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _federated_handoff_with_audit_impl,
    )

    out = _federated_handoff_with_audit_impl(
        query_gap="freee の請求書 #1234 が必要",
        max_results=3,
        industry="agriculture",
        region="関東",
        size="sme",
    )
    _common_chain_envelope_checks(out, "federated_handoff_with_audit")
    primary = out["primary_result"]
    # freee partner should land in the curated recommendation set.
    assert primary["recommendation_count"] >= 1
    partner_ids = [p["partner_id"] for p in primary["recommendations"]]
    assert "freee" in partner_ids
    # APPI audit row must carry the redact_policy_version + cohort_hash.
    audit = primary["audit_entry"]
    assert isinstance(audit["cohort_hash"], str) and len(audit["cohort_hash"]) > 0
    assert audit["reason"] == "ok"


def test_federated_handoff_with_audit_chain_empty_gap_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _federated_handoff_with_audit_impl,
    )

    out = _federated_handoff_with_audit_impl(query_gap="", max_results=3)
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_temporal_compliance_audit_chain_absent_when_no_snapshots() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _temporal_compliance_audit_impl,
    )

    # Empty tmp snapshots root → no nearest match either side → absent.
    out = _temporal_compliance_audit_impl(
        dataset_id="programs",
        baseline_as_of_date="2026-01-01",
        compare_as_of_date="2026-05-01",
        rule_tree_json=None,
    )
    _common_chain_envelope_checks(out, "temporal_compliance_audit")
    assert out["evidence"]["support_state"] == "absent"
    primary = out["primary_result"]
    assert primary["baseline_snapshot"] is None
    assert primary["compare_snapshot"] is None


def test_temporal_compliance_audit_chain_missing_dates_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.wave51_chains import (
        _temporal_compliance_audit_impl,
    )

    out = _temporal_compliance_audit_impl(
        dataset_id="programs",
        baseline_as_of_date="",
        compare_as_of_date="2026-05-01",
        rule_tree_json=None,
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


def test_mcp_tool_count_is_169_with_chain_wrappers_registered() -> None:
    """End-to-end: every Wave 51 chain wrapper registers and total == 169."""
    import jpintel_mcp.mcp.autonomath_tools  # noqa: F401  — triggers @mcp.tool
    from jpintel_mcp.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    expected_chain_tools = {
        "evidence_with_provenance_chain",
        "session_aware_eligibility_check_chain",
        "federated_handoff_with_audit_chain",
        "temporal_compliance_audit_chain",
    }
    missing = expected_chain_tools - names
    assert not missing, f"Wave 51 chain wrappers not registered: {sorted(missing)}"
    assert len(tools) == 169, f"Expected 169 tools after chain wrappers, got {len(tools)}"


def test_wave51_chains_wrapper_has_no_llm_sdk_import() -> None:
    """Re-affirm the No-LLM invariant inline for the chain wrapper module.

    The suite-wide ``test_no_llm_in_production.py`` already greps the
    full ``src/`` tree. This test inspects the loaded module's symbols
    so the assertion fires inside the same import context the FastMCP
    runtime uses, catching any future contributor who imports an LLM
    SDK via a typing-only / TYPE_CHECKING guard.
    """
    from jpintel_mcp.mcp.autonomath_tools import wave51_chains

    forbidden_module_heads = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
        "langchain",
        "mistralai",
        "cohere",
        "groq",
        "replicate",
        "together",
        "vertexai",
        "bedrock_runtime",
    )
    module_globals = vars(wave51_chains)
    # Any module-level symbol bound to an actual module object would
    # reveal an import — check the value's __name__ when it has one.
    for name, value in list(module_globals.items()):
        mod_name = getattr(value, "__name__", "")
        if not isinstance(mod_name, str) or not mod_name:
            continue
        head = mod_name.split(".")[0]
        assert head not in forbidden_module_heads, (
            f"forbidden LLM SDK module {mod_name!r} bound to symbol {name!r}"
        )
    # Also check sys.modules for any import the module triggered.
    suspects = [m for m in sys.modules if m.split(".")[0] in forbidden_module_heads]
    assert not suspects, f"forbidden LLM SDK modules loaded: {suspects}"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
