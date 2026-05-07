#!/usr/bin/env python3
"""Ingest 金融庁 (FSA) + 関東財務局 + 証券取引等監視委員会 (SESC) 行政処分 /
課徴金納付命令 / 警告 records into ``am_enforcement_detail`` + ``am_entities``.

Coverage:
  1. FSA news index https://www.fsa.go.jp/news/index.html — 291 entries,
     categories ginkou / shouken / hoken / kashikin / amlcft / sonota.
     Filter: title contains 行政処分 / 命令 / 課徴金 / 取消 / 警告 / 業務改善.
  2. FSA 課徴金一覧 https://www.fsa.go.jp/policy/kachoukin/05.html (current FY).
  3. SESC archive https://www.fsa.go.jp/sesc/news/c_{YYYY}/c_{YYYY}.html
     for 2022,2023,2024,2025,2026 — 課徴金勧告 / 告発 / 検査結果に基づく勧告.
  4. 関東財務局:
        - https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/syobun.htm
          (金融商品取引業者等行政処分一覧)
        - https://lfb.mof.go.jp/kantou/kinyuu/pagekthp032000340.html
          (適格機関投資家等特例業者行政処分一覧)
        - https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/mutoroku_caution.htm
          (無登録業者警告等)
        - https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/syobun_00002.htm
          (高速取引行為者行政処分)
        - https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/kankoku.htm
          (金融商品取引業者等勧告等)
        - https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/kouhyou.htm
          (適格機関投資家等特例業務勧告等)

Schema mapping:
  - enforcement_kind:
      業務改善命令         → 'business_improvement'
      業務停止 / 業務廃止 / 登録取消 / 取消し → 'license_revoke'
      課徴金 / 罰金 / 過怠金 → 'fine'
      報告徴求             → 'investigation'
      警告 / 注意喚起      → 'investigation'  (legal warning,監督上)
      告発                 → 'investigation'
      勧告                 → 'investigation'  (検査結果勧告 by SESC)
      otherwise            → 'other'
  - issuing_authority:
      '金融庁'  for /www.fsa.go.jp/news/...
      '証券取引等監視委員会' for /sesc/news/...
      '関東財務局' for /lfb.mof.go.jp/...
  - related_law_ref:
      ginkou      → '銀行法'
      shouken     → '金融商品取引法'
      hoken       → '保険業法'
      kashikin    → '貸金業法'
      sesc        → '金融商品取引法'
      kantou syouken → '金融商品取引法'
      kantou kashikin → '貸金業法'
  - amount_yen: 課徴金額 / 罰金額 in body, parsed from '金〇〇万円' / '〇億〇万円'.

Idempotency:
  - Dedup key: (issuing_authority, issuance_date, target_name).
  - canonical_id: AM-ENF-FSA-{seq8} where seq8 = sha1(authority|date|name)[:8].

Parallel-write:
  - BEGIN IMMEDIATE + busy_timeout=300000 (per CLAUDE.md §5).
  - Single bulk commit at end (matches PMDA / MHLW pattern).

CLI:
    python scripts/ingest/ingest_enforcement_fsa.py \\
        [--db autonomath.db] [--max-rows 200] [--dry-run] [--verbose]
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import contextlib  # noqa: E402  (sys.path manipulation precedes)

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.fsa")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"

FSA_NEWS_INDEX = "https://www.fsa.go.jp/news/index.html"
FSA_KACHOUKIN_INDEX = "https://www.fsa.go.jp/policy/kachoukin/05.html"
SESC_YEAR_FMT = "https://www.fsa.go.jp/sesc/news/c_{year}/c_{year}.html"
SESC_YEARS = (2022, 2023, 2024, 2025, 2026)

KANTOU_INDEX_URLS = (
    "https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/syobun.htm",
    "https://lfb.mof.go.jp/kantou/kinyuu/pagekthp032000340.html",
    "https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/mutoroku_caution.htm",
    "https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/syobun_00002.htm",
    "https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/kankoku.htm",
    "https://lfb.mof.go.jp/kantou/kinyuu/kinshotorihou/kouhyou.htm",
)

# Title-level inclusion filter (any one suffices)
KEYWORD_INCLUDE = (
    "行政処分",
    "業務改善命令",
    "業務停止",
    "業務廃止",
    "登録取消",
    "課徴金",
    "罰金",
    "過怠金",
    "取消し",
    "取消",
    "警告",
    "勧告",
    "告発",
    "報告徴求",
    "業務上の",
    "改善命令",
)
# Anti-spam exclusions in titles. "(案)" and 改正案 are policy drafts, not
# enforcement actions. Public comments / policy papers also excluded.
KEYWORD_EXCLUDE = (
    "意見交換会",
    "アンケート",
    "監督指針",
    "（案）",
    "(案)",
    "パブリックコメント",
    "募集",
    "セミナー",
    "シンポジウム",
    "懇談会",
    "研究会",
    "白書",
    "改正",
    "の公表",
    "ガイドライン",
    "事務ガイドライン",
    "金融上の措置",
    "災害",
    "金融経済教育",
    "中間報告",
    "報告書",
    "の改訂",
)

# ---------------------------------------------------------------------------
# Date / number parsing
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(r"(令和|平成|昭和)\s*(\d+|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
ERA_OFFSET = {"令和": 2018, "平成": 1988, "昭和": 1925}

# 法人番号 13-digit
HOUJIN_RE = re.compile(r"法人番号\s*[:：]?\s*([0-9０-９]{13})")

# Yen amounts: 金〇〇万円, 〇億〇〇〇〇万円, 〇〇円, etc.
YEN_RE = re.compile(
    r"(?:課徴金|金|罰金|納付すべき)\s*(?:額\s*)?"
    r"(?:金\s*)?([0-9０-９,，、]{1,3}(?:億)?[0-9０-９,，、]*"
    r"(?:万)?[0-9０-９,，、]*)\s*円"
)

CR_HOUJIN_PAT = re.compile(r"([0-9]{13})")


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_wareki(text: str) -> str | None:
    s = _normalize(text)
    m = WAREKI_RE.search(s)
    if not m:
        return None
    era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
    try:
        y_off = 1 if y_raw == "元" else int(y_raw)
    except ValueError:
        return None
    year = ERA_OFFSET[era] + y_off
    if 1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
        return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


_TR_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _parse_yen(text: str) -> int | None:
    """Best-effort 課徴金 / 罰金 amount extraction.

    Examples handled:
      ・金7844万円
      ・課徴金1億2,345万円
      ・金123,456円
      ・金１億２，３４５万円
    """
    if not text:
        return None
    s = _normalize(text)
    s = s.translate(_TR_DIGITS)
    s = s.replace(",", "").replace("，", "")
    # Try patterns like 'X億Y万円' first
    pat = re.compile(
        r"(?:課徴金|金|罰金|納付すべき(?:課徴金)?(?:の|)額)\s*"
        r"(?:額\s*)?(?:金\s*)?"
        r"(?:(\d+)億)?(?:(\d+)万)?(\d+)?\s*円"
    )
    best = None
    for m in pat.finditer(s):
        oku = int(m.group(1)) if m.group(1) else 0
        man = int(m.group(2)) if m.group(2) else 0
        yen = int(m.group(3)) if m.group(3) else 0
        if oku == 0 and man == 0 and yen == 0:
            continue
        amount = oku * 100_000_000 + man * 10_000 + yen
        if amount > 0 and (best is None or amount > best):
            best = amount
    return best


def _parse_houjin(body_text: str) -> str | None:
    m = HOUJIN_RE.search(_normalize(body_text))
    if m:
        digits = m.group(1).translate(_TR_DIGITS)
        if len(digits) == 13 and digits.isdigit():
            return digits
    # fallback: standalone 13-digit run preceded by 法人番号 within 12 chars
    s = _normalize(body_text).translate(_TR_DIGITS)
    m2 = re.search(r"法人番号[）\)（\(]*\s*[:：]?\s*(\d{13})", s)
    if m2:
        return m2.group(1)
    return None


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------


def _html_to_text(html: str) -> str:
    """Strip tags + scripts; return collapsed text."""
    s = re.sub(r"<script[^>]*>.+?</script>", " ", html, flags=re.S)
    s = re.sub(r"<style[^>]*>.+?</style>", " ", s, flags=re.S)
    s = re.sub(r"<header[^>]*>.+?</header>", " ", s, flags=re.S)
    s = re.sub(r"<footer[^>]*>.+?</footer>", " ", s, flags=re.S)
    s = re.sub(r"<nav[^>]*>.+?</nav>", " ", s, flags=re.S)
    s = re.sub(r"<aside[^>]*>.+?</aside>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_main(html: str) -> str:
    """Return inner HTML of main content area.

    FSA pages use <div id="main">, kantou (lfb.mof.go.jp) uses
    <div id="mainArea"> / <div id="mainAreaInner">. SESC mostly mirrors
    FSA.  Fall through to whole HTML if nothing matches.
    """
    for pat in (
        r"<main[^>]*>(.+?)</main>",
        r'<div\s+id="mainAreaInner"[^>]*>(.+?)<div\s+id="rightArea"',
        r'<div\s+id="mainArea"[^>]*>(.+?)<div\s+id="rightArea"',
        r'<div\s+id="mainArea"[^>]*>(.+?)<div\s+id="navigation"',
        r'<div\s+id="main"[^>]*>(.+?)<div\s+id="side"',
        r'<div\s+id="bodycontents"[^>]*>(.+?)</body>',
        r'<div\s+id="conteinar"[^>]*>(.+?)</body>',
    ):
        m = re.search(pat, html, re.S)
        if m:
            return m.group(1)
    return html


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str
    issuance_date: str
    issuing_authority: str
    enforcement_kind: str
    reason_summary: str
    related_law_ref: str
    source_url: str
    houjin_bangou: str | None = None
    amount_yen: int | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Title classification
# ---------------------------------------------------------------------------


def classify_kind(title: str, body: str) -> str:
    """Map title + body keyword to am_enforcement_detail.enforcement_kind."""
    s = _normalize(title) + " " + _normalize(body)[:400]
    # license_revoke beats business_improvement; fine beats both.
    if any(
        k in s
        for k in (
            "業務廃止命令",
            "業務停止命令",
            "登録取消",
            "取消し",
            "認可取消",
            "事業停止",
        )
    ):
        return "license_revoke"
    if "課徴金" in s or "罰金" in s or "過怠金" in s:
        return "fine"
    if "業務改善命令" in s or "改善命令" in s:
        return "business_improvement"
    if "報告徴求" in s or "報告徴収" in s:
        return "investigation"
    if "勧告" in s or "告発" in s or "警告" in s or "注意喚起" in s:
        return "investigation"
    return "other"


def passes_filter(title: str) -> bool:
    if not title:
        return False
    if any(x in title for x in KEYWORD_EXCLUDE):
        return False
    return any(k in title for k in KEYWORD_INCLUDE)


# ---------------------------------------------------------------------------
# Authority + law mapping by URL
# ---------------------------------------------------------------------------


def authority_from_url(url: str) -> str:
    if "/sesc/" in url:
        return "証券取引等監視委員会"
    if "lfb.mof.go.jp" in url:
        return "関東財務局"
    return "金融庁"


def law_ref_from_url(url: str, title: str = "", body: str = "") -> str:
    u = url.lower()
    s = title + body[:200]
    if "/sesc/" in u or "shouken" in u or "syouken" in u:
        return "金融商品取引法"
    if "ginkou" in u or "銀行" in s:
        return "銀行法"
    if "hoken" in u or "保険" in s:
        return "保険業法"
    if "kashikin" in u or "kasikin" in u or "貸金" in s:
        return "貸金業法"
    if "amlcft" in u:
        return "犯罪収益移転防止法"
    if "kinshotorihou" in u or "適格機関投資家" in s or "金融商品取引" in s:
        return "金融商品取引法"
    return "金融庁関係法令"


# ---------------------------------------------------------------------------
# Title cleanup → target_name
# ---------------------------------------------------------------------------


_TARGET_PAT = re.compile(
    r"^(.+?)(?:に対する行政処分|に対する課徴金|に対する業務改善命令|"
    r"に対する業務停止|に対する登録取消|に対する報告徴求|"
    r"に対する警告|に対する処分|"
    r"における[^：]+(?:虚偽記載|相場操縦|内部者取引|不正取引)|"
    r"による(?:相場操縦|内部者取引|有価証券報告書虚偽記載|偽計)|"
    r"の(?:相場操縦|内部者取引|不公正取引))"
)
_REMOVE_TAIL = re.compile(
    r"(について|に関する|の決定について|の公表|の更新|"
    r"の概要|を行いました|の検査結果|について（[^）]+）)$"
)


def extract_target_name(title: str, body_text: str = "") -> str:
    """Best-effort extraction of 事業者名 from title/body.

    1) Try title pattern '... に対する 行政処分 / 課徴金'.
    2) Try title pattern '...における ... 虚偽記載/相場操縦/内部者取引'.
    3) Fallback to body's first 株式会社/有限会社/合同会社 keyword span.
    """
    s = _normalize(title)
    s = re.sub(r"^[【\[「『][^】\]」』]+[】\]」』]\s*", "", s)
    s = re.sub(r":\s*金融庁$|：金融庁$", "", s)
    s = re.sub(r":\s*財務省関東財務局$|：財務省関東財務局$", "", s)
    s = re.sub(r":\s*証券取引等監視委員会$|：証券取引等監視委員会$", "", s)
    cand = None
    # 1) Direct '...に対する...' / 'における ... 虚偽記載'
    m = _TARGET_PAT.search(s)
    if m:
        cand = m.group(1).strip()
    # 2) 'X における ... 虚偽記載/相場操縦/内部者取引' — pull X
    if not cand:
        m2 = re.search(
            r"^(.+?)における[^（(]{0,30}"
            r"(?:虚偽記載|相場操縦|内部者取引|偽計|不公正取引|"
            r"不正取引|架空計上)",
            s,
        )
        if m2:
            cand = m2.group(1).strip()
    # 3) Fallback: pick first company-ish span from body
    if not cand or len(cand) < 2:
        b = _normalize(body_text)[:2000]
        bm = re.search(
            r"([\w・ー぀-ヿ一-鿿（）\(\)A-Za-z0-9\.&'\- ]+?"
            r"(?:株式会社|有限会社|合同会社|合資会社|合名会社|証券|信託"
            r"|銀行|保険|キャピタル|フィナンシャル|証券会社))",
            b,
        )
        if bm:
            cand = bm.group(1)
    if not cand:
        # last resort: trim title
        cand = _REMOVE_TAIL.sub("", s).strip()
    cand = re.sub(r"\s+", " ", cand).strip()
    # Strip *paired* outer wrappers only — leave (株) prefix intact.
    for open_c, close_c in (
        ("「", "」"),
        ("『", "』"),
        ("【", "】"),
        ("[", "]"),
    ):
        if cand.startswith(open_c) and cand.endswith(close_c):
            cand = cand[len(open_c) : -len(close_c)].strip()
    return cand[:200]


# ---------------------------------------------------------------------------
# Index page walkers
# ---------------------------------------------------------------------------


def _abs_url(base: str, href: str) -> str:
    # Drop URL fragments (e.g. #sp_summary) — they don't change the page.
    href = href.strip().split("#", 1)[0]
    if not href:
        return ""
    return urljoin(base, href)


_IDX_ANCHOR_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>([^<]{2,400})</a>', re.S)


def fetch_fsa_news_index(http: HttpClient) -> list[tuple[str, str]]:
    """Return [(url, title)] from FSA top news index, filtered by KEYWORD_INCLUDE."""
    out: list[tuple[str, str]] = []
    res = http.get(FSA_NEWS_INDEX, max_bytes=4 * 1024 * 1024)
    if not res.ok:
        _LOG.warning("[fsa] news index fetch fail status=%s", res.status)
        return out
    seen: set[str] = set()
    for m in _IDX_ANCHOR_RE.finditer(res.text):
        href = m.group(1)
        title = _normalize(m.group(2))
        if not title or not href:
            continue
        if not href.startswith("/news/r"):
            continue
        # Restrict to category subpaths
        if not re.match(
            r"^/news/r\d+/(ginkou|shouken|syouken|hoken|kashikin|kasikin|"
            r"amlcft|kokyakuhoni|sonota)/",
            href,
        ):
            continue
        if not passes_filter(title):
            continue
        url = _abs_url(FSA_NEWS_INDEX, href)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append((url, title))
    _LOG.info("[fsa-index] candidate articles=%d", len(out))
    return out


def fetch_fsa_kachoukin_index(http: HttpClient) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    res = http.get(FSA_KACHOUKIN_INDEX, max_bytes=2 * 1024 * 1024)
    if not res.ok:
        _LOG.warning("[fsa-kachoukin] fetch fail status=%s", res.status)
        return out
    seen: set[str] = set()
    # Only target /news/r{X}/shouken/{date}-N.html style case URLs.
    case_pat = re.compile(r"^/news/r\d+/shouken/[^/]+\.html$")
    for m in _IDX_ANCHOR_RE.finditer(res.text):
        href = m.group(1)
        title = _normalize(m.group(2))
        if not case_pat.match(href):
            continue
        url = _abs_url(FSA_KACHOUKIN_INDEX, href)
        if not url or url in seen:
            continue
        seen.add(url)
        # Title here is often only date — fetch detail later for real title.
        out.append((url, title or "課徴金納付命令"))
    _LOG.info("[fsa-kachoukin] candidate articles=%d", len(out))
    return out


def fetch_sesc_year_index(http: HttpClient, year: int) -> list[tuple[str, str]]:
    url = SESC_YEAR_FMT.format(year=year)
    res = http.get(url, max_bytes=2 * 1024 * 1024)
    if not res.ok:
        _LOG.warning("[sesc %d] index fetch fail status=%s", year, res.status)
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _IDX_ANCHOR_RE.finditer(res.text):
        href = m.group(1)
        title = _normalize(m.group(2))
        if not href:
            continue
        if not re.match(rf"^/sesc/news/c_{year}/{year}/\d{{8}}-\d+\.html$", href):
            continue
        absurl = _abs_url(url, href)
        if absurl in seen:
            continue
        seen.add(absurl)
        out.append((absurl, title or f"SESC {year}"))
    _LOG.info("[sesc %d] articles=%d", year, len(out))
    return out


def fetch_kantou_index(http: HttpClient, idx_url: str) -> list[tuple[str, str]]:
    """Pull (date,detail_url) pairs from a kantou enforcement index page.

    Pages list anchors whose title is 令和X年Y月Z日 (date), pointing to a
    detail page where target_name and 行政処分内容 live.
    """
    res = http.get(idx_url, max_bytes=2 * 1024 * 1024)
    if not res.ok:
        _LOG.warning("[kantou] %s fetch fail status=%s", idx_url, res.status)
        return []
    main_html = _extract_main(res.text)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in _IDX_ANCHOR_RE.finditer(main_html):
        href = m.group(1)
        title = _normalize(m.group(2))
        if not title:
            continue
        if not href.startswith("/kantou/kinyuu/"):
            continue
        if any(
            skip in href
            for skip in (
                "kashikin/mokuji",
                "shintaku/mokuji",
                "shogakutanki/mokuji",
                "touroku/mokuji",
                "/index.htm",
                "/index.html",
                "kinshotorihou/mokuji",
                "kinshotorihou/kinsho",
                "pagekthp00400016",
                "pagekthp00400017",
                "pagekthp00400022",
                "pagekthp00400034",
                "pagekthp00400036",
                "pagekthp00400037",
            )
        ):
            continue
        # date title? Accept "令和X年Y月Z日" or any 行政処分/警告 text
        if not (WAREKI_RE.search(title) or any(k in title for k in KEYWORD_INCLUDE)):
            continue
        url = _abs_url(idx_url, href)
        if url in seen:
            continue
        seen.add(url)
        out.append((url, title))
    _LOG.info("[kantou] %s articles=%d", urlparse(idx_url).path, len(out))
    return out


# ---------------------------------------------------------------------------
# Article parser
# ---------------------------------------------------------------------------


def parse_article(
    http: HttpClient,
    url: str,
    fallback_title: str,
) -> EnfRow | None:
    res = http.get(url, max_bytes=4 * 1024 * 1024)
    if not res.ok:
        _LOG.debug("[article] fetch fail %s status=%s", url, res.status)
        return None
    html = res.text
    # Title
    tm = re.search(r"<title>([^<]+)</title>", html)
    raw_title = _normalize(tm.group(1)) if tm else fallback_title
    # Strip site suffix
    title_clean = re.sub(r"[:：]\s*金融庁$", "", raw_title)
    title_clean = re.sub(r"[:：]\s*財務省関東財務局$", "", title_clean)
    title_clean = re.sub(r"[:：]\s*証券取引等監視委員会$", "", title_clean)
    main_html = _extract_main(html)
    body_text = _html_to_text(main_html)
    # Final filter: must contain at least one enforcement keyword
    if not (
        any(k in title_clean for k in KEYWORD_INCLUDE)
        or any(k in body_text[:1500] for k in KEYWORD_INCLUDE)
    ):
        return None
    # Issuance date: prefer first 令和X年Y月Z日 in body
    date_iso = None
    for m in WAREKI_RE.finditer(body_text):
        date_iso = _parse_wareki(m.group(0))
        if date_iso:
            break
    if not date_iso:
        date_iso = _parse_wareki(title_clean)
    if not date_iso:
        return None
    target = extract_target_name(title_clean, body_text)
    if not target or len(target) < 2:
        return None
    authority = authority_from_url(url)
    kind = classify_kind(title_clean, body_text)
    law_ref = law_ref_from_url(url, title_clean, body_text)
    amount = _parse_yen(body_text) if kind == "fine" else None
    houjin = _parse_houjin(body_text)
    reason = (f"{title_clean[:200]} | {body_text[:1200]}")[:1500]
    return EnfRow(
        target_name=target,
        issuance_date=date_iso,
        issuing_authority=authority,
        enforcement_kind=kind,
        reason_summary=reason,
        related_law_ref=law_ref,
        source_url=url,
        houjin_bangou=houjin,
        amount_yen=amount,
        extra={"title": title_clean[:300]},
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def collect_candidate_urls(http: HttpClient) -> list[tuple[str, str]]:
    """Build a deduped list of (article_url, hint_title) across all sources."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add_many(rows: list[tuple[str, str]]) -> None:
        for url, title in rows:
            if url in seen:
                continue
            seen.add(url)
            out.append((url, title))

    # Highest priority: FSA 課徴金 list (most likely to have amount_yen)
    _add_many(fetch_fsa_kachoukin_index(http))
    # Top news index (291 entries)
    _add_many(fetch_fsa_news_index(http))
    # SESC years
    for y in SESC_YEARS:
        _add_many(fetch_sesc_year_index(http, y))
    # Kantou enforcement listings
    for idx in KANTOU_INDEX_URLS:
        _add_many(fetch_kantou_index(http, idx))
    _LOG.info("total candidate URLs=%d", len(out))
    return out


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug8(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:8]


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def existing_dedup_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    cur = conn.execute(
        "SELECT issuing_authority, issuance_date, target_name "
        "FROM am_enforcement_detail "
        "WHERE issuing_authority IN ('金融庁','証券取引等監視委員会','関東財務局')"
    )
    for a, d, n in cur.fetchall():
        if a and d and n:
            out.add((a, d, n))
    return out


