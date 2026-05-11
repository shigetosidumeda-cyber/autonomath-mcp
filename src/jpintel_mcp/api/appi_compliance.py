"""GET /v1/appi/compliance/{houjin_bangou} — APPI 個情法 compliance state.

Wave 41 Axis 7a REST endpoint backed by ``am_appi_compliance`` (migration
245). Returns the latest known compliance status across all known
sources (PPC / EDINET / JIPDEC / other) for one ``houjin_bangou``.

Source discipline (non-negotiable)
----------------------------------
* PPC (個人情報保護委員会) — `https://www.ppc.go.jp/`.
* JIPDEC PrivacyMark / ISMS-P — `https://privacymark.jp/` / `https://isms.jp/`.
* EDINET 開示情報 — `https://disclosure2.edinet-fsa.go.jp/`.

Sensitive surface
-----------------
APPI rights overlap §44-3 (越境移転 通知) and §26 (漏えい等 報告). Any
回答 must NOT be construed as a legal opinion. The handler stamps a
``_disclaimer`` envelope citing 弁護士法 §72 + 個人情報保護法 §155
(指導・助言は PPC 専権) on every 2xx response.

CLAUDE.md / memory constraints
------------------------------
* NO LLM call — pure SQLite SELECT.
* NO cross-DB ATTACH; autonomath.db read-only handle opened separately.
* Memory `feedback_no_quick_check_on_huge_sqlite` honored — index-only
  walk via ``idx_am_appi_compliance_houjin``.
* Read budget: ¥3/req (1 ``_billing_unit``).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, status
from fastapi import Path as FastPath
from fastapi.responses import JSONResponse

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.appi_compliance")

router = APIRouter(prefix="/v1/appi", tags=["appi", "compliance"])


_APPI_DISCLAIMER = (
    "本レスポンスは jpcite が PPC (個人情報保護委員会) 公表資料 / EDINET 開示書面 / "
    "JIPDEC PrivacyMark・ISMS-P 公開リスト を機械的に整理した結果を返却するものであり、"
    "弁護士法 §72 (法令解釈) ・個人情報保護法 §155 (PPC 指導・助言 専権) のいずれの士業役務 "
    "にも該当しません。掲載の compliance_status は公表時点の事実であり、現在の状態が変更されて "
    "いる可能性があります。各 row の source_url で原典を確認のうえ、確定判断は資格を有する "
    "弁護士・個人情報保護士へご相談ください。"
)


def _autonomath_db_path() -> str:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return raw
    return str(Path(__file__).resolve().parents[3] / "autonomath.db")


def _open_am_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    try:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError:
        return None


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
            (name,),
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


@router.get(
    "/compliance/{houjin_bangou}",
    summary="APPI (個人情報保護法) compliance state",
    description=(
        "Returns the latest known APPI compliance state for one "
        "``houjin_bangou`` (13 桁 法人番号), aggregating rows from "
        "``am_appi_compliance`` (PPC / EDINET / JIPDEC). NO LLM call.\n\n"
        "**Pricing**: ¥3 / call (``_billing_unit: 1``). Pure SQLite.\n\n"
        "**Sensitive**: 弁護士法 §72 / 個人情報保護法 §155 fence — every "
        "response carries a ``_disclaimer`` envelope key. LLM agents MUST "
        "relay the disclaimer verbatim to end users."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {"description": "APPI compliance envelope."},
        404: {"description": "houjin_bangou not present in dataset."},
    },
)
def get_appi_compliance(
    conn: DbDep,
    ctx: ApiContextDep,
    houjin_bangou: Annotated[
        str,
        FastPath(
            min_length=13,
            max_length=13,
            description="13-digit 法人番号 (gBizINFO canonical form, no hyphens).",
        ),
    ],
) -> JSONResponse:
    """Return the APPI compliance bundle for ``houjin_bangou``."""
    t0 = time.perf_counter()

    if not houjin_bangou.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"houjin_bangou must be 13 numeric digits, got {houjin_bangou!r}."
            ),
        )

    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    am = _open_am_ro()
    if am is not None:
        try:
            if _table_exists(am, "am_appi_compliance"):
                fetched = am.execute(
                    "SELECT organization_id, organization_name, compliance_status, "
                    "       pic_certification, last_audit_date, source_url, "
                    "       source_kind, notes, refreshed_at "
                    "FROM am_appi_compliance "
                    "WHERE houjin_bangou = ? "
                    "ORDER BY refreshed_at DESC, organization_id ASC "
                    "LIMIT 50",
                    (houjin_bangou,),
                ).fetchall()
                for r in fetched:
                    rows.append(
                        {
                            "organization_id": r["organization_id"],
                            "organization_name": r["organization_name"],
                            "compliance_status": r["compliance_status"],
                            "pic_certification": bool(r["pic_certification"]),
                            "last_audit_date": r["last_audit_date"],
                            "source_url": r["source_url"],
                            "source_kind": r["source_kind"],
                            "notes": r["notes"],
                            "refreshed_at": r["refreshed_at"],
                        }
                    )
                # roll-up summary
                worst_rank = {
                    "non-compliant": 4,
                    "pending": 3,
                    "unknown": 2,
                    "registered": 1,
                    "exempt": 0,
                }
                worst_status = "unknown"
                for r in rows:
                    s = r["compliance_status"]
                    if worst_rank.get(s, 0) > worst_rank.get(worst_status, 0):
                        worst_status = s
                summary = {
                    "row_count": len(rows),
                    "worst_status": worst_status if rows else None,
                    "any_pic_certified": any(r["pic_certification"] for r in rows),
                    "sources": sorted({r["source_kind"] for r in rows if r["source_kind"]}),
                }
        except sqlite3.OperationalError as exc:
            logger.warning("appi_compliance query failed: %s", exc)
        finally:
            with suppress(Exception):
                am.close()

    if not rows:
        # Honest 404 — no PII leakage; the field is empty across all sources.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No APPI compliance row found for houjin_bangou={houjin_bangou}. "
                "This is honest absence — the dataset has no PPC / EDINET / JIPDEC "
                "record for this 法人. It is NOT a finding of compliance state."
            ),
        )

    result = {
        "houjin_bangou": houjin_bangou,
        "rows": rows,
        "summary": summary,
        "_billing_unit": 1,
        "_disclaimer": _APPI_DISCLAIMER,
        "precompute_source": "am_appi_compliance (mig 245)",
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "appi_compliance",
        latency_ms=latency_ms,
        result_count=len(rows),
        params={"houjin_bangou": houjin_bangou},
        strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


__all__ = ["router"]
