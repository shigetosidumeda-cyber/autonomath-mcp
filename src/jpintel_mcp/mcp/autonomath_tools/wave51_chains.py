"""Wave 51 service composition chain MCP wrappers (165 → 169).

Four MCP tools that surface the cross-dim composition chains defined in
``jpintel_mcp.composable_tools.wave51_chains`` so AI agent users can call
them via the same FastMCP stdio surface as the rest of the public
``autonomath-mcp`` tools.

Where ``wave51_dim_p_composed.py`` wraps the 4 dim P *atomic-fan-out*
composed tools (eligibility_audit_workpaper / subsidy_eligibility_full /
ma_due_diligence_pack / invoice_compatibility_check), this module wraps
the 4 **cross-dim chains** that thread the Wave 51 dim K-S modules
together — they are compound services that drive 3-5 dim modules per
call rather than 3-5 separate ¥3/req atomic calls:

    evidence_with_provenance         — dim P + Q + O + N
    session_aware_eligibility_check  — dim L + M + K
    federated_handoff_with_audit     — dim P + R + N
    temporal_compliance_audit        — dim Q + M + O

Each tool returns the canonical :class:`ComposedEnvelope` dict (JPCIR
``Evidence`` + ``OutcomeContract`` + citations + composed_steps), tagged
``_billing_unit=3`` to reflect the heavy-tier compound service price
(¥9.90 税込 vs. ¥3.30 for atomic calls) and the ¥900 estimated outcome
contract price ceiling Wave 50 RC1 sized compound chains for. Composed
``compression_ratio`` is surfaced so downstream SDK consumers can audit
the call density gain vs. atomic chaining.

Hard constraints (CLAUDE.md + ``feedback_composable_tools_pattern``):

* NO LLM call inside any wrapper body. Composition order is
  deterministic — declared by each chain's ``compose()`` body.
* No re-entry into the MCP protocol. The injected
  :class:`AtomicRegistry` is a Python-callable dispatcher; MCP-to-MCP
  recursion would re-spend the metering budget composition exists to
  compress. We pass a stub registry for the optional atomic_tool_name
  parameter — chains tolerate the stub via warnings instead of raising.
* 3 ¥3/billable units per compound call (heavy-tier compound service).
* §52 / §47条の2 / §72 / §1 / §3 non-substitution disclaimer envelope.
* Sensitive tool surface — every response carries ``_disclaimer``.
* No file-system writes against shared paths — chains accept
  ``audit_log_path`` / ``snapshot_registry`` / ``session_registry`` /
  ``predictive_event_path`` via kwargs so test fixtures can inject temp
  paths; the wrappers wire the chain primitives against the default
  filesystem paths (``data/snapshots/`` / ``data/sessions/`` /
  ``logs/anonymized_query_audit.jsonl``) at call time.
"""

from __future__ import annotations

import datetime as _dt
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
    EvidenceWithProvenance,
    FederatedHandoffWithAudit,
    SessionAwareEligibilityCheck,
    TemporalComplianceAudit,
)
from jpintel_mcp.config import settings
from jpintel_mcp.federated_mcp import load_default_registry as _load_federated_registry
from jpintel_mcp.mcp.server import _READ_ONLY, mcp
from jpintel_mcp.session_context import SessionRegistry
from jpintel_mcp.time_machine import SnapshotRegistry

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.wave51_chains")

_ENABLED = os.environ.get("AUTONOMATH_WAVE51_CHAINS_ENABLED", "1") in (
    "1",
    "true",
    "True",
    "yes",
    "on",
)

# Heavy-tier disclaimer — every chain emits this verbatim. The 5 sensitive
# fences (§52 / §47条の2 / §72 / §1 / §3) are matched by the no-LLM
# meta-test which greps for "§52" in the disclaimer body.
_DISCLAIMER = (
    "本 response は Wave 51 service composition chain (cross-dim K-S) の "
    "server-side 結果です。3-5 dim 連鎖 を 3 ¥3 units (税込 ¥9.90) "
    "に圧縮した heavy-tier compound service envelope であり、個別 dim "
    "primitive は jpcite SQLite + filesystem + 純 Python 経由で deterministic "
    "に解決されます。法的助言ではなく、税理士法 §52 / 公認会計士法 §47条の2 / "
    "弁護士法 §72 / 行政書士法 §1 / 司法書士法 §3 の代替ではありません。"
)

