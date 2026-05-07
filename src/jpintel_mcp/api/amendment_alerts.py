"""Amendment alert subscription feed (R8 / jpcite v0.3.4).

Endpoints under /v1/me/amendment_alerts:
  - POST   /v1/me/amendment_alerts/subscribe          create a multi-watch subscription
  - GET    /v1/me/amendment_alerts/feed               90-day rolling am_amendment_diff feed
  - DELETE /v1/me/amendment_alerts/{subscription_id}  soft-delete (deactivate) the row

Why a separate router (not part of alerts.py)
---------------------------------------------
The legacy alerts.py router (migration 038, /v1/me/alerts) commits to a single
(filter_type, filter_value) pair per row plus min_severity gating. This new
surface speaks **multi-watch JSON from day one** so a tax consultant can target
"every program in my book + the laws under those programs + my industry JSIC"
in one subscription. The fan-out cron joins it against `am_amendment_diff`
(autonomath.db, 12,116 rows as of 2026-05-07) instead of `am_amendment_snapshot`,
which is a different cadence shape.

Authentication
--------------
Authenticated via require_key (ApiContextDep). Anonymous tier rejected with
401 — there is no key to attach the subscription to. This matches the
posture of the legacy /v1/me/alerts surface and the /v1/me/cap probe.

Cost posture
------------
Subscriptions are FREE (no ¥3/req surcharge). project_autonomath_business_model
keeps the unit price immutable; the alert fan-out cost is ours to absorb as a
retention feature. The amendment feed itself (GET /feed) is also FREE — a
read of public corpus data the customer is already entitled to via the
public /v1/am/audit-log surface.

Output formats
--------------
GET /feed supports `?format=json` (default, structured envelope) and
`?format=atom` (RFC 4287 Atom 1.0 feed for RSS readers / news aggregators).
The Atom path emits a `_disclaimer` notice in each `<summary>` block per
§52 sensitive-surface rules; metadata (no advice) is the entire payload, so
the disclaimer is informational.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    ApiContextDep,
    DbDep,
)
from jpintel_mcp.mcp.autonomath_tools.db import connect_autonomath

_log = logging.getLogger("jpintel.api.amendment_alerts")

router = APIRouter(prefix="/v1/me/amendment_alerts", tags=["amendment-alerts"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Watch type vocabulary. Mirrors the matcher in scripts/cron/amendment_alert_fanout.py.
WATCH_TYPES: tuple[str, ...] = ("program_id", "law_id", "industry_jsic")

# Maximum watches per subscription. Keeps the cron O(N×M) bounded — a
# subscription with 1,000 watches × 12,000 diffs is a 12M-cell match and
# bumps cron CPU into Fly machine-restart territory.
MAX_WATCHES_PER_SUBSCRIPTION = 50

# Feed window (days). 90 days matches the audit-log RSS cadence.
FEED_WINDOW_DAYS = 90

# Hard ceiling on rows returned per feed call. Defends the autonomath.db read
# path from a malicious cursor + 1k watches × 90d combination.
MAX_FEED_ROWS = 500


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class WatchEntry(BaseModel):
    """Single watch entry inside a subscription's `watch` array."""

    type: Literal["program_id", "law_id", "industry_jsic"]
    id: Annotated[str, Field(min_length=1, max_length=200)]


class SubscribeRequest(BaseModel):
    watch: Annotated[
        list[WatchEntry],
        Field(min_length=1, max_length=MAX_WATCHES_PER_SUBSCRIPTION),
    ]


class SubscribeResponse(BaseModel):
    subscription_id: int
    watch_count: int
    created_at: str


class DeactivateResponse(BaseModel):
    ok: bool
    subscription_id: int


class FeedItem(BaseModel):
    diff_id: int
    entity_id: str
    field_name: str
    prev_value: str | None
    new_value: str | None
    detected_at: str
    source_url: str | None
    matched_watch: dict[str, str]


