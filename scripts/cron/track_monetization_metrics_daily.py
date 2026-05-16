#!/usr/bin/env python3
"""Wave 42 — daily monetization KPI tracker (agent-economy 8 new metrics).

Aggregates 12 KPIs daily into ``analytics/monetization_metrics_daily.jsonl``
(append-only) + ``site/status/monetization_dashboard.json`` (sidecar for
the agent-readable dashboard at ``/status/monetization_dashboard.html``).

The 8 new agent-economy KPIs (per ``agent_monetization_guide.md`` §10.1
and memory ``feedback_agent_new_kpis_8``):

1. **Agent-Sourced Revenue (ASR)** — JPY of metered requests routed
   through MCP/agent paths. Schema reality: ``usage_events`` has no
   ``user_agent`` column, so we proxy via ``endpoint`` LIKE '/mcp/%' OR
   '/v1/am/%' OR '/llms.txt' OR '/.well-known/mcp%' OR ``client_tag``
   non-null (X-Client-Tag header signals agent-side attribution).
2. **ARC (Annual Recurring Consumption)** — total ``usage_events`` rows
   in the last 30 days × 365/30 (rolling-annualized).
3. **Cost-to-Serve per Call** — sum(cost_ledger.amount_jpy) /
   usage_events count over the last 30 days (yen, integer).
4. **Agent Retention (D30)** — fraction of ``key_hash`` values that
   issued metered requests both 30 days ago AND in the last 24h.
5. **Time-to-First-Payment (TTFP)** — median seconds from
   ``api_keys.created_at`` to the first ``usage_events.ts`` for keys
   issued in last 30d.
6. **Per-Agent Spending Variance** — p90/p50 ratio of req count per
   ``key_hash`` over the last 7 days (high = unusual concentration /
   possible abuse).
7. **AI Mention Share** — reads ``analytics/aeo_citation_bench.json`` if
   present; surfaces last weekly average cite-rate across LLMs.
8. **Justification Strength** — coverage rate of ``source_url`` +
   ``primary_name`` length on S+A programs (0-100 scale). The schema
   has no ``description`` column; programs carry source attribution +
   primary_name + aliases_json + source_mentions_json instead.

Plus 4 legacy KPIs (MRR, ARR, Churn proxy, LTV/CAC proxy) for continuity.

Hard rules (memory):
* ``feedback_autonomath_no_api_use``: zero LLM API imports.
* ``feedback_no_quick_check_on_huge_sqlite``: no PRAGMA quick_check /
  full-scan ops on autonomath.db (9.7 GB).
* ``feedback_dont_extrapolate_principles``: this script only reads
  jpintel.db (~352 MB) for usage_events + api_keys, never autonomath.db.

Usage::

    python scripts/cron/track_monetization_metrics_daily.py
    python scripts/cron/track_monetization_metrics_daily.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import statistics
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.cron.monetization_metrics")

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
ANALYTICS = REPO_ROOT / "analytics"
SITE_STATUS = REPO_ROOT / "site" / "status"

JSONL_OUT = ANALYTICS / "monetization_metrics_daily.jsonl"
SIDECAR = SITE_STATUS / "monetization_dashboard.json"

# Yen per metered request (税込 ¥3.30). Memory:
# "Non-negotiable constraints: ¥3/req metered only".
YEN_PER_REQ = 3.30

# Endpoint substrings that mark a request as agent-sourced. The DB does
# not log User-Agent, so we use endpoint shape + client_tag as the
# attribution proxy. MCP routes + autonomath am/* surface + .well-known
# discovery are all agent-only.
AGENT_ENDPOINT_HINTS = (
    "/mcp/",
    "/v1/am/",
    "/llms.txt",
    "/.well-known/mcp",
    "/.well-known/agents",
    "/openapi",
    "/v1/x402/",  # forward-compat for Wave 42+ x402 endpoint
)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_db() -> sqlite3.Connection | None:
    if not JPINTEL_DB.exists():
        logger.warning("jpintel.db not found at %s; monetization metrics = 0", JPINTEL_DB)
        return None
    conn = sqlite3.connect(JPINTEL_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Agent KPI computations
# ---------------------------------------------------------------------------


def _compute_asr_jpy(conn: sqlite3.Connection, *, days: int = 1) -> int:
    """Sum yen attributable to agent-shaped endpoints + client_tag."""
    if not _table_exists(conn, "usage_events"):
        return 0
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    likes = " OR ".join(["endpoint LIKE ?"] * len(AGENT_ENDPOINT_HINTS))
    params: list[Any] = [f"%{h}%" for h in AGENT_ENDPOINT_HINTS] + [since]
    row = conn.execute(
        f"SELECT COUNT(*) FROM usage_events "
        f"WHERE (({likes}) OR client_tag IS NOT NULL) AND ts >= ?",
        params,
    ).fetchone()
    return int((row[0] if row else 0) * YEN_PER_REQ)


def _compute_arc_rows(conn: sqlite3.Connection) -> int:
    """Annual Recurring Consumption: req count in last 30d × 365/30."""
    if not _table_exists(conn, "usage_events"):
        return 0
    since = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute("SELECT COUNT(*) FROM usage_events WHERE ts >= ?", (since,)).fetchone()
    last30 = int(row[0] if row else 0)
    return int(last30 * 365.0 / 30.0)


def _compute_cost_to_serve_jpy(conn: sqlite3.Connection) -> int:
    """Cost-to-serve per call (yen). Returns 0 if either side is unknown."""
    if not (_table_exists(conn, "usage_events") and _table_exists(conn, "cost_ledger")):
        return 0
    since = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    req_row = conn.execute("SELECT COUNT(*) FROM usage_events WHERE ts >= ?", (since,)).fetchone()
    req_count = int(req_row[0] if req_row else 0) or 1  # avoid div by zero
    cost_row = conn.execute(
        "SELECT COALESCE(SUM(amount_jpy), 0) FROM cost_ledger WHERE incurred_at >= ?",
        (since,),
    ).fetchone()
    cost_jpy = int(cost_row[0] if cost_row else 0)
    return int(cost_jpy / req_count)


def _compute_agent_retention_d30(conn: sqlite3.Connection) -> float:
    """Fraction of api_keys active 30d ago that are still active today."""
    if not _table_exists(conn, "usage_events"):
        return 0.0
    now = datetime.now(UTC)
    d30_lo = (now - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
    d30_hi = (now - timedelta(days=29)).strftime("%Y-%m-%d %H:%M:%S")
    d0_lo = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    d30_active = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT key_hash FROM usage_events "
            "WHERE ts BETWEEN ? AND ? AND key_hash IS NOT NULL",
            (d30_lo, d30_hi),
        ).fetchall()
    }
    if not d30_active:
        return 0.0
    today_active = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT key_hash FROM usage_events WHERE ts >= ? AND key_hash IS NOT NULL",
            (d0_lo,),
        ).fetchall()
    }
    retained = d30_active & today_active
    return round(len(retained) / len(d30_active), 4)


def _compute_ttfp_seconds(conn: sqlite3.Connection) -> int:
    """Median seconds from api_keys.created_at to first usage event."""
    if not (_table_exists(conn, "usage_events") and _table_exists(conn, "api_keys")):
        return 0
    since = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """
        SELECT ak.key_hash, ak.created_at,
               (SELECT MIN(ts) FROM usage_events
                WHERE key_hash = ak.key_hash) AS first_use
        FROM api_keys ak
        WHERE ak.created_at >= ?
        """,
        (since,),
    ).fetchall()
    deltas: list[float] = []
    for r in rows:
        if not r["first_use"]:
            continue
        try:
            t0 = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(r["first_use"].replace("Z", "+00:00"))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=UTC)
            if t1.tzinfo is None:
                t1 = t1.replace(tzinfo=UTC)
            deltas.append((t1 - t0).total_seconds())
        except (ValueError, AttributeError):
            continue
    return int(statistics.median(deltas)) if deltas else 0


def _compute_spending_variance(conn: sqlite3.Connection) -> float:
    """p90/p50 ratio of req count per api_key over the last 7 days."""
    if not _table_exists(conn, "usage_events"):
        return 0.0
    since = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        """
        SELECT key_hash, COUNT(*) AS c
        FROM usage_events
        WHERE ts >= ? AND key_hash IS NOT NULL
        GROUP BY key_hash
        """,
        (since,),
    ).fetchall()
    counts = [int(r["c"]) for r in rows]
    if len(counts) < 5:
        return 0.0  # not enough data for stable percentiles
    counts.sort()
    p50 = counts[len(counts) // 2] or 1
    p90 = counts[int(len(counts) * 0.9)] or 1
    return round(p90 / p50, 2)


def _compute_ai_mention_share() -> float:
    """Read aeo_citation_bench weekly average if available; else 0.0."""
    bench_path = ANALYTICS / "aeo_citation_bench.json"
    if not bench_path.exists():
        return 0.0
    try:
        data = json.loads(bench_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return float(data.get("weekly_avg_cite_rate", 0.0))
        if isinstance(data, list) and data:
            recent = data[-7:]
            rates = [float(d.get("cite_rate", 0.0)) for d in recent if isinstance(d, dict)]
            if rates:
                return round(sum(rates) / len(rates), 4)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        pass
    return 0.0


def _compute_justification_strength(conn: sqlite3.Connection) -> int:
    """Programs schema has no ``description`` column — agents instead
    rely on ``primary_name`` (display name) + ``source_url`` (citation
    anchor) + ``source_mentions_json`` (proof-of-fact list) + ``aliases_json``
    (cross-naming). Score combines name length + source coverage on S+A.
    """
    if not _table_exists(conn, "programs"):
        return 0
    # S+A programs only — these are the high-value rows agents recommend
    row = conn.execute(
        """
        SELECT
          COALESCE(AVG(LENGTH(IFNULL(primary_name, ''))), 0) AS avg_name_len,
          COALESCE(AVG(CASE WHEN source_url IS NOT NULL AND source_url != ''
                            THEN 1 ELSE 0 END), 0) AS source_rate,
          COALESCE(AVG(CASE WHEN aliases_json IS NOT NULL AND aliases_json != ''
                            AND aliases_json != '[]'
                            THEN 1 ELSE 0 END), 0) AS alias_rate
        FROM programs
        WHERE tier IN ('S','A') AND excluded = 0
        """
    ).fetchone()
    if not row:
        return 0
    # 0-100 scale: name_len 0-30 -> 0-30, source_rate 0-1.0 -> 0-50,
    # alias_rate 0-1.0 -> 0-20.
    name_score = min(30, int((row["avg_name_len"] or 0) / 30 * 30))
    source_score = int((row["source_rate"] or 0) * 50)
    alias_score = int((row["alias_rate"] or 0) * 20)
    return name_score + source_score + alias_score


# ---------------------------------------------------------------------------
# Legacy KPI proxies (continuity with existing dashboards)
# ---------------------------------------------------------------------------


def _compute_mrr_jpy(conn: sqlite3.Connection) -> int:
    """Sum of metered usage_events × ¥3.30 over the last 30 days.

    Only ``metered=1`` rows count toward revenue — anon free-tier requests
    log to usage_events but with ``metered=0``.
    """
    if not _table_exists(conn, "usage_events"):
        return 0
    since = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        "SELECT COUNT(*) FROM usage_events WHERE ts >= ? AND metered = 1",
        (since,),
    ).fetchone()
    return int((row[0] if row else 0) * YEN_PER_REQ)


def _compute_arr_jpy(conn: sqlite3.Connection) -> int:
    return int(_compute_mrr_jpy(conn) * 12)


def _compute_churn_proxy(conn: sqlite3.Connection) -> float:
    """1 - D30 retention is a coarse churn proxy."""
    return round(1.0 - _compute_agent_retention_d30(conn), 4)


def _compute_ltv_cac_proxy(conn: sqlite3.Connection) -> float:
    """Organic-only ops -> CAC ~ 0. We surface LTV / max(CAC, 1) per memory
    `feedback_organic_only_no_ads`. With organic-only, CAC stays at ¥1
    sentinel so this stays comparable across days; the LTV component is the
    informative half (mean revenue per api_key over 30d × 12).
    """
    if not (_table_exists(conn, "usage_events") and _table_exists(conn, "api_keys")):
        return 0.0
    since = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        """
        SELECT COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT key_hash), 0) AS req_per_key
        FROM usage_events WHERE ts >= ? AND key_hash IS NOT NULL
        """,
        (since,),
    ).fetchone()
    req_per_key = float(row[0]) if row and row[0] is not None else 0.0
    ltv_jpy = req_per_key * YEN_PER_REQ * 12  # 1-year horizon
    return round(ltv_jpy / 1.0, 2)  # CAC sentinel = ¥1


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _write_jsonl(metrics: dict[str, Any]) -> None:
    ANALYTICS.mkdir(parents=True, exist_ok=True)
    with JSONL_OUT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(metrics, ensure_ascii=False) + "\n")


PUBLIC_SIDECAR_KEYS = (
    "captured_at",
    "arc_rows",
    "agent_retention_d30",
    "ttfp_seconds",
    "spending_variance_p90_p50",
    "ai_mention_share",
    "justification_strength",
    "anti_pattern_violations",
)


def _public_sidecar_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    public = {key: metrics.get(key) for key in PUBLIC_SIDECAR_KEYS if key in metrics}
    public["notes"] = "public-operations-summary"
    return public


def _write_sidecar(metrics: dict[str, Any]) -> None:
    SITE_STATUS.mkdir(parents=True, exist_ok=True)
    # Sidecar carries history of last 30 days for the static dashboard to
    # render sparklines. The public sidecar intentionally omits revenue,
    # cost, experiment, and customer-proxy metrics.
    history: list[dict[str, Any]] = []
    if SIDECAR.exists():
        try:
            existing = json.loads(SIDECAR.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                history = existing.get("history", [])
        except (json.JSONDecodeError, OSError):
            history = []
    public_metrics = _public_sidecar_metrics(metrics)
    history = [_public_sidecar_metrics(row) for row in history if isinstance(row, dict)]
    history.append(public_metrics)
    history = history[-30:]
    SIDECAR.write_text(
        json.dumps(
            {"generated_at": _now_iso(), "latest": public_metrics, "history": history},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute metrics + log only; do not append to JSONL or sidecar.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    conn = _open_db()
    metrics: dict[str, Any] = {
        "captured_at": _now_iso(),
        # 8 agent-economy KPIs
        "asr_24h_jpy": 0,
        "arc_rows": 0,
        "cost_to_serve_jpy": 0,
        "agent_retention_d30": 0.0,
        "ttfp_seconds": 0,
        "spending_variance_p90_p50": 0.0,
        "ai_mention_share": 0.0,
        "justification_strength": 0,
        # 4 legacy KPIs (proxies)
        "mrr_jpy": 0,
        "arr_jpy": 0,
        "churn_d30_proxy": 0.0,
        "ltv_cac_proxy": 0.0,
        # Bookkeeping
        "anti_pattern_violations": [],
        "notes": "wave42-monetization-guide-integration",
    }

    if conn is None:
        logger.warning("DB unavailable; all metrics zero")
    else:
        try:
            metrics["asr_24h_jpy"] = _compute_asr_jpy(conn, days=1)
            metrics["arc_rows"] = _compute_arc_rows(conn)
            metrics["cost_to_serve_jpy"] = _compute_cost_to_serve_jpy(conn)
            metrics["agent_retention_d30"] = _compute_agent_retention_d30(conn)
            metrics["ttfp_seconds"] = _compute_ttfp_seconds(conn)
            metrics["spending_variance_p90_p50"] = _compute_spending_variance(conn)
            metrics["ai_mention_share"] = _compute_ai_mention_share()
            metrics["justification_strength"] = _compute_justification_strength(conn)
            metrics["mrr_jpy"] = _compute_mrr_jpy(conn)
            metrics["arr_jpy"] = _compute_arr_jpy(conn)
            metrics["churn_d30_proxy"] = _compute_churn_proxy(conn)
            metrics["ltv_cac_proxy"] = _compute_ltv_cac_proxy(conn)
        finally:
            conn.close()

    # Anti-pattern guards (memory `feedback_agent_anti_patterns_10`).
    violations: list[str] = []
    # #6: Per-agent spending variance > 10 is an unusual-concentration signal.
    if metrics["spending_variance_p90_p50"] > 10.0:
        violations.append("spending_variance_high")
    # #8: Stale data rule. If justification_strength dropped below 30 we've
    # broken the "data hygiene" rule (description / source url coverage).
    if 0 < metrics["justification_strength"] < 30:
        violations.append("justification_strength_low")
    metrics["anti_pattern_violations"] = violations

    logger.info("monetization metrics: %s", json.dumps(metrics, ensure_ascii=False))

    if not args.dry_run:
        _write_jsonl(metrics)
        _write_sidecar(metrics)
        logger.info("wrote %s + %s", JSONL_OUT, SIDECAR)
    else:
        logger.info("[dry-run] skipping JSONL + sidecar write")

    return 0


if __name__ == "__main__":
    sys.exit(main())
