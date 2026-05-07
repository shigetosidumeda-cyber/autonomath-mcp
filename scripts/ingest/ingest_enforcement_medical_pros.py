#!/usr/bin/env python3
"""Ingest 厚労省 医道審議会 行政処分 (医師/歯科医師/看護師/保健師/助産師/薬剤師)
into ``am_enforcement_detail``.

Background:
  Twice a year the 厚生労働省 医道審議会 publishes 議事要旨 / 議事概要
  enumerating the 行政処分 issued under:

    - 医師法 (4条/7条)              — 医道分科会
    - 歯科医師法 (4条/7条)          — 医道分科会 (combined page)
    - 保健師助産師看護師法 (14条)   — 看護倫理部会
    - 薬剤師法 (5条/8条)            — 薬剤師倫理部会

  Individual practitioner names are NOT publicly disclosed (privacy
  policy); the publication exposes per-publication aggregate counts by
  処分種別 × 違反法令. Each "1件" inside that aggregate is a distinct
  practitioner — we materialize one ``am_enforcement_detail`` row per
  件 with a synthetic anonymized ``target_name``.

  Sources walked:
    - 医道分科会 index:
        /stf/shingi/shingi-idou_127786.html
      (links to ~17 議事要旨 HTML pages, 2017→2026)
    - 看護倫理部会 index:
        /stf/shingi/shingi-idou_127798.html
      (links to ~6-8 議事要旨 HTML pages, 2018→2026)
    - 薬剤師倫理部会 index:
        /stf/shingi/shingi-idou_127806.html
      (links to ~20+ 議事要旨 PDFs)

Schema mapping:
  - enforcement_kind:
      免許取消 → 'license_revoke'
      業務停止 / 医業停止 / 歯科医業停止 → 'business_improvement'
      戒告 → 'other'
      再教育研修命令 → 'other'
  - issuing_authority = '厚生労働省' (大臣処分, all rows)
  - target_name = "医師 #N (氏名非公表)" / "看護師 #N (氏名非公表)" etc.
    We DO NOT fabricate names. The MHLW publication itself names no
    individuals; we anonymize uniformly.
  - related_law_ref = '医師法' / '歯科医師法' / '保健師助産師看護師法' /
    '薬剤師法' + 第N条 where derivable.
  - reason_summary = full 罪種 phrase from the publication
    (e.g. '麻薬及び向精神薬取締法違反').
  - amount_yen = NULL (medical 処分 are non-monetary).

Parallel-write:
  - BEGIN IMMEDIATE + busy_timeout=300000.
  - Single transaction at end (small batch ≤1000 rows, low contention).

Dedup:
  - Within batch and against DB: composite key
    (issuing_authority, issuance_date, target_name) — target_name
    embeds the per-publication sequence so re-runs are idempotent.

CLI:
    python scripts/ingest/ingest_enforcement_medical_pros.py \\
        [--db autonomath.db] [--dry-run] [--max-insert N] [--verbose]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import re
import sqlite3
import sys
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: beautifulsoup4 not installed: {exc}", file=sys.stderr)
    raise

try:
    from pdfminer.high_level import extract_text as pdf_extract_text  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: pdfminer.six not installed: {exc}", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import contextlib

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.medical_pros")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
MHLW_AUTHORITY = "厚生労働省"
BASE = "https://www.mhlw.go.jp"

# Index pages — each lists 議事要旨 anchors per publication.
INDEX_IDOU = f"{BASE}/stf/shingi/shingi-idou_127786.html"  # 医道分科会 (医師+歯科医師)
INDEX_KANGO = f"{BASE}/stf/shingi/shingi-idou_127798.html"  # 看護倫理部会
INDEX_YAKU = f"{BASE}/stf/shingi/shingi-idou_127806.html"  # 薬剤師倫理部会


# ---------------------------------------------------------------------------
# Date / numeral parsing
# ---------------------------------------------------------------------------

_FULLWIDTH_DIGIT = str.maketrans("０１２３４５６７８９", "0123456789")
_KANJI_NUM = {
    "零": 0,
    "〇": 0,
    "○": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

ERA_OFFSET = {
    "令和": 2018,
    "平成": 1988,
    "昭和": 1925,
    "R": 2018,
    "H": 1988,
    "S": 1925,
}

_WAREKI_RE = re.compile(r"(令和|平成|昭和)\s*(\d+|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
_DATE_TITLE_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_date_in_text(text: str) -> str | None:
    """Find the first usable issuance date in the text body.

    Priority:
      1. 西暦 ``YYYY年M月D日`` (used in page titles).
      2. 和暦 ``令和N年M月D日`` (used in 日時 line).
    """
    if not text:
        return None
    s = _normalize(text)
    s = s.translate(_FULLWIDTH_DIGIT)

    m = _DATE_TITLE_RE.search(s)
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


def _parse_count(token: str) -> int | None:
    """Parse ``N件`` where N may be ASCII / fullwidth / kanji digit."""
    if not token:
        return None
    t = unicodedata.normalize("NFKC", token).strip()
    m = re.search(r"(\d+)\s*件", t)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 999 else None
    # kanji single digit like 一件
    m2 = re.search(r"([零〇○一二三四五六七八九十])\s*件", t)
    if m2:
        ch = m2.group(1)
        v = _KANJI_NUM.get(ch)
        if v is not None and 1 <= v <= 99:
            return v
    return None


# ---------------------------------------------------------------------------
# Index discovery
# ---------------------------------------------------------------------------


@dataclass
class Publication:
    url: str
    is_pdf: bool
    feed: str  # 'idou' / 'kango' / 'yaku'


def discover_publications(http: HttpClient) -> list[Publication]:
    """Walk index pages, collect 議事要旨 / 議事概要 detail anchors."""
    out: list[Publication] = []
    seen: set[str] = set()
    for index_url, feed in (
        (INDEX_IDOU, "idou"),
        (INDEX_KANGO, "kango"),
        (INDEX_YAKU, "yaku"),
    ):
        res = http.get(index_url)
        if not res.ok:
            _LOG.warning("[index] fetch fail %s status=%s", index_url, res.status)
            continue
        soup = BeautifulSoup(res.text, "html.parser")
        for a in soup.find_all("a"):
            href = (a.get("href") or "").strip()
            txt = _normalize(a.get_text(" ", strip=True))
            if not href or not txt:
                continue
            # Filter to 議事要旨 / 議事概要 anchors only.
            if "議事要旨" not in txt and "議事概要" not in txt:
                continue
            # Resolve relative URLs.
            absurl = urljoin(index_url, href)
            # Restrict to mhlw.go.jp.
            if "mhlw.go.jp" not in urlparse(absurl).netloc:
                continue
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(
                Publication(
                    url=absurl,
                    is_pdf=absurl.lower().endswith(".pdf"),
                    feed=feed,
                )
            )
        _LOG.info("[index] %s -> total publications=%d", feed, len(out))
    _LOG.info("[index] discovered total=%d publications", len(out))
    return out


# ---------------------------------------------------------------------------
# Body extraction
# ---------------------------------------------------------------------------

# Match a single concrete enforcement event line. The publications use
# patterns like:
#   "免許取消・・・・・・・・１件（強制わいせつ致傷１件）"
#   "医業停止２年・・・・・・１件（麻薬及び向精神薬取締法違反１件）"
#   "業務停止３月　　　　 ９件（道路交通法違反４件、暴行４件）"
#   "戒告・・・・・・・・・・２件（傷害１件、廃棄物の処理及び清掃に関する法律違反１件）"
#
# Strategy: find KIND lines up to the closing paren, then split inside
# the paren on '、' (full-width comma) to recover the per-罪種 sub-counts.

# Possible 処分 prefixes by feed.
_KIND_PATTERNS_DOC = [
    ("license_revoke", re.compile(r"免\s*許\s*取\s*消")),
    ("business_improvement", re.compile(r"(?:歯科)?医業\s*停\s*止\s*\d+\s*年\s*\d+\s*月")),
    ("business_improvement", re.compile(r"(?:歯科)?医業\s*停\s*止\s*\d+\s*年")),
    ("business_improvement", re.compile(r"(?:歯科)?医業\s*停\s*止\s*\d+\s*月")),
    ("other", re.compile(r"戒\s*告")),
    ("other", re.compile(r"再教育研修")),
]
_KIND_PATTERNS_NURSE = [
    ("license_revoke", re.compile(r"免\s*許\s*取\s*消")),
    ("business_improvement", re.compile(r"業\s*務\s*停\s*止\s*\d+\s*年\s*\d+\s*月")),
    ("business_improvement", re.compile(r"業\s*務\s*停\s*止\s*\d+\s*年")),
    ("business_improvement", re.compile(r"業\s*務\s*停\s*止\s*\d+\s*月")),
    ("other", re.compile(r"戒\s*告")),
]
# Same as nurse — 薬剤師 uses 業務停止/戒告 vocabulary too.
_KIND_PATTERNS_PHARMA = list(_KIND_PATTERNS_NURSE)

# 罪種 splitter inside the paren — '、' separates entries.
_REASON_SPLIT_RE = re.compile(r"[、，]")


@dataclass
class EnfRow:
    kind_label: str  # original line (e.g., '医業停止２年')
    enforcement_kind: str  # checked enum
    profession: str  # '医師'/'歯科医師'/'看護師'/'保健師'/'薬剤師'/...
    reason_text: str  # 罪種 (e.g. '麻薬及び向精神薬取締法違反')
    issuance_date: str
    source_url: str
    related_law_ref: str
    publication_url: str  # may equal source_url for HTML; for PDF it's the PDF URL
    feed: str  # 'idou'/'kango'/'yaku'


def _detect_section(line: str, feed: str) -> str | None:
    """Identify a section header line for profession breakdown."""
    s = _normalize(line)
    # 医道: '（医師）11件' / '（歯科医師）6件' or '医師　12件'
    if "医師" in s and "歯科" not in s and re.search(r"\d+\s*件", s):
        # Only when at start of line / before count
        if "歯科医師" not in s:
            return "医師"
    if "歯科医師" in s and re.search(r"\d+\s*件", s):
        return "歯科医師"
    # 看護: section headers often missing — treat default = 看護師
    return None


def _law_for(profession: str) -> str:
    """Return the canonical 関連法 string for the profession."""
    return {
        "医師": "医師法",
        "歯科医師": "歯科医師法",
        "看護師": "保健師助産師看護師法",
        "保健師": "保健師助産師看護師法",
        "助産師": "保健師助産師看護師法",
        "准看護師": "保健師助産師看護師法",
        "薬剤師": "薬剤師法",
    }.get(profession, "保健師助産師看護師法")


def _kind_patterns_for(feed: str) -> list[tuple[str, re.Pattern[str]]]:
    if feed == "idou":
        return _KIND_PATTERNS_DOC
    if feed == "yaku":
        return _KIND_PATTERNS_PHARMA
    return _KIND_PATTERNS_NURSE


def _default_profession(feed: str) -> str:
    return {"idou": "医師", "kango": "看護師", "yaku": "薬剤師"}.get(feed, "看護師")


def _extract_body_text(html: str) -> str:
    """Extract the article body text (post-nav)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main") or soup.find(id="content")
    if main:
        return main.get_text("\n", strip=True)
    return soup.get_text("\n", strip=True)


