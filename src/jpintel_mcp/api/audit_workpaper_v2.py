"""POST /v1/audit/workpaper — Wave 43.2.4 Dim D REST companion to the
``compose_audit_workpaper`` MCP tool.

Composes ``intel_houjin_full`` + ``apply_eligibility_chain_am`` +
``cross_check_jurisdiction`` + ``amendment_alert`` into a single year-end
audit workpaper substrate for one 法人 in one fiscal year. The route
delivers the same envelope the MCP path emits, so MCP and REST callers
share one contract.

Pricing: **1 req = 5 unit** (¥15 / 税込 ¥16.50). Documented in the route
description + ``_billing_unit=5`` in the response body.

Sensitive: 税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 /
行政書士法 §1. ``_disclaimer`` envelope is non-negotiable.

NO LLM call. Pure SQLite + Python projection — mirrors the MCP-side
composer in ``audit_workpaper_v2``.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api.audit import WorkpaperRequest, render_workpaper
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.audit_workpaper_v2")

router = APIRouter(prefix="/v1/audit", tags=["audit (税理士・会計士)"])
_DEFAULT_BACKGROUND_TASKS = BackgroundTasks()

_DISCLAIMER = (
    "本 audit/workpaper response は houjin_master / am_adopted_company_features /"
    " am_enforcement_detail / invoice_registrants / am_amendment_diff /"
    " jpi_tax_rulesets を機械的に SQL 結合した **公開情報の監査調書サブストレート**"
    "であり、税理士法 §52 (税務代理) ・公認会計士法 §47条の2 (会計士・監査法人の業務)"
    "・弁護士法 §72 (法律事務) ・行政書士法 §1 (申請代理) のいずれにも該当しません。"
    "監査判断・税額計算・申告書作成は資格を有する税理士・公認会計士の責任で行ってください。"
    "当ツール出力をそのまま監査調書として提出することは禁止です。"
)


class AuditWorkpaperRequest(BaseModel):
    client_houjin_bangou: Annotated[
        str,
        Field(
            description="13-digit 法人番号 (with or without 'T' prefix).",
            min_length=13,
            max_length=14,
        ),
    ]
    fiscal_year: Annotated[
        int,
        Field(
            description="FY start year (e.g. 2025 = FY2025 = 2025-04-01..2026-03-31).",
            ge=2000,
            le=2100,
        ),
    ]


def _autonomath_db_path() -> Path:
    """Resolve autonomath.db path. Mirrors api/intel_houjin_full helper."""
    try:
        p = settings.autonomath_db_path
        if isinstance(p, Path):
            return p
        return Path(str(p))
    except AttributeError:
        return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open autonomath.db RO. Returns None when missing."""
    p = _autonomath_db_path()
    if not p.exists() or p.stat().st_size == 0:
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
        return conn
    except sqlite3.OperationalError:
        return None


def _normalize_houjin(raw: str) -> str | None:
    """13-digit 法人番号 canonical normaliser."""
    s = str(raw or "").strip().lstrip("Tt")
    for ch in "- ,　":
        s = s.replace(ch, "")
    if not s.isdigit() or len(s) != 13:
        return None
    return s


def _fy_window(fiscal_year: int) -> tuple[str, str]:
    return f"{fiscal_year:04d}-04-01", f"{fiscal_year + 1:04d}-04-01"


