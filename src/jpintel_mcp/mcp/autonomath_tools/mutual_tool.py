"""AutonoMath MCP tool skeleton: search_mutual_plans.

Exposes a single MCP-style callable that queries am_insurance_mutual +
am_tax_rule directly. All inference is on the client side. The server ONLY
serves structured rows.

NO ANTHROPIC_API_KEY / SDK / Message Batches. Pure local SQLite.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = Path(
    os.environ.get(
        "AUTONOMATH_DB_PATH",
        str(_REPO_ROOT / "autonomath.db"),
    )
)

PLAN_KINDS = {
    "retirement_mutual",
    "bankruptcy_mutual",
    "dc_pension",
    "db_pension",
    "industry_pension",
    "welfare_insurance",
    "health_insurance",
    "other",
}

TAX_DED_TYPES = {
    "small_enterprise_deduction",
    "idekodc",
    "group_retirement",
    "corp_expense",
    "none",
}


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    p = db_path or DB_PATH
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.row_factory = sqlite3.Row
    return conn


def search_mutual_plans(
    plan_kind: str | None = None,
    premium_monthly_yen: int | None = None,
    tax_deduction_type: str | None = None,
    provider_entity_id: str | None = None,
    name_query: str | None = None,
    limit: int = 10,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Structured mutual/insurance/pension plan search.

    Parameters
    ----------
    plan_kind             one of PLAN_KINDS (or None to include all)
    premium_monthly_yen   client's intended monthly budget; matches rows where
                          premium_min <= budget <= premium_max (nulls allowed)
    tax_deduction_type    filter by deduction class
    provider_entity_id    FK am_authority.canonical_id (e.g. 'authority:smrj')
    name_query            LIKE '%...%' against primary_name
    limit                 result cap (1..100)
    db_path               override for tests

    Returns
    -------
    list[dict] per plan, each containing:
      - canonical_id, primary_name, provider_entity_id, plan_kind
      - premium_min_yen, premium_max_yen
      - tax_deduction_type, benefit_type
      - eligibility_cond  (dict, parsed JSON)
      - source_url
      - linked_tax_rules  list of am_tax_rule rows whose note or article_ref
                          plausibly matches the plan (simple heuristic: a
                          mutual row maps to tax_measure entities that were
                          seeded together, matched via tax_deduction_type).
    """
    if plan_kind is not None and plan_kind not in PLAN_KINDS:
        raise ValueError(f"unknown plan_kind={plan_kind!r}")
    if tax_deduction_type is not None and tax_deduction_type not in TAX_DED_TYPES:
        raise ValueError(f"unknown tax_deduction_type={tax_deduction_type!r}")
    limit = max(1, min(int(limit), 100))

    where: list[str] = []
    params: list[Any] = []
    if plan_kind:
        where.append("plan_kind = ?")
        params.append(plan_kind)
    if tax_deduction_type:
        where.append("tax_deduction_type = ?")
        params.append(tax_deduction_type)
    if provider_entity_id:
        where.append("provider_entity_id = ?")
        params.append(provider_entity_id)
    if name_query:
        where.append("primary_name LIKE ?")
        params.append(f"%{name_query}%")
    if premium_monthly_yen is not None:
        # budget must be within [premium_min, premium_max] (treat NULLs as open bound)
        where.append(
            "(premium_min_yen IS NULL OR premium_min_yen <= ?) "
            "AND (premium_max_yen IS NULL OR premium_max_yen >= ?)"
        )
        params.append(int(premium_monthly_yen))
        params.append(int(premium_monthly_yen))

    sql = (
        "SELECT canonical_id, primary_name, provider_entity_id, plan_kind, "
        "premium_min_yen, premium_max_yen, tax_deduction_type, benefit_type, "
        "eligibility_cond_json, source_url "
        "FROM am_insurance_mutual"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY plan_kind, primary_name LIMIT ?"
    params.append(limit)

    conn = _conn(db_path)
    try:
        rows: Iterable[sqlite3.Row] = conn.execute(sql, params).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["eligibility_cond"] = json.loads(d.pop("eligibility_cond_json") or "{}")
            except Exception:
                d["eligibility_cond"] = {}
            # Attach linked tax rules via heuristic:
            #  - small_enterprise_deduction / idekodc -> tax_measure:mutual_2026-04-24:*
            #  - corp_expense -> safetynet_sonkin if bankruptcy else none
            d["linked_tax_rules"] = _lookup_linked_tax(conn, d)
            out.append(d)
        return out
    finally:
        conn.close()


def _lookup_linked_tax(conn: sqlite3.Connection, plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Return am_tax_rule rows plausibly linked to the given mutual plan."""
    # Map mutual canonical_id / tax_deduction_type to the seed tax_measure ids.
    cid = plan["canonical_id"]
    ded = plan["tax_deduction_type"]

    candidates: list[str] = []
    if cid == "mutual:smrj:shokibo":
        candidates.append("tax_measure:mutual_2026-04-24:shokibo_kyosai_kakekin_kojo")
    if cid.startswith("mutual:npfa:ideco") or ded == "idekodc":
        candidates.append("tax_measure:mutual_2026-04-24:ideco_kakekin_kojo")
    if cid == "mutual:smrj:safety-net":
        candidates.append("tax_measure:mutual_2026-04-24:safetynet_sonkin")

    if not candidates:
        return []

    q = (
        "SELECT tax_measure_entity_id, rule_type, article_ref, source_url, note "
        "FROM am_tax_rule WHERE tax_measure_entity_id IN "
        f"({','.join('?' * len(candidates))})"
    )
    rows = conn.execute(q, candidates).fetchall()
    return [dict(r) for r in rows]


# MCP tool descriptor (framework-agnostic skeleton)
TOOL_DEFINITION = {
    "name": "search_mutual_plans",
    "description": (
        "AutonoMath mutual/insurance/pension search. Returns rows from "
        "am_insurance_mutual with linked am_tax_rule entries. Filter by "
        "plan_kind (retirement_mutual/bankruptcy_mutual/dc_pension/db_pension/"
        "industry_pension/welfare_insurance/health_insurance/other), monthly "
        "premium budget, tax_deduction_type "
        "(small_enterprise_deduction/idekodc/group_retirement/corp_expense/"
        "none), provider, name. All inference is the client's job."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "plan_kind": {"type": "string", "enum": sorted(PLAN_KINDS)},
            "premium_monthly_yen": {"type": "integer", "minimum": 0},
            "tax_deduction_type": {"type": "string", "enum": sorted(TAX_DED_TYPES)},
            "provider_entity_id": {"type": "string"},
            "name_query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "additionalProperties": False,
    },
}


def handle_tool_call(args: dict[str, Any]) -> dict[str, Any]:
    """Thin MCP adapter for `search_mutual_plans` tool call.

    Returns canonical pagination shape `{total, limit, offset, results}` to
    match the other 7 am search tools. `result_count` retained as deprecated
    alias; drop after 2026-07.
    """
    results = search_mutual_plans(**args)
    limit = int(args.get("limit", 10) or 10)
    offset = int(args.get("offset", 0) or 0)
    return {
        "total": len(results),
        "limit": limit,
        "offset": offset,
        "result_count": len(results),  # deprecated alias; drop after 2026-07
        "results": results,
    }


if __name__ == "__main__":
    # smoke test
    rows = search_mutual_plans(plan_kind="dc_pension", limit=10)
    print(f"dc_pension count: {len(rows)}")
    for r in rows:
        print(
            " -",
            r["canonical_id"],
            "|",
            r["primary_name"],
            "| tax:",
            r["tax_deduction_type"],
            "| tax_rules:",
            len(r["linked_tax_rules"]),
        )
