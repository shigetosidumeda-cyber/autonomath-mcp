"""Embed Widget API — origin-whitelisted search surface for `autonomath.js`.

Serves the JS SDK at `site/widget/autonomath.js`, which 税理士事務所・商工会議所・
中小企業支援サイト drop into their HP with one `<script>` + `<div>`.

Auth model — distinct from the main `am_...` API key
----------------------------------------------------
Widget keys look like `wgt_live_{32 hex}` (41 chars total). They sit in
`widget_keys` (migration 022), NOT `api_keys`. Why:

  * Widget keys are by design visible in the browser (script tag). Their
    only security comes from (a) Origin header matching, (b) per-key
    abuse rate limit, (c) billing/payment state. Leaking one is bounded — it can only
    be used from the whitelisted origins.
  * Widget keys only reach `/v1/widget/*`. They can't call /v1/programs,
    /v1/billing, etc. Full separation at the routing layer.
  * Widget pricing uses the same metered usage posture as the public API,
    but is tracked in its own counters because browser-visible keys need
    a different abuse boundary.

Endpoints (all under /v1/widget)
--------------------------------
  GET  /search         proxies to programs search logic (library import)
  GET  /enum_values    enum dropdowns for the widget filter UI (not billable)
  POST /signup         creates Stripe Checkout URL (Widget metered plan)
  POST /keys/from-checkout reveals/provisions the browser widget key
  POST /stripe-webhook Stripe subscription lifecycle (widget plan)
  GET  /{key_id}/usage lightweight JSON for owners (stubbed — key hash gate)
  OPTIONS routes are handled by the FastAPI CORS middleware we mount on the
          router itself (not the global one, because we need per-request
          origin echoing based on allowed_origins_json rather than a static
          allowlist).

NOT wired into main.py — caller is expected to do
    from jpintel_mcp.api.widget_auth import router as widget_router
    app.include_router(widget_router)
when the widget product launches. Kept isolated so a bug here can't
brownout the main `/v1/*` surface.
"""

import contextlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
from collections import deque
from datetime import UTC, datetime
from urllib.parse import urlparse
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, EmailStr, Field, field_validator

from jpintel_mcp.api.billing import validate_jpcite_service_redirect_url
from jpintel_mcp.api.deps import DbDep
from jpintel_mcp.api.vocab import (
    _JSIC_CATEGORIES,
    _PREFECTURES_CANONICAL,
    _normalize_authority_level,
    _normalize_industry_jsic,
    _normalize_prefecture,
)
from jpintel_mcp.config import settings

logger = logging.getLogger("jpintel.widget")

router = APIRouter(prefix="/v1/widget", tags=["widget"])


# ---------------------------------------------------------------------------
# Plan constants
# ---------------------------------------------------------------------------

PLAN_METERED = "metered"
PLAN_BUSINESS = "business"  # legacy alias accepted for old checkout metadata
PLAN_WHITELABEL = "business_whitelabel"  # legacy rows only; not offered in signup
METERED_WIDGET_PLANS = frozenset({PLAN_METERED, PLAN_BUSINESS, PLAN_WHITELABEL})

# New widget keys use the same ¥3/request metered posture as the public API.
# The schema still has included_reqs_mtd for backward compatibility, but new
# keys are provisioned with 0 included requests.
PLAN_INCLUDED_REQS: dict[str, int] = {
    PLAN_METERED: 0,
    PLAN_BUSINESS: 0,
    PLAN_WHITELABEL: 0,
}


def _normalize_plan(plan: str | None) -> str:
    value = (plan or PLAN_METERED).strip()
    if value in (PLAN_METERED, PLAN_BUSINESS):
        # The existing migration constrains plan to 'business' or
        # 'business_whitelabel'. Treat 'business' as the persisted legacy
        # spelling for the current metered SKU.
        return PLAN_BUSINESS
    if value == PLAN_WHITELABEL:
        raise ValueError("widget whitelabel plan is no longer offered")
    raise ValueError("plan must be 'metered'")


# Per-key per-minute rate limit (abuse gate, NOT quota). Kept in-process
# because the widget path must stay cheap — a dropping window over the last
# 60 s of timestamps is a handful of bytes per key and needs no DB roundtrip.
RATE_LIMIT_PER_MINUTE = 100
RATE_LIMIT_WINDOW_SECONDS = 60

_JST = ZoneInfo("Asia/Tokyo")


# ---------------------------------------------------------------------------
# In-memory rate limit
# ---------------------------------------------------------------------------

_rate_state: dict[str, deque[float]] = {}
_rate_lock = threading.Lock()


def _check_rate_limit(key_id: str) -> None:
    """100 req/min/key abuse gate. Raises 429 on breach.

    Separate from billing usage. This one exists to
    stop a runaway script on a customer's site from burning thousands of
    reqs/min before their Cloudflare / origin-side caching kicks in.
    """
    now = time.monotonic()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    with _rate_lock:
        buf = _rate_state.setdefault(key_id, deque())
        while buf and buf[0] < cutoff:
            buf.popleft()
        if len(buf) >= RATE_LIMIT_PER_MINUTE:
            retry_after = max(1, int(RATE_LIMIT_WINDOW_SECONDS - (now - buf[0])))
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                {
                    "error": "rate_limited",
                    "detail": f"widget key {key_id[:14]}… exceeded {RATE_LIMIT_PER_MINUTE} req/min",
                    "retry_after": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )
        buf.append(now)


