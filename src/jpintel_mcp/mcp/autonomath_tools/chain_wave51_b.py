"""Wave 51 chain B MCP wrappers (179 -> 184).

Five MCP tools that surface the per-dim primitive composition chains
added to ``jpintel_mcp.composable_tools.wave51_chains`` in Wave 51
chain B. Where ``wave51_chains.py`` (the original 4 cross-dim chains)
wraps thread-the-dims composition (dim P + Q + O + N etc), this module
wraps the **per-dim primitive composition** chains that thread multiple
atomic primitives within a single dim K-S module into one composed
call:

    predictive_subscriber_fanout         — dim K (3 atomic primitives)
    session_multi_step_eligibility       — dim L (open + N step + close)
    rule_tree_batch_eval                 — dim M (N trees x 1 context)
    anonymized_cohort_query_with_redact  — dim N (redact + k + audit)
    time_machine_snapshot_walk           — dim Q (N consecutive diffs)

Each tool returns the canonical :class:`ComposedEnvelope` dict (JPCIR
``Evidence`` + ``OutcomeContract`` + citations + composed_steps),
tagged ``_billing_unit=3`` to reflect the heavy-tier compound service
price (3 ¥3 units / 税込 ¥9.90) the rest of the Wave 51 chain surface
emits.

Hard constraints (mirrored from
``feedback_composable_tools_pattern`` + CLAUDE.md):

* NO LLM call inside any wrapper body. Composition order is
  deterministic — declared by each chain's ``compose()`` body.
* No re-entry into the MCP protocol. The injected
  :class:`AtomicRegistry` is a Python-callable dispatcher; MCP-to-MCP
  recursion would re-spend the metering budget composition exists to
  compress. We pass a stub registry (mirroring ``wave51_chains.py``)
  because every chain in this module sets
  ``atomic_dependencies = ()`` and never queries the registry.
* 3 ¥3/billable units per compound call (heavy-tier compound service).
* §52 / §47条の2 / §72 / §1 / §3 non-substitution disclaimer envelope.
* No file-system writes against shared paths — chains accept
  ``audit_log_path`` / ``snapshot_registry`` / ``session_registry`` /
  ``event_log_path`` / ``subscription_log_path`` via kwargs so test
  fixtures can inject temp paths; the wrappers wire the chain
  primitives against the default filesystem paths (``data/snapshots/``,
  ``data/sessions/``, ``logs/anonymized_query_audit.jsonl``,
  ``logs/predictive_events.jsonl``,
  ``logs/predictive_subscriptions.jsonl``) at call time, identical to
  ``wave51_chains.py`` defaults.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.composable_tools.base import (
    AtomicCallResult,
    ComposableTool,
    ComposedEnvelope,
    ComposedToolError,
)
from jpintel_mcp.composable_tools.wave51_chains import (
    AnonymizedCohortQueryWithRedact,
    PredictiveSubscriberFanout,
    RuleTreeBatchEval,
    SessionMultiStepEligibility,
    TimeMachineSnapshotWalk,
)
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.predictive_service import PredictionEvent, Subscription
from jpintel_mcp.rule_tree import RuleTree
from jpintel_mcp.session_context import SessionRegistry
from jpintel_mcp.time_machine import SnapshotRegistry

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.chain_wave51_b")

_ENABLED = os.environ.get("AUTONOMATH_WAVE51_CHAIN_B_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

# Heavy-tier disclaimer — every chain B emits this verbatim. The 5
# sensitive fences (§52 / §47条の2 / §72 / §1 / §3) are matched by the
# no-LLM meta-test which greps for "§52" in the disclaimer body.
_DISCLAIMER = (
    "本 response は Wave 51 service composition chain B (per-dim primitive "
    "composition K/L/M/N/Q) の server-side 結果です。dim 内 atomic primitive を "
    "3 ¥3 units (税込 ¥9.90) に圧縮した heavy-tier compound service envelope であり、"
    "個別 primitive は jpcite filesystem + 純 Python 経由で deterministic に解決されます。"
    "法的助言ではなく、税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / "
    "行政書士法 §1 / 司法書士法 §3 の代替ではありません。"
)

# Compound chains weigh ¥9.90 税込 — 3 ¥3 units per call (3x atomic).
# Mirrors ``wave51_chains.py`` so the chain B tier matches the original
# Wave 51 chain tier.
_COMPOUND_BILLING_UNIT = 3


# ---------------------------------------------------------------------------
# Stub AtomicRegistry — every chain in this module has empty
# ``atomic_dependencies`` so the stub never actually fires. We still
# pass one to satisfy the ``ComposableTool.compose`` signature.
# ---------------------------------------------------------------------------


class _StubAtomicRegistry:
    """Empty atomic registry stub for Wave 51 chain B MCP wrappers.

    Every chain B class declares ``atomic_dependencies = ()`` and ignores
    the registry inside ``compose()``. We supply a stub so the abstract
    base contract (``compose(registry, **kwargs)``) is satisfied without
    re-entering the MCP protocol.
    """

    def call(self, tool_name: str, /, **_kwargs: Any) -> AtomicCallResult:
        return AtomicCallResult(
            tool_name=tool_name,
            payload={},
            citations=(),
            notes=(
                f"chain_wave51_b stub: atomic '{tool_name}' returned empty "
                "from FastMCP runtime stub registry; chains B do not use "
                "the atomic registry — this method is unreachable in practice.",
            ),
        )

    def has(self, _tool_name: str, /) -> bool:
        # Always False — chain B classes declare no atomic dependencies
        # so they never call ``has()`` from their ``compose()`` bodies.
        return False


# ---------------------------------------------------------------------------
# Filesystem path helpers — wire chains against default repo locations.
# Mirror ``wave51_chains.py`` so the chain B surface shares the same
# env override knobs (AUTONOMATH_SNAPSHOTS_ROOT / _SESSIONS_ROOT /
# _PREDICTIVE_EVENT_PATH / ANONYMIZED_QUERY_AUDIT_LOG_PATH +
# AUTONOMATH_PREDICTIVE_SUBSCRIPTION_PATH for the new subscriber fanout
# chain).
# ---------------------------------------------------------------------------


def _snapshots_root() -> Path:
    """Resolve the dim Q snapshot registry root from env / default."""
    override = os.environ.get("AUTONOMATH_SNAPSHOTS_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "data" / "snapshots"


def _sessions_root() -> Path:
    """Resolve the dim L session registry root, falling back to tmp."""
    override = os.environ.get("AUTONOMATH_SESSIONS_ROOT")
    if override:
        return Path(override)
    default = Path(__file__).resolve().parents[4] / "data" / "sessions"
    try:
        default.mkdir(parents=True, exist_ok=True)
        return default
    except OSError:  # pragma: no cover — read-only volume fallback
        return Path(tempfile.gettempdir()) / "autonomath_sessions"


def _predictive_event_path() -> Path:
    """Resolve the dim K predictive event JSONL path."""
    override = os.environ.get("AUTONOMATH_PREDICTIVE_EVENT_PATH")
    if override:
        return Path(override)
    default = (
        Path(__file__).resolve().parents[4] / "logs" / "predictive_events.jsonl"
    )
    try:
        default.parent.mkdir(parents=True, exist_ok=True)
        return default
    except OSError:  # pragma: no cover — read-only volume fallback
        return Path(tempfile.gettempdir()) / "autonomath_predictive_events.jsonl"


def _predictive_subscription_path() -> Path:
    """Resolve the dim K predictive subscription JSONL path."""
    override = os.environ.get("AUTONOMATH_PREDICTIVE_SUBSCRIPTION_PATH")
    if override:
        return Path(override)
    default = (
        Path(__file__).resolve().parents[4]
        / "logs"
        / "predictive_subscriptions.jsonl"
    )
    try:
        default.parent.mkdir(parents=True, exist_ok=True)
        return default
    except OSError:  # pragma: no cover — read-only volume fallback
        return Path(tempfile.gettempdir()) / "autonomath_predictive_subscriptions.jsonl"


def _audit_log_path() -> Path:
    """Resolve the dim N audit log JSONL path."""
    override = os.environ.get("ANONYMIZED_QUERY_AUDIT_LOG_PATH")
    if override:
        return Path(override)
    default = (
        Path(__file__).resolve().parents[4]
        / "logs"
        / "anonymized_query_audit.jsonl"
    )
    try:
        default.parent.mkdir(parents=True, exist_ok=True)
        return default
    except OSError:  # pragma: no cover — read-only volume fallback
        return Path(tempfile.gettempdir()) / "anonymized_query_audit.jsonl"


# ---------------------------------------------------------------------------
# Shared envelope finalization — JPCIR-shaped dict per CLAUDE.md
# ---------------------------------------------------------------------------


def _run_chain(
    chain: ComposableTool,
    /,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute a Wave 51 chain B against the stub registry and return JPCIR envelope."""
    registry = _StubAtomicRegistry()
    try:
        envelope: ComposedEnvelope = chain.compose(registry, **kwargs)
    except ComposedToolError as exc:
        return make_error(
            code="subsystem_unavailable",
            message=str(exc),
            hint=(
                "Wave 51 chain B atomic dependency missing from runtime "
                "registry — call REST companion at /v1/chains/{tool}."
            ),
        )
    except ValueError as exc:
        # Chains raise ValueError on missing required dependencies
        # (SnapshotRegistry / SessionRegistry / Subscription / event /
        # RuleTree / steps) — surface as a structured error envelope
        # rather than crashing the MCP loop.
        return make_error(
            code="missing_required_arg",
            message=str(exc),
            hint="Pass the required *_registry / *_json / *_count argument.",
        )

    payload = envelope.to_dict()
    payload["_billing_unit"] = _COMPOUND_BILLING_UNIT
    payload["_disclaimer"] = _DISCLAIMER
    # Mirror the search-envelope keys so consumers that pattern-match on
    # {results, total, limit, offset} still see a valid shape.
    payload.setdefault("results", [])
    payload.setdefault("total", 0)
    payload.setdefault("limit", 1)
    payload.setdefault("offset", 0)
    return payload


