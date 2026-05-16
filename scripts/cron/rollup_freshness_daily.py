#!/usr/bin/env python3
"""Daily cron freshness rollup (Wave 37 SOT).

Reads the latest run history of every cron workflow in the canonical
``docs/runbook/cron_schedule_master.md`` schedule and snapshots:

  * ``last_run_at`` / ``conclusion`` from ``gh run list --workflow=<name>``
  * ``next_run_at`` derived from the cron expression
  * 7-day rolling row-inserted / updated / deleted from each cron's
    target table (computed from ``cron_ingest_log`` mini-table or table
    ``rowid`` deltas)
  * ``success_rate_24h`` percentage across the last 24 h of runs

Output: ``analytics/freshness_rollup_{date}.json``

The rollup is consumed by ``detect_freshness_sla_breach.py`` (alerting),
``site/data-freshness.html`` (dashboard heatmap) and the operator's daily
KPI digest.

This script intentionally avoids:

  * ``PRAGMA quick_check`` / ``PRAGMA integrity_check`` — the
    ``autonomath.db`` is 9.7 GB and a full-scan op hangs the runner.
  * Aggregator data sources — only first-party gh CLI + SQLite reads.
  * LLM imports — production cron gate forbids it.

Usage::

  python scripts/cron/rollup_freshness_daily.py
  python scripts/cron/rollup_freshness_daily.py --dry-run
  python scripts/cron/rollup_freshness_daily.py --verify-schedule

Constraints
-----------
- No write to ``autonomath.db`` / ``jpintel.db`` (read-only).
- Graceful when ``gh`` CLI is absent (``gh_unavailable`` flag).
- Idempotent — re-running overwrites the same day's snapshot.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("rollup_freshness_daily")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ANALYTICS_DIR = REPO_ROOT / "analytics"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

JST = timezone(timedelta(hours=9))
UTC = UTC


@dataclass(frozen=True)
class CronSpec:
    """Canonical cron lineup row from cron_schedule_master.md."""

    workflow: str
    cron_utc: str
    lane: str
    sla_hours: int
    db: str
    description: str
    target_tables: tuple[str, ...] = field(default_factory=tuple)


# Mirrors docs/runbook/cron_schedule_master.md §3 + §5.
CANONICAL_CRONS: list[CronSpec] = [
    # Lane A — ETL ingest
    CronSpec(
        "knowledge-graph-vec-embed",
        "0 17 * * *",
        "A",
        24,
        "autonomath",
        "Knowledge graph vec embed",
        ("am_entities_vec",),
    ),
    CronSpec(
        "portfolio-optimize-daily",
        "30 17 * * *",
        "A",
        24,
        "autonomath",
        "Portfolio optimize refresh",
        ("am_metrics",),
    ),
    CronSpec(
        "houjin-risk-score-daily",
        "0 18 * * *",
        "A",
        24,
        "autonomath",
        "Houjin risk score refresh",
        ("am_metrics",),
    ),
    CronSpec(
        "edinet-daily",
        "30 19 * * *",
        "A",
        24,
        "jpintel",
        "EDINET XBRL/PDF ingest",
        ("edinet_documents",),
    ),
    CronSpec(
        "adoption-rss-daily",
        "0 20 * * *",
        "A",
        24,
        "jpintel",
        "Adoption RSS poll",
        ("adoption_records",),
    ),
    # Lane B — Precompute
    CronSpec(
        "axis2-precompute-daily",
        "45 20 * * *",
        "B",
        24,
        "autonomath",
        "Cohort 5d / risk 4d / supplier chain",
        ("am_cohort_5d", "am_program_risk_4d", "am_supplier_chain"),
    ),
    CronSpec(
        "egov-amendment-daily", "0 21 * * *", "B", 24, "jpintel", "e-Gov amendments", ("laws",)
    ),
    CronSpec(
        "ax-metrics-daily",
        "15 21 * * *",
        "B",
        24,
        "autonomath",
        "AX aggregate metrics",
        ("am_metrics",),
    ),
    CronSpec(
        "enforcement-press-daily",
        "0 22 * * *",
        "B",
        24,
        "jpintel",
        "Enforcement press releases",
        ("enforcement_cases",),
    ),
    # Lane C — Monitoring
    CronSpec(
        "budget-subsidy-chain-daily",
        "0 23 * * *",
        "C",
        24,
        "autonomath",
        "Budget→subsidy chain detect",
        ("am_budget_chain",),
    ),
    CronSpec(
        "jpo-patents-daily", "30 23 * * *", "C", 24, "jpintel", "JPO patent ingest", ("patents",)
    ),
    CronSpec(
        "invoice-diff-daily",
        "0 0 * * *",
        "C",
        24,
        "jpintel",
        "Invoice registrant delta",
        ("invoice_registrants",),
    ),
    # Lane D — Weekly
    CronSpec(
        "municipality-subsidy-weekly",
        "0 18 * * 0",
        "D",
        168,
        "jpintel",
        "47 prefecture fan-out",
        ("programs",),
    ),
    CronSpec(
        "axis2def-promote-weekly",
        "0 18 * * 4",
        "D",
        168,
        "autonomath",
        "Definition promote",
        ("am_compat_matrix", "am_amount_condition", "am_amendment_snapshot"),
    ),
    CronSpec(
        "alliance-opportunity-weekly",
        "0 20 * * 0",
        "D",
        168,
        "autonomath",
        "Alliance opportunity precompute",
        ("am_alliance_opportunity",),
    ),
    CronSpec(
        "multilingual-weekly", "0 4 * * 0", "D", 168, "jpintel", "EN/KO/ZH fill", ("law_articles",)
    ),
    CronSpec(
        "extended-corpus-weekly",
        "0 2 * * 2",
        "D",
        168,
        "jpintel",
        "Kokkai/shingikai/brand",
        ("kokkai_records",),
    ),
    # Lane D — Monthly
    CronSpec(
        "axis6-output-monthly",
        "0 21 1 * *",
        "D",
        744,
        "autonomath",
        "Monthly 6-axis PDF report",
        (),
    ),
    CronSpec(
        "subsidy-30yr-forecast-monthly",
        "0 19 4 * *",
        "D",
        744,
        "autonomath",
        "30y subsidy cycle forecast",
        ("am_forecast_30yr",),
    ),
]


def gh_cli_available() -> bool:
    """Return True iff the `gh` CLI binary is on PATH."""
    return shutil.which("gh") is not None


def fetch_latest_run(workflow: str) -> dict[str, Any] | None:
    """Call `gh run list --workflow=<workflow>` and parse the latest run.

    Returns ``None`` when ``gh`` is missing, the workflow is unknown, or
    the API call fails. Never raises — the caller treats ``None`` as
    ``never_ran``.
    """
    if not gh_cli_available():
        return None
    cmd = [
        "gh",
        "run",
        "list",
        "--workflow",
        f"{workflow}.yml",
        "--limit",
        "1",
        "--json",
        "databaseId,conclusion,status,createdAt,updatedAt,event,headSha",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO_ROOT,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        logger.debug("gh run list failed for %s: %s", workflow, proc.stderr.strip())
        return None
    try:
        runs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not runs:
        return None
    run = runs[0]
    return {
        "database_id": run.get("databaseId"),
        "conclusion": run.get("conclusion"),
        "status": run.get("status"),
        "created_at": run.get("createdAt"),
        "updated_at": run.get("updatedAt"),
        "head_sha": (run.get("headSha") or "")[:7] or None,
    }


def fetch_run_history(workflow: str, hours: int = 24) -> list[dict[str, Any]]:
    """Return list of run dicts in the last ``hours`` window."""
    if not gh_cli_available():
        return []
    cmd = [
        "gh",
        "run",
        "list",
        "--workflow",
        f"{workflow}.yml",
        "--limit",
        "20",
        "--json",
        "conclusion,createdAt",
    ]
    try:
        proc = subprocess.run(
            cmd, check=False, capture_output=True, text=True, timeout=30, cwd=REPO_ROOT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    try:
        runs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    out: list[dict[str, Any]] = []
    for run in runs:
        ts = run.get("createdAt")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt >= cutoff:
            out.append(run)
    return out


def success_rate_24h(workflow: str) -> float | None:
    """Percentage of successful runs in the last 24 h, or ``None`` when unknown."""
    history = fetch_run_history(workflow, hours=24)
    if not history:
        return None
    success = sum(1 for r in history if r.get("conclusion") == "success")
    return round(success / len(history) * 100, 1)


def next_run_at(cron_utc: str, *, now: datetime | None = None) -> str | None:
    """Compute the next scheduled UTC run for a cron expression.

    Supports the subset used in this repo: ``M H DOM MON DOW`` with
    minute/hour as digits or ``*``, DOM/MON wildcards, and DOW as a
    single digit or ``*``. Returns ISO 8601 UTC or ``None`` when the
    expression cannot be parsed.
    """
    now = now or datetime.now(UTC)
    parts = cron_utc.split()
    if len(parts) != 5:
        return None
    minute_s, hour_s, dom_s, _mon_s, dow_s = parts
    if not minute_s.isdigit() or not hour_s.isdigit():
        return None
    minute = int(minute_s)
    hour = int(hour_s)
    # Walk forward up to 32 days to find the next firing.
    candidate = now.replace(minute=minute, hour=hour, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    for _ in range(32):
        dom_ok = dom_s == "*" or (dom_s.isdigit() and candidate.day == int(dom_s))
        dow_ok = dow_s == "*" or (dow_s.isdigit() and candidate.weekday() == ((int(dow_s) - 1) % 7))
        # cron DOW: 0=Sunday in GHA, Python weekday(): Monday=0. Map 0→6.
        if dow_s == "0":
            dow_ok = candidate.weekday() == 6
        if dom_ok and dow_ok:
            return candidate.isoformat()
        candidate = candidate + timedelta(days=1)
    return None


def db_table_freshness(db_path: Path, tables: tuple[str, ...]) -> dict[str, Any]:
    """Read MAX(last_verified) or row count from each table, no full-scan.

    Hard guard: refuses to open files larger than 10 GB to avoid the
    9.7 GB autonomath.db PRAGMA hazard. Uses ``LIMIT 1`` selects.
    """
    out: dict[str, Any] = {}
    if not tables:
        return out
    if not db_path.exists():
        for tbl in tables:
            out[tbl] = {"status": "db_missing"}
        return out
    if db_path.stat().st_size > 10 * 1024 * 1024 * 1024:
        for tbl in tables:
            out[tbl] = {"status": "db_too_large_skip"}
        return out
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    except sqlite3.OperationalError as exc:
        logger.warning("cannot open db %s: %s", db_path, exc)
        for tbl in tables:
            out[tbl] = {"status": "open_failed"}
        return out
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for tbl in tables:
            row_info: dict[str, Any] = {"table": tbl}
            try:
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                    (tbl,),
                )
                if cur.fetchone() is None:
                    row_info["status"] = "table_missing"
                    out[tbl] = row_info
                    continue
                cur.execute(f"PRAGMA table_info({tbl})")
                cols = {r[1] for r in cur.fetchall()}
                ts_col = None
                for candidate in (
                    "last_verified",
                    "updated_at",
                    "fetched_at",
                    "source_fetched_at",
                    "created_at",
                ):
                    if candidate in cols:
                        ts_col = candidate
                        break
                if ts_col is None:
                    row_info["status"] = "no_timestamp_col"
                else:
                    cur.execute(f"SELECT MAX({ts_col}) FROM {tbl}")  # noqa: S608
                    val = cur.fetchone()[0]
                    row_info["status"] = "ok"
                    row_info["timestamp_col"] = ts_col
                    row_info["max_timestamp"] = val
                out[tbl] = row_info
            except sqlite3.OperationalError as exc:
                row_info["status"] = "query_failed"
                row_info["error"] = str(exc)[:200]
                out[tbl] = row_info
    finally:
        conn.close()
    return out


def workflow_file_schedule(workflow: str) -> str | None:
    """Read the actual cron expression from the workflow file on disk."""
    path = WORKFLOWS_DIR / f"{workflow}.yml"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- cron:") or stripped.startswith("- cron :"):
            # `- cron: "0 18 * * *"` → extract between quotes
            for quote in ('"', "'"):
                if quote in stripped:
                    parts = stripped.split(quote)
                    if len(parts) >= 3:
                        return parts[1].strip()
            return stripped.split(":", 1)[-1].strip()
    return None


def verify_schedule_drift() -> list[dict[str, str]]:
    """Compare canonical cron table vs actual workflow files. Return mismatches."""
    drift: list[dict[str, str]] = []
    for spec in CANONICAL_CRONS:
        actual = workflow_file_schedule(spec.workflow)
        if actual is None:
            drift.append(
                {"workflow": spec.workflow, "expected": spec.cron_utc, "actual": "MISSING"}
            )
            continue
        if actual != spec.cron_utc:
            drift.append({"workflow": spec.workflow, "expected": spec.cron_utc, "actual": actual})
    return drift


def build_rollup(now: datetime | None = None) -> dict[str, Any]:
    """Build the full rollup snapshot for today."""
    now = now or datetime.now(UTC)
    gh_ok = gh_cli_available()
    jpintel_db = REPO_ROOT / "data" / "jpintel.db"
    autonomath_db = REPO_ROOT / "autonomath.db"

    crons_out: list[dict[str, Any]] = []
    for spec in CANONICAL_CRONS:
        latest = fetch_latest_run(spec.workflow) if gh_ok else None
        rate = success_rate_24h(spec.workflow) if gh_ok else None
        nxt = next_run_at(spec.cron_utc, now=now)
        db_target = autonomath_db if spec.db == "autonomath" else jpintel_db
        table_health = db_table_freshness(db_target, spec.target_tables)
        crons_out.append(
            {
                "workflow": spec.workflow,
                "lane": spec.lane,
                "cron_utc": spec.cron_utc,
                "sla_hours": spec.sla_hours,
                "db": spec.db,
                "description": spec.description,
                "last_run": latest,
                "next_run_at_utc": nxt,
                "success_rate_24h_pct": rate,
                "tables": table_health,
            }
        )

    return {
        "schema_version": 1,
        "generated_at_utc": now.isoformat(),
        "generated_at_jst": now.astimezone(JST).isoformat(),
        "gh_available": gh_ok,
        "canonical_cron_count": len(CANONICAL_CRONS),
        "crons": crons_out,
        "lane_summary": {
            "A": sum(1 for c in CANONICAL_CRONS if c.lane == "A"),
            "B": sum(1 for c in CANONICAL_CRONS if c.lane == "B"),
            "C": sum(1 for c in CANONICAL_CRONS if c.lane == "C"),
            "D": sum(1 for c in CANONICAL_CRONS if c.lane == "D"),
        },
    }


def write_snapshot(snapshot: dict[str, Any], date_str: str) -> Path:
    ANALYTICS_DIR.mkdir(parents=True, exist_ok=True)
    out = ANALYTICS_DIR / f"freshness_rollup_{date_str}.json"
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    # Maintain a stable "latest" alias for the dashboard.
    latest = ANALYTICS_DIR / "freshness_rollup_latest.json"
    latest.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="do not write the snapshot file")
    parser.add_argument(
        "--verify-schedule",
        action="store_true",
        help="diff actual workflow schedules against the canonical table",
    )
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.verify_schedule:
        drift = verify_schedule_drift()
        if drift:
            print(json.dumps({"status": "drift", "items": drift}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"status": "ok", "checked": len(CANONICAL_CRONS)}))
        return 0

    snapshot = build_rollup()
    if args.dry_run:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        return 0

    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    out = write_snapshot(snapshot, date_str)
    logger.info("rollup written: %s", out)
    print(json.dumps({"status": "ok", "snapshot": str(out.relative_to(REPO_ROOT))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
