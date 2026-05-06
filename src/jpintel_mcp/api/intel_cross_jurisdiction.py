"""POST /v1/intel/cross_jurisdiction — public-data jurisdiction mismatch surface."""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from jpintel_mcp.api.intel_risk_score import (
    _label_for_score,
    _normalize_houjin,
    _open_autonomath_ro,
    _table_exists,
)

logger = logging.getLogger("jpintel.api.intel_cross_jurisdiction")

router = APIRouter(prefix="/v1/intel", tags=["intel"])

_DISCLAIMER = (
    "本 cross_jurisdiction response は登記・適格請求書・採択/事業実態に関する"
    "公開情報を機械的に突合した参考情報です。税務代理ではありません / "
    "THIS IS NOT TAX REPRESENTATION。法的判断・所在地認定・申請代理・"
    "租税判断の代替ではありません。一次資料を確認し、必要に応じて税理士・"
    "弁護士・司法書士・行政書士へ相談してください。"
)


class CrossJurisdictionRequest(BaseModel):
    houjin_id: str = Field(
        ...,
        min_length=13,
        max_length=14,
        description="13-digit 法人番号 (with or without 'T' prefix).",
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _clean_pref(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def _first_pref(
    conn: sqlite3.Connection, table: str, *, houjin_id: str, column: str = "prefecture"
) -> str | None:
    if not _table_exists(conn, table):
        return None
    cols = _columns(conn, table)
    if column not in cols:
        return None
    where_col = "houjin_bangou" if "houjin_bangou" in cols else "entity_id"
    where_value = houjin_id if where_col == "houjin_bangou" else f"houjin:{houjin_id}"
    try:
        row = conn.execute(
            f"SELECT {column} FROM {table} WHERE {where_col} = ? AND {column} IS NOT NULL LIMIT 1",
            (where_value,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("jurisdiction first-pref query failed: %s", exc)
        return None
    return _clean_pref(row[column]) if row else None


def _distinct_prefs(
    conn: sqlite3.Connection, table: str, *, houjin_id: str, column: str = "prefecture"
) -> list[str]:
    if not _table_exists(conn, table):
        return []
    cols = _columns(conn, table)
    if column not in cols:
        return []
    where_col = "houjin_bangou" if "houjin_bangou" in cols else "entity_id"
    where_value = houjin_id if where_col == "houjin_bangou" else f"houjin:{houjin_id}"
    try:
        rows = conn.execute(
            f"SELECT DISTINCT {column} FROM {table} WHERE {where_col} = ? "
            f"AND {column} IS NOT NULL ORDER BY {column} LIMIT 50",
            (where_value,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("jurisdiction distinct-pref query failed: %s", exc)
        return []
    return [p for p in (_clean_pref(row[column]) for row in rows) if p]


def _invoice_pref(conn: sqlite3.Connection, houjin_id: str) -> tuple[str | None, str | None]:
    for table in ("jpi_invoice_registrants", "invoice_registrants"):
        if _table_exists(conn, table):
            return _first_pref(conn, table, houjin_id=houjin_id), table
    return None, None


def _operational_prefs(conn: sqlite3.Connection, houjin_id: str) -> tuple[list[str], list[str]]:
    tables_used: list[str] = []
    prefs: list[str] = []
    if _table_exists(conn, "am_adopted_company_features"):
        cols = _columns(conn, "am_adopted_company_features")
        if "dominant_prefecture" in cols:
            pref = _first_pref(
                conn,
                "am_adopted_company_features",
                houjin_id=houjin_id,
                column="dominant_prefecture",
            )
            if pref:
                prefs.append(pref)
                tables_used.append("am_adopted_company_features")
    if _table_exists(conn, "jpi_adoption_records"):
        adoption_prefs = _distinct_prefs(conn, "jpi_adoption_records", houjin_id=houjin_id)
        if adoption_prefs:
            prefs.extend(adoption_prefs)
            tables_used.append("jpi_adoption_records")
    return sorted(set(prefs)), tables_used


def _program_jurisdictions(conn: sqlite3.Connection, houjin_id: str) -> list[str]:
    if not _table_exists(conn, "jpi_adoption_records"):
        return []
    adoption_cols = _columns(conn, "jpi_adoption_records")
    program_col = "program_id" if "program_id" in adoption_cols else None
    if program_col is None:
        return []

    program_table = None
    for candidate in ("jpi_programs", "programs"):
        if _table_exists(conn, candidate) and {"unified_id", "prefecture"} <= _columns(
            conn, candidate
        ):
            program_table = candidate
            break
    if program_table is None:
        return []
    try:
        rows = conn.execute(
            f"SELECT DISTINCT p.prefecture "
            f"FROM jpi_adoption_records a "
            f"JOIN {program_table} p ON p.unified_id = a.{program_col} "
            f"WHERE a.houjin_bangou = ? AND p.prefecture IS NOT NULL "
            f"ORDER BY p.prefecture LIMIT 50",
            (houjin_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("program jurisdiction query failed: %s", exc)
        return []
    return [p for p in (_clean_pref(row["prefecture"]) for row in rows) if p]


def _build_mismatches(jurisdictions: dict[str, Any]) -> list[dict[str, Any]]:
    scalar = {
        "registered": jurisdictions.get("registered"),
        "invoice": jurisdictions.get("invoice"),
    }
    list_axes = {
        "operational": jurisdictions.get("operational") or [],
        "adoption": jurisdictions.get("adoption") or [],
    }
    axes: dict[str, set[str]] = {
        key: ({value} if value else set()) for key, value in scalar.items()
    }
    axes.update({key: set(values) for key, values in list_axes.items()})
    mismatches: list[dict[str, Any]] = []
    keys = list(axes)
    for idx, left in enumerate(keys):
        for right in keys[idx + 1 :]:
            if not axes[left] or not axes[right]:
                continue
            only_left = sorted(axes[left] - axes[right])
            only_right = sorted(axes[right] - axes[left])
            if only_left or only_right:
                mismatches.append(
                    {
                        "left": left,
                        "right": right,
                        "left_only": only_left,
                        "right_only": only_right,
                    }
                )
    return mismatches


@router.post(
    "/cross_jurisdiction",
    summary="Registered / invoice / operational / adoption jurisdiction mismatch surface",
)
def post_cross_jurisdiction(
    payload: Annotated[CrossJurisdictionRequest, Body(...)],
) -> dict[str, Any]:
    normalized = _normalize_houjin(payload.houjin_id)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_houjin_id", "field": "houjin_id"},
        )

    conn = _open_autonomath_ro()
    missing_tables: list[str] = []
    tables_used: list[str] = []
    jurisdictions: dict[str, Any] = {
        "registered": None,
        "invoice": None,
        "operational": [],
        "adoption": [],
    }
    if conn is None:
        missing_tables.extend(
            ["autonomath_db", "houjin_master", "jpi_invoice_registrants", "jpi_adoption_records"]
        )
    else:
        try:
            if _table_exists(conn, "houjin_master"):
                jurisdictions["registered"] = _first_pref(
                    conn, "houjin_master", houjin_id=normalized
                )
                tables_used.append("houjin_master")
            else:
                missing_tables.append("houjin_master")

            invoice, invoice_table = _invoice_pref(conn, normalized)
            jurisdictions["invoice"] = invoice
            if invoice_table:
                tables_used.append(invoice_table)
            else:
                missing_tables.append("jpi_invoice_registrants")

            operational, used = _operational_prefs(conn, normalized)
            jurisdictions["operational"] = operational
            tables_used.extend(used)
            if "jpi_adoption_records" not in used:
                missing_tables.append("jpi_adoption_records")

            adoption = _program_jurisdictions(conn, normalized)
            jurisdictions["adoption"] = sorted(set(adoption))
        finally:
            with contextlib.suppress(sqlite3.Error):
                conn.close()

    mismatches = _build_mismatches(jurisdictions)
    known_pref_count = len(
        {
            pref
            for pref in (
                [jurisdictions.get("registered"), jurisdictions.get("invoice")]
                + list(jurisdictions.get("operational") or [])
                + list(jurisdictions.get("adoption") or [])
            )
            if pref
        }
    )
    score = min(100.0, len(mismatches) * 15.0 + max(0, known_pref_count - 1) * 10.0)
    return {
        "houjin_id": normalized,
        "consistent": len(mismatches) == 0,
        "mismatch_count": len(mismatches),
        "risk_score": round(score, 2),
        "risk_label": _label_for_score(score),
        "jurisdictions": jurisdictions,
        "mismatches": mismatches,
        "data_coverage": {
            "tables_used": sorted(set(tables_used)),
            "missing_tables": sorted(set(missing_tables)),
            "sparse": bool(missing_tables),
        },
        "_disclaimer": _DISCLAIMER,
    }


__all__ = ["router"]
