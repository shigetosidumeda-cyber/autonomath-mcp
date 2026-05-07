"""顧問先別 client_tag 利用明細 — per-顧問先 spend breakdown for 税理士事務所.

Surfaces a single endpoint:

    GET /v1/billing/client_tag_breakdown
        ?period_start=YYYY-MM-DD
        ?period_end=YYYY-MM-DD
        ?format=json|csv

Why this exists:
    Today the monthly Stripe invoice is one consolidated line item. A 税理士
    using AutonoMath as a back-end across N 顧問先 cannot allocate that ¥N
    onto each 顧問先 's invoice without a per-顧問先 breakdown of the
    underlying ¥3/req calls. `usage_events.client_tag` (migration 085) carries
    the X-Client-Tag header that lets the caller tag every request with the
    client of record; this endpoint aggregates those tags into an
    Excel-/Sheet-ingestible per-顧問先 sub-bill.

Pricing model (memory: project_autonomath_business_model):
    ¥3/req 税別 (= ¥3.30 税込, 消費税 10%). Tax is applied at the breakdown
    level here for parity with the Stripe-rendered 適格請求書 footer; the
    rounding rule is JST 切り捨て (Python int() truncation), NEVER round() —
    consumption-tax practice on per-line ¥-unit invoices is to round down.

Auth + scope:
    Requires an authenticated API key (X-API-Key or Bearer Authorization).
    Scope is the parent/child tree of the caller (migration 086) so a parent
    sees the full fan-out across child keys, and a child sees only itself.
    The breakdown query itself is not metered; charging a customer to inspect
    their own bill creates recursive accounting and makes reconciliation
    harder to explain.

Hot path:
    SQLite GROUP BY on usage_events keyed by (key_hash, ts, client_tag).
    Migration 116 adds a covering composite index so the aggregate stays
    index-only. NULL client_tag is surfaced as the "untagged" bucket — never
    dropped, so the column-totals always reconcile against the consolidated
    Stripe invoice.

§28.1 + §28.7 of docs/_internal/value_maximization_plan_no_llm_api.md
locks this as a 60-day deliverable. Do not LLM-import here — the file is
on the production import graph and tests/test_no_llm_in_production.py
fails any anthropic / openai / google / claude_agent_sdk import.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    ApiContextDep,
    DbDep,
)

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger("jpintel.billing_breakdown")

router = APIRouter(prefix="/v1/billing", tags=["billing"])

# JST = UTC+9, no DST. Same fixed offset constant as anon_limit / usage. We
# defaults the period boundaries against the JST calendar month because that
# is the boundary 税理士 actually invoice against — using UTC would slice
# end-of-month requests into the wrong invoice for ~9 hours of every month.
_JST = timezone(timedelta(hours=9))

# ¥3/req 税別 (mirrors me._USAGE_UNIT_PRICE_YEN — duplicated, not imported,
# so a future split of billing into a separate package does not pull
# /v1/me into the import graph).
_UNIT_PRICE_YEN: int = 3

# Standard JP consumption-tax rate (軽減税率対象なし — digital service).
# Constant lives in code because the rate is locked across customers /
# regions / tier; a future hike is a code change, not a config change.
_TAX_RATE: float = 0.10

# Defensive ceiling on by_client_tag rows. An advisor with 1000+ 顧問先 is
# an outlier — beyond that we'd want a paginated endpoint. Picked at 1000
# so the worst-case single-shot response stays under ~200 KB JSON / 50 KB
# CSV (well within Cloudflare's per-response cap).
_MAX_BREAKDOWN_ROWS: int = 1000

# §52 / §72 disclaimer envelope. Mirrors the language used by the
# /v1/me/usage.csv export so dashboards rendering both surfaces speak in
# one voice. The numbers here are derived from internal usage_events rows
# (NOT a 税理士法 §52 advisory output) — but a 税理士 dropping the CSV
# straight into a 顧問先 invoice without operator review still inherits
# the same caveats, so we include the disclaimer for symmetry with the
# rest of the autonomath audit surface.
_DISCLAIMER = (
    "本明細は usage_events ログに基づくシステム的集計です。"
    "税理士法 §52 / §72 の助言ではありません。"
    "Stripe 適格請求書との突合せは月次 Stripe 請求書 (T8010001213708 — Bookyou株式会社) "
    "を一次資料として扱ってください。"
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PeriodBounds(BaseModel):
    start: str  # ISO date YYYY-MM-DD (JST calendar)
    end: str  # ISO date YYYY-MM-DD (JST calendar, inclusive)


class ClientTagRow(BaseModel):
    """Per-tag aggregate row in the breakdown response.

    `client_tag=None` is the "untagged" bucket (callers who didn't pass
    X-Client-Tag for that request). NEVER dropped — the row must surface
    so the sum of `yen_excl_tax` across all rows reconciles 1:1 with the
    Stripe invoice for the same period.
    """

    client_tag: str | None
    requests: int  # COUNT(*) — wall-clock # of API calls
    billable_units: int  # SUM(quantity) — Stripe metered units (per migr 085's batch path)
    yen_excl_tax: int  # billable_units * _UNIT_PRICE_YEN
    first_seen: str | None  # ISO date of first event in window (NULL when no rows)
    last_seen: str | None  # ISO date of last event in window


class ClientTagBreakdownResponse(BaseModel):
    account_id: str | None
    period: PeriodBounds
    total_requests: int
    total_billable_units: int
    total_billable_yen_excl_tax: int
    total_billable_yen_incl_tax: int
    tax_rate: float
    by_client_tag: list[ClientTagRow]
    untagged_requests: int
    untagged_yen: int
    capped_at_max_rows: bool
    _disclaimer: str


@dataclass(frozen=True)
class BreakdownAggregate:
    rows: list[ClientTagRow]
    capped: bool
    total_requests: int
    total_billable_units: int
    untagged_requests: int
    untagged_billable_units: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _today_jst() -> date:
    """Return today's date in JST (no time component)."""
    return datetime.now(_JST).date()


