"""Agent-safe OpenAPI projection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

AGENT_SAFE_PATHS: tuple[str, ...] = (
    "/v1/evidence/packets/query",
    "/v1/intelligence/precomputed/query",
    "/v1/programs/search",
    "/v1/programs/{unified_id}",
    "/v1/programs/batch",
    "/v1/source_manifest/{program_id}",
    "/v1/meta/freshness",
    "/v1/citations/verify",
    "/v1/cost/preview",
)


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
        "published daily limit; callers that need higher volume send X-API-Key."
    )
    for path_item in schema["paths"].values():
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
            operation["security"] = [{"ApiKeyAuth": []}, {}]
            operation["x-jpcite-agent-safe"] = True
            operation["x-jpcite-auth"] = "optional_x_api_key_for_paid_volume"
            operation.setdefault("tags", ["agent-evidence"])
    return schema


__all__ = ["AGENT_SAFE_PATHS", "build_agent_openapi_schema"]
