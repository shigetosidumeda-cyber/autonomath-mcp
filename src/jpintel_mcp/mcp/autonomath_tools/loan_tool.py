"""AutonoMath MCP tool skeleton: search_loans.

Exposes a single MCP-style callable that queries am_loan_product directly.
All inference is on the client side. The server ONLY serves structured rows.

NO ANTHROPIC_API_KEY / SDK / Message Batches. Pure local SQLite.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[4]
DB_PATH = Path(
    os.environ.get(
        "AUTONOMATH_DB_PATH",
        str(_REPO_ROOT / "autonomath.db"),
    )
)

LOAN_KINDS = {
    "ippan",
    "trou",
    "seirei",
    "sanko",
    "sogyo",
    "rinsei",
    "saigai",
    "shingiseikyu",
    "kiki",
    "other",
}

GUARANTOR_ENUM = {"required", "not_required", "exception", "unknown"}
COLLATERAL_ENUM = {"required", "not_required", "case_by_case", "unknown"}


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    p = db_path or DB_PATH
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.row_factory = sqlite3.Row
    return conn


def search_loans(
    loan_kind: str | None = None,
    no_collateral: bool = False,
    no_personal_guarantor: bool = False,
    no_third_party_guarantor: bool = False,
    max_amount_yen: int | None = None,
    min_amount_yen: int | None = None,
    lender_entity_id: str | None = None,
    name_query: str | None = None,
    limit: int = 10,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Structured loan-product search.

    Parameters
    ----------
    loan_kind          one of LOAN_KINDS (or None to include all)
    no_collateral      if True -> collateral_required='not_required'
    no_personal_guarantor     if True -> personal_guarantor='not_required'
    no_third_party_guarantor  if True -> third_party_guarantor='not_required'
    max_amount_yen     upper bound for limit_yen (matches >= row.limit_yen)
    min_amount_yen     require row.limit_yen >= this
    lender_entity_id   FK am_authority.canonical_id
    name_query         LIKE '%...%' against primary_name (simple)
    limit              result cap (1..100)
    db_path            override for tests

    Returns
    -------
    list[dict] with keys including the 3-axis guarantor flags.
    """
    if loan_kind is not None and loan_kind not in LOAN_KINDS:
        raise ValueError(f"unknown loan_kind={loan_kind!r}")
    limit = max(1, min(int(limit), 100))

    where: list[str] = []
    params: list[Any] = []
    if loan_kind:
        where.append("loan_program_kind = ?")
        params.append(loan_kind)
    if no_collateral:
        where.append("collateral_required = 'not_required'")
    if no_personal_guarantor:
        where.append("personal_guarantor = 'not_required'")
    if no_third_party_guarantor:
        where.append("third_party_guarantor = 'not_required'")
    if max_amount_yen is not None:
        # find loans whose cap is <= user's need OR user need is under cap
        where.append("(limit_yen IS NULL OR limit_yen >= ?)")
        params.append(int(max_amount_yen))
    if min_amount_yen is not None:
        where.append("(limit_yen IS NOT NULL AND limit_yen >= ?)")
        params.append(int(min_amount_yen))
    if lender_entity_id:
        where.append("lender_entity_id = ?")
        params.append(lender_entity_id)
    if name_query:
        where.append("primary_name LIKE ?")
        params.append(f"%{name_query}%")

    sql = (
        "SELECT canonical_id, primary_name, lender_entity_id, loan_program_kind, "
        "limit_yen, limit_yen_special, interest_rate_base_pct, "
        "interest_rate_special_pct, term_years_max, grace_period_months, "
        "collateral_required, personal_guarantor, third_party_guarantor, "
        "eligibility_cond_json, source_url "
        "FROM am_loan_product"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY (limit_yen IS NULL), limit_yen DESC LIMIT ?"
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
            # 3-axis convenience flags for client reasoning
            d["flags"] = {
                "no_collateral": d["collateral_required"] == "not_required",
                "no_personal_guarantor": d["personal_guarantor"] == "not_required",
                "no_third_party_guarantor": d["third_party_guarantor"] == "not_required",
            }
            out.append(d)
        return out
    finally:
        conn.close()


# MCP tool descriptor (framework-agnostic skeleton)
TOOL_DEFINITION = {
    "name": "search_loans",
    "description": (
        "AutonoMath loan search. Returns structured rows from am_loan_product. "
        "Supports filtering by loan_kind (ippan/trou/seirei/sanko/sogyo/rinsei/"
        "saigai/shingiseikyu/kiki/other), 3-axis guarantor flags "
        "(no_collateral / no_personal_guarantor / no_third_party_guarantor), "
        "amount range, lender. All inference is the client's job."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "loan_kind": {"type": "string", "enum": sorted(LOAN_KINDS)},
            "no_collateral": {"type": "boolean"},
            "no_personal_guarantor": {"type": "boolean"},
            "no_third_party_guarantor": {"type": "boolean"},
            "max_amount_yen": {"type": "integer", "minimum": 0},
            "min_amount_yen": {"type": "integer", "minimum": 0},
            "lender_entity_id": {"type": "string"},
            "name_query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
        },
        "additionalProperties": False,
    },
}


def handle_tool_call(args: dict[str, Any]) -> dict[str, Any]:
    """Thin MCP adapter for `search_loans` tool call.

    Returns canonical pagination shape `{total, limit, offset, results}` to
    match search_tax_incentives / search_certifications / list_open_programs
    / search_gx_programs_am. `result_count` is retained as a deprecated alias
    so v0.1 clients don't whipsaw on field rename; remove after 2026-07.
    """
    results = search_loans(**args)
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
    rows = search_loans(
        no_collateral=True, no_personal_guarantor=True, no_third_party_guarantor=True, limit=5
    )
    print(f"unsecured loans (3-axis no): {len(rows)}")
    for r in rows:
        print(" -", r["canonical_id"], "|", r["primary_name"], "|", r["limit_yen"])