# ---------------------------------------------------------------------------
# Origin matching
#
# allowed_origins_json is a JSON array. Each entry is either an exact
# origin ("https://example.com") or a wildcard subdomain pattern
# ("https://*.example.com"). Wildcard is limited to the leftmost label —
# this keeps the match surface small and unambiguous. No path, no query,
# scheme required. Public widget signup accepts HTTPS origins only.
# ---------------------------------------------------------------------------

_WILDCARD_ALLOWED_RE = re.compile(
    r"^(?P<scheme>https)://\*\.(?P<host>[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)$"
)


def _origin_allowed(origin: str | None, allowed_json: str) -> bool:
    """Return True iff `origin` matches any entry in `allowed_json` (a JSON array)."""
    if not origin:
        return False
    try:
        allowed = json.loads(allowed_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(allowed, list):
        return False
    for entry in allowed:
        if not isinstance(entry, str):
            continue
        if entry == origin:
            return True
        m = _WILDCARD_ALLOWED_RE.match(entry)
        if not m:
            continue
        # Match "https://*.example.com" against "https://sub.example.com"
        # and "https://deep.sub.example.com". Exactly the scheme matters.
        scheme = m.group("scheme")
        host_suffix = m.group("host")
        needle = f"{scheme}://"
        if not origin.startswith(needle):
            continue
        host_and_rest = origin[len(needle) :]
        # Strip any :port so "https://sub.example.com:8443" still matches
        # "https://*.example.com" — the widget is used from prod sites
        # but we can't refuse non-standard ports outright.
        host_only = host_and_rest.split("/", 1)[0].split(":", 1)[0]
        if host_only == host_suffix:
            continue  # wildcard requires a leading subdomain label
        if host_only.endswith("." + host_suffix):
            return True
    return False


def _validate_origin_pattern(entry: str) -> bool:
    """Return True iff `entry` is a well-formed exact or wildcard origin."""
    if _WILDCARD_ALLOWED_RE.match(entry):
        return True
    # Exact origin: scheme://host(:port)? no trailing slash, no path.
    parsed = urlparse(entry)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    try:
        parsed.port
    except ValueError:
        return False
    return not (parsed.path or parsed.params or parsed.query or parsed.fragment)


# ---------------------------------------------------------------------------
# CORS helpers
# ---------------------------------------------------------------------------


def _cors_headers(origin: str | None, allowed_json: str | None) -> dict[str, str]:
    """Return CORS headers echoing the request's Origin iff it's allowlisted.

    Per MDN: `Access-Control-Allow-Origin` must be either "*" or the exact
    origin string — never the pattern. We NEVER emit "*" because the widget
    key is tied to a specific set of origins on purpose.
    """
    headers: dict[str, str] = {
        "Vary": "Origin",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, X-Widget-Key",
        "Access-Control-Max-Age": "600",
    }
    if origin and allowed_json and _origin_allowed(origin, allowed_json):
        headers["Access-Control-Allow-Origin"] = origin
    return headers


# ---------------------------------------------------------------------------
# Key lookup + quota
# ---------------------------------------------------------------------------


def _jst_month_bucket(ts: datetime | None = None) -> str:
    ts = ts or datetime.now(UTC)
    return ts.astimezone(_JST).strftime("%Y-%m")


def _generate_widget_key() -> str:
    """Return a 'wgt_live_' + 32 hex chars key (41 chars)."""
    return "wgt_live_" + secrets.token_hex(16)


class WidgetKeyRow:
    __slots__ = (
        "key_id",
        "owner_email",
        "label",
        "allowed_origins_json",
        "stripe_customer_id",
        "stripe_subscription_id",
        "plan",
        "included_reqs_mtd",
        "reqs_used_mtd",
        "reqs_total",
        "branding_removed",
        "bucket_month",
        "disabled_at",
    )

    def __init__(self, row: sqlite3.Row):
        self.key_id = row["key_id"]
        self.owner_email = row["owner_email"]
        self.label = row["label"]
        self.allowed_origins_json = row["allowed_origins_json"]
        self.stripe_customer_id = row["stripe_customer_id"]
        self.stripe_subscription_id = row["stripe_subscription_id"]
        self.plan = row["plan"]
        self.included_reqs_mtd = row["included_reqs_mtd"]
        self.reqs_used_mtd = row["reqs_used_mtd"]
        self.reqs_total = row["reqs_total"]
        self.branding_removed = bool(row["branding_removed"])
        self.bucket_month = row["bucket_month"]
        self.disabled_at = row["disabled_at"]


def _copy_widget_key_row(dst: WidgetKeyRow, src: WidgetKeyRow) -> WidgetKeyRow:
    for name in WidgetKeyRow.__slots__:
        setattr(dst, name, getattr(src, name))
    return dst


def _refresh_widget_key(conn: sqlite3.Connection, wk: WidgetKeyRow) -> WidgetKeyRow:
    row = conn.execute(
        "SELECT * FROM widget_keys WHERE key_id = ?",
        (wk.key_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "invalid_key", "detail": "widget key not found"},
        )
    return _copy_widget_key_row(wk, WidgetKeyRow(row))


def _load_key(conn: sqlite3.Connection, key_id: str) -> WidgetKeyRow:
    if not key_id or not key_id.startswith("wgt_live_") or len(key_id) != 41:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "invalid_key", "detail": "widget key format invalid"},
        )
    row = conn.execute("SELECT * FROM widget_keys WHERE key_id = ?", (key_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "invalid_key", "detail": "widget key not found"},
        )
    wk = WidgetKeyRow(row)
    if wk.disabled_at:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"error": "key_disabled", "detail": "widget key disabled"},
        )
    return wk


