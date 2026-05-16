"""Wave 51 service composition chains across dim K-S modules.

Where ``tools.py`` ships composed tools whose atomic dependencies are
existing MCP atomic primitives (``apply_eligibility_chain_am`` etc),
this module ships **cross-dim composition chains** that thread the
Wave 51 dim K-S modules together into compound flows:

    evidence_with_provenance        — dim P + Q + O + N
    session_aware_eligibility_check — dim L + M + K
    federated_handoff_with_audit    — dim P + R + N
    temporal_compliance_audit       — dim Q + M + O

These chains exist because the 11 Wave 51 modules currently live as
isolated atomic primitives — agents must invoke 1 tool at a time, which
defeats the "per-call value" composition guarantee. Each chain in this
module wraps **multiple** dim modules behind a single composed entry
point so:

* a customer invocation drives 3-5 dim modules at ¥3/req billing units
  rather than 3-5 separate ¥3/req calls;
* the canonical :class:`Evidence` + :class:`OutcomeContract` envelope
  surfaces a single source-of-truth audit trail covering every dim
  module touched;
* deterministic (no-LLM) composition keeps the per-call latency budget
  under the 200 ms p50 target the Wave 50 RC1 contract layer was sized
  for.

Non-negotiable rules (mirrored from ``feedback_composable_tools_pattern``)
-------------------------------------------------------------------------
* **No LLM API import.** No ``anthropic`` / ``openai`` /
  ``google.generativeai`` / ``claude_agent_sdk``. The composition is
  decision-tree deterministic — order is fixed in each chain's
  :meth:`compose` body.
* **No aggregator fetch.** Every chain calls Wave 51 dim module
  primitives + (optionally) an injected :class:`AtomicRegistry`
  for legacy 139-tool MCP atomic surface reuse.
* **No partial-fail abandon.** When a dim module raises a recoverable
  error (e.g. ``SnapshotResult.nearest is None``), the chain surfaces
  the partial state in :attr:`ComposedEnvelope.warnings` rather than
  bubbling the exception. Unrecoverable errors (missing atomic
  dependency on the registry) still raise :class:`ComposedToolError`
  so the caller can decide to fall back to atomic chaining.
* **JPCIR envelope reuse.** Every chain emits a
  :class:`ComposedEnvelope` whose ``evidence`` is the canonical
  :class:`Evidence` model and whose ``outcome_contract`` is a
  :class:`OutcomeContract` — no fresh schema namespace.

Why these specific 4 chains
---------------------------
* **evidence_with_provenance** — bind composable_tools output to a
  specific :class:`Snapshot` (dim Q), Ed25519-sign the fact metadata
  (dim O), and gate the response behind a k-anonymity floor (dim N).
  This is the "signed audit-grade evidence" surface that 税理士 +
  M&A advisors require for use in 過去申告 review packs.
* **session_aware_eligibility_check** — wrap rule_tree.evaluate
  (dim M) in a 24h session (dim L) and enqueue a predictive event
  (dim K) so the agent gets notified when the underlying ruleset
  changes. This is the "compound multi-turn eligibility" surface.
* **federated_handoff_with_audit** — when composable_tools cannot
  answer, ask federated_mcp.recommend_handoff for a peer MCP, then
  write an APPI-grade audit entry (dim N audit log) so the handoff
  is reproducible. This is the "no-data graceful degradation"
  surface that drives Stream J organic funnel retention.
* **temporal_compliance_audit** — compare two time_machine snapshots
  (dim Q) via counterfactual_diff, evaluate a rule_tree (dim M) on
  the diff, then Ed25519-sign the verdict (dim O). This is the
  "compliance regression" surface for monthly closing review.

Public surface
--------------
    EvidenceWithProvenance         — ComposableTool subclass.
    SessionAwareEligibilityCheck   — ComposableTool subclass.
    FederatedHandoffWithAudit      — ComposableTool subclass.
    TemporalComplianceAudit        — ComposableTool subclass.
    WAVE51_CHAIN_TOOLS             — Canonical 4-tuple of chain names.
    register_wave51_chains()       — Build fresh instances per call.

All chains accept an :class:`AtomicRegistry` per
:class:`ComposableTool.run`, but treat the registry as **optional fuel**:
when the registry is missing the requested atomic, the chain falls
through to dim-module-only composition rather than raising. Tests inject
a deterministic fake registry to assert per-chain behaviour without
spinning up the full FastMCP server.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

from jpintel_mcp.agent_runtime.contracts import (
    Evidence,
    OutcomeContract,
)
from jpintel_mcp.anonymized_query import (
    REDACT_POLICY_VERSION,
    check_k_anonymity,
)
from jpintel_mcp.anonymized_query.audit_log import (
    cohort_hash,
    write_audit_entry,
)
from jpintel_mcp.composable_tools.base import (
    AtomicRegistry,
    ComposableTool,
    ComposedEnvelope,
)
from jpintel_mcp.explainable_fact import (
    FactMetadata,
    canonical_payload,
)
from jpintel_mcp.federated_mcp import (
    FederatedRegistry,
    PartnerMcp,
    recommend_handoff,
)
from jpintel_mcp.predictive_service import (
    PredictionEvent,
    enqueue_event,
)
from jpintel_mcp.rule_tree import (
    EvalResult,
    RuleTree,
    evaluate_tree,
)
from jpintel_mcp.session_context import (
    SavedContext,
    SessionRegistry,
)
from jpintel_mcp.time_machine import (
    DiffResult,
    Snapshot,
    SnapshotRegistry,
    SnapshotResult,
    counterfactual_diff,
    query_as_of,
)

# ---------------------------------------------------------------------------
# Internal helpers — shared by every chain
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """UTC ISO-8601 timestamp with trailing ``Z``.

    Used for :class:`Evidence.observed_at` so downstream consumers can
    age the composed result against snapshot cadence.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_str(value: object, fallback: str) -> str:
    """Coerce ``value`` to a non-empty stripped string, falling back."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _coerce_int(value: object, fallback: int) -> int:
    """Coerce ``value`` to an int, falling back on TypeError/ValueError."""
    if value is None:
        return fallback
    if isinstance(value, bool):
        # bool is an int subclass; reject explicitly so True / False do
        # not silently become 1 / 0 in a chain expecting a real cohort.
        return fallback
    if isinstance(value, int):
        return value
    if isinstance(value, (str, float)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback
    return fallback


def _build_evidence(
    chain_name: str,
    *,
    receipt_ids: tuple[str, ...],
    support_state: str,
    temporal_envelope: str,
    evidence_type: str = "derived_inference",
) -> Evidence:
    """Build the canonical :class:`Evidence` for a Wave 51 chain.

    The ``support_state`` is constrained by the contract validator on
    :class:`Evidence` to one of ``supported`` / ``partial`` /
    ``contested`` / ``absent``. ``absent`` requires
    ``evidence_type='absence_observation'`` — callers passing
    ``absent`` MUST also pass that evidence type or the model raises.
    """
    if not receipt_ids:
        receipt_ids = (f"chain_receipt_{chain_name}_synthetic",)
    claim_ref_id = f"chain_claim_{chain_name}_v1"
    # ``Evidence`` constrains evidence_type + support_state to closed
    # Literal sets; ``model_validate`` raises ValidationError when a
    # chain passes a value outside the contract — caught by the chain
    # caller and surfaced as a programmer error rather than swallowed.
    return Evidence.model_validate(
        {
            "evidence_id": f"chain_evidence_{chain_name}_v1",
            "claim_ref_ids": (claim_ref_id,),
            "receipt_ids": receipt_ids,
            "evidence_type": evidence_type,
            "support_state": support_state,
            "temporal_envelope": temporal_envelope,
            "observed_at": _now_iso(),
        }
    )


def _build_outcome_contract(
    chain_name: str,
    *,
    display_name: str,
    packet_ids: tuple[str, ...],
) -> OutcomeContract:
    """Build the canonical :class:`OutcomeContract` for a Wave 51 chain."""
    return OutcomeContract(
        outcome_contract_id=f"chain_{chain_name}",
        display_name=display_name,
        packet_ids=packet_ids,
        billable=True,
    )


# ---------------------------------------------------------------------------
# 1. evidence_with_provenance — dim P + Q + O + N
# ---------------------------------------------------------------------------


class EvidenceWithProvenance(ComposableTool):
    """Chain — composable_tools → time_machine → explainable_fact → anonymized_query.

    Compound flow:

    1. (Optional) Invoke a composable_tools atomic via the injected
       registry if present — used by the 税理士 audit-workpaper path
       to obtain the candidate fact body that needs signing.
    2. :func:`query_as_of` against the dim Q snapshot registry to lock
       the response to a specific point-in-time snapshot. When no
       snapshot is available, the chain proceeds with a "rolling"
       temporal envelope and surfaces the gap in ``warnings``.
    3. Build a :class:`FactMetadata` with ``verified_by='ed25519_sig'``
       and compute the canonical Ed25519 sign payload via
       :func:`canonical_payload`. The chain does NOT actually sign
       (private keys are caller-owned) — it returns the payload bytes
       so the consumer can hand to an HSM. The payload's hex digest
       is surfaced for audit trail.
    4. :func:`check_k_anonymity` against the cohort size derived from
       the snapshot payload. When the cohort fails the k=5 floor the
       chain marks the envelope ``support_state='partial'`` and
       surfaces the gate decision in ``warnings``.

    Required ``kwargs``: ``fact_id`` (str), ``cohort_size`` (int).
    Optional: ``dataset_id`` (str, default "programs"), ``as_of_date``
    (date), ``source_doc`` (str), ``snapshot_registry``
    (:class:`SnapshotRegistry`), ``atomic_tool_name`` (str — when set,
    the chain invokes the atomic via the injected registry and merges
    its citations into the envelope).
    """

    @property
    def composed_tool_name(self) -> str:
        return "evidence_with_provenance"

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        # No mandatory atomic dependencies — the chain runs purely on
        # dim K-S module primitives. Optional atomic_tool_name kwarg is
        # opportunistic, not declared here, so :meth:`validate_registry`
        # never trips on its absence.
        return ()

    @property
    def outcome_contract(self) -> OutcomeContract:
        return _build_outcome_contract(
            self.composed_tool_name,
            display_name="Signed evidence with snapshot provenance (composed)",
            packet_ids=("packet_evidence_with_provenance",),
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        fact_id = _coerce_str(kwargs.get("fact_id"), "fact_unknown")
        cohort_size = _coerce_int(kwargs.get("cohort_size"), 0)
        dataset_id = _coerce_str(kwargs.get("dataset_id"), "programs")
        source_doc = _coerce_str(
            kwargs.get("source_doc"),
            "https://www.e-gov.go.jp/",
        )
        atomic_tool_name = _coerce_str(kwargs.get("atomic_tool_name"), "")

        warnings: list[str] = []
        citations: list[dict[str, Any]] = []

        # Step 1: optional composable_tools atomic — opportunistic.
        atomic_payload: dict[str, Any] = {}
        atomic_invoked = False
        if atomic_tool_name and registry.has(atomic_tool_name):
            atomic_result = registry.call(atomic_tool_name)
            atomic_payload = dict(atomic_result.payload)
            citations.extend(atomic_result.citations)
            warnings.extend(atomic_result.notes)
            atomic_invoked = True
        elif atomic_tool_name and not registry.has(atomic_tool_name):
            warnings.append(
                f"evidence_with_provenance: atomic_tool_name={atomic_tool_name!r} "
                "not registered — skipping atomic step, proceeding with dim "
                "module composition."
            )

        # Step 2: lock to snapshot via dim Q.
        snapshot_registry = kwargs.get("snapshot_registry")
        as_of_value = kwargs.get("as_of_date")
        snapshot_result: SnapshotResult | None = None
        temporal_envelope = "rolling/observed"
        if isinstance(snapshot_registry, SnapshotRegistry) and as_of_value is not None:
            snap_as_of = _to_date(as_of_value)
            if snap_as_of is not None:
                snapshot_result = query_as_of(
                    snapshot_registry,
                    dataset_id,
                    snap_as_of,
                )
                if snapshot_result.nearest is not None:
                    temporal_envelope = (
                        f"{snapshot_result.nearest.as_of_date.isoformat()}/"
                        f"snapshot:{snapshot_result.nearest.snapshot_id}"
                    )
                else:
                    warnings.append(
                        "evidence_with_provenance: time_machine.query_as_of "
                        f"returned reason={snapshot_result.reason!r} for "
                        f"dataset={dataset_id!r} as_of={snap_as_of.isoformat()}"
                    )
            else:
                warnings.append(
                    "evidence_with_provenance: as_of_date could not be coerced "
                    "to date — skipping snapshot lock."
                )
        else:
            warnings.append(
                "evidence_with_provenance: no SnapshotRegistry or as_of_date "
                "supplied — proceeding with rolling temporal envelope."
            )

        # Step 3: build canonical signable payload via dim O.
        metadata = FactMetadata(
            source_doc=source_doc,
            extracted_at=_now_iso(),
            verified_by="ed25519_sig",
            confidence=1.0,
        )
        sign_payload = canonical_payload(fact_id, metadata)
        sign_payload_hex = sign_payload.hex()

        # Step 4: gate on dim N k-anonymity floor.
        k_result = check_k_anonymity(cohort_size)
        if not k_result.ok:
            warnings.append(
                "evidence_with_provenance: k-anonymity check failed "
                f"(cohort_size={cohort_size}, reason={k_result.reason!r}); "
                "support_state downgraded to 'partial'."
            )

        # Compose support_state.
        # - 'supported' when snapshot resolved AND k passed
        # - 'partial' when either step degraded
        # - 'absent' only on explicit "no snapshot AND empty atomic"
        snapshot_ok = snapshot_result is not None and snapshot_result.nearest is not None
        atomic_empty = atomic_invoked and not atomic_payload
        if snapshot_ok and k_result.ok:
            support_state = "supported"
        elif not snapshot_ok and not k_result.ok and atomic_empty:
            support_state = "absent"
        else:
            support_state = "partial"

        evidence_type = (
            "absence_observation" if support_state == "absent" else "derived_inference"
        )

        primary: dict[str, Any] = {
            "fact_id": fact_id,
            "source_doc": source_doc,
            "atomic_tool_name": atomic_tool_name or None,
            "atomic_payload": atomic_payload,
            "snapshot": (
                snapshot_result.nearest.model_dump(mode="json")
                if snapshot_ok and snapshot_result is not None and snapshot_result.nearest is not None
                else None
            ),
            "snapshot_reason": (
                snapshot_result.reason if snapshot_result is not None else "not_queried"
            ),
            "fact_metadata": metadata.model_dump(mode="json"),
            "ed25519_sign_payload_hex": sign_payload_hex,
            "ed25519_sign_payload_bytes_len": len(sign_payload),
            "k_anonymity": {
                "ok": k_result.ok,
                "reason": k_result.reason,
                "cohort_size": k_result.cohort_size,
                "floor": 5,
            },
        }
        receipt_ids: tuple[str, ...] = (
            f"chain_receipt_{self.composed_tool_name}_time_machine",
            f"chain_receipt_{self.composed_tool_name}_explainable_fact",
            f"chain_receipt_{self.composed_tool_name}_anonymized_query",
        )
        if atomic_invoked:
            receipt_ids = (
                f"chain_receipt_{self.composed_tool_name}_atomic",
                *receipt_ids,
            )
        evidence = _build_evidence(
            self.composed_tool_name,
            receipt_ids=receipt_ids,
            support_state=support_state,
            temporal_envelope=temporal_envelope,
            evidence_type=evidence_type,
        )
        composed_steps: tuple[str, ...] = (
            "time_machine.query_as_of",
            "explainable_fact.canonical_payload",
            "anonymized_query.check_k_anonymity",
        )
        if atomic_invoked:
            composed_steps = ("composable_tools.atomic", *composed_steps)
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=composed_steps,
            primary_result=primary,
            citations=tuple(citations),
            warnings=tuple(warnings),
            compression_ratio=len(composed_steps),
        )


# ---------------------------------------------------------------------------
# 2. session_aware_eligibility_check — dim L + M + K
# ---------------------------------------------------------------------------


class SessionAwareEligibilityCheck(ComposableTool):
    """Chain — session_context.open → rule_tree.evaluate → predictive.enqueue → close.

    Compound flow:

    1. :meth:`SessionRegistry.open_session` issues a fresh 24h state
       token + persists the supplied ``subject_context`` payload.
    2. :func:`rule_tree.evaluate_tree` runs the supplied
       :class:`RuleTree` against the merged context (subject_context +
       any extra eval_context kwargs).
    3. :func:`predictive_service.enqueue_event` writes a
       :class:`PredictionEvent` so the subscriber will be notified the
       next time the underlying ruleset (target_id) changes within the
       24h KPI window.
    4. :meth:`SessionRegistry.close_session` returns the terminal
       :class:`SavedContext` snapshot.

    Required ``kwargs``: ``subject_id`` (str), ``rule_tree``
    (:class:`RuleTree`), ``predictive_target_id`` (str — must match
    the ``program:<slug>`` / ``amendment:<slug>`` / ``houjin:<13 dig>``
    shape).
    Optional: ``subject_context`` (dict), ``eval_context`` (dict),
    ``session_registry`` (:class:`SessionRegistry`),
    ``predictive_event_path`` (Path-like — JSONL log override for
    tests), ``scheduled_at_iso`` (str — explicit ISO 8601 timestamp
    for the predictive event), ``event_id`` (str — caller-supplied id).
    """

    @property
    def composed_tool_name(self) -> str:
        return "session_aware_eligibility_check"

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        return ()

    @property
    def outcome_contract(self) -> OutcomeContract:
        return _build_outcome_contract(
            self.composed_tool_name,
            display_name=(
                "Session-aware eligibility check with predictive notification "
                "(composed)"
            ),
            packet_ids=("packet_session_aware_eligibility_check",),
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        # Silence the unused-arg note for the registry parameter — the
        # contract demands it (ComposableTool.compose signature) even
        # when the chain runs purely on dim modules.
        _ = registry

        subject_id = _coerce_str(kwargs.get("subject_id"), "subject_unknown")
        rule_tree = kwargs.get("rule_tree")
        target_id = _coerce_str(
            kwargs.get("predictive_target_id"),
            "program:unknown",
        )
        subject_context_raw = kwargs.get("subject_context")
        subject_context: dict[str, Any] = (
            dict(subject_context_raw) if isinstance(subject_context_raw, dict) else {}
        )
        eval_context_raw = kwargs.get("eval_context")
        eval_context: dict[str, Any] = (
            dict(eval_context_raw) if isinstance(eval_context_raw, dict) else {}
        )
        session_registry = kwargs.get("session_registry")
        event_path = kwargs.get("predictive_event_path")
        scheduled_at_iso = _coerce_str(
            kwargs.get("scheduled_at_iso"),
            _now_iso(),
        )
        event_id = _coerce_str(
            kwargs.get("event_id"),
            f"evt_chain_{subject_id}",
        )

        warnings: list[str] = []

        # Step 1: open session.
        if not isinstance(session_registry, SessionRegistry):
            raise ValueError(
                "session_aware_eligibility_check requires a SessionRegistry "
                "via kwargs['session_registry'] — tests should pass a "
                "tmp_path-rooted registry."
            )
        session_token = session_registry.open_session(
            subject_id=subject_id,
            current_state=subject_context,
        )

        # Step 2: evaluate rule tree.
        merged_context: dict[str, Any] = {**subject_context, **eval_context}
        eval_result: EvalResult | None = None
        eval_error: str | None = None
        if isinstance(rule_tree, RuleTree):
            try:
                eval_result = evaluate_tree(rule_tree, merged_context)
            except Exception as exc:  # noqa: BLE001 - chain-level fall-through
                eval_error = (
                    f"rule_tree.evaluate_tree raised "
                    f"{type(exc).__name__}: {exc}"
                )
                warnings.append(
                    "session_aware_eligibility_check: " + eval_error
                )
        else:
            warnings.append(
                "session_aware_eligibility_check: kwargs['rule_tree'] is not "
                "a RuleTree instance — skipping evaluation."
            )

        # Record the evaluation as a session step (best-effort).
        try:
            session_registry.step_session(
                session_token.token_id,
                action="rule_tree_evaluate",
                payload={
                    "rule_tree_id": (
                        rule_tree.tree_id
                        if isinstance(rule_tree, RuleTree)
                        else None
                    ),
                    "result": (
                        eval_result.model_dump(mode="json")
                        if eval_result is not None
                        else None
                    ),
                    "error": eval_error,
                },
            )
        except Exception as exc:  # noqa: BLE001 - best-effort step record
            warnings.append(
                f"session_aware_eligibility_check: step_session failed "
                f"({type(exc).__name__}: {exc})"
            )

        # Step 3: enqueue predictive event.
        predictive_event = PredictionEvent(
            event_id=event_id,
            event_type=_infer_event_type(target_id),
            target_id=target_id,
            scheduled_at=scheduled_at_iso,
            detected_at=_now_iso(),
            payload={
                "subject_id": subject_id,
                "session_token_id": session_token.token_id,
                "rule_tree_id": (
                    rule_tree.tree_id if isinstance(rule_tree, RuleTree) else None
                ),
                "verdict": _verdict_for(eval_result),
            },
        )
        enqueue_event(predictive_event, path=event_path)

        # Step 4: close session — terminal snapshot.
        final_ctx: SavedContext = session_registry.close_session(
            session_token.token_id
        )

        # Compose support_state.
        if eval_result is not None:
            support_state = "supported"
        elif eval_error is not None:
            support_state = "partial"
        else:
            support_state = "absent"
        evidence_type = (
            "absence_observation" if support_state == "absent" else "derived_inference"
        )

        primary: dict[str, Any] = {
            "subject_id": subject_id,
            "session_token_id": session_token.token_id,
            "session_expires_at": session_token.expires_at,
            "rule_tree_id": (
                rule_tree.tree_id if isinstance(rule_tree, RuleTree) else None
            ),
            "eval_result": (
                eval_result.model_dump(mode="json")
                if eval_result is not None
                else None
            ),
            "eval_error": eval_error,
            "predictive_event_id": predictive_event.event_id,
            "predictive_target_id": predictive_event.target_id,
            "predictive_scheduled_at": predictive_event.scheduled_at,
            "session_steps_count": final_ctx.steps_count(),
        }
        receipt_ids = (
            f"chain_receipt_{self.composed_tool_name}_session_open",
            f"chain_receipt_{self.composed_tool_name}_rule_tree",
            f"chain_receipt_{self.composed_tool_name}_predictive",
            f"chain_receipt_{self.composed_tool_name}_session_close",
        )
        evidence = _build_evidence(
            self.composed_tool_name,
            receipt_ids=receipt_ids,
            support_state=support_state,
            temporal_envelope="24h_session/observed",
            evidence_type=evidence_type,
        )
        composed_steps = (
            "session_context.open_session",
            "rule_tree.evaluate_tree",
            "predictive_service.enqueue_event",
            "session_context.close_session",
        )
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=composed_steps,
            primary_result=primary,
            citations=(),
            warnings=tuple(warnings),
            compression_ratio=len(composed_steps),
        )


def _infer_event_type(target_id: str) -> str:
    """Derive the dim K event_type from the watch-target id namespace."""
    if target_id.startswith("houjin:"):
        return "houjin_watch"
    if target_id.startswith("amendment:"):
        return "amendment_diff"
    # default — program:<slug>
    return "program_window"


def _verdict_for(result: EvalResult | None) -> str | None:
    """Extract a short verdict string from the rule_tree EvalResult."""
    if result is None:
        return None
    action = result.action
    if isinstance(action, str):
        return action
    if isinstance(action, dict):
        for key in ("verdict", "outcome", "label"):
            value = action.get(key)
            if isinstance(value, str):
                return value
    return None


# ---------------------------------------------------------------------------
# 3. federated_handoff_with_audit — dim P + R + N
# ---------------------------------------------------------------------------


class FederatedHandoffWithAudit(ComposableTool):
    """Chain — composable_tools probe → federated_mcp.recommend_handoff → anonymized_query.audit.

    Compound flow:

    1. (Optional) Invoke a composable_tools atomic to confirm the gap
       (e.g. ``search_programs_am`` returned 0 candidates). If the
       atomic is missing or returns a populated payload, the chain
       still emits a recommendation but downgrades support_state to
       ``partial`` since the handoff is no longer "first-resort".
    2. :func:`federated_mcp.recommend_handoff` matches the
       ``query_gap`` against the 6 curated partners and returns up to
       ``max_results`` ranked recommendations.
    3. :func:`anonymized_query.write_audit_entry` appends one APPI-
       grade audit row to the JSONL log capturing the cohort hash +
       redact policy version + outcome reason. The audit row marks
       the call ``reason='ok'`` for compliant handoffs and
       ``reason='invalid_filter'`` when the gap fails minimum hygiene
       (empty / whitespace-only).

    Required ``kwargs``: ``query_gap`` (str — the unanswered request).
    Optional: ``atomic_tool_name`` (str), ``federated_registry``
    (:class:`FederatedRegistry`), ``max_results`` (int, default 3),
    ``audit_log_path`` (Path-like — JSONL override for tests),
    ``industry`` / ``region`` / ``size`` (str — cohort filter axes
    fed into :func:`cohort_hash`).
    """

    @property
    def composed_tool_name(self) -> str:
        return "federated_handoff_with_audit"

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        return ()

    @property
    def outcome_contract(self) -> OutcomeContract:
        return _build_outcome_contract(
            self.composed_tool_name,
            display_name=(
                "Federated MCP handoff with anonymized audit (composed)"
            ),
            packet_ids=("packet_federated_handoff_with_audit",),
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        query_gap = _coerce_str(kwargs.get("query_gap"), "")
        atomic_tool_name = _coerce_str(kwargs.get("atomic_tool_name"), "")
        federated_registry = kwargs.get("federated_registry")
        max_results = _coerce_int(kwargs.get("max_results"), 3)
        if max_results < 1:
            max_results = 1
        audit_path = kwargs.get("audit_log_path")
        industry = kwargs.get("industry")
        region = kwargs.get("region")
        size = kwargs.get("size")

        warnings: list[str] = []
        citations: list[dict[str, Any]] = []

        # Step 1: optional gap-probe via atomic.
        atomic_invoked = False
        atomic_returned_empty = True
        atomic_payload: dict[str, Any] = {}
        if atomic_tool_name and registry.has(atomic_tool_name):
            atomic_result = registry.call(atomic_tool_name)
            atomic_invoked = True
            atomic_payload = dict(atomic_result.payload)
            citations.extend(atomic_result.citations)
            warnings.extend(atomic_result.notes)
            atomic_returned_empty = not bool(atomic_payload)
        elif atomic_tool_name and not registry.has(atomic_tool_name):
            warnings.append(
                f"federated_handoff_with_audit: atomic_tool_name={atomic_tool_name!r} "
                "not registered — proceeding with federated recommendation only."
            )

        # Step 2: federated_mcp recommendation.
        recommendations: tuple[PartnerMcp, ...] = ()
        if not query_gap:
            warnings.append(
                "federated_handoff_with_audit: query_gap is empty — "
                "skipping recommendation; audit row will record "
                "reason='invalid_filter'."
            )
        else:
            try:
                recommendations = recommend_handoff(
                    query_gap,
                    registry=(
                        federated_registry
                        if isinstance(federated_registry, FederatedRegistry)
                        else None
                    ),
                    max_results=max_results,
                )
            except ValueError as exc:
                warnings.append(
                    "federated_handoff_with_audit: recommend_handoff "
                    f"raised {exc}"
                )

        # Step 3: audit log row via dim N.
        cohort_hash_hex = cohort_hash(
            _maybe_str(industry),
            _maybe_str(region),
            _maybe_str(size),
        )
        audit_reason = "invalid_filter" if not query_gap else "ok"
        audit_entry = write_audit_entry(
            cohort_hash_hex=cohort_hash_hex,
            redact_policy_version=REDACT_POLICY_VERSION,
            cohort_size=len(recommendations),
            reason=audit_reason,
            pii_hits=[],
            path=audit_path,
        )

        # Compose support_state.
        if not query_gap:
            support_state = "absent"
        elif not recommendations:
            support_state = "partial"
        elif atomic_invoked and not atomic_returned_empty:
            # Atomic returned data; handoff is supplementary not primary.
            support_state = "partial"
        else:
            support_state = "supported"
        evidence_type = (
            "absence_observation" if support_state == "absent" else "derived_inference"
        )

        primary: dict[str, Any] = {
            "query_gap": query_gap or None,
            "atomic_tool_name": atomic_tool_name or None,
            "atomic_invoked": atomic_invoked,
            "atomic_payload": atomic_payload,
            "recommendations": [p.model_dump(mode="json") for p in recommendations],
            "recommendation_count": len(recommendations),
            "audit_entry": {
                "cohort_hash": audit_entry.cohort_hash,
                "redact_policy_version": audit_entry.redact_policy_version,
                "cohort_size": audit_entry.cohort_size,
                "reason": audit_entry.reason,
                "ts": audit_entry.ts,
            },
        }
        receipt_ids: tuple[str, ...] = (
            f"chain_receipt_{self.composed_tool_name}_federated_mcp",
            f"chain_receipt_{self.composed_tool_name}_anonymized_audit",
        )
        if atomic_invoked:
            receipt_ids = (
                f"chain_receipt_{self.composed_tool_name}_atomic",
                *receipt_ids,
            )
        evidence = _build_evidence(
            self.composed_tool_name,
            receipt_ids=receipt_ids,
            support_state=support_state,
            temporal_envelope="rolling/observed",
            evidence_type=evidence_type,
        )
        composed_steps: tuple[str, ...] = (
            "federated_mcp.recommend_handoff",
            "anonymized_query.write_audit_entry",
        )
        if atomic_invoked:
            composed_steps = ("composable_tools.atomic", *composed_steps)
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=composed_steps,
            primary_result=primary,
            citations=tuple(citations),
            warnings=tuple(warnings),
            compression_ratio=len(composed_steps),
        )


def _maybe_str(value: object) -> str | None:
    """Return ``value`` as a non-empty string, or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value else None
    return str(value)