def _first_of_month_jst(d: date) -> date:
    """Return the first day of the JST calendar month that contains `d`."""
    return d.replace(day=1)


def _resolve_tree_key_hashes(conn: sqlite3.Connection, key_hash: str) -> list[str]:
    """Return the key hashes the caller is allowed to inspect.

    Parent keys see their children for consolidated billing. Child keys see
    only their own usage so sibling `client_tag` values do not leak across
    tenants.
    """
    row = conn.execute(
        "SELECT id, parent_key_id FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        return [key_hash]
    rk = row.keys() if hasattr(row, "keys") else []
    own_id = row["id"] if "id" in rk else None
    parent_key_id = row["parent_key_id"] if "parent_key_id" in rk else None
    if parent_key_id is not None or own_id is None:
        return [key_hash]
    rows = conn.execute(
        "SELECT key_hash FROM api_keys WHERE id = ? OR parent_key_id = ?",
        (own_id, own_id),
    ).fetchall()
    hashes = [r["key_hash"] if hasattr(r, "keys") else r[0] for r in rows]
    if key_hash not in hashes:
        hashes.append(key_hash)
    return hashes


def _consumption_tax_inclusive_yen(yen_excl_tax: int) -> int:
    """Apply 10% JP consumption tax with 切り捨て (truncation) at the ¥ unit.

    Standard JP practice on per-line ¥-unit invoices: drop the fractional
    yen via floor division, NOT bankers' rounding. Examples:

        1,000 -> 1,100   (no fractional)
           99 ->   108   (108.9 -> 108, NOT 109)
       69,000 -> 75,900  (no fractional)

    Implemented with int() on a float-multiplied value rather than
    integer arithmetic so the rounding direction is unambiguous in the
    presence of floating-point representation noise (a future ¥1 unit
    price change could otherwise expose 0.99999999... drift). For ¥3/req
    the float path is exact; this is forward-compat insurance.
    """
    return int(yen_excl_tax + yen_excl_tax * _TAX_RATE)


def _csv_escape(value: object) -> str:
    """Minimal RFC 4180 escape — quote if comma / quote / newline present.

    Mirrors `me._csv_escape`. Duplicated for the same reason as
    `_resolve_tree_key_hashes` above.
    """
    s = "" if value is None else str(value)
    if any(ch in s for ch in (",", '"', "\n", "\r")):
        s = '"' + s.replace('"', '""') + '"'
    return s


def _parse_iso_date(s: str | None, *, fallback: date) -> date:
    """Parse YYYY-MM-DD or fall back. Raises 422 on malformed input."""
    if s is None or s == "":
        return fallback
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_date",
                "message": "period_* must be ISO YYYY-MM-DD",
                "got": s,
            },
        ) from e


