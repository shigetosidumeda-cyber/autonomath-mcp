#!/usr/bin/env python3
"""Wave 43.3.10 cell 10 — Aggregated SLA breach detection + Telegram push.

12 SLA metric (healthz uptime / 60-endpoint surface / freshness rollup /
cron success rate / RUM web-vitals / DLQ depth / circuit-breaker state /
backup integrity / R2 hash / postmortem queue / status_alerts critical /
ax_5pillars verdict). Per `feedback_no_operator_llm_api` and Wave 25 base:
NO LLM call — stdlib urllib POST to Telegram Bot API.

Outputs (rotation-friendly):
* ``analytics/sla_breach_w43_3_10.jsonl``   — append-only metric history
* ``site/status/sla_breach_w43_3_10.json``  — latest snapshot sidecar

When ``TG_BOT_TOKEN`` / ``TG_CHAT_ID`` env vars are unset the script still
computes the verdict (useful for dry-run / CI) and exits 0 — graceful no-op
per Wave 41 pattern.

Cron handle: ``.github/workflows/sla-breach-hourly.yml`` (hourly).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS = REPO_ROOT / "analytics"
SITE_STATUS = REPO_ROOT / "site" / "status"

JSONL = ANALYTICS / "sla_breach_w43_3_10.jsonl"
SIDECAR = SITE_STATUS / "sla_breach_w43_3_10.json"

# 12 SLA metrics. Each row: (id, source_relpath, threshold_field, op, value, label).
# op = "lt" means breach when value < threshold; "gt" means breach when value > threshold.
METRICS: list[dict[str, Any]] = [
    {
        "id": "healthz_uptime_24h",
        "src": "site/status/status.json",
        "field": "uptime_24h_pct",
        "op": "lt",
        "threshold": 99.0,
        "label": "healthz uptime",
    },
    {
        "id": "endpoint_surface_200_rate",
        "src": "site/status/status.json",
        "field": "endpoint_200_rate",
        "op": "lt",
        "threshold": 0.98,
        "label": "60-endpoint surface 200 rate",
    },
    {
        "id": "freshness_axes_ok",
        "src": "analytics/freshness_rollup.json",
        "field": "axes_ok_count",
        "op": "lt",
        "threshold": 10,
        "label": "freshness rollup green axes",
    },
    {
        "id": "cron_success_rate_24h",
        "src": "analytics/cron_health_24h.json",
        "field": "success_rate_24h",
        "op": "lt",
        "threshold": 0.95,
        "label": "cron 24h success rate",
    },
    {
        "id": "rum_lcp_p75",
        "src": "site/status/rum.json",
        "field": "p75_lcp_ms",
        "op": "gt",
        "threshold": 4000,
        "label": "RUM LCP p75",
    },
    {
        "id": "dlq_depth",
        "src": "analytics/dlq_depth.json",
        "field": "depth",
        "op": "gt",
        "threshold": 100,
        "label": "DLQ depth",
    },
    {
        "id": "circuit_state_open",
        "src": "analytics/circuit_state.json",
        "field": "open_count",
        "op": "gt",
        "threshold": 0,
        "label": "circuit breaker open",
    },
    {
        "id": "backup_integrity_pass",
        "src": "analytics/backup_verify_daily.json",
        "field": "integrity_pass",
        "op": "lt",
        "threshold": 1,
        "label": "backup integrity",
    },
    {
        "id": "r2_hash_match",
        "src": "analytics/backup_verify_daily.json",
        "field": "r2_hash_match",
        "op": "lt",
        "threshold": 1,
        "label": "R2 hash match",
    },
    {
        "id": "postmortem_queue",
        "src": "analytics/postmortem_queue.json",
        "field": "open_count",
        "op": "gt",
        "threshold": 0,
        "label": "postmortem queue",
    },
    {
        "id": "status_alerts_critical",
        "src": "site/status/status_alerts_w41.json",
        "field": "critical_count",
        "op": "gt",
        "threshold": 0,
        "label": "status_alerts critical",
    },
    {
        "id": "ax_5pillars_average",
        "src": "site/status/ax_5pillars.json",
        "field": "average_score",
        "op": "lt",
        "threshold": 8.0,
        "label": "AX 5pillars verdict",
    },
]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(src_rel: str) -> dict[str, Any] | None:
    p = REPO_ROOT / src_rel
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _extract(obj: dict[str, Any] | None, field: str) -> float | None:
    if not isinstance(obj, dict):
        return None
    cur: Any = obj
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    if isinstance(cur, bool):
        return float(int(cur))
    if isinstance(cur, (int, float)):
        return float(cur)
    return None


def _evaluate(metric: dict[str, Any]) -> dict[str, Any]:
    data = _load(metric["src"])
    value = _extract(data, metric["field"])
    if value is None:
        return {
            "id": metric["id"],
            "label": metric["label"],
            "value": None,
            "threshold": metric["threshold"],
            "breach": False,
            "state": "unknown",
        }
    op = metric["op"]
    threshold = float(metric["threshold"])
    breach = (value < threshold) if op == "lt" else (value > threshold)
    return {
        "id": metric["id"],
        "label": metric["label"],
        "value": value,
        "threshold": threshold,
        "op": op,
        "breach": bool(breach),
        "state": "breach" if breach else "ok",
    }


def _send_telegram(message: str) -> str:
    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "skip:env"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": message,
            "disable_web_page_preview": "1",
        }
    ).encode("ascii")
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - telegram https
            return f"ok:{resp.status}"
    except (urllib.error.URLError, TimeoutError) as exc:
        return f"error:{str(exc)[:120]}"


def run() -> int:
    ts = _now_iso()
    results = [_evaluate(m) for m in METRICS]
    breaches = [r for r in results if r["breach"]]
    payload = {
        "snapshot_ts": ts,
        "schema_version": 1,
        "metric_count": len(METRICS),
        "breach_count": len(breaches),
        "metrics": results,
    }
    SIDECAR.parent.mkdir(parents=True, exist_ok=True)
    SIDECAR.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    with JSONL.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {"ts": ts, "breach_count": len(breaches), "ids": [b["id"] for b in breaches]},
                ensure_ascii=False,
            )
            + "\n"
        )

    tg_status = "skip:no_breach"
    if breaches:
        lines = [
            f"[{b['id']}] {b['label']} value={b['value']} threshold={b['threshold']}"
            for b in breaches
        ]
        tg_status = _send_telegram("jpcite W43.3.10 SLA breach\n" + "\n".join(lines))

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(REPO_ROOT))
        except ValueError:
            return str(p)

    print(
        json.dumps(
            {
                "snapshot_ts": ts,
                "breach_count": len(breaches),
                "metric_count": len(METRICS),
                "telegram": tg_status,
                "sidecar": _rel(SIDECAR),
                "jsonl": _rel(JSONL),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(run())
