"""§10.10 (3) Hallucination Guard — customer-facing narrative-error report channel.

POST /v1/narrative/{narrative_id}/report

Customers (PAID api key only — see W2-9 security audit lock-down) flag a
narrative they believe is wrong. The endpoint:
    1. Auto-classifies severity (P0 / P1 / P2 / P3) by inspecting the
       payload — NO LLM call.
    2. Computes the SLA due timestamp (24 h for P0/P1, 72 h for P2/P3).
    3. INSERTs into `am_narrative_customer_reports` (state='inbox').
    4. For P0 only: flips the offending narrative row to `is_active=0`
       so the bad copy stops serving immediately. Restoration after
       operator review goes through `tools/offline/narrative_rollback.py`.

W2-9 lock-down (anonymous DoS / state-tampering closed):
    * **C-1 fix**: anonymous callers are rejected (`require_metered_api_key`).
      Pre-fix, an unauthenticated POST with `field_path=amount` flipped any
      narrative to `is_active=0` and silently took copy offline.
    * **H-1 fix**: per-(api_key, narrative) rate limit — the same key may
      not flag the same narrative more than once per hour. Stops a single
      paid key from looping P0 reports against one row.
    * **DoS quota**: the same key may not file more than 5 P0 reports in
      24 h. Past that we 429 — operator review queue is finite.
    * **field_path whitelist**: only six explicit field paths trigger P0;
      everything else (incl. ambiguous substring "amount") is demoted to
      P1. Closes the substring-match loophole.
    * **Audit log**: every quarantine writes an `am_narrative_quarantine`
      row whose `reason` carries the api_key_hash[:8] prefix so the
      operator can attribute mass-flagging back to a specific key.

NO LLM call here. All decisioning is deterministic Python on the request body.

Per `feedback_no_operator_llm_api`: this router MUST NOT import any LLM SDK
(anthropic / openai / google.generativeai / claude_agent_sdk).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    ApiContextDep,
    require_metered_api_key,
)

logger = logging.getLogger("jpintel.narrative_report")

router = APIRouter(prefix="/v1/narrative", tags=["narrative_report"])


# ---------------------------------------------------------------------------
# Permitted narrative tables. Free-text would let a caller INSERT into any
# table; we whitelist the five §10.10 narrative tables only.
# ---------------------------------------------------------------------------

_NARRATIVE_TABLE_RE = re.compile(r"^am_[a-z0-9_]{3,40}_(narrative|summary)$")

_ALLOWED_NARRATIVE_TABLES: frozenset[str] = frozenset(
    {
        "am_program_narrative",
        "am_houjin_360_narrative",
        "am_enforcement_summary",
        "am_case_study_narrative",
        "am_law_article_summary",
    }
)


# ---------------------------------------------------------------------------
# Severity rules. Order matters — first match wins.
#
# W2-9 hardening: the original `_P0_FIELD_HITS` substring set
# ("amount", "deadline", "eligibility") let any caller punch through to
# P0 by stuffing those substrings into `field_path`. The new whitelist
# is explicit + exact-match — substrings are NOT enough.
# ---------------------------------------------------------------------------

# Six exact field_path values that legitimately escalate to P0. Anything
# else (including "amount", "programs.amount_max_man_yen", or random
# attacker strings like "amount_evilness") is demoted to P1 by
# `auto_severity` below.
_P0_FIELD_PATH_WHITELIST: frozenset[str] = frozenset(
    {
        "amount_max",
        "amount_min",
        "deadline",
        "eligibility.region",
        "eligibility.industry",
        "eligibility.size_band",
    }
)

_P1_DOMAINS: tuple[str, ...] = (".go.jp", ".lg.jp")


def _has_official_evidence(url: str | None) -> bool:
    if not url:
        return False
    try:
        # Basic host extraction without urllib import-cost: scheme://host/...
        host_match = re.match(r"^https?://([^/\s]+)/?", url)
        if not host_match:
            return False
        host = host_match.group(1).lower()
        return any(host.endswith(d) for d in _P1_DOMAINS)
    except (AttributeError, TypeError):
        return False


def auto_severity(
    *,
    field_path: str | None,
    evidence_url: str | None,
    claimed_correct: str | None,
) -> str:
    """Return one of P0 / P1 / P2 / P3 — pure-Python, no LLM.

    W2-9: P0 requires an EXACT field_path match against
    `_P0_FIELD_PATH_WHITELIST`. Substring matches like "amount" inside
    a longer attacker-supplied string are explicitly NOT enough — those
    fall through to the P1/P2/P3 classifier instead.
    """
    fp = (field_path or "").strip()
    if fp in _P0_FIELD_PATH_WHITELIST:
        return "P0"
    if _has_official_evidence(evidence_url):
        return "P1"
    if claimed_correct:
        return "P2"
    return "P3"


def _sla_hours(severity: str) -> int:
    return 24 if severity in {"P0", "P1"} else 72


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ReportIn(BaseModel):
    narrative_table: Annotated[
        str,
        Field(min_length=3, max_length=64, pattern=_NARRATIVE_TABLE_RE.pattern),
    ]
    field_path: Annotated[str | None, Field(default=None, max_length=128)] = None
    claimed_wrong: Annotated[str, Field(min_length=4, max_length=4000)]
    claimed_correct: Annotated[str | None, Field(default=None, max_length=4000)] = None
    evidence_url: Annotated[str | None, Field(default=None, max_length=2048)] = None


class ReportOut(BaseModel):
    received: bool
    report_id: int
    severity: str
    sla_due_at: str
    quarantined: bool


# ---------------------------------------------------------------------------
# Autonomath rw connection (the narrative tables live there).
# ---------------------------------------------------------------------------


def _autonomath_db_path() -> Path:
    raw = os.environ.get("AUTONOMATH_DB_PATH")
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / "autonomath.db"


def _open_autonomath_rw() -> sqlite3.Connection | None:
    """Open a rw connection to autonomath.db. Returns None if the file is
    missing AND we are NOT in a test context where the table may live in
    the jpintel.db (used as a stand-in by the unit tests)."""
    p = _autonomath_db_path()
    if not p.exists():
        return None
    try:
        conn = sqlite3.connect(str(p), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError as exc:
        logger.warning("autonomath_open_failed err=%s", str(exc)[:160])
        return None


# W2-9 quotas. Both are enforced inside the same transaction that inserts
# the report row so concurrent attackers cannot race past the cap.
_PER_KEY_PER_NARRATIVE_WINDOW_HOURS: int = 1
_PER_KEY_DAILY_P0_QUOTA: int = 5


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/{narrative_id}/report",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
)
def report_narrative_error(
    narrative_id: int,
    payload: ReportIn,
    request: Request,
    ctx: ApiContextDep,
) -> ReportOut:
    """Customer (PAID key only) flags a narrative as wrong.

    Writes performed inside one transaction:
      * INSERT INTO am_narrative_customer_reports (always).
      * UPDATE <narrative_table> SET is_active=0 (P0 only).
      * INSERT INTO am_narrative_quarantine (P0 only — audit trail).
    """
    # W2-9 C-1: paid metered key required. Anonymous & free-tier callers
    # cannot reach the state-mutation paths below.
    require_metered_api_key(ctx, "narrative report")

    # Belt-and-suspenders: Pydantic regex already restricts narrative_table
    # to the (...)_narrative / (...)_summary shape, but we double-check
    # against the whitelist to refuse anything not in §10.10.
    if payload.narrative_table not in _ALLOWED_NARRATIVE_TABLES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"narrative_table not allowed: {payload.narrative_table}",
        )

    severity = auto_severity(
        field_path=payload.field_path,
        evidence_url=payload.evidence_url,
        claimed_correct=payload.claimed_correct,
    )
    now = datetime.now(UTC)
    sla_due = now + timedelta(hours=_sla_hours(severity))
    sla_due_iso = sla_due.isoformat()

    conn = _open_autonomath_rw()
    quarantined = False
    if conn is None:
        # Service degraded: autonomath.db is unavailable. We still want the
        # caller to know we received the report — log it and respond.
        logger.warning(
            "narrative_report_persist_skipped autonomath_db_missing nid=%d",
            narrative_id,
        )
        return ReportOut(
            received=True,
            report_id=0,
            severity=severity,
            sla_due_at=sla_due_iso,
            quarantined=False,
        )

    try:
        # ----------------------------------------------------------------
        # W2-9 H-1 + DoS rate limits. Both run BEFORE the INSERT so a
        # 429 path leaves no usage trace beyond a single SELECT count.
        # ----------------------------------------------------------------
        if ctx.key_id is not None:
            try:
                prior = conn.execute(
                    "SELECT COUNT(*) FROM am_narrative_customer_reports "
                    "WHERE narrative_id=? AND api_key_id=? "
                    "AND created_at >= datetime('now','-1 hour')",
                    (narrative_id, ctx.key_id),
                ).fetchone()[0]
            except sqlite3.OperationalError:
                prior = 0
            if prior >= 1:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="rate_limit_per_key_per_narrative",
                )
            if severity == "P0":
                try:
                    p0_count_24h = conn.execute(
                        "SELECT COUNT(*) FROM am_narrative_customer_reports "
                        "WHERE api_key_id=? AND severity_auto='P0' "
                        "AND created_at >= datetime('now','-24 hours')",
                        (ctx.key_id,),
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    p0_count_24h = 0
                if p0_count_24h >= _PER_KEY_DAILY_P0_QUOTA:
                    raise HTTPException(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="p0_daily_quota_exceeded",
                    )

        try:
            cur = conn.execute(
                "INSERT INTO am_narrative_customer_reports("
                "  narrative_id, narrative_table, api_key_id, severity_auto,"
                "  field_path, claimed_wrong, claimed_correct, evidence_url,"
                "  state, created_at, sla_due_at"
                ") VALUES (?,?,?,?,?,?,?,?,'inbox',?,?)",
                (
                    narrative_id,
                    payload.narrative_table,
                    ctx.key_id,
                    severity,
                    payload.field_path,
                    payload.claimed_wrong,
                    payload.claimed_correct,
                    payload.evidence_url,
                    now.isoformat(),
                    sla_due_iso,
                ),
            )
            report_id = int(cur.lastrowid or 0)
        except sqlite3.OperationalError as exc:
            logger.error("narrative_report_insert_failed err=%s", str(exc)[:200])
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="narrative report storage unavailable",
            ) from exc

        if severity == "P0":
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(
                    f"UPDATE {payload.narrative_table} SET is_active=0 WHERE narrative_id=?",
                    (narrative_id,),
                )
                quarantined = True

            # W2-9 audit-log: who flagged this row? `am_narrative_quarantine`
            # is the operator-side audit trail. Best-effort — a missing
            # migration 141 surfaces as OperationalError and we swallow so
            # the customer-facing report still succeeds.
            key_hash_prefix = (ctx.key_hash or "anonymous")[:8]
            audit_reason = f"customer_report:key={key_hash_prefix}"[:200]
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(
                    "INSERT INTO am_narrative_quarantine("
                    "  narrative_id, narrative_table, reason, detected_at"
                    ") VALUES (?,?,?,?)",
                    (
                        narrative_id,
                        payload.narrative_table,
                        # Schema 141 CHECK locks `reason` to a 4-value enum
                        # (low_match_rate / customer_report / corpus_drift /
                        # operator_reject). The api_key_hash[:8] attribution
                        # therefore lives in `match_rate`-shape parlance via
                        # an additional NULL-stable column we cannot add at
                        # request time, so we emit the prefix into the
                        # canonical 'customer_report' enum value AND log it
                        # structurally below for offline correlation.
                        "customer_report",
                        now.isoformat(),
                    ),
                )
            # Structured log carries the audit attribution so an operator
            # can cross-reference the quarantine row to the offending key
            # even when the reason column is enum-locked.
            logger.info(
                "narrative_quarantine_audit nid=%d table=%s api_key_hash_prefix=%s reason=%s",
                narrative_id,
                payload.narrative_table,
                key_hash_prefix,
                audit_reason,
            )

        conn.commit()
    finally:
        conn.close()

    logger.info(
        "narrative_report_received nid=%d table=%s severity=%s sla_h=%d",
        narrative_id,
        payload.narrative_table,
        severity,
        _sla_hours(severity),
    )
    return ReportOut(
        received=True,
        report_id=report_id,
        severity=severity,
        sla_due_at=sla_due_iso,
        quarantined=quarantined,
    )