class FeedResponse(BaseModel):
    subscription_count: int
    window_days: int
    results: list[FeedItem]
    _disclaimer: str = (
        "本フィードは公開された am_amendment_diff の差分情報のみを返します。"
        "個別判断・税務助言は行いません。各 source_url の一次情報をご確認ください。"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Return millisecond-precision UTC ISO-8601 (matches DB default)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def _validate_watch(watch: list[WatchEntry]) -> None:
    """Defensive checks beyond Pydantic shape validation."""
    if len(watch) == 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "watch must contain at least one entry",
        )
    if len(watch) > MAX_WATCHES_PER_SUBSCRIPTION:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"watch must contain at most {MAX_WATCHES_PER_SUBSCRIPTION} entries",
        )
    seen: set[tuple[str, str]] = set()
    for entry in watch:
        if entry.type not in WATCH_TYPES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"watch.type must be one of {WATCH_TYPES}, got {entry.type!r}",
            )
        key = (entry.type, entry.id)
        if key in seen:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"duplicate watch entry: {entry.type}={entry.id}",
            )
        seen.add(key)


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Idempotently create the table if it does not yet exist on this DB.

    The production DB has the table after migration wave24_194 lands via
    `scripts/migrate.py`. Tests construct a fresh seeded_db per session and
    do not always run the migration runner — this helper ensures the
    endpoint works regardless. CREATE IF NOT EXISTS is a no-op in production.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS amendment_alert_subscriptions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key_id      INTEGER,
            api_key_hash    TEXT NOT NULL,
            watch_json      TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            deactivated_at  TEXT,
            last_fanout_at  TEXT
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_amendment_alert_sub_key "
        "ON amendment_alert_subscriptions(api_key_hash, deactivated_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_amendment_alert_sub_active "
        "ON amendment_alert_subscriptions(deactivated_at, last_fanout_at)"
    )


def _load_active_watches(
    conn: sqlite3.Connection, key_hash: str
) -> list[tuple[int, list[WatchEntry]]]:
    """Return [(subscription_id, watches), ...] for the calling key."""
    _ensure_table(conn)
    rows = conn.execute(
        "SELECT id, watch_json FROM amendment_alert_subscriptions "
        "WHERE api_key_hash = ? AND deactivated_at IS NULL "
        "ORDER BY id ASC",
        (key_hash,),
    ).fetchall()
    out: list[tuple[int, list[WatchEntry]]] = []
    for row in rows:
        try:
            raw = json.loads(row["watch_json"])
        except (TypeError, ValueError):
            _log.warning("amendment_alert: malformed watch_json on subscription_id=%s", row["id"])
            continue
        watches: list[WatchEntry] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            wt = entry.get("type")
            wid = entry.get("id")
            if wt in WATCH_TYPES and isinstance(wid, str) and wid:
                watches.append(WatchEntry(type=wt, id=wid))
        if watches:
            out.append((int(row["id"]), watches))
    return out


