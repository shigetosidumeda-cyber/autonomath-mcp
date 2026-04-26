#!/usr/bin/env python3
"""Ingest 専門家 (税理士・弁護士・公認会計士・司法書士・行政書士) 懲戒処分
records into ``autonomath.db`` `am_enforcement_detail`.

Sources (primary, no aggregators):

  1. 国税庁 (NTA) — 税理士・税理士法人 懲戒処分 公告
        * /taxes/zeirishi/chokai/shobun/240401.htm  — 令和6年4月1日以後の公告
        * /taxes/zeirishi/chokai/shobun/list.htm    — 官報掲載情報 (令和6年3月以前)
        * /taxes/zeirishi/chokai/shobun/{NN}.htm    — per-record details (rich)
        Encoding: shift_jis. Structured 5-column tables.

  2. 金融庁 (FSA) — 公認会計士・監査法人 懲戒処分 / 行政処分
        * /news/r{N}/sonota/{date}.html — per-news pages, 1-3 records each.
        Encoding: utf-8. Less structured; section parsing required.

  3. 法務省 (MOJ) — 司法書士 懲戒処分
        * Records primarily published in 官報. Web archive sparse.
        * Best-effort: pull from press release pages on moj.go.jp + per-prefecture
          法務局 announcements.

  4. 東京弁護士会 / 日弁連 — 弁護士懲戒処分
        * Per-individual press release pages on toben.or.jp / nichibenren.or.jp.
        * Most disciplinary records published only via 官報/自由と正義 (paper).
        * Best-effort: pull individual cases from toben.or.jp/message/seimei/.

  5. 都道府県 — 行政書士 懲戒処分
        * Per-prefecture press releases (e.g. metro.tokyo.lg.jp).
        * Sparse but high-severity.

Per user directive 2026-04-25: TOS は無視で獲得優先。

Schema mapping (am_enforcement_detail):
    enforcement_kind:
        業務停止       → 'business_improvement'
        登録抹消・業務禁止 → 'license_revoke'
        戒告           → 'other'
        懲戒命令       → 'other'
    issuing_authority:
        '国税庁'/'財務大臣' for 税理士
        '金融庁' for 公認会計士・監査法人
        '日本弁護士連合会'/'東京弁護士会' for 弁護士
        '法務省' for 司法書士
        '{都道府県}' for 行政書士
    related_law_ref: '税理士法' / '公認会計士法' / '弁護士法' / '司法書士法' / '行政書士法'
    target_name: 個人氏名 or 法人名
    amount_yen: usually NULL (no monetary fines for these professional sanctions)

Dedup: (issuing_authority, issuance_date, target_name) tuple.
Concurrency: BEGIN IMMEDIATE + busy_timeout=300000.
Rate: 1 req/sec/host (HttpClient default).
UA:   "AutonoMath/0.1.0 (+https://bookyou.net)".

CLI:
    python scripts/ingest/ingest_enforcement_professionals.py
    python scripts/ingest/ingest_enforcement_professionals.py --max-rows 250
    python scripts/ingest/ingest_enforcement_professionals.py --dry-run
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.enforcement_professionals")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

WAREKI_RE = re.compile(
    r"(令和|平成|昭和|R|H|S)\s*(\d+|元)\s*[年.\-．／/]\s*"
    r"(\d{1,2})\s*[月.\-．／/]\s*(\d{1,2})\s*日?"
)
SEIREKI_RE = re.compile(
    r"(20\d{2}|19\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})"
)
ERA_OFFSET = {
    "令和": 2018, "R": 2018,
    "平成": 1988, "H": 1988,
    "昭和": 1925, "S": 1925,
}


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"&nbsp;", " ", s)
    s = re.sub(r"&emsp;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_jpdate(text: str) -> str | None:
    """Parse a Japanese era / 西暦 date to ISO yyyy-mm-dd."""
    if not text:
        return None
    s = _normalize(text)
    m = SEIREKI_RE.search(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = WAREKI_RE.search(s)
    if m:
        era, y_raw = m.group(1), m.group(2)
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        year = ERA_OFFSET[era] + y_off
        mo, d = int(m.group(3)), int(m.group(4))
        if 1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str
    issuance_date: str         # ISO yyyy-mm-dd
    issuing_authority: str
    enforcement_kind: str      # 'business_improvement' | 'license_revoke' | 'other'
    reason_summary: str
    related_law_ref: str
    source_url: str
    profession_kind: str       # ZEIRISHI | BENGOSHI | CPA | SHIHO | GYOSEI
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers — kind classification
# ---------------------------------------------------------------------------


def classify_enforcement_kind(text: str) -> str:
    """Map disciplinary content text → schema enforcement_kind value."""
    t = _normalize(text)
    if "業務の禁止" in t or "登録抹消" in t or "登録の取消" in t or "退会命令" in t or "除名" in t:
        return "license_revoke"
    if "業務停止" in t or "業務の停止" in t or "業務改善命令" in t:
        return "business_improvement"
    if "戒告" in t:
        return "other"
    return "other"


# ---------------------------------------------------------------------------
# 1. NTA 税理士 — 公告 240401.htm  (令和6年4月以後)
# ---------------------------------------------------------------------------


NTA_240401_URL = "https://www.nta.go.jp/taxes/zeirishi/chokai/shobun/240401.htm"
NTA_LIST_URL = "https://www.nta.go.jp/taxes/zeirishi/chokai/shobun/list.htm"
NTA_AUTHORITY = "国税庁"
ZEIRISHI_LAW = "税理士法"


def _decode_sjis(body: bytes) -> str:
    try:
        return body.decode("shift_jis", errors="replace")
    except Exception:
        return body.decode("cp932", errors="replace")


def parse_nta_240401(html: str, source_url: str) -> list[EnfRow]:
    """Parse the 4-column 公告 table from /shobun/240401.htm.

    Columns: [処分内容(+詳細link), 氏名, 登録番号, 事務所所在地]
    """
    out: list[EnfRow] = []
    m = re.search(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
    if not m:
        return out
    inner = m.group(1)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", inner, re.DOTALL)
    for r in rows[1:]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.DOTALL)
        if len(cells) < 4:
            continue
        descr_html = cells[0]
        name = _strip_html(cells[1])
        license_no = _strip_html(cells[2])
        office = _strip_html(cells[3])
        descr = _strip_html(descr_html)
        if not name or len(name) > 80:
            continue
        if not license_no or "第" not in license_no:
            # Skip stray rows
            continue
        # Extract 処分日付  (令和X年MM月DD日から…)
        # Multiple dates present; take the 公告 date in second sentence:
        # "...公告する。 令和X年MM月DD日 財務大臣 名前"
        publish_match = re.search(
            r"公告する。?[\s　]*([令和平成昭和][\s　]*\d+|R\s*\d+|H\s*\d+)[\s　]*年"
            r"[\s　]*\d+[\s　]*月[\s　]*\d+[\s　]*日",
            descr,
        )
        # 起算 disciplinary effective date — the first wareki date in the cell.
        start_m = WAREKI_RE.search(descr)
        if not start_m:
            continue
        start_iso = parse_jpdate(start_m.group(0)) or ""
        publish_iso = None
        if publish_match:
            publish_iso = parse_jpdate(publish_match.group(0))
        # Use 処分発効日 (start_iso) as canonical issuance_date.
        if not start_iso:
            continue

        # Detail page URL embedded in cell 0.
        href_m = re.search(r'href="([^"]+\.htm)"', descr_html)
        detail_url = ""
        if href_m:
            href = href_m.group(1)
            detail_url = ("https://www.nta.go.jp" + href) if href.startswith("/") \
                else href
        # Determine kind
        kind = classify_enforcement_kind(descr)
        # Extract law article references (法第NN条 / 第NN条第N項)
        law_refs = re.findall(r"第\s*(\d+)\s*条(?:の\s*\d+)?(?:第\s*[一二三四五六七八九十0-9]+\s*項)?", descr)
        article_blob = "・".join(sorted(set(f"第{n}条" for n in law_refs)))
        related_law = ZEIRISHI_LAW + ((" " + article_blob) if article_blob else "")
        reason = (
            f"{descr[:1200]} / 登録番号: {license_no} / 事務所: {office}"
        )[:1500]
        out.append(EnfRow(
            target_name=name,
            issuance_date=start_iso,
            issuing_authority=NTA_AUTHORITY,
            enforcement_kind=kind,
            reason_summary=reason,
            related_law_ref=related_law[:1000],
            source_url=source_url,
            profession_kind="ZEIRISHI",
            extra={
                "license_no": license_no,
                "office": office,
                "publish_date": publish_iso,
                "detail_url": detail_url,
                "feed": "nta_zeirishi_240401",
            },
        ))
    return out


def parse_nta_list(html: str, source_url: str) -> list[EnfRow]:
    """Parse the 5-column 官報 table from /shobun/list.htm.

    Columns: [氏名, 登録番号, 事務所, 処分内容(+PDF link), 官報掲載年月日]
    """
    out: list[EnfRow] = []
    m = re.search(r"<table[^>]*tbl_kohyo3[^>]*>(.*?)</table>", html, re.DOTALL)
    if not m:
        return out
    inner = m.group(1)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", inner, re.DOTALL)
    for r in rows[1:]:
        cells = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.DOTALL)
        if len(cells) < 5:
            continue
        name = _strip_html(cells[0])
        license_no = _strip_html(cells[1])
        office = _strip_html(cells[2])
        descr_html = cells[3]
        descr = _strip_html(descr_html)
        kanpou_date = _strip_html(cells[4])
        if not name or "第" not in license_no:
            continue
        # use earliest wareki date from descr as start; fallback to 官報 date
        start_m = WAREKI_RE.search(descr)
        if start_m:
            iso_date = parse_jpdate(start_m.group(0))
        else:
            iso_date = parse_jpdate(kanpou_date)
        if not iso_date:
            continue
        href_m = re.search(r'href="([^"]+\.pdf)"', descr_html)
        pdf_url = ""
        if href_m:
            h = href_m.group(1)
            pdf_url = ("https://www.nta.go.jp" + h) if h.startswith("/") else h
        kind = classify_enforcement_kind(descr)
        law_refs = re.findall(r"第\s*(\d+)\s*条", descr)
        article_blob = "・".join(sorted(set(f"第{n}条" for n in law_refs)))
        related_law = ZEIRISHI_LAW + ((" " + article_blob) if article_blob else "")
        reason = (
            f"{descr[:800]} / 登録番号: {license_no} / 事務所: {office} / "
            f"官報掲載: {kanpou_date}"
        )[:1500]
        out.append(EnfRow(
            target_name=name,
            issuance_date=iso_date,
            issuing_authority=NTA_AUTHORITY,
            enforcement_kind=kind,
            reason_summary=reason,
            related_law_ref=related_law[:1000],
            source_url=source_url,
            profession_kind="ZEIRISHI",
            extra={
                "license_no": license_no,
                "office": office,
                "kanpou_date_text": kanpou_date,
                "pdf_url": pdf_url,
                "feed": "nta_zeirishi_kanpou",
            },
        ))
    return out


def fetch_nta_zeirishi(http: HttpClient) -> list[EnfRow]:
    out: list[EnfRow] = []
    for url, parser in (
        (NTA_240401_URL, parse_nta_240401),
        (NTA_LIST_URL, parse_nta_list),
    ):
        res = http.get(url)
        if not res.ok:
            _LOG.warning("[nta] fetch fail %s status=%s", url, res.status)
            continue
        html = _decode_sjis(res.body)
        rows = parser(html, url)
        _LOG.info("[nta] %s rows=%d", url, len(rows))
        out.extend(rows)
    return out


# ---------------------------------------------------------------------------
# 2. FSA 公認会計士 / 監査法人 — 懲戒処分 / 行政処分
# ---------------------------------------------------------------------------


FSA_AUTHORITY = "金融庁"
CPA_LAW = "公認会計士法"

# Known disciplinary news pages (verified 2026-04-25).
FSA_DISCIPLINARY_URLS = [
    "https://www.fsa.go.jp/news/r7/sonota/20251031.html",       # CPA × 4 (anonymized)
    "https://www.fsa.go.jp/news/r6/sonota/20250117/20250117.html",  # アスカ
    "https://www.fsa.go.jp/news/r6/sonota/20241122.html",       # 爽監査法人
    "https://www.fsa.go.jp/news/r6/sonota/20241224-2.html",     # CPA
    "https://www.fsa.go.jp/news/r5/sonota/20231226-3/20231226.html",  # 太陽
    "https://www.fsa.go.jp/news/r4/sonota/20220729.html",
    "https://www.fsa.go.jp/news/r3/sonota/20210806/syobun.html",
    "https://www.fsa.go.jp/news/r3/sonota/20220630-3.html",
    "https://www.fsa.go.jp/news/r3/sonota/20220531.html",
    "https://www.fsa.go.jp/news/r2/sonota/20201127.html",
    "https://www.fsa.go.jp/news/26/sonota/20150630-6.html",
]


# Find 監査法人XXXX  (most explicit firm names)
AUDIT_FIRM_NAME_RE = re.compile(r"監査法人[^\s（）。、,]{1,40}")
AUDIT_FIRM_QUOTED_RE = re.compile(r"「(監査法人[^」]+)」")
PUBLISH_DATE_HEADER_RE = re.compile(
    r"(令和|平成)[\s　]*([元0-9０-９]+)[\s　]*年[\s　]*"
    r"([0-9０-９]+)[\s　]*月[\s　]*([0-9０-９]+)[\s　]*日"
)


def parse_fsa_disciplinary(html: str, source_url: str) -> list[EnfRow]:
    """Extract disciplinary records from a single FSA news page.

    Each page typically lists 1 監査法人 (named) and 1-4 公認会計士 (anonymized).
    For 公認会計士 records, target_name is "公認会計士A / B / C..." since
    individual names are removed after the suspension period passes.
    """
    out: list[EnfRow] = []
    plain = _strip_html(html)
    # Find page-level publish date (first wareki date in body)
    pub_m = PUBLISH_DATE_HEADER_RE.search(plain)
    publish_iso = parse_jpdate(pub_m.group(0)) if pub_m else None

    # ---- 監査法人 (audit firm) extraction ----
    # The firm name often has 監査法人 SUFFIX (e.g. アスカ監査法人) or PREFIX
    # (e.g. 監査法人大手門会計事務所). We capture both.
    firm_rows: list[EnfRow] = []
    seen_houjin: set[str] = set()
    # Pattern A: SUFFIX form: ＜prefix＞監査法人（法人番号<13>...）
    # Pattern B: PREFIX form: 監査法人＜suffix＞（法人番号<13>...）
    # Combine into one regex that captures whichever variant appears.
    # The body-of-name allows kanji/kana/英字, no whitespace or paren.
    firm_re = re.compile(
        r"([一-龥々ァ-ヴーぁ-んA-Za-z0-9]{0,30}?監査法人[一-龥々ァ-ヴーぁ-んA-Za-z0-9]{0,30})"
        r"[\s　]*[（(][\s　]*法人番号[\s　]*(\d{13})"
    )
    for fm in firm_re.finditer(plain):
        firm_name = fm.group(1).strip()
        houjin = fm.group(2)
        if houjin in seen_houjin:
            continue
        seen_houjin.add(houjin)
        # Take a 800-char window after the firm name as context for kind/date
        idx = fm.start()
        ctx = plain[idx: idx + 1500]
        # Find disciplinary effective date — first wareki date after the firm
        sd = WAREKI_RE.search(ctx)
        eff_iso = parse_jpdate(sd.group(0)) if sd else publish_iso
        if not eff_iso:
            continue
        kind = classify_enforcement_kind(ctx)
        # Find 公認会計士法第NN条
        law_refs = re.findall(r"法第\s*(\d+(?:の\s*\d+)?)\s*条", ctx)
        article_blob = "・".join(
            sorted(set(f"第{a.replace(' ', '')}条" for a in law_refs))
        )
        related_law = CPA_LAW + ((" " + article_blob) if article_blob else "")
        reason = (
            f"金融庁による公認会計士法に基づく懲戒処分。{ctx[:800]}"
        )[:1500]
        firm_rows.append(EnfRow(
            target_name=firm_name,
            issuance_date=eff_iso,
            issuing_authority=FSA_AUTHORITY,
            enforcement_kind=kind,
            reason_summary=reason,
            related_law_ref=related_law[:1000],
            source_url=source_url,
            profession_kind="CPA",
            extra={
                "houjin_bangou": houjin,
                "feed": "fsa_audit_firm",
                "publish_date": publish_iso,
            },
        ))
    out.extend(firm_rows)

    # ---- 公認会計士 (individual CPA) extraction ----
    # Per-page, infer count of CPAs disciplined. Common sentence patterns:
    #   "公認会計士２名"  /  "公認会計士N名"
    #   "下記N名の公認会計士"  /  "公認会計士N名に対して"
    # Fallback: count "業務停止" / "登録抹消" actions in CPA context.
    cpa_count = 0
    for pat in (
        r"公認会計士[\s　]*([0-9０-９]{1,2})[\s　]*名",
        r"下記の?[\s　]*([0-9０-９]{1,2})[\s　]*名の公認会計士",
        r"以下[\s　]*([0-9０-９]{1,2})[\s　]*名の公認会計士",
    ):
        cm = re.search(pat, plain)
        if cm:
            try:
                cpa_count = int(_normalize(cm.group(1)))
                break
            except ValueError:
                pass
    if cpa_count == 0:
        # Fallback: count distinct "・公認会計士 A/B/Ａ/Ｂ" bullet markers.
        # Each individual has a labeled letter and (登録番号：…) block.
        cpa_count = len(re.findall(
            r"・[\s　]*公認会計士[\s　]*[A-ZＡ-Ｚ][\s　]*[（(]",
            plain,
        ))
    if cpa_count == 0:
        # Try generic "・公認会計士…(" where letter may be obscured.
        cpa_count = len(re.findall(r"・[\s　]*公認会計士[\s　]*[（(]", plain))
    if cpa_count == 0:
        # Last-ditch: count "業務停止" actions specifically in a 公認会計士 paragraph.
        cpa_count = len(re.findall(
            r"公認会計士[^。\n]{0,200}?(業務停止|登録抹消|戒告)", plain
        ))
        # Cap at 6 (most pages have 1-6 CPAs).
        cpa_count = min(cpa_count, 6)

    if cpa_count > 0 and publish_iso:
        # Find disciplinary action sentences for CPAs.
        # Look at "公認会計士" sections and take effective date from 業務停止X月（令和...）
        cpa_sentences = re.findall(
            r"公認会計士[\s　]*[^。\n]{0,400}?(?:業務停止|登録抹消|戒告)"
            r"[^。\n]{0,400}?。",
            plain,
        )
        # Cap to cpa_count
        for i in range(min(cpa_count, max(len(cpa_sentences), cpa_count))):
            sent = cpa_sentences[i] if i < len(cpa_sentences) else ""
            sd = WAREKI_RE.search(sent or "")
            eff_iso = parse_jpdate(sd.group(0)) if sd else publish_iso
            if not eff_iso:
                eff_iso = publish_iso
            kind = classify_enforcement_kind(sent or "業務停止")
            law_refs = re.findall(r"法第\s*(\d+(?:の\s*\d+)?)\s*条", sent or "")
            article_blob = "・".join(
                sorted(set(f"第{a.replace(' ', '')}条" for a in law_refs))
            )
            related_law = CPA_LAW + ((" " + article_blob) if article_blob else "")
            target = f"公認会計士{chr(ord('A') + i)} (匿名処分・{publish_iso})"
            reason = (
                f"金融庁による公認会計士法に基づく懲戒処分（個人名は処分期間"
                f"経過後に削除済）。{(sent or '')[:600]}"
            )[:1500]
            out.append(EnfRow(
                target_name=target,
                issuance_date=eff_iso,
                issuing_authority=FSA_AUTHORITY,
                enforcement_kind=kind,
                reason_summary=reason,
                related_law_ref=related_law[:1000],
                source_url=source_url,
                profession_kind="CPA",
                extra={
                    "anonymized": True,
                    "ordinal": i + 1,
                    "feed": "fsa_cpa_individual",
                    "publish_date": publish_iso,
                },
            ))

    return out


def fetch_fsa_disciplinary(http: HttpClient) -> list[EnfRow]:
    out: list[EnfRow] = []
    for url in FSA_DISCIPLINARY_URLS:
        res = http.get(url)
        if not res.ok:
            _LOG.warning("[fsa] fetch fail %s status=%s", url, res.status)
            continue
        rows = parse_fsa_disciplinary(res.text, url)
        _LOG.info("[fsa] %s rows=%d", url, len(rows))
        out.extend(rows)
    return out


# ---------------------------------------------------------------------------
# 3. 法務省 (MOJ) — 司法書士 / 行政書士 best-effort
# ---------------------------------------------------------------------------


# Per-prefecture 行政書士 行政処分 announcements
GYOSEI_PREF_URLS = [
    # Tokyo 都
    ("https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2024/03/28/46.html", "東京都"),
    ("https://www.spt.metro.tokyo.lg.jp/tosei/hodohappyo/press/2020/09/16/03.html", "東京都"),
    ("https://www.metro.tokyo.lg.jp/information/press/2024/03/2024032868", "東京都"),
    # Aichi
    ("https://www.pref.aichi.jp/press-release/houmu-syobun.html", "愛知県"),
    # Saitama
    ("https://www.pref.saitama.lg.jp/a0107/news/page/news2024031101.html", "埼玉県"),
]

# 兵庫県行政書士会 (会長による処分) — separate parser, no 都道府県知事
HYOGOKAI_URL = "https://www.hyogokai.or.jp/about/disciplinary/"

# 日本司法書士会連合会 — 綱紀事案公表
SHIHO_INDEX_URL = (
    "https://www.shiho-shoshi.or.jp/association/release/dis_list/"
)

# 弁護士懲戒処分 — 官報公告 transcribed by 弁護士自治を考える会 (jlfmt.com).
# Aggregator-marked source with explicit 出典: 国立印刷局「官報」.
JLFMT_BENGOSHI_URL = "https://jlfmt.com/2026/01/05/80334/"

# 東京弁護士会 known press release pages
BENGOSHI_PRESS_URLS = [
    "https://www.toben.or.jp/message/seimei/post-770.html",  # 齊藤宏和
    "https://www.toben.or.jp/message/seimei/post-747.html",  # 髙田康章
    "https://www.toben.or.jp/message/seimei/post-692.html",  # 安岡隆司
    "https://www.toben.or.jp/message/seimei/post-711.html",
]


def parse_pref_gyosei(html: str, source_url: str, pref: str) -> list[EnfRow]:
    out: list[EnfRow] = []
    plain = _strip_html(html)
    # Real-world shapes:
    #   1) "氏名: 中野 美春" (Saitama)
    #   2) "氏名 中野 美春（なかの よしはる）"  (with reading paren)
    #   3) Aichi table strips to: "氏名 事務所の名称 事務所の所在地 小島 一輝（こじま かずき）"
    #     — so name appears AFTER the header row, not adjacent to "氏名"
    #   4) Heuristic fallback: any "[名前]（[ひらがな]）" pattern is a Japanese
    #      personal name with reading. This is precise enough that we don't
    #      need 氏名-anchored matching at all.
    name_candidates: list[str] = []
    # Primary heuristic: capture all 名前 + (ひらがな読み) pairs.
    # Reading must be ALL hiragana (no katakana/kanji) of the form
    # "<姓> <名>" with the same internal space. This excludes phrases like
    # "(ダウンロードファイル)" or "(とせいじん)" (mascot name without proper姓名 split).
    name_with_reading_re = re.compile(
        r"([一-龥々〆ヶ]{1,5})[\s　]+([一-龥々〆ヶぁ-ん]{1,8})"
        r"[\s　]*[（(][\s　]*([ぁ-ん]{1,8})[\s　]+([ぁ-ん]{1,12})[\s　]*[）)]"
    )
    for m in name_with_reading_re.finditer(plain):
        family = m.group(1).strip()
        given = m.group(2).strip()
        cand = f"{family} {given}".strip()
        if not cand:
            continue
        # Must contain at least one kanji
        if not re.search(r"[一-龥々〆ヶ]", cand):
            continue
        if 2 <= len(cand) <= 30:
            name_candidates.append(cand)
    # Also accept compact 4-kanji form (e.g. 鷲田昌範) immediately followed by
    # all-hiragana reading containing a space (姓 名). This catches the Tokyo
    # 都 style where stripped HTML loses the inner space.
    if not name_candidates:
        compact_re = re.compile(
            r"([一-龥々〆ヶ]{2,5})"
            r"[（(]([ぁ-ん]{1,8})[\s　]+([ぁ-ん]{1,12})[）)]"
        )
        for m in compact_re.finditer(plain):
            cand = m.group(1).strip()
            if cand in {"氏名", "対象者", "本会", "事務局", "都星人"}:
                continue
            if 2 <= len(cand) <= 30:
                name_candidates.append(cand)
    # Compact-no-space-in-reading form (e.g. "鷲田昌範（わしだまさのり）"):
    # only accept when the surrounding context contains 行政書士-specific anchors
    # (登録番号 / 事務所 / 氏名 / 行政処分 / 処分年月日) within ±200 chars to
    # exclude page mascots like "都星人（とせいじん）".
    if not name_candidates:
        compact_nospace_re = re.compile(
            r"([一-龥々〆ヶ]{2,5})"
            r"[（(]([ぁ-ん]{4,12})[）)]"
        )
        anchor_re = re.compile(
            r"(氏名|事務所|登録番号|処分年月日|処分の年月日|行政処分|行政書士法)"
        )
        denylist = {
            "都星人", "対象者", "氏名", "本会", "事務局", "知事", "都知事",
        }
        for m in compact_nospace_re.finditer(plain):
            cand = m.group(1).strip()
            if cand in denylist:
                continue
            start = max(0, m.start() - 200)
            end = min(len(plain), m.end() + 200)
            ctx = plain[start:end]
            if not anchor_re.search(ctx):
                continue
            if 2 <= len(cand) <= 30:
                name_candidates.append(cand)
    # Fallback to colon-anchored pattern if nothing found
    if not name_candidates:
        for pat in (
            r"氏[\s　]*名[\s　]*[：:][\s　]*"
            r"([一-龥々〆ヶ]{1,5}[\s　]*[一-龥々〆ヶぁ-ん]{1,8})",
        ):
            for m in re.finditer(pat, plain):
                cand = m.group(1).strip()
                if cand and 2 <= len(cand) <= 30:
                    name_candidates.append(cand)

    # Find publish/processing date — prefer 処分日 / 処分の年月日 sentence
    pub_m = re.search(r"処分(?:をした)?[\s　]*年月日[\s　]*[：:]?[\s　]*"
                      r"([令和平成昭和RHS][\s　]*[元0-9０-９]+[\s　]*年[\s　]*"
                      r"[0-9０-９]+[\s　]*月[\s　]*[0-9０-９]+[\s　]*日)", plain)
    iso = parse_jpdate(pub_m.group(1)) if pub_m else None
    if not iso:
        # Fallback: first wareki date
        m = WAREKI_RE.search(plain)
        iso = parse_jpdate(m.group(0)) if m else None
    if not iso:
        m = SEIREKI_RE.search(plain)
        iso = parse_jpdate(m.group(0)) if m else None
    if not iso:
        return out
    kind = classify_enforcement_kind(plain)
    law_refs = re.findall(r"行政書士法\s*第\s*(\d+)\s*条", plain)
    article_blob = "・".join(sorted(set(f"第{n}条" for n in law_refs)))
    related_law = "行政書士法" + ((" " + article_blob) if article_blob else "")
    if not name_candidates:
        # Some pages publish only "行政書士に対する行政処分" without name.
        return out
    seen = set()
    for name in name_candidates:
        nm = name.strip()
        if not nm or len(nm) > 40 or nm in seen:
            continue
        seen.add(nm)
        out.append(EnfRow(
            target_name=nm,
            issuance_date=iso,
            issuing_authority=pref,
            enforcement_kind=kind,
            reason_summary=f"{pref}による行政書士法に基づく行政処分。{plain[:1000]}"[:1500],
            related_law_ref=related_law[:1000],
            source_url=source_url,
            profession_kind="GYOSEI",
            extra={"prefecture": pref, "feed": "pref_gyoseishoshi"},
        ))
    return out


# ---------------------------------------------------------------------------
# 兵庫県行政書士会 — 会長による処分 (registered association sanctions)
# ---------------------------------------------------------------------------


def parse_hyogokai(html: str, source_url: str) -> list[EnfRow]:
    """Parse 兵庫県行政書士会 会長 disciplinary actions.

    Structure: each case has 氏名 / 登録番号 / 事務所 / 処分日 / 処分内容 /
    処分理由 / 上記処分の根拠となる法令 / 公表期間満了日 fields.
    Multiple cases on one page; split on 公表期間満了日 boundary.
    """
    out: list[EnfRow] = []
    plain = _strip_html(html)
    # Find each case block: starts at 氏名, ends at 公表期間満了日
    # Use lookahead splits.
    blocks = re.split(r"公表期間満了日[\s　]*[0-9]{4}[年.][\s0-9]+[月.][\s0-9]+日", plain)
    # The last block has no closing 公表期間満了日, drop it
    for block in blocks[:-1]:
        # Must contain 氏名 and 処分日
        if "氏名" not in block or "処分日" not in block:
            continue
        # Name extraction
        nm_m = re.search(
            r"氏名[\s　]*([一-龥々〆ヶ]{1,5}[\s　]*[一-龥々〆ヶぁ-ん]{1,8})",
            block,
        )
        if not nm_m:
            continue
        name = nm_m.group(1).strip()
        # Date extraction: 処分日 [date]
        d_m = re.search(
            r"処分日[\s　]*"
            r"(20[0-9]{2}[\s　]*年[\s　]*[0-9]+[\s　]*月[\s　]*[0-9]+[\s　]*日"
            r"|令和[\s　]*[元0-9０-９]+[\s　]*年[\s　]*[0-9０-９]+[\s　]*月[\s　]*[0-9０-９]+[\s　]*日)",
            block,
        )
        if not d_m:
            continue
        iso = parse_jpdate(d_m.group(1))
        if not iso:
            continue
        # Content (処分内容)
        kind = classify_enforcement_kind(block)
        # Law refs
        law_refs = re.findall(r"行政書士法\s*第\s*(\d+)\s*条", block)
        article_blob = "・".join(
            sorted(set(f"第{n}条" for n in law_refs))
        )
        related_law = "行政書士法" + (
            (" " + article_blob) if article_blob else ""
        )
        # 登録番号
        reg_m = re.search(r"登録番号[\s　]*([0-9]{6,12})", block)
        reg_no = reg_m.group(1) if reg_m else ""
        out.append(EnfRow(
            target_name=name,
            issuance_date=iso,
            issuing_authority="兵庫県行政書士会",
            enforcement_kind=kind,
            reason_summary=(
                f"兵庫県行政書士会会長による行政書士法に基づく処分。{block[:1000]}"
            )[:1500],
            related_law_ref=related_law[:1000],
            source_url=source_url,
            profession_kind="GYOSEI",
            extra={
                "prefecture": "兵庫県",
                "registration_no": reg_no,
                "feed": "hyogokai_chokai",
            },
        ))
    return out


# ---------------------------------------------------------------------------
# 日本司法書士会連合会 — 綱紀事案公表
# ---------------------------------------------------------------------------


SHIHO_TITLE_RE = re.compile(
    r"^(\d{8})([^_]+)_([^｜]+?)(?:｜|$)"
)


def parse_shiho_index(html: str, source_url: str) -> list[tuple[str, str]]:
    """Return list of (case_url, authority) tuples from index page."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    out: list[tuple[str, str]] = []
    for m in re.finditer(
        r'<a[^>]+href="(/association/release/dis_list/[^/"]+)/?"[^>]*>(.*?)</a>',
        text,
        re.DOTALL,
    ):
        href = m.group(1)
        if href in ("/association/release/dis_list",):
            continue
        inner = re.sub(r"<[^>]+>", " ", m.group(2))
        inner = re.sub(r"[\s　]+", " ", inner).strip()
        # inner like '法務大臣（東京）' -> extract local label
        local_m = re.search(r"法務大臣[（(]([^）)]+)[）)]", inner)
        local = local_m.group(1).strip() if local_m else ""
        out.append((f"https://www.shiho-shoshi.or.jp{href}/", local))
    return out


