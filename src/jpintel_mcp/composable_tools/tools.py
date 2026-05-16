"""The 4 initial composed tools per Wave 51 dim P spec.

The Wave 51 dim P memory ratifies a 4-tool initial cohort:

    eligibility_audit_workpaper  — 税理士 monthly audit workpaper.
    subsidy_eligibility_full     — 補助金 7-step full eligibility check.
    ma_due_diligence_pack        — M&A DD 12-axis bundle.
    invoice_compatibility_check  — 適格事業者照合 + corporate enrichment.

Each composed tool wraps 3-7 atomic tools that already exist on the
jpcite MCP surface (``apply_eligibility_chain_am`` /
``find_complementary_programs_am`` / ``cross_check_jurisdiction`` /
``match_due_diligence_questions`` / etc.). Composition happens
**server-side via direct Python calls** — composed tools do NOT re-enter
the MCP protocol.

Per the ``feedback_composable_tools_pattern`` rules:

* No LLM API call inside any composed tool body.
* No aggregator fetch — every atomic call hits jpcite's own SQLite +
  pure Python.
* No partial-fail abandon — atomic tool partial results surface in
  ``ComposedEnvelope.warnings`` rather than raising.
* Compression ratio (len(atomic_dependencies)) is the agent-visible
  multiplier ¥3 × N → ¥3 × 1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jpintel_mcp.agent_runtime.contracts import (
    Evidence,
    OutcomeContract,
)
from jpintel_mcp.composable_tools.base import (
    AtomicRegistry,
    ComposableTool,
    ComposedEnvelope,
)


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Composed tools stamp this on every :class:`Evidence` they emit so
    downstream consumers can age the result against snapshot cadence.
    Always UTC + ``Z`` suffix to avoid timezone ambiguity.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_str_id(value: Any, fallback: str) -> str:
    """Coerce a candidate identifier to a non-empty string.

    Composed tools accept arbitrary kwargs (entity_id, houjin_bangou,
    program_id, ...) — this helper ensures the id makes it into the
    composed evidence trail even when the caller passed an int / None.
    """
    if value is None:
        return fallback
    s = str(value).strip()
    return s if s else fallback


def _dedupe_citations(
    citations: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Deduplicate atomic citation dicts by ``source_url`` then ``source_id``.

    Several atomic tools cite the same primary source (e.g. METI
    program detail page) — surfacing the same URL N times in the
    composed envelope is noise. We keep the first occurrence so the
    source-of-truth ordering aligns with atomic call order.
    """
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for c in citations:
        key = ""
        url = c.get("source_url")
        if isinstance(url, str) and url:
            key = url
        else:
            sid = c.get("source_id")
            if isinstance(sid, str) and sid:
                key = sid
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(c)
    return tuple(deduped)


def _build_evidence(
    composed_tool_name: str,
    receipt_ids: tuple[str, ...],
    *,
    support_state: str,
    temporal_envelope: str,
) -> Evidence:
    """Construct an :class:`Evidence` for the composed result.

    ``support_state`` is constrained to the 4 values the underlying
    :class:`Evidence` accepts (``supported`` / ``partial`` / ``contested``
    / ``absent``). Composed tools pass:

    * ``supported`` when every atomic returned a populated payload.
    * ``partial`` when at least one atomic returned a sparse / empty
      result but the composed answer remains useful.
    * ``absent`` when the composed answer is "no hit, all atomic empty".

    ``receipt_ids`` is the tuple of synthesised receipt identifiers
    referencing the atomic call ledger. They are non-empty by the
    :class:`Evidence` validator.
    """
    if not receipt_ids:
        receipt_ids = (f"composed_receipt_{composed_tool_name}_synthetic",)
    claim_ref_id = f"composed_claim_{composed_tool_name}_v1"
    if support_state == "absent":
        evidence_type: str = "absence_observation"
    else:
        evidence_type = "derived_inference"
    return Evidence(
        evidence_id=f"composed_evidence_{composed_tool_name}_v1",
        claim_ref_ids=(claim_ref_id,),
        receipt_ids=receipt_ids,
        evidence_type=evidence_type,
        support_state=support_state,
        temporal_envelope=temporal_envelope,
        observed_at=_now_iso(),
    )


def _build_outcome_contract(
    composed_tool_name: str,
    *,
    display_name: str,
    packet_ids: tuple[str, ...],
    billable: bool,
) -> OutcomeContract:
    """Construct an :class:`OutcomeContract` for the composed tool.

    Composed tools carry their own outcome contract id (one per
    composed tool) so the 4 surfaces in ``DELIVERABLE_PRICING_RULES``
    can price them distinctly from the atomic surface.
    """
    return OutcomeContract(
        outcome_contract_id=f"composed_{composed_tool_name}",
        display_name=display_name,
        packet_ids=packet_ids,
        billable=billable,
    )