_PARSE_HEAD = re.compile(r"答\s*申\s*の\s*概\s*要|【答申の概要】|\[答申の概要\]")


def _slice_after_head(text: str) -> str:
    m = _PARSE_HEAD.search(text)
    if not m:
        return text
    return text[m.end() :]


_PROFESSION_SECTION_RE = re.compile(
    r"[（(]?\s*(医師|歯科医師|看護師|保健師|助産師|准看護師|薬剤師)\s*[）)]?\s*" r"\d+\s*件"
)


def _split_into_sections(body: str, feed: str) -> list[tuple[str, str]]:
    """Return [(profession, sub_text), ...]. If no section markers → one
    (default_profession, body) tuple."""
    matches = list(_PROFESSION_SECTION_RE.finditer(body))
    if not matches:
        return [(_default_profession(feed), body)]
    out: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        prof = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out.append((prof, body[start:end]))
    return out


_KIND_LINE_RE = re.compile(
    # KIND ... N件 (ROUTE) — dotted leaders / colons / spaces are flexible.
    # The reasons paren MAY contain nested parens (e.g. '刑法違反（有印…）').
    r"(?P<kind>(?:免\s*許\s*取\s*消"
    r"|(?:歯科)?医業\s*停\s*止\s*(?:\d+\s*年(?:\s*\d+\s*月)?|\d+\s*月)"
    r"|業\s*務\s*停\s*止\s*(?:\d+\s*年(?:\s*\d+\s*月)?|\d+\s*月|\d+\s*年)"
    r"|戒\s*告"
    r"|再教育研修(?:命令)?))\s*"
    r"[・･\s\.：:]*"  # dotted leaders / colons / spaces
    r"(?P<count>\d+)\s*件\s*"
    r"[（(](?P<reasons>(?:[^（）()]|（[^（）]*）|\([^()]*\))*)[)）]",
    re.MULTILINE,
)


