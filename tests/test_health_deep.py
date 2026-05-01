"""Happy-path tests for `api/_health_deep.py`.

Exercises the `get_deep_health()` pure-function path AND the live
`GET /v1/am/health/deep` route. The route is mounted on `health_router`
without AnonIpLimitDep — uptime monitors must poll without burning the
3/day anon quota.

In the test environment autonomath.db / static bundle paths likely don't
exist, so individual checks return `fail`. The aggregate status will be
`unhealthy` in that case, but the HTTP response itself remains 200 — the
contract is "always 200 + status field"; failure is signaled in the body.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def test_get_deep_health_returns_aggregate_doc():
    """Direct function call returns the documented schema shape."""
    from jpintel_mcp.api._health_deep import CHECKS, get_deep_health

    doc = get_deep_health(force=True)
    assert isinstance(doc, dict)
    assert "status" in doc
    assert doc["status"] in {"ok", "degraded", "unhealthy"}
    assert "version" in doc
    assert "checks" in doc
    assert "timestamp_utc" in doc
    assert "evaluated_at_jst" in doc

    # Every registered check appears in the result with status / details / value.
    expected_names = {name for name, _ in CHECKS}
    assert set(doc["checks"].keys()) == expected_names
    for _, check_result in doc["checks"].items():
        assert isinstance(check_result, dict)
        assert "status" in check_result
        assert "details" in check_result


def test_health_deep_route_returns_200(client: TestClient):
    """`GET /v1/am/health/deep` always returns 200 + valid status enum."""
    resp = client.get("/v1/am/health/deep?force=true")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert body["status"] in {"ok", "degraded", "unhealthy"}
    assert "checks" in body
    assert isinstance(body["checks"], dict)


def test_health_deep_can_fail_http_for_unhealthy_monitor(
    client: TestClient, monkeypatch
):
    """Fly can opt into HTTP 503 when the aggregate is unhealthy."""
    from jpintel_mcp.api import autonomath as autonomath_mod

    monkeypatch.setattr(
        autonomath_mod,
        "get_deep_health",
        lambda force=False: {
            "status": "unhealthy",
            "version": "test",
            "checks": {},
            "timestamp_utc": "2026-05-01T00:00:00Z",
            "evaluated_at_jst": "2026-05-01T09:00:00+09:00",
        },
    )

    resp = client.get("/v1/am/health/deep?force=true&fail_on_unhealthy=true")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unhealthy"
