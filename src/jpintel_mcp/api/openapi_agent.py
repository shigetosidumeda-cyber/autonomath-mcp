"""Agent-safe OpenAPI projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

AGENT_SAFE_PATHS: tuple[str, ...] = (
    "/v1/intelligence/precomputed/query",
    "/v1/evidence/packets/query",
    "/v1/programs/search",
    "/v1/programs/{unified_id}",
    "/v1/programs/batch",
    "/v1/source_manifest/{program_id}",
    "/v1/meta/freshness",
    "/v1/citations/verify",
    "/v1/cost/preview",
)

_AGENT_PRIORITIES: dict[str, tuple[int, str]] = {
    "/v1/intelligence/precomputed/query": (1, "compact_first_pass"),
    "/v1/evidence/packets/query": (2, "source_linked_evidence_packet"),
    "/v1/citations/verify": (3, "optional_citation_check"),
}


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
        name: deepcopy(schemas[name])
        for name in sorted(expanded)
        if name in schemas
    }
    if not components["schemas"]:
        components.pop("schemas", None)


def build_agent_openapi_schema(full_schema: dict[str, Any]) -> dict[str, Any]:
    """Return a reduced OpenAPI schema for LLM action importers."""
    schema = deepcopy(full_schema)
    all_paths = schema.get("paths") or {}
    schema["paths"] = {
        path: deepcopy(all_paths[path])
        for path in AGENT_SAFE_PATHS
        if path in all_paths
    }
    schema["security"] = []
    info = schema.setdefault("info", {})
    info["title"] = "jpcite Agent Evidence API"
    info["description"] = (
        "Agent-safe OpenAPI subset for evidence prefetch before answer "
        "generation. It excludes billing, webhook, OAuth, account-management, "
        "and operator endpoints. Anonymous callers can evaluate within the "
        "published daily limit unless an operation marks X-API-Key as required; "
        "callers that need higher volume send X-API-Key."
    )
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
            operation["security"] = [{"ApiKeyAuth": []}] if auth_required else [{"ApiKeyAuth": []}, {}]
            operation["x-jpcite-agent-safe"] = True
            operation["x-jpcite-auth"] = (
                "required_x_api_key"
                if auth_required
                else "optional_x_api_key_for_paid_volume"
            )
            responses = operation.get("responses")
            if isinstance(responses, dict):
                auth_response = responses.get("401")
                if isinstance(auth_response, dict):
                    if auth_required:
                        auth_response["description"] = (
                            "Authentication required. Send X-API-Key."
                        )
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
