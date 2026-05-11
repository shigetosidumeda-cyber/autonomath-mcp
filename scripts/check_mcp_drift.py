#!/usr/bin/env python3
# ruff: noqa: SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017
"""check_mcp_drift: assert tools count in MCP manifests vs facts_registry mcp_tools range."""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"

TARGETS = [
    "site/.well-known/mcp.json",
    "site/mcp-server.json",
]


def _tool_count(spec: dict) -> int | None:
    for key in ("tools", "tool_count"):
        if key in spec:
            v = spec[key]
            if isinstance(v, list):
                return len(v)
            if isinstance(v, int):
                return v
    pricing = spec.get("pricing") or {}
    if isinstance(pricing.get("tool_count"), int):
        return pricing["tool_count"]
    return None


def main() -> int:
    reg = json.loads(REGISTRY.read_text("utf-8"))
    lo, hi = reg["guards"]["numeric_ranges"]["mcp_tools"]
    fails: list[str] = []

    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            print(f"SKIP {rel} (not present)")
            continue
        try:
            spec = json.loads(p.read_text("utf-8"))
        except Exception as e:
            fails.append(f"{rel}: parse error {e}")
            continue
        n = _tool_count(spec)
        if n is None:
            print(f"SKIP {rel} (no tools / tool_count key)")
            continue
        if not lo <= n <= hi:
            fails.append(f"{rel}: tools={n} not in [{lo},{hi}]")
        else:
            print(f"OK {rel}: tools={n} in [{lo},{hi}]")

    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("OK: mcp tool count within registry range")
    return 0


if __name__ == "__main__":
    sys.exit(main())