def _classify_kind(kind_label: str, feed: str) -> str:
    label = _normalize(kind_label)
    for code, pat in _kind_patterns_for(feed):
        if pat.search(label):
            return code
    if "免許" in label:
        return "license_revoke"
    if "停止" in label:
        return "business_improvement"
    if "戒告" in label:
        return "other"
    return "other"


_REASON_TRIM_LEFT_RE = re.compile(r"^[\s　・･\.,，。．、①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮]+")
_NUMERIC_PREFIX_RE = re.compile(r"^[\s　]*\d+\s*[\.。．、,，)）]\s*")


def _clean_reason_token(s: str) -> str:
    """Normalize a single 罪種 token: strip outer whitespace, leading
    bullet/numeric prefixes ('1.', '2．', '①'), and stray newlines.

    The publications sometimes break a long compound 罪種 across lines like
        '1\n.\n児童買春…'
    after the dotted-leader pass. We collapse internal whitespace and
    strip those prefix decorations.
    """
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", s)
    t = re.sub(r"\s+", "", t)  # collapse all whitespace including newlines
    # Strip leading numeric "1." or "1." or kanji "①" markers.
    t = _NUMERIC_PREFIX_RE.sub("", t)
    t = _REASON_TRIM_LEFT_RE.sub("", t)
    t = t.rstrip("。、")
    return t


