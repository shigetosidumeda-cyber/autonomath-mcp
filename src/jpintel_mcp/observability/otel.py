"""OpenTelemetry distributed tracing initialiser for the jpcite API.

Wave 18 E2 — production telemetry surface that is **strictly stdlib +
opentelemetry-api / opentelemetry-sdk only**. No LLM provider SDK
(``anthropic`` / ``openai`` / ``google.generativeai``) is imported or
referenced — this module deals only in OTLP HTTP export to a generic
collector backend (Tempo / DataDog Free / Jaeger / Honeycomb / Grafana
Cloud / SigNoz).

The intent is to give every REST request a ``trace_id`` + ``span_id``
that propagates through middleware, router, and DB layer so a single
``trace_id`` lookup in the collector pulls the entire call graph.
Combined with the request-id contextvar already emitted in
``_RequestContextMiddleware``, this lets operator triage move from
"a customer reports a 502" → "this is the trace with the 30s SQL hang"
in one query.

Design constraints
------------------
* Never raise. Telemetry must never block the hot path; every import
  failure / config error returns False and the API continues without
  tracing. The unit test for this module asserts the public entry
  points are total over the failure modes.
* Two-gate activation: ``OTEL_EXPORTER_OTLP_ENDPOINT`` env var present
  AND ``opentelemetry`` package importable. Dev / CI runs without the
  endpoint see ``init_otel() → False`` and ``instrument_fastapi(app)``
  becomes a no-op.
* Sampling rate: ``OTEL_SAMPLE_RATE`` env var (float, 0.0..1.0). Default
  0.01 in production (1%) so a 10 req/s API costs ~864k spans/day instead
  of 86.4M — fits comfortably inside any collector free tier. Local dev
  bumps to 1.0 (100%) via ``JPINTEL_ENV=dev``.
* No LLM API import. We are forbidden from spending customer LLM tokens
  on infra plumbing (memory: ``feedback_autonomath_no_api_use`` +
  ``feedback_no_operator_llm_api``). OTLP HTTP export is fine — it's
  bounded-cost telemetry, not generative inference.
* Idempotent: ``init_otel()`` is safe to call multiple times; only the
  first call configures the global ``TracerProvider``.

Public surface
--------------
``init_otel() -> bool``
    Configure ``TracerProvider`` + OTLP HTTP exporter with the
    environment-driven sampler. Returns True iff a real exporter was
    wired (False on missing env / missing package / config error).

``instrument_fastapi(app) -> bool``
    Apply ``FastAPIInstrumentor`` to the given FastAPI app so every
    incoming HTTP request is wrapped in a server span. No-op when
    ``init_otel()`` did not succeed.

``current_trace_id() -> str | None``
    Return the active span's hex trace id (32 chars) or None when there
    is no active span / OTel is not initialised. Useful for log
    enrichment without forcing every log site to import OTel directly.

Backend wiring is done via the standard OTLP env vars:

* ``OTEL_EXPORTER_OTLP_ENDPOINT`` — collector URL (Tempo, DataDog
  ``https://otlp.datadoghq.com``, Jaeger, etc.). When unset, init
  short-circuits and no exporter is created.
* ``OTEL_EXPORTER_OTLP_HEADERS`` — comma-separated ``key=value`` headers
  (api-token, dd-api-key, etc.).
* ``OTEL_SAMPLE_RATE`` — float in [0, 1]. Default 0.01 prod, 1.0 dev.
* ``OTEL_SERVICE_NAME`` — defaults to ``jpcite-api``.

See ``docs/observability/otel_setup.md`` for backend-specific guidance.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("jpcite.observability.otel")

_INIT_ATTEMPTED = False
_INIT_OK = False
_DEFAULT_SERVICE_NAME = "jpcite-api"
_DEFAULT_PROD_SAMPLE_RATE = 0.01
_DEFAULT_DEV_SAMPLE_RATE = 1.0


def _resolve_sample_rate() -> float:
    """Return the configured trace sampler ratio (0.0..1.0).

    Precedence:
      1. ``OTEL_SAMPLE_RATE`` env var (explicit override, parsed as float)
      2. ``JPINTEL_ENV=prod`` → 0.01
      3. otherwise → 1.0 (dev / test capture everything)

    Invalid / out-of-range values fall back to the env default; we never
    raise on misconfiguration here because telemetry must never block
    the hot path.
    """
    raw = os.getenv("OTEL_SAMPLE_RATE", "").strip()
    if raw:
        try:
            v = float(raw)
            if 0.0 <= v <= 1.0:
                return v
        except (TypeError, ValueError):
            pass
    env = os.getenv("JPINTEL_ENV", "dev").strip().lower()
    if env in ("prod", "production"):
        return _DEFAULT_PROD_SAMPLE_RATE
    return _DEFAULT_DEV_SAMPLE_RATE


def _resolve_headers() -> dict[str, str]:
    """Parse ``OTEL_EXPORTER_OTLP_HEADERS`` (comma-separated key=value)."""
    raw = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    if not raw:
        return {}
    out: dict[str, str] = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip()
        v = v.strip()
        if k:
            out[k] = v
    return out


def init_otel() -> bool:
    """Configure the global TracerProvider + OTLP HTTP exporter.

    Idempotent — subsequent calls short-circuit on the cached ``_INIT_OK``
    flag. Returns True iff a real OTLP exporter was wired.
    """
    global _INIT_ATTEMPTED, _INIT_OK

    if _INIT_ATTEMPTED:
        return _INIT_OK
    _INIT_ATTEMPTED = True

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        # No collector configured — silent no-op, do not warn (this is
        # the expected state in dev / CI / unit tests).
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError as exc:
        logger.warning(
            "opentelemetry packages missing — tracing disabled. "
            "Install with `pip install opentelemetry-api "
            "opentelemetry-sdk opentelemetry-exporter-otlp-proto-http "
            "opentelemetry-instrumentation-fastapi`. exc=%s",
            type(exc).__name__,
        )
        return False

    try:
        service_name = os.getenv("OTEL_SERVICE_NAME", _DEFAULT_SERVICE_NAME).strip()
        env = os.getenv("JPINTEL_ENV", "dev").strip().lower()
        # Resource attributes follow the OTel semantic-conventions
        # registry — keep them stable so backend dashboards survive a
        # re-deploy. service.version pulls from the package import to
        # avoid a hard-coded value drifting from pyproject.toml.
        try:
            from jpintel_mcp import __version__ as _pkg_version
        except Exception:  # noqa: BLE001 — defensive at import time
            _pkg_version = "0.0.0"
        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": _pkg_version,
                "deployment.environment": env,
            }
        )
        sampler = TraceIdRatioBased(_resolve_sample_rate())
        provider = TracerProvider(resource=resource, sampler=sampler)
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=_resolve_headers() or None,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _INIT_OK = True
        logger.info(
            "otel_init_ok endpoint=%s sample_rate=%.3f service=%s env=%s",
            endpoint,
            _resolve_sample_rate(),
            service_name,
            env,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — telemetry never raises on hot path
        logger.warning(
            "otel_init_failed — tracing disabled. exc=%s msg=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
        _INIT_OK = False
        return False


def instrument_fastapi(app: FastAPI) -> bool:
    """Wrap ``app`` so every HTTP request is captured as a server span.

    No-op when ``init_otel()`` did not succeed or the FastAPI
    instrumentation package is missing. Idempotent — the upstream
    ``FastAPIInstrumentor.instrument_app`` is itself idempotent.
    """
    if not _INIT_OK:
        return False
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError as exc:
        logger.warning(
            "opentelemetry-instrumentation-fastapi missing — REST spans "
            "disabled. exc=%s",
            type(exc).__name__,
        )
        return False
    try:
        # ``excluded_urls`` keeps the trace stream focused on user-facing
        # surfaces — health / readiness probes hit every 5-15s and would
        # otherwise dominate the sample. Comma-separated path-prefix list
        # matches the OTel-standard env var when set.
        excluded = os.getenv(
            "OTEL_PYTHON_FASTAPI_EXCLUDED_URLS",
            "healthz,readyz,metrics",
        )
        FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded)
        logger.info("otel_instrument_fastapi_ok excluded=%s", excluded)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "otel_instrument_fastapi_failed exc=%s msg=%s",
            type(exc).__name__,
            str(exc)[:200],
        )
        return False


def current_trace_id() -> str | None:
    """Return the active span's hex trace id (32 chars), or None.

    Safe to call from anywhere — returns None when OTel is not
    initialised or no span is currently active. Use to enrich log
    lines / error envelopes with a stable trace correlation id without
    importing OTel at every log site.
    """
    if not _INIT_OK:
        return None
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None:
            return None
        ctx = span.get_span_context()
        if not ctx or not ctx.is_valid:
            return None
        return format(ctx.trace_id, "032x")
    except Exception:  # noqa: BLE001 — observability never raises
        return None


def _reset_for_test() -> None:
    """Test-only helper to clear the init-once flag.

    Used by the unit tests in tests/test_otel_init.py to exercise both
    the no-endpoint short-circuit and the configured-endpoint happy
    path within the same process. Not part of the public surface.
    """
    global _INIT_ATTEMPTED, _INIT_OK
    _INIT_ATTEMPTED = False
    _INIT_OK = False


__all__ = [
    "current_trace_id",
    "init_otel",
    "instrument_fastapi",
]


# Re-export ``Any`` from typing to keep mypy --strict happy on the
# TYPE_CHECKING-only import above without forcing a runtime dep.
_ = Any  # noqa: F841
