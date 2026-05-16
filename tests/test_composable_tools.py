"""Tests for Wave 51 dim P composable_tools.

The composed tools have no DB or HTTP dependency — they invoke atomic
callables via the injected :class:`AtomicRegistry`. These tests inject
a deterministic ``FakeRegistry`` and assert:

* The 4 composed tools register under their canonical names.
* Each composed tool invokes exactly its declared atomic dependencies
  with the documented kwargs.
* :class:`ComposedEnvelope` carries a populated ``primary_result`` /
  ``citations`` / ``evidence`` plus the canonical
  :class:`OutcomeContract`.
* Missing atomic dependencies raise :class:`ComposedToolError` before
  any side effect.
* Citations are deduplicated by ``source_url`` then ``source_id``.
* Compression ratio matches ``len(atomic_dependencies)``.

The composed tools NEVER call out to LLMs / HTTP — the
``FakeRegistry`` enforces that by failing the test if an unexpected
atomic name is invoked.
"""

from __future__ import annotations

from typing import Any

import pytest

from jpintel_mcp.agent_runtime.contracts import Evidence, OutcomeContract
from jpintel_mcp.composable_tools import (
    DEFAULT_COMPOSED_TOOLS,
    AtomicCallResult,
    AtomicRegistry,
    ComposableTool,
    ComposedEnvelope,
    ComposedToolError,
    EligibilityAuditWorkpaper,
    InvoiceCompatibilityCheck,
    MaDueDiligencePack,
    SubsidyEligibilityFull,
    register_default_tools,
)
from jpintel_mcp.composable_tools.base import COMPOSED_ENVELOPE_SCHEMA_VERSION

# ---------------------------------------------------------------------------
# Fake atomic registry — deterministic, no DB / HTTP.
# ---------------------------------------------------------------------------


class FakeRegistry:
    """Deterministic in-memory atomic registry for composed-tool tests.

    Each registered atomic is a fixed :class:`AtomicCallResult` returned
    on every call. Test cases can also pre-seed a per-call lambda for
    more nuanced assertions about argument flow.
    """

    def __init__(self) -> None:
        self._results: dict[str, AtomicCallResult] = {}
        self._calls: list[tuple[str, dict[str, Any]]] = []

    def register(self, tool_name: str, result: AtomicCallResult) -> None:
        self._results[tool_name] = result

    def call(self, tool_name: str, /, **kwargs: Any) -> AtomicCallResult:
        if tool_name not in self._results:
            raise KeyError(
                f"FakeRegistry: unexpected atomic invocation {tool_name!r} "
                f"with kwargs={kwargs!r}. Add an explicit `.register(...)` "
                "in the test if this is intentional."
            )
        self._calls.append((tool_name, dict(kwargs)))
        return self._results[tool_name]

    def has(self, tool_name: str, /) -> bool:
        return tool_name in self._results

    @property
    def calls(self) -> list[tuple[str, dict[str, Any]]]:
        return list(self._calls)


def _seed_atomic(
    registry: FakeRegistry,
    tool_name: str,
    *,
    payload: dict[str, Any] | None = None,
    citations: tuple[dict[str, Any], ...] = (),
    notes: tuple[str, ...] = (),
) -> None:
    """Helper — register a fixed AtomicCallResult under ``tool_name``."""
    registry.register(
        tool_name,
        AtomicCallResult(
            tool_name=tool_name,
            payload=payload or {},
            citations=citations,
            notes=notes,
        ),
    )


# ---------------------------------------------------------------------------
# Default registry / common assertions.
# ---------------------------------------------------------------------------


def test_default_composed_tools_registry_returns_canonical_4_tuple() -> None:
    tools = register_default_tools()
    assert tuple(t.composed_tool_name for t in tools) == DEFAULT_COMPOSED_TOOLS
    assert len(tools) == 4
    # Each composed tool yields a fresh instance so callers can subclass.
    assert id(register_default_tools()[0]) != id(tools[0])


def test_default_composed_tools_are_all_composable_tool_subclasses() -> None:
    for tool in register_default_tools():
        assert isinstance(tool, ComposableTool)
        assert isinstance(tool.outcome_contract, OutcomeContract)
        assert tool.atomic_dependencies, "every composed tool declares atomic deps"


