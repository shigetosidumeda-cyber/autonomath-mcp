"""Public audit-log explorer (Z3 — `am_amendment_diff` read surface).

Exposes the append-only diff log populated by
``scripts/cron/refresh_amendment_diff.py`` (migration 075) as a public,
reverse-chrono, cursor-paginated REST endpoint. This is the
"trust-by-transparency" surface — anyone (auth or not) can verify what
fields actually changed on which entity at which detected_at, against
which source_url, and compare prev_value / new_value byte-for-byte.

Why public read:
    The diff log IS the moat. Hiding it behind paid auth would defeat the
    entire purpose ("we run cron, you trust us"). The 3/日 anonymous IP
    quota (applied via ``AnonIpLimitDep`` in main.py) prevents scrape
    abuse; paid keys (¥3/req) bypass the anon ceiling and bill normally.

Pagination:
    Cursor-based (not offset-based) so a continuously-growing append-only
    log stays correctly paginated even when fresh rows arrive between
    requests. The cursor is the (detected_at, diff_id) tuple of the LAST
    row in the previous page, encoded as `<iso8601>|<diff_id>`. We sort
    by (detected_at DESC, diff_id DESC) so a tie-break on identical
    detected_at falls on the higher diff_id first.

Filters:
    * ``since=YYYY-MM-DD`` — only rows detected on/after this UTC date.
    * ``entity_id`` — exact-match lookup (FK to am_entities.canonical_id).
    * Both are optional. No free-text search over prev_value/new_value
      (that would invite the FTS-trigram false-positive class — callers
      who need that should fetch the page and grep client-side).

Billing:
    Uses ``log_usage()`` like every other ``/v1/am/*`` endpoint. Anonymous
    callers (key_hash=None) hit the IP-based 3/日 quota; paid keys are
    metered ¥3/req. No special treatment.

NOT a tax-advice surface:
    The diff log is metadata about public-source eligibility movements.
    It carries no §52 disclaimer because it does not return tax
    interpretation — it returns "field X went from value A to value B
    on date D against source-url S". Every row points back to a
    primary-source URL the customer can verify themselves.
"""
from __future__ import annotations

import base64
import logging
import sqlite3
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from jpintel_mcp.api.deps import ApiContextDep, DbDep, log_usage
from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

_log = logging.getLogger("jpintel.api.audit_log")

router = APIRouter(prefix="/v1/am", tags=["audit-log"])


# Tracked field metadata (mirrors scripts/cron/refresh_amendment_diff.py
# TRACKED_FIELDS). Keep these two lists in sync when the cron tracks new
# fields — the API is the public schema for what "an amendment" can be.
_TRACKED_FIELDS_JA = {
    "amount_max_yen": "補助上限額",
    "subsidy_rate_max": "補助率上限",
    "program.target_entity": "対象事業者",
    "program.target_business_size": "対象事業規模",
    "program.application_period": "申請期間",
    "program.application_period_r7": "申請期間R7",
    "program.application_channel": "申請窓口",
    "program.prerequisite": "前提条件",
    "program.subsidy_rate": "補助率本文",
    "eligibility_text": "適格要件 (合成)",
}


def _encode_cursor(detected_at: str, diff_id: int) -> str:
    """Encode (detected_at, diff_id) as an opaque base64 cursor.

    We pick base64-url-safe so consumers can drop the value verbatim into
    a query string without %-encoding. The body is `<iso>|<id>` so we can
    decode it without a separate state store.
    """
    raw = f"{detected_at}|{diff_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, int]:
    """Inverse of ``_encode_cursor``. Raises HTTPException(400) on garbage."""
    try:
        # Re-pad. urlsafe_b64decode requires len%4==0.
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        ts, sid = raw.rsplit("|", 1)
        return ts, int(sid)
    except (ValueError, UnicodeDecodeError, base64.binascii.Error) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"invalid cursor: {exc}",
        ) from exc


