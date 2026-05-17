#!/usr/bin/env python3
"""FF2 OpenAPI `x-cost-saving` extension injector.

Adds an `x-cost-saving` extension to every endpoint operation across the
public OpenAPI surfaces. Tier classification mirrors the MCP injector
(`scripts/ff2_embed_cost_saving_footer.py`) and the numbers come from
the FF1 SOT (`docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md` §3).

Targets (each is a self-contained OpenAPI 3.x JSON):
    site/openapi.agent.json
    site/openapi.agent.gpt30.json
    site/openapi/v1.json
    site/openapi/agent.json
    site/docs/openapi/v1.json
    site/docs/openapi/agent.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    "site/openapi.agent.json",
    "site/openapi.agent.gpt30.json",
    "site/openapi/v1.json",
    "site/openapi/agent.json",
    "site/docs/openapi/v1.json",
    "site/docs/openapi/agent.json",
]

# Mirror tier numbers exactly with SOT §3.
TIERS: dict[str, dict[str, float | int | str]] = {
    "A": {
        "yen": 3,
        "opus_turns": 3,
        "opus_yen": 54,
        "saving_pct": 94.4,
        "saving_yen": 51,
    },
    "B": {
        "yen": 6,
        "opus_turns": 5,
        "opus_yen": 170,
        "saving_pct": 96.5,
        "saving_yen": 164,
    },
    "C": {
        "yen": 12,
        "opus_turns": 7,
        "opus_yen": 347,
        "saving_pct": 96.5,
        "saving_yen": 335,
    },
    "D": {
        "yen": 30,
        "opus_turns": 7,
        "opus_yen": 500,
        "saving_pct": 94.0,
        "saving_yen": 470,
    },
}

VERIFIABLE_DOC = "docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md"

METHODS = {"get", "post", "put", "patch", "delete"}


def classify_path_tier(path: str, op: dict[str, Any]) -> str:
    """Map an OpenAPI path/operation to a tier label."""
    p = path.lower()
    op_id = (op.get("operationId") or "").lower()
    # Tier D — full evidence packets, portfolio analysis, regulatory chain
    if (
        "evidence/packets/full" in p
        or "portfolio_analysis" in p
        or "regulatory_impact_chain" in p
        or "evidence_packet_full" in op_id
        or "portfolio_analysis" in op_id
    ):
        return "D"
    # Tier C — precomputed answers, agent briefings, cohort, evidence packets,
    # facade (route / preview / execute), audit pack, advisors match.
    if (
        "precomputed" in p
        or "agent_briefing" in p
        or "cohort" in p
        or "/v1/evidence/packets" in p
        or "/v1/jpcite/" in p
        or "/v1/artifacts/" in p
        or "advisors/match" in p
        or "audit_pack" in p
    ):
        return "C"
    # Tier B — semantic, expand, batch_get, with_relations, v2, prescreen
    if (
        re.search(r"/v2(/|$)", p)
        or "semantic" in p
        or "expand" in p
        or "with_relations" in p
        or "batch_get" in p
        or "prescreen" in p
        or "match_" in op_id
        or "cohort_match" in p
    ):
        return "B"
    # Tier A — search, list, simple get, enum, count
    return "A"


def build_extension(tier: str) -> dict[str, Any]:
    t = TIERS[tier]
    return {
        "tier": tier,
        "jpcite_yen": t["yen"],
        "opus_4_7_equivalent_turns": t["opus_turns"],
        "opus_yen_estimate": t["opus_yen"],
        "saving_pct": t["saving_pct"],
        "saving_yen": t["saving_yen"],
        "baseline": "Claude Opus 4.7 multi-turn evidence chain",
        "verifiable_doc": VERIFIABLE_DOC,
    }


def process_file(path: Path, check_only: bool) -> tuple[int, int, dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    paths = data.get("paths", {})
    total_ops = 0
    changed = 0
    tier_dist: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
    for p, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for m, op in methods.items():
            if m.lower() not in METHODS or not isinstance(op, dict):
                continue
            total_ops += 1
            tier = classify_path_tier(p, op)
            ext = build_extension(tier)
            prev = op.get("x-cost-saving")
            if prev != ext:
                op["x-cost-saving"] = ext
                changed += 1
            tier_dist[tier] += 1
    if not check_only and changed:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return total_ops, changed, tier_dist


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    total_ops = 0
    total_changed = 0
    aggregate: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            print(f"SKIP (missing): {rel}", file=sys.stderr)
            continue
        n, c, dist = process_file(p, check_only=args.check)
        for k, v in dist.items():
            aggregate[k] += v
        total_ops += n
        total_changed += c
        print(f"  {rel}: ops={n} changed={c} tier_dist={dist}")
    print(f"TOTAL ops={total_ops} changed={total_changed} aggregate_tier_dist={aggregate}")
    if args.check and total_changed:
        print("DRIFT (run without --check to fix).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