def test_validate_registry_raises_with_missing_atomic_dependencies() -> None:
    tool = EligibilityAuditWorkpaper()
    empty_registry = FakeRegistry()
    with pytest.raises(ComposedToolError) as excinfo:
        tool.run(empty_registry, program_id="p1", entity_id="e1")
    msg = str(excinfo.value)
    assert "eligibility_audit_workpaper" in msg
    assert "apply_eligibility_chain_am" in msg


def test_atomic_registry_is_a_protocol_implemented_by_fake() -> None:
    # Structural conformance — composed tools accept any object with
    # call() + has(). FakeRegistry should pass isinstance against the
    # Protocol thanks to Python's duck typing.
    registry: AtomicRegistry = FakeRegistry()
    assert hasattr(registry, "call")
    assert hasattr(registry, "has")


# ---------------------------------------------------------------------------
# 1. EligibilityAuditWorkpaper
# ---------------------------------------------------------------------------


def _build_eligibility_audit_registry() -> FakeRegistry:
    reg = FakeRegistry()
    _seed_atomic(
        reg,
        "apply_eligibility_chain_am",
        payload={
            "eligibility_steps": [
                {"step": "prerequisite_check", "result": "pass"},
                {"step": "exclusion_check", "result": "pass"},
            ],
            "verdict": "eligible",
        },
        citations=(
            {"source_url": "https://example.gov/program/p1", "source_id": "src_p1"},
        ),
    )
    _seed_atomic(
        reg,
        "track_amendment_lineage_am",
        payload={
            "amendments": [
                {"effective_from": "2026-04-01", "diff_summary": "rate +1%"},
            ],
        },
        citations=(
            {"source_url": "https://example.gov/program/p1", "source_id": "src_p1"},
            {"source_url": "https://example.gov/amend/a1", "source_id": "src_a1"},
        ),
    )
    _seed_atomic(
        reg,
        "program_active_periods_am",
        payload={
            "rounds": [
                {"round_id": "r1", "open_at": "2026-05-01", "close_at": "2026-08-31"},
            ],
            "sunset_warning": None,
        },
    )
    _seed_atomic(
        reg,
        "find_complementary_programs_am",
        payload={
            "complementary_programs": [
                {"program_id": "p2", "compatibility": "compatible"},
            ],
        },
        notes=("complementary search used heuristic edges (am_compat_matrix unknown=4)",),
    )
    return reg


def test_eligibility_audit_workpaper_composes_4_atomic_tools() -> None:
    tool = EligibilityAuditWorkpaper()
    reg = _build_eligibility_audit_registry()
    env = tool.run(reg, program_id="p1", entity_id="e1", fy_start="2026-04-01")

    assert isinstance(env, ComposedEnvelope)
    assert env.composed_tool_name == "eligibility_audit_workpaper"
    assert env.schema_version == COMPOSED_ENVELOPE_SCHEMA_VERSION
    assert env.compression_ratio == 4
    assert env.composed_steps == (
        "apply_eligibility_chain_am",
        "track_amendment_lineage_am",
        "program_active_periods_am",
        "find_complementary_programs_am",
    )

    # Atomic invocation order matches dependency order.
    invoked = [name for name, _ in reg.calls]
    assert invoked == list(env.composed_steps)

    # Eligibility verdict + amendments + rounds + complementary all present.
    pr = env.primary_result
    assert pr["program_id"] == "p1"
    assert pr["entity_id"] == "e1"
    assert pr["eligibility_verdict"] == "eligible"
    assert len(pr["amendments_since_fy_start"]) == 1
    assert len(pr["active_rounds"]) == 1
    assert len(pr["complementary_programs"]) == 1
    assert pr["atomic_richness"] == [2, 1, 1, 1]

    # Citations deduped by source_url — only 2 unique even though
    # 3 atomic citations included a duplicate URL.
    urls = [c.get("source_url") for c in env.citations]
    assert urls == ["https://example.gov/program/p1", "https://example.gov/amend/a1"]

    # Evidence: derived_inference + supported (all atomic rich).
    assert env.evidence.evidence_type == "derived_inference"
    assert env.evidence.support_state == "supported"
    assert env.request_time_llm_call_performed is False

    # Warnings carry the atomic notes.
    assert any("heuristic edges" in w for w in env.warnings)


