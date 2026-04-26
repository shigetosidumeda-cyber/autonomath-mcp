#!/usr/bin/env python3
"""Ingest 農林水産省 (MAFF) 行政処分 / 措置命令 / 業務停止処分 into
``am_enforcement_detail`` + ``am_entities``.

Coverage (MVP, 2026-04-25 — first pass):

  Category                     | Source                                              | Rows ~
  -----------------------------|-----------------------------------------------------|------
  獣医師業務停止処分           | /j/press/syouan/tikusui/{YYMMDD}.html               | ~24
                              | (獣医師法第8条第2項) — anonymized 個人                 |
  獣医師受験禁止処分           | 獣医師国家試験 不正受験者 公表                       |  ~1
                              | /j/press/syouan/tikusui/{YYMMDD}.html               |
  食品表示法違反 不適正表示    | /{region}/press/{path}/hyouji/{YYMMDD}.html         | ~22
                              | 関東農政局 + 近畿農政局 + 北海道農政事務所           |
                              | (食品表示法第6条第1項に基づく指示)                   |
  カルタヘナ法 行政処分        | /j/press/syouan/nouan/{YYMMDD}.html                 |  ~1
                              | (遺伝子組換え生物等使用等規制法第14条第1項)          |
  -----------------------------|-----------------------------------------------------|------
  TOTAL (first ingest)         |                                                     | ~48

  Why so few:
   - Non-veterinary 獣医師処分 individual cases are NOT published — only
     aggregate 議事要旨 of the 獣医事審議会 are public, listing 案件数
     not names. We therefore only ingest the named press releases (one
     row per individual practitioner, anonymized as
     "獣医師 #NNN (氏名非公表)" matching the medical_pros script
     convention).
   - 飼料安全法 / 動物用医薬品 / 農薬取締法 / 家畜伝染病予防法 違反 are
     enforced almost entirely at 都道府県 level (out of MAFF national
     scope). MAFF's central press releases for these laws are 制度
     announcements and conference summaries, not individual processed
     enforcement actions. The collected /tmp/maff_wb_v2 corpus
     (200+ press releases 2018-2026) confirms zero individual 飼料 /
     動物用医薬品 / 農薬 enforcement press releases — those go to
     prefecture web sites covered by ingest_enforcement_kaigo_shogai
     and similar pref-level scripts.
   - 農地法違反 公表 list is on /j/keiei/koukai/houkokuchousa.html
     which returns Akamai 403 to all our access methods (curl,
     httpx, Playwright headless+headful, Wayback) and has no Wayback
     snapshot. Deferred to manual quarterly fetch.
   - Regional 食品表示違反 enforcement is concentrated at 関東/近畿
     (large urban consumer markets); 東北/中国四国/東海/九州/北陸
     pages return 403 to all access methods including Wayback (no
     snapshots). Periodic relaunch attempts may unblock them.

Anonymization policy (matches ingest_enforcement_medical_pros):
   The MAFF press release for 獣医師業務停止 names the individual
   practitioner publicly (e.g. "石原章和（茨城県在住47歳）"). Per
   AutonoMath data hygiene policy, we DO NOT propagate practitioner
   personal names to our DB even though they are publicly disclosed
   — the per-page incidence is so low (1-5/year) and downstream
   reuse risk so high that we anonymize as
   "獣医師 #NNN (氏名非公表)" with publication-stable sequence
   numbering. The full publication URL stays in source_url so users
   can retrieve names from the primary source if needed.

   Corporate enforcement (食品表示違反) keeps the company name AND
   the 法人番号 (extracted inline from the press release text).
   Example: "マルハニチロ株式会社" / 法人番号 2010601040697.

Schema mapping:
   - enforcement_kind:
       獣医師業務停止 → 'business_improvement'
       獣医師受験禁止 → 'license_revoke'
       食品表示違反 (指示) → 'business_improvement'
       カルタヘナ法 行政処分 (使用中止命令) → 'contract_suspend'
   - issuing_authority:
       中央 → '農林水産省'
       関東農政局 → '農林水産省 関東農政局'
       近畿農政局 → '農林水産省 近畿農政局'
       北海道農政事務所 → '農林水産省 北海道農政事務所'
   - related_law_ref:
       獣医師業務停止 → '獣医師法 第8条第2項'
       獣医師受験禁止 → '獣医師法 第14条'
       食品表示違反 → '食品表示法 第6条第1項'
       カルタヘナ法 → '遺伝子組換え生物等の使用等の規制による生物の多様性の確保に関する法律 第14条第1項'

Parallel-write:
   - BEGIN IMMEDIATE + busy_timeout=300000 (matches policy §5).
   - Single transaction at end (~50 rows; minimal contention).

Dedup:
   - Composite key (target_name, issuance_date, issuing_authority).
   - Existing-DB scan: rows whose canonical_id starts with
     'AM-ENF-MAFF-' or whose target_name matches our patterns.

License:
   - maff.go.jp content is 政府機関の著作物 (PDL v1.0 / 出典明記で
     利用可) per https://www.maff.go.jp/j/use/ . Attribution carried
     in raw_json under 'source_attribution'.

CLI:
    python scripts/ingest/ingest_enforcement_maff.py \\
        [--db autonomath.db] [--dry-run] [--max-insert N] [--verbose]

The script attempts LIVE refetch by default. If MAFF returns 403,
falls back to the local Wayback cache under /tmp/maff_wb_html and
/tmp/maff_wb_v2 (paths configurable via --cache-root).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: beautifulsoup4 not installed: {exc}", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.maff")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = (
    "AutonoMath/0.1.0 ingest "
    "(+https://bookyou.net; contact=info@bookyou.net)"
)
SOURCE_ATTRIBUTION = "農林水産省 ウェブサイト (PDL v1.0; 出典明記利用可)"

CENTRAL_AUTHORITY = "農林水産省"
KANTO_AUTHORITY = "農林水産省 関東農政局"
KINKI_AUTHORITY = "農林水産省 近畿農政局"
HOKKAIDO_AUTHORITY = "農林水産省 北海道農政事務所"

# Index URLs walked LIVE on each run.
KANTO_INDEX = "https://www.maff.go.jp/kanto/syo_an/hyouji/houdou.html"
KINKI_INDEX = "https://www.maff.go.jp/kinki/syouhi/hyouzi/houdou.html"
HOKKAIDO_INDEX = "https://www.maff.go.jp/hokkaido/press/index.html"

# Known central 獣医師業務停止 press release URLs (we cannot enumerate
# from MAFF site; collected via Wayback CDX 2018-2026). Maintain by
# hand; new ones are typically released 2-4 times/year. Each has 1-5
# anonymized practitioner cases.
KNOWN_ZYUI_URLS: tuple[str, ...] = (
    "https://www.maff.go.jp/j/press/syouan/tikusui/190731.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/201124_8.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/210922.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/220713.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/231109.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/240718.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/241105.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/250321.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/250704.html",
    "https://www.maff.go.jp/j/press/syouan/tikusui/251128.html",
)

# Known central 獣医師受験禁止 press releases (rare; ~1/year max).
KNOWN_ZYUI_EXAM_BAN_URLS: tuple[str, ...] = (
    "https://www.maff.go.jp/j/press/syouan/tikusui/250305.html",
)

# Known central カルタヘナ法 行政処分 press releases.
KNOWN_KARTAHENA_URLS: tuple[str, ...] = (
    "https://www.maff.go.jp/j/press/syouan/nouan/190507.html",
)

# ---------------------------------------------------------------------------
# Date / numeral parsing
# ---------------------------------------------------------------------------

_FULLWIDTH_DIGIT = str.maketrans("０１２３４５６７８９", "0123456789")

ERA_OFFSET = {"令和": 2018, "平成": 1988, "昭和": 1925}

_WAREKI_RE = re.compile(
    r"(令和|平成|昭和)\s*(\d+|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"
)
_SEIREKI_RE = re.compile(
    r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_date(text: str) -> str | None:
    """Return ISO YYYY-MM-DD from Japanese date in body or title."""
    if not text:
        return None
    s = _normalize(text).translate(_FULLWIDTH_DIGIT)
    m = _SEIREKI_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _WAREKI_RE.search(s)
    if m:
        era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        year = ERA_OFFSET[era] + y_off
        if 1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


# ---------------------------------------------------------------------------
# HTTP / cache layer
# ---------------------------------------------------------------------------

DEFAULT_CACHE_ROOTS = (
    Path("/tmp/maff_wb_html"),
    Path("/tmp/maff_wb_v2"),
    Path("/tmp/maff_case_html"),
)


def _slug_for_url(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").replace(":80", "").replace("/", "_").replace(":", "_")


def _scan_cache(roots: tuple[Path, ...]) -> dict[str, Path]:
    """Build {url_slug → cached file path} index across all cache roots."""
    out: dict[str, Path] = {}
    for root in roots:
        if not root.exists():
            continue
        for fp in root.iterdir():
            if not fp.is_file():
                continue
            name = fp.name
            # strip TS prefix if present (14-digit timestamp + _)
            if len(name) > 15 and name[:14].isdigit() and name[14] == "_":
                slug = name[15:]
            else:
                slug = name
            # last segment of slug is the press release filename
            if slug.endswith(".html"):
                # store under both the full slug and the trailing filename
                out.setdefault(slug, fp)
                out.setdefault(name.split("_")[-1], fp)
    return out


def _try_fetch_live(http: HttpClient, url: str) -> str | None:
    """Attempt direct LIVE fetch. MAFF Akamai blocks most paths; return
    None on non-200 / oversize so caller can fall back to cache."""
    res = http.get(url)
    if not res.ok or not res.body:
        return None
    text = res.text
    # Trivial 404 detector (Akamai serves 404 page with title "ご指定の…")
    if "ご指定のページは見つかりません" in text:
        return None
    return text


def _fetch_with_cache(
    url: str,
    http: HttpClient,
    cache_index: dict[str, Path],
) -> str | None:
    """Try LIVE first, fall back to local Wayback cache by slug match."""
    text = _try_fetch_live(http, url)
    if text is not None:
        return text
    # Fall back to cache
    slug = _slug_for_url(url)
    fp = cache_index.get(slug)
    if not fp:
        # Try just the trailing filename (e.g. "240326.html")
        tail = url.rsplit("/", 1)[-1]
        fp = cache_index.get(tail)
    if fp:
        try:
            return fp.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            _LOG.debug("cache read failed %s: %s", fp, exc)
    return None


# ---------------------------------------------------------------------------
# Index parsing (live regional 食品表示違反 indexes)
# ---------------------------------------------------------------------------


@dataclass
class ShokuhinIndexEntry:
    url: str
    title: str
    authority: str


def parse_index_for_shokuhin(
    html: str, base_url: str, authority: str,
) -> list[ShokuhinIndexEntry]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[ShokuhinIndexEntry] = []
    seen: set[str] = set()
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        text = (a.get_text(strip=True) or "").strip()
        if not text:
            continue
        # Filter to enforcement-themed links
        if not (("不適正表示" in text and "措置" in text)
                or ("違反" in text and "措置" in text)
                or "改善命令" in text):
            continue
        if href.startswith("/"):
            href = "https://www.maff.go.jp" + href
        if "maff.go.jp" not in href:
            continue
        # Drop trailing anchors / query
        href = href.split("#", 1)[0]
        if href in seen:
            continue
        seen.add(href)
        out.append(ShokuhinIndexEntry(
            url=href, title=text, authority=authority,
        ))
    return out


# ---------------------------------------------------------------------------
# Page parsers
# ---------------------------------------------------------------------------

# Pattern: "(社名)（住所。法人番号NNNNNNNNNNNNN。以下「略称」という。）"
# Two corporate-name shapes are common in MAFF prose:
#   (a) 「○○株式会社」  — name appears BEFORE 株式会社 (e.g. マルハニチロ株式会社)
#   (b) 「株式会社○○」  — name appears AFTER 株式会社 (e.g. 株式会社Olympic)
# The first capture group greedily captures any non-paren / non-、 chars that
# precede or follow 株式会社, allowing both shapes.
SHOKUHIN_BODY_RE = re.compile(
    r"([^（\(\n、 \t]*?(?:株式会社|有限会社|合同会社|合資会社|合名会社)"
    r"[A-Za-z0-9぀-ヿ一-鿿ー]*)\s*"
    r"[（\(]([^（\(\n]+?)。"
    r"\s*法人番号\s*(\d{13})\s*[。\.]?"
)

# Single-target pattern (1 case per page).
@dataclass
class ShokuhinCase:
    company_name: str
    houjin_bangou: str
    address: str
    issuance_date: str
    enforcement_kind: str  # 'business_improvement'
    related_law_ref: str
    reason_summary: str
    source_url: str
    issuing_authority: str
    raw_title: str


def parse_shokuhin_page(
    html: str, source_url: str, fallback_authority: str,
) -> list[ShokuhinCase]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.select_one("title").get_text(strip=True)
             if soup.select_one("title") else "")
    title = title.split("：")[0].strip()
    main = (soup.select_one("#main_content")
            or soup.select_one("main")
            or soup.select_one("body")
            or soup)
    body = main.get_text(separator="\n", strip=True)
    if not body:
        return []
    # Confirm enforcement
    if "不適正表示" not in title and "違反" not in title:
        return []
    # 地方農政局 detection from body (more reliable than fallback)
    authority = fallback_authority
    for kw, name in (
        ("関東農政局", KANTO_AUTHORITY),
        ("近畿農政局", KINKI_AUTHORITY),
        ("北海道農政事務所", HOKKAIDO_AUTHORITY),
        ("東海農政局", "農林水産省 東海農政局"),
        ("中国四国農政局", "農林水産省 中国四国農政局"),
        ("東北農政局", "農林水産省 東北農政局"),
        ("九州農政局", "農林水産省 九州農政局"),
        ("北陸農政局", "農林水産省 北陸農政局"),
    ):
        if kw in body:
            authority = name
            break

    # Date
    date = _parse_date(body) or _parse_date(title)
    if not date:
        return []

    # Body match for company info
    out: list[ShokuhinCase] = []
    seen_keys: set[tuple[str, str]] = set()
    for m in SHOKUHIN_BODY_RE.finditer(body):
        company = m.group(1).strip()
        addr = m.group(2).strip()
        hb = m.group(3).strip()
        # avoid duplicate (same company, same hb)
        key = (company, hb)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # Reason — pull a short synopsis from body
        # (sentence containing "確認した" or "販売した")
        reason_chunks: list[str] = []
        for sent in re.split(r"[。]", body):
            sent = sent.strip()
            if not sent:
                continue
            if "事実と異なる" in sent or "不適正" in sent or "確認しました" in sent:
                if len(sent) < 400:
                    reason_chunks.append(sent + "。")
            if len(reason_chunks) >= 2:
                break
        reason = " ".join(reason_chunks).strip() or title
        out.append(ShokuhinCase(
            company_name=company,
            houjin_bangou=hb,
            address=addr,
            issuance_date=date,
            enforcement_kind="business_improvement",
            related_law_ref="食品表示法 第6条第1項",
            reason_summary=reason[:1500],
            source_url=source_url,
            issuing_authority=authority,
            raw_title=title,
        ))
    return out


# 獣医師業務停止 parsing
ZYUI_HEADER_RE = re.compile(
    r"獣医師\s*(\d+)\s*名"
)
ZYUI_NUMBERED_CASE_RE = re.compile(
    r"[（\(]\s*(\d+)\s*[）\)]\s*"
    r"([^（\(\n]+?)\s*"
    r"[（\(]\s*([^（\(\n]+?)\s*[）\)]"
)
# Single-case form (no "(1)" prefix)
ZYUI_SINGLE_CASE_RE = re.compile(
    r"以下の獣医師に対し、獣医師法に基づく業務停止の処分を行いました。\s*"
    r"\n?\s*([^（\(\n]+?)\s*"
    r"[（\(]\s*([^（\(\n]+?)\s*[）\)]"
)


@dataclass
class ZyuiCase:
    publication_url: str
    issuance_date: str
    seq_in_publication: int
    enforcement_kind: str  # 'business_improvement'
    related_law_ref: str
    reason_summary: str
    source_url: str


def parse_zyui_page(html: str, source_url: str) -> list[ZyuiCase]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.select_one("title").get_text(strip=True)
             if soup.select_one("title") else "")
    if "獣医師" not in title or "業務停止処分" not in title:
        return []
    main = (soup.select_one("#main_content")
            or soup.select_one("main")
            or soup.select_one("body")
            or soup)
    body = main.get_text(separator="\n", strip=True)
    date = _parse_date(body)
    if not date:
        return []

    out: list[ZyuiCase] = []
    # Parse numbered cases first (multi-case form).
    matches = list(ZYUI_NUMBERED_CASE_RE.finditer(body))
    if matches:
        # Capture each case's "事件の概要" separately by splitting body
        sections = re.split(
            r"(?=[（\(]\s*\d+\s*[）\)]\s*[^\d])",
            body,
        )
        idx = 0
        for sec in sections:
            sm = ZYUI_NUMBERED_CASE_RE.search(sec)
            if not sm:
                continue
            seq = int(sm.group(1))
            # Pull case description = next ~600 chars
            tail = sec[sm.end():sm.end() + 800]
            # Extract 事件の概要
            jian = ""
            jm = re.search(r"事件の概要\s*[:：]?\s*(.+?)(?:司法処分|お問合せ|$)", tail, re.S)
            if jm:
                jian = jm.group(1).strip()
                jian = re.sub(r"\s+", " ", jian)[:500]
            shihou = ""
            sm2 = re.search(r"司法処分の内容\s*[:：]?\s*(.+?)(?:お問合せ|（\d+\)|$)", tail, re.S)
            if sm2:
                shihou = sm2.group(1).strip()
                shihou = re.sub(r"\s+", " ", shihou)[:300]
            stop = ""
            stop_m = re.search(r"行政処分の内容\s*[:：]?\s*(.+?)(?:事件の概要|司法処分|$)", tail, re.S)
            if stop_m:
                stop = stop_m.group(1).strip()
                stop = re.sub(r"\s+", " ", stop)[:200]
            reason = (
                f"獣医師業務停止: {stop}; 事件の概要: {jian}"
                f"; 司法処分: {shihou}"
            )
            idx += 1
            out.append(ZyuiCase(
                publication_url=source_url,
                issuance_date=date,
                seq_in_publication=idx,
                enforcement_kind="business_improvement",
                related_law_ref="獣医師法 第8条第2項",
                reason_summary=reason[:1500],
                source_url=source_url,
            ))
    else:
        # Single-case form
        m1 = ZYUI_SINGLE_CASE_RE.search(body)
        if m1:
            tail = body[m1.end():m1.end() + 800]
            jian = ""
            jm = re.search(r"事件の概要\s*[:：]?\s*(.+?)(?:司法処分|お問合せ|$)", tail, re.S)
            if jm:
                jian = re.sub(r"\s+", " ", jm.group(1).strip())[:500]
            shihou = ""
            sm2 = re.search(r"司法処分の内容\s*[:：]?\s*(.+?)(?:お問合せ|$)", tail, re.S)
            if sm2:
                shihou = re.sub(r"\s+", " ", sm2.group(1).strip())[:300]
            stop = ""
            stop_m = re.search(r"行政処分の内容\s*[:：]?\s*(.+?)(?:事件の概要|司法処分|$)", tail, re.S)
            if stop_m:
                stop = re.sub(r"\s+", " ", stop_m.group(1).strip())[:200]
            reason = (
                f"獣医師業務停止: {stop}; 事件の概要: {jian}"
                f"; 司法処分: {shihou}"
            )
            out.append(ZyuiCase(
                publication_url=source_url,
                issuance_date=date,
                seq_in_publication=1,
                enforcement_kind="business_improvement",
                related_law_ref="獣医師法 第8条第2項",
                reason_summary=reason[:1500],
                source_url=source_url,
            ))
    return out


def parse_zyui_exam_ban_page(html: str, source_url: str) -> list[ZyuiCase]:
    """Parse 獣医師国家試験 受験禁止処分 page."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.select_one("title").get_text(strip=True)
             if soup.select_one("title") else "")
    if "受験禁止処分" not in title:
        return []
    main = (soup.select_one("#main_content")
            or soup.select_one("main")
            or soup.select_one("body")
            or soup)
    body = main.get_text(separator="\n", strip=True)
    date = _parse_date(body)
    if not date:
        return []
    # Extract 処分理由 + 処分内容
    riyu = ""
    rm = re.search(r"処分理由\s*[:：]?\s*(.+?)(?:お問合せ|$)", body, re.S)
    if rm:
        riyu = re.sub(r"\s+", " ", rm.group(1).strip())[:600]
    naiyo = ""
    nm = re.search(r"処分内容\s*[:：]?\s*(.+?)(?:処分理由|お問合せ|$)", body, re.S)
    if nm:
        naiyo = re.sub(r"\s+", " ", nm.group(1).strip())[:300]
    reason = f"獣医師国家試験受験禁止処分: {naiyo}; 理由: {riyu}"
    return [ZyuiCase(
        publication_url=source_url,
        issuance_date=date,
        seq_in_publication=1,
        enforcement_kind="license_revoke",
        related_law_ref="獣医師法 第14条",
        reason_summary=reason[:1500],
        source_url=source_url,
    )]