def _roll_month_if_needed(
    conn: sqlite3.Connection, wk: WidgetKeyRow, now: datetime | None = None
) -> WidgetKeyRow:
    """JST month rollover. Zeros reqs_used_mtd when the JST month changes."""
    now = now or datetime.now(UTC)
    current = _jst_month_bucket(now)
    if wk.bucket_month == current:
        return wk
    iso = now.isoformat()
    conn.execute(
        "UPDATE widget_keys SET reqs_used_mtd = 0, bucket_month = ?, updated_at = ? "
        "WHERE key_id = ? AND COALESCE(bucket_month, '') != ?",
        (current, iso, wk.key_id, current),
    )
    return _refresh_widget_key(conn, wk)


def _enforce_quota_and_increment(conn: sqlite3.Connection, wk: WidgetKeyRow) -> None:
    """Bump counters and atomically queue one metered usage unit when needed."""
    savepoint = f"widget_quota_{secrets.token_hex(4)}"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        now_iso = datetime.now(UTC).isoformat()
        row = conn.execute(
            """
            UPDATE widget_keys
               SET reqs_used_mtd = reqs_used_mtd + 1,
                   reqs_total = reqs_total + 1,
                   last_used_at = ?,
                   updated_at = ?
             WHERE key_id = ?
            RETURNING reqs_used_mtd, reqs_total, included_reqs_mtd, plan,
                      stripe_subscription_id
            """,
            (now_iso, now_iso, wk.key_id),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                {"error": "invalid_key", "detail": "widget key not found"},
            )

        def _field(name: str, index: int) -> Any:
            return row[name] if hasattr(row, "keys") else row[index]

        wk.reqs_used_mtd = int(_field("reqs_used_mtd", 0) or 0)
        wk.reqs_total = int(_field("reqs_total", 1) or 0)
        wk.included_reqs_mtd = int(_field("included_reqs_mtd", 2) or 0)
        wk.plan = str(_field("plan", 3) or wk.plan)
        wk.stripe_subscription_id = str(_field("stripe_subscription_id", 4) or "")

        exceeded = wk.reqs_used_mtd > wk.included_reqs_mtd
        if exceeded and wk.plan in METERED_WIDGET_PLANS:
            # Counter + durable queue row are a single atomic unit. If the
            # queue write fails, roll the counter back and return a retryable
            # 503 instead of silently losing billable overage.
            try:
                _report_overage(
                    conn,
                    wk.stripe_subscription_id,
                    idempotency_key=f"widget_{wk.key_id}_{wk.reqs_total}",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "widget_overage_report_failed key=%s sub=%s",
                    wk.key_id[:14],
                    wk.stripe_subscription_id,
                    exc_info=True,
                )
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    {
                        "error": "billing_queue_unavailable",
                        "detail": "usage was not recorded; retry later",
                    },
                ) from exc
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        with contextlib.suppress(sqlite3.Error):
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        with contextlib.suppress(sqlite3.Error):
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def _report_overage(
    conn: sqlite3.Connection, subscription_id: str, *, idempotency_key: str
) -> None:
    """Queue one widget overage usage unit for durable Stripe reporting."""
    if not subscription_id:
        raise RuntimeError("widget overage missing stripe_subscription_id")

    from jpintel_mcp.api import _bg_task_queue

    _bg_task_queue.enqueue(
        conn,
        kind="stripe_usage_sync",
        payload={
            "subscription_id": subscription_id,
            "quantity": 1,
            "idempotency_key": idempotency_key,
        },
        dedup_key=f"widget_overage:{idempotency_key}",
    )