def _aggregate(
    conn: sqlite3.Connection,
    *,
    tree_hashes: list[str],
    period_start: date,
    period_end: date,
) -> BreakdownAggregate:
    """Run the GROUP BY aggregate over usage_events within [start, end].

    `period_end` is JST-calendar inclusive — the SQL bound is therefore
    converted to a half-open range `< (end+1) midnight JST` to capture
    the full day's events. Bounds are converted to UTC and compared via
    SQLite datetime() so UTC-stored usage rows and older offset-stamped
    rows land in the same customer-visible JST billing day.

    Returns (rows, capped_flag) where `capped_flag` is True when the
    advisor has more than _MAX_BREAKDOWN_ROWS distinct tags (signal for
    paginated-endpoint follow-up — out of scope for this task).
    """
    if not tree_hashes:
        return BreakdownAggregate([], False, 0, 0, 0, 0)
    placeholders = ",".join("?" * len(tree_hashes))
    # Bounds: [start_jst_midnight, end_jst_midnight + 1d) — half-open so a
    # request landing at 2026-04-30T23:59:59+09:00 is included in an
    # April invoice, but 2026-05-01T00:00:00+09:00 is NOT.
    start_iso = (
        datetime(period_start.year, period_start.month, period_start.day, tzinfo=_JST)
        .astimezone(UTC)
        .isoformat()
    )
    end_exclusive = period_end + timedelta(days=1)
    end_iso = (
        datetime(end_exclusive.year, end_exclusive.month, end_exclusive.day, tzinfo=_JST)
        .astimezone(UTC)
        .isoformat()
    )
    totals = conn.execute(
        f"""SELECT
                COUNT(*) AS req_count,
                COALESCE(SUM(COALESCE(quantity, 1)), 0) AS units,
                COALESCE(SUM(CASE WHEN client_tag IS NULL THEN 1 ELSE 0 END), 0)
                    AS untagged_requests,
                COALESCE(
                    SUM(CASE WHEN client_tag IS NULL THEN COALESCE(quantity, 1) ELSE 0 END),
                    0
                ) AS untagged_units
              FROM usage_events
             WHERE key_hash IN ({placeholders})
               AND COALESCE(metered, 0) = 1
               AND status >= 200
               AND status < 400
               AND datetime(ts) >= datetime(?)
               AND datetime(ts) <  datetime(?)""",  # noqa: S608 — placeholders only
        (*tree_hashes, start_iso, end_iso),
    ).fetchone()

    total_requests = int(totals["req_count"] or 0) if totals is not None else 0
    total_units = int(totals["units"] or 0) if totals is not None else 0
    untagged_requests = int(totals["untagged_requests"] or 0) if totals is not None else 0
    untagged_units = int(totals["untagged_units"] or 0) if totals is not None else 0

    # Single GROUP BY with NULL preserved (SQLite GROUP BY treats NULL as
    # its own bucket by default — verified against the migration 085
    # query in me._aggregate_by_client_tag). first_seen / last_seen are
    # min/max of the substring date, returned as YYYY-MM-DD for a stable
    # downstream Excel column.
    rows = conn.execute(
        f"""SELECT
                client_tag,
                COUNT(*) AS req_count,
                COALESCE(SUM(COALESCE(quantity, 1)), 0) AS units,
                MIN(date(datetime(ts), '+9 hours')) AS first_seen,
                MAX(date(datetime(ts), '+9 hours')) AS last_seen
              FROM usage_events
             WHERE key_hash IN ({placeholders})
               AND COALESCE(metered, 0) = 1
               AND status >= 200
               AND status < 400
               AND datetime(ts) >= datetime(?)
               AND datetime(ts) <  datetime(?)
          GROUP BY client_tag
          ORDER BY units DESC, req_count DESC, client_tag IS NULL, client_tag ASC
          LIMIT ?""",  # noqa: S608 — placeholders only, _MAX_BREAKDOWN_ROWS+1 literal
        (*tree_hashes, start_iso, end_iso, _MAX_BREAKDOWN_ROWS + 1),
    ).fetchall()

    capped = len(rows) > _MAX_BREAKDOWN_ROWS
    if capped:
        rows = rows[:_MAX_BREAKDOWN_ROWS]

    out: list[ClientTagRow] = []
    for r in rows:
        rk = r.keys() if hasattr(r, "keys") else []
        tag = r["client_tag"] if "client_tag" in rk else None
        req_count = int(r["req_count"]) if "req_count" in rk else 0
        units = int(r["units"]) if "units" in rk else req_count
        first_seen = r["first_seen"] if "first_seen" in rk else None
        last_seen = r["last_seen"] if "last_seen" in rk else None
        out.append(
            ClientTagRow(
                client_tag=tag,
                requests=req_count,
                billable_units=units,
                yen_excl_tax=units * _UNIT_PRICE_YEN,
                first_seen=first_seen,
                last_seen=last_seen,
            )
        )
    return BreakdownAggregate(
        rows=out,
        capped=capped,
        total_requests=total_requests,
        total_billable_units=total_units,
        untagged_requests=untagged_requests,
        untagged_billable_units=untagged_units,
    )


