"""Product A1 — 税理士月次決算 Pack (``product_tax_monthly_closing_pack``).

One MCP call returns a complete 月次決算 draft composing five moat lanes:

* HE-2 ``prepare_implementation_workpaper`` — N1 template + N2 portfolio
  + N3 reasoning + N4 filing window + N6 amendment alerts +
  N9 placeholder resolver (artifact_type = ``gessji_shiwake``).
* N3 ``walk_reasoning_chain`` — corporate_tax + consumption_tax chains.
* N4 ``find_filing_window`` — 税務署 window resolution for the houjin.
* N6 ``am_amendment_alert_impact`` — per-houjin 90-day amendment alerts.
* N8 ``monthly_closing`` recipe — call-sequence YAML loaded read-only
  from ``data/recipes/recipe_tax_monthly_closing.yaml``.

Tier-D pricing band (Stage 3 F4 design):

* Per-call: ¥1,000 (= 333x ¥3/req baseline).
* Per-houjin subscription: ¥100 / 法人 / 月 (unlimited reruns within month).

NO LLM. Pure SQLite + dict composition. §52 (税理士法) sensitive surface.
Output is a scaffold; 税理士 confirmation is statutory before submission.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import json
import logging
import sqlite3
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from ..moat_lane_tools._shared import DISCLAIMER, today_iso_utc

logger = logging.getLogger("jpintel.mcp.products.a1_tax_monthly")

_PRODUCT_ID = "A1"
_PRODUCT_NAME = "税理士月次決算 Pack"
_SCHEMA_VERSION = "product.a1.v1"
_UPSTREAM_MODULE = "jpintel_mcp.products.a1_tax_monthly"
_ARTIFACT_TYPE = "gessji_shiwake"
_SEGMENT_JA = "税理士"

# Tier-D pricing (F4 design).
_PRICE_PER_REQ_JPY = 1000
_PRICE_PER_HOUJIN_MONTHLY_JPY = 100

_VALUE_PROXY_LLM_LOW_JPY = 3000
_VALUE_PROXY_LLM_HIGH_JPY = 15000

_A1_DISCLAIMER = (
    DISCLAIMER + " 月次決算 draft は 税理士法 §52 のもと、最終署名は税理士の独占業務 "
    "です。本 product は会計士・税理士の作業補助 (retrieval + scaffold) "
    "に留まり、申告書 / 決算書の確定提出物ではありません。仕訳 / 課税 "
    "区分 / 改正対応 はすべて一次資料 (国税庁告示 / 通達 / e-Gov 法令) "
    "で再検証してください。"
)


def _autonomath_db_path() -> Path:
    raw = get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[4] / "autonomath.db"


def _open_ro() -> sqlite3.Connection | None:
    path = _autonomath_db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as exc:  # pragma: no cover
        logger.warning("autonomath.db open failed: %s", exc)
        return None


def _table_present(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _month_label(fiscal_year: int, month: int) -> str:
    return f"{fiscal_year:04d}-{month:02d}"


def _month_end(fiscal_year: int, month: int) -> _dt.date:
    if month == 12:
        return _dt.date(fiscal_year, 12, 31)
    return _dt.date(fiscal_year, month + 1, 1) - _dt.timedelta(days=1)


def _next_month_first(fiscal_year: int, month: int) -> _dt.date:
    if month == 12:
        return _dt.date(fiscal_year + 1, 1, 1)
    return _dt.date(fiscal_year, month + 1, 1)


def _compose_profit_loss_skeleton(month_label: str) -> list[dict[str, Any]]:
    accounts: list[tuple[str, str, str]] = [
        ("510", "売上高", "収益"),
        ("520", "売上原価", "費用"),
        ("530", "売上総利益", "利益"),
        ("610", "販売費及び一般管理費", "費用"),
        ("620", "営業利益", "利益"),
        ("710", "営業外収益", "収益"),
        ("720", "営業外費用", "費用"),
        ("730", "経常利益", "利益"),
        ("810", "特別利益", "収益"),
        ("820", "特別損失", "費用"),
        ("830", "税引前当期純利益", "利益"),
        ("910", "法人税等", "費用"),
        ("920", "当期純利益", "利益"),
    ]
    return [
        {
            "account_code": code,
            "account_name_ja": name,
            "kind": kind,
            "debit_jpy": None,
            "credit_jpy": None,
            "note": f"{month_label} 月次確定要 (税理士 review)",
        }
        for code, name, kind in accounts
    ]


def _compose_journal_skeleton(month_label: str) -> list[dict[str, Any]]:
    fy, mm = month_label.split("-")
    last_day = _month_end(int(fy), int(mm)).isoformat()
    return [
        {
            "date": last_day,
            "debit_account": "売掛金",
            "credit_account": "売上",
            "amount_jpy": None,
            "memo": f"{month_label} 月次売上計上 (税理士 review)",
        },
        {
            "date": last_day,
            "debit_account": "仕入",
            "credit_account": "買掛金",
            "amount_jpy": None,
            "memo": f"{month_label} 月次仕入計上 (税理士 review)",
        },
        {
            "date": last_day,
            "debit_account": "給与手当",
            "credit_account": "未払費用",
            "amount_jpy": None,
            "memo": f"{month_label} 月次給与計上 (税理士 review)",
        },
        {
            "date": last_day,
            "debit_account": "法定福利費",
            "credit_account": "未払金",
            "amount_jpy": None,
            "memo": f"{month_label} 社会保険料月次計上 (税理士 review)",
        },
        {
            "date": last_day,
            "debit_account": "地代家賃",
            "credit_account": "現金",
            "amount_jpy": None,
            "memo": f"{month_label} 家賃月次計上 (税理士 review)",
        },
    ]


def _compose_consumption_tax_skeleton(month_label: str, *, fiscal_year: int) -> dict[str, Any]:
    return {
        "month_label": month_label,
        "fiscal_year": fiscal_year,
        "tax_rate_buckets": [
            {"rate_label": "標準税率 10%", "rate": 0.10, "taxable_jpy": None, "tax_jpy": None},
            {"rate_label": "軽減税率 8%", "rate": 0.08, "taxable_jpy": None, "tax_jpy": None},
            {"rate_label": "非課税", "rate": 0.0, "taxable_jpy": None, "tax_jpy": 0},
            {"rate_label": "不課税", "rate": 0.0, "taxable_jpy": None, "tax_jpy": 0},
        ],
        "filing_classification": "本則課税 (or 簡易課税 — 事前選択届出 要確認)",
        "kakei_filing_due": _dt.date(fiscal_year + 1, 3, 31).isoformat(),
        "note": (
            "適格請求書 (T番号) 保存要件は インボイス制度 (2023-10-01〜) "
            "施行下では仕入税額控除の前提。本 scaffold は 区分 + 税率 + "
            "申告区分 を提示するのみ、実際の控除可否は税理士確認必須。"
        ),
    }


def _fetch_amendment_alerts_sync(
    houjin_bangou: str, horizon_days: int = 90
) -> list[dict[str, Any]]:
    if not houjin_bangou:
        return []
    conn = _open_ro()
    if conn is None:
        return []
    try:
        if not _table_present(conn, "am_amendment_alert_impact"):
            return []
        try:
            rows = conn.execute(
                """
                SELECT alert_id, amendment_diff_id, impact_score,
                       impacted_program_ids, impacted_tax_rule_ids,
                       detected_at, notified_at
                  FROM am_amendment_alert_impact
                 WHERE houjin_bangou = ?
                   AND datetime(detected_at) >= datetime('now', ?)
                 ORDER BY impact_score DESC, detected_at DESC
                 LIMIT 15
                """,
                (houjin_bangou, f"-{int(horizon_days)} days"),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            programs = json.loads(r["impacted_program_ids"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            programs = []
        try:
            tax_rules = json.loads(r["impacted_tax_rule_ids"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            tax_rules = []
        out.append(
            {
                "alert_id": int(r["alert_id"]),
                "amendment_diff_id": int(r["amendment_diff_id"]),
                "impact_score": int(r["impact_score"]),
                "impacted_program_ids": [str(p) for p in programs],
                "impacted_tax_rule_ids": [str(t) for t in tax_rules],
                "detected_at": r["detected_at"],
                "notified_at": r["notified_at"],
            }
        )
    return out


def _fetch_reasoning_chains_sync(limit: int = 5) -> list[dict[str, Any]]:
    conn = _open_ro()
    if conn is None:
        return []
    try:
        if not _table_present(conn, "am_legal_reasoning_chain"):
            return []
        rows = conn.execute(
            """
            SELECT chain_id, topic_id, topic_label, tax_category,
                   conclusion_text, confidence, opposing_view_text,
                   citations
              FROM am_legal_reasoning_chain
             WHERE tax_category IN ('corporate_tax','consumption_tax')
             ORDER BY confidence DESC, chain_id
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            cites = json.loads(r["citations"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            cites = {}
        out.append(
            {
                "chain_id": r["chain_id"],
                "topic_id": r["topic_id"],
                "topic_label": r["topic_label"],
                "tax_category": r["tax_category"],
                "conclusion_text": r["conclusion_text"],
                "confidence": float(r["confidence"] or 0.0),
                "opposing_view_text": r["opposing_view_text"],
                "citations": cites,
            }
        )
    return out


def _fetch_filing_window_sync(houjin_bangou: str) -> dict[str, Any]:
    if not houjin_bangou:
        return {"matches": [], "kind": "tax_office", "address": None}
    conn = _open_ro()
    if conn is None:
        return {"matches": [], "kind": "tax_office", "address": None}
    try:
        if not _table_present(conn, "am_window_directory"):
            return {"matches": [], "kind": "tax_office", "address": None}
        address: str | None = None
        try:
            row = conn.execute(
                "SELECT canonical_id FROM am_entities "
                "WHERE record_kind='corporate_entity' AND canonical_id = ? LIMIT 1",
                (f"houjin:{houjin_bangou}",),
            ).fetchone()
            if row is not None:
                fact = conn.execute(
                    "SELECT value_text FROM am_entity_facts "
                    "WHERE entity_id=? AND field_name IN "
                    "('corp.registered_address','corp.location','corp.address') "
                    "LIMIT 1",
                    (row["canonical_id"],),
                ).fetchone()
                if fact is not None:
                    address = str(fact["value_text"])
        except sqlite3.OperationalError:
            address = None
        matches: list[dict[str, Any]] = []
        if address:
            try:
                window_rows = conn.execute(
                    """
                    SELECT window_id, jurisdiction_kind, name, postal_address,
                           tel, url, source_url, jurisdiction_region_code
                      FROM am_window_directory
                     WHERE jurisdiction_kind = 'tax_office'
                       AND jurisdiction_houjin_filter_regex IS NOT NULL
                       AND ? LIKE jurisdiction_houjin_filter_regex || '%'
                     LIMIT 3
                    """,
                    (address,),
                ).fetchall()
                matches = [dict(r) for r in window_rows]
            except sqlite3.OperationalError:
                matches = []
    finally:
        conn.close()
    return {"matches": matches, "kind": "tax_office", "address": address}


def _recipe_path() -> Path:
    return (
        Path(__file__).resolve().parents[4] / "data" / "recipes" / "recipe_tax_monthly_closing.yaml"
    )


def _recipe_summary() -> dict[str, Any]:
    p = _recipe_path()
    out: dict[str, Any] = {
        "recipe_name": "recipe_tax_monthly_closing",
        "segment": "tax",
        "title": "月次決算 jpcite call sequence (税理士)",
        "expected_duration_seconds": None,
        "cost_estimate_jpy": None,
        "billable_units": None,
        "step_count": 0,
        "no_llm_required": True,
    }
    if not p.exists():
        return out
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:  # pragma: no cover
        return out
    step_count = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("expected_duration_seconds:"):
            with contextlib.suppress(ValueError, TypeError):
                out["expected_duration_seconds"] = int(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("cost_estimate_jpy:"):
            with contextlib.suppress(ValueError, TypeError):
                out["cost_estimate_jpy"] = int(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("billable_units:"):
            with contextlib.suppress(ValueError, TypeError):
                out["billable_units"] = int(stripped.split(":", 1)[1].strip())
        elif stripped.startswith("- step:"):
            step_count += 1
        elif stripped.startswith("title:"):
            out["title"] = stripped.split(":", 1)[1].strip()
    out["step_count"] = step_count
    return out


def _compose_warnings(
    *,
    month_label: str,
    amendment_alerts: list[dict[str, Any]],
    reasoning_chains: list[dict[str, Any]],
    filing_window: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    high_impact = [a for a in amendment_alerts if a["impact_score"] >= 7]
    if high_impact:
        warnings.append(
            {
                "severity": "high",
                "code": "amendment_high_impact",
                "message": (
                    f"impact_score >=7 の改正影響が {len(high_impact)} 件: "
                    f"alert_ids={[a['alert_id'] for a in high_impact[:5]]}. "
                    "月次仕訳・申告区分の再判定 必須。"
                ),
                "next_step": "track_amendment_lineage_am で詳細追跡 + 一次資料確認。",
            }
        )
    if not filing_window.get("matches"):
        warnings.append(
            {
                "severity": "medium",
                "code": "filing_window_unresolved",
                "message": (
                    "税務署 (filing_window) が houjin_bangou から自動解決でき "
                    "ませんでした (登録住所 facts 欠落 or N4 directory miss)。"
                ),
                "next_step": "find_filing_window(program_id='tax', houjin_bangou=...) を手動呼出。",
            }
        )
    if not reasoning_chains:
        warnings.append(
            {
                "severity": "low",
                "code": "reasoning_chain_empty",
                "message": (
                    "N3 reasoning chain (法人税 + 消費税) が取得できませんでした。"
                    "DB snapshot 差替後 / migration wave24_202 pending の可能性。"
                ),
                "next_step": "get_reasoning_chain(topic='corporate_tax:...') を直接呼出。",
            }
        )
    warnings.append(
        {
            "severity": "info",
            "code": "month_specific_check",
            "message": (
                f"{month_label} 月次仕訳の特例 (年末調整・賞与・棚卸・減価償却月割等) "
                "は本 scaffold で自動判定していません。"
            ),
            "next_step": "税理士 review で個別項目を確認。",
        }
    )
    return warnings


def _next_actions(
    *,
    month_label: str,
    filing_window: dict[str, Any],
    fiscal_year: int,
    month: int,
) -> list[dict[str, Any]]:
    window_names = [m.get("name") for m in filing_window.get("matches", [])][:3]
    next_month_first = _next_month_first(fiscal_year, month)
    genshen_due = next_month_first.replace(day=10)
    return [
        {
            "step": "operator fill amounts",
            "rationale": (
                f"{month_label} 月次の 売上 / 仕入 / 給与 / 社保 / 家賃 仕訳 "
                "amount を session に投入。仕訳 skeleton は account_code 単位で "
                "提供済み。"
            ),
        },
        {
            "step": "verify with 税理士",
            "rationale": (
                "§52 (税理士法) — 税務代理は税理士の独占業務。最終 仕訳 / 課税"
                "区分 / 改正対応 は税理士 review 必須。"
            ),
        },
        {
            "step": "submit to filing_window",
            "rationale": (
                f"翌月 10 日 ({genshen_due.isoformat()}) 源泉所得税納付期限。"
                "月次決算自体に法定提出義務は無いが、四半期次/年次申告の "
                "基礎データとして保管。"
            ),
            "filing_window_candidates": window_names,
        },
    ]


def _billing_envelope() -> dict[str, Any]:
    return {
        "tier": "D",
        "product_id": _PRODUCT_ID,
        "price_per_req_jpy": _PRICE_PER_REQ_JPY,
        "price_per_houjin_monthly_jpy": _PRICE_PER_HOUJIN_MONTHLY_JPY,
        "value_proxy": {
            "model": "claude-opus-4-7",
            "llm_equivalent_low_jpy": _VALUE_PROXY_LLM_LOW_JPY,
            "llm_equivalent_high_jpy": _VALUE_PROXY_LLM_HIGH_JPY,
            "saving_low_pct": round(
                100.0 * (1 - _PRICE_PER_REQ_JPY / _VALUE_PROXY_LLM_HIGH_JPY), 1
            ),
            "saving_high_pct": round(
                100.0 * (1 - _PRICE_PER_REQ_JPY / _VALUE_PROXY_LLM_LOW_JPY), 1
            ),
            "note": (
                "Opus 4.7 で同等成果物 (損益計算書 + 仕訳 + 課税仕入計算 + "
                "改正対応指示 + warning) を生成する場合 ≒ ¥3,000-15,000 LLM cost "
                f"(token + 3-pass review)。jpcite ¥{_PRICE_PER_REQ_JPY} は同等 "
                "scaffold を deterministic 計算で出力するため 67-93% 節約。"
            ),
        },
        "no_llm": True,
        "scaffold_only": True,
    }


def _empty_envelope(
    *, primary_input: dict[str, Any], rationale: str, status: str = "empty"
) -> dict[str, Any]:
    return {
        "tool_name": "product_tax_monthly_closing_pack",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": status,
            "product_id": _PRODUCT_ID,
            "product_name": _PRODUCT_NAME,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": rationale,
        },
        "month_label": primary_input.get("month_label"),
        "profit_loss": [],
        "journal_entries": [],
        "consumption_tax_calc": None,
        "amendment_alerts": [],
        "warnings": [],
        "filing_window": {"matches": [], "kind": "tax_office", "address": None},
        "reasoning_chains": [],
        "recipe": None,
        "next_actions": [],
        "billing": _billing_envelope(),
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a1_pack",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["HE-2", "N3", "N4", "N6", "N8"],
        },
        "_billing_unit": 1,
        "_disclaimer": _A1_DISCLAIMER,
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["HE-2", "N3", "N4", "N6", "N8"],
            "observed_at": today_iso_utc(),
        },
    }


@mcp.tool(annotations=_READ_ONLY)
async def product_tax_monthly_closing_pack(
    houjin_bangou: Annotated[
        str,
        Field(
            min_length=0,
            max_length=13,
            description=(
                "13-digit corporate number. Empty string is allowed for "
                "skeleton-mode (template + accounts chart + recipe + warnings "
                "only, no houjin-specific N6 alerts / N4 window resolution)."
            ),
        ),
    ] = "",
    fiscal_year: Annotated[
        int, Field(ge=2000, le=2100, description="Fiscal year (西暦, e.g. 2026).")
    ] = 2026,
    month: Annotated[int, Field(ge=1, le=12, description="Month 1-12 (1=January).")] = 1,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE — §52/監査基準] A1 Product — 税理士月次決算 Pack.

    Composes HE-2 (workpaper) + N3 (reasoning) + N4 (filing window) +
    N6 (amendment alerts) + N8 (monthly_closing recipe) into one
    deterministic 月次決算 draft.

    Returns the canonical A1 envelope: profit_loss + journal_entries +
    consumption_tax_calc + amendment_alerts + warnings + filing_window +
    reasoning_chains + recipe + next_actions + billing (¥1,000/req or
    ¥100/houjin/月) + value_proxy (¥3,000-¥15,000 LLM-equivalent) +
    §52 disclaimer.

    NO LLM. Scaffold-only. 税理士 review is statutory before submission.
    Pricing tier D; 1 ¥1,000 billable unit per call (or covered under
    ¥100/houjin/月 subscription envelope when active).
    """
    month_label = _month_label(fiscal_year, month)
    primary_input = {
        "houjin_bangou": houjin_bangou,
        "fiscal_year": fiscal_year,
        "month": month,
        "month_label": month_label,
        "artifact_type": _ARTIFACT_TYPE,
        "segment": _SEGMENT_JA,
    }
    if month < 1 or month > 12:  # pragma: no cover — pydantic catches
        return _empty_envelope(
            primary_input=primary_input,
            rationale=f"month={month!r} out of range 1..12",
        )
    loop = asyncio.get_event_loop()
    is_skeleton = not houjin_bangou
    if is_skeleton:
        amendment_alerts: list[dict[str, Any]] = []
        reasoning_chains = await loop.run_in_executor(None, _fetch_reasoning_chains_sync, 5)
        filing_window: dict[str, Any] = {
            "matches": [],
            "kind": "tax_office",
            "address": None,
        }
    else:
        alerts_task = loop.run_in_executor(None, _fetch_amendment_alerts_sync, houjin_bangou, 90)
        chains_task = loop.run_in_executor(None, _fetch_reasoning_chains_sync, 5)
        window_task = loop.run_in_executor(None, _fetch_filing_window_sync, houjin_bangou)
        amendment_alerts, reasoning_chains, filing_window = await asyncio.gather(
            alerts_task, chains_task, window_task
        )
    profit_loss = _compose_profit_loss_skeleton(month_label)
    journal_entries = _compose_journal_skeleton(month_label)
    consumption_tax_calc = _compose_consumption_tax_skeleton(month_label, fiscal_year=fiscal_year)
    recipe = _recipe_summary()
    warnings = _compose_warnings(
        month_label=month_label,
        amendment_alerts=amendment_alerts,
        reasoning_chains=reasoning_chains,
        filing_window=filing_window,
    )
    next_actions = _next_actions(
        month_label=month_label,
        filing_window=filing_window,
        fiscal_year=fiscal_year,
        month=month,
    )
    citations: list[dict[str, Any]] = []
    for chain in reasoning_chains[:3]:
        cites = chain.get("citations") or {}
        if isinstance(cites, dict):
            for kind in ("law", "tsutatsu"):
                entries = cites.get(kind, []) or []
                if isinstance(entries, list):
                    for entry in entries[:2]:
                        if isinstance(entry, dict):
                            citations.append({"kind": kind, **entry})
    return {
        "tool_name": "product_tax_monthly_closing_pack",
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "product_id": _PRODUCT_ID,
            "product_name": _PRODUCT_NAME,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "is_skeleton": is_skeleton,
            "segment": _SEGMENT_JA,
        },
        "month_label": month_label,
        "profit_loss": profit_loss,
        "journal_entries": journal_entries,
        "consumption_tax_calc": consumption_tax_calc,
        "amendment_alerts": amendment_alerts,
        "warnings": warnings,
        "filing_window": filing_window,
        "reasoning_chains": reasoning_chains,
        "recipe": recipe,
        "next_actions": next_actions,
        "billing": _billing_envelope(),
        "results": journal_entries,
        "total": len(journal_entries),
        "limit": len(journal_entries),
        "offset": 0,
        "citations": citations[:10],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a1_pack",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["HE-2", "N3", "N4", "N6", "N8"],
            "artifact_type": _ARTIFACT_TYPE,
            "amendment_alert_count": len(amendment_alerts),
            "reasoning_chain_count": len(reasoning_chains),
            "filing_window_count": len(filing_window.get("matches", [])),
        },
        "_billing_unit": 1,
        "_disclaimer": _A1_DISCLAIMER,
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["HE-2", "N3", "N4", "N6", "N8"],
            "observed_at": today_iso_utc(),
        },
    }


__all__ = ["product_tax_monthly_closing_pack"]