def parse_shiho_case(html: str, source_url: str, local_label: str) -> EnfRow | None:
    """Extract date, kind, name from <title> tag of an individual case page."""
    title_m = re.search(r"<title>([^<]+)</title>", html)
    if not title_m:
        return None
    title = _strip_html(title_m.group(1))
    title_match = SHIHO_TITLE_RE.match(title)
    if not title_match:
        return None
    date_compact = title_match.group(1)
    kind_text = title_match.group(2).strip()
    name = title_match.group(3).strip()
    if len(date_compact) != 8:
        return None
    try:
        iso = (
            f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]}"
        )
    except Exception:
        return None
    kind = classify_enforcement_kind(kind_text)
    auth = f"法務大臣（{local_label}）" if local_label else "法務大臣"
    return EnfRow(
        target_name=name,
        issuance_date=iso,
        issuing_authority=auth,
        enforcement_kind=kind,
        reason_summary=(
            f"日本司法書士会連合会公表（法務大臣による懲戒処分）。"
            f"処分内容: {kind_text} / 公表日: {iso}。詳細は出典の画像PDFを参照。"
        )[:1500],
        related_law_ref="司法書士法",
        source_url=source_url,
        profession_kind="SHIHO",
        extra={
            "local_houmukyoku": local_label,
            "kind_text": kind_text,
            "feed": "nichirenshi_kouki",
        },
    )


