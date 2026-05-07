"""cross_reference_tools — MCP wrappers for the R8 cross-reference deep
link API (api/programs_full_context.py).

Three tools register at import time when ``AUTONOMATH_CROSS_REFERENCE_ENABLED``
(default ON) and ``settings.autonomath_enabled`` are both truthy:

  * ``program_full_context``
      Bundles the full primary-source context of a 制度 in 1 call:
      program metadata + 法令根拠 + 改正履歴 + 関連判例 + 同業 採択事例 +
      関連 行政処分 + 排他ルール. Wraps the same in-process logic as
      GET /v1/programs/{id}/full_context.

  * ``law_related_programs_cross``
      Reverse program graph from a single 法令: walks the supersession
      chain (both directions) and surfaces every program that cites
      the law (or any predecessor) plus a per-ref_kind histogram.

  * ``cases_by_industry_size_pref``
      3-axis 採択事例 narrow (JSIC × employees / capital × prefecture).
      Replaces the manual 4-call pattern (search_case_studies → 4
      filter passes) with a single bounded SQL query.

Hard constraints (memory ``feedback_no_operator_llm_api`` +
``feedback_destruction_free_organization`` + memory
``feedback_autonomath_no_api_use``):

  * NO Anthropic API self-call. Customer LLM is the consumer.
  * Pure SQLite + Python. No HTTP roundtrip — same in-process build
    helpers as the REST handlers.
  * §72 / §52 / §1 / §27 disclaimer envelope on every response.
  * Single ¥3 / req billing event regardless of section count.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.cross_reference")

# Env gate. Default ON; flip to "0" for one-flag rollback without redeploy.
_ENABLED = os.environ.get("AUTONOMATH_CROSS_REFERENCE_ENABLED", "1") == "1"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_jpintel_safe() -> sqlite3.Connection | dict[str, Any]:
    """Open jpintel.db. Returns conn or error envelope on failure."""
    try:
        from jpintel_mcp.db.session import connect

        return connect()
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"jpintel.db open failed: {exc}",
            retry_with=["search_programs"],
        )


# ---------------------------------------------------------------------------
# Tool 1 — program_full_context
# ---------------------------------------------------------------------------


def _program_full_context_impl(
    program_id: str,
    include_sections: list[str] | None = None,
    max_per_section: int = 10,
    industry_jsic: str | None = None,
    prefecture: str | None = None,
) -> dict[str, Any]:
    """Compose the cross-reference bundle in-process.

    Delegates to ``api.programs_full_context._build_full_context`` so the
    REST endpoint and the MCP tool stay in lock-step.
    """
    from jpintel_mcp.api.programs_full_context import (
        _ALLOWED_SECTIONS,
        _DEFAULT_SECTIONS,
        _FULL_CONTEXT_DISCLAIMER,
        _build_full_context,
    )

    pid = (program_id or "").strip()
    if not pid:
        return make_error(
            code="invalid_input",
            message="program_id must be a non-empty unified_id (UNI-...).",
            field="program_id",
        )

    requested = tuple(include_sections) if include_sections else _DEFAULT_SECTIONS
    bad = [s for s in requested if s not in _ALLOWED_SECTIONS]
    if bad:
        return make_error(
            code="invalid_input",
            message=(
                f"include_sections contains unknown values: {bad}. "
                f"Allowed: {sorted(_ALLOWED_SECTIONS)}."
            ),
            field="include_sections",
        )
    seen: list[str] = []
    for s in requested:
        if s not in seen:
            seen.append(s)
    capped_max = max(1, min(int(max_per_section or 10), 50))

    conn_or_err = _open_jpintel_safe()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    try:
        body, _missing, program_found = _build_full_context(
            conn,
            program_id=pid,
            include_sections=tuple(seen),
            max_per_section=capped_max,
            industry_jsic=industry_jsic,
            prefecture=prefecture,
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    if "program" in seen and not program_found:
        return make_error(
            code="not_found",
            message=(
                f"program_id={pid!r} not found in jpintel programs. Verify via search_programs."
            ),
            field="program_id",
        )

    body["_disclaimer"] = _FULL_CONTEXT_DISCLAIMER
    body.setdefault("_billing_unit", 1)
    return body


# ---------------------------------------------------------------------------
# Tool 2 — law_related_programs_cross
# ---------------------------------------------------------------------------


def _law_related_programs_cross_impl(
    law_id: str,
    include_superseded: bool = True,
    ref_kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Cross-revision reverse program lookup keyed by a single law.

    Walks ``laws.superseded_by_law_id`` both directions, then unions the
    program_law_refs hits across the chain. Returns the law header +
    chain ids + ref_kind histogram + paginated program list.
    """
    from jpintel_mcp.api.programs_full_context import _FULL_CONTEXT_DISCLAIMER

    lid = (law_id or "").strip()
    if not lid:
        return make_error(
            code="invalid_input",
            message="law_id must be a non-empty LAW-* canonical id.",
            field="law_id",
        )
    allowed_kinds = {"authority", "eligibility", "exclusion", "reference", "penalty"}
    if ref_kind is not None and ref_kind not in allowed_kinds:
        return make_error(
            code="invalid_input",
            message=(f"ref_kind must be one of {sorted(allowed_kinds)}, got {ref_kind!r}"),
            field="ref_kind",
        )
    capped_limit = max(1, min(int(limit or 50), 200))
    capped_offset = max(0, int(offset or 0))

    conn_or_err = _open_jpintel_safe()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    try:
        law_row = conn.execute(
            "SELECT unified_id, law_title, law_number, law_type, ministry, "
            "       last_amended_date, revision_status, superseded_by_law_id, "
            "       full_text_url, source_url "
            "  FROM laws WHERE unified_id = ? LIMIT 1",
            (lid,),
        ).fetchone()
        if law_row is None:
            return make_error(
                code="not_found",
                message=f"law not found: {lid}",
                field="law_id",
                retry_with=["search_laws"],
            )

        chain_ids: list[str] = [lid]
        visited: set[str] = {lid}
        if include_superseded:
            cur = law_row["superseded_by_law_id"]
            steps = 0
            while cur and cur not in visited and steps < 16:
                chain_ids.append(cur)
                visited.add(cur)
                steps += 1
                try:
                    nrow = conn.execute(
                        "SELECT superseded_by_law_id FROM laws WHERE unified_id = ?",
                        (cur,),
                    ).fetchone()
                except sqlite3.Error:
                    break
                cur = nrow["superseded_by_law_id"] if nrow else None
            try:
                rrows = conn.execute(
                    "SELECT unified_id FROM laws WHERE superseded_by_law_id = ?",
                    (lid,),
                ).fetchall()
                for r in rrows:
                    if r["unified_id"] and r["unified_id"] not in visited:
                        chain_ids.append(r["unified_id"])
                        visited.add(r["unified_id"])
            except sqlite3.Error:
                pass

        placeholders = ",".join("?" for _ in chain_ids)
        where_parts = [f"plr.law_unified_id IN ({placeholders})"]
        params: list[Any] = list(chain_ids)
        if ref_kind is not None:
            where_parts.append("plr.ref_kind = ?")
            params.append(ref_kind)
        where_sql = " AND ".join(where_parts)

        histogram: dict[str, int] = dict.fromkeys(allowed_kinds, 0)
        try:
            for r in conn.execute(
                f"SELECT plr.ref_kind, COUNT(*) AS n "
                f"  FROM program_law_refs plr "
                f" WHERE plr.law_unified_id IN ({placeholders}) "
                f" GROUP BY plr.ref_kind",
                tuple(chain_ids),
            ).fetchall():
                histogram[r["ref_kind"]] = int(r["n"])
        except sqlite3.Error as exc:
            logger.warning("histogram query failed: %s", exc)

        try:
            (total,) = conn.execute(
                f"SELECT COUNT(*) FROM program_law_refs plr WHERE {where_sql}",
                tuple(params),
            ).fetchone()
        except sqlite3.Error:
            total = 0

        try:
            rows = conn.execute(
                f"SELECT plr.program_unified_id AS program_unified_id, "
                f"       plr.law_unified_id     AS law_unified_id, "
                f"       plr.ref_kind           AS ref_kind, "
                f"       plr.article_citation   AS article_citation, "
                f"       plr.source_url         AS source_url, "
                f"       plr.fetched_at         AS fetched_at, "
                f"       plr.confidence         AS confidence, "
                f"       p.primary_name         AS program_name, "
                f"       p.tier                 AS tier, "
                f"       p.prefecture           AS prefecture, "
                f"       p.authority_level      AS authority_level, "
                f"       p.program_kind         AS program_kind "
                f"  FROM program_law_refs plr "
                f"  LEFT JOIN programs p ON p.unified_id = plr.program_unified_id "
                f" WHERE {where_sql} "
                f" ORDER BY CASE plr.ref_kind "
                f"             WHEN 'authority'   THEN 0 "
                f"             WHEN 'eligibility' THEN 1 "
                f"             WHEN 'exclusion'   THEN 2 "
                f"             WHEN 'penalty'     THEN 3 "
                f"             WHEN 'reference'   THEN 4 "
                f"             ELSE 5 END, "
                f"          plr.confidence DESC, "
                f"          plr.program_unified_id ASC "
                f" LIMIT ? OFFSET ?",
                (*params, capped_limit, capped_offset),
            ).fetchall()
        except sqlite3.Error:
            rows = []

        results: list[dict[str, Any]] = []
        for r in rows:
            results.append(
                {
                    "program_unified_id": r["program_unified_id"],
                    "program_name": r["program_name"],
                    "law_unified_id": r["law_unified_id"],
                    "ref_kind": r["ref_kind"],
                    "article_citation": r["article_citation"],
                    "source_url": r["source_url"],
                    "fetched_at": r["fetched_at"],
                    "confidence": r["confidence"],
                    "tier": r["tier"],
                    "prefecture": r["prefecture"],
                    "authority_level": r["authority_level"],
                    "program_kind": r["program_kind"],
                }
            )

        body: dict[str, Any] = {
            "law": {
                "law_unified_id": law_row["unified_id"],
                "law_title": law_row["law_title"],
                "law_number": law_row["law_number"],
                "law_type": law_row["law_type"],
                "ministry": law_row["ministry"],
                "last_amended_date": law_row["last_amended_date"],
                "revision_status": law_row["revision_status"],
                "superseded_by_law_id": law_row["superseded_by_law_id"],
                "primary_url": law_row["full_text_url"] or law_row["source_url"],
            },
            "chain_law_unified_ids": chain_ids,
            "ref_kind_histogram": histogram,
            "include_superseded": include_superseded,
            "ref_kind_filter": ref_kind,
            "total": int(total or 0),
            "limit": capped_limit,
            "offset": capped_offset,
            "results": results,
            "_disclaimer": _FULL_CONTEXT_DISCLAIMER,
            "_billing_unit": 1,
        }
        return body
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()