def _build_workpaper(
    conn: sqlite3.Connection, houjin_id: str, fiscal_year: int
) -> dict[str, Any] | None:
    fy_start, fy_stop = _fy_window(fiscal_year)
    fy_end = f"{fiscal_year + 1:04d}-03-31"

    # --- houjin_meta ----------------------------------------------------
    try:
        meta_row = conn.execute(
            """
            SELECT houjin_bangou, normalized_name, address_normalized,
                   prefecture, municipality, corporation_type,
                   total_adoptions, total_received_yen
              FROM jpi_houjin_master
             WHERE houjin_bangou = ? LIMIT 1
            """,
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("workpaper rest meta lookup failed: %s", exc)
        return None
    if meta_row is None:
        return None
    meta = {
        "houjin_bangou": meta_row["houjin_bangou"],
        "name": meta_row["normalized_name"],
        "address": meta_row["address_normalized"],
        "prefecture": meta_row["prefecture"],
        "municipality": meta_row["municipality"],
        "corporation_type": meta_row["corporation_type"],
        "jsic_major": None,
        "total_adoptions": meta_row["total_adoptions"],
        "total_received_yen": meta_row["total_received_yen"],
    }

    # --- fy_adoptions ---------------------------------------------------
    adoptions: list[dict[str, Any]] = []
    with contextlib.suppress(sqlite3.Error):
        rows = conn.execute(
            """
            SELECT program_id, program_name_raw, company_name_raw, announced_at,
                   amount_granted_yen
              FROM jpi_adoption_records
             WHERE houjin_bangou = ?
               AND announced_at >= ?
               AND announced_at < ?
             ORDER BY announced_at DESC LIMIT 50
            """,
            (houjin_id, fy_start, fy_stop),
        ).fetchall()
        adoptions = [
            {
                "program_id": r["program_id"],
                "program_name": r["program_name_raw"],
                "applicant_name": r["company_name_raw"],
                "award_date": r["announced_at"],
                "amount_yen": r["amount_granted_yen"],
                "fiscal_year": fiscal_year,
                "announce_date": r["announced_at"],
            }
            for r in rows
        ]

    # --- fy_enforcement -------------------------------------------------
    enforcement: list[dict[str, Any]] = []
    with contextlib.suppress(sqlite3.Error):
        rows = conn.execute(
            """
            SELECT enforcement_id, enforcement_kind, issuance_date, amount_yen,
                   reason_summary, source_url
              FROM am_enforcement_detail
             WHERE houjin_bangou = ?
               AND issuance_date BETWEEN ? AND ?
             ORDER BY issuance_date DESC LIMIT 30
            """,
            (houjin_id, fy_start, fy_end),
        ).fetchall()
        enforcement = [
            {
                "detail_id": r["enforcement_id"],
                "enforcement_kind": r["enforcement_kind"],
                "enforcement_date": r["issuance_date"],
                "amount_yen": r["amount_yen"],
                "summary": r["reason_summary"],
                "source_url": r["source_url"],
            }
            for r in rows
        ]

    # --- jurisdiction ---------------------------------------------------
    jurisdiction: dict[str, Any] = {
        "registered_prefecture": meta_row["prefecture"],
        "invoice_prefecture": None,
        "operational_top_prefecture": None,
        "mismatch": False,
    }
    with contextlib.suppress(sqlite3.Error):
        inv = conn.execute(
            "SELECT prefecture FROM jpi_invoice_registrants "
            "WHERE houjin_bangou = ? ORDER BY registered_date DESC LIMIT 1",
            (houjin_id,),
        ).fetchone()
        if inv:
            jurisdiction["invoice_prefecture"] = inv["prefecture"]
        op = conn.execute(
            "SELECT prefecture FROM jpi_adoption_records "
            "WHERE houjin_bangou = ? AND prefecture IS NOT NULL "
            "GROUP BY prefecture ORDER BY COUNT(*) DESC LIMIT 1",
            (houjin_id,),
        ).fetchone()
        if op:
            jurisdiction["operational_top_prefecture"] = op["prefecture"]
    seen = {v for v in jurisdiction.values() if isinstance(v, str)}
    jurisdiction["mismatch"] = len(seen) > 1

    # --- amendment_alerts ----------------------------------------------
    amendment_alerts: list[dict[str, Any]] = []
    active_pids = [a["program_id"] for a in adoptions if isinstance(a.get("program_id"), str)]
    if active_pids:
        placeholders = ",".join("?" * len(active_pids))
        with contextlib.suppress(sqlite3.Error):
            amendment_alerts = [
                dict(r)
                for r in conn.execute(
                    f"""
                    SELECT entity_id, field_name, prev_value, new_value,
                           detected_at, source_url
                      FROM am_amendment_diff
                     WHERE entity_id IN ({placeholders})
                       AND detected_at >= ?
                       AND detected_at < ?
                     ORDER BY detected_at DESC LIMIT 60
                    """,
                    (*active_pids, fy_start, fy_stop),
                ).fetchall()
            ]

    flags: list[str] = []
    if enforcement:
        flags.append(f"FY内 行政処分 {len(enforcement)} 件 — 監査調書の重大記載項目候補。")
    if jurisdiction["mismatch"]:
        flags.append("登録/適格/操業 都道府県の3軸不一致 — 課税地・連結納税のヒアリング推奨。")
    if amendment_alerts:
        flags.append(
            f"FY内 当該採択先制度の改正イベント {len(amendment_alerts)} 件 — 適用要件再評価。"
        )
    if not adoptions:
        flags.append("FY内 採択 0 件 — 補助金収益認識の対象なし (前 FY 継続性は別途確認)。")

    return {
        "client_houjin_bangou": houjin_id,
        "fiscal_year": fiscal_year,
        "fy_window": {"start": fy_start, "end": fy_end},
        "houjin_meta": meta,
        "fy_adoptions": adoptions,
        "fy_enforcement": enforcement,
        "jurisdiction_breakdown": jurisdiction,
        "amendment_alerts": amendment_alerts,
        "counts": {
            "fy_adoption_count": len(adoptions),
            "fy_enforcement_count": len(enforcement),
            "fy_amendment_alert_count": len(amendment_alerts),
            "mismatch": jurisdiction["mismatch"],
        },
        "auditor_flags": flags,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 5,
    }


@router.post(
    "/workpaper",
    summary="Compose year-end audit workpaper for one 法人 × FY (5-unit composition)",
    description=(
        "Multi-hop composition for 税理士・会計士. Rolls up "
        "`intel_houjin_full` + `apply_eligibility_chain_am` + "
        "`cross_check_jurisdiction` + `amendment_alert` into ONE call.\n\n"
        "**Pricing:** 1 req = **5 unit** (¥15 / 税込 ¥16.50). The 5-unit "
        "price reflects the four fan-out subqueries this route collapses; "
        "the customer saves on manual fan-out (≥ 8 calls otherwise).\n\n"
        "Pure SQLite + Python projection. NO LLM call. **Sensitive:** "
        "税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / "
        "行政書士法 §1 — see `_disclaimer` envelope."
    ),
    responses={
        200: {"description": "Composed audit workpaper envelope."},
        404: {"description": "client_houjin_bangou not found in houjin_master."},
        422: {"description": "Malformed 法人番号 or fiscal_year out of range."},
    },
)
def post_audit_workpaper(
    request: Request,
    ctx: ApiContextDep,
    conn: DbDep,
    payload: AuditWorkpaperRequest | WorkpaperRequest,
    background_tasks: BackgroundTasks = _DEFAULT_BACKGROUND_TASKS,
    x_cost_cap_jpy: Annotated[str | None, Header(alias="X-Cost-Cap-JPY")] = None,
    _idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    if isinstance(payload, WorkpaperRequest):
        return render_workpaper(
            payload,
            request,
            conn,
            ctx,
            background_tasks,
            x_cost_cap_jpy,
            _idempotency_key,
        )

    t0 = time.perf_counter()
    hb = _normalize_houjin(payload.client_houjin_bangou)
    if hb is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_bangou",
                "field": "client_houjin_bangou",
                "message": (
                    f"client_houjin_bangou must be 13 digits "
                    f"(got {payload.client_houjin_bangou!r})."
                ),
            },
        )

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "autonomath_db_unreachable",
                "message": "autonomath.db is not currently mounted.",
            },
        )

    try:
        body = _build_workpaper(am_conn, hb, payload.fiscal_year)
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    if body is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "houjin_not_found",
                "field": "client_houjin_bangou",
                "message": (f"No houjin_master row for {hb}. Verify via /v1/houjin/{{bangou}}."),
            },
        )

    # log_usage: 5 units composition. Anonymous calls remain unmetered;
    # authenticated calls must leave a usage row instead of silently underbilling.
    if ctx.key_hash is not None:
        log_usage(
            conn,
            ctx,
            "audit_workpaper",
            request=request,
            quantity=5,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            strict_metering=ctx.metered,
        )
    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# Wave 46 dim 19 dim D sub-criterion: discovery surface (1 sub-axis lift)
