"""Trust infrastructure surfaces (migration 101).

Public, no-auth (read) endpoints that turn the Top-8 trust tables shipped
by ``scripts/migrations/101_trust_infrastructure.sql`` into customer-
visible artefacts:

  GET  /v1/health/sla         — uptime + p95 latency metrics for site/sla.html
  GET  /v1/corrections        — JSON list of correction_log rows
  POST /v1/corrections        — customer-submitted corrections (queue row)
  GET  /v1/corrections/feed   — RSS 2.0 feed (also rendered statically by cron)
  GET  /v1/trust/section52    — daily violation-count rollup (§52 audit log)
  GET  /v1/cross_source/{eid} — confirming_source_count + agreement verdict
  GET  /v1/staleness          — per-dataset stale-flag rollup

Why one router rather than five
--------------------------------
The trust 8-pack is one feature-cohort; splitting it across five files would
add five entries to ``main.py`` and five places where future operators have
to look for "where does the SLA page get its data". Keeping them together
also means one set of tests covers the whole cohort.

Posture
-------
- All read endpoints are public and unmetered. Same posture as
  ``transparency_router`` and ``audit_log_router``: trust signals must
  always be reachable. Polling consumes ZERO of the 50/月 anonymous quota.
- The write endpoint (POST /v1/corrections) is rate-limited inside the
  handler (one submission per (entity_id, field, IP-hash, day)) — so
  ``main.py`` does not wrap this router with ``AnonIpLimitDep``.
- No §52 sensitive surface here: every payload is descriptive metadata
  about data quality / corrections / cross-source agreement. No 助言.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import logging
import re
import sqlite3
from typing import Annotated, Any
from xml.sax.saxutils import escape as _xml_escape

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from jpintel_mcp.config import settings
from jpintel_mcp.services.cross_source import compute_cross_source_agreement

_log = logging.getLogger("jpintel.api.trust")

router = APIRouter(prefix="/v1", tags=["trust"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STALE_DAYS = 90  # programs not refreshed in 90+ days surface stale=true


def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.UTC)


def _utc_iso() -> str:
    return _utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _hmac_hex(value: str) -> str:
    """HMAC-SHA256 of *value* under api_key_salt — never reversible."""
    salt = (settings.api_key_salt or "trust-fallback-salt").encode("utf-8")
    return hmac.new(salt, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _client_ip(request: Request) -> str:
    """Best-effort client IP, X-Forwarded-For aware. Returns 'unknown' as fallback."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client is not None:
        return request.client.host or "unknown"
    return "unknown"


