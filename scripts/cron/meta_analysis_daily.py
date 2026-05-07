#!/usr/bin/env python3
"""Daily meta-analysis rollup over Wave 22+23 materialized views.

What this does
--------------
Walks the 13 W22 + W23 materialized aggregation tables, captures
``(row_count, latest_timestamp)`` for each, diffs against yesterday's
snapshot, and emits a single 1-page markdown health report under
``tools/offline/_inbox/_meta_analysis/{YYYY-MM-DD}.md``.

This is a **pure SQL aggregation + markdown gen** cron — no LLM API
call (CLAUDE.md + ``feedback_autonomath_no_api_use``), pure SQLite +
standard library, same posture as the other ``scripts/cron/*.py``
precompute scripts. Optional Slack post is gated on
``$SLACK_WEBHOOK_OPS`` and falls back silently when the secret is not
configured.

Tables monitored
----------------
W22 (8 tables, all confirmed live on autonomath.db):

* ``am_5hop_graph`` (W22-2) — 5-hop walk index
* ``am_entity_appearance_count`` (W22-3) — per-houjin appearance rollup
* ``am_temporal_correlation`` (W22-4) — pre/post 30/90 day amendment delta
* ``am_geo_industry_density`` (W22-5) — pref × jsic density score
* ``am_funding_stack_empirical`` (W22-6) — co-adoption pair empirics
* ``am_adopted_company_features`` (W22-7) — per-houjin adoption features
* ``am_entity_density_score`` (W22-9) — per-entity density rank
* ``am_data_quality_snapshot`` (W16/W22-10) — data_quality cached rollup

W23 (5 tables, optional — script tolerates ``no such table`` and
records ``status=missing`` so the report stays a complete contract):

* ``am_id_bridge`` (W23-3)
* ``am_adoption_trend_monthly`` (W23-5)
* ``am_enforcement_anomaly`` (W23-6)
* ``am_entity_pagerank`` (W23-7)
* ``am_citation_network`` (W23-8)

Each table has a different timestamp column name (computed_at /
last_updated / generated_at / snapshot_at). ``_TABLES`` below pins the
canonical column per table; missing column → ``last_ts=null`` and the
report flags ``no_ts`` in the table-level note.

Delta computation
-----------------
Loads ``{date-1}.json`` (state file written next to the markdown) and
diffs row counts. First run lands a baseline JSON with delta=0 and a
``baseline=true`` flag.

Invocation
----------
::

    python scripts/cron/meta_analysis_daily.py
    python scripts/cron/meta_analysis_daily.py --am-db /path/to/autonomath.db
    python scripts/cron/meta_analysis_daily.py --out-dir tools/offline/_inbox/_meta_analysis
    python scripts/cron/meta_analysis_daily.py --slack-webhook $SLACK_WEBHOOK_OPS
    python scripts/cron/meta_analysis_daily.py --dry-run

Schedule
--------
``.github/workflows/meta-analysis-daily.yml`` runs at 06:00 JST
(21:00 UTC).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

logger = logging.getLogger("autonomath.cron.meta_analysis_daily")


# Pinned (table, ts_column, wave) tuples. Order = display order in the
# markdown report. ts_column=None means the table has no last-updated
# column and we record only row_count + status.
_TABLES: list[tuple[str, str | None, str]] = [
    # W22 ------------------------------------------------------------
    ("am_5hop_graph", None, "W22-2"),
    ("am_entity_appearance_count", "computed_at", "W22-3"),
    ("am_temporal_correlation", "computed_at", "W22-4"),
    ("am_geo_industry_density", "last_updated", "W22-5"),
    ("am_funding_stack_empirical", "generated_at", "W22-6"),
    ("am_adopted_company_features", "computed_at", "W22-7"),
    ("am_entity_density_score", "last_updated", "W22-9"),
    ("am_data_quality_snapshot", "snapshot_at", "W16/W22-10"),
    # W23 (optional — tolerated absent; pin actual schema columns) ---
    ("am_id_bridge", "created_at", "W23-3"),
    ("am_adoption_trend_monthly", "computed_at", "W23-5"),
    ("am_enforcement_anomaly", "last_updated", "W23-6"),
    ("am_entity_pagerank", "last_updated", "W23-7"),
    ("am_citation_network", "computed_at", "W23-8"),
]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        for row in conn.execute(f"PRAGMA table_info({table})"):
            # PRAGMA returns: cid, name, type, notnull, dflt_value, pk
            if str(row[1]) == column:
                return True
    except sqlite3.OperationalError:
        return False
    return False


def _gather_one(conn: sqlite3.Connection, table: str, ts_column: str | None) -> dict[str, Any]:
    """Return a stat dict for one mat view.

    Returned shape::

        {
            "table": ...,
            "exists": bool,
            "row_count": int | None,
            "last_ts": str | None,
            "ts_column": str | None,
            "status": "ok" | "missing" | "no_ts" | "error",
            "error": str | None,
        }
    """
    out: dict[str, Any] = {
        "table": table,
        "exists": False,
        "row_count": None,
        "last_ts": None,
        "ts_column": ts_column,
        "status": "missing",
        "error": None,
    }
    if not _table_exists(conn, table):
        return out
    out["exists"] = True
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        out["row_count"] = int(row[0]) if row else 0
    except sqlite3.OperationalError as exc:
        out["status"] = "error"
        out["error"] = str(exc)
        return out

    if ts_column is None:
        out["status"] = "no_ts"
        return out

    if not _column_exists(conn, table, ts_column):
        out["status"] = "no_ts"
        out["error"] = f"column {ts_column!r} not present"
        return out

    try:
        row = conn.execute(f"SELECT MAX({ts_column}) FROM {table}").fetchone()
        out["last_ts"] = str(row[0]) if row and row[0] is not None else None
    except sqlite3.OperationalError as exc:
        out["status"] = "error"
        out["error"] = str(exc)
        return out

    out["status"] = "ok"
    return out


def _gather_all(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    stats: list[dict[str, Any]] = []
    for name, ts_col, wave in _TABLES:
        s = _gather_one(conn, name, ts_col)
        s["wave"] = wave
        stats.append(s)
    return stats


def _load_yesterday(out_dir: Path, today: date) -> dict[str, dict[str, Any]] | None:
    yest = (today - timedelta(days=1)).isoformat()
    path = out_dir / f"{yest}.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("could not parse yesterday snapshot %s: %s", path, exc)
        return None
    indexed: dict[str, dict[str, Any]] = {}
    for entry in raw.get("tables", []):
        name = entry.get("table")
        if name:
            indexed[str(name)] = entry
    return indexed


def _annotate_deltas(
    today_stats: list[dict[str, Any]],
    yesterday_indexed: dict[str, dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Annotate today's stats with row_count delta vs. yesterday.

    Returns ``(annotated, baseline)`` where ``baseline=True`` if there
    was no prior snapshot.
    """
    baseline = yesterday_indexed is None
    for s in today_stats:
        prior = (yesterday_indexed or {}).get(s["table"])
        if prior is None or prior.get("row_count") is None:
            s["row_count_delta"] = None
            s["row_count_prior"] = None
            continue
        prior_count = int(prior["row_count"])
        cur = s["row_count"] if s["row_count"] is not None else 0
        s["row_count_prior"] = prior_count
        s["row_count_delta"] = (cur - prior_count) if s["row_count"] is not None else None
    return today_stats, baseline


