"""A3 — 補助金活用ロードマップ Pack (¥500 / req).

One MCP call assembles a 12-month subsidy-activation roadmap for a houjin
by composing four upstream moat lanes:

* **N2** (``am_houjin_program_portfolio``) — portfolio + portfolio gap.
* **N4** (``am_application_round``) — application window calendar.
* **N6** (``am_amendment_alert_impact``) — pending amendment alerts that
  affect roadmap programs.
* **N7** (``am_segment_view``) — JSIC × size × prefecture segment view
  to estimate adoption / competitor density.

Output is a flat list of month-buckets (default = 12 months, configurable
1-24) plus an aggregate summary (total target subsidy amount, risk flags,
average competition density). NO LLM — pure SQLite + dict composition.

Hard constraints
----------------

* §52 / §47条の2 / §72 / §1 / §3 disclaimer envelope on every response.
* Scaffold-only — the roadmap never asserts adoption / 採択 / 交付決定.
* Read-only SQLite (URI ``ro``).
* ``_billing_unit = 167`` so the host MCP server bills ``167 × ¥3 = ¥501``
  (≈ ¥500 product tier, rounded up to the nearest ¥3 metered increment).

Tool
----

* ``product_subsidy_roadmap_12month(houjin_bangou, scope_year=12)`` —
  single heavy-output composition. ``scope_year`` is the rolling-month
  horizon (1-24, default 12); the parameter name mirrors the spec.
"""

from __future__ import annotations

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

logger = logging.getLogger("jpintel.mcp.products.a3_subsidy_roadmap")

_PRODUCT_ID = "A3"
_SCHEMA_VERSION = "products.a3.v1"
_UPSTREAM_MODULE = "jpintel_mcp.mcp.products.product_a3_subsidy_roadmap"

# A3 sells at ¥500 / call; the ¥3 metered ledger maps that to 167 units.
_BILLING_UNITS = 167

_RELATED_SHIHOU = ("税理士", "会計士", "行政書士", "司法書士", "社労士")


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
    except sqlite3.Error as exc:
        logger.warning("autonomath.db open failed: %s", exc)
        return None


def _table_present(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _parse_json_array(blob: Any) -> list[str]:
    if blob is None:
        return []
    try:
        decoded = json.loads(blob)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _fetch_portfolio(
    conn: sqlite3.Connection, houjin_bangou: str, limit: int
) -> list[dict[str, Any]]:
    if not _table_present(conn, "am_houjin_program_portfolio"):
        return []
    try:
        rows = conn.execute(
            """
            SELECT program_id, applicability_score, applied_status,
                   deadline, deadline_kind, priority_rank,
                   score_industry, score_size, score_region,
                   score_sector, score_target_form, computed_at
              FROM am_houjin_program_portfolio
             WHERE houjin_bangou = ?
             ORDER BY priority_rank ASC NULLS LAST, applicability_score DESC
             LIMIT ?
            """,
            (houjin_bangou, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "program_id": r["program_id"],
                "applicability_score": round(float(r["applicability_score"] or 0.0), 2),
                "applied_status": r["applied_status"],
                "deadline": r["deadline"],
                "deadline_kind": r["deadline_kind"],
                "priority_rank": r["priority_rank"],
                "score_breakdown": {
                    "industry": round(float(r["score_industry"] or 0.0), 2),
                    "size": round(float(r["score_size"] or 0.0), 2),
                    "region": round(float(r["score_region"] or 0.0), 2),
                    "sector": round(float(r["score_sector"] or 0.0), 2),
                    "target_form": round(float(r["score_target_form"] or 0.0), 2),
                },
            }
        )
    return out


def _fetch_rounds_for_program(
    conn: sqlite3.Connection,
    program_id: str,
    start_iso: str,
    end_iso: str,
) -> list[dict[str, Any]]:
    if not _table_present(conn, "am_application_round"):
        return []
    try:
        rows = conn.execute(
            """
            SELECT round_id, round_label, round_seq, status,
                   application_open_date, application_close_date,
                   announced_date, disbursement_start_date,
                   budget_yen, source_url
              FROM am_application_round
             WHERE program_entity_id = ?
               AND application_close_date >= ?
               AND application_close_date <= ?
             ORDER BY application_close_date ASC
            """,
            (program_id, start_iso, end_iso),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "round_id": r["round_id"],
                "round_label": r["round_label"],
                "round_seq": r["round_seq"],
                "status": r["status"],
                "application_open_date": r["application_open_date"],
                "application_close_date": r["application_close_date"],
                "announced_date": r["announced_date"],
                "disbursement_start_date": r["disbursement_start_date"],
                "budget_yen": r["budget_yen"],
                "source_url": r["source_url"],
            }
        )
    return out


