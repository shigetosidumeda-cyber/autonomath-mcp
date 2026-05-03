"""Saved Searches + Daily Alert Digest (W3 retention feature).

Endpoints under /v1/me/saved_searches:
    - POST   /v1/me/saved_searches             create a saved search
    - GET    /v1/me/saved_searches             list the calling key's saved
                                               searches
    - DELETE /v1/me/saved_searches/{id}        hard-delete a saved search

Why a separate router (not folded into me.py / alerts.py):
    * me.py is the dashboard-cookie surface. Saved searches are managed by
      the calling API key (X-API-Key / Authorization: Bearer) so MCP tools
      and CI callers can wire them in without touching the browser flow.
    * alerts.py owns Tier-3 amendment subscriptions which are FREE structural
      event fan-out (migration 038). Saved searches are a different product
      surface: customer-defined queries replayed daily, with each delivery
      metered at ¥3 through ``report_usage_async`` (the customer pulled the
      delivery, so we charge for it inside our flat ¥3/req unit price).

Authentication:
    Authenticated via require_key (ApiContextDep). Anonymous tier rejected
    with 401 — there is no key to attach the saved search to. Mirrors the
    /v1/me/cap and /v1/me/alerts/* posture.

Cost posture:
    * **Subscription** (POST/GET/DELETE) is FREE — these are CRUD calls on
      the customer's own row, not a metered surface. They still count
      against the per-key middleware rate limit.
    * **Delivery / manual replay** is ¥3/req metered. Each digest email the
      cron sends records one row into ``usage_events`` (endpoint
      ``saved_searches.digest``, status 200) and triggers
      ``report_usage_async`` which posts a usage_record to Stripe. See
      ``scripts/cron/run_saved_searches.py`` for the wiring. Manual
      ``/{id}/results`` and ``/{id}/results.xlsx`` calls are logged via
      ``log_usage`` on this route.

§52 fence:
    Every digest email rendered by ``saved_search_digest`` carries the
    税理士法 §52 / 弁護士法 §72 disclaimer in both the html and txt parts —
    we are 公開情報の検索, not 個別具体的な助言. The dashboard section that
    lets customers manage their saved searches surfaces the same line so the
    surface stays consistent.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field

from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends resolution)
    ApiContextDep,
    DbDep,
    log_usage,
)

router = APIRouter(prefix="/v1/me/saved_searches", tags=["saved-searches"])

logger = logging.getLogger("jpintel.saved_searches")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Hard cap on saved searches per key to bound cron fan-out cost. A solo
# operator running a single SaaS account has zero need for >50 named
# queries; if a customer hits this we want the visible 400 rather than a
# silent runaway cron bill.
MAX_SAVED_SEARCHES_PER_KEY = 50

# Filter keys allowed inside `query_json`. We constrain the surface to
# match what `programs.search` (api/programs.py) accepts so the cron can
# replay the same query without translation. Unknown keys would silently
# be dropped by the search endpoint, which would leave the customer
# baffled why their saved search returned nothing.
_ALLOWED_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "q",
        "prefecture",
        "authority_level",
        "target_types",  # list[str]
        "funding_purpose",  # list[str]
        "amount_min",
        "amount_max",
        "tier",  # list[str]
        "include_excluded",
    }
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SavedSearchQuery(BaseModel):
    """The query criteria for a saved search.

    Public criteria for a saved-search alert. These mirror public
    ``GET /v1/programs/search`` filters, but intentionally exclude
    non-public operator escape hatches. All fields
    are optional, BUT the create endpoint enforces "at least one filter" so
    a customer cannot save the empty-corpus query (which would email them
    every program every day).
    """

    q: Annotated[str | None, Field(default=None, max_length=200)] = None
    prefecture: Annotated[str | None, Field(default=None, max_length=20)] = None
    authority_level: Annotated[str | None, Field(default=None, max_length=20)] = None
    target_types: Annotated[
        list[str] | None, Field(default=None, max_length=20)
    ] = None
    funding_purpose: Annotated[
        list[str] | None, Field(default=None, max_length=20)
    ] = None
    amount_min: Annotated[float | None, Field(default=None, ge=0)] = None
    amount_max: Annotated[float | None, Field(default=None, ge=0)] = None
    tier: Annotated[list[str] | None, Field(default=None, max_length=4)] = None


# Slack-only webhook prefix for SSRF defense — see migration 099 docs.
# We accept the literal Slack incoming-webhook host only, never user-supplied
# arbitrary HTTPS URLs (defense against pivoting through internal services).
_SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/services/"


class CreateSavedSearchRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    query: SavedSearchQuery
    frequency: Literal["daily", "weekly"] = "daily"
    notify_email: EmailStr
    # Migration 099 — recurring engagement channel routing. Default 'email'
    # preserves the W3 contract for existing rows. 'slack' requires
    # channel_url to start with the Slack incoming-webhook prefix; any
    # other host is rejected with 422 (SSRF defense).
    channel_format: Literal["email", "slack"] = "email"
    channel_url: Annotated[str | None, Field(default=None, max_length=512)] = None


class SavedSearchResponse(BaseModel):
    id: int
    name: str
    query: dict[str, Any]
    frequency: str
    notify_email: str
    channel_format: str
    channel_url: str | None
    last_run_at: str | None
    created_at: str


class DeleteResponse(BaseModel):
    ok: bool
    id: int


class PatchSavedSearchRequest(BaseModel):
    """Partial update — only channel fields may be edited post-create.

    Renaming or rewriting the query is intentionally not supported (delete
    + create instead) so we have a clean audit trail. Channel routing is
    the only knob that legitimately flips post-create (consultant adds a
    Slack channel after onboarding via email).
    """

    channel_format: Literal["email", "slack"] | None = None
    channel_url: Annotated[str | None, Field(default=None, max_length=512)] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonicalise_query(q: SavedSearchQuery) -> dict[str, Any]:
    """Drop None/empty values and return a stable dict for JSON storage.

    The cron loads the JSON back via ``json.loads`` and passes it straight to
    ``programs.search``; canonicalisation here saves a defensive cleanup
    pass on every cron run.
    """
    raw = q.model_dump()
    cleaned: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in _ALLOWED_QUERY_KEYS:
            # Defence-in-depth — Pydantic already gates this, but a future
            # refactor that adds a field to SavedSearchQuery without
            # updating _ALLOWED_QUERY_KEYS would silently leak it.
            continue
        if v is None:
            continue
        if isinstance(v, list) and not v:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        cleaned[k] = v
    return cleaned


def _has_any_filter(query: dict[str, Any]) -> bool:
    """True iff the saved query has at least one non-default filter.

    `include_excluded=False` is the default, so we ignore it on the
    "do you have any filter" check. Without this check a customer could
    save the empty query and get every program in every digest.
    """
    for k, v in query.items():
        if k == "include_excluded":
            continue
        if v is None:
            continue
        if isinstance(v, list) and not v:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return True
    return False


def _row_to_response(row: dict[str, Any]) -> SavedSearchResponse:
    try:
        query = json.loads(row["query_json"]) if row["query_json"] else {}
    except (TypeError, ValueError):
        # On corruption, emit an empty query rather than 500ing the list
        # endpoint. The cron will skip the row when it can't parse.
        logger.warning(
            "saved_search.query_json_unparseable id=%s", row.get("id")
        )
        query = {}
    # Tolerate rows persisted before migration 099 (channel_format / channel_url
    # may be missing when reading via a legacy SELECT). Default to 'email'.
    channel_format = "email"
    channel_url: str | None = None
    try:
        if "channel_format" in row:  # type: ignore[operator]
            channel_format = row["channel_format"] or "email"
            channel_url = row["channel_url"]
    except (KeyError, AttributeError):
        pass
    return SavedSearchResponse(
        id=row["id"],
        name=row["name"],
        query=query,
        frequency=row["frequency"],
        notify_email=row["notify_email"],
        channel_format=channel_format,
        channel_url=channel_url,
        last_run_at=row["last_run_at"],
        created_at=row["created_at"],
    )


def _validate_channel(
    channel_format: str, channel_url: str | None
) -> None:
    """Raise 422 if the channel pair is inconsistent.

    Slack format requires a Slack-domain webhook URL; any other host is
    a SSRF risk. Email format requires channel_url to be NULL — accepting
    a stray URL there would leak it into a future webhook call.
    """
    if channel_format == "slack" and (
        not channel_url or not channel_url.startswith(_SLACK_WEBHOOK_PREFIX)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"channel_format='slack' requires channel_url with prefix "
            f"'{_SLACK_WEBHOOK_PREFIX}' (SSRF defense)",
        )
    if channel_format == "email" and channel_url is not None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "channel_format='email' must not include channel_url",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SavedSearchResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_saved_search(
    payload: CreateSavedSearchRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> SavedSearchResponse:
    """Create a new saved search on the calling key.

    Returns 401 for anonymous callers — there is no key_hash to attach the
    row to. Returns 400 when the query has no filters (empty-corpus guard).
    Returns 409 when the per-key cap (MAX_SAVED_SEARCHES_PER_KEY) is
    reached.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "saved searches require an authenticated API key",
        )

    query = _canonicalise_query(payload.query)
    if not _has_any_filter(query):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "query must include at least one filter (q, prefecture, target_types, funding_purpose, amount_min, amount_max, authority_level, or tier)",
        )

    # Enforce per-key cap so a runaway loop cannot create unbounded rows.
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM saved_searches WHERE api_key_hash = ?",
        (ctx.key_hash,),
    ).fetchone()
    if count >= MAX_SAVED_SEARCHES_PER_KEY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"saved search cap reached ({MAX_SAVED_SEARCHES_PER_KEY}); delete one before adding another",
        )

    # Channel pair validation (migration 099). Slack-format requires the
    # Slack-domain prefix; email-format must not carry a URL.
    _validate_channel(payload.channel_format, payload.channel_url)

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    cur = conn.execute(
        """INSERT INTO saved_searches(
                api_key_hash, name, query_json, frequency, notify_email,
                channel_format, channel_url,
                last_run_at, created_at
           ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            ctx.key_hash,
            payload.name.strip(),
            json.dumps(query, sort_keys=True, ensure_ascii=False, separators=(",", ":")),
            payload.frequency,
            payload.notify_email,
            payload.channel_format,
            payload.channel_url,
            None,  # last_run_at — set by the cron on first sweep
            now,
        ),
    )
    sub_id = cur.lastrowid
    if sub_id is None:
        # Defensive — sqlite always returns lastrowid for INSERT into a
        # rowid table, but the type signature says Optional.
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "failed to create saved search",
        )

    row = conn.execute(
        "SELECT id, name, query_json, frequency, notify_email, "
        "channel_format, channel_url, last_run_at, created_at "
        "FROM saved_searches WHERE id = ?",
        (sub_id,),
    ).fetchone()
    return _row_to_response(dict(row))


@router.get(
    "",
    response_model=list[SavedSearchResponse],
)
def list_saved_searches(
    ctx: ApiContextDep,
    conn: DbDep,
) -> list[SavedSearchResponse]:
    """Return all saved searches owned by the calling key.

    Ordered by id ascending so the dashboard's render order stays stable
    across calls (no UI flicker on poll).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "saved searches require an authenticated API key",
        )
    rows = conn.execute(
        """SELECT id, name, query_json, frequency, notify_email,
                  channel_format, channel_url,
                  last_run_at, created_at
             FROM saved_searches
            WHERE api_key_hash = ?
         ORDER BY id ASC""",
        (ctx.key_hash,),
    ).fetchall()
    return [_row_to_response(dict(r)) for r in rows]


