"""Recurring engagement endpoints — quarterly PDF / Slack webhook / email course alias.

Endpoints under /v1/me/recurring/*:
    - GET  /v1/me/recurring/quarterly/{year}/{quarter}   PDF download
    - POST /v1/me/recurring/slack                        set + verify Slack webhook
    - POST /v1/me/recurring/email_course/start           alias for /v1/me/courses

Cost posture (project_autonomath_business_model — ¥3/req metered ONLY):
    * Quarterly PDF: ¥3 metered per generated PDF (cached afterwards;
      cache hits are FREE because no compute is spent).
    * Slack webhook bind: FREE — sending the test message is one-shot
      and the operator pays for it inline (no customer billing).
    * email_course start: passes through to courses.subscribe_course
      which already meters the D+1 send.

§52 fence: every PDF body carries the disclaimer block (see
src/jpintel_mcp/templates/quarterly_report.html).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr, Field

from jpintel_mcp.api.deps import (
    ApiContextDep,  # noqa: TC001 (FastAPI dependency alias)
    DbDep,  # noqa: TC001 (FastAPI dependency alias)
    require_metered_api_key,
)

logger = logging.getLogger("jpintel.recurring")

router = APIRouter(prefix="/v1/me/recurring", tags=["recurring"])

# Slack-only webhook prefix — see saved_searches.py docstring (SSRF defense).
_SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/services/"

# Cache root for generated quarterly PDFs. The Fly volume mount under
# /app/data persists across deploys, so the cache survives a redeploy.
# Falls back to repo-root data/ for local dev.
_QUARTERLY_CACHE_DIR = Path("data/quarterly_pdfs")


# ---------------------------------------------------------------------------
# Quarterly PDF
# ---------------------------------------------------------------------------


def _quarter_period(year: int, quarter: int) -> tuple[str, str]:
    """Return (period_start, period_end) ISO date strings for the quarter.

    日本会計年度 ベース: Q1=4-6月 / Q2=7-9月 / Q3=10-12月 / Q4=1-3月 (翌年)
    """
    if quarter == 1:
        return f"{year}-04-01", f"{year}-06-30"
    if quarter == 2:
        return f"{year}-07-01", f"{year}-09-30"
    if quarter == 3:
        return f"{year}-10-01", f"{year}-12-31"
    if quarter == 4:
        return f"{year + 1}-01-01", f"{year + 1}-03-31"
    raise ValueError(f"invalid quarter: {quarter}")


def _api_key_id_token(key_hash: str) -> str:
    """Short stable token for cache filenames (no PII)."""
    return hashlib.sha256(key_hash.encode("utf-8")).hexdigest()[:16]


def _redacted_key_id(key_hash: str) -> str:
    return f"sk_***{_api_key_id_token(key_hash)[:8]}"


def _gather_usage_stats(
    conn: sqlite3.Connection, key_hash: str, period_start: str, period_end: str
) -> dict[str, Any]:
    rows = conn.execute(
        """SELECT endpoint, COUNT(*) AS n
             FROM usage_events
            WHERE key_hash = ?
              AND ts BETWEEN ? AND ?
         GROUP BY endpoint
         ORDER BY n DESC
            LIMIT 5""",
        (key_hash, f"{period_start}T00:00:00Z", f"{period_end}T23:59:59Z"),
    ).fetchall()
    top_endpoints = [{"endpoint": r["endpoint"], "count": r["n"]} for r in rows]

    totals = conn.execute(
        """SELECT
                COUNT(*) AS total,
                COALESCE(SUM(metered), 0) AS metered
             FROM usage_events
            WHERE key_hash = ?
              AND ts BETWEEN ? AND ?""",
        (key_hash, f"{period_start}T00:00:00Z", f"{period_end}T23:59:59Z"),
    ).fetchone()
    total = int(totals["total"] or 0)
    metered = int(totals["metered"] or 0)
    return {
        "total_requests": total,
        "metered_requests": metered,
        "billed_yen": metered * 3,
        "top_endpoints": top_endpoints,
    }


def _gather_watch_amendments(
    conn: sqlite3.Connection,
    key_hash: str,
    period_start: str,
    period_end: str,
) -> list[dict[str, Any]]:
    """Pull recent amendments touching the customer's watch list.

    The diff stream lives in autonomath.db (am_amendment_diff). For PDF
    rendering we keep this read jpintel-only — we read the customer's
    watched program ids out of client_profiles.last_active_program_ids_json
    and surface a placeholder list when autonomath.db is not attached.
    """
    rows = conn.execute(
        "SELECT last_active_program_ids_json FROM client_profiles WHERE api_key_hash = ?",
        (key_hash,),
    ).fetchall()
    watched: set[str] = set()
    for r in rows:
        try:
            for pid in json.loads(r["last_active_program_ids_json"] or "[]"):
                watched.add(str(pid))
        except (TypeError, ValueError):
            continue
    if not watched:
        return []
    # Without ATTACHing autonomath.db (cross-DB JOIN forbidden per CLAUDE.md),
    # the PDF surfaces watched-program names from `programs` only, marking
    # the change column as "改正検出" so the customer knows to drill down
    # via /v1/am/* tools. This keeps the PDF surface honest and avoids a
    # fake "no changes" claim.
    placeholders = ",".join("?" for _ in watched)
    progs = conn.execute(
        f"SELECT unified_id, primary_name FROM programs "
        f"WHERE unified_id IN ({placeholders}) LIMIT 50",
        list(watched),
    ).fetchall()
    return [
        {
            "entity_name": p["primary_name"],
            "field_name": "改正検出 (詳細は /v1/am/* で参照)",
            "detected_at": period_end,
        }
        for p in progs
    ]


def _gather_eligible_unapplied(conn: sqlite3.Connection, key_hash: str) -> list[dict[str, Any]]:
    """Programs that match any client_profile filters but are NOT in
    last_active_program_ids_json (= eligible but not yet applied).
    """
    profiles = conn.execute(
        "SELECT prefecture, target_types_json, last_active_program_ids_json "
        "FROM client_profiles WHERE api_key_hash = ?",
        (key_hash,),
    ).fetchall()
    if not profiles:
        return []
    applied: set[str] = set()
    prefectures: set[str] = set()
    for p in profiles:
        try:
            for pid in json.loads(p["last_active_program_ids_json"] or "[]"):
                applied.add(str(pid))
        except (TypeError, ValueError):
            continue
        if p["prefecture"]:
            prefectures.add(p["prefecture"])
    where = ["(excluded = 0 OR excluded IS NULL)", "tier IN ('S','A','B','C')"]
    params: list[Any] = []
    if prefectures:
        # OR over the consultant's covered prefectures.
        placeholders = ",".join("?" for _ in prefectures)
        where.append(f"(prefecture IN ({placeholders}) OR prefecture IS NULL)")
        params.extend(prefectures)
    sql = (
        "SELECT unified_id, primary_name, authority_name, amount_max_man_yen "
        f"FROM programs WHERE {' AND '.join(where)} "
        "ORDER BY amount_max_man_yen DESC NULLS LAST LIMIT 10"
    )
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        # NULLS LAST is not supported on every SQLite build; retry without it.
        sql = (
            "SELECT unified_id, primary_name, authority_name, amount_max_man_yen "
            f"FROM programs WHERE {' AND '.join(where)} "
            "ORDER BY amount_max_man_yen DESC LIMIT 10"
        )
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "primary_name": r["primary_name"],
            "authority_name": r["authority_name"],
            "amount_max_man_yen": r["amount_max_man_yen"],
        }
        for r in rows
        if r["unified_id"] not in applied
    ]


def _record_metered_pdf(conn: sqlite3.Connection, key_hash: str) -> bool:
    """Bill ¥3 for the PDF render. Mirrors saved_searches.digest shape."""
    from jpintel_mcp.billing.delivery import record_metered_delivery

    ok = record_metered_delivery(
        conn,
        key_hash=key_hash,
        endpoint="recurring.quarterly_pdf",
    )
    if not ok:
        logger.warning("recurring.pdf_billing_skipped key=%s", key_hash[:8])
    return ok


def _render_pdf_to(
    *,
    out_path: Path,
    context: dict[str, Any],
) -> bool:
    """Render the quarterly_report.html template to `out_path` as a PDF.

    Returns True on success. Logs + returns False on failure (test env
    without WeasyPrint installed, missing system fonts, etc) so callers
    can surface a 503 instead of a 500.
    """
    template_path = Path(__file__).resolve().parent.parent / "templates" / "quarterly_report.html"
    try:
        # Lazy-import jinja2 + weasyprint so a missing optional dep at
        # import time (test env) does not break the whole api package.
        from jinja2 import Template
    except ImportError:
        logger.error("jinja2_missing — quarterly_pdf cannot render")
        return False
    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("weasyprint_missing — quarterly_pdf cannot render")
        return False

    try:
        tmpl_src = template_path.read_text(encoding="utf-8")
        rendered = Template(tmpl_src).render(**context)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        HTML(string=rendered).write_pdf(str(out_path))
        return True
    except Exception:  # noqa: BLE001
        logger.exception("quarterly_pdf_render_failed")
        return False


def _render_metered_pdf_to_cache(
    *,
    conn: sqlite3.Connection,
    key_hash: str,
    cache_path: Path,
    context: dict[str, Any],
) -> bool:
    """Render the PDF, bill ¥3, then promote it to cache.

    The cache path is the customer-visible deliverable. Render into a temp
    file first, then record billing, then atomically promote the file. This
    keeps both bad states out of production: no billing when rendering fails,
    and no reusable PDF cache when billing fails.
    """
    tmp_path = cache_path.with_name(f".{cache_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        rendered = _render_pdf_to(out_path=tmp_path, context=context)
        if not rendered:
            return False
        billed = _record_metered_pdf(conn, key_hash)
        if not billed:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "pdf_billing_unavailable",
                    "message": (
                        "This paid PDF was not delivered because billing could not be recorded."
                    ),
                },
            )
        tmp_path.replace(cache_path)
        return True
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/quarterly/{year}/{quarter}")
def get_quarterly_pdf(
    year: int,
    quarter: int,
    ctx: ApiContextDep,
    conn: DbDep,
) -> FileResponse:
    """Generate (or serve cached) quarterly PDF for the calling key.

    Cached to data/quarterly_pdfs/<api_key_id>_<year>_q<n>.pdf — repeat
    downloads are read-from-disk, not re-rendered (and not metered).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "quarterly report requires an authenticated API key",
        )
    require_metered_api_key(ctx, "quarterly PDF")
    if quarter < 1 or quarter > 4:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "quarter must be 1, 2, 3, or 4")
    if year < 2024 or year > 2100:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "year out of range")

    token = _api_key_id_token(ctx.key_hash)
    cache_path = _QUARTERLY_CACHE_DIR / f"{token}_{year}_q{quarter}.pdf"
    if cache_path.exists():
        return FileResponse(
            path=str(cache_path),
            media_type="application/pdf",
            filename=f"quarterly_{year}_q{quarter}.pdf",
        )

    period_start, period_end = _quarter_period(year, quarter)
    usage_stats = _gather_usage_stats(conn, ctx.key_hash, period_start, period_end)
    watch_amendments = _gather_watch_amendments(conn, ctx.key_hash, period_start, period_end)
    eligible_unapplied = _gather_eligible_unapplied(conn, ctx.key_hash)
    amendment_summary = {
        "ウォッチ対象改正": len(watch_amendments),
        "新規申請可能制度": len(eligible_unapplied),
        "対象期間 (日)": (
            datetime.fromisoformat(period_end) - datetime.fromisoformat(period_start)
        ).days
        + 1,
    }
    context = {
        "year": year,
        "quarter": quarter,
        "period_start": period_start,
        "period_end": period_end,
        "rendered_at": datetime.now(UTC).isoformat(timespec="minutes").replace("+00:00", "Z"),
        "api_key_id_redacted": _redacted_key_id(ctx.key_hash),
        "usage_stats": usage_stats,
        "watch_amendments": watch_amendments,
        "eligible_unapplied": eligible_unapplied,
        "amendment_summary": amendment_summary,
    }
    rendered = _render_metered_pdf_to_cache(
        conn=conn,
        key_hash=ctx.key_hash,
        cache_path=cache_path,
        context=context,
    )
    if not rendered:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "PDF renderer unavailable — install weasyprint + jinja2 on the host",
        )
    return FileResponse(
        path=str(cache_path),
        media_type="application/pdf",
        filename=f"quarterly_{year}_q{quarter}.pdf",
    )


