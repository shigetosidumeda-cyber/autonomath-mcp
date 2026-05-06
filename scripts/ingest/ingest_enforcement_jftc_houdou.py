#!/usr/bin/env python3
"""Ingest JFTC (公正取引委員会) 報道発表 enforcement actions into autonomath.db.

Scope (2026-04-25):
    JFTC publishes 排除措置命令 / 課徴金納付命令 / 確約計画認定 / 審決 via
    報道発表資料 at https://www.jftc.go.jp/houdou/pressrelease/index.html.
    The list is split by year (2020..2026) and month (jan..dec). Each
    monthly index page contains <li><a href="…">(令和Y年M月D日)タイトル</a></li>
    rows. Detail pages have a structured table with 法人番号 / 名称 / 所在地.

    The companion script `ingest_enforcement_jftc.py` targets the
    /dk/ichiran/ structured listing (≈50 rows R2..R6 排除措置 + 確約 only).
    THIS script extends coverage by walking houdou/pressrelease/ which
    additionally includes 課徴金納付命令 (景表法 + 独禁法), 警告, 勧告, etc.
    Together the two scripts give significantly more JFTC enforcement
    coverage. Insertion is idempotent on (issuing_authority, issuance_date,
    target_name).

Source license:
    PDL v1.0 (公共データ利用規約 第1.0版) — see /kiyaku/index.html. Attribution:
        出典: 公正取引委員会ホームページ (https://www.jftc.go.jp/)
    Aggregators (biz.stayway, prtimes, nikkei, wikipedia) are BANNED per
    CLAUDE.md. We cite only jftc.go.jp URLs.

Schema mapping (am_enforcement_detail.enforcement_kind enum):
    排除措置命令         → business_improvement
    課徴金納付命令       → fine
    確約計画(の)認定     → other
    審決                 → other
    勧告 / 警告          → investigation  (lighter administrative measure)

Dedup key:
    (issuing_authority='公正取引委員会', issuance_date, target_name).
    Matches existing rows from /dk/ichiran/ ingest so re-running is safe.

CLI:
    python scripts/ingest/ingest_enforcement_jftc_houdou.py
    python scripts/ingest/ingest_enforcement_jftc_houdou.py --years 2020,2021,2022,2023,2024,2025
    python scripts/ingest/ingest_enforcement_jftc_houdou.py --max-inserts 150
    python scripts/ingest/ingest_enforcement_jftc_houdou.py --dry-run -v
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    import requests  # type: ignore
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(
        f"missing dep: {exc}. pip install requests beautifulsoup4",
        file=sys.stderr,
    )
    sys.exit(1)

_LOG = logging.getLogger("autonomath.ingest_jftc_houdou")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net) ingest-jftc-houdou (contact=ops@jpcite.com)"
BASE = "https://www.jftc.go.jp"
INDEX_URL = f"{BASE}/houdou/pressrelease/index.html"
HTTP_TIMEOUT = 60
RATE_SLEEP = 1.0  # polite 1 req/sec/host

DEFAULT_YEARS = ["2020", "2021", "2022", "2023", "2024", "2025"]
MONTHS = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)

# Title-keyword → enforcement_kind. Order matters — more specific tokens
# first. We only retain rows whose title matches one of these.
KIND_ORDER: tuple[tuple[str, str], ...] = (
    ("排除措置命令", "business_improvement"),
    ("課徴金納付命令", "fine"),
    ("確約計画", "other"),  # ...の認定 / の申請
    ("確約手続", "other"),
    ("審決", "other"),
    ("勧告", "investigation"),
    ("警告", "investigation"),
)

KIND_LABEL = {
    "business_improvement": "排除措置命令",
    "fine": "課徴金納付命令",
    "other": "確約計画認定/審決",
    "investigation": "勧告/警告",
}

# Date / number / 法人番号 patterns
WAREKI_RE = re.compile(
    r"(令和|平成)\s*(元|[0-9０-９]+)\s*年\s*"
    r"([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)
HOUJIN_RE = re.compile(r"\b([0-9]{13})\b")
AMOUNT_RE = re.compile(r"課徴金(?:の)?額[^\d]{0,30}?([0-9,０-９，]{2,20})\s*円")
AMOUNT_RE_ALT = re.compile(r"([0-9,０-９，]{2,20})\s*円(?:の課徴金|を支払)")

# Article extractor — first 法律条文 mentioned in summary section.
ARTICLE_RE = re.compile(
    r"(独占禁止法|私的独占の禁止及び公正取引の確保に関する法律|景品表示法|"
    r"不当景品類及び不当表示防止法|下請代金支払遅延等防止法)"
    r"(?:第\s*[0-9０-９]+\s*条(?:[第の]\s*[0-9０-９]+(?:\s*項)?)?)?"
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", text).strip()


def _strip_cell(el: Any) -> str:
    if el is None:
        return ""
    return _normalize(el.get_text(separator=" ", strip=True))


def _wareki_to_iso(text: str) -> str | None:
    """Convert 令和X年Y月Z日 / 平成X年Y月Z日 to ISO yyyy-mm-dd."""
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    m = WAREKI_RE.search(text)
    if not m:
        return None
    era, yr, mo, dy = m.group(1), m.group(2), m.group(3), m.group(4)
    yr_i = 1 if yr == "元" else int(yr)
    if era == "令和":
        year = 2018 + yr_i
    elif era == "平成":
        year = 1988 + yr_i
    else:
        return None
    try:
        return f"{year:04d}-{int(mo):02d}-{int(dy):02d}"
    except ValueError:
        return None


def _slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^0-9A-Za-z_\-぀-ヿ一-鿿々]", "", text)
    return text[:max_len] or "unknown"


def _amount_to_yen(s: str) -> int | None:
    if not s:
        return None
    digits = re.sub(r"[^0-9]", "", unicodedata.normalize("NFKC", s))
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    # sanity: reject single-digit / page numbers
    return n if n >= 1000 else None


def _classify_kind(title: str) -> tuple[str, str] | None:
    """Return (kind_token_jp, enforcement_kind) or None when not enforcement."""
    for token, kind in KIND_ORDER:
        if token in title:
            return token, kind
    return None


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class HttpClient:
    def __init__(self, *, user_agent: str = USER_AGENT) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self._last: float = 0.0

    def get(self, url: str) -> requests.Response | None:
        delta = time.monotonic() - self._last
        if delta < RATE_SLEEP:
            time.sleep(RATE_SLEEP - delta)
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=HTTP_TIMEOUT)
                self._last = time.monotonic()
                if resp.status_code == 200:
                    return resp
                if resp.status_code == 404:
                    return None
                last_err = RuntimeError(f"{resp.status_code} for {url}")
            except requests.RequestException as exc:
                last_err = exc
            time.sleep(2**attempt)
        _LOG.warning("fetch failed after retries: %s: %s", url, last_err)
        return None


# ---------------------------------------------------------------------------
# Listing parser
# ---------------------------------------------------------------------------

LIST_LINK_RE = re.compile(
    r"^\s*\(\s*(令和|平成)\s*[元0-9０-９]+\s*年\s*[0-9０-９]+\s*月\s*"
    r"[0-9０-９]+\s*日\s*\)\s*(.+?)\s*$"
)


@dataclass
class ListingEntry:
    issuance_date: str  # ISO yyyy-mm-dd
    title: str  # title without "(date)" prefix
    raw_label: str  # full anchor text including date prefix
    detail_url: str
    kind_token_jp: str  # 排除措置命令 / 課徴金納付命令 / etc.
    enforcement_kind: str
    year: str
    month: str


def parse_monthly_index(html: str, *, year: str, month: str, base_url: str) -> list[ListingEntry]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[ListingEntry] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Restrict to detail pages within this month folder.
        if not href:
            continue
        absurl = urljoin(base_url, href)
        if f"/houdou/pressrelease/{year}/{month}/" not in absurl:
            continue
        if absurl.rstrip("/").endswith("index.html"):
            continue
        # Skip non-html (PDFs etc. live one click further in).
        if not absurl.lower().endswith(".html"):
            continue
        anchor = _normalize(a.get_text(" ", strip=True))
        if not anchor:
            continue
        m = LIST_LINK_RE.match(anchor)
        if not m:
            continue
        # Extract date from anchor — full anchor text starts with (令和Y年…日).
        date_iso = _wareki_to_iso(anchor)
        if not date_iso:
            continue
        title = m.group(2).strip()
        kind = _classify_kind(title)
        if not kind:
            continue
        token, enf = kind
        out.append(
            ListingEntry(
                issuance_date=date_iso,
                title=title,
                raw_label=anchor,
                detail_url=absurl,
                kind_token_jp=token,
                enforcement_kind=enf,
                year=year,
                month=month,
            )
        )
    # Dedup within page (some lists repeat the same anchor in nav/footer).
    seen: set[str] = set()
    unique: list[ListingEntry] = []
    for e in out:
        if e.detail_url in seen:
            continue
        seen.add(e.detail_url)
        unique.append(e)
    return unique


# ---------------------------------------------------------------------------
# Detail parser
# ---------------------------------------------------------------------------


@dataclass
class DetailInfo:
    target_names: list[str] = field(default_factory=list)
    houjin_bangous: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    summary_text: str = ""
    amount_yen: int | None = None
    related_law_ref: str | None = None
    pdf_urls: list[str] = field(default_factory=list)


def parse_detail_page(html: str, source_url: str) -> DetailInfo:
    soup = BeautifulSoup(html, "html.parser")
    info = DetailInfo()

    # Walk every table and extract "法人番号 / 名称 / 所在地" rows. The page
    # may have multiple sets when there are several defendants — keep order.
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        label = _strip_cell(cells[0])
        value = _strip_cell(cells[1])
        if not label or not value:
            continue
        if label in ("法人番号",):
            m = HOUJIN_RE.search(value)
            if m:
                info.houjin_bangous.append(m.group(1))
        elif label in ("名称", "商号", "事業者名"):
            info.target_names.append(value[:255])
        elif label in ("所在地", "住所", "本店所在地"):
            info.addresses.append(value[:255])

    # Body text — first 2000 chars after the title block, used for amount /
    # article match and reason summary.
    body_chunks: list[str] = []
    for sel in ("div.area_main", "main", "div.main_inner", "article", "body"):
        node = soup.select_one(sel)
        if node:
            txt = _normalize(node.get_text(" ", strip=True))
            if len(txt) > 200:
                body_chunks.append(txt)
                break
    body = body_chunks[0] if body_chunks else _normalize(soup.get_text(" ", strip=True))
    info.summary_text = body[:4000]

    # Amount extraction — try the labelled pattern then alt.
    amt: int | None = None
    m = AMOUNT_RE.search(body)
    if not m:
        m = AMOUNT_RE_ALT.search(body)
    if m:
        amt = _amount_to_yen(m.group(1))
    info.amount_yen = amt

    # Article extraction.
    am = ARTICLE_RE.search(body)
    if am:
        info.related_law_ref = am.group(0)[:255]

    # PDF links.
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().endswith(".pdf"):
            info.pdf_urls.append(urljoin(source_url, href))
    info.pdf_urls = info.pdf_urls[:10]
    return info


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def ensure_jftc_authority(cur: sqlite3.Cursor) -> str:
    cur.execute(
        "SELECT canonical_id FROM am_authority WHERE canonical_id=?",
        ("authority:jftc",),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        """INSERT INTO am_authority
               (canonical_id, canonical_name, canonical_en, level, website)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "authority:jftc",
            "公正取引委員会",
            "JFTC",
            "agency",
            "https://www.jftc.go.jp/",
        ),
    )
    return "authority:jftc"


