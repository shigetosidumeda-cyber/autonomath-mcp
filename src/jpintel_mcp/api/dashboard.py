"""Tier 2 self-serve customer dashboard endpoints (P5-iota++, dd_v8_08 C/G).

Companion to the existing /v1/me/* control plane in `api/me.py`. Where me.py
implements the cookie-session sign-in flow for the static dashboard.html,
this module exposes Bearer-authenticated read-only summaries that the
dashboard JS (or any agent that already holds an API key) can fetch
directly.

  - GET  /v1/me/dashboard            usage summary (30-day) + cap state
  - GET  /v1/me/usage_by_tool        per-tool top 10 + count + ¥ amount
  - GET  /v1/me/billing_history      Stripe invoice list (5-min in-mem cache)
  - GET  /v1/me/tool_recommendation  intent -> tool list + reason

All endpoints require an authenticated key (`require_key`). Anonymous
callers (no X-API-Key / Bearer) get 401 — see "anon は 401" contract in
the launch-CLI spec. Anonymous browsers can still load dashboard.html and
see the static UI, but the data fetch fails closed.

The dashboard endpoints are read-only and do NOT log_usage(). Reading
your own usage history must not itself burn metered budget; the existing
control-plane endpoints in me.py follow the same posture.
"""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from jpintel_mcp.api.deps import (  # noqa: TC001 (runtime for FastAPI Depends)
    ApiContextDep,
    DbDep,
)
from jpintel_mcp.config import settings

router = APIRouter(tags=["dashboard"])

logger = logging.getLogger("jpintel.dashboard")


# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------
# AutonoMath is fully metered ¥3/req 税別 (税込 ¥3.30). The dashboard derives
# ¥ amounts client-side as count * UNIT_PRICE_YEN. Keeping the constant local
# means the UI stays honest if the price ever changes — no second source of
# truth in JS that could drift.
UNIT_PRICE_YEN: int = 3


# ---------------------------------------------------------------------------
# Auth helper — refuse anonymous callers explicitly.
# ---------------------------------------------------------------------------
# require_key() returns ApiContext(key_hash=None, tier="free") for anonymous
# requests rather than 401. Per spec the dashboard endpoints must reject
# anon outright, so we re-check key_hash here before serving any data.
def _require_authed(ctx: ApiContextDep) -> str:
    if ctx.key_hash is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "dashboard requires an authenticated API key",
        )
    return ctx.key_hash


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class UsageDay(BaseModel):
    date: str
    calls: int


class DashboardSummary(BaseModel):
    """Top-level dashboard payload — sized for a single render pass."""

    key_hash_prefix: str
    tier: str
    days: int
    series: list[UsageDay]
    today_calls: int
    last_7_calls: int
    last_30_calls: int
    last_30_amount_yen: int
    peak_day: UsageDay | None
    monthly_cap_yen: int | None
    month_to_date_calls: int
    month_to_date_amount_yen: int
    cap_remaining_yen: int | None
    unit_price_yen: int = UNIT_PRICE_YEN
    # Stripe subscription cache (mirrors api_keys.stripe_subscription_*).
    # `subscription_status` backs the v2 dunning banner; `current_period_end`
    # backs the "今月の請求期間: YYYY-MM-DD まで" line near the usage stats.
    # Both null for free / pre-billing keys (no Stripe subscription yet).
    subscription_status: str | None = None
    current_period_end: str | None = None


class ToolUsageRow(BaseModel):
    endpoint: str
    calls: int
    amount_yen: int
    avg_latency_ms: int | None = Field(
        default=None,
        description=(
            "Average request latency for this endpoint over the window, "
            "if telemetry is recorded. Currently unused — usage_events does "
            "not persist latency_ms — so the field is None today."
        ),
    )


class ToolUsageResponse(BaseModel):
    days: int
    total_calls: int
    total_amount_yen: int
    top: list[ToolUsageRow]


class BillingInvoice(BaseModel):
    id: str
    number: str | None
    period_start: str | None  # ISO date (yyyy-mm-dd)
    period_end: str | None
    amount_due_yen: int
    amount_paid_yen: int
    currency: str
    status: str
    hosted_invoice_url: str | None
    invoice_pdf: str | None
    created: str  # ISO timestamp


class BillingHistoryResponse(BaseModel):
    invoices: list[BillingInvoice]
    cached_at: str
    customer_id: str | None


class ToolRecommendation(BaseModel):
    endpoint: str
    name: str
    why: str
    confidence: float = Field(ge=0.0, le=1.0)


