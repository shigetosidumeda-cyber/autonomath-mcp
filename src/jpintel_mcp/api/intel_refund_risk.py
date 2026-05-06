"""POST /v1/intel/refund_risk — public-data refund / misuse risk surface."""

from __future__ import annotations

import contextlib
import datetime as _dt
import logging
import sqlite3
import unicodedata
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from jpintel_mcp.api.intel_risk_score import (
    _days_between,
    _decay_factor,
    _label_for_score,
    _normalize_houjin,
    _open_autonomath_ro,
    _refund_amount_points,
    _table_exists,
)

logger = logging.getLogger("jpintel.api.intel_refund_risk")

router = APIRouter(prefix="/v1/intel", tags=["intel"])

_DISCLAIMER = (
    "本 refund_risk response は公開情報 DB に含まれる返還・取消・不正受給・"
    "目的外使用に関する記録を rules-based に集計した参考指標です。"
    "信用格付けではありません / THIS IS NOT A CREDIT RATING。"
    "返還義務・取消処分・不正受給該当性・目的外使用該当性の確定判断ではなく、"
    "法的助言・税務代理・行政書士業務の代替ではありません。一次資料を確認し、"
    "必要に応じて弁護士・税理士・行政書士・認定支援機関へ相談してください。"
)

_REFUND_KINDS = {
    "grant_refund": "refund",
    "subsidy_exclude": "exclusion",
    "refund": "refund",
    "revocation": "cancellation",
    "cancellation": "cancellation",
    "fraud": "fraud",
    "misuse": "off_purpose_use",
}


class RefundRiskRequest(BaseModel):
    houjin_id: str = Field(
        ...,
        min_length=13,
        max_length=14,
        description="13-digit 法人番号 (with or without 'T' prefix).",
    )
    program_ids: list[str] = Field(
        default_factory=list,
        description="Program ids to compare against public refund / cancellation evidence.",
    )
    amount: int = Field(..., ge=0, description="Requested or reviewed amount in yen.")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _norm_program_id(raw: Any) -> str | None:
    if raw is None:
        return None
    s = unicodedata.normalize("NFKC", str(raw)).strip()
    return s or None


def _kind_bucket(kind: Any, text: Any = None) -> str | None:
    joined = f"{kind or ''} {text or ''}".lower()
    if not joined.strip():
        return None
    if "grant_refund" in joined or "返還" in joined or "refund" in joined:
        return "refund"
    if "subsidy_exclude" in joined or "除外" in joined:
        return "exclusion"
    if "取消" in joined or "取り消" in joined or "revok" in joined or "cancel" in joined:
        return "cancellation"
    if "不正" in joined or "fraud" in joined:
        return "fraud"
    if "目的外" in joined or "misuse" in joined:
        return "off_purpose_use"
    return _REFUND_KINDS.get(str(kind or "").strip())