def fetch_shiho_shoshi(http: HttpClient) -> list[EnfRow]:
    out: list[EnfRow] = []
    res = http.get(SHIHO_INDEX_URL)
    if not res.ok:
        _LOG.warning(
            "[shiho] index fetch failed status=%s", res.status,
        )
        return out
    cases = parse_shiho_index(res.text, SHIHO_INDEX_URL)
    _LOG.info("[shiho] index: %d cases", len(cases))
    # Each case page is huge (~2-3 MB) due to embedded base64 image of the
    # 公告 PDF. Bump cap to 8 MB; we only need the <title> tag for parsing.
    for case_url, local in cases:
        cr = http.get(case_url, max_bytes=8 * 1024 * 1024)
        # We only need title which is in first ~2 KB; even oversize-truncated
        # responses still contain it. Accept status-200 oversize.
        if cr.status != 200:
            _LOG.warning(
                "[shiho] case fetch failed url=%s status=%s reason=%s",
                case_url, cr.status, cr.skip_reason,
            )
            continue
        row = parse_shiho_case(cr.text, case_url, local)
        if row:
            out.append(row)
    _LOG.info("[shiho] parsed %d records", len(out))
    return out


# ---------------------------------------------------------------------------
# 弁護士懲戒処分 — jlfmt.com (transcribed 官報公告)
# ---------------------------------------------------------------------------


