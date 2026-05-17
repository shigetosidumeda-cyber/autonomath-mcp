#!/usr/bin/env python3
"""Lane N8 — generate 15 markdown docs under docs/_internal/recipes_n8/.

Each markdown is a human-readable companion to a data/recipes/*.yaml
file. The yaml is the machine-readable SOT; the .md is the
agent-readable rendering used in the docs site.

Idempotent: re-running overwrites the existing 15 files.
"""

from __future__ import annotations

from pathlib import Path

from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import _load_recipes

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "_internal" / "recipes_n8"

_SEGMENT_LABEL = {
    "tax": "税理士 (tax)",
    "audit": "会計士 (audit)",
    "gyousei": "行政書士 (gyousei)",
    "shihoshoshi": "司法書士 (shihoshoshi)",
    "ax_fde": "AX エンジニア / FDE (ax_fde)",
}


def _render(recipe: dict) -> str:
    name = recipe.get("recipe_name", "")
    title = recipe.get("title", "")
    seg = recipe.get("segment", "")
    seg_label = _SEGMENT_LABEL.get(str(seg), str(seg))
    disclaimer = recipe.get("disclaimer", "")
    preconds = recipe.get("preconditions", [])
    duration = recipe.get("expected_duration_seconds", "")
    parallel = recipe.get("parallel_calls_supported", False)
    cost = recipe.get("cost_estimate_jpy", "")
    bu = recipe.get("billable_units", "")
    output = recipe.get("output_artifact", {})
    steps = recipe.get("steps", [])

    lines: list[str] = []
    lines.append(f"# {name} - {title}")
    lines.append("")
    lines.append(f"**Segment**: {seg_label} / **Disclaimer**: {disclaimer}")
    lines.append("")
    lines.append("## Pre-conditions")
    for p in preconds:
        lines.append(f"- `{p}`")
    lines.append("")
    lines.append(f"## Steps ({len(steps)} MCP calls)")
    lines.append("")
    lines.append("| # | tool | purpose |")
    lines.append("|---|------|---------|")
    for step in steps:
        sid = step.get("step", "?")
        tool = step.get("tool_name", "")
        purpose = step.get("purpose", "")
        lines.append(f"| {sid} | `{tool}` | {purpose} |")
    lines.append("")
    lines.append("## Duration / cost")
    lines.append(f"- Expected duration: {duration} seconds")
    lines.append(f"- Parallel calls supported: {parallel}")
    lines.append(f"- Cost: ¥{cost} ({bu} billable units x ¥3)")
    lines.append("")
    lines.append("## Output artifact")
    if isinstance(output, dict):
        otype = output.get("type", "")
        ofmt = output.get("format", "")
        fields = output.get("fields", [])
        lines.append(f"- type: `{otype}`")
        lines.append(f"- format: `{ofmt}`")
        lines.append("- fields:")
        for f in fields:
            lines.append(f"  - `{f}`")
    lines.append("")
    lines.append(
        f"Machine-readable: [`data/recipes/{name}.yaml`](../../../data/recipes/{name}.yaml)."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recipes = _load_recipes()
    written = 0
    for recipe in recipes:
        name = recipe.get("recipe_name", "")
        if not name:
            continue
        path = OUT_DIR / f"{name}.md"
        path.write_text(_render(recipe), encoding="utf-8")
        written += 1
    print(f"wrote {written} recipe docs to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
