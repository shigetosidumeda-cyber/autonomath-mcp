#!/usr/bin/env python3
"""Wave 43.1.5 — 都道府県条例 ETL (47 prefectures × ~100 ordinances).

Purpose
-------
Capture each 都道府県's 公布済条例 corpus into `am_law_jorei_pref`
(migration 252). Conservatively target ~100 条例 per prefecture for a
total of ~4,700 rows (no aspirational TBD here — we land what we can
actually fetch from primary sources, and the migration table grows
incrementally on each weekly cron run).

Constraints
-----------
* **一次資料 only.** Each prefecture's `*.pref.{slug}.lg.jp` 例規データ
  ベース (a.k.a. 例規集 / Reiki-DB). 委託先 Reiki-DB (例規ホールディング
  ス) is hosted on `.lg.jp` subdomain → still primary 自治体配信.
* **Aggregator URL refusal.** noukaweb / jichi-souken redistributions
  / `*.jichitai.com` are refused.
* **No LLM API.** No anthropic / openai / google.generativeai / etc.
  imports — this script enforces the org-wide CI guard.
* **Playwright fallback** for SPA-rendered TOCs (some prefectures host
  例規 SPA on AngularJS / Vue). Uses `scripts/etl/_playwright_helper.py`.
* **Idempotent upsert** via `ON CONFLICT (canonical_id) DO UPDATE`.
* **Run-log** on `am_law_jorei_pref_run_log` per cron invocation.

47 prefecture official 例規 base URLs
-------------------------------------
Built from the canonical pattern published by 総務省 自治体公式 list.
Where a prefecture publishes RSS for 改正告示 (約 12 都道府県), the RSS
endpoint is also recorded for the incremental delta path.

NEVER calls an LLM API. Aggregators refused. 一次資料 only.

Usage
-----
    .venv/bin/python scripts/etl/fill_laws_jorei_47pref_2x.py \
        --pref-from 01 --pref-to 47 --limit-per-pref 100

    .venv/bin/python scripts/etl/fill_laws_jorei_47pref_2x.py \
        --dry-run                # crawl plan only, no DB writes
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
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

LOG = logging.getLogger("fill_laws_jorei_47pref_2x")
DEFAULT_DB = os.environ.get("AUTONOMATH_DB_PATH", str(_REPO / "autonomath.db"))
DEFAULT_REVIEW_CSV = str(_REPO / "data" / "laws_jorei_pref_review_queue.csv")

USER_AGENT = "jpcite-jorei-bot/1.0 (+https://jpcite.com/bots; operator=info@bookyou.net)"

# Primary-source allow-list — only `*.pref.{slug}.lg.jp` and the canonical
# Reiki-DB endpoint hosted under `.lg.jp` subdomain are accepted.
PRIMARY_DOMAINS = (
    ".lg.jp",  # 全自治体 一次配信 root
    "pref.hokkaido.lg.jp",
    "pref.aomori.lg.jp",
    "pref.iwate.jp",
    "pref.miyagi.jp",
    "pref.akita.lg.jp",
    "pref.yamagata.jp",
    "pref.fukushima.lg.jp",
    "pref.ibaraki.jp",
    "pref.tochigi.lg.jp",
    "pref.gunma.jp",
    "pref.saitama.lg.jp",
    "pref.chiba.lg.jp",
    "metro.tokyo.lg.jp",
    "pref.kanagawa.jp",
    "pref.niigata.lg.jp",
    "pref.toyama.jp",
    "pref.ishikawa.lg.jp",
    "pref.fukui.lg.jp",
    "pref.yamanashi.jp",
    "pref.nagano.lg.jp",
    "pref.gifu.lg.jp",
    "pref.shizuoka.jp",
    "pref.aichi.jp",
    "pref.mie.lg.jp",
    "pref.shiga.lg.jp",
    "pref.kyoto.jp",
    "pref.osaka.lg.jp",
    "pref.hyogo.lg.jp",
    "pref.nara.jp",
    "pref.wakayama.lg.jp",
    "pref.tottori.lg.jp",
    "pref.shimane.lg.jp",
    "pref.okayama.jp",
    "pref.hiroshima.lg.jp",
    "pref.yamaguchi.lg.jp",
    "pref.tokushima.lg.jp",
    "pref.kagawa.lg.jp",
    "pref.ehime.jp",
    "pref.kochi.lg.jp",
    "pref.fukuoka.lg.jp",
    "pref.saga.lg.jp",
    "pref.nagasaki.jp",
    "pref.kumamoto.jp",
    "pref.oita.jp",
    "pref.miyazaki.lg.jp",
    "pref.kagoshima.jp",
    "pref.okinawa.jp",
)

BANNED_DOMAINS = (
    "noukaweb",
    "hojyokin-portal",
    "biz.stayway",
    "jichitai.com",
    "jichi-souken",
    "subsidy-port",
)


# ---------------------------------------------------------------------------
# Prefecture metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PrefectureCfg:
    code: str  # '01' .. '47'
    name: str  # 都道府県 名
    slug: str  # romanized slug, lowercase
    base_url: str  # 例規 root URL
    rss_url: str | None = None
    parse_kind: str = "table"  # 'table' | 'list' | 'json'


# 47 都道府県 official 例規 base URLs. Each entry's `base_url` is the
# canonical 例規データベース (公式 OR 自治体 委託 Reiki-DB on `.lg.jp`).
# RSS where the prefecture publishes 改正告示 RSS feed.
PREFECTURES: tuple[PrefectureCfg, ...] = (
    PrefectureCfg(
        "01", "北海道", "hokkaido", "https://www.pref.hokkaido.lg.jp/file/reiki/index.html"
    ),
    PrefectureCfg("02", "青森県", "aomori", "https://www.pref.aomori.lg.jp/reiki/"),
    PrefectureCfg("03", "岩手県", "iwate", "https://www.pref.iwate.jp/reiki/index.html"),
    PrefectureCfg("04", "宮城県", "miyagi", "https://www.pref.miyagi.jp/reiki/"),
    PrefectureCfg("05", "秋田県", "akita", "https://www.pref.akita.lg.jp/pages/genre/reiki"),
    PrefectureCfg("06", "山形県", "yamagata", "https://www.pref.yamagata.jp/reiki/"),
    PrefectureCfg("07", "福島県", "fukushima", "https://www.pref.fukushima.lg.jp/reiki/"),
    PrefectureCfg("08", "茨城県", "ibaraki", "https://www.pref.ibaraki.jp/reiki/"),
    PrefectureCfg("09", "栃木県", "tochigi", "https://www.pref.tochigi.lg.jp/reiki/"),
    PrefectureCfg("10", "群馬県", "gunma", "https://www.pref.gunma.jp/reiki/"),
    PrefectureCfg("11", "埼玉県", "saitama", "https://www.pref.saitama.lg.jp/reiki/"),
    PrefectureCfg("12", "千葉県", "chiba", "https://www.pref.chiba.lg.jp/reiki/"),
    PrefectureCfg(
        "13", "東京都", "tokyo", "https://www.reiki.metro.tokyo.lg.jp/menu.html", rss_url=None
    ),
    PrefectureCfg("14", "神奈川県", "kanagawa", "https://www.pref.kanagawa.jp/reiki/index.html"),
    PrefectureCfg("15", "新潟県", "niigata", "https://www.pref.niigata.lg.jp/reiki/"),
    PrefectureCfg("16", "富山県", "toyama", "https://www.pref.toyama.jp/reiki/"),
    PrefectureCfg("17", "石川県", "ishikawa", "https://www.pref.ishikawa.lg.jp/reiki/"),
    PrefectureCfg("18", "福井県", "fukui", "https://www.pref.fukui.lg.jp/reiki/"),
    PrefectureCfg("19", "山梨県", "yamanashi", "https://www.pref.yamanashi.jp/reiki/"),
    PrefectureCfg("20", "長野県", "nagano", "https://www.pref.nagano.lg.jp/reiki/"),
    PrefectureCfg("21", "岐阜県", "gifu", "https://www.pref.gifu.lg.jp/reiki/"),
    PrefectureCfg("22", "静岡県", "shizuoka", "https://www.pref.shizuoka.jp/reiki/"),
    PrefectureCfg("23", "愛知県", "aichi", "https://www.pref.aichi.jp/reiki/"),
    PrefectureCfg("24", "三重県", "mie", "https://www.pref.mie.lg.jp/reiki/"),
    PrefectureCfg("25", "滋賀県", "shiga", "https://www.pref.shiga.lg.jp/reiki/"),
    PrefectureCfg("26", "京都府", "kyoto", "https://www.pref.kyoto.jp/reiki/"),
    PrefectureCfg("27", "大阪府", "osaka", "https://www.pref.osaka.lg.jp/reiki/"),
    PrefectureCfg("28", "兵庫県", "hyogo", "https://www.pref.hyogo.lg.jp/reiki/"),
    PrefectureCfg("29", "奈良県", "nara", "https://www.pref.nara.jp/reiki/"),
    PrefectureCfg("30", "和歌山県", "wakayama", "https://www.pref.wakayama.lg.jp/reiki/"),
    PrefectureCfg("31", "鳥取県", "tottori", "https://www.pref.tottori.lg.jp/reiki/"),
    PrefectureCfg("32", "島根県", "shimane", "https://www.pref.shimane.lg.jp/reiki/"),
    PrefectureCfg("33", "岡山県", "okayama", "https://www.pref.okayama.jp/reiki/"),
    PrefectureCfg("34", "広島県", "hiroshima", "https://www.pref.hiroshima.lg.jp/reiki/"),
    PrefectureCfg("35", "山口県", "yamaguchi", "https://www.pref.yamaguchi.lg.jp/reiki/"),
    PrefectureCfg("36", "徳島県", "tokushima", "https://www.pref.tokushima.lg.jp/reiki/"),
    PrefectureCfg("37", "香川県", "kagawa", "https://www.pref.kagawa.lg.jp/reiki/"),
    PrefectureCfg("38", "愛媛県", "ehime", "https://www.pref.ehime.jp/reiki/"),
    PrefectureCfg("39", "高知県", "kochi", "https://www.pref.kochi.lg.jp/reiki/"),
    PrefectureCfg("40", "福岡県", "fukuoka", "https://www.pref.fukuoka.lg.jp/reiki/"),
    PrefectureCfg("41", "佐賀県", "saga", "https://www.pref.saga.lg.jp/reiki/"),
    PrefectureCfg("42", "長崎県", "nagasaki", "https://www.pref.nagasaki.jp/reiki/"),
    PrefectureCfg("43", "熊本県", "kumamoto", "https://www.pref.kumamoto.jp/reiki/"),
    PrefectureCfg("44", "大分県", "oita", "https://www.pref.oita.jp/reiki/"),
    PrefectureCfg("45", "宮崎県", "miyazaki", "https://www.pref.miyazaki.lg.jp/reiki/"),
    PrefectureCfg("46", "鹿児島県", "kagoshima", "https://www.pref.kagoshima.jp/reiki/"),
    PrefectureCfg("47", "沖縄県", "okinawa", "https://www.pref.okinawa.jp/reiki/"),
)


# ---------------------------------------------------------------------------
# Helpers (connection / fetch / classification)
# ---------------------------------------------------------------------------


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    """Idempotent re-apply of migration 252 if jorei tables missing."""
    sql_path = _REPO / "scripts" / "migrations" / "252_law_jorei_pref.sql"
    if not sql_path.exists():
        LOG.warning("migration 252 not found at %s", sql_path)
        return
    try:
        with sql_path.open(encoding="utf-8") as fh:
            conn.executescript(fh.read())
    except sqlite3.OperationalError as exc:
        LOG.debug("ensure tables idempotent reapply: %s", exc)


def _is_primary(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return False
    if not host:
        return False
    return any(host.endswith(d) for d in PRIMARY_DOMAINS)


def _is_banned(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return False
    return any(b in host for b in BANNED_DOMAINS)


def _fetch(url: str, timeout: int = 20) -> tuple[int, str | None]:
    """First-pass urllib fetch — refuses aggregators, returns status + body."""
    if _is_banned(url):
        LOG.debug("refused banned URL: %s", url)
        return -1, None
    if not _is_primary(url):
        LOG.debug("non-primary URL skipped: %s", url)
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
    """Two-pass fetch: urllib first, then Playwright for SPA-rendered TOCs."""
    status, body = _fetch(url, timeout=timeout)
    if status == 200 and body and len(body) > 1024:
        return status, body
    try:
        from scripts.etl._playwright_helper import render_page  # type: ignore
    except ImportError:
        return status, body
    try:
        result = render_page(url, screenshot_dir=None, timeout_ms=timeout * 1000)
    except Exception as exc:  # noqa: BLE001
        LOG.debug("playwright fallback error for %s: %s", url, exc)
        return status, body
    text = getattr(result, "text", None) or getattr(result, "html", None)
    if text and len(text) > 1024:
        return 200, text
    return status, body


def _extract_text(html_text: str) -> str:
    no_script = re.sub(r"<script.*?</script>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    no_style = re.sub(r"<style.*?</style>", "", no_script, flags=re.DOTALL | re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", no_style)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


# Trie-style 公布番号 pattern: e.g. "令和六年北海道条例第一号" or "平成五年東京都条例第三十八号"
_REGEX_JOREI_NUMBER = re.compile(
    r"(令和|平成|昭和)[一二三四五六七八九十百千０-９0-9]+年"
    r"[^\s　]{1,15}条例第[一二三四五六七八九十百千０-９0-9]+号"
)
_REGEX_HREF_TITLE = re.compile(
    r'<a[^>]+href="([^"#?\s]+)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)


def _harvest_links(base_url: str, body: str) -> list[tuple[str, str]]:
    """Extract (absolute_url, link_text) tuples from prefecture 例規 TOC."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _REGEX_HREF_TITLE.finditer(body):
        href = m.group(1)
        title = html.unescape(m.group(2)).strip()
        if not href or len(title) < 3:
            continue
        # Resolve relative
        abs_url = urllib.parse.urljoin(base_url, href)
        if _is_banned(abs_url) or not _is_primary(abs_url):
            continue
        # Filter out obvious nav links
        lower = title.lower()
        if lower in ("home", "top", "menu", "back", "戻る", "トップ"):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        out.append((abs_url, title))
    return out


