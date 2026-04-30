import asyncio
import json
import logging
import os
import re
import secrets
import sys
import time
import unicodedata
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from jpintel_mcp import __version__
from jpintel_mcp.api._error_envelope import make_error, safe_request_id
from jpintel_mcp.api.accounting import router as accounting_router
from jpintel_mcp.api.admin import router as admin_router
from jpintel_mcp.api.admin_kpi import router as admin_kpi_router
from jpintel_mcp.api.advisors import router as advisors_router
from jpintel_mcp.api.alerts import router as alerts_router
from jpintel_mcp.api.anon_limit import (
    AnonIpLimitDep,
    _AnonRateLimitExceeded,
    anon_rate_limit_exception_handler,
)
from jpintel_mcp.api.appi_deletion import router as appi_deletion_router
from jpintel_mcp.api.appi_disclosure import router as appi_disclosure_router
from jpintel_mcp.api.audit import public_router as audit_public_router
from jpintel_mcp.api.audit import router as audit_router
from jpintel_mcp.api.audit_log import router as audit_log_router
from jpintel_mcp.api.autonomath import (
    health_router as autonomath_health_router,
)
from jpintel_mcp.api.autonomath import (
    router as autonomath_router,
)
from jpintel_mcp.api.bids import router as bids_router
from jpintel_mcp.api.billing import router as billing_router
from jpintel_mcp.api.bulk_evaluate import router as bulk_evaluate_router
from jpintel_mcp.api.calendar import router as calendar_router
from jpintel_mcp.api.case_studies import router as case_studies_router
from jpintel_mcp.api.citations import router as citations_router
from jpintel_mcp.api.client_profiles import router as client_profiles_router
from jpintel_mcp.api.compliance import router as compliance_router
from jpintel_mcp.api.confidence import router as confidence_router
from jpintel_mcp.api.cost import router as cost_router
from jpintel_mcp.api.courses import router as courses_router
from jpintel_mcp.api.court_decisions import router as court_decisions_router
from jpintel_mcp.api.customer_webhooks import router as customer_webhooks_router
from jpintel_mcp.api.dashboard import router as dashboard_router
from jpintel_mcp.api.device_flow import router as device_router
from jpintel_mcp.api.email_unsubscribe import router as email_unsubscribe_router
from jpintel_mcp.api.email_webhook import router as email_webhook_router
from jpintel_mcp.api.enforcement import router as enforcement_router
from jpintel_mcp.api.evidence import router as evidence_router
from jpintel_mcp.api.exclusions import router as exclusions_router
from jpintel_mcp.api.feedback import router as feedback_router
from jpintel_mcp.api.funding_stack import router as funding_stack_router
from jpintel_mcp.api.houjin import router as houjin_router
from jpintel_mcp.api.intelligence import router as intelligence_router
from jpintel_mcp.api.invoice_registrants import router as invoice_registrants_router
from jpintel_mcp.api.laws import router as laws_router
from jpintel_mcp.api.legal import router as legal_router
from jpintel_mcp.api.loan_programs import router as loan_programs_router
from jpintel_mcp.api.logging_config import setup_logging
from jpintel_mcp.api.ma_dd import (
    router as ma_dd_router,
)
from jpintel_mcp.api.ma_dd import (
    watches_router as me_watches_router,
)
from jpintel_mcp.api.me import router as me_router
from jpintel_mcp.api.meta import router as meta_router
from jpintel_mcp.api.meta_freshness import router as meta_freshness_router
from jpintel_mcp.api.middleware import (
    AnalyticsRecorderMiddleware,
    AnonQuotaHeaderMiddleware,
    ClientTagMiddleware,
    CustomerCapMiddleware,
    DeprecationWarningMiddleware,
    HostDeprecationMiddleware,
    KillSwitchMiddleware,
    OriginEnforcementMiddleware,
    PerIpEndpointLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    StrictQueryMiddleware,
)
from jpintel_mcp.api.prescreen import router as prescreen_router
from jpintel_mcp.api.programs import router as programs_router
from jpintel_mcp.api.response_sanitizer import ResponseSanitizerMiddleware
from jpintel_mcp.api.saved_searches import router as saved_searches_router
from jpintel_mcp.api.signup import router as signup_router
from jpintel_mcp.api.source_manifest import router as source_manifest_router
from jpintel_mcp.api.stats import router as stats_router
from jpintel_mcp.api.stats_funnel import router as stats_funnel_router
from jpintel_mcp.api.subscribers import router as subscribers_router
from jpintel_mcp.api.tax_rulesets import router as tax_rulesets_router
from jpintel_mcp.api.testimonials import (
    admin_router as testimonials_admin_router,
)
from jpintel_mcp.api.testimonials import (
    me_router as testimonials_me_router,
)
from jpintel_mcp.api.testimonials import (
    public_router as testimonials_public_router,
)
from jpintel_mcp.api.transparency import router as transparency_router
from jpintel_mcp.api.trust import router as trust_router
from jpintel_mcp.api.usage import router as usage_router
from jpintel_mcp.api.widget_auth import router as widget_router
from jpintel_mcp.config import settings
from jpintel_mcp.db.session import init_db
from jpintel_mcp.security.pii_redact import redact_pii

# ── Query telemetry ────────────────────────────────────────────────────────
# Structured JSON lines emitted to stdout via "autonomath.query" logger.
# No PII: only keys (not values) are logged; free-text is reduced to length
# and script-language heuristic.  Logging failure never blocks responses.
_query_log = logging.getLogger("autonomath.query")


def _detect_lang(text: str) -> str:
    """Return 'ja', 'en', or 'mixed' based on CJK character ratio."""
    if not text:
        return "en"
    cjk = sum(
        1
        for ch in text
        if unicodedata.category(ch) in ("Lo",) and "⺀" <= ch <= "鿿"
    )
    ratio = cjk / len(text)
    if ratio > 0.5:
        return "ja"
    if ratio > 0.1:
        return "mixed"
    return "en"


def _params_shape(request: Request) -> dict:
    """Return {key: True} for every query param present (no values)."""
    # True values (not None) so downstream log consumers can tell param was
    # present vs absent without inspecting the value. C420 does not apply here.
    shape: dict = {k: True for k in request.query_params}  # noqa: C420
    # Include q_len and q_lang when a free-text query is present.
    q = request.query_params.get("q")
    if q:
        shape["q_len"] = len(q)
        shape["q_lang"] = _detect_lang(q)
    return shape


def _emit_query_log(
    *,
    channel: str,
    endpoint: str,
    params_shape: dict,
    result_count: int,
    latency_ms: int,
    status: int | str,
    error_class: str | None,
) -> None:
    try:
        # INV-21: Defense-in-depth PII redaction. `params_shape` is supposed
        # to carry only keys + scalar metadata (q_len / q_lang), never raw
        # values, but a future endpoint that forgets that contract must not
        # leak 法人番号 / email / 電話 into telemetry. `endpoint` itself is
        # also passed through `redact_pii` because path params can carry
        # T-numbers (e.g. /v1/invoice_registrants/T8010001213708).
        # See `feedback_no_fake_data` + `analysis_wave18/.../INV-21`.
        record = {
            "ts": datetime.now(UTC).isoformat(),
            "channel": channel,
            "endpoint": redact_pii(endpoint),
            "params_shape": redact_pii(params_shape),
            "result_count": result_count,
            "latency_ms": latency_ms,
            "status": status,
            "error_class": error_class,
        }
        _query_log.info(json.dumps(record, ensure_ascii=False))
    except Exception:
        # Never block the response on telemetry failure.
        pass


# ── End query telemetry helpers ────────────────────────────────────────────

# Module-level readiness flag flipped True once lifespan startup completes.
# Drives /readyz so Fly's health check can distinguish "alive but not ready"
# (migrations / init_db still running) from "ready to serve traffic".
_ready: bool = False


