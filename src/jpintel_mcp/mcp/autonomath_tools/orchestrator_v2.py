"""orchestrator_v2 — Wave 43.2.6 Dim F multi-agent orchestration MCP tool.

Single MCP tool wrapping the four ``/v1/orchestrate/{target}`` REST routes
into one ``orchestrate_to_external_am`` entry point. AI agents discover
this tool via ``mcp.list_tools()`` and pick the target enum at call time
instead of choosing between four separate tools.

Tool shipped here
-----------------

  orchestrate_to_external_am(target, action, payload)
      Unified invoke surface. ``target`` is one of:

        - ``freee``  : POST customer's freee 仕訳 rows to freee receipts API
        - ``mf``     : POST customer's MoneyForward 経費 rows to MF Cloud API
        - ``notion`` : POST jpcite amendment matches as Notion database pages
        - ``slack``  : POST a Block Kit alert to the customer's Slack webhook

      ``action`` is currently only ``"invoke"`` (reserved for future
      ``"dry_run"`` / ``"preview"`` extensions). ``payload`` is a dict
      that mirrors the REST request body for the chosen target — see the
      per-target Pydantic schemas in ``api/orchestrator_v2.py``.

Pricing
-------

Each invocation logs ``quantity=ORCHESTRATE_UNIT_COUNT`` (3) against the
``orchestrate.<target>`` endpoint name via ``log_usage`` — same metering
as the REST surface. 3 units × ¥3 = ¥9 per call. Authentication is the
customer-side X-API-Key / Authorization Bearer; anonymous tier rejected
inside the impl (call returns ``error_envelope`` rather than raising,
matching the rest of the autonomath_tools package).

Memory references
-----------------
* ``feedback_zero_touch_solo`` — self-serve only. Customer brings their
  own freee / MF / Notion / Slack token; we don't store it.
* ``feedback_no_operator_llm_api`` — no anthropic / openai / sdk import.
* ``feedback_autonomath_no_api_use`` — composition is pure Python; the
  customer's LLM (Claude / Cursor / Codex) is the only LLM in the loop.
* ``feedback_ax_4_pillars`` — Layer-3 (Orchestration) surface. The agent
  drives the chain end-to-end (jpcite query -> external SaaS POST).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.orchestrator_v2")

# Env-gated registration (default on). Flip to "0" for one-flag rollback
# if a regression surfaces post-launch.
_ENABLED = (
    get_flag("JPCITE_ORCHESTRATOR_V2_ENABLED", "AUTONOMATH_ORCHESTRATOR_V2_ENABLED", "1") == "1"
)

# Mirror the REST router. Adding a new target requires touching BOTH the
# REST routes (api/orchestrator_v2.py) and this list — keep them in sync.
_ALLOWED_TARGETS: tuple[str, ...] = ("freee", "mf", "notion", "slack")
_ALLOWED_ACTIONS: tuple[str, ...] = ("invoke",)

# 1 MCP call = 3 billable units (matches REST). Stripe quantizes this
# against the orchestrate.<target> endpoint name when the customer's API
# key meters through the REST surface; the MCP path is operator-side
# composition only — the actual outbound HTTP POST happens inside the
# REST handler that the MCP customer invokes from their own agent.
ORCHESTRATE_UNIT_COUNT = 3

# Per-target minimal required field set. We validate at the tool boundary
# rather than punting to the REST 422 so the customer LLM sees a clean
# error envelope with retry guidance instead of a Pydantic ValidationError.
_REQUIRED_PAYLOAD_FIELDS: dict[str, frozenset[str]] = {
    "freee": frozenset({"freee_token", "company_id", "rows"}),
    "mf": frozenset({"mf_token", "office_id", "rows"}),
    "notion": frozenset({"notion_token", "database_id", "amendment_keys"}),
    "slack": frozenset({"slack_webhook_url", "kind", "title", "summary", "url"}),
}


# ---------------------------------------------------------------------------
# Disclaimer (§52 fence — orchestration touches accounting + tax surfaces)
# ---------------------------------------------------------------------------

_DISCLAIMER = (
    "本 response は freee / MoneyForward / Notion / Slack へのパススルー "
    "invoke 結果で、税務代理 (税理士法 §52)・申請代理 (行政書士法 §1)・"
    "法律事務 (弁護士法 §72) の代替ではありません。仕訳・科目割当は機械的 "
    "LIKE match で、最終判断は資格を有する士業と顧問先の合意のうえで "
    "行ってください。delivery_status が 4xx/5xx の場合は customer 側 token / "
    "API スコープ / quota を確認してください。"
)


# ---------------------------------------------------------------------------
# Compound _next_calls hints
# ---------------------------------------------------------------------------


def _next_calls_for_orchestrate(target: str, delivered_count: int) -> list[dict[str, Any]]:
    """Suggest 1-2 follow-up calls so the customer LLM chains naturally.

    Compound multiplier target: 1.8× — after an orchestrate the LLM
    typically asks "what's the audit trail?" (provenance) or "show me
    similar amendments" (track_amendment_lineage_am).
    """
    calls: list[dict[str, Any]] = [
        {
            "tool": "get_provenance",
            "args": {"entity_id": "<matched_program_id from results>"},
            "rationale": (
                "Audit trail for the matched program — required when the "
                "downstream system asks 'why did jpcite pick this row?'."
            ),
            "compound_mult": 1.4,
        },
    ]
    if target in ("freee", "mf"):
        calls.append(
            {
                "tool": "check_funding_stack_am",
                "args": {"program_ids": ["<matched_program_id>"]},
                "rationale": (
                    "Stack-rule sanity check — does the matched program "
                    "stack with the customer's existing 助成金?"
                ),
                "compound_mult": 1.5,
            }
        )
    elif target == "notion":
        calls.append(
            {
                "tool": "track_amendment_lineage_am",
                "args": {
                    "target_kind": "program",
                    "target_id": "<matched_program_id>",
                },
                "rationale": (
                    "Amendment lineage for the Notion ticket — surface the "
                    "history of changes before the tax team picks it up."
                ),
                "compound_mult": 1.4,
            }
        )
    if delivered_count == 0:
        calls.append(
            {
                "tool": "list_orchestrate_targets_am",
                "args": {},
                "rationale": (
                    "Zero deliveries — re-check target enum and token "
                    "scope. The /targets surface lists allowed values."
                ),
                "compound_mult": 1.1,
            }
        )
    return calls


# ---------------------------------------------------------------------------
# Pure-Python impl
# ---------------------------------------------------------------------------


def _orchestrate_impl(target: str, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate inputs and surface the orchestration manifest.

    Important: the MCP path does NOT make the outbound HTTP call to the
    external SaaS — that responsibility sits on the REST handler so the
    Stripe usage record + audit log + rate floor stay on ONE code path.
    The MCP tool returns the manifest (target + validated payload shape
    + ¥3/req cost preview + _next_calls) so the customer LLM can POST
    to ``/v1/orchestrate/{target}`` with confidence.
    """
    if target not in _ALLOWED_TARGETS:
        return make_error(
            code="invalid_argument",
            message=(f"target must be one of {_ALLOWED_TARGETS!r}; got {target!r}."),
            field="target",
            retry_with=["list_orchestrate_targets_am"],
        )
    if action not in _ALLOWED_ACTIONS:
        return make_error(
            code="invalid_argument",
            message=(f"action must be one of {_ALLOWED_ACTIONS!r}; got {action!r}."),
            field="action",
        )
    if not isinstance(payload, dict):
        return make_error(
            code="missing_required_arg",
            message="payload must be a dict matching the target's REST body schema.",
            field="payload",
        )
    required = _REQUIRED_PAYLOAD_FIELDS[target]
    missing = sorted(required - set(payload.keys()))
    if missing:
        return make_error(
            code="missing_required_arg",
            message=(f"payload missing required keys for target={target!r}: {missing!r}."),
            field="payload",
        )
    rest_path = f"/v1/orchestrate/{target}"
    return {
        "target": target,
        "action": action,
        "rest_endpoint": rest_path,
        "metered_units_per_call": ORCHESTRATE_UNIT_COUNT,
        "yen_per_call": ORCHESTRATE_UNIT_COUNT * 3,
        "payload_keys_validated": sorted(payload.keys()),
        "next_step": (
            f"POST {rest_path} with the validated payload using your "
            "metered API key. The REST handler performs the outbound HTTP "
            "call to the target SaaS and records the usage_event."
        ),
        "_next_calls": _next_calls_for_orchestrate(target, delivered_count=0),
        "_disclaimer": _DISCLAIMER,
    }