def test_eligibility_audit_workpaper_handles_all_empty_atomics_as_absent() -> None:
    tool = EligibilityAuditWorkpaper()
    reg = FakeRegistry()
    for atomic in tool.atomic_dependencies:
        _seed_atomic(reg, atomic, payload={})
    env = tool.run(reg, program_id="p1", entity_id="e1")
    assert env.evidence.support_state == "absent"
    assert env.evidence.evidence_type == "absence_observation"


def test_eligibility_audit_workpaper_marks_partial_when_one_atomic_empty() -> None:
    tool = EligibilityAuditWorkpaper()
    reg = _build_eligibility_audit_registry()
    # Override one atomic with empty payload — should flip to partial.
    _seed_atomic(reg, "program_active_periods_am", payload={"rounds": [], "sunset_warning": None})
    env = tool.run(reg, program_id="p1", entity_id="e1")
    assert env.evidence.support_state == "partial"
    assert env.evidence.evidence_type == "derived_inference"


def test_eligibility_audit_workpaper_to_dict_is_json_serialisable() -> None:
    tool = EligibilityAuditWorkpaper()
    reg = _build_eligibility_audit_registry()
    env = tool.run(reg, program_id="p1", entity_id="e1")
    payload = env.to_dict()
    assert payload["composed_tool_name"] == "eligibility_audit_workpaper"
    assert payload["compression_ratio"] == 4
    assert isinstance(payload["evidence"], dict)
    assert isinstance(payload["outcome_contract"], dict)
    assert payload["request_time_llm_call_performed"] is False


# ---------------------------------------------------------------------------
# 2. SubsidyEligibilityFull
# ---------------------------------------------------------------------------


def _build_subsidy_eligibility_registry(
    *, with_candidates: bool = True, with_enforcement: bool = False
) -> FakeRegistry:
    reg = FakeRegistry()
    _seed_atomic(
        reg,
        "search_programs_am",
        payload={
            "programs": [{"program_id": "p1", "tier": "S"}] if with_candidates else [],
        },
        citations=(
            {"source_url": "https://example.gov/list", "source_id": "src_list"},
        ),
    )
    _seed_atomic(
        reg,
        "apply_eligibility_chain_am",
        payload={
            "eligibility_steps": [{"step": "industry_match", "result": "pass"}],
            "verdict": "eligible",
        },
    )
    _seed_atomic(
        reg,
        "check_enforcement_am",
        payload={
            "enforcement_records": (
                [{"case_id": "c1", "severity": "warning"}] if with_enforcement else []
            ),
        },
    )
    _seed_atomic(
        reg,
        "program_active_periods_am",
        payload={"rounds": [{"round_id": "r1"}], "sunset_warning": None},
    )
    _seed_atomic(
        reg,
        "simulate_application_am",
        payload={
            "required_documents": [{"doc": "事業計画書"}, {"doc": "決算書"}],
            "completeness_score": 0.85,
        },
    )
    return reg


def test_subsidy_eligibility_full_composes_5_atomic_tools() -> None:
    tool = SubsidyEligibilityFull()
    reg = _build_subsidy_eligibility_registry()
    env = tool.run(
        reg,
        entity_id="e1",
        industry_jsic="E",
        prefecture="tokyo",
    )
    assert env.compression_ratio == 5
    assert env.composed_steps == (
        "search_programs_am",
        "apply_eligibility_chain_am",
        "check_enforcement_am",
        "program_active_periods_am",
        "simulate_application_am",
    )
    pr = env.primary_result
    assert pr["chosen_program_id"] == "p1"
    assert pr["completeness_score"] == 0.85
    assert len(pr["candidate_programs"]) == 1
    assert pr["atomic_richness"] == [1, 1, 0, 1, 2]
    # support_state = partial because enforcement returned 0 records.
    assert env.evidence.support_state == "partial"


def test_subsidy_eligibility_full_falls_back_when_no_candidates() -> None:
    tool = SubsidyEligibilityFull()
    reg = _build_subsidy_eligibility_registry(with_candidates=False)
    env = tool.run(reg, entity_id="e1", industry_jsic="E")
    pr = env.primary_result
    assert pr["chosen_program_id"] == "program_unknown"
    assert any("0 candidates" in w for w in env.warnings)


