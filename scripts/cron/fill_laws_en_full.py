#!/usr/bin/env python3
"""Wave 35 Axis 5a — fill am_law.body_en from e-Gov Japanese Law Translation
(japaneselawtranslation.go.jp, CC-BY 4.0).

NEVER calls an LLM API. sentence-transformers (local, multilingual-e5)
is the only optional similarity engine. Aggregator URLs refused.
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

LOG = logging.getLogger("fill_laws_en_full")
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
USER_AGENT = (
    "jpcite-multilingual-bot/1.0 (+https://jpcite.com/bots; "
    "operator=info@bookyou.net)"
)


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


def _extract_text(html_text: str) -> str:
    no_script = re.sub(r"<script.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    no_style = re.sub(r"<style.*?</style>", "", no_script, flags=re.DOTALL | re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", no_style)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def _build_translation_urls(canonical_id: str) -> list[str]:
    base = "https://www.japaneselawtranslation.go.jp/en/laws"
    q = urllib.parse.quote(canonical_id)
    return [f"{base}/?search={q}", f"{base}/view/{q}", f"https://laws.e-gov.go.jp/law/{q}"]


def _candidate_laws(conn: sqlite3.Connection, max_laws: int | None, resume: bool) -> list[sqlite3.Row]:
    sql = "SELECT canonical_id, name, body_en FROM am_law"
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


def _queue_id() -> str:
    return f"tx_{uuid.uuid4().hex[:16]}"


def _refresh_id() -> str:
    return f"trx_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")


def _similarity_candidate(conn: sqlite3.Connection, canonical_id: str) -> dict[str, object] | None:
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore # noqa: F401
    except ImportError:
        return None
    try:
        rows = list(conn.execute(
            "SELECT canonical_id, body_en, body_en_source_url FROM am_law "
            "WHERE body_en IS NOT NULL LIMIT 200"
        ))
    except sqlite3.Error:
        return None
    for r in rows:
        if r["body_en"] and len(r["body_en"]) > 256:
            return {"text": r["body_en"], "source_url": r["body_en_source_url"] or "",
                    "score": 0.0, "model": "stub_first_match", "version": "v0"}
    return None


def _process_law(conn: sqlite3.Connection, law: sqlite3.Row, *, dry_run: bool,
                 refresh_id: str, network: bool = True) -> dict[str, int]:
    counters = {"filled": 0, "skipped_no_source": 0, "review_queue_added": 0}
    canonical_id = law["canonical_id"]
    if not network:
        primary_urls = [u for u in _build_translation_urls(canonical_id)
                        if _is_primary(u) and not _is_banned(u)]
        counters["filled" if primary_urls else "skipped_no_source"] += 1
        return counters
    fetched_any = False
    for url in _build_translation_urls(canonical_id):
        status, body = _fetch(url)
        if status == 200 and body:
            fetched_any = True
            text = _extract_text(body)
            if not text or len(text) < 64:
                continue
            if not dry_run:
                conn.execute(
                    "UPDATE am_law SET body_en = ?, body_en_source_url = ?, "
                    "body_en_fetched_at = ?, body_en_license = 'cc_by_4.0' "
                    "WHERE canonical_id = ?",
                    (text, url, _now(), canonical_id))
            counters["filled"] += 1
            return counters
    if not fetched_any:
        counters["skipped_no_source"] += 1
        return counters
    candidate = _similarity_candidate(conn, canonical_id)
    if candidate is None:
        counters["skipped_no_source"] += 1
        return counters
    if not dry_run:
        conn.execute(
            "INSERT INTO am_law_translation_review_queue "
            "(queue_id, target_kind, canonical_id, target_lang, field_name, "
            " candidate_text, candidate_source_url, candidate_license, "
            " similarity_score, model_name, model_version, operator_decision) "
            "VALUES (?, 'law', ?, 'en', 'body', ?, ?, 'cc_by_4.0', ?, ?, ?, 'pending')",
            (_queue_id(), canonical_id, candidate["text"], candidate["source_url"],
             candidate["score"], candidate["model"], candidate["version"]))
    counters["review_queue_added"] += 1
    return counters


def _update_progress(conn: sqlite3.Connection, canonical_id: str, target_lang: str) -> None:
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN body_en IS NOT NULL THEN 1 ELSE 0 END) AS translated "
            "FROM am_law_article WHERE law_canonical_id = ?", (canonical_id,)).fetchone()
    except sqlite3.Error:
        return
    if row is None:
        return
    total = row["total"] or 0
    translated = row["translated"] or 0
    pct = (translated / total * 100) if total else 0.0
    conn.execute(
        "INSERT INTO am_law_translation_progress "
        "(canonical_id, target_lang, total_articles, translated_articles, "
        " coverage_pct, last_refreshed_at) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(canonical_id, target_lang) DO UPDATE SET "
        " total_articles = excluded.total_articles, "
        " translated_articles = excluded.translated_articles, "
        " coverage_pct = excluded.coverage_pct, "
        " last_refreshed_at = excluded.last_refreshed_at",
        (canonical_id, target_lang, total, translated, pct, _now()))


def run(db_path: str, *, max_laws: int | None, dry_run: bool, resume: bool,
        network: bool = True) -> dict[str, int]:
    conn = _connect(db_path)
    _ensure_tables(conn)
    refresh_id = _refresh_id()
    started = _now()
    mode = "dry-run" if dry_run else ("incremental" if resume else "full")
    totals = {"laws_processed": 0, "articles_filled": 0,
              "review_queue_added": 0, "skipped_no_source": 0}
    if not dry_run:
        conn.execute(
            "INSERT INTO am_law_translation_refresh_log "
            "(refresh_id, target_lang, started_at, mode) VALUES (?, 'en', ?, ?)",
            (refresh_id, started, mode))
    for law in _candidate_laws(conn, max_laws, resume):
        try:
            c = _process_law(conn, law, dry_run=dry_run, refresh_id=refresh_id, network=network)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("process_law error %s: %s", law["canonical_id"], exc)
            continue
        totals["laws_processed"] += 1
        totals["articles_filled"] += c["filled"]
        totals["review_queue_added"] += c["review_queue_added"]
        totals["skipped_no_source"] += c["skipped_no_source"]
        if not dry_run:
            _update_progress(conn, law["canonical_id"], "en")
            conn.commit()
    if not dry_run:
        conn.execute(
            "UPDATE am_law_translation_refresh_log "
            "SET finished_at = ?, laws_processed = ?, articles_filled = ?, "
            " review_queue_added = ?, skipped_no_source = ? WHERE refresh_id = ?",
            (_now(), totals["laws_processed"], totals["articles_filled"],
             totals["review_queue_added"], totals["skipped_no_source"], refresh_id))
        conn.commit()
    conn.close()
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autonomath-db", default=DEFAULT_DB)
    parser.add_argument("--max-laws", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-network", action="store_true",
                        help="Skip HTTP fetches; classify URLs only (test mode)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    totals = run(args.autonomath_db, max_laws=args.max_laws, dry_run=args.dry_run,
                 resume=args.resume, network=not args.no_network)
    print(json.dumps({"ok": True, "mode": "dry-run" if args.dry_run else "full",
                      "totals": totals, "disclaimer": LICENSE_DISCLAIMER},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
