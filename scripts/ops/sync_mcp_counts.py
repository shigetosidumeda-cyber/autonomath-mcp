#!/usr/bin/env python3
"""Sync MCP tool_count across discovery surfaces from server.json SOT.

Ground truth: ``server.json`` ``_meta.io.modelcontextprotocol.registry/
publisher-provided.tool_count``. This script writes that count back into the
sibling discovery surfaces (agents.json, trust.json, jpcite-federation.json,
mcp-server.json, mcp-server.full.json, dxt/manifest.json, llms-full.{txt,en}).

The script DOES NOT modify ``server.json`` itself — that file is the SOT and
manifest bumps must be intentional. It also DOES NOT modify CLAUDE.md, where
historical strings are retained as state markers per the SOT note in that
file (lines 11 and 51). Drift in CLAUDE.md is reported but not auto-rewritten.

Run with ``--dry-run`` to preview the diff. Run with ``--apply`` to write.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_ground_truth() -> int:
    raw = json.loads((REPO_ROOT / "server.json").read_text(encoding="utf-8"))
    meta = raw.get("_meta", {})
    publisher = meta.get("io.modelcontextprotocol.registry/publisher-provided", {})
    value = publisher.get("tool_count")
    if not isinstance(value, int):
        raise SystemExit("server.json: publisher-provided.tool_count missing or not int")
    return value


def _set_dotted(data: object, dotted: str, value: int) -> bool:
    """Set a JSON path, returning True iff the value changed."""
    parts = [p.replace("__SLASH__", "/") for p in dotted.split(".")]
    cur = data
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    if not isinstance(cur, dict):
        return False
    last = parts[-1]
    if last not in cur:
        return False
    if cur[last] == value:
        return False
    cur[last] = value
    return True


def _patch_json(path: Path, dotted_keys: list[str], value: int) -> list[str]:
    """Patch a JSON document in place, returning diff descriptions."""
    if not path.exists():
        return [f"{path.relative_to(REPO_ROOT)}: SKIP (missing)"]
    data = json.loads(path.read_text(encoding="utf-8"))
    changes: list[str] = []
    for dotted in dotted_keys:
        if _set_dotted(data, dotted, value):
            changes.append(f"{path.relative_to(REPO_ROOT)}: set {dotted} = {value}")
    if changes:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changes


def _patch_text(path: Path, patterns: list[tuple[str, str]]) -> list[str]:
    """Patch text-based discovery files via regex replacement."""
    if not path.exists():
        return [f"{path.relative_to(REPO_ROOT)}: SKIP (missing)"]
    text = path.read_text(encoding="utf-8")
    changes: list[str] = []
    new_text = text
    for pat, repl in patterns:
        replaced, n = re.subn(pat, repl, new_text)
        if n:
            changes.append(f"{path.relative_to(REPO_ROOT)}: {pat!r} replaced ({n} site(s))")
            new_text = replaced
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return changes


def _dry_patch_json(path: Path, dotted_keys: list[str], value: int) -> list[str]:
    if not path.exists():
        return [f"  {path.relative_to(REPO_ROOT)}: SKIP (missing)"]
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[str] = []
    for dotted in dotted_keys:
        cur = data
        parts = [p.replace("__SLASH__", "/") for p in dotted.split(".")]
        ok = True
        for p in parts[:-1]:
            if not isinstance(cur, dict) or p not in cur:
                ok = False
                break
            cur = cur[p]
        if not ok or not isinstance(cur, dict) or parts[-1] not in cur:
            continue
        old = cur[parts[-1]]
        if old != value:
            out.append(f"  {path.relative_to(REPO_ROOT)}: {dotted}: {old} -> {value}")
    return out


def _dry_patch_text(path: Path, patterns: list[tuple[str, str]]) -> list[str]:
    if not path.exists():
        return [f"  {path.relative_to(REPO_ROOT)}: SKIP (missing)"]
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for pat, repl in patterns:
        for m in re.finditer(pat, text):
            old = m.group(0)
            new = re.sub(pat, repl, old)
            if old != new:
                out.append(f"  {path.relative_to(REPO_ROOT)}: {old!r} -> {new!r}")
    return out


def build_targets(
    gt: int,
) -> tuple[list[tuple[Path, list[str]]], list[tuple[Path, list[tuple[str, str]]]]]:
    json_targets: list[tuple[Path, list[str]]] = [
        (
            REPO_ROOT / "site/.well-known/agents.json",
            ["tools_count.public_default", "tools_count.runtime_verified"],
        ),
        (
            REPO_ROOT / "site/.well-known/trust.json",
            ["ai_use.tool_count_default_gates"],
        ),
        (
            REPO_ROOT / "site/.well-known/jpcite-federation.json",
            [
                "capabilities.tool_count_runtime",
                "capabilities.tool_count_manifest",
            ],
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
    text_targets: list[tuple[Path, list[tuple[str, str]]]] = [
        (
            REPO_ROOT / "site/llms-full.txt",
            [(r"MCP\s*\((\d+)\s+tools", f"MCP ({gt} tools")],
        ),
        (
            REPO_ROOT / "site/llms-full.en.txt",
            [(r"MCP exposes\s+(\d+)\s+tools", f"MCP exposes {gt} tools")],
        ),
    ]
    return json_targets, text_targets


def _check_claudemd_drift(gt: int) -> list[str]:
    """Read-only report on CLAUDE.md drift (historical strings retained)."""
    path = REPO_ROOT / "CLAUDE.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for m in re.finditer(r"\*\*(\d+)\s+tools\*\*", text):
        n = int(m.group(1))
        if n != gt:
            line_no = text[: m.start()].count("\n") + 1
            out.append(
                f"  CLAUDE.md:{line_no}: '**{n} tools**' (expected {gt}) "
                f"-- historical marker, NOT auto-rewritten"
            )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="show diff only")
    parser.add_argument("--apply", action="store_true", help="write changes")
    args = parser.parse_args(argv)

    if args.dry_run == args.apply:
        print("usage: pass exactly one of --dry-run or --apply", file=sys.stderr)
        return 2

    gt = _load_ground_truth()
    print(f"server.json ground_truth tool_count = {gt}")
    json_targets, text_targets = build_targets(gt)

    if args.dry_run:
        print()
        print("--- proposed JSON changes ---")
        for path, keys in json_targets:
            for line in _dry_patch_json(path, keys, gt):
                print(line)
        print("--- proposed text changes ---")
        for path, patterns in text_targets:
            for line in _dry_patch_text(path, patterns):
                print(line)
        print()
        print("--- CLAUDE.md historical drift (NOT auto-rewritten) ---")
        for line in _check_claudemd_drift(gt):
            print(line)
        return 0

    all_changes: list[str] = []
    for path, keys in json_targets:
        all_changes.extend(_patch_json(path, keys, gt))
    for path, patterns in text_targets:
        all_changes.extend(_patch_text(path, patterns))

    if all_changes:
        print()
        print("--- applied changes ---")
        for line in all_changes:
            print(line)
    else:
        print()
        print("no changes needed (all sites already aligned)")

    print()
    print("--- CLAUDE.md historical drift (NOT auto-rewritten) ---")
    for line in _check_claudemd_drift(gt):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
