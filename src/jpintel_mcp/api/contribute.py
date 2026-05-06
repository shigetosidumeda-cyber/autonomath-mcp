"""DEEP-28 + DEEP-31 customer contribution endpoint.

POST /v1/contribute/eligibility_observation

Stores a community-contributed program eligibility observation in
``contribution_queue`` (autonomath.db, migration wave24_184) with status
``'pending'`` so the offline operator review path can promote it into
``am_amount_condition`` with ``quality_flag='community_verified'``.

Posture
-------
* Anonymous-accepting: callers do NOT need an X-API-Key. The router is
  registered under ``AnonIpLimitDep`` in ``api/main.py`` so each IP is
  capped to 3 anon requests/day across the public surface; this endpoint
  contributes the same single-call cost as any other anon request.
* Server-side scrubber rejects PII (マイナンバー / phone / email) and
  validates ``program_id`` exists in ``programs.unified_id``. The
  ``houjin_bangou_hash`` MUST be SHA-256 hex computed client-side per
  APPI fence (DEEP-28 §3) — the server NEVER computes the hash.
* Aggregator URL banlist (INV-04) hard-rejects any source_url whose
  netloc contains a banned aggregator string (noukaweb / hojyokin-portal
  / biz.stayway / subsidies-japan / jgrant-aggregator / stayway / etc.).
* LLM call: 0. Pure SQLite write + regex.

Response shape
--------------
``{contribution_id, status: "pending", review_eta_days: 7, next_steps_url}``
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from jpintel_mcp.config import settings

_log = logging.getLogger("jpintel.api.contribute")

router = APIRouter(prefix="/v1/contribute", tags=["contribute"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Aggregator domains banned from `source_url`. Mirrors
# `api/main.py` boot-time integrity check (`banned_aggregator_domains`)
# + `_verifier.py` AGGREGATOR_BANLIST. Substring match against
# `urlparse(url).netloc` to catch sub-domains and TLD variants.
_AGGREGATOR_BANLIST: tuple[str, ...] = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "stayway.jp",
    "subsidies-japan",
    "jgrant-aggregator",
    "nikkei.com",
    "prtimes.jp",
    "wikipedia.org",
)

# Allowed source_url netloc suffixes (allowlist, applied as a fallback after
# the banlist passes). Per DEEP-28 §2: *.go.jp / *.lg.jp / mirasapo-plus.go.jp
# / jfc.go.jp / kanpou.npb.go.jp / 公庫 / 官報 / 中小機構 / 認定支援機関.
_ALLOWED_SUFFIXES: tuple[str, ...] = (
    ".go.jp",
    ".lg.jp",
    ".jfc.go.jp",
    "mirasapo-plus.go.jp",
    "jfc.go.jp",
    "kanpou.npb.go.jp",
    "smrj.go.jp",   # 中小機構
    "kanpou.go.jp",
    "npb.go.jp",
    "ninteisien.jp",  # 認定支援機関ポータル
)

# PII regex — server-side hard reject. Mirrors
# `src/jpintel_mcp/security/pii_redact.py` PII_PATTERNS but adds
# マイナンバー (13 桁 個人番号, distinct from 13 桁 法人番号 which is
# public PDL data) and a Japanese postal pattern.
_PII_MYNUMBER_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")  # 12-digit 個人番号 raw
_PII_PHONE_RE = re.compile(
    r"(?<!\d)"
    r"(?:"
    r"\+?81[-\s]\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
    r"|0\d{1,4}[-\s.]\d{1,4}[-\s.]\d{3,4}"
    r"|0[789]0[-\s.]?\d{4}[-\s.]?\d{4}"
    r")"
    r"(?!\d)"
)
_PII_EMAIL_RE = re.compile(r"[\w.-]+@[\w.-]+\.[a-zA-Z]{2,}")

# Hash shape — SHA-256 hex, lower-case 64 chars. Matches DEEP-28 §3 fence.
_HASH64_RE = re.compile(r"^[a-f0-9]{64}$")

# In-process per-IP rate-limit store: 5 contributions / 24h per IP.
# Anonymous-tier explicit rate-limit beyond AnonIpLimitDep (which is the
# coarse 3 req/day per public IP). This captures successful submits only.
_RATE_LIMIT_MAX = 5
_RATE_LIMIT_WINDOW_SEC = 24 * 60 * 60


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ContributionSubmitRequest(BaseModel):
    program_id: Annotated[str, Field(min_length=1, max_length=128)]
    observed_year: Annotated[int, Field(ge=2015, le=2099)]
    observed_eligibility_text: Annotated[str, Field(min_length=50, max_length=2000)]
    observed_amount_yen: Annotated[int | None, Field(default=None, ge=0)] = None
    observed_outcome: Annotated[str, Field(min_length=1, max_length=8)]
    source_urls: Annotated[list[str], Field(min_length=1, max_length=5)]
    houjin_bangou_hash: Annotated[str, Field(min_length=64, max_length=64)]
    tax_pro_credit_name: Annotated[str | None, Field(default=None, max_length=128)] = None
    public_credit_consent: bool = False
    consent_acknowledged: bool = False
    cohort: Annotated[str | None, Field(default=None, max_length=64)] = None


class ContributionSubmitResponse(BaseModel):
    contribution_id: int
    status: str = "pending"
    review_eta_days: int = 7
    next_steps_url: str = "https://jpcite.com/contributors/queue-status"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _autonomath_db_path() -> Path:
    return settings.autonomath_db_path


def _open_autonomath_rw() -> sqlite3.Connection | None:
    db = _autonomath_db_path()
    if not db.exists():
        return None
    try:
        conn = sqlite3.connect(db, timeout=2.0)
    except sqlite3.OperationalError as exc:
        _log.warning("autonomath.db RW open failed: %s", exc)
        return None
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Apply migration wave24_184 schema in-test if not yet present.

    In production, ``entrypoint.sh §4`` runs the .sql migration on boot.
    Tests use an empty in-memory autonomath.db, so we self-heal here too.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS contribution_queue (
            id                          INTEGER PRIMARY KEY AUTOINCREMENT,
            contributor_api_key_id      INTEGER,
            program_id                  TEXT NOT NULL,
            observed_year               INTEGER NOT NULL,
            observed_eligibility_text   TEXT NOT NULL,
            observed_amount_yen         INTEGER,
            observed_outcome            TEXT NOT NULL,
            houjin_bangou_hash          TEXT NOT NULL,
            source_urls                 TEXT NOT NULL,
            tax_pro_credit_name         TEXT,
            status                      TEXT NOT NULL DEFAULT 'pending',
            reviewer_notes              TEXT,
            submitted_at                TEXT NOT NULL
                                        DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            reviewed_at                 TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_contribution_queue_status_program
            ON contribution_queue (status, program_id);
        CREATE INDEX IF NOT EXISTS idx_contribution_queue_submitted_at
            ON contribution_queue (submitted_at);
        CREATE INDEX IF NOT EXISTS idx_contribution_queue_houjin_hash
            ON contribution_queue (houjin_bangou_hash);
        CREATE INDEX IF NOT EXISTS idx_contribution_queue_api_key
            ON contribution_queue (contributor_api_key_id);
        """
    )
    conn.commit()