@router.get(
    "/audit-log",
    summary="Public audit log of am_amendment_diff (reverse-chrono, cursor-paginated)",
    description=(
        "**Public read** of the append-only `am_amendment_diff` table — "
        "the real per-field change log populated daily by "
        "`scripts/cron/refresh_amendment_diff.py` (migration 075). "
        "Anyone can verify what changed on which entity at which "
        "`detected_at`, against which `source_url`, byte-for-byte.\n\n"
        "**Pagination:** cursor-based. The first page request omits "
        "`cursor`; the response carries `next_cursor` (or null when "
        "exhausted). Pass `next_cursor` verbatim as `?cursor=...` for "
        "the next page. Cursor is opaque base64 — do not parse.\n\n"
        "**Filters:**\n"
        "- `since=YYYY-MM-DD` — UTC date floor on `detected_at`.\n"
        "- `entity_id` — exact match on `am_entities.canonical_id`.\n\n"
        "**Billing:** anonymous callers hit the 3/日 per-IP quota "
        "(JST 翌日 00:00 リセット). Paid keys are metered ¥3/req 税別 "
        "(税込 ¥3.30) and bypass the anonymous ceiling.\n\n"
        "**Honesty:** jpcite detects field-level diffs from public "
        "government sources via daily cron. **検出のみで個別判断は行いません。** "
        "Subscribe to `https://jpcite.com/audit-log.rss` for an RSS "
        "feed of the same data."
    ),
    responses={
        200: {
            "description": "Reverse-chrono diff rows + next_cursor.",
            "content": {
                "application/json": {
                    "example": {
                        "results": [
                            {
                                "diff_id": 12345,
                                "entity_id": "program_jigyou_saikouchiku_2026",
                                "field_name": "amount_max_yen",
                                "field_name_ja": "補助上限額",
                                "prev_value": "150000000",
                                "new_value": "200000000",
                                "prev_hash": "9c3f8e...",
                                "new_hash": "7a1b2d...",
                                "detected_at": "2026-04-28T03:14:22+00:00",
                                "source_url": "https://jigyou-saikouchiku.go.jp/...",
                            }
                        ],
                        "next_cursor": "MjAyNi0wNC0yOFQwMzoxNDoyMnwxMjM0NQ",
                        "limit": 100,
                        "filter": {
                            "since": "2026-04-01",
                            "entity_id": None,
                        },
                    }
                }
            },
        },
        400: {"description": "Invalid cursor / since format."},
    },
)
def rest_audit_log(
    conn: DbDep,
    ctx: ApiContextDep,
    since: Annotated[
        str | None,
        Query(
            min_length=10,
            max_length=10,
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            description="ISO YYYY-MM-DD UTC floor on detected_at.",
        ),
    ] = None,
    entity_id: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Exact match on am_entities.canonical_id.",
        ),
    ] = None,
    cursor: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Opaque pagination cursor from a previous response. "
            "Omit for the first page.",
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Max rows per page (default 50)."),
    ] = 50,
) -> JSONResponse:
    """Public reverse-chrono read of `am_amendment_diff`."""
    # Validate `since` is a real date (regex above only enforces shape).
    if since is not None:
        try:
            datetime.strptime(since, "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"invalid since (not a real YYYY-MM-DD date): {since}",
            ) from exc

    cursor_ts: str | None = None
    cursor_id: int | None = None
    if cursor is not None:
        cursor_ts, cursor_id = _decode_cursor(cursor)

    # Build SQL. We open a fresh autonomath.db connection because the
    # `conn` injected via DbDep is jpintel.db, and `am_amendment_diff`
    # lives in autonomath.db (CLAUDE.md: two-DB layout, no ATTACH).
    where: list[str] = []
    args: list[Any] = []
    if since is not None:
        where.append("detected_at >= ?")
        args.append(f"{since}T00:00:00")
    if entity_id is not None:
        where.append("entity_id = ?")
        args.append(entity_id)
    if cursor_ts is not None and cursor_id is not None:
        # Composite (detected_at DESC, diff_id DESC) cursor — strict
        # tuple-less-than against the last seen row.
        where.append("(detected_at < ? OR (detected_at = ? AND diff_id < ?))")
        args.extend([cursor_ts, cursor_ts, cursor_id])

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    sql = (
        "SELECT diff_id, entity_id, field_name, prev_value, new_value, "
        "       prev_hash, new_hash, detected_at, source_url "
        f"FROM am_amendment_diff {where_clause} "
        "ORDER BY detected_at DESC, diff_id DESC LIMIT ?"
    )
    args.append(limit + 1)  # +1 to peek if there's a next page.

    am_conn = connect_autonomath()
    try:
        rows = am_conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            # Migration 075 not yet applied on this volume — degrade
            # cleanly to an empty page so the public surface still works
            # the day the table appears via entrypoint.sh self-heal.
            _log.warning("am_amendment_diff missing on autonomath.db: %s", exc)
            rows = []
        else:
            raise

    # Materialise + decide on next_cursor.
    out: list[dict[str, Any]] = []
    for r in rows[:limit]:
        out.append(
            {
                "diff_id": r["diff_id"],
                "entity_id": r["entity_id"],
                "field_name": r["field_name"],
                "field_name_ja": _TRACKED_FIELDS_JA.get(r["field_name"]),
                "prev_value": r["prev_value"],
                "new_value": r["new_value"],
                "prev_hash": r["prev_hash"],
                "new_hash": r["new_hash"],
                "detected_at": r["detected_at"],
                "source_url": r["source_url"],
            }
        )
    next_cursor: str | None = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last["detected_at"], last["diff_id"])

    body = {
        "results": out,
        "next_cursor": next_cursor,
        "limit": limit,
        "filter": {
            "since": since,
            "entity_id": entity_id,
        },
        "_meta": {
            "honest_note": (
                "公的機関データの差分を毎日 cron で検出。"
                "検出のみで個別判断は行いません。"
            ),
            "rss": "https://jpcite.com/audit-log.rss",
            "license_metadata": "CC-BY-4.0 (差分メタデータ)",
            "creator": "Bookyou株式会社 (T8010001213708)",
        },
    }
    log_usage(
        conn,
        ctx,
        "am.audit_log.list",
        params={
            "since": since,
            "entity_id_present": entity_id is not None,
            "limit": limit,
            "cursor_present": cursor is not None,
        },
        result_count=len(out),
    )
    return JSONResponse(content=body)
