"""PERF-7 hot-path p95 regression gate.

Locks in the post-orjson p95 measurements documented in
``docs/_internal/api_perf_profile_2026_05_16.md`` with a 1.5-2x headroom
budget so a real regression trips the test but normal CI runner noise
does not.

Skipped on CI by default; opt in with::

    JPCITE_RUN_PERF_GATES=1 pytest tests/perf/test_api_p95_budget.py

The test deliberately uses the in-process :class:`fastapi.testclient.TestClient`
seeded by the project ``conftest.py`` fixtures so we only measure the
router + middleware + response-serialization paths — uvicorn / network /
TLS overhead is out of scope for the p95 budget.
"""

from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

# Budgets are sized ~1.5-2x above the post-PERF-7 measured p95. The formal
# agent-funnel hot-path budget is 200ms; these per-endpoint budgets sit
# well below that so we have deploy headroom.
P95_BUDGET_MS: dict[str, float] = {
    "/healthz": 50.0,
    "/v1/openapi.json": 80.0,
    "/v1/mcp-server.json": 120.0,
}

WARMUP_ITERATIONS = 10
MEASURE_ITERATIONS = 100


def _percentile(samples: list[float], pct: float) -> float:
    if not samples:
        return float("nan")
    s = sorted(samples)
    k = max(0, min(len(s) - 1, int(round(pct / 100.0 * (len(s) - 1)))))
    return s[k]


pytestmark = pytest.mark.skipif(
    os.environ.get("JPCITE_RUN_PERF_GATES") != "1",
    reason="perf gate disabled on CI by default; set JPCITE_RUN_PERF_GATES=1 to opt in",
)


@pytest.fixture()
def perf_client(monkeypatch: pytest.MonkeyPatch, jpintel_seeded_db: object) -> TestClient:
    """TestClient with the per-IP burst limiter disabled so the gate can
    drive 100+ sequential requests without 429-ing itself."""
    monkeypatch.setenv("RATE_LIMIT_BURST_DISABLED", "1")
    monkeypatch.setenv("ANON_RATE_LIMIT_PER_DAY", "1000000")
    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


@pytest.mark.parametrize("path", sorted(P95_BUDGET_MS))
def test_endpoint_p95_under_budget(perf_client: TestClient, path: str) -> None:
    """p95 latency under :data:`P95_BUDGET_MS` for each hot-path endpoint."""
    # warmup so JIT / import / DB-connection-pool warm-up doesn't poison
    # the measured window
    for _ in range(WARMUP_ITERATIONS):
        resp = perf_client.get(path)
        assert resp.status_code == 200, (
            f"warmup got {resp.status_code} from {path}: body[:200]={resp.text[:200]!r}"
        )

    samples_ms: list[float] = []
    for _ in range(MEASURE_ITERATIONS):
        t0 = time.perf_counter()
        resp = perf_client.get(path)
        samples_ms.append((time.perf_counter() - t0) * 1000.0)
        assert resp.status_code == 200, f"perf-iteration got {resp.status_code} from {path}"

    p95 = _percentile(samples_ms, 95)
    budget = P95_BUDGET_MS[path]
    assert p95 <= budget, (
        f"p95 regression on {path}: measured {p95:.2f}ms, budget {budget:.2f}ms "
        f"(p50={_percentile(samples_ms, 50):.2f}ms, "
        f"p99={_percentile(samples_ms, 99):.2f}ms, max={max(samples_ms):.2f}ms)"
    )