def _stripe_event_field(event: Any, key: str, default: Any = None) -> Any:
    try:
        return event[key]
    except (KeyError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Common request setup — origin + key + rate limit + quota
# ---------------------------------------------------------------------------


def _authorize(
    conn: sqlite3.Connection,
    request: Request,
    key_param: str | None,
    x_widget_key: str | None,
) -> tuple[WidgetKeyRow, str]:
    """Resolve + authorize a widget key. Returns (row, origin)."""
    key_id = key_param or x_widget_key
    if not key_id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "missing_key", "detail": "widget key required"},
        )
    wk = _load_key(conn, key_id)
    origin = request.headers.get("origin")
    # `Origin` is set by every modern browser on cross-origin requests.
    # If it's absent, the request is either same-origin (our demo page)
    # or a server-side call. We allow an absent Origin ONLY when the
    # key's allowed list includes "*" — never default-allow.
    if not origin:
        try:
            allowed = json.loads(wk.allowed_origins_json)
        except json.JSONDecodeError:
            allowed = []
        if not (isinstance(allowed, list) and "*" in allowed):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {"error": "origin_required", "detail": "Origin header required"},
            )
    elif not _origin_allowed(origin, wk.allowed_origins_json):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {
                "error": "origin_not_allowed",
                "detail": f"Origin {origin} is not on the allowlist for this key",
            },
        )

    _check_rate_limit(wk.key_id)
    _roll_month_if_needed(conn, wk)
    return wk, origin or ""


# ---------------------------------------------------------------------------
# Search + enum_values handlers
# ---------------------------------------------------------------------------


def _attach_widget_result_context(conn: sqlite3.Connection, body: dict[str, Any]) -> None:
    """Add compact evidence context that makes widget cards useful in practice."""
    results = body.get("results")
    if not isinstance(results, list) or not results:
        return
    ids = [
        str(item.get("unified_id"))
        for item in results
        if isinstance(item, dict) and item.get("unified_id")
    ]
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT unified_id, source_url, source_fetched_at FROM programs "
        f"WHERE unified_id IN ({placeholders})",
        ids,
    ).fetchall()
    by_id = {row["unified_id"]: row for row in rows}
    for item in results:
        if not isinstance(item, dict):
            continue
        row = by_id.get(str(item.get("unified_id") or ""))
        if row is None:
            continue
        item.setdefault("source_url", row["source_url"])
        item.setdefault("source_fetched_at", row["source_fetched_at"])
        item["prescreen_questions"] = [
            "所在地・業種・申請者区分が最新の募集要項に合うか",
            "対象経費、締切、他制度との併用可否を一次資料で確認したか",
        ]


@router.options("/search", include_in_schema=False)
@router.options("/enum_values", include_in_schema=False)
async def _preflight(
    request: Request,
    conn: DbDep,
) -> Response:
    """CORS preflight. We look up the key via query-string / header to
    match the actual request's origin rules, but we do not fail open —
    a preflight without a valid key returns empty CORS headers, which
    the browser treats as a denied preflight."""
    key_id = request.query_params.get("key") or request.headers.get("x-widget-key")
    origin = request.headers.get("origin")
    allowed_json: str | None = None
    if key_id:
        row = conn.execute(
            "SELECT allowed_origins_json, disabled_at FROM widget_keys WHERE key_id = ?",
            (key_id,),
        ).fetchone()
        if row and not row["disabled_at"]:
            allowed_json = row["allowed_origins_json"]
    return Response(status_code=204, headers=_cors_headers(origin, allowed_json))


