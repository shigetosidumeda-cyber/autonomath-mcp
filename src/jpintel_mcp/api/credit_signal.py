"""GET /v1/credit/signal/{houjin_bangou} — credit signal aggregate.

Wave 41 Axis 7b REST endpoint backed by ``am_credit_signal_aggregate``
(migration 246). Returns the rule-based credit signal aggregate for one
``houjin_bangou`` plus its constituent signals — primary-source URLs
only, NO ML / NO LLM.

Sensitive surface
-----------------
Credit signals are 与信判断 territory — incorrect use can damage 法人
of legitimate operations. The handler stamps a ``_disclaimer`` envelope
citing 弁護士法 §72 + 銀行法 §10 (信用情報 取扱 規制) on every 2xx
response. Output is a FACT (枚挙 of public-record 行政処分 / 取消 /
処分 等), NOT a credit judgment.

CLAUDE.md / memory constraints
------------------------------
* NO LLM call — pure SQLite SELECT.
* NO ML — the score is rule-based, computed offline by
  ``scripts/cron/aggregate_credit_signal_daily.py``.
* NO cross-DB ATTACH; autonomath.db read-only handle.
* Memory `feedback_no_quick_check_on_huge_sqlite` honored — index-only
  walk via the PRIMARY KEY on ``houjin_bangou``.
* Read budget: ¥3/req (1 ``_billing_unit``).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi import Path as FastPath
from fastapi.responses import JSONResponse

from jpintel_mcp.api._error_envelope import COMMON_ERROR_RESPONSES
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.credit_signal")

router = APIRouter(prefix="/v1/credit", tags=["credit", "signal"])


_CREDIT_DISCLAIMER = (
    "本レスポンスは jpcite が一次資料 (行政処分 / 適格事業者登録取消 / 採択取消 / "
    "判決 等の公的記録) を rule-based で集計した結果であり、ML/AI による予測値ではありません。"
    "弁護士法 §72 (法令解釈) ・銀行法 §10 (信用情報取扱 規制) のいずれの士業役務にも該当せず、"
    "与信判断・取引可否・保証 等の意思決定の根拠とはなりません。各 signal_url で原典を確認 "
    "のうえ、与信判断 が必要な場合は資格を有する弁護士・公認会計士へご相談ください。"
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
    "/signal/{houjin_bangou}",
    summary="Credit signal aggregate (rule-based, NO ML)",
    description=(
        "Returns the rule-based credit signal aggregate from "
        "``am_credit_signal_aggregate`` (migration 246), plus the top-N "
        "constituent signal rows from ``am_credit_signal``. NO LLM, NO "
        "ML — score 0..100 is computed offline by "
        "``scripts/cron/aggregate_credit_signal_daily.py`` using a "
        "deterministic severity-weighted decay formula.\n\n"
        "**Pricing**: ¥3 / call (``_billing_unit: 1``). Pure SQLite.\n\n"
        "**Sensitive**: 弁護士法 §72 / 銀行法 §10 fence — every response "
        "carries a ``_disclaimer`` envelope key. LLM agents MUST relay the "
        "disclaimer verbatim to end users."
    ),
    responses={
        **COMMON_ERROR_RESPONSES,
        200: {"description": "Credit signal envelope."},
        404: {"description": "houjin_bangou not present in dataset."},
    },
)
def get_credit_signal(
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
    max_signals: Annotated[
        int,
        Query(
            ge=1,
            le=50,
            description="Cap on returned constituent signal rows (default 20).",
        ),
    ] = 20,
) -> JSONResponse:
    """Return the credit signal aggregate for ``houjin_bangou``."""
    t0 = time.perf_counter()

    if not houjin_bangou.isdigit():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"houjin_bangou must be 13 numeric digits, got {houjin_bangou!r}.",
        )

    aggregate: dict[str, Any] | None = None
    signals: list[dict[str, Any]] = []
    am = _open_am_ro()
    if am is not None:
        try:
            if _table_exists(am, "am_credit_signal_aggregate"):
                agg = am.execute(
                    "SELECT houjin_bangou, signal_count, max_severity, "
                    "       rule_based_score, last_signal_date, refreshed_at, "
                    "       type_breakdown_json "
                    "FROM am_credit_signal_aggregate "
                    "WHERE houjin_bangou = ? LIMIT 1",
                    (houjin_bangou,),
                ).fetchone()
                if agg:
                    type_breakdown: dict[str, int] = {}
                    with suppress(json.JSONDecodeError, TypeError):
                        type_breakdown = json.loads(agg["type_breakdown_json"]) or {}
                    aggregate = {
                        "signal_count": agg["signal_count"],
                        "max_severity": agg["max_severity"],
                        "rule_based_score": agg["rule_based_score"],
                        "last_signal_date": agg["last_signal_date"],
                        "refreshed_at": agg["refreshed_at"],
                        "type_breakdown": type_breakdown,
                    }
            if _table_exists(am, "am_credit_signal"):
                fetched = am.execute(
                    "SELECT signal_id, signal_type, signal_date, severity, "
                    "       source_url, source_kind, evidence_text "
                    "FROM am_credit_signal "
                    "WHERE houjin_bangou = ? "
                    "ORDER BY severity DESC, signal_date DESC NULLS LAST, signal_id DESC "
                    "LIMIT ?",
                    (houjin_bangou, int(max_signals)),
                ).fetchall()
                for r in fetched:
                    signals.append(
                        {
                            "signal_id": r["signal_id"],
                            "signal_type": r["signal_type"],
                            "signal_date": r["signal_date"],
                            "severity": r["severity"],
                            "source_url": r["source_url"],
                            "source_kind": r["source_kind"],
                            "evidence_text": r["evidence_text"],
                        }
                    )
        except sqlite3.OperationalError as exc:
            logger.warning("credit_signal query failed: %s", exc)
        finally:
            with suppress(Exception):
                am.close()

    if aggregate is None and not signals:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No credit signal row found for houjin_bangou={houjin_bangou}. "
                "This is honest absence — the dataset has NO 行政処分 / 取消 / "
                "判決 record for this 法人. It is NOT a finding of creditworthiness."
            ),
        )

    result = {
        "houjin_bangou": houjin_bangou,
        "aggregate": aggregate or {},
        "signals": signals,
        "signal_count_returned": len(signals),
        "scoring_method": "rule_based_severity_with_36mo_linear_decay",
        "_billing_unit": 1,
        "_disclaimer": _CREDIT_DISCLAIMER,
        "precompute_source": "am_credit_signal_aggregate / am_credit_signal (mig 246)",
    }

    latency_ms = int((time.perf_counter() - t0) * 1000)
    log_usage(
        conn,
        ctx,
        "credit_signal",
        latency_ms=latency_ms,
        result_count=len(signals),
        params={"houjin_bangou": houjin_bangou, "max_signals": max_signals},
        strict_metering=True,
    )
    return JSONResponse(content=result, status_code=200)


__all__ = ["router"]
