"""M5 — Email course series subscriptions (recurring engagement).

Endpoints under /v1/me/courses:
    - POST   /v1/me/courses                          subscribe to a course
    - DELETE /v1/me/courses/{course_slug}            cancel an active subscription
    - GET    /v1/me/courses                          (small convenience for the dashboard)

Two pre-recorded courses live behind this surface as of W3 of the
1000h plan:

    * ``invoice``  — 「5日でわかるインボイス」 (5-day series, D+0..D+4)
    * ``dencho``   — 「7日でマスター電帳法」 (7-day series, D+0..D+6)

Each daily email is a pre-recorded markdown body (templates under
``email/templates/course_invoice_d{1..5}.{html,txt}`` and
``course_dencho_d{1..7}.{html,txt}``); §52 fence sits in EVERY footer
("税理士法 §52 / 弁護士法 §72 該当の業務はおこないません — 教育用").

Cost posture (project_autonomath_business_model):
    * Subscribe (POST) and cancel (DELETE) are FREE — they touch the
      customer's own row.
    * Each daily email delivery is ¥3 metered through ``report_usage_async``,
      same posture as saved-search digests (see
      scripts/cron/run_saved_searches.py).
    * D+0 fires immediately on subscribe (synchronous send, billed on
      success). D+1..D+N enqueue via the cron
      (scripts/cron/course_dispatcher.py).
    * 0-match runs do NOT bill — but courses always have content per day,
      so the only skip path is unsubscribe / hard bounce / suppression.

Course completion → upsell:
    When the cron flips status='complete', it emits an enqueue hook into
    ``email_schedule`` so the customer receives a polite "ここまでで学んだ
    内容を保存条件に変えて自動配信しませんか?" pointer to M1 saved_search.
    That upsell is ¥3-metered like any other email send.

§52 / educational only:
    Every course email body must NOT carry advisory language ("〇〇 する
    こと"). The template wording stays educational ("法令の本文は…と定めて
    います"). Tax-advice phrasing is a 税理士法 §52 violation; legal
    advice is 弁護士法 §72. We mention this in the docstring so the
    template editor sees the constraint at copy time.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from jpintel_mcp.api.deps import (
    ApiContextDep,  # noqa: TC001 - FastAPI resolves dependency aliases at runtime.
    DbDep,  # noqa: TC001 - FastAPI resolves dependency aliases at runtime.
)

router = APIRouter(prefix="/v1/me/courses", tags=["courses"])

logger = logging.getLogger("jpintel.courses")


# ---------------------------------------------------------------------------
# Course catalog (pinned metadata, no DB round-trip on subscribe)
# ---------------------------------------------------------------------------

# {slug: {length_days, title, template_alias_prefix}}
# template_alias resolves to f"{prefix}_d{N}" for day N in [1..length_days].
COURSE_CATALOG: dict[str, dict[str, Any]] = {
    "invoice": {
        "length_days": 5,
        "title": "5日でわかるインボイス",
        "template_prefix": "course_invoice",
    },
    "dencho": {
        "length_days": 7,
        "title": "7日でマスター電帳法",
        "template_prefix": "course_dencho",
    },
}

# Hard cap on simultaneous active courses per key — bounds cron fan-out.
MAX_ACTIVE_COURSES_PER_KEY = 5


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SubscribeCourseRequest(BaseModel):
    course_slug: Annotated[Literal["invoice", "dencho"], Field()]
    notify_email: EmailStr


class CourseSubscriptionResponse(BaseModel):
    id: int
    course_slug: str
    title: str
    length_days: int
    started_at: str
    current_day: int
    status: str
    notify_email: str


class DeleteCourseResponse(BaseModel):
    ok: bool
    course_slug: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: dict[str, Any]) -> CourseSubscriptionResponse:
    meta = COURSE_CATALOG.get(row["course_slug"], {})
    return CourseSubscriptionResponse(
        id=row["id"],
        course_slug=row["course_slug"],
        title=str(meta.get("title") or row["course_slug"]),
        length_days=int(meta.get("length_days") or 0),
        started_at=row["started_at"],
        current_day=int(row["current_day"] or 0),
        status=row["status"],
        notify_email=row["email"],
    )


def _send_day_n_now(
    *,
    to: str,
    course_slug: str,
    day_n: int,
) -> dict[str, Any]:
    """Fire the D+N course email synchronously. Returns Postmark response.

    Tolerant of missing email module / test mode — the helper catches
    transport errors and returns a dict so callers never re-raise.
    """
    try:
        from jpintel_mcp.email import get_client
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("courses.email_unavailable err=%s", exc)
        return {"skipped": True, "reason": "email_module_unavailable"}

    template_alias = _course_template_alias(course_slug, day_n)
    if template_alias is None:
        return {"skipped": True, "reason": "unknown_course_or_day"}

    meta = COURSE_CATALOG.get(course_slug) or {}
    title = str(meta.get("title") or course_slug)
    length = int(meta.get("length_days") or 0)

    try:
        client = get_client()
        return client._send(
            to=to,
            template_alias=template_alias,
            template_model={
                "course_slug": course_slug,
                "course_title": title,
                "day": day_n,
                "total_days": length,
                "manage_url": "https://jpcite.com/dashboard.html#courses",
                "disclaimer": (
                    "本メールは公開情報に基づく教育コンテンツです。"
                    "税理士法 §52 / 弁護士法 §72 該当の助言・代行はおこないません。"
                ),
            },
            tag=f"course-{course_slug}-d{day_n}",
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("courses.send_failed err=%s", exc)
        return {"skipped": True, "reason": "send_failed", "error": str(exc)}


def _course_template_alias(course_slug: str, day_n: int) -> str | None:
    meta = COURSE_CATALOG.get(course_slug)
    if not meta:
        return None
    length = int(meta.get("length_days") or 0)
    if day_n < 1 or day_n > length:
        return None
    prefix = str(meta.get("template_prefix") or "")
    if not prefix:
        return None
    return f"{prefix}_d{day_n}"


def _record_metered_delivery(
    *,
    conn: Any,
    key_hash: str,
    endpoint: str,
) -> None:
    """Mirror the saved-search delivery metering shape exactly so dashboards
    surface course / digest / report deliveries on the same axis.
    """
    from jpintel_mcp.billing.delivery import record_metered_delivery

    ok = record_metered_delivery(conn, key_hash=key_hash, endpoint=endpoint)
    if not ok:
        logger.warning("courses.delivery_billing_skipped endpoint=%s", endpoint)


def _raise_delivery_billing_cap_failed() -> None:
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "billing_cap_final_check_failed",
            "message": (
                "This paid response was not delivered because the "
                "final billing-cap check rejected the metered charge."
            ),
        },
    )


def _preflight_metered_delivery(
    *,
    conn: Any,
    key_hash: str,
    metered: bool,
    endpoint: str,
) -> None:
    """Run the strict delivery cap check before irreversible course effects.

    This intentionally closes any SQLite transaction before returning: the
    caller may send email next, and must not hold the writer lock while doing
    external I/O. The usage row is still written after a successful send; this
    preflight only rejects obviously unbillable deliveries before email.
    """
    from jpintel_mcp.api.deps import _metered_cap_final_check

    if not metered:
        logger.warning(
            "courses.delivery_billing_unavailable endpoint=%s",
            endpoint,
        )
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "billing_required",
                "message": "Course delivery requires a paid metered API key.",
            },
        )

    txn_started = False
    try:
        allowed, txn_started = _metered_cap_final_check(
            conn,
            key_hash=key_hash,
            metered=metered,
            status_code=200,
            quantity=1,
        )
        if txn_started:
            conn.execute("COMMIT")
            txn_started = False
    except Exception:
        if txn_started and conn.in_transaction:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
        raise
    if not allowed:
        logger.warning(
            "courses.delivery_billing_preflight_failed endpoint=%s",
            endpoint,
        )
        _raise_delivery_billing_cap_failed()


def _mark_delivery_sent_without_usage_row(
    *,
    conn: Any,
    sub_id: int,
    sent_at: str,
    endpoint: str,
) -> None:
    """Advance the subscription after a sent email even if usage persistence failed.

    At this point the external send already happened. Advancing current_day
    prevents client retries or cron from sending D+1 repeatedly while the
    caller still receives a fail-closed response for the missing audit row.
    """
    try:
        conn.execute(
            "UPDATE course_subscriptions SET current_day = 1, last_sent_at = ? WHERE id = ?",
            (sent_at, sub_id),
        )
    except Exception:
        logger.exception(
            "courses.delivery_sent_marker_failed endpoint=%s sub_id=%s",
            endpoint,
            sub_id,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=CourseSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def subscribe_course(
    payload: SubscribeCourseRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> CourseSubscriptionResponse:
    """Subscribe the calling key to a pre-recorded course.

    Side effect: fires D+1 email synchronously (immediate first lesson,
    metered ¥3 on success). The cron picks up D+2..D+N from the next
    sweep. We treat D+1 as "day 1 of the course" (current_day=1 after
    insert), not D+0, to keep the customer-facing language clean.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "course subscription requires an authenticated API key",
        )

    if payload.course_slug not in COURSE_CATALOG:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown course '{payload.course_slug}'; allowed: {sorted(COURSE_CATALOG)}",
        )

    # Cap on simultaneous active courses per key.
    (active_count,) = conn.execute(
        "SELECT COUNT(*) FROM course_subscriptions WHERE api_key_id = ? AND status = 'active'",
        (ctx.key_hash,),
    ).fetchone()

    if active_count >= MAX_ACTIVE_COURSES_PER_KEY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"active course cap reached ({MAX_ACTIVE_COURSES_PER_KEY})",
        )

    # Block duplicate active subscription to the same course.
    existing = conn.execute(
        "SELECT id FROM course_subscriptions "
        "WHERE api_key_id = ? AND course_slug = ? AND status = 'active'",
        (ctx.key_hash, payload.course_slug),
    ).fetchone()
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"already subscribed to course '{payload.course_slug}'",
        )

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    _preflight_metered_delivery(
        conn=conn,
        key_hash=ctx.key_hash,
        metered=ctx.metered,
        endpoint="courses.delivery",
    )

    # DEEP-46 Pattern A: insert subscription row at current_day=0, then
    # charge → email send → advance current_day=1. The previous order was
    # email → charge → advance; that left a partial-charge / partial-email
    # window if either side blew up. With Pattern A the only inconsistency
    # window is "charge succeeded, email failed" — handled below by leaving
    # current_day=0 so the cron retries the SAME D+1 next sweep.
    cur = conn.execute(
        """INSERT INTO course_subscriptions(
                api_key_id, email, course_slug, started_at,
                current_day, status, last_sent_at, created_at
           ) VALUES (?,?,?,?,?,?,?,?)""",
        (
            ctx.key_hash,
            payload.notify_email,
            payload.course_slug,
            now,
            0,  # bumped to 1 below ONLY after both charge + email succeed
            "active",
            None,
            now,
        ),
    )
    sub_id = cur.lastrowid
    if sub_id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "failed to create course subscription",
        )

    # Step 1 (Pattern A): charge ¥3 BEFORE the external email send. If the
    # cap final-check rejects, the email is never sent and current_day stays
    # at 0 so the cron will not race forward. The charge row is the single
    # source of truth for "did this customer get billed this day".
    charge_txn_started = False
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
            charge_txn_started = True
        _record_metered_delivery(
            conn=conn,
            key_hash=ctx.key_hash,
            endpoint="courses.delivery",
        )
        if charge_txn_started:
            conn.execute("COMMIT")
            charge_txn_started = False
    except Exception as exc:
        if conn.in_transaction:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
        with contextlib.suppress(Exception):
            conn.execute("DELETE FROM course_subscriptions WHERE id = ?", (sub_id,))
            conn.commit()
        logger.warning(
            "courses.delivery_charge_failed_pre_send endpoint=%s sub_id=%s",
            "courses.delivery",
            sub_id,
            exc_info=True,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "billing_cap_final_check_failed",
                "message": (
                    "This paid course was not delivered because the "
                    "billing charge could not be recorded before send."
                ),
            },
        ) from exc

    # Step 2 (Pattern A): synchronous D+1 send. Charge already succeeded; if
    # the email transport fails, current_day stays at 0 so the cron retries
    # the same day on the next sweep. The customer is NOT double-charged
    # because the cron's idempotency_cache key (course × day × YYYYMMDD)
    # dedups the second attempt.
    outcome = _send_day_n_now(
        to=payload.notify_email,
        course_slug=payload.course_slug,
        day_n=1,
    )
    sent_ok = "error" not in outcome and outcome.get("reason") not in {
        "unknown_course_or_day",
        "send_failed",
    }

    # Step 3 (Pattern A): advance current_day=1 ONLY after a successful send.
    if sent_ok:
        try:
            conn.execute(
                "UPDATE course_subscriptions SET current_day = 1, last_sent_at = ? WHERE id = ?",
                (now, sub_id),
            )
        except Exception:
            logger.exception(
                "courses.subscription_advance_failed sub_id=%s",
                sub_id,
            )

    row = conn.execute(
        "SELECT id, api_key_id, email, course_slug, started_at, current_day, "
        "       status, last_sent_at, completed_at, created_at "
        "FROM course_subscriptions WHERE id = ?",
        (sub_id,),
    ).fetchone()
    return _row_to_response(dict(row))


