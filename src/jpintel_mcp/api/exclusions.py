import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.models import (
    ExclusionCheckRequest,
    ExclusionCheckResponse,
    ExclusionHit,
    ExclusionRule,
)

router = APIRouter(prefix="/v1/exclusions", tags=["exclusions"])


def _row_to_rule(row: sqlite3.Row) -> ExclusionRule:
    def j(col: str, default: Any) -> Any:
        raw = row[col]
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    return ExclusionRule(
        rule_id=row["rule_id"],
        kind=row["kind"],
        severity=row["severity"],
        program_a=row["program_a"],
        program_b=row["program_b"],
        program_b_group=j("program_b_group_json", []),
        description=row["description"],
        source_notes=row["source_notes"],
        source_urls=j("source_urls_json", []),
        extra=j("extra_json", {}),
    )


@router.get("/rules", response_model=list[ExclusionRule])
def list_rules(
    conn: DbDep,
    ctx: ApiContextDep,
    limit: int = Query(
        200,
        ge=1,
        le=500,
        description=(
            "Maximum number of rules to return. Defaults to 200 (currently "
            "returns the full ruleset of 181). Cap is 500 to bound response "
            "size for AI-agent callers paying ¥3/req."
        ),
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of rules to skip for pagination (0 = first page).",
    ),
) -> list[ExclusionRule]:
    # NOTE: response shape stays a bare JSON array for backwards
    # compatibility with the python SDK (`list_exclusion_rules`) and the
    # existing `test_list_exclusion_rules` contract. Adding `limit`/`offset`
    # as declared Query params is what unblocks the strict_query middleware
    # — once they appear in the route's ``dependant.query_params`` set, the
    # middleware allows them through (see `api/middleware/strict_query.py`).
    rows = conn.execute(
        "SELECT * FROM exclusion_rules ORDER BY rule_id LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    log_usage(conn, ctx, "exclusions.rules", strict_metering=True)
    return [_row_to_rule(r) for r in rows]


@router.post("/check", response_model=ExclusionCheckResponse)
def check_exclusions(
    payload: ExclusionCheckRequest,
    conn: DbDep,
    ctx: ApiContextDep,
) -> ExclusionCheckResponse:
    program_ids = list(dict.fromkeys(payload.program_ids))
    if not program_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "program_ids required")

    # Dual-key expansion (P0-3 / J10 fix, migration 051). See the matching
    # block in src/jpintel_mcp/mcp/server.py:check_exclusions for the full
    # rationale. Summary: exclusion_rules.program_{a,b} use slugs, names,
    # and unified_ids interchangeably; migration 051 added _uid columns
    # for resolvable rows; here we expand caller input through programs to
    # match a rule under either its legacy key or its resolved _uid.
    selected = set(program_ids)
    placeholders = ",".join(["?"] * len(program_ids))
    prog_rows = conn.execute(
        f"SELECT unified_id, primary_name FROM programs "
        f"WHERE unified_id IN ({placeholders}) "
        f"   OR primary_name IN ({placeholders})",
        (*program_ids, *program_ids),
    ).fetchall()
    input_to_uid: dict[str, str] = {}
    uid_to_input: dict[str, str] = {}
    for pr in prog_rows:
        uid = pr["unified_id"]
        name = pr["primary_name"]
        if uid in selected:
            input_to_uid[uid] = uid
            uid_to_input.setdefault(uid, uid)
        if name and name in selected:
            input_to_uid[name] = uid
            uid_to_input.setdefault(uid, name)

    rows = conn.execute("SELECT * FROM exclusion_rules").fetchall()
    # PRAGMA table_info returns (cid, name, type, notnull, dflt, pk).
    col_names = {d[1] for d in conn.execute("PRAGMA table_info(exclusion_rules)")}
    has_uid = "program_a_uid" in col_names and "program_b_uid" in col_names
    rules = [_row_to_rule(r) for r in rows]

    def _match(rule_key: str | None, rule_uid: str | None) -> str | None:
        if rule_key and rule_key in selected:
            return rule_key
        if rule_uid:
            if rule_uid in selected:
                return uid_to_input.get(rule_uid, rule_uid)
            for caller_key, uid in input_to_uid.items():
                if uid == rule_uid:
                    return caller_key
        return None

    hits: list[ExclusionHit] = []
    for rule, raw in zip(rules, rows, strict=True):
        a_uid = raw["program_a_uid"] if has_uid else None
        b_uid = raw["program_b_uid"] if has_uid else None
        candidates: set[str] = set()
        ma = _match(rule.program_a, a_uid)
        if ma:
            candidates.add(ma)
        mb = _match(rule.program_b, b_uid)
        if mb:
            candidates.add(mb)
        for gid in rule.program_b_group:
            mg = _match(gid, None)
            if mg:
                candidates.add(mg)

        if len(candidates) >= 2 or (rule.kind == "prerequisite" and candidates):
            hits.append(
                ExclusionHit(
                    rule_id=rule.rule_id,
                    kind=rule.kind,
                    severity=rule.severity,
                    programs_involved=sorted(candidates),
                    description=rule.description,
                    source_urls=rule.source_urls,
                )
            )

    # Digest material for W7: group users by the set of programs they
    # repeatedly cross-check. program_ids is sorted so any permutation
    # hashes to the same digest.
    log_usage(
        conn,
        ctx,
        "exclusions.check",
        params={"program_ids": sorted(program_ids)},
        strict_metering=True,
    )
    return ExclusionCheckResponse(
        program_ids=program_ids,
        hits=hits,
        checked_rules=len(rules),
    )
