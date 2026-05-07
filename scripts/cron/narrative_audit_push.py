#!/usr/bin/env python3
"""§10.10 (6) Hallucination Guard — operator monthly stratified audit push.

Monthly Fly cron (1st 09:00 JST). Stratified random sample of n=1,000 narrative
rows across the five §10.10 narrative tables, weighted by the live row count
of each table (按分). Each sampled row is pushed to the operator Telegram bot
with the body, primary source URL, and a ✓/✗/修正 inline keyboard so the
operator can rapidly disposition rows on mobile.

The operator-side callback handler lives behind a SELECT-only API endpoint
(out of scope for this cron — see `api/narrative_audit_callback.py`, future
sibling). Per `feedback_no_operator_llm_api`: NO LLM call here, the cron is
pure SQLite + urllib.

Env:
    TG_BOT_TOKEN     bot token (required to push)
    TG_CHAT_ID       operator chat id (required to push)
    NARRATIVE_AUDIT_SAMPLE_SIZE  default 1000

Cron handle:
    .github/workflows/narrative-audit-monthly.yml (1st of each month).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
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

logger = logging.getLogger("autonomath.cron.narrative_audit_push")

# Narrative tables we sample from. The body column resolution mirrors the
# extractor — first present column wins.
_NARRATIVE_TABLES: tuple[str, ...] = (
    "am_program_narrative",
    "am_houjin_360_narrative",
    "am_enforcement_summary",
    "am_case_study_narrative",
    "am_law_article_summary",
)

_BODY_COLUMN_CANDIDATES: tuple[str, ...] = (
    "body_text",
    "body",
    "body_ja",
    "narrative",
    "summary",
    "text",
    "content",
)

_DEFAULT_SAMPLE_SIZE = 1000


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.narrative_audit_push")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _resolve_body_column(conn: sqlite3.Connection, table: str) -> str | None:
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for cand in _BODY_COLUMN_CANDIDATES:
        if cand in cols:
            return cand
    return None


def _row_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE is_active=1").fetchone()[0])
    except sqlite3.OperationalError:
        try:
            return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.OperationalError:
            return 0


def _stratified_alloc(counts: dict[str, int], total_sample: int) -> dict[str, int]:
    grand = sum(counts.values())
    if grand == 0:
        return dict.fromkeys(counts, 0)
    raw = {t: (n / grand) * total_sample for t, n in counts.items()}
    floored = {t: int(v) for t, v in raw.items()}
    rem = total_sample - sum(floored.values())
    # Distribute leftover by largest fractional remainder.
    fracs = sorted(((v - floored[t], t) for t, v in raw.items()), reverse=True)
    for _, t in fracs[:rem]:
        floored[t] += 1
    # Cap each cell at population size.
    for t in floored:
        if floored[t] > counts[t]:
            floored[t] = counts[t]
    return floored


def _sample_table(conn: sqlite3.Connection, table: str, body_col: str, n: int) -> list[dict]:
    if n <= 0:
        return []
    try:
        rows = conn.execute(
            f"SELECT narrative_id, {body_col} AS body FROM {table} "
            "WHERE is_active=1 ORDER BY RANDOM() LIMIT ?",
            (n,),
        ).fetchall()
    except sqlite3.OperationalError:
        # is_active column may not exist on older table snapshots.
        rows = conn.execute(
            f"SELECT narrative_id, {body_col} AS body FROM {table} ORDER BY RANDOM() LIMIT ?",
            (n,),
        ).fetchall()
    return [{"table": table, "narrative_id": int(r[0]), "body": str(r[1] or "")} for r in rows]


def _telegram_push(text: str, *, callback_data_yes: str, callback_data_no: str) -> bool:
    bot_token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not bot_token or not chat_id:
        logger.info("audit_telegram_push_skipped reason=missing_env")
        return False
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✓ OK", "callback_data": callback_data_yes},
                {"text": "✗ NG", "callback_data": callback_data_no},
                {
                    "text": "修正",
                    "callback_data": callback_data_no.replace(":no", ":fix"),
                },
            ]
        ]
    }
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": "Markdown",
            "disable_web_page_preview": "true",
            "reply_markup": json.dumps(keyboard, ensure_ascii=False),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310 - operator-config https endpoint, no file:/ schemes
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("audit_telegram_push_failed err=%s", str(exc)[:160])
        return False


def _resolve_source_url(conn: sqlite3.Connection, table: str, narrative_id: int) -> str | None:
    """Best-effort source_url lookup for the audit push card."""
    if table == "am_program_narrative":
        try:
            row = conn.execute(
                "SELECT p.source_url FROM am_program_narrative npn "
                "JOIN programs p ON p.id = npn.program_id "
                "WHERE npn.narrative_id = ?",
                (narrative_id,),
            ).fetchone()
            return row[0] if row and row[0] else None
        except sqlite3.OperationalError:
            return None
    return None


def run(*, db_path: Path, sample_size: int, dry_run: bool) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    pushed = 0
    sampled = 0
    try:
        counts: dict[str, int] = {}
        bodies: dict[str, str] = {}
        for tbl in _NARRATIVE_TABLES:
            if not _table_exists(conn, tbl):
                continue
            body_col = _resolve_body_column(conn, tbl)
            if body_col is None:
                continue
            counts[tbl] = _row_count(conn, tbl)
            bodies[tbl] = body_col

        if not counts:
            logger.warning("no_narrative_tables_present")
            return {"sampled": 0, "pushed": 0, "dry_run": dry_run}

        alloc = _stratified_alloc(counts, sample_size)
        logger.info(
            "audit_alloc total=%d %s",
            sample_size,
            json.dumps(alloc, ensure_ascii=False),
        )

        all_samples: list[dict] = []
        for tbl, n in alloc.items():
            all_samples.extend(_sample_table(conn, tbl, bodies[tbl], n))
        random.shuffle(all_samples)
        sampled = len(all_samples)

        run_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        for row in all_samples:
            src = _resolve_source_url(conn, row["table"], row["narrative_id"])
            text = (
                f"*[narrative audit]* `{row['table']}#{row['narrative_id']}`\n"
                f"出典: {src or 'n/a'}\n\n"
                f"{row['body'][:3000]}"
            )
            ok_cb = f"audit:{run_ts}:{row['table']}:{row['narrative_id']}:ok"
            no_cb = f"audit:{run_ts}:{row['table']}:{row['narrative_id']}:no"
            if dry_run:
                logger.info(
                    "audit_dry_run table=%s nid=%d body_chars=%d",
                    row["table"],
                    row["narrative_id"],
                    len(row["body"]),
                )
                continue
            if _telegram_push(text, callback_data_yes=ok_cb, callback_data_no=no_cb):
                pushed += 1
    finally:
        conn.close()
    return {"sampled": sampled, "pushed": pushed, "dry_run": dry_run}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="§10.10 monthly stratified narrative audit push (Telegram)"
    )
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument(
        "--sample-size",
        type=int,
        default=int(os.environ.get("NARRATIVE_AUDIT_SAMPLE_SIZE", _DEFAULT_SAMPLE_SIZE)),
    )
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    db_path = args.am_db if args.am_db else Path(str(settings.autonomath_db_path))
    with heartbeat("narrative_audit_push") as hb:
        try:
            counters = run(
                db_path=db_path,
                sample_size=int(args.sample_size),
                dry_run=bool(args.dry_run),
            )
        except Exception as e:
            logger.exception("narrative_audit_push_failed err=%s", e)
            return 1
        hb["rows_processed"] = int(counters.get("sampled", 0) or 0)
        hb["metadata"] = counters
    logger.info(
        "audit_done sampled=%d pushed=%d dry_run=%s",
        counters.get("sampled", 0),
        counters.get("pushed", 0),
        bool(args.dry_run),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