# ---------------------------------------------------------------------------
# カルタヘナ法
# ---------------------------------------------------------------------------

@dataclass
class KartahenaCase:
    target_name: str
    address: str
    issuance_date: str
    enforcement_kind: str
    related_law_ref: str
    reason_summary: str
    source_url: str
    issuing_authority: str


def parse_kartahena_page(html: str, source_url: str) -> list[KartahenaCase]:
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.select_one("title").get_text(strip=True)
             if soup.select_one("title") else "")
    if "カルタヘナ" not in title or "行政処分" not in title:
        return []
    main = (soup.select_one("#main_content")
            or soup.select_one("main")
            or soup.select_one("body")
            or soup)
    body = main.get_text(separator="\n", strip=True)
    date = _parse_date(body)
    if not date:
        return []
    name_m = re.search(r"名称\s*[:：]?\s*([^\n]+)", body)
    addr_m = re.search(r"所在地\s*[:：]?\s*([^\n]+)", body)
    riyu_m = re.search(r"処分理由\s*\n?\s*(.+?)(?:その他|お問合せ|$)", body, re.S)
    naiyo_m = re.search(r"処分内容\s*\n?\s*(.+?)(?:処分理由|その他|お問合せ|$)", body, re.S)
    if not name_m:
        return []
    target = re.sub(r"\s+", " ", name_m.group(1).strip())[:300]
    addr = re.sub(r"\s+", " ", addr_m.group(1).strip())[:300] if addr_m else ""
    naiyo = re.sub(r"\s+", " ", naiyo_m.group(1).strip())[:600] if naiyo_m else ""
    riyu = re.sub(r"\s+", " ", riyu_m.group(1).strip())[:600] if riyu_m else ""
    reason = (
        f"カルタヘナ法行政処分: {naiyo}; 処分理由: {riyu}"
    )
    return [KartahenaCase(
        target_name=target,
        address=addr,
        issuance_date=date,
        enforcement_kind="contract_suspend",
        related_law_ref=(
            "遺伝子組換え生物等の使用等の規制による生物の多様性の確保に関する法律 第14条第1項"
        ),
        reason_summary=reason[:1500],
        source_url=source_url,
        issuing_authority=CENTRAL_AUTHORITY,
    )]