class ToolRecommendationResponse(BaseModel):
    intent: str
    tools: list[ToolRecommendation]
    fallback_used: bool = Field(
        description=(
            "True when no keyword matched and we fell back to the catalog. "
            "Mirrors envelope.meta.alternative_intents semantics — caller can "
            "downgrade UI to 'browse all' instead of 'best match'."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers — usage aggregation
# ---------------------------------------------------------------------------


def _fetch_usage_series(
    conn: Any, key_hash: str, days: int
) -> list[UsageDay]:
    """Return a contiguous oldest-first series of (date, calls)."""
    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    start_iso = start.isoformat()
    rows = conn.execute(
        """SELECT substr(ts, 1, 10) AS d, COUNT(*) AS n
             FROM usage_events
            WHERE key_hash = ? AND ts >= ?
         GROUP BY d
         ORDER BY d ASC""",
        (key_hash, start_iso),
    ).fetchall()
    by_date: dict[str, int] = {r["d"]: r["n"] for r in rows}
    return [
        UsageDay(date=(start + timedelta(days=i)).isoformat(),
                 calls=by_date.get((start + timedelta(days=i)).isoformat(), 0))
        for i in range(days)
    ]


def _month_start_iso_utc() -> str:
    """Beginning of the current UTC month (matches usage_events.ts comparisons)."""
    now = datetime.now(UTC)
    return now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ).isoformat()


def _fetch_mtd_usage(conn: Any, key_hash: str) -> int:
    """Count metered+successful usage_events in the current calendar month."""
    (count,) = conn.execute(
        """SELECT COUNT(*) FROM usage_events
            WHERE key_hash = ? AND ts >= ?
              AND metered = 1 AND status < 400""",
        (key_hash, _month_start_iso_utc()),
    ).fetchone()
    return int(count)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/v1/me/dashboard", response_model=DashboardSummary)
def get_dashboard(
    ctx: ApiContextDep,
    conn: DbDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> DashboardSummary:
    """30-day usage summary for the calling key.

    Bearer-authenticated. The series is filled with zeros for days with no
    usage so the UI can render a contiguous bar chart without client-side
    gap-filling.
    """
    key_hash = _require_authed(ctx)
    series = _fetch_usage_series(conn, key_hash, days)

    # Aggregate windows
    today_calls = series[-1].calls if series else 0
    last_7_calls = sum(d.calls for d in series[-7:])
    last_30_calls = sum(d.calls for d in series[-30:])
    last_30_amount_yen = last_30_calls * UNIT_PRICE_YEN

    peak: UsageDay | None = None
    for d in series:
        if peak is None or d.calls > peak.calls:
            peak = d
    if peak is not None and peak.calls == 0:
        peak = None  # don't pretend a "peak" exists when nothing was called

    # Cap state — pull from api_keys; this is the same row me.py writes
    # via POST /v1/me/cap. We also pull the cached Stripe subscription
    # state (migration 052) so the v2 dunning banner + period-end line
    # render in a single round trip.
    row = conn.execute(
        "SELECT tier, monthly_cap_yen,"
        "       stripe_subscription_status,"
        "       stripe_subscription_current_period_end"
        "  FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    tier = row["tier"] if row else ctx.tier
    cap = row["monthly_cap_yen"] if row else None
    sub_status = row["stripe_subscription_status"] if row else None
    cpe_epoch = row["stripe_subscription_current_period_end"] if row else None
    # Surface ISO 8601 UTC so the JS can render the YYYY-MM-DD slice
    # without re-parsing an epoch. Match the format used by /v1/me.
    if cpe_epoch is None:
        current_period_end_iso: str | None = None
    else:
        try:
            current_period_end_iso = (
                datetime.fromtimestamp(int(cpe_epoch), tz=UTC)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )
        except (ValueError, OverflowError, OSError):
            current_period_end_iso = None

    mtd_calls = _fetch_mtd_usage(conn, key_hash)
    mtd_amount = mtd_calls * UNIT_PRICE_YEN
    cap_remaining = max(0, cap - mtd_amount) if cap is not None else None

    return DashboardSummary(
        key_hash_prefix=key_hash[:8],
        tier=tier,
        days=days,
        series=series,
        today_calls=today_calls,
        last_7_calls=last_7_calls,
        last_30_calls=last_30_calls,
        last_30_amount_yen=last_30_amount_yen,
        peak_day=peak,
        monthly_cap_yen=cap,
        month_to_date_calls=mtd_calls,
        month_to_date_amount_yen=mtd_amount,
        cap_remaining_yen=cap_remaining,
        subscription_status=sub_status,
        current_period_end=current_period_end_iso,
    )


@router.get("/v1/me/usage_by_tool", response_model=ToolUsageResponse)
def get_usage_by_tool(
    ctx: ApiContextDep,
    conn: DbDep,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> ToolUsageResponse:
    """Top N endpoints by call count over the requested window."""
    key_hash = _require_authed(ctx)
    start = (datetime.now(UTC).date() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """SELECT endpoint, COUNT(*) AS n,
                  SUM(CASE WHEN metered=1 AND status<400 THEN 1 ELSE 0 END) AS billable
             FROM usage_events
            WHERE key_hash = ? AND ts >= ?
         GROUP BY endpoint
         ORDER BY n DESC
            LIMIT ?""",
        (key_hash, start, limit),
    ).fetchall()
    top = [
        ToolUsageRow(
            endpoint=r["endpoint"] or "unknown",
            calls=int(r["n"]),
            amount_yen=int(r["billable"] or 0) * UNIT_PRICE_YEN,
            avg_latency_ms=None,
        )
        for r in rows
    ]
    total_calls = sum(r.calls for r in top)
    total_amount = sum(r.amount_yen for r in top)
    return ToolUsageResponse(
        days=days,
        total_calls=total_calls,
        total_amount_yen=total_amount,
        top=top,
    )


# ---------------------------------------------------------------------------
# Billing history — Stripe invoice list with 5-min in-memory cache.
# ---------------------------------------------------------------------------
# Cache key = customer_id; Stripe invoice listings are per-customer. TTL is
# short enough that a refunded / voided invoice surfaces in the dashboard
# within 5 minutes, but long enough to avoid hammering Stripe on a noisy tab.
# A process-local dict is fine for MVP single-machine fly.io; multi-machine
# scaling would need Redis or shared SQLite.
_BILLING_CACHE_TTL_SECONDS = 5 * 60
_BillingCacheEntry = tuple[float, list[BillingInvoice]]
_billing_cache: dict[str, _BillingCacheEntry] = {}
_billing_cache_lock = threading.Lock()


def _reset_billing_cache_state() -> None:
    """Test helper: drop all cached invoice lists."""
    with _billing_cache_lock:
        _billing_cache.clear()


def _stripe_status_to_int_yen(amount: int | float | None) -> int:
    """Stripe returns JPY amounts as integer minor-units (yen, since JPY has
    no fraction). Coerce defensively in case a future Stripe API tweak
    returns floats."""
    if amount is None:
        return 0
    try:
        return int(amount)
    except (TypeError, ValueError):
        return 0


def _list_stripe_invoices(customer_id: str) -> list[BillingInvoice]:
    """Fetch & normalise the customer's Stripe invoices.

    Returns up to 24 most-recent invoices (~2 years monthly billing). The
    Stripe SDK is imported lazily so a Stripe-less dev/test environment
    does not need to install or configure it just to import this module.
    """
    if not settings.stripe_secret_key:
        return []
    try:
        import stripe
    except ImportError:
        logger.warning("stripe SDK not installed; billing_history empty")
        return []

    stripe.api_key = settings.stripe_secret_key
    try:
        result = stripe.Invoice.list(customer=customer_id, limit=24)
    except Exception:  # pragma: no cover — network/auth issues
        logger.exception("stripe Invoice.list failed customer=%s", customer_id)
        return []

    invoices: list[BillingInvoice] = []
    for inv in getattr(result, "auto_paging_iter", lambda: [])():
        period_start = inv.get("period_start")
        period_end = inv.get("period_end")
        created = inv.get("created")
        invoices.append(
            BillingInvoice(
                id=inv.get("id", ""),
                number=inv.get("number"),
                period_start=(
                    datetime.fromtimestamp(period_start, UTC).date().isoformat()
                    if period_start else None
                ),
                period_end=(
                    datetime.fromtimestamp(period_end, UTC).date().isoformat()
                    if period_end else None
                ),
                amount_due_yen=_stripe_status_to_int_yen(inv.get("amount_due")),
                amount_paid_yen=_stripe_status_to_int_yen(inv.get("amount_paid")),
                currency=str(inv.get("currency", "jpy")),
                status=str(inv.get("status", "unknown")),
                hosted_invoice_url=inv.get("hosted_invoice_url"),
                invoice_pdf=inv.get("invoice_pdf"),
                created=(
                    datetime.fromtimestamp(created, UTC).isoformat()
                    if created else datetime.now(UTC).isoformat()
                ),
            )
        )
    return invoices


@router.get("/v1/me/billing_history", response_model=BillingHistoryResponse)
def get_billing_history(
    ctx: ApiContextDep, conn: DbDep
) -> BillingHistoryResponse:
    """Most-recent Stripe invoices for the calling key's customer.

    Uses a 5-minute in-process cache keyed by `customer_id`. Empty list when
    Stripe is unconfigured or the customer has no invoices yet — this is not
    an error, just a cold-start state.
    """
    key_hash = _require_authed(ctx)
    row = conn.execute(
        "SELECT customer_id FROM api_keys WHERE key_hash = ?",
        (key_hash,),
    ).fetchone()
    customer_id = row["customer_id"] if row else None

    if not customer_id:
        return BillingHistoryResponse(
            invoices=[],
            cached_at=datetime.now(UTC).isoformat(),
            customer_id=None,
        )

    import time as _time

    now = _time.monotonic()
    with _billing_cache_lock:
        hit = _billing_cache.get(customer_id)
        if hit is not None:
            ts, invoices = hit
            if now - ts < _BILLING_CACHE_TTL_SECONDS:
                return BillingHistoryResponse(
                    invoices=invoices,
                    cached_at=datetime.fromtimestamp(
                        _time.time() - (now - ts), UTC
                    ).isoformat(),
                    customer_id=customer_id,
                )

    invoices = _list_stripe_invoices(customer_id)

    with _billing_cache_lock:
        _billing_cache[customer_id] = (now, invoices)

    return BillingHistoryResponse(
        invoices=invoices,
        cached_at=datetime.now(UTC).isoformat(),
        customer_id=customer_id,
    )


# ---------------------------------------------------------------------------
# Tool recommendation (dd_v8_08 G).
# ---------------------------------------------------------------------------
# Mirrors `mcp.autonomath_tools.cs_features.derive_alternative_intents` but
# returns concrete REST endpoints + a "why" reason so an SDK / agent can
# call the recommended tool without an extra LLM round-trip.
#
# Catalog kept here (not imported from the MCP layer) because the MCP
# package depends on AUTONOMATH_ENABLED — REST callers must still get
# recommendations even when the autonomath subpackage is disabled.

_TOOL_CATALOG: list[dict[str, Any]] = [
    {
        "endpoint": "/v1/programs/search",
        "name": "programs.search",
        "purpose": "補助金 / 助成金 / 給付金 / 認定制度の網羅検索",
        "keywords": ["補助", "助成", "給付", "公募", "募集", "subsidy", "grant"],
    },
    {
        "endpoint": "/v1/loan_programs/search",
        "name": "loan_programs.search",
        "purpose": "公庫 / 政策金融 / 制度融資 (担保・保証人 三軸分解)",
        "keywords": ["融資", "貸付", "ローン", "loan", "公庫", "保証", "担保"],
    },
    {
        "endpoint": "/v1/am/tax_incentives",
        "name": "am.tax_incentives.search",
        "purpose": "税額控除 / 特別償却 / 繰越欠損金 / 非課税措置",
        "keywords": ["税", "税制", "控除", "減税", "償却", "tax", "deduction"],
    },
    {
        "endpoint": "/v1/am/certifications",
        "name": "am.certifications.search",
        "purpose": "認定制度 (経営革新 / 経営力向上 / 健康経営 など)",
        "keywords": ["認定", "経営革新", "経営力向上", "健康経営", "certification"],
    },
    {
        "endpoint": "/v1/laws/search",
        "name": "laws.search",
        "purpose": "法令 (法律 / 政令 / 省令) 全文検索 + 条文逆引き",
        "keywords": ["法律", "法令", "条文", "law", "statute"],
    },
    {
        "endpoint": "/v1/court_decisions/search",
        "name": "court_decisions.search",
        "purpose": "判例検索 (法令解釈 / 行政訴訟 / 税務争訟)",
        "keywords": ["判例", "判決", "裁判", "court", "decision", "訴訟"],
    },
    {
        "endpoint": "/v1/enforcement-cases/search",
        "name": "enforcement.search",
        "purpose": "行政処分・指導歴 (1,185 件) — 与信 / コンプライアンス DD",
        "keywords": ["処分", "違反", "コンプラ", "enforcement", "penalty", "行政指導"],
    },
    {
        "endpoint": "/v1/case_studies/search",
        "name": "case_studies.search",
        "purpose": "採択事例 (2,286 件) — 採択率 / 採択額 / 業種別実績",
        "keywords": ["採択", "事例", "実績", "case", "study", "採用"],
    },
    {
        "endpoint": "/v1/calendar/deadlines",
        "name": "calendar.deadlines",
        "purpose": "公募締切カレンダー (90 日先まで)",
        "keywords": ["締切", "deadline", "schedule", "公募期限"],
    },
    {
        "endpoint": "/v1/bids/search",
        "name": "bids.search",
        "purpose": "入札情報 (国・自治体)",
        "keywords": ["入札", "落札", "bid", "tender", "調達"],
    },
    {
        "endpoint": "/v1/tax_rulesets/search",
        "name": "tax_rulesets.search",
        "purpose": "税制 ruleset (申告条件 / 適用要件 評価)",
        "keywords": ["税制", "ruleset", "申告", "適用要件", "tax_rule"],
    },
    {
        "endpoint": "/v1/invoice_registrants/search",
        "name": "invoice_registrants.search",
        "purpose": "適格請求書発行事業者 (T-番号) 検索 — 国税庁 PDL v1.0",
        "keywords": ["適格請求書", "T番号", "T-number", "invoice_registrant", "登録番号"],
    },
    {
        "endpoint": "/v1/programs/prescreen",
        "name": "programs.prescreen",
        "purpose": "事前適格性スクリーニング (除外・前提・絶対条件)",
        "keywords": ["事前", "適格", "スクリーニング", "prescreen", "eligibility"],
    },
    {
        "endpoint": "/v1/exclusions/check",
        "name": "exclusions.check",
        "purpose": "併給禁止 / 排他制度ペア (181 ルール)",
        "keywords": ["併給", "排他", "exclusion", "重複", "mutex"],
    },
]


def _score(tokens: set[str], keywords: list[str]) -> tuple[int, list[str]]:
    """Return (hit_count, matched_keywords)."""
    matched = [k for k in keywords if any(k.lower() in t for t in tokens)]
    return len(matched), matched


@router.get(
    "/v1/me/tool_recommendation", response_model=ToolRecommendationResponse
)
def get_tool_recommendation(
    ctx: ApiContextDep,
    intent: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
) -> ToolRecommendationResponse:
    """Map a free-text intent to ranked tool candidates.

    Pure keyword scoring — no LLM call (memory: feedback_autonomath_no_api_use).
    The caller is expected to be an LLM agent; we return signal, the caller
    composes the next request.
    """
    _require_authed(ctx)
    raw = (intent or "").strip().lower()
    if not raw:
        # caller passed an empty string after trim — degrade to fallback
        raw = ""
    tokens = {raw}
    # Add naive whitespace + punctuation tokenisation so multi-word
    # English intents ("sme grant") match keywords individually.
    for sep in (" ", "、", ",", ".", "・", "/"):
        for chunk in raw.split(sep):
            chunk = chunk.strip()
            if chunk:
                tokens.add(chunk)

    scored: list[tuple[int, dict[str, Any], list[str]]] = []
    for entry in _TOOL_CATALOG:
        score, matched = _score(tokens, entry["keywords"])
        if score > 0:
            scored.append((score, entry, matched))

    scored.sort(key=lambda x: (-x[0], x[1]["name"]))

    fallback_used = False
    if not scored:
        fallback_used = True
        # Ranked default catalog tail — the 3 most-used surfaces.
        default = ["programs.search", "laws.search", "am.tax_incentives.search"]
        scored = []
        for name in default:
            for entry in _TOOL_CATALOG:
                if entry["name"] == name:
                    scored.append((0, entry, []))
                    break

    out: list[ToolRecommendation] = []
    for score, entry, matched in scored[:limit]:
        # Confidence: 1.0 when 2+ keywords matched; 0.6 for one match;
        # 0.2 for the fallback path. These are deterministic — no
        # statistical model — so the dashboard can show a stable bar.
        if fallback_used:
            confidence = 0.2
        elif score >= 2:
            confidence = 1.0
        else:
            confidence = 0.6

        why = (
            entry["purpose"]
            + (
                f" (一致: {', '.join(matched)})"
                if matched
                else " (汎用候補)"
            )
        )
        out.append(
            ToolRecommendation(
                endpoint=str(entry["endpoint"]),
                name=str(entry["name"]),
                why=why,
                confidence=confidence,
            )
        )

    return ToolRecommendationResponse(
        intent=intent,
        tools=out,
        fallback_used=fallback_used,
    )


__all__ = [
    "UNIT_PRICE_YEN",
    "_reset_billing_cache_state",
    "router",
]
