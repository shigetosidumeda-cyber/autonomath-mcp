"""POST /v1/intel/risk_score — multi-axis houjin risk score (Wave 32-3).

Why this exists
---------------
Customer LLMs evaluating a 法人番号 for engagement / DD / 顧問先 onboarding
currently fan out across 5+ endpoints (`/v1/intel/houjin/{id}/full` +
`/v1/am/check_enforcement` + invoice lookup + adoption history + watch
status) and then re-derive a risk surface client-side. Each LLM ends up
with a different rubric and the risk score becomes incomparable across
sessions.

This endpoint composes the same 5 axes from the public corpus into a
single rules-based 0-100 score with full per-axis transparency:

  * enforcement_risk     — am_enforcement_detail rows × kind severity ×
                            decay-by-recency.
  * refund_risk          — grant_refund / subsidy_exclude rows + the
                            historical 受給 amount from jpi_adoption_records.
  * invoice_compliance_risk — invoice_registrants registered/revoked status.
  * adoption_revocation_risk — adoption rows the houjin holds where the
                                 underlying program has recent amendments.
  * jurisdiction_drift_risk — registered (法務局) vs invoice (NTA) vs
                               operational (採択) prefecture divergence.

Hard constraints (CLAUDE.md / `feedback_no_operator_llm_api`)
-------------------------------------------------------------
NO LLM call inside this endpoint. Pure SQLite + Python. Every axis
formula is rules-based and transparent — the customer can recompute the
same score from the per-axis evidence_count + last_action_date fields.

Sensitive surface (与信判断 territory)
--------------------------------------
A 0-100 risk score sits adjacent to 与信判断 / 信用調査 / 業法 territory.
The disclaimer is **strictly stronger** than the houjin/full fence:
explicit "this is NOT a credit rating" + 弁護士法 §72 + 税理士法 §52 +
行政書士法 §1 fence verbatim. The customer LLM is expected to render
this verbatim alongside the score.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from jpintel_mcp.api._audit_seal import attach_seal_to_body
from jpintel_mcp.api._compact_envelope import to_compact, wants_compact
from jpintel_mcp.api._corpus_snapshot import attach_corpus_snapshot
from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage

logger = logging.getLogger("jpintel.api.intel_risk_score")

router = APIRouter(prefix="/v1/intel", tags=["intel"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALL_AXES: tuple[str, ...] = (
    "enforcement",
    "refund",
    "invoice_compliance",
    "adoption_revocation",
    "jurisdiction_drift",
)

# Per-enforcement-kind base severity weight (axis ceiling = 100).
# Mirrors the houjin/full _section_enforcement severity heuristic so
# the two surfaces stay coherent.
_ENFORCEMENT_KIND_WEIGHTS: dict[str, float] = {
    "license_revoke": 40.0,
    "fine": 30.0,
    "grant_refund": 35.0,
    "subsidy_exclude": 25.0,
    "contract_suspend": 20.0,
    "business_improvement": 10.0,
    "investigation": 8.0,
    "other": 5.0,
}


# Refund-axis: per-row floor + amount-scaling. amount_yen ≥ 100M → +20pt,
# ≥ 10M → +10pt, ≥ 1M → +5pt, else +2pt.
def _refund_amount_points(amount_yen: int | None) -> float:
    if amount_yen is None or amount_yen <= 0:
        return 2.0
    if amount_yen >= 100_000_000:
        return 20.0
    if amount_yen >= 10_000_000:
        return 10.0
    if amount_yen >= 1_000_000:
        return 5.0
    return 2.0


# Risk label thresholds. Inclusive lower bounds.
_LABEL_BANDS: tuple[tuple[float, str], ...] = (
    (75.0, "critical"),
    (50.0, "high"),
    (25.0, "med"),
    (0.0, "low"),
)


def _label_for_score(score: float) -> str:
    for floor, label in _LABEL_BANDS:
        if score >= floor:
            return label
    return "low"


# Recency decay: full weight at 0 days, 50% at 365d, 25% at 730d, 10% at 1825d.
def _decay_factor(days_ago: int | None) -> float:
    if days_ago is None or days_ago < 0:
        return 0.5
    if days_ago <= 30:
        return 1.0
    if days_ago <= 365:
        return 0.75
    if days_ago <= 730:
        return 0.5
    if days_ago <= 1825:
        return 0.25
    return 0.10


def _days_between(iso_date: str | None, ref: _dt.date) -> int | None:
    if not iso_date:
        return None
    try:
        d = _dt.date.fromisoformat(iso_date[:10])
    except (TypeError, ValueError):
        return None
    return max(0, (ref - d).days)


# Disclaimer — strictly stronger than houjin/full. Explicit non-credit-rating
# fence + §52 / §72 / §1 verbatim. The "NOT a credit rating" phrase is
# load-bearing under 業法 territory.
_DISCLAIMER = (
    "本 risk_score response は am_enforcement_detail + jpi_adoption_records "
    "+ invoice_registrants + am_amendment_diff + houjin_master を機械的に "
    "SQL 集計した **公開情報の rules-based 0-100 指標** であり、"
    "**THIS IS NOT A CREDIT RATING / 信用格付けではありません**。 "
    "弁護士法 §72 (法律事務) ・税理士法 §52 (税務代理) ・行政書士法 §1 "
    "(申請代理) ・割賦販売法 ・貸金業法 ・銀行法 のいずれの 与信判断 にも "
    "該当しません。 業法上の与信判断・反社チェック・信用情報照会は資格を "
    "有する 弁護士・税理士・行政書士・信用調査機関へ。 投資判断・取引判断・"
    "雇用判断の唯一根拠としては使用しないでください。"
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    """Resolve the autonomath.db path. Mirrors api/intel_houjin_full.py."""
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    try:
        from jpintel_mcp.config import settings

        p = settings.autonomath_db_path
        if isinstance(p, Path):
            return p
        return Path(str(p))
    except (AttributeError, ImportError):
        return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_ro() -> sqlite3.Connection | None:
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
        return (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1",
                (name,),
            ).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _normalize_houjin(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().lstrip("Tt")
    s = re.sub(r"[\s\-,　]", "", s)
    if not s.isdigit() or len(s) != 13:
        return None
    return s


# ---------------------------------------------------------------------------
# Pydantic body
# ---------------------------------------------------------------------------


class RiskScoreRequest(BaseModel):
    """POST body for /v1/intel/risk_score."""

    houjin_id: str = Field(
        ...,
        min_length=13,
        max_length=14,
        description="13-digit 法人番号 (with or without 'T' prefix).",
    )
    include_axes: list[str] | None = Field(
        default=None,
        description=(
            "Axes to score. Default = all of "
            "['enforcement','refund','invoice_compliance',"
            "'adoption_revocation','jurisdiction_drift']. Unknown tokens "
            "are dropped silently."
        ),
    )
    weight_overrides: dict[str, float] | None = Field(
        default=None,
        description=(
            "Per-axis weight overrides in [0, 1]. Default = even weighting "
            "(1.0 / len(axes) per axis). Out-of-range values clamp to "
            "[0, 1]; unknown axes drop."
        ),
    )


# ---------------------------------------------------------------------------
# Houjin meta + cohort helpers
# ---------------------------------------------------------------------------


def _fetch_houjin_meta(am_conn: sqlite3.Connection, houjin_id: str) -> dict[str, Any] | None:
    if not _table_exists(am_conn, "houjin_master"):
        return None
    try:
        row = am_conn.execute(
            "SELECT houjin_bangou, normalized_name, prefecture, municipality, "
            "       address_normalized, jsic_major, total_received_yen "
            "  FROM houjin_master "
            " WHERE houjin_bangou = ? LIMIT 1",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("houjin_master fetch failed: %s", exc)
        return None
    if row is None:
        return None
    return dict(row)


def _size_bucket_for_houjin(am_conn: sqlite3.Connection, houjin_id: str) -> str:
    """Coarse size bucket from total_received_yen for peer cohort matching.

    Buckets: micro (< ¥10M) / small (¥10M-100M) / mid (¥100M-1B) / large (≥ ¥1B).
    Falls back to 'unknown' if the houjin row carries no roll-up.
    """
    if not _table_exists(am_conn, "houjin_master"):
        return "unknown"
    try:
        row = am_conn.execute(
            "SELECT total_received_yen FROM houjin_master WHERE houjin_bangou = ? LIMIT 1",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error:
        return "unknown"
    if row is None or row["total_received_yen"] is None:
        return "unknown"
    try:
        amount = int(row["total_received_yen"])
    except (TypeError, ValueError):
        return "unknown"
    if amount >= 1_000_000_000:
        return "large"
    if amount >= 100_000_000:
        return "mid"
    if amount >= 10_000_000:
        return "small"
    return "micro"


# ---------------------------------------------------------------------------
# Per-axis scorers
# ---------------------------------------------------------------------------


def _score_enforcement(
    am_conn: sqlite3.Connection, houjin_id: str, ref: _dt.date
) -> dict[str, Any]:
    """enforcement_risk — sum of (kind_weight × decay) capped at 100."""
    out: dict[str, Any] = {
        "score": 0.0,
        "evidence_count": 0,
        "last_action_date": None,
        "severity_history": [],
    }
    if not _table_exists(am_conn, "am_enforcement_detail"):
        return out
    try:
        rows = am_conn.execute(
            "SELECT issuance_date, enforcement_kind, amount_yen "
            "  FROM am_enforcement_detail "
            " WHERE houjin_bangou = ? "
            " ORDER BY issuance_date DESC "
            " LIMIT 50",
            (houjin_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("enforcement_detail query failed: %s", exc)
        return out
    if not rows:
        return out

    total = 0.0
    history: list[dict[str, Any]] = []
    for r in rows:
        kind = r["enforcement_kind"] or "other"
        base = _ENFORCEMENT_KIND_WEIGHTS.get(kind, 5.0)
        days = _days_between(r["issuance_date"], ref)
        decay = _decay_factor(days)
        contribution = base * decay
        total += contribution
        history.append(
            {
                "date": r["issuance_date"],
                "kind": kind,
                "weight": round(base, 2),
                "decay": round(decay, 2),
                "contribution": round(contribution, 2),
            }
        )

    out["evidence_count"] = len(rows)
    out["last_action_date"] = rows[0]["issuance_date"]
    out["severity_history"] = history[:10]  # cap rendered history
    out["score"] = round(min(100.0, total), 2)
    return out


def _score_refund(am_conn: sqlite3.Connection, houjin_id: str, ref: _dt.date) -> dict[str, Any]:
    """refund_risk — grant_refund / subsidy_exclude rows + amount scaling."""
    out: dict[str, Any] = {
        "score": 0.0,
        "historical_refund_count": 0,
        "refund_amount_yen": 0,
        "programs_at_risk": [],
    }
    if not _table_exists(am_conn, "am_enforcement_detail"):
        return out
    try:
        rows = am_conn.execute(
            "SELECT issuance_date, enforcement_kind, amount_yen, "
            "       related_law_ref, target_name "
            "  FROM am_enforcement_detail "
            " WHERE houjin_bangou = ? "
            "   AND enforcement_kind IN ('grant_refund','subsidy_exclude') "
            " ORDER BY issuance_date DESC "
            " LIMIT 50",
            (houjin_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("refund_risk query failed: %s", exc)
        return out
    if not rows:
        return out

    total = 0.0
    refund_amount_total = 0
    programs: list[str] = []
    for r in rows:
        days = _days_between(r["issuance_date"], ref)
        decay = _decay_factor(days)
        amount_yen = r["amount_yen"]
        try:
            amount_yen_int = int(amount_yen) if amount_yen is not None else None
        except (TypeError, ValueError):
            amount_yen_int = None
        if amount_yen_int is not None:
            refund_amount_total += amount_yen_int
        contribution = _refund_amount_points(amount_yen_int) * decay
        # grant_refund weighs heavier than subsidy_exclude.
        if r["enforcement_kind"] == "grant_refund":
            contribution *= 1.5
        total += contribution
        program_label = r["related_law_ref"] or r["target_name"]
        if program_label and program_label not in programs and len(programs) < 10:
            programs.append(program_label)

    # Add a flat coverage premium per row (5pt × decay) so the count alone
    # carries weight even when amount_yen is missing.
    coverage = sum(5.0 * _decay_factor(_days_between(r["issuance_date"], ref)) for r in rows)
    total += min(coverage, 30.0)

    out["historical_refund_count"] = len(rows)
    out["refund_amount_yen"] = refund_amount_total
    out["programs_at_risk"] = programs
    out["score"] = round(min(100.0, total), 2)
    return out


def _score_invoice_compliance(
    am_conn: sqlite3.Connection, houjin_id: str, ref: _dt.date
) -> dict[str, Any]:
    """invoice_compliance_risk — registration status + revoke/expire flags."""
    out: dict[str, Any] = {
        "score": 0.0,
        "registered": False,
        "invoice_no": None,
        "missed_deadlines_count": 0,
    }
    table = None
    for candidate in ("jpi_invoice_registrants", "invoice_registrants"):
        if _table_exists(am_conn, candidate):
            table = candidate
            break
    if table is None:
        # Substrate missing — neutral score (caller can't act on it).
        out["score"] = 25.0
        return out
    try:
        row = am_conn.execute(
            f"SELECT invoice_registration_number, registered_date, "
            f"       revoked_date, expired_date "
            f"  FROM {table} "
            f" WHERE houjin_bangou = ? LIMIT 1",
            (houjin_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("invoice_compliance query failed: %s", exc)
        return out

    # No row → unregistered. ¥3 invoice surface treats unregistered as
    # mid-risk (¥0 入力税額控除 for buyers post 2026-09 transition).
    if row is None:
        out["score"] = 50.0
        out["missed_deadlines_count"] = 1
        return out

    revoked = row["revoked_date"]
    expired = row["expired_date"]
    is_active = not (revoked or expired)
    out["registered"] = bool(is_active)
    out["invoice_no"] = row["invoice_registration_number"]

    if is_active:
        # Active registration → very low risk. Slight floor (5pt) so the
        # axis still contributes to a non-zero total.
        out["score"] = 5.0
        return out

    # Revoked or expired → high risk. Decay by recency of revocation so
    # an old revoke is less alarming than a fresh one (contractor may
    # have re-registered under a new id we don't see).
    drop_date = revoked or expired
    days = _days_between(drop_date, ref)
    decay = _decay_factor(days)
    out["score"] = round(min(100.0, 70.0 * decay + 20.0), 2)
    out["missed_deadlines_count"] = 1
    return out


def _score_adoption_revocation(
    am_conn: sqlite3.Connection, houjin_id: str, ref: _dt.date
) -> dict[str, Any]:
    """adoption_revocation_risk — adoption rows whose programs have recent
    amendments (eligibility shift could revoke historical adoption).
    """
    out: dict[str, Any] = {
        "score": 0.0,
        "revoked_count": 0,
        "recent_amendment_count_on_held_programs": 0,
    }
    if not _table_exists(am_conn, "jpi_adoption_records"):
        return out
    try:
        adopt_rows = am_conn.execute(
            "SELECT DISTINCT program_id "
            "  FROM jpi_adoption_records "
            " WHERE houjin_bangou = ? "
            "   AND program_id IS NOT NULL "
            " LIMIT 50",
            (houjin_id,),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("adoption fetch failed: %s", exc)
        return out
    program_ids = [r["program_id"] for r in adopt_rows if r["program_id"]]
    if not program_ids:
        return out

    # Recent amendments on held programs (last 365d).
    recent_count = 0
    if _table_exists(am_conn, "am_amendment_diff"):
        cutoff = (ref - _dt.timedelta(days=365)).isoformat()
        # Build a parameterized IN clause. Cap at 50 to bound query size.
        program_ids_capped = program_ids[:50]
        placeholders = ",".join("?" for _ in program_ids_capped)
        try:
            row = am_conn.execute(
                f"SELECT COUNT(*) AS n "
                f"  FROM am_amendment_diff "
                f" WHERE entity_id IN ({placeholders}) "
                f"   AND substr(detected_at, 1, 10) >= ?",
                (*program_ids_capped, cutoff),
            ).fetchone()
            recent_count = int(row["n"]) if row and row["n"] is not None else 0
        except sqlite3.Error as exc:
            logger.warning("amendment_diff count failed: %s", exc)

    # Any explicit grant_refund / subsidy_exclude already counted in refund_risk
    # but we mirror it here as the "revoked_count" — the customer LLM wants
    # the adoption-axis surface separately.
    revoked_count = 0
    if _table_exists(am_conn, "am_enforcement_detail"):
        try:
            r = am_conn.execute(
                "SELECT COUNT(*) AS n "
                "  FROM am_enforcement_detail "
                " WHERE houjin_bangou = ? "
                "   AND enforcement_kind IN ('grant_refund','subsidy_exclude')",
                (houjin_id,),
            ).fetchone()
            revoked_count = int(r["n"]) if r and r["n"] is not None else 0
        except sqlite3.Error as exc:
            logger.warning("revoked_count query failed: %s", exc)

    out["revoked_count"] = revoked_count
    out["recent_amendment_count_on_held_programs"] = recent_count
    # 20pt per revoked + 5pt per recent amendment, cap 100.
    score = revoked_count * 20.0 + recent_count * 5.0
    out["score"] = round(min(100.0, score), 2)
    return out


def _score_jurisdiction_drift(
    am_conn: sqlite3.Connection, houjin_id: str, _ref: _dt.date
) -> dict[str, Any]:
    """jurisdiction_drift_risk — registered vs invoice vs adoption pref divergence."""
    out: dict[str, Any] = {
        "score": 0.0,
        "registered_pref": None,
        "invoice_pref": None,
        "adoption_pref": [],
        "divergence_count": 0,
    }

    # Registered prefecture from houjin_master.
    registered_pref: str | None = None
    if _table_exists(am_conn, "houjin_master"):
        try:
            row = am_conn.execute(
                "SELECT prefecture FROM houjin_master WHERE houjin_bangou = ? LIMIT 1",
                (houjin_id,),
            ).fetchone()
            if row and row["prefecture"]:
                registered_pref = row["prefecture"]
        except sqlite3.Error as exc:
            logger.warning("registered_pref fetch failed: %s", exc)
    out["registered_pref"] = registered_pref

    # Invoice prefecture from the registrants table.
    invoice_pref: str | None = None
    inv_table = None
    for candidate in ("jpi_invoice_registrants", "invoice_registrants"):
        if _table_exists(am_conn, candidate):
            inv_table = candidate
            break
    if inv_table:
        try:
            row = am_conn.execute(
                f"SELECT prefecture FROM {inv_table} WHERE houjin_bangou = ? LIMIT 1",
                (houjin_id,),
            ).fetchone()
            if row and row["prefecture"]:
                invoice_pref = row["prefecture"]
        except sqlite3.Error as exc:
            logger.warning("invoice_pref fetch failed: %s", exc)
    out["invoice_pref"] = invoice_pref

    # Operational prefectures from adoption records.
    adoption_prefs: list[str] = []
    if _table_exists(am_conn, "jpi_adoption_records"):
        try:
            rows = am_conn.execute(
                "SELECT DISTINCT prefecture "
                "  FROM jpi_adoption_records "
                " WHERE houjin_bangou = ? "
                "   AND prefecture IS NOT NULL "
                " ORDER BY prefecture "
                " LIMIT 20",
                (houjin_id,),
            ).fetchall()
            adoption_prefs = [r["prefecture"] for r in rows if r["prefecture"]]
        except sqlite3.Error as exc:
            logger.warning("adoption_prefs fetch failed: %s", exc)
    out["adoption_pref"] = adoption_prefs

    # Divergence count: distinct non-null prefectures across the three axes.
    seen: set[str] = set()
    if registered_pref:
        seen.add(registered_pref)
    if invoice_pref:
        seen.add(invoice_pref)
    seen.update(adoption_prefs)
    divergence = max(0, len(seen) - 1)
    out["divergence_count"] = divergence

    # 0 divergence → 0pt. 1 → 15pt. 2 → 35pt. 3+ → 60pt.
    if divergence == 0:
        score = 0.0
    elif divergence == 1:
        score = 15.0
    elif divergence == 2:
        score = 35.0
    else:
        score = min(100.0, 35.0 + 25.0 * (divergence - 2))
    out["score"] = round(score, 2)
    return out


# ---------------------------------------------------------------------------
# Peer benchmarking
# ---------------------------------------------------------------------------


def _benchmark_against_peers(
    am_conn: sqlite3.Connection,
    *,
    houjin_id: str,
    own_total_score: float,
    jsic_major: str | None,
    size_bucket: str,
) -> dict[str, Any]:
    """Compute peer cohort (same JSIC major + same size bucket) average score
    and the query houjin's percentile within the cohort.

    The cohort score uses a coarse proxy: enforcement_count from
    am_adopted_company_features (already rolled up). Higher proxy = riskier.
    The percentile reports: P(peer < own_score), so a HIGHER percentile
    means the queried houjin is RISKIER than peers.
    """
    out: dict[str, Any] = {
        "peer_avg_score": None,
        "query_percentile": None,
        "peer_count": 0,
        "cohort_jsic": jsic_major,
        "cohort_size_bucket": size_bucket,
    }
    if not _table_exists(am_conn, "am_adopted_company_features"):
        return out
    if not jsic_major:
        return out

    # Bucket → total_received_yen window. Mirrors _size_bucket_for_houjin.
    bucket_filter_sql = ""
    bucket_params: tuple[Any, ...] = ()
    if size_bucket != "unknown":
        # Re-derive from total_received_yen via houjin_master JOIN. We avoid
        # a dependency on aacf carrying the same bucket.
        if size_bucket == "micro":
            bucket_filter_sql = " AND COALESCE(hm.total_received_yen, 0) < 10000000 "
        elif size_bucket == "small":
            bucket_filter_sql = (
                " AND COALESCE(hm.total_received_yen, 0) BETWEEN 10000000 AND 99999999 "
            )
        elif size_bucket == "mid":
            bucket_filter_sql = (
                " AND COALESCE(hm.total_received_yen, 0) BETWEEN 100000000 AND 999999999 "
            )
        elif size_bucket == "large":
            bucket_filter_sql = " AND COALESCE(hm.total_received_yen, 0) >= 1000000000 "

    # Use enforcement_count from the rollup as a 0-100 proxy (cap at 5
    # rows × 20pt each). Coarse but sufficient for percentile ordering.
    try:
        rows = am_conn.execute(
            "SELECT aacf.enforcement_count AS ec "
            "  FROM am_adopted_company_features AS aacf "
            "  JOIN houjin_master AS hm "
            "    ON hm.houjin_bangou = aacf.houjin_bangou "
            " WHERE aacf.houjin_bangou != ? "
            "   AND aacf.dominant_jsic_major = ? "
            f"  {bucket_filter_sql} "
            " LIMIT 5000",
            (houjin_id, jsic_major, *bucket_params),
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("peer benchmark query failed: %s", exc)
        return out

    if not rows:
        return out

    proxy_scores = [min(100.0, int(r["ec"] or 0) * 20.0) for r in rows]
    avg = sum(proxy_scores) / len(proxy_scores)
    riskier = sum(1 for s in proxy_scores if s < own_total_score)
    out["peer_count"] = len(proxy_scores)
    out["peer_avg_score"] = round(avg, 2)
    out["query_percentile"] = round(riskier / len(proxy_scores), 4)
    return out


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


def _build_recommendations(axes_payload: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-axis rules-based recommendations, urgency keyed off score band."""
    recs: list[dict[str, Any]] = []

    enf = axes_payload.get("enforcement_risk") or {}
    if enf.get("score", 0) >= 25.0:
        recs.append(
            {
                "axis": "enforcement",
                "action": (
                    "行政処分履歴を一次資料 (issuing_authority サイト) で確認し、"
                    "対象事業/期間/再発状況を弁護士に相談する。"
                ),
                "urgency": "high" if enf.get("score", 0) >= 50.0 else "med",
            }
        )

    refund = axes_payload.get("refund_risk") or {}
    if refund.get("historical_refund_count", 0) >= 1:
        recs.append(
            {
                "axis": "refund",
                "action": (
                    "過去の返還命令対象 program について、現行受給制度の "
                    "排除事由 (subsidy_exclude) に該当しないか申請前に確認。"
                    "確定判断は行政書士・認定支援機関へ。"
                ),
                "urgency": "high" if refund.get("score", 0) >= 50.0 else "med",
            }
        )

    inv = axes_payload.get("invoice_compliance_risk") or {}
    if inv.get("score", 0) >= 50.0:
        recs.append(
            {
                "axis": "invoice_compliance",
                "action": (
                    "適格請求書発行事業者登録が無効化されています。"
                    "国税庁適格請求書サイトで現状確認、未登録なら再登録を税理士に相談。"
                ),
                "urgency": "high",
            }
        )
    elif not inv.get("registered", False) and inv.get("score", 0) >= 25.0:
        recs.append(
            {
                "axis": "invoice_compliance",
                "action": (
                    "適格請求書発行事業者として未登録。 取引先 (買手) の "
                    "入力税額控除に影響するため、事業継続要件を税理士と確認。"
                ),
                "urgency": "med",
            }
        )

    rev = axes_payload.get("adoption_revocation_risk") or {}
    if rev.get("recent_amendment_count_on_held_programs", 0) >= 1:
        recs.append(
            {
                "axis": "adoption_revocation",
                "action": (
                    "受給中の制度に直近12ヶ月内の改正履歴があります。"
                    "改正後の継続要件・実績報告義務を確認、認定支援機関に照会。"
                ),
                "urgency": "med",
            }
        )

    drift = axes_payload.get("jurisdiction_drift_risk") or {}
    if drift.get("divergence_count", 0) >= 2:
        recs.append(
            {
                "axis": "jurisdiction_drift",
                "action": (
                    "登記/インボイス/採択の管轄都道府県が複数に分散しています。"
                    "事業実態と登記住所の整合性を司法書士・税理士に確認。"
                ),
                "urgency": "low" if drift.get("divergence_count", 0) <= 2 else "med",
            }
        )

    return recs


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------


