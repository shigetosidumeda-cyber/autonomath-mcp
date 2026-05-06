#!/usr/bin/env python3
"""Compare DXT and registry MCP manifests beyond file-level drift.

The existing distribution drift checker validates the broad distribution
surface. This script focuses on the high-value agent-first surface: tool names,
tool descriptions, resource metadata, and version text across DXT and registry
manifests. It is read-only and writes a markdown report by default.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DXT = REPO_ROOT / "dxt" / "manifest.json"
DEFAULT_REGISTRY = REPO_ROOT / "mcp-server.full.json"
DEFAULT_OUT = REPO_ROOT / "docs" / "_internal" / "mcp_manifest_deep_diff_latest.md"
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class ToolDiff:
    name: str
    kind: str
    dxt_description: str
    registry_description: str


@dataclass(frozen=True)
class ManifestDiff:
    dxt_tool_count: int
    registry_tool_count: int
    description_diffs: list[ToolDiff]
    missing_in_dxt: list[str]
    missing_in_registry: list[str]
    dxt_version: str
    registry_version: str
    dxt_resource_count: int
    registry_resource_count: int


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _tool_descriptions(data: dict[str, Any]) -> dict[str, str]:
    tools = data.get("tools")
    if not isinstance(tools, list):
        return {}
    result: dict[str, str] = {}
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            continue
        description = tool.get("description")
        result[name] = description if isinstance(description, str) else ""
    return result


def compare_manifests(
    dxt_path: Path = DEFAULT_DXT, registry_path: Path = DEFAULT_REGISTRY
) -> ManifestDiff:
    dxt = _load_json(dxt_path)
    registry = _load_json(registry_path)
    dxt_tools = _tool_descriptions(dxt)
    registry_tools = _tool_descriptions(registry)

    dxt_names = set(dxt_tools)
    registry_names = set(registry_tools)
    shared = sorted(dxt_names & registry_names)
    description_diffs = [
        ToolDiff(
            name=name,
            kind="description_mismatch",
            dxt_description=dxt_tools[name],
            registry_description=registry_tools[name],
        )
        for name in shared
        if dxt_tools[name] != registry_tools[name]
    ]

    dxt_resources = dxt.get("resources")
    registry_resources = registry.get("resources")
    return ManifestDiff(
        dxt_tool_count=len(dxt_tools),
        registry_tool_count=len(registry_tools),
        description_diffs=description_diffs,
        missing_in_dxt=sorted(registry_names - dxt_names),
        missing_in_registry=sorted(dxt_names - registry_names),
        dxt_version=str(dxt.get("version", "")),
        registry_version=str(registry.get("version", "")),
        dxt_resource_count=len(dxt_resources) if isinstance(dxt_resources, list) else 0,
        registry_resource_count=len(registry_resources)
        if isinstance(registry_resources, list)
        else 0,
    )


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:220] if text.strip() else ""


def render_markdown(
    dxt_path: Path = DEFAULT_DXT,
    registry_path: Path = DEFAULT_REGISTRY,
) -> str:
    generated_at = datetime.now(UTC).astimezone(JST).isoformat(timespec="seconds")
    diff = compare_manifests(dxt_path, registry_path)
    has_hard_drift = bool(diff.missing_in_dxt or diff.missing_in_registry)
    has_soft_drift = bool(diff.description_diffs)

    lines = [
        "# MCP Manifest Deep Diff",
        "",
        f"- generated_at: `{generated_at}`",
        f"- dxt_manifest: `{dxt_path}`",
        f"- registry_manifest: `{registry_path}`",
        f"- dxt_tool_count: `{diff.dxt_tool_count}`",
        f"- registry_tool_count: `{diff.registry_tool_count}`",
        f"- dxt_version: `{diff.dxt_version}`",
        f"- registry_version: `{diff.registry_version}`",
        f"- dxt_resource_count: `{diff.dxt_resource_count}`",
        f"- registry_resource_count: `{diff.registry_resource_count}`",
        f"- hard_drift: `{str(has_hard_drift).lower()}`",
        f"- soft_description_drift: `{str(has_soft_drift).lower()}`",
        "",
        "## Interpretation",
        "",
        "- Hard drift means tool names are missing from one manifest.",
        "- Soft drift means the same tool exists but descriptions differ.",
        "- Description drift matters because agent routing depends on WHEN, WHEN NOT, CHAIN, LIMITATIONS, counts, and pricing language.",
        "- Resource drift may be intentional, but it should be explicit because DXT resources can teach Claude Desktop how to use the service.",
        "",
        "## Summary",
        "",
        "| item | count |",
        "|---|---:|",
        f"| missing_in_dxt | {len(diff.missing_in_dxt)} |",
        f"| missing_in_registry | {len(diff.missing_in_registry)} |",
        f"| description_mismatches | {len(diff.description_diffs)} |",
        "",
    ]

    if diff.missing_in_dxt:
        lines.extend(["## Missing In DXT", ""])
        lines.extend(f"- `{name}`" for name in diff.missing_in_dxt)
        lines.append("")

    if diff.missing_in_registry:
        lines.extend(["## Missing In Registry", ""])
        lines.extend(f"- `{name}`" for name in diff.missing_in_registry)
        lines.append("")

    lines.extend(
        [
            "## Description Mismatches",
            "",
            "| tool | dxt first line | registry first line |",
            "|---|---|---|",
        ]
    )
    for item in diff.description_diffs[:120]:
        lines.append(
            f"| `{item.name}` | {_first_line(item.dxt_description)} | "
            f"{_first_line(item.registry_description)} |"
        )
    overflow = len(diff.description_diffs) - 120
    if overflow > 0:
        lines.append(f"| ... | `{overflow}` more | |")

    lines.extend(
        [
            "",
            "## Recommended Gate",
            "",
            "1. Fail release on hard drift.",
            "2. Review soft drift when counts, pricing, free tier, tool limitations, or routing language differ.",
            "3. Keep DXT resource differences intentional and documented.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dxt", type=Path, default=DEFAULT_DXT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit non-zero on hard drift")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text = render_markdown(args.dxt, args.registry)
    if args.dry_run:
        print(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(args.out)

    diff = compare_manifests(args.dxt, args.registry)
    if args.strict and (diff.missing_in_dxt or diff.missing_in_registry):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