# ---------------------------------------------------------------------------
# 4. temporal_compliance_audit — dim Q + M + O
# ---------------------------------------------------------------------------


class TemporalComplianceAudit(ComposableTool):
    """Chain — time_machine.query_as_of × 2 → counterfactual_diff → rule_tree.evaluate → explainable_fact.

    Compound flow:

    1. :func:`query_as_of` at ``T-90`` (or caller-supplied
       ``baseline_as_of_date``) — the older anchor.
    2. :func:`query_as_of` at ``T-30`` (or caller-supplied
       ``compare_as_of_date``) — the newer anchor.
    3. :func:`counterfactual_diff` over the two snapshots — surfaces
       the added / removed / changed top-level keys.
    4. :func:`rule_tree.evaluate_tree` on the diff result merged with
       any extra eval context — produces a compliance verdict.
    5. Build a :class:`FactMetadata` with audit-grade
       ``verified_by='ed25519_sig'`` and compute the canonical sign
       payload for the verdict so the consumer can hand to an HSM.

    Required ``kwargs``: ``dataset_id`` (str),
    ``baseline_as_of_date`` (date), ``compare_as_of_date`` (date),
    ``rule_tree`` (:class:`RuleTree`), ``snapshot_registry``
    (:class:`SnapshotRegistry`).
    Optional: ``eval_context`` (dict), ``audit_fact_id`` (str —
    caller-supplied id for the resulting signed fact),
    ``audit_source_doc`` (str — primary-source URL for the sign
    payload).
    """

    @property
    def composed_tool_name(self) -> str:
        return "temporal_compliance_audit"

    @property
    def atomic_dependencies(self) -> tuple[str, ...]:
        return ()

    @property
    def outcome_contract(self) -> OutcomeContract:
        return _build_outcome_contract(
            self.composed_tool_name,
            display_name=(
                "Temporal compliance audit (counterfactual diff + signed "
                "rule_tree verdict, composed)"
            ),
            packet_ids=("packet_temporal_compliance_audit",),
        )

    def compose(
        self,
        registry: AtomicRegistry,
        /,
        **kwargs: Any,
    ) -> ComposedEnvelope:
        _ = registry  # contract — registry parameter required by ABC.

        dataset_id = _coerce_str(kwargs.get("dataset_id"), "programs")
        rule_tree = kwargs.get("rule_tree")
        snapshot_registry = kwargs.get("snapshot_registry")
        eval_context_raw = kwargs.get("eval_context")
        eval_context: dict[str, Any] = (
            dict(eval_context_raw) if isinstance(eval_context_raw, dict) else {}
        )
        audit_fact_id = _coerce_str(
            kwargs.get("audit_fact_id"),
            f"compliance_audit_{dataset_id}",
        )
        audit_source_doc = _coerce_str(
            kwargs.get("audit_source_doc"),
            "https://www.e-gov.go.jp/",
        )
        baseline_value = kwargs.get("baseline_as_of_date")
        compare_value = kwargs.get("compare_as_of_date")

        warnings: list[str] = []

        if not isinstance(snapshot_registry, SnapshotRegistry):
            raise ValueError(
                "temporal_compliance_audit requires kwargs['snapshot_registry'] "
                "as a SnapshotRegistry instance."
            )
        baseline_date = _to_date(baseline_value)
        compare_date = _to_date(compare_value)
        if baseline_date is None or compare_date is None:
            raise ValueError(
                "temporal_compliance_audit requires both baseline_as_of_date "
                "and compare_as_of_date to be coercible to a date."
            )

        # Step 1+2: dual snapshot lookups.
        baseline_result = query_as_of(
            snapshot_registry,
            dataset_id,
            baseline_date,
        )
        compare_result = query_as_of(
            snapshot_registry,
            dataset_id,
            compare_date,
        )

        baseline_snap: Snapshot | None = baseline_result.nearest
        compare_snap: Snapshot | None = compare_result.nearest

        if baseline_snap is None:
            warnings.append(
                f"temporal_compliance_audit: baseline snapshot "
                f"reason={baseline_result.reason!r} for dataset={dataset_id!r}"
            )
        if compare_snap is None:
            warnings.append(
                f"temporal_compliance_audit: compare snapshot "
                f"reason={compare_result.reason!r} for dataset={dataset_id!r}"
            )

        # Step 3: counterfactual_diff (only when both snapshots present).
        diff: DiffResult | None = None
        if baseline_snap is not None and compare_snap is not None:
            diff = counterfactual_diff(baseline_snap, compare_snap)

        # Step 4: rule_tree evaluation on the diff.
        rule_eval: EvalResult | None = None
        rule_error: str | None = None
        if isinstance(rule_tree, RuleTree) and diff is not None:
            merged_ctx: dict[str, Any] = {
                **eval_context,
                "added_count": len(diff.added),
                "removed_count": len(diff.removed),
                "changed_count": len(diff.changed),
                "unchanged_count": len(diff.unchanged),
                "content_hash_changed": diff.content_hash_changed,
            }
            try:
                rule_eval = evaluate_tree(rule_tree, merged_ctx)
            except Exception as exc:  # noqa: BLE001 — surface in warnings.
                rule_error = (
                    f"rule_tree.evaluate_tree raised "
                    f"{type(exc).__name__}: {exc}"
                )
                warnings.append("temporal_compliance_audit: " + rule_error)
        elif not isinstance(rule_tree, RuleTree):
            warnings.append(
                "temporal_compliance_audit: rule_tree kwarg is not a RuleTree "
                "instance — skipping evaluation."
            )

        # Step 5: build audit-grade sign payload.
        metadata = FactMetadata(
            source_doc=audit_source_doc,
            extracted_at=_now_iso(),
            verified_by="ed25519_sig",
            confidence=1.0 if (rule_eval is not None and diff is not None) else 0.5,
        )
        sign_payload = canonical_payload(audit_fact_id, metadata)
        sign_payload_hex = sign_payload.hex()

        # Compose support_state.
        if (
            baseline_snap is not None
            and compare_snap is not None
            and diff is not None
            and rule_eval is not None
        ):
            support_state = "supported"
        elif baseline_snap is None and compare_snap is None:
            support_state = "absent"
        else:
            support_state = "partial"
        evidence_type = (
            "absence_observation" if support_state == "absent" else "derived_inference"
        )

        baseline_dump: dict[str, Any] | None = (
            baseline_snap.model_dump(mode="json") if baseline_snap is not None else None
        )
        compare_dump: dict[str, Any] | None = (
            compare_snap.model_dump(mode="json") if compare_snap is not None else None
        )

        primary: dict[str, Any] = {
            "audit_fact_id": audit_fact_id,
            "dataset_id": dataset_id,
            "baseline_as_of_date": baseline_date.isoformat(),
            "compare_as_of_date": compare_date.isoformat(),
            "baseline_snapshot": baseline_dump,
            "compare_snapshot": compare_dump,
            "diff": diff.model_dump(mode="json") if diff is not None else None,
            "rule_eval": (
                rule_eval.model_dump(mode="json") if rule_eval is not None else None
            ),
            "rule_error": rule_error,
            "fact_metadata": metadata.model_dump(mode="json"),
            "ed25519_sign_payload_hex": sign_payload_hex,
        }
        receipt_ids = (
            f"chain_receipt_{self.composed_tool_name}_time_machine_baseline",
            f"chain_receipt_{self.composed_tool_name}_time_machine_compare",
            f"chain_receipt_{self.composed_tool_name}_counterfactual_diff",
            f"chain_receipt_{self.composed_tool_name}_rule_tree",
            f"chain_receipt_{self.composed_tool_name}_explainable_fact",
        )
        evidence = _build_evidence(
            self.composed_tool_name,
            receipt_ids=receipt_ids,
            support_state=support_state,
            temporal_envelope=(
                f"{baseline_date.isoformat()}/{compare_date.isoformat()}"
            ),
            evidence_type=evidence_type,
        )
        composed_steps = (
            "time_machine.query_as_of:baseline",
            "time_machine.query_as_of:compare",
            "time_machine.counterfactual_diff",
            "rule_tree.evaluate_tree",
            "explainable_fact.canonical_payload",
        )
        return ComposedEnvelope(
            composed_tool_name=self.composed_tool_name,
            evidence=evidence,
            outcome_contract=self.outcome_contract,
            composed_steps=composed_steps,
            primary_result=primary,
            citations=(),
            warnings=tuple(warnings),
            compression_ratio=len(composed_steps),
        )


# ---------------------------------------------------------------------------
# date coercion + canonical chain index
# ---------------------------------------------------------------------------


def _to_date(value: object) -> date | None:
    """Coerce ``value`` to a :class:`datetime.date`, or return ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


#: Canonical 4-tuple of Wave 51 chain names. Pinned for wire-shape
#: regression tests; bumping requires a coordinated manifest bump.
WAVE51_CHAIN_TOOLS: Final[tuple[str, ...]] = (
    "evidence_with_provenance",
    "session_aware_eligibility_check",
    "federated_handoff_with_audit",
    "temporal_compliance_audit",
)


def register_wave51_chains() -> tuple[ComposableTool, ...]:
    """Return fresh instances of the 4 Wave 51 service composition chains.

    A new instance per call so callers can mutate / subclass without
    sharing state.
    """
    return (
        EvidenceWithProvenance(),
        SessionAwareEligibilityCheck(),
        FederatedHandoffWithAudit(),
        TemporalComplianceAudit(),
    )


__all__ = [
    "WAVE51_CHAIN_TOOLS",
    "EvidenceWithProvenance",
    "FederatedHandoffWithAudit",
    "SessionAwareEligibilityCheck",
    "TemporalComplianceAudit",
    "register_wave51_chains",
]