# ---------------------------------------------------------------------------
#
# The POST /v1/audit/workpaper handler above is the *invocation* surface — it
# costs 5 units, requires a houjin lookup, and returns a fully composed
# substrate. The dim 19 audit flagged that there is no metadata surface a
# caller can probe to learn (a) which source tables the substrate joins,
# (b) which columns ship for each section, (c) the fence statutes the
# disclaimer cites, and (d) the billing unit, without paying for an
# invocation. GET /v1/audit/workpaper/schema fills that gap.
#
# Constraints (mirrors the dim F precedent at fact_signature_v2):
#   * Pure static dict — no SQLite open, no LLM call, no houjin lookup.
#   * 0 billing units (discoverability, not a billed compose).
#   * Same fence text & §52 / §47条の2 / §72 / 行政書士法 disclaimer.
#   * Single response, no pagination / no cursor (static payload).


_WORKPAPER_SCHEMA: dict[str, Any] = {
    "endpoint": "/v1/audit/workpaper",
    "method": "POST",
    "billing_unit_invoke": 5,
    "billing_unit_schema": 0,
    "composition_kind": "multi_hop_year_end_audit",
    "input_fields": [
        {
            "name": "client_houjin_bangou",
            "type": "string",
            "min_length": 13,
            "max_length": 14,
            "description": "13-digit 法人番号 (with or without 'T' prefix).",
        },
        {
            "name": "fiscal_year",
            "type": "integer",
            "min": 2000,
            "max": 2100,
            "description": ("FY start year (e.g. 2025 = FY2025 = 2025-04-01..2026-03-31)."),
        },
    ],
    "source_tables": [
        "jpi_houjin_master",
        "jpi_adoption_records",
        "am_enforcement_detail",
        "jpi_invoice_registrants",
        "am_amendment_diff",
    ],
    "output_sections": [
        {"key": "houjin_meta", "kind": "object", "row_cap": 1},
        {"key": "fy_adoptions", "kind": "array", "row_cap": 50},
        {"key": "fy_enforcement", "kind": "array", "row_cap": 30},
        {"key": "jurisdiction_breakdown", "kind": "object", "row_cap": 1},
        {"key": "amendment_alerts", "kind": "array", "row_cap": 60},
        {"key": "auditor_flags", "kind": "array", "row_cap": None},
    ],
    "fence_statutes": [
        "税理士法 §52",
        "公認会計士法 §47条の2",
        "弁護士法 §72",
        "行政書士法 §1",
    ],
    "non_negotiable": [
        "NO LLM call inside the compose path",
        "Output is a 公開情報 substrate, not an audit conclusion",
        "資格を有する税理士・会計士 must own the 判断",
    ],
    "disclaimer": _DISCLAIMER,
    "schema_version": "wave46-dim19-D-1",
}


@router.get(
    "/workpaper/schema",
    summary="Audit workpaper substrate schema (discovery, 0 units)",
    description=(
        "Discovery endpoint for the POST /v1/audit/workpaper composition. "
        "Returns the input field contract, source-table list, output "
        "section catalog, fence statutes, and disclaimer text **without** "
        "an invocation — agents can probe this before paying the 5-unit "
        "compose cost.\n\n"
        "**Pricing:** 0 unit. Pure static metadata, no SQLite open. "
        "**Sensitive:** Same §52 / §47条の2 / §72 / 行政書士法 §1 fence "
        "as the compose endpoint."
    ),
    responses={
        200: {"description": "Workpaper substrate schema envelope."},
    },
)
def get_audit_workpaper_schema(
    request: Request,
    ctx: ApiContextDep,
    conn: DbDep,
) -> JSONResponse:
    # Intentionally not metered: log_usage() clamps quantity < 1 to 1, while
    # this discovery surface is documented as 0 units.
    _ = (request, ctx, conn)
    return JSONResponse(content=_WORKPAPER_SCHEMA)
