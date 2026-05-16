#!/usr/bin/env python3
"""Wave 35 Axis 5b — fill programs.title_en / summary_en / eligibility_en
from official English ministry sub-paths. 一次資料 only, no LLM API.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from jpintel_mcp._jpcite_env_bridge import get_flag

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

LOG = logging.getLogger("fill_programs_en")
DEFAULT_DB = get_flag("JPCITE_DB_PATH", "JPINTEL_DB_PATH", str(_REPO / "data" / "jpintel.db"))

PRIMARY_DOMAINS = (
    "mhlw.go.jp",
    "meti.go.jp",
    "maff.go.jp",
    "mext.go.jp",
    "mlit.go.jp",
    "env.go.jp",
    "kantei.go.jp",
    "nta.go.jp",
    "fsa.go.jp",
    "jpo.go.jp",
    "jisha.go.jp",
    "smrj.go.jp",
    "chusho.meti.go.jp",
    "jfc.go.jp",
    "nichigin.go.jp",
    "jstage.jst.go.jp",
    "jetro.go.jp",
)
BANNED_DOMAINS = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "jgrants-portal.go.jp",
)
USER_AGENT = "jpcite-multilingual-bot/1.0 (+https://jpcite.com/bots; operator=info@bookyou.net)"


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    sql_path = _REPO / "scripts" / "migrations" / "241_programs_en.sql"
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


def _english_mirror_urls(source_url: str) -> list[str]:
    if not source_url:
        return []
    parsed = urllib.parse.urlparse(source_url)
    candidates = [
        urllib.parse.urlunparse(parsed._replace(path="/english" + parsed.path)),
        urllib.parse.urlunparse(parsed._replace(path="/e" + parsed.path)),
    ]
    if "/jp/" in parsed.path:
        candidates.append(
            urllib.parse.urlunparse(parsed._replace(path=parsed.path.replace("/jp/", "/en/", 1)))
        )
    if not parsed.netloc.startswith("en."):
        candidates.append(urllib.parse.urlunparse(parsed._replace(netloc="en." + parsed.netloc)))
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


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


def _extract_title(html_text: str) -> str | None:
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
    return None


def _queue_id() -> str:
    return f"ptx_{uuid.uuid4().hex[:16]}"


def _refresh_id() -> str:
    return f"prtx_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")


def _candidate_programs(conn: sqlite3.Connection, max_programs: int | None) -> list[sqlite3.Row]:
    try:
        sql = (
            "SELECT unified_id, primary_name, source_url, tier, translation_status "
            "FROM programs "
            "WHERE COALESCE(excluded, 0) = 0 AND tier IN ('S','A','B','C') "
            "  AND (translation_status IS NULL OR translation_status = 'unavailable') "
            "ORDER BY tier, unified_id"
        )
        if max_programs is not None:
            sql += f" LIMIT {int(max_programs)}"
        return list(conn.execute(sql))
    except sqlite3.Error as exc:
        LOG.warning("candidate fetch failed: %s", exc)
        return []


def _process_program(
    conn: sqlite3.Connection, program: sqlite3.Row, *, dry_run: bool, network: bool = True
) -> dict[str, int]:
    counters = {
        "filled": 0,
        "review_added": 0,
        "skipped_no_english_page": 0,
        "refused_aggregator": 0,
    }
    source_url = program["source_url"] or ""
    if _is_banned(source_url):
        counters["refused_aggregator"] += 1
        return counters
    urls = _english_mirror_urls(source_url)
    if not network:
        primary_urls = [u for u in urls if _is_primary(u) and not _is_banned(u)]
        counters["filled" if primary_urls else "skipped_no_english_page"] += 1
        return counters
    primary_hit: tuple[str, str] | None = None
    for u in urls:
        status, body = _fetch(u)
        if status == 200 and body and len(body) > 256:
            primary_hit = (u, body)
            break
    if primary_hit is None:
        counters["skipped_no_english_page"] += 1
        if not dry_run:
            conn.execute(
                "UPDATE programs SET translation_status = 'unavailable' "
                "WHERE unified_id = ? AND (translation_status IS NULL "
                "      OR translation_status = '')",
                (program["unified_id"],),
            )
        return counters
    url, body = primary_hit
    title = _extract_title(body)
    text = _extract_text(body)
    summary = (text[:2048] + "…") if len(text) > 2048 else text
    if not dry_run:
        conn.execute(
            "UPDATE programs SET title_en = ?, summary_en = ?, source_url_en = ?, "
            "translation_fetched_at = ?, translation_status = 'full' "
            "WHERE unified_id = ?",
            (title, summary, url, _now(), program["unified_id"]),
        )
    counters["filled"] += 1
    return counters


def run(
    db_path: str, *, max_programs: int | None, dry_run: bool, network: bool = True
) -> dict[str, int]:
    conn = _connect(db_path)
    _ensure_tables(conn)
    refresh_id = _refresh_id()
    started = _now()
    mode = "dry-run" if dry_run else "incremental"
    totals = {
        "programs_processed": 0,
        "programs_filled": 0,
        "review_queue_added": 0,
        "skipped_no_english_page": 0,
        "refused_aggregator": 0,
    }
    if not dry_run:
        conn.execute(
            "INSERT INTO programs_translation_refresh_log "
            "(refresh_id, target_lang, started_at, mode) VALUES (?, 'en', ?, ?)",
            (refresh_id, started, mode),
        )
    for prog in _candidate_programs(conn, max_programs):
        try:
            c = _process_program(conn, prog, dry_run=dry_run, network=network)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("process_program error %s: %s", prog["unified_id"], exc)
            continue
        totals["programs_processed"] += 1
        totals["programs_filled"] += c["filled"]
        totals["review_queue_added"] += c["review_added"]
        totals["skipped_no_english_page"] += c["skipped_no_english_page"]
        totals["refused_aggregator"] += c["refused_aggregator"]
        if not dry_run:
            conn.commit()
    if not dry_run:
        conn.execute(
            "UPDATE programs_translation_refresh_log "
            "SET finished_at = ?, programs_processed = ?, programs_filled = ?, "
            " review_queue_added = ?, skipped_no_english_page = ?, "
            " refused_aggregator = ? WHERE refresh_id = ?",
            (
                _now(),
                totals["programs_processed"],
                totals["programs_filled"],
                totals["review_queue_added"],
                totals["skipped_no_english_page"],
                totals["refused_aggregator"],
                refresh_id,
            ),
        )
        conn.commit()
    conn.close()
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jpintel-db", default=DEFAULT_DB)
    parser.add_argument("--max-programs", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Skip HTTP fetches; classify URLs only (test mode)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    totals = run(
        args.jpintel_db,
        max_programs=args.max_programs,
        dry_run=args.dry_run,
        network=not args.no_network,
    )
    print(json.dumps({"ok": True, "totals": totals}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