# ---------------------------------------------------------------------------
# 1. predictive_subscriber_fanout_chain — dim K (3 atomic primitives)
# ---------------------------------------------------------------------------


def _predictive_subscriber_fanout_impl(
    subscription_json: dict[str, Any] | None,
    event_json: dict[str, Any] | None,
) -> dict[str, Any]:
    """dim K chain — register subscription + enqueue event + due_for fanout."""
    if not isinstance(subscription_json, dict):
        return make_error(
            code="missing_required_arg",
            message="subscription_json is required (Subscription JSON dict).",
            field="subscription_json",
            hint="Pass a Subscription envelope with subscription_id / "
            "subscriber_id / watch_targets / channel / created_at.",
        )
    if not isinstance(event_json, dict):
        return make_error(
            code="missing_required_arg",
            message="event_json is required (PredictionEvent JSON dict).",
            field="event_json",
            hint="Pass a PredictionEvent envelope with event_id / event_type / "
            "target_id / scheduled_at / detected_at / payload.",
        )

    try:
        subscription = Subscription.model_validate(subscription_json)
    except Exception as exc:  # noqa: BLE001 — surface in envelope.
        return make_error(
            code="invalid_input",
            message=f"subscription_json failed validation: {exc}",
            field="subscription_json",
        )
    try:
        event = PredictionEvent.model_validate(event_json)
    except Exception as exc:  # noqa: BLE001 — surface in envelope.
        return make_error(
            code="invalid_input",
            message=f"event_json failed validation: {exc}",
            field="event_json",
        )

    kwargs: dict[str, Any] = {
        "subscription": subscription,
        "event": event,
        "event_log_path": _predictive_event_path(),
        "subscription_log_path": _predictive_subscription_path(),
    }
    return _run_chain(PredictiveSubscriberFanout(), **kwargs)