def _fetch_diffs_for_watches(
    watches: list[WatchEntry],
    since_iso: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Pull rows from `am_amendment_diff` matching ANY of the watch entries.

    Matching strategy
    -----------------
    - watch.type == 'program_id' or 'law_id': exact-match on
      `am_amendment_diff.entity_id` (canonical id form on the diff log).
    - watch.type == 'industry_jsic': join through `am_entity_facts` on
      field_name='industry_jsic' (when present) — implemented as a sub-SELECT
      so we do not pull the whole facts table into memory.

    Honest gap
    ----------
    industry_jsic resolution depends on `am_entity_facts` having the
    industry_jsic field populated for the affected entity. When it is not,
    the diff row is silently excluded. The cron logs the gap.
    """
    if not watches:
        return []

    am_conn = connect_autonomath()
    try:
        # Build per-type lists so we can use a single OR'd WHERE clause.
        ids_program: list[str] = []
        ids_law: list[str] = []
        ids_industry: list[str] = []
        for w in watches:
            if w.type == "program_id":
                ids_program.append(w.id)
            elif w.type == "law_id":
                ids_law.append(w.id)
            elif w.type == "industry_jsic":
                ids_industry.append(w.id)

        clauses: list[str] = []
        args: list[Any] = []
        if ids_program:
            placeholders = ",".join("?" * len(ids_program))
            clauses.append(f"d.entity_id IN ({placeholders})")
            args.extend(ids_program)
        if ids_law:
            placeholders = ",".join("?" * len(ids_law))
            clauses.append(f"d.entity_id IN ({placeholders})")
            args.extend(ids_law)
        if ids_industry:
            placeholders = ",".join("?" * len(ids_industry))
            clauses.append(
                "d.entity_id IN (SELECT entity_id FROM am_entity_facts "
                f"WHERE field_name = 'industry_jsic' AND value IN ({placeholders}))"
            )
            args.extend(ids_industry)

        where_or = " OR ".join(f"({c})" for c in clauses)
        sql = (
            "SELECT d.diff_id, d.entity_id, d.field_name, d.prev_value, "
            "       d.new_value, d.detected_at, d.source_url "
            "FROM am_amendment_diff d "
            f"WHERE d.detected_at >= ? AND ({where_or}) "
            "ORDER BY d.detected_at DESC, d.diff_id DESC LIMIT ?"
        )
        sql_args: list[Any] = [since_iso, *args, limit]

        try:
            rows = am_conn.execute(sql, sql_args).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                _log.warning("am_amendment_diff missing on autonomath.db: %s", exc)
                return []
            raise

        results: list[dict[str, Any]] = []
        # Build a quick {entity_id: matched_watch} for the response payload.
        watch_lookup = {(w.type, w.id) for w in watches}
        program_set = set(ids_program)
        law_set = set(ids_law)
        # industry_jsic match cannot be reverse-resolved cheaply — we
        # report the FIRST industry watch as the match for those rows.
        industry_first = ids_industry[0] if ids_industry else None
        for r in rows:
            entity_id = r["entity_id"]
            matched: dict[str, str]
            if entity_id in program_set and ("program_id", entity_id) in watch_lookup:
                matched = {"type": "program_id", "id": entity_id}
            elif entity_id in law_set and ("law_id", entity_id) in watch_lookup:
                matched = {"type": "law_id", "id": entity_id}
            elif industry_first is not None:
                matched = {"type": "industry_jsic", "id": industry_first}
            else:
                # Should not happen given the WHERE clause, but defend.
                matched = {"type": "program_id", "id": entity_id}
            results.append(
                {
                    "diff_id": r["diff_id"],
                    "entity_id": entity_id,
                    "field_name": r["field_name"],
                    "prev_value": r["prev_value"],
                    "new_value": r["new_value"],
                    "detected_at": r["detected_at"],
                    "source_url": r["source_url"],
                    "matched_watch": matched,
                }
            )
        return results
    finally:
        am_conn.close()


def _render_atom(items: list[dict[str, Any]], window_days: int) -> str:
    """Render an Atom 1.0 feed for the items list (RSS reader compat)."""
    now = _now_iso()
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="utf-8"?>')
    parts.append('<feed xmlns="http://www.w3.org/2005/Atom">')
    parts.append("<title>jpcite amendment alert feed</title>")
    parts.append('<link rel="self" href="https://api.jpcite.com/v1/me/amendment_alerts/feed"/>')
    parts.append(f"<id>urn:jpcite:amendment-alert-feed:{now}</id>")
    parts.append(f"<updated>{xml_escape(now)}</updated>")
    parts.append(
        "<subtitle>"
        f"直近 {window_days} 日の根拠条文 / 制度改正差分。"
        "個別判断は含みません。"
        "</subtitle>"
    )
    for item in items:
        diff_id = item["diff_id"]
        entity_id = item["entity_id"]
        field_name = item["field_name"]
        detected_at = item["detected_at"] or now
        prev_value = item.get("prev_value") or ""
        new_value = item.get("new_value") or ""
        source_url = item.get("source_url") or ""
        title = f"{entity_id} :: {field_name} 改正"
        body = (
            f"prev: {prev_value}\n"
            f"new: {new_value}\n\n"
            "本フィードは差分情報のみを返します。個別判断・税務助言は行いません。"
        )
        parts.append("<entry>")
        parts.append(f"<id>urn:jpcite:amendment-diff:{diff_id}</id>")
        parts.append(f"<title>{xml_escape(title)}</title>")
        parts.append(f"<updated>{xml_escape(detected_at)}</updated>")
        if source_url:
            parts.append(f'<link rel="related" href="{xml_escape(source_url)}"/>')
        parts.append(f"<summary>{xml_escape(body)}</summary>")
        parts.append("</entry>")
    parts.append("</feed>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/subscribe",
    response_model=SubscribeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Subscribe to multi-watch amendment-diff alerts",
)
def subscribe(
    payload: SubscribeRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> SubscribeResponse:
    """Create a new amendment-alert subscription.

    Body shape:
        {"watch": [{"type": "program_id", "id": "UNI-..."}, ...]}

    Returns the new `subscription_id` plus echo metadata. The fan-out cron
    (`scripts/cron/amendment_alert_fanout.py`) reads matching diffs from
    autonomath.db `am_amendment_diff` daily.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "amendment-alert subscriptions require an authenticated API key",
        )

    _validate_watch(payload.watch)
    _ensure_table(conn)

    watch_json = json.dumps(
        [{"type": w.type, "id": w.id} for w in payload.watch],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO amendment_alert_subscriptions("
        "api_key_id, api_key_hash, watch_json, created_at) "
        "VALUES (?, ?, ?, ?)",
        (ctx.key_id, ctx.key_hash, watch_json, now),
    )
    sub_id = cur.lastrowid
    if sub_id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "failed to create amendment-alert subscription",
        )
    return SubscribeResponse(
        subscription_id=int(sub_id),
        watch_count=len(payload.watch),
        created_at=now,
    )