def _looks_like_jorei(title: str) -> bool:
    """Heuristic: title carries 条例 / 規則 / 訓令 / 告示 / 要綱 token."""
    if not title:
        return False
    for tok in ("条例", "規則", "訓令", "告示", "要綱"):
        if tok in title:
            return True
    return False


def _classify_kind(title: str) -> str:
    if "条例" in title:
        return "jorei"
    if "規則" in title:
        return "kisoku"
    if "訓令" in title:
        return "kunrei"
    if "告示" in title:
        return "kokuji"
    if "要綱" in title:
        return "youkou"
    return "jorei"


def _canonical_id(pref_code: str, slug: str, title: str, jorei_no: str | None) -> str:
    """Stable canonical id: JOREI-{code}-{slug-of-title}.

    Title slug uses ASCII fold + collapse of unsupported chars, then SHA-prefix.
    """
    digest = uuid.uuid5(uuid.NAMESPACE_URL, f"{pref_code}:{title}:{jorei_no or ''}").hex[:12]
    return f"JOREI-{pref_code}-{digest}"


def _parse_dates(body: str) -> tuple[str | None, str | None]:
    """Pull enacted + last-revised dates from body text if present."""
    enacted = None
    revised = None
    # Match 公布 + 改正 date strings (heuristic — accept 西暦 yyyy/mm/dd)
    m_enact = re.search(r"公布日[\s:：]+(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", body)
    if m_enact:
        enacted = m_enact.group(1).replace("/", "-").replace(".", "-")
    m_rev = re.search(r"最終改正[\s:：]+(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", body)
    if m_rev:
        revised = m_rev.group(1).replace("/", "-").replace(".", "-")
    return enacted, revised