def upsert_entity_and_enforcement(
    conn: sqlite3.Connection,
    row: EnfRow,
    seq: int,
    now_iso: str,
) -> None:
    slug = _slug8(row.issuing_authority, row.issuance_date, row.target_name)
    canonical_id = f"AM-ENF-FSA-{slug}{seq:04d}"
    domain = urlparse(row.source_url).netloc or None
    primary_name = (
        f"{row.target_name} ({row.issuance_date}) - {row.issuing_authority} {row.enforcement_kind}"
    )[:500]
    raw_json = json.dumps(
        {
            "target_name": row.target_name,
            "issuance_date": row.issuance_date,
            "issuing_authority": row.issuing_authority,
            "enforcement_kind": row.enforcement_kind,
            "related_law_ref": row.related_law_ref,
            "amount_yen": row.amount_yen,
            "houjin_bangou": row.houjin_bangou,
            "reason_summary": row.reason_summary,
            "source_url": row.source_url,
            "extra": row.extra,
            "source_attribution": (
                "金融庁ウェブサイト"
                if row.issuing_authority == "金融庁"
                else (
                    "証券取引等監視委員会ウェブサイト"
                    if row.issuing_authority == "証券取引等監視委員会"
                    else "財務省関東財務局ウェブサイト"
                )
            ),
            "license": "政府機関の著作物（出典明記で転載引用可）",
        },
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            canonical_status, citation_status
        ) VALUES (?, 'enforcement', 'fsa_admin_action', NULL,
                  ?, NULL, 0.9, ?, ?, ?, ?, 'active', 'ok')
        ON CONFLICT(canonical_id) DO UPDATE SET
            primary_name      = excluded.primary_name,
            source_url        = excluded.source_url,
            source_url_domain = excluded.source_url_domain,
            fetched_at        = excluded.fetched_at,
            raw_json          = excluded.raw_json,
            updated_at        = datetime('now')
        """,
        (
            canonical_id,
            primary_name,
            row.source_url,
            domain,
            now_iso,
            raw_json,
        ),
    )
    conn.execute(
        """
        INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen,
            source_url, source_fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            row.houjin_bangou,
            row.target_name[:500],
            row.enforcement_kind,
            row.issuing_authority,
            row.issuance_date,
            row.reason_summary[:4000],
            row.related_law_ref[:1000],
            row.amount_yen,
            row.source_url,
            now_iso,
        ),
    )


