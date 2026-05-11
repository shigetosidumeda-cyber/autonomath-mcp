"""Latency-injection chaos tests (Wave 18 E3).

Injects 500 ms / 1 s / 3 s of additional latency in front of the local
jpcite API and asserts that:

  1. ``/healthz`` still returns 200 within a generous timeout (the probe
     must not collapse the moment upstream slows down).
  2. The HTTP client observes the injected latency (sanity check — if
     the toxic is not actually wired, the test fails loudly).
  3. The Sentry breadcrumb / OTel span ID is still emitted (correlation
     IDs must survive a slow upstream — verified via ``x-request-id``
     header round-trip).

These scenarios contribute to the resilience score reported by
``chaos-weekly.yml``. Target: 5/5 latency scenarios green.

Skipped automatically when Toxiproxy is not running — see conftest.py.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

# httpx is already a runtime dep (pyproject.toml dependencies).
httpx = pytest.importorskip("httpx")


# (toxic latency in ms, max allowed response time in s).  The upper bound
# is generous because the proxied API also has to do real work + DB I/O;
# we just need to detect that the toxic is actively delaying responses.
_LATENCY_SCENARIOS = [
    pytest.param(500, 8.0, id="latency-500ms"),
    pytest.param(1000, 12.0, id="latency-1s"),
    pytest.param(3000, 30.0, id="latency-3s"),
]


@pytest.mark.parametrize(("toxic_latency_ms", "max_response_s"), _LATENCY_SCENARIOS)
def test_healthz_under_latency_injection(
    api_proxy: Any,
    proxy_base_url: str,
    toxic_latency_ms: int,
    max_response_s: float,
) -> None:
    """``/healthz`` must succeed even when upstream gains N ms of latency.

    The toxic ``latency`` adds a fixed delay to *every* TCP byte both
    directions — a 1 s setting easily blows up to 2 s end-to-end.  We
    check (a) status 200, (b) wall-clock cost is at least the toxic
    delay (otherwise the toxic is broken / mis-wired), and (c) total
    cost stays under the budget.
    """
    api_proxy.add_toxic(
        type="latency",
        attributes={"latency": toxic_latency_ms, "jitter": 0},
    )

    started = time.monotonic()
    with httpx.Client(timeout=max_response_s + 5.0) as client:
        resp = client.get(f"{proxy_base_url}/healthz")
    elapsed = time.monotonic() - started

    assert resp.status_code == 200, (
        f"/healthz unexpected status {resp.status_code} under "
        f"{toxic_latency_ms}ms latency injection"
    )
    # Toxic actually delayed the response — converts to seconds and
    # subtracts a small skew for the proxy's own overhead.
    min_expected = (toxic_latency_ms / 1000.0) * 0.5
    assert elapsed >= min_expected, (
        f"toxic not active: elapsed={elapsed:.3f}s "
        f"< min_expected={min_expected:.3f}s"
    )
    assert elapsed <= max_response_s, (
        f"response exceeded budget: elapsed={elapsed:.3f}s "
        f"> max={max_response_s:.3f}s"
    )


def test_request_id_propagation_under_latency(
    api_proxy: Any, proxy_base_url: str
) -> None:
    """Correlation IDs must survive a slow upstream.

    The client supplies ``x-request-id``; the API echoes it back via
    ``_RequestContextMiddleware``.  Under 1 s latency injection the
    header must round-trip unchanged so OTel + Sentry breadcrumb
    correlation continues to work for slow-path debugging.
    """
    api_proxy.add_toxic(
        type="latency",
        attributes={"latency": 1000, "jitter": 0},
    )
    rid = "01CHAOS00000000000000LATENCY01"
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(
            f"{proxy_base_url}/healthz",
            headers={"x-request-id": rid},
        )
    assert resp.status_code == 200
    echoed = resp.headers.get("x-request-id", "")
    assert echoed == rid, (
        f"request-id round-trip broken under latency injection: "
        f"sent={rid!r} got={echoed!r}"
    )


def test_bandwidth_cap(api_proxy: Any, proxy_base_url: str) -> None:
    """A 1 KB/s upstream cap must not crash a small JSON response.

    The ``bandwidth`` toxic limits throughput to the given KB/s.  This
    verifies the API client / server stack tolerates slow pipes without
    hanging or returning truncated JSON.
    """
    api_proxy.add_toxic(
        type="bandwidth",
        attributes={"rate": 1},  # 1 KB/s, both directions
    )
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{proxy_base_url}/healthz")
    assert resp.status_code == 200
    body = resp.json()
    # /healthz always emits at least a `status` field; assert structure.
    assert isinstance(body, dict)
    assert "status" in body or "ok" in body or "ready" in body
