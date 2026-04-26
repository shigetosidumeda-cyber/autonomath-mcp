"""Sentry helper — safe capture from background scripts (cron, sweepers).

The FastAPI lifespan calls `sentry_sdk.init(...)` directly in
`jpintel_mcp.api.main._init_sentry`. This module is for the *other*
entry points: cron scripts under `scripts/cron/*` that need to flag
operator-actionable failures (cost overrun, source-URL rot, Stripe
dispute spike) without re-implementing the init / scrubber pipeline.

Design constraints:
  * Never raise. A monitoring helper that itself raises is worse than no
    monitoring — the caller's primary work (cost calc, ingest) must run
    to completion regardless of Sentry health.
  * Never call Anthropic / OpenAI / claude SDK. Per memory
    `feedback_autonomath_no_api_use` we are forbidden from spending
    customer LLM tokens on infra. Sentry HTTP is fine; LLM HTTP is not.
  * Two-gate activation: SENTRY_DSN present AND JPINTEL_ENV=prod. The
    cron host can read both env vars from the same Fly secrets file as
    the API; init is a no-op everywhere else.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("autonomath.observability.sentry")

_INIT_ATTEMPTED = False
_INIT_OK = False


def _ensure_init() -> bool:
    """Lazily initialise Sentry for non-API entry points (cron scripts).

    Idempotent: only the first call performs init; subsequent calls
    short-circuit on the cached `_INIT_OK` flag. Returns True iff Sentry
    is active and `capture_*` calls will actually transmit.
    """
    global _INIT_ATTEMPTED, _INIT_OK

    if _INIT_ATTEMPTED:
        return _INIT_OK
    _INIT_ATTEMPTED = True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    env = os.getenv("JPINTEL_ENV", "dev").strip()

    # Two-gate: prod-only AND DSN present. dev/test never transmit even
    # if a DSN leaks into the env.
    if not dsn or env != "prod":
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry_sdk not installed; capture calls will no-op")
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT", env),
            release=os.getenv("SENTRY_RELEASE") or None,
            # Cron entry points: lower sample rate than the API path
            # (these scripts run daily, not per-request, so volume is tiny
            # and we mainly want errors not traces).
            traces_sample_rate=float(
                os.getenv("SENTRY_CRON_TRACES_SAMPLE_RATE", "0.0")
            ),
            send_default_pii=False,
            include_local_variables=False,
            max_breadcrumbs=20,
        )
    except Exception as exc:  # noqa: BLE001 — observability cannot raise
        logger.warning("sentry init failed (non-fatal): %s", exc)
        return False

    _INIT_OK = True
    return True


def is_sentry_active() -> bool:
    """Return True iff capture_* calls would transmit to Sentry."""
    return _ensure_init()


def safe_capture_exception(exc: BaseException, **scope: Any) -> None:
    """Forward `exc` to Sentry with optional scope tags. Never raises.

    `scope` keys become Sentry tags (string-coerced). Use sparingly —
    high-cardinality tags (per-user, per-key) explode quota.
    """
    if not _ensure_init():
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as s:  # type: ignore[attr-defined]
            for k, v in scope.items():
                s.set_tag(k, str(v))
            sentry_sdk.capture_exception(exc)
    except Exception as nested:  # noqa: BLE001
        logger.warning("sentry capture_exception failed: %s", nested)


def safe_capture_message(
    message: str,
    *,
    level: str = "warning",
    **scope: Any,
) -> None:
    """Send a message-level alert to Sentry. Never raises.

    Use for non-exception conditions: budget threshold crossed, dispute
    rate spike, freshness SLA breach. `level` follows Sentry semantics
    (info / warning / error / fatal).
    """
    if not _ensure_init():
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as s:  # type: ignore[attr-defined]
            for k, v in scope.items():
                s.set_tag(k, str(v))
            sentry_sdk.capture_message(message, level=level)  # type: ignore[arg-type]
    except Exception as nested:  # noqa: BLE001
        logger.warning("sentry capture_message failed: %s", nested)
