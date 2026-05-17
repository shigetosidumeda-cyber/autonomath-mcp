#!/usr/bin/env python3
"""Lane G mass-invocation driver — Lambda async invoker at ~11K req/sec.

Drives ``jpcite-credit-canary-attestation-lite`` at sustained ~11K req/sec
to meet the Lane G $300/day Lambda spend target (revised down to ~1B
invocations/day = ~$410/day for 128MB / 100ms unit).

Design
======
- Uses **async invocation** (``InvocationType=Event``) so the driver does
  not wait for the Lambda response — this is what allows a single host
  to push >10K req/sec to Lambda's frontend.
- Bounded multi-threaded ``boto3.client('lambda').invoke()`` (not
  aioboto3 — boto3's botocore HTTP layer is fully thread-safe and stdlib
  ThreadPoolExecutor scales cleanly to 256+ workers when each call is
  network-bound and < 50ms).
- **DRY_RUN by default.** ``--commit`` is required to actually issue
  invocations. Live mode further requires ``--unlock-live-aws-commands``
  (mirrors the Stream W operator-token concern-separation pattern).
- **Budget cap.** ``--budget-usd`` (default 500) gates the projected
  spend. The driver declines to run when projected cost > budget.
- Idempotent run_id sequencing — each invocation carries a unique
  ``invocation_id`` (uuid4 hex) and an incrementing ``batch_index`` so
  the CloudWatch Logs audit moat can reconstruct per-batch ordering.

Cost model (Lambda Tokyo, 2026-05)
==================================
    request_usd_per_1M = 0.20
    compute_usd_per_gb_sec = 0.0000166667
    unit: 128 MB × 100 ms = 0.0125 GB-sec
    per-invoke cost = 0.20/1e6 + 0.0125 * 0.0000166667
                    = 2.00e-7 + 2.083e-7 = 4.08e-7 USD/invoke
    1B invocations  = ~$408 (within $300-$500 band).

CLI usage
=========
Dry-run projection only::

    $ ./scripts/aws_credit_ops/lambda_burn_driver_2026_05_17.py \\
        --requests 1000000 --concurrency 256

Live invocation (operator-only)::

    $ ./scripts/aws_credit_ops/lambda_burn_driver_2026_05_17.py \\
        --requests 1000000 --concurrency 256 \\
        --commit --unlock-live-aws-commands

Long-running burn (1B over 24h)::

    $ ./scripts/aws_credit_ops/lambda_burn_driver_2026_05_17.py \\
        --requests 1000000000 --concurrency 512 \\
        --rps-cap 12000 --commit --unlock-live-aws-commands

The driver uses a leaky-bucket rate limiter (``--rps-cap``) to keep the
sustained TPS predictable so the Lambda concurrency / reserved-concurrency
provisioning matches the actual demand.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Final

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SCHEMA_VERSION: Final[str] = "jpcite.lambda_burn_driver.v1"

# Pricing constants (Lambda Tokyo, 2026-05).
REQUEST_USD_PER_1M: Final[float] = 0.20
COMPUTE_USD_PER_GB_SEC: Final[float] = 0.0000166667
DEFAULT_MEMORY_MB: Final[int] = 128
DEFAULT_DURATION_MS: Final[int] = 100


def project_cost(
    requests: int,
    *,
    memory_mb: int = DEFAULT_MEMORY_MB,
    duration_ms: int = DEFAULT_DURATION_MS,
) -> dict[str, float]:
    """Project Lambda spend for a planned invocation count.

    All inputs are deterministic — call this from dry-run to print the
    expected envelope before issuing any side effect.
    """

    gb_sec_per_invoke = (memory_mb / 1024.0) * (duration_ms / 1000.0)
    request_usd = (requests / 1_000_000.0) * REQUEST_USD_PER_1M
    compute_usd = requests * gb_sec_per_invoke * COMPUTE_USD_PER_GB_SEC
    return {
        "requests": float(requests),
        "memory_mb": float(memory_mb),
        "duration_ms": float(duration_ms),
        "gb_sec_per_invoke": round(gb_sec_per_invoke, 9),
        "request_usd": round(request_usd, 4),
        "compute_usd": round(compute_usd, 4),
        "total_usd": round(request_usd + compute_usd, 4),
    }


@dataclass(frozen=True)
class BurnPlan:
    function_name: str
    requests: int
    concurrency: int
    rps_cap: float
    region: str
    run_id: str
    lane: str
    memory_mb: int
    duration_ms: int
    budget_usd: float
    commit: bool
    unlock_live: bool

    def asdict(self) -> dict[str, object]:
        return asdict(self)


def classify(plan: BurnPlan, projection: dict[str, float]) -> str:
    if not plan.commit:
        return "DRY_RUN"
    if not plan.unlock_live:
        return "BLOCKED_FLAG"
    if projection["total_usd"] > plan.budget_usd:
        return "BLOCKED_BUDGET"
    return "LIVE"


def build_envelope(
    plan: BurnPlan,
    projection: dict[str, float],
    *,
    timestamp: dt.datetime | None = None,
    result: dict[str, object] | None = None,
) -> dict[str, object]:
    ts = timestamp or dt.datetime.now(dt.UTC)
    classification = classify(plan, projection)
    env: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": ts.isoformat(),
        "plan": plan.asdict(),
        "projection": projection,
        "classification": classification,
        "budget_usd": plan.budget_usd,
    }
    if result is not None:
        env["result"] = result
    return env


# ----------------------------------------------------------------------------
# Live executor.
# ----------------------------------------------------------------------------


class _RateLimiter:
    """Simple token-bucket leaky-bucket limiter, thread-safe."""

    def __init__(self, rps_cap: float) -> None:
        self._lock = threading.Lock()
        self._rps_cap = max(rps_cap, 1.0)
        self._tokens = 0.0
        self._last = time.monotonic()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self._rps_cap, self._tokens + elapsed * self._rps_cap)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                deficit = 1.0 - self._tokens
                sleep_s = deficit / self._rps_cap
            time.sleep(max(sleep_s, 0.0005))


def _build_lambda_client(region: str, profile: str | None = None) -> object:
    cfg = Config(
        region_name=region,
        retries={"max_attempts": 2, "mode": "standard"},
        max_pool_connections=512,
        connect_timeout=5,
        read_timeout=15,
    )
    if profile:
        session = boto3.Session(profile_name=profile)
        return session.client("lambda", config=cfg)
    return boto3.client("lambda", config=cfg)


def _run_live(
    plan: BurnPlan,
    *,
    progress_every: int = 50_000,
    profile: str | None = None,
) -> dict[str, object]:
    client = _build_lambda_client(plan.region, profile=profile)
    limiter = _RateLimiter(plan.rps_cap)

    counters = {"ok": 0, "fail": 0}
    counter_lock = threading.Lock()
    started = time.time()

    def _invoke_one(idx: int) -> tuple[bool, int]:
        limiter.acquire()
        payload = {
            "run_id": plan.run_id,
            "lane": plan.lane,
            "batch_index": idx,
            "invocation_id": uuid.uuid4().hex,
            "client_tag": "lambda-burn-driver",
        }
        try:
            client.invoke(  # type: ignore[attr-defined]
                FunctionName=plan.function_name,
                InvocationType="Event",  # async
                Payload=json.dumps(payload).encode("utf-8"),
            )
            return True, idx
        except Exception as exc:  # noqa: BLE001
            if idx < 5:  # log a few sample failures for diagnostics
                logger.warning("invoke fail idx=%d err=%s", idx, exc)
            return False, idx

    with cf.ThreadPoolExecutor(max_workers=max(plan.concurrency, 1)) as pool:
        futures = (pool.submit(_invoke_one, i) for i in range(plan.requests))
        for future in cf.as_completed(list(futures)):
            ok, idx = future.result()
            with counter_lock:
                if ok:
                    counters["ok"] += 1
                else:
                    counters["fail"] += 1
                total = counters["ok"] + counters["fail"]
                if total % progress_every == 0:
                    elapsed = max(time.time() - started, 1e-6)
                    rps = total / elapsed
                    logger.info(
                        "progress total=%d ok=%d fail=%d elapsed=%.1fs rps=%.0f",
                        total,
                        counters["ok"],
                        counters["fail"],
                        elapsed,
                        rps,
                    )

    elapsed = max(time.time() - started, 1e-6)
    rps = (counters["ok"] + counters["fail"]) / elapsed
    return {
        "requests_total": plan.requests,
        "ok_count": counters["ok"],
        "fail_count": counters["fail"],
        "elapsed_s": round(elapsed, 3),
        "rps": round(rps, 2),
    }


# ----------------------------------------------------------------------------
# CLI.
# ----------------------------------------------------------------------------


def _parse_argv(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="jpcite Lane G Lambda mass-invocation burn driver")
    p.add_argument(
        "--function-name",
        default="jpcite-credit-canary-attestation-lite",
    )
    p.add_argument("--requests", type=int, default=10_000)
    p.add_argument("--concurrency", type=int, default=256)
    p.add_argument(
        "--rps-cap", type=float, default=11_500.0, help="leaky-bucket cap, default 11.5K req/sec"
    )
    p.add_argument("--region", default="ap-northeast-1")
    p.add_argument("--run-id", default="")
    p.add_argument("--lane", default="G")
    p.add_argument("--memory-mb", type=int, default=DEFAULT_MEMORY_MB)
    p.add_argument("--duration-ms", type=int, default=DEFAULT_DURATION_MS)
    p.add_argument("--budget-usd", type=float, default=500.0)
    p.add_argument("--commit", action="store_true")
    p.add_argument("--unlock-live-aws-commands", action="store_true", dest="unlock_live")
    p.add_argument(
        "--profile",
        default=os.environ.get("AWS_PROFILE", "") or None,
        help="boto3 profile name (defaults to $AWS_PROFILE)",
    )
    p.add_argument("--envelope-out", default="", help="optional path to write the envelope JSON")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv)
    run_id = args.run_id or dt.datetime.now(dt.UTC).strftime("lane-g-%Y%m%dT%H%M%SZ")

    plan = BurnPlan(
        function_name=args.function_name,
        requests=int(args.requests),
        concurrency=int(args.concurrency),
        rps_cap=float(args.rps_cap),
        region=args.region,
        run_id=run_id,
        lane=args.lane,
        memory_mb=int(args.memory_mb),
        duration_ms=int(args.duration_ms),
        budget_usd=float(args.budget_usd),
        commit=bool(args.commit),
        unlock_live=bool(args.unlock_live),
    )
    projection = project_cost(plan.requests, memory_mb=plan.memory_mb, duration_ms=plan.duration_ms)

    classification = classify(plan, projection)
    if classification != "LIVE":
        env = build_envelope(plan, projection)
        print(json.dumps(env, indent=2, ensure_ascii=False))
        if args.envelope_out:
            try:
                with open(args.envelope_out, "w", encoding="utf-8") as fh:
                    json.dump(env, fh, indent=2, ensure_ascii=False)
            except OSError as exc:
                logger.warning("envelope write failed: %s", exc)
        return 0

    logger.info(
        "LIVE burn fn=%s requests=%d concurrency=%d rps_cap=%.0f profile=%s",
        plan.function_name,
        plan.requests,
        plan.concurrency,
        plan.rps_cap,
        args.profile or "<default>",
    )
    result = _run_live(plan, profile=args.profile)
    env = build_envelope(plan, projection, result=result)
    print(json.dumps(env, indent=2, ensure_ascii=False))
    if args.envelope_out:
        try:
            with open(args.envelope_out, "w", encoding="utf-8") as fh:
                json.dump(env, fh, indent=2, ensure_ascii=False)
        except OSError as exc:
            logger.warning("envelope write failed: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