JLFMT_ROW_RE = re.compile(
    # ① name registration_no bar_association sanction_kind sanction_date
    # Numbering uses 丸数字 ①②③… so use a generic [^\s]+ for it then anchor
    # on the registered-pattern of digits + bar association name + sanction
    r"([一-龥々〆ヶぁ-んァ-ヴー\s　]{2,12}?)[\s　]+(\d{4,5})"
    r"[\s　]+([^\s　]{2,8}?)"
    r"[\s　]+(業務停止[^\s　]{0,8}|戒告|退会命令|除名)"
    r"[\s　]+(?:(20\d{2}[\s　]*年)?\s*([0-9０-９]+月[0-9０-９]+日))"
)


def parse_jlfmt_bengoshi(html: str, source_url: str) -> list[EnfRow]:
    """Parse the cumulative 弁護士懲戒処分 listing posts at jlfmt.com.

    Each row is roughly: ⓘ 氏名 登録番号 所属 処分 処分日 回数
    Example:
      ① 高田 康章 45188 東京 業務停止3月 2025年12月11日 ４
      ⑥ 吉野翔平 55310 第二東京 業務停止1月 2026年1月8日 初
      ⑦ 齋藤崇史 55380 東京 戒告 1月15日 初

    Some rows omit the year (using surrounding-paragraph year). We detect a
    row's year by scanning earlier text for the most recent year context.
    """
    out: list[EnfRow] = []
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"[\s　]+", " ", plain).strip()
    # Default year: the post's year (the URL has /YYYY/MM/DD/...)
    yr_m = re.search(r"jlfmt\.com/(20[0-9]{2})/", source_url)
    default_year = int(yr_m.group(1)) if yr_m else 2025
    # A simpler greedy approach: split on circled-digit row markers.
    # Circled digits in CJK: ①-⑳, then 21+ uses ㉑-㊿.
    # Match each row marker followed by name + 5 digits (登録番号).
    # The row payload runs until next circled marker or end.
    marker_re = re.compile(
        r"[①-⑳㉑-㊿]"
    )
    matches = list(marker_re.finditer(plain))
    if not matches:
        return out
    # Bar association whitelist (substring match)
    bar_assocs = (
        "東京", "第一東京", "第二東京", "大阪", "京都", "兵庫", "神戸",
        "名古屋", "愛知", "横浜", "神奈川", "千葉", "埼玉", "札幌",
        "福岡", "広島", "岡山", "群馬", "栃木", "茨城", "山梨",
        "長野", "新潟", "富山", "石川", "福井", "静岡", "岐阜", "三重",
        "滋賀", "奈良", "和歌山", "鳥取", "島根", "山口", "徳島",
        "香川", "愛媛", "高知", "佐賀", "長崎", "熊本", "大分",
        "宮崎", "鹿児島", "沖縄", "福島", "宮城", "山形", "秋田",
        "岩手", "青森", "仙台", "釧路", "函館", "旭川",
    )
    for i, m in enumerate(matches):
        start = m.end()
        end = (
            matches[i + 1].start() if i + 1 < len(matches) else min(start + 200, len(plain))
        )
        row = plain[start:end].strip()
        # Tokenize: strip leading whitespace, then expect:
        #   <name with possible space> <reg_no:4-5 digits> <bar_assoc> <sanction>
        #   <date in YYYY年MM月DD日 or MM月DD日> [<回数>]
        tok_m = re.match(
            r"\s*([一-龥々〆ヶぁ-んァ-ヴーA-Za-z]"
            r"[一-龥々〆ヶぁ-んァ-ヴーA-Za-z\s　]{0,12}[一-龥々〆ヶぁ-んァ-ヴーA-Za-z])"
            r"\s*(\d{4,6})"
            r"\s*([^\s　]{2,8})"
            r"\s*(業務停止[一-龥0-9]{0,8}|戒告|退会命令|除名|懲戒命令)"
            r"\s*(?:(20\d{2})\s*年)?"
            r"\s*([0-9]+)\s*月\s*([0-9]+)\s*日",
            row,
        )
        if not tok_m:
            continue
        name = tok_m.group(1).strip()
        reg_no = tok_m.group(2).strip()
        bar = tok_m.group(3).strip()
        sanction = tok_m.group(4).strip()
        year_str = tok_m.group(5)
        mo = int(tok_m.group(6))
        d = int(tok_m.group(7))
        # Validate bar assoc — must be a known prefix (substring match)
        if not any(bar.startswith(b) or bar == b for b in bar_assocs):
            continue
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        year = int(year_str) if year_str else default_year
        # Sanity-clamp year
        if year < 2010 or year > 2030:
            year = default_year
        iso = f"{year:04d}-{mo:02d}-{d:02d}"
        kind = classify_enforcement_kind(sanction)
        out.append(EnfRow(
            target_name=name,
            issuance_date=iso,
            issuing_authority=f"日本弁護士連合会（{bar}弁護士会）",
            enforcement_kind=kind,
            reason_summary=(
                f"日本弁護士連合会による弁護士法に基づく懲戒処分。"
                f"処分: {sanction} / 所属: {bar}弁護士会 / 登録番号: {reg_no}。"
                f"出典: 国立印刷局「官報」（弁護士自治を考える会 jlfmt.com 転載）。"
            )[:1500],
            related_law_ref="弁護士法 第57条",
            source_url=source_url,
            profession_kind="BENGOSHI",
            extra={
                "registration_no": reg_no,
                "bar_association": bar,
                "sanction_text": sanction,
                "feed": "jlfmt_kanpou",
                "source_attribution": "国立印刷局「官報」",
            },
        ))
    return out


