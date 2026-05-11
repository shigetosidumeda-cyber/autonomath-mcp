"""cohort_risk_chain — Wave 33 Axis 2a/2b/2c MCP tool surface.

Three MCP tools over the daily-refreshed precompute tables:

* match_cohort_5d_am — 5-axis cohort lookup (Axis 2a).
* program_risk_score_am — 4-axis program-risk score (Axis 2b).
* supplier_chain_am — bipartite supplier-chain traversal (Axis 2c).

NO LLM. NO full-scan op against the 9.7GB DB.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import suppress
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.cohort_risk_chain")

_ENABLED = os.environ.get("AUTONOMATH_COHORT_RISK_CHAIN_ENABLED", "1") == "1"


_DISCLAIMER = (
    "本 response は jpcite が公開情報を機械的に整理した結果を返却するものであり、"
    "税理士法 §52 / 公認会計士法 §47条の2 / 行政書士法 §1 / 弁護士法 §72 に基づく"
    "個別具体的な税務助言・監査意見・申請書面作成・法律相談の代替ではありません。"
    "最終的な判断は資格を有する士業へご相談ください。"
)


def _open_autonomath_ro() -> sqlite3.Connection | dict[str, Any]:
    try:
        return connect_autonomath()
    except FileNotFoundError as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db missing: {exc}",
            hint="Ensure autonomath.db is present at AUTONOMATH_DB_PATH.",
            retry_with=["search_case_studies"],
        )
    except sqlite3.Error as exc:
        return make_error(
            code="db_unavailable",
            message=f"autonomath.db open failed: {exc}",
            retry_with=["search_case_studies"],
        )


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def match_cohort_5d_impl(
    jsic_major: str,
    employee_band: str,
    prefecture_code: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    conn_or_err = _open_autonomath_ro()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    eligible: list[str] = []
    meta: dict[str, Any] = {}
    if _table_exists(conn, "am_cohort_5d"):
        try:
            row = conn.execute(
                "SELECT eligible_program_ids, eligible_count, last_refreshed_at "
                "FROM am_cohort_5d "
                "WHERE houjin_bangou IS NULL "
                "  AND jsic_major = ? AND employee_band = ? "
                "  AND COALESCE(prefecture_code, '_nationwide') = COALESCE(?, '_nationwide') "
                "LIMIT 1",
                (jsic_major, employee_band, prefecture_code),
            ).fetchone()
            if row:
                with suppress(json.JSONDecodeError, TypeError):
                    eligible = json.loads(row["eligible_program_ids"]) or []
                meta = {
                    "eligible_count": row["eligible_count"],
                    "last_refreshed_at": row["last_refreshed_at"],
                }
        except sqlite3.OperationalError:
            pass
    with suppress(Exception):
        conn.close()
    limit = max(1, min(int(limit), 100))
    eligible = eligible[:limit]
    return {
        "axes": {"jsic_major": jsic_major, "employee_band": employee_band,
                 "prefecture_code": prefecture_code},
        "eligible_program_ids": eligible,
        "results": [{"unified_id": p} for p in eligible],
        "total": len(eligible),
        "cohort_meta": meta,
        "_disclaimer": _DISCLAIMER,
        "precompute_source": "am_cohort_5d (mig 231)",
    }


def program_risk_score_impl(program_id: str) -> dict[str, Any]:
    conn_or_err = _open_autonomath_ro()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    top: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    if _table_exists(conn, "am_program_risk_4d"):
        try:
            rows = conn.execute(
                "SELECT gyouhou_id, enforcement_pattern_id, revocation_reason_id, "
                "       risk_score_0_100, evidence_json, last_refreshed_at "
                "FROM am_program_risk_4d WHERE program_id = ? "
                "ORDER BY risk_score_0_100 DESC LIMIT 10",
                (program_id,),
            ).fetchall()
            for r in rows:
                evidence: dict[str, Any] = {}
                with suppress(json.JSONDecodeError, TypeError):
                    evidence = json.loads(r["evidence_json"]) or {}
                all_rows.append({
                    "gyouhou_id": r["gyouhou_id"],
                    "enforcement_pattern_id": r["enforcement_pattern_id"],
                    "revocation_reason_id": r["revocation_reason_id"],
                    "risk_score_0_100": r["risk_score_0_100"],
                    "evidence": evidence,
                    "last_refreshed_at": r["last_refreshed_at"],
                })
            if all_rows:
                top = all_rows[0]
        except sqlite3.OperationalError:
            pass
    with suppress(Exception):
        conn.close()
    return {
        "program_id": program_id, "top_risk": top, "all_axes": all_rows,
        "axis_count": len(all_rows),
        "weights": {"gyouhou": 0.5, "enforcement": 0.3, "tsutatsu": 0.2},
        "_disclaimer": _DISCLAIMER,
        "precompute_source": "am_program_risk_4d (mig 232)",
    }


def supplier_chain_impl(houjin_bangou: str, max_hops: int = 3) -> dict[str, Any]:
    if not isinstance(houjin_bangou, str) or len(houjin_bangou) != 13:
        return make_error(
            code="invalid_enum",
            message="houjin_bangou must be a 13-character string",
            field="houjin_bangou",
        )
    max_hops = max(1, min(int(max_hops), 5))
    conn_or_err = _open_autonomath_ro()
    if isinstance(conn_or_err, dict):
        return conn_or_err
    conn = conn_or_err
    edges: list[dict[str, Any]] = []
    by_type: dict[str, int] = {}
    if _table_exists(conn, "am_supplier_chain"):
        try:
            rows = conn.execute(
                "SELECT partner_houjin_bangou, link_type, evidence_url, "
                "       evidence_date, hop_depth "
                "FROM am_supplier_chain "
                "WHERE anchor_houjin_bangou = ? AND hop_depth <= ? "
                "ORDER BY hop_depth ASC, partner_houjin_bangou ASC LIMIT 500",
                (houjin_bangou, max_hops),
            ).fetchall()
            for r in rows:
                lt = r["link_type"]
                by_type[lt] = by_type.get(lt, 0) + 1
                edges.append({
                    "partner": r["partner_houjin_bangou"],
                    "link_type": lt,
                    "evidence_url": r["evidence_url"],
                    "evidence_date": r["evidence_date"],
                    "hop_depth": r["hop_depth"],
                })
        except sqlite3.OperationalError:
            pass
    with suppress(Exception):
        conn.close()
    return {
        "anchor_houjin_bangou": houjin_bangou, "max_hops": max_hops,
        "edges": edges, "edge_count": len(edges), "by_link_type": by_type,
        "_disclaimer": _DISCLAIMER,
        "precompute_source": "am_supplier_chain (mig 233)",
    }


if _ENABLED and settings.autonomath_enabled:

    @mcp.tool(annotations=_READ_ONLY)
    def match_cohort_5d_am(
        jsic_major: Annotated[str, Field(min_length=1, max_length=1, description="JSIC 大分類 1 char (A-T).")],
        employee_band: Annotated[str, Field(description="'1-9' / '10-99' / '100-999' / '1000+'.")],
        prefecture_code: Annotated[str | None, Field(default=None, max_length=2, description="2-digit JIS pref code or None.")] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Max programs [1,100].")] = 20,
    ) -> dict[str, Any]:
        """[COHORT-5D] いつ使うか: 法人 × 業種 × 規模 × 地域 × 制度の 5 軸で「私と同じカテゴリの企業が通った制度」を即座に返す。入力: jsic_major (A-T)、employee_band (4 段階)、prefecture_code (47 都道府県 + null)、limit (1-100)。出力: eligible_program_ids[]、cohort_meta (last_refreshed_at, eligible_count)。エラー: invalid_enum / db_unavailable。1 ¥3/req。NO LLM。§52 / §47条の2 / §1 sensitive。"""
        return match_cohort_5d_impl(
            jsic_major=jsic_major, employee_band=employee_band,
            prefecture_code=prefecture_code, limit=limit,
        )

    @mcp.tool(annotations=_READ_ONLY)
    def program_risk_score_am(
        program_id: Annotated[str, Field(description="制度 unified_id, e.g. 'UNI-it-2025-...'")],
    ) -> dict[str, Any]:
        """[PROGRAM-RISK-4D] いつ使うか: 制度 × 業法 × 行政処分 × 取消理由の 4 軸 risk score (0-100) を返す。weighted: 業法 0.5 / 行政処分 0.3 / 取消理由 0.2。入力: program_id (unified_id)。出力: top_risk + all_axes[]、weights、_disclaimer。エラー: invalid_enum / db_unavailable。1 ¥3/req。NO LLM。§52 / §47条の2 / §1 sensitive — 行政書士法 §1 / 税理士法 §52 boundary 識別用途。"""
        return program_risk_score_impl(program_id=program_id)

    @mcp.tool(annotations=_READ_ONLY)
    def supplier_chain_am(
        houjin_bangou: Annotated[str, Field(min_length=13, max_length=13, description="Anchor 13-digit 法人番号.")],
        max_hops: Annotated[int, Field(ge=1, le=5, description="Traversal depth [1,5]. Default 3.")] = 3,
    ) -> dict[str, Any]:
        """[SUPPLIER-CHAIN] いつ使うか: anchor houjin を起点に bipartite chain (invoice_registrant_active/revoked, adoption_partner, enforcement_subject の 4 link_type) を最大 5 hop まで traverse。入力: houjin_bangou (13 桁) + max_hops (1-5)。出力: edges[]、by_link_type、edge_count。エラー: invalid_enum / db_unavailable。2 ¥3/req (heavy)。NO LLM。§52 / §47条の2 / §1 sensitive — 取引先デューデリ用途、最終判断は士業へ。"""
        return supplier_chain_impl(houjin_bangou=houjin_bangou, max_hops=max_hops)


__all__ = ["match_cohort_5d_impl", "program_risk_score_impl", "supplier_chain_impl"]
