#!/usr/bin/env python3
"""Lightweight daily performance smoke for public API endpoints.

Default mode runs against the local FastAPI app via TestClient, so it has no
network dependency. Set BASE_URL or pass --base-url to probe a deployed target.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


@dataclass(frozen=True)
class Endpoint:
    name: str
    path: str
    params: dict[str, str] | None = None


@dataclass(frozen=True)
class EndpointResult:
    name: str
    path: str
    samples: int
    ok: int
    status_codes: dict[int, int]
    p50_ms: float
    p95_ms: float
    max_ms: float
    threshold_ms: float
    passed: bool


class SyncClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...


DEFAULT_ENDPOINTS: tuple[Endpoint, ...] = (
    Endpoint("healthz", "/healthz"),
    Endpoint("programs_search", "/v1/programs/search", {"q": "補助金", "limit": "1"}),
    Endpoint("meta", "/v1/meta"),
)


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil((pct / 100.0) * len(ordered)) - 1)
    return ordered[min(index, len(ordered) - 1)]


def _request_once(client: SyncClient, endpoint: Endpoint, timeout_s: float) -> tuple[int, float]:
    start = time.perf_counter_ns()
    response = client.get(endpoint.path, params=endpoint.params, timeout=timeout_s)
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    return int(response.status_code), elapsed_ms


def measure_endpoint(
    client: SyncClient,
    endpoint: Endpoint,
    *,
    samples: int,
    warmups: int,
    timeout_s: float,
    threshold_ms: float,
) -> EndpointResult:
    for _ in range(warmups):
        _request_once(client, endpoint, timeout_s)

    timings: list[float] = []
    status_codes: dict[int, int] = {}
    ok = 0
    for _ in range(samples):
        status_code, elapsed_ms = _request_once(client, endpoint, timeout_s)
        timings.append(elapsed_ms)
        status_codes[status_code] = status_codes.get(status_code, 0) + 1
        if 200 <= status_code < 400:
            ok += 1

    p95_ms = percentile(timings, 95)
    passed = ok == samples and p95_ms <= threshold_ms
    return EndpointResult(
        name=endpoint.name,
        path=endpoint.path,
        samples=samples,
        ok=ok,
        status_codes=dict(sorted(status_codes.items())),
        p50_ms=percentile(timings, 50),
        p95_ms=p95_ms,
        max_ms=max(timings, default=0.0),
        threshold_ms=threshold_ms,
        passed=passed,
    )


def run_smoke(
    client: SyncClient,
    *,
    endpoints: Iterable[Endpoint] = DEFAULT_ENDPOINTS,
    samples: int = 5,
    warmups: int = 1,
    timeout_s: float = 5.0,
    threshold_ms: float = 1000.0,
) -> list[EndpointResult]:
    if samples < 1:
        raise ValueError("samples must be >= 1")
    if warmups < 0:
        raise ValueError("warmups must be >= 0")
    return [
        measure_endpoint(
            client,
            endpoint,
            samples=samples,
            warmups=warmups,
            timeout_s=timeout_s,
            threshold_ms=threshold_ms,
        )
        for endpoint in endpoints
    ]


def has_failure(results: Sequence[EndpointResult]) -> bool:
    return any(not result.passed for result in results)


def render_table(results: Sequence[EndpointResult], *, warn_only: bool) -> str:
    lines = [
        "jpcite performance smoke",
        f"mode={'warn-only' if warn_only else 'ci-fail'}",
        "",
        f"{'endpoint':<18} {'ok':>7} {'p50':>9} {'p95':>9} {'max':>9} {'status':>14} result",
    ]
    for result in results:
        statuses = ",".join(f"{code}:{count}" for code, count in result.status_codes.items())
        verdict = "ok" if result.passed else "WARN" if warn_only else "FAIL"
        lines.append(
            f"{result.name:<18} "
            f"{result.ok:>3}/{result.samples:<3} "
            f"{result.p50_ms:>8.1f}ms "
            f"{result.p95_ms:>8.1f}ms "
            f"{result.max_ms:>8.1f}ms "
            f"{statuses:>14} {verdict}"
        )
    return "\n".join(lines)


def _local_client() -> Any:
    from fastapi.testclient import TestClient

    from jpintel_mcp.api.main import create_app

    marker = time.time_ns()
    smoke_ip = f"198.18.{(marker >> 8) % 256}.{((marker >> 16) % 254) + 1}"
    return TestClient(
        create_app(),
        raise_server_exceptions=False,
        headers={"X-Forwarded-For": smoke_ip},
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL"),
        help="Probe this base URL instead of the local TestClient app. Defaults to BASE_URL.",
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout seconds.")
    parser.add_argument(
        "--threshold-ms",
        type=float,
        default=1000.0,
        help="Per-endpoint p95 threshold. Defaults to conservative 1000ms.",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Exit non-zero on non-2xx/3xx responses or p95 threshold breaches.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a text table.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    with contextlib.redirect_stdout(sys.stderr) if args.json else contextlib.nullcontext():
        if args.base_url:
            with httpx.Client(
                base_url=args.base_url,
                timeout=args.timeout,
                follow_redirects=True,
            ) as client:
                results = run_smoke(
                    client,
                    samples=args.samples,
                    warmups=args.warmups,
                    timeout_s=args.timeout,
                    threshold_ms=args.threshold_ms,
                )
        else:
            with _local_client() as client:
                results = run_smoke(
                    client,
                    samples=args.samples,
                    warmups=args.warmups,
                    timeout_s=args.timeout,
                    threshold_ms=args.threshold_ms,
                )

    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
    else:
        print(render_table(results, warn_only=not args.ci))

    return 1 if args.ci and has_failure(results) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