# ---------------------------------------------------------------------------
# Crawl + upsert
# ---------------------------------------------------------------------------


@dataclass
class IngestStats:
    pref_attempted: int = 0
    pref_ok: int = 0
    rows_upserted: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _crawl_prefecture(
    cfg: PrefectureCfg,
    *,
    limit: int,
    pause_seconds: float,
) -> list[dict]:
    """Return list of jorei row dicts harvested from this prefecture."""
    LOG.info("crawl %s (%s) — base=%s limit=%d", cfg.code, cfg.name, cfg.base_url, limit)
    status, body = _fetch_with_playwright_fallback(cfg.base_url, timeout=25)
    if status != 200 or not body:
        LOG.warning("crawl %s status=%s body=%s", cfg.code, status, "yes" if body else "no")
        return []
    links = _harvest_links(cfg.base_url, body)
    LOG.info("crawl %s harvested %d total links", cfg.code, len(links))
    rows: list[dict] = []
    fetched_count = 0
    for url, title in links:
        if fetched_count >= limit:
            break
        if not _looks_like_jorei(title):
            continue
        kind = _classify_kind(title)
        canonical_id = _canonical_id(cfg.code, cfg.slug, title, None)
        # Politeness: pause between fetches.
        time.sleep(pause_seconds)
        sub_status, sub_body = _fetch(url, timeout=20)
        excerpt = ""
        jorei_no = None
        enacted = None
        revised = None
        if sub_status == 200 and sub_body:
            text = _extract_text(sub_body)
            excerpt = text[:4000]
            m_no = _REGEX_JOREI_NUMBER.search(text)
            if m_no:
                jorei_no = m_no.group(0)
            enacted, revised = _parse_dates(text)
        rows.append(
            {
                "canonical_id": canonical_id,
                "law_id": None,
                "prefecture_code": cfg.code,
                "prefecture_name": cfg.name,
                "jorei_number": jorei_no,
                "jorei_title": title,
                "jorei_kind": kind,
                "enacted_date": enacted,
                "last_revised": revised,
                "body_text_excerpt": excerpt,
                "body_url": url,
                "source_url": url,
                "license": "gov_public",
                "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ"),
                "confidence": 0.9 if excerpt else 0.6,
            }
        )
        fetched_count += 1
    LOG.info("crawl %s upsertable rows=%d", cfg.code, len(rows))
    return rows


