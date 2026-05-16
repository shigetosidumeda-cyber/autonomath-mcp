#!/usr/bin/env python3
"""Wave 41 Agent I — extended e-Gov English crawl to lift `am_law.body_en`
coverage toward the full 6,493 law catalog.

Base implementation Wave 35 Axis 5a (`fill_laws_en_full.py`); v2 adds:

  1. JLT index crawl — fetch the master list at
     https://www.japaneselawtranslation.go.jp/en/laws/list and harvest
     <a href="/en/laws/view/{slug}"> targets so we can drive fill from the
     index instead of guessing canonical_id slugs.
  2. Wave 36 Playwright fallback — when urllib returns 0/non-200 for a
     JS-heavy page, retry through the local Playwright fallback module
     (`tools.playwright_fallback`) so JLT's React-rendered detail view
     still yields HTML.
  3. Audit re-count — log live counts of `am_law` total / body_en present
     / body_en NULL each run so the CLAUDE.md figure can be updated from
     authoritative numbers, not a stale snapshot.

NEVER calls an LLM API. sentence-transformers (local, multilingual-e5)
is the only optional similarity engine. Aggregator URLs are refused.
一次資料 only — sentence-transformer candidates land in review_queue,
not body_en directly.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

LOG = logging.getLogger("fill_laws_en_full_v2")
DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))

PRIMARY_DOMAINS = (
    "japaneselawtranslation.go.jp",
    "www.japaneselawtranslation.go.jp",
    "laws.e-gov.go.jp",
    "elaws.e-gov.go.jp",
)
BANNED_DOMAINS = ("noukaweb", "hojyokin-portal", "biz.stayway")

LICENSE_DISCLAIMER = (
    "Translations of Japanese laws on this page are courtesy translations "
    "sourced from the Japanese Ministry of Justice's e-Gov 日本法令外国語訳 "
    "(japaneselawtranslation.go.jp) under CC-BY 4.0. The Japanese-language "
    "original is the only legally authoritative version."
)
USER_AGENT = "jpcite-multilingual-bot/1.0 (+https://jpcite.com/bots; operator=info@bookyou.net)"

JLT_INDEX_URLS = (
    "https://www.japaneselawtranslation.go.jp/en/laws/list",
    "https://www.japaneselawtranslation.go.jp/en/laws",
)
JLT_VIEW_PREFIX = "/en/laws/view/"


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    sql_path = _REPO / "scripts" / "migrations" / "240_law_en_full.sql"
    if sql_path.exists():
        try:
            with sql_path.open(encoding="utf-8") as f:
                conn.executescript(f.read())
        except sqlite3.OperationalError:
            pass


def _is_primary(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(host.endswith(d) for d in PRIMARY_DOMAINS)


def _is_banned(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    return any(b in host for b in BANNED_DOMAINS)


def _fetch(url: str, timeout: int = 20) -> tuple[int, str | None]:
    if _is_banned(url):
        return -1, None
    if not _is_primary(url):
        return 0, None
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None


def _fetch_with_playwright_fallback(url: str, timeout: int = 20) -> tuple[int, str | None]:
    """Try urllib first; fall back to Playwright (Wave 36) on 0/non-200."""
    status, body = _fetch(url, timeout=timeout)
    if status == 200 and body:
        return status, body
    try:
        from tools.playwright_fallback import fetch_html  # type: ignore
    except ImportError:
        return status, body
    try:
        html_text = fetch_html(url, timeout_ms=timeout * 1000)
    except Exception as exc:  # noqa: BLE001
        LOG.debug("playwright fallback error for %s: %s", url, exc)
        return status, body
    if html_text and len(html_text) > 256:
        return 200, html_text
    return status, body


def _extract_text(html_text: str) -> str:
    no_script = re.sub(r"<script.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    no_style = re.sub(r"<style.*?</style>", "", no_script, flags=re.DOTALL | re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", no_style)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def _harvest_jlt_index() -> list[str]:
    """Return canonical_id slugs reachable from JLT master list."""
    slugs: list[str] = []
    seen: set[str] = set()
    for index_url in JLT_INDEX_URLS:
        status, body = _fetch_with_playwright_fallback(index_url)
        if status != 200 or not body:
            continue
        for m in re.finditer(r'href="(/en/laws/view/[^"#?]+)"', body):
            path = m.group(1)
            slug = path[len(JLT_VIEW_PREFIX) :]
            slug = urllib.parse.unquote(slug).strip("/")
            if slug and slug not in seen:
                seen.add(slug)
                slugs.append(slug)
    LOG.info("JLT index harvest: %d slugs", len(slugs))
    return slugs


def _build_translation_urls(canonical_id: str) -> list[str]:
    base = "https://www.japaneselawtranslation.go.jp/en/laws"
    q = urllib.parse.quote(canonical_id)
    return [
        f"{base}/view/{q}",
        f"{base}/?search={q}",
        f"https://laws.e-gov.go.jp/law/{q}",
    ]


def _candidate_laws(
    conn: sqlite3.Connection, max_laws: int | None, resume: bool
) -> list[sqlite3.Row]:
    sql = "SELECT canonical_id, canonical_name AS name, body_en FROM am_law"
    if resume:
        sql += " WHERE body_en IS NULL"
    sql += " ORDER BY canonical_id"
    if max_laws is not None:
        sql += f" LIMIT {int(max_laws)}"
    try:
        return list(conn.execute(sql))
    except sqlite3.Error as exc:
        LOG.warning("am_law fetch failed: %s", exc)
        return []


def _audit_counts(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        total = conn.execute("SELECT COUNT(*) FROM am_law").fetchone()[0]
        present = conn.execute("SELECT COUNT(*) FROM am_law WHERE body_en IS NOT NULL").fetchone()[
            0
        ]
    except sqlite3.Error:
        return {"laws_total": 0, "body_en_present": 0, "body_en_null": 0}
    return {
        "laws_total": int(total),
        "body_en_present": int(present),
        "body_en_null": int(total - present),
    }


def _article_audit(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        total = conn.execute("SELECT COUNT(*) FROM am_law_article").fetchone()[0]
        present = conn.execute(
            "SELECT COUNT(*) FROM am_law_article WHERE body_en IS NOT NULL"
        ).fetchone()[0]
    except sqlite3.Error:
        return {"articles_total": 0, "articles_en_present": 0}
    return {"articles_total": int(total), "articles_en_present": int(present)}


def _queue_id() -> str:
    return f"tx_{uuid.uuid4().hex[:16]}"


def _refresh_id() -> str:
    return f"trx_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")


def _process_law(
    conn: sqlite3.Connection,
    law: sqlite3.Row,
    *,
    dry_run: bool,
    refresh_id: str,
    network: bool = True,
    jlt_index: set[str] | None = None,
) -> dict[str, int]:
    counters = {"filled": 0, "skipped_no_source": 0, "review_queue_added": 0}
    canonical_id = law["canonical_id"]
    if not network:
        primary_urls = [
            u for u in _build_translation_urls(canonical_id) if _is_primary(u) and not _is_banned(u)
        ]
        counters["filled" if primary_urls else "skipped_no_source"] += 1
        return counters
    if jlt_index is not None and canonical_id not in jlt_index:
        # canonical_id is not on JLT index — skip without touching network.
        counters["skipped_no_source"] += 1
        return counters
    for url in _build_translation_urls(canonical_id):
        status, body = _fetch_with_playwright_fallback(url)
        if status == 200 and body:
            text = _extract_text(body)
            if not text or len(text) < 64:
                continue
            if not dry_run:
                conn.execute(
                    "UPDATE am_law SET body_en = ?, body_en_source_url = ?, "
                    "body_en_fetched_at = ?, body_en_license = 'cc_by_4.0' "
                    "WHERE canonical_id = ?",
                    (text, url, _now(), canonical_id),
                )
            counters["filled"] += 1
            return counters
    counters["skipped_no_source"] += 1
    return counters


def run(
    db_path: str,
    *,
    max_laws: int | None,
    dry_run: bool,
    resume: bool,
    network: bool = True,
    use_jlt_index: bool = True,
) -> dict[str, object]:
    conn = _connect(db_path)
    _ensure_tables(conn)
    refresh_id = _refresh_id()
    started = _now()
    mode = "dry-run" if dry_run else ("incremental" if resume else "full")
    totals = {
        "laws_processed": 0,
        "articles_filled": 0,
        "review_queue_added": 0,
        "skipped_no_source": 0,
    }
    audit_before = _audit_counts(conn)
    article_audit = _article_audit(conn)
    jlt_index: set[str] | None = None
    if network and use_jlt_index:
        jlt_index = set(_harvest_jlt_index())
    if not dry_run:
        conn.execute(
            "INSERT INTO am_law_translation_refresh_log "
            "(refresh_id, target_lang, started_at, mode) VALUES (?, 'en', ?, ?)",
            (refresh_id, started, mode),
        )
    for law in _candidate_laws(conn, max_laws, resume):
        try:
            c = _process_law(
                conn,
                law,
                dry_run=dry_run,
                refresh_id=refresh_id,
                network=network,
                jlt_index=jlt_index,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("process_law error %s: %s", law["canonical_id"], exc)
            continue
        totals["laws_processed"] += 1
        totals["articles_filled"] += c["filled"]
        totals["review_queue_added"] += c["review_queue_added"]
        totals["skipped_no_source"] += c["skipped_no_source"]
        if not dry_run:
            conn.commit()
    audit_after = _audit_counts(conn)
    if not dry_run:
        conn.execute(
            "UPDATE am_law_translation_refresh_log "
            "SET finished_at = ?, laws_processed = ?, articles_filled = ?, "
            " review_queue_added = ?, skipped_no_source = ? WHERE refresh_id = ?",
            (
                _now(),
                totals["laws_processed"],
                totals["articles_filled"],
                totals["review_queue_added"],
                totals["skipped_no_source"],
                refresh_id,
            ),
        )
        conn.commit()
    conn.close()
    return {
        "totals": totals,
        "audit_before": audit_before,
        "audit_after": audit_after,
        "article_audit": article_audit,
        "jlt_index_size": len(jlt_index) if jlt_index is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autonomath-db", default=DEFAULT_DB)
    parser.add_argument("--max-laws", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Skip HTTP fetches; classify URLs only (test mode)",
    )
    parser.add_argument(
        "--no-jlt-index",
        action="store_true",
        help="Skip JLT index harvest (rely on canonical_id only)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    result = run(
        args.autonomath_db,
        max_laws=args.max_laws,
        dry_run=args.dry_run,
        resume=args.resume,
        network=not args.no_network,
        use_jlt_index=not args.no_jlt_index,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "mode": "dry-run" if args.dry_run else "full",
                **result,
                "disclaimer": LICENSE_DISCLAIMER,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
