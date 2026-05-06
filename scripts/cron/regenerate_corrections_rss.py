#!/usr/bin/env python3
"""Regenerate /corrections.xml from correction_log (mig 101).

Static counterpart of ``GET /v1/corrections/feed``. Lets RSS subscribers
poll Cloudflare Pages directly without burning the API's anonymous quota.

Writes to ``site/corrections.xml.new`` and lets the next deploy swap.
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger("autonomath.cron.regenerate_corrections_rss")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

_DEFAULT_DB = Path(os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db")))
_DEFAULT_OUT = _REPO_ROOT / "site" / "corrections.xml.new"
_DOMAIN = "jpcite.com"


def _build(db_path: Path) -> str:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "SELECT id, detected_at, dataset, entity_id, field_name, "
                "       root_cause, source_url, correction_post_url "
                "FROM correction_log "
                "ORDER BY detected_at DESC, id DESC LIMIT 50"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                rows = []
            else:
                raise
    finally:
        conn.close()

    items = []
    for r in rows:
        title = (
            f"[{xml_escape(r['dataset'])}] {xml_escape(r['entity_id'])} — "
            f"{xml_escape(r['field_name'] or 'row-level')} "
            f"({xml_escape(r['root_cause'])})"
        )
        link = r["correction_post_url"] or f"https://{_DOMAIN}/news/correction-{r['id']}.html"
        try:
            pub_dt = datetime.fromisoformat(r["detected_at"].replace("Z", "+00:00"))
            pub_date = format_datetime(pub_dt)
        except Exception:  # noqa: BLE001
            pub_date = r["detected_at"]
        desc = (
            f"Source: {xml_escape(r['source_url'] or 'N/A')}. "
            "Operator: Bookyou株式会社 (T8010001213708)."
        )
        items.append(
            "  <item>\n"
            f"    <title>{title}</title>\n"
            f"    <link>{xml_escape(link)}</link>\n"
            f'    <guid isPermaLink="false">correction-{r["id"]}</guid>\n'
            f"    <pubDate>{pub_date}</pubDate>\n"
            f"    <description>{desc}</description>\n"
            "  </item>"
        )

    last_build = format_datetime(datetime.now(UTC))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "<channel>\n"
        "  <title>jpcite Corrections (correction_log)</title>\n"
        f"  <link>https://{_DOMAIN}/corrections.xml</link>\n"
        f'  <atom:link href="https://{_DOMAIN}/corrections.xml" '
        'rel="self" type="application/rss+xml" />\n'
        "  <description>Customer-reported and cross-source detected data "
        "corrections. CC-BY-4.0 metadata.</description>\n"
        "  <language>ja</language>\n"
        f"  <lastBuildDate>{last_build}</lastBuildDate>\n"
        "  <copyright>(C) 2026 Bookyou株式会社</copyright>\n"
        "  <dc:rights>CC-BY-4.0</dc:rights>\n" + "\n".join(items) + "\n</channel>\n</rss>\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    with heartbeat("regenerate_corrections_rss") as hb:
        if not args.db.exists():
            logger.error("autonomath.db missing at %s", args.db)
            hb["metadata"] = {"error": "db_missing", "path": str(args.db)}
            return 1

        body = _build(args.db)
        hb["metadata"] = {
            "bytes": len(body),
            "out": str(args.out),
            "dry_run": bool(args.dry_run),
        }
        if args.dry_run:
            sys.stdout.write(body)
            return 0
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
        logger.info("wrote %s (%d bytes)", args.out, len(body))
        hb["rows_processed"] = 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