_REASON_ENTRY_RE = re.compile(
    # capture everything (including nested parens, embedded 、) up to the
    # NEXT N件 terminator. Entries are separated by N件 itself, then an
    # optional 、 + space.
    r"(?P<reason>(?:[^（）()]|（[^（）]*）|\([^()]*\))+?)" r"(?P<n>\d+)\s*件"
)


def _parse_reasons(reasons_blob: str) -> list[tuple[str, int]]:
    """Extract per-罪種 (reason, count) pairs from the paren content.

    Each entry is the text up to (and ending with) ``N件``. Adjacent
    entries are separated by 、 and possibly whitespace, but commas
    *inside* a 罪種 (like '医薬品、医療機器等の…') are part of that
    single 罪種 — we never split on 、.

    Examples:
        '麻薬及び向精神薬取締法違反１件'
            -> [('麻薬及び向精神薬取締法違反', 1)]
        '道路交通法違反４件、暴行４件'
            -> [('道路交通法違反', 4), ('暴行', 4)]
        '所得税法違反、詐欺、医薬品、医療機器等の品質、有効性及び安全性の'
        '確保等に関する法律違反１件、岡山県迷惑行為防止条例違反、児童買春…'
        '１件、不同意わいせつ１件'
            -> 3 entries (one for each terminating N件), each entry's
               reason text including its own internal 、.
    """
    out: list[tuple[str, int]] = []
    if not reasons_blob:
        return out
    blob = unicodedata.normalize("NFKC", reasons_blob)
    # Drop leading separators.
    blob = blob.lstrip("、, 　")
    for m in _REASON_ENTRY_RE.finditer(blob):
        raw_reason = m.group("reason")
        n_str = m.group("n")
        try:
            n = int(n_str)
        except ValueError:
            continue
        if not 1 <= n <= 99:
            continue
        # Strip leading 、/space carried in from prior entry boundary.
        cleaned = raw_reason.lstrip("、, 　").rstrip("、, 　")
        cleaned = _clean_reason_token(cleaned)
        if not cleaned or len(cleaned) > 400:
            continue
        out.append((cleaned, n))
        m.end()
    if not out:
        # No N件 markers — treat the whole blob as one event count=1.
        token = _clean_reason_token(blob)
        if token and len(token) <= 400:
            out.append((token, 1))
    return out