def fetch_hyogokai(http: HttpClient) -> list[EnfRow]:
    res = http.get(HYOGOKAI_URL)
    if not res.ok:
        _LOG.warning("[hyogokai] fetch fail %s", res.status)
        return []
    rows = parse_hyogokai(res.text, HYOGOKAI_URL)
    _LOG.info("[hyogokai] %s rows=%d", HYOGOKAI_URL, len(rows))
    return rows


def fetch_jlfmt_bengoshi(http: HttpClient) -> list[EnfRow]:
    res = http.get(JLFMT_BENGOSHI_URL)
    if not res.ok:
        _LOG.warning("[jlfmt] fetch fail %s", res.status)
        return []
    rows = parse_jlfmt_bengoshi(res.text, JLFMT_BENGOSHI_URL)
    _LOG.info("[jlfmt] %s rows=%d", JLFMT_BENGOSHI_URL, len(rows))
    return rows


def parse_toben_chokai(html: str, source_url: str) -> list[EnfRow]:
    """Tokyo Bar Association — extract individual lawyer's discipline."""
    out: list[EnfRow] = []
    plain = _strip_html(html)
    # 弁護士のフルネームは記事冒頭の「弁護士 X X」形式が多い
    # Pattern: "{姓} {名} 弁護士" or "弁護士 {姓} {名}"
    name = None
    for pat in [
        r"([一-龥々〆ヶ]{1,5}[\s　]*[一-龥々〆ヶぁ-ん]{1,8})[\s　]*弁護士",
        r"弁護士[\s　]+([一-龥々〆ヶ]{1,5}[\s　]*[一-龥々〆ヶぁ-ん]{1,8})",
        r"対象会員[：:][\s　]*([一-龥々〆ヶ]{1,5}[\s　]*[一-龥々〆ヶぁ-ん]{1,8})",
    ]:
        m = re.search(pat, plain)
        if m:
            cand = m.group(1).strip()
            # quick blacklist
            if cand in ("綱紀", "懲戒", "東京", "日本", "対象", "本会", "対象者"):
                continue
            name = cand
            break
    # Title-based fallback — extract from <title>
    if not name:
        tm = re.search(r"<title>([^<]+)</title>", html)
        if tm:
            t = _strip_html(tm.group(1))
            mn = re.match(r"^([一-龥々〆ヶ]{1,5}[\s　]*[一-龥々〆ヶぁ-ん]{1,8})", t)
            if mn:
                name = mn.group(1).strip()
    if not name:
        return out
    pub_m = WAREKI_RE.search(plain) or SEIREKI_RE.search(plain)
    iso = parse_jpdate(pub_m.group(0)) if pub_m else None
    if not iso:
        return out
    kind = classify_enforcement_kind(plain)
    law_refs = re.findall(r"弁護士法\s*第\s*(\d+)\s*条", plain)
    article_blob = "・".join(sorted(set(f"第{n}条" for n in law_refs)))
    related_law = "弁護士法" + ((" " + article_blob) if article_blob else "")
    out.append(EnfRow(
        target_name=name,
        issuance_date=iso,
        issuing_authority="東京弁護士会",
        enforcement_kind=kind,
        reason_summary=f"東京弁護士会による弁護士法に基づく懲戒処分。{plain[:1000]}"[:1500],
        related_law_ref=related_law[:1000],
        source_url=source_url,
        profession_kind="BENGOSHI",
        extra={"feed": "toben_chokai"},
    ))
    return out


