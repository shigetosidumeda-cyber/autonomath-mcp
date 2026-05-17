#!/usr/bin/env python3
"""FF2 — apply all cost-saving embeddings idempotently.

Runs the 3 store-mutating injectors in order and the consistency validator:

1. MCP tool description footer (every ``mcp-server*.json``)
2. OpenAPI ``x-cost-saving`` extension (every ``site/openapi*.json`` /
   ``site/openapi/*.json`` / ``site/docs/openapi/*.json``)
3. ``.well-known/agents.json#cost_efficiency_claim``
4. ``scripts/validate_cost_saving_claims_consistency.py`` (gate)

This script is what GHA / pre-commit (and operators) should call. It is
intentionally minimal — the actual logic lives in the 3 dedicated
injectors so they remain individually inspectable / testable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> int:
    print(f"→ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=ROOT)
    return r.returncode


def ensure_agents_json_claim() -> int:
    p = ROOT / "site/.well-known/agents.json"
    if not p.exists():
        print(f"missing {p}", file=sys.stderr)
        return 1
    d = json.loads(p.read_text(encoding="utf-8"))
    if "cost_efficiency_claim" in d:
        return 0
    new_d: dict[str, object] = {}
    for k, v in d.items():
        new_d[k] = v
        if k == "pricing":
            new_d["cost_efficiency_claim"] = _claim_block()
    p.write_text(json.dumps(new_d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("agents.json: inserted cost_efficiency_claim")
    return 0


def _claim_block() -> dict[str, object]:
    return {
        "vs_baseline": "Claude Opus 4.7 / 7-turn evidence-gathering chain",
        "baseline_yen_per_query": 500,
        "jpcite_yen_per_query_range": [3, 30],
        "saving_ratio_min": 17,
        "saving_ratio_max": 167,
        "tiers": {
            "A": {
                "jpcite_yen": 3,
                "opus_equiv_turns": 3,
                "opus_equiv_yen": 54,
                "saving_pct": 94.4,
                "saving_yen": 51,
                "default_for": ["search_*", "list_*", "get_simple_*", "enum_*"],
            },
            "B": {
                "jpcite_yen": 6,
                "opus_equiv_turns": 5,
                "opus_equiv_yen": 170,
                "saving_pct": 96.5,
                "saving_yen": 164,
                "default_for": [
                    "search_v2_*",
                    "expand_*",
                    "get_with_relations_*",
                    "batch_get_*",
                ],
            },
            "C": {
                "jpcite_yen": 12,
                "opus_equiv_turns": 7,
                "opus_equiv_yen": 347,
                "saving_pct": 96.5,
                "saving_yen": 335,
                "default_for": [
                    "HE-1",
                    "HE-3",
                    "precomputed_answer",
                    "agent_briefing",
                    "cohort_*",
                    "jpcite_route",
                    "jpcite_preview_cost",
                    "jpcite_execute_packet",
                ],
            },
            "D": {
                "jpcite_yen": 30,
                "opus_equiv_turns": 7,
                "opus_equiv_yen": 500,
                "saving_pct": 94.0,
                "saving_yen": 470,
                "default_for": [
                    "HE-1_full",
                    "evidence_packet_full",
                    "portfolio_analysis",
                    "regulatory_impact_chain",
                ],
            },
        },
        "anchor": {
            "scenario": "Opus 4.7 7-turn Deep++ tool-calling at FX 150 JPY/USD (high-end)",
            "anchor_opus_47_7turn_jpy": 500,
            "anchor_fx_usd_jpy": 150,
        },
        "verifiable_at": "https://jpcite.com/cost-roi-sot",
        "verifiable_doc": "docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md",
        "validator": "scripts/validate_cost_saving_claims_consistency.py",
        "narrative_invariant": (
            "Narrative depth labels (A/B/C/D) advertise bundle cost vs "
            "depth-equivalent Opus chain. Billing remains flat 3 JPY / "
            "billable unit; tier labels are not a commercial-tier change."
        ),
    }


def main() -> int:
    rc = _run([sys.executable, "scripts/ff2_embed_cost_saving_footer.py"])
    if rc:
        return rc
    rc = _run([sys.executable, "scripts/ff2_embed_openapi_cost_saving.py"])
    if rc:
        return rc
    rc = _run([sys.executable, "scripts/ff2_embed_llms_narrative.py"])
    if rc:
        return rc
    rc = _run([sys.executable, "scripts/ff2_embed_html_cards.py"])
    if rc:
        return rc
    rc = ensure_agents_json_claim()
    if rc:
        return rc
    return _run([sys.executable, "scripts/validate_cost_saving_claims_consistency.py"])


if __name__ == "__main__":
    sys.exit(main())
