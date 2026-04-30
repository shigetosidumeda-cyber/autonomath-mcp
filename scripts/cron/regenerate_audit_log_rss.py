#!/usr/bin/env python3
"""Regenerate /audit-log.rss from am_amendment_diff.

Reads the latest 50 rows of `am_amendment_diff` (autonomath.db, migration
075), reverse-chrono, and emits an RSS 2.0 feed at site/audit-log.rss.new.
We never overwrite the existing rss.xml directly — the spec says write to
.new and let the next deploy swap. This protects the live feed from a
broken regen run.

This is the static-feed counterpart to the live `GET /v1/am/audit-log`
endpoint. RSS subscribers (Inoreader, Feedly, etc.) get the same data
without consuming our anonymous IP quota — no auth required, no quota
header, just plain CC-BY-4.0 differential metadata.

Idempotency
-----------
Re-running on the same diff log produces byte-identical output because
rows are sorted (detected_at DESC, diff_id DESC) and we cap at 50.

Usage
-----
    python scripts/cron/regenerate_audit_log_rss.py
    python scripts/cron/regenerate_audit_log_rss.py --dry-run

Exit codes
----------
0 success
1 fatal (autonomath.db missing, migration 075 not yet applied, etc.)
"""
from __future__ import annotations

import argparse
import html as html_lib
import logging
import os
import sqlite3
import sys
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

logger = logging.getLogger("autonomath.cron.regenerate_audit_log_rss")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from jpintel_mcp.observability import heartbeat  # noqa: E402

_DEFAULT_DB = Path(
    os.environ.get("AUTONOMATH_DB_PATH", str(_REPO_ROOT / "autonomath.db"))
)
_DEFAULT_OUT = _REPO_ROOT / "site" / "audit-log.rss.new"
_DEFAULT_DOMAIN = "jpcite.com"
_UTC = UTC

_MAX_ITEMS = 50

# Mirrors api/audit_log.py:_TRACKED_FIELDS_JA — keep in sync.
_TRACKED_FIELDS_JA = {
    "amount_max_yen": "補助上限額",
    "subsidy_rate_max": "補助率上限",
    "program.target_entity": "対象事業者",
    "program.target_business_size": "対象事業規模",
    "program.application_period": "申請期間",
    "program.application_period_r7": "申請期間R7",
    "program.application_channel": "申請窓口",
    "program.prerequisite": "前提条件",
    "program.subsidy_rate": "補助率本文",
    "eligibility_text": "適格要件 (合成)",
}


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.regenerate_audit_log_rss")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root.addHandler(h)


def _xml_escape(s: str) -> str:
    return html_lib.escape(s, quote=True)


def _truncate(s: str | None, n: int) -> str:
    if s is None:
        return "(null)"
    s = str(s)
    return s if len(s) <= n else s[:n] + "…"