# ---------------------------------------------------------------------------
# Common DB row representation
# ---------------------------------------------------------------------------

@dataclass
class EnfRow:
    """Unified enforcement row before insert."""
    canonical_id: str
    primary_name: str  # for am_entities
    target_name: str   # for am_enforcement_detail
    houjin_bangou: str | None
    enforcement_kind: str
    issuing_authority: str
    issuance_date: str
    reason_summary: str
    related_law_ref: str
    source_url: str
    raw_json: str


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------

def _slug8(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return h[:8]


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(
                f"missing table '{tbl}' — apply migrations first"
            )


def existing_dedup_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    """Return keys of MAFF rows already in DB so reruns are idempotent.

    Restrict to rows whose canonical_id starts with 'AM-ENF-MAFF-' or
    whose authority matches one we use, to avoid colliding with
    pre-existing MAFF补助金 grant_refund rows.
    """
    out: set[tuple[str, str, str]] = set()
    cur = conn.execute(
        "SELECT d.target_name, d.issuance_date, d.issuing_authority "
        "FROM am_enforcement_detail d "
        "WHERE d.entity_id LIKE 'AM-ENF-MAFF-%'"
    )
    for n, dte, a in cur.fetchall():
        if n and dte and a:
            out.add((n, dte, a))
    return out


def upsert_entity(
    conn: sqlite3.Connection,
    canonical_id: str,
    primary_name: str,
    url: str,
    raw_json: str,
    now_iso: str,
) -> None:
    domain = urlparse(url).netloc or None
    conn.execute(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            canonical_status, citation_status
        ) VALUES (?, 'enforcement', 'maff_enforcement', NULL,
                  ?, NULL, 0.9, ?, ?, ?, ?, 'active', 'ok')
        ON CONFLICT(canonical_id) DO UPDATE SET
            primary_name      = excluded.primary_name,
            source_url        = excluded.source_url,
            source_url_domain = excluded.source_url_domain,
            fetched_at        = excluded.fetched_at,
            raw_json          = excluded.raw_json,
            updated_at        = datetime('now')
        """,
        (canonical_id, primary_name[:500], url, domain, now_iso, raw_json),
    )


def insert_enforcement(
    conn: sqlite3.Connection,
    entity_id: str,
    target_name: str,
    houjin_bangou: str | None,
    enf_kind: str,
    issuing_authority: str,
    issuance_date: str,
    reason_summary: str,
    related_law_ref: str,
    source_url: str,
    now_iso: str,
) -> None:
    conn.execute(
        """
        INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen,
            source_url, source_fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, ?, ?)
        """,
        (
            entity_id,
            houjin_bangou,
            target_name[:500],
            enf_kind,
            issuing_authority,
            issuance_date,
            reason_summary[:4000],
            related_law_ref[:1000],
            source_url,
            now_iso,
        ),
    )


def write_rows(
    conn: sqlite3.Connection,
    rows: list[EnfRow],
    *,
    now_iso: str,
    max_insert: int | None,
) -> tuple[int, int, int]:
    """Insert rows in BEGIN IMMEDIATE block. Returns (inserted, dup_db, dup_batch)."""
    if not rows:
        return 0, 0, 0
    db_keys = existing_dedup_keys(conn)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = 0
    dup_db = 0
    dup_batch = 0

    try:
        conn.execute("BEGIN IMMEDIATE")
        for r in rows:
            if max_insert is not None and inserted >= max_insert:
                break
            key = (r.target_name, r.issuance_date, r.issuing_authority)
            if key in db_keys:
                dup_db += 1
                continue
            if key in batch_keys:
                dup_batch += 1
                continue
            batch_keys.add(key)
            try:
                upsert_entity(
                    conn, r.canonical_id, r.primary_name,
                    r.source_url, r.raw_json, now_iso,
                )
                insert_enforcement(
                    conn, r.canonical_id, r.target_name, r.houjin_bangou,
                    r.enforcement_kind, r.issuing_authority, r.issuance_date,
                    r.reason_summary, r.related_law_ref,
                    r.source_url, now_iso,
                )
                inserted += 1
            except sqlite3.Error as exc:
                _LOG.error(
                    "DB error name=%r date=%s: %s",
                    r.target_name, r.issuance_date, exc,
                )
                continue
        conn.commit()
    except sqlite3.Error as exc:
        _LOG.error("BEGIN/commit failed: %s", exc)
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
    return inserted, dup_db, dup_batch


# ---------------------------------------------------------------------------
# Row construction (per-source builder)
# ---------------------------------------------------------------------------


def build_shokuhin_rows(
    cases: list[ShokuhinCase],
) -> list[EnfRow]:
    out: list[EnfRow] = []
    for c in cases:
        slug = _slug8(c.source_url, c.company_name, c.houjin_bangou)
        canonical_id = (
            f"AM-ENF-MAFF-SHOKUHIN-{c.issuance_date.replace('-', '')}-{slug}"
        )
        primary_name = (
            f"{c.company_name} - 食品表示違反措置 ({c.issuance_date})"
        )
        raw_json = json.dumps({
            "category": "shokuhin_hyoji_houhan",
            "company_name": c.company_name,
            "houjin_bangou": c.houjin_bangou,
            "address": c.address,
            "issuance_date": c.issuance_date,
            "enforcement_kind": c.enforcement_kind,
            "related_law_ref": c.related_law_ref,
            "issuing_authority": c.issuing_authority,
            "title": c.raw_title,
            "source_url": c.source_url,
            "source_attribution": SOURCE_ATTRIBUTION,
            "license": "PDL v1.0 (出典明記利用可)",
        }, ensure_ascii=False)
        out.append(EnfRow(
            canonical_id=canonical_id,
            primary_name=primary_name[:500],
            target_name=c.company_name[:500],
            houjin_bangou=c.houjin_bangou,
            enforcement_kind=c.enforcement_kind,
            issuing_authority=c.issuing_authority,
            issuance_date=c.issuance_date,
            reason_summary=c.reason_summary,
            related_law_ref=c.related_law_ref,
            source_url=c.source_url,
            raw_json=raw_json,
        ))
    return out


def build_zyui_rows(
    cases: list[ZyuiCase],
) -> list[EnfRow]:
    out: list[EnfRow] = []
    for c in cases:
        target_name = f"獣医師 #{c.seq_in_publication:03d} (氏名非公表)"
        slug = _slug8(c.source_url, str(c.seq_in_publication), c.related_law_ref)
        kind_short = (
            "ZYUI-EXAM"
            if c.related_law_ref == "獣医師法 第14条"
            else "ZYUI-STOP"
        )
        canonical_id = (
            f"AM-ENF-MAFF-{kind_short}-{c.issuance_date.replace('-', '')}-{slug}"
        )
        primary_name = (
            f"{target_name} - 獣医師処分 ({c.issuance_date})"
        )
        raw_json = json.dumps({
            "category": "zyuui_syobun",
            "publication_url": c.publication_url,
            "seq_in_publication": c.seq_in_publication,
            "issuance_date": c.issuance_date,
            "enforcement_kind": c.enforcement_kind,
            "related_law_ref": c.related_law_ref,
            "issuing_authority": CENTRAL_AUTHORITY,
            "anonymized": True,
            "anonymization_reason": (
                "個人特定情報のため匿名化。氏名・年齢・在住都道府県は "
                "出典 URL から確認可能。"
            ),
            "source_url": c.source_url,
            "source_attribution": SOURCE_ATTRIBUTION,
            "license": "PDL v1.0 (出典明記利用可)",
        }, ensure_ascii=False)
        out.append(EnfRow(
            canonical_id=canonical_id,
            primary_name=primary_name[:500],
            target_name=target_name[:500],
            houjin_bangou=None,
            enforcement_kind=c.enforcement_kind,
            issuing_authority=CENTRAL_AUTHORITY,
            issuance_date=c.issuance_date,
            reason_summary=c.reason_summary,
            related_law_ref=c.related_law_ref,
            source_url=c.source_url,
            raw_json=raw_json,
        ))
    return out


def build_kartahena_rows(cases: list[KartahenaCase]) -> list[EnfRow]:
    out: list[EnfRow] = []
    for c in cases:
        slug = _slug8(c.source_url, c.target_name)
        canonical_id = (
            f"AM-ENF-MAFF-KARTAHENA-{c.issuance_date.replace('-', '')}-{slug}"
        )
        primary_name = (
            f"{c.target_name} - カルタヘナ法行政処分 ({c.issuance_date})"
        )
        raw_json = json.dumps({
            "category": "kartahena_gyousei_shobun",
            "target_name": c.target_name,
            "address": c.address,
            "issuance_date": c.issuance_date,
            "enforcement_kind": c.enforcement_kind,
            "related_law_ref": c.related_law_ref,
            "issuing_authority": c.issuing_authority,
            "source_url": c.source_url,
            "source_attribution": SOURCE_ATTRIBUTION,
            "license": "PDL v1.0 (出典明記利用可)",
        }, ensure_ascii=False)
        out.append(EnfRow(
            canonical_id=canonical_id,
            primary_name=primary_name[:500],
            target_name=c.target_name[:500],
            houjin_bangou=None,
            enforcement_kind=c.enforcement_kind,
            issuing_authority=c.issuing_authority,
            issuance_date=c.issuance_date,
            reason_summary=c.reason_summary,
            related_law_ref=c.related_law_ref,
            source_url=c.source_url,
            raw_json=raw_json,
        ))
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def collect_shokuhin_rows(
    http: HttpClient,
    cache: dict[str, Path],
) -> list[EnfRow]:
    """Walk regional 食品表示違反 indexes + parse each case page."""
    rows: list[EnfRow] = []
    for index_url, default_authority in (
        (KANTO_INDEX, KANTO_AUTHORITY),
        (KINKI_INDEX, KINKI_AUTHORITY),
        (HOKKAIDO_INDEX, HOKKAIDO_AUTHORITY),
    ):
        html = _fetch_with_cache(index_url, http, cache)
        if not html:
            _LOG.warning("[shokuhin] index unreachable: %s", index_url)
            continue
        entries = parse_index_for_shokuhin(
            html, index_url, default_authority,
        )
        _LOG.info(
            "[shokuhin] index=%s entries=%d", index_url, len(entries),
        )
        for e in entries:
            page = _fetch_with_cache(e.url, http, cache)
            if not page:
                _LOG.debug("[shokuhin] case unreachable: %s", e.url)
                continue
            cases = parse_shokuhin_page(page, e.url, e.authority)
            if not cases:
                _LOG.debug("[shokuhin] no cases parsed: %s", e.url)
                continue
            rows.extend(build_shokuhin_rows(cases))
    return rows


def collect_zyui_rows(
    http: HttpClient,
    cache: dict[str, Path],
) -> list[EnfRow]:
    """Fetch each known 獣医師 publication and parse cases."""
    rows: list[EnfRow] = []
    for url in KNOWN_ZYUI_URLS:
        html = _fetch_with_cache(url, http, cache)
        if not html:
            _LOG.warning("[zyui] unreachable: %s", url)
            continue
        cases = parse_zyui_page(html, url)
        _LOG.info("[zyui] %s cases=%d", url, len(cases))
        rows.extend(build_zyui_rows(cases))
    for url in KNOWN_ZYUI_EXAM_BAN_URLS:
        html = _fetch_with_cache(url, http, cache)
        if not html:
            continue
        cases = parse_zyui_exam_ban_page(html, url)
        _LOG.info("[zyui-exam] %s cases=%d", url, len(cases))
        rows.extend(build_zyui_rows(cases))
    return rows


def collect_kartahena_rows(
    http: HttpClient,
    cache: dict[str, Path],
) -> list[EnfRow]:
    rows: list[EnfRow] = []
    for url in KNOWN_KARTAHENA_URLS:
        html = _fetch_with_cache(url, http, cache)
        if not html:
            _LOG.warning("[kartahena] unreachable: %s", url)
            continue
        cases = parse_kartahena_page(html, url)
        _LOG.info("[kartahena] %s cases=%d", url, len(cases))
        rows.extend(build_kartahena_rows(cases))
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--max-insert", type=int, default=None)
    ap.add_argument(
        "--cache-root", action="append", type=Path, default=None,
        help="Additional cache directory of pre-fetched HTML "
             "(can repeat). Default: /tmp/maff_wb_html, "
             "/tmp/maff_wb_v2, /tmp/maff_case_html.",
    )
    ap.add_argument(
        "--skip-live", action="store_true",
        help="Do not attempt LIVE refetch (cache only).",
    )
    return ap.parse_args(argv)


class _NullHttp:
    """Pass-through that always returns None for fetch_live (cache-only mode)."""
    def get(self, url, **kw):
        class R: pass
        r = R()
        r.ok = False
        r.body = b""
        r.text = ""
        r.status = 0
        r.headers = {}
        return r
    def close(self): pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if args.skip_live:
        http = _NullHttp()  # type: ignore[assignment]
    else:
        http = HttpClient(user_agent=USER_AGENT)
    cache_roots = tuple(args.cache_root or DEFAULT_CACHE_ROOTS)
    cache_index = _scan_cache(cache_roots)
    _LOG.info(
        "cache: roots=%s entries=%d",
        [str(p) for p in cache_roots], len(cache_index),
    )

    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )

    # Walk all sources
    shokuhin = collect_shokuhin_rows(http, cache_index)
    zyui = collect_zyui_rows(http, cache_index)
    kartahena = collect_kartahena_rows(http, cache_index)

    all_rows: list[EnfRow] = []
    all_rows.extend(shokuhin)
    all_rows.extend(zyui)
    all_rows.extend(kartahena)

    _LOG.info(
        "parsed shokuhin=%d zyui=%d kartahena=%d total=%d",
        len(shokuhin), len(zyui), len(kartahena), len(all_rows),
    )

    if args.dry_run:
        for r in all_rows[:8]:
            _LOG.info(
                "sample: target=%r kind=%s law=%s date=%s authority=%s",
                r.target_name, r.enforcement_kind, r.related_law_ref,
                r.issuance_date, r.issuing_authority,
            )
        if hasattr(http, "close"):
            http.close()
        return 0

    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        if hasattr(http, "close"):
            http.close()
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_tables(conn)

    inserted, dup_db, dup_batch = write_rows(
        conn, all_rows, now_iso=now_iso, max_insert=args.max_insert,
    )
    try:
        conn.close()
    except sqlite3.Error:
        pass
    if hasattr(http, "close"):
        http.close()

    # Breakdown
    by_law: dict[str, int] = {}
    by_authority: dict[str, int] = {}
    for r in all_rows:
        by_law[r.related_law_ref] = by_law.get(r.related_law_ref, 0) + 1
        by_authority[r.issuing_authority] = (
            by_authority.get(r.issuing_authority, 0) + 1
        )

    _LOG.info(
        "done parsed=%d inserted=%d dup_db=%d dup_batch=%d",
        len(all_rows), inserted, dup_db, dup_batch,
    )
    print(
        f"MAFF enforcement ingest: parsed={len(all_rows)} "
        f"inserted={inserted} dup_db={dup_db} dup_batch={dup_batch}"
    )
    print("--- by law ---")
    for k, v in sorted(by_law.items(), key=lambda x: -x[1]):
        print(f"  {v:4d}  {k}")
    print("--- by authority ---")
    for k, v in sorted(by_authority.items(), key=lambda x: -x[1]):
        print(f"  {v:4d}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