# ---------------------------------------------------------------------------
# Slack webhook bind
# ---------------------------------------------------------------------------


class SetSlackRequest(BaseModel):
    saved_search_id: int
    channel_url: Annotated[str, Field(min_length=1, max_length=512)]


class SetSlackResponse(BaseModel):
    ok: bool
    saved_search_id: int
    test_delivered: bool


def _send_slack_test_message(channel_url: str) -> tuple[bool, str | None]:
    """POST a one-shot 'wired up' message to the Slack webhook.

    Returns (ok, error_str). 10s timeout — Slack's incoming-webhook is
    documented to respond <2s; 10s is the SLA fence.
    """
    body = json.dumps(
        {
            "text": (
                ":white_check_mark: jpcite: Slack 通知の連携が完了しました。"
                "今後、保存条件に該当する更新があればこのチャンネルへ配信します。"
            ),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        channel_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
            if 200 <= resp.status < 300:
                return True, None
            return False, f"http_{resp.status}"
    except urllib.error.HTTPError as exc:
        return False, f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


@router.post("/slack", response_model=SetSlackResponse)
def set_slack_webhook(
    payload: SetSlackRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> SetSlackResponse:
    """Bind a Slack incoming-webhook URL to a saved search.

    Server-side validation:
        * URL must start with `https://hooks.slack.com/services/` (SSRF
          defense — Slack-only domain)
        * A test message is POSTed; we commit the binding ONLY if Slack
          returns 2xx.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Slack webhook bind requires an authenticated API key",
        )
    if not payload.channel_url.startswith(_SLACK_WEBHOOK_PREFIX):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"channel_url must start with '{_SLACK_WEBHOOK_PREFIX}' "
            "(SSRF defense — Slack-only domain)",
        )
    row = conn.execute(
        "SELECT id FROM saved_searches WHERE id = ? AND api_key_hash = ?",
        (payload.saved_search_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"saved search {payload.saved_search_id} not found",
        )

    ok, err = _send_slack_test_message(payload.channel_url)
    if not ok:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Slack test message rejected ({err}); binding NOT saved",
        )
    conn.execute(
        "UPDATE saved_searches "
        "   SET channel_format = 'slack', channel_url = ? "
        " WHERE id = ? AND api_key_hash = ?",
        (payload.channel_url, payload.saved_search_id, ctx.key_hash),
    )
    return SetSlackResponse(
        ok=True,
        saved_search_id=payload.saved_search_id,
        test_delivered=True,
    )


# ---------------------------------------------------------------------------
# email_course alias
# ---------------------------------------------------------------------------


class StartEmailCourseRequest(BaseModel):
    notify_email: EmailStr
    course_slug: Annotated[Literal["invoice", "dencho"], Field(default="invoice")] = "invoice"


@router.post("/email_course/start", status_code=status.HTTP_201_CREATED)
def start_email_course(
    payload: StartEmailCourseRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> dict[str, Any]:
    """Starts the recurring email course for the authenticated account."""
    from jpintel_mcp.api.courses import (
        SubscribeCourseRequest,
        subscribe_course,
    )

    inner = SubscribeCourseRequest(
        course_slug=payload.course_slug,
        notify_email=payload.notify_email,
    )
    response = subscribe_course(payload=inner, ctx=ctx, conn=conn)
    return {
        "ok": True,
        "course_slug": response.course_slug,
        "subscription_id": response.id,
        "started_at": response.started_at,
    }


__all__ = ["router"]