def parse_publication(
    body_text: str,
    *,
    source_url: str,
    feed: str,
    fallback_date: str | None = None,
) -> list[EnfRow]:
    """Return one EnfRow per individual 件 in the publication."""
    out: list[EnfRow] = []
    if not body_text:
        return out
    # Find issuance date from anywhere in the body (e.g. 日時 line).
    issuance = _parse_date_in_text(body_text) or fallback_date
    if not issuance:
        _LOG.debug("[parse] no date found url=%s", source_url)
        return out

    # Restrict parsing to the section after 答申の概要.
    head_text = _slice_after_head(body_text)
    sections = _split_into_sections(head_text, feed)

    for prof, sub_text in sections:
        for m in _KIND_LINE_RE.finditer(sub_text):
            kind_label = _normalize(m.group("kind"))
            try:
                total = int(m.group("count"))
            except ValueError:
                continue
            if not 1 <= total <= 200:
                continue
            reasons = _parse_reasons(m.group("reasons"))
            sum_reasons = sum(n for _, n in reasons)

            # Materialize per-event rows. If we recovered explicit
            # 罪種 counts that sum to >= total, expand each. Otherwise
            # synthesize from available reasons; if no reasons parsed,
            # emit total rows with reason_text='不明'.
            enf_kind = _classify_kind(kind_label, feed)

            if reasons and sum_reasons >= total:
                # Cap at total — sometimes reasons over-attribute.
                emitted = 0
                for reason, n in reasons:
                    for _ in range(n):
                        if emitted >= total:
                            break
                        out.append(
                            EnfRow(
                                kind_label=kind_label,
                                enforcement_kind=enf_kind,
                                profession=prof,
                                reason_text=reason,
                                issuance_date=issuance,
                                source_url=source_url,
                                related_law_ref=_law_for(prof),
                                publication_url=source_url,
                                feed=feed,
                            )
                        )
                        emitted += 1
            else:
                # Distribute reasons but pad with first reason if short.
                expanded: list[str] = []
                for reason, n in reasons:
                    expanded.extend([reason] * n)
                while len(expanded) < total:
                    expanded.append(expanded[0] if expanded else "不明")
                expanded = expanded[:total]
                for reason in expanded:
                    out.append(
                        EnfRow(
                            kind_label=kind_label,
                            enforcement_kind=enf_kind,
                            profession=prof,
                            reason_text=reason,
                            issuance_date=issuance,
                            source_url=source_url,
                            related_law_ref=_law_for(prof),
                            publication_url=source_url,
                            feed=feed,
                        )
                    )
    return out


