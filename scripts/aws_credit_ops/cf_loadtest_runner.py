#!/usr/bin/env python3
"""CloudFront bandwidth load tester for jpcite packet mirror.

Fetches a sample of packet JSON files via the CloudFront distribution to
burn S3-origin → CloudFront-edge → client transfer bandwidth on AWS-side
credit. Runs locally (CLI) **and** inside Lambda — the same module is
imported by ``infra/aws/lambda/jpcite_cf_loadtest.py``.

Safety model (mirrors ``emit_burn_metric.py`` + ``emit_canary_attestation.py``):

- **DRY_RUN by default.** ``--commit`` is required to actually issue HTTP
  requests. Without it the runner prints the would-fetch URL sample +
  expected transfer envelope and exits 0.
- Live mode further requires ``--unlock-live-bandwidth-burn`` to pass —
  matches the operator-only flag used by canary attestation. Without it
  the runner short-circuits even when ``--commit`` is passed.
- Budget cap (``--budget-usd``, default 100) gates the *projected*
  transfer cost. The runner declines to run when projected_cost > budget,
  printing the projection envelope.

Cost model (Asia Pacific 1 — Tokyo, prefix tier ≤10 TB):

    egress USD/GB  = 0.114   (CloudFront ap-northeast-1 edge → public internet)
    request USD/req = 0.012 / 10_000 = 1.2e-6 (GET/HEAD HTTPS)

CLI usage (small-packet mix, the default)::

    $ ./scripts/aws_credit_ops/cf_loadtest_runner.py \
        --distribution-domain d111111abcdef8.cloudfront.net \
        --requests 10000 --concurrency 64

CLI usage (large_packet_streaming — burn 100+ GB by repeating big files)::

    $ ./scripts/aws_credit_ops/cf_loadtest_runner.py \
        --distribution-domain d111111abcdef8.cloudfront.net \
        --mode large_packet_streaming \
        --large-fetches 12 --small-fetches 2000 \
        --commit --unlock-live-bandwidth-burn

The runner samples object keys from a static manifest written by
``scripts/aws_credit_ops/cf_loadtest_build_manifest.py`` (see sibling).
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SCHEMA_VERSION: Final[str] = "jpcite.cf_loadtest_envelope.v2"

# Pricing constants. Asia-Pacific Tokyo edge, first tier (≤10 TB / month).
USD_PER_GB_ASIA: Final[float] = 0.114
USD_PER_REQUEST_HTTPS: Final[float] = 0.012 / 10_000  # 0.012 USD / 10k req
BYTES_PER_GB: Final[int] = 1_073_741_824  # 1024^3 (GiB; AWS CloudFront bills in binary GiB)

MODE_SMALL_MIX: Final[str] = "small_packet_mix"
MODE_LARGE_STREAMING: Final[str] = "large_packet_streaming"

# Hard-coded large-file keys for the ``large_packet_streaming`` mode.
# These point at multi-MB / GB objects that are mirrored through the
# CloudFront distribution; each fetch burns the full file's egress.
# Keep this list short and stable — adding keys requires the S3 objects
# to exist behind the CloudFront origin.
LARGE_KEYS: Final[tuple[str, ...]] = (
    "embeddings_db/embeddings.db",  # ~1.19 GB SQLite snapshot
)

# Per-file size hints (bytes) used only for projection — actual bytes
# are observed when ``--commit --unlock-live-bandwidth-burn`` is set.
LARGE_KEY_AVG_BYTES: Final[int] = 1_191_952_384  # ~1.19 GB (embeddings.db actual size 2026-05-16)
SMALL_KEY_AVG_BYTES: Final[int] = 2_000  # ~2 KB JSON packet


# ----------------------------------------------------------------------------
# Helpers — pure functions, fully testable without network or HTTP client.
# ----------------------------------------------------------------------------


def project_transfer_cost(
    requests: int,
    avg_object_bytes: int,
    *,
    usd_per_gb: float = USD_PER_GB_ASIA,
    usd_per_request: float = USD_PER_REQUEST_HTTPS,
) -> dict[str, float]:
    """Project transfer + request cost for a load test plan.

    Returns a flat dict with ``total_bytes``, ``total_gb``, ``transfer_usd``,
    ``request_usd``, and ``total_usd`` — easy to JSON-serialise.
    """

    requests = max(int(requests), 0)
    avg = max(int(avg_object_bytes), 0)
    total_bytes = float(requests) * float(avg)
    total_gb = total_bytes / float(BYTES_PER_GB)
    transfer_usd = total_gb * float(usd_per_gb)
    request_usd = float(requests) * float(usd_per_request)
    total_usd = transfer_usd + request_usd
    return {
        "requests": float(requests),
        "avg_object_bytes": float(avg),
        "total_bytes": total_bytes,
        "total_gb": total_gb,
        "transfer_usd": round(transfer_usd, 6),
        "request_usd": round(request_usd, 6),
        "total_usd": round(total_usd, 6),
    }


def project_mixed_transfer_cost(
    large_fetches: int,
    small_fetches: int,
    *,
    large_avg_bytes: int = LARGE_KEY_AVG_BYTES,
    small_avg_bytes: int = SMALL_KEY_AVG_BYTES,
    usd_per_gb: float = USD_PER_GB_ASIA,
    usd_per_request: float = USD_PER_REQUEST_HTTPS,
) -> dict[str, float]:
    """Project transfer cost for a large+small mixed plan.

    Mirrors :func:`project_transfer_cost` but accepts split fetch counts so
    the projection envelope reflects the realistic large/small mix used by
    ``large_packet_streaming`` mode.
    """

    large_fetches = max(int(large_fetches), 0)
    small_fetches = max(int(small_fetches), 0)
    total_requests = large_fetches + small_fetches
    total_bytes = (
        float(large_fetches) * float(large_avg_bytes)
        + float(small_fetches) * float(small_avg_bytes)
    )
    total_gb = total_bytes / float(BYTES_PER_GB)
    transfer_usd = total_gb * float(usd_per_gb)
    request_usd = float(total_requests) * float(usd_per_request)
    total_usd = transfer_usd + request_usd
    return {
        "requests": float(total_requests),
        "large_fetches": float(large_fetches),
        "small_fetches": float(small_fetches),
        "large_avg_bytes": float(large_avg_bytes),
        "small_avg_bytes": float(small_avg_bytes),
        "total_bytes": total_bytes,
        "total_gb": total_gb,
        "transfer_usd": round(transfer_usd, 6),
        "request_usd": round(request_usd, 6),
        "total_usd": round(total_usd, 6),
    }


def load_manifest_keys(manifest_path: Path) -> list[str]:
    """Load packet key list from a newline-delimited or JSON manifest file."""

    text = manifest_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError(f"manifest {manifest_path} is not a JSON list")
        return [str(k) for k in data]
    return [line.strip() for line in text.splitlines() if line.strip()]


def sample_keys(keys: list[str], n: int, *, seed: int = 0) -> list[str]:
    """Sample ``n`` keys with replacement using a deterministic seed."""

    if not keys:
        return []
    rng = random.Random(seed)  # noqa: S311 — deterministic test sampling, not security
    return [rng.choice(keys) for _ in range(max(int(n), 0))]


def build_mixed_keys(
    small_keys: list[str],
    large_fetches: int,
    small_fetches: int,
    *,
    seed: int = 0,
    large_keys: tuple[str, ...] = LARGE_KEYS,
) -> list[str]:
    """Compose a fetch order of ``large_fetches`` large keys + ``small_fetches`` small.

    Order is randomised but deterministic for a given seed so the same
    plan always burns the same bytes in the same sequence.
    """

    rng = random.Random(seed)  # noqa: S311 — deterministic sampling
    plan: list[str] = []
    if not large_keys:
        large_keys = LARGE_KEYS
    for _ in range(max(int(large_fetches), 0)):
        plan.append(rng.choice(large_keys))
    if small_keys:
        for _ in range(max(int(small_fetches), 0)):
            plan.append(rng.choice(small_keys))
    rng.shuffle(plan)
    return plan


def build_urls(distribution_domain: str, keys: Iterable[str]) -> list[str]:
    """Compose ``https://<domain>/<key>`` URLs from CloudFront domain + keys."""

    domain = distribution_domain.strip().rstrip("/")
    if not domain:
        raise ValueError("distribution_domain must not be empty")
    out = []
    for k in keys:
        k_norm = str(k).lstrip("/")
        out.append(f"https://{domain}/{k_norm}")
    return out