# Compound chains weigh ¥9.90 税込 — 3 ¥3 units per call (3x atomic).
# The ¥900 estimated outcome contract price ceiling (Wave 50 RC1 sizing
# for compound services) reflects the dim-fan-out savings vs raw LLM
# inference — see ``feedback_cost_saving_v2_quantified`` for the per-use
# case Y comparison the 14 outcome contracts were sized against.
_COMPOUND_BILLING_UNIT = 3


# ---------------------------------------------------------------------------
# Stub AtomicRegistry — composed chains do NOT re-enter MCP
# ---------------------------------------------------------------------------


class _StubAtomicRegistry:
    """Empty atomic registry stub for Wave 51 chain MCP wrappers.

    Mirrors the :class:`_StubAtomicRegistry` used by
    ``wave51_dim_p_composed.py``: the full atomic Python callable
    registry is wired in REST + ETL paths; in the FastMCP stdio runtime
    the atomic surface is the @mcp.tool registry, not a direct Python
    callable graph. Re-entering the MCP protocol from a chain would
    re-spend the metering budget composition exists to compress, so this
    wrapper provides a deterministic stub that:

    * returns ``has(name) == False`` for every tool name so chains route
      through the dim-module-only composition path (chains tolerate
      atomic absence via warnings rather than raising), and
    * surfaces a note in :meth:`call` output so downstream agents know
      where to call (the REST companion at ``/v1/composed/{tool}``) if
      they need the populated atomic payload.

    The stub is intentionally untyped against the
    :class:`AtomicRegistry` Protocol — Protocol membership is structural
    and the two methods + return shape suffice.
    """

    def call(self, tool_name: str, /, **_kwargs: Any) -> AtomicCallResult:
        return AtomicCallResult(
            tool_name=tool_name,
            payload={},
            citations=(),
            notes=(
                f"wave51_chain stub: atomic '{tool_name}' returned empty "
                "from FastMCP runtime stub registry; call REST companion "
                f"/v1/composed/{tool_name} for populated payload.",
            ),
        )

    def has(self, _tool_name: str, /) -> bool:
        # The chains check has() before call(); returning False routes
        # them through the dim-only path which is the contract under
        # FastMCP runtime — atomic re-entry is deferred to REST.
        return False


# ---------------------------------------------------------------------------
# Filesystem path helpers — wire chains against default repo locations
# ---------------------------------------------------------------------------


