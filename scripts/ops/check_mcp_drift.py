#!/usr/bin/env python3
"""Detect MCP tool_count drift across discovery surfaces.

Ground-truth source: ``server.json`` ``_meta.io.modelcontextprotocol.registry/
publisher-provided.tool_count`` is the manifest pin. Every other discovery
surface (agents.json, trust.json, jpcite-federation.json, dxt/manifest.json,
mcp-server.json, mcp-server.full.json, llms-full.txt, llms-full.en.txt,
) must align with this single number.

Agent entry shims such as ``CLAUDE.md`` intentionally do not hardcode volatile
counts; they point at ``AGENTS.md`` / ``scripts/distribution_manifest.yml``.

This script is read-only. Use ``sync_mcp_counts.py`` to apply fixes.

Exit codes:
- 0: no drift
- 1: drift detected (printed to stdout)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CountSite:
    """One discovery surface that pins or echoes the manifest tool_count."""

    label: str
    path: Path
    values: list[int] = field(default_factory=list)
    error: str | None = None


def _load_server_json_count() -> int:
    """Read the ground-truth ``tool_count`` from ``server.json``."""
    raw = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
    meta = raw.get("_meta", {})
    publisher = meta.get("io.modelcontextprotocol.registry/publisher-provided", {})
    value = publisher.get("tool_count")
    if not isinstance(value, int):
        raise SystemExit("server.json: publisher-provided.tool_count missing or not int")
    return value


def _json_path_value(data: object, dotted: str) -> object | None:
    """Walk a JSON document by a dotted/slashed path."""
    cur: object = data
    for raw in dotted.split("."):
        key = raw.replace("__SLASH__", "/")
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _collect_json_counts(path: Path, dotted_keys: list[str]) -> CountSite:
    site = CountSite(label=str(path.relative_to(REPO_ROOT)), path=path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        site.error = "file_not_found"
        return site
    except json.JSONDecodeError as exc:
        site.error = f"json_error: {exc}"
        return site
    for dotted in dotted_keys:
        v = _json_path_value(data, dotted)
        if isinstance(v, int):
            site.values.append(v)
    return site


def _collect_text_counts(path: Path, patterns: list[str]) -> CountSite:
    site = CountSite(label=str(path.relative_to(REPO_ROOT)), path=path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        site.error = "file_not_found"
        return site
    for pat in patterns:
        for m in re.finditer(pat, text):
            try:
                site.values.append(int(m.group(1)))
            except (IndexError, ValueError):
                continue
    return site


# Sites that must be exactly == server.json tool_count.
JSON_SITES: list[tuple[Path, list[str]]] = [
    (
        REPO_ROOT / "site/.well-known/agents.json",
        ["tools_count.public_default", "tools_count.runtime_verified"],
    ),
    (REPO_ROOT / "site/.well-known/trust.json", ["ai_use.tool_count_default_gates"]),
    (
        REPO_ROOT / "site/.well-known/jpcite-federation.json",
        ["capabilities.tool_count_runtime", "capabilities.tool_count_manifest"],
    ),
    (
        REPO_ROOT / "mcp-server.json",
        [
            "_meta.io__SLASH__modelcontextprotocol.registry__SLASH__publisher-provided.tool_count",
            "_meta.tool_count",
        ],
    ),
    (
        REPO_ROOT / "mcp-server.full.json",
        [
            "_meta.io__SLASH__modelcontextprotocol.registry__SLASH__publisher-provided.tool_count",
            "_meta.tool_count",
        ],
    ),
    (
        REPO_ROOT / "dxt/manifest.json",
        [
            "_meta.io__SLASH__modelcontextprotocol.registry__SLASH__publisher-provided.tool_count",
            "_meta.tool_count",
        ],
    ),
]

# Text sites: regex that must match the same count.
TEXT_SITES: list[tuple[Path, list[str]]] = [
    (REPO_ROOT / "site/llms-full.txt", [r"MCP\s*\(\s*(\d+)\s+tools"]),
    (REPO_ROOT / "site/llms-full.en.txt", [r"MCP exposes\s+(\d+)\s+tools"]),
]


def collect_all_sites() -> list[CountSite]:
    sites: list[CountSite] = []
    for path, keys in JSON_SITES:
        sites.append(_collect_json_counts(path, keys))
    for path, patterns in TEXT_SITES:
        sites.append(_collect_text_counts(path, patterns))
    return sites


def detect_drift(ground_truth: int, sites: list[CountSite]) -> list[str]:
    drift: list[str] = []
    for site in sites:
        if site.error:
            drift.append(f"  {site.label}: {site.error}")
            continue
        if not site.values:
            drift.append(f"  {site.label}: no count found (selector mismatch)")
            continue
        bad = [v for v in site.values if v != ground_truth]
        if bad:
            drift.append(f"  {site.label}: found {site.values} (expected {ground_truth})")
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)

    gt = _load_server_json_count()
    sites = collect_all_sites()
    drift = detect_drift(gt, sites)

    if args.json:
        payload = {
            "ground_truth": gt,
            "sites": [{"label": s.label, "values": s.values, "error": s.error} for s in sites],
            "drift": drift,
            "drift_count": len(drift),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if not drift else 1

    print(f"ground_truth (server.json tool_count): {gt}")
    print(f"sites probed: {len(sites)}")
    for s in sites:
        if s.error:
            tag = "ERR"
        elif not s.values:
            tag = "MISS"
        elif all(v == gt for v in s.values):
            tag = "OK"
        else:
            tag = "DRIFT"
        print(f"  [{tag:5}] {s.label}: {s.values or '(none)'}")
    if drift:
        print()
        print(f"DRIFT DETECTED ({len(drift)} site(s)):")
        for line in drift:
            print(line)
        return 1
    print()
    print("NO DRIFT.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
