"""Connection-drop / TCP-reset chaos tests (Wave 18 E3).

Validates that the jpcite API client surface degrades gracefully when
the upstream TCP socket is severed mid-flight.  Scenarios:

  1. ``reset_peer``  — Toxiproxy sends a TCP RST after N ms; the client
     must raise a recognizable httpx connection error, not a hang.
  2. ``timeout``     — Toxiproxy holds the connection open for N ms then
     closes it; the client must respect its own timeout configuration.
  3. ``limit_data``  — Toxiproxy closes after N bytes have flowed; the
     client must see a short read / EOF surface.

These scenarios contribute to the resilience score reported by
``chaos-weekly.yml``.  Target: 5/5 connection scenarios green.

Skipped automatically when Toxiproxy is not running — see conftest.py.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")


def test_reset_peer_raises_connection_error(api_proxy: Any, proxy_base_url: str) -> None:
    """A TCP RST 100 ms in must surface as a connection error, not a hang.

    The ``reset_peer`` toxic with ``timeout=100`` injects a RST after
    100 ms of stream activity.  The httpx client should raise
    ``httpx.RemoteProtocolError`` / ``httpx.ConnectError`` /
    ``httpx.ReadError`` — any of these is acceptable, what matters is
    that we surface the failure quickly (under 5 s) rather than hanging.
    """
    api_proxy.add_toxic(
        type="reset_peer",
        attributes={"timeout": 100},
    )
    started = time.monotonic()
    with pytest.raises(httpx.HTTPError), httpx.Client(timeout=5.0) as client:
        client.get(f"{proxy_base_url}/healthz")
    elapsed = time.monotonic() - started
    # Must surface within 5 s — we are checking that the failure is
    # *fast*, not that it eventually happens.
    assert elapsed < 5.0, f"connection reset did not surface quickly: elapsed={elapsed:.3f}s"


def test_timeout_toxic_respects_client_budget(api_proxy: Any, proxy_base_url: str) -> None:
    """``timeout`` toxic must trip the client's own read-timeout.

    The toxic holds the connection open for 5000 ms before closing.
    With a 1 s client read-timeout, httpx must raise inside ~1-2 s.
    """
    api_proxy.add_toxic(
        type="timeout",
        attributes={"timeout": 5000},
    )
    started = time.monotonic()
    with (
        pytest.raises(httpx.HTTPError),
        httpx.Client(timeout=httpx.Timeout(connect=1.0, read=1.0, write=1.0, pool=1.0)) as client,
    ):
        client.get(f"{proxy_base_url}/healthz")
    elapsed = time.monotonic() - started
    assert elapsed < 4.0, f"client timeout did not fire in time: elapsed={elapsed:.3f}s"


def test_limit_data_truncates_response(api_proxy: Any, proxy_base_url: str) -> None:
    """``limit_data`` closing after 32 bytes must produce a recognizable error.

    The toxic disconnects after 32 bytes of upstream→downstream flow,
    which is well short of a full HTTP response.  The client must
    either raise an HTTP-shape error or get a clearly-incomplete body
    — we accept both because httpx behavior varies by response phase
    (headers vs body cutoff).
    """
    api_proxy.add_toxic(
        type="limit_data",
        attributes={"bytes": 32},
    )
    raised = False
    body_ok = False
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{proxy_base_url}/healthz")
        # If we got a response at all, it must NOT be a valid full
        # JSON body — the 32-byte cap is far below /healthz size.
        try:
            resp.json()
            body_ok = True
        except Exception:  # noqa: BLE001 — truncated payload is the success case
            pass
    except httpx.HTTPError:
        raised = True
    assert raised or not body_ok, (
        "limit_data=32 unexpectedly produced a complete valid response — "
        "toxic not active or upstream payload too small"
    )


def test_recovery_after_toxic_clear(api_proxy: Any, proxy_base_url: str) -> None:
    """After removing the toxic, the proxy must serve normal traffic again.

    Regression guard for the runbook step "clear all toxics, verify
    baseline".  Adds + removes a toxic and confirms that a subsequent
    request succeeds in <2 s.
    """
    toxic = api_proxy.add_toxic(
        type="latency",
        attributes={"latency": 2000, "jitter": 0},
    )
    # Confirm toxic is active by observing the slow path …
    with httpx.Client(timeout=10.0) as client:
        slow = client.get(f"{proxy_base_url}/healthz")
    assert slow.status_code == 200

    # … then clear it and confirm fast path returns.
    try:
        toxic.destroy()
    except Exception:  # noqa: BLE001 — best effort, proxy.destroy in teardown anyway
        # toxiproxy-python uses different APIs across versions; fall
        # back to clearing all toxics via the proxy itself.
        try:
            for t in api_proxy.toxics():
                t.destroy()
        except Exception:  # noqa: BLE001
            pass

    started = time.monotonic()
    with httpx.Client(timeout=5.0) as client:
        fast = client.get(f"{proxy_base_url}/healthz")
    elapsed = time.monotonic() - started
    assert fast.status_code == 200
    assert elapsed < 2.0, f"baseline did not return after toxic removal: elapsed={elapsed:.3f}s"
