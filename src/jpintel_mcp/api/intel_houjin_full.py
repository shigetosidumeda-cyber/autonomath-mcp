"""GET /v1/intel/houjin/{houjin_id}/full — composite houjin 360-degree bundle.

Wave 30-3 composite. Customer LLMs that need a full corporate dossier on
one 法人番号 currently fan out across 5+ endpoints (`/v1/houjin/{bangou}`,
`/v1/intel/probability_radar`, `/v1/am/check_enforcement`, invoice lookup,
peer density, watch status). This composite endpoint merges every read
into one GET so the customer LLM consumes 80%+ fewer round-trips.

Substrates joined
-----------------
* ``houjin_master``                     — meta (name, prefecture, JSIC, capital)
* ``am_adopted_company_features``       — adoption history rollup
* ``am_enforcement_detail``             — 行政処分 records
* ``invoice_registrants`` (jpi mirror)  — invoice registration status
* ``am_geo_industry_density``           — peer summary
* ``customer_watches``                  — watch status (mig 088)

NO LLM call. Pure SQLite + Python projection. ¥3 / call (`_billing_unit`).

Sensitive: §52 (税理士法) + §72 (弁護士法) + §1 (行政書士法) fence in
the disclaimer envelope (mirrors envelope_wrapper SENSITIVE_TOOLS pattern).

Compact envelope: opt-in via ``?compact=true`` or ``X-JPCite-Compact: 1``
header for 30-50% byte reduction (compact_envelope projection).
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
from jpintel_mcp.api._response_models import IntelHoujinFullResponse
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.api.intel_houjin_full")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BANGOU_RE = re.compile(r"^\d{13}$")

# Default sections returned when the caller omits ``include_sections``.
_ALL_SECTIONS: tuple[str, ...] = (
    "meta",
    "adoption_history",
    "enforcement",
    "invoice_status",
    "peer_summary",
    "jurisdiction",
    "watch_status",
)

_DEFAULT_MAX_PER_SECTION = 10
_HARD_MAX_PER_SECTION = 50
_ENFORCEMENT_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3}
_TABLE_TO_DECISION_SECTION: dict[str, tuple[str, ...]] = {
    "autonomath.db": (
        "meta",
        "adoption_history",
        "enforcement",
        "invoice_status",
        "peer_summary",
        "jurisdiction",
    ),
    "houjin_master": ("meta", "jurisdiction"),
    "jpi_adoption_records": ("adoption_history", "jurisdiction"),
    "am_enforcement_detail": ("enforcement",),
    "invoice_registrants": ("invoice_status",),
    "jpi_invoice_registrants": ("invoice_status",),
    "am_adopted_company_features": ("peer_summary",),
    "customer_watches": ("watch_status",),
    "am_amendment_diff": ("watch_status",),
}

# Sensitive — §52 / §72 / §1 fence (mirrors envelope_wrapper.SENSITIVE_TOOLS).
_DISCLAIMER = (
    "本 houjin/full response は houjin_master + am_adopted_company_features "
    "+ am_enforcement_detail + invoice_registrants + am_geo_industry_density "
    "+ customer_watches を機械的に SQL 結合した **公開情報の名寄せ結果** で "
    "あり、税理士法 §52 (税務代理) ・弁護士法 §72 (法律事務) ・行政書士法 §1の2 "
    "(申請代理) のいずれにも該当しません。検索結果のみ提供、与信・税務・"
    "法令適用の業務判断は primary source 確認必須、確定判断は資格を有する"
    "税理士・弁護士・行政書士・公認会計士へ。"
)


# ---------------------------------------------------------------------------
# DB connection helpers
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    """Resolve the autonomath.db path. Mirrors api/houjin.py::_autonomath_db_path."""
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


def _normalize_houjin(raw: str) -> str | None:
    """Strip 'T' prefix, NFKC fullwidth-digits, hyphens, spaces. Return 13
    digits or None on malformed input.
    """
    s = unicodedata.normalize("NFKC", str(raw or ""))
    s = s.strip().lstrip("Tt")
    for ch in "- ,　":
        s = s.replace(ch, "")
    if not s.isdigit() or len(s) != 13:
        return None
    return s


def _parse_include_sections(raw: list[str] | None) -> list[str]:
    """Normalise the ``include_sections`` query into a canonical list.

    Empty / None → all sections. Unknown tokens are silently dropped (the
    customer LLM gets the recognised subset rather than a 422).
    """
    if not raw:
        return list(_ALL_SECTIONS)
    requested: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        for token in item.split(","):
            t = token.strip().lower()
            if t and t in _ALL_SECTIONS and t not in requested:
                requested.append(t)
    return requested or list(_ALL_SECTIONS)


# ---------------------------------------------------------------------------
# Section composers — each returns the section payload OR None when the
# substrate is missing. Soft-fail on every branch.
# ---------------------------------------------------------------------------


def _section_meta(
    am_conn: sqlite3.Connection, houjin_id: str, missing: list[str]
) -> dict[str, Any] | None:
    """houjin_meta — name, capital, employees, founded, JSIC, address."""
    if not _table_exists(am_conn, "houjin_master"):
        missing.append("houjin_master")
        return None
    try:
        row = am_conn.execute(
            "SELECT houjin_bangou, normalized_name, address_normalized, "
            "       prefecture, municipality, corporation_type, "
            "       established_date, jsic_major, jsic_middle, jsic_minor, "
            "       total_adoptions, total_received_yen "
            "  FROM houjin_master "
            " WHERE houjin_bangou = ? LIMIT 1",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("houjin_master query failed: %s", exc)
        return None
    if row is None:
        return None

    # capital + employees live as EAV facts on am_entity_facts (corp.* schema).
    capital_yen: int | None = None
    employees: int | None = None
    if _table_exists(am_conn, "am_entity_facts"):
        try:
            for fact in am_conn.execute(
                "SELECT field_name, field_value_text, field_value_numeric "
                "  FROM am_entity_facts "
                " WHERE entity_id = ? "
                "   AND field_name IN ('corp.capital_amount', 'corp.employee_count') "
                " LIMIT 16",
                (f"houjin:{houjin_id}",),
            ).fetchall():
                fname = fact["field_name"]
                num = fact["field_value_numeric"]
                txt = fact["field_value_text"]
                value: Any = num if num is not None else txt
                if fname == "corp.capital_amount" and value is not None:
                    try:
                        capital_yen = int(float(value))
                    except (TypeError, ValueError):
                        capital_yen = None
                elif fname == "corp.employee_count" and value is not None:
                    try:
                        employees = int(float(value))
                    except (TypeError, ValueError):
                        employees = None
        except sqlite3.Error as exc:
            logger.warning("am_entity_facts query failed: %s", exc)

    address = row["address_normalized"]
    if not address:
        # Fall back to (prefecture + municipality) when normalized address is null.
        parts = [row["prefecture"], row["municipality"]]
        address = "".join(p for p in parts if p) or None

    jsic_codes = [c for c in (row["jsic_major"], row["jsic_middle"], row["jsic_minor"]) if c]
    jsic_value = "/".join(jsic_codes) if jsic_codes else None

    return {
        "houjin_bangou": row["houjin_bangou"],
        "name": row["normalized_name"],
        "capital": capital_yen,
        "employees": employees,
        "founded": row["established_date"],
        "jsic": jsic_value,
        "address": address,
        "corporation_type": row["corporation_type"],
        "total_adoptions": int(row["total_adoptions"] or 0),
        "total_received_yen": int(row["total_received_yen"] or 0),
    }


def _section_adoption_history(
    am_conn: sqlite3.Connection,
    houjin_id: str,
    *,
    max_n: int,
    missing: list[str],
) -> list[dict[str, Any]]:
    """adoption_history — top-N by amount from jpi_adoption_records."""
    if not _table_exists(am_conn, "jpi_adoption_records"):
        missing.append("jpi_adoption_records")
        return []
    try:
        rows = am_conn.execute(
            "SELECT program_id, program_name_raw, "
            "       amount_granted_yen, announced_at "
            "  FROM jpi_adoption_records "
            " WHERE houjin_bangou = ? "
            " ORDER BY COALESCE(amount_granted_yen, 0) DESC, "
            "          COALESCE(announced_at, '') DESC "
            " LIMIT ?",
            (houjin_id, int(max_n)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("jpi_adoption_records query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        announced = r["announced_at"] or ""
        year = announced[:4] if announced and len(announced) >= 4 else None
        out.append(
            {
                "program_id": r["program_id"],
                "name": r["program_name_raw"],
                "amount": (
                    int(r["amount_granted_yen"]) if r["amount_granted_yen"] is not None else None
                ),
                "year": year,
            }
        )
    return out


def _section_enforcement(
    am_conn: sqlite3.Connection,
    houjin_id: str,
    *,
    max_n: int,
    missing: list[str],
) -> list[dict[str, Any]]:
    """enforcement_records — am_enforcement_detail filter by houjin_bangou."""
    if not _table_exists(am_conn, "am_enforcement_detail"):
        missing.append("am_enforcement_detail")
        return []
    try:
        rows = am_conn.execute(
            "SELECT issuance_date, enforcement_kind, target_name, "
            "       reason_summary, amount_yen, issuing_authority, "
            "       related_law_ref, source_url "
            "  FROM am_enforcement_detail "
            " WHERE houjin_bangou = ? "
            " ORDER BY issuance_date DESC "
            " LIMIT ?",
            (houjin_id, int(max_n)),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("am_enforcement_detail query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        kind = r["enforcement_kind"] or ""
        # Severity heuristic — license_revoke / fine / grant_refund are the
        # high-severity surfaces; investigation / business_improvement are
        # warnings. Pure deterministic mapping, no LLM.
        if kind in ("license_revoke", "fine", "grant_refund"):
            severity = "high"
        elif kind in ("subsidy_exclude", "contract_suspend"):
            severity = "medium"
        else:
            severity = "low"
        out.append(
            {
                "date": r["issuance_date"],
                "action": kind or None,
                "target_program": r["related_law_ref"] or r["target_name"],
                "severity": severity,
                "amount_yen": (int(r["amount_yen"]) if r["amount_yen"] is not None else None),
                "issuing_authority": r["issuing_authority"],
                "reason_summary": r["reason_summary"],
                "source_url": r["source_url"],
            }
        )
    return out


def _section_invoice_status(
    am_conn: sqlite3.Connection, houjin_id: str, missing: list[str]
) -> dict[str, Any]:
    """invoice_status — invoice_registrants (or jpi mirror) lookup."""
    table = None
    for candidate in ("jpi_invoice_registrants", "invoice_registrants"):
        if _table_exists(am_conn, candidate):
            table = candidate
            break
    if table is None:
        missing.append("invoice_registrants")
        return {"registered": False, "registration_no": None, "registered_date": None}
    try:
        row = am_conn.execute(
            f"SELECT invoice_registration_number, registered_date, revoked_date, "
            f"       expired_date, prefecture "
            f"  FROM {table} "
            f" WHERE houjin_bangou = ? LIMIT 1",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("%s query failed: %s", table, exc)
        return {"registered": False, "registration_no": None, "registered_date": None}
    if row is None:
        return {"registered": False, "registration_no": None, "registered_date": None}
    is_active = not (row["revoked_date"] or row["expired_date"])
    return {
        "registered": bool(is_active),
        "registration_no": row["invoice_registration_number"],
        "registered_date": row["registered_date"],
        "revoked_date": row["revoked_date"],
        "expired_date": row["expired_date"],
        "invoice_pref": row["prefecture"],
    }


def _section_peer_summary(
    am_conn: sqlite3.Connection,
    houjin_id: str,
    missing: list[str],
) -> dict[str, Any]:
    """peer_summary — same prefecture × jsic_major slice from
    am_geo_industry_density + am_adopted_company_features.
    """
    if not _table_exists(am_conn, "am_adopted_company_features"):
        missing.append("am_adopted_company_features")
        return {
            "peer_count": 0,
            "peer_avg_adoption_count": None,
            "query_percentile": None,
        }

    # Resolve the houjin's dominant prefecture + JSIC for the peer cohort key.
    try:
        own = am_conn.execute(
            "SELECT adoption_count, dominant_jsic_major, dominant_prefecture "
            "  FROM am_adopted_company_features "
            " WHERE houjin_bangou = ? LIMIT 1",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("am_adopted_company_features (own) failed: %s", exc)
        return {
            "peer_count": 0,
            "peer_avg_adoption_count": None,
            "query_percentile": None,
        }

    own_count = int(own["adoption_count"]) if own and own["adoption_count"] else 0
    own_jsic = own["dominant_jsic_major"] if own else None
    own_pref = own["dominant_prefecture"] if own else None

    if not own_jsic and not own_pref:
        return {
            "peer_count": 0,
            "peer_avg_adoption_count": None,
            "query_percentile": None,
            "cohort_jsic": None,
            "cohort_prefecture": None,
        }

    # Peer cohort: same dominant_prefecture + same dominant_jsic_major,
    # excluding the queried houjin itself.
    try:
        agg = am_conn.execute(
            "SELECT COUNT(*) AS n, "
            "       AVG(adoption_count) AS avg_n, "
            "       SUM(CASE WHEN adoption_count <= ? THEN 1 ELSE 0 END) AS rank_n "
            "  FROM am_adopted_company_features "
            " WHERE houjin_bangou != ? "
            "   AND dominant_jsic_major = ? "
            "   AND dominant_prefecture = ?",
            (own_count, houjin_id, own_jsic, own_pref),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("peer cohort aggregate failed: %s", exc)
        return {
            "peer_count": 0,
            "peer_avg_adoption_count": None,
            "query_percentile": None,
        }

    peer_count = int(agg["n"]) if agg and agg["n"] is not None else 0
    avg_n = round(float(agg["avg_n"]), 2) if agg and agg["avg_n"] is not None else None
    percentile: float | None = None
    if peer_count > 0 and agg and agg["rank_n"] is not None:
        percentile = round(float(agg["rank_n"]) / float(peer_count), 4)

    return {
        "peer_count": peer_count,
        "peer_avg_adoption_count": avg_n,
        "query_percentile": percentile,
        "cohort_jsic": own_jsic,
        "cohort_prefecture": own_pref,
        "own_adoption_count": own_count,
    }


def _section_jurisdiction(
    am_conn: sqlite3.Connection,
    houjin_id: str,
    *,
    invoice_block: dict[str, Any] | None,
    meta_block: dict[str, Any] | None,
    max_n: int,
    missing: list[str],
) -> dict[str, Any]:
    """jurisdiction_breakdown — registered (法務局), invoice (NTA),
    operational (採択 prefectures) breakdown.
    """
    registered_pref: str | None = (meta_block or {}).get("prefecture") if meta_block else None
    if registered_pref is None and meta_block:
        # Pull from address as a last resort (prefecture key absent).
        addr = meta_block.get("address") or ""
        # First 4 chars usually contain the prefecture for the long form
        # (e.g. "東京都千代田区..."). Best-effort, never raises.
        if "都" in addr or "府" in addr or "県" in addr or "道" in addr:
            for marker in ("都", "府", "県", "道"):
                idx = addr.find(marker)
                if 0 < idx < 6:
                    registered_pref = addr[: idx + 1]
                    break

    invoice_pref: str | None = (invoice_block or {}).get("invoice_pref")

    operational_prefs: list[str] = []
    if _table_exists(am_conn, "jpi_adoption_records"):
        try:
            rows = am_conn.execute(
                "SELECT DISTINCT prefecture "
                "  FROM jpi_adoption_records "
                " WHERE houjin_bangou = ? "
                "   AND prefecture IS NOT NULL "
                " ORDER BY prefecture "
                " LIMIT ?",
                (houjin_id, int(max_n)),
            ).fetchall()
            operational_prefs = [r["prefecture"] for r in rows if r["prefecture"]]
        except sqlite3.Error as exc:
            logger.warning("operational_prefs query failed: %s", exc)

    return {
        "registered_pref": registered_pref,
        "invoice_pref": invoice_pref,
        "operational_prefs": operational_prefs,
        "consistent": _is_jurisdiction_consistent(registered_pref, invoice_pref, operational_prefs),
    }


def _is_jurisdiction_consistent(
    registered: str | None,
    invoice: str | None,
    operational: list[str],
) -> bool:
    """True iff registered/invoice/operational all agree (or are empty).

    A True here is "no discrepancy detected in the public corpus" — never
    a positive 与信 signal on its own. A False is an audit-worthy flag.
    """
    seen = {p for p in (registered, invoice) if p}
    seen.update(p for p in operational if p)
    return len(seen) <= 1


def _invoice_decision_status(invoice: dict[str, Any]) -> str:
    """Return a stable invoice status label for decision support."""
    if invoice.get("revoked_date"):
        return "revoked"
    if invoice.get("expired_date"):
        return "expired"
    if invoice.get("registered") is True:
        return "active"
    if invoice.get("registration_no"):
        return "inactive"
    return "not_found_in_returned_section"


def _max_enforcement_severity(records: list[dict[str, Any]]) -> str | None:
    """Highest deterministic severity label from enforcement records."""
    max_label: str | None = None
    max_rank = 0
    for record in records:
        severity = record.get("severity")
        rank = _ENFORCEMENT_SEVERITY_RANK.get(str(severity), 0)
        if rank > max_rank:
            max_rank = rank
            max_label = str(severity)
    return max_label


def _append_decision_action(actions: list[dict[str, Any]], action: dict[str, Any]) -> None:
    """Append one action per stable action id."""
    action_id = action.get("action")
    if not action_id:
        return
    if any(existing.get("action") == action_id for existing in actions):
        return
    actions.append(action)


def _build_decision_support(body: dict[str, Any], sections: list[str]) -> dict[str, Any]:
    """Build deterministic decision support from already-returned sections only."""
    risk_summary: dict[str, Any] = {
        "sections_evaluated": list(sections),
        "flags": [],
    }
    decision_insights: list[dict[str, Any]] = []
    next_actions: list[dict[str, Any]] = []
    known_gaps: list[dict[str, Any]] = []
    flags: list[str] = risk_summary["flags"]

    if "enforcement" in sections and "enforcement_records" in body:
        records = [r for r in body.get("enforcement_records", []) if isinstance(r, dict)]
        record_count = len(records)
        max_severity = _max_enforcement_severity(records)
        enforcement_status = "detected" if record_count else "not_detected_in_returned_section"
        risk_summary["enforcement"] = {
            "status": enforcement_status,
            "record_count": record_count,
            "max_severity": max_severity,
        }
        if record_count:
            flags.append("enforcement_records_present")
            decision_insights.append(
                {
                    "insight_id": "enforcement_detected",
                    "section": "enforcement",
                    "message": (
                        "Returned enforcement_records contain public enforcement "
                        "signals; verify source URLs before relying on them."
                    ),
                    "source_fields": [
                        "enforcement_records[].date",
                        "enforcement_records[].action",
                        "enforcement_records[].severity",
                        "enforcement_records[].source_url",
                    ],
                }
            )
            _append_decision_action(
                next_actions,
                {
                    "action": "verify_enforcement_source",
                    "priority": "high" if max_severity == "high" else "medium",
                    "reason": "Enforcement records were returned in this response.",
                    "source_fields": [
                        "enforcement_records[].source_url",
                        "enforcement_records[].issuing_authority",
                    ],
                },
            )
        else:
            decision_insights.append(
                {
                    "insight_id": "enforcement_not_detected",
                    "section": "enforcement",
                    "message": (
                        "No enforcement_records were returned; absence in this "
                        "response is not proof of safety."
                    ),
                    "source_fields": ["enforcement_records"],
                }
            )

    if "invoice_status" in sections and "invoice_status" in body:
        invoice = body.get("invoice_status") or {}
        if not isinstance(invoice, dict):
            invoice = {}
        invoice_status = _invoice_decision_status(invoice)
        registration_no = invoice.get("registration_no")
        risk_summary["invoice_status"] = {
            "status": invoice_status,
            "registered": invoice.get("registered"),
            "registration_no_present": bool(registration_no),
        }
        if invoice_status != "active":
            flags.append(f"invoice_{invoice_status}")
        decision_insights.append(
            {
                "insight_id": f"invoice_{invoice_status}",
                "section": "invoice_status",
                "message": (
                    "Invoice status was projected from the returned invoice_status "
                    "section; confirm the current NTA publication before tax use."
                ),
                "source_fields": [
                    "invoice_status.registered",
                    "invoice_status.registration_no",
                    "invoice_status.registered_date",
                    "invoice_status.revoked_date",
                    "invoice_status.expired_date",
                ],
            }
        )
        _append_decision_action(
            next_actions,
            {
                "action": "review_invoice_status",
                "priority": "low" if invoice_status == "active" else "medium",
                "reason": "Invoice registration can change after corpus ingestion.",
                "source_fields": [
                    "invoice_status.registration_no",
                    "invoice_status.revoked_date",
                    "invoice_status.expired_date",
                ],
            },
        )

    if "jurisdiction" in sections and "jurisdiction_breakdown" in body:
        jurisdiction = body.get("jurisdiction_breakdown") or {}
        if not isinstance(jurisdiction, dict):
            jurisdiction = {}
        has_jurisdiction_data = bool(
            jurisdiction.get("registered_pref")
            or jurisdiction.get("invoice_pref")
            or jurisdiction.get("operational_prefs")
        )
        consistent = jurisdiction.get("consistent") if has_jurisdiction_data else None
        jurisdiction_status = (
            "mismatch"
            if consistent is False
            else "consistent"
            if consistent is True
            else "insufficient_data"
        )
        risk_summary["jurisdiction"] = {
            "status": jurisdiction_status,
            "consistent": consistent,
            "registered_pref": jurisdiction.get("registered_pref"),
            "invoice_pref": jurisdiction.get("invoice_pref"),
            "operational_pref_count": len(jurisdiction.get("operational_prefs") or []),
        }
        if consistent is False:
            flags.append("jurisdiction_mismatch")
            decision_insights.append(
                {
                    "insight_id": "jurisdiction_mismatch",
                    "section": "jurisdiction",
                    "message": (
                        "Registered, invoice, and operational prefectures do not "
                        "all align in the returned jurisdiction_breakdown."
                    ),
                    "source_fields": [
                        "jurisdiction_breakdown.registered_pref",
                        "jurisdiction_breakdown.invoice_pref",
                        "jurisdiction_breakdown.operational_prefs",
                        "jurisdiction_breakdown.consistent",
                    ],
                }
            )
            _append_decision_action(
                next_actions,
                {
                    "action": "review_jurisdiction",
                    "priority": "medium",
                    "reason": "Jurisdiction fields do not align in this response.",
                    "source_fields": [
                        "jurisdiction_breakdown.registered_pref",
                        "jurisdiction_breakdown.invoice_pref",
                        "jurisdiction_breakdown.operational_prefs",
                    ],
                },
            )
        else:
            decision_insights.append(
                {
                    "insight_id": f"jurisdiction_{jurisdiction_status}",
                    "section": "jurisdiction",
                    "message": (
                        "No jurisdiction mismatch was detected in returned fields; "
                        "this is not proof of complete jurisdiction coverage."
                    ),
                    "source_fields": [
                        "jurisdiction_breakdown.registered_pref",
                        "jurisdiction_breakdown.invoice_pref",
                        "jurisdiction_breakdown.operational_prefs",
                        "jurisdiction_breakdown.consistent",
                    ],
                }
            )

    if "watch_status" in sections and "watch_status" in body:
        watch = body.get("watch_status") or {}
        if not isinstance(watch, dict):
            watch = {}
        watch_state = "watched" if watch.get("is_watched") else "not_watched"
        risk_summary["watch_status"] = {
            "status": watch_state,
            "is_watched": bool(watch.get("is_watched")),
            "watch_subscribers": int(watch.get("watch_subscribers") or 0),
            "last_amendment": watch.get("last_amendment"),
        }
        if watch.get("is_watched"):
            flags.append("watch_active")
        decision_insights.append(
            {
                "insight_id": f"watch_{watch_state}",
                "section": "watch_status",
                "message": (
                    "Watch status was projected from customer_watches and amendment "
                    "diff data returned in watch_status."
                ),
                "source_fields": [
                    "watch_status.is_watched",
                    "watch_status.watch_subscribers",
                    "watch_status.last_amendment",
                ],
            }
        )
        _append_decision_action(
            next_actions,
            {
                "action": "monitor_changes",
                "priority": "low" if watch.get("is_watched") else "medium",
                "reason": "Corporate watch and amendment status should be monitored over time.",
                "source_fields": [
                    "watch_status.is_watched",
                    "watch_status.last_amendment",
                ],
            },
        )

    _dq_raw = body.get("data_quality")
    data_quality: dict[Any, Any] = _dq_raw if isinstance(_dq_raw, dict) else {}
    missing_substrate = data_quality.get("missing_substrate") or []
    if isinstance(missing_substrate, list):
        for substrate in sorted(s for s in missing_substrate if isinstance(s, str)):
            known_gaps.append(
                {
                    "gap_id": "missing_substrate",
                    "section": None,
                    "message": (
                        f"{substrate} was unavailable; missing signals are not proof of safety."
                    ),
                    "source_fields": ["data_quality.missing_substrate"],
                }
            )

    missing_tables = data_quality.get("missing_tables") or []
    if isinstance(missing_tables, list):
        for table in sorted(t for t in missing_tables if isinstance(t, str)):
            table_sections = _TABLE_TO_DECISION_SECTION.get(table, ())
            relevant_sections = [s for s in table_sections if s in sections]
            if not relevant_sections:
                continue
            known_gaps.append(
                {
                    "gap_id": "missing_table",
                    "section": relevant_sections[0],
                    "table": table,
                    "message": (
                        f"{table} was unavailable for requested sections; absence "
                        "of returned records is not proof of safety."
                    ),
                    "source_fields": ["data_quality.missing_tables"],
                }
            )

    _append_empty_section_gaps(body, sections, known_gaps)

    return {
        "risk_summary": risk_summary,
        "decision_insights": decision_insights,
        "next_actions": next_actions,
        "known_gaps": known_gaps,
    }


def _append_empty_section_gaps(
    body: dict[str, Any],
    sections: list[str],
    known_gaps: list[dict[str, Any]],
) -> None:
    """Record empty requested sections without treating absence as safety."""
    empty_checks: list[tuple[str, str, bool, str]] = [
        ("meta", "houjin_meta", not body.get("houjin_meta"), "houjin_meta"),
        (
            "adoption_history",
            "adoption_history",
            body.get("adoption_history") == [],
            "adoption_history",
        ),
        (
            "enforcement",
            "enforcement_records",
            body.get("enforcement_records") == [],
            "enforcement_records",
        ),
        (
            "invoice_status",
            "invoice_status",
            isinstance(body.get("invoice_status"), dict)
            and not body["invoice_status"].get("registration_no"),
            "invoice_status.registration_no",
        ),
        (
            "peer_summary",
            "peer_summary",
            isinstance(body.get("peer_summary"), dict)
            and not body["peer_summary"].get("peer_count"),
            "peer_summary.peer_count",
        ),
        (
            "jurisdiction",
            "jurisdiction_breakdown",
            isinstance(body.get("jurisdiction_breakdown"), dict)
            and not (
                body["jurisdiction_breakdown"].get("registered_pref")
                or body["jurisdiction_breakdown"].get("invoice_pref")
                or body["jurisdiction_breakdown"].get("operational_prefs")
            ),
            "jurisdiction_breakdown",
        ),
        (
            "watch_status",
            "watch_status",
            isinstance(body.get("watch_status"), dict)
            and not body["watch_status"].get("is_watched")
            and not body["watch_status"].get("last_amendment"),
            "watch_status",
        ),
    ]
    for section, field, is_empty, source_field in empty_checks:
        if section not in sections or field not in body or not is_empty:
            continue
        known_gaps.append(
            {
                "gap_id": "empty_section",
                "section": section,
                "message": (
                    f"{field} is empty in this response; non-detection is not proof of safety."
                ),
                "source_fields": [source_field],
            }
        )


def _section_watch_status(
    jpintel_conn: sqlite3.Connection,
    am_conn: sqlite3.Connection | None,
    houjin_id: str,
    missing: list[str],
) -> dict[str, Any]:
    """watch_status — customer_watches (mig 088) + last amendment date."""
    is_watched = False
    subscribers = 0
    if _table_exists(jpintel_conn, "customer_watches"):
        try:
            row = jpintel_conn.execute(
                "SELECT COUNT(*) AS n "
                "  FROM customer_watches "
                " WHERE watch_kind = 'houjin' "
                "   AND target_id = ? "
                "   AND status = 'active'",
                (houjin_id,),
            ).fetchone()
            subscribers = int(row["n"]) if row and row["n"] is not None else 0
            is_watched = subscribers > 0
        except sqlite3.Error as exc:
            logger.warning("customer_watches query failed: %s", exc)
    else:
        missing.append("customer_watches")

    last_amendment: str | None = None
    if am_conn is not None and _table_exists(am_conn, "am_amendment_diff"):
        try:
            row = am_conn.execute(
                "SELECT MAX(detected_at) AS dt   FROM am_amendment_diff  WHERE entity_id = ?",
                (f"houjin:{houjin_id}",),
            ).fetchone()
            last_amendment = row["dt"] if row else None
        except sqlite3.Error as exc:
            logger.warning("am_amendment_diff query failed: %s", exc)
    elif am_conn is None:
        missing.append("am_amendment_diff")

    return {
        "is_watched": bool(is_watched),
        "watch_subscribers": subscribers,
        "last_amendment": last_amendment,
    }


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def _build_houjin_full(
    *,
    jpintel_conn: sqlite3.Connection,
    am_conn: sqlite3.Connection | None,
    houjin_id: str,
    sections: list[str],
    max_per_section: int,
) -> dict[str, Any]:
    """Compose the full envelope. Soft-fails per section."""
    body: dict[str, Any] = {
        "houjin_bangou": houjin_id,
        "sections_returned": sections,
        "max_per_section": max_per_section,
    }
    missing: list[str] = []

    if am_conn is None:
        body["data_quality"] = {
            "missing_substrate": ["autonomath.db"],
            "note": "autonomath.db unavailable; only watch_status section can be served.",
        }

    meta_block: dict[str, Any] | None = None
    if "meta" in sections and am_conn is not None:
        meta_block = _section_meta(am_conn, houjin_id, missing)
        body["houjin_meta"] = meta_block

    if "adoption_history" in sections and am_conn is not None:
        body["adoption_history"] = _section_adoption_history(
            am_conn, houjin_id, max_n=max_per_section, missing=missing
        )

    if "enforcement" in sections and am_conn is not None:
        body["enforcement_records"] = _section_enforcement(
            am_conn, houjin_id, max_n=max_per_section, missing=missing
        )

    invoice_block: dict[str, Any] | None = None
    if "invoice_status" in sections and am_conn is not None:
        invoice_block = _section_invoice_status(am_conn, houjin_id, missing)
        body["invoice_status"] = invoice_block

    if "peer_summary" in sections and am_conn is not None:
        body["peer_summary"] = _section_peer_summary(am_conn, houjin_id, missing)

    if "jurisdiction" in sections and am_conn is not None:
        body["jurisdiction_breakdown"] = _section_jurisdiction(
            am_conn,
            houjin_id,
            invoice_block=invoice_block,
            meta_block=meta_block,
            max_n=max_per_section,
            missing=missing,
        )

    if "watch_status" in sections:
        body["watch_status"] = _section_watch_status(jpintel_conn, am_conn, houjin_id, missing)

    if missing:
        body.setdefault("data_quality", {})
        body["data_quality"]["missing_tables"] = sorted(set(missing))

    body["decision_support"] = _build_decision_support(body, sections)
    body["_disclaimer"] = _DISCLAIMER
    body["_billing_unit"] = 1
    return body


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/houjin/{houjin_id}/full",
    response_model=IntelHoujinFullResponse,
    summary="Composite houjin 360-degree bundle (meta + adoption + enforcement + invoice + peer + jurisdiction + watch)",
    description=(
        "Single-call corporate dossier on one 法人番号. Merges 5+ legacy "
        "fan-out reads (`/v1/houjin/{bangou}` + `/v1/intel/probability_radar` "
        "+ `/v1/am/check_enforcement` + invoice lookup + peer density + "
        "watch status) into one GET so the customer LLM consumes 80%+ "
        "fewer round-trips.\n\n"
        "**Pricing:** ¥3 / call (1 unit total) regardless of "
        "`max_per_section` or how many `include_sections` are requested.\n\n"
        "**Sections** (default = all): "
        "`meta`, `adoption_history`, `enforcement`, `invoice_status`, "
        "`peer_summary`, `jurisdiction`, `watch_status`. Pass a "
        "comma-separated `include_sections` to narrow.\n\n"
        "Pure SQL + Python projection. NO LLM call. Sensitive: §52 / §72 / "
        "§1 fence on the disclaimer envelope."
    ),
    responses={
        200: {"description": "Composite houjin bundle envelope."},
        404: {"description": "houjin_id not found in any joined substrate."},
        422: {"description": "Malformed houjin_bangou (must be 13 digits)."},
    },
)
def get_intel_houjin_full(
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
    houjin_id: Annotated[
        str,
        PathParam(
            min_length=13,
            max_length=14,
            description="13-digit 法人番号 (NTA canonical), with or without 'T' prefix.",
        ),
    ],
    include_sections: Annotated[
        list[str] | None,
        Query(
            description=(
                "Comma-separated section names to include. Default = all of "
                "`meta`, `adoption_history`, `enforcement`, `invoice_status`, "
                "`peer_summary`, `jurisdiction`, `watch_status`. Unknown tokens "
                "are dropped silently."
            ),
        ),
    ] = None,
    max_per_section: Annotated[
        int,
        Query(
            ge=1,
            le=_HARD_MAX_PER_SECTION,
            description=(
                "Cap per list-shaped section (adoption_history, enforcement_records, "
                f"operational_prefs). Hard cap = {_HARD_MAX_PER_SECTION}."
            ),
        ),
    ] = _DEFAULT_MAX_PER_SECTION,
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

    normalized = _normalize_houjin(houjin_id)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_bangou",
                "field": "houjin_id",
                "message": (
                    f"houjin_id must be 13 digits (with or without 'T' prefix); got {houjin_id!r}."
                ),
            },
        )

    sections = _parse_include_sections(include_sections)
    capped_max = max(
        1, min(int(max_per_section or _DEFAULT_MAX_PER_SECTION), _HARD_MAX_PER_SECTION)
    )

    am_conn = _open_autonomath_ro()
    try:
        body = _build_houjin_full(
            jpintel_conn=conn,
            am_conn=am_conn,
            houjin_id=normalized,
            sections=sections,
            max_per_section=capped_max,
        )
    finally:
        if am_conn is not None:
            with contextlib.suppress(sqlite3.Error):
                am_conn.close()

    # 404 only when EVERY substrate-backed section came back empty AND no
    # watch row exists. The watch_status section is jpintel-backed and
    # remains useful even if autonomath.db is offline, so we compute the
    # 404 from the substrate signals only.
    if _is_empty_response(body, sections):
        raise HTTPException(
            status_code=404,
            detail={
                "error": "houjin_not_found",
                "houjin_id": normalized,
                "message": (
                    f"No data found for 法人番号={normalized} across "
                    f"houjin_master / am_adopted_company_features / "
                    f"am_enforcement_detail / invoice_registrants / "
                    f"customer_watches. Either the id is unknown or the "
                    f"NTA bulk ingest has not yet caught up."
                ),
            },
        )

    # Auditor reproducibility (same pattern as intel.match / intel.path).
    # Soft-fail — the response still carries the section payload.
    with contextlib.suppress(sqlite3.Error):
        body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.houjin_full",
        latency_ms=latency_ms,
        result_count=len(sections),
        params={
            "houjin_bangou_present": bool(normalized),
            "section_count": len(sections),
            "max_per_section": capped_max,
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.houjin_full",
        request_params={
            "houjin_id": normalized,
            "include_sections": sections,
            "max_per_section": capped_max,
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if compact or wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


def _is_empty_response(body: dict[str, Any], sections: list[str]) -> bool:
    """True iff every requested substrate-backed section came back empty
    AND no watch row exists. Used to gate the 404 branch.
    """
    if "meta" in sections and body.get("houjin_meta"):
        return False
    if "adoption_history" in sections and body.get("adoption_history"):
        return False
    if "enforcement" in sections and body.get("enforcement_records"):
        return False
    if "invoice_status" in sections:
        inv = body.get("invoice_status") or {}
        if inv.get("registered") or inv.get("registration_no"):
            return False
    if "peer_summary" in sections:
        peer = body.get("peer_summary") or {}
        if peer.get("peer_count"):
            return False
    if "jurisdiction" in sections:
        jur = body.get("jurisdiction_breakdown") or {}
        if jur.get("registered_pref") or jur.get("invoice_pref") or jur.get("operational_prefs"):
            return False
    if "watch_status" in sections:
        watch = body.get("watch_status") or {}
        if watch.get("is_watched") or watch.get("last_amendment"):
            return False
    return True


__all__ = ["router"]
