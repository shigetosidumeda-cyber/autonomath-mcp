#!/usr/bin/env python3
"""FF2 cost-saving footer injector.

Reads the FF1 SOT (`docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md`) for tier
parameters and embeds a uniform `Cost-saving claim` footer at the end of every
MCP tool description across the 4 server manifests.

Idempotent: if a description already contains the footer marker the previous
block is replaced (not duplicated). Run order:

    python scripts/ff2_embed_cost_saving_footer.py            # apply
    python scripts/ff2_embed_cost_saving_footer.py --check    # exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOT_DOC = "docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md"

# Tier table — must match SOT §3 exactly. Validator checks this.
TIERS: dict[str, dict[str, float | int | str]] = {
    "A": {
        "yen": 3,
        "opus_turns": 3,
        "opus_yen": 54,
        "saving_pct": 94.4,
        "saving_yen": 51,
        "section": "3",
        "label": "simple",
    },
    "B": {
        "yen": 6,
        "opus_turns": 5,
        "opus_yen": 170,
        "saving_pct": 96.5,
        "saving_yen": 164,
        "section": "3",
        "label": "medium",
    },
    "C": {
        "yen": 12,
        "opus_turns": 7,
        "opus_yen": 347,
        "saving_pct": 96.5,
        "saving_yen": 335,
        "section": "3",
        "label": "deep",
    },
    "D": {
        "yen": 30,
        "opus_turns": 7,
        "opus_yen": 500,
        "saving_pct": 94.0,
        "saving_yen": 470,
        "section": "3",
        "label": "deep+",
    },
}

FOOTER_BEGIN = "---\n**Cost-saving claim**:"
FOOTER_END_MARKER = "**Verifiable**: docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md"

MCP_MANIFESTS = [
    "mcp-server.json",
    "mcp-server.full.json",
    "mcp-server.core.json",
    "mcp-server.composition.json",
]


def classify_tier(name: str) -> str:
    """Map a tool name to a default tier per FF1 SOT §3."""
    # Tier D: deepest bundles
    if (
        "evidence_packet_full" in name
        or "portfolio_analysis" in name
        or "regulatory_impact_chain" in name
        or "he_1_full" in name.lower()
        or "he1_full" in name.lower()
    ):
        return "D"
    # Tier C: precomputed answers / agent briefings / cohort / HE-1 / HE-3
    if (
        "precomputed_answer" in name
        or "agent_briefing" in name
        or name.lower().startswith("he_1")
        or name.lower().startswith("he_3")
        or "cohort" in name
        or "regulatory_impact" in name
        or name.startswith("jpcite_route")
        or name.startswith("jpcite_preview_cost")
        or name.startswith("jpcite_execute_packet")
    ):
        return "C"
    # Tier B: search_v2_ / expand_ / get_with_relations / batch_get / semantic
    if re.match(
        r"^(search_v2_|expand_|get_with_relations_|batch_get_|semantic_|match_)",
        name,
    ):
        return "B"
    # Tier A: default (search_, list_, get_simple_, enum_, find_, check_, count_, get_)
    return "A"


def build_footer(tier: str) -> str:
    t = TIERS[tier]
    return (
        "\n\n---\n"
        f"**Cost-saving claim**: Equivalent to ~{t['opus_turns']}-turn "
        f"Claude Opus 4.7 reasoning (~¥{t['opus_yen']}). "
        f"This tool returns the precomputed/structured answer for "
        f"¥{t['yen']}/req (tier {tier}).\n"
        f"Saving: {t['saving_pct']}% / ¥{t['saving_yen']}/req vs raw Opus call.\n"
        f"**Verifiable**: docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md §{t['section']}\n"
    )


_FOOTER_RE = re.compile(
    r"\n*---\n\*\*Cost-saving claim\*\*:.*?docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17\.md §\d+\n?",
    re.DOTALL,
)


def strip_existing_footer(desc: str) -> str:
    return _FOOTER_RE.sub("", desc).rstrip() + "\n"


def inject_for_tool(tool: dict[str, object]) -> tuple[bool, str]:
    """Return (changed, tier) for the supplied tool, mutating tool['description']."""
    name = str(tool["name"])
    tier = classify_tier(name)
    desc_obj = tool.get("description", "")
    desc = str(desc_obj) if desc_obj is not None else ""
    stripped = strip_existing_footer(desc).rstrip()
    new_desc = stripped + build_footer(tier)
    changed = new_desc != desc
    tool["description"] = new_desc
    return changed, tier


def process_manifest(path: Path, check_only: bool) -> tuple[int, int, dict[str, int]]:
    """Returns (tool_count, changed_count, tier_distribution)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    tools = data.get("tools", [])
    changed = 0
    tier_dist: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
    for t in tools:
        was_changed, tier = inject_for_tool(t)
        tier_dist[tier] += 1
        if was_changed:
            changed += 1
    if not check_only and changed:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return len(tools), changed, tier_dist


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="non-zero exit on drift")
    args = ap.parse_args()

    total_tools = 0
    total_changed = 0
    aggregate: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0}
    for fname in MCP_MANIFESTS:
        p = ROOT / fname
        if not p.exists():
            print(f"SKIP (missing): {fname}", file=sys.stderr)
            continue
        n, c, dist = process_manifest(p, check_only=args.check)
        for k, v in dist.items():
            aggregate[k] += v
        total_tools += n
        total_changed += c
        print(f"  {fname}: tools={n} changed={c} tier_dist={dist}")
    print(f"TOTAL tools={total_tools} changed={total_changed} aggregate_tier_dist={aggregate}")
    if args.check and total_changed:
        print("DRIFT detected (run without --check to fix).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