# ---------------------------------------------------------------------------
# 2. session_multi_step_eligibility_chain — dim L (open + N step + close)
# ---------------------------------------------------------------------------


def _session_multi_step_eligibility_impl(
    subject_id: str,
    steps: list[dict[str, Any]] | None,
    initial_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """dim L chain — open_session + N step_session + close_session in 1 call."""
    if not subject_id or not subject_id.strip():
        return make_error(
            code="missing_required_arg",
            message="subject_id is required.",
            field="subject_id",
        )
    if not isinstance(steps, list):
        return make_error(
            code="missing_required_arg",
            message="steps is required (list of {action, payload} mappings).",
            field="steps",
            hint="Pass a list of {action: str, payload: dict | null} mappings.",
        )

    try:
        session_registry = SessionRegistry(root=_sessions_root())
    except Exception as exc:  # pragma: no cover — filesystem guard
        return make_error(
            code="db_unavailable",
            message=f"session registry init failed: {exc}",
        )

    kwargs: dict[str, Any] = {
        "subject_id": subject_id,
        "steps": steps,
        "session_registry": session_registry,
    }
    if isinstance(initial_state, dict):
        kwargs["initial_state"] = initial_state

    return _run_chain(SessionMultiStepEligibility(), **kwargs)


# ---------------------------------------------------------------------------
# 3. rule_tree_batch_eval_chain — dim M (N trees x 1 context)
# ---------------------------------------------------------------------------


def _rule_tree_batch_eval_impl(
    rule_tree_jsons: list[dict[str, Any]] | None,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """dim M chain — evaluate N rule trees over a single context."""
    if not isinstance(rule_tree_jsons, list):
        return make_error(
            code="missing_required_arg",
            message="rule_tree_jsons is required (list of RuleTree JSON dicts).",
            field="rule_tree_jsons",
            hint="Pass a list of RuleTree envelopes (one per tree).",
        )
    if not isinstance(context, dict):
        return make_error(
            code="missing_required_arg",
            message="context is required (evaluation context dict).",
            field="context",
        )

    trees: list[RuleTree] = []
    for idx, raw_tree in enumerate(rule_tree_jsons):
        if not isinstance(raw_tree, dict):
            return make_error(
                code="invalid_input",
                message=f"rule_tree_jsons[{idx}] is not a JSON dict.",
                field="rule_tree_jsons",
            )
        try:
            trees.append(RuleTree.model_validate(raw_tree))
        except Exception as exc:  # noqa: BLE001 — surface in envelope.
            return make_error(
                code="invalid_input",
                message=f"rule_tree_jsons[{idx}] failed validation: {exc}",
                field="rule_tree_jsons",
            )

    kwargs: dict[str, Any] = {
        "trees": trees,
        "context": context,
    }
    return _run_chain(RuleTreeBatchEval(), **kwargs)


# ---------------------------------------------------------------------------
# 4. anonymized_cohort_query_with_redact_chain — dim N (redact + k + audit)
# ---------------------------------------------------------------------------


def _anonymized_cohort_query_with_redact_impl(
    sample: dict[str, Any] | None,
    cohort_size: int,
    industry: str = "",
    region: str = "",
    size: str = "",
) -> dict[str, Any]:
    """dim N chain — pii_redact + k_anonymity + write_audit_entry in 1 call."""
    if not isinstance(sample, dict):
        return make_error(
            code="missing_required_arg",
            message="sample is required (one row / sample dict).",
            field="sample",
            hint="Pass the candidate row dict to redact + audit.",
        )
    if not isinstance(cohort_size, int) or isinstance(cohort_size, bool):
        return make_error(
            code="invalid_input",
            message="cohort_size must be an int.",
            field="cohort_size",
        )
    if cohort_size < 0:
        return make_error(
            code="out_of_range",
            message="cohort_size must be >= 0.",
            field="cohort_size",
        )

    kwargs: dict[str, Any] = {
        "sample": sample,
        "cohort_size": cohort_size,
        "audit_log_path": _audit_log_path(),
    }
    if industry:
        kwargs["industry"] = industry
    if region:
        kwargs["region"] = region
    if size:
        kwargs["size"] = size

    return _run_chain(AnonymizedCohortQueryWithRedact(), **kwargs)


# ---------------------------------------------------------------------------
# 5. time_machine_snapshot_walk_chain — dim Q (N consecutive monthly diffs)
# ---------------------------------------------------------------------------


def _time_machine_snapshot_walk_impl(
    dataset_id: str,
    start_as_of_date: str,
    end_as_of_date: str,
    month_count_cap: int = 12,
) -> dict[str, Any]:
    """dim Q chain — walk N consecutive monthly snapshots + pairwise diffs."""
    if not dataset_id or not dataset_id.strip():
        return make_error(
            code="missing_required_arg",
            message="dataset_id is required.",
            field="dataset_id",
        )
    if not start_as_of_date or not start_as_of_date.strip():
        return make_error(
            code="missing_required_arg",
            message="start_as_of_date is required.",
            field="start_as_of_date",
            hint="Pass an ISO YYYY-MM-DD date — the older anchor.",
        )
    if not end_as_of_date or not end_as_of_date.strip():
        return make_error(
            code="missing_required_arg",
            message="end_as_of_date is required.",
            field="end_as_of_date",
            hint="Pass an ISO YYYY-MM-DD date — the newer anchor.",
        )

    try:
        snapshot_registry = SnapshotRegistry(_snapshots_root())
    except Exception as exc:  # pragma: no cover — filesystem guard
        return make_error(
            code="db_unavailable",
            message=f"snapshot registry init failed: {exc}",
        )

    kwargs: dict[str, Any] = {
        "dataset_id": dataset_id,
        "start_as_of_date": start_as_of_date,
        "end_as_of_date": end_as_of_date,
        "snapshot_registry": snapshot_registry,
        "month_count_cap": month_count_cap,
    }
    return _run_chain(TimeMachineSnapshotWalk(), **kwargs)


# ---------------------------------------------------------------------------
# MCP tool registration — gated on AUTONOMATH_WAVE51_CHAIN_B_ENABLED + settings
# ---------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def predictive_subscriber_fanout_chain(
        subscription_json: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Subscription JSON envelope — subscription_id / "
                    "subscriber_id / watch_targets (tuple of "
                    "'houjin:<13d>' | 'program:<slug>' | 'amendment:<slug>') / "
                    "channel ('webhook'|'mcp_resource'|'email_digest') / "
                    "created_at (ISO 8601 UTC)."
                ),
            ),
        ],
        event_json: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "PredictionEvent JSON envelope — event_id / event_type "
                    "('houjin_watch'|'program_window'|'amendment_diff') / "
                    "target_id / scheduled_at (ISO 8601 UTC) / "
                    "detected_at (ISO 8601 UTC) / payload (free dict)."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain B — predictive_subscriber_fanout (dim K). Registers the supplied Subscription, enqueues the supplied PredictionEvent, then runs due_events_for_subscriber to confirm the event lands inside the 24h notification KPI window. Returns ComposedEnvelope with composed_steps (predictive_service.register_subscription + enqueue_event + due_events_for_subscriber) + target_event_in_due_window. NO LLM, no HTTP, 3 ¥3 units (heavy compound tier)."""
        return _predictive_subscriber_fanout_impl(
            subscription_json=subscription_json,
            event_json=event_json,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def session_multi_step_eligibility_chain(
        subject_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=128,
                description=(
                    "Caller-supplied opaque subject id (API key id, agent run "
                    "id) — NOT PII per dim N redact rules."
                ),
            ),
        ],
        steps: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description=(
                    "Sequence of step entries — each entry is "
                    "{action: str, payload: dict | null}. Action is a "
                    "1-64 char identifier; payload is capped at 16 KiB. "
                    "Up to 32 steps per session (dim L MAX_STEPS)."
                ),
            ),
        ],
        initial_state: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Optional initial saved_context payload. Capped at "
                    "16 KiB (dim L MAX_CONTEXT_BYTES). Defaults to empty."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain B — session_multi_step_eligibility (dim L). Opens a fresh 24h session, persists each supplied step in order, then closes the session and returns the terminal SavedContext snapshot. Surfaces per-step status (persisted / failed / skipped) so the agent can audit which actions landed. Returns ComposedEnvelope with composed_steps (session_context.open + step_batch + close). NO LLM, 3 ¥3 units (heavy compound tier)."""
        return _session_multi_step_eligibility_impl(
            subject_id=subject_id,
            steps=steps,
            initial_state=initial_state,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def rule_tree_batch_eval_chain(
        rule_tree_jsons: Annotated[
            list[dict[str, Any]] | None,
            Field(
                description=(
                    "List of JSON-serialised RuleTree envelopes (dim M). "
                    "Each tree carries tree_id / name / version / root "
                    "RuleNode. Evaluated independently — failure in one "
                    "tree does not halt the others."
                ),
            ),
        ],
        context: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Shared evaluation context dict. Identifier keys are "
                    "looked up against this dict by every tree. Flatten "
                    "nested structures before passing — dotted paths are "
                    "not supported by the dim M evaluator."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain B — rule_tree_batch_eval (dim M). Evaluates N RuleTrees over a single context dict in 1 call and returns every verdict + rationale_path + source_doc_ids in parallel index order. Replaces N atomic rule_engine_check round-trips with one composed call. Returns ComposedEnvelope with composed_steps (rule_tree.evaluate_tree:batch). NO LLM, 3 ¥3 units (heavy compound tier)."""
        return _rule_tree_batch_eval_impl(
            rule_tree_jsons=rule_tree_jsons,
            context=context,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def anonymized_cohort_query_with_redact_chain(
        sample: Annotated[
            dict[str, Any] | None,
            Field(
                description=(
                    "Candidate row / response dict to redact + audit. "
                    "PII columns (法人番号 / 氏名 / 住所 / phone / email / "
                    "mynumber) are stripped via redact_pii_fields; "
                    "string leaves are scrubbed via redact_text."
                ),
            ),
        ],
        cohort_size: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "Pre-computed cohort size for the sample. Must be "
                    ">= 5 (K_ANONYMITY_MIN) for support_state=supported."
                ),
            ),
        ],
        industry: Annotated[
            str,
            Field(
                default="",
                max_length=64,
                description="Cohort filter — industry (JSIC major / display name).",
            ),
        ] = "",
        region: Annotated[
            str,
            Field(
                default="",
                max_length=32,
                description="Cohort filter — region (都道府県 / region code).",
            ),
        ] = "",
        size: Annotated[
            str,
            Field(
                default="",
                max_length=32,
                description="Cohort filter — size ('sme' / '中小企業' / 'large').",
            ),
        ] = "",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain B — anonymized_cohort_query_with_redact (dim N). Fuses the three dim N primitives (redact_pii_fields over the sample row, check_k_anonymity over the cohort_size, write_audit_entry for the APPI-grade audit row) into one composed call. Returns ComposedEnvelope with composed_steps (anonymized_query.redact_pii_fields + check_k_anonymity + write_audit_entry) + redacted_sample + audit_entry. NO LLM, 3 ¥3 units (heavy compound tier)."""
        return _anonymized_cohort_query_with_redact_impl(
            sample=sample,
            cohort_size=cohort_size,
            industry=industry,
            region=region,
            size=size,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def time_machine_snapshot_walk_chain(
        dataset_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=40,
                description=(
                    "Snapshot dataset id (e.g. 'programs', 'tax_rulesets', "
                    "'laws'). Maps to "
                    "data/snapshots/<yyyy_mm>/<dataset_id>.json."
                ),
            ),
        ],
        start_as_of_date: Annotated[
            str,
            Field(
                min_length=10,
                max_length=10,
                description=(
                    "Start of the walk window, ISO YYYY-MM-DD (older anchor)."
                ),
            ),
        ],
        end_as_of_date: Annotated[
            str,
            Field(
                min_length=10,
                max_length=10,
                description=(
                    "End of the walk window, ISO YYYY-MM-DD (newer anchor). "
                    "Must be >= start_as_of_date."
                ),
            ),
        ],
        month_count_cap: Annotated[
            int,
            Field(
                default=12,
                ge=1,
                le=60,
                description=(
                    "Bound on iterations. Caps the walk at this many monthly "
                    "buckets so a pathological window cannot absorb the full "
                    "60-month retention budget in one call. Range [1, 60]."
                ),
            ),
        ] = 12,
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain B — time_machine_snapshot_walk (dim Q). Walks one snapshot per month between start_as_of_date and end_as_of_date (capped at month_count_cap) and emits pairwise counterfactual_diff results so the agent can trace how the dataset evolved over the window. Returns ComposedEnvelope with composed_steps (time_machine.query_as_of:walk + counterfactual_diff:pairs) + diffs[] + resolved_snapshot_ids[]. NO LLM, 3 ¥3 units (heavy compound tier)."""
        return _time_machine_snapshot_walk_impl(
            dataset_id=dataset_id,
            start_as_of_date=start_as_of_date,
            end_as_of_date=end_as_of_date,
            month_count_cap=month_count_cap,
        )


__all__ = [
    "_anonymized_cohort_query_with_redact_impl",
    "_predictive_subscriber_fanout_impl",
    "_rule_tree_batch_eval_impl",
    "_session_multi_step_eligibility_impl",
    "_time_machine_snapshot_walk_impl",
]