@router.get(
    "/feed",
    summary="90-day rolling feed of am_amendment_diff matches for the calling key",
    description=(
        "Returns the calling key's matching `am_amendment_diff` rows from the "
        "last 90 days. Supports `format=json` (default, envelope with "
        "_disclaimer) or `format=atom` (RFC 4287 1.0 for RSS readers).\n\n"
        "Each item carries `matched_watch` so consumers can attribute the "
        "alert to the originating watch entry. Rows are ordered "
        "(detected_at DESC, diff_id DESC).\n\n"
        "**Honesty:** jpcite detects field-level diffs from public "
        "government sources via daily cron. **検出のみで個別判断は行いません。**"
    ),
)
def feed(
    ctx: ApiContextDep,
    conn: DbDep,
    format: Annotated[  # noqa: A002 (FastAPI query name is part of public API)
        Literal["json", "atom"], Query(description="Response format")
    ] = "json",
    limit: Annotated[
        int, Query(ge=1, le=MAX_FEED_ROWS, description="Max rows (default 100)")
    ] = 100,
) -> Response:
    """Return the calling key's 90-day feed."""
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "amendment-alert feed requires an authenticated API key",
        )

    subscriptions = _load_active_watches(conn, ctx.key_hash)
    if not subscriptions:
        # No active subscriptions ⇒ empty feed (200, not 404, so RSS readers
        # do not unsubscribe).
        if format == "atom":
            return Response(
                content=_render_atom([], FEED_WINDOW_DAYS),
                media_type="application/atom+xml; charset=utf-8",
            )
        return JSONResponse(
            FeedResponse(
                subscription_count=0,
                window_days=FEED_WINDOW_DAYS,
                results=[],
            ).model_dump()
        )

    # Union the watches across all active subscriptions, dedup by (type, id).
    union: dict[tuple[str, str], WatchEntry] = {}
    for _sub_id, watches in subscriptions:
        for w in watches:
            union.setdefault((w.type, w.id), w)
    all_watches = list(union.values())

    since = (datetime.now(UTC) - timedelta(days=FEED_WINDOW_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    rows = _fetch_diffs_for_watches(all_watches, since, limit)

    if format == "atom":
        return Response(
            content=_render_atom(rows, FEED_WINDOW_DAYS),
            media_type="application/atom+xml; charset=utf-8",
        )

    return JSONResponse(
        FeedResponse(
            subscription_count=len(subscriptions),
            window_days=FEED_WINDOW_DAYS,
            results=[FeedItem(**r) for r in rows],
        ).model_dump()
    )


@router.delete(
    "/{subscription_id}",
    response_model=DeactivateResponse,
    summary="Soft-delete (deactivate) an amendment-alert subscription",
)
def deactivate(
    subscription_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
) -> DeactivateResponse:
    """Mark the subscription deactivated. The row stays for audit trail.

    404 when the id does not belong to this key OR is already deactivated
    (so callers cannot probe other keys' id-space).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "amendment-alert subscriptions require an authenticated API key",
        )
    _ensure_table(conn)
    row = conn.execute(
        "SELECT id FROM amendment_alert_subscriptions "
        "WHERE id = ? AND api_key_hash = ? AND deactivated_at IS NULL",
        (subscription_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "amendment-alert subscription not found",
        )
    now = _now_iso()
    conn.execute(
        "UPDATE amendment_alert_subscriptions SET deactivated_at = ? "
        "WHERE id = ? AND api_key_hash = ?",
        (now, subscription_id, ctx.key_hash),
    )
    return DeactivateResponse(ok=True, subscription_id=subscription_id)


__all__ = [
    "FEED_WINDOW_DAYS",
    "MAX_FEED_ROWS",
    "MAX_WATCHES_PER_SUBSCRIPTION",
    "WATCH_TYPES",
    "router",
]