@router.get("/search")
def widget_search(
    request: Request,
    conn: DbDep,
    key: Annotated[str | None, Query(description="widget key; wgt_live_...", max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    prefecture: Annotated[str | None, Query(max_length=20)] = None,
    authority_level: Annotated[str | None, Query(max_length=20)] = None,
    industry: Annotated[str | None, Query(max_length=20)] = None,
    target: Annotated[list[str] | None, Query(max_length=64)] = None,
    funding_purpose: Annotated[list[str] | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    x_widget_key: Annotated[str | None, Header(alias="X-Widget-Key")] = None,
) -> JSONResponse:
    """Search programs restricted to the widget surface.

    Searches programs through the embeddable widget with the same filters as
    program search.
    """
    wk, origin = _authorize(conn, request, key, x_widget_key)

    # Reuse programs search logic in-process. Import inside the handler
    # because programs.py imports from multiple subsystems that are cheap
    # but not essential at module load (tests construct widget_auth alone).
    from jpintel_mcp.api.deps import ApiContext
    from jpintel_mcp.api.programs import search_programs

    # Synthesize an ApiContext: widget calls are unauthenticated against
    # the main api_keys table — we don't want widget keys to log into
    # usage_events (that table is sized for authenticated `am_` key
    # traffic, and widget is its own accounting path). tier="free" avoids
    # paid-only features (fields=full) which the widget doesn't need.
    ctx = ApiContext(key_hash=None, tier="free", customer_id=None)

    # Only expose a narrow subset of filters to the widget — industry/target/
    # funding_purpose/prefecture are enough for the common "what am I
    # eligible for?" card list. Tier filter stays server-side (hardcoded
    # to production tiers S/A/B/C, X-quarantined excluded by programs.py).
    norm_prefecture = _normalize_prefecture(prefecture)
    norm_authority = _normalize_authority_level(authority_level)
    norm_industry = _normalize_industry_jsic(industry)

    # target maps to target_types in programs.search; we pass as-is and
    # rely on programs.py LIKE match. industry is surfaced to the widget
    # user but the programs schema doesn't filter by industry_jsic today —
    # we translate to a funding_purpose hint when it's a known agri code.
    # For now we pass industry separately through q so trigram picks it up.
    q_effective = q
    if norm_industry and not q_effective:
        # surface JSIC as a secondary free-text hint — crude but non-breaking.
        q_effective = norm_industry

    try:
        resp: JSONResponse = search_programs(  # type: ignore[call-arg]
            request=request,
            conn=conn,
            ctx=ctx,
            q=q_effective,
            tier=None,
            prefecture=norm_prefecture,
            authority_level=norm_authority,
            funding_purpose=funding_purpose,
            target_type=target,
            amount_min=None,
            amount_max=None,
            include_excluded=False,
            limit=limit,
            offset=0,
            fields="default",
        )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("widget_search failed key=%s", wk.key_id[:14])
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            {"error": "search_failed", "detail": "widget search failed"},
        ) from e

    # Re-wrap the body to include widget-level branding + usage state.
    try:
        body = json.loads(bytes(resp.body))
    except (json.JSONDecodeError, AttributeError):
        body = {"total": 0, "results": [], "limit": limit, "offset": 0}

    _attach_widget_result_context(conn, body)
    _enforce_quota_and_increment(conn, wk)
    body["widget"] = {
        "plan": wk.plan,
        "branding": not wk.branding_removed,  # show "powered by" iff True
        "reqs_used_mtd": wk.reqs_used_mtd,
        "included_reqs_mtd": wk.included_reqs_mtd,
        "overage": max(0, wk.reqs_used_mtd - wk.included_reqs_mtd),
    }

    headers = _cors_headers(origin, wk.allowed_origins_json)
    return JSONResponse(content=body, headers=headers)


@router.get("/enum_values")
def widget_enum_values(
    request: Request,
    conn: DbDep,
    key: Annotated[str | None, Query(max_length=64)] = None,
    x_widget_key: Annotated[str | None, Header(alias="X-Widget-Key")] = None,
) -> JSONResponse:
    """Return filter enum vocab for widget dropdowns — prefectures, industries,
    authority_levels, and a short target_types list drawn from programs."""
    wk, origin = _authorize(conn, request, key, x_widget_key)

    prefectures = [
        {"code": canonical, "label_ja": canonical}
        for canonical, _short, _romaji in _PREFECTURES_CANONICAL
    ]
    # "全国" first-position — nationwide programs are the common starting filter.
    prefectures.insert(0, {"code": "全国", "label_ja": "全国 (national)"})

    industries = [
        {"code": code, "label_ja": jp_name, "label_en": en_name}
        for code, jp_name, en_name in _JSIC_CATEGORIES
    ]

    authority_levels = [
        {"code": "national", "label_ja": "国"},
        {"code": "prefecture", "label_ja": "都道府県"},
        {"code": "municipality", "label_ja": "市区町村"},
        {"code": "financial", "label_ja": "公的金融機関"},
    ]

    # target_types: drawn from the unified_registry vocabulary. Kept small
    # deliberately — the widget form is a single-screen select, not a
    # 40-option firehose.
    target_types = [
        {"code": "中小企業", "label_ja": "中小企業"},
        {"code": "小規模事業者", "label_ja": "小規模事業者"},
        {"code": "個人事業主", "label_ja": "個人事業主"},
        {"code": "法人", "label_ja": "法人"},
        {"code": "農業者", "label_ja": "農業者"},
        {"code": "NPO", "label_ja": "NPO法人"},
        {"code": "創業者", "label_ja": "創業予定者・創業間もない事業者"},
        {"code": "女性起業家", "label_ja": "女性起業家"},
    ]

    body = {
        "prefectures": prefectures,
        "industries": industries,
        "authority_levels": authority_levels,
        "target_types": target_types,
        "widget": {
            "plan": wk.plan,
            "branding": not wk.branding_removed,
            "reqs_used_mtd": wk.reqs_used_mtd,
            "included_reqs_mtd": wk.included_reqs_mtd,
        },
    }
    headers = _cors_headers(origin, wk.allowed_origins_json)
    return JSONResponse(content=body, headers=headers)


# ---------------------------------------------------------------------------
# Signup + Stripe webhook
# ---------------------------------------------------------------------------


class WidgetSignupRequest(BaseModel):
    email: EmailStr
    origins: list[str] = Field(..., min_length=1, max_length=20)
    plan: str = Field(default=PLAN_METERED)
    label: str | None = Field(default=None, max_length=120)
    success_url: str
    cancel_url: str

    @field_validator("plan")
    @classmethod
    def _check_plan(cls, v: str) -> str:
        return _normalize_plan(v)

    @field_validator("origins")
    @classmethod
    def _check_origins(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for entry in v:
            entry = entry.strip()
            if not _validate_origin_pattern(entry):
                raise ValueError(f"invalid origin pattern: {entry}")
            cleaned.append(entry)
        return cleaned


class WidgetSignupResponse(BaseModel):
    checkout_url: str
    session_id: str


class WidgetKeyIssueRequest(BaseModel):
    session_id: str = Field(..., min_length=3, max_length=255)


class WidgetKeyIssueResponse(BaseModel):
    widget_key: str
    plan: str
    allowed_origins: list[str]
    label: str | None = None
    customer_id: str


@router.post("/signup", response_model=WidgetSignupResponse)
def widget_signup(payload: WidgetSignupRequest) -> WidgetSignupResponse:
    """Create a Stripe Checkout session for the widget plan.

    After successful payment, widget access is provisioned automatically
    and associated with the allowed origins supplied in this request.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "stripe_unconfigured", "detail": "Stripe not configured"},
        )

    import stripe  # local import keeps module load cheap for tests

    stripe.api_key = settings.stripe_secret_key
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version

    import os

    price_id = os.environ.get("STRIPE_PRICE_WIDGET_METERED") or os.environ.get(
        "STRIPE_PRICE_WIDGET_BUSINESS", ""
    )
    if not price_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {
                "error": "price_unconfigured",
                "detail": (
                    "STRIPE_PRICE_WIDGET_METERED not set. "
                    "Legacy STRIPE_PRICE_WIDGET_BUSINESS is still accepted."
                ),
            },
        )

    extra: dict[str, Any] = {}
    if settings.stripe_tax_enabled:
        extra["automatic_tax"] = {"enabled": True}
        extra["tax_id_collection"] = {"enabled": True}
        extra["billing_address_collection"] = "required"

    metadata = {
        "autonomath_product": "widget",
        "autonomath_plan": payload.plan,
        "autonomath_origins": json.dumps(payload.origins, ensure_ascii=False),
        "autonomath_label": payload.label or "",
    }

    success_url = validate_jpcite_service_redirect_url(payload.success_url, kind="success")
    cancel_url = validate_jpcite_service_redirect_url(payload.cancel_url, kind="cancel")
    checkout_locale = "en" if urlparse(success_url).path.startswith("/en/") else "ja"
    submit_message = (
        "By registering, you agree to the Terms of Service "
        "(https://jpcite.com/en/tos.html) and Privacy Policy "
        "(https://jpcite.com/en/privacy.html)."
        if checkout_locale == "en"
        else (
            "ご登録により利用規約 (https://jpcite.com/tos.html) "
            "およびプライバシーポリシー (https://jpcite.com/privacy.html) "
            "に同意したものとみなされます。"
        )
    )

    session = stripe.checkout.Session.create(  # type: ignore[call-arg,unused-ignore]
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        customer_email=str(payload.email),
        allow_promotion_codes=True,
        locale=checkout_locale,
        branding_settings={"display_name": "jpcite"},
        subscription_data={"metadata": metadata},
        metadata=metadata,
        custom_text={
            "submit": {"message": submit_message}
        },
        **extra,
    )
    return WidgetSignupResponse(checkout_url=session.url or "", session_id=session.id)


def _stripe_object_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _plain_stripe_mapping(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return dict(obj)
    with contextlib.suppress(Exception):
        return dict(obj)
    data: dict[str, Any] = {}
    for key in ("id", "subscription", "customer", "customer_email", "metadata", "customer_details"):
        value = getattr(obj, key, None)
        if value is not None:
            data[key] = value
    return data


@router.post("/keys/from-checkout", response_model=WidgetKeyIssueResponse)
def widget_key_from_checkout(
    payload: WidgetKeyIssueRequest,
    conn: DbDep,
) -> WidgetKeyIssueResponse:
    """Reveal or provision a widget key after Stripe Checkout.

    Widget keys are browser-visible and origin-locked, so this page can show
    the key directly after a completed Checkout session. The webhook remains
    the durable path; this endpoint covers the normal post-payment screen when
    Stripe's webhook arrives a few seconds later than the browser redirect.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "stripe_unconfigured", "detail": "Stripe not configured"},
        )

    import stripe

    stripe.api_key = settings.stripe_secret_key
    if settings.stripe_api_version:
        stripe.api_version = settings.stripe_api_version

    session = stripe.checkout.Session.retrieve(payload.session_id)
    md = _stripe_object_get(session, "metadata", {}) or {}
    if not isinstance(md, dict):
        md = dict(md)
    if md.get("autonomath_product") != "widget":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "checkout session is not widget")
    if _stripe_object_get(session, "status") != "complete":
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "checkout session incomplete")
    if _stripe_object_get(session, "mode") != "subscription":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "checkout session is not a subscription")
    session_livemode = bool(_stripe_object_get(session, "livemode", False))
    if session_livemode != (settings.env == "prod"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "checkout livemode mismatch")
    if _stripe_object_get(session, "payment_status") not in ("paid", "no_payment_required"):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "checkout session not paid")

    sub_id = str(_stripe_object_get(session, "subscription", "") or "")
    customer_id = str(_stripe_object_get(session, "customer", "") or "")
    if not sub_id or not customer_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "checkout session missing subscription")

    existing = conn.execute(
        "SELECT * FROM widget_keys WHERE stripe_subscription_id = ? LIMIT 1",
        (sub_id,),
    ).fetchone()
    if existing is None:
        session_obj = _plain_stripe_mapping(session)
        session_obj["metadata"] = md
        session_obj["subscription"] = sub_id
        session_obj["customer"] = customer_id
        _provision_widget_key(conn, session_obj=session_obj)
        existing = conn.execute(
            "SELECT * FROM widget_keys WHERE stripe_subscription_id = ? LIMIT 1",
            (sub_id,),
        ).fetchone()

    if existing is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "widget key provisioning is still pending; retry in a few seconds",
        )

    wk = WidgetKeyRow(existing)
    return WidgetKeyIssueResponse(
        widget_key=wk.key_id,
        plan=wk.plan,
        allowed_origins=json.loads(wk.allowed_origins_json or "[]"),
        label=wk.label,
        customer_id=wk.stripe_customer_id,
    )


