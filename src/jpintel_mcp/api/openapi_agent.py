"""Agent-safe OpenAPI projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

AGENT_SAFE_PATHS: tuple[str, ...] = (
    "/v1/intelligence/precomputed/query",
    "/v1/evidence/packets/query",
    "/v1/programs/search",
    "/v1/programs/{unified_id}",
    "/v1/source_manifest/{program_id}",
    "/v1/meta/freshness",
    "/v1/stats/coverage",
    "/v1/stats/freshness",
    "/v1/citations/verify",
    "/v1/cost/preview",
)

_AGENT_PRIORITIES: dict[str, tuple[int, str]] = {
    "/v1/intelligence/precomputed/query": (1, "compact_first_pass"),
    "/v1/evidence/packets/query": (2, "source_linked_evidence_packet"),
    "/v1/citations/verify": (3, "optional_citation_check"),
}

_AGENT_OPERATION_IDS: dict[tuple[str, str], str] = {
    ("get", "/v1/intelligence/precomputed/query"): "prefetchIntelligence",
    ("post", "/v1/evidence/packets/query"): "queryEvidencePacket",
    ("get", "/v1/programs/search"): "searchPrograms",
    ("get", "/v1/programs/{unified_id}"): "getProgram",
    ("get", "/v1/source_manifest/{program_id}"): "getSourceManifest",
    ("get", "/v1/meta/freshness"): "getMetaFreshness",
    ("get", "/v1/stats/coverage"): "getStatsCoverage",
    ("get", "/v1/stats/freshness"): "getStatsFreshness",
    ("post", "/v1/citations/verify"): "verifyCitations",
    ("post", "/v1/cost/preview"): "previewCost",
}

_AGENT_PRICING_METADATA: dict[str, Any] = {
    "billing_model": "metered_api_and_mcp_calls",
    "unit_price_jpy_ex_tax": 3,
    "unit_price_jpy_tax_included": 3.3,
    "anonymous_limit": "3 requests/day per IP, resets at 00:00 JST",
    "api_key_header": "X-API-Key",
    "api_key_env_var": "JPCITE_API_KEY",
    "pricing_url": "https://jpcite.com/pricing.html",
    "upgrade_url": "https://jpcite.com/pricing.html#api-paid",
    "simple_usage_examples": [
        {
            "billable_units": 10,
            "estimated_jpy_tax_included": 33,
            "plain_ja": "10回使っても税込約33円です。",
            "plain_en": "10 billable calls are about JPY 33 including tax.",
        },
        {
            "billable_units": 100,
            "estimated_jpy_tax_included": 330,
            "plain_ja": "100回使っても税込約330円です。",
            "plain_en": "100 billable calls are about JPY 330 including tax.",
        },
        {
            "billable_units": 1000,
            "estimated_jpy_tax_included": 3300,
            "plain_ja": "1,000回使っても税込約3,300円です。",
            "plain_en": "1,000 billable calls are about JPY 3,300 including tax.",
        },
    ],
    "agent_explanation": (
        "It is safe to explain jpcite as a low-priced evidence lookup layer: "
        "ordinary paid calls are currently JPY 3 ex-tax / about JPY 3.30 "
        "including tax per billable unit, so even repeated evidence lookups "
        "are usually measured in tens or hundreds of yen before large batch "
        "or export workflows. Do not claim that external LLM billing always "
        "goes down; token/search savings are conditional on the caller's "
        "baseline and model settings."
    ),
    "cost_savings_guardrail": (
        "Only present jpcite as a token/context cost reducer when the response "
        "contains cost_savings_decision=supported_by_caller_baseline. Otherwise "
        "present the value as low-cost source-linked evidence prefetch."
    ),
}

_FREE_AGENT_PATHS: frozenset[str] = frozenset(
    {
        "/v1/cost/preview",
        "/v1/meta/freshness",
        "/v1/stats/coverage",
        "/v1/stats/freshness",
    }
)


def _collect_schema_refs(node: Any, refs: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            refs.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _collect_schema_refs(value, refs)
    elif isinstance(node, list):
        for item in node:
            _collect_schema_refs(item, refs)


def _prune_components(schema: dict[str, Any]) -> None:
    components = schema.get("components")
    if not isinstance(components, dict):
        return
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return

    needed: set[str] = set()
    _collect_schema_refs(schema.get("paths") or {}, needed)
    expanded: set[str] = set()
    while needed - expanded:
        name = (needed - expanded).pop()
        expanded.add(name)
        component = schemas.get(name)
        if component is not None:
            _collect_schema_refs(component, needed)
    components["schemas"] = {
        name: deepcopy(schemas[name]) for name in sorted(expanded) if name in schemas
    }
    if not components["schemas"]:
        components.pop("schemas", None)


def build_agent_openapi_schema(full_schema: dict[str, Any]) -> dict[str, Any]:
    """Return a reduced OpenAPI schema for LLM action importers."""
    schema = deepcopy(full_schema)
    all_paths = schema.get("paths") or {}
    schema["paths"] = {
        path: deepcopy(all_paths[path]) for path in AGENT_SAFE_PATHS if path in all_paths
    }
    schema["security"] = []
    info = schema.setdefault("info", {})
    info["title"] = "jpcite Agent Evidence API"
    info["description"] = (
        "Agent-safe OpenAPI subset for evidence prefetch before answer "
        "generation. jpcite returns source-linked facts, source_url, "
        "fetched timestamps, known gaps, and compatibility rules; it does not "
        "call external LLM APIs and does not generate final legal/tax advice. "
        "Optional token/context fields are input-context estimates based on "
        "caller-supplied baselines, not provider billing guarantees. This spec "
        "excludes billing, webhook, OAuth, account-management, and operator "
        "endpoints. Anonymous callers can evaluate within the published daily "
        "limit unless an operation marks X-API-Key as required; callers that "
        "need higher volume send X-API-Key."
    )
    info["x-jpcite-pricing"] = deepcopy(_AGENT_PRICING_METADATA)
    for path, path_item in schema["paths"].items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
                "trace",
            }:
                continue
            if not isinstance(operation, dict):
                continue
            auth_required = path == "/v1/citations/verify"
            operation_id = _AGENT_OPERATION_IDS.get((method.lower(), path))
            if operation_id:
                operation["operationId"] = operation_id
            operation["security"] = (
                [{"ApiKeyAuth": []}] if auth_required else [{"ApiKeyAuth": []}, {}]
            )
            operation["x-jpcite-agent-safe"] = True
            operation["x-jpcite-auth"] = (
                "required_x_api_key" if auth_required else "optional_x_api_key_for_paid_volume"
            )
            if path in _FREE_AGENT_PATHS:
                operation["x-jpcite-billing"] = {
                    "billable": False,
                    "billing_units": 0,
                    "plain_ja": "このエンドポイントは料金確認・透明性確認用で、通常の課金対象外です。",
                    "plain_en": (
                        "This endpoint is for cost preview or transparency checks "
                        "and is not normally metered."
                    ),
                }
            else:
                operation["x-jpcite-billing"] = {
                    "billable": True,
                    "billing_units_per_successful_call": 1,
                    "unit_price_jpy_ex_tax": 3,
                    "unit_price_jpy_tax_included": 3.3,
                    "plain_ja": (
                        "通常の有料利用では成功した1呼び出しあたり1 unit、"
                        "税別3円・税込約3.30円です。失敗リクエストは課金対象外です。"
                    ),
                    "plain_en": (
                        "In ordinary paid use, a successful call is 1 unit: "
                        "JPY 3 ex-tax / about JPY 3.30 including tax. Failed "
                        "requests are not billed."
                    ),
                }
            responses = operation.get("responses")
            if isinstance(responses, dict):
                auth_response = responses.get("401")
                if isinstance(auth_response, dict):
                    if auth_required:
                        auth_response["description"] = "Authentication required. Send X-API-Key."
                    else:
                        auth_response["description"] = (
                            "Invalid authentication — returned only when an API "
                            "key is supplied but invalid. Anonymous callers may "
                            "use the published daily limit; quota exhaustion "
                            "returns 429."
                        )
            priority = _AGENT_PRIORITIES.get(path)
            if priority:
                operation["x-jpcite-agent-priority"] = priority[0]
                operation["x-jpcite-route-purpose"] = priority[1]
            operation.setdefault("tags", ["agent-evidence"])
    _prune_components(schema)
    return schema


__all__ = ["AGENT_SAFE_PATHS", "build_agent_openapi_schema"]