def _today_iso_utc() -> str:
    return _dt.datetime.now(tz=_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshots_root() -> Path:
    """Resolve the dim Q snapshot registry root from env / default.

    Mirrors :func:`wave51_dim_q_time_machine_v2._snapshots_root` so
    chains touching ``data/snapshots/`` share the same env override
    knob (``AUTONOMATH_SNAPSHOTS_ROOT``) used by the dim Q v2 wrapper.
    """
    override = os.environ.get("AUTONOMATH_SNAPSHOTS_ROOT")
    if override:
        return Path(override)
    # Repo-root default — src/jpintel_mcp/.. -> ../../.. -> repo root.
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


def _audit_log_path() -> Path:
    """Resolve the dim N audit log JSONL path.

    Mirrors :func:`wave51_dim_n_anonymized._audit_path` so chains
    that write APPI-grade audit rows share the same env override
    (``ANONYMIZED_QUERY_AUDIT_LOG_PATH``).
    """
    override = os.environ.get("ANONYMIZED_QUERY_AUDIT_LOG_PATH")
    if override:
        return Path(override)
    default = (
        Path(__file__).resolve().parents[4] / "logs" / "anonymized_query_audit.jsonl"
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
    """Execute a Wave 51 chain against the stub registry and return JPCIR envelope.

    The chain's ``ComposedEnvelope`` carries the canonical Evidence +
    OutcomeContract; we serialize via :meth:`ComposedEnvelope.to_dict`,
    then attach the heavy-tier billing markers + disclaimer so the
    response matches the wire shape the rest of the public MCP surface
    emits (search envelope keys ``results`` / ``total`` / ``limit`` /
    ``offset``).
    """
    registry = _StubAtomicRegistry()
    try:
        envelope: ComposedEnvelope = chain.compose(registry, **kwargs)
    except ComposedToolError as exc:
        return make_error(
            code="subsystem_unavailable",
            message=str(exc),
            hint=(
                "Wave 51 chain atomic dependency missing from runtime "
                "registry — call REST companion at /v1/chains/{tool}."
            ),
        )
    except ValueError as exc:
        # Chains raise ValueError on missing required dependencies
        # (SnapshotRegistry / SessionRegistry / RuleTree) — surface as
        # a structured error envelope rather than crashing the MCP loop.
        return make_error(
            code="missing_required_arg",
            message=str(exc),
            hint="Pass the required *_registry / rule_tree argument.",
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
# 1. evidence_with_provenance_chain — dim P + Q + O + N
# ---------------------------------------------------------------------------


def _evidence_with_provenance_impl(
    fact_id: str,
    cohort_size: int,
    dataset_id: str = "programs",
    as_of_date: str = "",
    source_doc: str = "https://www.e-gov.go.jp/",
    atomic_tool_name: str = "",
) -> dict[str, Any]:
    """dim P + Q + O + N chain — signed audit-grade evidence."""
    if not fact_id or not fact_id.strip():
        return make_error(
            code="missing_required_arg",
            message="fact_id is required.",
            field="fact_id",
            hint="Pass the canonical fact id whose evidence you want signed.",
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

    # Wire dim Q SnapshotRegistry only when as_of_date is supplied —
    # the chain tolerates a missing snapshot_registry and surfaces the
    # gap as a warning instead of raising.
    snapshot_registry: SnapshotRegistry | None = None
    as_of_value: Any = ""
    if as_of_date and as_of_date.strip():
        try:
            snapshot_registry = SnapshotRegistry(_snapshots_root())
            as_of_value = as_of_date.strip()
        except Exception as exc:  # pragma: no cover — filesystem guard
            logger.warning(
                "evidence_with_provenance_chain: SnapshotRegistry init failed: %s",
                exc,
            )
            snapshot_registry = None

    kwargs: dict[str, Any] = {
        "fact_id": fact_id,
        "cohort_size": cohort_size,
        "dataset_id": dataset_id,
        "source_doc": source_doc,
        "atomic_tool_name": atomic_tool_name,
    }
    if snapshot_registry is not None:
        kwargs["snapshot_registry"] = snapshot_registry
        kwargs["as_of_date"] = as_of_value

    return _run_chain(EvidenceWithProvenance(), **kwargs)


# ---------------------------------------------------------------------------
# 2. session_aware_eligibility_check_chain — dim L + M + K
# ---------------------------------------------------------------------------


def _session_aware_eligibility_check_impl(
    subject_id: str,
    rule_tree_json: dict[str, Any] | None,
    predictive_target_id: str,
    subject_context: dict[str, Any] | None = None,
    eval_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """dim L + M + K chain — session-aware eligibility + predictive notify."""
    if not subject_id or not subject_id.strip():
        return make_error(
            code="missing_required_arg",
            message="subject_id is required.",
            field="subject_id",
            hint="Pass the 法人番号 / entity id whose eligibility you want to evaluate.",
        )
    if not predictive_target_id or not predictive_target_id.strip():
        return make_error(
            code="missing_required_arg",
            message="predictive_target_id is required.",
            field="predictive_target_id",
            hint=(
                "Pass a watch target id like 'program:<slug>', "
                "'amendment:<slug>', or 'houjin:<13 digits>'."
            ),
        )

    # Build the dim M RuleTree on the fly from the caller-supplied JSON
    # so the agent can describe the tree inline (matches the rest of the
    # autonomath surface which accepts JSON over the stdio wire).
    rule_tree: Any = None
    if isinstance(rule_tree_json, dict):
        try:
            from jpintel_mcp.rule_tree import RuleTree

            rule_tree = RuleTree.model_validate(rule_tree_json)
        except Exception as exc:  # noqa: BLE001 — surface in envelope
            return make_error(
                code="invalid_input",
                message=f"rule_tree_json failed validation: {exc}",
                field="rule_tree_json",
            )

    # Wire dim L SessionRegistry against the default repo path so the
    # 24h state token persists across calls; tests inject via env var.
    try:
        session_registry = SessionRegistry(root=_sessions_root())
    except Exception as exc:  # pragma: no cover — filesystem guard
        return make_error(
            code="db_unavailable",
            message=f"session registry init failed: {exc}",
        )

    kwargs: dict[str, Any] = {
        "subject_id": subject_id,
        "predictive_target_id": predictive_target_id,
        "session_registry": session_registry,
        "predictive_event_path": _predictive_event_path(),
    }
    if rule_tree is not None:
        kwargs["rule_tree"] = rule_tree
    if isinstance(subject_context, dict):
        kwargs["subject_context"] = subject_context
    if isinstance(eval_context, dict):
        kwargs["eval_context"] = eval_context

    return _run_chain(SessionAwareEligibilityCheck(), **kwargs)


# ---------------------------------------------------------------------------
# 3. federated_handoff_with_audit_chain — dim P + R + N
# ---------------------------------------------------------------------------


def _federated_handoff_with_audit_impl(
    query_gap: str,
    max_results: int = 3,
    atomic_tool_name: str = "",
    industry: str = "",
    region: str = "",
    size: str = "",
) -> dict[str, Any]:
    """dim P + R + N chain — federated handoff + APPI audit row."""
    if not query_gap or not query_gap.strip():
        return make_error(
            code="missing_required_arg",
            message="query_gap is required.",
            field="query_gap",
            hint=(
                "Pass a free-form gap description e.g. "
                "'freee の請求書 #1234'."
            ),
        )
    if max_results < 1 or max_results > 6:
        return make_error(
            code="out_of_range",
            message="max_results must be in [1, 6].",
            field="max_results",
        )

    # Wire dim R FederatedRegistry (curated 6-partner) — read-only.
    federated_registry = _load_federated_registry()

    kwargs: dict[str, Any] = {
        "query_gap": query_gap,
        "max_results": max_results,
        "atomic_tool_name": atomic_tool_name,
        "federated_registry": federated_registry,
        "audit_log_path": _audit_log_path(),
    }
    # Optional cohort filter axes (industry / region / size) feed into
    # the dim N cohort_hash so audit rows are anonymized but reproducible.
    if industry:
        kwargs["industry"] = industry
    if region:
        kwargs["region"] = region
    if size:
        kwargs["size"] = size

    return _run_chain(FederatedHandoffWithAudit(), **kwargs)


# ---------------------------------------------------------------------------
# 4. temporal_compliance_audit_chain — dim Q + M + O
# ---------------------------------------------------------------------------


def _temporal_compliance_audit_impl(
    dataset_id: str,
    baseline_as_of_date: str,
    compare_as_of_date: str,
    rule_tree_json: dict[str, Any] | None,
    eval_context: dict[str, Any] | None = None,
    audit_fact_id: str = "",
    audit_source_doc: str = "https://www.e-gov.go.jp/",
) -> dict[str, Any]:
    """dim Q + M + O chain — counterfactual diff + signed verdict."""
    if not dataset_id or not dataset_id.strip():
        return make_error(
            code="missing_required_arg",
            message="dataset_id is required.",
            field="dataset_id",
        )
    if not baseline_as_of_date or not baseline_as_of_date.strip():
        return make_error(
            code="missing_required_arg",
            message="baseline_as_of_date is required.",
            field="baseline_as_of_date",
            hint="Pass an ISO YYYY-MM-DD date — the older anchor.",
        )
    if not compare_as_of_date or not compare_as_of_date.strip():
        return make_error(
            code="missing_required_arg",
            message="compare_as_of_date is required.",
            field="compare_as_of_date",
            hint="Pass an ISO YYYY-MM-DD date — the newer anchor.",
        )

    # Build the dim M RuleTree on the fly from caller-supplied JSON.
    rule_tree: Any = None
    if isinstance(rule_tree_json, dict):
        try:
            from jpintel_mcp.rule_tree import RuleTree

            rule_tree = RuleTree.model_validate(rule_tree_json)
        except Exception as exc:  # noqa: BLE001 — surface in envelope
            return make_error(
                code="invalid_input",
                message=f"rule_tree_json failed validation: {exc}",
                field="rule_tree_json",
            )

    # Wire dim Q SnapshotRegistry against the default repo path.
    try:
        snapshot_registry = SnapshotRegistry(_snapshots_root())
    except Exception as exc:  # pragma: no cover — filesystem guard
        return make_error(
            code="db_unavailable",
            message=f"snapshot registry init failed: {exc}",
        )

    kwargs: dict[str, Any] = {
        "dataset_id": dataset_id,
        "baseline_as_of_date": baseline_as_of_date,
        "compare_as_of_date": compare_as_of_date,
        "snapshot_registry": snapshot_registry,
        "audit_source_doc": audit_source_doc,
    }
    if rule_tree is not None:
        kwargs["rule_tree"] = rule_tree
    if isinstance(eval_context, dict):
        kwargs["eval_context"] = eval_context
    if audit_fact_id:
        kwargs["audit_fact_id"] = audit_fact_id

    return _run_chain(TemporalComplianceAudit(), **kwargs)


# ---------------------------------------------------------------------------
# MCP tool registration — gated on AUTONOMATH_WAVE51_CHAINS_ENABLED + settings
# ---------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def evidence_with_provenance_chain(
        fact_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=128,
                description=(
                    "Canonical fact id whose evidence will be locked to a "
                    "snapshot, signed (Ed25519 canonical payload), and "
                    "gated behind k=5 cohort floor."
                ),
            ),
        ],
        cohort_size: Annotated[
            int,
            Field(
                ge=0,
                description=(
                    "Pre-computed cohort size for the fact. Must be >= 5 "
                    "(K_ANONYMITY_MIN) for support_state=supported; "
                    "smaller cohorts downgrade to 'partial' with a warning."
                ),
            ),
        ],
        dataset_id: Annotated[
            str,
            Field(
                default="programs",
                max_length=40,
                description=(
                    "Snapshot dataset id (e.g. 'programs', 'laws'). Maps "
                    "to data/snapshots/<yyyy_mm>/<dataset_id>.json."
                ),
            ),
        ] = "programs",
        as_of_date: Annotated[
            str,
            Field(
                default="",
                max_length=10,
                description=(
                    "Optional ISO YYYY-MM-DD pivot date. When set, the "
                    "chain locks the response to the nearest <= snapshot. "
                    "Empty = rolling/observed envelope."
                ),
            ),
        ] = "",
        source_doc: Annotated[
            str,
            Field(
                default="https://www.e-gov.go.jp/",
                max_length=512,
                description="Primary-source URL for the FactMetadata payload.",
            ),
        ] = "https://www.e-gov.go.jp/",
        atomic_tool_name: Annotated[
            str,
            Field(
                default="",
                max_length=64,
                description=(
                    "Optional composable_tools atomic name to invoke. "
                    "FastMCP runtime stub registry routes through dim-only "
                    "composition — use REST companion for atomic data."
                ),
            ),
        ] = "",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain — evidence_with_provenance (dim P + Q + O + N). Locks a fact to a monthly snapshot, builds an Ed25519-signable canonical payload, and gates the response behind k=5 cohort floor. Returns ComposedEnvelope with composed_steps (time_machine.query_as_of + explainable_fact.canonical_payload + anonymized_query.check_k_anonymity) + compression_ratio. NO LLM, 3 ¥3 units (税込 ¥9.90 — heavy compound tier)."""
        return _evidence_with_provenance_impl(
            fact_id=fact_id,
            cohort_size=cohort_size,
            dataset_id=dataset_id,
            as_of_date=as_of_date,
            source_doc=source_doc,
            atomic_tool_name=atomic_tool_name,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def session_aware_eligibility_check_chain(
        subject_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description=(
                    "Entity id (法人番号 / individual id) whose eligibility "
                    "is being evaluated."
                ),
            ),
        ],
        predictive_target_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                description=(
                    "Watch target id — 'program:<slug>' / 'amendment:<slug>' "
                    "/ 'houjin:<13 digits>'. Determines event_type."
                ),
            ),
        ],
        rule_tree_json: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Optional JSON-serialised RuleTree (dim M). When "
                    "omitted, the chain still opens the session + enqueues "
                    "the predictive event but evaluation is skipped."
                ),
            ),
        ] = None,
        subject_context: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Subject-side context payload persisted in the 24h "
                    "session token (saved_context). Free-shape dict."
                ),
            ),
        ] = None,
        eval_context: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Extra context merged into the rule_tree.evaluate "
                    "input. Free-shape dict."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain — session_aware_eligibility_check (dim L + M + K). Opens a 24h session_context, evaluates rule_tree, enqueues a predictive_service event so the subject is notified the next time the underlying ruleset changes, then closes the session. Returns ComposedEnvelope with composed_steps (session_context.open_session + rule_tree.evaluate_tree + predictive_service.enqueue_event + session_context.close_session) + verdict + session_token_id. NO LLM, 3 ¥3 units (heavy compound tier)."""
        return _session_aware_eligibility_check_impl(
            subject_id=subject_id,
            rule_tree_json=rule_tree_json,
            predictive_target_id=predictive_target_id,
            subject_context=subject_context,
            eval_context=eval_context,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def federated_handoff_with_audit_chain(
        query_gap: Annotated[
            str,
            Field(
                min_length=1,
                max_length=512,
                description=(
                    "Free-form description of the unanswered request. "
                    "Example: 'freee の請求書 #1234 が必要' or 'look up "
                    "the pull request title on github'."
                ),
            ),
        ],
        max_results: Annotated[
            int,
            Field(
                ge=1,
                le=6,
                description="Maximum number of partners to return (1-6).",
            ),
        ] = 3,
        atomic_tool_name: Annotated[
            str,
            Field(
                default="",
                max_length=64,
                description=(
                    "Optional composable_tools atomic name to confirm the "
                    "gap (e.g. 'search_programs_am'). FastMCP runtime "
                    "stub routes to dim-only composition."
                ),
            ),
        ] = "",
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
                description="Cohort filter — size (e.g. 'sme', '中小企業', 'large').",
            ),
        ] = "",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain — federated_handoff_with_audit (dim P + R + N). When jpcite cannot answer, asks the curated 6-partner federation (freee/mf/notion/slack/github/linear) for a handoff recommendation, then writes one APPI-grade audit row (cohort hash + redact policy + outcome reason). Returns ComposedEnvelope with composed_steps (federated_mcp.recommend_handoff + anonymized_query.write_audit_entry) + recommendations[] + audit_entry. NO LLM, no HTTP, 3 ¥3 units (heavy compound tier)."""
        return _federated_handoff_with_audit_impl(
            query_gap=query_gap,
            max_results=max_results,
            atomic_tool_name=atomic_tool_name,
            industry=industry,
            region=region,
            size=size,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def temporal_compliance_audit_chain(
        dataset_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=40,
                description=(
                    "Snapshot dataset id (e.g. 'programs', 'tax_rulesets'). "
                    "Maps to data/snapshots/<yyyy_mm>/<dataset_id>.json."
                ),
            ),
        ],
        baseline_as_of_date: Annotated[
            str,
            Field(
                min_length=10,
                max_length=10,
                description="Baseline 'before' date, ISO YYYY-MM-DD (older anchor).",
            ),
        ],
        compare_as_of_date: Annotated[
            str,
            Field(
                min_length=10,
                max_length=10,
                description="Compare 'after' date, ISO YYYY-MM-DD (newer anchor).",
            ),
        ],
        rule_tree_json: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Optional JSON-serialised RuleTree (dim M) evaluated "
                    "over the diff. When omitted, the chain returns the "
                    "diff + signable payload without a verdict."
                ),
            ),
        ] = None,
        eval_context: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Extra context merged into the rule_tree.evaluate "
                    "input alongside the diff counters."
                ),
            ),
        ] = None,
        audit_fact_id: Annotated[
            str,
            Field(
                default="",
                max_length=128,
                description=(
                    "Caller-supplied id for the resulting signed compliance "
                    "fact. Default = f'compliance_audit_{dataset_id}'."
                ),
            ),
        ] = "",
        audit_source_doc: Annotated[
            str,
            Field(
                default="https://www.e-gov.go.jp/",
                max_length=512,
                description="Primary-source URL for the FactMetadata payload.",
            ),
        ] = "https://www.e-gov.go.jp/",
    ) -> dict[str, Any]:
        """[AUDIT, SENSITIVE — §52/§47条の2/§72/§1] Wave 51 chain — temporal_compliance_audit (dim Q + M + O). Resolves two monthly snapshots, runs counterfactual_diff (added/removed/changed/unchanged + content_hash_changed), evaluates a rule_tree over the diff, then builds an Ed25519-signable canonical payload for the verdict. Returns ComposedEnvelope with composed_steps (time_machine.query_as_of:baseline + :compare + counterfactual_diff + rule_tree.evaluate_tree + explainable_fact.canonical_payload). The "monthly closing compliance regression" surface. NO LLM, 3 ¥3 units (heavy compound tier)."""
        return _temporal_compliance_audit_impl(
            dataset_id=dataset_id,
            baseline_as_of_date=baseline_as_of_date,
            compare_as_of_date=compare_as_of_date,
            rule_tree_json=rule_tree_json,
            eval_context=eval_context,
            audit_fact_id=audit_fact_id,
            audit_source_doc=audit_source_doc,
        )


__all__ = [
    "_evidence_with_provenance_impl",
    "_federated_handoff_with_audit_impl",
    "_session_aware_eligibility_check_impl",
    "_temporal_compliance_audit_impl",
]