@router.post("/stripe-webhook")
async def widget_stripe_webhook(
    request: Request,
    conn: DbDep,
    stripe_signature: Annotated[str | None, Header(alias="stripe-signature")] = None,
) -> dict[str, str]:
    """Process widget billing events.

    Checkout completion provisions a widget key. Subscription cancellation
    or payment failure disables widget access until billing is resolved.
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "webhook secret unset")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    body = await request.body()
    try:
        event = stripe.Webhook.construct_event(  # type: ignore[no-untyped-call]
            body,
            stripe_signature or "",
            settings.stripe_webhook_secret,
            tolerance=300,
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad signature") from None

    etype = _stripe_event_field(event, "type", "")
    obj = _stripe_event_field(_stripe_event_field(event, "data", {}), "object", {})
    event_id = str(_stripe_event_field(event, "id", "") or "")
    event_livemode = bool(_stripe_event_field(event, "livemode", False))
    is_production = settings.env == "prod"
    if event_livemode != is_production:
        logger.error(
            "widget.webhook.livemode_mismatch event_id=%s event_livemode=%s is_production=%s",
            event_id,
            event_livemode,
            is_production,
        )
        return {"status": "livemode_mismatch_ignored"}

    # Only react to widget-tagged events. Shared webhook endpoint with the
    # main billing flow is deliberately NOT re-used — that one provisions
    # api_keys and would misroute widget signups.
    is_widget = False
    widget_lookup_failed = False
    if isinstance(obj, dict):
        md = obj.get("metadata") or {}
        is_widget = md.get("autonomath_product") == "widget"
        if not is_widget:
            # subscription objects carry metadata at their own level, but
            # invoice events have it nested under the subscription we
            # retrieve. Check via subscription retrieve if needed.
            sub_id = obj.get("subscription") if etype.startswith("invoice") else None
            if sub_id:
                try:
                    sub = stripe.Subscription.retrieve(sub_id)
                    md2 = dict(sub["metadata"]) if sub["metadata"] else {}
                    is_widget = md2.get("autonomath_product") == "widget"
                    if is_widget:
                        obj = dict(obj)
                        obj["_widget_subscription"] = sub
                except Exception:  # noqa: BLE001
                    widget_lookup_failed = True
                    logger.warning(
                        "widget_webhook_sub_retrieve_failed sub=%s", sub_id, exc_info=True
                    )
    if not is_widget:
        if widget_lookup_failed:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "widget subscription lookup failed",
            )
        # Silently ignore non-widget events so a shared endpoint with the
        # main billing webhook doesn't double-process.
        return {"status": "ignored", "reason": "not_widget"}

    dedup_id = f"widget:{event_id}" if event_id else ""
    if dedup_id:
        existing = conn.execute(
            "SELECT processed_at FROM stripe_webhook_events WHERE event_id = ?",
            (dedup_id,),
        ).fetchone()
        if existing:
            if existing["processed_at"] is None:
                raise HTTPException(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "webhook event previously received but not processed",
                )
            logger.info(
                "widget.webhook.duplicate_ignored event_id=%s type=%s",
                event_id,
                etype,
            )
            return {"status": "duplicate_ignored"}
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO stripe_webhook_events"
                " (event_id, event_type, livemode, received_at)"
                " VALUES (?, ?, ?, datetime('now'))",
                (dedup_id, etype, 1 if event_livemode else 0),
            )
        except Exception:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            re_check = conn.execute(
                "SELECT processed_at FROM stripe_webhook_events WHERE event_id = ?",
                (dedup_id,),
            ).fetchone()
            if re_check:
                return {"status": "duplicate_ignored"}
            raise

    handler_exc: BaseException | None = None
    try:
        if etype == "checkout.session.completed":
            _provision_widget_key(conn, session_obj=obj)
        elif etype == "customer.subscription.deleted":
            _disable_widget_key(conn, subscription_id=obj.get("id"))
        elif etype == "invoice.payment_failed":
            sub_id = obj.get("subscription")
            if sub_id:
                _disable_widget_key(conn, subscription_id=sub_id)
        elif etype == "invoice.paid":
            # Re-enable a disabled key on successful payment.
            sub_id = obj.get("subscription")
            if sub_id:
                _enable_widget_key(conn, subscription_id=sub_id)
    except Exception as exc:  # noqa: BLE001
        handler_exc = exc

    if handler_exc is not None:
        if dedup_id:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
        logger.exception(
            "widget.webhook.handler_failed event_id=%s type=%s",
            event_id,
            etype,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "widget webhook handler failed",
        ) from handler_exc

    if dedup_id:
        try:
            conn.execute(
                "UPDATE stripe_webhook_events SET processed_at = datetime('now')"
                " WHERE event_id = ?",
                (dedup_id,),
            )
            conn.execute("COMMIT")
        except Exception:
            with contextlib.suppress(Exception):
                conn.execute("ROLLBACK")
            raise

    return {"status": "received"}


def _provision_widget_key(conn: sqlite3.Connection, session_obj: dict[str, Any]) -> None:
    """Create the widget_keys row after Checkout completes."""
    sub_id = session_obj.get("subscription")
    customer_id = session_obj.get("customer")
    md = session_obj.get("metadata") or {}
    try:
        plan = _normalize_plan(md.get("autonomath_plan"))
    except ValueError:
        logger.warning("widget_provision_unsupported_plan md=%s", md)
        return
    label = md.get("autonomath_label") or None
    try:
        origins = json.loads(md.get("autonomath_origins") or "[]")
        if not isinstance(origins, list):
            origins = []
    except json.JSONDecodeError:
        origins = []
    if not sub_id or not customer_id:
        logger.warning("widget_provision_missing_ids md=%s", md)
        return
    if not origins:
        logger.warning("widget_provision_no_origins sub=%s", sub_id)

    existing = conn.execute(
        "SELECT key_id FROM widget_keys WHERE stripe_subscription_id = ? LIMIT 1",
        (sub_id,),
    ).fetchone()
    if existing:
        logger.info("widget_provision_idempotent sub=%s", sub_id)
        return

    # customer_details.email is present on checkout.session.completed.
    cd = session_obj.get("customer_details") or {}
    email = cd.get("email") or session_obj.get("customer_email") or ""

    key_id = _generate_widget_key()
    now = datetime.now(UTC).isoformat()
    included = PLAN_INCLUDED_REQS.get(plan, 0)
    branding_removed = 0
    conn.execute(
        "INSERT INTO widget_keys("
        "  key_id, owner_email, label, allowed_origins_json, stripe_customer_id, "
        "  stripe_subscription_id, plan, included_reqs_mtd, reqs_used_mtd, "
        "  reqs_total, branding_removed, bucket_month, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)",
        (
            key_id,
            email,
            label,
            json.dumps(origins, ensure_ascii=False),
            customer_id,
            sub_id,
            plan,
            included,
            branding_removed,
            _jst_month_bucket(),
            now,
            now,
        ),
    )
    logger.info("widget_provisioned key=%s plan=%s origins=%d", key_id[:14], plan, len(origins))


def _disable_widget_key(conn: sqlite3.Connection, subscription_id: str | None) -> None:
    if not subscription_id:
        return
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        "UPDATE widget_keys SET disabled_at = ?, updated_at = ? "
        "WHERE stripe_subscription_id = ? AND disabled_at IS NULL",
        (now, now, subscription_id),
    )
    if cur.rowcount:
        logger.info("widget_disabled sub=%s rows=%d", subscription_id, cur.rowcount)


def _enable_widget_key(conn: sqlite3.Connection, subscription_id: str | None) -> None:
    if not subscription_id:
        return
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        "UPDATE widget_keys SET disabled_at = NULL, updated_at = ? "
        "WHERE stripe_subscription_id = ? AND disabled_at IS NOT NULL",
        (now, subscription_id),
    )
    if cur.rowcount:
        logger.info("widget_enabled sub=%s rows=%d", subscription_id, cur.rowcount)


# ---------------------------------------------------------------------------
# Usage endpoint (Bearer admin)
# ---------------------------------------------------------------------------


@router.get("/{key_id}/usage")
def widget_usage(
    key_id: str,
    conn: DbDep,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """Owner-visible usage for their widget key. Bearer admin required.

    The dashboard consumes this via a scheduled fetch, so the endpoint returns
    stable JSON-first fields for current-month usage.
    """
    admin_key = settings.admin_api_key
    if not admin_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"error": "admin_disabled", "detail": "admin endpoints disabled"},
        )
    bearer = (authorization or "").split(None, 1)
    # Constant-time admin key compare (avoid leaking matching-prefix length
    # via response timing). length-mismatch arms short-circuit in compare_digest
    # but reveal nothing about content.
    if (
        len(bearer) != 2
        or bearer[0].lower() != "bearer"
        or not hmac.compare_digest(bearer[1].encode("utf-8"), admin_key.encode("utf-8"))
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"error": "admin_auth_failed"},
        )
    row = conn.execute("SELECT * FROM widget_keys WHERE key_id = ?", (key_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "widget key not found")
    wk = WidgetKeyRow(row)
    return JSONResponse(
        content={
            "key_id": wk.key_id,
            "owner_email": wk.owner_email,
            "label": wk.label,
            "plan": wk.plan,
            "included_reqs_mtd": wk.included_reqs_mtd,
            "reqs_used_mtd": wk.reqs_used_mtd,
            "reqs_total": wk.reqs_total,
            "bucket_month": wk.bucket_month,
            "branding_removed": wk.branding_removed,
            "disabled": wk.disabled_at is not None,
            "allowed_origins": json.loads(wk.allowed_origins_json or "[]"),
        }
    )


__all__ = ["router"]