def _resolve_account_id(conn: sqlite3.Connection, key_hash: str) -> str | None:
    """Resolve the Stripe customer_id (== account_id for billing purposes).

    For the breakdown the "account" is whatever Stripe will invoice under —
    that is `api_keys.customer_id`. Read from the parent row of the tree
    when the caller is a child (migration 086) so the dashboard always
    surfaces ONE account_id even for fan-out parents.
    """
    row = conn.execute(
        "SELECT customer_id, parent_key_id FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        return None
    rk = row.keys() if hasattr(row, "keys") else []
    cust = row["customer_id"] if "customer_id" in rk else None
    parent_key_id = row["parent_key_id"] if "parent_key_id" in rk else None
    if cust is not None or parent_key_id is None:
        return cust
    parent = conn.execute(
        "SELECT customer_id FROM api_keys WHERE id = ?",
        (parent_key_id,),
    ).fetchone()
    if parent is None:
        return None
    prk = parent.keys() if hasattr(parent, "keys") else []
    return parent["customer_id"] if "customer_id" in prk else None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get(
    "/client_tag_breakdown",
    response_model=None,  # we return Response directly for the CSV branch
    summary="顧問先別 client_tag 利用明細",
)
def get_client_tag_breakdown(
    ctx: ApiContextDep,
    conn: DbDep,
    period_start: Annotated[
        str | None,
        Query(
            description="期間開始日 (ISO YYYY-MM-DD, JST calendar). 既定: 当月初日",
        ),
    ] = None,
    period_end: Annotated[
        str | None,
        Query(
            description="期間終了日 (ISO YYYY-MM-DD, JST calendar, 当日含む). 既定: 本日",
        ),
    ] = None,
    format: Annotated[  # noqa: A002 — shadowing builtin matches public wire name
        Literal["json", "csv"],
        Query(
            description="json (default) または csv (Excel-Compatible UTF-8)",
        ),
    ] = "json",
) -> Response | dict[str, Any]:
    """Per-客先 (client_tag) breakdown of metered usage for the auth'd account.

    Returns one row per distinct `X-Client-Tag` value that appeared in
    the window, sorted by yen_excl_tax DESC, plus a synthetic
    `client_tag=null` row for un-tagged calls. The grand totals on the
    response reconcile 1:1 with the Stripe invoice that covers the same
    period (JST calendar boundary, 切り捨て consumption-tax math).

    The request itself is intentionally unmetered so the response reconciles
    directly against the underlying usage_events ledger.
    """
    if ctx.key_hash is None:
        # Anonymous / no-key — no Stripe customer to break down.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "api key required for billing breakdown",
        )

    # Period defaults: first-of-month JST -> today JST. period_end is
    # inclusive (caller-friendly) — converted to a half-open SQL bound
    # in `_aggregate`.
    today_jst = _today_jst()
    start_d = _parse_iso_date(period_start, fallback=_first_of_month_jst(today_jst))
    end_d = _parse_iso_date(period_end, fallback=today_jst)
    if end_d < start_d:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": "invalid_period",
                "message": "period_end must be >= period_start",
                "period_start": start_d.isoformat(),
                "period_end": end_d.isoformat(),
            },
        )

    tree_hashes = _resolve_tree_key_hashes(conn, ctx.key_hash)
    aggregate = _aggregate(
        conn,
        tree_hashes=tree_hashes,
        period_start=start_d,
        period_end=end_d,
    )
    rows = aggregate.rows

    total_requests = aggregate.total_requests
    total_billable_units = aggregate.total_billable_units
    total_yen_excl = total_billable_units * _UNIT_PRICE_YEN
    total_yen_incl = _consumption_tax_inclusive_yen(total_yen_excl)
    untagged_requests = aggregate.untagged_requests
    untagged_yen = aggregate.untagged_billable_units * _UNIT_PRICE_YEN

    account_id = _resolve_account_id(conn, ctx.key_hash)

    if format == "csv":
        # Append-friendly schema as specced. The header row is stable so
        # advisors can pipe multiple months into the same Sheets tab.
        # period_start / period_end repeated on every row gives the
        # downstream pivot a clean dimension to filter on.
        header = (
            "period_start,period_end,client_tag,requests,billable_units,"
            "yen_excl_tax,first_seen,last_seen"
        )
        lines = [header]
        for row in rows:
            lines.append(
                ",".join(
                    [
                        _csv_escape(start_d.isoformat()),
                        _csv_escape(end_d.isoformat()),
                        _csv_escape(row.client_tag if row.client_tag is not None else ""),
                        _csv_escape(row.requests),
                        _csv_escape(row.billable_units),
                        _csv_escape(row.yen_excl_tax),
                        _csv_escape(row.first_seen if row.first_seen is not None else ""),
                        _csv_escape(row.last_seen if row.last_seen is not None else ""),
                    ]
                )
            )
        body = "\r\n".join(lines) + "\r\n"
        # Excel-JP friendly: UTF-8 BOM so MS Excel auto-detects encoding.
        # text/csv; charset=utf-8 is the canonical media type per RFC 7111.
        filename = f"autonomath_breakdown_{start_d.isoformat()}_{end_d.isoformat()}.csv"
        return Response(
            content=("﻿" + body).encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    # JSON branch. We dict() the response manually instead of using the
    # pydantic model so the leading-underscore `_disclaimer` field
    # survives JSON serialization (pydantic strips underscore-prefixed
    # fields by default, and the spec contract names it _disclaimer).
    return {
        "account_id": account_id,
        "period": {
            "start": start_d.isoformat(),
            "end": end_d.isoformat(),
        },
        "total_requests": total_requests,
        "total_billable_units": total_billable_units,
        "total_billable_yen_excl_tax": total_yen_excl,
        "total_billable_yen_incl_tax": total_yen_incl,
        "tax_rate": _TAX_RATE,
        "by_client_tag": [
            {
                "client_tag": r.client_tag,
                "requests": r.requests,
                "billable_units": r.billable_units,
                "yen_excl_tax": r.yen_excl_tax,
                "first_seen": r.first_seen,
                "last_seen": r.last_seen,
            }
            for r in rows
        ],
        "untagged_requests": untagged_requests,
        "untagged_yen": untagged_yen,
        "capped_at_max_rows": aggregate.capped,
        "_disclaimer": _DISCLAIMER,
    }
