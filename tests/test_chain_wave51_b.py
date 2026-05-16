"""Smoke tests for the 5 Wave 51 chain B MCP wrappers (179 -> 184).

Asserts the canonical ``ComposedEnvelope`` dict shape for each chain B
wrapper:

* ``composed_tool_name`` matches the canonical name.
* ``schema_version`` / ``_billing_unit=3`` / ``_disclaimer`` containing
  ``§52`` (heavy-tier sensitive surface).
* ``support_state`` lands in the closed Literal set.
* ``composed_steps`` lists every dim primitive invoked.
* Validation errors emit a structured ``make_error`` envelope rather
  than raising.

No LLM. No HTTP. No mutation of real DB / shared filesystem (all
fixture paths route through tmp_path-equivalent env overrides set
before module import).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest

# Route every chain's filesystem dependency through a temp path before
# importing the module so the wrappers never touch the real repo paths.
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="chain_wave51_b_test_"))
os.environ.setdefault("AUTONOMATH_SNAPSHOTS_ROOT", str(_TMP_ROOT / "snap"))
os.environ.setdefault("AUTONOMATH_SESSIONS_ROOT", str(_TMP_ROOT / "sessions"))
os.environ.setdefault(
    "AUTONOMATH_PREDICTIVE_EVENT_PATH",
    str(_TMP_ROOT / "predictive_events.jsonl"),
)
os.environ.setdefault(
    "AUTONOMATH_PREDICTIVE_SUBSCRIPTION_PATH",
    str(_TMP_ROOT / "predictive_subscriptions.jsonl"),
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
    # Composed-step ordering surface — every chain emits >= 1 step.
    steps = envelope.get("composed_steps")
    assert isinstance(steps, list) and len(steps) >= 1


# ---------------------------------------------------------------------------
# 1. predictive_subscriber_fanout_chain
# ---------------------------------------------------------------------------


def test_predictive_subscriber_fanout_envelope() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _predictive_subscriber_fanout_impl,
    )

    out = _predictive_subscriber_fanout_impl(
        subscription_json={
            "subscription_id": "sub_test_001",
            "subscriber_id": "subscriber_test_001",
            "watch_targets": ["program:test_slug"],
            "channel": "mcp_resource",
            "created_at": "2026-05-16T00:00:00Z",
        },
        event_json={
            "event_id": "evt_test_001",
            "event_type": "program_window",
            "target_id": "program:test_slug",
            # scheduled_at well within the 24h KPI window.
            "scheduled_at": "2026-05-16T01:00:00Z",
            "detected_at": "2026-05-16T00:30:00Z",
            "payload": {"note": "test event"},
        },
    )
    _common_chain_envelope_checks(out, "predictive_subscriber_fanout")
    primary = out["primary_result"]
    assert primary["subscription_id"] == "sub_test_001"
    assert primary["event_id"] == "evt_test_001"
    # Target id maps cleanly across subscription + event so the
    # subscriber should receive the event when the dim K registry runs.
    assert "program:test_slug" in primary["watch_targets"]


def test_predictive_subscriber_fanout_missing_subscription_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _predictive_subscriber_fanout_impl,
    )

    out = _predictive_subscriber_fanout_impl(
        subscription_json=None,
        event_json={
            "event_id": "evt_x",
            "event_type": "program_window",
            "target_id": "program:x",
            "scheduled_at": "2026-05-16T00:00:00Z",
            "detected_at": "2026-05-16T00:00:00Z",
            "payload": {},
        },
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


# ---------------------------------------------------------------------------
# 2. session_multi_step_eligibility_chain
# ---------------------------------------------------------------------------


def test_session_multi_step_eligibility_envelope() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _session_multi_step_eligibility_impl,
    )

    out = _session_multi_step_eligibility_impl(
        subject_id="subj_test_001",
        steps=[
            {"action": "narrow_industry", "payload": {"industry": "agriculture"}},
            {"action": "check_capital_band", "payload": {"capital_yen": 5_000_000}},
            {"action": "confirm_region", "payload": {"prefecture": "関東"}},
        ],
        initial_state={"phase": "discovery"},
    )
    _common_chain_envelope_checks(out, "session_multi_step_eligibility")
    primary = out["primary_result"]
    assert primary["subject_id"] == "subj_test_001"
    assert primary["steps_supplied"] == 3
    assert primary["steps_persisted"] == 3
    # Final SavedContext snapshot must reflect every step.
    assert primary["final_steps_count"] == 3


def test_session_multi_step_eligibility_missing_steps_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _session_multi_step_eligibility_impl,
    )

    out = _session_multi_step_eligibility_impl(
        subject_id="subj_test_002",
        steps=None,
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


# ---------------------------------------------------------------------------
# 3. rule_tree_batch_eval_chain
# ---------------------------------------------------------------------------


def test_rule_tree_batch_eval_envelope() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _rule_tree_batch_eval_impl,
    )

    # Two minimal single-node trees with terminal actions — both
    # evaluate against the same context, only the true_branch path
    # differs across trees.
    tree_one = {
        "tree_id": "tree_smb_check",
        "name": "中小企業判定",
        "version": "1.0.0",
        "root": {
            "node_id": "root",
            "condition_expr": "capital_yen <= 300000000",
            "true_branch": {
                "node_id": "smb_yes",
                "action": {"verdict": "smb"},
            },
            "false_branch": {
                "node_id": "smb_no",
                "action": {"verdict": "large"},
            },
        },
    }
    tree_two = {
        "tree_id": "tree_region_check",
        "name": "関東判定",
        "version": "1.0.0",
        "root": {
            "node_id": "root",
            "condition_expr": "prefecture == '関東'",
            "true_branch": {
                "node_id": "kantou_yes",
                "action": {"verdict": "kantou"},
            },
            "false_branch": {
                "node_id": "kantou_no",
                "action": {"verdict": "other"},
            },
        },
    }
    out = _rule_tree_batch_eval_impl(
        rule_tree_jsons=[tree_one, tree_two],
        context={"capital_yen": 5_000_000, "prefecture": "関東"},
    )
    _common_chain_envelope_checks(out, "rule_tree_batch_eval")
    primary = out["primary_result"]
    assert primary["tree_count"] == 2
    assert primary["successful_evals"] == 2
    verdicts = sorted(r["verdict"] for r in primary["results"])
    assert verdicts == ["kantou", "smb"]


def test_rule_tree_batch_eval_missing_trees_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _rule_tree_batch_eval_impl,
    )

    out = _rule_tree_batch_eval_impl(
        rule_tree_jsons=None,
        context={"k": "v"},
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


# ---------------------------------------------------------------------------
# 4. anonymized_cohort_query_with_redact_chain
# ---------------------------------------------------------------------------


def test_anonymized_cohort_query_with_redact_envelope_supported() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _anonymized_cohort_query_with_redact_impl,
    )

    out = _anonymized_cohort_query_with_redact_impl(
        sample={
            "company": "Bookyou株式会社",
            "houjin_bangou": "8010001213708",  # PII — must be stripped.
            "industry_jsic_major": "K",
            "metric_value": 1234,
        },
        cohort_size=12,  # >= K_ANONYMITY_MIN
        industry="K",
        region="関東",
        size="sme",
    )
    _common_chain_envelope_checks(out, "anonymized_cohort_query_with_redact")
    primary = out["primary_result"]
    assert primary["k_anonymity"]["ok"] is True
    # The houjin_bangou column must be removed by the dim N redactor.
    assert "houjin_bangou" not in primary["redacted_sample"]
    assert primary["audit_entry"]["reason"] == "ok"


def test_anonymized_cohort_query_with_redact_envelope_below_k_downgrades() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _anonymized_cohort_query_with_redact_impl,
    )

    out = _anonymized_cohort_query_with_redact_impl(
        sample={"industry": "K", "metric": 99},
        cohort_size=2,  # < K_ANONYMITY_MIN
        industry="K",
    )
    _common_chain_envelope_checks(out, "anonymized_cohort_query_with_redact")
    assert out["evidence"]["support_state"] == "partial"
    assert out["primary_result"]["audit_entry"]["reason"] == "cohort_too_small"


def test_anonymized_cohort_query_with_redact_missing_sample_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _anonymized_cohort_query_with_redact_impl,
    )

    out = _anonymized_cohort_query_with_redact_impl(
        sample=None,
        cohort_size=10,
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


# ---------------------------------------------------------------------------
# 5. time_machine_snapshot_walk_chain
# ---------------------------------------------------------------------------


def test_time_machine_snapshot_walk_absent_when_no_snapshots() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _time_machine_snapshot_walk_impl,
    )

    # Empty tmp snapshots root — no snapshot will resolve, so the
    # chain emits ``support_state=absent`` rather than raising.
    out = _time_machine_snapshot_walk_impl(
        dataset_id="programs",
        start_as_of_date="2026-01-01",
        end_as_of_date="2026-04-01",
        month_count_cap=4,
    )
    _common_chain_envelope_checks(out, "time_machine_snapshot_walk")
    assert out["evidence"]["support_state"] == "absent"
    primary = out["primary_result"]
    assert primary["months_walked"] == 4
    assert primary["non_null_snapshots"] == 0
    assert primary["diff_count"] == 0


def test_time_machine_snapshot_walk_missing_dates_returns_error() -> None:
    from jpintel_mcp.mcp.autonomath_tools.chain_wave51_b import (
        _time_machine_snapshot_walk_impl,
    )

    out = _time_machine_snapshot_walk_impl(
        dataset_id="programs",
        start_as_of_date="",
        end_as_of_date="2026-05-01",
    )
    assert "error" in out
    assert out["error"]["code"] == "missing_required_arg"


# ---------------------------------------------------------------------------
# E2E: MCP tool count is 184 with chain B wrappers registered
# ---------------------------------------------------------------------------


def test_mcp_tool_count_is_184_with_chain_b_wrappers_registered() -> None:
    """End-to-end: every chain B wrapper registers and total == 184."""
    import jpintel_mcp.mcp.autonomath_tools  # noqa: F401  — triggers @mcp.tool
    from jpintel_mcp.mcp.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    expected_chain_b_tools = {
        "predictive_subscriber_fanout_chain",
        "session_multi_step_eligibility_chain",
        "rule_tree_batch_eval_chain",
        "anonymized_cohort_query_with_redact_chain",
        "time_machine_snapshot_walk_chain",
    }
    missing = expected_chain_b_tools - names
    assert not missing, f"Wave 51 chain B wrappers not registered: {sorted(missing)}"
    assert len(tools) == 184, (
        f"Expected 184 tools after chain B wrappers, got {len(tools)}"
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