def fetch_publication_rows(
    http: HttpClient,
    pub: Publication,
) -> list[EnfRow]:
    """Fetch one publication and return parsed EnfRows."""
    if pub.is_pdf:
        res = http.get(pub.url, max_bytes=10 * 1024 * 1024)
        if not res.ok:
            _LOG.warning("[fetch] PDF fail %s status=%s", pub.url, res.status)
            return []
        try:
            text = pdf_extract_text(io.BytesIO(res.body))
        except Exception as exc:  # broad — pdfminer raises various
            _LOG.warning("[fetch] PDF parse fail %s: %s", pub.url, exc)
            return []
        return parse_publication(
            text,
            source_url=pub.url,
            feed=pub.feed,
        )
    # HTML
    res = http.get(pub.url)
    if not res.ok:
        _LOG.warning("[fetch] HTML fail %s status=%s", pub.url, res.status)
        return []
    body = _extract_body_text(res.text)
    return parse_publication(
        body,
        source_url=pub.url,
        feed=pub.feed,
    )


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug8(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return h[:8]


def _kind_slug(profession: str) -> str:
    return {
        "医師": "ISHI",
        "歯科医師": "SHIKA",
        "看護師": "KANGO",
        "保健師": "HOKEN",
        "助産師": "JOSAN",
        "准看護師": "JUNKAN",
        "薬剤師": "YAKUZAISHI",
    }.get(profession, "MED")


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def existing_dedup_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    """Return {(target_name, issuance_date, issuing_authority)} for prior
    medical-pros rows so reruns are idempotent.

    We restrict to rows whose source_topic was set by this script (or whose
    target_name carries our anonymized prefix), which avoids over-matching
    against unrelated MHLW rows.
    """
    out: set[tuple[str, str, str]] = set()
    cur = conn.execute(
        "SELECT target_name, issuance_date, issuing_authority "
        "FROM am_enforcement_detail "
        "WHERE issuing_authority = ? "
        "  AND ( target_name LIKE '医師 #%' "
        "     OR target_name LIKE '歯科医師 #%' "
        "     OR target_name LIKE '看護師 #%' "
        "     OR target_name LIKE '保健師 #%' "
        "     OR target_name LIKE '助産師 #%' "
        "     OR target_name LIKE '准看護師 #%' "
        "     OR target_name LIKE '薬剤師 #%' )",
        (MHLW_AUTHORITY,),
    )
    for n, d, a in cur.fetchall():
        if n and d and a:
            out.add((n, d, a))
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
        ) VALUES (?, 'enforcement', 'mhlw_idou_medical_pros', NULL,
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
    enf_kind: str,
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
        ) VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, ?, ?)
        """,
        (
            entity_id,
            target_name[:500],
            enf_kind,
            MHLW_AUTHORITY,
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

    # Sequential per-publication numbering — for stable target_name across
    # reruns we hash (publication_url, profession, kind_label, reason_text,
    # idx-within-line). Build that upfront.
    counter: dict[tuple[str, str], int] = {}

    try:
        conn.execute("BEGIN IMMEDIATE")
        for r in rows:
            if max_insert is not None and inserted >= max_insert:
                break
            # Per-publication counter keyed by profession.
            ck = (r.publication_url, r.profession)
            counter[ck] = counter.get(ck, 0) + 1
            seq = counter[ck]
            # Compose anonymized target_name with publication-stable seq.
            target_name = f"{r.profession} #{seq:03d} (氏名非公表)"

            key = (target_name, r.issuance_date, MHLW_AUTHORITY)
            if key in db_keys:
                dup_db += 1
                continue
            if key in batch_keys:
                dup_batch += 1
                continue
            batch_keys.add(key)

            kind_short = _kind_slug(r.profession)
            slug = _slug8(
                r.publication_url,
                r.profession,
                str(seq),
                r.kind_label,
            )
            canonical_id = f"AM-ENF-MED-{kind_short}-{r.issuance_date.replace('-', '')}-{slug}"
            primary_name = f"{target_name} - {r.kind_label} ({r.reason_text[:60]})"
            reason_summary = (
                f"医道審議会答申: {r.kind_label} / 違反: {r.reason_text} "
                f"(関連法: {r.related_law_ref}; 個人氏名は非公表)"
            )
            raw_json = json.dumps(
                {
                    "profession": r.profession,
                    "kind_label": r.kind_label,
                    "enforcement_kind": r.enforcement_kind,
                    "reason_text": r.reason_text,
                    "issuance_date": r.issuance_date,
                    "issuing_authority": MHLW_AUTHORITY,
                    "related_law_ref": r.related_law_ref,
                    "source_url": r.source_url,
                    "publication_url": r.publication_url,
                    "feed": r.feed,
                    "anonymized": True,
                    "source_attribution": "厚生労働省 医道審議会",
                    "license": "政府機関の著作物（出典明記で転載引用可）",
                },
                ensure_ascii=False,
            )
            try:
                upsert_entity(
                    conn,
                    canonical_id,
                    primary_name,
                    r.source_url,
                    raw_json,
                    now_iso,
                )
                insert_enforcement(
                    conn,
                    canonical_id,
                    target_name,
                    r.enforcement_kind,
                    r.issuance_date,
                    reason_summary,
                    r.related_law_ref,
                    r.source_url,
                    now_iso,
                )
                inserted += 1
            except sqlite3.Error as exc:
                _LOG.error(
                    "DB error name=%r date=%s: %s",
                    target_name,
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
# CLI orchestrator
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--max-insert",
        type=int,
        default=None,
        help="Stop after N successful inserts (for incremental runs)",
    )
    ap.add_argument(
        "--max-publications",
        type=int,
        default=None,
        help="Limit how many publications to fetch (debug)",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    http = HttpClient(user_agent=USER_AGENT)
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    pubs = discover_publications(http)
    if args.max_publications:
        pubs = pubs[: args.max_publications]
    _LOG.info("walking %d publications", len(pubs))

    all_rows: list[EnfRow] = []
    for i, pub in enumerate(pubs, 1):
        rows = fetch_publication_rows(http, pub)
        _LOG.info(
            "[%d/%d] %s feed=%s rows=%d",
            i,
            len(pubs),
            pub.url,
            pub.feed,
            len(rows),
        )
        all_rows.extend(rows)

    _LOG.info("total parsed events=%d", len(all_rows))

    if args.dry_run:
        for r in all_rows[:10]:
            _LOG.info(
                "sample: prof=%s kind=%s date=%s reason=%s",
                r.profession,
                r.kind_label,
                r.issuance_date,
                r.reason_text[:60],
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
        all_rows,
        now_iso=now_iso,
        max_insert=args.max_insert,
    )
    with contextlib.suppress(sqlite3.Error):
        conn.close()
    http.close()

    _LOG.info(
        "done parsed=%d inserted=%d dup_db=%d dup_batch=%d",
        len(all_rows),
        inserted,
        dup_db,
        dup_batch,
    )
    print(
        f"MHLW 医道審議会 ingest: parsed={len(all_rows)} "
        f"inserted={inserted} dup_db={dup_db} dup_batch={dup_batch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
