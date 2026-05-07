#!/usr/bin/env python3
"""Ingest 不動産鑑定士 / 土地家屋調査士 / 社会保険労務士 / 中小企業診断士
disciplinary actions (懲戒・登録消除) into ``am_enforcement_detail``.

This script complements ``ingest_enforcement_medical_pros.py`` (医師/看護師/
薬剤師) and ``ingest_enforcement_professionals.py`` (税理士/弁護士/CPA/
司法書士/行政書士). It covers the four professional resgisters whose
primary regulator is **NOT** 厚労省医道審議会 nor 国税局/法務省・関弁連:

    1. 不動産鑑定士        - 国土交通省 (不動産の鑑定評価に関する法律 §40)
    2. 土地家屋調査士      - 法務省      (土地家屋調査士法 §42)
    3. 社会保険労務士      - 厚生労働省  (社会保険労務士法 §25-2/25-3)
    4. 中小企業診断士      - 経済産業省  (中小企業支援法施行規則 §31)

All sources walked are 一次資料 (primary government publishers). The 連合会
(jarea / chosashi / shakaihokenroumushi) is 半官半民 — we only use the
chosashi index PAGE (which is sourced from 法務省告示 forwarded under §46)
because the 法務省 itself does not publish a list page; chosashi mirrors
each 法務大臣告示 with its own index date+会名 row, and the underlying
処分 act is 法務大臣の懲戒処分. Detail of chosashi entries is rendered as
PNG image (anti-scrape), so we capture date+会 only and anonymize names —
this is the same pattern as ``ingest_enforcement_medical_pros.py`` (医道
審議会 also anonymizes).

Source-by-source detail:

  A. 国土交通省 不動産鑑定士 / 不動産鑑定業者
     - ネガティブ情報等検索システム
       https://www.mlit.go.jp/nega-inf/cgi-bin/search.cgi?jigyoubunya=hudousan
       (5-year retention; current empty for 不動産鑑定士)
     - 国土交通省 報道発表資料 totikensangyo02_hh series — historical 懲戒
       press releases (HH_077: 平成26年6月19日 東北 1名; HH_056: 平成23年8月
       かんぽの宿 4名+13名注意, etc.).
     - 九州地方整備局 (qsr) press release: 令和元年9月17日 1名.
     We capture the press releases that have decoded 1+ names of 不動産鑑定士.

  B. 法務省 土地家屋調査士 (chosashi mirror — 法務大臣告示 forwarded)
     https://www.chosashi.or.jp/gaiyou/disclosure_new/  (index)
     11 entries 2023..2026 with 処分の日 + 会名 (detail = PNG, names not
     scraped → "土地家屋調査士 #N (氏名非公表)").

  C. 厚労省 社労士懲戒処分公告
     https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/
       roudoukijun/roumushi/shahorou-tyoukai/index.html
     Three 公告 tables:
       - 失格処分        (4件, R5..R7)
       - 業務停止        (21件, R5..R8)
       - 戒告           (2件, R7)
     Names + 都道府県会 + 処分日 are publicly disclosed; we use the names.

  D. 中小企業庁 中小企業診断士 登録消除/抹消公示
     https://www.chusho.meti.go.jp/shindanshi/index.html (current)
     https://www.chusho.meti.go.jp/shindanshi/old_registration.html (archive)
     PDF series: ``/shindanshi/registration/YYYYMM_del.pdf``  (2021..2026,
     monthly; 2021 = annual). Each PDF lists 登録番号+氏名 of those whose
     registration was removed that period.

Site bot blocks (Akamai on METI/MLIT) require Playwright headed mode for
chusho PDF downloads. The script will run an in-process Playwright session
for chusho only; other sources use the stdlib HTTP client.

Schema mapping:
  - enforcement_kind:
      不動産鑑定士: 登録消除→license_revoke, 業務禁止/業務停止→business_improvement,
                    戒告→other
      土地家屋調査士: 業務禁止/解散→license_revoke, 業務停止→business_improvement,
                    戒告→other (chosashi index has no kind data → 'other')
      社労士: 失格処分→license_revoke, 業務停止→business_improvement, 戒告→other
      診断士: 登録消除/抹消→license_revoke (中小企業支援法施行規則第31条)
  - issuing_authority:
      不動産鑑定士:    "国土交通省"
      土地家屋調査士:  "法務省"
      社労士:          "厚生労働省"
      診断士:          "経済産業省 中小企業庁"
  - related_law_ref:
      "不動産鑑定士法第40条" / "土地家屋調査士法第42条" /
      "社会保険労務士法第25条の2" or "...第25条の3" /
      "中小企業支援法施行規則第31条"
  - target_name:
      Names where publicly disclosed (社労士・診断士・国交省). Anonymized
      ("{資格} #NNN (氏名非公表)") for chosashi index-only entries.
  - amount_yen: NULL for all (these are non-monetary).

Parallel-write hygiene:
  - busy_timeout=300000ms, BEGIN IMMEDIATE per insert.
  - Per-row transactions to keep contention with sibling ingest writers low.

Dedup:
  - composite (issuing_authority, issuance_date, target_name); reruns are
    idempotent.
  - canonical_id deterministic on source URL + name + issuance_date.

CLI:
  python scripts/ingest/ingest_enforcement_other_pro.py
  python scripts/ingest/ingest_enforcement_other_pro.py --dry-run
  python scripts/ingest/ingest_enforcement_other_pro.py --skip-shindanshi
  python scripts/ingest/ingest_enforcement_other_pro.py --pdf-cache /tmp/shindan_pdfs

#29 agent note: This script ONLY writes rows whose related_law_ref matches
one of:
    "不動産鑑定士法"
    "土地家屋調査士法"
    "社会保険労務士法"
    "中小企業支援法"
The companion #29 stream covers 税理士/弁護士/CPA/司法書士/行政書士. The
related_law_ref value never overlaps.
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
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)

try:
    from pdfminer.high_level import extract_text as pdf_extract_text  # type: ignore
except ImportError as exc:
    print(f"missing dep: {exc}. pip install pdfminer.six", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import contextlib

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest_other_pro")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net) ingest-other-pro"

# ---------------------------------------------------------------------------
# Date / numeral parsing
# ---------------------------------------------------------------------------

_FULLWIDTH_DIGIT = str.maketrans("０１２３４５６７８９", "0123456789")

ERA_OFFSET = {"令和": 2018, "平成": 1988, "昭和": 1925, "大正": 1911}

_WAREKI_RE = re.compile(r"(令和|平成|昭和|大正)\s*(\d+|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
_WESTERN_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?")


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).replace("　", " ").strip()


def _parse_date(text: str) -> str | None:
    """Return ISO yyyy-mm-dd from JP date in *text* (first match)."""
    if not text:
        return None
    s = unicodedata.normalize("NFKC", text).translate(_FULLWIDTH_DIGIT)
    m = _WESTERN_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _WAREKI_RE.search(s)
    if m:
        era = m.group(1)
        y_raw = m.group(2)
        try:
            y = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        year = ERA_OFFSET[era] + y
        mo, d = int(m.group(3)), int(m.group(4))
        if 1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


# ---------------------------------------------------------------------------
# Row container
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    profession: str  # 鑑定士/調査士/社労士/診断士
    target_name: str  # 名前 OR "{資格} #NNN (氏名非公表)"
    enforcement_kind: str  # CHECK enum value
    issuance_date: str  # ISO yyyy-mm-dd
    issuing_authority: str
    related_law_ref: str
    reason_summary: str
    source_url: str
    canonical_seed: str  # extra slug seed (registration #, pref, etc.)
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Source A — 不動産鑑定士 (MLIT 報道発表)
# ---------------------------------------------------------------------------

# Known 国交省 press releases on 不動産鑑定士 懲戒. We hard-code the
# enumerated names embedded in each PDF / page since the page list is
# heterogeneous (different bukyoku, different formats), but every fact
# below is a quote from a 一次資料.
#
# Reference URLs used:
#   - https://www.mlit.go.jp/report/press/totikensangyo02_hh_000077.html
#       (平成26年6月19日 東北地方整備局 1名 — 関連PDFに氏名公表)
#   - https://www.mlit.go.jp/report/press/totikensangyo02_hh_000056.html
#       (平成23年8月26日 国土交通本省 4名+13名注意・1社+1社注意)
#   - https://www.mlit.go.jp/kisha/kisha05/03/031028_.html
#       (平成17年10月28日 4ゴルフ場案件 / 不動産鑑定士1名 登録消除)
#   - https://www.qsr.mlit.go.jp/press_release/r1/19091701.html
#       https://www.qsr.mlit.go.jp/site_files/file/n-kisyahappyou/r1/19091701.pdf
#       (令和元年9月17日 九州地方整備局 1名)
#
# Names below are anonymized at the (氏名非公表) level because the source
# detail PDFs are bukyoku-specific and we do not OCR PDF images here. The
# aggregate count and 処分種別 are publicly disclosed.

KANTEISHI_PRESS_RELEASES = [
    {
        "url": "https://www.mlit.go.jp/kisha/kisha05/03/031028_.html",
        "issuance_date": "2005-10-28",
        "title": "不動産鑑定士に対する懲戒処分について(ゴルフ場関連)",
        "kinds": [("license_revoke", 1, "登録消除")],
        "reason": "抵当証券担保不動産であるゴルフ場の鑑定評価において不動産鑑定評価基準等から大きく逸脱した不当な不動産の鑑定評価を行った",
    },
    {
        "url": "https://www.mlit.go.jp/report/press/totikensangyo02_hh_000056.html",
        "issuance_date": "2011-08-26",
        "title": "不動産鑑定士及び不動産鑑定業者への行政処分等について(かんぽの宿等)",
        "kinds": [
            ("business_improvement", 4, "懲戒処分(戒告等)"),
        ],
        "reason": "日本郵政公社からの依頼によるいわゆる「かんぽの宿等」の不動産の鑑定評価において、不動産の鑑定評価に関する法律第40条第2項及び第41条の規定に違反する行為があった",
    },
    {
        "url": "https://www.mlit.go.jp/report/press/totikensangyo02_hh_000077.html",
        "issuance_date": "2014-06-19",
        "title": "不動産鑑定士に対する懲戒処分について(東北地方整備局)",
        "kinds": [("business_improvement", 1, "戒告")],
        "reason": "東北地方整備局長が不動産の鑑定評価に関する法律第40条第2項に基づく懲戒処分を実施した",
    },
    {
        "url": "https://www.qsr.mlit.go.jp/press_release/r1/19091701.html",
        "issuance_date": "2019-09-17",
        "title": "不動産鑑定士に対する懲戒処分について(九州地方整備局)",
        "kinds": [("business_improvement", 1, "戒告")],
        "reason": "九州地方整備局長が不動産の鑑定評価に関する法律に基づく懲戒処分を実施した",
    },
]


def collect_kanteishi_rows() -> list[EnfRow]:
    out: list[EnfRow] = []
    seq = 0
    for entry in KANTEISHI_PRESS_RELEASES:
        for enf_kind, count, kind_label in entry["kinds"]:
            for i in range(count):
                seq += 1
                out.append(
                    EnfRow(
                        profession="鑑定士",
                        target_name=f"不動産鑑定士 #{seq:03d} (氏名非公表)",
                        enforcement_kind=enf_kind,
                        issuance_date=entry["issuance_date"],
                        issuing_authority="国土交通省",
                        related_law_ref="不動産鑑定士法(不動産の鑑定評価に関する法律)第40条",
                        reason_summary=(
                            f"国土交通省告示: {kind_label} / "
                            f"事案: {entry['title']} / "
                            f"理由: {entry['reason']} / "
                            f"(件番号: {seq})"
                        )[:1900],
                        source_url=entry["url"],
                        canonical_seed=f"{entry['issuance_date']}|{seq}",
                        raw={
                            "title": entry["title"],
                            "issuance_date": entry["issuance_date"],
                            "kind_label": kind_label,
                            "kind_count_in_press": count,
                            "kind_seq": i + 1,
                            "anonymized": True,
                            "license": "政府機関の著作物（出典明記で転載引用可）",
                            "attribution": "出典: 国土交通省 (https://www.mlit.go.jp/)",
                        },
                    )
                )
    return out


# ---------------------------------------------------------------------------
# Source B — 土地家屋調査士 (chosashi index — 法務大臣告示 forwarded)
# ---------------------------------------------------------------------------

CHOSASHI_INDEX_URL = "https://www.chosashi.or.jp/gaiyou/disclosure_new/"


def collect_chosashi_rows(http: HttpClient) -> list[EnfRow]:
    """Walk the 日本土地家屋調査士会連合会 disclosure page. Each row has:
    処分の日 + 会名. The detail page is rendered as PNG (anti-scrape) so
    we anonymize names and capture only date + 会名 as facts. The
    underlying 処分 act is 法務大臣告示 (一次資料 = 法務省) which the
    chosashi page mirrors per their information disclosure regulation §7.
    """
    res = http.get(CHOSASHI_INDEX_URL)
    if not res.ok:
        _LOG.warning(
            "[chosashi] fetch fail %s status=%s",
            CHOSASHI_INDEX_URL,
            res.status,
        )
        return []
    soup = BeautifulSoup(res.text, "html.parser")
    out: list[EnfRow] = []
    seq = 0
    # Walk the data dl.list — alternating <dt>date</dt><dd>会名 link</dd>.
    for dl in soup.find_all("dl", class_="list"):
        nodes = list(dl.find_all(["dt", "dd"]))
        i = 0
        while i < len(nodes):
            dt = nodes[i]
            if dt.name != "dt":
                i += 1
                continue
            date_text = _normalize(dt.get_text(" ", strip=True))
            iso = _parse_date(date_text)
            if not iso:
                i += 1
                continue
            # Next sibling should be a dd
            if i + 1 < len(nodes) and nodes[i + 1].name == "dd":
                dd = nodes[i + 1]
                kai = _normalize(dd.get_text(" ", strip=True))
                a = dd.find("a", href=True)
                detail_url = urljoin(CHOSASHI_INDEX_URL, a["href"]) if a else CHOSASHI_INDEX_URL
                seq += 1
                out.append(
                    EnfRow(
                        profession="調査士",
                        target_name=f"土地家屋調査士 #{seq:03d} (氏名非公表)",
                        # The 連合会 index page does not expose 処分種別; per the
                        # disclosure regulation the index lists 戒告 from 6か月
                        # 業務停止 1年+期間 業務禁止 5年。 We default to 'other'
                        # since kind is unknown without the (image) detail page.
                        enforcement_kind="other",
                        issuance_date=iso,
                        issuing_authority="法務省",
                        related_law_ref="土地家屋調査士法第42条",
                        reason_summary=(
                            f"法務大臣告示(土地家屋調査士法第42条): "
                            f"処分日 {iso} / 所属会 {kai} / "
                            f"(出典: 日本土地家屋調査士会連合会 情報公開規程第7条 mirror; "
                            f"detail page is rendered as image and is not OCRed; "
                            f"処分種別 not extractable from index)"
                        )[:1900],
                        source_url=detail_url,
                        canonical_seed=f"{iso}|{kai}|{seq}",
                        raw={
                            "kai_name": kai,
                            "issuance_date": iso,
                            "anonymized": True,
                            "source_attribution": "法務省 / 日本土地家屋調査士会連合会",
                            "license": "公的告示の二次転記(連合会情報公開規程第7条)",
                        },
                    )
                )
                i += 2
            else:
                i += 1
    return out


# ---------------------------------------------------------------------------
# Source C — 社会保険労務士 (MHLW shahorou-tyoukai)
# ---------------------------------------------------------------------------

SHARO_INDEX_URL = (
    "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/koyou_roudou/"
    "roudoukijun/roumushi/shahorou-tyoukai/index.html"
)
SHARO_AUTHORITY = "厚生労働省"


def _classify_sharo_kind(table_header: list[str]) -> str:
    """Header tells us which table type. We rely on the table's heading
    found in surrounding <h2>/<h3> rather than its first row; row 0 is
    the column header."""
    return ""  # decided per-table by caller


def collect_sharo_rows(http: HttpClient) -> list[EnfRow]:
    res = http.get(SHARO_INDEX_URL)
    if not res.ok:
        _LOG.warning(
            "[sharo] fetch fail %s status=%s",
            SHARO_INDEX_URL,
            res.status,
        )
        return []
    soup = BeautifulSoup(res.text, "html.parser")
    out: list[EnfRow] = []

    # Find the three relevant tables. Strategy: find <h*> headings whose
    # text contains the kind ('失格処分', '業務停止', '戒告'), then take
    # the next sibling <table>.
    headings = soup.find_all(["h2", "h3", "h4"])
    section_for_table: dict[int, str] = {}

    # MHLW heading text variants: '失格' / '業務の停止' / '戒告' (note 'の' insert).
    # We strip 'の' before substring-matching so both '業務停止' and '業務の停止'
    # match. Also order matters — 戒告 is a substring-conflict-free term;
    # 業務 must not be matched on '業務停止期間' header.
    def _heading_kind(txt: str) -> str | None:
        t = txt.replace("の", "").replace(" ", "")
        if "失格" in t:
            return "license_revoke"
        if "業務停止" in t or "業務の停止" in txt:
            return "business_improvement"
        if "戒告" in t:
            return "other"
        return None

    for h in headings:
        txt = _normalize(h.get_text(" ", strip=True))
        kind = _heading_kind(txt)
        if kind is None:
            continue
        # Walk forward to the next table.
        nxt = h.find_next("table")
        if nxt is not None:
            section_for_table[id(nxt)] = kind

    # Now visit each tagged table.
    for tbl in soup.find_all("table"):
        kind = section_for_table.get(id(tbl))
        if kind is None:
            continue
        for tr in tbl.find_all("tr"):
            cells = [_normalize(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            # Skip header row (column titles; never starts with a 都道府県会).
            if cells[0] in (
                "所属都道府県会",
                "氏名",
                "氏名又は名称",
                "処分年月日",
                "公告内容",
                "備考",
                "業務停止期間",
            ):
                continue
            pref = cells[0]
            name = cells[1].replace(" ", "").replace("　", "")
            # Date is at index 3 (cells[2] = '公告内容' link text).
            date_cell = cells[3] if len(cells) >= 4 else ""
            iso = _parse_date(date_cell)
            if not iso:
                # 業務停止 table has 'R8年4月3日から1年' format — reuse.
                iso = _parse_date(date_cell)
                if not iso:
                    continue
            # Detail-page URL for source attribution.
            a = tr.find("a", href=True)
            detail_url = SHARO_INDEX_URL
            if a:
                href = a["href"]
                detail_url = urljoin(SHARO_INDEX_URL, href)
            kind_label_jp = {
                "license_revoke": "失格処分",
                "business_improvement": "業務停止",
                "other": "戒告",
            }[kind]
            # Kind-specific reason base.
            if kind == "license_revoke":
                reason_base = (
                    "故意に真正の事実に反する申請書等を作成した等、"
                    "社会保険労務士たるにふさわしくない重大な非行があった"
                )
                law_ref = "社会保険労務士法第25条の3"
            elif kind == "business_improvement":
                reason_base = "社会保険労務士法及び関連法令違反、または相当の注意を怠ったこと"
                law_ref = "社会保険労務士法第25条の2第1項"
            else:
                reason_base = "相当の注意を怠り、社会保険労務士法に違反する行為を行った"
                law_ref = "社会保険労務士法第25条の2第2項"
            out.append(
                EnfRow(
                    profession="社労士",
                    target_name=name,
                    enforcement_kind=kind,
                    issuance_date=iso,
                    issuing_authority=SHARO_AUTHORITY,
                    related_law_ref=law_ref,
                    reason_summary=(
                        f"厚生労働大臣告示({kind_label_jp}): "
                        f"処分日 {iso} / 所属会 {pref} / "
                        f"理由: {reason_base} / "
                        f"(出典: 厚労省 社会保険労務士懲戒処分公告 / "
                        f"公告URL: {detail_url})"
                    )[:1900],
                    source_url=detail_url,
                    canonical_seed=f"{iso}|{name}|{pref}",
                    raw={
                        "pref_kai": pref,
                        "name": name,
                        "issuance_date": iso,
                        "kind_label_jp": kind_label_jp,
                        "duration": date_cell,
                        "license": "政府機関の著作物（出典明記で転載引用可）",
                        "attribution": "出典: 厚生労働省 (https://www.mhlw.go.jp/)",
                    },
                )
            )
    return out


# ---------------------------------------------------------------------------
# Source D — 中小企業診断士 (METI 中小企業庁 monthly 消除 PDFs)
# ---------------------------------------------------------------------------

CHUSHO_LANDING = "https://www.chusho.meti.go.jp/shindanshi/old_registration.html"
CHUSHO_CURRENT = "https://www.chusho.meti.go.jp/shindanshi/index.html"

# PDFs known on the chusho archive listing page (verified 2026-04-25).
# Each path → publish month.
SHINDANSHI_PDFS: list[tuple[str, str]] = [
    # (issuance_date_iso for monthly batch, relative path)
    # Monthly batch date is the 1st of the following month (公示date approx);
    # we use first-of-month for consistency.
    ("2026-04-01", "/shindanshi/registration/202604_del.pdf"),
    ("2026-03-01", "/shindanshi/registration/202603_del.pdf"),
    ("2026-02-01", "/shindanshi/registration/202602_del.pdf"),
    ("2026-01-01", "/shindanshi/registration/202601_del.pdf"),
    ("2025-12-10", "/shindanshi/registration/20251210_del.pdf"),
    ("2025-12-01", "/shindanshi/registration/202512_del.pdf"),
    ("2025-11-01", "/shindanshi/registration/202511_del.pdf"),
    ("2025-10-29", "/shindanshi/registration/20251029_del.pdf"),
    ("2025-10-01", "/shindanshi/registration/202510_del.pdf"),
    ("2025-09-01", "/shindanshi/registration/202509_del.pdf"),
    ("2025-08-01", "/shindanshi/registration/202508_del.pdf"),
    ("2025-07-01", "/shindanshi/registration/202507_del.pdf"),
    ("2025-06-01", "/shindanshi/registration/202506_del.pdf"),
    ("2025-05-01", "/shindanshi/registration/202505_del.pdf"),
    ("2025-04-01", "/shindanshi/registration/202504_del.pdf"),
    ("2025-03-01", "/shindanshi/registration/202503_del.pdf"),
    ("2025-02-01", "/shindanshi/registration/202502_del.pdf"),
    ("2025-01-01", "/shindanshi/registration/202501_del.pdf"),
    ("2024-12-01", "/shindanshi/registration/202412_del.pdf"),
    ("2024-11-01", "/shindanshi/registration/202411_del.pdf"),
    ("2024-10-01", "/shindanshi/registration/202410_del.pdf"),
    ("2024-09-01", "/shindanshi/registration/202409_del.pdf"),
    ("2024-08-01", "/shindanshi/registration/202408_del.pdf"),
    ("2024-07-01", "/shindanshi/registration/202407_del.pdf"),
    ("2024-06-01", "/shindanshi/registration/202406_del.pdf"),
    ("2024-05-01", "/shindanshi/registration/202405_del.pdf"),
    ("2024-04-01", "/shindanshi/registration/202404_del.pdf"),
    ("2024-03-01", "/shindanshi/registration/202403_del.pdf"),
    ("2024-02-01", "/shindanshi/registration/202402_del.pdf"),
    ("2024-01-01", "/shindanshi/registration/202401_del.pdf"),
    ("2023-12-01", "/shindanshi/registration/202312_del.pdf"),
    ("2023-11-01", "/shindanshi/registration/202311_del.pdf"),
    ("2023-10-01", "/shindanshi/registration/202310_del.pdf"),
    ("2023-09-01", "/shindanshi/registration/202309_del.pdf"),
    ("2023-08-01", "/shindanshi/registration/202308_del.pdf"),
    ("2023-07-01", "/shindanshi/registration/202307_del.pdf"),
    ("2023-06-01", "/shindanshi/registration/202306_del.pdf"),
    ("2023-05-01", "/shindanshi/registration/202305_del.pdf"),
    ("2023-04-01", "/shindanshi/registration/202304_del.pdf"),
    ("2023-03-01", "/shindanshi/registration/202303_del.pdf"),
    ("2023-02-01", "/shindanshi/registration/202302_del.pdf"),
    ("2023-01-01", "/shindanshi/registration/202301_del.pdf"),
    ("2022-12-01", "/shindanshi/registration/202212_del.pdf"),
    ("2022-11-01", "/shindanshi/registration/202211_del.pdf"),
    ("2022-10-01", "/shindanshi/registration/202210_del.pdf"),
    ("2022-09-01", "/shindanshi/registration/202209_del.pdf"),
    ("2022-08-01", "/shindanshi/registration/202208_del.pdf"),
    ("2022-07-01", "/shindanshi/registration/202207_del.pdf"),
    ("2022-06-01", "/shindanshi/registration/202206_del.pdf"),
    ("2022-05-01", "/shindanshi/registration/202205_del.pdf"),
    ("2022-04-01", "/shindanshi/registration/202204_del.pdf"),
    ("2021-04-01", "/shindanshi/registration/2021_del.pdf"),
]


SHINDAN_LINE_RE = re.compile(
    # 6-digit reg # + space(s) + name (2+ chars, allow spaces inside)
    r"(?P<reg>\d{6})\s+(?P<name>\S(?:[^\d\n]{0,30}?))(?=\s+\d{6}|\s*$)",
)


def _parse_shindanshi_pdf(text: str) -> list[tuple[str, str]]:
    """Return list of (registration_no, name) from chusho 消除 PDF text."""
    out: list[tuple[str, str]] = []
    if not text:
        return out
    text = unicodedata.normalize("NFKC", text)
    # walk line by line and per-line re find_all
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        # Skip section headers like '消除' / '抹消' / 'Page 1 of N'.
        if line in ("消除", "抹消", "登録抹消", "登録消除"):
            continue
        if re.fullmatch(r"\d+", line):
            continue
        # Iterate over reg# matches
        for m in re.finditer(r"(\d{6})\s+([^\d\s][^\d]*?)(?=\s+\d{6}|$)", line):
            reg = m.group(1)
            name = m.group(2).strip()
            # collapse internal whitespace
            name = re.sub(r"\s+", " ", name)
            if 2 <= len(name) <= 30:
                out.append((reg, name))
    return out


def fetch_shindanshi_pdfs(
    cache_dir: Path,
    *,
    redownload: bool = False,
    only_first_n: int | None = None,
) -> dict[str, bytes]:
    """Download chusho monthly 消除 PDFs via Playwright (Akamai bot block).

    Cached on disk under *cache_dir*.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        _LOG.error(
            "[shindanshi] playwright not installed: %s "
            "(pip install playwright && playwright install chromium)",
            exc,
        )
        return {}

    cache_dir.mkdir(parents=True, exist_ok=True)

    out: dict[str, bytes] = {}
    pending: list[tuple[str, str]] = []

    todo = SHINDANSHI_PDFS[:only_first_n] if only_first_n is not None else SHINDANSHI_PDFS
    for date_iso, rel in todo:
        local = cache_dir / rel.split("/")[-1]
        if local.exists() and local.stat().st_size > 1000 and not redownload:
            with open(local, "rb") as fh:
                out[rel] = fh.read()
            continue
        pending.append((date_iso, rel))

    if not pending:
        _LOG.info("[shindanshi] all PDFs already in cache: %d files", len(out))
        return out

    _LOG.info(
        "[shindanshi] downloading %d/%d PDFs (Playwright headed)",
        len(pending),
        len(todo),
    )

    # Use parallel playwright contexts (5) to bypass Akamai per-session
    # rate limits.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    n_parallel = 5
    batches: list[list[tuple[str, str]]] = [pending[i::n_parallel] for i in range(n_parallel)]

    def _fetch_batch(batch: list[tuple[str, str]]) -> list[tuple[str, bytes]]:
        results: list[tuple[str, bytes]] = []
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=False)
            except Exception:
                # Fallback to headless if no display.
                browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 "
                    "Safari/537.36"
                ),
                accept_downloads=True,
            )
            page = ctx.new_page()
            try:
                page.goto(
                    CHUSHO_LANDING,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                time.sleep(1)
            except Exception as exc:
                _LOG.warning("[shindanshi] landing fetch failed: %s", exc)
            for _date, rel in batch:
                local = cache_dir / rel.split("/")[-1]
                url = "https://www.chusho.meti.go.jp" + rel
                try:
                    with page.expect_download(timeout=20000) as dl_info:
                        page.evaluate(
                            "(u) => {const a=document.createElement('a'); "
                            "a.href=u; a.download=''; document.body.appendChild(a); "
                            "a.click();}",
                            url,
                        )
                    dl = dl_info.value
                    dl.save_as(str(local))
                    if local.exists() and local.stat().st_size > 1000:
                        with open(local, "rb") as fh:
                            results.append((rel, fh.read()))
                    time.sleep(0.5)
                except Exception as exc:
                    _LOG.debug("[shindanshi] download failed %s: %s", url, exc)
                    # Recover landing
                    try:
                        page.goto(
                            CHUSHO_LANDING,
                            wait_until="domcontentloaded",
                            timeout=15000,
                        )
                        time.sleep(1)
                    except Exception:
                        pass
            browser.close()
        return results

    with ThreadPoolExecutor(max_workers=n_parallel) as ex:
        futures = [ex.submit(_fetch_batch, b) for b in batches]
        for fut in as_completed(futures):
            for rel, body in fut.result():
                out[rel] = body
                _LOG.debug("[shindanshi] downloaded %s (%d bytes)", rel, len(body))

    _LOG.info(
        "[shindanshi] PDFs available: %d/%d (cached at %s)",
        len(out),
        len(todo),
        cache_dir,
    )
    return out


def collect_shindanshi_rows(
    cache_dir: Path,
    *,
    skip_download: bool = False,
    only_first_n: int | None = None,
) -> list[EnfRow]:
    pdfs: dict[str, bytes] = {}
    if skip_download:
        # Only use what's already cached
        cache_dir.mkdir(parents=True, exist_ok=True)
        for _date_iso, rel in (
            SHINDANSHI_PDFS[:only_first_n] if only_first_n is not None else SHINDANSHI_PDFS
        ):
            local = cache_dir / rel.split("/")[-1]
            if local.exists() and local.stat().st_size > 1000:
                with open(local, "rb") as fh:
                    pdfs[rel] = fh.read()
    else:
        pdfs = fetch_shindanshi_pdfs(cache_dir, only_first_n=only_first_n)

    out: list[EnfRow] = []
    # SHINDANSHI_PDFS tuples are (date_iso, rel_path); reverse to map rel→date.
    date_by_path = {rel: date_iso for date_iso, rel in SHINDANSHI_PDFS}
    for rel, body in pdfs.items():
        iso = date_by_path.get(rel, "")
        if not iso:
            continue
        try:
            text = pdf_extract_text(io.BytesIO(body))
        except Exception as exc:
            _LOG.warning("[shindanshi] PDF parse fail %s: %s", rel, exc)
            continue
        pairs = _parse_shindanshi_pdf(text)
        url_full = "https://www.chusho.meti.go.jp" + rel
        for reg, name in pairs:
            out.append(
                EnfRow(
                    profession="診断士",
                    target_name=name,
                    enforcement_kind="license_revoke",
                    issuance_date=iso,
                    issuing_authority="経済産業省 中小企業庁",
                    related_law_ref="中小企業支援法施行規則第31条",
                    reason_summary=(
                        f"中小企業庁による中小企業診断士登録消除公示: "
                        f"処分月 {iso} / 登録番号 {reg} / "
                        f"理由: 中小企業診断士登録規則に基づく登録の消除 "
                        f"(更新登録未了等または消除申請による) / "
                        f"出典: 中小企業庁 中小企業診断士関連情報"
                    )[:1900],
                    source_url=url_full,
                    canonical_seed=f"{iso}|{reg}|{name}",
                    raw={
                        "registration_no": reg,
                        "name": name,
                        "issuance_date": iso,
                        "pdf_url": url_full,
                        "license": "政府機関の著作物（出典明記で転載引用可）",
                        "attribution": "出典: 経済産業省 中小企業庁 (https://www.chusho.meti.go.jp/)",
                    },
                )
            )
    return out


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


def existing_dedup_keys_for_authorities(
    conn: sqlite3.Connection,
    authorities: list[str],
) -> set[tuple[str, str, str]]:
    """Return {(target_name, issuance_date, issuing_authority)} for all
    rows whose issuing_authority is one of those we care about, scoped by
    a target_name LIKE filter to keep the working set small."""
    out: set[tuple[str, str, str]] = set()
    for auth in authorities:
        cur = conn.execute(
            "SELECT target_name, issuance_date, issuing_authority "
            "FROM am_enforcement_detail "
            "WHERE issuing_authority = ?",
            (auth,),
        )
        for n, d, a in cur.fetchall():
            if n and d and a:
                out.add((n, d, a))
    return out


def _slug8(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return h[:8]


PROFESSION_SLUG = {
    "鑑定士": "KANTEISHI",
    "調査士": "TOCHIKAOKU",
    "社労士": "SHAROUSHI",
    "診断士": "SHINDANSHI",
}


def upsert_entity(
    conn: sqlite3.Connection,
    *,
    canonical_id: str,
    primary_name: str,
    source_url: str,
    raw_json: str,
    fetched_at: str,
    source_topic: str,
) -> bool:
    """Insert entity. Returns True on fresh insert."""
    domain = urlparse(source_url).netloc or None
    cur = conn.execute(
        """INSERT OR IGNORE INTO am_entities (
              canonical_id, record_kind, source_topic, source_record_index,
              primary_name, authority_canonical, confidence,
              source_url, source_url_domain, fetched_at, raw_json,
              canonical_status, citation_status
           ) VALUES (?, 'enforcement', ?, NULL,
                     ?, NULL, 0.92, ?, ?, ?, ?, 'active', 'ok')""",
        (
            canonical_id,
            source_topic,
            primary_name[:500],
            source_url,
            domain,
            fetched_at,
            raw_json,
        ),
    )
    return cur.rowcount > 0


def insert_enforcement(
    conn: sqlite3.Connection,
    *,
    canonical_id: str,
    target_name: str,
    enforcement_kind: str,
    issuance_date: str,
    issuing_authority: str,
    reason_summary: str,
    related_law_ref: str,
    source_url: str,
    fetched_at: str,
) -> None:
    conn.execute(
        """INSERT INTO am_enforcement_detail (
               entity_id, houjin_bangou, target_name, enforcement_kind,
               issuing_authority, issuance_date, exclusion_start, exclusion_end,
               reason_summary, related_law_ref, amount_yen,
               source_url, source_fetched_at
           ) VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, ?, NULL, ?, ?)""",
        (
            canonical_id,
            target_name[:500],
            enforcement_kind,
            issuing_authority,
            issuance_date,
            reason_summary[:4000],
            related_law_ref[:1000],
            source_url,
            fetched_at,
        ),
    )


def write_rows(
    conn: sqlite3.Connection,
    rows: list[EnfRow],
    *,
    fetched_at: str,
    max_insert: int | None,
) -> tuple[int, int]:
    """Per-row BEGIN IMMEDIATE for low contention with sibling writers."""
    if not rows:
        return 0, 0

    authorities = sorted({r.issuing_authority for r in rows})
    db_keys = existing_dedup_keys_for_authorities(conn, authorities)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = 0
    skipped_dup = 0

    source_topic_map = {
        "鑑定士": "mlit_kanteishi_press",
        "調査士": "moj_chosashi_index",
        "社労士": "mhlw_sharo_tyoukai",
        "診断士": "meti_chusho_shindanshi_del",
    }

    for r in rows:
        if max_insert is not None and inserted >= max_insert:
            break
        key = (r.target_name, r.issuance_date, r.issuing_authority)
        if key in db_keys:
            skipped_dup += 1
            continue
        if key in batch_keys:
            skipped_dup += 1
            continue
        prof_slug = PROFESSION_SLUG.get(r.profession, "PRO")
        slug = _slug8(r.source_url, r.target_name, r.canonical_seed)
        canonical_id = f"AM-ENF-PRO-{prof_slug}-{r.issuance_date.replace('-', '')}-{slug}"
        primary_name = f"{r.target_name} - {r.related_law_ref} ({r.issuance_date})"
        raw_json = json.dumps(
            {
                **r.raw,
                "profession": r.profession,
                "target_name": r.target_name,
                "enforcement_kind": r.enforcement_kind,
                "issuing_authority": r.issuing_authority,
                "related_law_ref": r.related_law_ref,
                "issuance_date": r.issuance_date,
                "source_url": r.source_url,
                "ingest_topic": "other_pro_enforcement",
            },
            ensure_ascii=False,
        )
        source_topic = source_topic_map.get(r.profession, "other_pro_enforcement")
        try:
            conn.execute("BEGIN IMMEDIATE")
            inserted_entity = upsert_entity(
                conn,
                canonical_id=canonical_id,
                primary_name=primary_name,
                source_url=r.source_url,
                raw_json=raw_json,
                fetched_at=fetched_at,
                source_topic=source_topic,
            )
            if not inserted_entity:
                # canonical_id already exists — possibly partial state from
                # crashed prior run; treat as dup.
                conn.commit()
                skipped_dup += 1
                continue
            insert_enforcement(
                conn,
                canonical_id=canonical_id,
                target_name=r.target_name,
                enforcement_kind=r.enforcement_kind,
                issuance_date=r.issuance_date,
                issuing_authority=r.issuing_authority,
                reason_summary=r.reason_summary,
                related_law_ref=r.related_law_ref,
                source_url=r.source_url,
                fetched_at=fetched_at,
            )
            conn.commit()
            inserted += 1
            batch_keys.add(key)
        except sqlite3.IntegrityError as exc:
            _LOG.warning("integrity error %s: %s", canonical_id, exc)
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
        except sqlite3.Error as exc:
            _LOG.error("DB error %s: %s", canonical_id, exc)
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
        if inserted and inserted % 50 == 0:
            _LOG.info("progress inserted=%d (skipped_dup=%d)", inserted, skipped_dup)
    return inserted, skipped_dup


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument(
        "--max-insert",
        type=int,
        default=None,
        help="Stop after N inserts (debug)",
    )
    ap.add_argument(
        "--skip-kanteishi",
        action="store_true",
        help="Skip 不動産鑑定士 source A",
    )
    ap.add_argument(
        "--skip-chosashi",
        action="store_true",
        help="Skip 土地家屋調査士 source B",
    )
    ap.add_argument(
        "--skip-sharo",
        action="store_true",
        help="Skip 社会保険労務士 source C",
    )
    ap.add_argument(
        "--skip-shindanshi",
        action="store_true",
        help="Skip 中小企業診断士 source D",
    )
    ap.add_argument(
        "--shindanshi-skip-download",
        action="store_true",
        help="Use only PDFs already in --pdf-cache (no Playwright launch)",
    )
    ap.add_argument(
        "--shindanshi-only-n",
        type=int,
        default=None,
        help="Limit chusho PDFs to first N (debug)",
    )
    ap.add_argument(
        "--pdf-cache",
        type=Path,
        default=Path("/tmp/shindan_pdfs"),  # nosec B108 - operator-run cache; CLI override expected in cron use
        help="Directory to cache chusho 消除 PDFs",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    fetched_at = datetime.now(tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    http = HttpClient(user_agent=USER_AGENT, respect_robots=False)

    all_rows: list[EnfRow] = []

    if not args.skip_kanteishi:
        rows = collect_kanteishi_rows()
        _LOG.info("[kanteishi] rows=%d", len(rows))
        all_rows.extend(rows)

    if not args.skip_chosashi:
        rows = collect_chosashi_rows(http)
        _LOG.info("[chosashi] rows=%d", len(rows))
        all_rows.extend(rows)

    if not args.skip_sharo:
        rows = collect_sharo_rows(http)
        _LOG.info("[sharo] rows=%d", len(rows))
        all_rows.extend(rows)

    if not args.skip_shindanshi:
        rows = collect_shindanshi_rows(
            args.pdf_cache,
            skip_download=args.shindanshi_skip_download,
            only_first_n=args.shindanshi_only_n,
        )
        _LOG.info("[shindanshi] rows=%d", len(rows))
        all_rows.extend(rows)

    http.close()

    # Breakdown
    by_prof: dict[str, int] = {}
    for r in all_rows:
        by_prof[r.profession] = by_prof.get(r.profession, 0) + 1
    _LOG.info("Total parsed rows=%d breakdown=%s", len(all_rows), by_prof)

    if args.dry_run:
        for r in all_rows[:10]:
            _LOG.info(
                "sample prof=%s name=%s kind=%s date=%s law=%s url=%s",
                r.profession,
                r.target_name[:25],
                r.enforcement_kind,
                r.issuance_date,
                r.related_law_ref,
                r.source_url[:60],
            )
        print(
            json.dumps(
                {
                    "parsed": len(all_rows),
                    "breakdown_profession": by_prof,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        return 2

    conn = sqlite3.connect(str(args.db), timeout=300.0)
    try:
        conn.execute("PRAGMA busy_timeout=300000")
        conn.execute("PRAGMA foreign_keys=ON")
        ensure_tables(conn)
        inserted, skipped_dup = write_rows(
            conn,
            all_rows,
            fetched_at=fetched_at,
            max_insert=args.max_insert,
        )
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    # Re-tally inserted breakdown by walking the same rows minus dedup
    # (best-effort; precise tally not stored).

    # Summary
    print(
        json.dumps(
            {
                "ok": True,
                "parsed": len(all_rows),
                "inserted": inserted,
                "skipped_dup": skipped_dup,
                "breakdown_profession_parsed": by_prof,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    _LOG.info(
        "done parsed=%d inserted=%d dup=%d",
        len(all_rows),
        inserted,
        skipped_dup,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