def _init_sentry() -> None:
    # Two-gate init: (a) DSN present (no-op in CI / dev without SENTRY_DSN),
    # (b) JPINTEL_ENV=prod (silences staging / dev / test even when an
    # operator forgets to scope a SENTRY_DSN secret per environment).
    # See docs/observability.md "Sentry 設定手順". Both gates needed: a
    # mis-scoped DSN in dev would otherwise pollute prod issue counts and
    # quota, breaking the P1-5 alert rule.
    if not settings.sentry_dsn:
        return
    if os.getenv("JPINTEL_ENV", "dev") != "prod":
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        from jpintel_mcp.api.sentry_filters import (
            sentry_before_send,
            sentry_before_send_transaction,
        )
    except ImportError:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        send_default_pii=False,
        # Never attach local-variable snapshots on stack frames — they can
        # capture X-API-Key values from dependency resolution frames,
        # Stripe-Signature from webhook handlers, etc. The request context
        # already gives us enough to triage without leaking the raw material.
        include_local_variables=False,
        max_breadcrumbs=50,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        before_send=sentry_before_send,
        before_send_transaction=sentry_before_send_transaction,
    )


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class _RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        inbound = request.headers.get("x-request-id", "")
        rid = inbound if _REQUEST_ID_RE.fullmatch(inbound) else secrets.token_hex(8)
        # Stash on request.state so downstream exception handlers can read
        # the SAME id that was generated here. Reading
        # `request.headers["x-request-id"]` in the 5xx handler returns
        # "unknown" when the client did not supply one — that's the original
        # bug: every internally-generated id was lost on the error path.
        request.state.request_id = rid
        clear_contextvars()
        bind_contextvars(
            request_id=rid,
            path=request.url.path,
            method=request.method,
        )
        response: Response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


class _QueryTelemetryMiddleware(BaseHTTPMiddleware):
    """Emit one structured JSON log line per request to 'autonomath.query'.

    Placed AFTER CORS (so we don't log preflight OPTIONS) but BEFORE routers.
    Never blocks the response — logging errors are swallowed silently.
    No PII: query-param values are never logged; only keys are recorded.
    Free-text `q` param reduced to length + language heuristic.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        t0 = time.monotonic()
        error_class: str | None = None
        status: int | str = "error"
        try:
            response: Response = await call_next(request)
            status = response.status_code
        except Exception as exc:
            error_class = type(exc).__name__
            status = "error"
            raise
        finally:
            latency_ms = int((time.monotonic() - t0) * 1000)
            _emit_query_log(
                channel="rest",
                endpoint=request.url.path,
                params_shape=_params_shape(request),
                result_count=0,  # REST: result count not available in middleware
                latency_ms=latency_ms,
                status=status,
                error_class=error_class,
            )
        return response


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/teardown for the API.

    On startup we initialise Sentry, configure logging, and run `init_db()`
    (idempotent — safe on an already-migrated volume). After init_db we run
    two hard-fail integrity gates:
      1) **Aggregator domain assertion**: `programs.source_url` MUST NOT
         contain any banned aggregator domain (noukaweb, hojyokin-portal,
         biz.stayway, stayway.jp, nikkei.com, prtimes.jp, wikipedia.org).
         Past incidents → 詐欺 risk; we refuse to serve traffic if any
         aggregator-sourced row leaked in. See memory: `feedback_no_fake_data`
         and CLAUDE.md "Data hygiene".
      2) **Pepper guard (prod only)**: in `JPINTEL_ENV=prod`, the API-key
         hashing pepper `AUTONOMATH_API_HASH_PEPPER` must be set and not
         the placeholder. Empty / placeholder → log critical + sys.exit(1).
    Only after both pass do we flip `_ready` so `/readyz` starts returning
    200. On shutdown uvicorn's `timeout_graceful_shutdown` (set in `run()`)
    gives in-flight Stripe webhooks up to 30s to drain before the worker dies.
    """
    global _ready
    _init_sentry()
    setup_logging(level=settings.log_level, fmt=settings.log_format)
    init_db()

    logger = logging.getLogger("jpintel.api")

    # ── Pepper guard (prod only) ────────────────────────────────────────
    # In production, refuse to start if the API-key hashing pepper is
    # missing or still the dev placeholder. Hashing keys with a
    # known-public pepper would render every stored hash trivially
    # crackable. Skip in dev/test so local runs don't require setup.
    if os.getenv("JPINTEL_ENV") == "prod":
        _pepper = os.getenv("AUTONOMATH_API_HASH_PEPPER", "")
        if _pepper in ("", "dev-pepper-change-me"):
            logger.critical(
                "FATAL: AUTONOMATH_API_HASH_PEPPER is unset or still the dev "
                "placeholder in prod. Refusing to start. Set a rotated pepper "
                "via `flyctl secrets set AUTONOMATH_API_HASH_PEPPER=...`."
            )
            sys.exit(1)

    # ── Integration-token Fernet key validation ─────────────────────────
    # `INTEGRATION_TOKEN_SECRET` MUST be a valid Fernet key (32-byte
    # url-safe base64) — otherwise every Google Sheets / kintone /
    # Postmark inbound credential read fails with 503 mid-request, which
    # surfaces to the customer dashboard as "operator misconfigured".
    # Catch the misconfiguration at boot in prod so the first 503 never
    # reaches a customer. Dev / test skip this gate (no integrations
    # exercised on local uvicorn). Supports comma-separated MultiFernet
    # rotation list — extra keys decrypt legacy ciphertexts only.
    if os.getenv("JPINTEL_ENV") == "prod":
        _fkey = os.getenv("INTEGRATION_TOKEN_SECRET", "").strip()
        if _fkey:
            try:
                from cryptography.fernet import Fernet, MultiFernet

                _candidates = [k.strip() for k in _fkey.split(",") if k.strip()]
                if len(_candidates) == 1:
                    Fernet(_candidates[0].encode("utf-8"))
                else:
                    MultiFernet([
                        Fernet(k.encode("utf-8")) for k in _candidates
                    ])
            except Exception as _exc:  # noqa: BLE001
                logger.critical(
                    "FATAL: INTEGRATION_TOKEN_SECRET is set but is not a valid "
                    "Fernet key (32-byte url-safe base64). Refusing to start. "
                    "Generate via `python -c 'from cryptography.fernet import "
                    "Fernet;print(Fernet.generate_key().decode())'`. exc=%s",
                    type(_exc).__name__,
                )
                sys.exit(1)

    # ── Aggregator domain integrity assertion ───────────────────────────
    # Hard-fail the boot if any banned aggregator domain shows up in
    # programs.source_url. We never serve traffic on tainted data —
    # silent "warn but continue" is wrong here.
    from jpintel_mcp.db.session import connect

    banned_aggregator_domains = [
        "noukaweb",
        "hojyokin-portal",
        "biz.stayway",
        "stayway.jp",
        "nikkei.com",
        "prtimes.jp",
        "wikipedia.org",
    ]
    with connect() as _con:
        for _domain in banned_aggregator_domains:
            _count = _con.execute(
                "SELECT COUNT(*) FROM programs WHERE source_url LIKE ?",
                (f"%{_domain}%",),
            ).fetchone()[0]
            if _count > 0:
                raise RuntimeError(
                    f"FATAL: Banned aggregator '{_domain}' found in {_count} "
                    f"programs.source_url. Refusing to serve traffic. "
                    f"(memory: feedback_no_fake_data + CLAUDE.md)"
                )
    logger.info(
        "aggregator_integrity_pass",
        extra={
            "banned_domains_checked": len(banned_aggregator_domains),
            "matches": 0,
        },
    )

    # ── Durable background-task worker (migration 060) ──────────────────
    # FastAPI BackgroundTasks live in process memory. A SIGTERM between
    # `add_task` and execution drops the side-effect silently — for the
    # D+0 welcome (raw API key, one-time view) that translates to a paid
    # customer never seeing their key. We spawn an asyncio worker here
    # that drains `bg_task_queue` rows; the migrated callers in `me.py`
    # and `billing.py` enqueue durably instead of using BackgroundTasks
    # for those side-effects. Worker logs everything; never crashes.
    from jpintel_mcp.api._bg_task_worker import run_worker_loop

    _bg_stop = asyncio.Event()
    _bg_task = asyncio.create_task(
        run_worker_loop(_bg_stop), name="bg_task_worker"
    )

    _ready = True
    try:
        yield
    finally:
        _ready = False
        # Cooperative shutdown. Worker checks `_bg_stop` between polls so
        # this returns within POLL_INTERVAL_S (2s) under the 30s graceful
        # shutdown budget set in `run()`.
        _bg_stop.set()
        try:
            await asyncio.wait_for(_bg_task, timeout=10.0)
        except (TimeoutError, asyncio.CancelledError):
            _bg_task.cancel()
        except Exception:  # pragma: no cover — defensive
            logger.exception("bg_task_worker_shutdown_error")