@dataclasses.dataclass(frozen=True)
class LoadTestPlan:
    distribution_domain: str
    requests: int
    concurrency: int
    avg_object_bytes: int
    manifest_path: str
    seed: int
    budget_usd: float
    commit: bool
    unlock_live: bool
    mode: str = MODE_SMALL_MIX
    large_fetches: int = 0
    small_fetches: int = 0

    def asdict(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def classify(plan: LoadTestPlan, projection: dict[str, float]) -> str:
    """Return ``DRY_RUN`` / ``BLOCKED_BUDGET`` / ``BLOCKED_FLAG`` / ``LIVE``."""

    if not plan.commit:
        return "DRY_RUN"
    if not plan.unlock_live:
        return "BLOCKED_FLAG"
    if projection["total_usd"] > plan.budget_usd:
        return "BLOCKED_BUDGET"
    return "LIVE"


def build_envelope(
    plan: LoadTestPlan,
    keys_total: int,
    projection: dict[str, float],
    *,
    timestamp: dt.datetime | None = None,
) -> dict[str, object]:
    """Build the would-emit envelope for stdout / Lambda return value."""

    ts = timestamp or dt.datetime.now(dt.UTC)
    classification = classify(plan, projection)
    return {
        "schema_version": SCHEMA_VERSION,
        "timestamp": ts.isoformat(),
        "plan": plan.asdict(),
        "keys_total_in_manifest": int(keys_total),
        "projection": projection,
        "classification": classification,
        "budget_usd": plan.budget_usd,
    }


# ----------------------------------------------------------------------------
# Live HTTP exec — only imported when classification == LIVE.
# ----------------------------------------------------------------------------


def _stream_fetch(
    url: str,
    *,
    timeout_s: float,
    chunk_bytes: int,
) -> tuple[bool, int]:
    """Download a URL in chunks and discard the body.

    Returns ``(ok, bytes_received)``. Streaming-and-discarding keeps the
    memory footprint constant regardless of object size — required for
    the ``large_packet_streaming`` mode where each fetch is 1+ GB.
    """

    import urllib.request

    try:
        req = urllib.request.Request(url, method="GET")  # noqa: S310 — known CF mirror domain
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            total = 0
            while True:
                chunk = resp.read(chunk_bytes)
                if not chunk:
                    break
                total += len(chunk)
            return True, total
    except Exception as exc:  # pragma: no cover — exercised by smoke
        logger.debug("fetch failed url=%s err=%s", url, exc)
        return False, 0


def _run_live_http(
    urls: list[str],
    *,
    concurrency: int,
    timeout_s: float = 120.0,
    chunk_bytes: int = 1 << 20,  # 1 MiB
) -> dict[str, object]:
    """Execute the HTTP fetches with bounded concurrency.

    Uses ``urllib.request`` from stdlib — no third-party HTTP client so
    Lambda zip stays minimal and there's no boto3 import cost path.

    Bodies are streamed-and-discarded in ``chunk_bytes`` chunks so 1+ GB
    fetches do not OOM the Lambda runtime.
    """

    import concurrent.futures as cf

    n = len(urls)
    bytes_total = 0
    ok_count = 0
    fail_count = 0
    started = time.time()

    def _fetch(url: str) -> tuple[bool, int]:
        return _stream_fetch(url, timeout_s=timeout_s, chunk_bytes=chunk_bytes)

    with cf.ThreadPoolExecutor(max_workers=max(int(concurrency), 1)) as pool:
        for ok, nbytes in pool.map(_fetch, urls):
            if ok:
                ok_count += 1
                bytes_total += nbytes
            else:
                fail_count += 1

    elapsed = max(time.time() - started, 1e-6)
    return {
        "requests_total": int(n),
        "ok_count": int(ok_count),
        "fail_count": int(fail_count),
        "bytes_total": int(bytes_total),
        "elapsed_s": round(elapsed, 3),
        "rps": round(n / elapsed, 2),
        "throughput_mbps": round((bytes_total * 8 / 1e6) / elapsed, 2),
    }


# ----------------------------------------------------------------------------
# CLI entry point.
# ----------------------------------------------------------------------------


def _parse_argv(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="jpcite CloudFront bandwidth load tester")
    p.add_argument("--distribution-domain", required=True,
                   help="CloudFront distribution domain (e.g. d1234.cloudfront.net)")
    p.add_argument("--manifest-path", default="infra/aws/cloudfront/jpcite_packet_keys.txt",
                   help="newline-delimited or JSON list of S3 keys to sample")
    p.add_argument("--mode", default=MODE_SMALL_MIX,
                   choices=[MODE_SMALL_MIX, MODE_LARGE_STREAMING],
                   help="small_packet_mix (default) or large_packet_streaming")
    p.add_argument("--requests", type=int, default=10_000,
                   help="(small_packet_mix only) total request count")
    p.add_argument("--large-fetches", type=int, default=0,
                   help="(large_packet_streaming) number of large-key fetches")
    p.add_argument("--small-fetches", type=int, default=0,
                   help="(large_packet_streaming) number of small-key fetches")
    p.add_argument("--concurrency", type=int, default=64)
    p.add_argument("--avg-object-bytes", type=int, default=2_000,
                   help="projection input (real bytes are read from network when --commit)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--budget-usd", type=float, default=100.0,
                   help="abort if projected total_usd exceeds this")
    p.add_argument("--commit", action="store_true",
                   help="actually issue HTTP requests (otherwise DRY_RUN)")
    p.add_argument("--unlock-live-bandwidth-burn", action="store_true",
                   dest="unlock_live",
                   help="operator-only flag; required in addition to --commit")
    p.add_argument("--max-sample-urls", type=int, default=10,
                   help="print this many sampled URLs in dry-run envelope")
    p.add_argument("--timeout-s", type=float, default=120.0,
                   help="per-fetch socket timeout (large files need ≥60s)")
    p.add_argument("--chunk-bytes", type=int, default=1 << 20,
                   help="streaming read chunk size in bytes (default 1 MiB)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv)

    if args.mode == MODE_LARGE_STREAMING:
        total_requests = max(int(args.large_fetches), 0) + max(int(args.small_fetches), 0)
        # avg_object_bytes is only used by the legacy projection; the
        # mixed projection is the authoritative one for this mode.
        avg_for_legacy = LARGE_KEY_AVG_BYTES if args.large_fetches else SMALL_KEY_AVG_BYTES
        plan = LoadTestPlan(
            distribution_domain=args.distribution_domain,
            requests=total_requests,
            concurrency=args.concurrency,
            avg_object_bytes=avg_for_legacy,
            manifest_path=args.manifest_path,
            seed=args.seed,
            budget_usd=args.budget_usd,
            commit=args.commit,
            unlock_live=args.unlock_live,
            mode=MODE_LARGE_STREAMING,
            large_fetches=int(args.large_fetches),
            small_fetches=int(args.small_fetches),
        )
        projection = project_mixed_transfer_cost(
            args.large_fetches, args.small_fetches
        )
    else:
        plan = LoadTestPlan(
            distribution_domain=args.distribution_domain,
            requests=args.requests,
            concurrency=args.concurrency,
            avg_object_bytes=args.avg_object_bytes,
            manifest_path=args.manifest_path,
            seed=args.seed,
            budget_usd=args.budget_usd,
            commit=args.commit,
            unlock_live=args.unlock_live,
            mode=MODE_SMALL_MIX,
            large_fetches=0,
            small_fetches=args.requests,
        )
        projection = project_transfer_cost(args.requests, args.avg_object_bytes)

    manifest = Path(args.manifest_path)
    if not manifest.exists():
        logger.warning("manifest %s not found — using empty key list", manifest)
        small_keys: list[str] = []
    else:
        small_keys = load_manifest_keys(manifest)

    if plan.mode == MODE_LARGE_STREAMING:
        sampled = build_mixed_keys(
            small_keys,
            plan.large_fetches,
            plan.small_fetches,
            seed=plan.seed,
        )
    else:
        sampled = sample_keys(small_keys, plan.requests, seed=plan.seed)
    envelope = build_envelope(plan, keys_total=len(small_keys), projection=projection)

    classification = str(envelope["classification"])
    envelope["sample_urls"] = build_urls(plan.distribution_domain, sampled[: args.max_sample_urls])

    if classification != "LIVE":
        print(json.dumps(envelope, indent=2, ensure_ascii=False))
        return 0

    if not sampled:
        envelope["error"] = "manifest empty — cannot execute live load test"
        print(json.dumps(envelope, indent=2, ensure_ascii=False))
        return 2

    urls = build_urls(plan.distribution_domain, sampled)
    result = _run_live_http(
        urls,
        concurrency=plan.concurrency,
        timeout_s=args.timeout_s,
        chunk_bytes=args.chunk_bytes,
    )
    envelope["result"] = result
    bytes_total_val = result["bytes_total"]
    requests_total_val = result["requests_total"]
    assert isinstance(bytes_total_val, (int, float)), "bytes_total must be numeric"
    assert isinstance(requests_total_val, (int, float)), "requests_total must be numeric"
    actual_gb = float(bytes_total_val) / float(BYTES_PER_GB)
    transfer_usd = round(actual_gb * USD_PER_GB_ASIA, 6)
    request_usd = round(float(requests_total_val) * USD_PER_REQUEST_HTTPS, 6)
    envelope["actual_transfer_usd"] = transfer_usd
    envelope["actual_request_usd"] = request_usd
    envelope["actual_total_usd"] = round(transfer_usd + request_usd, 6)
    print(json.dumps(envelope, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