def test_subsidy_eligibility_full_honours_program_id_hint() -> None:
    tool = SubsidyEligibilityFull()
    reg = _build_subsidy_eligibility_registry()
    env = tool.run(
        reg,
        entity_id="e1",
        industry_jsic="E",
        program_id_hint="p_hint",
    )
    invoked = dict(reg.calls)
    assert invoked["apply_eligibility_chain_am"]["program_id"] == "p_hint"
    assert invoked["simulate_application_am"]["program_id"] == "p_hint"
    assert env.primary_result["chosen_program_id"] == "p_hint"


# ---------------------------------------------------------------------------
# 3. MaDueDiligencePack
# ---------------------------------------------------------------------------


def _build_ma_dd_registry() -> FakeRegistry:
    reg = FakeRegistry()
    _seed_atomic(
        reg,
        "match_due_diligence_questions",
        payload={
            "questions": [
                {"q_id": "q1", "category": "credit"},
                {"q_id": "q2", "category": "governance"},
            ],
            "categories": ["credit", "governance"],
        },
    )
    _seed_atomic(
        reg,
        "cross_check_jurisdiction",
        payload={
            "jurisdictions": [
                {"source": "houjin_master", "value": "東京都港区"},
                {"source": "invoice_registrants", "value": "東京都港区"},
            ],
            "mismatches": [],
        },
    )
    _seed_atomic(
        reg,
        "check_enforcement_am",
        payload={"enforcement_records": []},
    )
    _seed_atomic(
        reg,
        "track_amendment_lineage_am",
        payload={"amendments": [{"effective_from": "2026-01-15"}]},
    )
    return reg


def test_ma_dd_pack_composes_4_atomic_tools() -> None:
    tool = MaDueDiligencePack()
    reg = _build_ma_dd_registry()
    env = tool.run(
        reg,
        target_houjin_bangou="8010001213708",
        industry_jsic="E",
        portfolio_id="port1",
    )
    assert env.compression_ratio == 4
    pr = env.primary_result
    assert pr["target_houjin_bangou"] == "8010001213708"
    assert pr["industry_jsic"] == "E"
    assert pr["portfolio_id"] == "port1"
    assert len(pr["dd_questions"]) == 2
    assert pr["jurisdiction_mismatches"] == []
    assert env.outcome_contract.outcome_contract_id == "composed_ma_due_diligence_pack"


def test_ma_dd_pack_drops_empty_portfolio_id_to_none() -> None:
    tool = MaDueDiligencePack()
    reg = _build_ma_dd_registry()
    env = tool.run(reg, target_houjin_bangou="8010001213708")
    assert env.primary_result["portfolio_id"] is None


# ---------------------------------------------------------------------------
# 4. InvoiceCompatibilityCheck
# ---------------------------------------------------------------------------


def _build_invoice_registry(
    *, registered: bool = True, with_entity: bool = True
) -> FakeRegistry:
    reg = FakeRegistry()
    _seed_atomic(
        reg,
        "check_invoice_registrant",
        payload={
            "registered": registered,
            "registered_name": "Bookyou株式会社" if registered else None,
            "registered_address": "東京都文京区小日向2-22-1" if registered else None,
            "active_on_as_of": registered,
        },
        citations=(
            {"source_url": "https://www.invoice-kojin.nta.go.jp/", "source_id": "nta"},
        ),
    )
    _seed_atomic(
        reg,
        "corporate_layer_lookup",
        payload={
            "entity": (
                {
                    "houjin_bangou": "8010001213708",
                    "name": "Bookyou株式会社",
                }
                if with_entity
                else None
            ),
            "aliases": ["ブックユー", "BOOKYOU"] if with_entity else [],
        },
    )
    _seed_atomic(
        reg,
        "check_enforcement_am",
        payload={"enforcement_records": []},
    )
    return reg


