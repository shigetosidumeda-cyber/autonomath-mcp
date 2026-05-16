"""Lambda handler — CloudFront bandwidth load tester for jpcite.

Invocations are submitted in parallel by
``scripts/aws_credit_ops/cf_loadtest_invoke.sh``. Each Lambda fetches a
sample of packet URLs through the CloudFront mirror to burn S3-origin →
CloudFront-edge → public-internet egress bandwidth on the AWS-credit
side.

Safety model mirrors ``jpcite_credit_burn_metric.lambda_handler``:

- ``JPCITE_CF_LOADTEST_ENABLED`` env var must equal ``"true"`` for live
  HTTP exec. Anything else short-circuits to dry-run (returns envelope
  with classification ``DRY_RUN``, no HTTP issued).
- The shared library ``cf_loadtest_runner.py`` is bundled side-by-side
  in the zip so the import resolves without a package wrapper.
- CloudWatch metric emission is gated by the same flag.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Final

import boto3  # type: ignore[import-not-found]

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cf_loadtest_runner  # noqa: E402

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION: Final[str] = os.environ.get("AWS_REGION", "ap-northeast-1")
METRIC_NAMESPACE: Final[str] = os.environ.get(
    "JPCITE_CF_LOADTEST_NAMESPACE", "jpcite/credit"
)


def _enabled() -> bool:
    return os.environ.get("JPCITE_CF_LOADTEST_ENABLED", "false").strip().lower() == "true"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    """EventBridge / manual entry point.

    Event payload (optional overrides)::

        {
          "distribution_domain": "d1234.cloudfront.net",
          "requests": 10000,
          "concurrency": 64,
          "seed": 0
        }
    """

    started_at = time.time()
    live = _enabled()

    distribution_domain = str(
        event.get("distribution_domain") or _env_str("JPCITE_CF_DISTRIBUTION_DOMAIN")
    )
    if not distribution_domain:
        return {
            "lambda": "jpcite-cf-loadtest",
            "mode": "error",
            "error": "missing distribution_domain (env JPCITE_CF_DISTRIBUTION_DOMAIN or event field)",
        }

    requests_n = int(event.get("requests") or _env_int("JPCITE_CF_REQUESTS", 10_000))
    concurrency = int(event.get("concurrency") or _env_int("JPCITE_CF_CONCURRENCY", 64))
    seed = int(event.get("seed") or _env_int("JPCITE_CF_SEED", 0))
    avg_bytes = int(event.get("avg_object_bytes") or _env_int("JPCITE_CF_AVG_BYTES", 2_000))
    budget_usd = float(event.get("budget_usd") or float(os.environ.get("JPCITE_CF_BUDGET_USD", "100")))
    manifest_path = str(event.get("manifest_path") or _env_str(
        "JPCITE_CF_MANIFEST_PATH", str(_HERE / "jpcite_packet_keys.txt")
    ))

    plan = cf_loadtest_runner.LoadTestPlan(
        distribution_domain=distribution_domain,
        requests=requests_n,
        concurrency=concurrency,
        avg_object_bytes=avg_bytes,
        manifest_path=manifest_path,
        seed=seed,
        budget_usd=budget_usd,
        commit=live,
        unlock_live=live,
    )

    keys: list[str] = []
    manifest = Path(manifest_path)
    if manifest.exists():
        keys = cf_loadtest_runner.load_manifest_keys(manifest)

    projection = cf_loadtest_runner.project_transfer_cost(requests_n, avg_bytes)
    envelope = cf_loadtest_runner.build_envelope(plan, keys_total=len(keys), projection=projection)
    classification = str(envelope["classification"])
    logger.info(
        "cf_loadtest invoked mode=%s classification=%s requests=%d concurrency=%d",
        "live" if live else "dry_run",
        classification,
        requests_n,
        concurrency,
    )

    result: dict[str, Any] = {}
    if classification == "LIVE" and keys:
        sampled = cf_loadtest_runner.sample_keys(keys, requests_n, seed=seed)
        urls = cf_loadtest_runner.build_urls(distribution_domain, sampled)
        result = cf_loadtest_runner._run_live_http(urls, concurrency=concurrency)
        envelope["result"] = result
        envelope["actual_transfer_usd"] = round(
            float(result["bytes_total"]) / float(cf_loadtest_runner.BYTES_PER_GB)
            * cf_loadtest_runner.USD_PER_GB_ASIA,
            6,
        )
        envelope["actual_request_usd"] = round(
            float(result["requests_total"]) * cf_loadtest_runner.USD_PER_REQUEST_HTTPS,
            6,
        )
        envelope["actual_total_usd"] = round(
            float(envelope["actual_transfer_usd"]) + float(envelope["actual_request_usd"]),
            6,
        )

        if live:
            try:
                cw = boto3.client("cloudwatch", region_name=REGION)
                cw.put_metric_data(
                    Namespace=METRIC_NAMESPACE,
                    MetricData=[
                        {
                            "MetricName": "CFLoadTestBytes",
                            "Value": float(result["bytes_total"]),
                            "Unit": "Bytes",
                            "Dimensions": [
                                {"Name": "Distribution", "Value": distribution_domain},
                            ],
                        },
                        {
                            "MetricName": "CFLoadTestRequests",
                            "Value": float(result["requests_total"]),
                            "Unit": "Count",
                            "Dimensions": [
                                {"Name": "Distribution", "Value": distribution_domain},
                            ],
                        },
                    ],
                )
            except Exception as exc:  # pragma: no cover — best-effort metric emit
                logger.warning("CW put_metric_data failed: %s", exc)

    duration_s = round(time.time() - started_at, 3)
    payload = {
        "lambda": "jpcite-cf-loadtest",
        "mode": "live" if live else "dry_run",
        "classification": classification,
        "duration_s": duration_s,
        "envelope": envelope,
        "safety_env": {
            "JPCITE_CF_LOADTEST_ENABLED": os.environ.get("JPCITE_CF_LOADTEST_ENABLED", "false"),
        },
    }
    logger.info("cf_loadtest payload=%s", json.dumps(payload, default=str, ensure_ascii=False))
    return payload
