import asyncio
import json
import logging
import os
import re
import sys
import time
import unicodedata
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from jpintel_mcp import __version__
from jpintel_mcp.api._error_envelope import make_error, safe_request_id
from jpintel_mcp.api.accounting import router as accounting_router
from jpintel_mcp.api.admin import router as admin_router
from jpintel_mcp.api.admin_kpi import router as admin_kpi_router
from jpintel_mcp.api.advisors import router as advisors_router
from jpintel_mcp.api.alerts import router as alerts_router
from jpintel_mcp.api.amendment_alerts import router as amendment_alerts_router
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
from jpintel_mcp.api.benchmark import router as benchmark_router
from jpintel_mcp.api.bids import router as bids_router
from jpintel_mcp.api.billing import router as billing_router
from jpintel_mcp.api.billing_breakdown import router as billing_breakdown_router
from jpintel_mcp.api.bulk_evaluate import router as bulk_evaluate_router
from jpintel_mcp.api.calendar import router as calendar_router
from jpintel_mcp.api.case_cohort_match import router as case_cohort_match_router
from jpintel_mcp.api.case_studies import router as case_studies_router
from jpintel_mcp.api.citation_badge import router as citation_badge_router
from jpintel_mcp.api.citations import router as citations_router
from jpintel_mcp.api.client_profiles import router as client_profiles_router
from jpintel_mcp.api.compliance import router as compliance_router
from jpintel_mcp.api.confidence import router as confidence_router
from jpintel_mcp.api.contribute import router as contribute_router
from jpintel_mcp.api.corporate_form import router as corporate_form_router
from jpintel_mcp.api.cost import router as cost_router
from jpintel_mcp.api.courses import router as courses_router
from jpintel_mcp.api.court_decisions import router as court_decisions_router
from jpintel_mcp.api.customer_webhooks import router as customer_webhooks_router
from jpintel_mcp.api.dashboard import router as dashboard_router
from jpintel_mcp.api.device_flow import router as device_router
from jpintel_mcp.api.disaster import router as disaster_router
from jpintel_mcp.api.discover import router as discover_router
from jpintel_mcp.api.eligibility_check import router as eligibility_check_router
from jpintel_mcp.api.email_unsubscribe import router as email_unsubscribe_router
from jpintel_mcp.api.email_webhook import router as email_webhook_router
from jpintel_mcp.api.enforcement import router as enforcement_router
from jpintel_mcp.api.evidence import router as evidence_router
from jpintel_mcp.api.exclusions import router as exclusions_router
from jpintel_mcp.api.feedback import router as feedback_router
from jpintel_mcp.api.funding_stack import router as funding_stack_router
from jpintel_mcp.api.funding_stage import router as funding_stage_router
from jpintel_mcp.api.funnel_events import router as funnel_events_router
from jpintel_mcp.api.houjin import router as houjin_router
from jpintel_mcp.api.intelligence import router as intelligence_router
from jpintel_mcp.api.invoice_registrants import router as invoice_registrants_router
from jpintel_mcp.api.invoice_risk import (
    houjin_invoice_router as invoice_risk_houjin_router,
)
from jpintel_mcp.api.invoice_risk import (
    router as invoice_risk_router,
)
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
    CostCapMiddleware,
    CustomerCapMiddleware,
    DeprecationWarningMiddleware,
    EnvelopeAdapterMiddleware,
    HostDeprecationMiddleware,
    IdempotencyMiddleware,
    KillSwitchMiddleware,
    LanguageResolverMiddleware,
    OriginEnforcementMiddleware,
    PerIpEndpointLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    StaticManifestCacheMiddleware,
    StrictQueryMiddleware,
)
from jpintel_mcp.api.middleware.origin_enforcement import _MUST_INCLUDE
from jpintel_mcp.api.openapi_agent import build_agent_openapi_schema
from jpintel_mcp.api.policy_upstream import router as policy_upstream_router
from jpintel_mcp.api.prescreen import router as prescreen_router
from jpintel_mcp.api.programs import router as programs_router
from jpintel_mcp.api.regions import router as regions_router
from jpintel_mcp.api.response_sanitizer import ResponseSanitizerMiddleware
from jpintel_mcp.api.saved_searches import router as saved_searches_router
from jpintel_mcp.api.signup import router as signup_router
from jpintel_mcp.api.source_manifest import router as source_manifest_router
from jpintel_mcp.api.stats import router as stats_router
from jpintel_mcp.api.stats_funnel import router as stats_funnel_router
from jpintel_mcp.api.subscribers import router as subscribers_router
from jpintel_mcp.api.succession import router as succession_router
from jpintel_mcp.api.tax_chain import router as tax_chain_router
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
from jpintel_mcp.api.time_machine import router as time_machine_router
from jpintel_mcp.api.transparency import router as transparency_router
from jpintel_mcp.api.trust import router as trust_router
from jpintel_mcp.api.usage import router as usage_router
from jpintel_mcp.api.verify import router as verify_router
from jpintel_mcp.api.widget_auth import router as widget_router
from jpintel_mcp.config import settings
from jpintel_mcp.db.session import init_db
from jpintel_mcp.security.pii_redact import redact_pii

artifacts_router: Any | None = None


def _resolve_mcp_server_manifest_path() -> Path | None:
    """Find the registry manifest in both source-tree and Docker layouts."""
    candidates: list[Path] = []
    env_path = os.getenv("MCP_SERVER_MANIFEST_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend(
        [
            Path("/app/mcp-server.json"),
            Path.cwd() / "mcp-server.json",
            Path(__file__).resolve().parents[3] / "mcp-server.json",
        ]
    )

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


# ── Query telemetry ────────────────────────────────────────────────────────
# Structured JSON lines emitted to stdout via "autonomath.query" logger.
# No PII: only keys (not values) are logged; free-text is reduced to length
# and script-language heuristic.  Logging failure never blocks responses.
_query_log = logging.getLogger("autonomath.query")


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def _optional_router(module_name: str, attr: str = "router") -> Any | None:
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            return None
        raise
    return getattr(module, attr)


def _include_experimental_router(
    app: FastAPI,
    module_name: str,
    *,
    attr: str = "router",
    dependencies: list[Any] | None = None,
) -> None:
    if not _env_truthy("AUTONOMATH_EXPERIMENTAL_API_ENABLED"):
        return
    router = _optional_router(module_name, attr)
    if router is not None:
        app.include_router(router, dependencies=dependencies)


def _detect_lang(text: str) -> str:
    """Return 'ja', 'en', or 'mixed' based on CJK character ratio."""
    if not text:
        return "en"
    cjk = sum(1 for ch in text if unicodedata.category(ch) in ("Lo",) and "⺀" <= ch <= "鿿")
    ratio = cjk / len(text)
    if ratio > 0.5:
        return "ja"
    if ratio > 0.1:
        return "mixed"
    return "en"


def _params_shape(request: Request) -> dict[str, Any]:
    """Return {key: True} for every query param present (no values)."""
    # True values (not None) so downstream log consumers can tell param was
    # present vs absent without inspecting the value. C420 does not apply here.
    shape: dict[str, Any] = {k: True for k in request.query_params}  # noqa: C420
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
    params_shape: dict[str, Any],
    result_count: int,
    latency_ms: int,
    status: int | str,
    error_class: str | None,
    request_id: str | None = None,
) -> None:
    try:
        # INV-21: Defense-in-depth PII redaction. `params_shape` is supposed
        # to carry only keys + scalar metadata (q_len / q_lang), never raw
        # values, but a future endpoint that forgets that contract must not
        # leak 法人番号 / email / 電話 into telemetry. `endpoint` itself is
        # also passed through `redact_pii` because path params can carry
        # T-numbers (e.g. /v1/invoice_registrants/T8010001213708).
        # See `feedback_no_fake_data` + `analysis_wave18/.../INV-21`.
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "channel": channel,
            "endpoint": redact_pii(endpoint),
            "params_shape": redact_pii(params_shape),
            "result_count": result_count,
            "latency_ms": latency_ms,
            "status": status,
            "error_class": error_class,
        }
        # R8 audit-log deep audit (2026-05-07): include request_id so the
        # query telemetry JSON line can be joined to the response header,
        # the structured log lines under the same request, the
        # `error.request_id` envelope, and the Sentry tag — single id
        # threads forensic reconstruction during an incident.
        if request_id:
            record["request_id"] = request_id
        _query_log.info(json.dumps(record, ensure_ascii=False))
    except Exception:
        # Never block the response on telemetry failure.
        pass


# ── End query telemetry helpers ────────────────────────────────────────────

# Module-level readiness flag flipped True once lifespan startup completes.
# Drives /readyz so Fly's health check can distinguish "alive but not ready"
# (migrations / init_db still running) from "ready to serve traffic".
_ready: bool = False


def _is_production_env() -> bool:
    """Return true for both supported production env labels."""
    env = os.getenv("JPINTEL_ENV", getattr(settings, "env", "dev")) or "dev"
    return env.lower() in {"prod", "production"}


# ── §S2 production secrets boot-gate (W28) ─────────────────────────────────
# Forbidden API_KEY_SALT values that MUST never ship to production. The
# pre-commit hook (`tests/test_no_default_secrets_in_prod.py`) scans tracked
# `.env.production` / `fly.production.toml` files for these strings and the
# boot-gate (`_assert_production_secrets`) refuses to start the API when
# `JPINTEL_ENV` is `prod`/`production` and the running config still carries
# a placeholder. The empty string is included so we also reject the case
# where API_KEY_SALT was unset by a misconfigured fly secret rotation.
_FORBIDDEN_SALTS: frozenset[str] = frozenset(
    {
        "dev-salt",
        "test-salt",
        "change-this-salt-in-prod",
        "",
    }
)
_FORBIDDEN_AUDIT_SEAL_VALUES: frozenset[str] = frozenset(
    {
        "dev-audit-seal-salt",
        "test-audit-seal-salt",
        "change-this-audit-seal-secret-in-prod",
        "",
    }
)


def _audit_seal_rotation_keys(raw: str) -> list[str]:
    """Return configured audit-seal rotation secret values.

    Production operators normally set a comma-separated list. Historical
    rotation tests used JSON objects with an ``s`` secret field, so the boot
    gate accepts that shape too and validates the same underlying secrets.
    """
    raw = raw.strip()
    if not raw:
        return []
    if raw[0] in "[{":
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                "[BOOT FAIL] JPINTEL_AUDIT_SEAL_KEYS must be valid JSON or a "
                "comma-separated rotation list in production."
            ) from exc
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            raise SystemExit(
                "[BOOT FAIL] JPINTEL_AUDIT_SEAL_KEYS JSON must be a list in production."
            )
        keys: list[str] = []
        for item in parsed:
            secret = item.get("s") if isinstance(item, dict) else item
            keys.append(secret if isinstance(secret, str) else "")
        return keys
    return [part.strip() for part in raw.split(",")]


def _assert_audit_seal_value(name: str, value: str) -> None:
    if value in _FORBIDDEN_AUDIT_SEAL_VALUES:
        raise SystemExit(
            f"[BOOT FAIL] {name} is set to a forbidden placeholder ({value!r}). "
            "Set a unique audit-seal key value."
        )
    if len(value) < 32:
        raise SystemExit(f"[BOOT FAIL] {name} must be ≥32 chars in production (got {len(value)}).")