def write_rows(
    conn: sqlite3.Connection,
    rows: list[EnfRow],
    *,
    now_iso: str,
    max_inserts: int,
) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0
    db_keys = existing_dedup_keys(conn)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = dup_db = dup_batch = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for r in rows:
            if inserted >= max_inserts:
                break
            key = (r.issuing_authority, r.issuance_date, r.target_name)
            if key in db_keys:
                dup_db += 1
                continue
            if key in batch_keys:
                dup_batch += 1
                continue
            batch_keys.add(key)
            try:
                upsert_entity_and_enforcement(conn, r, inserted, now_iso)
                inserted += 1
            except sqlite3.Error as exc:
                _LOG.error(
                    "insert error name=%r date=%s err=%s",
                    r.target_name,
                    r.issuance_date,
                    exc,
                )
                continue
        conn.commit()
    except sqlite3.Error as exc:
        _LOG.error("BEGIN/commit failed: %s", exc)
        with contextlib.suppress(sqlite3.Error):
            conn.rollback()
    return inserted, dup_db, dup_batch


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--max-rows", type=int, default=400)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    http = HttpClient(user_agent=USER_AGENT)
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    candidates = collect_candidate_urls(http)
    parsed: list[EnfRow] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for i, (url, hint) in enumerate(candidates):
        if len(parsed) >= args.max_rows:
            break
        row = parse_article(http, url, hint)
        if not row:
            continue
        k = (row.issuing_authority, row.issuance_date, row.target_name)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        parsed.append(row)
        if (i + 1) % 25 == 0:
            _LOG.info("[parse] processed=%d parsed=%d", i + 1, len(parsed))
    _LOG.info("total parsed=%d", len(parsed))

    if args.dry_run:
        for r in parsed[:5]:
            _LOG.info(
                "sample: name=%s date=%s auth=%s kind=%s law=%s amt=%s",
                r.target_name,
                r.issuance_date,
                r.issuing_authority,
                r.enforcement_kind,
                r.related_law_ref,
                r.amount_yen,
            )
        http.close()
        return 0

    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        http.close()
        return 2
    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_tables(conn)

    inserted, dup_db, dup_batch = write_rows(
        conn,
        parsed,
        now_iso=now_iso,
        max_inserts=args.max_rows,
    )
    with contextlib.suppress(sqlite3.Error):
        conn.close()
    http.close()

    # Breakdown
    print(
        f"FSA enforcement ingest: candidates={len(candidates)} "
        f"parsed={len(parsed)} inserted={inserted} "
        f"dup_db={dup_db} dup_batch={dup_batch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