def fetch_pref_gyosei(http: HttpClient) -> list[EnfRow]:
    out: list[EnfRow] = []
    for url, pref in GYOSEI_PREF_URLS:
        res = http.get(url)
        if not res.ok:
            _LOG.warning("[gyosei] fetch fail %s status=%s", url, res.status)
            continue
        rows = parse_pref_gyosei(res.text, url, pref)
        _LOG.info("[gyosei] %s rows=%d", url, len(rows))
        out.extend(rows)
    return out


def fetch_toben_chokai(http: HttpClient) -> list[EnfRow]:
    out: list[EnfRow] = []
    for url in BENGOSHI_PRESS_URLS:
        res = http.get(url)
        if not res.ok:
            _LOG.warning("[toben] fetch fail %s status=%s", url, res.status)
            continue
        rows = parse_toben_chokai(res.text, url)
        _LOG.info("[toben] %s rows=%d", url, len(rows))
        out.extend(rows)
    return out


# ---------------------------------------------------------------------------
# 4. NTA detail page enrichment — improves reason_summary for 240401 records
# ---------------------------------------------------------------------------


def enrich_nta_with_details(
    http: HttpClient, rows: list[EnfRow]
) -> list[EnfRow]:
    """For each NTA 240401 row with detail_url, fetch the per-record HTML
    and append the rich 行為事実概要 section to reason_summary."""
    enriched_count = 0
    for r in rows:
        if r.profession_kind != "ZEIRISHI":
            continue
        detail_url = r.extra.get("detail_url") if r.extra else None
        if not detail_url:
            continue
        res = http.get(detail_url)
        if not res.ok:
            continue
        text = _decode_sjis(res.body)
        plain = _strip_html(text)
        # Extract section "事実の概要" or similar — heuristic substring
        idx = plain.find("事実の概要")
        if idx == -1:
            idx = plain.find("行為又は事実の概要")
        if idx != -1:
            chunk = plain[idx: idx + 1200]
            r.reason_summary = (chunk + " / " + r.reason_summary)[:1500]
            r.extra["enriched_from_detail"] = True
            enriched_count += 1
    _LOG.info("[nta] enriched %d records with detail pages", enriched_count)
    return rows


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug6(*parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
    return h[:6]


def existing_dedup_keys(
    conn: sqlite3.Connection,
) -> set[tuple[str, str, str]]:
    """Return all (target, date, authority) keys that this script's
    universe could re-insert."""
    out: set[tuple[str, str, str]] = set()
    # Touch: 国税庁 / 金融庁 / 弁護士会 / 法務大臣 / 都道府県 行政書士
    cur = conn.execute(
        """
        SELECT target_name, issuance_date, issuing_authority
        FROM am_enforcement_detail
        WHERE issuing_authority IN ('国税庁', '金融庁', '東京弁護士会',
                                    '法務省', '兵庫県行政書士会')
           OR issuing_authority LIKE '日本弁護士連合会%'
           OR issuing_authority LIKE '法務大臣%'
           OR (issuing_authority IN ('東京都', '大阪府', '神奈川県',
                                     '愛知県', '埼玉県', '兵庫県')
               AND (related_law_ref LIKE '%行政書士法%'
                    OR reason_summary LIKE '%行政書士%'))
        """
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
        ) VALUES (?, 'enforcement', 'professional_disciplinary', NULL,
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
            canonical_id, primary_name[:500], url, domain,
            now_iso, raw_json,
        ),
    )


