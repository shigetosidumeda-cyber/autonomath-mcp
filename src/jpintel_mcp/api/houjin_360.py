"""GET /v1/houjin/{houjin_bangou}/360 — unified houjin 360 surface.

R8 (2026-05-07). One 法人番号 → all public-corpus surfaces in a single
GET, plus a deterministic multi-axis scoring block. Filling the gap that
existed between two cousins:

* ``/v1/houjin/{bangou}``                 — gBizINFO 21 facts + adoption
                                            rollup + enforcement rollup
                                            (no bids, no recent_news,
                                             no watch_alerts, no scoring)
* ``/v1/intel/houjin/{id}/full``          — meta + adoption + enforcement
                                            + invoice + peer + jurisdiction
                                            + watch_status + decision_support
                                            (no bids_won, no recent_news,
                                             no compliance/credit/risk
                                             tri-axis numeric scoring)

This endpoint is the **only** surface that joins:

* ``houjin_master``                  — meta (NTA canonical name + addr)
* ``jpi_adoption_records``           — full ``adoption_records`` (top-N)
* ``am_enforcement_detail``          — ``enforcement_cases`` (top-N)
* ``bids``                           — ``bids_won`` via ``winner_houjin_bangou``
* ``jpi_invoice_registrants``        — invoice registrant status
* ``am_amendment_diff``              — ``recent_news`` (latest deltas)
* ``customer_watches`` + watch row   — ``watch_alerts``

Plus a deterministic 3-axis scoring block (NO LLM, NO opinion):

* ``risk_score``        — 0..1, derived from enforcement count × severity +
                          invoice revoked/expired + amendment-burst signal
* ``credit_score``      — 0..1, derived from adoption count × amount +
                          bids won × awarded_amount + capital + employees
* ``compliance_score``  — 0..1, derived from invoice active + enforcement
                          absence + jurisdiction consistency + master
                          completeness

Pricing: ¥3 / call (1 unit). NO LLM call. Pure SQLite + Python projection.

Sensitive: §52 (税理士法) + §72 (弁護士法) + §1 (行政書士法) fence.
The 3-axis scores are *descriptive* signals over the public corpus — they
are never a 与信 / 税務 / 法令適用 verdict.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.houjin_360")

router = APIRouter(prefix="/v1/houjin", tags=["houjin"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_BANGOU_RE = re.compile(r"^\d{13}$")

_DEFAULT_LIMIT = 10
_HARD_LIMIT = 50

# Severity → weight contribution to the risk axis. Mirrors the ranking in
# ``intel_houjin_full._section_enforcement`` so the two endpoints assign
# the same severity label to the same enforcement_kind.
_ENFORCEMENT_KIND_WEIGHT: dict[str, float] = {
    "license_revoke": 1.00,
    "fine": 0.85,
    "grant_refund": 0.85,
    "subsidy_exclude": 0.55,
    "contract_suspend": 0.55,
    "investigation": 0.30,
    "business_improvement": 0.20,
    "warning": 0.15,
}
_ENFORCEMENT_KIND_SEVERITY: dict[str, str] = {
    "license_revoke": "high",
    "fine": "high",
    "grant_refund": "high",
    "subsidy_exclude": "medium",
    "contract_suspend": "medium",
    "investigation": "low",
    "business_improvement": "low",
    "warning": "low",
}

# Sensitive — §52 / §72 / §1 fence (mirrors envelope_wrapper.SENSITIVE_TOOLS).
_DISCLAIMER = (
    "本 houjin/360 response は houjin_master + jpi_adoption_records + "
    "am_enforcement_detail + bids + jpi_invoice_registrants + "
    "am_amendment_diff + customer_watches を機械的に SQL 結合した "
    "**公開情報の名寄せ結果** であり、税理士法 §52 (税務代理) ・"
    "弁護士法 §72 (法律事務) ・行政書士法 §1の2 (申請代理) のいずれにも"
    "該当しません。risk_score / credit_score / compliance_score は "
    "公開コーパスからの **descriptive 指標** であり、与信判断・"
    "税務判断・法令適用判断ではありません。確定判断は資格を有する"
    "税理士・弁護士・行政書士・公認会計士へ。"
)


# ---------------------------------------------------------------------------
# DB connection helpers
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    """Resolve the autonomath.db path. Mirrors api/houjin.py."""
    try:
        p = settings.autonomath_db_path
        if isinstance(p, Path):
            return p
        return Path(str(p))
    except AttributeError:
        return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
    """Open ``autonomath.db`` read-only. Returns None when missing."""
    p = _autonomath_db_path()
    if not p.exists() or p.stat().st_size == 0:
        return None
    uri = f"file:{p}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute("PRAGMA query_only=1")
            conn.execute("PRAGMA temp_store=MEMORY")
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


def _normalize_bangou(raw: str) -> str | None:
    """Strip 'T' prefix, NFKC fullwidth-digits, hyphens, spaces."""
    s = unicodedata.normalize("NFKC", str(raw or ""))
    s = s.strip().lstrip("Tt")
    for ch in "- ,　":
        s = s.replace(ch, "")
    if not s.isdigit() or len(s) != 13:
        return None
    return s


# ---------------------------------------------------------------------------
# Surface composers — each soft-fails on missing substrate.
# ---------------------------------------------------------------------------


def _section_master(
    am_conn: sqlite3.Connection, bangou: str, missing: list[str]
) -> dict[str, Any] | None:
    """master — houjin_master row + capital/employees from EAV facts."""
    if not _table_exists(am_conn, "houjin_master"):
        missing.append("houjin_master")
        return None
    try:
        row = am_conn.execute(
            "SELECT houjin_bangou, normalized_name, address_normalized, "
            "       prefecture, municipality, corporation_type, "
            "       established_date, close_date, jsic_major, jsic_middle, "
            "       jsic_minor, total_adoptions, total_received_yen, "
            "       last_updated_nta "
            "  FROM houjin_master "
            " WHERE houjin_bangou = ? LIMIT 1",
            (bangou,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("houjin_master query failed: %s", exc)
        return None
    if row is None:
        return None

    capital_yen: int | None = None
    employees: int | None = None
    rep_name: str | None = None
    company_url: str | None = None
    if _table_exists(am_conn, "am_entity_facts"):
        try:
            rows = am_conn.execute(
                "SELECT field_name, field_value_text, field_value_numeric "
                "  FROM am_entity_facts "
                " WHERE entity_id = ? "
                "   AND field_name IN ('corp.capital_amount', "
                "                       'corp.employee_count', "
                "                       'corp.representative', "
                "                       'corp.company_url') "
                " LIMIT 16",
                (f"houjin:{bangou}",),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("am_entity_facts query failed: %s", exc)
            rows = []
        for fact in rows:
            fname = fact["field_name"]
            num = fact["field_value_numeric"]
            txt = fact["field_value_text"]
            if fname == "corp.capital_amount":
                with contextlib.suppress(TypeError, ValueError):
                    if num is not None:
                        capital_yen = int(float(num))
                    elif txt is not None:
                        capital_yen = int(float(txt))
            elif fname == "corp.employee_count":
                with contextlib.suppress(TypeError, ValueError):
                    if num is not None:
                        employees = int(float(num))
                    elif txt is not None:
                        employees = int(float(txt))
            elif fname == "corp.representative":
                rep_name = txt
            elif fname == "corp.company_url":
                company_url = txt

    address = row["address_normalized"]
    if not address:
        parts = [row["prefecture"], row["municipality"]]
        address = "".join(p for p in parts if p) or None

    jsic_codes = [c for c in (row["jsic_major"], row["jsic_middle"], row["jsic_minor"]) if c]
    jsic_value = "/".join(jsic_codes) if jsic_codes else None

    return {
        "houjin_bangou": row["houjin_bangou"],
        "name": row["normalized_name"],
        "address": address,
        "prefecture": row["prefecture"],
        "municipality": row["municipality"],
        "corporation_type": row["corporation_type"],
        "established_date": row["established_date"],
        "close_date": row["close_date"],
        "active": row["close_date"] is None,
        "jsic_major": row["jsic_major"],
        "jsic": jsic_value,
        "capital_yen": capital_yen,
        "employees": employees,
        "representative": rep_name,
        "company_url": company_url,
        "total_adoptions_rollup": int(row["total_adoptions"] or 0),
        "total_received_yen_rollup": int(row["total_received_yen"] or 0),
        "last_updated_nta": row["last_updated_nta"],
    }


def _section_adoption_records(
    am_conn: sqlite3.Connection,
    bangou: str,
    *,
    limit: int,
    missing: list[str],
) -> dict[str, Any]:
    """adoption_records — full top-N + total + total amount."""
    if not _table_exists(am_conn, "jpi_adoption_records"):
        missing.append("jpi_adoption_records")
        return {"total": 0, "total_amount_yen": 0, "records": []}
    try:
        agg = am_conn.execute(
            "SELECT COUNT(*) AS n, "
            "       COALESCE(SUM(amount_granted_yen), 0) AS amt "
            "  FROM jpi_adoption_records WHERE houjin_bangou = ?",
            (bangou,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("jpi_adoption_records aggregate failed: %s", exc)
        return {"total": 0, "total_amount_yen": 0, "records": []}
    total = int(agg["n"]) if agg and agg["n"] is not None else 0
    total_amount = int(agg["amt"]) if agg and agg["amt"] is not None else 0

    records: list[dict[str, Any]] = []
    if total > 0:
        try:
            rows = am_conn.execute(
                "SELECT program_id, program_name_raw, round_label, "
                "       amount_granted_yen, announced_at, prefecture, "
                "       industry_jsic_medium, source_url "
                "  FROM jpi_adoption_records "
                " WHERE houjin_bangou = ? "
                " ORDER BY COALESCE(amount_granted_yen, 0) DESC, "
                "          COALESCE(announced_at, '') DESC "
                " LIMIT ?",
                (bangou, int(limit)),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("jpi_adoption_records detail failed: %s", exc)
            rows = []
        for r in rows:
            announced = r["announced_at"] or ""
            year = announced[:4] if announced and len(announced) >= 4 else None
            amt = r["amount_granted_yen"]
            records.append(
                {
                    "program_id": r["program_id"],
                    "program_name": r["program_name_raw"],
                    "round_label": r["round_label"],
                    "amount_granted_yen": int(amt) if amt is not None else None,
                    "announced_at": r["announced_at"],
                    "year": year,
                    "prefecture": r["prefecture"],
                    "industry_jsic_medium": r["industry_jsic_medium"],
                    "source_url": r["source_url"],
                }
            )
    return {
        "total": total,
        "total_amount_yen": total_amount,
        "records": records,
    }


def _section_enforcement_cases(
    am_conn: sqlite3.Connection,
    bangou: str,
    *,
    limit: int,
    missing: list[str],
) -> dict[str, Any]:
    """enforcement_cases — full top-N + total + total amount + max severity."""
    if not _table_exists(am_conn, "am_enforcement_detail"):
        missing.append("am_enforcement_detail")
        return {
            "total": 0,
            "total_amount_yen": 0,
            "max_severity": None,
            "records": [],
        }
    try:
        agg = am_conn.execute(
            "SELECT COUNT(*) AS n, "
            "       COALESCE(SUM(amount_yen), 0) AS amt "
            "  FROM am_enforcement_detail WHERE houjin_bangou = ?",
            (bangou,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("am_enforcement_detail aggregate failed: %s", exc)
        return {
            "total": 0,
            "total_amount_yen": 0,
            "max_severity": None,
            "records": [],
        }
    total = int(agg["n"]) if agg and agg["n"] is not None else 0
    total_amount = int(agg["amt"]) if agg and agg["amt"] is not None else 0

    records: list[dict[str, Any]] = []
    max_severity: str | None = None
    if total > 0:
        try:
            rows = am_conn.execute(
                "SELECT issuance_date, enforcement_kind, target_name, "
                "       reason_summary, amount_yen, issuing_authority, "
                "       related_law_ref, source_url, exclusion_start, "
                "       exclusion_end "
                "  FROM am_enforcement_detail "
                " WHERE houjin_bangou = ? "
                " ORDER BY issuance_date DESC "
                " LIMIT ?",
                (bangou, int(limit)),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("am_enforcement_detail detail failed: %s", exc)
            rows = []
        severity_rank = {"low": 1, "medium": 2, "high": 3}
        max_rank = 0
        for r in rows:
            kind = r["enforcement_kind"] or ""
            severity = _ENFORCEMENT_KIND_SEVERITY.get(kind, "low")
            rank = severity_rank.get(severity, 0)
            if rank > max_rank:
                max_rank = rank
                max_severity = severity
            amt = r["amount_yen"]
            records.append(
                {
                    "issuance_date": r["issuance_date"],
                    "enforcement_kind": kind or None,
                    "severity": severity,
                    "target_name": r["target_name"],
                    "reason_summary": r["reason_summary"],
                    "amount_yen": int(amt) if amt is not None else None,
                    "issuing_authority": r["issuing_authority"],
                    "related_law_ref": r["related_law_ref"],
                    "exclusion_start": r["exclusion_start"],
                    "exclusion_end": r["exclusion_end"],
                    "source_url": r["source_url"],
                }
            )
    return {
        "total": total,
        "total_amount_yen": total_amount,
        "max_severity": max_severity,
        "records": records,
    }


def _section_bids_won(
    jpintel_conn: sqlite3.Connection,
    am_conn: sqlite3.Connection | None,
    bangou: str,
    *,
    limit: int,
    missing: list[str],
) -> dict[str, Any]:
    """bids_won — bids ``winner_houjin_bangou`` filter (top-N by awarded amount).

    Tries jpintel.db first (canonical bids table), then falls back to the
    autonomath.db mirror (jpi_bids) when present. Soft-fails if neither
    is available.
    """
    table: str | None = None
    chosen_conn: sqlite3.Connection | None = None
    if _table_exists(jpintel_conn, "bids"):
        chosen_conn = jpintel_conn
        table = "bids"
    elif am_conn is not None and _table_exists(am_conn, "jpi_bids"):
        chosen_conn = am_conn
        table = "jpi_bids"
    elif am_conn is not None and _table_exists(am_conn, "bids"):
        chosen_conn = am_conn
        table = "bids"
    if chosen_conn is None or table is None:
        missing.append("bids")
        return {"total": 0, "total_awarded_yen": 0, "records": []}

    try:
        agg = chosen_conn.execute(
            f"SELECT COUNT(*) AS n, "
            f"       COALESCE(SUM(awarded_amount_yen), 0) AS amt "
            f"  FROM {table} WHERE winner_houjin_bangou = ?",
            (bangou,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("%s aggregate failed: %s", table, exc)
        return {"total": 0, "total_awarded_yen": 0, "records": []}
    total = int(agg["n"]) if agg and agg["n"] is not None else 0
    total_amount = int(agg["amt"]) if agg and agg["amt"] is not None else 0

    records: list[dict[str, Any]] = []
    if total > 0:
        try:
            rows = chosen_conn.execute(
                f"SELECT unified_id, bid_title, bid_kind, procuring_entity, "
                f"       ministry, prefecture, decision_date, "
                f"       awarded_amount_yen, budget_ceiling_yen, "
                f"       classification_code, source_url "
                f"  FROM {table} "
                f" WHERE winner_houjin_bangou = ? "
                f" ORDER BY COALESCE(awarded_amount_yen, 0) DESC, "
                f"          COALESCE(decision_date, '') DESC "
                f" LIMIT ?",
                (bangou, int(limit)),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("%s detail failed: %s", table, exc)
            rows = []
        for r in rows:
            decision = r["decision_date"] or ""
            year = decision[:4] if decision and len(decision) >= 4 else None
            awarded = r["awarded_amount_yen"]
            ceiling = r["budget_ceiling_yen"]
            records.append(
                {
                    "unified_id": r["unified_id"],
                    "bid_title": r["bid_title"],
                    "bid_kind": r["bid_kind"],
                    "procuring_entity": r["procuring_entity"],
                    "ministry": r["ministry"],
                    "prefecture": r["prefecture"],
                    "decision_date": r["decision_date"],
                    "year": year,
                    "awarded_amount_yen": int(awarded) if awarded is not None else None,
                    "budget_ceiling_yen": int(ceiling) if ceiling is not None else None,
                    "classification_code": r["classification_code"],
                    "source_url": r["source_url"],
                }
            )
    return {
        "total": total,
        "total_awarded_yen": total_amount,
        "records": records,
    }


def _section_invoice_status(
    am_conn: sqlite3.Connection, bangou: str, missing: list[str]
) -> dict[str, Any]:
    """invoice_registrant_status — invoice_registrants lookup."""
    table: str | None = None
    for candidate in ("jpi_invoice_registrants", "invoice_registrants"):
        if _table_exists(am_conn, candidate):
            table = candidate
            break
    if table is None:
        missing.append("invoice_registrants")
        return {
            "registered": False,
            "registration_no": None,
            "registered_date": None,
            "status": "not_found",
        }
    try:
        row = am_conn.execute(
            f"SELECT invoice_registration_number, registered_date, "
            f"       revoked_date, expired_date, prefecture, "
            f"       registrant_kind, normalized_name "
            f"  FROM {table} "
            f" WHERE houjin_bangou = ? LIMIT 1",
            (bangou,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("%s query failed: %s", table, exc)
        return {
            "registered": False,
            "registration_no": None,
            "registered_date": None,
            "status": "not_found",
        }
    if row is None:
        return {
            "registered": False,
            "registration_no": None,
            "registered_date": None,
            "status": "not_found",
        }
    revoked = row["revoked_date"]
    expired = row["expired_date"]
    is_active = not (revoked or expired)
    if revoked:
        status = "revoked"
    elif expired:
        status = "expired"
    elif is_active and row["invoice_registration_number"]:
        status = "active"
    else:
        status = "inactive"
    return {
        "registered": bool(is_active),
        "registration_no": row["invoice_registration_number"],
        "registered_date": row["registered_date"],
        "revoked_date": revoked,
        "expired_date": expired,
        "prefecture": row["prefecture"],
        "registrant_kind": row["registrant_kind"],
        "registrant_name": row["normalized_name"],
        "status": status,
    }


def _section_recent_news(
    am_conn: sqlite3.Connection,
    bangou: str,
    *,
    limit: int,
    missing: list[str],
) -> list[dict[str, Any]]:
    """recent_news — am_amendment_diff entries for ``houjin:<bangou>``.

    Local-corpus only. NO web fetch, NO LLM. The "news" framing is the
    minimum-viable surface that explains *why* a watch_alert fired —
    the amendment diff rows ARE the local news signal.
    """
    if not _table_exists(am_conn, "am_amendment_diff"):
        missing.append("am_amendment_diff")
        return []
    try:
        rows = am_conn.execute(
            "SELECT field_name, prev_value, new_value, detected_at, source_url "
            "  FROM am_amendment_diff "
            " WHERE entity_id = ? "
            " ORDER BY detected_at DESC "
            " LIMIT ?",
            (f"houjin:{bangou}", int(limit)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_amendment_diff query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "field_name": r["field_name"],
                "prev_value": r["prev_value"],
                "new_value": r["new_value"],
                "detected_at": r["detected_at"],
                "source_url": r["source_url"],
                "kind": "amendment_diff",
            }
        )
    return out


def _section_watch_alerts(
    jpintel_conn: sqlite3.Connection,
    am_conn: sqlite3.Connection | None,
    bangou: str,
    *,
    limit: int,
    missing: list[str],
) -> dict[str, Any]:
    """watch_alerts — customer_watches subscribers + last_amendment + active flags."""
    is_watched = False
    subscribers = 0
    last_event_at: str | None = None
    registered_at: str | None = None

    if _table_exists(jpintel_conn, "customer_watches"):
        try:
            row = jpintel_conn.execute(
                "SELECT COUNT(*) AS n, MAX(last_event_at) AS last_at, "
                "       MIN(registered_at) AS reg_at "
                "  FROM customer_watches "
                " WHERE watch_kind = 'houjin' "
                "   AND target_id = ? "
                "   AND status = 'active'",
                (bangou,),
            ).fetchone()
            if row is not None:
                subscribers = int(row["n"]) if row["n"] is not None else 0
                is_watched = subscribers > 0
                last_event_at = row["last_at"]
                registered_at = row["reg_at"]
        except sqlite3.Error as exc:
            logger.warning("customer_watches query failed: %s", exc)
    else:
        missing.append("customer_watches")

    last_amendment: str | None = None
    recent_alerts: list[dict[str, Any]] = []
    if am_conn is not None and _table_exists(am_conn, "am_amendment_diff"):
        try:
            row = am_conn.execute(
                "SELECT MAX(detected_at) AS dt FROM am_amendment_diff WHERE entity_id = ?",
                (f"houjin:{bangou}",),
            ).fetchone()
            last_amendment = row["dt"] if row else None
        except sqlite3.Error as exc:
            logger.warning("am_amendment_diff MAX query failed: %s", exc)
        # Surface the most recent N diffs as the "alert events" list so
        # watchers see what they would have been notified about.
        try:
            rows = am_conn.execute(
                "SELECT field_name, new_value, detected_at "
                "  FROM am_amendment_diff "
                " WHERE entity_id = ? "
                " ORDER BY detected_at DESC LIMIT ?",
                (f"houjin:{bangou}", int(limit)),
            ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("am_amendment_diff alert detail failed: %s", exc)
            rows = []
        for r in rows:
            recent_alerts.append(
                {
                    "field_name": r["field_name"],
                    "new_value": r["new_value"],
                    "detected_at": r["detected_at"],
                    "kind": "amendment",
                }
            )
    elif am_conn is None:
        missing.append("am_amendment_diff")

    return {
        "is_watched": bool(is_watched),
        "watch_subscribers": subscribers,
        "first_registered_at": registered_at,
        "last_event_at": last_event_at,
        "last_amendment_at": last_amendment,
        "recent_alerts": recent_alerts,
    }


# ---------------------------------------------------------------------------
# Multi-axis scoring (deterministic, descriptive — never a verdict).
# ---------------------------------------------------------------------------


def _logistic_normalise(value: float, *, scale: float) -> float:
    """Squash a non-negative count / amount onto [0, 1].

    Uses ``value / (value + scale)`` — a smooth saturating curve that maps
    0 to 0 and large values to ~1, with the half-way point at ``scale``.
    """
    v = max(0.0, float(value))
    if scale <= 0:
        return 0.0
    return round(v / (v + scale), 4)


def _score_risk(
    enforcement: dict[str, Any],
    invoice: dict[str, Any],
    news: list[dict[str, Any]],
) -> dict[str, Any]:
    """risk_score — higher = more risk signal on the public corpus.

    Inputs:
      * enforcement.records[].enforcement_kind  (severity weight)
      * invoice.status                          (revoked / expired adds risk)
      * news (amendment_diff burst)             (>3 in window → modest add)
    """
    components: dict[str, float] = {}

    # Enforcement weight = sum of per-record kind weights, capped at 4.0
    # (≈ 4 high-severity items saturates the axis).
    raw_weight = 0.0
    for record in enforcement.get("records") or []:
        kind = (record or {}).get("enforcement_kind") or ""
        raw_weight += _ENFORCEMENT_KIND_WEIGHT.get(kind, 0.0)
    enforcement_score = _logistic_normalise(raw_weight, scale=1.5)
    components["enforcement"] = enforcement_score

    # Invoice status. Active → 0; inactive/not_found → small penalty;
    # revoked/expired → larger.
    status = invoice.get("status") or "not_found"
    if status == "revoked":
        invoice_score = 0.85
    elif status == "expired":
        invoice_score = 0.55
    elif status == "inactive":
        invoice_score = 0.30
    elif status == "not_found":
        invoice_score = 0.15
    else:  # active
        invoice_score = 0.00
    components["invoice"] = invoice_score

    # News burst — local-corpus amendment diffs in the response window.
    news_count = len(news or [])
    news_score = _logistic_normalise(news_count, scale=5.0)
    components["news_burst"] = news_score

    # Weighted: enforcement 0.55 / invoice 0.30 / news 0.15.
    total = 0.55 * enforcement_score + 0.30 * invoice_score + 0.15 * news_score
    return {
        "value": round(total, 4),
        "components": components,
        "weights": {"enforcement": 0.55, "invoice": 0.30, "news_burst": 0.15},
        "interpretation": "0 = clean public footprint; 1 = saturated risk signal",
    }


def _score_credit(
    master: dict[str, Any] | None,
    adoption: dict[str, Any],
    bids: dict[str, Any],
) -> dict[str, Any]:
    """credit_score — higher = stronger public-corpus business footprint.

    Inputs:
      * adoption.total + adoption.total_amount_yen  (gov adoption track)
      * bids.total + bids.total_awarded_yen         (procurement track)
      * master.capital_yen + master.employees       (size signal)
    """
    components: dict[str, float] = {}

    adoption_total = int(adoption.get("total") or 0)
    adoption_amount = int(adoption.get("total_amount_yen") or 0)
    adoption_score = 0.5 * _logistic_normalise(
        adoption_total, scale=3.0
    ) + 0.5 * _logistic_normalise(adoption_amount / 1_000_000, scale=20.0)
    adoption_score = round(adoption_score, 4)
    components["adoption"] = adoption_score

    bids_total = int(bids.get("total") or 0)
    bids_amount = int(bids.get("total_awarded_yen") or 0)
    bids_score = 0.5 * _logistic_normalise(bids_total, scale=3.0) + 0.5 * _logistic_normalise(
        bids_amount / 1_000_000, scale=50.0
    )
    bids_score = round(bids_score, 4)
    components["bids"] = bids_score

    capital = (master or {}).get("capital_yen") or 0
    employees = (master or {}).get("employees") or 0
    capital_score = _logistic_normalise(float(capital) / 1_000_000, scale=50.0)
    employees_score = _logistic_normalise(float(employees), scale=30.0)
    size_score = round(0.5 * capital_score + 0.5 * employees_score, 4)
    components["size"] = size_score

    # Weighted: adoption 0.45 / bids 0.30 / size 0.25.
    total = 0.45 * adoption_score + 0.30 * bids_score + 0.25 * size_score
    return {
        "value": round(total, 4),
        "components": components,
        "weights": {"adoption": 0.45, "bids": 0.30, "size": 0.25},
        "interpretation": (
            "0 = no public adoption / procurement / size signal; "
            "1 = saturated public-corpus business footprint"
        ),
    }


def _score_compliance(
    master: dict[str, Any] | None,
    invoice: dict[str, Any],
    enforcement: dict[str, Any],
) -> dict[str, Any]:
    """compliance_score — higher = cleaner compliance signal.

    Inputs:
      * invoice.status == 'active'                          (positive)
      * enforcement.total == 0 AND no high severity         (positive)
      * master.active is True (not closed) AND complete     (positive)
    """
    components: dict[str, float] = {}

    invoice_status = invoice.get("status") or "not_found"
    if invoice_status == "active":
        invoice_score = 1.00
    elif invoice_status == "inactive":
        invoice_score = 0.70
    elif invoice_status == "expired":
        invoice_score = 0.40
    elif invoice_status == "revoked":
        invoice_score = 0.10
    else:  # not_found — neutral, not penalty (NTA bulk lag is common)
        invoice_score = 0.55
    components["invoice"] = round(invoice_score, 4)

    enforcement_total = int(enforcement.get("total") or 0)
    max_severity = enforcement.get("max_severity") or None
    if enforcement_total == 0:
        enforcement_score = 1.00
    elif max_severity == "high":
        enforcement_score = 0.10
    elif max_severity == "medium":
        enforcement_score = 0.40
    else:
        enforcement_score = 0.65
    components["enforcement"] = round(enforcement_score, 4)

    master_score = 0.0
    if master is not None:
        # Active flag carries half the weight; data completeness the rest.
        active = bool(master.get("active"))
        completeness = 0.0
        for key in (
            "name",
            "address",
            "prefecture",
            "established_date",
            "jsic_major",
        ):
            if master.get(key):
                completeness += 0.20
        master_score = round(0.5 * (1.0 if active else 0.0) + 0.5 * completeness, 4)
    components["master"] = master_score

    # Weighted: invoice 0.40 / enforcement 0.40 / master 0.20.
    total = 0.40 * components["invoice"] + 0.40 * components["enforcement"] + 0.20 * master_score
    return {
        "value": round(total, 4),
        "components": components,
        "weights": {"invoice": 0.40, "enforcement": 0.40, "master": 0.20},
        "interpretation": (
            "0 = active compliance issues; 1 = clean public-corpus compliance posture"
        ),
    }


def _build_scores(
    *,
    master: dict[str, Any] | None,
    adoption: dict[str, Any],
    enforcement: dict[str, Any],
    bids: dict[str, Any],
    invoice: dict[str, Any],
    news: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compose the 3-axis scoring block."""
    return {
        "risk_score": _score_risk(enforcement, invoice, news),
        "credit_score": _score_credit(master, adoption, bids),
        "compliance_score": _score_compliance(master, invoice, enforcement),
    }


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def _build_houjin_360(
    *,
    jpintel_conn: sqlite3.Connection,
    am_conn: sqlite3.Connection | None,
    bangou: str,
    limit: int,
) -> dict[str, Any]:
    """Compose the unified envelope. Soft-fails per substrate."""
    body: dict[str, Any] = {
        "houjin_bangou": bangou,
        "limit_per_section": limit,
    }
    missing: list[str] = []

    if am_conn is None:
        body["data_quality"] = {
            "missing_substrate": ["autonomath.db"],
            "note": ("autonomath.db unavailable; only watch_alerts (jpintel-side) can be served."),
        }

    master_block: dict[str, Any] | None = None
    if am_conn is not None:
        master_block = _section_master(am_conn, bangou, missing)
    body["master"] = master_block

    if am_conn is not None:
        adoption_block = _section_adoption_records(am_conn, bangou, limit=limit, missing=missing)
    else:
        adoption_block = {"total": 0, "total_amount_yen": 0, "records": []}
    body["adoption_records"] = adoption_block

    if am_conn is not None:
        enforcement_block = _section_enforcement_cases(
            am_conn, bangou, limit=limit, missing=missing
        )
    else:
        enforcement_block = {
            "total": 0,
            "total_amount_yen": 0,
            "max_severity": None,
            "records": [],
        }
    body["enforcement_cases"] = enforcement_block

    bids_block = _section_bids_won(jpintel_conn, am_conn, bangou, limit=limit, missing=missing)
    body["bids_won"] = bids_block

    if am_conn is not None:
        invoice_block = _section_invoice_status(am_conn, bangou, missing)
    else:
        invoice_block = {
            "registered": False,
            "registration_no": None,
            "registered_date": None,
            "status": "not_found",
        }
    body["invoice_registrant_status"] = invoice_block

    if am_conn is not None:
        news_block = _section_recent_news(am_conn, bangou, limit=limit, missing=missing)
    else:
        news_block = []
    body["recent_news"] = news_block

    body["watch_alerts"] = _section_watch_alerts(
        jpintel_conn, am_conn, bangou, limit=limit, missing=missing
    )

    body["scores"] = _build_scores(
        master=master_block,
        adoption=adoption_block,
        enforcement=enforcement_block,
        bids=bids_block,
        invoice=invoice_block,
        news=news_block,
    )

    if missing:
        dq = body.setdefault("data_quality", {})
        dq["missing_tables"] = sorted(set(missing))

    # R8 BUGHUNT (2026-05-07): always-on substrate caveat so a 200 with a hot
    # houjin_bangou still discloses the upstream gaps (357 orphans, 805 unknown
    # license, 0% amount_granted_yen). Without this, an LLM consumer who never
    # hits a missing-table branch could mistake the response for a
    # fully-authoritative profile.
    dq = body.setdefault("data_quality", {})
    dq.setdefault(
        "substrate_caveat",
        (
            "houjin_master / jpi_adoption_records / jpi_invoice_registrants / "
            "am_enforcement_detail / bids / am_amendment_diff の併合結果。"
            "jpi_adoption_records には 357 orphan houjin_bangou (houjin_master "
            "未登録、gBiz delta 自己回復待ち) が残存。amount_granted_yen は "
            "0/201,845 行 populated。am_source 97,272 行のうち 805 行は "
            "license='unknown'。3 軸 score (risk / credit / compliance) は "
            "公開コーパスに対する descriptive signal であり、与信 / 税務 / "
            "法令適用 verdict ではない。"
        ),
    )
    dq.setdefault("orphan_houjin_in_adoption_records", 357)
    dq.setdefault("license_unknown_count", 805)
    dq.setdefault("amount_granted_yen_populated", 0)
    dq.setdefault("adoption_records_total", 201_845)

    body["_disclaimer"] = _DISCLAIMER
    body["_billing_unit"] = 1
    return body