def create_app() -> FastAPI:
    app = FastAPI(
        title="AutonoMath",
        version=__version__,
        description=(
            "AutonoMath is a Japanese public-program intelligence API + MCP "
            "server. It exposes a single retrieval surface over **10,790 "
            "補助金 / 融資 / 税制 / 認定** programs (tier S/A/B/C searchable; "
            "1,923 tier-X rows are quarantined and not returned), **2,286 "
            "採択事例 (case studies)**, **108 融資 (loan products)** decomposed "
            "across the three risk axes (担保 / 個人保証人 / 第三者保証人), "
            "**1,185 行政処分 (enforcement cases)**, **9,484 laws** (e-Gov, "
            "CC-BY 4.0), **35 税務判定ルールセット (tax rulesets)**, **2,065 "
            "court decisions (判例)**, **362 bids (入札)**, and **13,801 "
            "適格請求書発行事業者 (NTA invoice registrants, PDL v1.0)**. Every row "
            "carries a primary-source URL + fetched_at timestamp.\n\n"
            "## Who this is for\n\n"
            "Built for LLM agents (Claude / ChatGPT / Perplexity / Cursor) "
            "and developers building Japanese-business automation. Use cases:\n"
            "- discover candidate 補助金 / 助成金 by region + industry + amount\n"
            "- check whether a 法人番号 is a registered 適格請求書発行事業者\n"
            "- look up the current 税務判定ルールセット (e.g. 2割特例, "
            "電子帳簿保存法) and evaluate caller-supplied 事業者プロファイル against it\n"
            "- pull 採択事例 (real awarded grants) for prior-art research\n"
            "- check 行政処分 history before extending credit / awarding "
            "subsidy\n"
            "- read e-Gov 法令 articles and trace which programs cite them\n\n"
            "## Information lookup, not professional advice (税理士法 §52)\n\n"
            "**This API returns information retrieved from public Japanese "
            "government sources. It is NOT 税務助言 (tax advice), NOT 法律相談 "
            "(legal advice), and NOT a substitute for 士業 (税理士 / 弁護士 / "
            "社労士 / 行政書士) consultation.** Every `/v1/am/*` and `/v1/tax_*` "
            "response carries an explicit `_disclaimer` envelope key making "
            "this fence machine-readable. LLM agents relaying this data to "
            "end users MUST surface the disclaimer.\n\n"
            "## Quickstart\n\n"
            "Anonymous (no auth, **3 req/日 per IP**, JST 翌日 00:00 リセット):\n"
            "```bash\n"
            "curl 'https://api.jpcite.com/v1/programs/search?q=IT導入&limit=5'\n"
            "```\n\n"
            "Authenticated (¥3/req metered, 税込 ¥3.30, no tier SKUs, no "
            "minimums) — pass `X-API-Key: sk_...` issued via Stripe Checkout:\n"
            "```bash\n"
            "curl -H 'X-API-Key: sk_live_...' "
            "'https://api.jpcite.com/v1/programs/search?q=DX&prefecture=東京都&tier=S'\n"
            "```\n\n"
            "## Pagination + envelopes\n\n"
            "- All search endpoints share `{total, limit, offset, results[]}` "
            "shape with `limit<=100` (default 20).\n"
            "- Search responses returning data sourced from PDL v1.0 (NTA "
            "invoice registrants) carry an `attribution` block — required by "
            "the license. Do not strip it.\n"
            "- `/v1/am/*` and `/v1/tax_rulesets/*` carry `_disclaimer` "
            "(税理士法 §52 fence) — relay verbatim.\n\n"
            "## Operator\n\n"
            "Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708), 代表 梅田茂利, "
            "info@bookyou.net. Canonical site: https://jpcite.com. "
            "MCP package: `pip install autonomath-mcp` (PyPI). "
            "MCP exposes 69 tools at default gates (39 jpintel + 30 "
            "autonomath; protocol 2025-06-18).\n\n"
            "---\n\n"
            "## 日本語要約 (JP summary)\n\n"
            "AutonoMath (税務会計AI) は **10,790 件の補助金 / 融資 / 税制 / 認定** "
            "(tier S/A/B/C のみ検索対象、tier X 1,923 件は品質保留)、**2,286 件の"
            "採択事例**、**108 件の融資商品** (担保 / 個人保証人 / 第三者保証人 "
            "三軸分解)、**1,185 件の行政処分**、**9,484 件の法令** (e-Gov / "
            "CC-BY 4.0)、**35 件の税務判定ルールセット**、**2,065 件の判例**、"
            "**362 件の入札案件**、**13,801 件の適格請求書発行事業者 (国税庁 / PDL "
            "v1.0)** を、REST + MCP の単一検索面で公開する API です。各レコードは "
            "一次情報源 URL と取得時刻 (`source_url` / `fetched_at`) を保持しています。\n\n"
            "**用途:** LLM エージェント (Claude / ChatGPT / Perplexity / Cursor) と"
            "日本企業向け業務自動化開発者向け。地域 × 業種 × 金額の補助金候補抽出、"
            "13 桁 法人番号 → 適格請求書発行事業者 登録確認、税務判定ルール適用判断、"
            "採択事例の事前研究、行政処分歴の与信前 DD、e-Gov 法令の条文参照、等。\n\n"
            "**税理士法 §52 fence:** 本 API は公的情報の検索結果を返すサービスで、"
            "**税務助言・法律相談・士業 (税理士 / 弁護士 / 社労士 / 行政書士) 業務の"
            "代替ではありません**。`/v1/am/*` および `/v1/tax_*` の各レスポンスは "
            "`_disclaimer` キーをもち、機械可読な形でこの境界を表明しています。LLM "
            "エージェントは end user に情報を中継する際、`_disclaimer` を必ず併示"
            "してください。\n\n"
            "**料金体系:** 認証なし (匿名) は IP あたり 3 リクエスト / 日 (JST 翌日 "
            "00:00 リセット)、有料は ¥3 / リクエスト 完全従量 (税込 ¥3.30)。"
            "tier 課金・座席課金・年契約最低料金はありません。Stripe Checkout で "
            "発行した `X-API-Key: sk_...` を Authorization header に設定してください。\n\n"
            "**運営者:** Bookyou株式会社 (適格請求書発行事業者番号 T8010001213708 / 代表 梅田茂利 / "
            "info@bookyou.net / 東京都文京区小日向2-22-1)。商号: 税務会計AI。"
            "公式サイト: https://jpcite.com/."
        ),
        lifespan=_lifespan,
        openapi_url="/v1/openapi.json",
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "X-API-Key",
            "Content-Type",
            "X-Request-ID",
            "X-CSRF-Token",
            "X-Client-Tag",
            "Stripe-Signature",
            "X-Postmark-Webhook-Signature",
            # IETF Idempotency-Key (draft-ietf-httpapi-idempotency-key-header).
            # Used by /v1/me/clients/bulk_evaluate (commit=true) and the
            # kintone integration POST. Without it on the allowlist, browser-
            # side preflight rejects the header and the dashboard's retry UI
            # cannot send the dedup token alongside the POST body.
            "Idempotency-Key",
        ],
        max_age=3600,
    )
    # Wave 16 P1: hard origin enforcement. Starlette's CORSMiddleware only
    # strips the Access-Control-Allow-Origin header on a non-whitelisted
    # origin — the request still reaches the handler. OriginEnforcement
    # short-circuits with 403 BEFORE any DB write or Stripe API call.
    # Same-origin (no Origin header) and webhook callers are passed through.
    app.add_middleware(OriginEnforcementMiddleware)
    # P2.6.5 browser hardening: HSTS (1y, includeSubDomains, preload),
    # CSP (default-src 'self' + frame-ancestors 'none'), X-Frame-Options
    # DENY, X-Content-Type-Options nosniff, Referrer-Policy
    # strict-origin-when-cross-origin, Permissions-Policy
    # geolocation/microphone/camera blocked. See
    # api/middleware/security_headers.py docstring. DNSSEC + HSTS preload
    # registry submission are domain-side actions (Cloudflare dashboard +
    # hstspreload.org), tracked in
    # docs/_internal/autonomath_com_dns_runbook.md.
    app.add_middleware(SecurityHeadersMiddleware)
    # Legacy host deprecation (api.zeimu-kaikei.ai → api.jpcite.com).
    # Stamps RFC 8594 `Deprecation: true` + RFC 9745 `Sunset: <date>` +
    # RFC 8288 `Link: <successor>; rel="successor-version"` on every
    # response served via the legacy hostname. Both hostnames continue
    # to point at the same Fly app indefinitely; the headers are a
    # client-side migration hint, not a hard cutover. Body and status
    # code are untouched. Added near SecurityHeadersMiddleware (also a
    # pure response-header stamper) so it sees the final response after
    # router + downstream middleware have produced it. See
    # `docs/_internal/api_domain_migration.md` for the migration plan.
    app.add_middleware(HostDeprecationMiddleware)
    # INV-22: 景表法 keyword block on JSON responses. Runs INSIDE security
    # headers so the sanitized body is what receives `x-content-sanitized`
    # and CSP. False-positive budget < 1% (negation contexts whitelisted
    # — see api/response_sanitizer.py docstring).
    app.add_middleware(ResponseSanitizerMiddleware)
    app.add_middleware(_RequestContextMiddleware)
    # Deprecation observability (2026-04-29): tags hits to routes flagged
    # `deprecated=True` (OpenAPI canonical) OR responses carrying RFC 8594
    # `Deprecation` / RFC 9745 `Sunset` headers. Emits to Sentry via
    # safe_capture_message(metric="api.deprecation.hit", level="warning",
    # route=<path>) — consumed by the `deprecated_endpoint_hit` rule in
    # monitoring/sentry_alert_rules.yml (threshold 100/7d, weekly digest).
    # Sentry-only: short-circuits to no-op when SENTRY_DSN unset (dev/CI).
    # Added INSIDE _RequestContextMiddleware so request-id binding has
    # already happened, OUTSIDE rate-limit / cap so a deprecated-hit that
    # gets 429'd or 503'd does not tag the metric (only successful or
    # handler-routed responses count toward the deprecation budget).
    app.add_middleware(DeprecationWarningMiddleware)
    # S3 friction removal (2026-04-25): every anonymous response carries
    # X-Anon-Quota-Remaining + X-Anon-Quota-Reset + X-Anon-Upgrade-Url so
    # an LLM caller (or its human in the loop) sees the upgrade path
    # *before* hitting the 3/日 ceiling. Authed callers are skipped to
    # avoid noise. Reads request.state.anon_quota set by AnonIpLimitDep;
    # routes without that dep (e.g. /healthz) silently get no anon
    # headers — same exemption posture as the dep itself.
    app.add_middleware(AnonQuotaHeaderMiddleware)
    # X-Client-Tag attribution (税理士 顧問先 invoice line-item passthrough).
    # Stashes a validated tag onto request.state.client_tag (or None) so
    # log_usage can persist it into usage_events.client_tag (migration 085).
    # Cheap pass-through middleware — ~22 LOC, no DB read, never blocks.
    # Added BEFORE CustomerCap so a cap-rejected request can still
    # forward-attribute its cap-reached telemetry (none today, but the
    # ordering keeps options open).
    app.add_middleware(ClientTagMiddleware)
    # P3-W customer self-cap: short-circuit with 503 + cap_reached:true once
    # month-to-date billable spend (¥3/req) reaches the customer's
    # `monthly_cap_yen`. Runs after request-id binding so logged 503s carry
    # the request id, but before telemetry so a cap-rejection is logged with
    # the full latency. Anonymous callers (no X-API-Key) are skipped.
    app.add_middleware(CustomerCapMiddleware)
    # D9 burst throttle: 10 req/s per paid key, 1 req/s per anon IP. Sits
    # OUTSIDE the cap middleware (added later → wraps cap) so a 429 never
    # records a usage_events row. Whitelists /healthz, /readyz, Stripe
    # webhook, and OPTIONS preflight. See api/middleware/rate_limit.py.
    app.add_middleware(RateLimitMiddleware)
    # P0 per-IP, per-endpoint, per-minute cap (audit a7388ccfd9ed7fb8c).
    # Sliding 60s window: 30 req/min on heavy search endpoints
    # (programs/search, case_studies/search), 60 req/min on single-record
    # reads, 10 req/min on financial endpoints (checkout, billing-portal).
    # Complements the burst gate above (per-second) — this catches the
    # slow-and-steady abuse pattern that stays under 10 req/s but pins
    # SQLite over a minute. Disable via PER_IP_ENDPOINT_LIMIT_DISABLED=1.
    app.add_middleware(PerIpEndpointLimitMiddleware)
    # δ1 strict query: reject undeclared query params with 422 before any
    # DB read. Added AFTER rate-limit so an `unknown_query_parameter` 422
    # is also subject to the burst gate (a malicious caller cannot bypass
    # rate limits by spamming bad query strings); but BEFORE telemetry so
    # the rejected request is still logged with full latency. Closes K4
    # / J10 silent-drop bug where 87% of routes silently dropped unknown
    # keys. Opt-out: JPINTEL_STRICT_QUERY_DISABLED=1.
    app.add_middleware(StrictQueryMiddleware)
    # Telemetry middleware runs outermost (added last = executes first in
    # Starlette's LIFO middleware stack) so it captures the full latency.
    app.add_middleware(_QueryTelemetryMiddleware)
    # P0-10 (2026-04-30): persist EVERY request (auth + anon) to
    # analytics_events for adoption / funnel / feature-coverage dashboards.
    # Sits alongside _QueryTelemetryMiddleware (which only emits stdout
    # JSON lines, never persists). The DB write runs synchronously after
    # call_next on a short-lived connection — failure never blocks the
    # response. Excludes /healthz, /readyz, /openapi.json etc internally.
    # `usage_events` remains the billing ledger; this is orthogonal traffic
    # analytics that captures the 99% anonymous tail `log_usage` cannot
    # reach (key_hash NOT NULL FK on usage_events).
    app.add_middleware(AnalyticsRecorderMiddleware)
    # P0 global kill switch (audit a7388ccfd9ed7fb8c). MUST be added LAST
    # so it executes FIRST in the LIFO stack — a killed app never even
    # runs DB queries / cap bookkeeping for blocked traffic. Allowlists
    # /healthz, /readyz, /v1/am/health/deep, /status, /robots.txt so
    # monitoring + crawler hygiene survive an incident. Operator runbook:
    # docs/_internal/launch_kill_switch.md.
    app.add_middleware(KillSwitchMiddleware)

    _log = logging.getLogger("jpintel.api")

    @app.exception_handler(FileNotFoundError)
    async def _db_missing_handler(request: Request, exc: FileNotFoundError) -> JSONResponse:
        """
        Honest 503 fence when a backing SQLite file is missing on disk.

        autonomath.db on the API server can be 0 bytes / absent when
        AUTONOMATH_DB_URL bootstrap is unset. The /v1/am/* endpoints
        catch sqlite3.OperationalError today, but `connect_autonomath`
        also raises plain FileNotFoundError before any query. Treat
        either path as a clear ``db_unavailable`` instead of the
        previous "sparse 200 + empty result" silent miss (詐欺 risk
        per `feedback_autonomath_fraud_risk`).
        """
        rid = safe_request_id(request)
        if rid == "unset":
            rid = secrets.token_hex(8)
        path_str = str(request.url.path)
        is_am = path_str.startswith("/v1/am/")
        _log.warning(
            "db_missing path=%s is_am=%s err=%s rid=%s",
            path_str, is_am, exc, rid,
        )
        canonical = make_error(
            code="db_unavailable",
            request_id=rid,
            path=path_str,
            method=request.method,
        )
        return JSONResponse(
            status_code=503,
            content=canonical,
            headers={"x-request-id": rid, "Retry-After": "300"},
        )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            raise exc
        # Prefer the id stamped onto `request.state` by
        # `_RequestContextMiddleware` (covers BOTH client-supplied
        # `x-request-id` and our `secrets.token_hex(8)` fallback). Header
        # lookup returns None for the auto-generated case → the literal
        # "unknown" leaked into prod 5xx bodies before this fix (J5).
        rid = safe_request_id(request)
        if rid == "unset":
            # Last-ditch: synthesise so the user has SOMETHING actionable
            # even if every upstream layer failed. This branch is only hit
            # when the request bypassed _RequestContextMiddleware (very
            # rare — typically a startup-error raise).
            rid = secrets.token_hex(8)
        _log.exception(
            "unhandled exception request_id=%s path=%s", rid, request.url.path
        )
        # Back-compat shape: keep "detail" + "request_id" at the root for
        # callers that already pattern-match on those keys (test_error_handler
        # asserts this), AND attach the canonical δ envelope under "error".
        legacy = {"detail": "internal server error", "request_id": rid}
        canonical = make_error(
            code="internal_error",
            request_id=rid,
            path=request.url.path,
            method=request.method,
        )
        legacy.update(canonical)
        return JSONResponse(
            status_code=500,
            content=legacy,
            headers={"x-request-id": rid},
        )

    # Custom 429 handler for the anon rate limit — emits the flat body
    # `{"detail": "...", "limit": ..., "resets_at": "..."}` at the root
    # level instead of FastAPI's default `{"detail": ...}` envelope.
    app.add_exception_handler(
        _AnonRateLimitExceeded, anon_rate_limit_exception_handler
    )

    # Pydantic's default 422 body is English-only. Translate common
    # constraint types to Japanese via a `msg_ja` field tacked onto each
    # error entry, and add a JP summary at the envelope root. The original
    # `msg` / `type` / `loc` fields stay intact for programmatic clients.
    _msg_ja = {
        "value_error.missing": "必須項目です",
        "missing": "必須項目です",
        "string_too_short": "文字列が短すぎます",
        "string_too_long": "文字列が長すぎます",
        "greater_than": "値が下限を下回っています",
        "greater_than_equal": "値が下限を下回っています",
        "less_than": "値が上限を超えています",
        "less_than_equal": "値が上限を超えています",
        "int_parsing": "整数を指定してください",
        "float_parsing": "数値を指定してください",
        "bool_parsing": "真偽値 (true/false) を指定してください",
        "type_error.integer": "整数を指定してください",
        "type_error.float": "数値を指定してください",
        "value_error": "値が不正です",
        "enum": "許可された値ではありません",
        "literal_error": "許可された値ではありません",
        "url_parsing": "URL 形式が不正です",
        "datetime_parsing": "日時形式が不正です",
        "date_parsing": "日付形式が不正です",
        "json_invalid": "JSON 形式が不正です",
        "extra_forbidden": "許可されていないフィールドです",
        "string_pattern_mismatch": "形式が一致しません",
    }

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors_en = exc.errors()
        errors_ja = [
            {**e, "msg_ja": _msg_ja.get(e.get("type"), e.get("msg"))}
            for e in errors_en
        ]
        # δ2: attach the canonical {"error": {...}} envelope alongside the
        # back-compat `detail` / `detail_summary_ja` keys so tooling can
        # opt into the structured shape without breaking existing callers.
        canonical = make_error(
            code="invalid_enum",
            request_id=safe_request_id(request),
            field_errors=errors_ja,
            path=request.url.path,
            method=request.method,
        )
        body = {
            "detail": errors_ja,
            "detail_summary_ja": (
                "入力検証に失敗しました。各フィールドのエラーを確認してください。"
            ),
        }
        body.update(canonical)
        return JSONResponse(status_code=422, content=body)

    # δ3: structured envelope for HTTPException(401 / 404 / 405 / 503).
    # FastAPI's default body is `{"detail": "..."}` which gives an LLM
    # caller no machine-readable code. We keep `detail` for back-compat
    # but attach the canonical envelope under `error`. Anon-rate-limit
    # 429 (_AnonRateLimitExceeded) has its own dedicated handler that
    # already emits a flat structured body; we do NOT touch that path.
    #
    # Registering against StarletteHTTPException (the parent class of
    # FastAPI's HTTPException) so the unknown-route 404 emitted by the
    # router itself — which raises Starlette's plain HTTPException, not
    # FastAPI's subclass — also gets the structured shape.
    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # Anon rate limit short-circuit — its handler already runs because
        # the more-specific subclass match wins; but defensively if the
        # generic Exception handler ever re-raises HTTPException, fall
        # through to the dedicated body shape.
        if isinstance(exc, _AnonRateLimitExceeded):
            return anon_rate_limit_exception_handler(request, exc)

        rid = safe_request_id(request)
        status_code = exc.status_code

        # Map status -> code; default falls through to a generic shape.
        if status_code == 401:
            code = "auth_required"
        elif status_code == 403:
            code = "auth_invalid"
        elif status_code == 404:
            code = "route_not_found"
        elif status_code == 405:
            code = "method_not_allowed"
        elif status_code == 429:
            code = "rate_limit_exceeded"
        elif status_code == 503:
            code = "service_unavailable"
        else:
            # Pass non-mapped HTTPException bodies through unchanged so
            # we don't steamroll richly-shaped 4xx bodies emitted from
            # individual routers (e.g. Stripe webhook 400, prescreen
            # validation). The router author already chose a body shape.
            return JSONResponse(
                status_code=status_code,
                content={"detail": exc.detail},
                headers=getattr(exc, "headers", None) or {},
            )

        extras: dict[str, Any] = {}
        # Preserve detail when it is something useful (string or dict),
        # so the structured envelope can carry it without losing prior
        # context (cap-reached body, custom 503 detail, etc.).
        if isinstance(exc.detail, dict):
            for k, v in exc.detail.items():
                if k not in {"code", "user_message", "request_id"}:
                    extras[k] = v
        elif exc.detail and exc.detail not in {
            "Not Found", "Method Not Allowed", "Unauthorized", "Forbidden",
        }:
            extras["detail"] = exc.detail

        if status_code == 404:
            # Suggest a couple of canonical entry points so an LLM caller
            # has somewhere to bounce off when it guesses a wrong path.
            extras.setdefault(
                "suggested_paths",
                [
                    "/v1/openapi.json",
                    "/v1/programs/search",
                    "/v1/meta",
                    "/v1/stats/coverage",
                ],
            )
            extras.setdefault("path", request.url.path)
        elif status_code == 401:
            extras.setdefault(
                "retry_with",
                {"header": "X-API-Key", "alt_header": "Authorization: Bearer"},
            )
        elif status_code == 503:
            # Surface Retry-After value into the envelope so an LLM that
            # ignores headers still sees the wait hint.
            ra = (getattr(exc, "headers", None) or {}).get("Retry-After")
            if ra:
                extras.setdefault("retry_after", int(ra) if str(ra).isdigit() else ra)

        canonical = make_error(code=code, request_id=rid, **extras)
        body = {"detail": exc.detail}
        body.update(canonical)
        return JSONResponse(
            status_code=status_code,
            content=body,
            headers=getattr(exc, "headers", None) or {},
        )

    # Back-compat: serve the OpenAPI spec at /openapi.json too, 308 -> /v1/.
    @app.get("/openapi.json", include_in_schema=False)
    async def _openapi_legacy_redirect() -> RedirectResponse:
        return RedirectResponse(url="/v1/openapi.json", status_code=308)

    # Router wiring. AnonIpLimitDep is attached only to routers whose
    # routes accept anonymous callers and should count toward the per-IP
    # quota. Excluded deliberately:
    #   - meta_router: contains /healthz (liveness) — route-level dep only
    #     on /meta and /v1/ping instead (see api/meta.py).
    #   - billing_router: /v1/billing/webhook is Stripe; others (checkout,
    #     portal, keys/from-checkout) are not discoverability calls.
    #   - subscribers_router: /v1/subscribers/unsubscribe must stay usable
    #     from email links; the POST has its own in-memory bucket.
    #   - me_router: dashboard session endpoints; CSRF-adjacent — leave
    #     untouched.
    #   - admin_router: internal only.
    #   - feedback_router: users hitting the anon 3/day per-IP cap MUST
    #     still be able to tell us the API is broken. The feedback endpoint
    #     has its own 10/day per-IP-hash limiter (see api/feedback.py), so
    #     removing the global dep doesn't open a spam vector.
    app.include_router(meta_router)
    # Public anti-詐欺 transparency endpoint (/v1/meta/freshness). No auth, no
    # AnonIpLimitDep — same posture as /healthz; serves aggregated freshness
    # stats so customers/agents can verify data is fresh enough for purpose.
    app.include_router(meta_freshness_router)
    # Trust-signal pages backend (/v1/am/data-freshness +
    # /v1/am/programs/{id}/sources). Same public posture as
    # meta_freshness_router — these are anti-詐欺 transparency surfaces
    # that must always answer (uptime monitor / static page polling).
    # Mounted WITHOUT AnonIpLimitDep so polling the freshness page from
    # the browser does not burn the 3/日 anonymous quota.
    app.include_router(transparency_router)
    # Trust 8-pack (migration 101 — corrections, SLA, cross-source, staleness,
    # §52 audit rollup). All read endpoints public + unmetered, same posture
    # as transparency_router. POST /v1/corrections has its own per-day
    # idempotency dedup so we do NOT wrap the router with AnonIpLimitDep
    # (a customer reporting a data bug must always be able to do so).
    # See src/jpintel_mcp/api/trust.py for the surface inventory.
    app.include_router(trust_router)
    # Public stats endpoints (P5-ι, brand 5-pillar 透明・誠実 / anti-aggregator).
    # /v1/stats/coverage + /v1/stats/freshness + /v1/stats/usage. No auth, no
    # AnonIpLimitDep — same transparency posture as meta_freshness. Cached
    # 5 minutes in-process to absorb landing-page traffic spikes.
    app.include_router(stats_router)
    # /v1/stats/funnel — operator-only live funnel (admin-key gated, hidden
    # from openapi). Distinct from /v1/admin/funnel which reads the
    # precomputed funnel_daily rollup; this one computes off raw tables so
    # the operator can see numbers before the rollup catches up.
    app.include_router(stats_funnel_router)
    # P5-attribution: Bayesian Discovery + Use confidence dashboard.
    # /v1/stats/confidence — same transparency posture as the other /stats/*
    # surfaces. 5-min in-memory cache. Per-tool aggregates only (no
    # per-customer breakdown). See docs/confidence_methodology.md.
    app.include_router(confidence_router)
    # Public testimonial list (approved rows only). The submission endpoint
    # under /v1/me/testimonials requires X-API-Key (anti-fake), the moderation
    # endpoints under /v1/admin/testimonials/* require ADMIN_API_KEY.
    app.include_router(testimonials_public_router)
    # /v1/usage — Wave 17 P1 anonymous quota probe. Mounted WITHOUT
    # AnonIpLimitDep on purpose: a "how much quota do I have left" call
    # must be free to make repeatedly, otherwise the probe burns the
    # runway it's meant to report on. See api/usage.py docstring.
    app.include_router(usage_router)
    app.include_router(programs_router, dependencies=[AnonIpLimitDep])
    app.include_router(prescreen_router, dependencies=[AnonIpLimitDep])
    app.include_router(exclusions_router, dependencies=[AnonIpLimitDep])
    app.include_router(enforcement_router, dependencies=[AnonIpLimitDep])
    app.include_router(case_studies_router, dependencies=[AnonIpLimitDep])
    app.include_router(loan_programs_router, dependencies=[AnonIpLimitDep])
    # 015_laws + 016_court_decisions: new statute / 判例 surfaces. No
    # preview gate — both are first-class from launch. Anon-quota-gated
    # like programs/enforcement/etc. so the 3/day per-IP cap applies.
    app.include_router(laws_router, dependencies=[AnonIpLimitDep])
    app.include_router(court_decisions_router, dependencies=[AnonIpLimitDep])
    # 4-dataset expansion (2026-04-24): 入札 (bids) / 税制 ruleset /
    # 適格請求書発行事業者 (invoice registrants). First-class, anon-quota-gated
    # like the other discovery surfaces.
    app.include_router(bids_router, dependencies=[AnonIpLimitDep])
    app.include_router(tax_rulesets_router, dependencies=[AnonIpLimitDep])
    app.include_router(invoice_registrants_router, dependencies=[AnonIpLimitDep])
    # /v1/evidence/packets/* — Evidence Packet composer (LLM-resilient
    # business plan §6). Bundles primary metadata + per-fact provenance +
    # compat-matrix rule verdicts into one envelope. ¥3/req metered;
    # anonymous tier inherits the 50/月 IP cap via AnonIpLimitDep.
    app.include_router(evidence_router, dependencies=[AnonIpLimitDep])
    # /v1/source_manifest/{program_id} — per-program source rollup.
    app.include_router(source_manifest_router, dependencies=[AnonIpLimitDep])
    # /v1/citations/verify — deterministic citation verifier.
    app.include_router(citations_router, dependencies=[AnonIpLimitDep])
    # /v1/cost/preview — Evidence Pre-fetch Layer estimator (no LLM).
    app.include_router(cost_router, dependencies=[AnonIpLimitDep])
    # /v1/intelligence/precomputed/query — compact precomputed context
    # bundle for offline token-cost benchmarking and LLM prefetch flows.
    app.include_router(intelligence_router, dependencies=[AnonIpLimitDep])
    # /v1/funding_stack/check — pure rule engine over compat_matrix + exclusion_rules.
    app.include_router(funding_stack_router, dependencies=[AnonIpLimitDep])
    # /v1/houjin/{bangou} — corporate 360 lookup surfacing 1.12M gBizINFO
    # facts already in autonomath.db (am_entities corporate_entity +
    # am_entity_facts corp.*). Same anon-quota posture as the other
    # discovery surfaces — 3/日 per-IP cap applies.
    app.include_router(houjin_router, dependencies=[AnonIpLimitDep])
    # /v1/calendar/deadlines is live (activated from preview 2026-04-24).
    # Previously gated behind enable_preview_endpoints; now a first-class
    # discovery surface, so it mounts unconditionally.
    app.include_router(calendar_router, dependencies=[AnonIpLimitDep])
    app.include_router(billing_router)
    # P3.5 Stripe edge cases (refund_request intake live; dispute/tax-exempt/
    # currency/invoice-modification/Stripe-Tax-fallback are dispatched from
    # billing.webhook itself, only the refund_request REST endpoint mounts here).
    from jpintel_mcp.billing.stripe_edge_cases import router as stripe_edge_router

    app.include_router(stripe_edge_router)
    # OAuth 2.0 Device Authorization Grant (RFC 8628). Not anon-quota-gated —
    # the authorize endpoint is the entry point for new callers who don't yet
    # have a key. Rate limiting is handled inside device_flow.py (poll cap).
    app.include_router(device_router)
    # Postmark delivery/bounce/spam webhook. Signature-verified inside the
    # handler; unauthenticated callers never touch the DB.
    app.include_router(email_webhook_router)
    # Master-list email unsubscribe (P2.6.4 / 特電法 §3, migration 072).
    # No AnonIpLimitDep — opt-out must always be reachable, otherwise a
    # rate-limited user cannot honour the legal opt-out path. The HMAC
    # token in the URL is the auth.
    app.include_router(email_unsubscribe_router)
    app.include_router(subscribers_router)
    # Compliance Alerts (¥500/月 法令改正通知 email subscription). No
    # AnonIpLimitDep at the router level: this router includes
    # /v1/compliance/stripe-webhook which Stripe-originating IPs would
    # otherwise burn the per-IP 3/日 anon quota for. Per-route signup
    # spam limiting belongs inside compliance.py (follow-up).
    app.include_router(compliance_router)
    # Email-only trial signup (POST /v1/signup, GET /v1/signup/verify).
    # Conversion-pathway audit 2026-04-29 — captures evaluator emails
    # before they bounce. NOT anon-quota-gated: the signup itself burns
    # ZERO of the 3/日 anon quota (filling that bucket would create a
    # perverse incentive to skip signup). Per-IP velocity (1/24h) lives
    # inside signup.py instead.
    app.include_router(signup_router)
    app.include_router(me_router)
    # Tier 2 customer dashboard (P5-iota++, dd_v8_08 C/G). Bearer-authenticated
    # read-only summaries (`/v1/me/dashboard`, `/v1/me/usage_by_tool`,
    # `/v1/me/billing_history`, `/v1/me/tool_recommendation`). Anonymous
    # callers are rejected inside each handler — the router does not get
    # AnonIpLimitDep because dashboard reads should not consume the public
    # 50-req/月 IP quota.
    app.include_router(dashboard_router)
    app.include_router(feedback_router)
    # APPI §31 個人情報開示請求 intake. Anonymous-accessible (a data subject
    # may not be a paid customer); the route itself never emits personal
    # data — it only mints a request_id and notifies the operator. Gated
    # at the env-flag level inside the handler so a flip from "1" → "0"
    # rolls the intake back without redeploying. See P4 audit 2026-04-25.
    if os.getenv("AUTONOMATH_APPI_ENABLED", "1") not in ("0", "false", "False"):
        app.include_router(appi_disclosure_router)
        # APPI §33 個人情報削除請求 intake. Symmetrical to §31 above and
        # gated by the same env flag — flipping to "0" rolls back BOTH
        # intakes. The endpoint never deletes rows; deletion is manual
        # within the §33-3 30-day SLA after operator identity verification.
        app.include_router(appi_deletion_router)
    # Authed testimonial write/delete (X-API-Key required). Submitter can
    # POST one or DELETE their own; rows enter moderation queue (approved_at
    # NULL) until the operator approves them via /v1/admin/testimonials/*.
    app.include_router(testimonials_me_router)
    app.include_router(advisors_router)
    # Tier 3 amendment alerts (P5-ι++ / dd_v8_08 H/I). Authenticated-only,
    # subscription is FREE (no ¥3/req surcharge) — retention feature, not a
    # metered surface. Anonymous callers are 401'd inside the router itself.
    app.include_router(alerts_router)
    # Customer-side outbound webhooks (¥3/req metered, HMAC required).
    # Distinct from alerts_router (FREE retention surface). The dispatcher
    # cron (scripts/cron/dispatch_webhooks.py) emits Stripe usage records
    # only for HTTP 2xx deliveries; failures + retries do not bill. Auto-
    # disable after 5 consecutive failures prevents runaway billing if the
    # customer endpoint goes dark. Migration 080 owns the schema.
    app.include_router(customer_webhooks_router)
    # W3 saved-searches + daily/weekly digest. Authenticated-only CRUD on
    # the calling key's own rows; the cron sweep
    # (scripts/cron/run_saved_searches.py) reports each delivered digest
    # via report_usage_async so deliveries are ¥3/req metered. Subscribe
    # path itself is FREE (it is the customer's own row).
    app.include_router(saved_searches_router)
    # Migration 096 — client_profiles registry for 補助金コンサル fan-out.
    # Authenticated-only CRUD on the calling key's own 顧問先 metadata.
    # CRUD is FREE; the fan-out path (saved_searches × profile_ids) is
    # ¥3-metered by the cron sweep (scripts/cron/run_saved_searches.py).
    # Mounted under /v1/me/client_profiles — no AnonIpLimitDep because
    # the router gates on require_key (anon → 401).
    app.include_router(client_profiles_router)
    # Consultant trigger #1 — CSV bulk eligibility evaluation. Mounted under
    # /v1/me/clients/bulk_evaluate. Cost-preview path is FREE; commit=true
    # bills ¥3 × N rows and returns a ZIP of per-client result CSVs.
    app.include_router(bulk_evaluate_router)
    # Migration 099 — recurring engagement substrate (M5 email courses).
    # Mounted under /v1/me/courses, FREE CRUD on the calling key's own
    # row tree; per-day delivery is ¥3-metered through the cron sweep.
    app.include_router(courses_router)
    # Migration 099 — quarterly PDF + Slack webhook + email_course alias.
    # Mounted under /v1/me/recurring/* (auth required). PDF render is
    # ¥3-metered per generation (cached afterwards so repeat downloads
    # are free). Slack webhook test send is FREE (one-shot at bind time).
    from jpintel_mcp.api.recurring_quarterly import router as recurring_router

    app.include_router(recurring_router)
    # Workflow integrations 5-pack (migration 105):
    #   POST /v1/integrations/slack            slash command (¥3/call)
    #   POST /v1/integrations/slack/webhook    incoming-webhook drop-in
    #   POST /v1/integrations/sheets           Apps Script callback
    #   POST /v1/integrations/google/start     OAuth start (FREE)
    #   GET  /v1/integrations/google/callback  OAuth callback (FREE)
    #   POST /v1/integrations/email/inbound    Postmark inbound parse (¥3)
    #   POST /v1/integrations/email/connect    Mark inbound enabled (FREE)
    #   GET  /v1/integrations/excel            WEBSERVICE cell formula (¥3)
    #   POST /v1/integrations/kintone          plugin-button callback (¥3)
    #   POST /v1/integrations/kintone/connect  bind API token (FREE)
    #   POST /v1/integrations/kintone/sync     daily sync (¥3/call, NOT/row)
    # CRUD/connect endpoints are FREE; each delivery surface bills exactly
    # ¥3 (one row in usage_events per call, regardless of result count —
    # see _bill_one_call). Mounted with AnonIpLimitDep so unauthenticated
    # probes hit the 3/日 IP cap before the route handler runs.
    from jpintel_mcp.api.integrations import router as integrations_router

    app.include_router(integrations_router, dependencies=[AnonIpLimitDep])
    # LINE Messaging API webhook receiver — second product surface for
    # 中小企業 cohort (CLAUDE.md cohort #6). Deterministic state machine,
    # NO LLM call, billing inherits the existing programs.search ¥3
    # event accounting. Mounted WITHOUT AnonIpLimitDep because LINE
    # delivers from a fixed IP range that would burn the 3/日 IP cap
    # within minutes; we apply per-line_user quota inside the handler.
    from jpintel_mcp.api.line_webhook import router as line_webhook_router

    app.include_router(line_webhook_router)
    # Public audit-log explorer (Z3 — am_amendment_diff read surface).
    # Mounted BEFORE the autonomath_router with AnonIpLimitDep so the
    # 3/日 per-IP quota applies. Paid keys (¥3/req) bypass the anon
    # ceiling and bill normally — same as other /v1/am/* endpoints.
    app.include_router(audit_log_router, dependencies=[AnonIpLimitDep])
    # Autonomath REST router exposes the 16 am_* tools at /v1/am/*.
    # Same anonymous IP rate-limit dep as other public endpoints.
    app.include_router(autonomath_router, dependencies=[AnonIpLimitDep])
    # M&A pillar bundle (Wave 22 / 2026-04-29):
    #   POST /v1/am/dd_batch     — 1..200 法人 batch DD (¥3 per id)
    #   GET  /v1/am/group_graph  — 2-hop part_of traversal (¥3 per call)
    #   POST /v1/am/dd_export    — audit-bundle ZIP via signed R2 URL
    #                              (¥3 × N + ¥30 fixed bundle fee — only
    #                              non-¥3 SKU in the system).
    # Same anonymous IP rate-limit dep as other /v1/am/* surfaces; the
    # write paths self-gate on `ctx.key_hash is None` → 401.
    app.include_router(ma_dd_router, dependencies=[AnonIpLimitDep])
    # M&A pillar Pillar 2 — customer-scoped real-time watches at
    # /v1/me/watches/*. Watches register FREE; ¥3 per HTTP 2xx delivery
    # via the existing customer_webhooks dispatcher.
    app.include_router(me_watches_router)
    # 会計士・監査法人 work-paper bundle at /v1/audit/* (POST workpaper +
    # POST batch_evaluate + GET snapshot_attestation). Authenticated-only
    # (audit firms hold paid keys) — handler-level 401 short-circuits
    # anonymous traffic, but we still mount with AnonIpLimitDep so an
    # unauthenticated probe burns the public quota and not free
    # compute.
    app.include_router(audit_router, dependencies=[AnonIpLimitDep])
    # §17.D public seal verifier (GET /v1/audit/seals/{seal_id}). Mounted
    # WITHOUT AnonIpLimitDep so customers can always verify a seal even
    # after the 3/日 anon quota is exhausted; billable=0.
    app.include_router(audit_public_router)
    # Autonomath health probe (10-check aggregate) — same exemption as
    # /healthz / /readyz. Mounted without AnonIpLimitDep so production
    # uptime monitors can poll without burning the 3/日 anonymous quota.
    app.include_router(autonomath_health_router)
    # Widget embed product (¥10,000/月 Business / ¥30,000/月 Whitelabel),
    # mounted at /v1/widget/*. Origin-whitelisted + per-key monthly quota
    # are enforced inside widget_auth.py. NOT anon-quota-gated: widget
    # keys are paid and Cloudflare may NAT browser traffic to a small set
    # of IPs, so AnonIpLimitDep would double-limit a paid customer's
    # entire site to 3/日. CORS preflight is handled per-route to echo
    # back the matched origin from allowed_origins_json.
    app.include_router(widget_router)
    # Admin router is internal-only. Router sets include_in_schema=False so
    # /v1/admin/* is absent from /openapi.json and docs/openapi/v1.json.
    app.include_router(admin_router)
    # Operator KPI dashboard backend (`/v1/admin/kpi`). Same admin-key gate
    # + include_in_schema=False posture as the rest of /v1/admin/*. Mirrors
    # the JSON shape emitted by `scripts/ops_quick_stats.py --json` so the
    # CLI, the dashboard, and the daily email digest all read one source.
    app.include_router(admin_kpi_router)
    # Operator moderation for testimonials (approve / unapprove). Same admin-
    # key gate + include_in_schema=False posture as the rest of /v1/admin/*.
    app.include_router(testimonials_admin_router)

    # Preview / roadmap endpoints (legal, accounting, calendar). Gated behind
    # `settings.enable_preview_endpoints` so:
    #   - default (flag off): routes unmounted -> 404, clean public OpenAPI
    #   - flag on: routes mounted and return HTTP 501 with a roadmap body,
    #     which lets SDK generators + partners see the future contract ahead
    #     of implementation. See `docs/preview_endpoints.md`.
    if settings.enable_preview_endpoints:
        app.include_router(legal_router)
        app.include_router(accounting_router)

    # Readiness probe. Fly's health check hits /healthz (liveness / DB ping);
    # /readyz returns 200 only after lifespan startup has finished, so a
    # load balancer that adds this probe can hold traffic off a machine
    # that is alive-but-still-migrating. Intentionally does NOT touch the
    # DB — that is /healthz's job.
    @app.get("/readyz")
    def readyz() -> JSONResponse:
        if _ready:
            return JSONResponse(status_code=200, content={"status": "ready"})
        return JSONResponse(status_code=503, content={"status": "starting"})

    # OpenAPI customization: inject `servers`, `securitySchemes`, and rich
    # info-section metadata (contact / termsOfService / license) so SDK
    # generators and API explorers (Stainless, Mintlify, Postman) get a
    # complete spec. Without `servers` they default to a relative `/`
    # baseURL; without `securitySchemes` they cannot generate auth wiring.
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=__version__,
            description=app.description,
            routes=app.routes,
        )
        schema["servers"] = [
            {"url": "https://api.jpcite.com", "description": "Production"},
            {"url": "http://localhost:8080", "description": "Local development"},
        ]
        schema.setdefault("components", {})
        schema["components"]["securitySchemes"] = {
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": (
                    "Customer API key issued via Stripe Checkout. "
                    "Anonymous tier (no key) gets 3 req/日 per IP."
                ),
            }
        }
        # Spec-level default security so SDK generators emit auth wiring on
        # every operation. Endpoints that accept anonymous traffic still work
        # without the header; this is a hint to tooling, not a hard gate.
        schema["security"] = [{"ApiKeyAuth": []}]
        # Info-section metadata: contact / ToS / license. Surfaces in
        # generated docs (Stainless, Mintlify, ReDoc) and SDK readmes.
        schema["info"]["contact"] = {
            "name": "AutonoMath Support",
            "email": "info@bookyou.net",
        }
        schema["info"]["termsOfService"] = "https://jpcite.com/terms.html"
        schema["info"]["license"] = {
            "name": "Proprietary - see termsOfService",
        }
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    return app


app = create_app()


def run() -> None:
    # timeout_graceful_shutdown=30: on SIGTERM (rolling deploy, Fly machine
    # replace), uvicorn stops accepting new connections and waits up to 30s
    # for in-flight requests to finish before killing workers. Stripe
    # webhook handlers are the motivating case — dropping one mid-write
    # means a desynced subscription state in SQLite.
    uvicorn.run(
        "jpintel_mcp.api.main:app",
        host="0.0.0.0",
        port=8080,
        reload=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    run()
