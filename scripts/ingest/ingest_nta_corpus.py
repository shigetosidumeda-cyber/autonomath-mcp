"""Ingest NTA primary-source corpus into autonomath.db.

Targets (one --target per run, or --target all):
  saiketsu     — 国税不服審判所 公表裁決事例 (kfs.go.jp/service/JP/idx/{vol}.html)
  shitsugi     — 国税庁 質疑応答事例 (nta.go.jp/law/shitsugi/{cat}/01.htm)
  bunsho       — 国税庁 文書回答事例 (nta.go.jp/law/bunshokaito/{cat}/...)
  tsutatsu_idx — projection over am_law_article tsutatsu rows into nta_tsutatsu_index

Usage:
  python scripts/ingest/ingest_nta_corpus.py --target saiketsu --max-minutes 30
  python scripts/ingest/ingest_nta_corpus.py --target shitsugi --max-minutes 30
  python scripts/ingest/ingest_nta_corpus.py --target bunsho --max-minutes 30
  python scripts/ingest/ingest_nta_corpus.py --target tsutatsu_idx
  python scripts/ingest/ingest_nta_corpus.py --target all --max-minutes 30

Constraints:
  * 2 sec / req delay (政府サイトに優しく; robots.txt is permissive but we go slower).
  * Resumable: cursor file at data/autonomath/_nta_{target}_cursor.txt holds the
    last-processed key. On restart we skip every URL already INSERT-ed (UNIQUE
    on source_url makes this idempotent regardless).
  * Wall-clock cap via --max-minutes (default 30). Stops politely.
  * Encoding: try shift_jis first (kfs.go.jp + older nta.go.jp), fall back to
    utf-8 (newer bunshokaito pages).
  * No Anthropic API. No aggregator URLs.
  * License: 'gov_standard' (NTA + 国税不服審判所 利用規約 / PDL v1.0 ministry
    standard). source_url required on every row.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import ssl
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

try:
    import certifi

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "autonomath.db"
CURSOR_DIR = REPO_ROOT / "data" / "autonomath"
CURSOR_DIR.mkdir(parents=True, exist_ok=True)

KFS_BASE = "https://www.kfs.go.jp"
NTA_BASE = "https://www.nta.go.jp"
UA = "AutonoMath/0.1.0 (+https://bookyou.net; sss@bookyou.net)"

DELAY_SEC = 2.0  # 1 req / 2 sec — kinder than robots.txt would require

SHITSUGI_CATEGORIES = [
    "shotoku", "gensen", "joto", "sozoku", "hyoka",
    "hojin", "shohi", "inshi", "hotei",
]

BUNSHO_CATEGORIES = [
    ("shotoku", "02"),
    ("gensen", "03"),
    ("joto-sanrin", "04"),
    ("sozoku", "05"),
    ("zoyo", "06"),
    ("hyoka", "07"),
    ("hojin", "08"),
    ("shohi", "09"),
    ("shozei", "10"),
    ("sonota", "01"),
]

# 元号→西暦変換 (起点年)
ERA_BASE = {"令和": 2018, "平成": 1988, "昭和": 1925}
KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                "六": 6, "七": 7, "八": 8, "九": 9, "元": 1, "十": 10}


def _kanji_to_int(s: str) -> int | None:
    """Best-effort 漢数字 → int (handles 元 / 十 / mixed)."""
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    if "元" in s:
        return 1
    # Handle 二十三 / 三十 patterns
    if "十" in s:
        before, _, after = s.partition("十")
        b = KANJI_DIGITS.get(before, 1) if before else 1
        a = KANJI_DIGITS.get(after, 0) if after else 0
        return b * 10 + a
    # Concatenated 漢数字 e.g. 二〇二一
    if all(c in KANJI_DIGITS for c in s):
        return int("".join(str(KANJI_DIGITS[c]) for c in s))
    try:
        return int(s)
    except ValueError:
        return None


_ERA_DATE_RE = re.compile(r"(令和|平成|昭和)\s*([元一二三四五六七八九十〇\d]+)\s*年\s*([元一二三四五六七八九十〇\d]+)\s*月\s*([元一二三四五六七八九十〇\d]+)\s*日")


def parse_japanese_date(text: str) -> str | None:
    """Parse 令和3年3月26日 / 平成30年12月1日 → 'YYYY-MM-DD'."""
    if not text:
        return None
    m = _ERA_DATE_RE.search(text)
    if not m:
        return None
    era, y_raw, mo_raw, d_raw = m.groups()
    y = _kanji_to_int(y_raw)
    mo = _kanji_to_int(mo_raw)
    d = _kanji_to_int(d_raw)
    if y is None or mo is None or d is None:
        return None
    base = ERA_BASE.get(era)
    if base is None:
        return None
    year = base + y
    return f"{year:04d}-{mo:02d}-{d:02d}"


def fetch(url: str, *, retries: int = 3) -> str:
    """Fetch URL, decoding shift_jis or utf-8 as appropriate."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
                raw = resp.read()
                # Sniff encoding from <meta charset> if possible
                head = raw[:512].lower()
                if b"charset=utf-8" in head or b'charset="utf-8"' in head:
                    return raw.decode("utf-8", errors="replace")
                if b"charset=shift_jis" in head or b'charset="shift_jis"' in head:
                    return raw.decode("shift_jis", errors="replace")
                # Fallback: try shift_jis first (older NTA + KFS), then utf-8
                try:
                    return raw.decode("shift_jis")
                except UnicodeDecodeError:
                    return raw.decode("utf-8", errors="replace")
        except Exception as exc:
            last_err = exc
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url}: {last_err}")


def connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db), timeout=300.0, isolation_level=None)
    conn.execute("PRAGMA busy_timeout = 300000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def cursor_path(target: str) -> Path:
    return CURSOR_DIR / f"_nta_{target}_cursor.txt"


def read_cursor(target: str) -> str | None:
    p = cursor_path(target)
    if p.exists():
        return p.read_text(encoding="utf-8").strip() or None
    return None


def write_cursor(target: str, value: str) -> None:
    cursor_path(target).write_text(value, encoding="utf-8")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Saiketsu (国税不服審判所 公表裁決事例)
# ---------------------------------------------------------------------------

def discover_saiketsu_volumes() -> list[int]:
    """Read kfs.go.jp/service/JP/index.html and pull idx/{N}.html numbers."""
    html = fetch(f"{KFS_BASE}/service/JP/index.html")
    soup = BeautifulSoup(html, "html.parser")
    nums: set[int] = set()
    for a in soup.find_all("a", href=True):
        m = re.match(r"^idx/(\d+)\.html$", a["href"])
        if m:
            nums.add(int(m.group(1)))
    return sorted(nums)


def parse_volume_index(volume_no: int) -> list[tuple[str, str, str]]:
    """Return [(case_no, tax_type, decision_url), ...] for one volume."""
    url = f"{KFS_BASE}/service/JP/idx/{volume_no}.html"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="contents") or soup
    out: list[tuple[str, str, str]] = []
    current_tax_type = ""
    for el in content.descendants:
        if not hasattr(el, "name") or el.name is None:
            continue
        if el.name == "h2":
            current_tax_type = el.get_text(" ", strip=True).rstrip("関係").rstrip("法")
            continue
        if el.name == "a" and isinstance(el.get("href"), str):
            href = el["href"]
            m = re.match(r"^\.\./(\d+)/(\d+)/index\.html$", href)
            if m and int(m.group(1)) == volume_no:
                case_no = m.group(2)
                full_url = f"{KFS_BASE}/service/JP/{volume_no}/{case_no}/index.html"
                out.append((case_no, current_tax_type, full_url))
    return out