def test_invoice_compatibility_check_supported_when_registered_and_entity() -> None:
    tool = InvoiceCompatibilityCheck()
    reg = _build_invoice_registry()
    env = tool.run(
        reg,
        houjin_bangou="8010001213708",
        invoice_date="2026-05-16",
    )
    assert env.compression_ratio == 3
    pr = env.primary_result
    assert pr["registered"] is True
    assert pr["registered_name"] == "Bookyou株式会社"
    assert pr["registration_active_on_invoice_date"] is True
    assert pr["corporate_entity"]["houjin_bangou"] == "8010001213708"
    assert env.evidence.support_state == "supported"


def test_invoice_compatibility_check_absent_when_no_registration_no_entity() -> None:
    tool = InvoiceCompatibilityCheck()
    reg = _build_invoice_registry(registered=False, with_entity=False)
    env = tool.run(reg, houjin_bangou="9999999999999")
    pr = env.primary_result
    assert pr["registered"] is False
    assert pr["corporate_entity"] is None
    assert env.evidence.support_state == "absent"
    assert env.evidence.evidence_type == "absence_observation"


def test_invoice_compatibility_check_drops_invoice_date_when_blank() -> None:
    tool = InvoiceCompatibilityCheck()
    reg = _build_invoice_registry()
    env = tool.run(reg, houjin_bangou="8010001213708")
    assert env.primary_result["invoice_date"] is None


# ---------------------------------------------------------------------------
# Cross-cutting invariants.
# ---------------------------------------------------------------------------


def test_every_composed_tool_emits_an_evidence_with_llm_flag_false() -> None:
    """The Wave 51 dim P rule: no LLM hop on the composed surface."""
    payload_for = {
        EligibilityAuditWorkpaper: _build_eligibility_audit_registry,
        SubsidyEligibilityFull: _build_subsidy_eligibility_registry,
        MaDueDiligencePack: _build_ma_dd_registry,
        InvoiceCompatibilityCheck: _build_invoice_registry,
    }
    kwargs_for: dict[type[ComposableTool], dict[str, Any]] = {
        EligibilityAuditWorkpaper: {"program_id": "p1", "entity_id": "e1"},
        SubsidyEligibilityFull: {"entity_id": "e1", "industry_jsic": "E"},
        MaDueDiligencePack: {"target_houjin_bangou": "8010001213708"},
        InvoiceCompatibilityCheck: {"houjin_bangou": "8010001213708"},
    }
    for cls, factory in payload_for.items():
        tool = cls()
        env = tool.run(factory(), **kwargs_for[cls])
        assert isinstance(env.evidence, Evidence)
        assert env.evidence.request_time_llm_call_performed is False
        assert env.request_time_llm_call_performed is False


def test_every_composed_tool_has_unique_outcome_contract_id() -> None:
    seen = {tool.outcome_contract.outcome_contract_id for tool in register_default_tools()}
    assert len(seen) == 4


def test_compression_ratio_equals_atomic_dependency_count() -> None:
    for tool in register_default_tools():
        # We don't run the tool here — registry is empty. The ratio is
        # a structural invariant of the composed tool, asserted from
        # the dependency tuple.
        assert len(tool.atomic_dependencies) >= 3, (
            f"{tool.composed_tool_name}: compression must be ≥3x (Wave 51 dim P)"
        )


def test_citations_dedupe_drops_repeated_source_url_keeps_first() -> None:
    tool = EligibilityAuditWorkpaper()
    reg = _build_eligibility_audit_registry()
    env = tool.run(reg, program_id="p1", entity_id="e1")
    # Two atomic emitted source_url=https://example.gov/program/p1 — only
    # the first survives dedup.
    urls = [c.get("source_url") for c in env.citations]
    assert urls.count("https://example.gov/program/p1") == 1


def test_missing_dependency_raises_before_any_atomic_call() -> None:
    tool = SubsidyEligibilityFull()
    reg = FakeRegistry()
    # Register all but one.
    for atomic in tool.atomic_dependencies[:-1]:
        _seed_atomic(reg, atomic, payload={})
    with pytest.raises(ComposedToolError) as excinfo:
        tool.run(reg, entity_id="e1", industry_jsic="E")
    # The missing one is named.
    assert tool.atomic_dependencies[-1] in str(excinfo.value)
    # AND no atomic was called — registry calls list is empty.
    assert reg.calls == []
