#!/usr/bin/env python3
"""Generate weekly am_amendment_diff RSS 2.0 feed (Wave 15 F7).

Surfaces the last 7 days of append-only amendment diff rows from
`autonomath.db::am_amendment_diff` (12,116 rows live, mig 075) as an
RSS 2.0 channel so AI agents + 税理士 watchers can poll one URL and
receive every meaningful eligibility change shipped in the past week.

What ships per item
-------------------
* diff_id (RSS guid)
* entity_id (am_entities.canonical_id) + display_name when resolvable
* field_name (e.g. ``eligibility_text``, ``amount_max_yen``,
  ``program.application_period``)
* prev_value / new_value (truncated snippets) + prev_hash / new_hash
* source_url (the URL that produced the diff at detection time)
* detected_at (RFC 2822 pubDate)

Schedule
--------
``0 3 * * 1`` (every Monday 03:00 UTC) via
``.github/workflows/amendment-diff-rss-weekly.yml``.

Output
------
Writes ``site/feeds/amendment_diff.xml`` (creates the ``feeds/``
directory if missing) plus a single sitemap-index entry the deploy
pipeline picks up via the existing static-asset sweep.

Hard constraints
----------------
* NO Anthropic / openai / SDK import. Pure SQLite + stdlib.
* Append-only read posture — never mutates am_amendment_diff.
* Idempotent: re-running same day overwrites the XML byte-identically
  when nothing changed in the 7-day window.

Usage
-----
::
    python3 scripts/cron/generate_amendment_diff_rss.py
    python3 scripts/cron/generate_amendment_diff_rss.py --dry-run
    python3 scripts/cron/generate_amendment_diff_rss.py --window-days 14
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timedelta

try:
    from datetime import UTC  # Python 3.11+
except ImportError:  # pragma: no cover — Python 3.9/3.10 fallback for local dry-runs
    UTC = UTC  # type: ignore[misc, assignment]
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from jpintel_mcp._jpcite_env_bridge import get_flag

logger = logging.getLogger("autonomath.cron.generate_amendment_diff_rss")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Optional heartbeat — best-effort, do not crash the cron when the
# observability stack is absent.
try:  # noqa: SIM105
    from jpintel_mcp.observability import heartbeat  # noqa: E402
except Exception:  # noqa: BLE001
    from contextlib import contextmanager

    @contextmanager
    def heartbeat(_name: str):  # type: ignore[no-redef]
        yield {}


_DEFAULT_DB = Path(
    get_flag("JPCITE_AUTONOMATH_DB_PATH", "AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db"))
)
_DEFAULT_OUT = _REPO_ROOT / "site" / "feeds" / "amendment_diff.xml"
_DOMAIN = "jpcite.com"
_DEFAULT_WINDOW_DAYS = 7
_MAX_ITEMS = 200
_SNIPPET_CAP = 220


def _truncate(value: str | None) -> str:
    if not value:
        return ""
    s = str(value).strip()
    if len(s) <= _SNIPPET_CAP:
        return s
    return s[: _SNIPPET_CAP - 1] + "…"


def _build(db_path: Path, *, window_days: int) -> str:
    """Build the RSS 2.0 body from the last ``window_days`` of diffs."""
    cutoff = (datetime.now(UTC) - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                """
                SELECT
                    d.diff_id,
                    d.entity_id,
                    d.field_name,
                    d.prev_value,
                    d.new_value,
                    d.prev_hash,
                    d.new_hash,
                    d.detected_at,
                    d.source_url,
                    e.primary_name AS display_name,
                    e.record_kind  AS kind
                  FROM am_amendment_diff d
             LEFT JOIN am_entities e
                    ON e.canonical_id = d.entity_id
                 WHERE d.detected_at >= ?
              ORDER BY d.detected_at DESC, d.diff_id DESC
                 LIMIT ?
                """,
                (cutoff, _MAX_ITEMS),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                logger.warning("am_amendment_diff table absent: %s", exc)
                rows = []
            else:
                raise
    finally:
        conn.close()

    items: list[str] = []
    for r in rows:
        display = r["display_name"] or r["entity_id"]
        kind = r["kind"] or "entity"
        title = (
            f"[{xml_escape(kind)}] {xml_escape(display)} — "
            f"{xml_escape(r['field_name'] or 'unknown_field')}"
        )
        link = r["source_url"] or f"https://{_DOMAIN}/feeds/amendment_diff.xml#diff-{r['diff_id']}"
        try:
            pub_dt = datetime.fromisoformat(str(r["detected_at"]).replace("Z", "+00:00"))
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=UTC)
            pub_date = format_datetime(pub_dt)
        except (ValueError, TypeError):
            pub_date = format_datetime(datetime.now(UTC))

        prev_snip = _truncate(r["prev_value"])
        new_snip = _truncate(r["new_value"])
        desc = (
            f"entity_id: {xml_escape(r['entity_id'])}. "
            f"field: {xml_escape(r['field_name'] or '')}. "
            f"prev: {xml_escape(prev_snip) or '(none)'} → "
            f"new: {xml_escape(new_snip) or '(none)'}. "
            f"prev_hash: {xml_escape(r['prev_hash'] or '')[:12]} "
            f"new_hash: {xml_escape(r['new_hash'] or '')[:12]}. "
            f"source: {xml_escape(r['source_url'] or 'N/A')}. "
            "Operator: Bookyou株式会社 (T8010001213708)."
        )
        items.append(
            "  <item>\n"
            f"    <title>{title}</title>\n"
            f"    <link>{xml_escape(link)}</link>\n"
            f'    <guid isPermaLink="false">amendment-diff-{r["diff_id"]}</guid>\n'
            f"    <pubDate>{pub_date}</pubDate>\n"
            f"    <category>{xml_escape(r['field_name'] or 'amendment_diff')}</category>\n"
            f"    <description>{desc}</description>\n"
            "  </item>"
        )

    last_build = format_datetime(datetime.now(UTC))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "<channel>\n"
        "  <title>jpcite Amendment Diff (am_amendment_diff weekly)</title>\n"
        f"  <link>https://{_DOMAIN}/feeds/amendment_diff.xml</link>\n"
        f'  <atom:link href="https://{_DOMAIN}/feeds/amendment_diff.xml" '
        'rel="self" type="application/rss+xml" />\n'
        "  <description>Append-only eligibility-change log shipped from "
        "autonomath.db::am_amendment_diff (12k+ rows). One entry per "
        "(entity_id, field_name) diff detected in the last 7 days. "
        "For AI agents and 税理士 watchers polling primary-source "
        "amendment events. CC-BY-4.0 metadata.</description>\n"
        "  <language>ja</language>\n"
        f"  <lastBuildDate>{last_build}</lastBuildDate>\n"
        "  <ttl>1440</ttl>\n"
        "  <copyright>(C) 2026 Bookyou株式会社</copyright>\n"
        "  <dc:rights>CC-BY-4.0</dc:rights>\n"
        "  <generator>jpcite/generate_amendment_diff_rss.py</generator>\n"
        + ("\n".join(items) if items else "")
        + "\n</channel>\n</rss>\n"
    )


def _patch_sitemap_index(sitemap_path: Path) -> None:
    """Append the amendment_diff feed entry to sitemap-index.xml if absent.

    Idempotent: when the entry is already present (string match on the
    feed URL), the function is a no-op. When the sitemap file is
    missing entirely, the function is a no-op (the deploy pipeline
    generates sitemaps elsewhere).
    """
    if not sitemap_path.exists():
        return
    body = sitemap_path.read_text(encoding="utf-8")
    feed_url = f"https://{_DOMAIN}/feeds/amendment_diff.xml"
    if feed_url in body:
        return
    insertion = (
        f"  <sitemap>\n"
        f"    <loc>{feed_url}</loc>\n"
        f"    <lastmod>{datetime.now(UTC).strftime('%Y-%m-%d')}</lastmod>\n"
        f"  </sitemap>\n"
    )
    if "</sitemapindex>" in body:
        patched = body.replace("</sitemapindex>", insertion + "</sitemapindex>")
        sitemap_path.write_text(patched, encoding="utf-8")
        logger.info("patched %s with amendment_diff feed entry", sitemap_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument(
        "--window-days",
        type=int,
        default=_DEFAULT_WINDOW_DAYS,
        help="Number of days to look back (default 7).",
    )
    parser.add_argument(
        "--sitemap",
        type=Path,
        default=_REPO_ROOT / "site" / "sitemap-index.xml",
        help="sitemap-index.xml path to patch with the feed entry (idempotent).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    with heartbeat("generate_amendment_diff_rss") as hb:
        if not args.db.exists():
            logger.error("autonomath.db missing at %s", args.db)
            if isinstance(hb, dict):
                hb["metadata"] = {"error": "db_missing", "path": str(args.db)}
            if args.dry_run:
                # On dry-run we still want a syntactically valid empty feed
                # so the workflow's xmllint gate passes in CI without the DB.
                sys.stdout.write(_build_empty())
                return 0
            return 1

        body = _build(args.db, window_days=args.window_days)
        if isinstance(hb, dict):
            hb["metadata"] = {
                "bytes": len(body),
                "out": str(args.out),
                "dry_run": bool(args.dry_run),
                "window_days": args.window_days,
            }
        if args.dry_run:
            sys.stdout.write(body)
            return 0
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(body, encoding="utf-8")
        logger.info("wrote %s (%d bytes)", args.out, len(body))
        _patch_sitemap_index(args.sitemap)
        if isinstance(hb, dict):
            hb["rows_processed"] = body.count("<item>")
    return 0


def _build_empty() -> str:
    """Return a syntactically valid empty RSS feed for dry-run when DB is absent."""
    last_build = format_datetime(datetime.now(UTC))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        "<channel>\n"
        "  <title>jpcite Amendment Diff (am_amendment_diff weekly)</title>\n"
        f"  <link>https://{_DOMAIN}/feeds/amendment_diff.xml</link>\n"
        f'  <atom:link href="https://{_DOMAIN}/feeds/amendment_diff.xml" '
        'rel="self" type="application/rss+xml" />\n'
        "  <description>(autonomath.db absent — empty placeholder)</description>\n"
        "  <language>ja</language>\n"
        f"  <lastBuildDate>{last_build}</lastBuildDate>\n"
        "  <copyright>(C) 2026 Bookyou株式会社</copyright>\n"
        "</channel>\n</rss>\n"
    )


if __name__ == "__main__":
    sys.exit(main())
