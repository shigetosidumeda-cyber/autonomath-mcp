#!/usr/bin/env python3
"""Daily confidence snapshot (P5-attribution / Bayesian Discovery+Use).

What it does:
  1. Reads the last 30 days of `query_log_v2` (PII-redacted upstream by
     INV-21 / A5) and `usage_events` from jpintel.db.
  2. Computes Bayesian Discovery (P(found_result|invoked)) and Use
     (P(returned_within_7d|first_invocation)) per tool, with Beta(1,1)
     prior, using `jpintel_mcp.analytics.bayesian`.
  3. Aggregates by 5-cohort audience bucket where available.
  4. Writes a JSON snapshot to `analytics/confidence_<YYYY-MM-DD>.json`
     so the public dashboard can plot a daily timeline.
  5. Emits one structured log line on completion.

Constraints:
  * No Anthropic / claude / SDK calls — pure SQL + numpy/scipy.
  * query_log_v2 carries `tool`, `result_bucket`, `api_key_hash`,
    `ts` (epoch seconds) — no PII; we never read raw query text.
  * Per-customer detail is NEVER written to the snapshot. Cohort
    granularity caps at the 5 P5-pitch audience buckets.

Usage:
    python scripts/cron/confidence_update.py            # writes today's snapshot
    python scripts/cron/confidence_update.py --dry-run  # compute + log only
    python scripts/cron/confidence_update.py --window-days 30
    python scripts/cron/confidence_update.py --out /tmp/conf.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.analytics.bayesian import (  # noqa: E402
    discovery_confidence,
    overall_confidence,
    use_confidence,
)
from jpintel_mcp.config import settings  # noqa: E402

logger = logging.getLogger("autonomath.cron.confidence_update")

DEFAULT_WINDOW_DAYS = 30


# ---------------------------------------------------------------------------
# DB readers — PII-safe (only structural columns are selected)
# ---------------------------------------------------------------------------


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {r[1] for r in rows}


def _load_query_log(
    conn: sqlite3.Connection, since_unix: float
) -> list[dict[str, Any]]:
    """Return query_log rows with the columns we need for Discovery.

    Falls back gracefully if `query_log_v2` is absent (fresh dev DBs):
    we return an empty list rather than raising. The cron is supposed
    to be safe to schedule before the table has any rows.
    """
    if not _table_exists(conn, "query_log_v2"):
        return []
    cols = _column_names(conn, "query_log_v2")
    select_cols = ["tool"]
    if "result_bucket" in cols:
        select_cols.append("result_bucket")
    if "result_count" in cols:
        select_cols.append("result_count")
    if "api_key_hash" in cols:
        select_cols.append("api_key_hash")
    if "ts" in cols:
        select_cols.append("ts")
    sql = (
        f"SELECT {', '.join(select_cols)} FROM query_log_v2 "  # noqa: S608
        f"WHERE ts >= ?"
    )
    rows: list[dict[str, Any]] = []
    for r in conn.execute(sql, (since_unix,)).fetchall():
        d = dict(r)
        rows.append(d)
    return rows


def _load_usage_events(
    conn: sqlite3.Connection, since_iso: str
) -> list[dict[str, Any]]:
    """Return usage_events rows tagged with a synthetic `tool` field.

    `usage_events.endpoint` is the short endpoint name (programs.search,
    enforcement.get, ...) — the same label space as query_log_v2.tool —
    so we map endpoint→tool here. ts is stored as ISO-8601; we convert
    to epoch seconds so the bayesian module can do simple arithmetic.
    """
    if not _table_exists(conn, "usage_events"):
        return []
    sql = (
        "SELECT key_hash, endpoint AS tool, ts FROM usage_events "
        "WHERE ts >= ? AND key_hash IS NOT NULL"
    )
    out: list[dict[str, Any]] = []
    for r in conn.execute(sql, (since_iso,)).fetchall():
        ts_s = r["ts"]
        try:
            if ts_s.endswith("Z"):
                ts_s = ts_s[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_s)
            ts_unix = dt.timestamp()
        except (AttributeError, ValueError):
            continue
        out.append(
            {
                "tool": r["tool"],
                "key_hash": r["key_hash"],
                "ts_unix": ts_unix,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Snapshot writer
# ---------------------------------------------------------------------------


def _build_snapshot(
    discovery: dict[str, Any],
    use: dict[str, Any],
    *,
    window_days: int,
    since_iso: str,
    until_iso: str,
) -> dict[str, Any]:
    overall = overall_confidence(discovery, use)
    # Re-shape per-tool rows into the dashboard's preferred form: one
    # array entry per tool with both Discovery and Use side-by-side.
    by_tool: dict[str, dict[str, Any]] = {}
    for r in discovery.get("per_tool") or []:
        by_tool[r["tool"]] = {
            "tool": r["tool"],
            "discovery": {
                "value": r["discovery"],
                "ci95": r["ci95"],
                "hits": r["hits"],
                "trials": r["trials"],
                "by_cohort": r.get("by_cohort", {}),
            },
        }
    for r in use.get("per_tool") or []:
        bag = by_tool.setdefault(
            r["tool"],
            {"tool": r["tool"], "discovery": None},
        )
        bag["use"] = {
            "value": r["use"],
            "ci95": r["ci95"],
            "hits": r["hits"],
            "trials": r["trials"],
            "by_cohort": r.get("by_cohort", {}),
        }
    per_tool_array = sorted(by_tool.values(), key=lambda x: x["tool"])
    return {
        "generated_at": (
            datetime.now(UTC).replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            )
        ),
        "window_days": window_days,
        "since": since_iso,
        "until": until_iso,
        "overall": overall,
        "discovery_overall": discovery.get("overall"),
        "use_overall": use.get("overall"),
        "per_tool": per_tool_array,
    }


def _resolve_db_path() -> Path:
    """Pick the right jpintel.db on the host.

    Settings.db_path is the canonical path (`./data/jpintel.db` in dev,
    `/data/jpintel.db` on Fly via JPINTEL_DB_PATH env). If neither
    exists we fall back to `./jpintel.db` at repo root because some
    early-stage volumes only have the bare DB file.
    """
    candidate = Path(settings.db_path)
    if candidate.is_file():
        return candidate
    fallback = _REPO / "jpintel.db"
    if fallback.is_file():
        return fallback
    return candidate  # let caller surface the FileNotFoundError


def _open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def run(
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    out_path: Path | None = None,
    db_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Compute and write a daily snapshot. Returns the snapshot dict."""
    db = db_path or _resolve_db_path()
    if not db.is_file():
        logger.warning("confidence_update_no_db path=%s", db)
        return {}
    until = datetime.now(UTC)
    since = until - timedelta(days=window_days)
    since_unix = since.timestamp()
    since_iso = since.replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    until_iso = until.replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )

    t0 = time.monotonic()
    with _open_db(db) as conn:
        ql = _load_query_log(conn, since_unix)
        ue = _load_usage_events(conn, since_iso)

    discovery = discovery_confidence(ql)
    use = use_confidence(ue)
    snapshot = _build_snapshot(
        discovery,
        use,
        window_days=window_days,
        since_iso=since_iso,
        until_iso=until_iso,
    )

    out_dir = _REPO / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_path or out_dir / f"confidence_{date.today().isoformat()}.json"

    if not dry_run:
        target.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    logger.info(
        json.dumps(
            {
                "event": "confidence_update_done",
                "dry_run": dry_run,
                "out": str(target),
                "query_log_rows": len(ql),
                "usage_events_rows": len(ue),
                "tools_seen": len(snapshot.get("per_tool") or []),
                "discovery_weighted": snapshot["overall"]["discovery_weighted"],
                "use_weighted": snapshot["overall"]["use_weighted"],
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
            },
            ensure_ascii=False,
        )
    )
    return snapshot


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help="Lookback window in days (default: %(default)s)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Override output path (defaults to analytics/confidence_<DATE>.json)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Override jpintel.db path",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + log only, do not write the snapshot file",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    snapshot = run(
        window_days=args.window_days,
        out_path=args.out,
        db_path=args.db,
        dry_run=args.dry_run,
    )
    if not snapshot:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