@router.patch(
    "/{saved_id}",
    response_model=SavedSearchResponse,
)
def update_saved_search(
    saved_id: int,
    payload: PatchSavedSearchRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> SavedSearchResponse:
    """Update channel routing on an existing saved search.

    Only `channel_format` + `channel_url` are mutable post-create. Either
    both must be provided (full channel re-bind) or neither (no-op 200).
    Anything else is rejected with 422 to prevent half-bound rows.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "saved searches require an authenticated API key",
        )
    row = conn.execute(
        "SELECT id, name, query_json, frequency, notify_email, "
        "channel_format, channel_url, last_run_at, created_at "
        "FROM saved_searches WHERE id = ? AND api_key_hash = ?",
        (saved_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "saved search not found"
        )

    # Treat partial PATCH as no-op (return current row) when neither field
    # is supplied. When EITHER is supplied, both must be supplied so we
    # never persist an inconsistent (slack, NULL) or (email, https://...)
    # pair through a one-sided update.
    if payload.channel_format is None and payload.channel_url is None:
        return _row_to_response(dict(row))
    if payload.channel_format is None or (
        payload.channel_format == "slack" and payload.channel_url is None
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "channel_format + channel_url must be supplied together; for "
            "email mode pass channel_url=null explicitly",
        )

    _validate_channel(payload.channel_format, payload.channel_url)
    conn.execute(
        "UPDATE saved_searches "
        "   SET channel_format = ?, channel_url = ? "
        " WHERE id = ? AND api_key_hash = ?",
        (
            payload.channel_format,
            payload.channel_url,
            saved_id,
            ctx.key_hash,
        ),
    )
    row = conn.execute(
        "SELECT id, name, query_json, frequency, notify_email, "
        "channel_format, channel_url, last_run_at, created_at "
        "FROM saved_searches WHERE id = ?",
        (saved_id,),
    ).fetchone()
    return _row_to_response(dict(row))


@router.delete(
    "/{saved_id}",
    response_model=DeleteResponse,
)
def delete_saved_search(
    saved_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
) -> DeleteResponse:
    """Hard-delete a saved search. 404 when the id is not the caller's.

    We hard-delete (not soft) because the saved-search row is a bookmark,
    not a transactional record — the audit trail for delivered digests
    lives in ``usage_events`` and is unaffected by deletion here.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "saved searches require an authenticated API key",
        )
    row = conn.execute(
        "SELECT id FROM saved_searches WHERE id = ? AND api_key_hash = ?",
        (saved_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        # 404 (not 403) so callers cannot probe the id-space of other keys.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "saved search not found"
        )
    conn.execute(
        "DELETE FROM saved_searches WHERE id = ? AND api_key_hash = ?",
        (saved_id, ctx.key_hash),
    )
    return DeleteResponse(ok=True, id=saved_id)


# ---------------------------------------------------------------------------
# Workflow integrations 5-pack — Excel download + Google-Sheet binding
# ---------------------------------------------------------------------------
#
# Two thin extensions to the saved-search surface that the integrations
# 5-pack relies on:
#
#   GET  /v1/me/saved_searches/{id}/results.xlsx
#       Renders today's saved-search result set as an XLSX workbook
#       (re-uses api/formats/xlsx.py — the existing 6-pack output renderer).
#       One ¥3 charge per call (NOT per row).
#
#   POST /v1/me/saved_searches/{id}/sheet
#       Bind a Google Sheets spreadsheet ID to this saved search so the
#       daily cron can append rows directly into it. The actual append
#       runs via the customer's stored google_sheets credential
#       (api/_integration_tokens.load_account / scripts/cron/run_saved_searches.py).
#
# Migration 105 added saved_searches.sheet_id + sheet_tab_name. This file
# tolerates both pre- and post-migration schemas via _has_sheet_id_column.


def _has_sheet_id_column(conn) -> bool:
    """Return True iff migration 105 has run (saved_searches has sheet_id)."""
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(saved_searches)")}
    except Exception:  # noqa: BLE001
        return False
    return "sheet_id" in cols


def _saved_query_list(value: Any) -> list[str] | None:
    """Normalize historical scalar saved-query fields to list shape."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    if isinstance(value, tuple | set):
        return [str(item) for item in value if item is not None and str(item)]
    text = str(value)
    return [text] if text else None


def _run_saved_search_query(conn, query: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Replay a saved search with identical filters for every output format."""
    from jpintel_mcp.api.programs import _build_search_response

    body = _build_search_response(
        conn=conn,
        q=query.get("q"),
        tier=_saved_query_list(query.get("tier")),
        prefecture=query.get("prefecture"),
        authority_level=query.get("authority_level"),
        funding_purpose=_saved_query_list(query.get("funding_purpose")),
        target_type=_saved_query_list(
            query.get("target_types") or query.get("target_type")
        ),
        amount_min=query.get("amount_min"),
        amount_max=query.get("amount_max"),
        include_excluded=False,
        limit=int(query.get("limit") or 100),
        offset=0,
        fields="default",
        include_advisors=False,
        as_of_iso=None,
    )
    rows = body.get("results", []) if isinstance(body, dict) else []
    safe_rows = [row for row in rows if isinstance(row, dict)]
    for result in safe_rows:
        program_id = result.get("unified_id")
        if isinstance(program_id, str) and program_id:
            result.setdefault(
                "evidence_packet_endpoint",
                f"/v1/evidence/packets/program/{program_id}",
            )
    total = int(body.get("total", 0)) if isinstance(body, dict) else 0
    return safe_rows, total


class BindSheetRequest(BaseModel):
    sheet_id: str = Field(..., min_length=20, max_length=120)
    sheet_tab_name: str | None = Field(default="jpcite", max_length=64)


class BindSheetResponse(BaseModel):
    ok: bool
    saved_search_id: int
    sheet_id: str
    sheet_tab_name: str


@router.post(
    "/{saved_id}/sheet",
    response_model=BindSheetResponse,
    status_code=status.HTTP_200_OK,
)
def bind_sheet_to_saved_search(
    saved_id: int,
    payload: BindSheetRequest,
    ctx: ApiContextDep,
    conn: DbDep,
) -> BindSheetResponse:
    """Bind a Google Sheets spreadsheet ID to this saved search.

    Pre-condition: the calling key has already completed the OAuth
    handshake at ``/v1/integrations/google/start`` → callback. We do NOT
    re-verify here (that would require a 4th hop to Google for a single
    bind). The cron job will surface "credential missing" on the next
    delivery if the customer revoked the OAuth grant on Google's side.
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sheet bind requires an authenticated API key",
        )
    if not _has_sheet_id_column(conn):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "saved_searches.sheet_id not yet provisioned (migration 105)",
        )
    row = conn.execute(
        "SELECT id FROM saved_searches WHERE id = ? AND api_key_hash = ?",
        (saved_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved search not found")

    tab = payload.sheet_tab_name or "jpcite"
    conn.execute(
        "UPDATE saved_searches "
        "   SET sheet_id = ?, sheet_tab_name = ? "
        " WHERE id = ? AND api_key_hash = ?",
        (payload.sheet_id, tab, saved_id, ctx.key_hash),
    )
    return BindSheetResponse(
        ok=True,
        saved_search_id=saved_id,
        sheet_id=payload.sheet_id,
        sheet_tab_name=tab,
    )


@router.get(
    "/{saved_id}/results",
    summary="Run today's saved-search and return results in chosen format",
    description=(
        "Re-run the saved search query against the current corpus and "
        "return the matching rows in the requested format. Allowed "
        "formats: `json` (default), `csv`, `xlsx`, `ics` (one VEVENT per "
        "row that carries `next_deadline`). One ¥3 charge per call "
        "regardless of row count or format. The same §52 / 税理士法 "
        "disclaimer is embedded in every non-JSON body, plus the "
        "`corpus_snapshot_id` is mirrored as `X-Corpus-Snapshot-Id` and "
        "into the format body (CSV comment row, ICS X-WR-CALDESC, etc.)."
    ),
)
def saved_search_results(
    saved_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
    format: Annotated[  # noqa: A002 — matches dispatcher param name
        str,
        Query(
            description=(
                "Output format. `json` returns the raw envelope; "
                "`csv`/`xlsx` produce a downloadable workbook/sheet; "
                "`ics` produces an iCalendar file with one VEVENT per "
                "deadline-bearing row. Other formats (md / docx-application "
                "/ accounting CSVs) are rejected — they are wired on the "
                "/v1/programs surface, not on saved_searches."
            ),
            pattern=r"^(json|csv|xlsx|ics)$",
        ),
    ] = "json",
):
    """Run the saved-search query and return the results in chosen format.

    Re-uses ``_build_search_response`` so the result shape is identical to
    a fresh ``GET /v1/programs/search`` with the same filters. Result-set
    is capped at 100 rows by default — the saved-query JSON may pin a
    smaller limit. Single ¥3 charge per request (counted at the route
    layer, not per row).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "saved searches require an authenticated API key",
        )
    row = conn.execute(
        "SELECT id, query_json FROM saved_searches "
        "WHERE id = ? AND api_key_hash = ?",
        (saved_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved search not found")

    try:
        query = json.loads(row["query_json"]) if row["query_json"] else {}
    except json.JSONDecodeError:
        query = {}

    from jpintel_mcp.api._corpus_snapshot import compute_corpus_snapshot

    rows, total = _run_saved_search_query(conn, query)
    snapshot_id, checksum = compute_corpus_snapshot(conn)

    if format == "json":
        from fastapi.responses import JSONResponse

        envelope = {
            "saved_search_id": saved_id,
            "total": total,
            "results": rows,
            "corpus_snapshot_id": snapshot_id,
            "corpus_checksum": checksum,
        }
        response = JSONResponse(
            content=envelope,
            headers={
                "X-Corpus-Snapshot-Id": snapshot_id,
                "X-Corpus-Checksum": checksum,
            },
        )
        log_usage(
            conn,
            ctx,
            "saved_searches.results",
            params={"saved_search_id": saved_id, "format": format},
            result_count=len(rows),
        )
        return response

    from jpintel_mcp.api._format_dispatch import render

    meta = {
        "filename_stem": f"jpcite_saved_{saved_id}",
        "endpoint": "saved_searches.results",
        "saved_search_id": saved_id,
        "total": total,
        "corpus_snapshot_id": snapshot_id,
        "corpus_checksum": checksum,
    }
    resp = render(rows, format, meta)
    resp.headers["X-Corpus-Snapshot-Id"] = snapshot_id
    resp.headers["X-Corpus-Checksum"] = checksum
    log_usage(
        conn,
        ctx,
        "saved_searches.results",
        params={"saved_search_id": saved_id, "format": format},
        result_count=len(rows),
    )
    return resp


@router.get(
    "/{saved_id}/results.xlsx",
    summary="Download today's saved-search results as XLSX",
    description=(
        "Re-runs the saved search and returns the result rows as an "
        "openpyxl-streamed XLSX workbook. ¥3 per call regardless of row "
        "count. The workbook carries the §52 disclaimer in row 1 of the "
        "data sheet plus a ``_meta`` sheet with license + brand."
    ),
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}
            }
        }
    },
)
def saved_search_results_xlsx(
    saved_id: int,
    ctx: ApiContextDep,
    conn: DbDep,
):
    """Stream the saved-search results as XLSX.

    Re-uses the same _build_search_response + xlsx renderer as the rest of
    the format-dispatch surface — there is exactly one place where the
    workbook layout lives (api/formats/xlsx.py).
    """
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "XLSX download requires API key"
        )
    row = conn.execute(
        "SELECT id, query_json FROM saved_searches "
        "WHERE id = ? AND api_key_hash = ?",
        (saved_id, ctx.key_hash),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved search not found")

    try:
        query = json.loads(row["query_json"]) if row["query_json"] else {}
    except json.JSONDecodeError:
        query = {}

    from jpintel_mcp.api.formats.xlsx import render_xlsx

    rows, total = _run_saved_search_query(conn, query)
    meta = {
        "saved_search_id": saved_id,
        "total": total,
        "license": "jpcite evidence export",
    }
    response = render_xlsx(rows, meta)
    log_usage(
        conn,
        ctx,
        "saved_searches.results_xlsx",
        params={"saved_search_id": saved_id, "format": "xlsx"},
        result_count=len(rows),
    )
    return response


__all__ = [
    "MAX_SAVED_SEARCHES_PER_KEY",
    "router",
]
