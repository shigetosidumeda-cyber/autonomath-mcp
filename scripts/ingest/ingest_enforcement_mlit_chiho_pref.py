#!/usr/bin/env python3
"""Ingest 地方整備局 + 政令指定都市/都道府県 建設業課 監督処分・指名停止 into
``am_entities`` + ``am_enforcement_detail``.

Background:
  既に am_enforcement_detail に MLIT 中央 (kensetugyousya) 612 件あり、
  47 都道府県 工事系 指名停止 (pref_shimei_teishi) 数百件あり、
  47 労働局 (mhlw_roudoukyoku) 354 件あり。
  本 script は地方整備局単位 + 都道府県知事許可 建設業者監督処分 (Osaka 等) を
  追加層として取り込む。

Sources (primary, TOS無視で aggregator banned):
  ===== 地方整備局 (8 局) =====
  - 北海道開発局 指名停止: https://www.hkd.mlit.go.jp/ky/ki/kaikei/* (PDF/年度)
  - 関東地方整備局 監督処分: https://www.ktr.mlit.go.jp/kensan/* (PDF/案件)
  - 中部地方整備局 営業停止/指示: https://www.cbr.mlit.go.jp/kensei/info/syobun/*.htm
  - 中国地方整備局 指名停止: https://www.cgr.mlit.go.jp/order/sochi/pdf/* (PDF/案件)
  - 九州地方整備局 指名停止: https://www.qsr.mlit.go.jp/site_files/newstopics_files/* (PDF/案件)
  ===== 都道府県知事許可 建設業者 処分 =====
  - 大阪府 建設業処分業者一覧: https://www.pref.osaka.lg.jp/o130200/kenshin/syobunitiran-top/* (HTML/年度)

Schema target (autonomath.db):
  am_entities (canonical_id='enforcement:mlit-local:{org_slug}:{date}:{hash8}',
               record_kind='enforcement', source_topic='mlit_chiho_pref')
  am_enforcement_detail (entity_id, target_name, enforcement_kind,
                         issuing_authority, issuance_date,
                         exclusion_start, exclusion_end, reason_summary,
                         related_law_ref, source_url)

enforcement_kind mapping:
    指名停止              -> contract_suspend
    営業停止              -> business_improvement
    許可取消/取消し       -> license_revoke
    指示                  -> business_improvement
    監督処分              -> business_improvement (default)

dedup key: (issuing_authority, target_name, issuance_date)

CLI:
    python scripts/ingest/ingest_enforcement_mlit_chiho_pref.py \\
        --db autonomath.db [--limit 200] [--dry-run]

Parallel-safe: BEGIN IMMEDIATE + busy_timeout=300000.
"""

from __future__ import annotations

import argparse
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

_LOG = logging.getLogger("autonomath.ingest.mlit_chiho_pref")
DEFAULT_DB = REPO_ROOT / "autonomath.db"

PDF_MAX = 10 * 1024 * 1024
HTML_MAX = 4 * 1024 * 1024


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

# 令和7年4月17日 / 令和8年4月9日 (full-width digits permitted via NFKC)
_R_DATE = re.compile(r"令\s*和\s*([\d０-９]+)\s*年\s*([\d０-９]{1,2})\s*月\s*([\d０-９]{1,2})\s*日")
# 平成28年5月16日
_H_DATE = re.compile(r"平\s*成\s*([\d０-９]+)\s*年\s*([\d０-９]{1,2})\s*月\s*([\d０-９]{1,2})\s*日")
# 2024/3/27 or 2024.3.27
_ISO_DATE = re.compile(r"(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})")
# R7.4.17 / R8.4.9
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
    """Return ISO yyyy-mm-dd of first date in text (Reiwa preferred)."""
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
    """Return ISO dates in text, in order of appearance."""
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
    org_slug: str  # e.g. 'osaka-pref' / 'hkd' / 'cbr' / 'cgr' / 'qsr'
    issuing_authority: str  # '大阪府' / '北海道開発局' / '中部地方整備局' / ...
    target_name: str
    address: str | None
    issuance_date: str  # ISO yyyy-mm-dd
    period_start: str | None
    period_end: str | None
    enforcement_kind: str  # contract_suspend / business_improvement / license_revoke
    punishment_raw: str
    reason_summary: str | None
    related_law_ref: str | None
    houjin_bangou: str | None
    source_url: str

    def canonical_id(self) -> str:
        key = f"{self.issuing_authority}|{self.target_name}|{self.issuance_date}|{self.punishment_raw}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        return f"enforcement:mlit-local:{self.org_slug}:{self.issuance_date}:{digest}"


# ---------------------------------------------------------------------------
# Punishment → kind mapping
# ---------------------------------------------------------------------------


def map_kind(punish: str) -> str:
    p = punish or ""
    if "指名停止" in p:
        return "contract_suspend"
    if "取消し" in p or "取り消し" in p or "取消" in p:
        return "license_revoke"
    if "営業停止" in p or "業務停止" in p:
        return "business_improvement"
    if "指示" in p:
        return "business_improvement"
    if "監督処分" in p:
        return "business_improvement"
    return "business_improvement"


# ---------------------------------------------------------------------------
# HTML helpers
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


def _html_tables(html: str) -> list[str]:
    return re.findall(r"<table[^>]*>.*?</table>", html, flags=re.DOTALL | re.IGNORECASE)