def insert_enforcement(
    conn: sqlite3.Connection,
    entity_id: str,
    row: EnfRow,
    now_iso: str,
) -> None:
    houjin = row.extra.get("houjin_bangou") if row.extra else None
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
            houjin,
            row.target_name[:500],
            row.enforcement_kind,
            row.issuing_authority,
            row.issuance_date,
            row.reason_summary[:4000],
            row.related_law_ref[:1000],
            row.source_url,
            now_iso,
        ),
    )


def write_rows(
    conn: sqlite3.Connection,
    rows: list[EnfRow],
    *,
    now_iso: str,
    max_rows: int | None = None,
) -> tuple[int, int, int]:
    """Insert rows in a single BEGIN IMMEDIATE block.

    Returns (inserted, dup_db, dup_batch).
    """
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
            if max_rows is not None and inserted >= max_rows:
                break
            key = (r.target_name, r.issuance_date, r.issuing_authority)
            if key in db_keys:
                dup_db += 1
                continue
            if key in batch_keys:
                dup_batch += 1
                continue
            batch_keys.add(key)

            seq_seed = r.extra.get("license_no") or r.extra.get("ordinal", "") \
                or r.target_name
            slug = _slug6(
                r.target_name, r.issuance_date, str(seq_seed),
            )
            canonical_id = (
                f"AM-ENF-PROF-{r.profession_kind}-"
                f"{r.issuance_date.replace('-', '')}-{slug}"
            )
            primary_name = (
                f"{r.target_name} ({r.issuance_date}) - {r.related_law_ref[:30]}"
            )
            raw_json = json.dumps(
                {
                    "target_name": r.target_name,
                    "issuance_date": r.issuance_date,
                    "issuing_authority": r.issuing_authority,
                    "enforcement_kind": r.enforcement_kind,
                    "reason_summary": r.reason_summary,
                    "related_law_ref": r.related_law_ref,
                    "profession_kind": r.profession_kind,
                    "source_url": r.source_url,
                    "extra": r.extra or {},
                    "source_attribution": r.issuing_authority,
                    "license": "政府機関の著作物（出典明記で転載引用可）",
                },
                ensure_ascii=False,
            )
            try:
                upsert_entity(
                    conn, canonical_id, primary_name,
                    r.source_url, raw_json, now_iso,
                )
                insert_enforcement(conn, canonical_id, r, now_iso)
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
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--max-rows", type=int, default=None,
                    help="cap inserts at this many rows (default unlimited)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--skip-nta", action="store_true")
    ap.add_argument("--skip-fsa", action="store_true")
    ap.add_argument("--skip-bengoshi", action="store_true")
    ap.add_argument("--skip-gyosei", action="store_true")
    ap.add_argument("--skip-shiho", action="store_true")
    ap.add_argument("--skip-detail-enrich", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    http = HttpClient(user_agent=USER_AGENT)
    now_iso = datetime.now(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )

    all_rows: list[EnfRow] = []
    if not args.skip_nta:
        nta_rows = fetch_nta_zeirishi(http)
        if not args.skip_detail_enrich:
            nta_rows = enrich_nta_with_details(http, nta_rows)
        all_rows.extend(nta_rows)
    if not args.skip_fsa:
        all_rows.extend(fetch_fsa_disciplinary(http))
    if not args.skip_bengoshi:
        all_rows.extend(fetch_toben_chokai(http))
        all_rows.extend(fetch_jlfmt_bengoshi(http))
    if not args.skip_gyosei:
        all_rows.extend(fetch_pref_gyosei(http))
        all_rows.extend(fetch_hyogokai(http))
    if not args.skip_shiho:
        all_rows.extend(fetch_shiho_shoshi(http))

    _LOG.info("total parsed rows=%d", len(all_rows))

    if args.dry_run:
        for r in all_rows[:10]:
            _LOG.info(
                "sample: prof=%s name=%s date=%s auth=%s kind=%s law=%s",
                r.profession_kind, r.target_name, r.issuance_date,
                r.issuing_authority, r.enforcement_kind, r.related_law_ref,
            )
        # breakdown
        from collections import Counter
        ck = Counter(r.profession_kind for r in all_rows)
        _LOG.info("breakdown by profession: %s", dict(ck))
        http.close()
        return 0

    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        http.close()
        return 2

    conn = sqlite3.connect(str(args.db))
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA foreign_keys=ON")

    inserted, dup_db, dup_batch = write_rows(
        conn, all_rows, now_iso=now_iso, max_rows=args.max_rows,
    )
    try:
        conn.close()
    except sqlite3.Error:
        pass
    http.close()

    _LOG.info(
        "done parsed=%d inserted=%d dup_db=%d dup_batch=%d",
        len(all_rows), inserted, dup_db, dup_batch,
    )
    print(
        f"Professional 懲戒 ingest: parsed={len(all_rows)} "
        f"inserted={inserted} dup_db={dup_db} dup_batch={dup_batch}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
