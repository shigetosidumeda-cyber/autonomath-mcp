"""POST /v1/intel/competitor_landscape — deterministic peer landscape.

The endpoint is intentionally rules-based: no LLM calls, only SQLite reads
from the autonomath substrate plus small Python aggregations. Missing optional
tables degrade into `known_gaps` / `data_quality.missing_tables` instead of a
500 so thin customer installations still get an honest envelope.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import time
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_competitor_landscape")

router = APIRouter(prefix="/v1/intel", tags=["intel"])

_DISCLAIMER = (
    "本 competitor_landscape は houjin_master / adoption / enforcement / "
    "invoice substrate を機械的に集計した統計的 peer landscape であり、"
    "同業認定・市場シェア推定・採択率予測・法務/税務判断ではありません。"
    "広告・営業利用時は景表法の優良誤認/有利誤認に留意し、確定判断は資格を"
    "有する専門家へ確認してください。"
)


class CompetitorLandscapeRequest(BaseModel):
    houjin_id: str | None = Field(
        None,
        min_length=13,
        max_length=14,
        description="13-digit 法人番号, with or without invoice 'T' prefix.",
    )
    industry: str | None = Field(
        None,
        min_length=1,
        max_length=40,
        description="JSIC major letter or industry label used as seed.",
    )
    prefecture: str | None = Field(None, min_length=1, max_length=20)
    peer_limit: int = Field(5, ge=1, le=10)


def _normalize_houjin(raw: str | None) -> str | None:
    if not raw:
        return None
    s = re.sub(r"[\s\-,　]", "", str(raw).strip().lstrip("Tt"))
    if not s.isdigit() or len(s) != 13:
        return None
    return s


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except sqlite3.Error:
        return set()


def _missing(missing_tables: list[str], table: str) -> None:
    if table not in missing_tables:
        missing_tables.append(table)


def _open_autonomath() -> sqlite3.Connection | None:
    from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

    try:
        return connect_autonomath()
    except (FileNotFoundError, sqlite3.Error) as exc:
        logger.warning("autonomath unavailable for competitor_landscape: %s", exc)
        return None


def _first_existing(cols: set[str], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in cols:
            return name
    return None


def _fetch_seed(
    conn: sqlite3.Connection,
    *,
    houjin_id: str | None,
    industry: str | None,
    prefecture: str | None,
    missing_tables: list[str],
) -> dict[str, Any]:
    seed = {
        "houjin_id": houjin_id,
        "name": None,
        "industry": industry,
        "prefecture": prefecture,
    }
    if not houjin_id:
        return seed
    if not _table_exists(conn, "houjin_master"):
        _missing(missing_tables, "houjin_master")
        return seed

    cols = _columns(conn, "houjin_master")
    name_col = _first_existing(cols, ("normalized_name", "name", "corporate_name"))
    industry_col = _first_existing(cols, ("jsic_major", "industry", "industry_raw"))
    pref_col = _first_existing(cols, ("prefecture", "prefecture_name"))
    select_cols = ["houjin_bangou"]
    for col in (name_col, industry_col, pref_col):
        if col and col not in select_cols:
            select_cols.append(col)
    try:
        row = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM houjin_master WHERE houjin_bangou=? LIMIT 1",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("seed lookup failed: %s", exc)
        return seed
    if not row:
        return seed
    if name_col:
        seed["name"] = row[name_col]
    if industry_col and not seed["industry"]:
        seed["industry"] = row[industry_col]
    if pref_col and not seed["prefecture"]:
        seed["prefecture"] = row[pref_col]
    return seed


def _fetch_peers(
    conn: sqlite3.Connection,
    *,
    seed: dict[str, Any],
    limit: int,
    missing_tables: list[str],
) -> list[dict[str, Any]]:
    if not _table_exists(conn, "houjin_master"):
        _missing(missing_tables, "houjin_master")
        return []

    cols = _columns(conn, "houjin_master")
    name_col = _first_existing(cols, ("normalized_name", "name", "corporate_name"))
    industry_col = _first_existing(cols, ("jsic_major", "industry", "industry_raw"))
    pref_col = _first_existing(cols, ("prefecture", "prefecture_name"))
    select_cols = ["houjin_bangou"]
    for col in (name_col, industry_col, pref_col):
        if col and col not in select_cols:
            select_cols.append(col)

    where: list[str] = []
    params: list[Any] = []
    if seed.get("houjin_id"):
        where.append("houjin_bangou <> ?")
        params.append(seed["houjin_id"])
    if industry_col and seed.get("industry"):
        where.append(f"{industry_col} = ?")
        params.append(seed["industry"])
    if pref_col and seed.get("prefecture"):
        where.append(f"{pref_col} = ?")
        params.append(seed["prefecture"])
    if not where:
        where.append("1=1")

    try:
        rows = conn.execute(
            f"SELECT {', '.join(select_cols)} FROM houjin_master "
            f"WHERE {' AND '.join(where)} ORDER BY houjin_bangou ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("peer lookup failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        hid = str(row["houjin_bangou"])
        out.append(
            {
                "houjin_id": hid,
                "name": row[name_col] if name_col else None,
                "industry": row[industry_col] if industry_col else None,
                "prefecture": row[pref_col] if pref_col else None,
                "adoption": {"count": 0, "total_amount_yen": 0, "top_programs": []},
                "enforcement": {"count": 0, "latest_action_date": None, "kinds": []},
                "invoice": {"registered": None, "status": "unknown"},
                "differentiators": [],
            }
        )
    return out


def _apply_adoption(
    conn: sqlite3.Connection, peers: list[dict[str, Any]], missing: list[str]
) -> None:
    if not peers:
        return
    if not _table_exists(conn, "jpi_adoption_records"):
        _missing(missing, "jpi_adoption_records")
        return
    cols = _columns(conn, "jpi_adoption_records")
    program_col = _first_existing(cols, ("program_id", "program_id_hint", "program_name_raw"))
    amount_col = _first_existing(cols, ("amount_granted_yen", "amount_project_total_yen"))
    ids = [p["houjin_id"] for p in peers]
    placeholders = ",".join(["?"] * len(ids))
    amount_expr = f"COALESCE(SUM({amount_col}), 0)" if amount_col else "0"
    program_expr = program_col or "NULL"
    try:
        rows = conn.execute(
            "SELECT houjin_bangou, COUNT(*) AS c, "
            f"{amount_expr} AS amount, GROUP_CONCAT(DISTINCT {program_expr}) AS programs "
            f"FROM jpi_adoption_records WHERE houjin_bangou IN ({placeholders}) "
            "GROUP BY houjin_bangou",
            ids,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("adoption signal query failed: %s", exc)
        return
    by_id = {p["houjin_id"]: p for p in peers}
    for row in rows:
        peer = by_id.get(str(row["houjin_bangou"]))
        if not peer:
            continue
        programs = [x for x in str(row["programs"] or "").split(",") if x][:5]
        peer["adoption"] = {
            "count": int(row["c"] or 0),
            "total_amount_yen": int(row["amount"] or 0),
            "top_programs": programs,
        }


def _apply_enforcement(
    conn: sqlite3.Connection, peers: list[dict[str, Any]], missing: list[str]
) -> None:
    if not peers:
        return
    if not _table_exists(conn, "am_enforcement_detail"):
        _missing(missing, "am_enforcement_detail")
        return
    cols = _columns(conn, "am_enforcement_detail")
    kind_col = _first_existing(cols, ("kind", "action_kind", "enforcement_kind"))
    date_col = _first_existing(cols, ("action_date", "published_at", "date"))
    ids = [p["houjin_id"] for p in peers]
    placeholders = ",".join(["?"] * len(ids))
    kind_expr = f"GROUP_CONCAT(DISTINCT {kind_col})" if kind_col else "NULL"
    date_expr = f"MAX({date_col})" if date_col else "NULL"
    try:
        rows = conn.execute(
            "SELECT houjin_bangou, COUNT(*) AS c, "
            f"{date_expr} AS latest, {kind_expr} AS kinds "
            f"FROM am_enforcement_detail WHERE houjin_bangou IN ({placeholders}) "
            "GROUP BY houjin_bangou",
            ids,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("enforcement signal query failed: %s", exc)
        return
    by_id = {p["houjin_id"]: p for p in peers}
    for row in rows:
        peer = by_id.get(str(row["houjin_bangou"]))
        if peer:
            peer["enforcement"] = {
                "count": int(row["c"] or 0),
                "latest_action_date": row["latest"],
                "kinds": [x for x in str(row["kinds"] or "").split(",") if x],
            }


def _apply_invoice(
    conn: sqlite3.Connection, peers: list[dict[str, Any]], missing: list[str]
) -> None:
    if not peers:
        return
    table = "invoice_registrants" if _table_exists(conn, "invoice_registrants") else None
    if table is None and _table_exists(conn, "jpi_invoice_registrants"):
        table = "jpi_invoice_registrants"
    if table is None:
        _missing(missing, "invoice_registrants")
        return
    cols = _columns(conn, table)
    id_col = _first_existing(cols, ("houjin_bangou", "corporate_number", "registrant_number"))
    status_col = _first_existing(cols, ("status", "registration_status"))
    if not id_col:
        return
    ids = [p["houjin_id"] for p in peers]
    t_ids = [f"T{x}" for x in ids]
    placeholders = ",".join(["?"] * (len(ids) + len(t_ids)))
    status_expr = status_col or "'registered'"
    try:
        rows = conn.execute(
            f"SELECT {id_col} AS hid, {status_expr} AS status "
            f"FROM {table} WHERE {id_col} IN ({placeholders})",
            (*ids, *t_ids),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("invoice signal query failed: %s", exc)
        return
    by_id = {p["houjin_id"]: p for p in peers}
    for row in rows:
        hid = _normalize_houjin(str(row["hid"]))
        peer = by_id.get(hid or "")
        if peer:
            status = str(row["status"] or "registered")
            peer["invoice"] = {
                "registered": status.lower() not in {"revoked", "inactive", "取消"},
                "status": status,
            }


def _add_differentiators(peers: list[dict[str, Any]]) -> list[str]:
    if not peers:
        return []
    avg_adoption = sum(p["adoption"]["count"] for p in peers) / len(peers)
    avg_amount = sum(p["adoption"]["total_amount_yen"] for p in peers) / len(peers)
    landscape: list[str] = []
    registered = sum(1 for p in peers if p["invoice"]["registered"] is True)
    enforcement_count = sum(1 for p in peers if p["enforcement"]["count"] > 0)
    for p in peers:
        diffs: list[str] = []
        if p["adoption"]["count"] > avg_adoption:
            diffs.append("above_peer_average_adoption")
        if p["adoption"]["total_amount_yen"] > avg_amount:
            diffs.append("above_peer_average_amount")
        if p["enforcement"]["count"] > 0:
            diffs.append("enforcement_footprint")
        if p["invoice"]["registered"] is True:
            diffs.append("invoice_registered")
        p["differentiators"] = diffs
    if registered:
        landscape.append(f"{registered}/{len(peers)} peers have invoice registration signal")
    if enforcement_count:
        landscape.append(f"{enforcement_count}/{len(peers)} peers have enforcement signal")
    if avg_adoption:
        landscape.append(f"average peer adoption count={round(avg_adoption, 2)}")
    return landscape


def _build_envelope(
    conn: sqlite3.Connection | None, payload: CompetitorLandscapeRequest
) -> dict[str, Any]:
    missing: list[str] = []
    known_gaps: list[str] = []
    if conn is None:
        missing = ["autonomath.db"]
        known_gaps.append("autonomath.db unavailable; returned seed-only sparse envelope")
        return {
            "seed": {
                "houjin_id": _normalize_houjin(payload.houjin_id),
                "name": None,
                "industry": payload.industry,
                "prefecture": payload.prefecture,
            },
            "peers": [],
            "differentiators": [],
            "signals": {"adoption": None, "enforcement": None, "invoice": None},
            "known_gaps": known_gaps,
            "data_quality": {"missing_tables": missing, "peer_count": 0},
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 1,
        }

    houjin_id = _normalize_houjin(payload.houjin_id) if payload.houjin_id else None
    seed = _fetch_seed(
        conn,
        houjin_id=houjin_id,
        industry=payload.industry,
        prefecture=payload.prefecture,
        missing_tables=missing,
    )
    peers = _fetch_peers(conn, seed=seed, limit=payload.peer_limit, missing_tables=missing)
    _apply_adoption(conn, peers, missing)
    _apply_enforcement(conn, peers, missing)
    _apply_invoice(conn, peers, missing)
    differentiators = _add_differentiators(peers)

    if not peers:
        known_gaps.append("no peer rows matched the supplied seed")
    for table in sorted(set(missing)):
        known_gaps.append(f"{table} unavailable; related signals are partial")

    return {
        "seed": seed,
        "peers": peers,
        "differentiators": differentiators,
        "signals": {
            "adoption": {"covered_peers": sum(1 for p in peers if p["adoption"]["count"] > 0)},
            "enforcement": {
                "covered_peers": sum(1 for p in peers if p["enforcement"]["count"] > 0)
            },
            "invoice": {
                "registered_peers": sum(1 for p in peers if p["invoice"]["registered"] is True)
            },
        },
        "known_gaps": known_gaps,
        "data_quality": {"missing_tables": sorted(set(missing)), "peer_count": len(peers)},
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }


@router.post(
    "/competitor_landscape",
    summary="Competitor landscape from houjin / industry / prefecture seed (NO LLM)",
)
def post_competitor_landscape(
    payload: Annotated[CompetitorLandscapeRequest, Body(...)],
    conn: DbDep,
    ctx: ApiContextDep,
) -> dict[str, Any]:
    _t0 = time.perf_counter()
    if not payload.houjin_id and not payload.industry and not payload.prefecture:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "missing_required_field",
                "field": "houjin_id|industry|prefecture",
                "message": "supply at least one seed field",
            },
        )
    normalized = _normalize_houjin(payload.houjin_id) if payload.houjin_id else None
    if payload.houjin_id and normalized is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_id",
                "field": "houjin_id",
                "message": "houjin_id must be 13 digits, with or without T prefix",
            },
        )

    am_conn = _open_autonomath()
    body = _build_envelope(am_conn, payload)
    with contextlib.suppress(sqlite3.Error):
        body = attach_corpus_snapshot(body, conn)
    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.competitor_landscape",
        latency_ms=latency_ms,
        result_count=len(body.get("peers") or []),
        params={"houjin_id_present": bool(payload.houjin_id), "peer_limit": payload.peer_limit},
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.competitor_landscape",
        request_params={
            "houjin_id": normalized,
            "industry": payload.industry,
            "prefecture": payload.prefecture,
            "peer_limit": payload.peer_limit,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )
    return body


__all__ = ["router"]
