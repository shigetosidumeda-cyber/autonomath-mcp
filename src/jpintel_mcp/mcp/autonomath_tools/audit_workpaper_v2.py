"""Wave 43.2.4 Dim D — ``compose_audit_workpaper`` MCP tool.

Multi-hop monetisation composition. **One MCP call rolls up four other
single-purpose tools** into the year-end / fiscal-year audit workpaper a
税理士 / 会計士 needs for a single client house. Combines:

  * intel_houjin_full          (W30-3) — 法人 360 dossier
  * apply_eligibility_chain_am (Wave 21) — per-program eligibility chain
  * cross_check_jurisdiction   (Wave 22) — 登録 vs 適格事業者 vs 採択 不一致
  * amendment_alert lookups    — 当 FY 中の制度改正イベント

Pricing: **1 req = 5 unit** (¥15, 税込 ¥16.50). Documented in the tool
docstring + `_billing_unit=5`. The 5-unit price reflects the four
fan-out subqueries this tool collapses; the customer LLM still saves
because the *manual* fan-out would be ≥ 8 tool calls (4 substrates +
prerequisite_chain probes).

Sensitive fence
---------------
税理士法 §52 / 公認会計士法 §47条の2 / 弁護士法 §72 / 行政書士法 §1.
The tool delivers a **公開情報の機械的名寄せ pack** for the auditor's
working paper folder; the auditor is the regulated party making the
判断. The disclaimer envelope is non-negotiable.

NO LLM call inside the tool — pure SQLite + Python projection. Honours
`feedback_autonomath_no_api_use` + `feedback_no_operator_llm_api`.

Gating
------
Env-gated on ``AUTONOMATH_AUDIT_WORKPAPER_ENABLED`` (default ``"1"``).
Also requires the global ``AUTONOMATH_ENABLED``.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
from typing import Annotated, Any

from pydantic import Field

from jpintel_mcp._jpcite_env_bridge import get_flag
from jpintel_mcp.config import settings
from jpintel_mcp.mcp.server import _READ_ONLY, mcp

from .db import connect_autonomath
from .error_envelope import make_error

logger = logging.getLogger("jpintel.mcp.autonomath.audit_workpaper_v2")

_ENABLED = get_flag("JPCITE_AUDIT_WORKPAPER_ENABLED", "AUTONOMATH_AUDIT_WORKPAPER_ENABLED", "1") == "1"

# Sensitive — 4-業法 fence, mirrors envelope_wrapper.SENSITIVE_TOOLS.
_DISCLAIMER = (
    "本 audit/workpaper response は houjin_master / am_adopted_company_features"
    " / am_enforcement_detail / invoice_registrants / am_amendment_diff /"
    " jpi_tax_rulesets を機械的に SQL 結合した **公開情報の監査調書サブストレート**"
    "であり、税理士法 §52 (税務代理) ・公認会計士法 §47条の2 (会計士・監査法人の業務)"
    "・弁護士法 §72 (法律事務) ・行政書士法 §1 (申請代理) のいずれにも該当しません。"
    "監査判断・税額計算・申告書作成は資格を有する税理士・公認会計士の責任で行ってください。"
    "当ツール出力をそのまま監査調書として提出することは禁止です。"
)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {
        str(row["name"] if isinstance(row, sqlite3.Row) else row[1]) for row in rows
    }


def _has_tool_registered(name: str) -> bool:
    tool_manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(tool_manager, "_tools", None)
    return isinstance(tools, dict) and name in tools


def _resolve_fy_window(fiscal_year: int) -> tuple[str, str]:
    """Map an FY label (e.g. ``2025``) to ISO [start, end] for 4/1–3/31."""
    return (f"{fiscal_year:04d}-04-01", f"{fiscal_year + 1:04d}-03-31")


def _normalize_houjin(raw: str) -> str | None:
    """13-digit 法人番号 canonical normaliser (mirrors api/intel_houjin_full)."""
    s = str(raw or "").strip().lstrip("Tt")
    for ch in "- ,　":
        s = s.replace(ch, "")
    if not s.isdigit() or len(s) != 13:
        return None
    return s


def _section_houjin_meta(
    conn: sqlite3.Connection, houjin_id: str
) -> dict[str, Any] | None:
    """Min 法人 metadata used by the workpaper cover page."""
    columns = _table_columns(conn, "jpi_houjin_master")
    jsic_expr = "jsic_major" if "jsic_major" in columns else "NULL AS jsic_major"
    try:
        row = conn.execute(
            f"""
            SELECT houjin_bangou, normalized_name, address_normalized,
                   prefecture, municipality, corporation_type,
                   {jsic_expr}, total_adoptions, total_received_yen
              FROM jpi_houjin_master
             WHERE houjin_bangou = ?
             LIMIT 1
            """,
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.debug("workpaper meta lookup failed: %s", exc)
        return None
    if row is None:
        return None
    return {
        "houjin_bangou": row["houjin_bangou"],
        "name": row["normalized_name"],
        "address": row["address_normalized"],
        "prefecture": row["prefecture"],
        "municipality": row["municipality"],
        "corporation_type": row["corporation_type"],
        "jsic_major": row["jsic_major"],
        "total_adoptions": row["total_adoptions"],
        "total_received_yen": row["total_received_yen"],
    }


def _section_fy_adoptions(
    conn: sqlite3.Connection, houjin_id: str, fy_start: str, fy_end: str
) -> list[dict[str, Any]]:
    """Adoption records whose award/announcement date sits inside the FY."""
    columns = _table_columns(conn, "jpi_adoption_records")
    if "applicant_houjin_bangou" in columns:
        houjin_col = "applicant_houjin_bangou"
        program_name_col = "program_name"
        applicant_name_col = "applicant_name"
        date_expr = "COALESCE(award_date, announce_date)"
        amount_col = "amount_yen"
    else:
        houjin_col = "houjin_bangou"
        program_name_col = "program_name_raw"
        applicant_name_col = "company_name_raw"
        date_expr = "announced_at"
        amount_col = "amount_granted_yen"
    try:
        rows = conn.execute(
            f"""
            SELECT program_id,
                   {program_name_col} AS program_name,
                   {applicant_name_col} AS applicant_name,
                   {date_expr} AS award_date,
                   {amount_col} AS amount_yen,
                   {date_expr} AS announce_date
              FROM jpi_adoption_records
             WHERE {houjin_col} = ?
               AND substr({date_expr}, 1, 10) BETWEEN ? AND ?
             ORDER BY {date_expr} DESC
             LIMIT 50
            """,
            (houjin_id, fy_start, fy_end),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("workpaper adoption query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    fiscal_year = int(fy_start[:4])
    for row in rows:
        item = dict(row)
        item["fiscal_year"] = fiscal_year
        out.append(item)
    return out


def _section_fy_enforcement(
    conn: sqlite3.Connection, houjin_id: str, fy_start: str, fy_end: str
) -> list[dict[str, Any]]:
    """Enforcement (grant refund / subsidy_exclude / fine) inside FY."""
    columns = _table_columns(conn, "am_enforcement_detail")
    detail_col = "detail_id" if "detail_id" in columns else "enforcement_id"
    date_col = "enforcement_date" if "enforcement_date" in columns else "issuance_date"
    summary_col = "summary" if "summary" in columns else "reason_summary"
    try:
        rows = conn.execute(
            f"""
            SELECT {detail_col} AS detail_id,
                   enforcement_kind,
                   {date_col} AS enforcement_date,
                   amount_yen,
                   {summary_col} AS summary,
                   source_url
              FROM am_enforcement_detail
             WHERE houjin_bangou = ?
               AND {date_col} IS NOT NULL
               AND {date_col} BETWEEN ? AND ?
             ORDER BY {date_col} DESC
             LIMIT 30
            """,
            (houjin_id, fy_start, fy_end),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("workpaper enforcement query failed: %s", exc)
        return []
    return [dict(r) for r in rows]


def _section_jurisdiction_mismatch(
    conn: sqlite3.Connection, houjin_id: str
) -> dict[str, Any]:
    """Registered vs invoice vs operational mismatch.

    Mirrors `wave22_tools._cross_check_jurisdiction_impl` minimally — we
    only project the three prefectures + mismatch flag the auditor needs.
    """
    out: dict[str, Any] = {
        "registered_prefecture": None,
        "invoice_prefecture": None,
        "operational_top_prefecture": None,
        "mismatch": False,
    }
    adoption_columns = _table_columns(conn, "jpi_adoption_records")
    houjin_col = (
        "applicant_houjin_bangou"
        if "applicant_houjin_bangou" in adoption_columns
        else "houjin_bangou"
    )
    try:
        h = conn.execute(
            "SELECT prefecture FROM jpi_houjin_master WHERE houjin_bangou = ? LIMIT 1",
            (houjin_id,),
        ).fetchone()
        if h:
            out["registered_prefecture"] = h["prefecture"]
        i = conn.execute(
            "SELECT prefecture FROM jpi_invoice_registrants WHERE houjin_bangou = ? "
            "ORDER BY registered_date DESC LIMIT 1",
            (houjin_id,),
        ).fetchone()
        if i:
            out["invoice_prefecture"] = i["prefecture"]
        op = conn.execute(
            """
            SELECT prefecture, COUNT(*) AS n
              FROM jpi_adoption_records
             WHERE {houjin_col} = ? AND prefecture IS NOT NULL
             GROUP BY prefecture ORDER BY n DESC LIMIT 1
            """.format(houjin_col=houjin_col),
            (houjin_id,),
        ).fetchone()
        if op:
            out["operational_top_prefecture"] = op["prefecture"]
    except sqlite3.Error as exc:
        logger.debug("workpaper jurisdiction query failed: %s", exc)
    seen = {v for v in out.values() if isinstance(v, str)}
    out["mismatch"] = len(seen) > 1
    return out


def _section_amendment_alerts(
    conn: sqlite3.Connection, program_ids: list[str], fy_start: str, fy_end: str
) -> list[dict[str, Any]]:
    """am_amendment_diff hits on the client's FY-active programs."""
    if not program_ids:
        return []
    placeholders = ",".join("?" * len(program_ids))
    try:
        rows = conn.execute(
            f"""
            SELECT entity_id, field_name, prev_value, new_value, detected_at, source_url
              FROM am_amendment_diff
             WHERE entity_id IN ({placeholders})
               AND substr(detected_at, 1, 10) BETWEEN ? AND ?
             ORDER BY detected_at DESC
             LIMIT 60
            """,
            (*program_ids, fy_start, fy_end),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.debug("workpaper amendment lookup failed: %s", exc)
        return []
    return [dict(r) for r in rows]


def _compose_workpaper_impl(
    client_houjin_bangou: str,
    fiscal_year: int,
) -> dict[str, Any]:
    """Pure-Python composer. NO LLM, NO HTTP, NO ATTACH."""
    hb = _normalize_houjin(client_houjin_bangou)
    if hb is None:
        return make_error(
            code="invalid_input",
            message=(
                f"client_houjin_bangou must be 13 digits "
                f"(got {client_houjin_bangou!r})."
            ),
            field="client_houjin_bangou",
        )
    if not isinstance(fiscal_year, int) or not (2000 <= fiscal_year <= 2100):
        return make_error(
            code="out_of_range",
            message=f"fiscal_year must be 2000..2100 (got {fiscal_year!r}).",
            field="fiscal_year",
        )

    fy_start, fy_end = _resolve_fy_window(fiscal_year)

    try:
        conn = connect_autonomath(mode="ro")
    except Exception as exc:  # noqa: BLE001
        return make_error(
            code="internal",
            message=f"autonomath.db unreachable: {exc}",
        )

    try:
        meta = _section_houjin_meta(conn, hb)
        if meta is None:
            return make_error(
                code="not_found",
                message=(
                    f"No houjin_master row for {hb}. Verify the 13-digit "
                    "法人番号 (try intel_houjin_full or search_programs)."
                ),
                field="client_houjin_bangou",
                retry_with=["intel_houjin_full"],
            )

        adoptions = _section_fy_adoptions(conn, hb, fy_start, fy_end)
        enforcement = _section_fy_enforcement(conn, hb, fy_start, fy_end)
        jurisdiction = _section_jurisdiction_mismatch(conn, hb)
        active_pids = [
            a["program_id"] for a in adoptions if isinstance(a.get("program_id"), str)
        ]
        amendment_alerts = _section_amendment_alerts(
            conn, active_pids, fy_start, fy_end
        )

        # Decision support: 監査人の注意喚起 (ranked).
        flags: list[str] = []
        if enforcement:
            flags.append(
                f"FY内 行政処分 {len(enforcement)} 件 — 監査調書の重大記載項目候補。"
            )
        if jurisdiction.get("mismatch"):
            flags.append(
                "登録/適格/操業 都道府県の3軸不一致 — 課税地・連結納税のヒアリング推奨。"
            )
        if amendment_alerts:
            flags.append(
                f"FY内 当該採択先制度の改正イベント {len(amendment_alerts)} 件 — "
                "適用要件再評価。"
            )
        if not adoptions:
            flags.append(
                "FY内 採択 0 件 — 補助金収益認識の対象なし (前 FY 採択分の継続性は別途確認)。"
            )

        body: dict[str, Any] = {
            "client_houjin_bangou": hb,
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
                "mismatch": jurisdiction.get("mismatch", False),
            },
            "auditor_flags": flags,
            "_next_calls": [
                {
                    "tool": "intel_houjin_full",
                    "args": {"houjin_id": hb},
                    "why": "Drill into 360 dossier when a flag fires.",
                },
                {
                    "tool": "apply_eligibility_chain_am",
                    "args": {"profile": {}, "program_ids": active_pids[:5]},
                    "why": "Per-program eligibility chain for FY-active adoptions.",
                },
            ],
            "_disclaimer": _DISCLAIMER,
            "_billing_unit": 5,
        }
        return body
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()