def _support_state_for(
    payload_richness: tuple[int, ...],
) -> str:
    """Pick a ``support_state`` value from atomic richness counts.

    Each composed tool measures how many rows / entries each atomic
    returned, then summarises with:

    * ``supported`` — every atomic returned at least one row.
    * ``partial`` — some atomic returned rows, others were empty.
    * ``absent`` — every atomic returned zero rows.

    The simple-majority heuristic keeps the gate deterministic — no
    inference. Calling code can override with an explicit string.
    """
    if not payload_richness:
        return "absent"
    if all(n > 0 for n in payload_richness):
        return "supported"
    if any(n > 0 for n in payload_richness):
        return "partial"
    return "absent"


# ---------------------------------------------------------------------------
# 1. eligibility_audit_workpaper — 税理士 monthly audit workpaper
# ---------------------------------------------------------------------------


class EligibilityAuditWorkpaper(ComposableTool):
    """Composed tool — 税理士 monthly eligibility audit workpaper.

    Atomic dependencies (in invocation order):

    1. ``apply_eligibility_chain_am`` — prerequisite + exclusion eval.
    2. ``track_amendment_lineage_am`` — amendment snapshots since FY start.
    3. ``program_active_periods_am`` — active rounds / sunset warning.
    4. ``find_complementary_programs_am`` — complementary program graph.

    Caller-facing compression: 1 composed call replaces 4 atomic
    invocations the customer would otherwise chain manually.

    Required ``kwargs``: ``program_id`` (str — the program under audit).
    Optional: ``entity_id`` (str — 顧問先 法人 id; passed to the
    eligibility chain), ``fy_start`` (str ISO date for amendment window).
    """

    @property
    def composed_tool_name(self) -> str:
        return "eligibility_audit_workpaper"

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        return (
            "apply_eligibility_chain_am",
            "track_amendment_lineage_am",
            "program_active_periods_am",
            "find_complementary_programs_am",
        )

    @property
    def outcome_contract(self) -> OutcomeContract:
        return _build_outcome_contract(
            self.composed_tool_name,
            display_name="税理士 monthly eligibility audit workpaper (composed)",
            packet_ids=("packet_eligibility_audit_workpaper",),
            billable=True,
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        program_id = _coerce_str_id(kwargs.get("program_id"), "program_unknown")
        entity_id = _coerce_str_id(kwargs.get("entity_id"), "entity_unknown")
        fy_start = _coerce_str_id(kwargs.get("fy_start"), "1970-01-01")

        elig = registry.call(
            "apply_eligibility_chain_am",
            program_id=program_id,
            entity_id=entity_id,
        )
        lineage = registry.call(
            "track_amendment_lineage_am",
            program_id=program_id,
            since=fy_start,
        )
        active = registry.call(
            "program_active_periods_am",
            program_id=program_id,
        )
        complementary = registry.call(
            "find_complementary_programs_am",
            seed_program_id=program_id,
        )

        citations = _dedupe_citations(
            elig.citations + lineage.citations + active.citations + complementary.citations
        )
        warnings: list[str] = []
        warnings.extend(elig.notes)
        warnings.extend(lineage.notes)
        warnings.extend(active.notes)
        warnings.extend(complementary.notes)

        richness = (
            len(elig.payload.get("eligibility_steps", []) or []),
            len(lineage.payload.get("amendments", []) or []),
            len(active.payload.get("rounds", []) or []),
            len(complementary.payload.get("complementary_programs", []) or []),
        )
        support = _support_state_for(richness)

        primary: dict[str, Any] = {
            "program_id": program_id,
            "entity_id": entity_id,
            "eligibility_steps": elig.payload.get("eligibility_steps", []),
            "eligibility_verdict": elig.payload.get("verdict", "unknown"),
            "amendments_since_fy_start": lineage.payload.get("amendments", []),
            "active_rounds": active.payload.get("rounds", []),
            "sunset_warning": active.payload.get("sunset_warning"),
            "complementary_programs": complementary.payload.get("complementary_programs", []),
            "atomic_richness": list(richness),
        }
        evidence = _build_evidence(
            self.composed_tool_name,
            receipt_ids=tuple(
                f"composed_receipt_{self.composed_tool_name}_{atomic}"
                for atomic in self.atomic_dependencies
            ),
            support_state=support,
            temporal_envelope=f"{fy_start}/observed",
        )
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=self.atomic_dependencies,
            primary_result=primary,
            citations=citations,
            warnings=tuple(warnings),
            compression_ratio=len(self.atomic_dependencies),
        )


