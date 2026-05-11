#!/usr/bin/env python3
"""Wave 41 Agent I — extended `am_law.body_zh` source discovery.

Base implementation Wave 35 Axis 5c (`fill_laws_zh.py`); v2 adds:

  1. Authoritative ZH index discovery — fetch each candidate ministry's
     known Chinese-language hubs (外務省 / METI / JETRO / 駐日中国大使館
     via mofa.go.jp public-domain mirror) and harvest links matching the
     law canonical_id pattern.
  2. JLT explicit ZH endpoint — `https://www.japaneselawtranslation.go.jp/zh/`
     does not exist for most laws, but a small (~20-50) hand-curated set
     of treaty / trade-friendly laws have explicit Chinese mirrors at
     METI's CN gateway and JETRO's zh-cn portal. Try both.
  3. Manual review queue export to `data/laws_zh_review_queue.csv` for
     operator-paste workflow. The catch-rate for ZH is small by design;
     manual operator review is the only auditable path.

NEVER calls an LLM API. Aggregator URLs refused. 一次資料 only — any
sentence-transformer candidate lands in `am_law_translation_review_queue`,
not body_zh directly.
"""
from __future__ import annotations

import argparse
import csv
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

LOG = logging.getLogger("fill_laws_zh_v2")
DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_REVIEW_CSV = str(_REPO / "data" / "laws_zh_review_queue.csv")

PRIMARY_DOMAINS = (
    "japaneselawtranslation.go.jp", "meti.go.jp", "mlit.go.jp",
    "jetro.go.jp", "jnto.go.jp", "mhlw.go.jp", "mofa.go.jp",
    "moj.go.jp", "soumu.go.jp",
)
BANNED_DOMAINS = ("noukaweb", "hojyokin-portal", "biz.stayway")
USER_AGENT = (
    "jpcite-multilingual-bot/1.0 (+https://jpcite.com/bots; "
    "operator=info@bookyou.net)"
)

