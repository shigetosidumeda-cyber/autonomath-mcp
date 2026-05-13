#!/usr/bin/env python3
"""H2: Aggregate 9 audit metrics into `site/status/audit_dashboard.json`,
the SOT consumed by `site/status/audit_dashboard.html` and the
`audit-regression-gate.yml` weekly workflow.

9 metrics
---------
    1. SEO crawl coverage    (Bingbot+Googlebot fetch ratio)        from monitoring/seo_metrics.md or analytics/seo_*.jsonl
    2. GEO citation rate     (LLM citation share)                   from analytics/aeo_citation_bench_*.jsonl
    3. HTML structure        (JSON-LD valid + heading hierarchy)    from analytics/html_audit_*.jsonl
    4. a11y                  (axe-core violations/1k pages)          from analytics/a11y_*.jsonl
    5. Core Web Vitals       (LCP/INP/CLS weighted)                  from site/status/rum.json (server-rolling)
    6. CF AI Audit           (許可 LLM bot ratio)                    from site/status/cf_ai_audit.json
    7. RUM beacon            (client-side LCP p75)                   from site/status/rum.json
    8. SLA uptime            (api.jpcite.com 7-day)                  from monitoring/uptime_metrics_endpoint.md + status.json
    9. Data coverage         (programs S/A tier 200-OK ratio)        from analytics/source_refresh_summary_*.jsonl

For any metric where the upstream input is missing the aggregator emits
a `null` value (not a zero) so consumers can distinguish "data unavailable"
from "metric is zero today". This matches the honesty rule —
`source_fetched_at` semantics rolled out across the codebase.

4 pillars
---------
Each pillar is a weighted average across the 9 metrics. The weights
encode the AX (Agent Experience) framework:

    Discovery  = 0.5 SEO + 0.3 GEO + 0.2 AI_audit
    Reasoning  = 0.4 HTML + 0.3 a11y + 0.3 coverage
    Action     = 0.5 SLA + 0.5 RUM
    Context    = 0.4 GEO + 0.3 HTML + 0.3 coverage

(The weights also live in `docs/_internal/ax_4_pillars.md` for governance.)

7-day rolling
-------------
The output keeps a `daily` array of the last 7 daily snapshots. Each
re-run prepends today's row and pops anything older than 7 days. The
write is atomic (write tmp + rename) so a partial failure cannot leave
the dashboard with a half-written JSON.

Usage
-----
    python3 scripts/ops/audit_dashboard_aggregate.py
    python3 scripts/ops/audit_dashboard_aggregate.py --dry-run

CI hook
-------
The weekly workflow runs this before pushing — see
.github/workflows/audit-regression-gate.yml.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_PATH = REPO_ROOT / "site" / "status" / "audit_dashboard.json"
ANALYTICS_DIR = REPO_ROOT / "analytics"
STATUS_DIR = REPO_ROOT / "site" / "status"
MONITORING_DIR = REPO_ROOT / "monitoring"

# Metric targets — mirrored from the static HTML so /status/audit_dashboard.html
# and audit-regression-gate.yml stay in sync.
METRIC_SPEC: dict[str, dict] = {
    "seo": {"target": 92.0, "unit": "%", "lower_is_better": False},
    "geo": {"target": 35.0, "unit": "%", "lower_is_better": False},
    "html": {"target": 0.95, "unit": None, "lower_is_better": False},
    "a11y": {"target": 0.5, "unit": "/1k", "lower_is_better": True},
    "cwv": {"target": 0.90, "unit": None, "lower_is_better": False},
    "ai_audit": {"target": 80.0, "unit": "%", "lower_is_better": False},
    "rum": {"target": 2500, "unit": "ms", "lower_is_better": True},
    "sla": {"target": 99.9, "unit": "%", "lower_is_better": False},
    "coverage": {"target": 95.0, "unit": "%", "lower_is_better": False},
}

PILLAR_WEIGHTS: dict[str, dict[str, float]] = {
    "discovery": {"seo": 0.5, "geo": 0.3, "ai_audit": 0.2},
    "reasoning": {"html": 0.4, "a11y": 0.3, "coverage": 0.3},
    "action": {"sla": 0.5, "rum": 0.5},
    "context": {"geo": 0.4, "html": 0.3, "coverage": 0.3},
}


def _read_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl_latest(prefix: str) -> dict | None:
    """Return the most-recent JSONL row from analytics/ whose basename
    starts with `prefix`. Useful for *_2026-05-11.jsonl rolling files.
    """
    if not ANALYTICS_DIR.exists():
        return None
    files = sorted(
        [p for p in ANALYTICS_DIR.iterdir() if p.is_file() and p.name.startswith(prefix)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in files:
        try:
            rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            continue
        for raw in reversed(rows):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                continue
    return None


def collect_metrics() -> dict[str, dict]:
    """Pull current values for the 9 metrics from upstream artifacts."""
    out: dict[str, dict] = {}

    # 1. SEO crawl coverage
    seo_row = _read_jsonl_latest("seo_") or _read_jsonl_latest("crawl_")
    out["seo"] = {
        "value": float(seo_row["fetch_ratio_pct"])
        if seo_row and "fetch_ratio_pct" in seo_row
        else None,
    }

    # 2. GEO citation rate
    geo_row = _read_jsonl_latest("aeo_citation_") or _read_jsonl_latest("geo_")
    out["geo"] = {
        "value": float(geo_row["citation_rate_pct"])
        if geo_row and "citation_rate_pct" in geo_row
        else None,
    }

    # 3. HTML structure score
    html_row = _read_jsonl_latest("html_audit_")
    out["html"] = {
        "value": float(html_row["score"]) if html_row and "score" in html_row else None,
    }

    # 4. a11y violations / 1k pages
    a11y_row = _read_jsonl_latest("a11y_")
    out["a11y"] = {
        "value": float(a11y_row["violations_per_1k"])
        if a11y_row and "violations_per_1k" in a11y_row
        else None,
    }

    # 5. Core Web Vitals weighted
    cwv_row = _read_jsonl_latest("cwv_") or _read_json(STATUS_DIR / "rum.json")
    if cwv_row and isinstance(cwv_row, dict):
        if "cwv_weighted" in cwv_row:
            cwv_val = float(cwv_row["cwv_weighted"])
        elif "lcp_p75_ms" in cwv_row and "inp_p75_ms" in cwv_row and "cls_p75" in cwv_row:
            # Lighthouse-style: pass/warn/fail bands per CrUX 2024.
            def _band(v, good, ok):
                return 1.0 if v <= good else (0.5 if v <= ok else 0.0)

            cwv_val = round(
                (
                    0.5 * _band(cwv_row["lcp_p75_ms"], 2500, 4000)
                    + 0.4 * _band(cwv_row["inp_p75_ms"], 200, 500)
                    + 0.1 * _band(cwv_row["cls_p75"], 0.1, 0.25)
                ),
                3,
            )
        else:
            cwv_val = None
    else:
        cwv_val = None
    out["cwv"] = {"value": cwv_val}

    # 6. CF AI Audit ratio
    ai_dump = _read_json(STATUS_DIR / "cf_ai_audit.json")
    if ai_dump and isinstance(ai_dump, dict):
        allowed = ai_dump.get("allowed_bot_fetches")
        total = ai_dump.get("total_bot_fetches")
        if allowed is not None and total and float(total) > 0:
            out["ai_audit"] = {"value": round(float(allowed) / float(total) * 100, 2)}
        else:
            out["ai_audit"] = {"value": None}
    else:
        out["ai_audit"] = {"value": None}

    # 7. RUM beacon LCP p75
    rum = _read_json(STATUS_DIR / "rum.json")
    out["rum"] = {
        "value": float(rum["lcp_p75_ms"])
        if rum and isinstance(rum, dict) and "lcp_p75_ms" in rum
        else None,
    }

    # 8. SLA uptime
    status = _read_json(STATUS_DIR / "status.json")
    if status and isinstance(status, dict):
        # status.json uses either `uptime_7d_pct` or `availability` keyed.
        sla_val = (
            status.get("uptime_7d_pct")
            or status.get("availability_7d")
            or status.get("availability")
        )
        out["sla"] = {"value": float(sla_val) if sla_val is not None else None}
    else:
        out["sla"] = {"value": None}

    # 9. Data coverage — programs source URL 200 OK ratio
    cov_row = _read_jsonl_latest("source_refresh_") or _read_jsonl_latest("coverage_")
    out["coverage"] = {
        "value": float(cov_row["pct_200"]) if cov_row and "pct_200" in cov_row else None,
    }

    # Attach metric metadata
    for k, spec in METRIC_SPEC.items():
        out.setdefault(k, {"value": None})
        out[k]["target"] = spec["target"]
        out[k]["unit"] = spec["unit"]
        out[k]["lower_is_better"] = spec["lower_is_better"]

    return out


def normalize_to_pillar_unit(metric: str, value: float | None) -> float | None:
    """Map a metric value to [0..1] for pillar weighting. NULLs stay NULL."""
    if value is None:
        return None
    spec = METRIC_SPEC[metric]
    target = float(spec["target"])
    if spec["lower_is_better"]:
        if target <= 0:
            return 1.0 if value <= 0 else 0.0
        return max(0.0, min(1.0, (target / value) if value > 0 else 1.0))
    if target == 0:
        return 1.0
    return max(0.0, min(1.0, float(value) / target))


def compute_pillars(metrics: dict[str, dict]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for pillar, weights in PILLAR_WEIGHTS.items():
        total_w = 0.0
        acc = 0.0
        all_null = True
        for m, w in weights.items():
            v = normalize_to_pillar_unit(m, metrics.get(m, {}).get("value"))
            if v is None:
                continue
            total_w += w
            acc += v * w
            all_null = False
        out[pillar] = None if all_null or total_w == 0 else round(acc / total_w, 3)
    return out


def merge_daily(existing: list[dict] | None, today_row: dict) -> list[dict]:
    """Prepend today, drop anything older than 7 days. Dedupe on `date`."""
    seven_days_ago = (datetime.now(UTC) - timedelta(days=7)).date().isoformat()
    out: list[dict] = [today_row]
    seen_dates = {today_row["date"]}
    for row in existing or []:
        d = row.get("date")
        if not d or d in seen_dates or d < seven_days_ago:
            continue
        seen_dates.add(d)
        out.append(row)
    out.sort(key=lambda r: r["date"], reverse=True)
    return out[:7]


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".audit_dashboard.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            with contextlib.suppress(OSError):
                os.unlink(tmp)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default=str(OUT_PATH))
    args = parser.parse_args()

    metrics = collect_metrics()
    pillars = compute_pillars(metrics)

    today = datetime.now(UTC)
    today_row = {
        "date": today.date().isoformat(),
        "seo": metrics["seo"].get("value"),
        "geo": metrics["geo"].get("value"),
        "html": metrics["html"].get("value"),
        "a11y": metrics["a11y"].get("value"),
        "cwv": metrics["cwv"].get("value"),
        "ai_audit": metrics["ai_audit"].get("value"),
        "rum": metrics["rum"].get("value"),
        "sla": metrics["sla"].get("value"),
        "coverage": metrics["coverage"].get("value"),
    }

    existing = _read_json(Path(args.out)) or {}
    daily = merge_daily(existing.get("daily") if isinstance(existing, dict) else None, today_row)

    out_doc = {
        "schema": "jpcite/audit_dashboard/v1",
        "generated_at": today.isoformat(),
        "last_updated": today.isoformat(),
        "metrics": metrics,
        "pillars": pillars,
        "daily": daily,
        "sources": {
            "seo": "analytics/seo_*.jsonl",
            "geo": "analytics/aeo_citation_*.jsonl",
            "html": "analytics/html_audit_*.jsonl",
            "a11y": "analytics/a11y_*.jsonl",
            "cwv": "site/status/rum.json",
            "ai_audit": "site/status/cf_ai_audit.json",
            "rum": "site/status/rum.json",
            "sla": "site/status/status.json",
            "coverage": "analytics/source_refresh_*.jsonl",
        },
    }

    if args.dry_run:
        json.dump(out_doc, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0

    atomic_write(Path(args.out), out_doc)
    print(f"wrote {args.out}")
    print(f"metrics non-null: {sum(1 for m in metrics.values() if m.get('value') is not None)}/9")
    print(f"pillars non-null: {sum(1 for v in pillars.values() if v is not None)}/4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