def _parse_axes(raw: list[str] | None) -> list[str]:
    if not raw:
        return list(_ALL_AXES)
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        for token in item.split(","):
            t = token.strip().lower()
            if t and t in _ALL_AXES and t not in out:
                out.append(t)
    return out or list(_ALL_AXES)


def _normalize_weights(
    selected_axes: list[str], overrides: dict[str, float] | None
) -> dict[str, float]:
    """Even-weight default; overrides clamp to [0, 1] and renormalize.

    If every axis has an override, weights pass through clamped (no
    renormalisation — caller controls absolute scale). If only some axes
    have overrides, the un-overridden axes split the remainder evenly.
    """
    if not selected_axes:
        return {}
    overrides = overrides or {}
    clean: dict[str, float] = {}
    for axis, weight in overrides.items():
        if axis not in selected_axes:
            continue
        try:
            w = float(weight)
        except (TypeError, ValueError):
            continue
        clean[axis] = max(0.0, min(1.0, w))

    weights: dict[str, float] = {}
    if not clean:
        even = 1.0 / len(selected_axes)
        for axis in selected_axes:
            weights[axis] = even
        return weights

    # If every axis has an explicit override, pass through clamped.
    if set(clean.keys()) >= set(selected_axes):
        for axis in selected_axes:
            weights[axis] = clean[axis]
        return weights

    # Mixed: overrides verbatim, remainder split evenly across un-overridden.
    overridden_total = sum(clean.values())
    remaining = max(0.0, 1.0 - overridden_total)
    un_overridden = [a for a in selected_axes if a not in clean]
    even_remaining = remaining / len(un_overridden) if un_overridden else 0.0
    for axis in selected_axes:
        weights[axis] = clean.get(axis, even_remaining)
    return weights


