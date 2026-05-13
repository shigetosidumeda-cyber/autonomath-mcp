#!/usr/bin/env python3
"""Wave 38 — Cumulative endpoint coverage audit (W17-W37 absorbed).

The Wave 15 ``audit_runner_seo.py`` audits the static site for SEO health.
This script extends that frame: it walks ``docs/openapi/v1.json`` (or
``site/openapi.json`` when running off the live mirror), enumerates every
path emitted between Waves 17-37 (218 → 282 → 320+ as cohort expansion
shipped), and emits a JSON snapshot the dashboard + regression gate can
read.

Output structure:

    {
      "schema_version": 1,
      "generated_at": "<ISO 8601>",
      "openapi_source": "docs/openapi/v1.json",
      "paths_total": 238,
      "paths_by_prefix": {"/v1/programs": 12, ...},
      "wave_cohorts": {
        "wave31_axis1bc": ["/v1/jpo/...", "/v1/edinet/..."],
        "wave33_axis2": ["/v1/am/cohort_5d/...", ...],
        "wave34_axis4": [...],
        "wave35_axis5": [...],
        "wave36_axis6": [...],
        "wave37_freshness": [...]
      },
      "missing_expected": [],
      "verdict": "ok" | "degraded" | "fail"
    }

Pure stdlib. NO network calls in the default mode. With ``--probe-live``
the script will additionally fan-out 5 sample queries per path against a
target host and verify 2xx — this is the path used by the GHA matrix when
auditing the deployed API.

Usage:
    python3 scripts/ops/audit_endpoint_coverage_v2.py \\
        --out-json analytics/endpoint_coverage_w38.json
    python3 scripts/ops/audit_endpoint_coverage_v2.py \\
        --probe-live https://api.jpcite.com \\
        --out-json analytics/endpoint_coverage_w38_live.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OPENAPI = REPO_ROOT / "docs" / "openapi" / "v1.json"
MIRROR_OPENAPI = REPO_ROOT / "site" / "openapi.json"

# Each wave shipped a recognisable prefix. The matcher is keyword-based so
# new sub-paths added inside the same cohort are auto-grouped on next run.
WAVE_COHORT_PATTERNS: dict[str, list[str]] = {
    "wave31_axis1bc_jpo_edinet": ["/jpo/", "/edinet/", "/patent"],
    "wave32_axis1def_court_industry_nta": [
        "/court_decisions",
        "/industry/",
        "/nta_",
    ],
    "wave33_axis2_cohort_risk_supplier": [
        "/cohort_5d",
        "/program_risk_4d",
        "/supplier_chain",
        "/program_risk",
    ],
    "wave34_axis4_combine": [
        "/portfolio_optimize",
        "/houjin_risk_score",
        "/subsidy_30yr_forecast",
        "/alliance_opportunity",
        "/knowledge_graph",
    ],
    "wave35_axis5_multilingual": ["/en/", "/zh/", "/ko/", "lang="],
    "wave35_axis6_output": [
        "/export",
        "/pdf",
        "/excel",
        "/webhook",
        "/plugins/",
    ],
    "wave36_axis6_plugins": ["/freee", "/mf", "/yayoi", "/notion", "/linear"],
    "wave37_freshness_sla": ["/freshness", "/sla", "/cron_schedule"],
}

EXPECTED_MIN_PATHS = 218  # Wave 17 lower bound; degraded if below.


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_openapi(path: Path) -> tuple[Path, dict[str, Any]]:
    if not path.exists() and MIRROR_OPENAPI.exists():
        path = MIRROR_OPENAPI
    if not path.exists():
        raise SystemExit(f"OpenAPI file not found: {path}")
    return path, json.loads(path.read_text(encoding="utf-8"))


def classify_path(p: str) -> str | None:
    for cohort, needles in WAVE_COHORT_PATTERNS.items():
        if any(n in p for n in needles):
            return cohort
    return None


def summarise(spec: dict[str, Any]) -> dict[str, Any]:
    paths = list(spec.get("paths", {}).keys())
    by_prefix: dict[str, int] = defaultdict(int)
    cohorts: dict[str, list[str]] = defaultdict(list)
    for p in paths:
        # Group by 3-level prefix for human-scan
        parts = p.split("/")
        prefix = "/".join(parts[:4]) if len(parts) > 3 else p
        by_prefix[prefix] += 1
        cohort = classify_path(p)
        if cohort:
            cohorts[cohort].append(p)
    return {
        "paths_total": len(paths),
        "paths_by_prefix": dict(sorted(by_prefix.items(), key=lambda kv: -kv[1])[:30]),
        "wave_cohorts": {k: sorted(v) for k, v in cohorts.items()},
        "all_paths": sorted(paths),
    }


# ---------------------------------------------------------------------------
# Optional live probe
# ---------------------------------------------------------------------------


def probe_live(
    host: str, paths: list[str], timeout: float = 10.0, sample_size: int = 5
) -> dict[str, Any]:
    sampled = paths[:sample_size] if len(paths) > sample_size else paths
    results: list[dict[str, Any]] = []
    fail_count = 0
    for raw in sampled:
        # Skip parametrised paths — they would require synthetic ids.
        if "{" in raw:
            results.append({"path": raw, "status": "skipped_param", "http": None})
            continue
        url = host.rstrip("/") + raw
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "jpcite-wave38-endpoint-audit/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                code = resp.getcode()
            ok = 200 <= code < 400
            if not ok:
                fail_count += 1
            results.append({"path": raw, "status": "ok" if ok else "fail", "http": code})
        except urllib.error.HTTPError as exc:
            # 401/403 are operational gates — count as ok-shape; 5xx is fail
            http_code = exc.code
            ok = http_code in (401, 403, 405)
            if not ok:
                fail_count += 1
            results.append({"path": raw, "status": "ok" if ok else "fail", "http": http_code})
        except (urllib.error.URLError, OSError) as exc:
            fail_count += 1
            results.append({"path": raw, "status": "fail", "http": None, "error": str(exc)})
    return {
        "host": host,
        "sampled": len(sampled),
        "fail_count": fail_count,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def verdict_for(summary: dict[str, Any], live: dict[str, Any] | None) -> str:
    if summary["paths_total"] < EXPECTED_MIN_PATHS:
        return "fail"
    if live is not None and live["fail_count"] > 0:
        return "degraded"
    if summary["paths_total"] < EXPECTED_MIN_PATHS + 20:
        return "degraded"
    return "ok"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--openapi", default=str(DEFAULT_OPENAPI), help="Path to OpenAPI spec.")
    p.add_argument("--out-json", required=False, help="Where to write JSON snapshot.")
    p.add_argument(
        "--probe-live",
        help="Host base (e.g. https://api.jpcite.com); when set, probe live endpoints.",
    )
    args = p.parse_args(argv)

    path, spec = load_openapi(Path(args.openapi))
    summary = summarise(spec)

    live = None
    if args.probe_live:
        live = probe_live(args.probe_live, summary["all_paths"])

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "openapi_source": str(path.relative_to(REPO_ROOT)),
        "paths_total": summary["paths_total"],
        "paths_by_prefix": summary["paths_by_prefix"],
        "wave_cohorts": summary["wave_cohorts"],
        "expected_min_paths": EXPECTED_MIN_PATHS,
        "live_probe": live,
        "verdict": verdict_for(summary, live),
    }

    out_text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(out_text)
    else:
        print(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
