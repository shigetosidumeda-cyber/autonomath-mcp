#!/usr/bin/env python3
"""Ingest 国土交通省 (本省+営繕+THR/HRR/KKR/SKR) + 政令指定都市 公共工事入札
**指名停止業者公表** into ``am_entities`` + ``am_enforcement_detail``.

Background:
  既に am_enforcement_detail (autonomath.db) に
    - mlit_kensetugyousya (中央建設業許可監督処分) 2,012 件
    - mlit_chiho_pref (Hkd/Cbr/Cgr/Qsr/Ktr + Osaka府) 214 件
    - pref_shimei_teishi (47 都道府県の一部) 0 件 ※未起動
  本 script は **MLIT 本省 (大臣官房+営繕部) + 残 4 局 (THR/HRR/KKR/SKR) +
  政令指定都市 (Saitama/Chiba/Yokohama/Kawasaki/Nagoya/Kobe + Kyoto府)** を
  追加層として取り込む。

Sources (primary, TOS無視, aggregator banned):
  ===== MLIT 本省 (大臣官房) =====
  - 大臣官房会計課 指名停止: https://www.mlit.go.jp/page/kanbo05_hy_003092.html
        → /page/content/001590926.pdf (table 形式 法人番号入)
  - 大臣官房官庁営繕部 指名停止: https://www.mlit.go.jp/report/press/eizen01_hh_000282.html
        → 別紙 PDF (single-case 形式)

  ===== 残 4 地方整備局 =====
  - 東北 (THR): https://www.thr.mlit.go.jp/Bumon/B00013/K00730/simeiteisi/R{5,6,7,8}simeiteisi.pdf
        → 累積一覧 PDF (table 形式)
  - 北陸 (HRR): https://www.hrr.mlit.go.jp/ home page links to
        press/{YYYY}/{M}/{YYMMDD}soumubu*.pdf (single-case 形式)
  - 近畿 (KKR): https://www.kkr.mlit.go.jp/n_info/{idx}.html
        → -att/aXXXX.pdf (single-case 形式) 80+ 件
  - 四国 (SKR): https://www.skr.mlit.go.jp/send/shimei/index.html (Shift_JIS)
        → R{N}/{YYYYMMDD}.pdf (single-case 形式)

  ===== 政令指定都市 (建設業者 + 物品委託) =====
  - さいたま市: /005/001/017/011/002/p008392_d/fil/R{3..8}teisiitiran.pdf
  - 千葉市: /zaiseikyoku/shisan/keiyaku/documents/{08,07}simeiteisi*.pdf
  - 川崎市: /233300/cmsfiles/contents/0000090/90252/{YYMMDD}shimeiteishiichiran.pdf
  - 横浜市: keiyaku.city.yokohama.lg.jp epco MeiboTeishiList (Shift_JIS form)
  - 名古屋市: chotatsu.city.nagoya.jp/chotatsu_topix/simeiteisiR{05..08}.pdf
  - 神戸市: city.kobe.lg.jp a05182/shimeiteishisochi.html (HTML <h2>)
  - 京都府: pref.kyoto.jp/zaisan/documents/r80401.pdf 等

Schema target (autonomath.db):
  am_entities (canonical_id='enforcement:shimei-teishi:{org_slug}:{date}:{hash12}',
               record_kind='enforcement', source_topic='shimei_teishi')
  am_enforcement_detail (entity_id, target_name, enforcement_kind,
                         issuing_authority, issuance_date,
                         exclusion_start, exclusion_end, reason_summary,
                         related_law_ref, source_url)

dedup key: (issuing_authority, target_name, issuance_date)

CLI:
    python scripts/ingest/ingest_enforcement_shimei_teishi.py \\
        --db autonomath.db [--limit 500] [--dry-run]

Parallel-safe: BEGIN IMMEDIATE + busy_timeout=300000 + 6-attempt retry loop.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import logging
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.shimei_teishi")
DEFAULT_DB = REPO_ROOT / "autonomath.db"

PDF_MAX = 10 * 1024 * 1024
HTML_MAX = 4 * 1024 * 1024


# ---------------------------------------------------------------------------
# Date parsing (mirror mlit_chiho_pref)
# ---------------------------------------------------------------------------

_R_DATE = re.compile(r"令\s*和\s*([\d０-９]+)\s*年\s*([\d０-９]{1,2})\s*月\s*([\d０-９]{1,2})\s*日")
_H_DATE = re.compile(r"平\s*成\s*([\d０-９]+)\s*年\s*([\d０-９]{1,2})\s*月\s*([\d０-９]{1,2})\s*日")
_ISO_DATE = re.compile(r"(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})")
_R_DATE_SHORT = re.compile(r"(?:^|[^A-Za-z])R\s*(\d+)[\s.\-]+(\d{1,2})[\s.\-]+(\d{1,2})")

_FW_DIGIT_TBL = str.maketrans("０１２３４５６７８９", "0123456789")


def _to_int(s: str) -> int:
    return int(s.translate(_FW_DIGIT_TBL))


def reiwa_to_iso(y: int, mo: int, d: int) -> str | None:
    year = 2018 + y  # R1=2019
    try:
        return dt.date(year, mo, d).isoformat()
    except ValueError:
        return None


def heisei_to_iso(y: int, mo: int, d: int) -> str | None:
    year = 1988 + y  # H1=1989
    try:
        return dt.date(year, mo, d).isoformat()
    except ValueError:
        return None


def parse_first_date(text: str) -> str | None:
    if not text:
        return None
    m = _R_DATE.search(text)
    if m:
        return reiwa_to_iso(_to_int(m.group(1)), _to_int(m.group(2)), _to_int(m.group(3)))
    m = _H_DATE.search(text)
    if m:
        return heisei_to_iso(_to_int(m.group(1)), _to_int(m.group(2)), _to_int(m.group(3)))
    m = _R_DATE_SHORT.search(text)
    if m:
        return reiwa_to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _ISO_DATE.search(text)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    return None


def all_dates(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in _R_DATE.finditer(text):
        iso = reiwa_to_iso(_to_int(m.group(1)), _to_int(m.group(2)), _to_int(m.group(3)))
        if iso and iso not in seen:
            seen.add(iso)
            out.append(iso)
    for m in _H_DATE.finditer(text):
        iso = heisei_to_iso(_to_int(m.group(1)), _to_int(m.group(2)), _to_int(m.group(3)))
        if iso and iso not in seen:
            seen.add(iso)
            out.append(iso)
    for m in _R_DATE_SHORT.finditer(text):
        iso = reiwa_to_iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if iso and iso not in seen:
            seen.add(iso)
            out.append(iso)
    for m in _ISO_DATE.finditer(text):
        try:
            iso = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            continue
        if iso and iso not in seen:
            seen.add(iso)
            out.append(iso)
    return out


# ---------------------------------------------------------------------------
# Row container
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    org_slug: str
    issuing_authority: str
    target_name: str
    address: str | None
    issuance_date: str
    period_start: str | None
    period_end: str | None
    enforcement_kind: str
    punishment_raw: str
    reason_summary: str | None
    related_law_ref: str | None
    houjin_bangou: str | None
    source_url: str

    def canonical_id(self) -> str:
        key = (
            f"{self.issuing_authority}|{self.target_name}|{self.issuance_date}|"
            f"{self.punishment_raw or ''}|{self.period_end or ''}"
        )
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        return f"enforcement:shimei-teishi:{self.org_slug}:{self.issuance_date}:{digest}"


def map_kind(punish: str) -> str:
    p = punish or ""
    if "指名停止" in p or "入札参加停止" in p or "指名除外" in p:
        return "contract_suspend"
    if "取消し" in p or "取り消し" in p or "取消" in p:
        return "license_revoke"
    if "営業停止" in p or "業務停止" in p:
        return "business_improvement"
    if "指示" in p:
        return "business_improvement"
    if "監督処分" in p:
        return "business_improvement"
    return "contract_suspend"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " / ", s, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&lt;", "<", s)
    s = re.sub(r"&gt;", ">", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _pdftotext(body: bytes) -> str:
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"],
            input=body,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        _LOG.warning("pdftotext failed: %s", exc)
        return ""
    return proc.stdout.decode("utf-8", errors="replace")


def fetch_decoded(http: HttpClient, url: str, max_bytes: int = HTML_MAX) -> str:
    """Fetch HTML, try Shift_JIS / cp932 / utf-8 in order.

    Some 政令市/地整局 pages are still served as Shift_JIS without proper
    charset header. HttpClient.text trusts header; we explicitly probe.
    """
    res = http.get(url, max_bytes=max_bytes)
    if not res.ok or not res.body:
        return ""
    # Look at meta charset to decide.
    head = res.body[:2048].lower()
    if b"shift_jis" in head or b"shift-jis" in head or b"x-sjis" in head:
        for enc in ("shift_jis", "cp932"):
            try:
                return res.body.decode(enc)
            except UnicodeDecodeError:
                continue
    # Default: rely on FetchResult.text (header-aware) but fall back.
    try:
        return res.text
    except Exception:
        return res.body.decode("utf-8", errors="replace")


# Companies tokens regex used across multiple parsers.
COMPANY_TOKENS = (
    "株式会社",
    "有限会社",
    "合同会社",
    "合資会社",
    "（株）",
    "(株)",
    "（有）",
    "(有)",
    "（資）",
    "（名）",
    "公益財団法人",
    "公益社団法人",
    "社会福祉法人",
    "医療法人",
    "一般財団法人",
    "一般社団法人",
)


def looks_like_company(s: str) -> bool:
    if not s:
        return False
    return any(t in s for t in COMPANY_TOKENS)


def _compress_jp_spaces(text: str) -> str:
    """Collapse single spaces between Japanese characters (and between
    Japanese-and-ASCII transitions where the space is clearly a layout
    artifact). This rescues SKR-style PDFs where pdftotext emits
    "有限 会 社 岡 設備 設 計" instead of "有限会社岡設備設計"."""
    # Pattern: a single ASCII or full-width space between two Japanese characters
    # (CJK ideograph, Hiragana, Katakana, full-width number/letter).
    jp_class = r"[぀-ヿ一-鿿＀-￯]"
    # Repeat 2 times to handle "X Y Z" → "XY Z" → "XYZ".
    out = text
    for _ in range(3):
        out = re.sub(rf"({jp_class})[ 　]({jp_class})", r"\1\2", out)
    return out


def normalize_houjin(s: str | None) -> str | None:
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) == 13:
        return digits
    return None


# ---------------------------------------------------------------------------
# 1. MLIT 大臣官房会計課 指名停止 PDF (table style with 法人番号)
# ---------------------------------------------------------------------------

MLIT_KANBO_PAGE = "https://www.mlit.go.jp/page/kanbo05_hy_003092.html"


def discover_mlit_kanbo_pdfs(http: HttpClient) -> list[str]:
    """Find PDF links from the kanbo top page."""
    res = http.get(MLIT_KANBO_PAGE, max_bytes=HTML_MAX)
    if not res.ok or not res.body:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for href in re.findall(r'href="([^"]+\.pdf)"', res.text, flags=re.IGNORECASE):
        if href.startswith("http"):
            absurl = href
        elif href.startswith("/"):
            absurl = "https://www.mlit.go.jp" + href
        else:
            absurl = urllib.parse.urljoin(MLIT_KANBO_PAGE, href)
        if absurl in seen:
            continue
        seen.add(absurl)
        out.append(absurl)
    return out


def parse_mlit_kanbo_pdf(text: str, source_url: str) -> list[EnfRow]:
    """Parse the kanbo PDF: rows with 法人名 / 法人番号 / 住所 / 対象部局 /
    指名停止期間 / 該当事項 / 指名停止理由 columns.

    The PDF is laid out with whitespace-aligned columns; we walk lines and
    detect rows by anchor patterns (R{N}.M.D ～ R{N}.M.D / 9-13-digit 法人番号).
    """
    if not text:
        return []
    rows: list[EnfRow] = []
    lines = text.splitlines()

    # Period span pattern: R{N}.M.D ～ R{N}.M.D (with possibly half/full-width punctuation)
    period_rx = re.compile(
        r"(R\s*\d+[.\s]+\d+[.\s]+\d+|令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)"
        r"\s*[～\-~–]+\s*"
        r"(R\s*\d+[.\s]+\d+[.\s]+\d+|令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)"
    )
    houjin_rx = re.compile(r"\b(\d{13})\b")
    betsu_rx = re.compile(r"別表第\s*[1-3０-９一二三]\s*第\s*\d+\s*号")

    # Strategy: split by candidate header anchors. Each row begins on a line
    # containing a company token; subsequent lines (until next company token
    # or end of file) carry the same row's continuation.
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cur:
                cur.append("")
            continue
        if looks_like_company(stripped) and not stripped.startswith("（"):
            # Heuristic: only start new block if the company token appears
            # near the line beginning (not inside a 理由 paragraph).
            # Take the leftmost 60 chars and check for company token.
            head = stripped[:60]
            if looks_like_company(head):
                if cur:
                    blocks.append(cur)
                cur = [line]
                continue
        cur.append(line)
    if cur:
        blocks.append(cur)

    for block in blocks:
        block_text = "\n".join(block)
        # Period dates
        period_start: str | None = None
        period_end: str | None = None
        pm = period_rx.search(block_text)
        if pm:
            ds = parse_first_date(pm.group(1))
            de = parse_first_date(pm.group(2))
            if ds:
                period_start = ds
            if de:
                period_end = de
        # Issuance date = period_start (the kanbo PDF doesn't have a separate
        # 処分日 column; period_start equals 開始日)
        issuance = period_start or parse_first_date(block_text[:200])
        if not issuance:
            continue
        # Houjin
        houjin: str | None = None
        hm = houjin_rx.search(block_text)
        if hm:
            houjin = hm.group(1)
        # Company name = first line head; strip leading whitespace and trailing addr.
        first_line = block[0].strip()
        # Extract company name: the kanbo PDF often puts NAME then 法人番号 then ADDR
        # on the same line. Split by 2+ whitespace.
        parts = re.split(r"\s{2,}|　{1,}", first_line)
        parts = [p.strip() for p in parts if p.strip()]
        if not parts:
            continue
        name = parts[0]
        # Drop trailing markers.
        name = re.sub(r"^\s*[\d０-９]+\s*[.．、)）]?\s*", "", name).strip()
        # 2-line name handling: if the first line's head doesn't end with a
        # company suffix AND a follow-up line has additional company tokens,
        # combine them.
        company_suffix_rx = re.compile(
            r"(?:株式会社|有限会社|合同会社|合資会社|（株）|\(株\)|（有）|\(有\)|"
            r"協会|連合会|組合|連盟|協議会|機構|財団|社団|法人)$"
        )
        # Standalone "法人" prefixes are PREFIXES (not complete names) — force continuation.
        standalone_prefix = {
            "一般社団法人",
            "一般財団法人",
            "公益社団法人",
            "公益財団法人",
            "社会福祉法人",
            "医療法人",
            "学校法人",
            "宗教法人",
            "特定非営利活動法人",
            "独立行政法人",
            "国立大学法人",
        }
        is_standalone_prefix = name in standalone_prefix
        if (
            looks_like_company(name)
            and (is_standalone_prefix or not company_suffix_rx.search(name))
            and len(block) > 1
        ):
            for follow_line in block[1:8]:
                fl = follow_line.strip()
                if not fl:
                    continue
                # Skip (don't break on) noise lines: 法人番号 line, R-date line,
                # 都道府県 address line, government agency continuation.
                if re.match(r"^\d{8,}", fl):
                    continue
                if re.search(r"R\d+\.|令和\s*\d", fl):
                    continue
                # If line head is a 都道府県 fragment, it's address — skip.
                if re.match(r"^[一-鿿]+(?:都|道|府|県)[一-鿿]", fl):
                    continue
                # Skip lines starting with 政府機関 continuation (e.g. "区海上保安本部")
                if re.match(r"^[本第区部局会庁署気]", fl):
                    continue
                fp = re.split(r"\s{2,}|　{2,}", fl)[0].strip()
                if not fp:
                    continue
                # Combine only if continuation contains a known company-suffix token.
                if any(
                    t in fp
                    for t in (
                        "協会",
                        "連合会",
                        "組合",
                        "連盟",
                        "協議会",
                        "機構",
                        "財団",
                        "法人",
                        "株式会社",
                        "有限会社",
                        "支社",
                        "支店",
                        "事務所",
                    )
                ):
                    name = (name + fp).strip()
                    break
        if not looks_like_company(name) or len(name) < 2:
            continue
        if name in {"法人名", "業者名", "商号又は名称"}:
            continue
        # Address: walk subsequent parts looking for prefecture marker.
        addr_candidates: list[str] = []
        for p in parts[1:]:
            if houjin_rx.fullmatch(p):
                continue
            addr_candidates.append(p)
        # Append continuation lines that look like address chunks.
        addr_text = " ".join(addr_candidates) if addr_candidates else None

        # Reason summary: take the part of block after the betsu code.
        reason: str | None = None
        bm = betsu_rx.search(block_text)
        if bm:
            after = block_text[bm.end() :]
            after = re.sub(r"\s+", " ", after).strip()
            if after:
                reason = after[:1500]
        if not reason:
            reason = re.sub(r"\s+", " ", block_text)[:1500]

        # Related law / 該当事項 token
        related = "措置要領 別表" if bm else "工事請負契約に係る指名停止等の措置要領"
        if bm:
            related = bm.group(0)[:200]

        # Punishment label
        punish = "指名停止"
        period_kakko = re.search(r"\(([^)]*月)\)|（([^）]*月)）", block_text)
        if period_kakko:
            piece = (period_kakko.group(1) or period_kakko.group(2) or "").strip()
            if piece:
                punish = f"指名停止 {piece}"

        rows.append(
            EnfRow(
                org_slug="mlit-kanbo",
                issuing_authority="国土交通省大臣官房会計課",
                target_name=name,
                address=addr_text,
                issuance_date=issuance,
                period_start=period_start,
                period_end=period_end,
                enforcement_kind="contract_suspend",
                punishment_raw=punish,
                reason_summary=reason,
                related_law_ref=related,
                houjin_bangou=houjin,
                source_url=source_url,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# 2. MLIT 営繕部 指名停止 (single-case 別紙 PDF, similar to Hkd/Kkr style)
# ---------------------------------------------------------------------------

MLIT_EIZEN_INDEX = "https://www.mlit.go.jp/report/press/eizen01_hh_000282.html"


def discover_mlit_eizen_pdfs(http: HttpClient) -> list[str]:
    """Walk the eizen press list, plus older 'eizen01_hh_*.html' siblings."""
    out: list[str] = []
    seen: set[str] = set()
    for index_url in (
        MLIT_EIZEN_INDEX,
        # Sibling press release indexes (keep in sync with archive year list).
        "https://www.mlit.go.jp/report/press/eizen01_hh_001000.html",
    ):
        res = http.get(index_url, max_bytes=HTML_MAX)
        if not res.ok or not res.body:
            continue
        for href in re.findall(r'href="([^"]+\.pdf)"', res.text, flags=re.IGNORECASE):
            if href.startswith("http"):
                absurl = href
            elif href.startswith("/"):
                absurl = "https://www.mlit.go.jp" + href
            else:
                absurl = urllib.parse.urljoin(index_url, href)
            # Filter: only press content PDFs.
            if "/report/press/content/" not in absurl:
                continue
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(absurl)
    return out


# ---------------------------------------------------------------------------
# 3. Generic single-case 指名停止 PDF parser (HRR, KKR, SKR, MLIT-eizen variants)
# ---------------------------------------------------------------------------


@dataclass
class SingleCasePdfSource:
    org_slug: str
    issuing_authority: str
    pdf_url: str
    discovered_date: str | None = None


def parse_single_case_pdf(
    text: str,
    source: SingleCasePdfSource,
) -> list[EnfRow]:
    """Press-release style 指名停止 PDF (1 PDF = 1 or more companies).

    Matches HRR/KKR/SKR/MLIT-eizen layouts:
        令和X年Y月Z日
        <発行体>
        指名停止措置の概要
        １．指名停止措置業者名(及び住所)
            <NAME>      <ADDRESS>
        ２．指名停止措置期間
            令和X年... ～ 令和X年... (Nヵ月)
        ３．指名停止措置の範囲
        ４．事実概要
        ５．指名停止措置理由
    """
    if not text:
        return []
    if "措置" not in text or ("指名停止" not in text and "監督処分" not in text):
        return []
    issuance = parse_first_date(text[:600]) or source.discovered_date
    # Try to find issuance from the press header pattern.
    if not issuance:
        m = re.search(r"記\s*者\s*発\s*表[^\n]{0,120}\n[^\n]*?(令和[^\n]+?日)", text)
        if m:
            issuance = parse_first_date(m.group(1))
    if not issuance:
        return []

    # Extract company section after "業者名" header.
    company_lines: list[tuple[str, str | None]] = []

    # Pattern A (single line, MLIT-eizen / single-case):
    #   "杉山管工設備株式会社                   神奈川県横浜市中区..."
    #   directly under header "指名停止措置業者     住所"
    section = re.search(
        r"指\s*名\s*停\s*止\s*措\s*置\s*業\s*者(?:\s*名)?(?:\s*及\s*び\s*住\s*所)?[\s\S]*?\n([\s\S]+?)"
        r"(?=(?:２|2|３|3)\s*[\s.．、]?\s*指\s*名\s*停\s*止\s*措\s*置\s*期\s*間"
        r"|\n\s*指\s*名\s*停\s*止\s*措\s*置\s*の\s*範\s*囲)",
        text,
    )
    if section:
        block = section.group(1)
        for raw in block.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("指名停止措置業者") or "業者名" in line and "住所" in line:
                continue
            if re.match(r"^[1-9０-９一二三四五六七八九]\s*[.．、]?\s*$", line):
                continue
            line_clean = re.sub(
                r"^(?:[1-9０-９一二三四五六七八九]\s*[.．、)）]?\s*)+", "", line
            ).strip()
            parts = re.split(r"\s{2,}|　{1,}", line_clean)
            parts = [p.strip() for p in parts if p.strip()]
            if not parts:
                continue
            cand = parts[0]
            # Skip a stray header repeat.
            if cand in {"指名停止措置業者", "指名停止措置業者名", "業者名", "業者の住所", "住所"}:
                continue
            if not looks_like_company(cand):
                continue
            addr = " ".join(parts[1:]).strip() if len(parts) > 1 else None
            if addr in {"住所", "業者の住所"}:
                addr = None
            company_lines.append((cand, addr))

    # Pattern B fallback: "1.指名停止措置業者名 ：<NAME>" style + "代表者及び住所" line.
    if not company_lines:
        inline = re.search(
            r"指\s*名\s*停\s*止\s*措\s*置\s*業\s*者\s*名\s*[：:]\s*([^\n]+)",
            text,
        )
        if inline:
            cand = inline.group(1).strip()
            cand = re.split(r"\s{2,}|　{2,}", cand)[0].strip()
            if looks_like_company(cand):
                # Try to get address from "代表者及び住所" or "業者の住所" or 住所.
                addr_match = re.search(
                    r"(?:代\s*表\s*者\s*及\s*び\s*住\s*所|業\s*者\s*の?\s*住\s*所|住\s*所)\s*[：:\s]*([^\n]+)",
                    text,
                )
                addr = None
                if addr_match:
                    addr = (
                        re.split(r"\s{2,}|　{2,}", addr_match.group(1).strip())[0].strip() or None
                    )
                company_lines.append((cand, addr))

    # Pattern C: "<NAME>に対して指名停止措置を行いました" sentence.
    if not company_lines:
        sent = re.search(
            r"([^、。\n]+?(?:株式会社|有限会社|合同会社|合資会社)[^、。\n]*?)に対し",
            text,
        )
        if sent:
            cand = sent.group(1).strip()
            cand = cand.lstrip("、，,。 　").strip()
            cand = re.sub(r"^.*?(?=[一-鿿])", "", cand, count=0)
            cand = cand.strip("（）()「」『』\"' 　")
            # Strip a leading address phrase if present.
            cand = re.sub(r"^[^、。\n]+?(?:都|道|府|県)[^、。\n]+?(?:市|区|町|村)\s*", "", cand)
            if looks_like_company(cand):
                addr_match = re.search(r"所在地\s*[：:]?\s*([^）)\n]+)", text)
                addr = addr_match.group(1).strip() if addr_match else None
                company_lines.append((cand, addr))

    if not company_lines:
        return []

    # Period
    period_start: str | None = None
    period_end: str | None = None
    period_match = re.search(
        r"指名停止措置期間[\s\S]{0,400}?(令和\d+\s*年\s*\d+\s*月\s*\d+\s*日|R\s*\d+[.\s]+\d+[.\s]+\d+)\s*"
        r"(?:から|[～\-~–])\s*"
        r"(令和\d+\s*年\s*\d+\s*月\s*\d+\s*日|R\s*\d+[.\s]+\d+[.\s]+\d+)",
        text,
    )
    if period_match:
        period_start = parse_first_date(period_match.group(1))
        period_end = parse_first_date(period_match.group(2))

    # Reason summary
    reason_parts = []
    sub = re.search(
        r"事\s*実\s*概\s*要\s*\n([\s\S]+?)(?=(?:５|5)\s*[\s.．、]|＜|【問合せ|＜問い合わせ)",
        text,
    )
    if sub:
        reason_parts.append(re.sub(r"\s+", " ", sub.group(1).strip())[:1200])
    sub = re.search(
        r"指名停止措置理由[\s\S]*?\n([\s\S]+?)(?=＜|【問合せ|問い合わせ|別紙|参考)",
        text,
    )
    if sub:
        reason_parts.append(re.sub(r"\s+", " ", sub.group(1).strip())[:600])
    reason = " / ".join(reason_parts)[:1500] if reason_parts else None
    if not reason:
        head = text.split("\n\n")[:5]
        reason = re.sub(r"\s+", " ", " ".join(head))[:1200]

    # Punishment label
    punish_label = "指名停止"
    period_text = re.search(r"(\d+\s*[ヵか]月|\d+\s*週間)", text)
    if period_text:
        punish_label = f"指名停止 {period_text.group(1)}"

    rows: list[EnfRow] = []
    for name, addr in company_lines:
        rows.append(
            EnfRow(
                org_slug=source.org_slug,
                issuing_authority=source.issuing_authority,
                target_name=name,
                address=addr,
                issuance_date=issuance,
                period_start=period_start,
                period_end=period_end,
                enforcement_kind="contract_suspend",
                punishment_raw=punish_label,
                reason_summary=reason,
                related_law_ref="工事請負契約に係る指名停止等の措置要領",
                houjin_bangou=None,
                source_url=source.pdf_url,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# 4. THR 東北 累積一覧 PDF (table style with 業者コード)
# ---------------------------------------------------------------------------

THR_PDF_URLS = [
    ("https://www.thr.mlit.go.jp/Bumon/B00013/K00730/simeiteisi/R8simeiteisi.pdf", "R8"),
    ("https://www.thr.mlit.go.jp/Bumon/B00013/K00730/simeiteisi/R7simeiteisi.pdf", "R7"),
    ("https://www.thr.mlit.go.jp/Bumon/B00013/K00730/simeiteisi/R6simeiteisi.pdf", "R6"),
    ("https://www.thr.mlit.go.jp/Bumon/B00013/K00730/simeiteisi/R5simeiteisi.pdf", "R5"),
]


def parse_thr_pdf(text: str, source_url: str) -> list[EnfRow]:
    """THR cumulative table:
      指 名 停 止 期 間              業 者 名         所 在 地  業 者 コ ー ド  停 止 理 由  適 用 条 項 備 考

    1   令和7年4月11日 ～ 令和7年8月10日 4ヵ月  (株)NIPPO     東京都中央区  10000273000  ...   別表第1-2及び別表第2-15
    """
    if not text:
        return []
    rows: list[EnfRow] = []

    period_rx = re.compile(
        r"令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日\s*[～\-~–]\s*"
        r"令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日"
    )

    # Walk lines; treat each block starting with a row-number anchor as one row.
    lines = text.splitlines()
    blocks: list[list[str]] = []
    cur: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Row-number anchor: "  1   令和" or "10   令和"
        if re.match(r"^[0-9]{1,4}\s+令和\s*\d+", stripped):
            if cur:
                blocks.append(cur)
            cur = [line]
        else:
            if cur:
                cur.append(line)
    if cur:
        blocks.append(cur)

    for block in blocks:
        joined = "\n".join(block)
        text_block = re.sub(r"\s+", " ", joined)
        pm = period_rx.search(joined)
        if not pm:
            continue
        period_dates = all_dates(pm.group(0))
        if len(period_dates) < 2:
            continue
        period_start, period_end = period_dates[0], period_dates[1]

        # Company name appears on the same line as period start, following
        # "Nヵ月" token.
        # Find 'Nヵ月' marker, and capture text after that on the same line.
        first_line = block[0]
        kakko = re.search(r"\d+\s*[ヵか]月\s+(.+)$", first_line)
        if not kakko:
            continue
        rest = kakko.group(1).strip()
        # 'rest' may be "(株)NIPPO           東京都中央区        10000273000      過失による粗雑工事..."
        parts = re.split(r"\s{2,}|　{2,}", rest)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            continue
        # Heuristic: name is parts[0]; if a follow-up line exists (long company
        # names often span 2 lines, like "パナソニックマーケティング ジャパン(株)"),
        # join with the next line's first segment.
        name = parts[0]
        # If name has a 都道府県 fragment glued on (single space split), peel it off.
        prefecture_split = re.search(
            r"^(.+?(?:株式会社|有限会社|合同会社|合資会社|（株）|\(株\)|（有）|\(有\)|（資）|（名）))\s+([一-鿿]+(?:都|道|府|県)[一-鿿]+)$",
            name,
        )
        if prefecture_split:
            name = prefecture_split.group(1)
            # Move the address fragment back into parts so address extraction picks it up.
            parts.insert(1, prefecture_split.group(2))
        # If continuation line starts with a non-place token and contains a
        # company suffix, append.
        if len(block) > 1:
            for follow_line in block[1:]:
                fl = follow_line.strip()
                if not fl:
                    continue
                # Skip lines that begin with explicit address/period markers.
                if re.match(
                    r"^令和|^過失|^独占禁止|^建設業法|^贈賄|^競売|^安全|^別表|^不正|^[0-9０-９]{8,}",
                    fl,
                ):
                    break
                if any(
                    t in fl
                    for t in (
                        "株）",
                        "(株)",
                        "（株）",
                        "(有)",
                        "（有）",
                        "ジャパン",
                        "システムズ",
                        "エンジニアリング",
                        "マーケティング",
                    )
                ):
                    fp = re.split(r"\s{2,}|　{2,}", fl)[0].strip()
                    if (
                        fp
                        and not looks_like_company(name)
                        or fp.endswith(("(株)", "（株）", "(株）"))
                    ):
                        name = (name + fp).replace("  ", " ")
                        break
        name = name.strip()
        if not name or len(name) < 2:
            continue

        # Address = parts[1] if it looks like prefecture; else None.
        address: str | None = None
        if len(parts) >= 2:
            cand = parts[1]
            if re.match(r"^[一-鿿]+(?:都|道|府|県)", cand):
                address = cand

        # 法人番号 (業者コード is ad-hoc; not 13-digit 法人番号 — skip)
        houjin = None

        # Reason: find words like 不正, 独占禁止法, 建設業法, 贈賄, 過失, 安全管理 etc.
        reason_match = re.search(
            r"(独占禁止法[^別\n]*?|建設業法[^別\n]*?|贈賄[^別\n]*?|過失による[^別\n]*?|"
            r"談合[^別\n]*?|不正又は不誠実[^別\n]*?|安全管理[^別\n]*?|公契約関係競売等妨害[^別\n]*?|"
            r"労働安全衛生[^別\n]*?|偽造[^別\n]*?)(?=\s*別表|$)",
            text_block,
        )
        reason = reason_match.group(1).strip() if reason_match else None
        if reason:
            reason = reason[:500]

        # 適用条項 = 別表第N-M
        betsu = re.search(
            r"別表第[0-9０-９一二三]+[\-—‐－]?[0-9０-９]*(?:及び別表第[0-9０-９]+[\-—‐－]?[0-9０-９]*)?",
            text_block,
        )
        related = betsu.group(0)[:200] if betsu else "工事請負契約に係る指名停止等の措置要領"

        rows.append(
            EnfRow(
                org_slug="thr",
                issuing_authority="東北地方整備局",
                target_name=name,
                address=address,
                issuance_date=period_start,
                period_start=period_start,
                period_end=period_end,
                enforcement_kind="contract_suspend",
                punishment_raw="指名停止",
                reason_summary=reason,
                related_law_ref=related,
                houjin_bangou=houjin,
                source_url=source_url,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# 5. HRR 北陸 home page → individual press PDFs (single-case)
# ---------------------------------------------------------------------------

HRR_HOMEPAGE = "https://www.hrr.mlit.go.jp/"


def discover_hrr_pdfs(http: HttpClient) -> list[SingleCasePdfSource]:
    out: list[SingleCasePdfSource] = []
    seen: set[str] = set()
    for index_url in (
        HRR_HOMEPAGE,
        # Press archive root pattern (latest year sub).
        "https://www.hrr.mlit.go.jp/press/index.html",
    ):
        res = http.get(index_url, max_bytes=HTML_MAX)
        if not res.ok or not res.body:
            continue
        for href in re.findall(r'href="([^"]*soumubu[^"]*\.pdf)"', res.text, flags=re.IGNORECASE):
            if href.startswith("http"):
                absurl = href
            elif href.startswith("/"):
                absurl = "https://www.hrr.mlit.go.jp" + href
            else:
                absurl = urllib.parse.urljoin(index_url, href)
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(
                SingleCasePdfSource(
                    org_slug="hrr",
                    issuing_authority="北陸地方整備局",
                    pdf_url=absurl,
                )
            )
    # Also enumerate likely YY-MM-DD soumubu filenames from a small year window
    # to catch cases that have rolled off the index.
    today = dt.date.today()
    for year_offset in range(0, 3):
        y = today.year - year_offset
        index = f"https://www.hrr.mlit.go.jp/press/{y}/index.html"
        res = http.get(index, max_bytes=HTML_MAX)
        if not res.ok or not res.body:
            continue
        for href in re.findall(r'href="([^"]*soumubu[^"]*\.pdf)"', res.text, flags=re.IGNORECASE):
            absurl = urllib.parse.urljoin(index, href)
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(
                SingleCasePdfSource(
                    org_slug="hrr",
                    issuing_authority="北陸地方整備局",
                    pdf_url=absurl,
                )
            )
    return out


# ---------------------------------------------------------------------------
# 6. KKR 近畿 fiscal-year index → -att/aXXXX.pdf
# ---------------------------------------------------------------------------

KKR_INDEX_PAGES = [
    "https://www.kkr.mlit.go.jp/n_info/olnrk8000000ouh9.html",  # R8
    "https://www.kkr.mlit.go.jp/n_info/c9us5e000000jzf8.html",  # R7
    "https://www.kkr.mlit.go.jp/n_info/r9733f000002jql8.html",  # R6
]


def discover_kkr_pdfs(http: HttpClient) -> list[SingleCasePdfSource]:
    out: list[SingleCasePdfSource] = []
    seen: set[str] = set()
    for index_url in KKR_INDEX_PAGES:
        res = http.get(index_url, max_bytes=HTML_MAX)
        if not res.ok or not res.body:
            continue
        base = index_url.rsplit("/", 1)[0] + "/"
        for href in re.findall(r'href="([^"]+\.pdf)"', res.text, flags=re.IGNORECASE):
            if href.startswith("http"):
                absurl = href
            elif href.startswith("/"):
                absurl = "https://www.kkr.mlit.go.jp" + href
            else:
                absurl = urllib.parse.urljoin(base, href)
            # Filter to per-case PDFs in -att directory.
            if "-att/" not in absurl:
                continue
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(
                SingleCasePdfSource(
                    org_slug="kkr",
                    issuing_authority="近畿地方整備局",
                    pdf_url=absurl,
                )
            )
    return out


# ---------------------------------------------------------------------------
# 7. SKR 四国 Shift_JIS index → R{N}/{YYYYMMDD}.pdf
# ---------------------------------------------------------------------------

SKR_INDEX = "https://www.skr.mlit.go.jp/send/shimei/index.html"


def discover_skr_pdfs(http: HttpClient) -> list[SingleCasePdfSource]:
    out: list[SingleCasePdfSource] = []
    seen: set[str] = set()
    html = fetch_decoded(http, SKR_INDEX)
    if not html:
        return out
    base = SKR_INDEX.rsplit("/", 1)[0] + "/"
    for href in re.findall(r'href="([^"]+\.pdf)"', html, flags=re.IGNORECASE):
        if href.startswith("http"):
            absurl = href
        elif href.startswith("/"):
            absurl = "https://www.skr.mlit.go.jp" + href
        else:
            absurl = urllib.parse.urljoin(base, href)
        if absurl in seen:
            continue
        seen.add(absurl)
        # The filename encodes the date (YYYYMMDD); use it as a hint.
        m = re.search(r"/(\d{8})(?:_\d+)?\.pdf$", absurl)
        discovered_date = None
        if m:
            with contextlib.suppress(ValueError):
                discovered_date = dt.date(
                    int(m.group(1)[0:4]), int(m.group(1)[4:6]), int(m.group(1)[6:8])
                ).isoformat()
        out.append(
            SingleCasePdfSource(
                org_slug="skr",
                issuing_authority="四国地方整備局",
                pdf_url=absurl,
                discovered_date=discovered_date,
            )
        )
    return out


# ---------------------------------------------------------------------------
# 8. Saitama / Chiba / Kawasaki / Nagoya: cumulative fiscal-year PDF tables
# ---------------------------------------------------------------------------


@dataclass
class CityCumPdf:
    org_slug: str
    issuing_authority: str
    pdf_url: str


# (org_slug, authority, url)
SAITAMA_PDFS = [
    (
        "saitama",
        "さいたま市",
        f"https://www.city.saitama.lg.jp/005/001/017/011/002/p008392_d/fil/R{n}teisiitiran.pdf",
    )
    for n in (8, 7, 6, 5, 4, 3)
]


def discover_chiba_pdfs(http: HttpClient) -> list[CityCumPdf]:
    out: list[CityCumPdf] = []
    seen: set[str] = set()
    res = http.get(
        "https://www.city.chiba.jp/zaiseikyoku/shisan/keiyaku/simeiteisi.html",
        max_bytes=HTML_MAX,
    )
    if not res.ok or not res.body:
        return out
    # Pull all .pdf and .xlsx links.
    for href in re.findall(r'href="([^"]+\.(?:pdf|xlsx?))"', res.text, flags=re.IGNORECASE):
        if href.startswith("http"):
            absurl = href
        elif href.startswith("/"):
            absurl = "https://www.city.chiba.jp" + href
        else:
            absurl = urllib.parse.urljoin(
                "https://www.city.chiba.jp/zaiseikyoku/shisan/keiyaku/",
                href,
            )
        # Restrict to "simeiteisi" filename.
        if "simeiteisi" not in absurl.lower():
            continue
        if absurl in seen:
            continue
        seen.add(absurl)
        # Ingest only PDF (XLSX requires extra dep).
        if not absurl.lower().endswith(".pdf"):
            continue
        out.append(
            CityCumPdf(
                org_slug="chiba",
                issuing_authority="千葉市",
                pdf_url=absurl,
            )
        )
    return out


def discover_kawasaki_pdfs(http: HttpClient) -> list[CityCumPdf]:
    """Kawasaki: a single 政令市 page lists rolling cumulative PDFs.

    Try the published cmsfiles tree (90252) where files are named
    `{YYMMDD}shimeiteishiichiran.pdf`.
    """
    out: list[CityCumPdf] = []
    # Fetch the parent index page (if present) and follow .pdf links.
    indexes = [
        "https://www.city.kawasaki.jp/233300/page/0000090252.html",
        "https://www.city.kawasaki.jp/233300/page/0000090252_00001.html",
    ]
    seen: set[str] = set()
    for idx in indexes:
        res = http.get(idx, max_bytes=HTML_MAX)
        if not res.ok or not res.body:
            continue
        for href in re.findall(
            r'href="([^"]+shimeiteishi[^"]*\.pdf)"', res.text, flags=re.IGNORECASE
        ):
            if href.startswith("http"):
                absurl = href
            elif href.startswith("/"):
                absurl = "https://www.city.kawasaki.jp" + href
            else:
                absurl = urllib.parse.urljoin(idx, href)
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(
                CityCumPdf(
                    org_slug="kawasaki",
                    issuing_authority="川崎市",
                    pdf_url=absurl,
                )
            )
    # Add explicit known files (verified via curl HEAD).
    for fname in (
        "5080425shimeiteishiichiran.pdf",
        "5080328shimeiteishiichiran.pdf",
        "5070304shimeiteishiichiran.pdf",
        "5060305shimeiteishiichiran.pdf",
        "shimeiteishiichiran5050224.pdf",
    ):
        absurl = f"https://www.city.kawasaki.jp/233300/cmsfiles/contents/0000090/90252/{fname}"
        if absurl in seen:
            continue
        seen.add(absurl)
        out.append(
            CityCumPdf(
                org_slug="kawasaki",
                issuing_authority="川崎市",
                pdf_url=absurl,
            )
        )
    return out


NAGOYA_PDFS = [
    CityCumPdf(
        org_slug="nagoya",
        issuing_authority="名古屋市",
        pdf_url=f"https://www.chotatsu.city.nagoya.jp/chotatsu_topix/simeiteisiR{y:02d}.pdf",
    )
    for y in (8, 7, 6, 5)
]


def parse_nagoya_pdf(text: str, source: CityCumPdf) -> list[EnfRow]:
    """Nagoya cumulative PDF has very fragmented layout. Anchor on the
    "自：令和X年..." → "至：令和X年..." date span and pull the nearby company
    name from preceding/following lines.
    """
    if not text:
        return []
    rows: list[EnfRow] = []
    lines = text.splitlines()

    jishi_rx = re.compile(
        r"自[：:]\s*令\s*和\s*([\d０-９]+)\s*年\s*([\d０-９]+)\s*月\s*([\d０-９]+)\s*日"
    )
    shi_rx = re.compile(
        r"至[：:]\s*令\s*和\s*([\d０-９]+)\s*年\s*([\d０-９]+)\s*月\s*([\d０-９]+)\s*日"
    )

    seen_keys: set[tuple[str, str]] = set()

    i = 0
    while i < len(lines):
        line = lines[i]
        ji = jishi_rx.search(line)
        if not ji:
            i += 1
            continue
        period_start = reiwa_to_iso(
            _to_int(ji.group(1)), _to_int(ji.group(2)), _to_int(ji.group(3))
        )
        # 至 is on same or next 1-3 lines.
        period_end: str | None = None
        for j in range(i, min(i + 4, len(lines))):
            sm = shi_rx.search(lines[j])
            if sm:
                period_end = reiwa_to_iso(
                    _to_int(sm.group(1)), _to_int(sm.group(2)), _to_int(sm.group(3))
                )
                break
        if not period_start:
            i += 1
            continue
        # Find company name: scan within ±5 lines for a line containing a
        # company token. Prefer lines BEFORE the 自 line.
        name: str | None = None
        for j in range(max(0, i - 5), min(len(lines), i + 5)):
            if j == i:
                continue
            cand_line = lines[j]
            if not looks_like_company(cand_line):
                continue
            # Strip leading row numbering and split on 2+ whitespace.
            stripped = cand_line.strip()
            stripped = re.sub(r"^(?:[0-9０-９]+\s*[.．、)）]?\s*)+", "", stripped)
            parts = re.split(r"\s{2,}|　{2,}", stripped)
            parts = [p.strip() for p in parts if p.strip()]
            if not parts:
                continue
            # Locate first company-token segment.
            for p in parts:
                if looks_like_company(p):
                    cand_name = p
                    # Possible 2-line continuation: peek at j+2 (since dates
                    # interleave; e.g. "株式会社ＡＤＫマーケティン" then "グ・ソリューションズ中部支社" two lines later).
                    if not re.search(
                        r"(?:株式会社|有限会社|合同会社|合資会社|（株）|\(株\)|（有）|\(有\)|"
                        r"協会|連合会|組合|機構|財団|法人|支社|支店|事務所|営業所)$",
                        cand_name,
                    ):
                        for k in range(j + 1, min(len(lines), j + 4)):
                            extra = lines[k].strip()
                            extra = re.sub(r"^(?:[0-9０-９]+\s*[.．、)）]?\s*)+", "", extra)
                            extra_parts = re.split(r"\s{2,}|　{2,}", extra)
                            extra_parts = [p2.strip() for p2 in extra_parts if p2.strip()]
                            if not extra_parts:
                                continue
                            ext = extra_parts[0]
                            if (
                                ext
                                and not re.search(r"R\d+\.|令和|自[：:]|至[：:]", ext)
                                and not re.match(r"^[一-鿿]+(?:都|道|府|県|市|区|町|村)", ext)
                                and len(ext) <= 50
                                and re.search(r"[一-鿿ぁ-んァ-ヶー]", ext)
                            ):
                                cand_name = cand_name + ext
                                break
                    name = cand_name
                    break
            if name:
                break
        if not name:
            i += 1
            continue
        key = (name, period_start)
        if key in seen_keys:
            i += 1
            continue
        seen_keys.add(key)
        # Address: scan for 名古屋市/愛知県 fragment within ±3 lines.
        address: str | None = None
        for j in range(max(0, i - 3), min(len(lines), i + 4)):
            am = re.search(
                r"((?:名古屋市|愛知県|東京都|大阪府|兵庫県|神奈川県|京都府|"
                r"[一-鿿]+県)[一-鿿々\-ー\d０-９丁目番地号]+)",
                lines[j],
            )
            if am:
                address = am.group(1)[:200]
                break
        # Reason: take a window around the row.
        reason_parts: list[str] = []
        for j in range(i, min(len(lines), i + 8)):
            chunk = lines[j].strip()
            if not chunk:
                continue
            if any(
                t in chunk
                for t in (
                    "該当者が",
                    "違反",
                    "事故",
                    "妨害",
                    "不正",
                    "辞退",
                    "排除措置",
                    "贈賄",
                    "公衆損害",
                )
            ):
                reason_parts.append(chunk)
        # Also peek backwards for context.
        for j in range(max(0, i - 5), i):
            chunk = lines[j].strip()
            if any(t in chunk for t in ("該当者が", "違反", "事故", "妨害", "不正", "辞退")):
                reason_parts.append(chunk)
        reason = " ".join(reason_parts)[:1000] if reason_parts else None

        # 適用条項
        betsu = re.search(r"別表第[12０-９一二三]+第\d+号", "\n".join(lines[i : i + 8]))
        related = betsu.group(0)[:200] if betsu else "名古屋市指名停止基準要綱"

        rows.append(
            EnfRow(
                org_slug=source.org_slug,
                issuing_authority=source.issuing_authority,
                target_name=name,
                address=address,
                issuance_date=period_start,
                period_start=period_start,
                period_end=period_end,
                enforcement_kind="contract_suspend",
                punishment_raw="指名停止",
                reason_summary=reason,
                related_law_ref=related,
                houjin_bangou=None,
                source_url=source.pdf_url,
            )
        )
        i += 1
    return rows


def parse_chiba_pdf(text: str, source: CityCumPdf) -> list[EnfRow]:
    """Chiba City 指名停止措置一覧表 parser.

    Layout: numbered rows where each row spans ~6 lines:
      line+0: <indent>会社名
      line+1..2: <indent>代表取締役 ...   令和N年M月D日から (start_date col)
      line+2..3: <num> <地区区分> <○マーク列> ... 措置要件 ...
      line+3..4: <indent>住所...                令和N年M月D日まで (end_date col)
      line+4..5: 番N号 (address continuation)

    Strategy: detect numbered row anchors (line begins with digit+whitespace),
    then collect ~8 following lines until next anchor; from that block extract
    company name, two dates (any 令和...日 patterns), and reason.
    """
    if not text:
        return []
    lines = text.splitlines()

    # Find row anchors: lines starting with a row number AND containing 地区区分.
    # The digit may be flush-left with optional intervening 代表取締役 text:
    #   "1                        市内    ○   －    －"
    #   "12 代表取締役社長 舘山 勝         市外    -"
    anchor_rx = re.compile(r"^\s{0,4}([0-9]{1,3})\s.*?(市内|準市内|市外)\s")
    # Company name line: indented + contains a 法人 token. Allow either form:
    #   "株式会社博報堂"     (prefix: 株式会社X)
    #   "株式会社 大林組"    (prefix with space: 株式会社 X)
    #   "日本交通技術株式会社" (suffix: X株式会社)
    # Strategy: find the first 法人 marker in the indented content, then take a
    # window of [marker_start - 30 chars] .. [marker_end + 30 chars] limited to
    # the same line, and trim. Names rarely contain 2+ consecutive whitespace.
    company_marker_rx = re.compile(
        r"(株式会社|有限会社|合同会社|合資会社|（株）|\(株\)|（有）|\(有\)|"
        r"協会|連合会|組合|連盟|協議会|機構|財団|社団|法人|公社|公庫)"
    )

    # Collect anchor positions.
    anchors: list[int] = []
    for idx, line in enumerate(lines):
        if anchor_rx.match(line):
            anchors.append(idx)
    if not anchors:
        return []

    # End of last block is the next anchor's start (minus 1) OR end of file.
    rows: list[EnfRow] = []
    for ai, start in enumerate(anchors):
        end = anchors[ai + 1] if ai + 1 < len(anchors) else len(lines)
        # Look back up to 5 lines for the company name.
        # Look forward up to (end - start) lines for reason + dates + address.
        block_start = max(0, start - 5)
        block_lines = lines[block_start:end]
        block_text = "\n".join(block_lines)

        # Extract suspension period. Prefer dates explicitly marked with から/まで.
        kara_rx = re.compile(r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)\s*から")
        made_rx = re.compile(r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)\s*まで")
        kara_m = kara_rx.search(block_text)
        made_m = made_rx.search(block_text)
        if kara_m and made_m:
            period_start = parse_first_date(kara_m.group(1))
            period_end = parse_first_date(made_m.group(1))
        else:
            # Fallback: any two 令和 dates
            date_rx = re.compile(r"令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日")
            dates = date_rx.findall(block_text)
            if len(dates) < 2:
                continue
            period_start = parse_first_date(dates[0])
            period_end = parse_first_date(dates[1])
        if not period_start:
            continue

        def _extract_name_from_line(ln: str) -> str | None:
            """Extract a company name from one indented line."""
            stripped = ln.strip()
            # Drop leading row-numbering / row markers.
            stripped = re.sub(r"^[\d０-９]+\s*[.．、)）]?\s*", "", stripped)
            if not stripped:
                return None
            # Reject lines that look like address (start with 都道府県).
            if re.match(r"^[一-鿿]+(?:都|道|府|県)", stripped):
                return None
            # Reject lines that contain dates / period markers.
            if re.search(r"令和\s*\d|から|まで|R\d+\.", stripped):
                return None
            # Reject lines with 代表取締役 (those are name+rep lines, but rep alone is
            # not a company).
            if "代表取締役" in stripped or "代表者" in stripped:
                # Try to extract just the company portion before 代表取締役.
                head = re.split(r"\s{2,}|代表取締役|代表者", stripped, maxsplit=1)[0].strip()
                if head and company_marker_rx.search(head):
                    return head
                return None
            # Cleanup multiple-internal-spaces — Chiba "株式会社 大林組" has 1 space:
            # collapse single space between 株式会社 and following Japanese chars.
            cleaned = re.sub(
                r"(株式会社|有限会社|合同会社|合資会社)\s+([一-鿿一-鿿])",
                r"\1\2",
                stripped,
            )
            cleaned = re.sub(
                r"([一-鿿一-鿿])\s+(株式会社|有限会社|合同会社|合資会社)",
                r"\1\2",
                cleaned,
            )
            # Drop trailing tabular noise (after 2+ spaces).
            cleaned = re.split(r"\s{2,}|　{2,}", cleaned)[0].strip()
            if not cleaned or not company_marker_rx.search(cleaned):
                return None
            # If the line is "X株式会社Y" where Y is reason text (e.g.
            # "千葉エコクリエイション株式会社安全管理措置の不適切"), truncate at
            # the suffix. Detect by looking for a known reason-start token AFTER
            # the suffix.
            reason_starters = (
                "安全管理措置",
                "公衆損害",
                "独占禁止法違反",
                "契約違反",
                "不正又は不誠実",
                "談合",
                "贈賄",
                "労働安全衛生法違反",
                "建設業法違反",
                "措置要件",
                "別表",
                "安全管理",
                "労働安全",
                "第２条",
                "第２第",
                "第１第",
                "第二条",
            )
            for term in ("株式会社", "有限会社", "合同会社", "合資会社"):
                idx = cleaned.find(term)
                if idx > 0:  # X株式会社 (suffix form)
                    end_pos = idx + len(term)
                    tail = cleaned[end_pos:].strip()
                    if tail and any(tail.startswith(rs) for rs in reason_starters):
                        cleaned = cleaned[:end_pos]
                        break
            # Reject if too short or doesn't end with a 法人 token.
            if len(cleaned) < 3:
                return None
            return cleaned

        # Find company name: walk lines BEFORE the anchor line, prefer the
        # closest indented line that contains a company marker.
        name = None
        for ln in reversed(block_lines[: start - block_start]):
            cand = _extract_name_from_line(ln)
            if cand and looks_like_company(cand) and len(cand) >= 3:
                # Special: Chiba sometimes splits "株式会社" / "X" across 2 lines:
                #   line 0: "株式会社"
                #   line 1: "大林組  代表取締役 ..."
                # If cand is exactly "株式会社" / similar bare prefix, try to
                # combine with the NEXT non-empty line in block.
                if cand in {"株式会社", "有限会社", "合同会社", "合資会社"}:
                    ln_idx_in_block = block_lines.index(ln)
                    for nxt in block_lines[ln_idx_in_block + 1 :]:
                        ext = nxt.strip()
                        if not ext:
                            continue
                        # First word of next line.
                        head = re.split(r"\s{2,}|　{2,}", ext)[0].strip()
                        head = re.sub(r"^代表[取締役者社長].*", "", head).strip()
                        if head and not re.search(r"令和|から|まで|代表", head):
                            cand = cand + head
                        break
                # Special: If cand is a STANDALONE 法人 prefix, append next line.
                standalone = {
                    "一般社団法人",
                    "一般財団法人",
                    "公益社団法人",
                    "公益財団法人",
                    "社会福祉法人",
                    "医療法人",
                    "学校法人",
                    "宗教法人",
                }
                if cand in standalone:
                    ln_idx_in_block = block_lines.index(ln)
                    for nxt in block_lines[ln_idx_in_block + 1 :]:
                        ext = nxt.strip()
                        if not ext:
                            continue
                        head = re.split(r"\s{2,}|　{2,}", ext)[0].strip()
                        if head and not re.search(r"令和|から|まで|代表", head):
                            cand = cand + head
                        break
                name = cand
                break
        if not name:
            # Fallback: scan whole block.
            for ln in block_lines:
                cand = _extract_name_from_line(ln)
                if cand and looks_like_company(cand) and len(cand) >= 3:
                    name = cand
                    break
        if not name:
            continue
        if name in {"法人名", "業者名", "商号又は名称", "有資格業者名"}:
            continue

        # Extract address: line after company often contains 代表取締役 -> skip,
        # then look for line starting with 都道府県 (5 lines following anchor).
        address: str | None = None
        for ln in block_lines:
            m_addr = re.match(r"^\s+([一-鿿]+(?:都|道|府|県)[^\n]+)$", ln)
            if m_addr:
                cand = m_addr.group(1).strip()
                # Drop tabular noise after multiple spaces.
                cand = re.split(r"\s{3,}", cand)[0].strip()
                if 4 <= len(cand) <= 80:
                    address = cand
                    break

        # Reason: scan for "措置要件" column (between 期間 and 適用条項 columns).
        # Heuristic: any line on the anchor line that contains 違反/契約違反/不正/談合/独占禁止法.
        reason = None
        reason_kw = re.compile(
            r"(独占禁止法違反行為|契約違反|不正又は不誠実な行為|談合(?:及び競売入札妨害)?|"
            r"安全管理措置の不適切[\s\S]{0,15}事故|公衆損害事故|手抜工事|贈賄|"
            r"虚偽記載|労働安全衛生法違反)"
        )
        rm = reason_kw.search(block_text)
        if rm:
            reason = rm.group(1).strip()

        # Issuance date: use the publication date as issuance date if no clear
        # processing date is available. Fall back to period_start.
        issuance_date = period_start

        rows.append(
            EnfRow(
                org_slug=source.org_slug,
                issuing_authority=source.issuing_authority,
                target_name=name,
                address=address,
                issuance_date=issuance_date,
                period_start=period_start,
                period_end=period_end,
                enforcement_kind="contract_suspend",
                punishment_raw="指名停止",
                reason_summary=reason,
                related_law_ref=None,
                houjin_bangou=None,
                source_url=source.pdf_url,
            )
        )
    return rows


def parse_cum_pdf(text: str, source: CityCumPdf) -> list[EnfRow]:
    """Generic cumulative-list PDF parser for 政令市 publications.

    Anchor on lines containing a "Nヵ月" or 期間 marker AND a company name AND
    a date pair. Falls back to row-by-row segmentation by company anchors.
    """
    if not text:
        return []
    rows: list[EnfRow] = []

    # Strategy: walk lines, group by row anchor. A row anchor is either
    # (a) a line whose head contains a company token OR
    # (b) a line whose head matches "  N   <date>" (numbered rows like Kawasaki).
    lines = text.splitlines()
    blocks: list[list[str]] = []
    cur: list[str] = []
    row_anchor_rx = re.compile(r"^\s*[0-9]{1,4}\s+(?:R\s*\d+|令和\s*\d+|H\s*\d+|\d{4}[./\-])")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if cur:
                cur.append("")
            continue
        head = stripped[:80]
        is_anchor = looks_like_company(head) or row_anchor_rx.match(line)
        if is_anchor:
            if cur:
                blocks.append(cur)
            cur = [line]
        else:
            cur.append(line)
    if cur:
        blocks.append(cur)

    period_rx = re.compile(
        r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)\s*(?:から|[～\-~–])\s*"
        r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)"
    )
    # Alternative period: 自：令和... 至：令和... (Nagoya)
    jishi_rx = re.compile(
        r"自[：:]\s*(令和\s*\d+\s*年[\s\d０-９]+月[\s\d０-９]+日)[\s\S]{0,40}?"
        r"至[：:]\s*(令和\s*\d+\s*年[\s\d０-９]+月[\s\d０-９]+日)"
    )
    # Alternative period: R{N}.M.D～R{N}.M.D (Kawasaki / Saitama variants)
    short_period_rx = re.compile(
        r"(R\s*\d+[.\s]+\d+[.\s]+\d+|令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)\s*[～\-~–]+\s*"
        r"(R\s*\d+[.\s]+\d+[.\s]+\d+|令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)"
    )

    for block in blocks:
        block_text = "\n".join(block)
        pm = period_rx.search(block_text)
        if not pm:
            pm = jishi_rx.search(block_text)
        if not pm:
            pm = short_period_rx.search(block_text)
        if not pm:
            continue
        period_start = parse_first_date(pm.group(1))
        period_end = parse_first_date(pm.group(2))
        if not period_start:
            continue
        # Company name from first line.
        first_line = block[0].strip()
        # Strip leading row numbering and any leading R/令和/H date token.
        first_line = re.sub(r"^(?:[0-9０-９]+\s*[.．、)）]?\s*)+", "", first_line)
        first_line = re.sub(
            r"^(?:R\s*\d+[.\s]+\d+[.\s]+\d+|令和\s*\d+\s*年[\d０-９]+月[\d０-９]+日)\s+",
            "",
            first_line,
        )
        parts = re.split(r"\s{2,}|　{2,}", first_line)
        parts = [p.strip() for p in parts if p.strip()]
        if not parts:
            continue
        # Locate the first part that contains a company token.
        name_idx = -1
        for i, p in enumerate(parts):
            if looks_like_company(p):
                name_idx = i
                break
        if name_idx < 0:
            # Fall back to parts[0]
            name = parts[0]
        else:
            name = parts[name_idx]
            # Merge with next part if needed (e.g. "株式会社" followed by "美栄工業")
            if name_idx + 1 < len(parts):
                nxt = parts[name_idx + 1]
                # Only merge if next part isn't an address/prefecture or date.
                if (
                    not re.match(r"^[一-鿿]+(?:都|道|府|県|市|区|町|村)", nxt)
                    and not re.search(r"R\d+\.|令和|\d{4}[./\-]", nxt)
                    and len(nxt) <= 40
                    and not re.match(r"^\d", nxt)
                ):
                    name = name + nxt
        # If name continues on next line (Nagoya style: "株式会社ＡＤＫマーケティン" → "グ・ソリューションズ中部支社"),
        # append the next non-empty line ONLY if the current name doesn't already
        # end with a company suffix AND the next line first segment looks like a
        # name continuation (no 都道府県市区町村 prefix, no 令和/R-date, no 数字+丁目).
        company_suffix_rx = re.compile(
            r"(株式会社|有限会社|合同会社|合資会社|\(株\)|（株）|\(有\)|（有）|"
            r"公益社団法人|公益財団法人|社会福祉法人|医療法人|一般財団法人|一般社団法人)$"
        )
        if not company_suffix_rx.search(name):
            for follow in block[1:]:
                fl = follow.strip()
                if not fl:
                    continue
                # Skip lines that are clearly addresses, periods, or reasons.
                if re.search(r"令和|R\d+\.|\d+丁目|\d+番地|～|から|まで", fl):
                    break
                if re.match(r"^[一-鿿]+(?:都|道|府|県)", fl):
                    break
                cand = re.split(r"\s{2,}|　{2,}", fl)[0].strip()
                # Continuation must be a plausible name fragment (Japanese chars,
                # no period, no leading punctuation that would indicate reason
                # parenthetical like "反）").
                if not cand:
                    continue
                if cand.startswith(("反", "）", ")", "（", "(", ".", "。", "、")):
                    break
                if re.search(r"^[一-鿿]+(?:停止|違反|事故|妨害|談合|事業|工事|令和)", cand):
                    break
                name = (name + cand).strip()
                break
        name = name.strip()
        if not name or len(name) < 2 or not looks_like_company(name):
            continue
        # Address: scan parts after the name for a 都道府県/市区町村 fragment.
        address: str | None = None
        for p in parts[name_idx + 1 :] if name_idx >= 0 else parts[1:]:
            if re.match(r"^[一-鿿]+(?:都|道|府|県|市|区|町|村)", p):
                address = p
                break
        if not address:
            am = re.search(
                r"([一-鿿]+(?:都|道|府|県)[一-鿿々\-ー\d０-９丁目番地号]+(?:[一二三四五六七八九十\d０-９]+丁目)?[一二三四五六七八九十\d０-９]*)",
                block_text,
            )
            if am:
                address = am.group(1)[:200]

        # Reason: take everything after "停止理由" / "理由" / "違反" / "事故" tokens, or last segment.
        reason_match = re.search(
            r"(独占禁止法[^\n]*?|建設業法[^\n]*?|公衆損害事故[^\n]*?|安全管理[^\n]*?|"
            r"談合[^\n]*?|契約違反[^\n]*?|不正又は不誠実[^\n]*?|過失[^\n]*?|"
            r"労働安全衛生[^\n]*?|偽造[^\n]*?|競売入札妨害[^\n]*?|贈賄[^\n]*?)",
            block_text,
        )
        reason = reason_match.group(1).strip()[:500] if reason_match else None
        if not reason:
            reason = re.sub(r"\s+", " ", block_text)[:500]

        # 適用条項
        betsu = re.search(r"別表第[0-9０-９一二三]+第\d+号", block_text)
        related = betsu.group(0)[:200] if betsu else "指名停止基準要綱"

        houjin = (
            normalize_houjin(re.search(r"\b\d{13}\b", block_text).group(0))
            if re.search(r"\b\d{13}\b", block_text)
            else None
        )

        rows.append(
            EnfRow(
                org_slug=source.org_slug,
                issuing_authority=source.issuing_authority,
                target_name=name,
                address=address,
                issuance_date=period_start,
                period_start=period_start,
                period_end=period_end,
                enforcement_kind="contract_suspend",
                punishment_raw="指名停止",
                reason_summary=reason,
                related_law_ref=related,
                houjin_bangou=houjin,
                source_url=source.pdf_url,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# 9. Yokohama epco MeiboTeishiList (Shift_JIS HTML form)
# ---------------------------------------------------------------------------

YOKOHAMA_URL = "https://keiyaku.city.yokohama.lg.jp/epco/servlet/p?job=MeiboTeishiList"


def parse_yokohama(html: str) -> list[EnfRow]:
    if not html:
        return []
    rows: list[EnfRow] = []
    # Each disciplinary entry uses 5 rows of left-aligned <td>:
    #   1) registration code (pcv300-column-bottom valign="middle" align="center")
    #   2) (empty image cell)
    #   3) NAME (valign="top" align="left")
    #   4) ADDRESS
    #   5) PERIOD (令和 yyyy.mm.dd 〜 令和 yyyy.mm.dd)
    #   6) REASON
    #   7) NOTE (備考)
    # We extract "NAME" / "ADDRESS" / "PERIOD" / "REASON" tuples by walking <td> tags.
    td_rx = re.compile(
        r'<td[^>]*pcv300-column-bottom[^>]*valign="top"[^>]*align="left"[^>]*>(.*?)</td>',
        flags=re.IGNORECASE | re.DOTALL,
    )
    cells = [_strip_html(m.group(1)) for m in td_rx.finditer(html)]
    # Cells come in groups of 4: NAME, ADDR, PERIOD, REASON (the trailing 備考
    # cell is often empty). Walk in steps of 4 and validate.
    i = 0
    while i + 3 < len(cells):
        name = cells[i].strip()
        addr = cells[i + 1].strip()
        period = cells[i + 2].strip()
        reason = cells[i + 3].strip()
        # Skip the optional 5th 備考 cell if present and empty.
        # But sometimes the 備考 cell is non-empty; advance by 4 and scan for
        # the next legitimate "name" cell.
        if not looks_like_company(name) and not any(
            t in name for t in ("市", "県", "公益", "学校法人", "法人")
        ):
            i += 1
            continue
        # Period should contain 令和 and ～
        if "令和" not in period or "〜" not in period and "～" not in period:
            i += 1
            continue
        period = period.replace("〜", "～")
        period = re.sub(r"\s+", "", period)
        period_dates = all_dates(period)
        if len(period_dates) < 2:
            i += 1
            continue
        period_start, period_end = period_dates[0], period_dates[1]
        rows.append(
            EnfRow(
                org_slug="yokohama",
                issuing_authority="横浜市",
                target_name=name,
                address=addr or None,
                issuance_date=period_start,
                period_start=period_start,
                period_end=period_end,
                enforcement_kind="contract_suspend",
                punishment_raw="指名停止",
                reason_summary=(reason or "")[:500] or None,
                related_law_ref="横浜市指名停止等措置要綱",
                houjin_bangou=None,
                source_url=YOKOHAMA_URL,
            )
        )
        i += 4
    return rows


# ---------------------------------------------------------------------------
# 10. Kobe HTML page (<h2>{NAME}＜{ADDR}＞</h2> repeating blocks)
# ---------------------------------------------------------------------------

KOBE_URL = "https://www.city.kobe.lg.jp/a05182/shimeiteishisochi.html"


def parse_kobe(html: str) -> list[EnfRow]:
    if not html:
        return []
    rows: list[EnfRow] = []
    # Split on <h2> markers.
    sections = re.split(r"<h2[^>]*>", html, flags=re.IGNORECASE)
    for sec in sections[1:]:
        # Section header: "<NAME>＜<ADDR>＞</h2>..."
        head_match = re.match(r"([^<＜]+)＜([^＞]+)＞</h2>", sec, flags=re.IGNORECASE)
        if not head_match:
            continue
        name = head_match.group(1).strip()
        addr = head_match.group(2).strip()
        if not looks_like_company(name) and not any(
            t in name for t in ("有限会社", "公益", "法人")
        ):
            continue
        # Period is "指名停止期間：YYYY年MM月DD日～YYYY年MM月DD日（Nヶ月）"
        period_match = re.search(
            r"指名停止期間\s*[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*[～\-~–]\s*"
            r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
            sec,
        )
        if not period_match:
            continue
        try:
            period_start = dt.date(
                int(period_match.group(1)),
                int(period_match.group(2)),
                int(period_match.group(3)),
            ).isoformat()
            period_end = dt.date(
                int(period_match.group(4)),
                int(period_match.group(5)),
                int(period_match.group(6)),
            ).isoformat()
        except ValueError:
            continue
        # Reason text: <p> after "指名停止の理由"
        reason_match = re.search(
            r"指名停止の理由[\s\S]*?<br\s*/?>\s*([\s\S]+?)(?=</p>|<br[^>]*>\s*（|<br[^>]*>\s*\(|（神戸市指名停止)",
            sec,
            flags=re.IGNORECASE,
        )
        reason = _strip_html(reason_match.group(1)) if reason_match else None
        # 適用条項
        betsu = re.search(r"別表第[12０-９一二三]\s*第\d+\s*[項号]", sec)
        related = betsu.group(0)[:200] if betsu else "神戸市指名停止基準要綱"
        rows.append(
            EnfRow(
                org_slug="kobe",
                issuing_authority="神戸市",
                target_name=name,
                address=addr,
                issuance_date=period_start,
                period_start=period_start,
                period_end=period_end,
                enforcement_kind="contract_suspend",
                punishment_raw="指名停止",
                reason_summary=(reason or "")[:1000] or None,
                related_law_ref=related,
                houjin_bangou=None,
                source_url=KOBE_URL,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# 11. Kyoto 府 (zaisan + nyusatu PDFs)
# ---------------------------------------------------------------------------

KYOTO_PDFS = [
    CityCumPdf(
        org_slug="kyoto-pref",
        issuing_authority="京都府",
        pdf_url="https://www.pref.kyoto.jp/zaisan/documents/r80401.pdf",
    ),
    CityCumPdf(
        org_slug="kyoto-pref",
        issuing_authority="京都府",
        pdf_url="https://www.pref.kyoto.jp/zaisan/documents/r70401.pdf",
    ),
    CityCumPdf(
        org_slug="kyoto-pref",
        issuing_authority="京都府",
        pdf_url="https://www.pref.kyoto.jp/zaisan/documents/r60401.pdf",
    ),
    CityCumPdf(
        org_slug="kyoto-pref",
        issuing_authority="京都府",
        pdf_url="https://www.pref.kyoto.jp/nyusatu/documents/list_entry_suspended_20250408.pdf",
    ),
    CityCumPdf(
        org_slug="kyoto-pref",
        issuing_authority="京都府",
        pdf_url="https://www.pref.kyoto.jp/nyusatu/documents/list_entry_suspended_20240408.pdf",
    ),
]


def parse_kyoto_pdf(text: str, source: CityCumPdf) -> list[EnfRow]:
    """Kyoto pref tabular layout. Each row spans 2-3 lines:
        令和{N}年{M}月{D}日から            {company}        {address}    {reason}
                    商号又は名称
        令和{N}年{M}月{D}日まで                        ({related law})
    Strategy: walk lines, when a "から" line is found, look for the matching
    "まで" line within next 4 lines AND a company-name on adjacent line.
    """
    if not text:
        return []
    rows: list[EnfRow] = []
    lines = text.splitlines()
    kara_rx = re.compile(r"令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日\s*から")
    made_rx = re.compile(r"令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日\s*まで")
    date_rx = re.compile(r"令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日")

    i = 0
    while i < len(lines):
        line = lines[i]
        if kara_rx.search(line):
            # Look for まで within next 5 lines.
            made_idx = -1
            for j in range(i + 1, min(i + 6, len(lines))):
                if made_rx.search(lines[j]):
                    made_idx = j
                    break
            if made_idx < 0:
                i += 1
                continue
            # Block: lines i..made_idx
            block_lines = lines[i : made_idx + 1]
            block_text = "\n".join(block_lines)
            kara_m = re.search(r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)\s*から", block_text)
            made_m = re.search(r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)\s*まで", block_text)
            if not kara_m or not made_m:
                i = made_idx + 1
                continue
            period_start = parse_first_date(kara_m.group(1))
            period_end = parse_first_date(made_m.group(1))
            if not period_start:
                i = made_idx + 1
                continue
            # Find company name in any block line.
            name = None
            for ln in block_lines:
                # Strip kara/made dates first.
                stripped = kara_rx.sub("", ln)
                stripped = made_rx.sub("", stripped)
                stripped = date_rx.sub("", stripped)
                stripped = stripped.strip()
                # Tokenize by 2+ whitespace.
                for tok in re.split(r"\s{2,}|　{2,}", stripped):
                    tok = tok.strip()
                    if not tok:
                        continue
                    # Reject tokens that are address prefectures, reason texts.
                    if re.match(r"^[一-鿿]+(?:都|道|府|県|市|区|町|村)", tok):
                        continue
                    if re.search(r"違反|理由|別表|不正|談合|契約", tok):
                        continue
                    if not looks_like_company(tok):
                        continue
                    if 3 <= len(tok) <= 80:
                        name = tok
                        break
                if name:
                    break
            if not name:
                i = made_idx + 1
                continue
            address = None
            for ln in block_lines:
                m_addr = re.search(r"([一-鿿]+(?:府|県|都|道)[^\s]*[市区町村][^\s]*)", ln)
                if m_addr:
                    address = m_addr.group(1)
                    break
                # Fallback: 京都市右京区, etc. (no pref prefix).
                m_addr2 = re.search(r"(京都[市府][^\s]+[区町])", ln)
                if m_addr2:
                    address = m_addr2.group(1)
                    break
            reason = None
            reason_kw = re.compile(
                r"(独占禁止法違反行為|契約違反|不正又は不誠実な行為|談合(?:及び競売入札妨害)?|"
                r"安全管理措置の不適切[\s\S]{0,15}事故|公衆損害事故|手抜工事|贈賄|"
                r"虚偽記載|労働安全衛生法違反|建設業法違反行為)"
            )
            rm = reason_kw.search(block_text)
            if rm:
                reason = rm.group(1).strip()
            rows.append(
                EnfRow(
                    org_slug=source.org_slug,
                    issuing_authority=source.issuing_authority,
                    target_name=name,
                    address=address,
                    issuance_date=period_start,
                    period_start=period_start,
                    period_end=period_end,
                    enforcement_kind="contract_suspend",
                    punishment_raw="指名停止",
                    reason_summary=reason,
                    related_law_ref=None,
                    houjin_bangou=None,
                    source_url=source.pdf_url,
                )
            )
            i = made_idx + 1
        else:
            i += 1
    return rows


# ---------------------------------------------------------------------------
# DB layer (mirror mlit_chiho_pref)
# ---------------------------------------------------------------------------


def open_db(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=300.0)
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA journal_mode = WAL")
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_enforcement_detail'"
    ).fetchone()
    if not row:
        conn.close()
        raise SystemExit("am_enforcement_detail missing")
    return conn


def load_dedup(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for r in conn.execute(
        "SELECT IFNULL(issuing_authority, ''), IFNULL(target_name, ''), issuance_date "
        "FROM am_enforcement_detail"
    ):
        out.add((r[0], r[1], r[2]))
    return out


def insert_row(conn: sqlite3.Connection, row: EnfRow, fetched_at: str) -> str:
    canonical_id = row.canonical_id()
    raw_json = json.dumps(
        {
            "org_slug": row.org_slug,
            "issuing_authority": row.issuing_authority,
            "target_name": row.target_name,
            "address": row.address,
            "issuance_date": row.issuance_date,
            "period_start": row.period_start,
            "period_end": row.period_end,
            "enforcement_kind": row.enforcement_kind,
            "punishment_raw": row.punishment_raw,
            "reason_summary": row.reason_summary,
            "related_law_ref": row.related_law_ref,
            "houjin_bangou": row.houjin_bangou,
            "source_url": row.source_url,
            "fetched_at": fetched_at,
            "source": "shimei_teishi",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    src_domain = urllib.parse.urlparse(row.source_url).netloc

    cur = conn.execute(
        """INSERT OR IGNORE INTO am_entities (
            canonical_id, record_kind, source_topic, primary_name,
            confidence, source_url, source_url_domain, fetched_at, raw_json
        ) VALUES (?, 'enforcement', 'shimei_teishi', ?, ?, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            row.target_name,
            0.92,
            row.source_url,
            src_domain,
            fetched_at,
            raw_json,
        ),
    )
    entity_inserted = cur.rowcount > 0

    existing = conn.execute(
        "SELECT enforcement_id FROM am_enforcement_detail WHERE entity_id = ?",
        (canonical_id,),
    ).fetchone()
    if existing:
        return "skip"

    conn.execute(
        """INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen,
            source_url, source_fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            canonical_id,
            row.houjin_bangou,
            row.target_name[:500],
            row.enforcement_kind,
            row.issuing_authority,
            row.issuance_date,
            row.period_start,
            row.period_end,
            (row.reason_summary or "")[:4000] or None,
            (row.related_law_ref or "")[:1000] or None,
            row.source_url,
            fetched_at,
        ),
    )
    return "insert" if entity_inserted else "update"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_SOURCES = (
    "mlit-kanbo,mlit-eizen,thr,hrr,kkr,skr,saitama,chiba,kawasaki,nagoya,kobe,yokohama,kyoto-pref"
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--limit", type=int, default=None, help="stop once total queued reaches this value"
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--sources", type=str, default=ALL_SOURCES, help="comma list of source ids to walk"
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    sources = {s.strip() for s in args.sources.split(",") if s.strip()}
    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    http = HttpClient()

    dedup: set[tuple[str, str, str]] = set()
    if not args.dry_run:
        c0 = open_db(args.db)
        try:
            dedup = load_dedup(c0)
            _LOG.info("preload dedup keys=%d", len(dedup))
        finally:
            c0.close()

    pending: list[EnfRow] = []
    counters: dict[str, dict[str, int]] = {}

    def stat(slug: str) -> dict[str, int]:
        return counters.setdefault(slug, {"fetched": 0, "built": 0, "dup": 0})

    def add_rows(slug: str, rows: list[EnfRow]) -> None:
        stat(slug)["built"] += len(rows)
        for r in rows:
            key = (r.issuing_authority, r.target_name, r.issuance_date)
            if key in dedup:
                stat(slug)["dup"] += 1
                continue
            dedup.add(key)
            pending.append(r)

    def reached_limit() -> bool:
        return bool(args.limit and len(pending) >= args.limit)

    try:
        # ===== MLIT 大臣官房会計課 =====
        if "mlit-kanbo" in sources and not reached_limit():
            for pdf_url in discover_mlit_kanbo_pdfs(http):
                if reached_limit():
                    break
                pres = http.get(pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("mlit-kanbo")["fetched"] += 1
                text = _pdftotext(pres.body)
                add_rows("mlit-kanbo", parse_mlit_kanbo_pdf(text, pdf_url))

        # ===== MLIT 営繕部 =====
        if "mlit-eizen" in sources and not reached_limit():
            for pdf_url in discover_mlit_eizen_pdfs(http):
                if reached_limit():
                    break
                pres = http.get(pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("mlit-eizen")["fetched"] += 1
                text = _pdftotext(pres.body)
                src = SingleCasePdfSource(
                    org_slug="mlit-eizen",
                    issuing_authority="国土交通省大臣官房官庁営繕部",
                    pdf_url=pdf_url,
                )
                add_rows("mlit-eizen", parse_single_case_pdf(text, src))

        # ===== THR 東北 累積 PDF =====
        if "thr" in sources and not reached_limit():
            for url, _fy in THR_PDF_URLS:
                if reached_limit():
                    break
                pres = http.get(url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("thr")["fetched"] += 1
                text = _pdftotext(pres.body)
                add_rows("thr", parse_thr_pdf(text, url))

        # ===== HRR 北陸 press PDFs =====
        if "hrr" in sources and not reached_limit():
            hrr_pdfs = discover_hrr_pdfs(http)
            _LOG.info("hrr discovered %d pdfs", len(hrr_pdfs))
            for src in hrr_pdfs:
                if reached_limit():
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("hrr")["fetched"] += 1
                text = _pdftotext(pres.body)
                add_rows("hrr", parse_single_case_pdf(text, src))

        # ===== KKR 近畿 case PDFs =====
        if "kkr" in sources and not reached_limit():
            kkr_pdfs = discover_kkr_pdfs(http)
            _LOG.info("kkr discovered %d pdfs", len(kkr_pdfs))
            for src in kkr_pdfs:
                if reached_limit():
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("kkr")["fetched"] += 1
                text = _pdftotext(pres.body)
                add_rows("kkr", parse_single_case_pdf(text, src))

        # ===== SKR 四国 case PDFs (Shift_JIS index) =====
        if "skr" in sources and not reached_limit():
            skr_pdfs = discover_skr_pdfs(http)
            _LOG.info("skr discovered %d pdfs", len(skr_pdfs))
            for src in skr_pdfs:
                if reached_limit():
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("skr")["fetched"] += 1
                text = _pdftotext(pres.body)
                # SKR press PDFs have spaces between every Japanese character.
                text = _compress_jp_spaces(text)
                add_rows("skr", parse_single_case_pdf(text, src))

        # ===== Saitama (cum PDF) =====
        if "saitama" in sources and not reached_limit():
            for slug, auth, url in SAITAMA_PDFS:
                if reached_limit():
                    break
                pres = http.get(url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat(slug)["fetched"] += 1
                text = _pdftotext(pres.body)
                src = CityCumPdf(org_slug=slug, issuing_authority=auth, pdf_url=url)
                add_rows(slug, parse_cum_pdf(text, src))

        # ===== Chiba City =====
        if "chiba" in sources and not reached_limit():
            for src in discover_chiba_pdfs(http):
                if reached_limit():
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat(src.org_slug)["fetched"] += 1
                text = _pdftotext(pres.body)
                # Try chiba-specific parser first; fall back to generic.
                chiba_rows = parse_chiba_pdf(text, src)
                if chiba_rows:
                    add_rows(src.org_slug, chiba_rows)
                else:
                    add_rows(src.org_slug, parse_cum_pdf(text, src))

        # ===== Kawasaki =====
        if "kawasaki" in sources and not reached_limit():
            for src in discover_kawasaki_pdfs(http):
                if reached_limit():
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat(src.org_slug)["fetched"] += 1
                text = _pdftotext(pres.body)
                add_rows(src.org_slug, parse_cum_pdf(text, src))

        # ===== Nagoya =====
        if "nagoya" in sources and not reached_limit():
            for src in NAGOYA_PDFS:
                if reached_limit():
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat(src.org_slug)["fetched"] += 1
                text = _pdftotext(pres.body)
                add_rows(src.org_slug, parse_nagoya_pdf(text, src))

        # ===== Kobe HTML =====
        if "kobe" in sources and not reached_limit():
            html = fetch_decoded(http, KOBE_URL, max_bytes=HTML_MAX)
            if html:
                stat("kobe")["fetched"] += 1
                add_rows("kobe", parse_kobe(html))

        # ===== Yokohama (Shift_JIS form) =====
        if "yokohama" in sources and not reached_limit():
            html = fetch_decoded(http, YOKOHAMA_URL, max_bytes=HTML_MAX)
            if html:
                stat("yokohama")["fetched"] += 1
                add_rows("yokohama", parse_yokohama(html))

        # ===== Kyoto pref PDFs =====
        if "kyoto-pref" in sources and not reached_limit():
            for src in KYOTO_PDFS:
                if reached_limit():
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat(src.org_slug)["fetched"] += 1
                text = _pdftotext(pres.body)
                add_rows(src.org_slug, parse_kyoto_pdf(text, src))

    finally:
        http.close()

    _LOG.info("queued=%d (per_source=%s)", len(pending), counters)

    if args.dry_run:
        for r in pending[:10]:
            _LOG.info(
                "DRY %s | %s | %s | %s | period=%s..%s",
                r.issuing_authority,
                r.issuance_date,
                r.target_name,
                r.punishment_raw[:40],
                r.period_start,
                r.period_end,
            )
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "queued": len(pending),
                    "per_source": counters,
                },
                ensure_ascii=False,
            )
        )
        return 0

    inserted = 0
    skip = 0
    if pending:
        for write_attempt in range(6):
            conn = open_db(args.db)
            try:
                conn.execute("BEGIN IMMEDIATE")
                for r in pending:
                    try:
                        verdict = insert_row(conn, r, fetched_at)
                    except sqlite3.Error as exc:
                        _LOG.error("DB insert err %s: %s", r.target_name, exc)
                        continue
                    if verdict == "insert":
                        inserted += 1
                        if (inserted % 100) == 0:
                            conn.commit()
                            conn.execute("BEGIN IMMEDIATE")
                    else:
                        skip += 1
                conn.commit()
                break
            except sqlite3.OperationalError as exc:
                wait = 5 * (write_attempt + 1)
                _LOG.warning(
                    "write contention attempt=%d wait=%ds err=%s", write_attempt, wait, exc
                )
                time.sleep(wait)
                continue
            finally:
                conn.close()

    breakdown_q = []
    if not args.dry_run:
        c0 = open_db(args.db)
        try:
            for slug, auth in [
                ("mlit-kanbo", "国土交通省大臣官房会計課"),
                ("mlit-eizen", "国土交通省大臣官房官庁営繕部"),
                ("thr", "東北地方整備局"),
                ("hrr", "北陸地方整備局"),
                ("kkr", "近畿地方整備局"),
                ("skr", "四国地方整備局"),
                ("saitama", "さいたま市"),
                ("chiba", "千葉市"),
                ("kawasaki", "川崎市"),
                ("nagoya", "名古屋市"),
                ("kobe", "神戸市"),
                ("yokohama", "横浜市"),
                ("kyoto-pref", "京都府"),
            ]:
                n = c0.execute(
                    "SELECT COUNT(*) FROM am_enforcement_detail "
                    "WHERE issuing_authority = ? AND entity_id LIKE ?",
                    (auth, f"enforcement:shimei-teishi:{slug}:%"),
                ).fetchone()[0]
                breakdown_q.append((slug, auth, n))
        finally:
            c0.close()

    _LOG.info("SUMMARY queued=%d inserted=%d skip=%d", len(pending), inserted, skip)
    _LOG.info("BREAKDOWN %s", breakdown_q)
    print(
        json.dumps(
            {
                "queued": len(pending),
                "inserted": inserted,
                "skip": skip,
                "per_source": counters,
                "breakdown_by_org": breakdown_q,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