def existing_dedup_keys(cur: sqlite3.Cursor) -> set[tuple[str, str]]:
    cur.execute(
        "SELECT issuance_date, target_name FROM am_enforcement_detail WHERE issuing_authority=?",
        ("公正取引委員会",),
    )
    out: set[tuple[str, str]] = set()
    for iso_date, name in cur.fetchall():
        if iso_date and name:
            out.add((iso_date, _normalize(name)))
    return out


def existing_canonical_ids(cur: sqlite3.Cursor) -> set[str]:
    cur.execute(
        "SELECT canonical_id FROM am_entities WHERE record_kind='enforcement' "
        "AND authority_canonical=?",
        ("authority:jftc",),
    )
    return {row[0] for row in cur.fetchall()}


def build_canonical_id(
    issuance_date: str,
    title: str,
    detail_url: str,
) -> str:
    slug = _slugify(title, max_len=32)
    # Use the URL stem as a unique suffix to avoid collisions when titles
    # are identical (rare but possible across years).
    stem = detail_url.rsplit("/", 1)[-1].split(".", 1)[0]
    stem_slug = _slugify(stem, max_len=20)
    base = f"enforcement:jftc-houdou:{issuance_date}:{slug}"
    if stem_slug and stem_slug != "unknown":
        base = f"{base}:{stem_slug}"
    return base[:255]


