#!/usr/bin/env python3
"""Verify P0 facade discovery consistency across 5 surfaces.

The 4 P0 facade tools — `jpcite_route`, `jpcite_preview_cost`,
`jpcite_execute_packet`, `jpcite_get_packet` — must be present and consistent
across:

  1. REST OpenAPI agent spec (site/openapi.agent.json + slim
     site/openapi.agent.gpt30.json) with REST endpoint, summary,
     operationId, x-mcp-tool extension, requestBody schema, and response
     schema.
  2. MCP tool manifest (site/mcp-server.json — the user-facing tool list;
     site/server.json is the MCP registry stub and does NOT contain tool
     names).
  3. .well-known/agents.json with `tools.recommended_first[].name`.
  4. .well-known/llms.json with `tools.recommended_first[].name`.
  5. llms.txt narrative with a `## P0 Facade` section that lists all 4 tool
     names.

This script is deterministic, does NOT call any LLM, and exits non-zero on
any inconsistency. Run after editing any of the 5 surfaces.

Usage:
  python scripts/ops/check_p0_facade_discovery_consistency.py
  python scripts/ops/check_p0_facade_discovery_consistency.py --site-root site
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

P0_FACADE_TOOLS: tuple[str, ...] = (
    "jpcite_route",
    "jpcite_preview_cost",
    "jpcite_execute_packet",
    "jpcite_get_packet",
)

P0_FACADE_REST_ENDPOINTS: dict[str, tuple[str, str]] = {
    "jpcite_route": ("POST", "/v1/jpcite/route"),
    "jpcite_preview_cost": ("POST", "/v1/jpcite/preview_cost"),
    "jpcite_execute_packet": ("POST", "/v1/jpcite/execute_packet"),
    "jpcite_get_packet": ("GET", "/v1/jpcite/get_packet/{packet_id}"),
}


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _check_openapi(
    spec_path: Path,
    *,
    label: str,
    errors: list[str],
    require_x_mcp_tool: bool = True,
) -> None:
    if not spec_path.exists():
        errors.append(f"{label}: file missing — {spec_path}")
        return
    spec = _load_json(spec_path)
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        errors.append(f"{label}: paths is not a dict")
        return

    for tool_name in P0_FACADE_TOOLS:
        method, route = P0_FACADE_REST_ENDPOINTS[tool_name]
        entry = paths.get(route)
        if entry is None:
            errors.append(f"{label}: missing path {route} for tool {tool_name}")
            continue
        operation = entry.get(method.lower()) if isinstance(entry, dict) else None
        if operation is None:
            errors.append(f"{label}: path {route} missing {method} operation for {tool_name}")
            continue
        if not operation.get("summary"):
            errors.append(f"{label}: {route} {method} missing summary")
        if not operation.get("operationId"):
            errors.append(f"{label}: {route} {method} missing operationId")
        if require_x_mcp_tool:
            x_mcp = operation.get("x-mcp-tool") or {}
            if not isinstance(x_mcp, dict) or x_mcp.get("name") != tool_name:
                errors.append(
                    f"{label}: {route} {method} x-mcp-tool.name "
                    f"!= {tool_name} (got {x_mcp.get('name') if isinstance(x_mcp, dict) else x_mcp!r})"
                )
            if x_mcp.get("facade_tier") != "P0":
                errors.append(
                    f"{label}: {route} {method} x-mcp-tool.facade_tier != P0 for {tool_name}"
                )
        # POST endpoints must declare requestBody; GET endpoints must declare path param.
        if method == "POST":
            req_body = operation.get("requestBody") or {}
            if not isinstance(req_body, dict) or not req_body.get("content"):
                errors.append(f"{label}: {route} POST missing requestBody.content for {tool_name}")
        else:
            params = operation.get("parameters") or []
            param_names = {p.get("name") for p in params if isinstance(p, dict)}
            if "packet_id" not in param_names:
                errors.append(f"{label}: {route} GET missing packet_id path parameter")
        responses = operation.get("responses") or {}
        if not isinstance(responses, dict) or not responses:
            errors.append(f"{label}: {route} {method} missing responses")


def _check_mcp_manifest(path: Path, *, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"mcp-server.json: file missing — {path}")
        return
    manifest = _load_json(path)
    tools = manifest.get("tools")
    if not isinstance(tools, list):
        errors.append("mcp-server.json: tools is not a list")
        return
    names = {t.get("name") for t in tools if isinstance(t, dict)}
    for tool_name in P0_FACADE_TOOLS:
        if tool_name not in names:
            errors.append(f"mcp-server.json: missing tool {tool_name}")


def _check_recommended_first(path: Path, *, label: str, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"{label}: file missing — {path}")
        return
    data = _load_json(path)
    tools = data.get("tools") or {}
    if not isinstance(tools, dict):
        errors.append(f"{label}: 'tools' is not an object")
        return
    rec = tools.get("recommended_first")
    if not isinstance(rec, list):
        errors.append(f"{label}: tools.recommended_first is not a list")
        return
    rec_names = {t.get("name") for t in rec if isinstance(t, dict)}
    for tool_name in P0_FACADE_TOOLS:
        if tool_name not in rec_names:
            errors.append(f"{label}: {tool_name} not present in tools.recommended_first")
    # Validate per-tool fields
    by_name = {t.get("name"): t for t in rec if isinstance(t, dict)}
    for tool_name in P0_FACADE_TOOLS:
        entry = by_name.get(tool_name)
        if entry is None:
            continue
        if entry.get("facade_tier") != "P0":
            errors.append(
                f"{label}: {tool_name} facade_tier != P0 (got {entry.get('facade_tier')!r})"
            )
        expected_method, expected_route = P0_FACADE_REST_ENDPOINTS[tool_name]
        if entry.get("rest_endpoint") != expected_route:
            errors.append(
                f"{label}: {tool_name} rest_endpoint mismatch "
                f"(expected {expected_route}, got {entry.get('rest_endpoint')!r})"
            )
        if entry.get("method") != expected_method:
            errors.append(
                f"{label}: {tool_name} method mismatch "
                f"(expected {expected_method}, got {entry.get('method')!r})"
            )
        if entry.get("request_time_llm_call_performed") is not False:
            errors.append(f"{label}: {tool_name} request_time_llm_call_performed must be false")


def _check_llms_txt(path: Path, *, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"llms.txt: file missing — {path}")
        return
    text = path.read_text(encoding="utf-8")
    if "## P0 Facade" not in text:
        errors.append("llms.txt: missing '## P0 Facade' section header")
    for tool_name in P0_FACADE_TOOLS:
        if tool_name not in text:
            errors.append(f"llms.txt: missing tool name reference {tool_name}")
    if "outcome_catalog" not in text:
        errors.append(
            "llms.txt: P0 Facade section should link the outcome_catalog "
            "(release catalog reference)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site-root",
        default="site",
        help="Path to the site/ directory (default: site)",
    )
    args = parser.parse_args()

    site_root = Path(args.site_root).resolve()
    if not site_root.is_dir():
        print(
            f"ERROR: --site-root not a directory: {site_root}",
            file=sys.stderr,
        )
        return 2

    errors: list[str] = []

    _check_openapi(
        site_root / "openapi.agent.json",
        label="openapi.agent.json",
        errors=errors,
    )
    _check_openapi(
        site_root / "openapi.agent.gpt30.json",
        label="openapi.agent.gpt30.json",
        errors=errors,
    )
    _check_mcp_manifest(site_root / "mcp-server.json", errors=errors)
    _check_recommended_first(
        site_root / ".well-known" / "agents.json",
        label=".well-known/agents.json",
        errors=errors,
    )
    _check_recommended_first(
        site_root / ".well-known" / "llms.json",
        label=".well-known/llms.json",
        errors=errors,
    )
    _check_llms_txt(site_root / "llms.txt", errors=errors)

    summary = {
        "p0_facade_tools": list(P0_FACADE_TOOLS),
        "rest_endpoints": {name: list(P0_FACADE_REST_ENDPOINTS[name]) for name in P0_FACADE_TOOLS},
        "surfaces_checked": [
            str(site_root / "openapi.agent.json"),
            str(site_root / "openapi.agent.gpt30.json"),
            str(site_root / "mcp-server.json"),
            str(site_root / ".well-known" / "agents.json"),
            str(site_root / ".well-known" / "llms.json"),
            str(site_root / "llms.txt"),
        ],
        "errors": errors,
        "ok": not errors,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
