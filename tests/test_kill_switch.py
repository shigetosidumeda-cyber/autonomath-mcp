"""Kill-switch + per-IP-endpoint cap + audit-log tests.

P0 abuse / DoS lever (audit a7388ccfd9ed7fb8c, 2026-04-25). Covers:

* ``KillSwitchMiddleware`` (``api/middleware/kill_switch.py``)
* ``PerIpEndpointLimitMiddleware`` (``api/middleware/per_ip_endpoint_limit.py``)
* ``GET /v1/admin/kill_switch_status`` (``api/admin.py``)
* ``audit_log`` row written on every kill-switch hit

The conftest disables ``RATE_LIMIT_BURST_DISABLED=1`` so the per-second
burst gate does not 429 our 31-request loop. We also clear the
per-IP-endpoint sliding window between tests so each test starts clean.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_kill_switch_and_buckets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sure no test leaks ``KILL_SWITCH_GLOBAL`` into another, and
    drop the per-IP-endpoint sliding window so every test starts fresh.
    """
    monkeypatch.delenv("KILL_SWITCH_GLOBAL", raising=False)
    monkeypatch.delenv("KILL_SWITCH_REASON", raising=False)
    from jpintel_mcp.api.middleware.kill_switch import _reset_kill_switch_state
    from jpintel_mcp.api.middleware.per_ip_endpoint_limit import (
        _reset_per_ip_endpoint_buckets,
    )

    _reset_kill_switch_state()
    _reset_per_ip_endpoint_buckets()
    yield
    _reset_kill_switch_state()
    _reset_per_ip_endpoint_buckets()


# ---------------------------------------------------------------------------
# Kill switch: off → normal traffic
# ---------------------------------------------------------------------------


def test_kill_switch_off_allows_normal_traffic(client: TestClient) -> None:
    """``KILL_SWITCH_GLOBAL`` unset → every endpoint behaves normally."""
    r_meta = client.get("/v1/meta")
    assert r_meta.status_code == 200, r_meta.text

    r_health = client.get("/healthz")
    assert r_health.status_code == 200, r_health.text


# ---------------------------------------------------------------------------
# Kill switch: on → 503 on traffic, allowlist still 200
# ---------------------------------------------------------------------------


def test_kill_switch_on_returns_503_envelope_on_search(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``KILL_SWITCH_GLOBAL=1`` → /v1/programs/search returns 503 with the
    canonical service_unavailable envelope.

    NB: monkeypatching has to happen on the SAME ``os.environ`` the
    middleware reads — the middleware reads on every request via
    ``os.environ.get`` so this just works.
    """
    monkeypatch.setenv("KILL_SWITCH_GLOBAL", "1")
    monkeypatch.setenv(
        "KILL_SWITCH_REASON", "test ddos from 1.2.3.4"
    )

    r = client.get("/v1/programs/search?q=test")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["error"]["code"] == "service_unavailable"
    # Per spec: details.retry_after = "see_status_page".
    assert body["error"]["details"]["retry_after"] == "see_status_page"
    # User-facing message points at the public status page. Both legacy
    # (autonomath.ai) and current (zeimu-kaikei.ai) brands accepted —
    # the brand was renamed during the v0.3.x rebrand and either is
    # acceptable until the legacy domain retires.
    msg = body["error"]["user_message"]
    assert "/status" in msg, msg
    assert ("autonomath.ai" in msg) or ("zeimu-kaikei.ai" in msg), msg


def test_kill_switch_on_healthz_still_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allowlisted paths (/healthz) keep responding 200 even when killed.

    Without this, Fly's liveness check would fail, the orchestrator would
    cycle the machine, and the secret toggle would lose its KILL_SWITCH_*
    env vars on the new boot — making the kill-switch un-recoverable.
    """
    monkeypatch.setenv("KILL_SWITCH_GLOBAL", "1")
    r = client.get("/healthz")
    assert r.status_code == 200, r.text


def test_kill_switch_on_readyz_still_responds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/readyz is allowlisted — the kill switch must NOT 503 it. The
    handler itself may legitimately return 503 ``{"status": "starting"}``
    when the lifespan hasn't flipped ``_ready=True`` yet (the TestClient
    triggers the lifespan lazily); what we care about is that the body
    is the readyz body, not the kill-switch envelope.
    """
    monkeypatch.setenv("KILL_SWITCH_GLOBAL", "1")
    r = client.get("/readyz")
    body = r.json()
    # If the kill switch had blocked us, body would be the canonical
    # ``{"error": {"code": "service_unavailable", ...}}`` envelope.
    assert "error" not in body, f"kill switch blocked readyz: {r.text}"
    assert "status" in body


def test_kill_switch_off_value_other_than_1_does_not_trigger(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The switch is strictly equality with the literal string ``"1"``.

    ``"true"`` / ``"yes"`` / ``"0"`` / empty must NOT flip it — operators
    have shipped envs to prod with truthy-string sloppiness in the past
    (memory: feedback_validate_before_apply).
    """
    for val in ["true", "0", "", "yes"]:
        monkeypatch.setenv("KILL_SWITCH_GLOBAL", val)
        r = client.get("/v1/meta")
        assert r.status_code == 200, f"value={val!r} unexpectedly killed"


# ---------------------------------------------------------------------------
# Kill switch: audit log written
# ---------------------------------------------------------------------------


