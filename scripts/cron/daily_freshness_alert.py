#!/usr/bin/env python3
"""Axis 3 daily ingest freshness alert (5-source rollup).

Aggregates the previous 24h ingest counters for each of the 5 Axis 3 daily
sources, writes the rollup to ``site/status/data_freshness.html`` (and a
JSON twin at ``site/status/data_freshness.json``), and emits a Telegram bot
alert when an anomaly is detected:

  * Source ingest = 0 rows (likely 5xx / DOM drift / banned host)
  * Error ratio > 10 % across feeds
  * Cron last_run_at older than 26h (missed schedule)

Tracked sources:

  1. adoption_rss          (poll_adoption_rss_daily.py)
  2. egov_amendment        (poll_egov_amendment_daily.py)
  3. enforcement_press     (poll_enforcement_daily.py)
  4. budget_subsidy_chain  (detect_budget_to_subsidy_chain.py)
  5. invoice_diff          (diff_invoice_registrants_daily.py)

The script reads the per-source ingest log line emitted by each cron
(``<source>_done {...counters...}`` line in stdout) by inspecting the SQLite
``cron_ingest_log`` mini-table the crons append to on every run. If that
table is empty/missing, the cron is treated as ``never_ran``.

Telegram payload (only when ``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID``
secrets set; otherwise the alert is logged only).

Constraints
-----------
* LLM call = 0.
* No DB integrity_check / full-scan.

Usage
-----
    python scripts/cron/daily_freshness_alert.py
    python scripts/cron/daily_freshness_alert.py --dry-run

Exit codes
----------
0 success (even if anomalies — they are reported in the dashboard + alert)
1 fatal (db missing, output write failure)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("jpcite.cron.freshness_alert")

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = _REPO_ROOT / "autonomath.db"
DEFAULT_OUT_DIR = _REPO_ROOT / "site" / "status"

SOURCES: tuple[str, ...] = (
    "adoption_rss",
    "egov_amendment",
    "enforcement_press",
    "budget_subsidy_chain",
    "invoice_diff",
)

ZERO_INGEST_THRESHOLD = 0
ERROR_RATIO_THRESHOLD = 0.10
STALE_CRON_THRESHOLD_HOURS = 26


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    p.add_argument(
        "--db",
        default=os.environ.get("AUTONOMATH_DB_PATH", str(DEFAULT_DB_PATH)),
    )
    p.add_argument(
        "--out-dir",
        default=str(DEFAULT_OUT_DIR),
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def _open(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"db missing: {p}")
    conn = sqlite3.connect(str(p), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_log_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS cron_ingest_log (
            log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT NOT NULL,
            counters    TEXT NOT NULL,
            ran_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_cron_ingest_log_src_time
            ON cron_ingest_log(source, ran_at DESC);
        """
    )
    conn.commit()