def _assert_production_secrets() -> None:
    """Hard-fail boot when production env carries placeholder/missing secrets.

    Called from the lifespan startup hook (and exercised directly by
    `tests/test_boot_gate.py`). Behaviour matrix:

      * `JPINTEL_ENV` not in {"prod", "production"} → no-op.
      * API_KEY_SALT ∈ _FORBIDDEN_SALTS → SystemExit("[BOOT FAIL] API_KEY_SALT ...").
      * len(API_KEY_SALT) < 32 → SystemExit("[BOOT FAIL] API_KEY_SALT ≥32 chars ...").
      * JPINTEL_AUDIT_SEAL_KEYS set but empty/short/placeholder →
        SystemExit("[BOOT FAIL] JPINTEL_AUDIT_SEAL_KEYS ...").
      * AUDIT_SEAL_SECRET placeholder/missing AND no valid
        JPINTEL_AUDIT_SEAL_KEYS rotation list set →
        SystemExit("[BOOT FAIL] AUDIT_SEAL ...").
      * CLOUDFLARE_TURNSTILE_SECRET empty while APPI intake is enabled AND
        AUTONOMATH_APPI_REQUIRE_TURNSTILE != "0" →
        SystemExit("[BOOT FAIL] CLOUDFLARE_TURNSTILE_SECRET ...").
        Setting AUTONOMATH_APPI_REQUIRE_TURNSTILE=0 lets the operator
        activate the APPI router without a Turnstile secret. The router
        gracefully bypasses Turnstile verification at request time when
        the secret is unset (`_verify_turnstile_token` short-circuits on
        empty secret); abuse is rate-limited by the anonymous IP cap and
        the 14/30-day manual-review SLA. See
        docs/runbook/privacy_router_activation.md.
      * STRIPE_WEBHOOK_SECRET empty → SystemExit("[BOOT FAIL] STRIPE_WEBHOOK_SECRET ...").
      * STRIPE_SECRET_KEY empty/test-mode → SystemExit("[BOOT FAIL] STRIPE_SECRET_KEY ...").

    The function reads from the live `settings` module so tests can
    reload+rebind it via `monkeypatch.setattr(main, "settings", ...)`.
    """
    env_label = (getattr(settings, "env", "") or "").lower()
    if env_label not in {"prod", "production"}:
        return

    salt = getattr(settings, "api_key_salt", "") or ""
    if salt in _FORBIDDEN_SALTS:
        raise SystemExit(
            f"[BOOT FAIL] API_KEY_SALT is set to a forbidden placeholder ({salt!r}). "
            f"Set a unique value via `fly secrets set API_KEY_SALT=...`."
        )
    if len(salt) < 32:
        raise SystemExit(
            f"[BOOT FAIL] API_KEY_SALT must be ≥32 chars in production (got {len(salt)})."
        )

    audit_secret = getattr(settings, "audit_seal_secret", "") or ""
    audit_keys_raw = os.getenv("JPINTEL_AUDIT_SEAL_KEYS")
    audit_rotation_keys = (
        _audit_seal_rotation_keys(audit_keys_raw) if audit_keys_raw is not None else []
    )
    if audit_keys_raw is not None and not audit_rotation_keys:
        raise SystemExit(
            "[BOOT FAIL] JPINTEL_AUDIT_SEAL_KEYS must contain at least one "
            "non-placeholder ≥32-char value in production."
        )
    for index, audit_key in enumerate(audit_rotation_keys, start=1):
        _assert_audit_seal_value(f"JPINTEL_AUDIT_SEAL_KEYS[{index}]", audit_key)

    audit_secret_ok = audit_secret not in _FORBIDDEN_AUDIT_SEAL_VALUES and (len(audit_secret) >= 32)
    if not audit_secret_ok and not audit_rotation_keys:
        raise SystemExit(
            "[BOOT FAIL] AUDIT_SEAL_SECRET (or JPINTEL_AUDIT_SEAL_KEYS rotation "
            "list) must be set to a non-placeholder ≥32-char value in production."
        )

    appi_enabled = os.getenv("AUTONOMATH_APPI_ENABLED", "1") not in {
        "0",
        "false",
        "False",
    }
    require_turnstile = os.getenv("AUTONOMATH_APPI_REQUIRE_TURNSTILE", "1") not in {
        "0",
        "false",
        "False",
    }
    if (
        appi_enabled
        and require_turnstile
        and not os.getenv("CLOUDFLARE_TURNSTILE_SECRET", "").strip()
    ):
        raise SystemExit(
            "[BOOT FAIL] CLOUDFLARE_TURNSTILE_SECRET must be set in production "
            "when APPI intake is enabled. Set "
            "AUTONOMATH_APPI_REQUIRE_TURNSTILE=0 to opt out (honor system + "
            "manual review). See docs/runbook/privacy_router_activation.md."
        )

    if not (getattr(settings, "stripe_webhook_secret", "") or "").strip():
        raise SystemExit("[BOOT FAIL] STRIPE_WEBHOOK_SECRET must be set in production.")

    stripe_secret_key = (getattr(settings, "stripe_secret_key", "") or "").strip()
    if not stripe_secret_key:
        raise SystemExit("[BOOT FAIL] STRIPE_SECRET_KEY must be set in production.")
    if not stripe_secret_key.startswith(("sk_live_", "rk_live_")):
        raise SystemExit(
            "[BOOT FAIL] STRIPE_SECRET_KEY must be a live-mode Stripe key in production."
        )


def _init_sentry() -> None:
    # Two-gate init: (a) DSN present (no-op in CI / dev without SENTRY_DSN),
    # (b) JPINTEL_ENV=prod (silences staging / dev / test even when an
    # operator forgets to scope a SENTRY_DSN secret per environment).
    # See docs/observability.md "Sentry 設定手順". Both gates needed: a
    # mis-scoped DSN in dev would otherwise pollute prod issue counts and
    # quota, breaking the P1-5 alert rule.
    if not settings.sentry_dsn:
        return
    if not _is_production_env():
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
    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        # R8 audit-log deep audit (2026-05-07): unify the happy-path mint with
        # the error-path mint. Pre-fix the happy path used `secrets.token_hex(8)`
        # (16 hex chars) while `_error_envelope._mint_request_id()` produced a
        # 26-char Crockford-base32 ULID — same regex window but different
        # shapes, so log search by id-length filter would split the same
        # request across two formats. Switch to the ULID mint so the response
        # `x-request-id` header, the structured-log `request_id` contextvar,
        # and the `error.request_id` envelope all share one shape (26-char
        # ULID; lexicographically time-sortable for forensic windowing).
        from jpintel_mcp.api._error_envelope import _mint_request_id

        inbound = request.headers.get("x-request-id", "")
        rid = inbound if _REQUEST_ID_RE.fullmatch(inbound) else _mint_request_id()
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
        # R8 audit-log deep audit (2026-05-07): forward request_id as a Sentry
        # tag so issue-search and triage can pivot on the same id that
        # appears in `x-request-id`, the JSON log line, and the
        # `error.request_id` envelope. Sentry SDK auto-attaches the
        # x-request-id HEADER to event.request, but the value is buried in a
        # request blob — without an explicit tag the search filter
        # `request_id:01KR0Q...` returns zero hits. No-op when Sentry is not
        # initialised (dev / non-prod) — `set_tag` is safe on a stub hub.
        try:
            import sentry_sdk

            sentry_sdk.set_tag("request_id", rid)
        except Exception:  # noqa: BLE001 — observability never raises on the hot path
            pass
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

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
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
            # R8 audit-log deep audit (2026-05-07): pull the rid stamped onto
            # request.state by `_RequestContextMiddleware` so the query log
            # line carries the same correlation id as the response header
            # and the structlog contextvar.
            rid_for_log: str | None = None
            try:
                rid_for_log = getattr(request.state, "request_id", None)
            except Exception:  # noqa: BLE001 — telemetry never raises
                rid_for_log = None
            _emit_query_log(
                channel="rest",
                endpoint=request.url.path,
                params_shape=_params_shape(request),
                result_count=0,  # REST: result count not available in middleware
                latency_ms=latency_ms,
                status=status,
                request_id=rid_for_log,
                error_class=error_class,
            )
        return response


logger = logging.getLogger("jpintel.api")
_ready = False

_COMPONENT_SCHEMA_NAMES = {
    "jpintel_mcp__api__advisors__SignupRequest": "AdvisorSignupRequest",
    "jpintel_mcp__api__advisors__SignupResponse": "AdvisorSignupResponse",
    "jpintel_mcp__api__alerts__SubscribeRequest": "AlertSubscribeRequest",
    "jpintel_mcp__api__billing__CheckoutRequest": "BillingCheckoutRequest",
    "jpintel_mcp__api__client_profiles__DeleteResponse": "ClientProfileDeleteResponse",
    "jpintel_mcp__api__compliance__CheckoutRequest": "ComplianceCheckoutRequest",
    "jpintel_mcp__api__compliance__CheckoutResponse": "CheckoutResponse",
    "jpintel_mcp__api__compliance__SubscribeRequest": "ComplianceSubscribeRequest",
    "jpintel_mcp__api__compliance__SubscribeResponse": "ComplianceSubscribeResponse",
    "jpintel_mcp__api__customer_webhooks__DeleteResponse": "WebhookDeleteResponse",
    "jpintel_mcp__api__dashboard__UsageDay": "UsageDay",
    "jpintel_mcp__api__invoice_registrants__SearchResponse": ("InvoiceRegistrantSearchResponse"),
    "jpintel_mcp__api__me__UsageDay": "UsageDay",
    "jpintel_mcp__api__saved_searches__DeleteResponse": "SavedSearchDeleteResponse",
    "jpintel_mcp__api__signup__SignupRequest": "TrialSignupRequest",
    "jpintel_mcp__api__signup__SignupResponse": "TrialSignupResponse",
    "jpintel_mcp__api__subscribers__SubscribeRequest": "SubscriberSubscribeRequest",
    "jpintel_mcp__api__subscribers__SubscribeResponse": "SubscriberSubscribeResponse",
    "jpintel_mcp__models__SearchResponse": "ProgramSearchResponse",
}