# ---------------------------------------------------------------------------
# 2. subsidy_eligibility_full — 補助金 7-step full eligibility check
# ---------------------------------------------------------------------------


class SubsidyEligibilityFull(ComposableTool):
    """Composed tool — full 補助金 7-step eligibility check.

    Atomic dependencies (in invocation order):

    1. ``search_programs_am`` — narrow by entity industry / region.
    2. ``apply_eligibility_chain_am`` — prerequisite + exclusion eval.
    3. ``check_enforcement_am`` — 行政処分 disqualification check.
    4. ``program_active_periods_am`` — active rounds / sunset.
    5. ``simulate_application_am`` — required documents + readiness.

    Caller-facing compression: 1 composed call replaces 5 atomic
    invocations a 補助金 consultant would otherwise chain per program.

    Required ``kwargs``: ``entity_id`` (str), ``industry_jsic`` (str).
    Optional: ``prefecture`` (str), ``program_id_hint`` (str — when the
    caller has already narrowed to a candidate program).
    """

    @property
    def composed_tool_name(self) -> str:
        return "subsidy_eligibility_full"

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        return (
            "search_programs_am",
            "apply_eligibility_chain_am",
            "check_enforcement_am",
            "program_active_periods_am",
            "simulate_application_am",
        )

    @property
    def outcome_contract(self) -> OutcomeContract:
        return _build_outcome_contract(
            self.composed_tool_name,
            display_name="補助金 7-step full eligibility check (composed)",
            packet_ids=("packet_subsidy_eligibility_full",),
            billable=True,
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        entity_id = _coerce_str_id(kwargs.get("entity_id"), "entity_unknown")
        industry_jsic = _coerce_str_id(kwargs.get("industry_jsic"), "unknown")
        prefecture = _coerce_str_id(kwargs.get("prefecture"), "any")
        program_id_hint = _coerce_str_id(kwargs.get("program_id_hint"), "")

        search = registry.call(
            "search_programs_am",
            entity_id=entity_id,
            industry_jsic=industry_jsic,
            prefecture=prefecture,
        )
        candidates = list(search.payload.get("programs", []) or [])
        chosen_id: str
        if program_id_hint:
            chosen_id = program_id_hint
        elif candidates:
            first = candidates[0]
            chosen_id = _coerce_str_id(
                first.get("program_id") if isinstance(first, dict) else None,
                "program_unknown",
            )
        else:
            chosen_id = "program_unknown"

        elig = registry.call(
            "apply_eligibility_chain_am",
            program_id=chosen_id,
            entity_id=entity_id,
        )
        enforcement = registry.call(
            "check_enforcement_am",
            entity_id=entity_id,
        )
        active = registry.call(
            "program_active_periods_am",
            program_id=chosen_id,
        )
        simulation = registry.call(
            "simulate_application_am",
            program_id=chosen_id,
            entity_id=entity_id,
        )

        citations = _dedupe_citations(
            search.citations
            + elig.citations
            + enforcement.citations
            + active.citations
            + simulation.citations
        )
        warnings: list[str] = []
        warnings.extend(search.notes)
        warnings.extend(elig.notes)
        warnings.extend(enforcement.notes)
        warnings.extend(active.notes)
        warnings.extend(simulation.notes)
        if not candidates and not program_id_hint:
            warnings.append(
                "subsidy_eligibility_full: search_programs_am returned 0 candidates "
                "and no program_id_hint provided; downstream atomic calls use "
                "program_unknown as a placeholder."
            )

        richness = (
            len(candidates),
            len(elig.payload.get("eligibility_steps", []) or []),
            int(bool(enforcement.payload.get("enforcement_records", []))),
            len(active.payload.get("rounds", []) or []),
            len(simulation.payload.get("required_documents", []) or []),
        )
        support = _support_state_for(richness)

        primary: dict[str, Any] = {
            "entity_id": entity_id,
            "industry_jsic": industry_jsic,
            "prefecture": prefecture,
            "candidate_programs": candidates,
            "chosen_program_id": chosen_id,
            "eligibility_steps": elig.payload.get("eligibility_steps", []),
            "eligibility_verdict": elig.payload.get("verdict", "unknown"),
            "enforcement_records": enforcement.payload.get("enforcement_records", []),
            "active_rounds": active.payload.get("rounds", []),
            "sunset_warning": active.payload.get("sunset_warning"),
            "required_documents": simulation.payload.get("required_documents", []),
            "completeness_score": simulation.payload.get("completeness_score"),
            "atomic_richness": list(richness),
        }
        evidence = _build_evidence(
            self.composed_tool_name,
            receipt_ids=tuple(
                f"composed_receipt_{self.composed_tool_name}_{atomic}"
                for atomic in self.atomic_dependencies
            ),
            support_state=support,
            temporal_envelope="rolling/observed",
        )
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=self.atomic_dependencies,
            primary_result=primary,
            citations=citations,
            warnings=tuple(warnings),
            compression_ratio=len(self.atomic_dependencies),
        )