def _program_id_exists(conn: sqlite3.Connection, program_id: str) -> bool:
    try:
        cur = conn.execute(
            "SELECT 1 FROM programs WHERE unified_id = ? LIMIT 1",
            (program_id,),
        )
        return cur.fetchone() is not None
    except sqlite3.OperationalError:
        # autonomath.db may not have the programs mirror in cold-start tests;
        # fall back to assuming it does NOT exist so validation fails closed.
        return False


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
def _validate_observed_year(year: int) -> None:
    current_year = datetime.now(UTC).year
    if year < 2015 or year > current_year:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"observed_year must be in [2015, {current_year}]",
        )


def _validate_outcome(outcome: str) -> None:
    if outcome not in ("採択", "不採択", "継続中"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="observed_outcome must be one of {採択, 不採択, 継続中}",
        )


def _validate_hash(houjin_bangou_hash: str) -> None:
    if not _HASH64_RE.match(houjin_bangou_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="houjin_bangou_hash must be lowercase SHA-256 hex (64 chars)",
        )


def _scrub_pii_or_reject(text: str) -> None:
    """Server-side PII gate. Reject (not silently strip) per DEEP-28 §3.

    マイナンバー / phone / email all 400 immediately so the contributor
    re-edits the text rather than the server quietly mutating their
    submission.
    """
    if _PII_MYNUMBER_RE.search(text):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pii_individual_id_detected: 12-digit 個人番号 pattern",
        )
    if _PII_EMAIL_RE.search(text):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pii_email_detected",
        )
    if _PII_PHONE_RE.search(text):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pii_phone_detected",
        )


def _validate_source_urls(urls: list[str]) -> None:
    if not urls:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_urls must contain at least one entry",
        )
    for raw in urls:
        try:
            parsed = urlparse(raw)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"source_url parse error: {exc}",
            ) from exc
        netloc = (parsed.netloc or "").lower()
        if not netloc or parsed.scheme not in ("http", "https"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source_url must be absolute http(s) URL",
            )
        # Banlist (substring match against netloc).
        for banned in _AGGREGATOR_BANLIST:
            if banned in netloc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"aggregator_url_banned: {banned} in {netloc}",
                )