def _summary_metrics(stats: list[dict[str, Any]]) -> dict[str, Any]:
    n_total = len(stats)
    n_ok = sum(1 for s in stats if s["status"] == "ok")
    n_no_ts = sum(1 for s in stats if s["status"] == "no_ts")
    n_missing = sum(1 for s in stats if s["status"] == "missing")
    n_error = sum(1 for s in stats if s["status"] == "error")
    rows_total = sum(int(s["row_count"] or 0) for s in stats if s["exists"])
    delta_total = sum(int(s.get("row_count_delta") or 0) for s in stats if s.get("row_count_delta"))
    return {
        "total": n_total,
        "ok": n_ok,
        "no_ts": n_no_ts,
        "missing": n_missing,
        "error": n_error,
        "rows_total": rows_total,
        "delta_total": delta_total,
    }


def _fmt_int(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n:,}"


def _fmt_delta(d: int | None) -> str:
    if d is None:
        return "—"
    if d == 0:
        return "0"
    sign = "+" if d > 0 else ""
    return f"{sign}{d:,}"


def _render_markdown(
    today: date,
    am_db: Path,
    stats: list[dict[str, Any]],
    metrics: dict[str, Any],
    baseline: bool,
) -> str:
    lines: list[str] = []
    lines.append(f"# meta_analysis_daily — {today.isoformat()}")
    lines.append("")
    lines.append(
        f"_Source DB:_ `{am_db}`  ·  _generated:_ "
        f"{datetime.now(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')}"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"- tables monitored: **{metrics['total']}** "
        f"(ok={metrics['ok']}, no_ts={metrics['no_ts']}, "
        f"missing={metrics['missing']}, error={metrics['error']})"
    )
    lines.append(f"- total rows across mat views: **{_fmt_int(metrics['rows_total'])}**")
    if baseline:
        lines.append("- delta vs. yesterday: **baseline (no prior snapshot)**")
    else:
        lines.append(
            f"- delta vs. yesterday: **{_fmt_delta(metrics['delta_total'])}** "
            "(net rows added across all tables)"
        )
    lines.append("")
    lines.append("## Per-table status")
    lines.append("")
    lines.append("| Wave | Table | Rows | Δ vs. yesterday | Last updated | Status | Note |")
    lines.append("|------|-------|-----:|----------------:|--------------|--------|------|")
    for s in stats:
        wave = s.get("wave", "")
        table = f"`{s['table']}`"
        rows = _fmt_int(s["row_count"])
        delta = _fmt_delta(s.get("row_count_delta"))
        last_ts = s["last_ts"] or "—"
        status = s["status"]
        note = ""
        if status == "missing":
            note = "table not present (W23 pending or rollback)"
        elif status == "no_ts":
            note = (
                f"no timestamp column ({s['ts_column']})"
                if s.get("ts_column") and s.get("error")
                else "no timestamp column declared"
            )
        elif status == "error":
            note = (s.get("error") or "")[:80]
        lines.append(f"| {wave} | {table} | {rows} | {delta} | {last_ts} | {status} | {note} |")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- This page is computed daily by "
        "`scripts/cron/meta_analysis_daily.py` (cron schedule: "
        "06:00 JST / 21:00 UTC, see "
        "`.github/workflows/meta-analysis-daily.yml`)."
    )
    lines.append(
        "- Pure SQL aggregation + markdown gen; **no LLM call** "
        "(CLAUDE.md + `feedback_autonomath_no_api_use`)."
    )
    lines.append(
        "- Optional Slack summary posted to `$SLACK_WEBHOOK_OPS` when "
        "configured; silent fall-through otherwise."
    )
    lines.append("")
    return "\n".join(lines)