# ---------------------------------------------------------------------------
# 3. ma_due_diligence_pack — M&A DD 12-axis bundle
# ---------------------------------------------------------------------------


class MaDueDiligencePack(ComposableTool):
    """Composed tool — M&A DD 12-axis bundle.

    Atomic dependencies (in invocation order):

    1. ``match_due_diligence_questions`` — DD question deck.
    2. ``cross_check_jurisdiction`` — 法務局 / NTA / 採択 jurisdictions.
    3. ``check_enforcement_am`` — 行政処分 history.
    4. ``track_amendment_lineage_am`` — recent amendment impact on
       eligibility windows.

    Caller-facing compression: 1 composed call replaces 4 atomic
    invocations an M&A advisor would otherwise chain across DD
    workpapers.

    Required ``kwargs``: ``target_houjin_bangou`` (str — 法人番号 of
    the DD target). Optional: ``industry_jsic`` (str), ``portfolio_id``
    (str — when the buyer is a portfolio holding company).
    """

    @property
    def composed_tool_name(self) -> str:
        return "ma_due_diligence_pack"

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        return (
            "match_due_diligence_questions",
            "cross_check_jurisdiction",
            "check_enforcement_am",
            "track_amendment_lineage_am",
        )

    @property
    def outcome_contract(self) -> OutcomeContract:
        return _build_outcome_contract(
            self.composed_tool_name,
            display_name="M&A 12-axis due diligence pack (composed)",
            packet_ids=("packet_ma_due_diligence_pack",),
            billable=True,
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        houjin_bangou = _coerce_str_id(
            kwargs.get("target_houjin_bangou"), "houjin_unknown"
        )
        industry_jsic = _coerce_str_id(kwargs.get("industry_jsic"), "unknown")
        portfolio_id = _coerce_str_id(kwargs.get("portfolio_id"), "")

        dd_questions = registry.call(
            "match_due_diligence_questions",
            target_houjin_bangou=houjin_bangou,
            industry_jsic=industry_jsic,
            portfolio_id=portfolio_id,
        )
        jurisdictions = registry.call(
            "cross_check_jurisdiction",
            target_houjin_bangou=houjin_bangou,
        )
        enforcement = registry.call(
            "check_enforcement_am",
            houjin_bangou=houjin_bangou,
        )
        lineage = registry.call(
            "track_amendment_lineage_am",
            houjin_bangou=houjin_bangou,
        )

        citations = _dedupe_citations(
            dd_questions.citations
            + jurisdictions.citations
            + enforcement.citations
            + lineage.citations
        )
        warnings: list[str] = []
        warnings.extend(dd_questions.notes)
        warnings.extend(jurisdictions.notes)
        warnings.extend(enforcement.notes)
        warnings.extend(lineage.notes)

        richness = (
            len(dd_questions.payload.get("questions", []) or []),
            int(bool(jurisdictions.payload.get("jurisdictions", []))),
            len(enforcement.payload.get("enforcement_records", []) or []),
            len(lineage.payload.get("amendments", []) or []),
        )
        support = _support_state_for(richness)

        primary: dict[str, Any] = {
            "target_houjin_bangou": houjin_bangou,
            "industry_jsic": industry_jsic,
            "portfolio_id": portfolio_id or None,
            "dd_questions": dd_questions.payload.get("questions", []),
            "dd_categories": dd_questions.payload.get("categories", []),
            "jurisdictions": jurisdictions.payload.get("jurisdictions", []),
            "jurisdiction_mismatches": jurisdictions.payload.get("mismatches", []),
            "enforcement_records": enforcement.payload.get("enforcement_records", []),
            "amendment_impact": lineage.payload.get("amendments", []),
            "atomic_richness": list(richness),
        }
        evidence = _build_evidence(
            self.composed_tool_name,
            receipt_ids=tuple(
                f"composed_receipt_{self.composed_tool_name}_{atomic}"
                for atomic in self.atomic_dependencies
            ),
            support_state=support,
            temporal_envelope="rolling/observed",
        )
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=self.atomic_dependencies,
            primary_result=primary,
            citations=citations,
            warnings=tuple(warnings),
            compression_ratio=len(self.atomic_dependencies),
        )