# ---------------------------------------------------------------------------
# Tool 3 — cases_by_industry_size_pref
# ---------------------------------------------------------------------------


def _cases_by_industry_size_pref_impl(
    industry_jsic: str | None = None,
    prefecture: str | None = None,
    min_employees: int | None = None,
    max_employees: int | None = None,
    min_capital_yen: int | None = None,
    max_capital_yen: int | None = None,
    is_sole_proprietor: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """3-axis case_studies narrow."""
    from jpintel_mcp.api.programs_full_context import (
        _FULL_CONTEXT_DISCLAIMER,
        _json_list,
        _truncate,
    )

    if min_employees is not None and max_employees is not None and min_employees > max_employees:
        return make_error(
            code="invalid_input",
            message=(f"min_employees ({min_employees}) > max_employees ({max_employees})."),
            field="min_employees",
        )
    if (
        min_capital_yen is not None
        and max_capital_yen is not None
        and min_capital_yen > max_capital_yen
    ):
        return make_error(
            code="invalid_input",
            message=(f"min_capital_yen ({min_capital_yen}) > max_capital_yen ({max_capital_yen})."),
            field="min_capital_yen",
        )

    capped_limit = max(1, min(int(limit or 20), 100))
    capped_offset = max(0, int(offset or 0))

    conn_or_err = _open_jpintel_safe()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    try:
        where: list[str] = []
        params: list[Any] = []
        if industry_jsic:
            where.append("industry_jsic LIKE ?")
            params.append(f"{industry_jsic}%")
        if prefecture:
            where.append("prefecture = ?")
            params.append(prefecture)
        if min_employees is not None:
            where.append("COALESCE(employees, -1) >= ?")
            params.append(min_employees)
        if max_employees is not None:
            where.append("COALESCE(employees, 99999999) <= ?")
            params.append(max_employees)
        if min_capital_yen is not None:
            where.append("COALESCE(capital_yen, -1) >= ?")
            params.append(min_capital_yen)
        if max_capital_yen is not None:
            where.append("COALESCE(capital_yen, " + str(10**18) + ") <= ?")
            params.append(max_capital_yen)
        if is_sole_proprietor is not None:
            where.append("COALESCE(is_sole_proprietor, 0) = ?")
            params.append(1 if is_sole_proprietor else 0)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        try:
            (total,) = conn.execute(
                f"SELECT COUNT(*) FROM case_studies{where_sql}",
                tuple(params),
            ).fetchone()
        except sqlite3.Error:
            total = 0

        try:
            rows = conn.execute(
                "SELECT case_id, company_name, houjin_bangou, is_sole_proprietor, "
                "       prefecture, municipality, industry_jsic, industry_name, "
                "       employees, founded_year, capital_yen, "
                "       case_title, case_summary, programs_used_json, "
                "       total_subsidy_received_yen, outcomes_json, patterns_json, "
                "       publication_date, source_url, source_excerpt, "
                "       fetched_at, confidence "
                f"  FROM case_studies{where_sql} "
                " ORDER BY publication_date DESC NULLS LAST, case_id ASC "
                " LIMIT ? OFFSET ?",
                (*params, capped_limit, capped_offset),
            ).fetchall()
        except sqlite3.Error:
            rows = []

        results: list[dict[str, Any]] = []
        for r in rows:
            sole = r["is_sole_proprietor"]
            results.append(
                {
                    "case_id": r["case_id"],
                    "company_name": r["company_name"],
                    "houjin_bangou": r["houjin_bangou"],
                    "is_sole_proprietor": None if sole is None else bool(sole),
                    "prefecture": r["prefecture"],
                    "municipality": r["municipality"],
                    "industry_jsic": r["industry_jsic"],
                    "industry_name": r["industry_name"],
                    "employees": r["employees"],
                    "founded_year": r["founded_year"],
                    "capital_yen": r["capital_yen"],
                    "case_title": r["case_title"],
                    "case_summary": _truncate(r["case_summary"], 400),
                    "programs_used": _json_list(r["programs_used_json"]),
                    "total_subsidy_received_yen": r["total_subsidy_received_yen"],
                    "publication_date": r["publication_date"],
                    "source_url": r["source_url"],
                    "source_excerpt": _truncate(r["source_excerpt"], 200),
                    "confidence": r["confidence"],
                }
            )

        return {
            "filters": {
                "industry_jsic": industry_jsic,
                "prefecture": prefecture,
                "min_employees": min_employees,
                "max_employees": max_employees,
                "min_capital_yen": min_capital_yen,
                "max_capital_yen": max_capital_yen,
                "is_sole_proprietor": is_sole_proprietor,
            },
            "total": int(total or 0),
            "limit": capped_limit,
            "offset": capped_offset,
            "results": results,
            "_disclaimer": _FULL_CONTEXT_DISCLAIMER,
            "_billing_unit": 1,
        }
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def program_full_context(
        program_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description=("Program canonical id (UNI-...) on jpintel.programs."),
            ),
        ],
        include_sections: Annotated[
            list[str] | None,
            Field(
                None,
                description=(
                    "Sections to include. Allowed: program, law_basis, "
                    "court_decisions, case_studies, enforcement_cases, "
                    "exclusion_rules. Defaults to all 6."
                ),
            ),
        ] = None,
        max_per_section: Annotated[
            int,
            Field(
                10,
                ge=1,
                le=50,
                description="Per-section row cap (1..50, default 10).",
            ),
        ] = 10,
        industry_jsic: Annotated[
            str | None,
            Field(
                None,
                max_length=10,
                description=(
                    "JSIC industry prefix (overrides the program-derived "
                    "JSIC for case_studies narrowing)."
                ),
            ),
        ] = None,
        prefecture: Annotated[
            str | None,
            Field(
                None,
                max_length=10,
                description=(
                    "Prefecture filter for case_studies narrowing "
                    "(overrides program-derived prefecture)."
                ),
            ),
        ] = None,
    ) -> dict[str, Any]:
        """[CROSS-REF R8] Bundle the full primary-source context of a 制度 in 1 call: program metadata + 法令根拠 + 改正履歴 + 関連判例 + 同業 採択事例 + 関連 行政処分 + 排他ルール. Pure SQLite over jpintel + best-effort autonomath am_amendment_diff. ¥3/req. §72/§52/§1/§27 fence."""
        return _program_full_context_impl(
            program_id=program_id,
            include_sections=include_sections,
            max_per_section=max_per_section,
            industry_jsic=industry_jsic,
            prefecture=prefecture,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def law_related_programs_cross(
        law_id: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Law canonical id (LAW-...) on jpintel.laws.",
            ),
        ],
        include_superseded: Annotated[
            bool,
            Field(
                True,
                description=(
                    "Walk superseded_by_law_id chain (both directions). "
                    "Default true so the customer LLM gets the full "
                    "historical surface."
                ),
            ),
        ] = True,
        ref_kind: Annotated[
            str | None,
            Field(
                None,
                max_length=20,
                description=(
                    "Filter by citation kind (authority / eligibility / "
                    "exclusion / reference / penalty)."
                ),
            ),
        ] = None,
        limit: Annotated[int, Field(50, ge=1, le=200)] = 50,
        offset: Annotated[int, Field(0, ge=0)] = 0,
    ) -> dict[str, Any]:
        """[CROSS-REF R8] Reverse program lookup for a 法令: walks supersession chain (both directions) and surfaces every program citing the law (or a predecessor) with a ref_kind histogram. Pure SQLite over laws + program_law_refs. ¥3/req. §72/§52/§1 fence."""
        return _law_related_programs_cross_impl(
            law_id=law_id,
            include_superseded=include_superseded,
            ref_kind=ref_kind,
            limit=limit,
            offset=offset,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def cases_by_industry_size_pref(
        industry_jsic: Annotated[
            str | None,
            Field(
                None,
                max_length=10,
                description="JSIC industry prefix (e.g. 'A' / '05' / '0111').",
            ),
        ] = None,
        prefecture: Annotated[
            str | None,
            Field(
                None,
                max_length=10,
                description="Prefecture exact match (e.g. '東京都').",
            ),
        ] = None,
        min_employees: Annotated[
            int | None,
            Field(None, ge=0, le=1_000_000),
        ] = None,
        max_employees: Annotated[
            int | None,
            Field(None, ge=0, le=1_000_000),
        ] = None,
        min_capital_yen: Annotated[
            int | None,
            Field(None, ge=0, le=10**14),
        ] = None,
        max_capital_yen: Annotated[
            int | None,
            Field(None, ge=0, le=10**14),
        ] = None,
        is_sole_proprietor: Annotated[
            bool | None,
            Field(None, description="Filter to (or exclude) 個人事業主 rows."),
        ] = None,
        limit: Annotated[int, Field(20, ge=1, le=100)] = 20,
        offset: Annotated[int, Field(0, ge=0)] = 0,
    ) -> dict[str, Any]:
        """[CROSS-REF R8] 採択事例 narrowed by 業種 (JSIC) × 規模 (employees / capital) × 都道府県 in 1 call. Pure SQLite over case_studies. ¥3/req. NOT sensitive (1次資料の検索)."""
        return _cases_by_industry_size_pref_impl(
            industry_jsic=industry_jsic,
            prefecture=prefecture,
            min_employees=min_employees,
            max_employees=max_employees,
            min_capital_yen=min_capital_yen,
            max_capital_yen=max_capital_yen,
            is_sole_proprietor=is_sole_proprietor,
            limit=limit,
            offset=offset,
        )


__all__ = [
    "_program_full_context_impl",
    "_law_related_programs_cross_impl",
    "_cases_by_industry_size_pref_impl",
]