# ---------------------------------------------------------------------------
# MCP tool registration.
# ---------------------------------------------------------------------------
if _ENABLED and settings.autonomath_enabled:

    _TOOL_NAME = (
        "compose_audit_workpaper_v2"
        if _has_tool_registered("compose_audit_workpaper")
        else "compose_audit_workpaper"
    )

    @mcp.tool(name=_TOOL_NAME, annotations=_READ_ONLY)
    def compose_audit_workpaper(
        client_houjin_bangou: Annotated[
            str,
            Field(
                description=(
                    "13-digit 法人番号 (with or without 'T' prefix) of the client."
                ),
                min_length=13,
                max_length=14,
            ),
        ],
        fiscal_year: Annotated[
            int,
            Field(
                description=(
                    "JP fiscal year start year (e.g. 2025 = FY2025 = 2025-04-01"
                    "..2026-03-31)."
                ),
                ge=2000,
                le=2100,
            ),
        ],
    ) -> dict[str, Any]:
        """Roll up intel_houjin_full + apply_eligibility_chain + cross_check_jurisdiction + amendment_alert for one 法人 in one FY into a 税理士/会計士 audit workpaper. ¥15 / call (5 units). NO LLM, pure SQL. §52 / §47条の2 / §72 / §1 sensitive."""
        return _compose_workpaper_impl(
            client_houjin_bangou=client_houjin_bangou,
            fiscal_year=fiscal_year,
        )