def _slack_payload(
    today: date,
    metrics: dict[str, Any],
    stats: list[dict[str, Any]],
    baseline: bool,
) -> dict[str, Any]:
    delta_line = (
        "baseline (no prior snapshot)"
        if baseline
        else f"Δ {_fmt_delta(metrics['delta_total'])} rows vs. yesterday"
    )
    summary = (
        f"meta_analysis_daily {today.isoformat()} — "
        f"{metrics['ok']}/{metrics['total']} ok, "
        f"{metrics['missing']} missing, {metrics['error']} error · "
        f"rows={_fmt_int(metrics['rows_total'])} · {delta_line}"
    )
    movers = sorted(
        (s for s in stats if s.get("row_count_delta")),
        key=lambda s: abs(int(s["row_count_delta"] or 0)),
        reverse=True,
    )[:5]
    block_lines = [summary]
    if movers:
        block_lines.append("")
        block_lines.append("Top movers:")
        for m in movers:
            block_lines.append(
                f"- {m['table']}: {_fmt_delta(m['row_count_delta'])} "
                f"(now {_fmt_int(m['row_count'])})"
            )
    text = "\n".join(block_lines)
    return {"text": text}


def _post_slack(webhook: str, payload: dict[str, Any]) -> bool:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310  # nosec B310 - operator-config https endpoint, no file:/ schemes
            ok = 200 <= resp.status < 300
            if not ok:
                logger.warning("slack post non-2xx: %s", resp.status)
            return ok
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("slack post failed: %s", exc)
        return False