# ---------------------------------------------------------------------------
# 4. invoice_compatibility_check — 適格事業者照合 + corporate enrichment
# ---------------------------------------------------------------------------


class InvoiceCompatibilityCheck(ComposableTool):
    """Composed tool — 適格事業者照合 + 取引先 enrichment.

    Atomic dependencies (in invocation order):

    1. ``check_invoice_registrant`` — NTA 適格事業者 registry lookup.
    2. ``corporate_layer_lookup`` — gBiz / houjin master enrichment.
    3. ``check_enforcement_am`` — 行政処分 history of the counterparty.

    Caller-facing compression: 1 composed call replaces 3 atomic
    invocations a 経理 ops user would otherwise chain per counterparty.

    Required ``kwargs``: ``houjin_bangou`` (str — 13-digit 法人番号 or
    "T" prefix invoice number). Optional: ``invoice_date`` (str ISO
    date — when the caller wants to verify registration was active on
    a specific invoice date).
    """

    @property
    def composed_tool_name(self) -> str:
        return "invoice_compatibility_check"

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        return (
            "check_invoice_registrant",
            "corporate_layer_lookup",
            "check_enforcement_am",
        )

    @property
    def outcome_contract(self) -> OutcomeContract:
        return _build_outcome_contract(
            self.composed_tool_name,
            display_name="適格事業者照合 + 取引先 enrichment (composed)",
            packet_ids=("packet_invoice_compatibility_check",),
            billable=True,
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        houjin_bangou = _coerce_str_id(kwargs.get("houjin_bangou"), "houjin_unknown")
        invoice_date = _coerce_str_id(kwargs.get("invoice_date"), "")

        invoice = registry.call(
            "check_invoice_registrant",
            houjin_bangou=houjin_bangou,
            as_of=invoice_date,
        )
        corporate = registry.call(
            "corporate_layer_lookup",
            houjin_bangou=houjin_bangou,
        )
        enforcement = registry.call(
            "check_enforcement_am",
            houjin_bangou=houjin_bangou,
        )

        citations = _dedupe_citations(
            invoice.citations + corporate.citations + enforcement.citations
        )
        warnings: list[str] = []
        warnings.extend(invoice.notes)
        warnings.extend(corporate.notes)
        warnings.extend(enforcement.notes)

        is_registered = bool(invoice.payload.get("registered", False))
        richness = (
            int(is_registered),
            int(bool(corporate.payload.get("entity"))),
            len(enforcement.payload.get("enforcement_records", []) or []),
        )
        # Special case: registered=True with empty enforcement is still
        # supported (the desirable case). support_state should NOT mark
        # this as partial; we explicitly fold "registered=True" into a
        # supported verdict and reserve "absent" for the
        # registered=False AND no entity row case.
        if is_registered and corporate.payload.get("entity"):
            support = "supported"
        else:
            support = _support_state_for(richness)

        primary: dict[str, Any] = {
            "houjin_bangou": houjin_bangou,
            "invoice_date": invoice_date or None,
            "registered": is_registered,
            "registered_name": invoice.payload.get("registered_name"),
            "registered_address": invoice.payload.get("registered_address"),
            "registration_active_on_invoice_date": invoice.payload.get(
                "active_on_as_of"
            ),
            "corporate_entity": corporate.payload.get("entity"),
            "corporate_aliases": corporate.payload.get("aliases", []),
            "enforcement_records": enforcement.payload.get("enforcement_records", []),
            "atomic_richness": list(richness),
        }
        evidence = _build_evidence(
            self.composed_tool_name,
            receipt_ids=tuple(
                f"composed_receipt_{self.composed_tool_name}_{atomic}"
                for atomic in self.atomic_dependencies
            ),
            support_state=support,
            temporal_envelope=f"{invoice_date or 'rolling'}/observed",
        )
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=self.atomic_dependencies,
            primary_result=primary,
            citations=citations,
            warnings=tuple(warnings),
            compression_ratio=len(self.atomic_dependencies),
        )


__all__ = [
    "EligibilityAuditWorkpaper",
    "InvoiceCompatibilityCheck",
    "MaDueDiligencePack",
    "SubsidyEligibilityFull",
]