# ---------------------------------------------------------------------------
# Empty-response detector — feeds the 404 branch.
# ---------------------------------------------------------------------------


def _is_empty_response(body: dict[str, Any]) -> bool:
    """True iff every substrate-backed section is empty AND no watch row."""
    if body.get("master"):
        return False
    if (body.get("adoption_records") or {}).get("total"):
        return False
    if (body.get("enforcement_cases") or {}).get("total"):
        return False
    if (body.get("bids_won") or {}).get("total"):
        return False
    inv = body.get("invoice_registrant_status") or {}
    if inv.get("registered") or inv.get("registration_no"):
        return False
    if body.get("recent_news"):
        return False
    watch = body.get("watch_alerts") or {}
    return not (watch.get("is_watched") or watch.get("last_amendment_at"))


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/{houjin_bangou}/360",
    summary=(
        "Unified houjin 360 — master + adoption + enforcement + bids_won + "
        "invoice + recent_news + watch_alerts + 3-axis scoring"
    ),
    description=(
        "One 法人番号 → all public-corpus surfaces in a single GET. Joins "
        "houjin_master + jpi_adoption_records + am_enforcement_detail + "
        "bids + jpi_invoice_registrants + am_amendment_diff + "
        "customer_watches and projects a deterministic 3-axis scoring "
        "block (risk_score / credit_score / compliance_score).\n\n"
        "**Pricing:** ¥3 / call (1 unit) regardless of `limit`.\n\n"
        "**Sections** (always returned): `master`, `adoption_records`, "
        "`enforcement_cases`, `bids_won`, `invoice_registrant_status`, "
        "`recent_news`, `watch_alerts`, `scores`.\n\n"
        "Pure SQL + Python projection. NO LLM call. Sensitive: §52 / §72 "
        "/ §1 fence on the disclaimer envelope. The 3-axis scores are "
        "*descriptive* signals over the public corpus — never a 与信 / "
        "税務 / 法令適用 verdict."
    ),
    responses={
        200: {"description": "Unified houjin 360 envelope."},
        404: {"description": "houjin_bangou not found in any joined substrate."},
        422: {"description": "Malformed houjin_bangou (must be 13 digits)."},
    },
)
def get_houjin_360(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    houjin_bangou: Annotated[
        str,
        PathParam(
            min_length=13,
            max_length=14,
            description="13-digit 法人番号 (NTA canonical), with or without 'T' prefix.",
        ),
    ],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=_HARD_LIMIT,
            description=(
                "Cap per list-shaped section (adoption_records, "
                "enforcement_cases, bids_won, recent_news, "
                f"watch_alerts.recent_alerts). Hard cap = {_HARD_LIMIT}."
            ),
        ),
    ] = _DEFAULT_LIMIT,
    compact: Annotated[
        bool,
        Query(
            description=(
                "Return the compact envelope projection. Also supported via X-JPCite-Compact: 1."
            ),
        ),
    ] = False,
) -> JSONResponse:
    _t0 = time.perf_counter()

    normalized = _normalize_bangou(houjin_bangou)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_bangou",
                "field": "houjin_bangou",
                "message": (
                    f"houjin_bangou must be 13 digits (with or without 'T' "
                    f"prefix); got {houjin_bangou!r}."
                ),
            },
        )

    capped_limit = max(1, min(int(limit or _DEFAULT_LIMIT), _HARD_LIMIT))

    am_conn = _open_autonomath_ro()
    try:
        body = _build_houjin_360(
            jpintel_conn=conn,
            am_conn=am_conn,
            bangou=normalized,
            limit=capped_limit,
        )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    if _is_empty_response(body):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "houjin_not_found",
                "houjin_bangou": normalized,
                "message": (
                    f"No data found for 法人番号={normalized} across "
                    "houjin_master / jpi_adoption_records / "
                    "am_enforcement_detail / bids / "
                    "jpi_invoice_registrants / am_amendment_diff / "
                    "customer_watches. Either the id is unknown or the "
                    "NTA bulk ingest has not yet caught up."
                ),
            },
        )

    with contextlib.suppress(sqlite3.Error):
        body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "houjin.360",
        latency_ms=latency_ms,
        result_count=8,
        params={
            "houjin_bangou_present": bool(normalized),
            "limit": capped_limit,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="houjin.360",
        request_params={"houjin_bangou": normalized, "limit": capped_limit},
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if compact or wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


__all__ = ["router", "_build_houjin_360", "_normalize_bangou"]
