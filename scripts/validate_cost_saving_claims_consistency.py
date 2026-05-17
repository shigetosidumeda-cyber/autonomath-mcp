#!/usr/bin/env python3
"""FF2 cost-saving claim consistency validator.

Single-purpose gate: the **tier quintuple** ``(yen, opus_turns, opus_yen,
saving_pct, saving_yen)`` must be identical across the 3 customer-facing
stores so that an agent's "this saves X% / ¥Y vs Opus" narrative cannot drift
from the actual service contract.

Stores checked:

1. MCP tool description footers (`mcp-server*.json`)
2. OpenAPI ``x-cost-saving`` extensions on every operation
   (`site/openapi*.json`, `site/openapi/*.json`, `site/docs/openapi/*.json`)
3. ``.well-known/agents.json#cost_efficiency_claim``

The canonical numbers come from
``docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md`` §3. The validator
re-derives the expected values from the FF1 SOT-mirrored constants in
`ff2_embed_cost_saving_footer.py` (single point of source).

Run modes::

    python scripts/validate_cost_saving_claims_consistency.py
    python scripts/validate_cost_saving_claims_consistency.py --verbose
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOT_DOC_REL = "docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md"

# Mirror of FF1 SOT §3 quintuples.
EXPECTED: dict[str, dict[str, float | int]] = {
    "A": {"yen": 3, "opus_turns": 3, "opus_yen": 54, "saving_pct": 94.4, "saving_yen": 51},
    "B": {"yen": 6, "opus_turns": 5, "opus_yen": 170, "saving_pct": 96.5, "saving_yen": 164},
    "C": {"yen": 12, "opus_turns": 7, "opus_yen": 347, "saving_pct": 96.5, "saving_yen": 335},
    "D": {"yen": 30, "opus_turns": 7, "opus_yen": 500, "saving_pct": 94.0, "saving_yen": 470},
}

# Saving ratio envelope (cost_efficiency_claim block).
EXPECTED_RATIO_MIN = 17  # ¥500 / ¥30
EXPECTED_RATIO_MAX = 167  # ¥500 / ¥3
EXPECTED_BASELINE_YEN = 500
EXPECTED_RANGE_LOW = 3
EXPECTED_RANGE_HIGH = 30

MCP_MANIFESTS = [
    "mcp-server.json",
    "mcp-server.full.json",
    "mcp-server.core.json",
    "mcp-server.composition.json",
]
OPENAPI_TARGETS = [
    "site/openapi.agent.json",
    "site/openapi.agent.gpt30.json",
    "site/openapi/v1.json",
    "site/openapi/agent.json",
    "site/docs/openapi/v1.json",
    "site/docs/openapi/agent.json",
]
AGENTS_JSON = "site/.well-known/agents.json"

# Regex extracting the quintuple from a tool description footer.
FOOTER_RE = re.compile(
    r"\*\*Cost-saving claim\*\*: Equivalent to ~(?P<opus_turns>\d+)-turn "
    r"Claude Opus 4\.7 reasoning \(~¥(?P<opus_yen>[\d,]+)\)\. "
    r"This tool returns the precomputed/structured answer for "
    r"¥(?P<yen>\d+)/req \(tier (?P<tier>[A-D])\)\.\s*\n"
    r"Saving: (?P<saving_pct>\d+\.\d+)% / ¥(?P<saving_yen>[\d,]+)/req vs raw Opus call\.",
    re.MULTILINE,
)


def _eq(a: float, b: float) -> bool:
    return abs(float(a) - float(b)) < 0.01


def validate_mcp() -> tuple[int, int, list[str]]:
    """Returns (tools_seen, mismatches, error_messages)."""
    tools_seen = 0
    mismatches = 0
    errors: list[str] = []
    for fname in MCP_MANIFESTS:
        p = ROOT / fname
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for t in data.get("tools", []):
            tools_seen += 1
            desc = t.get("description", "") or ""
            m = FOOTER_RE.search(desc)
            if m is None:
                mismatches += 1
                errors.append(f"MCP {fname}::{t.get('name')} missing cost-saving footer")
                continue
            tier = m.group("tier")
            exp = EXPECTED[tier]
            actual = {
                "yen": int(m.group("yen")),
                "opus_turns": int(m.group("opus_turns")),
                "opus_yen": int(m.group("opus_yen").replace(",", "")),
                "saving_pct": float(m.group("saving_pct")),
                "saving_yen": int(m.group("saving_yen").replace(",", "")),
            }
            for k in ("yen", "opus_turns", "opus_yen", "saving_pct", "saving_yen"):
                if not _eq(actual[k], float(exp[k])):
                    mismatches += 1
                    errors.append(
                        f"MCP {fname}::{t.get('name')} tier={tier} key={k} "
                        f"actual={actual[k]} expected={exp[k]}"
                    )
                    break
            # Verify verifiable doc reference.
            if SOT_DOC_REL not in desc:
                mismatches += 1
                errors.append(f"MCP {fname}::{t.get('name')} missing SOT doc reference")
    return tools_seen, mismatches, errors


def validate_openapi() -> tuple[int, int, list[str]]:
    ops_seen = 0
    mismatches = 0
    errors: list[str] = []
    for rel in OPENAPI_TARGETS:
        p = ROOT / rel
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for path, methods in (data.get("paths") or {}).items():
            if not isinstance(methods, dict):
                continue
            for method, op in methods.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if not isinstance(op, dict):
                    continue
                ops_seen += 1
                ext = op.get("x-cost-saving")
                if not isinstance(ext, dict):
                    mismatches += 1
                    errors.append(f"OpenAPI {rel}::{method.upper()} {path} missing x-cost-saving")
                    continue
                tier = ext.get("tier")
                if tier not in EXPECTED:
                    mismatches += 1
                    errors.append(f"OpenAPI {rel}::{method.upper()} {path} bad tier={tier}")
                    continue
                exp = EXPECTED[tier]
                checks = {
                    "jpcite_yen": ext.get("jpcite_yen"),
                    "opus_4_7_equivalent_turns": ext.get("opus_4_7_equivalent_turns"),
                    "opus_yen_estimate": ext.get("opus_yen_estimate"),
                    "saving_pct": ext.get("saving_pct"),
                    "saving_yen": ext.get("saving_yen"),
                }
                mapping = {
                    "jpcite_yen": exp["yen"],
                    "opus_4_7_equivalent_turns": exp["opus_turns"],
                    "opus_yen_estimate": exp["opus_yen"],
                    "saving_pct": exp["saving_pct"],
                    "saving_yen": exp["saving_yen"],
                }
                for k, actual in checks.items():
                    if actual is None or not _eq(actual, float(mapping[k])):
                        mismatches += 1
                        errors.append(
                            f"OpenAPI {rel}::{method.upper()} {path} tier={tier} "
                            f"key={k} actual={actual} expected={mapping[k]}"
                        )
                        break
                if ext.get("verifiable_doc") != SOT_DOC_REL:
                    mismatches += 1
                    errors.append(f"OpenAPI {rel}::{method.upper()} {path} bad verifiable_doc")
    return ops_seen, mismatches, errors


def validate_agents_json() -> tuple[int, int, list[str]]:
    errors: list[str] = []
    mismatches = 0
    p = ROOT / AGENTS_JSON
    if not p.exists():
        return 0, 1, [f"missing {AGENTS_JSON}"]
    data = json.loads(p.read_text(encoding="utf-8"))
    claim = data.get("cost_efficiency_claim")
    if not isinstance(claim, dict):
        return 0, 1, ["agents.json missing cost_efficiency_claim block"]
    if claim.get("baseline_yen_per_query") != EXPECTED_BASELINE_YEN:
        mismatches += 1
        errors.append(
            f"agents.json baseline_yen_per_query={claim.get('baseline_yen_per_query')} "
            f"!= {EXPECTED_BASELINE_YEN}"
        )
    rng = claim.get("jpcite_yen_per_query_range")
    if rng != [EXPECTED_RANGE_LOW, EXPECTED_RANGE_HIGH]:
        mismatches += 1
        errors.append(
            f"agents.json jpcite_yen_per_query_range={rng} != "
            f"[{EXPECTED_RANGE_LOW},{EXPECTED_RANGE_HIGH}]"
        )
    if claim.get("saving_ratio_min") != EXPECTED_RATIO_MIN:
        mismatches += 1
        errors.append(
            f"agents.json saving_ratio_min={claim.get('saving_ratio_min')} != {EXPECTED_RATIO_MIN}"
        )
    if claim.get("saving_ratio_max") != EXPECTED_RATIO_MAX:
        mismatches += 1
        errors.append(
            f"agents.json saving_ratio_max={claim.get('saving_ratio_max')} != {EXPECTED_RATIO_MAX}"
        )
    if claim.get("verifiable_doc") != SOT_DOC_REL:
        mismatches += 1
        errors.append(f"agents.json verifiable_doc={claim.get('verifiable_doc')} != {SOT_DOC_REL}")
    tiers = claim.get("tiers")
    if not isinstance(tiers, dict):
        mismatches += 1
        errors.append("agents.json cost_efficiency_claim.tiers missing")
        return 4, mismatches, errors
    for tier, exp in EXPECTED.items():
        block = tiers.get(tier)
        if not isinstance(block, dict):
            mismatches += 1
            errors.append(f"agents.json tiers.{tier} missing")
            continue
        checks = {
            "jpcite_yen": block.get("jpcite_yen"),
            "opus_equiv_turns": block.get("opus_equiv_turns"),
            "opus_equiv_yen": block.get("opus_equiv_yen"),
            "saving_pct": block.get("saving_pct"),
            "saving_yen": block.get("saving_yen"),
        }
        mapping = {
            "jpcite_yen": exp["yen"],
            "opus_equiv_turns": exp["opus_turns"],
            "opus_equiv_yen": exp["opus_yen"],
            "saving_pct": exp["saving_pct"],
            "saving_yen": exp["saving_yen"],
        }
        for k, actual in checks.items():
            if actual is None or not _eq(actual, float(mapping[k])):
                mismatches += 1
                errors.append(
                    f"agents.json tiers.{tier} key={k} actual={actual} expected={mapping[k]}"
                )
                break
    return 4, mismatches, errors


def validate_sot_exists() -> tuple[int, int, list[str]]:
    p = ROOT / SOT_DOC_REL
    if not p.exists():
        return 0, 1, [f"FF1 SOT {SOT_DOC_REL} missing"]
    text = p.read_text(encoding="utf-8")
    # cheap signal: tier table line(s) must mention each price
    for tier, exp in EXPECTED.items():
        needle = f"¥{int(exp['yen'])}"
        if needle not in text:
            return 1, 1, [f"FF1 SOT missing tier {tier} price ¥{exp['yen']}"]
    return 1, 0, []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    sot_ok, sot_err, sot_errs = validate_sot_exists()
    tools_seen, tool_err, tool_errs = validate_mcp()
    ops_seen, op_err, op_errs = validate_openapi()
    a_seen, a_err, a_errs = validate_agents_json()
    total = sot_err + tool_err + op_err + a_err
    print(
        f"FF2 consistency check: SOT(ok={sot_ok}, err={sot_err}); "
        f"MCP(tools={tools_seen}, err={tool_err}); "
        f"OpenAPI(ops={ops_seen}, err={op_err}); "
        f"agents.json(checks={a_seen}, err={a_err}); "
        f"TOTAL_ERR={total}"
    )
    if args.verbose or total:
        for e in sot_errs + tool_errs + op_errs + a_errs:
            print(f"  - {e}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