def _fetch_amendment_alerts(
    conn: sqlite3.Connection,
    houjin_bangou: str,
    program_ids: set[str],
    horizon_days: int = 120,
) -> list[dict[str, Any]]:
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
             LIMIT 20
            """,
            (houjin_bangou, f"-{int(horizon_days)} days"),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        impacted = _parse_json_array(r["impacted_program_ids"])
        if program_ids and not any(p in program_ids for p in impacted):
            continue
        out.append(
            {
                "alert_id": int(r["alert_id"]),
                "amendment_diff_id": int(r["amendment_diff_id"]),
                "impact_score": int(r["impact_score"]),
                "impacted_program_ids": impacted,
                "impacted_tax_rule_ids": _parse_json_array(r["impacted_tax_rule_ids"]),
                "detected_at": r["detected_at"],
                "notified_at": r["notified_at"],
            }
        )
    return out


def _fetch_segment_summary(
    conn: sqlite3.Connection,
    jsic_major: str | None,
    size_band: str | None,
    prefecture: str | None,
) -> dict[str, Any]:
    if not _table_present(conn, "am_segment_view"):
        return {}
    where: list[str] = []
    params: list[Any] = []
    if jsic_major:
        where.append("jsic_major = ?")
        params.append(jsic_major)
    if size_band:
        where.append("size_band = ?")
        params.append(size_band)
    if prefecture:
        where.append("prefecture = ?")
        params.append(prefecture)
    sql = (  # nosec B608 — whitelisted column predicates only
        "SELECT segment_key, jsic_major, jsic_name_ja, size_band, prefecture, "
        "       program_count, judgment_count, tsutatsu_count, "
        "       popularity_rank, adoption_count "
        "  FROM am_segment_view "
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY popularity_rank ASC NULLS LAST LIMIT 5"
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return {}
    if not rows:
        return {}
    return {
        "rows_observed": len(rows),
        "median_adoption_count": sorted(int(r["adoption_count"]) for r in rows)[len(rows) // 2],
        "top_program_count": int(rows[0]["program_count"]),
        "filters": {"jsic_major": jsic_major, "size_band": size_band, "prefecture": prefecture},
        "rows": [dict(r) for r in rows[:5]],
    }


def _lookup_houjin_attributes(
    conn: sqlite3.Connection, houjin_bangou: str
) -> dict[str, str | None]:
    out: dict[str, str | None] = {
        "jsic_major": None,
        "size_band": None,
        "prefecture": None,
        "address": None,
    }
    if not _table_present(conn, "am_entity_facts"):
        return out
    try:
        rows = conn.execute(
            """
            SELECT field_name, value_text
              FROM am_entity_facts
             WHERE entity_id = ?
               AND field_name IN (
                   'corp.jsic_major',
                   'corp.size_band',
                   'corp.prefecture',
                   'corp.registered_address',
                   'corp.location',
                   'corp.address'
               )
            """,
            (f"houjin:{houjin_bangou}",),
        ).fetchall()
    except sqlite3.OperationalError:
        return out
    for r in rows:
        fn = r["field_name"]
        val = r["value_text"]
        if fn == "corp.jsic_major":
            out["jsic_major"] = val
        elif fn == "corp.size_band":
            out["size_band"] = val
        elif fn == "corp.prefecture":
            out["prefecture"] = val
        elif (
            fn in ("corp.registered_address", "corp.location", "corp.address")
            and not out["address"]
        ):
            out["address"] = val
    if not out["prefecture"] and out["address"]:
        for pref_hint in ("東京都", "大阪府", "京都府", "北海道"):
            if out["address"].startswith(pref_hint):
                out["prefecture"] = pref_hint
                break
        else:
            for token in ("県", "府", "都", "道"):
                idx = out["address"].find(token)
                if 1 < idx < 8:
                    out["prefecture"] = out["address"][: idx + 1]
                    break
    return out


def _iter_months(start: _dt.date, scope_months: int) -> list[tuple[str, _dt.date, _dt.date]]:
    out: list[tuple[str, _dt.date, _dt.date]] = []
    cur = _dt.date(start.year, start.month, 1)
    for _ in range(scope_months):
        if cur.month == 12:
            nxt = _dt.date(cur.year + 1, 1, 1)
        else:
            nxt = _dt.date(cur.year, cur.month + 1, 1)
        last = nxt - _dt.timedelta(days=1)
        out.append((f"{cur.year:04d}-{cur.month:02d}", cur, last))
        cur = nxt
    return out


def _estimate_adoption_probability(
    score: float,
    segment_adoption_count: int,
    segment_program_count: int,
) -> float:
    density = 0.5
    if segment_program_count > 0:
        density = min(1.0, float(segment_adoption_count) / float(segment_program_count) / 5.0)
    blended = 0.65 * max(0.0, min(1.0, score)) + 0.35 * density
    return round(max(0.0, min(0.95, blended)), 2)


def _required_documents_for_program(program_id: str, deadline_kind: str | None) -> list[str]:
    pid_lower = program_id.lower()
    base = [
        "登記事項証明書 (履歴事項全部証明書)",
        "決算書 (直近2期分)",
        "事業計画書",
        "見積書 / 仕様書",
    ]
    if "it" in pid_lower or "dx" in pid_lower:
        base.append("IT 導入支援事業者 連名申請書")
        base.append("ベンダー見積書 (IT 導入補助金 様式)")
    if "monozukuri" in pid_lower or "monozu" in pid_lower or "manufacture" in pid_lower:
        base.append("ものづくり補助金 認定支援機関確認書")
        base.append("付加価値額算出シート")
    if "saikouchiku" in pid_lower or "saikouchi" in pid_lower:
        base.append("認定経営革新等支援機関 確認書")
        base.append("事業再構築指針への該当性 説明書")
    if "shouene" in pid_lower or "gx" in pid_lower or "energy" in pid_lower:
        base.append("省エネ計算根拠書類")
        base.append("CO2 削減効果算定シート")
    if (deadline_kind or "").lower() in ("rolling", "ongoing"):
        base.append("随時受付 — 公募要領 最新版 確認")
    return base


def _related_shihou_for_program(program_id: str) -> list[str]:
    pid_lower = program_id.lower()
    if "kabuka" in pid_lower or "tax" in pid_lower:
        return ["税理士"]
    if "hojo" in pid_lower or "hojokin" in pid_lower or "subsidy" in pid_lower:
        return ["行政書士", "中小企業診断士"]
    if "monozu" in pid_lower or "saikouchi" in pid_lower:
        return ["行政書士", "中小企業診断士"]
    if "it" in pid_lower or "dx" in pid_lower:
        return ["行政書士", "IT 導入支援事業者"]
    return ["行政書士"]


def _compose_month_buckets(
    portfolio: list[dict[str, Any]],
    rounds_by_program: dict[str, list[dict[str, Any]]],
    scope_months: int,
    segment_summary: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    today = _dt.date.today()
    months = _iter_months(today, scope_months)
    bucket_index: dict[str, dict[str, Any]] = {
        ym: {
            "month": ym,
            "month_start": s.isoformat(),
            "month_end": e.isoformat(),
            "items": [],
            "item_count": 0,
            "estimated_total_yen": 0,
        }
        for ym, s, e in months
    }
    competitor_avg = int(segment_summary.get("median_adoption_count") or 0)
    program_count = int(segment_summary.get("top_program_count") or 0)
    total_target_yen = 0
    risk_flags: list[str] = []
    for program in portfolio:
        program_id = program["program_id"]
        rounds = rounds_by_program.get(program_id, [])
        for rnd in rounds:
            close = rnd.get("application_close_date")
            if not close:
                continue
            try:
                close_d = _dt.date.fromisoformat(close[:10])
            except ValueError:
                continue
            ym = f"{close_d.year:04d}-{close_d.month:02d}"
            if ym not in bucket_index:
                continue
            adoption_prob = _estimate_adoption_probability(
                score=program["applicability_score"],
                segment_adoption_count=competitor_avg,
                segment_program_count=program_count,
            )
            budget_yen = int(rnd.get("budget_yen") or 0)
            expected_yen = int(round(budget_yen * adoption_prob))
            item = {
                "program_id": program_id,
                "round_label": rnd.get("round_label"),
                "application_open_date": rnd.get("application_open_date"),
                "application_close_date": close,
                "announced_date": rnd.get("announced_date"),
                "disbursement_start_date": rnd.get("disbursement_start_date"),
                "budget_yen": budget_yen,
                "status": rnd.get("status"),
                "applicability_score": program["applicability_score"],
                "applied_status": program["applied_status"],
                "adoption_probability_estimate": adoption_prob,
                "expected_subsidy_yen": expected_yen,
                "competitor_density_estimate": competitor_avg,
                "required_documents": _required_documents_for_program(
                    program_id, program.get("deadline_kind")
                ),
                "related_shihou": _related_shihou_for_program(program_id),
                "source_url": rnd.get("source_url"),
            }
            bucket_index[ym]["items"].append(item)
            bucket_index[ym]["item_count"] += 1
            bucket_index[ym]["estimated_total_yen"] += expected_yen
            total_target_yen += expected_yen
            if budget_yen == 0:
                risk_flags.append(f"budget_yen unknown for round_id={rnd.get('round_id')!s}")
            if adoption_prob < 0.20:
                risk_flags.append(
                    f"low adoption probability ({adoption_prob}) for program {program_id}"
                )
    for bucket in bucket_index.values():
        bucket["items"].sort(key=lambda i: i["application_close_date"] or "9999-12-31")
    buckets = [bucket_index[ym] for ym, _, _ in months]
    aggregate = {
        "scope_months": scope_months,
        "total_program_rounds": sum(b["item_count"] for b in buckets),
        "total_estimated_subsidy_yen": total_target_yen,
        "avg_competitor_density": competitor_avg,
        "risk_flags": sorted(set(risk_flags))[:10],
    }
    return buckets, aggregate


def _empty_envelope(
    *, primary_input: dict[str, Any], rationale: str, status: str = "empty"
) -> dict[str, Any]:
    return {
        "tool_name": "product_subsidy_roadmap_12month",
        "product_id": _PRODUCT_ID,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": status,
            "product_id": _PRODUCT_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "rationale": rationale,
        },
        "months": [],
        "aggregate": {
            "scope_months": int(primary_input.get("scope_year") or 12),
            "total_program_rounds": 0,
            "total_estimated_subsidy_yen": 0,
            "avg_competitor_density": 0,
            "risk_flags": [],
        },
        "houjin_attributes": {},
        "segment_summary": {},
        "amendment_alerts": [],
        "portfolio_top": [],
        "agent_next_actions": [],
        "billing": {"unit": _BILLING_UNITS, "yen": _BILLING_UNITS * 3, "product_id": _PRODUCT_ID},
        "results": [],
        "total": 0,
        "limit": 0,
        "offset": 0,
        "citations": [],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a3_subsidy_roadmap",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["N2", "N4", "N6", "N7"],
        },
        "_billing_unit": _BILLING_UNITS,
        "_disclaimer": DISCLAIMER,
        "_related_shihou": list(_RELATED_SHIHOU),
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["N2", "N4", "N6", "N7"],
            "observed_at": today_iso_utc(),
        },
    }


def _agent_next_actions(
    buckets: list[dict[str, Any]],
    amendment_alerts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    upcoming_round_ids = [i["program_id"] for b in buckets for i in b["items"][:3]][:3]
    return [
        {
            "step": "review upcoming deadlines",
            "items": upcoming_round_ids,
            "rationale": (
                "Top-3 rolling-window rounds by close-date — agent should "
                "verify the 公募要領 1st-party page before drafting any artifact."
            ),
        },
        {
            "step": "subscribe to amendment alerts",
            "items": [str(a["amendment_diff_id"]) for a in amendment_alerts[:3]],
            "rationale": (
                "N6 amendment alerts that touch any program in the roadmap. "
                "Subscribe via dispatch_webhooks.py cron to receive amendment "
                "drift updates before each application close-date."
            ),
        },
        {
            "step": "engage 士業",
            "items": [],
            "rationale": (
                "§52 / §47条の2 / §72 / §1 / §3 — scaffold-only roadmap. "
                "申請代理 / 税務助言 / 監査調書 are out of scope; "
                "engage the matching 士業 (税理士 / 行政書士 / 中小企業診断士 / "
                "認定経営革新等支援機関) before submission."
            ),
        },
    ]


@mcp.tool(annotations=_READ_ONLY)
def product_subsidy_roadmap_12month(
    houjin_bangou: Annotated[
        str,
        Field(
            min_length=13,
            max_length=13,
            description="13-digit 法人番号 (houjin_bangou).",
        ),
    ],
    scope_year: Annotated[
        int,
        Field(
            ge=1,
            le=24,
            description=(
                "Rolling-month horizon (1-24). Default 12. Despite the name "
                "'scope_year' the unit is months — kept for parity with the "
                "product spec."
            ),
        ),
    ] = 12,
) -> dict[str, Any]:
    """[AUDIT, SENSITIVE - §52/§47条の2/§72/§1/§3] A3 - 補助金活用ロードマップ Pack.

    Composes N2 portfolio gap + N4 application rounds + N6 amendment
    alerts + N7 segment-view into one 12-month subsidy-activation
    roadmap. Each month bucket lists: applicable programs ordered by
    deadline, required documents, related 士業, estimated adoption
    probability, expected subsidy yen, competitor density.

    Output is scaffold-only — 採択 / 交付決定 / 申請代理 are out of
    scope. 1 billable call counts as 167 units (167 × ¥3 ≈ ¥500).
    NO LLM inference — pure SQLite + dict composition.
    """
    primary_input = {"houjin_bangou": houjin_bangou, "scope_year": int(scope_year)}

    conn = _open_ro()
    if conn is None:
        return _empty_envelope(
            primary_input=primary_input,
            rationale=(
                "autonomath.db is not present at the configured path. "
                "A3 roadmap requires the upstream lanes to be live."
            ),
            status="db_unavailable",
        )

    try:
        houjin_attrs = _lookup_houjin_attributes(conn, houjin_bangou)
        portfolio = _fetch_portfolio(conn, houjin_bangou, limit=40)
        if not portfolio:
            return _empty_envelope(
                primary_input=primary_input,
                rationale=(
                    f"No am_houjin_program_portfolio rows for houjin_bangou={houjin_bangou!r}. "
                    "Either outside the precomputed cohort or ETL has not landed yet."
                ),
                status="no_portfolio",
            )

        today = _dt.date.today()
        scope_months = 12 if scope_year == 12 else max(1, min(24, int(scope_year)))
        end_date = today + _dt.timedelta(days=31 * scope_months + 5)
        start_iso = today.isoformat()
        end_iso = end_date.isoformat()

        rounds_by_program: dict[str, list[dict[str, Any]]] = {}
        program_ids: set[str] = set()
        for p in portfolio:
            pid = p["program_id"]
            program_ids.add(pid)
            rounds_by_program[pid] = _fetch_rounds_for_program(conn, pid, start_iso, end_iso)

        amendment_alerts = _fetch_amendment_alerts(
            conn, houjin_bangou, program_ids, horizon_days=120
        )

        segment_summary = _fetch_segment_summary(
            conn,
            jsic_major=houjin_attrs["jsic_major"],
            size_band=houjin_attrs["size_band"],
            prefecture=houjin_attrs["prefecture"],
        )

        buckets, aggregate = _compose_month_buckets(
            portfolio=portfolio,
            rounds_by_program=rounds_by_program,
            scope_months=scope_months,
            segment_summary=segment_summary,
        )
    finally:
        conn.close()

    next_actions = _agent_next_actions(buckets, amendment_alerts)

    return {
        "tool_name": "product_subsidy_roadmap_12month",
        "product_id": _PRODUCT_ID,
        "schema_version": _SCHEMA_VERSION,
        "primary_result": {
            "status": "ok",
            "product_id": _PRODUCT_ID,
            "upstream_module": _UPSTREAM_MODULE,
            "primary_input": primary_input,
            "houjin_bangou": houjin_bangou,
            "scope_months": scope_months,
            "summary": {
                "portfolio_size": len(portfolio),
                "total_rounds_in_window": aggregate["total_program_rounds"],
                "total_estimated_subsidy_yen": aggregate["total_estimated_subsidy_yen"],
                "amendment_alerts": len(amendment_alerts),
            },
        },
        "months": buckets,
        "aggregate": aggregate,
        "houjin_attributes": houjin_attrs,
        "segment_summary": segment_summary,
        "amendment_alerts": amendment_alerts,
        "portfolio_top": portfolio[:10],
        "agent_next_actions": next_actions,
        "billing": {"unit": _BILLING_UNITS, "yen": _BILLING_UNITS * 3, "product_id": _PRODUCT_ID},
        "results": buckets,
        "total": len(buckets),
        "limit": len(buckets),
        "offset": 0,
        "citations": [
            {"source_url": r.get("source_url"), "round_id": r.get("round_id")}
            for rounds in rounds_by_program.values()
            for r in rounds[:1]
            if r.get("source_url")
        ][:10],
        "provenance": {
            "source_module": _UPSTREAM_MODULE,
            "product_id": _PRODUCT_ID,
            "wrap_kind": "product_a3_subsidy_roadmap",
            "observed_at": today_iso_utc(),
            "composed_lanes": ["N2", "N4", "N6", "N7"],
            "scope_months": scope_months,
        },
        "_billing_unit": _BILLING_UNITS,
        "_disclaimer": DISCLAIMER,
        "_related_shihou": list(_RELATED_SHIHOU),
        "_provenance": {
            "product_id": _PRODUCT_ID,
            "composed_lanes": ["N2", "N4", "N6", "N7"],
            "observed_at": today_iso_utc(),
        },
    }


__all__ = ["product_subsidy_roadmap_12month"]