def _persist_outputs(
    out_dir: Path,
    today: date,
    am_db: Path,
    stats: list[dict[str, Any]],
    metrics: dict[str, Any],
    baseline: bool,
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{today.isoformat()}.md"
    json_path = out_dir / f"{today.isoformat()}.json"
    md_text = _render_markdown(today, am_db, stats, metrics, baseline)
    md_path.write_text(md_text, encoding="utf-8")
    json_payload = {
        "date": today.isoformat(),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "am_db": str(am_db),
        "baseline": baseline,
        "metrics": metrics,
        "tables": stats,
    }
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO / "tools" / "offline" / "_inbox" / "_meta_analysis",
        help="Output directory for {YYYY-MM-DD}.md + .json snapshot.",
    )
    parser.add_argument(
        "--slack-webhook",
        default=os.environ.get("SLACK_WEBHOOK_OPS", ""),
        help="Slack incoming webhook URL (default: $SLACK_WEBHOOK_OPS).",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Override snapshot date (YYYY-MM-DD). Defaults to today (UTC).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute + render but do not write files or post to Slack.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.am_db is None:
        try:
            from jpintel_mcp.config import settings  # noqa: WPS433

            am_db = settings.autonomath_db_path
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "could not import settings.autonomath_db_path (%s); "
                "falling back to ./autonomath.db",
                exc,
            )
            am_db = _REPO / "autonomath.db"
    else:
        am_db = args.am_db

    am_db = Path(am_db)
    if not am_db.exists():
        logger.error("autonomath.db not found at %s", am_db)
        return 2

    if args.date:
        try:
            today = date.fromisoformat(args.date)
        except ValueError:
            logger.error("--date must be YYYY-MM-DD, got %r", args.date)
            return 2
    else:
        today = datetime.now(UTC).date()

    am_conn = sqlite3.connect(str(am_db))
    am_conn.row_factory = sqlite3.Row
    try:
        stats = _gather_all(am_conn)
    finally:
        with contextlib.suppress(Exception):
            am_conn.close()

    yesterday_indexed = _load_yesterday(args.out_dir, today)
    stats, baseline = _annotate_deltas(stats, yesterday_indexed)
    metrics = _summary_metrics(stats)

    logger.info(
        "meta_analysis_daily %s: ok=%d/%d, rows=%d, delta=%d, baseline=%s",
        today.isoformat(),
        metrics["ok"],
        metrics["total"],
        metrics["rows_total"],
        metrics["delta_total"],
        baseline,
    )

    if args.dry_run:
        md = _render_markdown(today, am_db, stats, metrics, baseline)
        sys.stdout.write(md)
        return 0

    md_path, json_path = _persist_outputs(args.out_dir, today, am_db, stats, metrics, baseline)
    logger.info("wrote %s", md_path)
    logger.info("wrote %s", json_path)

    if args.slack_webhook:
        payload = _slack_payload(today, metrics, stats, baseline)
        ok = _post_slack(args.slack_webhook, payload)
        logger.info("slack post: %s", "ok" if ok else "failed")
    else:
        logger.info("SLACK_WEBHOOK_OPS not configured; skipping Slack post.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