def _open_autonomath_ro() -> sqlite3.Connection:
    """Read-only autonomath.db connection. Raises 503 if DB absent."""
    db = settings.autonomath_db_path
    if not db.exists():
        raise HTTPException(status_code=503, detail="autonomath.db missing")
    uri = f"file:{db}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def _open_autonomath_rw() -> sqlite3.Connection:
    """Read-write autonomath.db connection (only used for the POST submit path).

    The trust router is the ONE write path on autonomath.db that lives inside
    the API process — every other write is a cron job. We open per-request
    rather than reuse the global RO pool because writes need WAL semantics.
    """
    db = settings.autonomath_db_path
    if not db.exists():
        raise HTTPException(status_code=503, detail="autonomath.db missing")
    conn = sqlite3.connect(str(db), timeout=2.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 1. SLA health  /  GET /v1/health/sla
# ---------------------------------------------------------------------------
# Reads the in-process p95 sample buffer maintained by
# `_QueryTelemetryMiddleware` is too noisy / not aggregated — instead we
# derive uptime + latency from `usage_events` rows in jpintel.db (the same
# table billing reads from). The 7-day rolling window matches the SLO doc
# in monitoring/sla_targets.md.

class SlaResponse(BaseModel):
    window: str = Field(..., description='"24h" or "7d"')
    uptime_pct: float = Field(..., description="Successful (status<500) / total")
    p95_latency_ms: int | None = Field(
        None, description="p95 of latency_ms across non-error events; None if too few samples."
    )
    sample_count: int
    generated_at: str
    target: dict[str, Any] = Field(
        default_factory=lambda: {
            "uptime_pct": 99.5,
            "p95_latency_ms": 1500,
            "source": "monitoring/sla_targets.md",
        },
    )


def _percentile(values: list[int], pct: float) -> int | None:
    """Inclusive-rank percentile. Returns None on empty input."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))
    return int(s[k])


@router.get("/health/sla", response_model=SlaResponse, tags=["trust", "sla"])
async def sla_metrics(
    window: Annotated[str, Query(pattern="^(24h|7d)$")] = "7d",
) -> SlaResponse:
    """Public SLA metrics — uptime + p95 latency.

    Reads from jpintel.db `usage_events` (every API call lands a row).
    Uptime = (status < 500) / total. p95 across non-error events.
    """
    delta = _dt.timedelta(days=7) if window == "7d" else _dt.timedelta(hours=24)
    cutoff = (_utcnow() - delta).isoformat()

    from jpintel_mcp.db.session import connect

    conn = connect()
    try:
        try:
            total_row = conn.execute(
                "SELECT COUNT(*) AS n, "
                "       SUM(CASE WHEN status < 500 THEN 1 ELSE 0 END) AS ok "
                "FROM usage_events WHERE ts >= ?",
                (cutoff,),
            ).fetchone()
        except sqlite3.OperationalError:
            # usage_events table absent on a brand-new test DB: degrade
            # to a deterministic-but-honest "no samples yet" response.
            total_row = None
        if total_row is None or (total_row["n"] or 0) == 0:
            return SlaResponse(
                window=window,
                uptime_pct=100.0,
                p95_latency_ms=None,
                sample_count=0,
                generated_at=_utc_iso(),
            )

        n = int(total_row["n"] or 0)
        ok = int(total_row["ok"] or 0)
        uptime = round(100.0 * ok / n, 3) if n > 0 else 100.0

        # p95 over recent latencies (skip NULL values; only search endpoints
        # populate latency_ms today, which is exactly the SLO measurement set).
        try:
            lat_rows = conn.execute(
                "SELECT latency_ms FROM usage_events "
                "WHERE ts >= ? AND latency_ms IS NOT NULL AND status < 500 "
                "ORDER BY ts DESC LIMIT 5000",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError:
            lat_rows = []
        latencies = [int(r[0]) for r in lat_rows if r[0] is not None]
        p95 = _percentile(latencies, 95.0)

        return SlaResponse(
            window=window,
            uptime_pct=uptime,
            p95_latency_ms=p95,
            sample_count=n,
            generated_at=_utc_iso(),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. Corrections list  /  GET /v1/corrections
# ---------------------------------------------------------------------------

@router.get("/corrections", tags=["trust", "corrections"])
async def list_corrections(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    dataset: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
) -> JSONResponse:
    """Most-recent corrections (correction_log table, mig 101).

    Reverse-chrono. Cite-only — every row carries source_url + reproducer_sql
    so an auditor can verify the correction byte-for-byte.
    """
    where = ""
    args: list[Any] = []
    if dataset:
        where = "WHERE dataset = ?"
        args.append(dataset)
    args.append(limit)
    sql = (
        "SELECT id, detected_at, dataset, entity_id, field_name, "
        "       prev_value_hash, new_value_hash, root_cause, source_url, "
        "       reproducer_sql, correction_post_url "
        f"FROM correction_log {where} "
        "ORDER BY detected_at DESC, id DESC LIMIT ?"
    )

    conn = _open_autonomath_ro()
    try:
        try:
            rows = conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                rows = []
            else:
                raise
    finally:
        conn.close()

    out = [dict(r) for r in rows]
    body = {
        "results": out,
        "limit": limit,
        "filter": {"dataset": dataset},
        "_meta": {
            "rss": "/v1/corrections/feed",
            "license_metadata": "CC-BY-4.0",
            "creator": "Bookyou株式会社 (T8010001213708)",
        },
    }
    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# 3. Correction submit  /  POST /v1/corrections
# ---------------------------------------------------------------------------

class CorrectionSubmit(BaseModel):
    entity_id: str = Field(..., min_length=1, max_length=200)
    field: str = Field(..., min_length=1, max_length=120)
    claimed_correct_value: str = Field(..., min_length=1, max_length=4000)
    evidence_url: str = Field(..., pattern=r"^https?://", max_length=2000)
    reporter_email: str | None = Field(None, max_length=320)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/corrections", tags=["trust", "corrections"], status_code=201)
async def submit_correction(
    request: Request,
    payload: Annotated[CorrectionSubmit, Body(...)],
) -> JSONResponse:
    """Customer-submitted data correction. Idempotent on (entity_id, field, IP-hash, day)."""
    if payload.reporter_email and not _EMAIL_RE.match(payload.reporter_email):
        # 422 (semantic validation failure) — request was syntactically valid
        # JSON, but a field value did not satisfy a server-side constraint.
        # 400 was the previous status; switching to 422 to align with the rest
        # of the API where Pydantic + custom-validator failures both return
        # 422 (handled by `_validation_handler` in main.py).
        raise HTTPException(status_code=422, detail="invalid reporter_email")

    ip = _client_ip(request)
    ip_hash = _hmac_hex(ip)
    email_hmac = _hmac_hex(payload.reporter_email or f"anon:{ip_hash}")

    submitted_at = _utc_iso()
    today = submitted_at[:10]

    conn = _open_autonomath_rw()
    try:
        # Same-day dedup: skip insert if (entity_id, field, ip_hash, day) seen.
        try:
            dup = conn.execute(
                "SELECT id FROM correction_submissions "
                "WHERE entity_id = ? AND field = ? AND reporter_ip_hash = ? "
                "AND substr(submitted_at, 1, 10) = ? "
                "ORDER BY id DESC LIMIT 1",
                (payload.entity_id, payload.field, ip_hash, today),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                raise HTTPException(
                    status_code=503,
                    detail="correction_submissions table missing (mig 101 not applied)",
                ) from exc
            raise

        if dup is not None:
            return JSONResponse(
                status_code=200,
                content={
                    "id": int(dup["id"]),
                    "status": "duplicate",
                    "message": "Already submitted today.",
                },
            )

        cur = conn.execute(
            "INSERT INTO correction_submissions("
            "  submitted_at, entity_id, field, claimed_correct_value, "
            "  evidence_url, reporter_email_hmac, reporter_ip_hash, status"
            ") VALUES (?,?,?,?,?,?,?, 'pending')",
            (
                submitted_at, payload.entity_id, payload.field,
                payload.claimed_correct_value, payload.evidence_url,
                email_hmac, ip_hash,
            ),
        )
        new_id = int(cur.lastrowid or 0)
    finally:
        conn.close()

    return JSONResponse(
        status_code=201,
        content={
            "id": new_id,
            "status": "pending",
            "submitted_at": submitted_at,
            "message": (
                "Submission received. Operator (Bookyou株式会社) reviews "
                "submissions weekly; accepted corrections appear in "
                "/v1/corrections within 7 days."
            ),
        },
    )


# ---------------------------------------------------------------------------
# 4. Corrections RSS feed  /  GET /v1/corrections/feed
# ---------------------------------------------------------------------------

_RSS_DOMAIN = "jpcite.com"


@router.get(
    "/corrections/feed",
    tags=["trust", "corrections"],
    response_class=Response,
)
async def corrections_rss_feed() -> Response:
    """RSS 2.0 of the latest 50 corrections."""
    conn = _open_autonomath_ro()
    try:
        try:
            rows = conn.execute(
                "SELECT id, detected_at, dataset, entity_id, field_name, "
                "       root_cause, source_url, correction_post_url "
                "FROM correction_log "
                "ORDER BY detected_at DESC, id DESC LIMIT 50"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                rows = []
            else:
                raise
    finally:
        conn.close()

    items: list[str] = []
    for r in rows:
        title = (
            f"[{_xml_escape(r['dataset'])}] {_xml_escape(r['entity_id'])}"
            f" — {_xml_escape(r['field_name'] or 'row-level')}"
            f" ({_xml_escape(r['root_cause'])})"
        )
        link_url = (
            r["correction_post_url"]
            or f"https://{_RSS_DOMAIN}/news/correction-{r['id']}.html"
        )
        guid = f"correction-{r['id']}"
        # detected_at is ISO 8601; convert to RFC 822-ish for RSS pubDate.
        try:
            pub_dt = _dt.datetime.fromisoformat(
                r["detected_at"].replace("Z", "+00:00")
            )
            from email.utils import format_datetime
            pub_date = format_datetime(pub_dt)
        except Exception:  # noqa: BLE001
            pub_date = r["detected_at"]
        desc = (
            f"Source: {_xml_escape(r['source_url'] or 'N/A')}. "
            "Operator: Bookyou株式会社 (T8010001213708)."
        )
        items.append(
            f"  <item>\n"
            f"    <title>{title}</title>\n"
            f"    <link>{_xml_escape(link_url)}</link>\n"
            f"    <guid isPermaLink=\"false\">{guid}</guid>\n"
            f"    <pubDate>{pub_date}</pubDate>\n"
            f"    <description>{desc}</description>\n"
            f"  </item>"
        )

    last_build = _utc_iso()
    rss = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "<channel>\n"
        "  <title>税務会計AI Corrections (correction_log)</title>\n"
        f"  <link>https://{_RSS_DOMAIN}/corrections.xml</link>\n"
        f'  <atom:link href="https://{_RSS_DOMAIN}/corrections.xml" rel="self" type="application/rss+xml" />\n'
        "  <description>Customer-reported and cross-source detected data "
        "corrections. CC-BY-4.0 metadata.</description>\n"
        "  <language>ja</language>\n"
        f"  <lastBuildDate>{last_build}</lastBuildDate>\n"
        "  <copyright>(C) 2026 Bookyou株式会社</copyright>\n"
        '  <dc:rights>CC-BY-4.0</dc:rights>\n'
        + "\n".join(items)
        + "\n</channel>\n</rss>\n"
    )
    return Response(
        content=rss,
        media_type="application/rss+xml; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# 5. §52 audit log rollup  /  GET /v1/audit/section52
# ---------------------------------------------------------------------------

@router.get("/trust/section52", tags=["trust", "audit"])
async def audit_section52(
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> JSONResponse:
    """Per-day §52 violation count rollup.

    Reads `audit_log_section52` (mig 101). The cron sampler populates this
    table; here we return the aggregate so the public /compliance page can
    render trend-line + verdict.
    """
    cutoff = (_utcnow() - _dt.timedelta(days=days)).isoformat()
    conn = _open_autonomath_ro()
    try:
        try:
            rows = conn.execute(
                "SELECT substr(sampled_at, 1, 10) AS day, "
                "       COUNT(*) AS sampled, "
                "       SUM(violation) AS violations, "
                "       SUM(CASE WHEN disclaimer_present = 0 THEN 1 ELSE 0 END) AS missing_disclaimer "
                "FROM audit_log_section52 "
                "WHERE sampled_at >= ? "
                "GROUP BY day ORDER BY day DESC",
                (cutoff,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                rows = []
            else:
                raise
    finally:
        conn.close()

    days_out = [
        {
            "day": r["day"],
            "sampled": int(r["sampled"] or 0),
            "violations": int(r["violations"] or 0),
            "missing_disclaimer": int(r["missing_disclaimer"] or 0),
        }
        for r in rows
    ]
    total_v = sum(d["violations"] for d in days_out)
    total_s = sum(d["sampled"] for d in days_out)

    return JSONResponse(
        content={
            "window_days": days,
            "days": days_out,
            "summary": {
                "samples": total_s,
                "violations": total_v,
                "violation_rate": (
                    round(total_v / total_s, 4) if total_s > 0 else 0.0
                ),
            },
            "_meta": {
                "fence": "§52 disclaimer envelope; details in CONSTITUTION 13.2 + docs/_internal/section52_audit.md",
                "creator": "Bookyou株式会社 (T8010001213708)",
            },
        }
    )


# ---------------------------------------------------------------------------
# 6. Cross-source agreement  /  GET /v1/cross_source/{entity_id}
# ---------------------------------------------------------------------------

@router.get("/cross_source/{entity_id}", tags=["trust", "cross_source"])
async def cross_source_check(
    entity_id: Annotated[str, PathParam(min_length=1, max_length=200)],
    field: Annotated[str | None, Query(min_length=1, max_length=120)] = None,
) -> JSONResponse:
    """Verify how many distinct sources confirm an entity (or one field).

    Wraps services.cross_source.compute_cross_source_agreement so callers
    get a single endpoint while the math lives in a unit-testable module.
    """
    conn = _open_autonomath_ro()
    try:
        verdict = compute_cross_source_agreement(conn, entity_id, field)
    finally:
        conn.close()
    if verdict is None:
        raise HTTPException(status_code=404, detail="entity not found")
    return JSONResponse(content=verdict)


# ---------------------------------------------------------------------------
# 7. Stale-data rollup  /  GET /v1/staleness
# ---------------------------------------------------------------------------

@router.get("/staleness", tags=["trust", "staleness"])
async def staleness_summary(
    threshold_days: Annotated[int, Query(ge=1, le=365)] = _STALE_DAYS,
) -> JSONResponse:
    """Per-dataset count of rows fresher / staler than threshold_days."""
    cutoff = (_utcnow() - _dt.timedelta(days=threshold_days)).date().isoformat()
    datasets: list[dict[str, Any]] = []

    # Tables + fetched_at column. Mirrors transparency.py registry but the
    # column names differ (e.g. programs uses source_fetched_at).
    targets: tuple[tuple[str, str, str], ...] = (
        ("programs", "jpi_programs", "source_fetched_at"),
        ("laws", "jpi_laws", "fetched_at"),
        ("tax_rulesets", "jpi_tax_rulesets", "fetched_at"),
        ("court_decisions", "jpi_court_decisions", "fetched_at"),
        ("bids", "jpi_bids", "fetched_at"),
        ("invoice_registrants", "jpi_invoice_registrants", "fetched_at"),
        ("loan_programs", "jpi_loan_programs", "fetched_at"),
        ("case_studies", "jpi_case_studies", "fetched_at"),
        ("enforcement_cases", "jpi_enforcement_cases", "fetched_at"),
    )
    conn = _open_autonomath_ro()
    try:
        cutoff_iso = f"{cutoff}T00:00:00"
        for name, table, col in targets:
            try:
                row = conn.execute(
                    f"SELECT COUNT(*) AS total, "
                    f"       SUM(CASE WHEN {col} < ? OR {col} IS NULL THEN 1 ELSE 0 END) AS stale "
                    f"FROM {table}",
                    (cutoff_iso,),
                ).fetchone()
            except sqlite3.OperationalError:
                # Table absent in this fixture — return placeholders so the
                # response shape stays stable across deployments.
                datasets.append({
                    "name": name,
                    "total": 0,
                    "stale": 0,
                    "stale_pct": 0.0,
                    "_note": f"table {table} absent",
                })
                continue
            total = int(row["total"] or 0)
            stale = int(row["stale"] or 0)
            datasets.append({
                "name": name,
                "total": total,
                "stale": stale,
                "stale_pct": round(100.0 * stale / total, 2) if total > 0 else 0.0,
            })
    finally:
        conn.close()

    return JSONResponse(
        content={
            "threshold_days": threshold_days,
            "datasets": datasets,
            "generated_at": _utc_iso(),
        }
    )


__all__ = ["router"]
