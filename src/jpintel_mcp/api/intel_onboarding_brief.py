"""POST /v1/intel/onboarding_brief -- first-week brief from local facts."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from jpintel_mcp.api import deps as api_deps

# DbDep MUST be imported at module-load time (not under TYPE_CHECKING) —
# `from __future__ import annotations` would otherwise demote the
# `conn: DbDep` route param to a query string and 422 every request.
DbDep = api_deps.DbDep

router = APIRouter(prefix="/v1/intel", tags=["intel"])


class CustomerProfile(BaseModel):
    name: str | None = Field(None, max_length=200)
    industry: str | None = Field(None, max_length=100)
    prefecture: str | None = Field(None, max_length=20)
    employees: int | None = Field(None, ge=0)
    capital_yen: int | None = Field(None, ge=0)


class OnboardingBriefRequest(BaseModel):
    houjin_id: str | None = Field(None, max_length=14)
    customer_profile: CustomerProfile | None = None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _normalize_houjin(value: str | None) -> str | None:
    s = (value or "").strip().upper()
    if s.startswith("T") and len(s) == 14:
        s = s[1:]
    return s or None


def _fact_value(row: dict[str, Any]) -> Any:
    for key in ("field_value_text", "field_value_numeric", "field_value_json", "value"):
        value = row.get(key)
        if value is not None and str(value).strip():
            return value
    return None


def _fetch_houjin_facts(
    conn: sqlite3.Connection, houjin_id: str | None, known_gaps: list[str]
) -> list[dict[str, Any]]:
    houjin = _normalize_houjin(houjin_id)
    if not houjin:
        return []
    if not _table_exists(conn, "am_entity_facts"):
        known_gaps.append("am_entity_facts table is not available")
        return []

    cols = _columns(conn, "am_entity_facts")
    select = {
        "entity_id": "entity_id" if "entity_id" in cols else "NULL",
        "field_name": "field_name" if "field_name" in cols else "NULL",
        "field_value_text": "field_value_text" if "field_value_text" in cols else "NULL",
        "field_value_numeric": ("field_value_numeric" if "field_value_numeric" in cols else "NULL"),
        "field_value_json": "field_value_json" if "field_value_json" in cols else "NULL",
        "source_url": "source_url" if "source_url" in cols else "NULL",
        "fetched_at": (
            "fetched_at"
            if "fetched_at" in cols
            else ("created_at" if "created_at" in cols else "NULL")
        ),
    }
    entity_col = "entity_id" if "entity_id" in cols else None
    if not entity_col:
        known_gaps.append("am_entity_facts.entity_id is not available")
        return []
    sql = (
        "SELECT "
        + ", ".join(f"{expr} AS {alias}" for alias, expr in select.items())
        + " FROM am_entity_facts WHERE entity_id IN (?, ?) "
        + " ORDER BY fetched_at DESC NULLS LAST LIMIT 100"
    )
    try:
        return [dict(row) for row in conn.execute(sql, (houjin, f"houjin:{houjin}")).fetchall()]
    except sqlite3.Error as exc:
        known_gaps.append(f"am_entity_facts query failed: {exc}")
        return []


def _facts_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for row in rows:
        field = row.get("field_name")
        if field and field not in out:
            out[str(field)] = _fact_value(row)
    return out


def _as_boolish(value: Any) -> bool | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "registered", "登録", "登録済"}:
        return True
    if s in {"0", "false", "no", "n", "unregistered", "未登録"}:
        return False
    return None


def _source_links(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        url = row.get("source_url")
        if not url or url in seen:
            continue
        seen.add(str(url))
        out.append({"url": url, "fetched_at": row.get("fetched_at")})
    return out


@router.post(
    "/onboarding_brief",
    summary="First-week onboarding brief from local houjin facts",
)
def post_onboarding_brief(
    payload: Annotated[OnboardingBriefRequest, Body(...)],
    conn: DbDep,
) -> dict[str, Any]:
    if not payload.houjin_id and payload.customer_profile is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_profile",
                "message": "houjin_id or customer_profile is required",
            },
        )

    known_gaps: list[str] = []
    fact_rows = _fetch_houjin_facts(conn, payload.houjin_id, known_gaps)
    facts = _facts_map(fact_rows)
    profile = (
        payload.customer_profile.model_dump(exclude_none=True) if payload.customer_profile else {}
    )

    if not fact_rows and payload.houjin_id:
        known_gaps.append("no local facts found for houjin_id")
    if not fact_rows and not profile:
        return {
            "houjin_id": _normalize_houjin(payload.houjin_id),
            "customer_profile": profile,
            "first_week_checklist": [],
            "due_diligence_prompts": [],
            "risk_flags": [],
            "recommended_next_calls": [],
            "source_links": [],
            "as_of": datetime.now(UTC).isoformat(),
            "known_gaps": list(dict.fromkeys(known_gaps)),
        }

    name = profile.get("name") or facts.get("corp.name") or facts.get("name")
    industry = profile.get("industry") or facts.get("corp.industry") or facts.get("industry")
    prefecture = (
        profile.get("prefecture") or facts.get("corp.prefecture") or facts.get("prefecture")
    )
    employees = profile.get("employees") or facts.get("corp.employee_count")
    capital = profile.get("capital_yen") or facts.get("corp.capital_amount")
    invoice_registered = _as_boolish(
        facts.get("corp.invoice_registered") or facts.get("invoice_registered")
    )

    checklist = [
        {
            "task": "Confirm corporate identity, address, and representative records",
            "basis": "houjin_id" if payload.houjin_id else "customer_profile",
        },
        {
            "task": "Map eligibility-critical facts to candidate programs",
            "basis": "industry/prefecture/employees/capital",
        },
        {
            "task": "Collect primary evidence for payroll, tax, and project spend",
            "basis": "first-week due diligence",
        },
    ]
    if invoice_registered is not True:
        checklist.append(
            {
                "task": "Confirm invoice registration status before tax-sensitive workflows",
                "basis": "invoice fact missing or not registered",
            }
        )

    prompts = [
        "Which revenue lines and project costs need source documents in week one?",
        "Which subsidies, loans, or tax incentives has the customer already used?",
        "Are there related companies, officers, or prior names that change eligibility?",
    ]
    if industry:
        prompts.append(
            f"Confirm whether the stated industry ({industry}) matches actual operations."
        )
    if prefecture:
        prompts.append(f"Confirm operating sites and applications tied to {prefecture}.")

    risk_flags: list[dict[str, Any]] = []
    enforcement_count = facts.get("corp.enforcement_count") or facts.get("enforcement_count")
    if enforcement_count not in (None, "", 0, "0"):
        risk_flags.append({"level": "high", "flag": "enforcement history fact is present"})
    if facts.get("corp.close_date") or facts.get("close_date"):
        risk_flags.append({"level": "high", "flag": "corporate close-date fact is present"})
    if invoice_registered is False:
        risk_flags.append({"level": "medium", "flag": "invoice registration appears absent"})
    if not fact_rows:
        risk_flags.append({"level": "medium", "flag": "brief is based only on supplied profile"})

    next_calls = [
        {
            "call": "Evidence intake call",
            "goal": "Collect source documents for core facts and spending plan",
        },
        {
            "call": "Eligibility triage call",
            "goal": "Review candidate programs against company size, region, and project purpose",
        },
    ]
    if risk_flags:
        next_calls.append(
            {
                "call": "Risk review call",
                "goal": "Resolve red flags before application or advisory work",
            }
        )

    fetched_values = [str(row["fetched_at"]) for row in fact_rows if row.get("fetched_at")]
    return {
        "houjin_id": _normalize_houjin(payload.houjin_id),
        "customer_profile": {
            "name": name,
            "industry": industry,
            "prefecture": prefecture,
            "employees": employees,
            "capital_yen": capital,
        },
        "first_week_checklist": checklist,
        "due_diligence_prompts": prompts,
        "risk_flags": risk_flags,
        "recommended_next_calls": next_calls,
        "source_links": _source_links(fact_rows),
        "as_of": max(fetched_values) if fetched_values else datetime.now(UTC).isoformat(),
        "known_gaps": list(dict.fromkeys(known_gaps)),
    }


__all__ = ["router"]