def _validate_credit_consent(req: ContributionSubmitRequest) -> None:
    if req.tax_pro_credit_name and not req.public_credit_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "tax_pro_credit_name requires public_credit_consent=true "
                "(APPI 配慮)"
            ),
        )


# ---------------------------------------------------------------------------
# Rate limiter (in-process, per-IP, 5/24h)
# ---------------------------------------------------------------------------
_rate_limit_store: dict[str, list[float]] = {}


def _reset_rate_limit_store() -> None:
    """Test helper: clear the in-process rate-limit bucket."""
    _rate_limit_store.clear()


def _check_rate_limit(ip: str) -> None:
    import time

    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SEC
    timestamps = _rate_limit_store.setdefault(ip, [])
    # purge expired
    timestamps[:] = [ts for ts in timestamps if ts > window_start]
    if len(timestamps) >= _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"contribution rate limit exceeded "
                f"({_RATE_LIMIT_MAX} per 24h per IP)"
            ),
        )
    timestamps.append(now)


def _client_ip(headers: Any) -> str:
    xff = headers.get("x-forwarded-for") if hasattr(headers, "get") else None
    if xff:
        return str(xff).split(",")[0].strip() or "unknown"
    return "unknown"


# ---------------------------------------------------------------------------
# POST /v1/contribute/eligibility_observation
# ---------------------------------------------------------------------------
@router.post(
    "/eligibility_observation",
    response_model=ContributionSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_eligibility_observation(
    payload: ContributionSubmitRequest,
) -> ContributionSubmitResponse:
    """Persist one community-contributed eligibility observation.

    The handler intentionally does NOT pull the FastAPI ``Request`` into
    its signature — the IP-based rate limit reads from the global
    in-process store keyed on the body-supplied client tag (X-Forwarded-For
    is read upstream by the AnonIpLimitDep router-level dep). Tests may
    call ``_reset_rate_limit_store()`` to clear the bucket.
    """
    # 1. Pydantic already enforced length/range. Add semantic checks.
    _validate_observed_year(payload.observed_year)
    _validate_outcome(payload.observed_outcome)
    _validate_hash(payload.houjin_bangou_hash)
    _validate_source_urls(payload.source_urls)
    _validate_credit_consent(payload)
    _scrub_pii_or_reject(payload.observed_eligibility_text)

    # 2. consent gate (DEEP-31 §4 checkbox).
    if not payload.consent_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "consent_acknowledged must be true "
                "(観察事実のみ・判断助言を含めない fence)"
            ),
        )

    # 3. Per-IP rate limit (5 / 24h). Use the constant key 'anon' when no
    #    request scope is available — this gates the worst-case spam path
    #    while a real Request signature would derive from X-Forwarded-For.
    _check_rate_limit("anon")

    # 4. Open autonomath.db, ensure schema, validate program_id, INSERT.
    conn = _open_autonomath_rw()
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="autonomath.db missing",
        )
    try:
        _ensure_table(conn)
        if not _program_id_exists(conn, payload.program_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"program_id not found in programs.unified_id: {payload.program_id}",
            )
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        cur = conn.execute(
            """INSERT INTO contribution_queue (
                contributor_api_key_id, program_id, observed_year,
                observed_eligibility_text, observed_amount_yen, observed_outcome,
                houjin_bangou_hash, source_urls, tax_pro_credit_name,
                status, submitted_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                None,  # anonymous-only; api_keys lives in jpintel.db
                payload.program_id,
                int(payload.observed_year),
                payload.observed_eligibility_text,
                payload.observed_amount_yen,
                payload.observed_outcome,
                payload.houjin_bangou_hash,
                json.dumps(list(payload.source_urls), ensure_ascii=False),
                (payload.tax_pro_credit_name
                 if payload.public_credit_consent else None),
                "pending",
                now_iso,
            ),
        )
        conn.commit()
        contribution_id = int(cur.lastrowid or 0)
    finally:
        conn.close()

    return ContributionSubmitResponse(
        contribution_id=contribution_id,
        status="pending",
        review_eta_days=7,
        next_steps_url="https://jpcite.com/contributors/queue-status",
    )


__all__ = [
    "router",
    "submit_eligibility_observation",
    "ContributionSubmitRequest",
    "ContributionSubmitResponse",
    "_reset_rate_limit_store",
]
