#!/usr/bin/env python3
"""Wave 35 Axis 5c — fill am_law.body_zh from ministry official 中文 pages.
NEVER calls an LLM API. 一次資料 only.
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

LOG = logging.getLogger("fill_laws_zh")
DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))

PRIMARY_DOMAINS = (
    "japaneselawtranslation.go.jp", "meti.go.jp", "mlit.go.jp",
    "jetro.go.jp", "jnto.go.jp", "mhlw.go.jp", "mofa.go.jp",
)
BANNED_DOMAINS = ("noukaweb", "hojyokin-portal", "biz.stayway")
USER_AGENT = (
    "jpcite-multilingual-bot/1.0 (+https://jpcite.com/bots; "
    "operator=info@bookyou.net)"
)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    for slug in ("240_law_en_full", "242_law_zh"):
        sql_path = _REPO / "scripts" / "migrations" / f"{slug}.sql"
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


def _zh_mirror_urls(jp_url: str, canonical_id: str) -> list[str]:
    candidates: list[str] = []
    if jp_url:
        parsed = urllib.parse.urlparse(jp_url)
        candidates.append(
            urllib.parse.urlunparse(parsed._replace(path="/zh" + parsed.path))
        )
        candidates.append(
            urllib.parse.urlunparse(parsed._replace(path="/chinese" + parsed.path))
        )
    q = urllib.parse.quote(canonical_id)
    candidates.append(f"https://www.japaneselawtranslation.go.jp/zh/laws/?search={q}")
    candidates.append(f"https://www.jetro.go.jp/zh-cn/{q}.html")
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _candidate_laws(conn: sqlite3.Connection, max_laws: int | None) -> list[sqlite3.Row]:
    sql = "SELECT canonical_id, name, body_zh FROM am_law WHERE body_zh IS NULL"
    if max_laws is not None:
        sql += f" LIMIT {int(max_laws)}"
    try:
        return list(conn.execute(sql))
    except sqlite3.Error as exc:
        LOG.warning("candidate fetch failed: %s", exc)
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
        rows = list(
            conn.execute(
                "SELECT canonical_id, body_zh, body_zh_source_url FROM am_law "
                "WHERE body_zh IS NOT NULL LIMIT 50"
            )
        )
    except sqlite3.Error:
        return None
    for r in rows:
        if r["body_zh"] and len(r["body_zh"]) > 256:
            return {
                "text": r["body_zh"],
                "source_url": r["body_zh_source_url"] or "",
                "score": 0.0,
                "model": "stub_first_match",
                "version": "v0",
            }
    return None


def _process_law(conn: sqlite3.Connection, law: sqlite3.Row, *, dry_run: bool,
                 network: bool = True) -> dict[str, int]:
    counters = {"filled": 0, "skipped_no_source": 0, "review_queue_added": 0}
    canonical_id = law["canonical_id"]
    if not network:
        primary_urls = [
            u for u in _zh_mirror_urls("", canonical_id)
            if _is_primary(u) and not _is_banned(u)
        ]
        if primary_urls:
            counters["filled"] += 1
        else:
            counters["skipped_no_source"] += 1
        return counters
    for url in _zh_mirror_urls("", canonical_id):
        status, body = _fetch(url)
        if status == 200 and body:
            text = _extract_text(body)
            if not text or len(text) < 64:
                continue
            if not dry_run:
                conn.execute(
                    "UPDATE am_law SET body_zh = ?, body_zh_source_url = ?, "
                    "body_zh_fetched_at = ?, body_zh_license = 'gov_public' "
                    "WHERE canonical_id = ?",
                    (text, url, _now(), canonical_id),
                )
            counters["filled"] += 1
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
            "VALUES (?, 'law', ?, 'zh', 'body', ?, ?, 'gov_public', ?, ?, ?, 'pending')",
            (_queue_id(), canonical_id, candidate["text"], candidate["source_url"],
             candidate["score"], candidate["model"], candidate["version"]),
        )
    counters["review_queue_added"] += 1
    return counters


def run(db_path: str, *, max_laws: int | None, dry_run: bool,
        network: bool = True) -> dict[str, int]:
    conn = _connect(db_path)
    _ensure_tables(conn)
    refresh_id = _refresh_id()
    started = _now()
    mode = "dry-run" if dry_run else "incremental"
    totals = {"laws_processed": 0, "articles_filled": 0,
              "review_queue_added": 0, "skipped_no_source": 0}
    if not dry_run:
        conn.execute(
            "INSERT INTO am_law_translation_refresh_log "
            "(refresh_id, target_lang, started_at, mode) VALUES (?, 'zh', ?, ?)",
            (refresh_id, started, mode),
        )
    for law in _candidate_laws(conn, max_laws):
        try:
            c = _process_law(conn, law, dry_run=dry_run, network=network)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("process_law error %s: %s", law["canonical_id"], exc)
            continue
        totals["laws_processed"] += 1
        totals["articles_filled"] += c["filled"]
        totals["review_queue_added"] += c["review_queue_added"]
        totals["skipped_no_source"] += c["skipped_no_source"]
        if not dry_run:
            conn.commit()
    if not dry_run:
        conn.execute(
            "UPDATE am_law_translation_refresh_log "
            "SET finished_at = ?, laws_processed = ?, articles_filled = ?, "
            " review_queue_added = ?, skipped_no_source = ? WHERE refresh_id = ?",
            (_now(), totals["laws_processed"], totals["articles_filled"],
             totals["review_queue_added"], totals["skipped_no_source"], refresh_id),
        )
        conn.commit()
    conn.close()
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autonomath-db", default=DEFAULT_DB)
    parser.add_argument("--max-laws", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-network", action="store_true",
                        help="Skip HTTP fetches; classify URLs only (test mode)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    totals = run(args.autonomath_db, max_laws=args.max_laws,
                 dry_run=args.dry_run, network=not args.no_network)
    print(json.dumps({"ok": True, "totals": totals}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