@router.get(
    "",
    response_model=list[CourseSubscriptionResponse],
)
def list_courses(
    ctx: ApiContextDep,
    conn: DbDep,
) -> list[CourseSubscriptionResponse]:
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "course list requires an authenticated API key",
        )
    rows = conn.execute(
        """SELECT id, api_key_id, email, course_slug, started_at, current_day,
                  status, last_sent_at, completed_at, created_at
             FROM course_subscriptions
            WHERE api_key_id = ?
         ORDER BY id ASC""",
        (ctx.key_hash,),
    ).fetchall()
    return [_row_to_response(dict(r)) for r in rows]


@router.delete(
    "/{course_slug}",
    response_model=DeleteCourseResponse,
)
def cancel_course(
    course_slug: str,
    ctx: ApiContextDep,
    conn: DbDep,
) -> DeleteCourseResponse:
    """Cancel an active course. Soft-cancel (status='cancelled') so the
    history row stays for audit and the cron stops picking it up.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "course cancel requires an authenticated API key",
        )
    if course_slug not in COURSE_CATALOG:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "course not found")
    row = conn.execute(
        "SELECT id FROM course_subscriptions "
        "WHERE api_key_id = ? AND course_slug = ? AND status = 'active'",
        (ctx.key_hash, course_slug),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "active course subscription not found")
    conn.execute(
        "UPDATE course_subscriptions SET status = 'cancelled' WHERE id = ?",
        (row["id"],),
    )
    return DeleteCourseResponse(ok=True, course_slug=course_slug)


__all__ = [
    "COURSE_CATALOG",
    "MAX_ACTIVE_COURSES_PER_KEY",
    "router",
]
