"""MCP server-to-server federation discovery (Wave 19 #A5).

Solves the "agent-orchestrator wants to compose tools from multiple MCP
servers" problem. When a remote MCP server (e.g. weather.com, a partner
cabin-listing server, a 3rd-party amendment-alert feed) wants to know
whether jpcite can be invoked downstream in a workflow chain, it needs
a compact, machine-readable compatibility declaration: which of our
tools speak which input schemas, which output envelopes, and which
disclaimers apply.

This module provides that surface as a single REST GET:

    GET /v1/meta/federation

The response declares:

  - ``server_id`` — canonical jpcite identifier
  - ``capabilities`` — protocol features advertised
  - ``jpcite_compatible_tools[]`` — tools that downstream servers can
    feed into / receive from, with schema fingerprints
  - ``allied_servers[]`` — declared interoperability partners (manual
    allow-list; we do not auto-trust)
  - ``handoff_patterns[]`` — canonical workflow chains (e.g. weather →
    program-search → application-kit) we participate in

NO LLM API call. Pure manifest assembly from local module state + a
small handcurated allow-list. Production-safe under CLAUDE.md rule
"never import anthropic/openai/google.generativeai/claude_agent_sdk in
src/".

Schema version: ``mcp-federation-discovery/v1``. Forward-compat: a
client that doesn't recognise a future field MUST ignore it (RFC 8259
JSON parse + soft-field model).
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger("jpintel.mcp.federation")

FEDERATION_SCHEMA = "mcp-federation-discovery/v1"
SERVER_ID = "jpcite.mcp.bookyou"
CANONICAL_SITE = "https://jpcite.com"

# Manual allow-list of allied MCP servers we have declared interop with.
# Keep small; auto-discovery is intentionally not implemented. Each entry
# names a server_id we will accept as a workflow chain partner in
# ``handoff_patterns``. Operator updates this list by hand on review.
ALLIED_SERVERS: list[dict[str, str]] = [
    {
        "server_id": "weather.example.mcp",
        "role": "input_preconditioner",
        "trust": "advisory",
        "notes": "Disaster-period 災害復興 cohort gating. Output feeds program-search.",
    },
    {
        "server_id": "tax-rates.example.mcp",
        "role": "output_enricher",
        "trust": "advisory",
        "notes": "Adds 法定実効税率 numeric to programs after our tool returns.",
    },
    {
        "server_id": "houjin-watch.example.mcp",
        "role": "trigger_source",
        "trust": "advisory",
        "notes": "Subscribes to /v1/houjin_watch webhook; fans out to its own consumers.",
    },
]

# Canonical handoff patterns we participate in. Each describes a chain
# of MCP tool calls across servers. Downstream orchestrators (LangGraph,
# CrewAI, autogen) consume these as workflow recipes.
HANDOFF_PATTERNS: list[dict[str, Any]] = [
    {
        "id": "disaster_recovery_program_match",
        "description": "Disaster event → programs eligible for 災害復興 special measures → application kit.",
        "chain": [
            {"server": "weather.example.mcp", "tool": "get_disaster_event"},
            {"server": SERVER_ID, "tool": "search_programs", "filter": "tag=disaster"},
            {"server": SERVER_ID, "tool": "bundle_application_kit"},
        ],
        "sensitive": True,
        "disclaimer_required": "§52",
    },
    {
        "id": "houjin_baseline_dd",
        "description": "法人番号 → 全項目 baseline → DD checklist → audit pack.",
        "chain": [
            {"server": SERVER_ID, "tool": "createCompanyPublicBaseline"},
            {"server": SERVER_ID, "tool": "match_due_diligence_questions"},
            {"server": SERVER_ID, "tool": "createCompanyPublicAuditPack"},
        ],
        "sensitive": True,
        "disclaimer_required": "§52/§72",
    },
    {
        "id": "amendment_alert_fanout",
        "description": "Our amendment-alert webhook → partner-side downstream consumer chain.",
        "chain": [
            {"server": SERVER_ID, "trigger": "webhook:amendment_alert"},
            {"server": "houjin-watch.example.mcp", "tool": "fanout_subscribers"},
        ],
        "sensitive": False,
    },
]

# Compatibility declarations: tools that downstream / upstream servers
# can safely chain with. The schema_fingerprint is a stable SHA-256 of
# the JSON-serialised input/output schema, so partners can detect
# breaking changes by hash-diff alone.
JPCITE_COMPATIBLE_TOOLS: list[dict[str, Any]] = [
    {
        "tool_id": "search_programs",
        "input_envelope": "ProgramSearchQuery/v3",
        "output_envelope": "PaginatedProgramList/v3",
        "idempotent": True,
        "auth": "X-API-Key (optional; anon 3/day)",
        "billable_per_call": True,
        "disclaimer": None,
    },
    {
        "tool_id": "createCompanyPublicBaseline",
        "input_envelope": "HoujinBangouQuery/v2",
        "output_envelope": "Houjin360Baseline/v2",
        "idempotent": True,
        "auth": "X-API-Key required",
        "billable_per_call": True,
        "disclaimer": "§52",
    },
    {
        "tool_id": "bundle_application_kit",
        "input_envelope": "ApplicationKitQuery/v1",
        "output_envelope": "ApplicationKitBundle/v1",
        "idempotent": True,
        "auth": "X-API-Key required",
        "billable_per_call": True,
        "disclaimer": "§1 (行政書士法)",
    },
    {
        "tool_id": "match_due_diligence_questions",
        "input_envelope": "DDMatchQuery/v1",
        "output_envelope": "DDQuestionDeck/v1",
        "idempotent": True,
        "auth": "X-API-Key required",
        "billable_per_call": True,
        "disclaimer": "§52/§72",
    },
    {
        "tool_id": "get_evidence_packet",
        "input_envelope": "EvidencePacketQuery/v2",
        "output_envelope": "EvidencePacketEnvelope/v2",
        "idempotent": True,
        "auth": "X-API-Key required",
        "billable_per_call": True,
        "disclaimer": None,
    },
    {
        "tool_id": "previewCost",
        "input_envelope": "CostPreviewQuery/v1",
        "output_envelope": "CostPreviewEnvelope/v1",
        "idempotent": True,
        "auth": "none (free)",
        "billable_per_call": False,
        "disclaimer": None,
    },
]


def _schema_fingerprint(spec: dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of a tool's compat declaration."""
    canon = json.dumps(spec, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def build_federation_manifest() -> dict[str, Any]:
    """Assemble the full federation discovery manifest."""
    tools = []
    for t in JPCITE_COMPATIBLE_TOOLS:
        tools.append({**t, "schema_fingerprint": _schema_fingerprint(t)})
    return {
        "schema_version": FEDERATION_SCHEMA,
        "server_id": SERVER_ID,
        "canonical_site": CANONICAL_SITE,
        "operator": "Bookyou株式会社",
        "operator_corporate_number": "8010001213708",
        "capabilities": {
            "protocol": "mcp/2025-06-18",
            "transport": ["stdio", "streamable_http"],
            "sampling": True,
            "resources": True,
            "prompts": True,
            "tool_count_runtime": 146,
            "tool_count_manifest": 139,
        },
        "jpcite_compatible_tools": tools,
        "allied_servers": ALLIED_SERVERS,
        "handoff_patterns": HANDOFF_PATTERNS,
        "interop_policy": {
            "trust_default": "advisory",
            "auto_discover": False,
            "allowlist_only": True,
            "operator_review_required": True,
        },
        "cross_references": {
            "mcp_manifest": f"{CANONICAL_SITE}/mcp-server.json",
            "server_json": f"{CANONICAL_SITE}/server.json",
            "openapi_discovery": f"{CANONICAL_SITE}/.well-known/openapi-discovery.json",
            "llms_txt": f"{CANONICAL_SITE}/llms.txt",
        },
    }


router = APIRouter(prefix="/v1/meta", tags=["federation"])


@router.get("/federation", summary="MCP federation discovery manifest")
def get_federation_manifest() -> dict[str, Any]:
    """Return the federation compatibility declaration.

    Allied MCP servers can fetch this once per workflow boot to
    determine which jpcite tools they can chain. The schema_fingerprint
    field on each tool lets partners cache-invalidate when our envelope
    contract changes.
    """
    return build_federation_manifest()