def _camelize_component_part(value: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[_\W]+", value) if part)


def _public_component_schema_name(name: str) -> str:
    explicit = _COMPONENT_SCHEMA_NAMES.get(name)
    if explicit:
        return explicit
    if not name.startswith("jpintel_mcp__"):
        return name

    parts = name.split("__")
    model_name = parts[-1]
    module_parts = [part for part in parts[1:-1] if part not in {"api", "models", "jpintel_mcp"}]
    prefix = "".join(_camelize_component_part(part) for part in module_parts[-2:])
    return f"{prefix}{model_name}" if prefix else model_name


def _rewrite_openapi_component_refs(node: Any, renamed: dict[str, str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            prefix = "#/components/schemas/"
            if ref.startswith(prefix):
                name = ref[len(prefix) :]
                public_name = renamed.get(name)
                if public_name:
                    node["$ref"] = f"{prefix}{public_name}"
        for value in node.values():
            _rewrite_openapi_component_refs(value, renamed)
    elif isinstance(node, list):
        for item in node:
            _rewrite_openapi_component_refs(item, renamed)


def _normalize_openapi_component_schema_names(schema: dict[str, Any]) -> None:
    components = schema.get("components")
    if not isinstance(components, dict):
        return
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return

    renamed = {
        name: _public_component_schema_name(name)
        for name in schemas
        if _public_component_schema_name(name) != name
    }
    if not renamed:
        return

    normalized: dict[str, Any] = {}
    for name, component_schema in schemas.items():
        public_name = renamed.get(name, name) or name
        existing = normalized.get(public_name)
        if existing is not None and existing != component_schema:
            raise RuntimeError(f"OpenAPI component rename collision: {name} -> {public_name}")
        normalized[public_name] = component_schema
    components["schemas"] = normalized
    _rewrite_openapi_component_refs(schema, renamed)


def _sanitize_openapi_public_text(text: str) -> str:
    text = re.sub(
        r"\A(?:Stripe webhook|stripe webhook|billing event) endpoint\..*",
        "Billing event endpoint.",
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\APersist a (?:trial_signups|trial signup) (?:row|record) \+ mail a magic link\. Always 202 Accepted\..*",
        (
            "Accept a trial signup and send a magic link. Accepted signup "
            "attempts return 202.\n\n"
            "The response shape is stable so signups do not disclose whether an "
            "address has already used a trial. Rate-limit failures may return 429. "
            "Trial keys are not connected to paid billing."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\AVerify the magic-link token, issue a trial key, redirect to /trial\.html\..*",
        (
            "Verify a magic-link token, issue a trial key, and redirect to the "
            "trial page. Invalid, expired, or already-used links redirect with "
            "a status indicator. Successful verification returns the newly "
            "issued key in the URL fragment for one-time display."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\AList the calling key's webhooks .*",
        ("List the calling key's registered outbound webhooks, including disabled webhooks."),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\ARegister a new outbound webhook\..*",
        (
            "Register a new outbound webhook. The response includes the "
            "signing secret once; subsequent reads include only a short "
            "signing secret hint."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\ARecords the calling key's preference for which inbound parse address to publish\..*",
        (
            "Record the calling key's preferred inbound email parse address. "
            "Final setup may require support assistance."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\ACreate an unverified advisor profile \+ return Stripe Connect onboarding URL\..*",
        (
            "Create an advisor profile and return an onboarding URL when "
            "available. Self-serve signup does not require an API key."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\AConfirm the advisor's 法人番号 exists in (?:invoice_registrants|invoice registrant records) .*",
        (
            "Confirm an advisor's 法人番号 against invoice registrant records "
            "and mark the advisor profile as verified when it matches."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\ACreate a new pending subscription \+ send verification email\..*",
        (
            "Create a pending subscription and send a verification email. "
            "Duplicate requests use the same response shape to avoid email "
            "enumeration."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\AMark a subscriber as verified\. Renders a minimal HTML page\..*",
        (
            "Verify a subscriber email token and render a confirmation page. "
            "Repeated valid clicks are idempotent. Paid subscribers are "
            "directed to checkout."
        ),
        text,
        flags=re.S,
    )
    text = re.sub(r"P0 fixes from audit.*?(?=\n\n\*\*|\Z)", "", text, flags=re.S)
    text = re.sub(r"\*\*Operator\*\*:.*?(?=\n\n|\Z)", "", text, flags=re.S)
    text = re.sub(r"Operator: Bookyou株式会社.*?(?=\.|\n)", "jpcite support", text)
    text = re.sub(r"See `src/[^`]+` module docstring for scope\.\n?", "", text)
    text = re.sub(r"\(memory: [^)]+\)", "", text)
    text = re.sub(r"memory: [A-Za-z0-9_/-]+", "", text)
    text = re.sub(
        r"\*\*404 semantics:\*\*.*?\n\n",
        (
            "**404 semantics:** A miss means the record is not available in "
            "jpcite's current snapshot. The response includes official lookup "
            "guidance when available.\n\n"
        ),
        text,
        flags=re.S,
    )
    replacements = [
        (r"info@bookyou\.net", "jpcite support"),
        (r"Bookyou株式会社", "jpcite operator"),
        (r"Bookyou Inc\.", "jpcite operator"),
        (r"T8010001213708", "jpcite legal identifier"),
        (r"usage_events", "usage records"),
        (r"jpintel\.db", "indexed corpus"),
        (r"autonomath\.db", "extended corpus"),
        (r"\bBackgroundTasks\b", "background work"),
        (r"DB unavailable / invalid input", "Data unavailable or invalid input"),
        (r"\bSQLite\b", "persistent storage"),
        (r"stripe_webhook_events", "billing event records"),
        (r"\bsecret_hmac\b", "signing secret"),
        (r"\bsecret_last4\b", "signing secret hint"),
        (r"trial_signups", "trial signup"),
        (r"\bUNIQUE\b", "deduplication rule"),
        (r"\bIntegrityError\b", "duplicate signup"),
        (r"deps\._enforce_quota", "quota checks"),
        (r"ApiContext\.metered", "metering checks"),
        (r"issued_api_key_hash", "issued key record"),
        (r"raw-key", "one-time key"),
        (r"raw API key", "one-time API key"),
        (
            r"Returned when STRIPE_SECRET_KEY is set\. Null in dev/offline mode — the signup record is still created so the advisor can retry onboarding\.",
            "Returned when Stripe onboarding is available. Null when onboarding cannot be started immediately; the signup record is still created so the advisor can retry.",
        ),
        (r"\bSTRIPE_SECRET_KEY\b", "Stripe onboarding"),
        (r"\bdev/offline mode\b", "onboarding unavailable"),
        (r"\bWired by L5\.?", ""),
        (r"safe overshoot", "conservative estimate"),
        (
            r"Honeypot\. Real callers MUST leave this null/empty\. The web form hides this field via CSS; only autofilled bots populate it\. Any non-empty value is treated as abuse and rejected\.",
            "Reserved anti-abuse field. Leave it empty.",
        ),
        (r"\(api/programs\.py\)", ""),
        (r"empty-corpus query", "unbounded saved search"),
        (r"free \(dunning\) tiers", "temporary billing-status cases"),
        (
            r"Authentication: intentionally light today.*",
            "Access is limited to the advisor dashboard flow.",
        ),
        (
            r"\s*expected to be reached via the Stripe Connect Express portal return\n"
            r"URL \(or via magic-link email\)\. Adding API-key auth here would block\n"
            r"the simplest flow where the advisor arrives from Stripe's own\n"
            r"dashboard\. If this becomes abused, add a signed HMAC\n"
            r"``\?token=\.\.\.`` in the URL and verify here\.",
            "",
        ),
        (
            r"If this becomes abused, add a signed HMAC\s+``\?token=\.\.\.`` "
            r"in the URL and verify here\.",
            "",
        ),
        (r"runaway-billing", "excess delivery"),
        (r"hammering their downstream", "sending too many test requests"),
        (r"scripts/[^\s`)]+", "scheduled source refresh"),
        (r"seed_advisors\.py", "source refresh"),
        (r"docs/_internal/[^\s`)]+", "support-assisted setup notes"),
        (r"default gates", "standard configuration"),
        (r"legal review pending", "not publicly available"),
        (r"\bbroken\b", "disabled"),
        (r"\bmigration\s+\d+", "schema update"),
        (r"\bcron\b", "scheduled job"),
        (r"\binternal\b", "service"),
        (r"\bV4\b", "current release"),
        (r"\bP3-W\b", "budget control"),
        (r"\brequire_key\b", "API-key authentication"),
        (r"\bapi_keys row\b", "API key"),
        (r"\bapi_keys\b", "API keys"),
        (r"\braw key\b", "newly issued key"),
        (r"\bin-process pickup\b", "one-time retrieval"),
        (r"\bfull table\b", "complete dataset"),
        (r"\bam_relation\b", "relationship graph"),
        (r"\bStripe webhook\b", "billing event"),
        (r"\bstripe webhook\b", "billing event"),
        (r"\bsource records\b", "public records"),
        (r"\bsource record\b", "public record"),
        (r"\bOperator\b", "Support team"),
        (r"\boperator\b", "support team"),
        (r"\binternal HTTP hop\b", "extra HTTP hop"),
        (r"\binternal-only columns\b", "non-public columns"),
        (r"\binternal-only\b", "non-public"),
        (r"\binternal runbook\b", "support-assisted setup notes"),
        (r"\bsupport runbook\b", "support-assisted setup notes"),
        (r"\binternal write\b", "write"),
        (r"\bInternal error\b", "Server error"),
        (r"\binternal client identifier\b", "client-defined identifier"),
        (r"\binternal billing\b", "billing"),
        (r"project_autonomath_business_model", "the published pricing model"),
        (r"feedback_autonomath_no_api_use", "jpcite does not call an LLM API"),
        (r"metadata\.autonomath_product", "metadata.product"),
        (r"autonomath\.intake_consistency_rules", "jpcite validation rules"),
        (r"autonomath\.intake\.", "jpcite.validation."),
        (r"\bAUTONOMATH_SNAPSHOT_ENABLED\b", "snapshot feature flag"),
        (r"\bautonomath public dataset\b", "public adoption dataset"),
        (r"\bautonomath canonical id\b", "stable legacy id"),
        (r"\bautonomath spine\b", "historical snapshot index"),
        (r"\bunified autonomath dataset\b", "unified jpcite dataset"),
        (r"\bAutonoMath\b", "jpcite"),
        (r"\bautonomath dataset\b", "jpcite dataset"),
        (r"\(autonomath\)", ""),
        (r"\(jpintel\)", ""),
        (r"\bjpintel\b", "jpcite"),
        (
            r"jpintel_mcp\.utils\.slug\.program_static_url",
            "jpcite static URL builder",
        ),
        (r"jpintel_mcp\.utils\.slug", "jpcite static URL builder"),
        (r"am_validation_rule", "configured validation rules"),
        (r"jpintel 内", "jpcite で"),
        (r"jpcite でで", "jpcite で"),
        (r"\bapi_key_hash\b", "API key identifier"),
        (
            r"``GOOGLE_OAUTH_CLIENT_ID`` env var must be set on the support team "
            r"side before this works \(503 otherwise\)\.",
            "Google OAuth must be configured before this works (503 otherwise).",
        ),
        (r"\bNO billing\b", "no billing charge"),
        (r"\bFREE\b", "no request charge"),
        (
            r"the two values differ only in the guarantee that full's "
            r"enriched/source_mentions keys are present even when null",
            "the two values differ only in the documented `full` response shape; "
            "enriched/source_mentions keys are included even when null",
        ),
        (r"keys guaranteed present", "keys included in the documented response shape"),
        (r"\bguaranteed present\b", "included in the documented response shape"),
        (
            r"must yield byte-identical\n\s+results, OR",
            "is expected to yield byte-identical results, or",
        ),
        (r"manual review", "support review"),
        (r"manual support team action", "support-assisted setup"),
        (r"data/workpapers/[^\s`)]+", "generated PDF"),
        (r"data/quarterly_pdfs/[^\s`)]+", "generated PDF"),
        (r"benchmark bundles?", "JSON responses"),
        (r"debugging or post-deploy verification", "fresh status checks"),
        (r"post-launch monthly bulk refresh", "scheduled source refresh"),
        (r"launch-week miss frequently means", "miss may mean"),
        (r"X-Zeimu-", "X-Jpcite-"),
        (r"fts5_trigram \+ LIKE fallback", "text search with fallback matching"),
        (r"FTS5 trigram", "text search"),
        (r"FTS5", "text search"),
        (r"fts5_trigram", "text search"),
        (r"\bFTS\b", "text search"),
        (r"trigram tokenizer limitation", "short-query limitation"),
        (r"trigram zero-match", "short-query zero-match"),
        (
            r"quoted-phrase workaround for 2\+ character kanji compounds",
            "Japanese phrase normalization",
        ),
        (r"quality-gate quarantine", "publication review hold"),
        (r"Tier X", "non-public records"),
        (r"tier X", "non-public records"),
        (r"[Rr]eview-held(?:/quarantine)? records?", "non-public records"),
        (r"[Rr]eview-held(?:/quarantine)? rows?", "non-public records"),
        (r"\bquarantine rows?", "non-public records"),
        (r"case_studies_fts", "case study index"),
        (r"corpus dump guard", "broad empty-search guard"),
        (r"\bhandler\b", "API"),
        (r"am_entity_facts\.source_id", "per-fact source reference"),
        (r"am_entity_facts\.id", "fact identifier"),
        (r"am_entities\.canonical_id", "stable entity identifier"),
        (r"am_entity_source", "entity-level source references"),
        (r"am_entity_annotation", "entity annotations"),
        (r"am_entity_facts", "fact records"),
        (r"am_entities", "public records"),
        (r"am_source", "source catalog"),
        (r"am_amendment_diff", "public change log"),
        (r"am_amendment_snapshot", "historical snapshot"),
        (r"entity_id_map", "stable identifier map"),
        (r"jpi_[A-Za-z0-9_]+", "public dataset"),
        (r"programs\.unified_id", "linked program identifier"),
        (r"invoice_registrants", "invoice registrant records"),
        (r"widget_keys row", "widget key"),
        (r"\bLIKE\b", "fallback matching"),
        (r"\brank(ed|ing)?\b", "relevance-ordered"),
        (r"\bcache key\b", "repeat-request matching"),
        (r"\bcached\b", "temporarily reused"),
        (r"\bcache\b", "short-lived response reuse"),
        (r"\btable\b", "dataset"),
        (r"\btables\b", "datasets"),
        (r"\bview\b", "dataset"),
        (r"\bviews\b", "datasets"),
        (r"\bMigration\b", "Schema update"),
        (r"\bmig(?:ration)?\.?\s*\d+", "schema update"),
        (r"\.sql\b", ""),
        (r"\bwave\s*\d+\b", "current release"),
        (r"\bWave\s*\d+\b", "Current release"),
        (r"\bphase[_ -]?[A-Za-z0-9]+\b", "release track"),
        (r"\bgate(d)?\b", "controlled"),
        (r"not re-metered", "not billed again"),
        (r"read-from-disk", "read from packaged data"),
        (r"\brows\b", "records"),
        (r"\brow\b", "record"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    pricing_replacements = [
        (r"¥3 / リクエスト 完全従量", "¥3/billable unit 完全従量"),
        (r"¥3/request", "¥3/billable unit"),
        (r"¥3/req", "¥3/billable unit"),
        (r"¥3 per request", "¥3 per billable unit"),
        (
            r"One ¥3 charge per request regardless of format\.",
            "One billable unit regardless of format.",
        ),
        (r"Single ¥3 charge per request", "Single billable unit"),
    ]
    for pattern, replacement in pricing_replacements:
        text = re.sub(pattern, replacement, text)
    text = text.replace("¥3/billable unit unit price", "¥3/billable unit price")
    # Some generic replacements above intentionally rewrite implementation
    # nouns such as "row" to "record" late in the pass. Re-apply the public
    # source wording after that final generic sweep so runtime OpenAPI and the
    # exported committed spec stay byte-compatible.
    text = re.sub(r"\bsource records\b", "public records", text)
    text = re.sub(r"\bsource record\b", "public record", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_PUBLIC_OPENAPI_HIDDEN_PATHS: frozenset[str] = frozenset(
    {
        "/v1/billing/webhook",
        "/v1/compliance/stripe-webhook",
        "/v1/email/webhook",
        "/v1/integrations/email/inbound",
        "/v1/integrations/google/callback",
        "/v1/integrations/line/webhook",
        "/v1/integrations/sheets",
        "/v1/integrations/slack/webhook",
        "/v1/widget/stripe-webhook",
    }
)


def _prune_openapi_public_paths(schema: dict[str, Any]) -> None:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return
    for path in _PUBLIC_OPENAPI_HIDDEN_PATHS:
        paths.pop(path, None)


def _sanitize_openapi_public_schema(node: Any) -> None:
    if isinstance(node, dict):
        tags = node.get("tags")
        if isinstance(tags, list):
            # Operation-level `tags` is a list of strings; root-level
            # `tags` is a list of `{name, description}` dicts. Apply the
            # legacy autonomath -> jpcite rename to both shapes so the
            # public schema stays consistent.
            _legacy_rename = {
                "autonomath": "jpcite",
                "autonomath-health": "jpcite-health",
            }
            new_tags: list[Any] = []
            for item in tags:
                if isinstance(item, str):
                    new_tags.append(_legacy_rename.get(item, item))
                elif isinstance(item, dict):
                    name = item.get("name")
                    if isinstance(name, str) and name in _legacy_rename:
                        item = dict(item)
                        item["name"] = _legacy_rename[name]
                    new_tags.append(item)
                else:
                    new_tags.append(item)
            node["tags"] = new_tags
        if node.get("title") == "WebhookResponse":
            properties = node.get("properties")
            if isinstance(properties, dict):
                secret_schema = properties.pop("secret_hmac", None)
                if isinstance(secret_schema, dict):
                    secret_schema["title"] = "Signing Secret"
                    properties["signing_secret"] = secret_schema
                hint_schema = properties.pop("secret_last4", None)
                if isinstance(hint_schema, dict):
                    hint_schema["title"] = "Signing Secret Hint"
                    properties["signing_secret_hint"] = hint_schema
            required = node.get("required")
            if isinstance(required, list):
                node["required"] = [
                    {
                        "secret_hmac": "signing_secret",
                        "secret_last4": "signing_secret_hint",
                    }.get(item, item)
                    for item in required
                ]
        if node.get("title") == "_DataHealthCheck":
            properties = node.get("properties")
            if isinstance(properties, dict) and "table" in properties:
                properties["dataset"] = properties.pop("table")
                dataset_schema = properties.get("dataset")
                if isinstance(dataset_schema, dict):
                    dataset_schema["title"] = "Dataset"
            required = node.get("required")
            if isinstance(required, list):
                node["required"] = ["dataset" if item == "table" else item for item in required]
        enum_values = node.get("enum")
        if isinstance(enum_values, list):
            node["enum"] = [item for item in enum_values if item != "internal"]
        properties = node.get("properties")
        if isinstance(properties, dict):
            properties.pop("include_excluded", None)
            required = node.get("required")
            if isinstance(required, list):
                node["required"] = [item for item in required if item != "include_excluded"]
        parameters = node.get("parameters")
        if isinstance(parameters, list):
            node["parameters"] = [
                parameter
                for parameter in parameters
                if not (
                    isinstance(parameter, dict)
                    and parameter.get("name") in {"include_internal", "include_excluded"}
                )
            ]
        for key, value in list(node.items()):
            if isinstance(value, str):
                node[key] = _sanitize_openapi_public_text(value)
            else:
                _sanitize_openapi_public_schema(value)
    elif isinstance(node, list):
        for item in node:
            _sanitize_openapi_public_schema(item)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/teardown for the API.

    On startup we initialise Sentry, configure logging, run the production
    secret boot gate, and then run `init_db()` (idempotent — safe on an
    already-migrated volume). After init_db we run hard-fail integrity gates:
      1) **Production secret boot gate**: in `JPINTEL_ENV=prod`/`production`,
         placeholders or missing operational secrets abort before DB init.
         This includes APPI Turnstile when APPI intake is enabled.
      2) **Aggregator domain assertion**: `programs.source_url` MUST NOT
         contain any banned aggregator domain (noukaweb, hojyokin-portal,
         biz.stayway, stayway.jp, nikkei.com, prtimes.jp, wikipedia.org).
         Past incidents → 詐欺 risk; we refuse to serve traffic if any
         aggregator-sourced row leaked in. See memory: `feedback_no_fake_data`
         and CLAUDE.md "Data hygiene".
      3) **Pepper guard (prod only)**: in `JPINTEL_ENV=prod`, the API-key
         hashing pepper `AUTONOMATH_API_HASH_PEPPER` must be set and not
         the placeholder. Empty / placeholder → log critical + sys.exit(1).
    Only after both pass do we flip `_ready` so `/readyz` starts returning
    200. On shutdown uvicorn's `timeout_graceful_shutdown` (set in `run()`)
    gives in-flight Stripe webhooks up to 30s to drain before the worker dies.
    """
    global _ready
    _init_sentry()
    setup_logging(level=settings.log_level, fmt=settings.log_format)
    _assert_production_secrets()
    init_db()

    # ── Pepper guard (prod only) ────────────────────────────────────────
    # In production, refuse to start if the API-key hashing pepper is
    # missing or still the dev placeholder. Hashing keys with a
    # known-public pepper would render every stored hash trivially
    # crackable. Skip in dev/test so local runs don't require setup.
    if _is_production_env():
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
    if _is_production_env():
        _fkey = os.getenv("INTEGRATION_TOKEN_SECRET", "").strip()
        if _fkey:
            try:
                from cryptography.fernet import Fernet, MultiFernet

                _candidates = [k.strip() for k in _fkey.split(",") if k.strip()]
                if len(_candidates) == 1:
                    Fernet(_candidates[0].encode("utf-8"))
                else:
                    MultiFernet([Fernet(k.encode("utf-8")) for k in _candidates])
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
    _bg_task = asyncio.create_task(run_worker_loop(_bg_stop), name="bg_task_worker")

    # ── Boot-time SQLite cold-start warmup (R8_PERF_BASELINE #3) ────────
    # First /v1/am/health/deep hit on a freshly-booted Fly machine
    # measured at 30.92s (Fly proxy ceiling) because the 9.4 GB
    # autonomath.db has zero pages in the OS page cache. Second hit
    # <400ms once cached. We fire-and-forget cheap SELECT COUNT(*) +
    # LIMIT 1 probes against the hottest tables in a background task so
    # the page cache fills concurrently with the first inbound traffic.
    # The task NEVER raises (see `_db_warmup.py` for the swallowed-error
    # contract) and is bounded by an outer 30s budget so it can't keep
    # the worker alive past Fly's 60s grace.
    from jpintel_mcp.api._db_warmup import schedule_warmup

    _warmup_task = schedule_warmup()

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
        # Warmup is fire-and-forget; if it's still running on shutdown
        # cancel it cleanly so asyncio doesn't log a "task was destroyed
        # but it is pending" warning.
        if not _warmup_task.done():
            _warmup_task.cancel()
            try:
                await asyncio.wait_for(_warmup_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                pass
            except Exception:  # pragma: no cover — defensive
                logger.exception("db_warmup_shutdown_error")


def create_app() -> FastAPI:
    app = FastAPI(
        title="jpcite",
        version=__version__,
        description=(
            "jpcite is a Japanese public-program intelligence API + MCP "
            "server. It exposes a single retrieval surface over public "
            "Japanese programs, case studies, loan products, enforcement "
            "cases, laws, tax references, court decisions, bids, and invoice "
            "registrants. Records include source URLs and fetched timestamps "
            "where available.\n\n"
            "## Who this is for\n\n"
            "Built for LLM agents (Claude Desktop / Cursor / Cline via MCP; "
            "ChatGPT Custom GPTs via OpenAPI Actions) and developers building "
            "Japanese-business automation. Use cases:\n"
            "- discover candidate 補助金 / 助成金 by region + industry + amount\n"
            "- check whether a 法人番号 is a registered 適格請求書発行事業者\n"
            "- look up the current 税務判定ルールセット (e.g. 2割特例, "
            "電子帳簿保存法) and evaluate caller-supplied 事業者プロファイル against it\n"
            "- pull 採択事例 (real awarded grants) for prior-art research\n"
            "- check 行政処分 history before extending credit / awarding "
            "subsidy\n"
            "- read e-Gov 法令 articles and trace which programs cite them\n\n"
            "For AI workflows, call `/v1/intelligence/precomputed/query` or "
            "`/v1/evidence/packets/query` before answer generation to retrieve "
            "compact source-linked evidence. Optional compression fields compare "
            "caller-supplied input-context baselines.\n\n"
            "## Information lookup, not professional advice (税理士法 §52)\n\n"
            "**This API returns information retrieved from public Japanese "
            "sources and official provider pages. It is NOT 税務助言 (tax advice), NOT 法律相談 "
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
            "Authenticated (¥3/billable unit metered, 税込 ¥3.30, no tier SKUs, no "
            "monthly minimum commitment; normal search/detail calls are 1 unit, "
            "batch/export endpoints document their fan-out formula) — pass `X-API-Key: am_...` issued via "
            "Stripe Checkout:\n"
            "```bash\n"
            "curl -H 'X-API-Key: am_live_...' "
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
            "## About\n\n"
            "Canonical site: https://jpcite.com. "
            "MCP package: `pip install autonomath-mcp` (PyPI). "
            "MCP exposes 139 tools in the standard configuration.\n\n"
            "---\n\n"
            "## 日本語要約 (JP summary)\n\n"
            "jpcite は **11,601 件の検索可能な補助金 / 融資 / 税制 / 認定** "
            "(全 14,472 件を追跡し、11,601 件を通常検索で公開)、**2,286 件の"
            "採択事例**、**108 件の融資商品** (担保 / 個人保証人 / 第三者保証人 "
            "三軸分解)、**1,185 件の行政処分**、**9,484 件の法令** (e-Gov / "
            "CC-BY 4.0)、**50 件の税務判定ルールセット**、**2,065 件の判例**、"
            "**362 件の入札案件**、**13,801 件の適格請求書発行事業者 (国税庁 / PDL "
            "v1.0)** を、REST + MCP の単一検索面で公開する API です。各レコードは "
            "一次情報源 URL と取得時刻 (`source_url` / `fetched_at`) を保持しています。\n\n"
            "**用途:** LLM エージェント (Claude Desktop / Cursor / Cline は MCP、"
            "ChatGPT Custom GPT は OpenAPI Actions) と"
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
            "発行した `X-API-Key: am_...` を `X-API-Key` ヘッダー"
            "または `Authorization: Bearer ...` で送信してください。\n\n"
            "**公式サイト:** https://jpcite.com/."
        ),
        lifespan=_lifespan,
        openapi_url="/v1/openapi.json",
    )

    origins = sorted(
        {o.strip().rstrip("/") for o in settings.cors_origins.split(",") if o.strip()}
        | set(_MUST_INCLUDE)
    )
    # Wave 16 P1: hard origin enforcement is mounted after CORS below so it
    # runs outermost. That lets it return the legacy 403 for disallowed
    # regular/preflight origins before any DB write or Stripe API call, while
    # still letting allowed-origin short-circuit responses pass through CORS.
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
    # R8 perf, 2026-05-07: Cache-Control on static-ish JSON manifests so
    # Cloudflare / SDK generators / Stainless-style introspectors don't
    # re-fetch 539 KB / 252 KB / 386 B blobs that only change on deploy.
    # Stamps `public, max-age=300, s-maxage=600` on /v1/openapi.json,
    # /v1/openapi.agent.json, /v1/mcp-server.json — see
    # api/middleware/static_cache_headers.py docstring. Added EARLY so
    # it runs LATE on the response (after the manifest body has been
    # serialized). Idempotent setdefault — any future per-route override
    # (e.g. `no-store` on a customer-state surface) wins.
    app.add_middleware(StaticManifestCacheMiddleware)
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
    # §28.2 response envelope negotiation. Routes that explicitly serve the
    # v2 shape set request.state.envelope_v2_served or the response header;
    # all other routes keep advertising v1 even when a caller sends the v2
    # Accept media type.
    app.add_middleware(EnvelopeAdapterMiddleware)
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
    # R8 i18n: resolve `?lang=` (override) → Accept-Language q-value → "ja"
    # default and stash onto request.state.lang. Pure pass-through, no DB
    # read, ~80 LOC. Sits after CORS / rate-limit (registered LATER in this
    # function; Starlette LIFO means CORS executes first) so a 429 path
    # never spends cycles on language parsing, and before all envelope
    # helpers + route handlers that read request.state.lang to pick
    # ja vs en user_message copy. See api/middleware/language_resolver.py
    # for full resolution logic and rationale.
    app.add_middleware(LanguageResolverMiddleware)
    # Per-request budget guard for authenticated bulk/batch routes.
    # Missing X-Cost-Cap-JPY on paid bulk requests should fail before the
    # handler fans out into billable work. Anonymous evaluation calls are not
    # forced to carry the header because they cannot create metered spend.
    app.add_middleware(CostCapMiddleware)
    # P3-W customer self-cap: short-circuit with 503 + cap_reached:true once
    # month-to-date billable spend (¥3/req) reaches the customer's
    # `monthly_cap_yen`. Runs after request-id binding so logged 503s carry
    # the request id, but before telemetry so a cap-rejection is logged with
    # the full latency. Anonymous callers (no X-API-Key) are skipped.
    app.add_middleware(CustomerCapMiddleware)
    # Idempotency-Key replay cache for customer POST retries. Added after
    # CustomerCap so Starlette executes it before cap/router work; replayed
    # responses return directly and do not create usage_events rows.
    app.add_middleware(IdempotencyMiddleware)
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
    # CORS is added last so it executes first in Starlette's LIFO middleware
    # stack. That lets browser clients read short-circuit responses from
    # cost-cap/rate-limit/origin guards and lets preflight complete before
    # request logging or billing guards run.
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
            "X-Cost-Cap-JPY",
            "Stripe-Signature",
            "X-Postmark-Webhook-Signature",
            # IETF Idempotency-Key (draft-ietf-httpapi-idempotency-key-header).
            # Accepted by /v1/me/clients/bulk_evaluate (commit=true) as a
            # form-field fallback and by the kintone integration POST.
            # Without it on the allowlist, browser-side preflight rejects the
            # dedup token before the handler can enforce retry safety.
            "Idempotency-Key",
        ],
        expose_headers=[
            "X-Anon-Quota-Remaining",
            "X-Anon-Quota-Reset",
            "X-Anon-Upgrade-Url",
            "X-Anon-Direct-Checkout-Url",
            "X-Anon-Trial-Url",
            "X-Billed-Yen",
            "X-Cost-Yen",
            "X-Cost-Cap-Required",
            "X-Cost-Capped",
            "X-Cap-Yen",
            "X-Used-Yen",
            "X-Remaining-Yen",
            "X-Idempotent-Replay",
            "X-Idempotency-Replayed",
            "X-Metered",
            "Retry-After",
        ],
        max_age=3600,
    )
    app.add_middleware(OriginEnforcementMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

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
            from jpintel_mcp.api._error_envelope import _mint_request_id

            rid = _mint_request_id()
        path_str = str(request.url.path)
        is_am = path_str.startswith("/v1/am/")
        _log.warning(
            "db_missing path=%s is_am=%s err=%s rid=%s",
            path_str,
            is_am,
            exc,
            rid,
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
            # rare — typically a startup-error raise). Use the same ULID
            # mint as the request-context middleware so the id shape stays
            # uniform across log search.
            from jpintel_mcp.api._error_envelope import _mint_request_id

            rid = _mint_request_id()
        _log.exception("unhandled exception request_id=%s path=%s", rid, request.url.path)
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
    app.add_exception_handler(_AnonRateLimitExceeded, anon_rate_limit_exception_handler)

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
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        def _json_safe_error(error: dict[str, object]) -> dict[str, object]:
            safe = dict(error)
            ctx = safe.get("ctx")
            if isinstance(ctx, dict):
                safe["ctx"] = {
                    str(k): v if isinstance(v, (str, int, float, bool)) or v is None else str(v)
                    for k, v in ctx.items()
                }
            return safe

        errors_en = [_json_safe_error(e) for e in exc.errors()]
        errors_ja = [{**e, "msg_ja": _msg_ja.get(e.get("type"), e.get("msg"))} for e in errors_en]
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
        if status_code == 400:
            # R8-ERR-1 (P0) fix: Stripe webhook + other 400 callers used to
            # leak a bare `{"detail":"bad signature"}` (26 bytes, no
            # request_id, no documentation anchor). Wrap 400 in the
            # canonical envelope under `bad_request` while preserving the
            # original `detail` (string OR dict) at the top level so every
            # existing pattern-match in tests + customer agents keeps
            # firing. Router authors that already shape `detail` as a
            # rich dict (e.g. `{"error":"...","code":"..."}`) still get
            # the merged envelope: extras pull through dict keys verbatim.
            #
            # 2026-05-11 install-friction hotfix: also attach a `hint` extra
            # so an LLM agent that hits a 400 because of an UTF-8 raw query
            # string can self-repair without reading our docs. The dominant
            # cause of bare 400s in the wild is `curl "https://api.../search?q=補助金"`
            # which breaks the HTTP request line on most curl builds — the
            # fix is `curl -G --data-urlencode "q=補助金"` (or POST + JSON).
            code = "bad_request"
        elif status_code == 401:
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
            # individual routers (e.g. prescreen validation 422 paths
            # that already carry their own envelope). The router author
            # already chose a body shape.
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
            "Not Found",
            "Method Not Allowed",
            "Unauthorized",
            "Forbidden",
        }:
            extras["detail"] = exc.detail

        if status_code == 400:
            # AI agent self-repair hint: the #1 cause of 400 in the wild
            # is non-ASCII query params passed raw on the request line
            # (curl "...?q=補助金" → most curl builds emit invalid UTF-8
            # in the HTTP request line). The fix is `-G --data-urlencode`
            # for GET, or POST + JSON body. We also surface the canonical
            # docs anchor so an agent has an unambiguous escalation path.
            extras.setdefault(
                "hint",
                "Use --data-urlencode for non-ASCII query params "
                "(e.g. curl -G '<url>' --data-urlencode 'q=補助金'), "
                "or POST with a JSON body. See documentation anchor for the "
                "full repair recipe.",
            )
            extras.setdefault(
                "docs",
                "https://jpcite.com/docs/error_handling#bad_request",
            )
        elif status_code == 404:
            # Suggest a couple of canonical entry points so an LLM caller
            # has somewhere to bounce off when it guesses a wrong path.
            extras.setdefault(
                "suggested_paths",
                [
                    "/v1/openapi.agent.json",
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

    @app.get("/v1/openapi.agent.json", include_in_schema=False)
    def _openapi_agent() -> JSONResponse:
        return JSONResponse(content=build_agent_openapi_schema(app.openapi()))

    # R8 perf, 2026-05-07: Serve the MCP registry manifest (`mcp-server.json`)
    # at /v1/mcp-server.json so the URL referenced by `manifest_url` in that
    # very file resolves to a 200. Reads the file from the Docker runtime
    # layout first (`/app/mcp-server.json`), then falls back to source-tree
    # locations so local tests still work. Cache-Control header is added by
    # StaticManifestCacheMiddleware (LIFO outer) so CF / browsers see the
    # same `public, max-age=300, s-maxage=600` envelope as the OpenAPI
    # manifests.

    @app.get("/v1/mcp-server.json", include_in_schema=False)
    def _mcp_server_manifest() -> JSONResponse:
        manifest_path = _resolve_mcp_server_manifest_path()
        if manifest_path is None:  # pragma: no cover — defensive
            raise HTTPException(status_code=404, detail="mcp-server.json not found")
        text = manifest_path.read_text(encoding="utf-8")
        return JSONResponse(content=json.loads(text))

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
    # /v1/funnel/event — §4-E browser-side breadcrumb sink (Playground
    # success, pricing view, MCP install copy, checkout start, etc.).
    # Hidden from openapi (internal collection sink, not customer API).
    # No AnonIpLimitDep — we want every fire (including rapid bursts on
    # quickstart_copy) recorded; analytics integrity > anti-abuse here.
    app.include_router(funnel_events_router)
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
    # M02 (2026-05-07): 法人格 × 制度 matrix surface — registered BEFORE
    # programs_router so the more-specific paths
    # `/v1/programs/by_corporate_form` and
    # `/v1/programs/{unified_id}/eligibility_by_form` win the strict-query
    # middleware's first-FULL-match walk against the catchall
    # `/v1/programs/{unified_id}` route in programs_router.
    # GET /v1/programs/by_corporate_form?form=<form>&industry_jsic=<axis> +
    # GET /v1/programs/{unified_id}/eligibility_by_form. Pivots
    # am_target_profile (43 法人格 buckets) + am_program_eligibility_predicate_json
    # ($.target_entity_types axis) so callers can narrow by 株式会社 / 合同会社 /
    # NPO / 一般社団 / 学校 / 医療 / 個人事業主 etc. Pure SQLite + Python — NO LLM.
    # Inherits the same 3/日 anon-IP cap as programs_router.
    app.include_router(corporate_form_router, dependencies=[AnonIpLimitDep])
    app.include_router(programs_router, dependencies=[AnonIpLimitDep])
    # R8 (2026-05-07): am_compat_matrix 43,966 rows full-surface.
    # POST /v1/programs/portfolio_optimize + GET /v1/programs/{a}/compatibility/{b}.
    # Pure SQLite + Python over am_compat_matrix + am_funding_stack_empirical +
    # am_program_eligibility_predicate + am_relation.
    from jpintel_mcp.api.compatibility import router as compatibility_router

    app.include_router(compatibility_router, dependencies=[AnonIpLimitDep])
    # R8 GEO REGION API (2026-05-07): 47都道府県 × 1,724市区町村 hit-map.
    # /v1/programs/by_region/{code}, /v1/regions/{code}/coverage, /v1/regions/search.
    app.include_router(regions_router, dependencies=[AnonIpLimitDep])
    # W29-9 fix: customer-agent e2e flow needs the narrative + eligibility
    # predicate caches reachable over HTTP (Wave 24 / W26-6 shipped them
    # MCP-only). Both routes share `/v1/programs/{id}/...` prefix so they
    # mount adjacent to programs_router and inherit the same anon quota.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.eligibility_predicate",
        dependencies=[AnonIpLimitDep],
    )
    _include_experimental_router(
        app,
        "jpintel_mcp.api.narrative",
        dependencies=[AnonIpLimitDep],
    )
    app.include_router(prescreen_router, dependencies=[AnonIpLimitDep])
    app.include_router(exclusions_router, dependencies=[AnonIpLimitDep])
    app.include_router(enforcement_router, dependencies=[AnonIpLimitDep])
    # R8 (2026-05-07): dynamic eligibility check joining 行政処分 history
    # (am_enforcement_detail, autonomath.db) with exclusion_rules
    # (jpintel.db). Pure SQLite walk + static enforcement_kind→severity
    # table — no LLM call. Anon-quota-gated like programs/exclusions.
    app.include_router(eligibility_check_router, dependencies=[AnonIpLimitDep])
    app.include_router(case_studies_router, dependencies=[AnonIpLimitDep])
    # R8 (2026-05-07): cohort matcher (POST /v1/cases/cohort_match) over
    # case_studies (jpintel.db, 2,286) + jpi_adoption_records (autonomath.db,
    # 201,845). Same anon quota gate as case_studies_router.
    app.include_router(case_cohort_match_router, dependencies=[AnonIpLimitDep])
    app.include_router(benchmark_router, dependencies=[AnonIpLimitDep])
    app.include_router(loan_programs_router, dependencies=[AnonIpLimitDep])
    # 2026-05-07 (R8): 災害復興 × 特例制度 surface — three endpoints under
    # /v1/disaster/* projecting the existing programs corpus through a
    # disaster-keyword + prefecture lens. No new schema; pure read.
    app.include_router(disaster_router, dependencies=[AnonIpLimitDep])
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
    # /v1/tax_rules/{rule_id}/full_chain — 税制 + 法令 + 通達 + 裁決 + 判例 +
    # 改正履歴 in 1 call. Pure SQLite over jpintel.db (tax_rulesets / laws /
    # court_decisions) + autonomath.db (nta_tsutatsu_index / nta_saiketsu).
    # Sensitive: 税理士法 §52 / 弁護士法 §72 / 公認会計士法 §47条の2 disclaimer.
    app.include_router(tax_chain_router, dependencies=[AnonIpLimitDep])
    app.include_router(invoice_registrants_router, dependencies=[AnonIpLimitDep])
    # R8 invoice risk lookup (2026-05-07): /v1/invoice_registrants/{tnum}/risk
    # + /v1/invoice_registrants/batch_risk + /v1/houjin/{bangou}/invoice_status.
    # Composes invoice_registrants × houjin_master + registration-age heuristic
    # into a 0-100 score + tax_credit_eligible boolean. Pure SQL + Python; NO
    # LLM. PDL v1.0 attribution + §52 _disclaimer on every 2xx body.
    app.include_router(invoice_risk_router, dependencies=[AnonIpLimitDep])
    app.include_router(invoice_risk_houjin_router, dependencies=[AnonIpLimitDep])
    # /v1/evidence/packets/* — Evidence Packet composer (LLM-resilient
    # business plan §6). Bundles primary metadata + per-fact provenance +
    # compat-matrix rule verdicts into one envelope. ¥3/req metered;
    # anonymous tier inherits the 3/day IP cap via AnonIpLimitDep.
    app.include_router(evidence_router, dependencies=[AnonIpLimitDep])
    # /v1/evidence/packets/batch — paid-only bulk composer. It enforces
    # metered API key auth inside the handler and should not burn anonymous
    # quota before returning its auth/cap envelope.
    _include_experimental_router(app, "jpintel_mcp.api.evidence_batch")
    # /v1/source_manifest/{program_id} — per-program source rollup.
    app.include_router(source_manifest_router, dependencies=[AnonIpLimitDep])
    # /v1/citations/verify — deterministic citation verifier.
    app.include_router(citations_router, dependencies=[AnonIpLimitDep])
    # /v1/verify/answer — DEEP-25 + DEEP-37 verifiable answer primitive.
    # 4-axis weighted score (sources_match + sources_alive + corpus_present
    # + boundary_clean), claim_count cap = 5, ¥3/req, LLM call 0.
    app.include_router(verify_router, dependencies=[AnonIpLimitDep])
    # /widget/badge.svg + /citation/{request_id} — DEEP-27 jpcite verified
    # badge widget (CL-08). 4 SVG states (verified / expired / invalid /
    # boundary_warn) backed by `citation_log` (mig wave24_183) + static
    # MD render. NO LLM call. NO AnonIpLimitDep — the badge MUST render
    # on every customer-page hit, otherwise the trust signal breaks; the
    # Cloudflare Worker layer handles per-IP rate limiting at 60 req/min.
    app.include_router(citation_badge_router)
    # /v1/cost/preview — Evidence Pre-fetch Layer estimator (no LLM).
    # Free/non-metered estimator: it has its own short per-IP throttle and
    # must not burn the anonymous 3/day discovery allowance.
    app.include_router(cost_router)
    # /v1/calculator/savings — public ROI estimator. Pure arithmetic,
    # no DB write and no metering; keep it outside AnonIpLimitDep so the
    # marketing calculator can call it repeatedly without burning API quota.
    _include_experimental_router(app, "jpintel_mcp.api.calculator")
    # /v1/intelligence/precomputed/query — compact precomputed context
    # bundle for offline token-cost benchmarking and LLM prefetch flows.
    app.include_router(intelligence_router, dependencies=[AnonIpLimitDep])
    # /v1/intel/probability_radar — program × houjin radar bundle
    # (probability estimate + same-industry rate + ROI + evidence) in 1 call.
    # Pure SQLite over am_recommended_programs / am_adopted_company_features /
    # jpi_adoption_records. Sensitive: §52 / 行政書士法 §1 disclaimer.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/program/{program_id}/full — composite per-program bundle
    # (meta + eligibility + amendments + adoptions + similar + citations +
    # audit_proof) in 1 call. Replaces the 8-call fan-out a customer LLM
    # otherwise has to assemble. Pure SQLite over programs /
    # am_program_eligibility_predicate / am_amendment_diff /
    # jpi_adoption_records / am_recommended_programs / program_law_refs /
    # nta_tsutatsu_index / audit_merkle_anchor. Sensitive: §52 / §1 / §72.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_program_full",
        attr="intel_program_full_router",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/citation_pack/{program_id} — markdown / json bundle of every
    # primary-source citation surface (法令 / 通達 / 裁決 / 判例 / 行政処分 /
    # 採択) for a program in 1 call. Pure SQLite cross-join of
    # program_law_refs / laws / nta_tsutatsu_index / nta_saiketsu /
    # court_decisions / enforcement_cases / adoption_records. Sensitive:
    # §52 / §47条の2 / §1 / §72 disclaimer.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_citation_pack",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/regulatory_context/{program_id} — program → 法令 + 通達 +
    # 裁決 + 判例 + 行政処分 full regulatory bundle in 1 call. Pure SQLite
    # over program_law_refs / laws / am_law_article / nta_tsutatsu_index /
    # nta_saiketsu / court_decisions / enforcement_cases. Sensitive: 弁護士法
    # §72 + 税理士法 §52 + 行政書士法 §1 disclaimer.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_regulatory_context",
        dependencies=[AnonIpLimitDep],
    )
    # R8 cross-reference deep link API (2026-05-07).
    _include_experimental_router(
        app,
        "jpintel_mcp.api.programs_full_context",
        dependencies=[AnonIpLimitDep],
    )
    _include_experimental_router(
        app,
        "jpintel_mcp.api.programs_full_context",
        attr="laws_cross_router",
        dependencies=[AnonIpLimitDep],
    )
    _include_experimental_router(
        app,
        "jpintel_mcp.api.programs_full_context",
        attr="cases_cross_router",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/timeline/{program_id} — annual cross-substrate event timeline
    # (amendment + adoption + enforcement + narrative_update). Pure SQLite
    # over am_amendment_diff / am_adoption_trend_monthly /
    # am_enforcement_anomaly / am_adopted_company_features /
    # am_program_narrative_full. Sensitive: §52 / §1 / §72 disclaimer.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_timeline",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/actionable/* — pre-rendered actionable Q/A cache lookup
    # (Wave 30-5). Top-N (intent_class × input_dict) tuples are precomputed
    # offline by scripts/cron/precompute_actionable_answers.py into
    # am_actionable_qa_cache (migration 169). On hit returns the cached
    # envelope (¥3 metered, hit_count bumped); on miss returns 404 with
    # {_not_cached: true} so the caller can fall back to the on-demand
    # composer. NO LLM call. Pure SQLite + sha256.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_actionable",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/diff — composite entity-comparison endpoint (M&A DD).
    # Returns shared / unique_to_a / unique_to_b / conflict_points across
    # programs / houjin_master / am_law_article + am_5hop_graph (depth) +
    # am_program_eligibility_predicate + am_id_bridge. Pure SQLite, no LLM.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_diff",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/path — bidirectional BFS reasoning chain between 2 entities.
    # Joins am_5hop_graph (Wave 24 §152) + am_citation_network (Wave 24 §163)
    # + am_id_bridge (159) and returns shortest path + up to 3 alternates so
    # a customer LLM can visualise the citation chain in 1 RPC. Pure SQLite,
    # no LLM. Sensitive: §52 / §72 / §1 disclaimer.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_path",
        dependencies=[AnonIpLimitDep],
    )
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_risk_score",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/conflict — combo conflict detector + alternative bundles.
    # Cross-joins am_funding_stack_empirical (実証 stack co-occurrence) +
    # am_program_eligibility_predicate (法的 mutual exclusion) +
    # am_compat_matrix (rule-based fallback). Returns conflict_pairs +
    # compatible_subset + top-3 alternative_bundles. Pure SQLite + Python
    # graph walk. Sensitive: §52 / §1 / §72 disclaimer.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_conflict",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/why_excluded — eligibility-failure reasoning + remediation +
    # alternative-program suggestion in 1 call. Cross-joins
    # am_program_eligibility_predicate_json (W26-6) with houjin attrs
    # (am_entities corp.*) and am_recommended_programs (W29-8). Pure
    # SQLite + Python diff. Sensitive: 行政書士法 §1 / 税理士法 §52 fence.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_why_excluded",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/bundle/optimal — houjin → 最適 program bundle (greedy weighted
    # max-IS) in 1 call. Cross-joins am_recommended_programs (W29-8 precomputed
    # top-N per houjin) + am_program_eligibility_predicate (W26-6 predicate
    # filter) + am_funding_stack_empirical (W22-6 conflict edges) + jpi_programs
    # (amount roll-up). Returns bundle + bundle_total + conflict_avoidance +
    # optimization_log + runner_up_bundles. Pure SQLite + Python greedy. Sensitive:
    # 行政書士法 §1 / 税理士法 §52 fence.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_bundle_optimal",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/houjin/{houjin_id}/full — composite houjin 360 bundle
    # (meta + adoption_history + enforcement + invoice_status + peer_summary +
    # jurisdiction + watch_status) in 1 GET. Cross-joins houjin_master +
    # am_adopted_company_features + am_enforcement_detail + invoice_registrants
    # + am_geo_industry_density + customer_watches (mig 088). Pure SQLite,
    # NO LLM. Sensitive: §52 / §72 / 行政書士法 §1 disclaimer.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_houjin_full",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/intel/peer_group — 同業他社 N peers (Jaccard on jsic + prefecture +
    # log-bucketed capital/employees) + per-peer adoption facts + statistical
    # context + peer-validated program recs. Cross-joins houjin_master +
    # am_adopted_company_features + am_geo_industry_density + am_entity_facts
    # + jpi_adoption_records + jpi_programs. Pure SQLite + Python. Sensitive:
    # 景表法 / 行政書士法 §1 / 税理士法 §52 fence.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.intel_peer_group",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/funding_stack/check — pure rule engine over compat_matrix + exclusion_rules.
    app.include_router(funding_stack_router, dependencies=[AnonIpLimitDep])
    # /v1/funding_stages/catalog (FREE) + /v1/programs/by_funding_stage (¥3/req).
    # Stage-aware program matcher. Pure SQL over jpintel.programs with a closed
    # 5-stage enum (seed / early / growth / ipo / succession). Catalog path is
    # constant data and never billed; matcher path is metered + anon-quota-gated
    # so the 3/日 IP limit composes with the rest of the discovery surfaces.
    app.include_router(funding_stage_router, dependencies=[AnonIpLimitDep])
    # /v1/artifacts/compatibility_table — same rule engine wrapped as a
    # copy-paste-ready artifact envelope. The artifact backend is shipped as
    # its own packet, so a hardening-only checkout must still boot without it.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.artifacts",
        dependencies=[AnonIpLimitDep],
    )
    # /v1/artifacts/company_public_baseline + company_folder_brief +
    # company_public_audit_pack — public-source corporate diligence pack.
    # Always-on (NOT gated behind AUTONOMATH_EXPERIMENTAL_API_ENABLED) so the
    # 24 contract tests in tests/test_artifacts_company_public_packs.py and
    # downstream MCP/SDK consumers can rely on the routes existing on every
    # production boot. Pure SQLite + Python builders defined in
    # jpintel_mcp.api.artifacts; NO LLM. §47条の2 + §52 + §72 + §3 fenced.
    from jpintel_mcp.api.company_public_packs import router as company_public_packs_router

    app.include_router(company_public_packs_router, dependencies=[AnonIpLimitDep])
    # /v1/discover/related/{entity_id} — multi-axis (5) related entity composer.
    # Pure SQL + sqlite-vec over am_5hop_graph / am_funding_stack_empirical /
    # am_entity_density_score / am_entities_vec_* + program_law_refs. Same
    # anon 3/日 IP cap as the other discovery surfaces.
    app.include_router(discover_router, dependencies=[AnonIpLimitDep])
    # /v1/programs/{id}/at + /v1/programs/{id}/evolution/{year} — DEEP-22
    # Regulatory Time Machine. Pivots off am_amendment_snapshot
    # (14,596 captures + 144 definitive-dated). Pure SQL + Python — NO LLM.
    # ¥3/req metered, anonymous tier shares the 3/日 IP cap.
    app.include_router(time_machine_router, dependencies=[AnonIpLimitDep])
    # /v1/houjin/{bangou} — corporate 360 lookup surfacing 1.12M gBizINFO
    # facts already in autonomath.db (am_entities corporate_entity +
    # am_entity_facts corp.*). Same anon-quota posture as the other
    # discovery surfaces — 3/日 per-IP cap applies.
    app.include_router(houjin_router, dependencies=[AnonIpLimitDep])
    # /v1/succession/* — M&A / 事業承継 制度 matcher.
    # Surfaces the 事業承継 chain (経営承継円滑化法 + 事業承継税制 +
    # 事業承継・引継ぎ補助金 + M&A補助金 + 都道府県融資 + 政策金融公庫融資).
    # Pure SQL + Python, NO LLM. ¥3/req metered (1 unit per call).
    # Anonymous tier shares the 3/日 IP cap. M&A pillar of the
    # cohort revenue model — pairs with houjin_watch (mig 088).
    app.include_router(succession_router, dependencies=[AnonIpLimitDep])
    # /v1/houjin/{houjin_bangou}/360 — R8 unified houjin 360 surface
    # (master + adoption_records + enforcement_cases + bids_won +
    # invoice_registrant_status + recent_news + watch_alerts + 3-axis
    # scoring). Cross-joins houjin_master + jpi_adoption_records +
    # am_enforcement_detail + bids + jpi_invoice_registrants +
    # am_amendment_diff + customer_watches. Pure SQL + Python; NO LLM.
    # Sensitive: §52 / §72 / §1 fence on the disclaimer envelope.
    from jpintel_mcp.api.houjin_360 import router as houjin_360_router

    app.include_router(houjin_360_router, dependencies=[AnonIpLimitDep])
    # /v1/calendar/deadlines is live (activated from preview 2026-04-24).
    # Previously gated behind enable_preview_endpoints; now a first-class
    # discovery surface, so it mounts unconditionally.
    app.include_router(calendar_router, dependencies=[AnonIpLimitDep])
    # R8 (2026-05-07): /v1/programs/{id}/timeline + /v1/cases/timeline_trend
    # + /v1/me/upcoming_rounds_for_my_profile. Annual adoption rollup over
    # jpi_adoption_records (201,845) + next_round (am_application_round
    # 1,256, 422 open / 493 upcoming) + per-profile fan-out match against
    # client_profiles. Pure SQLite + Python — NO LLM. ¥3 / call flat.
    # §52 / §47条の2 / §1 fence on the trend surfaces; §1 only on the
    # upcoming-rounds list (pure schedule data).
    from jpintel_mcp.api.timeline_trend import router as timeline_trend_router

    app.include_router(timeline_trend_router, dependencies=[AnonIpLimitDep])
    app.include_router(billing_router)
    # /v1/billing/client_tag_breakdown — authenticated control-plane read.
    # It is never billable and must not consume the public anonymous free
    # allowance when an unauthenticated caller gets a 401.
    app.include_router(billing_breakdown_router)
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
    # 3 req/日 IP quota.
    app.include_router(dashboard_router)
    app.include_router(feedback_router)
    # DEEP-28 + DEEP-31 customer contribution. Anonymous-accepting (no
    # API key required); rate-limited per-IP 5 / 24h inside the handler
    # PLUS the AnonIpLimitDep daily 3 cap. Server-side scrubber rejects
    # PII (マイナンバー / phone / email), aggregator URLs (INV-04 banlist),
    # and program_id mismatches. Writes to autonomath.db
    # contribution_queue (migration wave24_184).
    app.include_router(contribute_router, dependencies=[AnonIpLimitDep])
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
    # R8 amendment-alert subscription feed (jpcite v0.3.4). Multi-watch
    # subscription surface joined against am_amendment_diff (autonomath.db).
    # Subscriptions + feed read are FREE retention features (no ¥3/req
    # surcharge). Distinct from alerts_router (legacy single-filter form)
    # — this surface speaks watch:[{type,id}] arrays from day one. Mounted
    # under /v1/me/amendment_alerts. Anonymous callers are 401'd inside the
    # router itself; no AnonIpLimitDep wrapper needed.
    app.include_router(amendment_alerts_router)
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
    # GitHub OAuth sign-in surface (R8 audit gap — ``/v1/auth/github/*``
    # was 404 in production after Fly secrets ``GITHUB_OAUTH_CLIENT_ID``
    # / ``GITHUB_OAUTH_CLIENT_SECRET`` were deployed but the router was
    # never mounted). Pre-auth: caller does NOT need an API key to begin
    # OAuth — anon IP rate limit applies so brute-force state probes are
    # capped at 3/日 per IP. Scopes are read-only (``read:user
    # user:email``); no GitHub-side credentials are persisted.
    from jpintel_mcp.api.auth_github import router as auth_github_router

    app.include_router(auth_github_router, dependencies=[AnonIpLimitDep])
    # Google OAuth sign-in surface — paired with auth_github above.
    # Distinct from the existing /v1/integrations/google/* path which
    # handles Google Sheets write integration (separate scope set +
    # refresh-token persistence). This module is sign-in only:
    # exchanges code for id_token, validates aud/iss, mints a
    # jpcite-side JWT cookie, redirects to dashboard. Returns 503 when
    # GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set,
    # same shape as the GitHub unconfigured branch.
    from jpintel_mcp.api.auth_google import router as auth_google_router

    app.include_router(auth_google_router, dependencies=[AnonIpLimitDep])
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
    # Wave 24 REST wrappers for the extended /v1/am/* surface.
    _include_experimental_router(
        app,
        "jpintel_mcp.api.wave24_endpoints",
        dependencies=[AnonIpLimitDep],
    )
    # DEEP-46 政策 上流 signal 統合 (2 endpoints: POST /watch + GET
    # /{topic}/timeline). Cross-axis rollup over kokkai_utterance +
    # shingikai_minutes + pubcomment_announcement + am_amendment_diff +
    # jpi_programs. NO LLM, single ¥3/req billing per call. Mounted
    # with AnonIpLimitDep so the 3/日 per-IP quota applies; paid keys
    # bypass the anon ceiling and bill normally.
    app.include_router(policy_upstream_router, dependencies=[AnonIpLimitDep])
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
    # W29-9 fix: per-evidence-packet Merkle inclusion proof
    # (GET /v1/audit/proof/{evidence_packet_id}). Mounted WITHOUT
    # AnonIpLimitDep — public read; the audit-log moat IS the moat,
    # third-party verification cannot be paywalled. See
    # api/audit_proof.py module docstring.
    _include_experimental_router(app, "jpintel_mcp.api.audit_proof")
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
            "name": "jpcite Support",
            "url": "https://jpcite.com/tokushoho.html",
        }
        schema["info"]["termsOfService"] = "https://jpcite.com/tos.html"
        schema["info"]["license"] = {
            "name": "Proprietary - see termsOfService",
        }
        # Root-level tags block (R8_AI_CONSUMER_AUDIT recommended #1).
        # Each tag carries a 2-line description so AI-side OpenAPI consumers
        # (Stainless / ReDoc / Mintlify / Custom GPTs / MCP wrappers) can
        # render human-readable section headings instead of raw slug labels.
        # The vocabulary mirrors the operation-level tag values already
        # emitted by individual routers — adding/changing operation tags
        # requires adding an entry here too.
        schema["tags"] = [
            {
                "name": "programs",
                "description": (
                    "Search and detail-lookup over the unified Japanese "
                    "public-program corpus (補助金 / 助成金 / 融資 / 税制 / 認定). "
                    "Primary discovery surface — most callers start here."
                ),
            },
            {
                "name": "jpcite",
                "description": (
                    "Unified `/v1/am/*` surface over the autonomath.db "
                    "entity-fact corpus (税制特例 / 認定 / 法令照会 / 採択統計 / "
                    "行政処分 / 融資 / 共済). Each response carries a "
                    "`_disclaimer` envelope (税理士法 §52 fence)."
                ),
            },
            {
                "name": "jpcite-health",
                "description": (
                    "Heartbeat / deep-health probes for the jpcite surface. "
                    "Unbilled and unrate-limited; safe for production uptime "
                    "monitoring without consuming the anonymous quota."
                ),
            },
            {
                "name": "case-studies",
                "description": (
                    "採択事例 (real awarded grants / 認定 outcomes) for "
                    "prior-art research. Backed by 2,286 indexed cases."
                ),
            },
            {
                "name": "loan-programs",
                "description": (
                    "融資商品 (108 products) decomposed across three "
                    "independent risk axes: 担保 / 個人保証人 / 第三者保証人."
                ),
            },
            {
                "name": "enforcement-cases",
                "description": (
                    "行政処分 history (1,185 records). Pre-credit / "
                    "pre-subsidy DD lookups by 法人番号 or party name."
                ),
            },
            {
                "name": "laws",
                "description": (
                    "e-Gov 法令 lookup (CC-BY 4.0). 9,484 metadata records "
                    "with article references where available; body/article "
                    "coverage varies by record."
                ),
            },
            {
                "name": "tax_rulesets",
                "description": (
                    "Structured 税務判定ルールセット (50 rulesets) — 2割特例, "
                    "経過措置, 電子帳簿保存法, 研究開発税制, IT導入会計処理. "
                    "Evaluate caller-supplied 事業者プロファイル against rules."
                ),
            },
            {
                "name": "court-decisions",
                "description": (
                    "判例 corpus (2,065 decisions). Includes 国税不服審判所 "
                    "裁決事例 + 通達 references on §52-relevant tax surfaces."
                ),
            },
            {
                "name": "bids",
                "description": (
                    "公共入札 案件 (362 records). Active 案件 by 発注機関 / industry / 締切 date."
                ),
            },
            {
                "name": "invoice_registrants",
                "description": (
                    "適格請求書発行事業者 (国税庁 PDL v1.0 mirror, 13,801 "
                    "current mirror rows; scheduled source refresh). Confirm a "
                    "13-digit 法人番号 is registered. Attribution required."
                ),
            },
            {
                "name": "intelligence",
                "description": (
                    "Pre-computed compact evidence packets for AI workflows. "
                    "Call before answer generation to retrieve source-linked "
                    "context with optional baseline compression."
                ),
            },
            {
                "name": "evidence",
                "description": (
                    "Evidence-packet builder + value-guidance schema. "
                    "Bundles retrieval results into citation-ready payloads."
                ),
            },
            {
                "name": "verify",
                "description": (
                    "Verifier endpoints — confidence scores, cross-source "
                    "agreement, identity-confidence golden tests."
                ),
            },
            {
                "name": "trust",
                "description": (
                    "Trust infrastructure surface: SLA, corrections feed, "
                    "cross-source agreement, stale-data tracking."
                ),
            },
            {
                "name": "transparency",
                "description": (
                    "Public methodology + source-license + audit-trail "
                    "documentation. Read-only; no auth required."
                ),
            },
            {
                "name": "audit",
                "description": (
                    "税理士 / 会計士 monthly audit-seal pack endpoints. Authenticated keys only."
                ),
            },
            {
                "name": "audit-log",
                "description": ("Append-only audit log + RSS feed regeneration."),
            },
            {
                "name": "audit (会計士・監査法人)",
                "description": (
                    "監査法人 / 会計士 surface — companion seals, attestation "
                    "exports, signed retrieval logs."
                ),
            },
            {
                "name": "billing",
                "description": (
                    "Stripe metered billing — Checkout, customer portal, "
                    "billing breakdown, predictive cap alerts. ¥3/billable "
                    "unit, 税込 ¥3.30, no tier SKUs."
                ),
            },
            {
                "name": "compliance",
                "description": (
                    "Compliance subscription + checkout for the enterprise "
                    "compliance product (subscription billing, not metered)."
                ),
            },
            {
                "name": "advisors",
                "description": (
                    "Advisor signup + Stripe Connect onboarding + 法人番号 verification flow."
                ),
            },
            {
                "name": "subscribers",
                "description": ("Newsletter / digest subscription opt-in + verification."),
            },
            {
                "name": "signup",
                "description": (
                    "Trial signup + magic-link verification. Issues a "
                    "single-use trial key; not connected to paid billing."
                ),
            },
            {
                "name": "device",
                "description": ("OAuth device-flow endpoints for CLI / headless agents."),
            },
            {
                "name": "me",
                "description": (
                    "Caller-self surface — current usage, key metadata, "
                    "preferences. Requires API-key authentication."
                ),
            },
            {
                "name": "dashboard",
                "description": (
                    "Per-key dashboard views — usage history, quota, billing breakdown summary."
                ),
            },
            {
                "name": "usage",
                "description": (
                    "Anonymous + authenticated usage / quota probe. "
                    "Surfaces remaining 3/日 anon allowance + reset window."
                ),
            },
            {
                "name": "saved-searches",
                "description": (
                    "User-defined saved searches with optional 顧問先 "
                    "fan-out and email/Slack delivery cadence."
                ),
            },
            {
                "name": "client-profiles",
                "description": (
                    "顧問先 master records for the 税理士 / 補助金 consultant "
                    "fan-out cohorts. Sub-API-key parent/child supported."
                ),
            },
            {
                "name": "courses",
                "description": (
                    "Recurring engagement substrate — Slack digest, email "
                    "course, quarterly PDF generation cadence."
                ),
            },
            {
                "name": "recurring",
                "description": (
                    "Quarterly PDF + Slack webhook delivery for recurring "
                    "engagement (税理士 / 会計士 cohorts)."
                ),
            },
            {
                "name": "alerts",
                "description": (
                    "Alert subscription endpoints — program updates, "
                    "houjin watch, deadline calendar."
                ),
            },
            {
                "name": "customer_webhooks",
                "description": (
                    "Per-key outbound webhook registry. Signing secret "
                    "returned once on creation; subsequent reads expose "
                    "only a short signing-secret hint."
                ),
            },
            {
                "name": "customer_watches",
                "description": (
                    "Customer-defined watch lists (houjin / program / "
                    "law amendment cadence triggers)."
                ),
            },
            {
                "name": "calendar",
                "description": (
                    "Deadline / 公募 calendar surface. Read-only feeds + "
                    "post-award calendar wiring."
                ),
            },
            {
                "name": "exclusions",
                "description": (
                    "Exclusion / prerequisite rule lookup (181 rules). "
                    "Pair with `/v1/programs/prescreen` for the full chain."
                ),
            },
            {
                "name": "feedback",
                "description": (
                    "User feedback intake — corrections, missing-program "
                    "reports, content quality flags."
                ),
            },
            {
                "name": "contribute",
                "description": (
                    "Public contribution path for community-sourced "
                    "corrections. Trust-scored, queue-moderated."
                ),
            },
            {
                "name": "corrections",
                "description": ("Published corrections feed — what changed, when, why."),
            },
            {
                "name": "discover",
                "description": (
                    "One-shot discovery wrappers (smb_starter_pack, "
                    "subsidy_combo_finder, deadline_calendar, etc.)."
                ),
            },
            {
                "name": "stats",
                "description": (
                    "Public statistics surface — corpus counts, freshness, "
                    "tier breakdown. Includes funnel-analytics export."
                ),
            },
            {
                "name": "meta",
                "description": (
                    "Spec metadata — server version, build hash, OpenAPI "
                    "agent projection, source manifests."
                ),
            },
            {
                "name": "source_manifest",
                "description": (
                    "Per-source manifest — license, attribution, fetched_at, refresh cadence."
                ),
            },
            {
                "name": "houjin",
                "description": (
                    "法人番号 lookup + houjin_watch cohort surface (M&A deal-side cohort)."
                ),
            },
            {
                "name": "ma_dd",
                "description": (
                    "M&A due-diligence helpers — DD question matcher, "
                    "decision insights, peer-group baselines."
                ),
            },
            {
                "name": "funding-stack",
                "description": (
                    "Funding-stack assembly + complementary-program search. "
                    "Wave 21 composition tools."
                ),
            },
            {
                "name": "bulk-evaluate",
                "description": (
                    "Batch evaluation surface — apply a ruleset to many "
                    "profiles in one call. Documents fan-out billing."
                ),
            },
            {
                "name": "integrations",
                "description": (
                    "Excel / kintone / freee / MF integration shims — "
                    "tabular-output and email-reply variants."
                ),
            },
            {
                "name": "widget",
                "description": (
                    "Embeddable search widget surface — origin-locked, widget-key authenticated."
                ),
            },
            {
                "name": "artifacts",
                "description": (
                    "Generated artifact builders — company public packs, "
                    "folder briefs, audit-pack PDFs."
                ),
            },
            {
                "name": "citations",
                "description": (
                    "Citation builder — turn corpus rows into "
                    "citation-ready blocks for downstream LLM use."
                ),
            },
            {
                "name": "citation_badge",
                "description": ("Embeddable citation badge / SVG endpoints."),
            },
            {
                "name": "testimonials",
                "description": (
                    "Public testimonial submission + admin moderation + "
                    "caller-self testimonial management."
                ),
            },
            {
                "name": "time_machine",
                "description": (
                    "Snapshot-as-of querying — replay corpus state at a "
                    "given timestamp when the snapshot feature flag is enabled."
                ),
            },
            {
                "name": "cost",
                "description": (
                    "Cost-cap header + billing-cap alerting. Header-driven "
                    "X-Cost-Cap-JPY / Idempotency-Key contract."
                ),
            },
            {
                "name": "email",
                "description": ("Inbound email parse + outbound transactional webhook callbacks."),
            },
            {
                "name": "privacy",
                "description": ("APPI deletion + disclosure request endpoints."),
            },
            {
                "name": "sla",
                "description": ("Published SLA telemetry + uptime metrics."),
            },
            {
                "name": "staleness",
                "description": (
                    "Stale-data tracking — when each source was last "
                    "verified vs the current snapshot."
                ),
            },
            {
                "name": "cross_source",
                "description": (
                    "Cross-source agreement audit — which sources agree "
                    "vs disagree on a given 法人番号 / program."
                ),
            },
        ]
        _normalize_openapi_component_schema_names(schema)
        _prune_openapi_public_paths(schema)
        _sanitize_openapi_public_schema(schema)
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
        host="0.0.0.0",  # nosec B104 - intentional bind on Fly.io container; ingress is fronted by Fly proxy
        port=8080,
        reload=False,
        log_config=None,
        timeout_graceful_shutdown=30,
    )


if __name__ == "__main__":
    run()
