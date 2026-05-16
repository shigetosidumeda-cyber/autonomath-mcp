"""Unit tests for Wave 51 service composition chains across dim K-S.

The chains compose multiple Wave 51 dim modules behind a single
:class:`ComposableTool` entry point. Tests assert:

* The 4 chains register under their canonical names + are
  :class:`ComposableTool` subclasses.
* Each chain emits a :class:`ComposedEnvelope` whose ``evidence`` is a
  canonical :class:`Evidence` model and whose ``outcome_contract`` is a
  :class:`OutcomeContract` — no fresh schema namespace.
* The composed_steps tuple lists every dim module touched in order.
* Happy path + degraded path + missing-input cases route through the
  documented support_state values.
* No LLM SDK import anywhere in the chain module.

Module-level docstring on each chain documents the exact dim-module
calls; the test names mirror those calls so a failing test surfaces
which composition step regressed.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from jpintel_mcp.agent_runtime.contracts import Evidence, OutcomeContract
from jpintel_mcp.composable_tools import (
    WAVE51_CHAIN_TOOLS,
    AtomicCallResult,
    ComposableTool,
    ComposedEnvelope,
    EvidenceWithProvenance,
    FederatedHandoffWithAudit,
    SessionAwareEligibilityCheck,
    TemporalComplianceAudit,
    register_wave51_chains,
)
from jpintel_mcp.federated_mcp import load_default_registry
from jpintel_mcp.rule_tree import RuleNode, RuleTree
from jpintel_mcp.session_context import SessionRegistry
from jpintel_mcp.time_machine import Snapshot, SnapshotRegistry

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAINS_SRC = REPO_ROOT / "src" / "jpintel_mcp" / "composable_tools" / "wave51_chains.py"


# ---------------------------------------------------------------------------
# Fake atomic registry mirroring the dim P composable_tools test pattern.
# ---------------------------------------------------------------------------


class FakeRegistry:
    """Minimal AtomicRegistry double — only the canonical atomic paths."""

    def __init__(self) -> None:
        self._results: dict[str, AtomicCallResult] = {}
        self._calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, tool_name: str, result: AtomicCallResult) -> None:
        self._results[tool_name] = result

    def call(self, tool_name: str, /, **kwargs: Any) -> AtomicCallResult:
        if tool_name not in self._results:
            raise KeyError(
                f"FakeRegistry: unexpected atomic call {tool_name!r}; "
                "register via FakeRegistry.register(...) first."
            )
        self._calls.append((tool_name, dict(kwargs)))
        return self._results[tool_name]

    def has(self, tool_name: str, /) -> bool:
        return tool_name in self._results

    @property
    def calls(self) -> list[tuple[str, dict[str, Any]]]:
        return list(self._calls)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hex64(token: str = "a") -> str:
    return (token * 64)[:64]


def _make_snapshot(
    *,
    dataset: str = "programs",
    bucket: str = "2024_03",
    as_of: date = date(2024, 3, 31),
    payload: dict[str, Any] | None = None,
) -> Snapshot:
    pay = payload or {"k": "v", "threshold": 100}
    return Snapshot(
        snapshot_id=f"{dataset}@{bucket}",
        as_of_date=as_of,
        source_dataset_id=dataset,
        content_hash=Snapshot.compute_content_hash(pay),
        payload=pay,
    )


def _seed_snapshot_registry(tmp_path: Path) -> SnapshotRegistry:
    """Populate a SnapshotRegistry with two snapshots for the same dataset."""
    reg = SnapshotRegistry(tmp_path / "snapshots")
    reg.put(_make_snapshot(bucket="2024_03", as_of=date(2024, 3, 31)))
    reg.put(
        _make_snapshot(
            bucket="2024_06",
            as_of=date(2024, 6, 30),
            payload={"k": "v", "threshold": 200, "extra": "newrow"},
        )
    )
    return reg


def _terminal_rule_tree(tree_id: str = "test_tree") -> RuleTree:
    """Build a simple branch tree that returns 'eligible' if x > 0."""
    return RuleTree(
        tree_id=tree_id,
        name="Test eligibility",
        version="1.0.0",
        root=RuleNode(
            node_id="root",
            condition_expr="x > 0",
            true_branch=RuleNode(
                node_id="leaf_eligible",
                action={"verdict": "eligible"},
            ),
            false_branch=RuleNode(
                node_id="leaf_ineligible",
                action={"verdict": "ineligible"},
            ),
        ),
    )


def _diff_rule_tree() -> RuleTree:
    """A rule tree that fires on counterfactual_diff context keys."""
    return RuleTree(
        tree_id="compliance_audit_tree",
        name="Compliance regression",
        version="1.0.0",
        root=RuleNode(
            node_id="root",
            condition_expr="changed_count > 0 or added_count > 0",
            true_branch=RuleNode(
                node_id="leaf_diff",
                action={"verdict": "drift_detected"},
            ),
            false_branch=RuleNode(
                node_id="leaf_no_diff",
                action={"verdict": "stable"},
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Registry + module-level invariants
# ---------------------------------------------------------------------------


def test_register_wave51_chains_returns_canonical_4_tuple() -> None:
    chains = register_wave51_chains()
    assert tuple(c.composed_tool_name for c in chains) == WAVE51_CHAIN_TOOLS
    assert len(chains) == 4


def test_wave51_chains_are_composable_tool_subclasses() -> None:
    for chain in register_wave51_chains():
        assert isinstance(chain, ComposableTool)
        assert isinstance(chain.outcome_contract, OutcomeContract)
        # Wave 51 chains have empty atomic_dependencies — they consume
        # dim modules directly rather than declaring registry deps.
        assert chain.atomic_dependencies == ()


def test_wave51_chains_module_carries_no_llm_sdk_import() -> None:
    """Scan for `import X` / `from X` statements only — docstrings may
    legitimately *describe* the banned modules in the no-LLM rule.
    """
    src = CHAINS_SRC.read_text(encoding="utf-8")
    for banned in ("anthropic", "openai", "google.generativeai", "claude_agent_sdk"):
        # Look for the exact `import <banned>` / `from <banned>` token
        # forms — these are the only patterns that would actually pull
        # the SDK at runtime.
        for pattern in (f"import {banned}", f"from {banned}"):
            assert pattern not in src, (
                f"wave51_chains.py must not have `{pattern}` — composition is "
                "deterministic + LLM-free per feedback_composable_tools_pattern."
            )


# ---------------------------------------------------------------------------
# evidence_with_provenance — dim P + Q + O + N
# ---------------------------------------------------------------------------


def test_evidence_with_provenance_supported_path(tmp_path: Path) -> None:
    snap_reg = _seed_snapshot_registry(tmp_path)
    fake = FakeRegistry()
    fake.register(
        "atomic_gap_probe",
        AtomicCallResult(
            tool_name="atomic_gap_probe",
            payload={"hit": True, "rows": [{"id": 1}]},
            citations=({"source_url": "https://example.gov.jp/x"},),
        ),
    )
    chain = EvidenceWithProvenance()
    envelope = chain.run(
        fake,
        fact_id="fact_evidence_test",
        cohort_size=12,
        dataset_id="programs",
        as_of_date=date(2024, 4, 15),  # falls on the 2024_03 snapshot
        source_doc="https://www.maff.go.jp/example",
        snapshot_registry=snap_reg,
        atomic_tool_name="atomic_gap_probe",
    )
    assert isinstance(envelope, ComposedEnvelope)
    assert isinstance(envelope.evidence, Evidence)
    assert envelope.evidence.support_state == "supported"
    assert envelope.composed_tool_name == "evidence_with_provenance"
    primary = envelope.primary_result
    assert primary["fact_id"] == "fact_evidence_test"
    assert primary["snapshot"] is not None
    assert primary["snapshot_reason"] == "ok"
    assert primary["k_anonymity"]["ok"] is True
    assert primary["k_anonymity"]["floor"] == 5
    assert len(primary["ed25519_sign_payload_hex"]) > 0
    # Atomic invoked → composed_steps grew to 4.
    assert envelope.composed_steps[0] == "composable_tools.atomic"
    assert envelope.compression_ratio == 4


def test_evidence_with_provenance_partial_when_k_anonymity_fails(
    tmp_path: Path,
) -> None:
    snap_reg = _seed_snapshot_registry(tmp_path)
    chain = EvidenceWithProvenance()
    envelope = chain.run(
        FakeRegistry(),
        fact_id="fact_low_k",
        cohort_size=3,  # below k=5 floor
        dataset_id="programs",
        as_of_date=date(2024, 7, 1),  # resolves to 2024_06 snapshot
        snapshot_registry=snap_reg,
    )
    assert envelope.evidence.support_state == "partial"
    primary = envelope.primary_result
    assert primary["k_anonymity"]["ok"] is False
    assert primary["k_anonymity"]["reason"] == "cohort_too_small"
    assert any("k-anonymity check failed" in w for w in envelope.warnings)


def test_evidence_with_provenance_absent_when_no_snapshot_no_atomic(
    tmp_path: Path,
) -> None:
    """No snapshot match + no atomic → support_state='absent'."""
    snap_reg = SnapshotRegistry(tmp_path / "empty_snapshots")
    fake = FakeRegistry()
    fake.register(
        "atomic_empty",
        AtomicCallResult(tool_name="atomic_empty", payload={}),
    )
    chain = EvidenceWithProvenance()
    envelope = chain.run(
        fake,
        fact_id="fact_absent",
        cohort_size=0,
        dataset_id="programs",
        as_of_date=date(2024, 3, 31),
        snapshot_registry=snap_reg,
        atomic_tool_name="atomic_empty",
    )
    assert envelope.evidence.support_state == "absent"
    assert envelope.evidence.evidence_type == "absence_observation"


def test_evidence_with_provenance_handles_missing_atomic_gracefully(
    tmp_path: Path,
) -> None:
    snap_reg = _seed_snapshot_registry(tmp_path)
    chain = EvidenceWithProvenance()
    envelope = chain.run(
        FakeRegistry(),
        fact_id="fact_missing_atomic",
        cohort_size=10,
        dataset_id="programs",
        as_of_date=date(2024, 4, 15),
        snapshot_registry=snap_reg,
        atomic_tool_name="atomic_that_does_not_exist",
    )
    # Atomic missing is non-fatal → still supported (snapshot + k pass).
    assert envelope.evidence.support_state == "supported"
    assert any("not registered" in w for w in envelope.warnings)


# ---------------------------------------------------------------------------
# session_aware_eligibility_check — dim L + M + K
# ---------------------------------------------------------------------------


def test_session_aware_eligibility_check_happy_path(tmp_path: Path) -> None:
    session_reg = SessionRegistry(root=tmp_path / "sessions")
    event_log = tmp_path / "events.jsonl"
    chain = SessionAwareEligibilityCheck()
    envelope = chain.run(
        FakeRegistry(),
        subject_id="agent_run_001",
        rule_tree=_terminal_rule_tree(),
        predictive_target_id="program:test_program_1",
        subject_context={"x": 5, "industry": "manufacturing"},
        session_registry=session_reg,
        predictive_event_path=event_log,
    )
    assert isinstance(envelope, ComposedEnvelope)
    assert envelope.evidence.support_state == "supported"
    primary = envelope.primary_result
    assert primary["subject_id"] == "agent_run_001"
    assert primary["eval_result"] is not None
    assert primary["eval_result"]["action"] == {"verdict": "eligible"}
    assert primary["predictive_target_id"] == "program:test_program_1"
    # Event log written.
    assert event_log.exists()
    events_text = event_log.read_text(encoding="utf-8").strip()
    assert events_text, "predictive event log must be non-empty"
    parsed = json.loads(events_text.splitlines()[0])
    assert parsed["target_id"] == "program:test_program_1"
    assert parsed["event_type"] == "program_window"
    # Session was closed → token cannot be reused.
    from jpintel_mcp.session_context import SessionNotFoundError

    with pytest.raises(SessionNotFoundError):
        session_reg.get_context(primary["session_token_id"])


def test_session_aware_eligibility_check_partial_on_rule_eval_error(
    tmp_path: Path,
) -> None:
    """Rule tree referencing a missing context key → partial, not crash."""
    session_reg = SessionRegistry(root=tmp_path / "sessions2")
    event_log = tmp_path / "events2.jsonl"
    chain = SessionAwareEligibilityCheck()
    envelope = chain.run(
        FakeRegistry(),
        subject_id="agent_run_002",
        rule_tree=_terminal_rule_tree(),
        predictive_target_id="program:test_program_2",
        subject_context={},  # 'x' missing
        eval_context={},
        session_registry=session_reg,
        predictive_event_path=event_log,
    )
    assert envelope.evidence.support_state == "partial"
    assert envelope.primary_result["eval_error"] is not None
    assert envelope.primary_result["eval_result"] is None


def test_session_aware_eligibility_check_houjin_target_yields_houjin_watch(
    tmp_path: Path,
) -> None:
    session_reg = SessionRegistry(root=tmp_path / "sessions3")
    event_log = tmp_path / "events3.jsonl"
    chain = SessionAwareEligibilityCheck()
    chain.run(
        FakeRegistry(),
        subject_id="agent_run_003",
        rule_tree=_terminal_rule_tree(),
        predictive_target_id="houjin:7000012050002",
        subject_context={"x": 1},
        session_registry=session_reg,
        predictive_event_path=event_log,
    )
    parsed = json.loads(event_log.read_text(encoding="utf-8").strip().splitlines()[0])
    assert parsed["event_type"] == "houjin_watch"


def test_session_aware_eligibility_check_requires_session_registry() -> None:
    chain = SessionAwareEligibilityCheck()
    with pytest.raises(ValueError, match="SessionRegistry"):
        chain.run(
            FakeRegistry(),
            subject_id="boom",
            rule_tree=_terminal_rule_tree(),
            predictive_target_id="program:x",
        )


# ---------------------------------------------------------------------------
# federated_handoff_with_audit — dim P + R + N
# ---------------------------------------------------------------------------


def test_federated_handoff_with_audit_supported_path(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    chain = FederatedHandoffWithAudit()
    envelope = chain.run(
        FakeRegistry(),
        query_gap="freee の請求書 #1234 を確認したい",
        federated_registry=load_default_registry(),
        audit_log_path=audit_path,
        industry="construction",
        region="13",
        size="medium",
    )
    assert isinstance(envelope, ComposedEnvelope)
    assert envelope.evidence.support_state == "supported"
    primary = envelope.primary_result
    assert primary["recommendation_count"] >= 1
    # freee is the canonical hit on this gap string.
    rec_ids = [r["partner_id"] for r in primary["recommendations"]]
    assert "freee" in rec_ids
    # Audit row written.
    assert audit_path.exists()
    audit_row = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert audit_row["reason"] == "ok"
    assert audit_row["cohort_hash"]


def test_federated_handoff_with_audit_partial_when_atomic_returns_data(
    tmp_path: Path,
) -> None:
    """When the atomic gap probe returns data the handoff is supplementary."""
    audit_path = tmp_path / "audit_partial.jsonl"
    fake = FakeRegistry()
    fake.register(
        "atomic_probe",
        AtomicCallResult(
            tool_name="atomic_probe",
            payload={"hit": True, "rows": [{"id": 1}]},
        ),
    )
    chain = FederatedHandoffWithAudit()
    envelope = chain.run(
        fake,
        query_gap="github のプルリクエストを取得",
        atomic_tool_name="atomic_probe",
        audit_log_path=audit_path,
    )
    assert envelope.evidence.support_state == "partial"
    assert envelope.primary_result["atomic_invoked"] is True


def test_federated_handoff_with_audit_absent_on_empty_query(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit_empty.jsonl"
    chain = FederatedHandoffWithAudit()
    envelope = chain.run(
        FakeRegistry(),
        query_gap="",
        audit_log_path=audit_path,
    )
    assert envelope.evidence.support_state == "absent"
    audit_row = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
    assert audit_row["reason"] == "invalid_filter"


def test_federated_handoff_with_audit_partial_on_no_matching_partner(
    tmp_path: Path,
) -> None:
    """Unmatched gap string still writes audit row, support_state='partial'."""
    audit_path = tmp_path / "audit_nomatch.jsonl"
    chain = FederatedHandoffWithAudit()
    envelope = chain.run(
        FakeRegistry(),
        query_gap="zzzzz_no_partner_matches_this_string_zzzzz",
        audit_log_path=audit_path,
    )
    assert envelope.evidence.support_state == "partial"
    assert envelope.primary_result["recommendation_count"] == 0
    assert audit_path.exists()


# ---------------------------------------------------------------------------
# temporal_compliance_audit — dim Q + M + O
# ---------------------------------------------------------------------------


def test_temporal_compliance_audit_supported_path(tmp_path: Path) -> None:
    snap_reg = _seed_snapshot_registry(tmp_path)
    chain = TemporalComplianceAudit()
    envelope = chain.run(
        FakeRegistry(),
        dataset_id="programs",
        baseline_as_of_date=date(2024, 4, 15),  # resolves to 2024_03
        compare_as_of_date=date(2024, 7, 1),  # resolves to 2024_06
        rule_tree=_diff_rule_tree(),
        snapshot_registry=snap_reg,
        audit_fact_id="audit_2024_q2",
        audit_source_doc="https://www.maff.go.jp/audit",
    )
    assert isinstance(envelope, ComposedEnvelope)
    assert envelope.evidence.support_state == "supported"
    primary = envelope.primary_result
    assert primary["baseline_snapshot"] is not None
    assert primary["compare_snapshot"] is not None
    assert primary["diff"] is not None
    # 2024_06 added "extra" key + changed "threshold".
    diff_added = primary["diff"]["added"]
    diff_changed = primary["diff"]["changed"]
    assert "extra" in diff_added
    assert "threshold" in diff_changed
    # Rule tree fired with verdict='drift_detected' because changed_count > 0.
    assert primary["rule_eval"] is not None
    assert primary["rule_eval"]["action"] == {"verdict": "drift_detected"}
    # Sign payload populated.
    assert primary["ed25519_sign_payload_hex"]


def test_temporal_compliance_audit_partial_when_one_snapshot_missing(
    tmp_path: Path,
) -> None:
    snap_reg = _seed_snapshot_registry(tmp_path)
    chain = TemporalComplianceAudit()
    envelope = chain.run(
        FakeRegistry(),
        dataset_id="programs",
        baseline_as_of_date=date(2020, 1, 1),  # before any snapshot
        compare_as_of_date=date(2024, 7, 1),
        rule_tree=_diff_rule_tree(),
        snapshot_registry=snap_reg,
    )
    assert envelope.evidence.support_state == "partial"
    assert envelope.primary_result["baseline_snapshot"] is None
    assert envelope.primary_result["compare_snapshot"] is not None
    assert envelope.primary_result["diff"] is None


def test_temporal_compliance_audit_absent_when_both_snapshots_missing(
    tmp_path: Path,
) -> None:
    snap_reg = SnapshotRegistry(tmp_path / "empty_snaps")
    chain = TemporalComplianceAudit()
    envelope = chain.run(
        FakeRegistry(),
        dataset_id="programs",
        baseline_as_of_date=date(2020, 1, 1),
        compare_as_of_date=date(2020, 6, 1),
        rule_tree=_diff_rule_tree(),
        snapshot_registry=snap_reg,
    )
    assert envelope.evidence.support_state == "absent"
    assert envelope.evidence.evidence_type == "absence_observation"


def test_temporal_compliance_audit_requires_snapshot_registry() -> None:
    chain = TemporalComplianceAudit()
    with pytest.raises(ValueError, match="snapshot_registry"):
        chain.run(
            FakeRegistry(),
            dataset_id="programs",
            baseline_as_of_date=date(2024, 1, 1),
            compare_as_of_date=date(2024, 6, 1),
            rule_tree=_diff_rule_tree(),
        )


def test_temporal_compliance_audit_requires_dates(tmp_path: Path) -> None:
    snap_reg = _seed_snapshot_registry(tmp_path)
    chain = TemporalComplianceAudit()
    with pytest.raises(ValueError, match="date"):
        chain.run(
            FakeRegistry(),
            dataset_id="programs",
            baseline_as_of_date="not-a-date",
            compare_as_of_date=date(2024, 6, 1),
            rule_tree=_diff_rule_tree(),
            snapshot_registry=snap_reg,
        )


# ---------------------------------------------------------------------------
# Type contract — every chain returns a frozen-shape envelope
# ---------------------------------------------------------------------------


def test_every_chain_yields_jpcir_envelope_shape(tmp_path: Path) -> None:
    """Smoke test — every chain produces a ComposedEnvelope with
    canonical Evidence + OutcomeContract + composed_steps + citations.
    """
    snap_reg = _seed_snapshot_registry(tmp_path)
    session_reg = SessionRegistry(root=tmp_path / "ev_sessions")
    rule_tree = _terminal_rule_tree()
    diff_tree = _diff_rule_tree()

    chains_inputs: list[tuple[ComposableTool, dict[str, Any]]] = [
        (
            EvidenceWithProvenance(),
            {
                "fact_id": "fact_smoke",
                "cohort_size": 10,
                "dataset_id": "programs",
                "as_of_date": date(2024, 4, 15),
                "snapshot_registry": snap_reg,
            },
        ),
        (
            SessionAwareEligibilityCheck(),
            {
                "subject_id": "smoke_subject",
                "rule_tree": rule_tree,
                "predictive_target_id": "program:smoke",
                "subject_context": {"x": 7},
                "session_registry": session_reg,
                "predictive_event_path": tmp_path / "smoke_events.jsonl",
            },
        ),
        (
            FederatedHandoffWithAudit(),
            {
                "query_gap": "freee の請求書",
                "audit_log_path": tmp_path / "smoke_audit.jsonl",
            },
        ),
        (
            TemporalComplianceAudit(),
            {
                "dataset_id": "programs",
                "baseline_as_of_date": date(2024, 4, 15),
                "compare_as_of_date": date(2024, 7, 1),
                "rule_tree": diff_tree,
                "snapshot_registry": snap_reg,
            },
        ),
    ]
    for chain, kwargs in chains_inputs:
        envelope = chain.run(FakeRegistry(), **kwargs)
        assert isinstance(envelope, ComposedEnvelope)
        assert isinstance(envelope.evidence, Evidence)
        assert isinstance(envelope.outcome_contract, OutcomeContract)
        assert envelope.composed_steps
        assert envelope.composed_tool_name == chain.composed_tool_name
        # Wire shape — to_dict round-trip works.
        wire = envelope.to_dict()
        assert wire["composed_tool_name"] == chain.composed_tool_name
        assert "evidence" in wire
        assert "outcome_contract" in wire


# ---------------------------------------------------------------------------
# Wire-shape regression — WAVE51_CHAIN_TOOLS is pinned for manifest sync
# ---------------------------------------------------------------------------


def test_wave51_chain_tools_tuple_is_canonical_and_immutable() -> None:
    assert WAVE51_CHAIN_TOOLS == (
        "evidence_with_provenance",
        "session_aware_eligibility_check",
        "federated_handoff_with_audit",
        "temporal_compliance_audit",
    )
    assert isinstance(WAVE51_CHAIN_TOOLS, tuple)