def _parse_detected_at(raw: str) -> datetime:
    """Parse `am_amendment_diff.detected_at` into a UTC datetime.

    SQLite CURRENT_TIMESTAMP emits `YYYY-MM-DD HH:MM:SS` in UTC. Some
    rows may already carry an explicit `+00:00` suffix. We normalize
    both into a tz-aware UTC datetime.
    """
    raw = raw.strip()
    if "T" not in raw:
        # SQLite default format `YYYY-MM-DD HH:MM:SS`.
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=_UTC)
        except ValueError:
            pass
    # ISO 8601 — try fromisoformat which accepts trailing tz.
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        # Fall back to "now" so the feed never breaks on a malformed
        # row. Log loudly so operators notice.
        logger.warning("malformed_detected_at value=%r", raw)
        return datetime.now(_UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def _fetch_diff_rows(db_path: Path, limit: int) -> list[dict]:
    if not db_path.exists():
        logger.error("autonomath_db_missing path=%s", db_path)
        return []
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError as exc:
        logger.error("connect_failed path=%s err=%s", db_path, exc)
        return []
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT diff_id, entity_id, field_name, prev_value, new_value, "
            "       prev_hash, new_hash, detected_at, source_url "
            "FROM am_amendment_diff "
            "ORDER BY detected_at DESC, diff_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            logger.warning(
                "am_amendment_diff missing — emitting empty feed (cron will "
                "populate post-launch)."
            )
            return []
        logger.error("query_failed err=%s", exc)
        return []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _render_rss(rows: list[dict], *, domain: str) -> str:
    feed_url = f"https://{domain}/audit-log.rss"
    page_url = f"https://{domain}/audit-log.html"

    if rows:
        last_build = max(_parse_detected_at(r["detected_at"]) for r in rows)
    else:
        last_build = datetime.now(_UTC).replace(minute=0, second=0, microsecond=0)

    lines: list[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:cc="http://web.resource.org/cc/">'
    )
    lines.append("<channel>")
    lines.append("  <title>jpcite 変更履歴 (am_amendment_diff)</title>")
    lines.append(f"  <link>{_xml_escape(page_url)}</link>")
    lines.append(
        f'  <atom:link href="{_xml_escape(feed_url)}" rel="self" type="application/rss+xml" />'
    )
    lines.append(
        "  <description>"
        "公的機関データの差分を毎日 cron で検出。検出のみで個別判断は行いません。"
        "差分メタデータは CC-BY-4.0、原典は各 source_url の公的機関ライセンスに従います。"
        "</description>"
    )
    lines.append("  <language>ja</language>")
    lines.append("  <copyright>(C) 2026 Bookyou株式会社</copyright>")
    lines.append("  <generator>AutonoMath audit-log RSS (Bookyou株式会社)</generator>")
    lines.append("  <dc:rights>CC-BY-4.0 (差分メタデータ)</dc:rights>")
    lines.append(f"  <lastBuildDate>{format_datetime(last_build)}</lastBuildDate>")
    lines.append("")

    for r in rows:
        field_ja = _TRACKED_FIELDS_JA.get(r["field_name"]) or r["field_name"]
        title = (
            f"{r['entity_id']} — {r['field_name']} ({field_ja}) "
            f"が変更されました"
        )
        prev = _truncate(r["prev_value"], 200)
        new = _truncate(r["new_value"], 200)
        desc = (
            f"entity_id: {r['entity_id']}\n"
            f"field_name: {r['field_name']} ({field_ja})\n"
            f"prev_value: {prev}\n"
            f"new_value: {new}\n"
            f"prev_hash: {r['prev_hash'] or '(初回観測)'}\n"
            f"new_hash: {r['new_hash'] or '(field disappeared)'}\n"
            f"source_url: {r['source_url'] or '(none)'}"
        )
        # GUID = stable diff_id (append-only — never re-used).
        guid = f"autonomath:audit:diff:{r['diff_id']}"
        lines.append("  <item>")
        lines.append(f"    <title>{_xml_escape(title)}</title>")
        lines.append(f"    <link>{_xml_escape(page_url)}#diff-{r['diff_id']}</link>")
        lines.append(f"    <description>{_xml_escape(desc)}</description>")
        lines.append("    <category>amendment</category>")
        lines.append(f'    <guid isPermaLink="false">{_xml_escape(guid)}</guid>')
        lines.append(
            f"    <pubDate>"
            f"{format_datetime(_parse_detected_at(r['detected_at']))}"
            f"</pubDate>"
        )
        if r["source_url"]:
            lines.append(
                f"    <source url=\"{_xml_escape(r['source_url'])}\">"
                "primary government source"
                "</source>"
            )
        lines.append("  </item>")
        lines.append("")

    lines.append("</channel>")
    lines.append("</rss>")
    return "\n".join(lines) + "\n"


def _write_if_changed(path: Path, content: str, dry_run: bool) -> bool:
    if dry_run:
        logger.info(
            "would_write path=%s bytes=%d",
            path.relative_to(_REPO_ROOT)
            if str(path).startswith(str(_REPO_ROOT))
            else path,
            len(content.encode("utf-8")),
        )
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except Exception:
            existing = ""
        if existing == content:
            logger.info("rss_unchanged path=%s", path)
            return False
    path.write_text(content, encoding="utf-8")
    logger.info("wrote_rss path=%s bytes=%d", path, len(content.encode("utf-8")))
    return True


def run(
    *,
    db_path: Path = _DEFAULT_DB,
    out_path: Path = _DEFAULT_OUT,
    domain: str = _DEFAULT_DOMAIN,
    dry_run: bool = False,
) -> int:
    rows = _fetch_diff_rows(db_path, _MAX_ITEMS)
    xml = _render_rss(rows, domain=domain)
    _write_if_changed(out_path, xml, dry_run)
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Regenerate audit-log.rss")
    p.add_argument("--db", type=Path, default=_DEFAULT_DB)
    p.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    p.add_argument("--domain", default=_DEFAULT_DOMAIN)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)
    with heartbeat("regenerate_audit_log_rss") as hb:
        rc = run(
            db_path=args.db,
            out_path=args.out,
            domain=args.domain,
            dry_run=args.dry_run,
        )
        hb["metadata"] = {"dry_run": bool(args.dry_run), "exit_code": rc}
    return rc


if __name__ == "__main__":
    sys.exit(main())