def test_kill_switch_writes_audit_log_on_block(
    client: TestClient,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every blocked request appends one ``audit_log`` row with
    ``event_type='kill_switch_block'`` so post-incident triage can see
    which paths got hammered.
    """
    monkeypatch.setenv("KILL_SWITCH_GLOBAL", "1")
    monkeypatch.setenv("KILL_SWITCH_REASON", "audit-test")

    # Make sure we start clean for the audit_log assertion below.
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "DELETE FROM audit_log WHERE event_type = 'kill_switch_block'"
        )
        c.commit()
    except sqlite3.OperationalError:
        # Table may not exist on fresh DBs — schema added by migration
        # 058. The middleware swallows missing-table errors silently.
        c.close()
        pytest.skip("audit_log table not present in this test DB")
    c.close()

    r = client.get("/v1/programs/search?q=test")
    assert r.status_code == 503

    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT event_type, metadata FROM audit_log "
            "WHERE event_type = 'kill_switch_block' "
            "ORDER BY ts DESC LIMIT 5"
        ).fetchall()
    finally:
        c.close()
    assert len(rows) >= 1, "expected at least one kill_switch_block row"
    # metadata is a JSON blob carrying path / method / reason.
    import json as _json

    md = _json.loads(rows[0][1] or "{}")
    assert md.get("path") == "/v1/programs/search"
    assert md.get("method") == "GET"
    assert md.get("reason") == "audit-test"


# ---------------------------------------------------------------------------
# Per-IP-endpoint sliding-minute cap
# ---------------------------------------------------------------------------


def test_per_ip_endpoint_search_cap_31st_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """30 req/min cap on /v1/programs/search → the 31st within 60s is
    429 with bucket label ``per-ip:search_programs``.

    The conftest's ``RATE_LIMIT_BURST_DISABLED=1`` is left in place so
    the per-second burst gate doesn't 429 us first.
    """
    # Fire 30 — all should pass under the per-IP cap.
    for i in range(30):
        r = client.get("/v1/programs/search?q=test")
        assert r.status_code != 429, (
            f"hit per-ip 429 unexpectedly at request {i + 1}: {r.text}"
        )

    # 31st must be 429 from PerIpEndpointLimitMiddleware.
    r = client.get("/v1/programs/search?q=test")
    assert r.status_code == 429, r.text
    body = r.json()
    assert body["error"]["code"] == "rate_limited"
    assert body["error"]["bucket"].startswith("per-ip:")
    assert body["error"]["limit_per_minute"] == 30
    assert int(r.headers["Retry-After"]) >= 1


def test_per_ip_endpoint_cap_disabled_via_env(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``PER_IP_ENDPOINT_LIMIT_DISABLED=1`` short-circuits the middleware
    so 100 calls all pass. Used as an emergency disable lever.
    """
    monkeypatch.setenv("PER_IP_ENDPOINT_LIMIT_DISABLED", "1")
    for i in range(35):
        r = client.get("/v1/programs/search?q=test")
        assert r.status_code != 429, (
            f"hit 429 at {i + 1} despite disable flag"
        )


# ---------------------------------------------------------------------------
# Admin status endpoint
# ---------------------------------------------------------------------------


def test_admin_kill_switch_status_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``GET /v1/admin/kill_switch_status`` returns ``enabled=false`` when
    the switch is off. Requires ``X-API-Key=ADMIN_API_KEY``.
    """
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    # Force settings reload so the new ADMIN_API_KEY is picked up.
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")

    r = client.get(
        "/v1/admin/kill_switch_status",
        headers={"X-API-Key": "test-admin-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is False
    assert body["since_iso"] is None
    assert body["reason"] is None


def test_admin_kill_switch_status_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When ``KILL_SWITCH_GLOBAL=1`` the admin endpoint returns enabled
    with a ``since_iso`` timestamp and the configured reason.

    NB: /v1/admin/* is an allowlisted-shaped path? **No** — only the
    explicit set in ``_KILL_SWITCH_ALLOWLIST`` is allowlisted. So when
    the switch is ON, the admin endpoint itself would be 503'd by the
    middleware. To inspect status during an incident, the operator
    inspects the secret directly via ``flyctl secrets list`` or relies
    on the local copy of this runbook. This test verifies the helper
    returns sensible values WHEN we can reach it — so we exercise it
    via the helpers directly (call the function under test).
    """
    monkeypatch.setenv("KILL_SWITCH_GLOBAL", "1")
    monkeypatch.setenv("KILL_SWITCH_REASON", "incident-7")

    from jpintel_mcp.api.middleware.kill_switch import (
        _kill_switch_active,
        _kill_switch_reason,
        _kill_switch_since,
    )

    assert _kill_switch_active() is True
    assert _kill_switch_reason() == "incident-7"
    since = _kill_switch_since()
    assert isinstance(since, str)
    # ISO-8601 'Z' suffix.
    assert since.endswith("Z")


def test_admin_kill_switch_status_requires_admin_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an admin key configured, the endpoint is 503. With one
    configured but missing X-API-Key, 401.
    """
    from jpintel_mcp.config import settings

    # No admin key → 503.
    monkeypatch.setattr(settings, "admin_api_key", "")
    r = client.get("/v1/admin/kill_switch_status")
    assert r.status_code == 503, r.text

    # Configured admin key but missing header → 401.
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    r = client.get("/v1/admin/kill_switch_status")
    assert r.status_code == 401, r.text
