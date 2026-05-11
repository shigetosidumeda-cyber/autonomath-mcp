#!/usr/bin/env python3
# ruff: noqa: SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017
"""check_openapi_drift: assert .paths length of OpenAPI specs vs facts_registry.

LLM 呼出ゼロ。Targets:
- site/openapi.agent.json -> openapi_paths_agent range
- site/openapi.agent.gpt30.json -> openapi_paths_agent range
- docs/openapi/v1.json -> openapi_paths_public range
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"

CHECKS = [
    ("site/openapi.agent.json", "openapi_paths_agent"),
    ("site/openapi.agent.gpt30.json", "openapi_paths_agent"),
    ("docs/openapi/v1.json", "openapi_paths_public"),
]


def main() -> int:
    reg = json.loads(REGISTRY.read_text("utf-8"))
    ranges = reg["guards"]["numeric_ranges"]
    fails: list[str] = []

    for rel, key in CHECKS:
        p = ROOT / rel
        if not p.exists():
            print(f"SKIP {rel} (not present)")
            continue
        try:
            spec = json.loads(p.read_text("utf-8"))
        except Exception as e:
            fails.append(f"{rel}: parse error {e}")
            continue
        n = len(spec.get("paths") or {})
        lo, hi = ranges[key]
        if not lo <= n <= hi:
            fails.append(f"{rel}: paths={n} not in [{lo},{hi}] ({key})")
        else:
            print(f"OK {rel}: paths={n} in [{lo},{hi}] ({key})")

    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("OK: openapi drift within registry ranges")
    return 0


if __name__ == "__main__":
    sys.exit(main())
