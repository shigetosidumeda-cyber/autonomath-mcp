#!/usr/bin/env python3
"""§10.10 (3) Hallucination Guard — SLA breach pusher (Telegram).

Hourly Fly cron. Walks `am_narrative_customer_reports` for P0/P1 rows whose
`sla_due_at` is in the past AND whose `state` is still `inbox`, then pushes
a one-line summary per breach to the operator Telegram bot.

Per `feedback_no_operator_llm_api`: NO LLM call, this is a urllib POST to the
Telegram Bot API.

Env:
    TG_BOT_TOKEN     — bot token issued by @BotFather (required to push)
    TG_CHAT_ID       — chat ID for the operator (required to push)

When the env vars are missing the cron still runs (and logs the breach
count) but does not push — useful for dry-run verification.

Cron handle:
    .github/workflows/narrative-sla-breach-hourly.yml (hourly).
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.narrative_report_sla_breach")


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.narrative_report_sla_breach")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _push_telegram(text: str) -> bool:
    """Send `text` to the operator chat via Telegram bot API.

    Returns True on success, False if env vars missing OR the call failed.
    """
    bot_token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not bot_token or not chat_id:
        logger.info("telegram_push_skipped reason=missing_env")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            if not ok:
                logger.warning("telegram_push_non_200 status=%d", resp.status)
            return ok
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("telegram_push_failed err=%s", str(exc)[:160])
        return False


def _select_breaches(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT report_id, narrative_id, narrative_table, severity_auto,"
            "       sla_due_at, created_at "
            "  FROM am_narrative_customer_reports "
            " WHERE state = 'inbox' "
            "   AND severity_auto IN ('P0','P1') "
            "   AND sla_due_at < ? "
            " ORDER BY severity_auto ASC, sla_due_at ASC "
            " LIMIT 100",
            (datetime.now(UTC).isoformat(),),
        )
    )


def run(*, db_path: Path, dry_run: bool) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    pushed = 0
    breach_count = 0
    try:
        try:
            rows = _select_breaches(conn)
        except sqlite3.OperationalError as exc:
            logger.warning("sla_breach_select_failed err=%s", str(exc)[:160])
            return {"breaches": 0, "pushed": 0, "dry_run": dry_run}
        breach_count = len(rows)
        if breach_count == 0:
            logger.info("no_sla_breaches")
            return {"breaches": 0, "pushed": 0, "dry_run": dry_run}

        for r in rows:
            text = (
                f"[SLA BREACH {r['severity_auto']}] "
                f"narrative {r['narrative_table']}#{r['narrative_id']} "
                f"report_id={r['report_id']} "
                f"due={r['sla_due_at']} created={r['created_at']}"
            )
            if dry_run:
                logger.info("breach_dry_run %s", text)
                continue
            if _push_telegram(text):
                pushed += 1
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute(
                        "UPDATE am_narrative_customer_reports "
                        "SET operator_note = COALESCE(operator_note,'') "
                        "    || '|breach_notified=' || ? "
                        "WHERE report_id = ?",
                        (
                            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M"),
                            int(r["report_id"]),
                        ),
                    )
        if not dry_run:
            conn.commit()
    finally:
        conn.close()
    return {"breaches": breach_count, "pushed": pushed, "dry_run": dry_run}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="§10.10 narrative-report SLA breach pusher (hourly)")
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    db_path = args.am_db if args.am_db else Path(str(settings.autonomath_db_path))
    with heartbeat("narrative_report_sla_breach") as hb:
        try:
            counters = run(db_path=db_path, dry_run=bool(args.dry_run))
        except Exception as e:
            logger.exception("narrative_sla_breach_failed err=%s", e)
            return 1
        hb["rows_processed"] = int(counters.get("breaches", 0) or 0)
        hb["metadata"] = counters
    logger.info(
        "sla_breach_done breaches=%d pushed=%d dry_run=%s",
        counters.get("breaches", 0),
        counters.get("pushed", 0),
        bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