def parse_saiketsu_decision(volume_no: int, case_no: str, tax_type: str, url: str, html: str, fiscal_period: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    decision_date = parse_japanese_date(title)
    content = soup.find("div", id="contents") or soup
    # Drop nav/breadcrumbs by removing them if present
    for sel in ["nav", "header", "footer"]:
        for tag in content.find_all(sel):
            tag.decompose()
    fulltext = content.get_text("\n", strip=True)
    # First substantive paragraph as summary
    summary = ""
    for p in content.find_all("p"):
        t = p.get_text(" ", strip=True)
        if len(t) > 30 and "ホーム" not in t and ">>" not in t:
            summary = t
            break
    return {
        "volume_no": volume_no,
        "case_no": case_no,
        "decision_date": decision_date,
        "fiscal_period": fiscal_period,
        "tax_type": tax_type,
        "title": title,
        "decision_summary": summary[:2000] if summary else None,
        "fulltext": fulltext,
        "source_url": url,
    }


def parse_volume_period(volume_no: int) -> str:
    """Pull the fiscal_period label off the volume index page."""
    url = f"{KFS_BASE}/service/JP/idx/{volume_no}.html"
    try:
        html = fetch(url)
    except Exception:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def ingest_saiketsu(conn: sqlite3.Connection, *, max_seconds: float, recent_only_years: int = 5) -> dict[str, int]:
    """Ingest saiketsu volumes from newest to oldest. Cursor is the last-volume:case_no done."""
    t_start = time.time()
    counts = {"volumes_seen": 0, "decisions_seen": 0, "decisions_inserted": 0}
    cursor = read_cursor("saiketsu")
    last_vol, last_case = 0, ""
    if cursor:
        try:
            v, c = cursor.split(":", 1)
            last_vol, last_case = int(v), c
        except ValueError:
            pass

    volumes = discover_saiketsu_volumes()
    print(f"[saiketsu] discovered {len(volumes)} volumes (range {volumes[0]}..{volumes[-1]})", flush=True)
    # Newest first. Restrict to recent N years if requested.
    volumes_desc = sorted(volumes, reverse=True)
    if recent_only_years > 0:
        # ~4 volumes per year (3-month chunks)
        keep = recent_only_years * 4
        volumes_desc = volumes_desc[:keep]
        print(f"[saiketsu] focusing on {len(volumes_desc)} most recent volumes (~{recent_only_years} years)", flush=True)

    for volume_no in volumes_desc:
        if last_vol and volume_no > last_vol:
            # Already past this volume during a prior run
            continue
        if time.time() - t_start > max_seconds:
            print(f"[saiketsu] time cap hit at vol={volume_no}", flush=True)
            break
        counts["volumes_seen"] += 1
        try:
            fiscal_period = parse_volume_period(volume_no)
            time.sleep(DELAY_SEC)
            cases = parse_volume_index(volume_no)
        except Exception as exc:
            print(f"[saiketsu] vol={volume_no} index failed: {exc}", flush=True)
            time.sleep(DELAY_SEC)
            continue
        for case_no, tax_type, dec_url in cases:
            if last_vol == volume_no and case_no <= last_case:
                continue
            if time.time() - t_start > max_seconds:
                print(f"[saiketsu] time cap hit at vol={volume_no} case={case_no}", flush=True)
                write_cursor("saiketsu", f"{volume_no}:{case_no}")
                return counts
            counts["decisions_seen"] += 1
            # Skip if already in DB
            existing = conn.execute(
                "SELECT 1 FROM nta_saiketsu WHERE source_url=?", (dec_url,)
            ).fetchone()
            if existing:
                write_cursor("saiketsu", f"{volume_no}:{case_no}")
                continue
            try:
                page_html = fetch(dec_url)
            except Exception as exc:
                print(f"[saiketsu] vol={volume_no}/{case_no} fetch failed: {exc}", flush=True)
                time.sleep(DELAY_SEC)
                continue
            try:
                row = parse_saiketsu_decision(volume_no, case_no, tax_type, dec_url, page_html, fiscal_period)
                conn.execute(
                    """INSERT OR IGNORE INTO nta_saiketsu
                       (volume_no, case_no, decision_date, fiscal_period, tax_type,
                        title, decision_summary, fulltext, source_url, license, ingested_at)
                       VALUES (?,?,?,?,?,?,?,?,?,'gov_standard',?)""",
                    (row["volume_no"], row["case_no"], row["decision_date"], row["fiscal_period"],
                     row["tax_type"], row["title"], row["decision_summary"], row["fulltext"],
                     row["source_url"], now_iso()),
                )
                if conn.total_changes > 0:
                    counts["decisions_inserted"] += 1
                write_cursor("saiketsu", f"{volume_no}:{case_no}")
            except Exception as exc:
                print(f"[saiketsu] vol={volume_no}/{case_no} parse failed: {exc}", flush=True)
            time.sleep(DELAY_SEC)
    return counts


# ---------------------------------------------------------------------------
# Shitsugi (国税庁 質疑応答事例)
# ---------------------------------------------------------------------------

def discover_shitsugi_pages(category: str) -> list[str]:
    """Walk the category index (multi-page) and return all page URLs."""
    out: list[str] = []
    seen: set[str] = set()
    # Index pages numbered 01, 02, ... per category.
    for idx_no in range(1, 50):  # reasonable cap
        idx_url = f"{NTA_BASE}/law/shitsugi/{category}/{idx_no:02d}.htm"
        try:
            html = fetch(idx_url)
        except Exception:
            break
        time.sleep(DELAY_SEC)
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find("div", id="contents") or soup
        any_found = False
        for a in content.find_all("a", href=True):
            href = a["href"]
            m = re.match(rf"^/law/shitsugi/{category}/(\d+)/(\d+)\.htm$", href) \
                or re.match(rf"^(\d+)/(\d+)\.htm$", href)
            if m:
                # Build full URL
                if href.startswith("/"):
                    full = NTA_BASE + href
                else:
                    full = f"{NTA_BASE}/law/shitsugi/{category}/{href}"
                if full not in seen:
                    seen.add(full)
                    out.append(full)
                    any_found = True
        if not any_found:
            break  # No more index pages
    return out


def parse_shitsugi_page(url: str, html: str, category: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not title or "指定されたページ" in title or "ページを表示できません" in title:
        return None
    content = soup.find("div", id="contents") or soup
    text = content.get_text("\n", strip=True)
    # Carve out 【照会要旨】 / 【回答要旨】 / 【関係法令通達】
    def carve(label: str, *, until: list[str]) -> str:
        idx = text.find(label)
        if idx < 0:
            return ""
        start = idx + len(label)
        ends = [text.find(u, start) for u in until]
        ends = [e for e in ends if e > 0]
        end = min(ends) if ends else len(text)
        return text[start:end].strip()

    question = carve("【照会要旨】", until=["【回答要旨】", "【関係法令通達】"])
    answer = carve("【回答要旨】", until=["【関係法令通達】", "注記"])
    related_law = carve("【関係法令通達】", until=["注記"])
    if not question or not answer:
        return None
    # slug from URL: /law/shitsugi/shotoku/01/05.htm -> shotoku-01-05
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    # parts: ['law', 'shitsugi', '<cat>', '<idx>', '<file>.htm']
    slug = "-".join(parts[2:]).replace(".htm", "")
    return {
        "slug": slug,
        "category": category,
        "question": question,
        "answer": answer,
        "related_law": related_law or None,
        "source_url": url,
    }


def ingest_shitsugi(conn: sqlite3.Connection, *, max_seconds: float) -> dict[str, int]:
    t_start = time.time()
    counts = {"pages_seen": 0, "pages_inserted": 0, "categories_done": 0}
    cursor = read_cursor("shitsugi") or ""

    for category in SHITSUGI_CATEGORIES:
        if time.time() - t_start > max_seconds:
            print(f"[shitsugi] time cap at category={category}", flush=True)
            break
        if cursor and cursor.startswith("done:") and category in cursor.split(":", 1)[1].split(","):
            continue
        try:
            page_urls = discover_shitsugi_pages(category)
        except Exception as exc:
            print(f"[shitsugi] cat={category} discovery failed: {exc}", flush=True)
            continue
        print(f"[shitsugi] cat={category}: {len(page_urls)} pages discovered", flush=True)
        for url in page_urls:
            if time.time() - t_start > max_seconds:
                write_cursor("shitsugi", f"partial:{category}:{url}")
                return counts
            counts["pages_seen"] += 1
            existing = conn.execute(
                "SELECT 1 FROM nta_shitsugi WHERE source_url=?", (url,)
            ).fetchone()
            if existing:
                continue
            try:
                page_html = fetch(url)
            except Exception as exc:
                print(f"[shitsugi] {url} fetch failed: {exc}", flush=True)
                time.sleep(DELAY_SEC)
                continue
            try:
                row = parse_shitsugi_page(url, page_html, category)
                if row:
                    conn.execute(
                        """INSERT OR IGNORE INTO nta_shitsugi
                           (slug, category, question, answer, related_law,
                            source_url, license, ingested_at)
                           VALUES (?,?,?,?,?,?,'gov_standard',?)""",
                        (row["slug"], row["category"], row["question"], row["answer"],
                         row["related_law"], row["source_url"], now_iso()),
                    )
                    if conn.total_changes > 0:
                        counts["pages_inserted"] += 1
            except Exception as exc:
                print(f"[shitsugi] {url} parse failed: {exc}", flush=True)
            time.sleep(DELAY_SEC)
        counts["categories_done"] += 1
        write_cursor("shitsugi", f"partial:done:{category}")
    return counts


# ---------------------------------------------------------------------------
# Bunsho kaitou (文書回答事例)
# ---------------------------------------------------------------------------

def discover_bunsho_entries(category: str, idx_no: str) -> list[str]:
    """Walk one category index page and return doc URLs."""
    idx_url = f"{NTA_BASE}/law/bunshokaito/{category}/{idx_no}.htm"
    try:
        html = fetch(idx_url)
    except Exception:
        return []
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("div", id="contents") or soup
    out: list[str] = []
    seen: set[str] = set()
    for a in content.find_all("a", href=True):
        href = a["href"]
        # Match patterns like /law/bunshokaito/shotoku/250416/index.htm
        # or /about/organization/tokyo/bunshokaito/shotoku/260218/index.htm
        if "/bunshokaito/" not in href:
            continue
        if href.endswith((".pdf", ".html#")):
            continue
        if href.endswith("01.htm") or href == f"/law/bunshokaito/{category}/{idx_no}.htm":
            continue
        # Build absolute URL
        if href.startswith("/"):
            full = NTA_BASE + href
        elif href.startswith("http"):
            full = href
        else:
            continue
        if "/index.htm" in full or full.endswith(".htm"):
            if full not in seen:
                seen.add(full)
                out.append(full)
    return out


def parse_bunsho_page(url: str, html: str, category: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not title or "指定されたページ" in title or "ページを表示できません" in title:
        return None
    content = soup.find("div", id="contents") or soup
    text = content.get_text("\n", strip=True)
    # Date is usually visible in the footer or near the title
    response_date = parse_japanese_date(text[:2000]) or parse_japanese_date(text[-2000:])
    # 文書回答 sections: 【照会の趣旨】 + 【回答】(or 【回答内容】 / 別紙) + various
    def carve(label: str, *, until: list[str]) -> str:
        idx = text.find(label)
        if idx < 0:
            return ""
        start = idx + len(label)
        ends = [text.find(u, start) for u in until]
        ends = [e for e in ends if e > 0]
        end = min(ends) if ends else len(text)
        return text[start:end].strip()

    request_summary = carve("【照会の趣旨】", until=["【事前照会者の", "【事前照会の事実関係】", "【回答】", "【回答内容】", "（注）"])
    if not request_summary:
        request_summary = carve("【事前照会の趣旨】", until=["【回答】", "【回答内容】"])
    answer = carve("【回答】", until=["（参考）", "（注）"])
    if not answer:
        answer = carve("【回答内容】", until=["（参考）", "（注）"])
    if not request_summary and not answer:
        # Use full text as answer fallback for older PDF-style entries
        answer = text[:5000]
    # slug from URL
    parsed = urllib.parse.urlparse(url)
    parts = [p for p in parsed.path.split("/") if p and p != "index.htm"]
    slug = "-".join(parts).replace(".htm", "")
    return {
        "slug": slug,
        "category": category,
        "response_date": response_date,
        "request_summary": request_summary[:5000] if request_summary else (title[:500] if title else None),
        "answer": answer[:50000] if answer else None,
        "source_url": url,
    }


def ingest_bunsho(conn: sqlite3.Connection, *, max_seconds: float) -> dict[str, int]:
    t_start = time.time()
    counts = {"pages_seen": 0, "pages_inserted": 0}
    cursor = read_cursor("bunsho") or ""

    for category, idx_no in BUNSHO_CATEGORIES:
        if time.time() - t_start > max_seconds:
            print(f"[bunsho] time cap at cat={category}", flush=True)
            break
        if cursor.startswith("done:") and category in cursor[5:].split(","):
            continue
        try:
            entries = discover_bunsho_entries(category, idx_no)
        except Exception as exc:
            print(f"[bunsho] cat={category} discovery failed: {exc}", flush=True)
            continue
        print(f"[bunsho] cat={category}: {len(entries)} entries discovered", flush=True)
        time.sleep(DELAY_SEC)
        for url in entries:
            if time.time() - t_start > max_seconds:
                write_cursor("bunsho", f"partial:{category}:{url}")
                return counts
            counts["pages_seen"] += 1
            existing = conn.execute(
                "SELECT 1 FROM nta_bunsho_kaitou WHERE source_url=?", (url,)
            ).fetchone()
            if existing:
                continue
            try:
                page_html = fetch(url)
            except Exception as exc:
                print(f"[bunsho] {url} fetch failed: {exc}", flush=True)
                time.sleep(DELAY_SEC)
                continue
            try:
                row = parse_bunsho_page(url, page_html, category)
                if row and (row["request_summary"] or row["answer"]):
                    conn.execute(
                        """INSERT OR IGNORE INTO nta_bunsho_kaitou
                           (slug, category, response_date, request_summary, answer,
                            source_url, license, ingested_at)
                           VALUES (?,?,?,?,?,?,'gov_standard',?)""",
                        (row["slug"], row["category"], row["response_date"],
                         row["request_summary"], row["answer"],
                         row["source_url"], now_iso()),
                    )
                    if conn.total_changes > 0:
                        counts["pages_inserted"] += 1
            except Exception as exc:
                print(f"[bunsho] {url} parse failed: {exc}", flush=True)
            time.sleep(DELAY_SEC)
    return counts


# ---------------------------------------------------------------------------
# Tsutatsu index — populate nta_tsutatsu_index from existing am_law_article
# ---------------------------------------------------------------------------

LAW_PREFIX_MAP = {
    "law:hojin-zei-tsutatsu": "法基通",
    "law:shotoku-zei-tsutatsu": "所基通",
    "law:shohi-zei-tsutatsu": "消基通",
    "law:zaisan-hyoka-tsutatsu": "評基通",
    "law:sozoku-zei-tsutatsu": "相基通",
}


def ingest_tsutatsu_idx(conn: sqlite3.Connection) -> dict[str, int]:
    counts = {"rows_indexed": 0}
    rows = conn.execute(
        """SELECT law_canonical_id, article_number, title, text_full,
                  source_url, source_fetched_at
           FROM am_law_article
           WHERE article_kind='tsutatsu'
             AND law_canonical_id IN (?,?,?,?,?)""",
        tuple(LAW_PREFIX_MAP.keys()),
    ).fetchall()
    refreshed_at = now_iso()
    for row in rows:
        prefix = LAW_PREFIX_MAP.get(row["law_canonical_id"])
        if not prefix:
            continue
        code = f"{prefix}-{row['article_number']}"
        body_excerpt = (row["text_full"] or "")[:500]
        try:
            conn.execute(
                """INSERT INTO nta_tsutatsu_index
                   (code, law_canonical_id, article_number, title, body_excerpt,
                    source_url, last_amended, refreshed_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(code) DO UPDATE SET
                     title=excluded.title,
                     body_excerpt=excluded.body_excerpt,
                     source_url=excluded.source_url,
                     refreshed_at=excluded.refreshed_at""",
                (code, row["law_canonical_id"], row["article_number"],
                 row["title"], body_excerpt, row["source_url"],
                 row["source_fetched_at"], refreshed_at),
            )
            counts["rows_indexed"] += 1
        except Exception as exc:
            print(f"[tsutatsu_idx] {code} failed: {exc}", flush=True)
    return counts


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True,
                    choices=["saiketsu", "shitsugi", "bunsho", "tsutatsu_idx", "all"])
    ap.add_argument("--max-minutes", type=float, default=30.0)
    ap.add_argument("--recent-years", type=int, default=5,
                    help="For saiketsu, restrict to most recent N years (0=all)")
    ap.add_argument("--db", default=str(DB_PATH))
    args = ap.parse_args()

    conn = connect(Path(args.db))
    max_sec = args.max_minutes * 60.0

    targets = [args.target] if args.target != "all" else ["tsutatsu_idx", "saiketsu", "shitsugi", "bunsho"]
    overall = {}
    t_start = time.time()
    for target in targets:
        elapsed = time.time() - t_start
        budget = max_sec - elapsed
        if budget <= 30:
            print(f"[{target}] skipped — no time budget left ({budget:.1f}s)", flush=True)
            break
        print(f"[{target}] starting (budget={budget:.0f}s)", flush=True)
        try:
            if target == "saiketsu":
                overall[target] = ingest_saiketsu(conn, max_seconds=budget, recent_only_years=args.recent_years)
            elif target == "shitsugi":
                overall[target] = ingest_shitsugi(conn, max_seconds=budget)
            elif target == "bunsho":
                overall[target] = ingest_bunsho(conn, max_seconds=budget)
            elif target == "tsutatsu_idx":
                overall[target] = ingest_tsutatsu_idx(conn)
        except Exception as exc:
            print(f"[{target}] FAILED: {exc}", flush=True)
            import traceback
            traceback.print_exc()
        print(f"[{target}] result: {overall.get(target)}", flush=True)

    conn.close()
    print(f"\n[summary] {overall}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