def _latest_for_source(conn: sqlite3.Connection, source: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT counters, ran_at
        FROM cron_ingest_log
        WHERE source = ?
        ORDER BY ran_at DESC
        LIMIT 1
        """,
        (source,),
    ).fetchone()
    if row is None:
        return None
    try:
        counters = json.loads(row["counters"])
    except (ValueError, TypeError):
        counters = {}
    return {"counters": counters, "ran_at": row["ran_at"]}


def _anomalies(snapshot: dict[str, Any]) -> list[str]:
    out: list[str] = []
    now = _dt.datetime.now(_dt.UTC)
    for src, data in snapshot.items():
        if data is None:
            out.append(f"{src}: NEVER_RAN")
            continue
        counters = data.get("counters") or {}
        inserted = (
            int(counters.get("inserted") or 0)
            + int(counters.get("inserted_jpintel") or 0)
            + int(counters.get("inserted_autonomath") or 0)
            + int(counters.get("snap_inserted") or 0)
            + int(counters.get("diff_inserted") or 0)
            + int(counters.get("chains_inserted") or 0)
            + int(counters.get("updated") or 0)
        )
        fetched = int(counters.get("fetched") or 0)
        feed_failed = int(counters.get("feed_failed") or 0)
        ran_at_raw = data.get("ran_at")
        if inserted <= ZERO_INGEST_THRESHOLD and fetched <= ZERO_INGEST_THRESHOLD:
            out.append(f"{src}: ZERO_INGEST (fetched=0 inserted=0)")
        if fetched > 0:
            ratio = (counters.get("skipped", 0) + feed_failed) / max(fetched, 1)
            if ratio > ERROR_RATIO_THRESHOLD and feed_failed:
                out.append(f"{src}: HIGH_ERROR_RATIO ratio={ratio:.2%} feed_failed={feed_failed}")
        if ran_at_raw:
            try:
                ran_at = _dt.datetime.fromisoformat(ran_at_raw.replace("Z", "+00:00"))
                hours_old = (now - ran_at).total_seconds() / 3600
                if hours_old > STALE_CRON_THRESHOLD_HOURS:
                    out.append(f"{src}: STALE_CRON hours_old={hours_old:.1f}")
            except ValueError:
                pass
    return out


def _render_dashboard(snapshot: dict[str, Any], anomalies: list[str]) -> str:
    now_iso = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows: list[str] = []
    for src, data in snapshot.items():
        if data is None:
            counters_html = "<em>never_ran</em>"
            ran_at = "&mdash;"
        else:
            counters_html = (
                "<pre>"
                + json.dumps(data.get("counters") or {}, ensure_ascii=False, indent=2)
                + "</pre>"
            )
            ran_at = data.get("ran_at") or "&mdash;"
        rows.append(f"<tr><td>{src}</td><td>{ran_at}</td><td>{counters_html}</td></tr>")
    anomalies_html = (
        "<ul>" + "".join(f"<li>{a}</li>" for a in anomalies) + "</ul>"
        if anomalies
        else "<p>OK: 0 anomalies.</p>"
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>jpcite data freshness — Axis 3 daily ingest</title>
<meta name="generator" content="daily_freshness_alert.py">
<link rel="stylesheet" href="/assets/site.css">
</head>
<body>
<header><h1>jpcite data freshness</h1></header>
<main>
<p>Generated at <code>{now_iso}</code>. Axis 3 daily ingest sources, last run:</p>
<table>
<thead><tr><th>source</th><th>ran_at (UTC)</th><th>counters</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
<section><h2>Anomalies ({len(anomalies)})</h2>{anomalies_html}</section>
</main>
</body>
</html>
"""


def _telegram_alert(anomalies: list[str]) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    text = "[jpcite Axis 3 freshness alert]\n" + "\n".join(anomalies)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = httpx.post(
            url,
            data={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        logger.warning("telegram alert send failed: %s", exc)
        return False
    if resp.status_code != 200:
        logger.warning("telegram alert HTTP %d", resp.status_code)
        return False
    return True


def run(db_path: Path, out_dir: Path, dry_run: bool) -> dict[str, Any]:
    conn = _open(str(db_path))
    _ensure_log_table(conn)
    snapshot: dict[str, Any] = {src: _latest_for_source(conn, src) for src in SOURCES}
    conn.close()
    anomalies = _anomalies(snapshot)
    json_payload = {
        "generated_at": _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": snapshot,
        "anomalies": anomalies,
    }
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "data_freshness.html").write_text(
            _render_dashboard(snapshot, anomalies),
            encoding="utf-8",
        )
        (out_dir / "data_freshness.json").write_text(
            json.dumps(json_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if anomalies:
            _telegram_alert(anomalies)
    return json_payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        payload = run(
            db_path=Path(args.db),
            out_dir=Path(args.out_dir),
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        logger.error("db_missing err=%s", exc)
        return 1
    except OSError as exc:
        logger.error("write_failed err=%s", exc)
        return 1
    logger.info(
        "freshness_alert_done sources=%d anomalies=%d",
        len(payload.get("sources", {})),
        len(payload.get("anomalies", [])),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