def insert_one(
    cur: sqlite3.Cursor,
    *,
    canonical_id: str,
    listing: ListingEntry,
    detail: DetailInfo,
    chosen_target: str,
    houjin_bangou: str | None,
    related_law_ref: str | None,
    reason_summary: str,
    amount_yen: int | None,
    now_iso: str,
) -> bool:
    """Insert one am_entities + am_enforcement_detail pair. Returns True on
    fresh insert. Returns False if INSERT OR IGNORE produced a no-op (the
    canonical_id already exists)."""
    raw = {
        "source": "jftc:houdou_pressrelease",
        "year": listing.year,
        "month": listing.month,
        "title": listing.title,
        "raw_label": listing.raw_label,
        "kind_token_jp": listing.kind_token_jp,
        "enforcement_kind": listing.enforcement_kind,
        "detail_url": listing.detail_url,
        "issuance_date": listing.issuance_date,
        "all_target_names": detail.target_names,
        "all_houjin_bangous": detail.houjin_bangous,
        "addresses": detail.addresses,
        "amount_yen": amount_yen,
        "related_law_ref": related_law_ref,
        "pdf_urls": detail.pdf_urls,
        "issuing_authority": "公正取引委員会",
        "authority_canonical": "authority:jftc",
        "license": "PDL v1.0",
        "attribution": ("出典: 公正取引委員会ホームページ (https://www.jftc.go.jp/)"),
        "fetched_at": now_iso,
    }
    cur.execute(
        """INSERT OR IGNORE INTO am_entities
               (canonical_id, record_kind, source_topic, source_record_index,
                primary_name, authority_canonical, confidence, source_url,
                source_url_domain, fetched_at, raw_json,
                canonical_status, citation_status)
           VALUES (?, 'enforcement', ?, NULL, ?, 'authority:jftc', ?, ?, ?, ?,
                   ?, 'active', 'ok')""",
        (
            canonical_id,
            f"jftc_houdou_{listing.year}_{listing.month}",
            chosen_target[:255],
            0.92,
            listing.detail_url,
            "jftc.go.jp",
            now_iso,
            json.dumps(raw, ensure_ascii=False),
        ),
    )
    if cur.rowcount == 0:
        return False
    cur.execute(
        """INSERT INTO am_enforcement_detail
               (entity_id, houjin_bangou, target_name, enforcement_kind,
                issuing_authority, issuance_date, reason_summary,
                related_law_ref, amount_yen, source_url, source_fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            houjin_bangou,
            chosen_target[:255],
            listing.enforcement_kind,
            "公正取引委員会",
            listing.issuance_date,
            reason_summary[:2000] if reason_summary else None,
            related_law_ref[:255] if related_law_ref else None,
            amount_yen,
            listing.detail_url,
            now_iso,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def collect_listings(http: HttpClient, years: list[str]) -> list[ListingEntry]:
    out: list[ListingEntry] = []
    for year in years:
        for month in MONTHS:
            url = f"{BASE}/houdou/pressrelease/{year}/{month}/index.html"
            resp = http.get(url)
            if resp is None:
                _LOG.debug("monthly index missing %s", url)
                continue
            entries = parse_monthly_index(resp.text, year=year, month=month, base_url=url)
            if entries:
                _LOG.info(
                    "[list] %s/%s -> %d enforcement-tagged entries",
                    year,
                    month,
                    len(entries),
                )
            out.extend(entries)
    _LOG.info("total listings (pre-dedup): %d", len(out))
    # Sort newest-first so we see contemporary cases earlier.
    out.sort(key=lambda e: e.issuance_date, reverse=True)
    return out


def choose_target_name(
    listing: ListingEntry,
    detail: DetailInfo,
) -> tuple[str, str | None]:
    """Return (target_name, houjin_bangou) — best-effort single defendant.

    Multi-defendant 排除措置 cases sometimes do not list a 法人番号 in a
    single 名称 row. In that case we fall back to a derived 件名 string and
    leave houjin_bangou=None.
    """
    if detail.target_names:
        primary = detail.target_names[0]
        houjin = detail.houjin_bangous[0] if detail.houjin_bangous else None
        return primary, houjin
    # Derive from title — strip trailing "に対する…命令について" etc.
    derived = re.sub(
        r"に対する.*$",
        "",
        listing.title,
    ).strip()
    derived = re.sub(r"から.*$", "", derived).strip()
    if not derived:
        derived = listing.title
    return derived[:255], None


def run(
    db_path: Path,
    *,
    years: list[str],
    max_inserts: int,
    dry_run: bool,
    verbose: bool,
) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    now_iso = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    http = HttpClient()

    # 1. Walk year/month index pages.
    listings = collect_listings(http, years)

    if dry_run:
        _LOG.info(
            "dry-run: %d candidate listings (would attempt to insert up to %d)",
            len(listings),
            max_inserts,
        )
        for e in listings[:8]:
            _LOG.info(
                "  cand %s [%s] %s -> %s",
                e.issuance_date,
                e.kind_token_jp,
                e.title[:60],
                e.detail_url,
            )
        return 0

    # 2. Open DB; pre-load dedup sets so we can stop early.
    if not db_path.exists():
        _LOG.error("autonomath.db missing: %s", db_path)
        return 2
    con = sqlite3.connect(str(db_path), timeout=300.0)
    try:
        con.execute("PRAGMA busy_timeout=300000")
        con.execute("PRAGMA foreign_keys=ON")
        ensure_tables(con)
        cur = con.cursor()
        cur.execute("BEGIN IMMEDIATE")
        ensure_jftc_authority(cur)
        existing_keys = existing_dedup_keys(cur)
        existing_ids = existing_canonical_ids(cur)
        con.commit()
    except sqlite3.Error as exc:
        _LOG.error("DB init failed: %s", exc)
        try:
            con.close()
        except sqlite3.Error:
            pass
        return 2

    # 3. Walk listings, fetch detail, write per-entry transactions to keep
    #    contention low if other ingest workers are active.
    inserted = 0
    skipped_dup_db = 0
    skipped_dup_id = 0
    skipped_no_data = 0
    breakdown: dict[str, int] = {}
    samples: list[dict[str, Any]] = []

    for entry in listings:
        if inserted >= max_inserts:
            _LOG.info("reached --max-inserts=%d, stopping", max_inserts)
            break

        # Cheap pre-check on (date, title-derived target) before HTTP.
        # Real check after we have detail.target_names.
        canonical_id = build_canonical_id(
            entry.issuance_date,
            entry.title,
            entry.detail_url,
        )
        if canonical_id in existing_ids:
            skipped_dup_id += 1
            continue

        resp = http.get(entry.detail_url)
        if resp is None:
            _LOG.debug("detail fetch missing %s", entry.detail_url)
            skipped_no_data += 1
            continue
        detail = parse_detail_page(resp.text, entry.detail_url)
        target_name, houjin = choose_target_name(entry, detail)
        key = (entry.issuance_date, _normalize(target_name))
        if key in existing_keys:
            skipped_dup_db += 1
            continue

        # Build a compact reason. For 確約 / 排除措置 cases the press body's
        # opening sentence describes the violation succinctly; otherwise fall
        # back to title.
        reason_lines: list[str] = []
        if entry.kind_token_jp:
            reason_lines.append(f"[{entry.kind_token_jp}]")
        # First sentence of body (cap 600 chars).
        first = re.split(r"。", detail.summary_text or "", maxsplit=1)[0]
        if first:
            reason_lines.append(first.strip()[:600] + "。")
        reason_lines.append(f"件名: {entry.title}")
        reason_summary = " ".join(reason_lines).strip()

        # related_law_ref fallback.
        related_law_ref = detail.related_law_ref
        if not related_law_ref:
            if entry.kind_token_jp == "排除措置命令":
                related_law_ref = "独占禁止法"
            elif entry.kind_token_jp == "課徴金納付命令":
                # Some 課徴金 are 景表法 not 独禁法 — title usually carries the
                # word. Check title text.
                if "景品表示" in entry.title or "景表" in entry.title:
                    related_law_ref = "景品表示法 第8条"
                else:
                    related_law_ref = "独占禁止法 第7条の2"
            elif entry.kind_token_jp == "確約計画" or entry.kind_token_jp == "確約手続":
                related_law_ref = "独占禁止法 第48条の3"
            elif entry.kind_token_jp == "審決":
                related_law_ref = "独占禁止法"
            else:
                related_law_ref = "独占禁止法"

        # amount_yen is only meaningful for 課徴金納付命令 ('fine'). For
        # 排除措置命令 / 確約 / 警告 / 勧告 the regex sometimes captures
        # incidental small numbers in the body — drop those.
        amt_yen = detail.amount_yen if entry.enforcement_kind == "fine" else None

        try:
            cur.execute("BEGIN IMMEDIATE")
            ok = insert_one(
                cur,
                canonical_id=canonical_id,
                listing=entry,
                detail=detail,
                chosen_target=target_name,
                houjin_bangou=houjin,
                related_law_ref=related_law_ref,
                reason_summary=reason_summary,
                amount_yen=amt_yen,
                now_iso=now_iso,
            )
            con.commit()
        except sqlite3.IntegrityError as exc:
            _LOG.warning(
                "integrity error for %s: %s",
                canonical_id,
                exc,
            )
            try:
                con.rollback()
            except sqlite3.Error:
                pass
            continue
        except sqlite3.Error as exc:
            _LOG.error("DB error for %s: %s", canonical_id, exc)
            try:
                con.rollback()
            except sqlite3.Error:
                pass
            continue

        if ok:
            inserted += 1
            existing_keys.add(key)
            existing_ids.add(canonical_id)
            breakdown[entry.enforcement_kind] = breakdown.get(entry.enforcement_kind, 0) + 1
            if len(samples) < 3:
                samples.append(
                    {
                        "canonical_id": canonical_id,
                        "issuance_date": entry.issuance_date,
                        "kind_jp": entry.kind_token_jp,
                        "enforcement_kind": entry.enforcement_kind,
                        "target_name": target_name,
                        "houjin_bangou": houjin,
                        "amount_yen": amt_yen,
                        "related_law_ref": related_law_ref,
                        "source_url": entry.detail_url,
                    }
                )
            if inserted % 10 == 0:
                _LOG.info(
                    "progress inserted=%d (target=%d) latest=%s [%s]",
                    inserted,
                    max_inserts,
                    entry.issuance_date,
                    entry.kind_token_jp,
                )
        else:
            skipped_dup_id += 1

    # 4. Final summary.
    cur.execute(
        "SELECT COUNT(*) FROM am_enforcement_detail WHERE issuing_authority=?",
        ("公正取引委員会",),
    )
    after_jftc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM am_enforcement_detail")
    after_total = cur.fetchone()[0]
    try:
        con.close()
    except sqlite3.Error:
        pass

    _LOG.info(
        "done inserted=%d dup_db=%d dup_id=%d no_data=%d listings=%d",
        inserted,
        skipped_dup_db,
        skipped_dup_id,
        skipped_no_data,
        len(listings),
    )
    _LOG.info(
        "post-insert: jftc_rows=%d total_am_enforcement_detail=%d",
        after_jftc,
        after_total,
    )

    print(
        json.dumps(
            {
                "inserted": inserted,
                "breakdown_by_enforcement_kind": breakdown,
                "skipped_dup_db": skipped_dup_db,
                "skipped_dup_canonical_id": skipped_dup_id,
                "skipped_no_data": skipped_no_data,
                "candidate_listings": len(listings),
                "post_jftc_total": after_jftc,
                "post_am_enforcement_detail_total": after_total,
                "samples": samples,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return inserted


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--years",
        type=str,
        default=",".join(DEFAULT_YEARS),
        help="comma-separated calendar years (e.g. 2020,2021,2022,2023,2024,2025)",
    )
    ap.add_argument(
        "--max-inserts",
        type=int,
        default=150,
        help="stop after this many fresh inserts (default 150)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    years = [y.strip() for y in args.years.split(",") if y.strip()]
    inserted = run(
        args.db,
        years=years,
        max_inserts=args.max_inserts,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    return 0 if (args.dry_run or inserted >= 0) else 1


if __name__ == "__main__":
    sys.exit(main())
