"""Generate `site/releases/rc1-p0-bootstrap/capability_matrix.json`.

Generator is the source of truth for the 169-tool agent-discovery matrix.
Reads the canonical mcp-server.json + outcome contract catalog + cost preview
catalog and emits the merged matrix.

Run:

    .venv/bin/python scripts/generate_capability_matrix.py

The matrix preserves the existing P0 facade shape (`capabilities` array +
`p0_facade_tools` + `matrix_id` + `generated_from_capsule_id` +
`full_catalog_default_visible: false`) and adds a `tools` array with one
entry per MCP tool. Each tool entry carries:

  - tool_id, surface (MCP/OpenAPI/static), free_or_paid,
    billing_units, cost_band, agent_handoff_kind

Free/paid classification is by substring heuristic over tool names; the
rule of thumb is: discovery / preview / health / cost-preview = free,
composed / heavy outcome packs = heavy paid, mid joins = mid paid,
remaining lookups = light paid.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER_PATH = ROOT / "mcp-server.json"
OUTCOME_CATALOG_PATH = (
    ROOT / "site" / "releases" / "rc1-p0-bootstrap" / "outcome_contract_catalog.json"
)
COST_PREVIEW_PATH = (
    ROOT / "site" / "releases" / "rc1-p0-bootstrap" / "cost_preview_catalog.json"
)
OUTPUT_PATH = (
    ROOT / "site" / "releases" / "rc1-p0-bootstrap" / "capability_matrix.json"
)

# Heuristic classification — order matters: more-specific first.
FREE_SUBSTRINGS: tuple[str, ...] = (
    "list_static_resources",
    "list_example_profiles",
    "get_static_resource",
    "get_example_profile",
    "deep_health",
    "get_meta",
    "enum_values",
    "get_usage_status",
    "health_check",
    "whoami",
    "list_exclusion_rules",
    "list_open_programs",
    "list_tax_sunset_alerts",
    "list_prebuilt_packets",
    "recommend_partner_for_gap",
    "preview",
    "cost_preview",
    "route",
    "mcp_get_packet",
)

HEAVY_OUTCOME_SUBSTRINGS: tuple[str, ...] = (
    "application_strategy",
    "client_monthly_review",
    "cashbook",
    "csv_overlay",
    "foreign_investor",
    "application_kit",
    "reviewer_handoff",
    "auditor_evidence",
    "subsidy_combo",
    "subsidy_roadmap",
    "composed",
    "public_dd",
    "counterparty_public_dd",
    "public_funding_traceback",
    "ma_due_diligence",
    "due_diligence_pack",
)

MID_OUTCOME_SUBSTRINGS: tuple[str, ...] = (
    "regulation_change_watch",
    "court_enforcement",
    "evidence_answer",
    "healthcare_regulatory",
    "local_government_permit",
    "compatibility",
    "amendment",
    "lineage",
    "monthly_review",
    "cohort",
    "snapshot",
    "as_of",
    "time_machine",
    "counterfactual",
    "composition",
    "compose",
    "matrix_check",
    "matrix_grid",
    "matrix",
)


def classify_tool(name: str) -> tuple[str, str, int, bool]:
    """Return (cost_band, agent_handoff_kind, estimated_price_jpy, billable).

    Returns one of cost_band in {"free","light","mid","heavy"} and a
    coarse agent_handoff_kind tag for routing decision.
    """
    if any(sub in name for sub in FREE_SUBSTRINGS):
        return ("free", "control", 0, False)
    if any(sub in name for sub in HEAVY_OUTCOME_SUBSTRINGS):
        return ("heavy", "composed_outcome", 900, True)
    if any(sub in name for sub in MID_OUTCOME_SUBSTRINGS):
        return ("mid", "joined_outcome", 600, True)
    return ("light", "atomic_lookup", 300, True)


def build_tool_entry(tool: dict[str, object]) -> dict[str, object]:
    name = str(tool["name"])
    cost_band, agent_handoff_kind, est_price, billable = classify_tool(name)
    return {
        "tool_id": name,
        "surface": "MCP",
        "free_or_paid": "free" if not billable else "paid",
        "billing_units": "request",
        "billable_unit_price_jpy": 3 if billable else 0,
        "cost_band": cost_band,
        "estimated_price_jpy": est_price,
        "agent_handoff_kind": agent_handoff_kind,
    }


def build_matrix() -> dict[str, object]:
    mcp_server = json.loads(MCP_SERVER_PATH.read_text())
    tools = mcp_server["tools"]
    tool_entries = [build_tool_entry(t) for t in tools]

    free_total = sum(1 for t in tool_entries if t["free_or_paid"] == "free")
    paid_total = sum(1 for t in tool_entries if t["free_or_paid"] == "paid")
    light = sum(1 for t in tool_entries if t["cost_band"] == "light")
    mid = sum(1 for t in tool_entries if t["cost_band"] == "mid")
    heavy = sum(1 for t in tool_entries if t["cost_band"] == "heavy")

    # Preserve original P0 facade capabilities array (agent-routing facade).
    p0_facade_capabilities = [
        {
            "capability_id": "jpcite_route",
            "billable": False,
            "blocked": False,
            "executable": True,
            "previewable": False,
            "recommendable": True,
        },
        {
            "capability_id": "jpcite_preview_cost",
            "billable": False,
            "blocked": False,
            "executable": True,
            "previewable": True,
            "recommendable": True,
        },
        {
            "capability_id": "jpcite_execute_packet",
            "billable": True,
            "blocked": False,
            "executable": True,
            "previewable": False,
            "recommendable": True,
        },
        {
            "capability_id": "jpcite_get_packet",
            "billable": False,
            "blocked": False,
            "executable": True,
            "previewable": False,
            "recommendable": True,
        },
    ]

    return {
        "matrix_id": "rc1-p0-bootstrap-2026-05-15:capability-matrix",
        "generated_from_capsule_id": "rc1-p0-bootstrap-2026-05-15",
        "full_catalog_default_visible": False,
        "p0_facade_tools": [
            "jpcite_route",
            "jpcite_preview_cost",
            "jpcite_execute_packet",
            "jpcite_get_packet",
        ],
        "capabilities": p0_facade_capabilities,
        "tool_count": len(tool_entries),
        "free_paid_breakdown": {
            "free": free_total,
            "paid": paid_total,
            "by_band": {
                "free": free_total,
                "light": light,
                "mid": mid,
                "heavy": heavy,
            },
        },
        "tools": tool_entries,
    }


def main() -> None:
    matrix = build_matrix()
    OUTPUT_PATH.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {OUTPUT_PATH} with {matrix['tool_count']} tools")


if __name__ == "__main__":
    main()