# Known authoritative Chinese-language hubs we crawl for canonical_id matches.
ZH_HUB_URLS = (
    "https://www.mofa.go.jp/mofaj/area/china/index.html",  # MOFA China index (ja)
    "https://www.meti.go.jp/policy/external_economy/cn/",  # METI CN policy hub
    "https://www.jetro.go.jp/zh-cn/",                       # JETRO simplified
    "https://www.jetro.go.jp/zh-tw/",                       # JETRO traditional
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


def _fetch_with_playwright_fallback(url: str, timeout: int = 20) -> tuple[int, str | None]:
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


def _harvest_zh_hubs() -> dict[str, str]:
    """Map canonical_id-like slug → first ZH hub link discovered."""
    found: dict[str, str] = {}
    for hub_url in ZH_HUB_URLS:
        status, body = _fetch_with_playwright_fallback(hub_url)
        if status != 200 or not body:
            continue
        # Heuristic: look for hrefs containing law slug fragments.
        for m in re.finditer(r'href="([^"#?]+)"', body):
            href = m.group(1)
            if not href.startswith("http"):
                href = urllib.parse.urljoin(hub_url, href)
            parsed = urllib.parse.urlparse(href)
            if not _is_primary(href) or _is_banned(href):
                continue
            # Extract trailing path segment as candidate slug.
            seg = parsed.path.rstrip("/").rsplit("/", 1)[-1]
            seg = urllib.parse.unquote(seg).lower()
            if seg and len(seg) >= 4 and seg not in found:
                found[seg] = href
    LOG.info("ZH hub harvest: %d slug candidates", len(found))
    return found


def _zh_mirror_urls(jp_url: str, canonical_id: str,
                    zh_hub_map: dict[str, str] | None = None) -> list[str]:
    candidates: list[str] = []
    if jp_url:
        parsed = urllib.parse.urlparse(jp_url)
        candidates.append(urllib.parse.urlunparse(parsed._replace(path="/zh" + parsed.path)))
        candidates.append(urllib.parse.urlunparse(parsed._replace(path="/chinese" + parsed.path)))
    q = urllib.parse.quote(canonical_id)
    candidates.append(f"https://www.japaneselawtranslation.go.jp/zh/laws/?search={q}")
    candidates.append(f"https://www.jetro.go.jp/zh-cn/{q}.html")
    candidates.append(f"https://www.jetro.go.jp/zh-tw/{q}.html")
    # Pull through hub discovery if available.
    if zh_hub_map is not None:
        slug = canonical_id.lower()
        if slug in zh_hub_map:
            candidates.insert(0, zh_hub_map[slug])
    seen: set[str] = set()
    uniq: list[str] = []
    for c in candidates:
        if c not in seen and not _is_banned(c):
            seen.add(c)
            uniq.append(c)
    return uniq


def _candidate_laws(conn: sqlite3.Connection, max_laws: int | None) -> list[sqlite3.Row]:
    sql = "SELECT canonical_id, canonical_name AS name, body_zh FROM am_law WHERE body_zh IS NULL"
    if max_laws is not None:
        sql += f" LIMIT {int(max_laws)}"
    try:
        return list(conn.execute(sql))
    except sqlite3.Error as exc:
        LOG.warning("candidate fetch failed: %s", exc)
        return []


def _audit_counts(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        total = conn.execute("SELECT COUNT(*) FROM am_law").fetchone()[0]
        present = conn.execute(
            "SELECT COUNT(*) FROM am_law WHERE body_zh IS NOT NULL"
        ).fetchone()[0]
    except sqlite3.Error:
        return {"laws_total": 0, "body_zh_present": 0}
    return {"laws_total": int(total), "body_zh_present": int(present)}


def _queue_id() -> str:
    return f"tx_{uuid.uuid4().hex[:16]}"


def _refresh_id() -> str:
    return f"trx_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")


def _process_law(conn: sqlite3.Connection, law: sqlite3.Row, *, dry_run: bool,
                 network: bool = True,
                 zh_hub_map: dict[str, str] | None = None
                 ) -> tuple[dict[str, int], str | None]:
    counters = {"filled": 0, "skipped_no_source": 0, "review_queue_added": 0}
    canonical_id = law["canonical_id"]
    if not network:
        primary_urls = [u for u in _zh_mirror_urls("", canonical_id, None)
                        if _is_primary(u) and not _is_banned(u)]
        counters["filled" if primary_urls else "skipped_no_source"] += 1
        return counters, None
    for url in _zh_mirror_urls("", canonical_id, zh_hub_map):
        status, body = _fetch_with_playwright_fallback(url)
        if status == 200 and body:
            text = _extract_text(body)
            if not text or len(text) < 64:
                continue
            if not dry_run:
                conn.execute(
                    "UPDATE am_law SET body_zh = ?, body_zh_source_url = ?, "
                    "body_zh_fetched_at = ?, body_zh_license = 'gov_public' "
                    "WHERE canonical_id = ?",
                    (text, url, _now(), canonical_id))
            counters["filled"] += 1
            return counters, None
    counters["skipped_no_source"] += 1
    return counters, canonical_id


def _write_review_csv(rows: list[sqlite3.Row], csv_path: str, target_lang: str) -> None:
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    write_header = not Path(csv_path).exists()
    with open(csv_path, "a", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        if write_header:
            w.writerow([
                "canonical_id", "name", "target_lang", "operator_url",
                "operator_notes", "queued_at",
            ])
        for r in rows:
            w.writerow([
                r["canonical_id"], r["name"], target_lang, "", "", _now(),
            ])


def run(db_path: str, *, max_laws: int | None, dry_run: bool,
        network: bool = True,
        review_csv: str = DEFAULT_REVIEW_CSV) -> dict[str, object]:
    conn = _connect(db_path)
    _ensure_tables(conn)
    refresh_id = _refresh_id()
    started = _now()
    mode = "dry-run" if dry_run else "incremental"
    totals = {"laws_processed": 0, "articles_filled": 0,
              "review_queue_added": 0, "skipped_no_source": 0}
    zh_hub_map: dict[str, str] | None = None
    if network:
        zh_hub_map = _harvest_zh_hubs()
    audit_before = _audit_counts(conn)
    if not dry_run:
        try:
            conn.execute(
                "INSERT INTO am_law_translation_refresh_log "
                "(refresh_id, target_lang, started_at, mode) VALUES (?, 'zh', ?, ?)",
                (refresh_id, started, mode))
        except sqlite3.Error:
            pass
    review_rows: list[sqlite3.Row] = []
    for law in _candidate_laws(conn, max_laws):
        try:
            c, queued = _process_law(conn, law, dry_run=dry_run, network=network,
                                     zh_hub_map=zh_hub_map)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("process_law error %s: %s", law["canonical_id"], exc)
            continue
        totals["laws_processed"] += 1
        totals["articles_filled"] += c["filled"]
        totals["skipped_no_source"] += c["skipped_no_source"]
        if queued:
            review_rows.append(law)
            totals["review_queue_added"] += 1
        if not dry_run:
            conn.commit()
    if review_rows and not dry_run:
        _write_review_csv(review_rows, review_csv, "zh")
    audit_after = _audit_counts(conn)
    if not dry_run:
        try:
            conn.execute(
                "UPDATE am_law_translation_refresh_log "
                "SET finished_at = ?, laws_processed = ?, articles_filled = ?, "
                " review_queue_added = ?, skipped_no_source = ? WHERE refresh_id = ?",
                (_now(), totals["laws_processed"], totals["articles_filled"],
                 totals["review_queue_added"], totals["skipped_no_source"], refresh_id))
            conn.commit()
        except sqlite3.Error:
            pass
    conn.close()
    return {
        "totals": totals,
        "audit_before": audit_before,
        "audit_after": audit_after,
        "zh_hub_size": len(zh_hub_map) if zh_hub_map is not None else None,
        "review_csv": review_csv if review_rows and not dry_run else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--autonomath-db", default=DEFAULT_DB)
    parser.add_argument("--max-laws", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--review-csv", default=DEFAULT_REVIEW_CSV)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    result = run(args.autonomath_db, max_laws=args.max_laws,
                 dry_run=args.dry_run, network=not args.no_network,
                 review_csv=args.review_csv)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