def _build_risk_score(
    *,
    am_conn: sqlite3.Connection,
    houjin_id: str,
    selected_axes: list[str],
    weight_overrides: dict[str, float] | None,
) -> dict[str, Any]:
    today = _dt.date.today()

    meta = _fetch_houjin_meta(am_conn, houjin_id)
    name = meta["normalized_name"] if meta else None

    axes_payload: dict[str, dict[str, Any]] = {}
    if "enforcement" in selected_axes:
        axes_payload["enforcement_risk"] = _score_enforcement(am_conn, houjin_id, today)
    if "refund" in selected_axes:
        axes_payload["refund_risk"] = _score_refund(am_conn, houjin_id, today)
    if "invoice_compliance" in selected_axes:
        axes_payload["invoice_compliance_risk"] = _score_invoice_compliance(
            am_conn, houjin_id, today
        )
    if "adoption_revocation" in selected_axes:
        axes_payload["adoption_revocation_risk"] = _score_adoption_revocation(
            am_conn, houjin_id, today
        )
    if "jurisdiction_drift" in selected_axes:
        axes_payload["jurisdiction_drift_risk"] = _score_jurisdiction_drift(
            am_conn, houjin_id, today
        )

    weights = _normalize_weights(selected_axes, weight_overrides)
    # Per-axis score map keyed by axis short name (matches weights keys).
    axis_short_to_block = {
        "enforcement": "enforcement_risk",
        "refund": "refund_risk",
        "invoice_compliance": "invoice_compliance_risk",
        "adoption_revocation": "adoption_revocation_risk",
        "jurisdiction_drift": "jurisdiction_drift_risk",
    }
    total = 0.0
    for axis_short, weight in weights.items():
        block = axes_payload.get(axis_short_to_block[axis_short]) or {}
        total += float(block.get("score", 0.0)) * weight
    total_score = round(min(100.0, max(0.0, total)), 2)
    label = _label_for_score(total_score)

    recommendations = _build_recommendations(axes_payload)

    # Peer benchmarking — uses jsic_major + size bucket.
    jsic_major = (meta or {}).get("jsic_major")
    size_bucket = _size_bucket_for_houjin(am_conn, houjin_id)
    benchmarking = _benchmark_against_peers(
        am_conn,
        houjin_id=houjin_id,
        own_total_score=total_score,
        jsic_major=jsic_major,
        size_bucket=size_bucket,
    )

    body: dict[str, Any] = {
        "houjin_id": houjin_id,
        "name": name,
        "total_score": total_score,
        "risk_label": label,
        "axes_evaluated": selected_axes,
        "axis_weights": {a: round(w, 4) for a, w in weights.items()},
        "axes": axes_payload,
        "recommendations": recommendations,
        "benchmarking": benchmarking,
        "_disclaimer": _DISCLAIMER,
        "_billing_unit": 1,
    }
    return body


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/risk_score",
    summary="Multi-axis houjin risk score (enforcement / refund / invoice / adoption / jurisdiction)",
    description=(
        "Composes 5 rules-based 0-100 axes into a single weighted total "
        "(higher = riskier). Pure SQLite + Python over am_enforcement_detail "
        "+ jpi_adoption_records + invoice_registrants + am_amendment_diff "
        "+ houjin_master. NO LLM call.\n\n"
        "**THIS IS NOT A CREDIT RATING.** The endpoint sits adjacent to "
        "与信判断 territory; the disclaimer fence (§52 / §72 / §1 + 業法) "
        "must be rendered verbatim.\n\n"
        "**Pricing:** ¥3 / call (`_billing_unit: 1`)."
    ),
    responses={
        200: {"description": "risk_score envelope (compact-friendly)."},
        404: {"description": "houjin_id not found in autonomath substrate."},
        422: {"description": "Malformed houjin_id (must be 13 digits)."},
        503: {"description": "autonomath.db not provisioned on this volume."},
    },
)
def post_risk_score(
    payload: Annotated[RiskScoreRequest, Body(...)],
    request: Request,
    conn: DbDep,
    ctx: ApiContextDep,
) -> JSONResponse:
    _t0 = time.perf_counter()

    normalized = _normalize_houjin(payload.houjin_id)
    if normalized is None:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_houjin_id",
                "field": "houjin_id",
                "message": (
                    f"houjin_id must be 13 digits (with or without 'T' prefix); "
                    f"got {payload.houjin_id!r}."
                ),
            },
        )

    selected_axes = _parse_axes(payload.include_axes)

    am_conn = _open_autonomath_ro()
    if am_conn is None:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "autonomath_db_unavailable",
                "message": "autonomath.db is not provisioned on this volume.",
            },
        )

    try:
        # 404 only when the queried houjin has zero footprint across every
        # substrate we touch. We probe houjin_master + adoption first
        # (cheapest cardinality) and short-circuit when both are empty.
        meta_row = _fetch_houjin_meta(am_conn, normalized)
        has_adoption = False
        if _table_exists(am_conn, "jpi_adoption_records"):
            try:
                row = am_conn.execute(
                    "SELECT 1 FROM jpi_adoption_records WHERE houjin_bangou = ? LIMIT 1",
                    (normalized,),
                ).fetchone()
                has_adoption = row is not None
            except sqlite3.Error:
                pass
        has_enforcement = False
        if _table_exists(am_conn, "am_enforcement_detail"):
            try:
                row = am_conn.execute(
                    "SELECT 1 FROM am_enforcement_detail WHERE houjin_bangou = ? LIMIT 1",
                    (normalized,),
                ).fetchone()
                has_enforcement = row is not None
            except sqlite3.Error:
                pass

        if meta_row is None and not has_adoption and not has_enforcement:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "houjin_not_found",
                    "houjin_id": normalized,
                    "message": (
                        f"No data found for 法人番号={normalized} across "
                        f"houjin_master / jpi_adoption_records / "
                        f"am_enforcement_detail. Either the id is unknown "
                        f"or the NTA bulk ingest has not yet caught up."
                    ),
                },
            )

        body = _build_risk_score(
            am_conn=am_conn,
            houjin_id=normalized,
            selected_axes=selected_axes,
            weight_overrides=payload.weight_overrides,
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            am_conn.close()

    # Auditor reproducibility (mirrors intel_houjin_full).
    with contextlib.suppress(sqlite3.Error):
        body = attach_corpus_snapshot(body, conn)

    latency_ms = int((time.perf_counter() - _t0) * 1000)
    log_usage(
        conn,
        ctx,
        "intel.risk_score",
        latency_ms=latency_ms,
        result_count=len(selected_axes),
        params={
            "houjin_id_present": True,
            "axis_count": len(selected_axes),
            "has_overrides": bool(payload.weight_overrides),
        },
        strict_metering=True,
    )
    attach_seal_to_body(
        body,
        endpoint="intel.risk_score",
        request_params={
            "houjin_id": normalized,
            "include_axes": selected_axes,
            "weight_overrides": payload.weight_overrides or {},
        },
        api_key_hash=ctx.key_hash,
        conn=conn,
    )

    if request is not None and wants_compact(request):
        body = to_compact(body)

    return JSONResponse(content=body)


__all__ = ["router"]