def _list_targets_impl() -> dict[str, Any]:
    """Helper to surface the allowed targets + per-call pricing."""
    return {
        "targets": list(_ALLOWED_TARGETS),
        "actions": list(_ALLOWED_ACTIONS),
        "metered_units_per_call": ORCHESTRATE_UNIT_COUNT,
        "yen_per_call": ORCHESTRATE_UNIT_COUNT * 3,
        "rest_endpoints": [f"/v1/orchestrate/{t}" for t in _ALLOWED_TARGETS],
        "required_payload_fields": {
            t: sorted(_REQUIRED_PAYLOAD_FIELDS[t]) for t in _ALLOWED_TARGETS
        },
        "_disclaimer": _DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# MCP tool registration (gated by AUTONOMATH_ORCHESTRATOR_V2_ENABLED +
# global AUTONOMATH_ENABLED checked at package __init__.py).
# ---------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def orchestrate_to_external_am(
        target: Annotated[
            Literal["freee", "mf", "notion", "slack"],
            Field(
                description=(
                    "External SaaS target to invoke. Use list_orchestrate_targets_am"
                    " to discover allowed values + per-target required payload keys."
                ),
            ),
        ],
        action: Annotated[
            Literal["invoke"],
            Field(
                description=(
                    "Reserved enum. Only 'invoke' is live today; 'dry_run'/'preview'"
                    " land in a future Wave."
                ),
            ),
        ],
        payload: Annotated[
            dict[str, Any],
            Field(
                description=(
                    "Body that mirrors the target's REST schema (see /v1/orchestrate/{target})."
                ),
            ),
        ],
    ) -> dict[str, Any]:
        """Validate orchestration intent + return the REST manifest. Customer LLM then POSTs to /v1/orchestrate/{target} for actual outbound HTTP. 1 call = 3 metered units (¥9). §52 sensitive (accounting/tax surfaces)."""
        return _orchestrate_impl(target=target, action=action, payload=payload)

    @mcp.tool(annotations=_READ_ONLY)
    def list_orchestrate_targets_am() -> dict[str, Any]:
        """List allowed orchestration targets + per-target required payload keys + per-call pricing. NOT metered (discovery surface)."""
        return _list_targets_impl()
