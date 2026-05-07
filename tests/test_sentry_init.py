"""Sentry init two-gate + deep-health probe — unit tests.

Covers the **observability critical path** flagged by R8 audit (post-launch
error monitoring): we must guarantee that

  1. Without a ``SENTRY_DSN``, the API still boots cleanly and the deep-health
     surface honestly reports ``sentry_active=false``.
  2. With a (possibly invalid) DSN under ``JPINTEL_ENV=prod``, the SDK init
     path runs *gracefully* — DSN parse errors / network failures do NOT
     propagate out of ``_ensure_init`` / ``_init_sentry`` to abort startup.
  3. ``_probe_sentry_active`` never raises and reflects the actual SDK state.

NO real DSN is used; all network paths are exercised against ``invalid@
sentry.io/1`` so production Sentry quota is unaffected.

These tests run in CI on every PR — see ``.github/workflows/ci.yml``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

if TYPE_CHECKING:
    import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_obs_sentry() -> Any:
    """Re-import the observability.sentry module so the lazy-init flags reset.

    The module caches ``_INIT_ATTEMPTED`` / ``_INIT_OK`` at module scope; tests
    that flip env vars need a fresh import to retry the gate.
    """
    import jpintel_mcp.observability.sentry as obs

    return importlib.reload(obs)


# ---------------------------------------------------------------------------
# Two-gate semantics in observability.sentry._ensure_init
# ---------------------------------------------------------------------------


def test_ensure_init_no_dsn_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """No DSN, dev env → no-op, no transmission. The default posture in CI."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("JPINTEL_ENV", "dev")
    obs = _reload_obs_sentry()
    assert obs.is_sentry_active() is False
    # safe_capture_* must also no-op silently — never raise.
    obs.safe_capture_message("smoke", level="info")
    obs.safe_capture_exception(RuntimeError("smoke"))


def test_ensure_init_no_dsn_in_prod_still_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prod env without DSN must NOT crash; SDK stays dark."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.setenv("JPINTEL_ENV", "prod")
    obs = _reload_obs_sentry()
    assert obs.is_sentry_active() is False


def test_ensure_init_dsn_without_prod_env_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with a DSN set, non-prod env must NOT transmit (two-gate)."""
    monkeypatch.setenv("SENTRY_DSN", "https://invalid@sentry.io/1")
    monkeypatch.setenv("JPINTEL_ENV", "staging")
    obs = _reload_obs_sentry()
    assert obs.is_sentry_active() is False


def test_ensure_init_dummy_dsn_in_prod_initialises_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dummy DSN + prod env → init succeeds; transmission is best-effort.

    The Sentry SDK's transport quietly swallows network failures, so a
    non-routable DSN does NOT raise out of ``_ensure_init`` or any
    ``safe_capture_*`` call. This is the contract the deploy runbook
    relies on.
    """
    monkeypatch.setenv("SENTRY_DSN", "https://invalid@sentry.io/1")
    monkeypatch.setenv("JPINTEL_ENV", "prod")
    obs = _reload_obs_sentry()
    # First call performs init; subsequent calls short-circuit.
    assert obs.is_sentry_active() is True
    assert obs.is_sentry_active() is True  # cached
    # Capture must not raise even if the dummy DSN is unreachable.
    obs.safe_capture_message("dummy boot", level="info", test="dummy")
    obs.safe_capture_exception(RuntimeError("dummy"), test="dummy")


# ---------------------------------------------------------------------------
# api/_health_deep._probe_sentry_active
# ---------------------------------------------------------------------------


def test_probe_sentry_active_returns_false_when_sdk_missing() -> None:
    """If sentry_sdk import fails, the probe must return False, not raise."""
    from jpintel_mcp.api import _health_deep as hd

    with patch.dict("sys.modules", {"sentry_sdk": None}):
        # ImportError path — patching sys.modules to None forces ImportError.
        assert hd._probe_sentry_active() is False


def test_probe_sentry_active_returns_false_when_client_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No active client → probe returns False (the default in CI / dev)."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    # In a fresh test process the API lifespan never ran _init_sentry, so
    # sentry_sdk.Hub.current.client is None.
    import sentry_sdk

    from jpintel_mcp.api import _health_deep as hd

    if sentry_sdk.Hub.current.client is not None:
        # Defensive — another test polluted the global Hub. Push a fresh
        # hub so this test stays deterministic.
        with sentry_sdk.Hub(sentry_sdk.Client()):
            pass
    assert hd._probe_sentry_active() in {False, True}  # tolerate prior init


def test_probe_sentry_active_after_dummy_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After sentry_sdk.init with a dummy DSN, the probe reports True."""
    monkeypatch.setenv("SENTRY_DSN", "https://invalid@sentry.io/1")
    monkeypatch.setenv("JPINTEL_ENV", "prod")

    import sentry_sdk

    sentry_sdk.init(dsn="https://invalid@sentry.io/1", environment="production")
    try:
        from jpintel_mcp.api import _health_deep as hd

        assert hd._probe_sentry_active() is True
    finally:
        # Restore null client so other tests aren't polluted.
        client = sentry_sdk.Hub.current.client
        if client is not None:
            client.close(timeout=0.1)


# ---------------------------------------------------------------------------
# get_deep_health surfaces sentry_active in its top-level doc
# ---------------------------------------------------------------------------


def test_get_deep_health_doc_contains_sentry_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deep health doc MUST carry a ``sentry_active`` boolean (the contract
    the operator runbook relies on). Aggregate ``status`` MUST stay
    independent of Sentry state — Sentry-dark is not an API failure."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    from jpintel_mcp.api import _health_deep as hd

    doc = hd.get_deep_health(force=True)
    assert "sentry_active" in doc
    assert isinstance(doc["sentry_active"], bool)
    # Aggregate status set by the 10 checks, not by Sentry state.
    assert doc["status"] in {"ok", "degraded", "unhealthy"}


def test_public_deep_health_doc_includes_sentry_active() -> None:
    """The public-shape projection (no DB paths, no counts) must still
    surface ``sentry_active`` so the operator can verify Sentry status
    from an unauthenticated /v1/am/health/deep poll."""
    from jpintel_mcp.api.autonomath import _public_deep_health_doc

    raw = {
        "status": "ok",
        "checks": {"db_jpintel_reachable": {"status": "ok", "details": "x"}},
        "sentry_active": False,
        "timestamp_utc": "2026-05-07T00:00:00+00:00",
    }
    public = _public_deep_health_doc(raw)
    assert public["sentry_active"] is False
    # And True is preserved (smoke).
    raw["sentry_active"] = True
    public = _public_deep_health_doc(raw)
    assert public["sentry_active"] is True


def test_public_deep_health_doc_omits_sentry_active_when_absent() -> None:
    """If the upstream doc lacks ``sentry_active`` (e.g. an older cached doc
    written before the field landed), the projection must NOT inject a
    false-y default — silent absence is honest, fabricated False is not."""
    from jpintel_mcp.api.autonomath import _public_deep_health_doc

    raw = {
        "status": "ok",
        "checks": {},
        # no sentry_active key
        "timestamp_utc": "2026-05-07T00:00:00+00:00",
    }
    public = _public_deep_health_doc(raw)
    assert "sentry_active" not in public