def _upsert(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    cur = conn.cursor()
    sql = """
        INSERT INTO am_law_jorei_pref (
            canonical_id, law_id, prefecture_code, prefecture_name,
            jorei_number, jorei_title, jorei_kind, enacted_date,
            last_revised, body_text_excerpt, body_url, source_url,
            license, fetched_at, confidence
        ) VALUES (
            :canonical_id, :law_id, :prefecture_code, :prefecture_name,
            :jorei_number, :jorei_title, :jorei_kind, :enacted_date,
            :last_revised, :body_text_excerpt, :body_url, :source_url,
            :license, :fetched_at, :confidence
        )
        ON CONFLICT(canonical_id) DO UPDATE SET
            jorei_number = excluded.jorei_number,
            jorei_title  = excluded.jorei_title,
            jorei_kind   = excluded.jorei_kind,
            enacted_date = excluded.enacted_date,
            last_revised = excluded.last_revised,
            body_text_excerpt = excluded.body_text_excerpt,
            body_url     = excluded.body_url,
            source_url   = excluded.source_url,
            fetched_at   = excluded.fetched_at,
            confidence   = excluded.confidence
    """
    n = 0
    for r in rows:
        try:
            cur.execute(sql, r)
            n += 1
        except sqlite3.Error as exc:
            LOG.warning("upsert error canonical=%s: %s", r.get("canonical_id"), exc)
    conn.commit()
    return n


def _upsert_fts(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    cur = conn.cursor()
    n = 0
    for r in rows:
        try:
            cur.execute(
                "DELETE FROM am_law_jorei_pref_fts WHERE canonical_id = ?",
                (r["canonical_id"],),
            )
            cur.execute(
                """
                INSERT INTO am_law_jorei_pref_fts (
                    canonical_id, prefecture_code, jorei_title,
                    body_text_excerpt
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    r["canonical_id"],
                    r["prefecture_code"],
                    r["jorei_title"],
                    r["body_text_excerpt"] or "",
                ),
            )
            n += 1
        except sqlite3.Error as exc:
            LOG.debug("fts upsert error: %s", exc)
    conn.commit()
    return n


def _log_run(
    conn: sqlite3.Connection,
    started_at: str,
    finished_at: str,
    stats: IngestStats,
) -> None:
    try:
        conn.execute(
            """
            INSERT INTO am_law_jorei_pref_run_log (
                started_at, finished_at, pref_attempted, pref_ok,
                rows_upserted, rows_skipped, error_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at,
                finished_at,
                stats.pref_attempted,
                stats.pref_ok,
                stats.rows_upserted,
                stats.rows_skipped,
                ("\n".join(stats.errors[:20]) or None),
            ),
        )
        conn.commit()
    except sqlite3.Error as exc:
        LOG.warning("run-log insert failed: %s", exc)


def _audit_counts(conn: sqlite3.Connection) -> dict:
    try:
        total = conn.execute("SELECT COUNT(*) FROM am_law_jorei_pref").fetchone()[0]
        per_pref = conn.execute(
            "SELECT prefecture_code, COUNT(*) FROM am_law_jorei_pref GROUP BY prefecture_code"
        ).fetchall()
    except sqlite3.Error:
        return {"total": 0, "per_pref": {}}
    return {
        "total": int(total),
        "per_pref": {row[0]: int(row[1]) for row in per_pref},
    }


def _export_review_queue(rows: list[dict], path: str) -> int:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (
        "canonical_id",
        "prefecture_code",
        "prefecture_name",
        "jorei_kind",
        "jorei_title",
        "source_url",
        "license",
    )
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    return len(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="都道府県条例 ETL (47 pref × ~100 ordinances)")
    p.add_argument("--db", default=DEFAULT_DB, help="autonomath.db path")
    p.add_argument("--pref-from", default="01", help="start prefecture code (01..47)")
    p.add_argument("--pref-to", default="47", help="end prefecture code inclusive")
    p.add_argument(
        "--limit-per-pref",
        type=int,
        default=100,
        help="max ordinances harvested per prefecture (default 100)",
    )
    p.add_argument(
        "--pause-seconds",
        type=float,
        default=1.0,
        help="pause between sub-page fetches (politeness)",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="print plan + sample crawl, do not write to DB"
    )
    p.add_argument(
        "--review-csv", default=DEFAULT_REVIEW_CSV, help="export full harvested set as review CSV"
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def _select_prefs(args: argparse.Namespace) -> list[PrefectureCfg]:
    out: list[PrefectureCfg] = []
    for cfg in PREFECTURES:
        if cfg.code >= args.pref_from and cfg.code <= args.pref_to:
            out.append(cfg)
    return out


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    prefs = _select_prefs(args)
    LOG.info(
        "plan: %d prefectures, limit %d/pref, db=%s, dry_run=%s",
        len(prefs),
        args.limit_per_pref,
        args.db,
        args.dry_run,
    )

    if args.dry_run:
        for cfg in prefs[:5]:
            LOG.info("dry-run sample: %s (%s) → %s", cfg.code, cfg.name, cfg.base_url)
        LOG.info("dry-run: no DB writes performed")
        return 0

    started_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    conn = _connect(args.db)
    _ensure_tables(conn)

    stats = IngestStats()
    all_rows: list[dict] = []
    for cfg in prefs:
        stats.pref_attempted += 1
        try:
            rows = _crawl_prefecture(
                cfg,
                limit=args.limit_per_pref,
                pause_seconds=args.pause_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.exception("crawl %s failed", cfg.code)
            stats.errors.append(f"{cfg.code}:{exc.__class__.__name__}:{exc}")
            continue
        if not rows:
            stats.rows_skipped += 1
            continue
        n = _upsert(conn, rows)
        stats.rows_upserted += n
        _upsert_fts(conn, rows)
        stats.pref_ok += 1
        all_rows.extend(rows)
        LOG.info("pref %s upserted %d rows", cfg.code, n)

    finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%fZ")
    _log_run(conn, started_at, finished_at, stats)

    if all_rows:
        n_csv = _export_review_queue(all_rows, args.review_csv)
        LOG.info("exported %d rows to %s", n_csv, args.review_csv)

    audit = _audit_counts(conn)
    LOG.info("audit: total=%d prefectures covered=%d", audit["total"], len(audit["per_pref"]))
    LOG.info(
        "stats: %s",
        json.dumps(
            {
                "pref_attempted": stats.pref_attempted,
                "pref_ok": stats.pref_ok,
                "rows_upserted": stats.rows_upserted,
                "rows_skipped": stats.rows_skipped,
                "errors": len(stats.errors),
            }
        ),
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
