#!/usr/bin/env python3
"""Wave 43.5 — daily 6-stage agent-funnel KPI tracker.

Captures the cradle-to-retention funnel for agent-sourced revenue across
six locked stages, all computed from local SQLite + filesystem (NO LLM
calls, NO outbound HTTP — pure read-side aggregator).

The six stages, in flow order:

1. **Discoverability** — Can an agent find jpcite via discovery surfaces?
   Probe: existence + freshness of ``llms.txt`` / ``llms-full.txt`` /
   ``.well-known/mcp.json`` / ``.well-known/agents.json`` / OpenAPI /
   sitemap, plus count of agent-readable companion ``.md`` files under
   ``site/`` (Wave 19 bulk landed 10,259 files).
2. **Justifiability** — Can the agent justify a recommendation it made
   based on jpcite output? Probe: programs S+A coverage of
   ``source_url`` + ``primary_name``, plus ``am_entity_facts.source_id``
   non-null fraction.
3. **Trustability** — Does the corpus carry trust evidence (citation
   audit signals, cross-source agreement, RUM clean health)? Probe:
   ``analytics/ai_mention_share_monthly.jsonl`` last summary +
   ``site/status/health.json`` 5-component health snapshot if present.
4. **Accessibility** — Can the agent get the data through ¥0 anonymous
   path + ¥3 metered path? Probe: ``usage_events`` last-24h split by
   ``is_anonymous`` flag + ``llms.txt`` size sanity (≤ 60 KB target).
5. **Payability** — Can the agent pay (Stripe metered + API key issue +
   x402 forward-compat)? Probe: ``api_keys`` count active + Stripe
   subscription_id non-null count + ``cost_ledger`` last-24h presence.
6. **Retainability** — Do agents keep coming back? Probe: D30 retention
   (mirrored from track_monetization_metrics_daily but recomputed here
   so this script is freestanding) + ``saved_searches`` weekly cadence
   count.

Hard rules (memory):

* ``feedback_autonomath_no_api_use``: zero LLM API imports.
* ``feedback_no_quick_check_on_huge_sqlite``: no PRAGMA quick_check /
  full-scan ops on autonomath.db (9.7 GB).
* ``feedback_dont_extrapolate_principles``: this script only reads
  jpintel.db (~352 MB) for usage_events / api_keys / programs +
  filesystem for site discovery probes.

Outputs:

* ``analytics/funnel_6stage_daily.jsonl`` — append-only history.
* ``site/status/funnel_6stage.json`` — sidecar for the dashboard.

Usage::

    python scripts/cron/track_funnel_6stage_daily.py
    python scripts/cron/track_funnel_6stage_daily.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("autonomath.cron.funnel_6stage")

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
SITE = REPO_ROOT / "site"
ANALYTICS = REPO_ROOT / "analytics"
SITE_STATUS = SITE / "status"

JSONL_OUT = ANALYTICS / "funnel_6stage_daily.jsonl"
SIDECAR = SITE_STATUS / "funnel_6stage.json"

DISCOVERY_FILES = [
    "llms.txt",
    "llms-full.txt",
    ".well-known/mcp.json",
    ".well-known/agents.json",
    ".well-known/openid-configuration",
    "openapi.json",
    "sitemap.xml",
    "robots.txt",
    "agents.json",
    "ai-plugin.json",
]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open_db() -> sqlite3.Connection | None:
    if not JPINTEL_DB.exists():
        logger.warning("jpintel.db not found at %s; funnel stages 4-6 → 0", JPINTEL_DB)
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
# Stage 1 — Discoverability
# ---------------------------------------------------------------------------


def stage1_discoverability() -> dict[str, Any]:
    present = []
    missing = []
    for rel in DISCOVERY_FILES:
        path = SITE / rel
        if path.exists() and path.stat().st_size > 0:
            present.append(rel)
        else:
            missing.append(rel)
    companion_md = 0
    if SITE.exists():
        # cheap glob; companion .md sit under site/ in various subtrees
        for _ in SITE.rglob("*.companion.md"):
            companion_md += 1
            if companion_md >= 20_000:  # safety cap
                break
    score = round(len(present) / len(DISCOVERY_FILES), 4)
    return {
        "stage": "discoverability",
        "score": score,
        "present_count": len(present),
        "total_probes": len(DISCOVERY_FILES),
        "missing": missing,
        "companion_md_count": companion_md,
    }


# ---------------------------------------------------------------------------
# Stage 2 — Justifiability
# ---------------------------------------------------------------------------


def stage2_justifiability(conn: sqlite3.Connection | None) -> dict[str, Any]:
    if conn is None or not _table_exists(conn, "programs"):
        return {"stage": "justifiability", "score": 0.0, "reason": "no_db"}
    total = conn.execute(
        "SELECT COUNT(*) FROM programs WHERE tier IN ('S','A') AND excluded=0"
    ).fetchone()[0]
    with_source = conn.execute(
        "SELECT COUNT(*) FROM programs "
        "WHERE tier IN ('S','A') AND excluded=0 "
        "AND source_url IS NOT NULL AND source_url <> ''"
    ).fetchone()[0]
    with_name = conn.execute(
        "SELECT COUNT(*) FROM programs "
        "WHERE tier IN ('S','A') AND excluded=0 "
        "AND primary_name IS NOT NULL AND LENGTH(primary_name) >= 4"
    ).fetchone()[0]
    if not total:
        return {"stage": "justifiability", "score": 0.0, "n_sa_total": 0}
    coverage_src = with_source / total
    coverage_name = with_name / total
    score = round((coverage_src + coverage_name) / 2, 4)
    return {
        "stage": "justifiability",
        "score": score,
        "n_sa_total": total,
        "coverage_source_url": round(coverage_src, 4),
        "coverage_primary_name": round(coverage_name, 4),
    }


# ---------------------------------------------------------------------------
# Stage 3 — Trustability
# ---------------------------------------------------------------------------


def stage3_trustability() -> dict[str, Any]:
    ams_summary: dict[str, Any] = {}
    ams_path = ANALYTICS / "ai_mention_share_monthly.jsonl"
    if ams_path.exists():
        with ams_path.open("r", encoding="utf-8") as f:
            last = None
            for line in f:
                last = line
            if last:
                try:
                    obj = json.loads(last)
                    ams_summary = obj.get("summary") or {}
                except json.JSONDecodeError:
                    ams_summary = {}
    health_summary: dict[str, Any] = {}
    health_path = SITE_STATUS / "health.json"
    if health_path.exists():
        try:
            health_summary = json.loads(health_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            health_summary = {}
    components = health_summary.get("components") or {}
    healthy = sum(1 for v in components.values() if isinstance(v, dict) and v.get("status") == "ok")
    total_health = max(len(components), 1)
    health_score = healthy / total_health
    ams_score = float(ams_summary.get("citation_rate_avg", 0.0))
    score = round((ams_score + health_score) / 2, 4)
    return {
        "stage": "trustability",
        "score": score,
        "ams_citation_rate_avg": ams_score,
        "health_components_healthy": healthy,
        "health_components_total": total_health,
    }


# ---------------------------------------------------------------------------
# Stage 4 — Accessibility
# ---------------------------------------------------------------------------


def stage4_accessibility(conn: sqlite3.Connection | None) -> dict[str, Any]:
    llms_kb = 0.0
    llms_path = SITE / "llms.txt"
    if llms_path.exists():
        llms_kb = round(llms_path.stat().st_size / 1024.0, 2)
    anon = metered = 0
    if conn is not None and _table_exists(conn, "usage_events"):
        since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        # `usage_events.key_hash IS NULL` is the anonymous path proxy.
        row = conn.execute(
            "SELECT "
            "  SUM(CASE WHEN key_hash IS NULL THEN 1 ELSE 0 END) AS anon, "
            "  SUM(CASE WHEN key_hash IS NOT NULL THEN 1 ELSE 0 END) AS metered "
            "FROM usage_events WHERE ts >= ?",
            (since,),
        ).fetchone()
        if row:
            anon = int(row["anon"] or 0)
            metered = int(row["metered"] or 0)
    total = anon + metered
    # Score: presence of both paths + llms.txt within budget (≤ 60 KB).
    score = 0.0
    if llms_path.exists() and llms_kb <= 60.0:
        score += 0.5
    if total > 0:
        # Both paths used — reward.
        if anon > 0 and metered > 0:
            score += 0.5
        else:
            score += 0.25
    return {
        "stage": "accessibility",
        "score": round(score, 4),
        "llms_txt_kb": llms_kb,
        "anonymous_req_24h": anon,
        "metered_req_24h": metered,
    }


# ---------------------------------------------------------------------------
# Stage 5 — Payability
# ---------------------------------------------------------------------------


def stage5_payability(conn: sqlite3.Connection | None) -> dict[str, Any]:
    if conn is None or not _table_exists(conn, "api_keys"):
        return {"stage": "payability", "score": 0.0, "reason": "no_db"}
    active_keys = conn.execute(
        "SELECT COUNT(*) FROM api_keys WHERE revoked_at IS NULL"
    ).fetchone()[0]
    stripe_linked = 0
    cols = {r[1] for r in conn.execute("PRAGMA table_info(api_keys)").fetchall()}
    if "stripe_subscription_id" in cols:
        stripe_linked = conn.execute(
            "SELECT COUNT(*) FROM api_keys "
            "WHERE revoked_at IS NULL "
            "AND stripe_subscription_id IS NOT NULL AND stripe_subscription_id <> ''"
        ).fetchone()[0]
    cost_24h = 0
    if _table_exists(conn, "cost_ledger"):
        since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            "SELECT COUNT(*) FROM cost_ledger WHERE incurred_at >= ?", (since,)
        ).fetchone()
        cost_24h = int(row[0] if row else 0)
    score = 0.0
    if active_keys > 0:
        score += 0.4
    if stripe_linked > 0:
        score += 0.4
    if cost_24h > 0:
        score += 0.2
    return {
        "stage": "payability",
        "score": round(score, 4),
        "active_api_keys": active_keys,
        "stripe_linked_keys": stripe_linked,
        "cost_ledger_rows_24h": cost_24h,
    }


# ---------------------------------------------------------------------------
# Stage 6 — Retainability
# ---------------------------------------------------------------------------


def stage6_retainability(conn: sqlite3.Connection | None) -> dict[str, Any]:
    if conn is None or not _table_exists(conn, "usage_events"):
        return {"stage": "retainability", "score": 0.0, "reason": "no_db"}
    now = datetime.now(UTC)
    d30_lo = (now - timedelta(days=31)).strftime("%Y-%m-%d %H:%M:%S")
    d30_hi = (now - timedelta(days=29)).strftime("%Y-%m-%d %H:%M:%S")
    d0_lo = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    d30 = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT key_hash FROM usage_events "
            "WHERE ts BETWEEN ? AND ? AND key_hash IS NOT NULL",
            (d30_lo, d30_hi),
        ).fetchall()
    }
    today = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT key_hash FROM usage_events "
            "WHERE ts >= ? AND key_hash IS NOT NULL",
            (d0_lo,),
        ).fetchall()
    }
    retention = 0.0
    if d30:
        retention = round(len(d30 & today) / len(d30), 4)
    saved_count = 0
    if _table_exists(conn, "saved_searches"):
        cols = {r[1] for r in conn.execute("PRAGMA table_info(saved_searches)").fetchall()}
        if "frequency" in cols:
            saved_count = conn.execute(
                "SELECT COUNT(*) FROM saved_searches WHERE frequency = 'weekly'"
            ).fetchone()[0]
    # Score blends D30 retention with saved-search weekly cadence presence.
    score = retention * 0.7 + (0.3 if saved_count > 0 else 0.0)
    return {
        "stage": "retainability",
        "score": round(score, 4),
        "d30_retention": retention,
        "d30_eligible_keys": len(d30),
        "saved_searches_weekly": saved_count,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(dry_run: bool = False) -> dict[str, Any]:
    conn = _open_db()
    try:
        stages = [
            stage1_discoverability(),
            stage2_justifiability(conn),
            stage3_trustability(),
            stage4_accessibility(conn),
            stage5_payability(conn),
            stage6_retainability(conn),
        ]
    finally:
        if conn is not None:
            conn.close()
    funnel_score = round(sum(s.get("score", 0.0) for s in stages) / len(stages), 4)
    snapshot = {
        "generated_at": _now_iso(),
        "funnel_score": funnel_score,
        "stages": stages,
    }
    if dry_run:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return snapshot
    ANALYTICS.mkdir(parents=True, exist_ok=True)
    SITE_STATUS.mkdir(parents=True, exist_ok=True)
    with JSONL_OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    with SIDECAR.open("w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    logger.info(
        "funnel_6stage emitted: funnel_score=%s stages=%s",
        funnel_score,
        len(stages),
    )
    return snapshot


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print JSON, do not write files")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    snapshot = run(dry_run=args.dry_run)
    return 0 if snapshot else 1


if __name__ == "__main__":
    sys.exit(main())