def _fetch_refund_evidence(
    conn: sqlite3.Connection,
    *,
    houjin_id: str,
    requested_programs: set[str],
    ref_date: _dt.date,
) -> tuple[list[dict[str, Any]], list[str]]:
    missing: list[str] = []
    if not _table_exists(conn, "am_enforcement_detail"):
        return [], ["am_enforcement_detail"]

    cols = _columns(conn, "am_enforcement_detail")
    wanted = [
        c
        for c in (
            "issuance_date",
            "enforcement_kind",
            "amount_yen",
            "related_law_ref",
            "target_name",
            "program_id",
            "reason",
            "summary",
            "source_url",
        )
        if c in cols
    ]
    if not wanted:
        return [], missing

    where_col = "houjin_bangou" if "houjin_bangou" in cols else "entity_id"
    where_value = houjin_id if where_col == "houjin_bangou" else f"houjin:{houjin_id}"
    try:
        rows = conn.execute(
            f"SELECT {', '.join(wanted)} FROM am_enforcement_detail "
            f"WHERE {where_col} = ? ORDER BY "
            f"{'issuance_date' if 'issuance_date' in cols else 'rowid'} DESC LIMIT 100",
            (where_value,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("refund evidence query failed: %s", exc)
        return [], missing

    evidence: list[dict[str, Any]] = []
    for row in rows:
        rd = dict(row)
        bucket = _kind_bucket(
            rd.get("enforcement_kind"),
            " ".join(str(rd.get(k) or "") for k in ("reason", "summary", "target_name")),
        )
        if bucket is None:
            continue
        program_id = _norm_program_id(rd.get("program_id") or rd.get("related_law_ref"))
        program_overlap = bool(program_id and program_id in requested_programs)
        if requested_programs and program_id and not program_overlap:
            continue
        amount_yen = rd.get("amount_yen")
        try:
            amount_int = int(amount_yen) if amount_yen is not None else None
        except (TypeError, ValueError):
            amount_int = None
        decay = _decay_factor(_days_between(rd.get("issuance_date"), ref_date))
        evidence.append(
            {
                "date": rd.get("issuance_date"),
                "kind": bucket,
                "program_id": program_id,
                "amount_yen": amount_int,
                "source_ref": rd.get("source_url") or rd.get("related_law_ref"),
                "program_overlap": program_overlap,
                "decay": round(decay, 2),
            }
        )
    return evidence[:50], missing


def _score_refund_surface(
    evidence: list[dict[str, Any]], *, requested_amount_yen: int
) -> tuple[float, dict[str, Any]]:
    kind_weight = {
        "refund": 28.0,
        "exclusion": 22.0,
        "cancellation": 20.0,
        "fraud": 35.0,
        "off_purpose_use": 30.0,
    }
    total = 0.0
    counts = {k: 0 for k in kind_weight}
    refund_amount_total = 0
    overlap_count = 0
    for ev in evidence:
        kind = str(ev.get("kind") or "")
        counts[kind] = counts.get(kind, 0) + 1
        amount = ev.get("amount_yen")
        if isinstance(amount, int) and amount > 0:
            refund_amount_total += amount
        if ev.get("program_overlap"):
            overlap_count += 1
        decay = float(ev.get("decay") or 0.5)
        total += (kind_weight.get(kind, 10.0) + _refund_amount_points(amount)) * decay
        if ev.get("program_overlap"):
            total += 10.0

    exposure = 0.0
    if requested_amount_yen >= 100_000_000:
        exposure = 15.0
    elif requested_amount_yen >= 10_000_000:
        exposure = 8.0
    elif requested_amount_yen >= 1_000_000:
        exposure = 3.0
    if evidence:
        total += exposure

    signals = {
        "evidence_count": len(evidence),
        "refund_or_return_count": counts.get("refund", 0),
        "cancellation_count": counts.get("cancellation", 0),
        "fraud_count": counts.get("fraud", 0),
        "off_purpose_use_count": counts.get("off_purpose_use", 0),
        "exclusion_count": counts.get("exclusion", 0),
        "program_overlap_count": overlap_count,
        "public_refund_amount_yen": refund_amount_total,
        "requested_amount_exposure_points": exposure,
    }
    return round(min(100.0, max(0.0, total)), 2), signals


@router.post(
    "/refund_risk",
    summary="Rules-based refund / cancellation / fraud / off-purpose-use risk surface",
)
def post_refund_risk(payload: Annotated[RefundRiskRequest, Body(...)]) -> dict[str, Any]:
    normalized = _normalize_houjin(payload.houjin_id)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail={"error": "invalid_houjin_id", "field": "houjin_id"},
        )

    program_ids = sorted({pid for pid in (_norm_program_id(p) for p in payload.program_ids) if pid})
    conn = _open_autonomath_ro()
    missing_tables: list[str] = []
    evidence: list[dict[str, Any]] = []
    if conn is None:
        missing_tables.extend(["autonomath_db", "am_enforcement_detail"])
    else:
        try:
            evidence, missing_tables = _fetch_refund_evidence(
                conn,
                houjin_id=normalized,
                requested_programs=set(program_ids),
                ref_date=_dt.date.today(),
            )
        finally:
            with contextlib.suppress(sqlite3.Error):
                conn.close()

    score, signals = _score_refund_surface(evidence, requested_amount_yen=payload.amount)
    return {
        "houjin_id": normalized,
        "program_ids": program_ids,
        "amount_yen": payload.amount,
        "risk_score": score,
        "risk_label": _label_for_score(score),
        "signals": signals,
        "evidence": evidence,
        "data_coverage": {
            "missing_tables": missing_tables,
            "sparse": bool(missing_tables),
        },
        "_disclaimer": _DISCLAIMER,
    }


__all__ = ["router"]