def _table_rows(tbl_html: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr_m in re.finditer(r"<tr[^>]*>.*?</tr>", tbl_html, flags=re.DOTALL | re.IGNORECASE):
        cells = re.findall(
            r"<t[hd][^>]*>(.*?)</t[hd]>",
            tr_m.group(0),
            flags=re.DOTALL | re.IGNORECASE,
        )
        rows.append([_strip_html(c) for c in cells])
    return rows


# ---------------------------------------------------------------------------
# pdftotext shell-out
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Osaka 大阪府 HTML parser (Source 1)
# ---------------------------------------------------------------------------

OSAKA_FY_URLS = [
    ("https://www.pref.osaka.lg.jp/o130200/kenshin/syobunitiran-top/syobunitiran-r07.html", "R7"),
    ("https://www.pref.osaka.lg.jp/o130200/kenshin/syobunitiran-top/syobunitiran-r06.html", "R6"),
    ("https://www.pref.osaka.lg.jp/kenshin/syobunitiran-top/syobunitiran-r05.html", "R5"),
    ("https://www.pref.osaka.lg.jp/kenshin/syobunitiran-top/syobunitiran-r04.html", "R4"),
    ("https://www.pref.osaka.lg.jp/kenshin/syobunitiran-top/syobunitiran-r03.html", "R3"),
]


def parse_osaka_fy_page(html: str, source_url: str) -> list[EnfRow]:
    """Osaka 大阪府 8-column table:
    建設業者名 / 主たる営業所所在地等 / 許可番号 / 処分内容 /
    処分年月日 / 処分事由 / 備考(原因) / 法人番号
    """
    rows: list[EnfRow] = []
    for tbl_html in _html_tables(html):
        # Validate this is the disciplinary table by checking header presence.
        if "建設業者名" not in tbl_html or "処分年月日" not in tbl_html:
            continue
        for cells in _table_rows(tbl_html):
            if len(cells) < 5:
                continue
            # Skip header rows (cell[0] == 建設業者名)
            name = cells[0].strip()
            if not name or name == "建設業者名":
                continue
            address = cells[1].strip() if len(cells) > 1 else None
            license_no = cells[2].strip() if len(cells) > 2 else None
            punish = cells[3].strip() if len(cells) > 3 else ""
            date_raw = cells[4].strip() if len(cells) > 4 else ""
            reason_clause = cells[5].strip() if len(cells) > 5 else None
            reason_detail = cells[6].strip() if len(cells) > 6 else None
            houjin_raw = cells[7].strip() if len(cells) > 7 else None

            iso = parse_first_date(date_raw)
            if not iso:
                continue
            kind = map_kind(punish)

            # Extract period from punishment string if 営業停止
            period_start: str | None = None
            period_end: str | None = None
            if "営業停止" in punish:
                period_dates = all_dates(punish)
                if len(period_dates) >= 2:
                    period_start, period_end = period_dates[0], period_dates[1]

            houjin = None
            if houjin_raw:
                digits = re.sub(r"\D", "", houjin_raw)
                if len(digits) == 13:
                    houjin = digits

            reason_combined: str | None = None
            for piece in [reason_clause, reason_detail]:
                if piece:
                    reason_combined = (
                        (reason_combined + " / " + piece) if reason_combined else piece
                    )
            if reason_combined:
                reason_combined = reason_combined[:1500]

            related = None
            if license_no:
                # Keep license number as ancillary; primary law ref from 処分事由
                pass
            if reason_clause:
                # Most are 建設業法第N条…
                m = re.search(r"建設業法[^\s／]+", reason_clause)
                if m:
                    related = m.group(0)[:200]

            rows.append(
                EnfRow(
                    org_slug="osaka-pref",
                    issuing_authority="大阪府",
                    target_name=name,
                    address=address,
                    issuance_date=iso,
                    period_start=period_start,
                    period_end=period_end,
                    enforcement_kind=kind,
                    punishment_raw=punish,
                    reason_summary=reason_combined,
                    related_law_ref=related,
                    houjin_bangou=houjin,
                    source_url=source_url,
                )
            )
    return rows


# ---------------------------------------------------------------------------
# Hokkaido 開発局 PDF index walker (Source 2)
# ---------------------------------------------------------------------------

HKD_INDEX_PAGES = [
    "https://www.hkd.mlit.go.jp/ky/ki/kaikei/jtfkjs0000007c3p.html",  # R8
    "https://www.hkd.mlit.go.jp/ky/ki/kaikei/k5m5qg0000003u0s.html",  # R7
    "https://www.hkd.mlit.go.jp/ky/ki/kaikei/slo5pa000001dfpz.html",  # R6
    "https://www.hkd.mlit.go.jp/ky/ki/kaikei/slo5pa00000112g3.html",  # R5
    "https://www.hkd.mlit.go.jp/ky/ki/kaikei/slo5pa000000l3rs.html",  # R4
]


def find_hkd_pdf_links(html: str, page_url: str) -> list[str]:
    """Find PDF links in Hokkaido fiscal year index."""
    base = page_url.rsplit("/", 1)[0] + "/"
    out: list[str] = []
    seen: set[str] = set()
    for href in re.findall(
        r'<a[^>]+href="([^"]+\.pdf)"',
        html,
        flags=re.IGNORECASE,
    ):
        if href.startswith("http"):
            absurl = href
        elif href.startswith("/"):
            absurl = "https://www.hkd.mlit.go.jp" + href
        else:
            absurl = urllib.parse.urljoin(base, href)
        # Filter to 措置 PDFs only — must be in -att/ subpath
        if "/kaikei/" not in absurl:
            continue
        if absurl in seen:
            continue
        # Skip 措置要領 / 苦情処理 boilerplate (single-shot guidance documents)
        if any(k in absurl for k in ("buppintousoti", "kujyou")):
            continue
        # Skip the requirements doc (knqr/knw4 + bpwi pattern)
        if "knw4" in absurl or "bpwi" in absurl:
            continue
        seen.add(absurl)
        out.append(absurl)
    return out


def parse_hkd_pdf(text: str, source_url: str) -> list[EnfRow]:
    """Hokkaido 開発局: 1 PDF = 1 措置 case.

    Format:
        令和X年Y月Z日
        北海道開発局
        指名停止措置を行いました
        ...
        １． 指名停止措置業者名及び住所
              指名停止措置業者名         住    所
            <NAME>                     <ADDRESS>

        ２．指名停止措置期間：令和X1年Y1月Z1日 ～ 令和X2年Y2月Z2日 (Nか月)
    """
    if not text:
        return []
    # Issuance date = top-of-page date
    issuance = parse_first_date(text[:400])
    if not issuance:
        return []

    # Skip non-措置 documents (e.g. 措置要領 itself).
    if "措置を行いました" not in text and "指名停止" not in text:
        return []

    target_name: str | None = None
    address: str | None = None

    # Pattern 0 (most reliable): the lead paragraph "北海道開発局は、<NAME>に対し".
    lead = re.search(
        r"北海道開発局は[、,]\s*([^\n、。]+?)(?:及び同社代表取締役)?(?:及び[^、。]+)?に対し",
        text,
    )
    if lead:
        cand = lead.group(1).strip()
        # Strip 「」 quotes if present.
        cand = cand.strip("「」『』\"' 　")
        if any(
            tok in cand
            for tok in (
                "株式会社",
                "有限会社",
                "合同会社",
                "合資会社",
                "（株）",
                "(株)",
                "（有）",
                "(有)",
            )
        ):
            target_name = cand

    # Pattern 1: line right after 指名停止措置業者名 ... 住所 header (skip the header line itself).
    if not target_name:
        m = re.search(
            r"指名停止措置業者名[^\n]*住\s*所\s*\n([\s\S]+?)(?=\n[^\n]*指\s*名\s*停\s*止\s*措\s*置\s*期\s*間|\n\d[\s.．、]+指名停止)",
            text,
        )
        if m:
            block = m.group(1).strip()
            for line in block.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Skip header echoes and numbering rows.
                if line.startswith("指名停止措置業者名") or ("住所" in line and "業者名" in line):
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
                cand = parts[0].strip()
                if cand in {"指名停止措置業者名", "業者名", "住所", "業者の住所"}:
                    continue
                if not any(
                    tok in cand
                    for tok in (
                        "株式会社",
                        "有限会社",
                        "合同会社",
                        "合資会社",
                        "（株）",
                        "(株)",
                        "（有）",
                        "(有)",
                    )
                ):
                    continue
                target_name = cand
                if len(parts) > 1:
                    address = " ".join(parts[1:])
                break

    if not target_name:
        # Fallback: look for company name on a body line.
        for line in text.splitlines():
            if "株式会社" in line or "有限会社" in line or "合同会社" in line:
                if "住所" in line or "所在地" in line:
                    continue
                cand = line.strip()
                if any(
                    skip in cand
                    for skip in ("措置業者名", "指名停止措置業者名", "電話", "問合せ", "代表取締役")
                ):
                    continue
                cand = re.sub(
                    r"^(?:[1-9０-９一二三四五六七八九]\s*[.．、)）]?\s*)+", "", cand
                ).strip()
                parts = re.split(r"\s{2,}|　{1,}", cand)
                if parts and parts[0] not in {"指名停止措置業者名"}:
                    target_name = parts[0].strip()
                    if len(parts) > 1:
                        address = " ".join(parts[1:]).strip()
                    break

    if not target_name or len(target_name) < 2:
        return []
    if target_name in {"指名停止措置業者名", "業者名"}:
        return []

    # Period
    period_start: str | None = None
    period_end: str | None = None
    period_match = re.search(
        r"指\s*名\s*停\s*止\s*措\s*置\s*期\s*間[：:\s]*([\s\S]{1,300}?)(?:３|3)[\s.．、]",
        text,
    )
    if period_match:
        period_dates = all_dates(period_match.group(1))
        if len(period_dates) >= 2:
            period_start, period_end = period_dates[0], period_dates[1]
        elif len(period_dates) == 1:
            period_start = period_dates[0]

    # Reason summary: pull subtitle line "～理由～"
    reason: str | None = None
    sub = re.search(r"指名停止措置を行いました\s*[\n～]*\s*～([^～\n]{2,80})～", text)
    if sub:
        reason = sub.group(1).strip()
    # Also collect a longer reason from the body paragraph.
    re.search(
        r"(?:１|1)[\s.．、]+指名停止措置業者名[\s\S]+?(?=記\s*\n)",
        text,
    )
    # Better: take the lead paragraph between page header and `記`.
    pre_record = text.split("記", 1)[0]
    if pre_record:
        para = re.sub(r"\s+", " ", pre_record)
        # Remove header date lines.
        reason = (reason + " / " + para)[:1500] if reason else para[:1500]

    # Punishment 期間 + label
    raw_punish = "指名停止"
    period_text = re.search(r"(\d+\s*[ヵか]月)", text)
    if period_text:
        raw_punish = f"指名停止 {period_text.group(1)}"

    return [
        EnfRow(
            org_slug="hkd",
            issuing_authority="北海道開発局",
            target_name=target_name,
            address=address,
            issuance_date=issuance,
            period_start=period_start,
            period_end=period_end,
            enforcement_kind="contract_suspend",
            punishment_raw=raw_punish,
            reason_summary=reason,
            related_law_ref="北海道開発局工事契約等指名停止等の措置要領",
            houjin_bangou=None,
            source_url=source_url,
        )
    ]


# ---------------------------------------------------------------------------
# 中部地方整備局 (Cbr) Shift_JIS HTML detail pages (Source 3)
# ---------------------------------------------------------------------------

CBR_INDEX_PAGES = [
    ("https://www.cbr.mlit.go.jp/kensei/info/syobun/kensetu-index.html", "営業停止"),
    ("https://www.cbr.mlit.go.jp/kensei/info/syobun/kensetusiji-index.html", "指示"),
]


def fetch_cbr_decoded(http: HttpClient, url: str) -> str:
    """Cbr pages are Shift_JIS. HttpClient.text fallbacks to declared charset
    or utf-8; we explicitly decode as Shift_JIS."""
    res = http.get(url, max_bytes=HTML_MAX)
    if not res.ok or not res.body:
        return ""
    # Try Shift_JIS first
    for enc in ("shift_jis", "cp932", "utf-8"):
        try:
            return res.body.decode(enc)
        except UnicodeDecodeError:
            continue
    return res.body.decode("utf-8", errors="replace")


def find_cbr_detail_links(index_html: str, base_url: str) -> list[str]:
    """Each index page lists detail pages like teishi2016111701.htm or shiji_2016072501.htm"""
    out: list[str] = []
    seen: set[str] = set()
    base = base_url.rsplit("/", 1)[0] + "/"
    for href in re.findall(
        r'<a[^>]+href="([^"]+\.html?)"',
        index_html,
        flags=re.IGNORECASE,
    ):
        if not (href.startswith("teishi") or href.startswith("shiji")):
            continue
        absurl = urllib.parse.urljoin(base, href)
        if absurl in seen:
            continue
        seen.add(absurl)
        out.append(absurl)
    return out


def parse_cbr_detail(html: str, source_url: str) -> list[EnfRow]:
    """Cbr 中部地方整備局 detail page: <table> with 商号又は名称 / 代表者氏名 /
    主たる営業所の所在地 / 許可番号 / 処分の年月日 / 処分の内容 / 違反事実 /
    根拠法令 ..."""
    if not html:
        return []
    # Build dt-like map from <tr>...<th>label</th><td>value</td>...
    fields: dict[str, str] = {}
    for tbl_html in _html_tables(html):
        for cells in _table_rows(tbl_html):
            if len(cells) < 2:
                continue
            label = cells[0].strip()
            value = " / ".join(c.strip() for c in cells[1:] if c.strip())
            if label and value and len(label) < 40:
                fields.setdefault(label, value)

    name = fields.get("商号又は名称") or fields.get("商号") or fields.get("名称")
    if not name:
        return []
    issuance_raw = (
        fields.get("処分の年月日")
        or fields.get("処分年月日")
        or fields.get("処分日")
        or fields.get("処分を行った日")
        or ""
    )
    issuance = parse_first_date(issuance_raw)
    if not issuance:
        # Try whole page
        issuance = parse_first_date(html)
    if not issuance:
        return []

    address = fields.get("主たる営業所の所在地") or fields.get("所在地")
    license_no = fields.get("許可番号")
    license_kinds = fields.get("許可を受けている建設業の種類")
    punishment = (
        fields.get("処分の内容")
        or fields.get("処分内容")
        or ("営業停止" if "teishi" in source_url else "指示")
    )
    reason = (
        fields.get("処分の原因となった事実")
        or fields.get("違反行為の概要")
        or fields.get("違反事実")
    )
    law_ref = fields.get("根拠法令") or fields.get("関係法令") or "建設業法"
    period_start: str | None = None
    period_end: str | None = None
    if "営業停止" in punishment or "停止" in punishment:
        # Period appears in 処分の内容 or in dedicated 期間 field.
        period_field = fields.get("処分の期間") or fields.get("期間") or punishment
        period_dates = all_dates(period_field)
        if len(period_dates) >= 2:
            period_start, period_end = period_dates[0], period_dates[1]

    # Compose reason summary including license info.
    reason_parts = []
    if reason:
        reason_parts.append(reason)
    if license_kinds:
        reason_parts.append(f"許可業種: {license_kinds}")
    if license_no:
        reason_parts.append(f"許可番号: {license_no}")
    summary = " / ".join(reason_parts)[:1500] if reason_parts else None

    return [
        EnfRow(
            org_slug="cbr",
            issuing_authority="中部地方整備局",
            target_name=name,
            address=address,
            issuance_date=issuance,
            period_start=period_start,
            period_end=period_end,
            enforcement_kind=map_kind(punishment),
            punishment_raw=punishment,
            reason_summary=summary,
            related_law_ref=law_ref,
            houjin_bangou=None,
            source_url=source_url,
        )
    ]


# ---------------------------------------------------------------------------
# Single-case PDF parser (Chugoku / Kyushu / Kanto / 中部営業停止 PDF) (Source 4-6)
# ---------------------------------------------------------------------------


@dataclass
class SingleCasePdfSource:
    org_slug: str
    issuing_authority: str
    pdf_url: str
    discovered_date: str | None = None  # ISO; if known from index


def parse_single_case_pdf(
    text: str,
    source: SingleCasePdfSource,
) -> list[EnfRow]:
    """Generic 'press-release style' 指名停止 PDF (1 PDF = 1+ company).

    Layout (Chugoku/Kyushu typical):
        令和X年Y月Z日
        中国地方整備局 (or 九州...)

        指名停止措置について
          中国地方整備局は、〜により〜について指名停止の措置を行いました。

        １．指名停止措置業者名及び住所
            <NAME>      <ADDRESS>
            (multiple lines = multiple companies)

        ２．指名停止措置期間
            令和X年Y月Z日 ～ 令和X年Y月Z日 (Nヵ月)

        ４．事実の概要
            (paragraph...)
        ５．指名停止措置理由
            (paragraph...)
    """
    if not text:
        return []
    issuance = parse_first_date(text[:400]) or source.discovered_date
    if not issuance:
        return []

    # Bail out on requirements/guidelines docs (no 措置 keyword)
    if "措置" not in text or ("指名停止" not in text and "監督処分" not in text):
        return []

    # Extract company section after "業者名" and before "期間".
    section = re.search(
        r"(?:１|1)[\s.．、]+指名停止措置業者名[\s\S]*?\n([\s\S]+?)(?=(?:２|2|３|3)[\s.．、]+指名停止|\n[\s\S]*?指名停止措置の?範囲|\n[\s\S]*?指名停止措置期間)",
        text,
    )
    company_lines: list[tuple[str, str | None]] = []

    # Pattern A (Kyushu/QSR style): single-line "1. 指名停止措置業者名 ： <NAME>" + next line "業者の住所 ： <ADDR>".
    inline = re.search(
        r"指名停止措置業者名\s*[：:]\s*([^\n]+)",
        text,
    )
    if inline:
        cand = inline.group(1).strip()
        # Strip trailing whitespace/colon noise.
        cand = re.split(r"\s{2,}|　", cand)[0].strip()
        if (
            cand
            and len(cand) >= 2
            and any(
                tok in cand
                for tok in (
                    "株式会社",
                    "有限会社",
                    "合同会社",
                    "合資会社",
                    "（株）",
                    "(株)",
                    "（有）",
                    "(有)",
                )
            )
        ):
            addr_match = re.search(r"業\s*者\s*の?\s*住\s*所\s*[：:]\s*([^\n]+)", text)
            addr = None
            if addr_match:
                addr = re.split(r"\s{2,}|　", addr_match.group(1).strip())[0].strip() or None
            company_lines.append((cand, addr))

    # Pattern B (Chugoku/CGR multi-row style): block of name+address lines under header.
    if not company_lines and section:
        block = section.group(1)
        for raw in block.splitlines():
            line = raw.strip()
            if not line:
                continue
            # Skip header repeat lines and numeric markers.
            if line.startswith("指名停止措置業者名") or ("住所" in line and "業者名" in line):
                continue
            if re.match(r"^[1-9０-９一二三四五六七八九]\s*[.．、]?\s*$", line):
                continue
            # Recognize company tokens.
            if not any(
                tok in line
                for tok in (
                    "株式会社",
                    "有限会社",
                    "合同会社",
                    "（株）",
                    "(株)",
                    "（有）",
                    "(有)",
                    "合資会社",
                    "（資）",
                    "（名）",
                )
            ):
                continue
            # Strip leading list-numbering like "1." or "(1)".
            line_clean = re.sub(
                r"^(?:[1-9０-９一二三四五六七八九]\s*[.．、)）]?\s*)+", "", line
            ).strip()
            parts = re.split(r"\s{2,}|　{1,}", line_clean)
            parts = [p.strip() for p in parts if p.strip()]
            if not parts:
                continue
            name = parts[0].strip()
            if name in {"指名停止措置業者名", "業者名", "業者の住所", "住所"}:
                continue
            if re.match(r"^[1-9０-９]\.?$", name):
                continue
            addr = " ".join(parts[1:]).strip() if len(parts) > 1 else None
            company_lines.append((name, addr))

    if not company_lines:
        # Fallback: scan pages for first matching company on its own line.
        for line in text.splitlines():
            if "株式会社" in line or "有限会社" in line:
                line = line.strip()
                if any(tok in line for tok in ("代表", "問合せ", "ホームページ", "電話")):
                    continue
                # Strip leading numbering.
                line = re.sub(
                    r"^(?:[1-9０-９一二三四五六七八九]\s*[.．、)）]?\s*)+", "", line
                ).strip()
                parts = re.split(r"\s{2,}|　{1,}", line)
                parts = [p.strip() for p in parts if p.strip()]
                if (
                    parts
                    and len(parts[0]) >= 2
                    and parts[0] not in {"指名停止措置業者名", "業者名"}
                ):
                    company_lines.append((parts[0], " ".join(parts[1:]) or None))
                    break

    if not company_lines:
        return []

    # Period
    period_start: str | None = None
    period_end: str | None = None
    period_match = re.search(
        r"(?:２|2)[\s.．、]+指名停止措置期間[\s\S]{0,400}?(令和\d+\s*年\s*\d+\s*月\s*\d+\s*日)\s*[～\-~–]+\s*(令和\d+\s*年\s*\d+\s*月\s*\d+\s*日)",
        text,
    )
    if period_match:
        period_start = parse_first_date(period_match.group(1))
        period_end = parse_first_date(period_match.group(2))

    # Reason summary
    reason_parts = []
    sub = re.search(
        r"事\s*実\s*の\s*概\s*要\s*\n([\s\S]+?)(?=(?:５|5)[\s.．、]+|別紙のとおり|＜問い合わせ先＞)",
        text,
    )
    if sub:
        reason_parts.append(re.sub(r"\s+", " ", sub.group(1).strip())[:1200])
    sub = re.search(
        r"指名停止措置理由[\s\S]*?\n([\s\S]+?)(?=＜|【問合せ先】|問い合わせ先|別紙のとおり)", text
    )
    if sub:
        reason_parts.append(re.sub(r"\s+", " ", sub.group(1).strip())[:600])
    reason = " / ".join(reason_parts)[:1500] if reason_parts else None
    if not reason:
        # Fall back to the lead paragraph.
        head = text.split("\n\n")[:5]
        reason = re.sub(r"\s+", " ", " ".join(head))[:1200]

    # Period token in punishment label.
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
# Index discovery for 指名停止 PDFs (Chugoku, Kyushu)
# ---------------------------------------------------------------------------


def discover_qsr_pdfs(http: HttpClient) -> list[SingleCasePdfSource]:
    """Walk 九州地方整備局 fiscal year index pages for individual PDF case links."""
    out: list[SingleCasePdfSource] = []
    seen: set[str] = set()
    for index_url in (
        "https://www.qsr.mlit.go.jp/nyusatu_joho/shimeiteishi/shimeiteishi_r7.html",
        "https://www.qsr.mlit.go.jp/nyusatu_joho/shimeiteishi/shimeiteishi_r6.html",
        "https://www.qsr.mlit.go.jp/nyusatu_joho/shimeiteishi/shimeiteishi_r5.html",
    ):
        res = http.get(index_url, max_bytes=HTML_MAX)
        if not res.ok or not res.body:
            continue
        html = res.text
        base = index_url.rsplit("/", 1)[0] + "/"
        for href in re.findall(r'href="([^"]+\.pdf)"', html, flags=re.IGNORECASE):
            if href.startswith("http"):
                absurl = href
            elif href.startswith("/"):
                absurl = "https://www.qsr.mlit.go.jp" + href
            else:
                absurl = urllib.parse.urljoin(base, href)
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(
                SingleCasePdfSource(
                    org_slug="qsr",
                    issuing_authority="九州地方整備局",
                    pdf_url=absurl,
                )
            )
    return out


def discover_cgr_pdfs(http: HttpClient) -> list[SingleCasePdfSource]:
    """Walk 中国地方整備局 fiscal year index pages."""
    out: list[SingleCasePdfSource] = []
    seen: set[str] = set()
    for index_url in (
        "https://www.cgr.mlit.go.jp/order/sochi/shimeiteisi_2025.html",
        "https://www.cgr.mlit.go.jp/order/sochi/shimeiteisi_2024.html",
        "https://www.cgr.mlit.go.jp/order/sochi/shimeiteisi_2023.html",
    ):
        res = http.get(index_url, max_bytes=HTML_MAX)
        if not res.ok or not res.body:
            continue
        html = res.text
        base = index_url.rsplit("/", 1)[0] + "/"
        for href in re.findall(r'href="([^"]+\.pdf)"', html, flags=re.IGNORECASE):
            if href.startswith("http"):
                absurl = href
            elif href.startswith("/"):
                absurl = "https://www.cgr.mlit.go.jp" + href
            else:
                absurl = urllib.parse.urljoin(base, href)
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(
                SingleCasePdfSource(
                    org_slug="cgr",
                    issuing_authority="中国地方整備局",
                    pdf_url=absurl,
                )
            )
    return out


def discover_ktr_pdfs(http: HttpClient) -> list[SingleCasePdfSource]:
    """関東地方整備局 監督処分 (kensetsu) PDF index."""
    seen: set[str] = set()
    out: list[SingleCasePdfSource] = []
    for index_url in (
        "https://www.ktr.mlit.go.jp/kensan/kensan00000027.html",
        "https://www.ktr.mlit.go.jp/kensan/index00000006.html",
    ):
        res = http.get(index_url, max_bytes=HTML_MAX)
        if not res.ok or not res.body:
            continue
        html = res.text
        for href in re.findall(r'href="([^"]+\.pdf)"', html, flags=re.IGNORECASE):
            if href.startswith("http"):
                absurl = href
            elif href.startswith("/"):
                absurl = "https://www.ktr.mlit.go.jp" + href
            else:
                continue
            if absurl in seen:
                continue
            seen.add(absurl)
            out.append(
                SingleCasePdfSource(
                    org_slug="ktr",
                    issuing_authority="関東地方整備局",
                    pdf_url=absurl,
                )
            )
    return out


def parse_ktr_pdf(text: str, source: SingleCasePdfSource) -> list[EnfRow]:
    """関東地方整備局 監督処分 PDFs are similar press-release style.

    They include:
      - 商号又は名称 / 代表者 / 主たる営業所の所在地 / 許可番号 /
        処分の内容 / 処分の年月日 / 処分の原因となった事実 / 根拠法令
    """
    if not text or "監督処分" not in text and "営業停止" not in text and "指示" not in text:
        return []

    # Try field extraction.
    def field(pat: str) -> str | None:
        m = re.search(pat + r"\s*[：:\s]*([^\n]+)", text)
        return m.group(1).strip() if m else None

    name = field(r"商号又は名称") or field(r"商\s*号") or field(r"処分業者")
    if not name:
        return []
    # Drop trailing ()
    name = name.split("代表者")[0].strip()
    issuance_raw = field(r"処分の?年月日") or text[:200]
    issuance = parse_first_date(issuance_raw)
    if not issuance:
        return []
    address = field(r"主たる営業所の所在地") or field(r"所在地")
    punishment = field(r"処分の?内容") or "監督処分"
    reason = field(r"処分の原因となった事実") or field(r"違反事実")
    law = field(r"根拠法令") or "建設業法"
    period_dates = all_dates(punishment) if punishment else []
    period_start = period_dates[0] if len(period_dates) >= 1 else None
    period_end = period_dates[1] if len(period_dates) >= 2 else None

    return [
        EnfRow(
            org_slug=source.org_slug,
            issuing_authority=source.issuing_authority,
            target_name=name,
            address=address,
            issuance_date=issuance,
            period_start=period_start,
            period_end=period_end,
            enforcement_kind=map_kind(punishment),
            punishment_raw=punishment,
            reason_summary=(reason or "")[:1500] or None,
            related_law_ref=law[:200] if law else None,
            houjin_bangou=None,
            source_url=source.pdf_url,
        )
    ]


# ---------------------------------------------------------------------------
# DB layer
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
    """Load existing (issuing_authority, target_name, issuance_date) tuples."""
    out: set[tuple[str, str, str]] = set()
    for r in conn.execute(
        "SELECT IFNULL(issuing_authority, ''), IFNULL(target_name, ''), issuance_date "
        "FROM am_enforcement_detail"
    ):
        out.add((r[0], r[1], r[2]))
    return out


def insert_row(
    conn: sqlite3.Connection,
    row: EnfRow,
    fetched_at: str,
) -> str:
    """Insert am_entities + am_enforcement_detail. Returns 'insert' | 'skip'."""
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
            "source": "mlit_chiho_pref",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    src_domain = urllib.parse.urlparse(row.source_url).netloc

    cur = conn.execute(
        """INSERT OR IGNORE INTO am_entities (
            canonical_id, record_kind, source_topic, primary_name,
            confidence, source_url, source_url_domain, fetched_at, raw_json
        ) VALUES (?, 'enforcement', 'mlit_chiho_pref', ?, ?, ?, ?, ?, ?)
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--limit", type=int, default=None, help="stop once total inserted reaches this value"
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--sources",
        type=str,
        default="osaka,hkd,cbr,cgr,qsr,ktr",
        help="comma-list of source ids to walk",
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
        s = counters.setdefault(slug, {"fetched": 0, "built": 0, "dup": 0})
        return s

    try:
        # ===== Osaka 大阪府 HTML =====
        if "osaka" in sources:
            for url, fy in OSAKA_FY_URLS:
                _LOG.info("fetching osaka %s %s", fy, url)
                res = http.get(url, max_bytes=HTML_MAX)
                if not res.ok or not res.body:
                    _LOG.warning("osaka fetch fail status=%s url=%s", res.status, url)
                    continue
                stat("osaka-pref")["fetched"] += 1
                rows = parse_osaka_fy_page(res.text, url)
                stat("osaka-pref")["built"] += len(rows)
                _LOG.info("osaka %s parsed=%d", fy, len(rows))
                for r in rows:
                    key = (r.issuing_authority, r.target_name, r.issuance_date)
                    if key in dedup:
                        stat("osaka-pref")["dup"] += 1
                        continue
                    dedup.add(key)
                    pending.append(r)
                    if args.limit and len(pending) >= args.limit:
                        break
                if args.limit and len(pending) >= args.limit:
                    break

        # ===== Hokkaido 開発局 PDFs =====
        if "hkd" in sources and (not args.limit or len(pending) < args.limit):
            for index_url in HKD_INDEX_PAGES:
                _LOG.info("fetching hkd index %s", index_url)
                res = http.get(index_url, max_bytes=HTML_MAX)
                if not res.ok or not res.body:
                    continue
                pdf_urls = find_hkd_pdf_links(res.text, index_url)
                _LOG.info("hkd %s found %d PDFs", index_url, len(pdf_urls))
                for pu in pdf_urls:
                    if args.limit and len(pending) >= args.limit:
                        break
                    pres = http.get(pu, max_bytes=PDF_MAX)
                    if not pres.ok or not pres.body:
                        continue
                    stat("hkd")["fetched"] += 1
                    text = _pdftotext(pres.body)
                    rows = parse_hkd_pdf(text, pu)
                    stat("hkd")["built"] += len(rows)
                    for r in rows:
                        key = (r.issuing_authority, r.target_name, r.issuance_date)
                        if key in dedup:
                            stat("hkd")["dup"] += 1
                            continue
                        dedup.add(key)
                        pending.append(r)
                if args.limit and len(pending) >= args.limit:
                    break

        # ===== 中部地方整備局 (Cbr) Shift_JIS HTML =====
        if "cbr" in sources and (not args.limit or len(pending) < args.limit):
            for index_url, _label in CBR_INDEX_PAGES:
                index_html = fetch_cbr_decoded(http, index_url)
                if not index_html:
                    continue
                detail_urls = find_cbr_detail_links(index_html, index_url)
                _LOG.info("cbr %s found %d detail pages", index_url, len(detail_urls))
                for du in detail_urls:
                    if args.limit and len(pending) >= args.limit:
                        break
                    detail_html = fetch_cbr_decoded(http, du)
                    if not detail_html:
                        continue
                    stat("cbr")["fetched"] += 1
                    rows = parse_cbr_detail(detail_html, du)
                    stat("cbr")["built"] += len(rows)
                    for r in rows:
                        key = (r.issuing_authority, r.target_name, r.issuance_date)
                        if key in dedup:
                            stat("cbr")["dup"] += 1
                            continue
                        dedup.add(key)
                        pending.append(r)
                if args.limit and len(pending) >= args.limit:
                    break

        # ===== 中国地方整備局 (Cgr) PDFs =====
        if "cgr" in sources and (not args.limit or len(pending) < args.limit):
            cgr_pdfs = discover_cgr_pdfs(http)
            _LOG.info("cgr found %d PDFs", len(cgr_pdfs))
            for src in cgr_pdfs:
                if args.limit and len(pending) >= args.limit:
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("cgr")["fetched"] += 1
                text = _pdftotext(pres.body)
                rows = parse_single_case_pdf(text, src)
                stat("cgr")["built"] += len(rows)
                for r in rows:
                    key = (r.issuing_authority, r.target_name, r.issuance_date)
                    if key in dedup:
                        stat("cgr")["dup"] += 1
                        continue
                    dedup.add(key)
                    pending.append(r)

        # ===== 九州地方整備局 (Qsr) PDFs =====
        if "qsr" in sources and (not args.limit or len(pending) < args.limit):
            qsr_pdfs = discover_qsr_pdfs(http)
            _LOG.info("qsr found %d PDFs", len(qsr_pdfs))
            for src in qsr_pdfs:
                if args.limit and len(pending) >= args.limit:
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("qsr")["fetched"] += 1
                text = _pdftotext(pres.body)
                rows = parse_single_case_pdf(text, src)
                stat("qsr")["built"] += len(rows)
                for r in rows:
                    key = (r.issuing_authority, r.target_name, r.issuance_date)
                    if key in dedup:
                        stat("qsr")["dup"] += 1
                        continue
                    dedup.add(key)
                    pending.append(r)

        # ===== 関東地方整備局 (Ktr) PDFs =====
        if "ktr" in sources and (not args.limit or len(pending) < args.limit):
            ktr_pdfs = discover_ktr_pdfs(http)
            _LOG.info("ktr found %d PDFs", len(ktr_pdfs))
            for src in ktr_pdfs:
                if args.limit and len(pending) >= args.limit:
                    break
                pres = http.get(src.pdf_url, max_bytes=PDF_MAX)
                if not pres.ok or not pres.body:
                    continue
                stat("ktr")["fetched"] += 1
                text = _pdftotext(pres.body)
                rows = parse_ktr_pdf(text, src)
                stat("ktr")["built"] += len(rows)
                for r in rows:
                    key = (r.issuing_authority, r.target_name, r.issuance_date)
                    if key in dedup:
                        stat("ktr")["dup"] += 1
                        continue
                    dedup.add(key)
                    pending.append(r)

    finally:
        http.close()

    _LOG.info("queued=%d (per_source=%s)", len(pending), counters)

    if args.dry_run:
        for r in pending[:5]:
            _LOG.info(
                "DRY %s | %s | %s | %s | %s",
                r.issuing_authority,
                r.issuance_date,
                r.target_name,
                r.punishment_raw[:40],
                r.enforcement_kind,
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
            for slug_label, auth in [
                ("osaka-pref", "大阪府"),
                ("hkd", "北海道開発局"),
                ("cbr", "中部地方整備局"),
                ("cgr", "中国地方整備局"),
                ("qsr", "九州地方整備局"),
                ("ktr", "関東地方整備局"),
            ]:
                n = c0.execute(
                    "SELECT COUNT(*) FROM am_enforcement_detail "
                    "WHERE issuing_authority = ? AND entity_id LIKE ?",
                    (auth, f"enforcement:mlit-local:{slug_label}:%"),
                ).fetchone()[0]
                breakdown_q.append((slug_label, n))
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
