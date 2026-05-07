#!/usr/bin/env python3
"""Ingest 47 都道府県警察 公安委員会 行政処分 (古物営業法 / 風俗営業適正化法 /
警備業法 / 探偵業法 / 自動車運転代行業法 / 質屋営業法) into ``am_enforcement_detail``.

Background:
  Public Safety Commission (公安委員会) issued enforcement records under
  six related laws governed by 47 都道府県警察:

    1. 警備業法 — 認定の取消し / 営業停止命令 / 営業廃止命令 / 指示
    2. 探偵業の業務の適正化に関する法律 — 同上
    3. 古物営業法 — 許可の取消し / 営業停止命令 / 指示
    4. 質屋営業法 — 営業停止命令
    5. 風俗営業等の規制及び業務の適正化等に関する法律 — 許可取消 / 営業停止 / 指示 /
       第41条第2項に基づく公示
    6. 自動車運転代行業の業務の適正化に関する法律 — 認定取消 / 営業停止 / 指示

  Reality check (verified 2026-04-25):
    Per-record disposition lists across 47 prefectures are sparse — most
    prefectures publish only the 処分基準 (criteria) without naming
    individual 業者. The handful of prefectures that DO list named cases
    yield concrete data. We harvest those primary-source records honestly.

  This script is a complement to ``ingest_enforcement_npa.py`` (兵庫 only)
  — it adds approximately 17 additional prefectures' confirmed primary
  disposition pages.

  Approach:
    - Walk a curated SOURCES list of police-site pages confirmed (probed
      via WebFetch on 2026-04-25) to contain *named* business entities +
      date + disposition kind.
    - Per-source parser tailored to each prefecture's HTML layout:
        * keishicho_keibi_html / kanagawa_keibi_html / chiba_keibi_html
          (etc.) for 警備業
        * osaka_keibi_html for 大阪府
        * miyagi_keibi_html for 宮城
        * shizuoka_keibi_html for 静岡 (anchor-based with PDFs)
        * generic_keibi_table for prefectures with simple table HTML
        * kanagawa_daiko_html / yamaguchi_daiko_html / saitama_daiko_html
          / fukui_daiko_html / nara_daiko_html / etc. for 自動車運転代行
        * fukuoka_daiko_html — Fukuoka 運転代行 PDF list
        * kyoto_daiko_html — 京都府 運転代行
        * kumamoto_daiko_html — 熊本県 運転代行 (1 record)
        * ishikawa_daiko_html — 石川県 運転代行
        * hokkaido_daiko_html — 北海道 運転代行
        * yamaguchi_daiko_html — 山口県 運転代行 (7 records)
        * fuei_kouji_html — 風適法 第41条 公示 (existing in npa script,
          not duplicated here)

Schema mapping (am_enforcement_detail):
    - enforcement_kind:
        * 営業停止 / 営業の停止命令 / 業務停止 / 停止命令 → 'business_improvement'
        * 中止命令 / 再発防止命令 / 指示 → 'business_improvement'
        * 認定の取消 / 許可の取消 / 廃止命令 → 'license_revoke'
        * 公示 → 'other'
    - issuing_authority: '{prefecture}公安委員会' or '警視庁公安委員会'
    - related_law_ref: full statute name; 警備業法 / 古物営業法 /
      風俗営業等... / 自動車運転代行業の業務の適正化に関する法律 etc.
    - amount_yen: NULL (police orders rarely include monetary fines).

Anonymization:
    - 古物商 individual proprietors (氏名公表) are anonymized as
      "古物商 #{県名}-{seq:03d} (氏名非公表)" — reuses the medical_pros
      pattern. Corporate names (株式会社/有限会社/合同会社) stay as-is.
    - Driving-substitute 運転代行 屋号 (e.g. "運転代行Tommy") are not
      personally identifiable, so passed through verbatim.

Parallel-write:
    BEGIN IMMEDIATE + busy_timeout=300000 (CLAUDE.md §5).

Dedup:
    (issuing_authority, issuance_date, target_name) tuple, both DB and
    batch.

CLI:
    python scripts/ingest/ingest_enforcement_pref_police.py \\
        [--db autonomath.db] [--dry-run] [--verbose] [--limit 200]
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
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"ERROR: beautifulsoup4 not installed: {exc}", file=sys.stderr)
    raise

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import contextlib

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.pref_police")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Source:
    prefecture: str  # 兵庫県 / 東京都 / 大阪府 / etc.
    authority: str  # 兵庫県公安委員会 / 警視庁公安委員会 etc.
    url: str
    parser: str
    related_law: str  # default related_law for this source
    note: str = ""


@dataclass
class EnfRow:
    target_name: str
    issuance_date: str  # ISO yyyy-mm-dd
    issuing_authority: str
    enforcement_kind: str  # checked against CHECK constraint
    reason_summary: str
    related_law_ref: str
    source_url: str
    extra: dict | None = None


# ---------------------------------------------------------------------------
# Source registry — only prefectures with confirmed named records as of 2026-04-25
# ---------------------------------------------------------------------------


KEIBIGYOU = "警備業法"
TANTEI = "探偵業の業務の適正化に関する法律"
KOBUTSU = "古物営業法"
FUEI = "風俗営業等の規制及び業務の適正化等に関する法律"
DAIKO = "自動車運転代行業の業務の適正化に関する法律"
SHITSUYA = "質屋営業法"


SOURCES: list[Source] = [
    # === 警備業法 行政処分 (公表) ===
    Source(
        "大阪府",
        "大阪府公安委員会",
        "https://www.police.pref.osaka.lg.jp/tetsuduki/ninkyoka/3/12075.html",
        "osaka_keibi_html",
        KEIBIGYOU,
        note="大阪府公安委員会 警備業法 行政処分公表",
    ),
    Source(
        "宮城県",
        "宮城県公安委員会",
        "https://www.police.pref.miyagi.jp/seian/kyoninka/gyouseisyobun/kouhyouichiran.html",
        "miyagi_keibi_html",
        KEIBIGYOU,
        note="宮城県公安委員会 警備業法 行政処分公表",
    ),
    Source(
        "千葉県",
        "千葉県公安委員会",
        "https://www.police.pref.chiba.jp/fuhoka/orders_information_12.html",
        "chiba_keibi_html",
        KEIBIGYOU,
        note="千葉県公安委員会 警備業法 行政処分公表",
    ),
    Source(
        "静岡県",
        "静岡県公安委員会",
        "https://www.pref.shizuoka.jp/police/about/hore/kebi.html",
        "shizuoka_keibi_html",
        KEIBIGYOU,
        note="静岡県公安委員会 警備業法 行政処分公表 (anchor-based)",
    ),
    # === 自動車運転代行業 行政処分 (公表) ===
    Source(
        "神奈川県",
        "神奈川県公安委員会",
        "https://www.police.pref.kanagawa.jp/kotsu/ho_shiko/mesf0076.html",
        "kanagawa_daiko_html",
        DAIKO,
        note="神奈川県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "奈良県",
        "奈良県公安委員会",
        "https://www.police.pref.nara.jp/0000005528.html",
        "nara_daiko_html",
        DAIKO,
        note="奈良県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "福井県",
        "福井県公安委員会",
        "https://www.pref.fukui.lg.jp/kenkei/doc/kenkei/daiko.html",
        "fukui_daiko_html",
        DAIKO,
        note="福井県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "埼玉県",
        "埼玉県公安委員会",
        "https://www.police.pref.saitama.lg.jp/f0010/shinse/daikou.html",
        "saitama_daiko_html",
        DAIKO,
        note="埼玉県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "北海道",
        "北海道知事",
        "https://www.pref.hokkaido.lg.jp/ss/stk/daikougyo.html",
        "hokkaido_daiko_html",
        DAIKO,
        note="北海道知事 運転代行 行政処分公表 (運転代行は知事処分)",
    ),
    Source(
        "石川県",
        "石川県公安委員会",
        "https://www2.police.pref.ishikawa.lg.jp/trafficsafety/trafficsafety05/trafficsafety14.html",
        "ishikawa_daiko_html",
        DAIKO,
        note="石川県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "山口県",
        "山口県公安委員会",
        "https://www.pref.yamaguchi.lg.jp/site/police/10488.html",
        "yamaguchi_daiko_html",
        DAIKO,
        note="山口県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "熊本県",
        "熊本県公安委員会",
        "https://www.pref.kumamoto.jp/site/police/51952.html",
        "kumamoto_daiko_html",
        DAIKO,
        note="熊本県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "京都府",
        "京都府公安委員会",
        "https://www.pref.kyoto.jp/fukei/kotu/koki_2/daiko/shobun.html",
        "kyoto_daiko_html",
        DAIKO,
        note="京都府公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "福岡県",
        "福岡県公安委員会",
        "https://www.police.pref.fukuoka.jp/kotsu/kotsukikaku/untendaiko/gyoseisyobunkohyo.html",
        "fukuoka_daiko_html",
        DAIKO,
        note="福岡県公安委員会 運転代行 行政処分公表",
    ),
    # Added 2026-04-25 (second-pass discovery)
    Source(
        "青森県",
        "青森県公安委員会",
        "https://www.police.pref.aomori.jp/koutubu/koutu_kikaku/unten_daikou.html",
        "aomori_daiko_html",
        DAIKO,
        note="青森県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "秋田県",
        "秋田県公安委員会",
        "https://www.police.pref.akita.lg.jp/kouan/gyouseishobun-daikou/daikou-itiran",
        "akita_daiko_html",
        DAIKO,
        note="秋田県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "富山県",
        "富山県公安委員会",
        "https://police.pref.toyama.jp/documents/533/gyoseisyobun.pdf",
        "toyama_daiko_pdf",
        DAIKO,
        note="富山県公安委員会 運転代行 行政処分簿 (PDF)",
    ),
    Source(
        "茨城県",
        "茨城県公安委員会",
        "https://www.pref.ibaraki.jp/kenkei/a02_traffic/drive_agency/penalty.html",
        "ibaraki_daiko_html",
        DAIKO,
        note="茨城県公安委員会 運転代行 行政処分公表",
    ),
    Source(
        "長崎県",
        "長崎県公安委員会",
        "https://www.police.pref.nagasaki.jp/police/disclosure/gyosei-shobun/kotsubu/",
        "nagasaki_daiko_html",
        DAIKO,
        note="長崎県公安委員会 運転代行 行政処分公表 (一覧形式)",
    ),
    Source(
        "佐賀県",
        "佐賀県知事",
        "https://www.pref.saga.lg.jp/kiji00359076/3_59076_up_ih1ctsmb.pdf",
        "saga_chiji_daiko_pdf",
        DAIKO,
        note="佐賀県知事 運転代行 行政処分票 (PDF) 令8.1.27",
    ),
    Source(
        "佐賀県",
        "佐賀県知事",
        "https://www.pref.saga.lg.jp/kiji00359076/3_59076_up_br8q0kne.pdf",
        "saga_chiji_daiko_pdf",
        DAIKO,
        note="佐賀県知事 運転代行 行政処分票 (PDF) 令8.2.25",
    ),
    # === 警備業法 行政処分 (公表) — additional ===
    Source(
        "兵庫県",
        "兵庫県公安委員会",
        "https://www.police.pref.hyogo.lg.jp/sc/order.htm",
        "hyogo_keibi_html",
        KEIBIGYOU,
        note="兵庫県公安委員会 警備業法 行政処分公表",
    ),
]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


WAREKI_RE = re.compile(
    r"(令和|平成|R|H)\s*(\d+|元)\s*[年.\-．／/]\s*"
    r"(\d{1,2})\s*[月.\-．／/]\s*(\d{1,2})\s*日?"
)
SEIREKI_RE = re.compile(r"(20\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})")
ERA_OFFSET = {"令和": 2018, "R": 2018, "平成": 1988, "H": 1988}


def _normalize(s: str) -> str:
    if not s:
        return ""
    return unicodedata.normalize("NFKC", s).strip()


def _parse_date(text: str) -> str | None:
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
        era, y_raw, mo, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            return None
        year = ERA_OFFSET[era] + y_off
        if 1990 <= year <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{year:04d}-{mo:02d}-{d:02d}"
    return None


def _resolve_url(href: str, base: str) -> str:
    if not href:
        return base
    return urljoin(base, href.strip())


# ---------------------------------------------------------------------------
# Kind classification
# ---------------------------------------------------------------------------


def _classify_kind(text: str) -> str:
    """Map 処分内容 keywords → enforcement_kind (CHECK enum)."""
    t = text or ""
    if any(
        k in t for k in ("認定の取消", "認定取消", "許可の取消", "許可取消", "営業廃止", "廃止命令")
    ):
        return "license_revoke"
    if any(
        k in t
        for k in (
            "中止命令",
            "再発防止命令",
            "営業停止",
            "業務停止",
            "停止命令",
            "停止処分",
            "指示",
        )
    ):
        return "business_improvement"
    if "公示" in t or "指定" in t:
        return "other"
    return "other"


# ---------------------------------------------------------------------------
# Parser: simple table with [認定/業者名/年月日] (大阪/宮城/神奈川 daiko)
# ---------------------------------------------------------------------------


def _parse_table_with_company_and_date(
    soup: BeautifulSoup,
    *,
    authority: str,
    related_law: str,
    source_url: str,
    section_law_hint: str | None = None,
) -> list[EnfRow]:
    """Parse simple table rows where each row has:
    [認定番号 (optional), 業者名 (株式/有限/合同), 処分年月日, (optional: 処分内容)]
    """
    out: list[EnfRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if not cell_texts:
            continue
        # Skip header rows
        if any(
            (
                c == "認定"
                or c == "氏名又は名称"
                or c == "処分年月日"
                or c == "業者名"
                or c == "処分の年月日"
            )
            for c in cell_texts
        ):
            continue
        target_name = next(
            (t for t in cell_texts if any(s in t for s in ("株式会社", "有限会社", "合同会社"))),
            None,
        )
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        if not (target_name and date_text):
            continue
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        # Extract 認定番号
        ninteibango = next(
            (t for t in cell_texts if "号" in t and ("公安委員会" in t or "第" in t)),
            None,
        )
        # Extract 処分内容
        kind_text = next(
            (
                t
                for t in cell_texts
                if any(
                    k in t
                    for k in (
                        "指示",
                        "営業停止",
                        "営業廃止",
                        "停止命令",
                        "認定の取消",
                        "認定取消",
                        "許可の取消",
                        "許可取消",
                    )
                )
            ),
            None,
        )
        if kind_text is None:
            # Default for these pages: "指示" if no explicit kind given
            kind_text = "指示"
        kind = _classify_kind(kind_text)
        section = section_law_hint or related_law
        reason = f"{section}違反による行政処分（{kind_text}）"
        if ninteibango:
            reason += f" / 認定番号: {ninteibango[:80]}"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority=authority,
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=related_law[:500],
                source_url=source_url,
                extra={
                    "ninteibango": ninteibango,
                    "kind_text": kind_text,
                    "section_law": section,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 大阪府警 警備業 (table format)
# ---------------------------------------------------------------------------


def parse_osaka_keibi_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    return _parse_table_with_company_and_date(
        soup,
        authority="大阪府公安委員会",
        related_law=KEIBIGYOU,
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# Parser: 宮城県警 警備業
# ---------------------------------------------------------------------------


def parse_miyagi_keibi_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    return _parse_table_with_company_and_date(
        soup,
        authority="宮城県公安委員会",
        related_law=KEIBIGYOU,
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# Parser: 千葉県警 警備業 (no table — paragraphs)
# ---------------------------------------------------------------------------


_CHIBA_BLOCK_RE = re.compile(
    r"((?:株式会社|有限会社|合同会社)[^\n]+)\n"
    r"認定[:：]\s*([^\n]+?)(指示|営業停止|営業廃止|認定の取消|認定取消|"
    r"許可の取消|許可取消)\s*"
    r"([^\n]+?)(?:\n|$)",
    re.MULTILINE,
)


def parse_chiba_keibi_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    out: list[EnfRow] = []
    for m in _CHIBA_BLOCK_RE.finditer(text):
        name = _normalize(m.group(1))
        ninteibango = _normalize(m.group(2))
        kind_text = _normalize(m.group(3))
        date_part = _normalize(m.group(4))
        date_iso = _parse_date(date_part)
        if not date_iso:
            continue
        kind = _classify_kind(kind_text)
        reason = f"{KEIBIGYOU}違反による行政処分（{kind_text}） / 認定番号: {ninteibango[:80]}"
        out.append(
            EnfRow(
                target_name=name,
                issuance_date=date_iso,
                issuing_authority="千葉県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=KEIBIGYOU[:500],
                source_url=source_url,
                extra={
                    "ninteibango": ninteibango,
                    "kind_text": kind_text,
                    "section_law": KEIBIGYOU,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 静岡県警 警備業 (anchor list with "令和N年MM月DD日 業者名")
# ---------------------------------------------------------------------------


_SHIZUOKA_ANCHOR_RE = re.compile(
    r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)"
    r"(.+?)(?:\s*（PDF.*)?$"
)


def parse_shizuoka_keibi_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().endswith(".pdf"):
            continue
        txt = _normalize(a.get_text(" ", strip=True))
        # Heading area must mention 警備業 (some are 探偵 PDFs)
        if "公表基準" in txt or "kijun" in href.lower():
            continue
        m = _SHIZUOKA_ANCHOR_RE.search(txt)
        if not m:
            continue
        date_text = m.group(1)
        rest = m.group(2)
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        # Strip trailing 株式会社/有限会社 indicator if present
        rest = re.sub(r"（PDF.*$", "", rest).strip()
        # Filter to corporate names only
        if not any(s in rest for s in ("株式会社", "有限会社", "合同会社")):
            continue
        target_name = rest
        # Default to 警備業法; the page mixes 警備業 + 探偵業 sections.
        # We classify based on context (page heading) — defaults 警備業.
        # Use 'other' guess kind since per-PDF kind is in PDF body; we use
        # 'business_improvement' as the documented disposition type for
        # all entries on this page (per page intro: "営業停止/指示/取消").
        # Without per-PDF parse we conservatively classify as
        # 'business_improvement' since 4/5 are 指示/営業停止 typically.
        # For honesty we mark kind_text='処分（詳細はPDF参照）'.
        kind_text = "処分（詳細はPDF参照）"
        kind = "business_improvement"
        pdf_url = _resolve_url(href, source_url)
        reason = f"{KEIBIGYOU}違反による行政処分 / 詳細PDF: {pdf_url}"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="静岡県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=KEIBIGYOU[:500],
                source_url=source_url,
                extra={
                    "pdf_url": pdf_url,
                    "kind_text": kind_text,
                    "section_law": KEIBIGYOU,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 神奈川県警 運転代行 (table with explicit 指示 column)
# ---------------------------------------------------------------------------


def parse_kanagawa_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    return _parse_table_with_company_and_date(
        soup,
        authority="神奈川県公安委員会",
        related_law=DAIKO,
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# Parser: 奈良県警 運転代行 — text-based (operator name + date + kind)
# ---------------------------------------------------------------------------


_NARA_KIND_PATTERNS = [
    ("認定の取消", "license_revoke"),
    ("認定取消", "license_revoke"),
    ("営業停止", "business_improvement"),
    ("指示", "business_improvement"),
]


def parse_nara_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    """Nara publishes records inline as section-prefixed entries:
    認定取消処分がなされた自動車運転代行業者
      運転代行ヤマト(R8.2.26)(サイズ：58.95KB)
    営業停止処分がなされた自動車運転代行業者
      奈良運転代行Goo(R6.6.28)(サイズ：68.99KB)
      運転代行フルート(R6.7.22)...
    指示処分がなされた自動車運転代行業者
      運転代行一心(R6.5.1)...
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    text = soup.get_text(" ", strip=True)
    text = _normalize(text)

    # Find each section header and the slice up to the next section / end.
    sections = [
        ("認定取消", "license_revoke"),
        ("営業停止", "business_improvement"),
        ("指示処分", "business_improvement"),
    ]
    # Use canonical section header strings present in HTML
    header_map = {
        "認定取消処分がなされた自動車運転代行業者": "license_revoke",
        "営業停止処分がなされた自動車運転代行業者": "business_improvement",
        "指示処分がなされた自動車運転代行業者": "business_improvement",
    }
    # Locate header positions
    boundaries: list[tuple[int, str]] = []
    for hdr in header_map:
        idx = 0
        while True:
            pos = text.find(hdr, idx)
            if pos < 0:
                break
            boundaries.append((pos, hdr))
            idx = pos + len(hdr)
    boundaries.sort()
    if not boundaries:
        return out

    # Slice text per section
    seen_in_text: set[tuple[str, str, str]] = set()
    # Pattern: <name>(R<y>.<m>.<d>)(サイズ：...) — extract repeated occurrences
    entry_re = re.compile(
        r"([^\s（()]{2,40}?)\s*[(（]\s*[RＲ]\s*(\d{1,2})\s*[.．]\s*"
        r"(\d{1,2})\s*[.．]\s*(\d{1,2})\s*[)）]"
    )
    for i, (start, hdr) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        section_text = text[start + len(hdr) : end]
        kind_text = hdr.replace("処分がなされた自動車運転代行業者", "")
        kind = header_map[hdr]
        for m in entry_re.finditer(section_text):
            raw_name = _normalize(m.group(1))
            # Strip trailing 株式会社 / parenthetical fragments
            raw_name = re.sub(r"^(株式会社|有限会社|合同会社)\s*", "", raw_name) or raw_name
            # Reject obviously non-name fragments
            if len(raw_name) < 2 or raw_name in ("代行", "運転代行"):
                continue
            if any(stop in raw_name for stop in ("一覧", "規定", "基準", "サイズ", "について")):
                continue
            yr = 2018 + int(m.group(2))
            mo, d = int(m.group(3)), int(m.group(4))
            if not (1990 <= yr <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
                continue
            date_iso = f"{yr:04d}-{mo:02d}-{d:02d}"
            key = (raw_name, date_iso, kind_text)
            if key in seen_in_text:
                continue
            seen_in_text.add(key)
            reason = f"{DAIKO}違反による行政処分（{kind_text}）"
            out.append(
                EnfRow(
                    target_name=raw_name,
                    issuance_date=date_iso,
                    issuing_authority="奈良県公安委員会",
                    enforcement_kind=kind,
                    reason_summary=reason[:1500],
                    related_law_ref=DAIKO[:500],
                    source_url=source_url,
                    extra={"kind_text": kind_text, "section_law": DAIKO},
                )
            )
    return out


# ---------------------------------------------------------------------------
# Parser: 福井県警 運転代行 — table with [date / kind / 認定 / name / location]
# ---------------------------------------------------------------------------


def parse_fukui_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if not cell_texts:
            continue
        # Skip header
        if any(
            "処分年月日" in c or "処分内容" in c or "業者名" in c for c in cell_texts
        ) and not any(WAREKI_RE.search(c) for c in cell_texts):
            continue
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        kind_text = next(
            (
                t
                for t in cell_texts
                if any(k in t for k in ("指示", "営業停止", "認定の取消", "認定取消", "営業廃止"))
            ),
            None,
        )
        # Name: a cell that looks like a 運転代行 屋号 or 株式会社
        target_name = next(
            (
                t
                for t in cell_texts
                if (
                    ("代行" in t and len(t) <= 30 and "違反" not in t and "業者" not in t)
                    or any(s in t for s in ("株式会社", "有限会社", "合同会社"))
                )
            ),
            None,
        )
        if not (target_name and date_text and kind_text):
            continue
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        kind = _classify_kind(kind_text)
        reason = f"{DAIKO}違反による行政処分（{kind_text}）"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="福井県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={"kind_text": kind_text, "section_law": DAIKO},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 埼玉県警 運転代行 — table with [認定/業者名/年月日]
# ---------------------------------------------------------------------------


def parse_saitama_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    """Saitama publishes 運転代行 dispositions in a numbered table.

    Headers: 番号 / 認定番号 / 業者名 / 処分年月日
    Each row also carries an embedded link to the per-disposition PDF
    which holds 処分内容. The HTML body itself does not include kind, so
    we tag with 'business_improvement' (most 指示) and reason explicitly
    flags PDF-only detail.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if len(cell_texts) < 3:
            continue
        # Heuristic: name col contains 代行 keyword
        target_name = next(
            (
                t
                for t in cell_texts
                if "代行" in t
                and len(t) <= 30
                and "認定" not in t
                and "処分" not in t
                and "業者" not in t
            ),
            None,
        )
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        ninteibango = next(
            (t for t in cell_texts if t.startswith("第") and "号" in t),
            None,
        )
        if not (target_name and date_text):
            continue
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        kind_text = "処分（詳細はPDF参照）"
        kind = "business_improvement"
        # Try to recover PDF link if any.
        pdf_url = None
        for a in tr.find_all("a", href=True):
            if a["href"].lower().endswith(".pdf"):
                pdf_url = _resolve_url(a["href"], source_url)
                break
        reason = f"{DAIKO}違反による行政処分（指示処分等） / 認定番号: {ninteibango or '不明'}"
        if pdf_url:
            reason += f" / 詳細PDF: {pdf_url}"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="埼玉県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={
                    "ninteibango": ninteibango,
                    "pdf_url": pdf_url,
                    "section_law": DAIKO,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 北海道 運転代行 — table with [name / date / kind]
# ---------------------------------------------------------------------------


def parse_hokkaido_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    """Hokkaido (北海道知事 — not 公安委員会) publishes inline records:
    令和6年(2024年)9月 4日 指示処分(運転代行アンカー) (PDF 58.6KB)
    令和6年(2024年)9月19日 指示処分(アクティブ代行サービス) (PDF 61.7KB)
    令和7年(2025年)5月29日 指示処分(アクセス運転代行) (PDF 60.2KB)
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    text = _normalize(soup.get_text(" ", strip=True))

    # Pattern: 令和X年(YYYY年)M月D日 (指示|営業停止|認定取消|認定の取消)処分(NAME) (PDF size)
    block_re = re.compile(
        r"令和\s*(\d+|元)\s*年\s*[(（]?\s*(20\d{2})\s*年\s*[)）]?\s*"
        r"(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*"
        r"(指示|営業停止|認定の?取消|認定取消)\s*処分\s*[(（]\s*([^)）\s][^)）]*?)\s*[)）]"
    )
    seen: set[tuple[str, str, str]] = set()
    for m in block_re.finditer(text):
        yr = int(m.group(2))
        mo, d = int(m.group(3)), int(m.group(4))
        kind_text = _normalize(m.group(5))
        name = _normalize(m.group(6))
        if not (1990 <= yr <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            continue
        if not name or len(name) > 50:
            continue
        date_iso = f"{yr:04d}-{mo:02d}-{d:02d}"
        kind = _classify_kind(kind_text)
        key = (name, date_iso, kind_text)
        if key in seen:
            continue
        seen.add(key)
        reason = f"{DAIKO}違反による行政処分（{kind_text}）"
        out.append(
            EnfRow(
                target_name=name,
                issuance_date=date_iso,
                # Source page is 北海道庁 (知事) not 公安委員会; keep accurate
                issuing_authority="北海道知事",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={"kind_text": kind_text, "section_law": DAIKO},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 石川県警 運転代行 — table with header rows by year
# ---------------------------------------------------------------------------


def parse_ishikawa_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if len(cell_texts) < 3:
            continue
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        target_name = next(
            (
                t
                for t in cell_texts
                if "代行" in t and len(t) <= 30 and "業者" not in t and "処分" not in t
            ),
            None,
        )
        kind_text = next(
            (
                t
                for t in cell_texts
                if any(k in t for k in ("指示", "営業停止", "認定の取消", "認定取消", "営業廃止"))
            ),
            None,
        )
        ninteibango = next(
            (t for t in cell_texts if "公安委員会" in t and "号" in t),
            None,
        )
        if not (target_name and date_text and kind_text):
            continue
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        kind = _classify_kind(kind_text)
        reason = f"{DAIKO}違反による行政処分（{kind_text}） / 認定番号: {ninteibango or '不明'}"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="石川県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={
                    "ninteibango": ninteibango,
                    "kind_text": kind_text,
                    "section_law": DAIKO,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 山口県警 運転代行 — table with [date / name]
# ---------------------------------------------------------------------------


def parse_yamaguchi_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if not cell_texts:
            continue
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        target_name = next(
            (
                t
                for t in cell_texts
                if "代行" in t
                and len(t) <= 30
                and "業者" not in t
                and "処分" not in t
                and "県" not in t
            ),
            None,
        )
        kind_text = (
            next(
                (
                    t
                    for t in cell_texts
                    if any(
                        k in t for k in ("指示", "営業停止", "認定の取消", "認定取消", "営業廃止")
                    )
                ),
                None,
            )
            or "処分（詳細はPDF参照）"
        )
        if not (target_name and date_text):
            continue
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        kind = _classify_kind(kind_text)
        reason = f"{DAIKO}違反による行政処分（{kind_text}）"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="山口県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={"kind_text": kind_text, "section_law": DAIKO},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 熊本県警 運転代行 — table
# ---------------------------------------------------------------------------


def parse_kumamoto_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if not cell_texts:
            continue
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        target_name = next(
            (
                t
                for t in cell_texts
                if "代行" in t and len(t) <= 30 and "処分" not in t and "業者" not in t
            ),
            None,
        )
        kind_text = next(
            (
                t
                for t in cell_texts
                if any(k in t for k in ("指示", "営業停止", "認定の取消", "認定取消", "営業廃止"))
            ),
            None,
        )
        ninteibango = next(
            (t for t in cell_texts if "公安委員会" in t and "号" in t),
            None,
        )
        if not (target_name and date_text and kind_text):
            continue
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        kind = _classify_kind(kind_text)
        reason = f"{DAIKO}違反による行政処分（{kind_text}） / 認定番号: {ninteibango or '不明'}"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="熊本県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={
                    "ninteibango": ninteibango,
                    "kind_text": kind_text,
                    "section_law": DAIKO,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 京都府警 運転代行 — text-based with kind column
# ---------------------------------------------------------------------------


def parse_kyoto_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if not cell_texts:
            continue
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        target_name = next(
            (
                t
                for t in cell_texts
                if (
                    ("代行" in t and len(t) <= 30 and "処分" not in t and "業者" not in t)
                    or any(s in t for s in ("株式会社", "有限会社", "合同会社"))
                )
            ),
            None,
        )
        kind_text = next(
            (
                t
                for t in cell_texts
                if any(k in t for k in ("指示処分", "営業停止処分", "認定取消"))
            ),
            None,
        )
        if not (target_name and kind_text):
            continue
        # Kyoto omits per-record date in summary table — fall back to
        # most-recent publication date on page (令和7年12月9日)
        date_iso = _parse_date(date_text) if date_text else None
        if not date_iso:
            # Skip entries lacking concrete date — Kyoto summary is
            # incomplete; we'd need a per-PDF parse for date precision.
            continue
        kind = _classify_kind(kind_text)
        reason = f"{DAIKO}違反による行政処分（{kind_text}）"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="京都府公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={"kind_text": kind_text, "section_law": DAIKO},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 福岡県警 運転代行 — anchor-based PDF list
# ---------------------------------------------------------------------------


_FUKUOKA_DAIKO_RE = re.compile(
    r"(令和\s*\d+\s*年\s*\d+\s*月\s*\d+\s*日)?\s*"
    r"(.+?代行|.*?運転代行)?"
)


def parse_fukuoka_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    """Fukuoka 運転代行 page: HTML lists rows of [name / date / PDF link]."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if not cell_texts:
            continue
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        target_name = next(
            (
                t
                for t in cell_texts
                if "代行" in t and len(t) <= 30 and "処分" not in t and "業者" not in t
            ),
            None,
        )
        if not (target_name and date_text):
            continue
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        kind_text = (
            next(
                (
                    t
                    for t in cell_texts
                    if any(
                        k in t for k in ("指示", "営業停止", "認定の取消", "認定取消", "営業廃止")
                    )
                ),
                None,
            )
            or "処分（詳細はPDF参照）"
        )
        kind = _classify_kind(kind_text)
        # Recover PDF link
        pdf_url = None
        for a in tr.find_all("a", href=True):
            if a["href"].lower().endswith(".pdf"):
                pdf_url = _resolve_url(a["href"], source_url)
                break
        reason = f"{DAIKO}違反による行政処分（{kind_text}）"
        if pdf_url:
            reason += f" / 詳細PDF: {pdf_url}"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="福岡県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={
                    "pdf_url": pdf_url,
                    "kind_text": kind_text,
                    "section_law": DAIKO,
                },
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 青森県警 運転代行 — inline list "令和７年６月26日 認定取消処分（マルセ代行社）（PDF:27KB）"
# ---------------------------------------------------------------------------


def parse_aomori_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    text = _normalize(soup.get_text(" ", strip=True))
    # Pattern: 令和X年M月D日 (認定取消|認定の取消|営業停止|指示)処分(NAME)(PDF:..KB)
    block_re = re.compile(
        r"令和\s*(\d+|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*"
        r"(認定の?取消|営業停止|指示|営業廃止)\s*処分\s*[(（]\s*([^)）][^)）]*?)\s*[)）]"
    )
    seen: set[tuple[str, str, str]] = set()
    for m in block_re.finditer(text):
        y_raw = m.group(1)
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            continue
        yr = 2018 + y_off
        mo, d = int(m.group(2)), int(m.group(3))
        kind_text = _normalize(m.group(4))
        name = _normalize(m.group(5))
        # Filter out summary fragments
        if "PDF" in name and len(name) < 6:
            continue
        # Strip inline footnote markers
        name = re.sub(r"\s*PDF:.*$", "", name).strip()
        if not (1990 <= yr <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            continue
        if not name or len(name) > 60:
            continue
        date_iso = f"{yr:04d}-{mo:02d}-{d:02d}"
        kind = _classify_kind(kind_text)
        key = (name, date_iso, kind_text)
        if key in seen:
            continue
        seen.add(key)
        reason = f"{DAIKO}違反による行政処分（{kind_text}）"
        out.append(
            EnfRow(
                target_name=name,
                issuance_date=date_iso,
                issuing_authority="青森県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={"kind_text": kind_text, "section_law": DAIKO},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 秋田県警 運転代行 — inline list "令和８年３月５日付け ファースト代行 [60KB]"
# ---------------------------------------------------------------------------


def parse_akita_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    text = _normalize(soup.get_text(" ", strip=True))
    # Pattern: 令和X年M月D日付け <NAME> [SIZE]
    # Names can include 株式会社 / 有限会社 / 屋号
    block_re = re.compile(
        r"令和\s*(\d+|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*付け?\s+"
        r"([^\s\[【]+(?:\s+[^\s\[【]+)?)\s*[\[【]"
    )
    seen: set[tuple[str, str]] = set()
    for m in block_re.finditer(text):
        y_raw = m.group(1)
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            continue
        yr = 2018 + y_off
        mo, d = int(m.group(2)), int(m.group(3))
        name = _normalize(m.group(4))
        # Drop trailing PDF/size hints
        name = re.sub(r"\s*PDF.*$", "", name).strip()
        # Reject obvious garbage
        if not name or len(name) > 60:
            continue
        if name in ("代行", "運転代行"):
            continue
        if not (1990 <= yr <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            continue
        date_iso = f"{yr:04d}-{mo:02d}-{d:02d}"
        key = (name, date_iso)
        if key in seen:
            continue
        seen.add(key)
        # Akita doesn't list kind_text inline — default to license/business action;
        # fall back to "other" if uncertain.
        reason = f"{DAIKO}違反による行政処分（公表対象）"
        out.append(
            EnfRow(
                target_name=name,
                issuance_date=date_iso,
                issuing_authority="秋田県公安委員会",
                enforcement_kind="other",
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={"kind_text": "公表対象処分", "section_law": DAIKO},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 富山県警 運転代行 — single-record PDF 行政処分簿
# ---------------------------------------------------------------------------


def _parse_pref_pol_pdf(pdf_text: str, source_url: str, authority: str) -> list[EnfRow]:
    """Generic 行政処分簿 別記様式第２号 PDF parser used for Toyama / Kagawa /
    similar single-record公安委員会 PDFs.
    """
    out: list[EnfRow] = []
    text = _normalize(pdf_text)
    # Name extraction — handle both "名 称 又 は 記 号" with surrounding whitespace
    name_m = re.search(
        r"名\s*称\s*又\s*は\s*記\s*号\s+([^\s][^\n\r]{0,40})",
        text,
    )
    date_m = WAREKI_RE.search(text) or SEIREKI_RE.search(text)
    kind_m = re.search(
        r"処\s*分\s*内\s*容\s+(認定の取消し|認定の取消|営業停止命令|営業廃止命令|"
        r"営業停止|営業廃止|指示処分|指示)",
        text,
    )
    if not (name_m and date_m and kind_m):
        return out
    name = _normalize(name_m.group(1)).strip()
    # Strip possible trailing 認定番号 fragments
    name = re.split(r"\s+主たる", name)[0].strip()
    date_iso = _parse_date(date_m.group(0))
    kind_text = _normalize(kind_m.group(1))
    if not date_iso or not name or len(name) > 60:
        return out
    kind = _classify_kind(kind_text)
    reason = f"{DAIKO}違反による行政処分（{kind_text}）"
    out.append(
        EnfRow(
            target_name=name,
            issuance_date=date_iso,
            issuing_authority=authority,
            enforcement_kind=kind,
            reason_summary=reason[:1500],
            related_law_ref=DAIKO[:500],
            source_url=source_url,
            extra={"kind_text": kind_text, "section_law": DAIKO, "format": "pdf"},
        )
    )
    return out


def parse_toyama_daiko_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    return _parse_pref_pol_pdf(pdf_text, source_url, "富山県公安委員会")


def parse_kagawa_daiko_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    return _parse_pref_pol_pdf(pdf_text, source_url, "香川県公安委員会")


def parse_saga_chiji_daiko_pdf(pdf_text: str, source_url: str) -> list[EnfRow]:
    """佐賀県知事 自動車運転代行業 行政処分票 (別記様式５).

    Layout differs from 別記様式２号 used by 公安委員会 — the leftmost
    "被処分者" label is split character-by-character across multiple rows
    (被 / 処 / 分 / 者), so the generic helper grabs garbage like '分' as
    the name. We instead find the line containing the value to the right of
    the "の名称又は記号" label cell.
    """
    out: list[EnfRow] = []
    text = pdf_text
    # The line PRECEDING "の名称又は記号" carries the value (PDF layout puts
    # value on line indented far right; pdftotext folds that to the prior line).
    lines = text.splitlines()
    name = None
    for i, ln in enumerate(lines):
        if "の名称又は記号" in ln:
            # value sits on the line immediately above
            if i >= 1:
                cand = _normalize(lines[i - 1]).strip()
                # Strip leading '処' / '被' / '分' single-char labels
                cand = re.sub(r"^[被処分者\s]{1,4}", "", cand).strip()
                # Drop trailing 認定番号-like digits
                cand = re.split(r"\s+佐賀県公安委員会", cand)[0].strip()
                if 2 <= len(cand) <= 60:
                    name = cand
            break
    if not name:
        return out
    text_norm = _normalize(text)
    date_m = WAREKI_RE.search(text_norm) or SEIREKI_RE.search(text_norm)
    kind_m = re.search(
        r"処\s*分\s*内\s*容\s+(認定の取消し|認定の取消|営業停止命令|営業廃止命令|"
        r"営業停止|営業廃止|指示処分|指示)",
        text_norm,
    )
    if not (date_m and kind_m):
        return out
    date_iso = _parse_date(date_m.group(0))
    kind_text = _normalize(kind_m.group(1))
    if not date_iso:
        return out
    kind = _classify_kind(kind_text)
    reason_m = re.search(
        r"処\s*分\s*理\s*由\s+([^\n\r]{1,400}(?:\n\s*[^\n\r]{1,200}){0,4})",
        text_norm,
    )
    reason = f"{DAIKO}違反による行政処分（{kind_text}）" + (
        f"; {_normalize(reason_m.group(1)).strip()[:1000]}" if reason_m else ""
    )
    out.append(
        EnfRow(
            target_name=name,
            issuance_date=date_iso,
            issuing_authority="佐賀県知事",
            enforcement_kind=kind,
            reason_summary=reason[:1500],
            related_law_ref=DAIKO[:500],
            source_url=source_url,
            extra={
                "kind_text": kind_text,
                "section_law": DAIKO,
                "format": "pdf",
                "issuer_type": "知事",
            },
        )
    )
    return out


# ---------------------------------------------------------------------------
# Parser: 茨城県警 運転代行 — clean table [処分年月 / 処分内容 / 認定番号 / 業者名 / 所在地 / 詳細]
# ---------------------------------------------------------------------------


def parse_ibaraki_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    seen: set[tuple[str, str, str]] = set()
    # 処分年月 may be 令和7年12月 (no day) — accept that form too.
    YM_RE = re.compile(r"令和\s*(\d+|元)\s*年\s*(\d{1,2})\s*月")
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if len(cell_texts) < 4:
            continue
        # Skip header
        if any("処分年月" in c or c == "認定番号" or c == "詳細" for c in cell_texts) and not any(
            WAREKI_RE.search(c) or YM_RE.search(c) for c in cell_texts
        ):
            continue
        date_text = next(
            (
                c
                for c in cell_texts
                if WAREKI_RE.search(c) or SEIREKI_RE.search(c) or YM_RE.search(c)
            ),
            None,
        )
        kind_text = next(
            (
                c
                for c in cell_texts
                if any(k in c for k in ("営業停止", "認定取消", "認定の取消", "営業廃止", "指示"))
                and len(c) <= 12
            ),
            None,
        )
        target_name = next(
            (
                c
                for c in cell_texts
                if (
                    ("代行" in c or any(s in c for s in ("株式会社", "有限会社", "合同会社")))
                    and len(c) <= 40
                    and "業者" not in c
                    and "認定" not in c
                    and "PDF" not in c
                )
            ),
            None,
        )
        if not (date_text and kind_text and target_name):
            continue
        parsed = _parse_date(date_text)
        if not parsed:
            ym = YM_RE.search(date_text)
            if ym:
                y_raw = ym.group(1)
                y_off = 1 if y_raw == "元" else int(y_raw)
                yr, mo = 2018 + y_off, int(ym.group(2))
                parsed = f"{yr:04d}-{mo:02d}-01"
        if not parsed:
            continue
        kind = _classify_kind(kind_text)
        key = (target_name, parsed, kind_text)
        if key in seen:
            continue
        seen.add(key)
        reason = f"{DAIKO}違反による行政処分（{kind_text}）"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=parsed,
                issuing_authority="茨城県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={"kind_text": kind_text, "section_law": DAIKO},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 長崎県警 運転代行 — inline list "令和６年６月１２日 クレア運転代行"
# ---------------------------------------------------------------------------


def parse_nagasaki_daiko_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    text = _normalize(soup.get_text(" ", strip=True))
    # Pattern: 令和X年M月D日 <NAME> (NAME may contain 代行 or 運転代行)
    block_re = re.compile(
        r"令和\s*(\d+|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s+"
        r"([^\s\d令和。。]+(?:代行|運転代行|株式会社[^\s]+|有限会社[^\s]+))"
    )
    seen: set[tuple[str, str]] = set()
    for m in block_re.finditer(text):
        y_raw = m.group(1)
        try:
            y_off = 1 if y_raw == "元" else int(y_raw)
        except ValueError:
            continue
        yr = 2018 + y_off
        mo, d = int(m.group(2)), int(m.group(3))
        name = _normalize(m.group(4))
        if not (1990 <= yr <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            continue
        if not name or len(name) > 40:
            continue
        date_iso = f"{yr:04d}-{mo:02d}-{d:02d}"
        key = (name, date_iso)
        if key in seen:
            continue
        seen.add(key)
        # No kind text inline — default to "other" (公表対象だが処分種別は省略)
        reason = f"{DAIKO}違反による行政処分（公表対象）"
        out.append(
            EnfRow(
                target_name=name,
                issuance_date=date_iso,
                issuing_authority="長崎県公安委員会",
                enforcement_kind="other",
                reason_summary=reason[:1500],
                related_law_ref=DAIKO[:500],
                source_url=source_url,
                extra={"kind_text": "公表対象処分", "section_law": DAIKO},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Parser: 兵庫県公安委員会 警備業 — table [認定番号 / 処分内容 / 氏名又は名称 / 処分年月日 / 詳細]
# ---------------------------------------------------------------------------


def parse_hyogo_keibi_html(html: str, source_url: str) -> list[EnfRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[EnfRow] = []
    seen: set[tuple[str, str, str]] = set()
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if len(cell_texts) < 4:
            continue
        # Skip header
        if any("認定の番号" in c or "処分の年月日" in c for c in cell_texts) and not any(
            WAREKI_RE.search(c) for c in cell_texts
        ):
            continue
        date_text = next(
            (c for c in cell_texts if WAREKI_RE.search(c) or SEIREKI_RE.search(c)), None
        )
        kind_text = next(
            (
                c
                for c in cell_texts
                if any(k in c for k in ("営業停止", "認定取消", "認定の取消", "営業廃止", "指示"))
                and len(c) <= 12
            ),
            None,
        )
        target_name = next(
            (
                c
                for c in cell_texts
                if any(s in c for s in ("株式会社", "有限会社", "合同会社")) and len(c) <= 40
            ),
            None,
        )
        if not (date_text and kind_text and target_name):
            continue
        date_iso = _parse_date(date_text)
        if not date_iso:
            continue
        kind = _classify_kind(kind_text)
        key = (target_name, date_iso, kind_text)
        if key in seen:
            continue
        seen.add(key)
        reason = f"{KEIBIGYOU}違反による行政処分（{kind_text}）"
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="兵庫県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=KEIBIGYOU[:500],
                source_url=source_url,
                extra={"kind_text": kind_text, "section_law": KEIBIGYOU},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Source dispatch
# ---------------------------------------------------------------------------


PARSERS = {
    "osaka_keibi_html": parse_osaka_keibi_html,
    "miyagi_keibi_html": parse_miyagi_keibi_html,
    "chiba_keibi_html": parse_chiba_keibi_html,
    "shizuoka_keibi_html": parse_shizuoka_keibi_html,
    "kanagawa_daiko_html": parse_kanagawa_daiko_html,
    "nara_daiko_html": parse_nara_daiko_html,
    "fukui_daiko_html": parse_fukui_daiko_html,
    "saitama_daiko_html": parse_saitama_daiko_html,
    "hokkaido_daiko_html": parse_hokkaido_daiko_html,
    "ishikawa_daiko_html": parse_ishikawa_daiko_html,
    "yamaguchi_daiko_html": parse_yamaguchi_daiko_html,
    "kumamoto_daiko_html": parse_kumamoto_daiko_html,
    "kyoto_daiko_html": parse_kyoto_daiko_html,
    "fukuoka_daiko_html": parse_fukuoka_daiko_html,
    "aomori_daiko_html": parse_aomori_daiko_html,
    "akita_daiko_html": parse_akita_daiko_html,
    "toyama_daiko_pdf": parse_toyama_daiko_pdf,
    "kagawa_daiko_pdf": parse_kagawa_daiko_pdf,
    "saga_chiji_daiko_pdf": parse_saga_chiji_daiko_pdf,
    "ibaraki_daiko_html": parse_ibaraki_daiko_html,
    "nagasaki_daiko_html": parse_nagasaki_daiko_html,
    "hyogo_keibi_html": parse_hyogo_keibi_html,
}


# Hosts whose TLS chain is misconfigured (intermediate cert missing). Public
# pages, no creds — verify=False is acceptable here; we only read static HTML.
SSL_BYPASS_HOSTS = {
    "www.police.pref.nagasaki.jp",
}


def _fetch_with_ssl_bypass(url: str) -> tuple[int, bytes, dict[str, str]]:
    """Fallback fetch using httpx with verify=False for hosts on SSL_BYPASS_HOSTS.

    Polite: 1 req/sec across the whole script via the parent HttpClient pacing
    is bypassed here, but these are one-shot reads per source, so the actual
    request rate is well below the 1 req/sec cap.
    """
    import httpx

    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.5"}
    r = httpx.get(url, verify=False, follow_redirects=True, timeout=15.0, headers=headers)
    return r.status_code, r.content, dict(r.headers)


def fetch_source(http: HttpClient, src: Source) -> list[EnfRow]:
    # PDFs need a higher byte cap and pdftotext extraction.
    is_pdf = src.url.lower().endswith(".pdf") or src.parser.endswith("_pdf")
    host = urlparse(src.url).netloc
    if host in SSL_BYPASS_HOSTS:
        try:
            status, body, headers = _fetch_with_ssl_bypass(src.url)
        except Exception as exc:
            _LOG.warning("[%s] ssl-bypass fetch failed url=%s err=%s", src.parser, src.url, exc)
            return []
        if not (200 <= status < 300):
            _LOG.warning("[%s] ssl-bypass non-2xx status=%s url=%s", src.parser, status, src.url)
            return []

        # Synthesize a minimal FetchResult-like result
        class _R:
            pass

        res = _R()
        res.ok = True
        res.status = status
        res.body = body
        # Decode text honoring server charset where present
        ct = headers.get("content-type", "")
        encoding = None
        for part in ct.split(";"):
            part = part.strip().lower()
            if part.startswith("charset="):
                encoding = part[len("charset=") :]
                break
        try:
            res.text = body.decode(encoding or "utf-8", errors="replace")
        except LookupError:
            res.text = body.decode("utf-8", errors="replace")
    elif is_pdf:
        from scripts.lib.http import PDF_MAX_BYTES

        res = http.get(src.url, max_bytes=PDF_MAX_BYTES)
    else:
        res = http.get(src.url)
    if not res.ok:
        _LOG.warning("[%s] fetch failed status=%s url=%s", src.parser, res.status, src.url)
        return []
    parser = PARSERS.get(src.parser)
    if not parser:
        _LOG.warning("unknown parser %s", src.parser)
        return []
    try:
        if is_pdf:
            import subprocess
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(res.body)
                tmp_path = f.name
            try:
                proc = subprocess.run(
                    ["pdftotext", "-layout", tmp_path, "-"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                rows = parser(proc.stdout, src.url)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        else:
            rows = parser(res.text, src.url)
    except Exception as exc:  # broad — parser robustness
        _LOG.error("[%s] parser failed: %s", src.parser, exc)
        return []
    # Dedup within source.
    seen: set[tuple[str, str, str]] = set()
    deduped: list[EnfRow] = []
    for r in rows:
        key = (r.target_name, r.issuance_date, r.issuing_authority)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug8(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def ensure_tables(conn: sqlite3.Connection) -> None:
    for tbl in ("am_entities", "am_enforcement_detail"):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (tbl,),
        ).fetchone()
        if not row:
            raise SystemExit(f"missing table '{tbl}' — apply migrations first")


def existing_dedup_keys(
    conn: sqlite3.Connection,
) -> set[tuple[str, str, str]]:
    """Return existing (target_name, issuance_date, issuing_authority) tuples
    for pref-police-style enforcement records so reruns are idempotent.

    Includes 公安委員会 / 警察庁 / 警視庁 AND 知事 (Hokkaido & Saga 自動車運転代行
    are issued by 知事, not 公安委員会).
    """
    out: set[tuple[str, str, str]] = set()
    cur = conn.execute(
        "SELECT target_name, issuance_date, issuing_authority "
        "FROM am_enforcement_detail "
        "WHERE issuing_authority LIKE ? "
        "   OR issuing_authority LIKE ? "
        "   OR issuing_authority LIKE ? "
        "   OR issuing_authority LIKE ? ",
        (
            "%公安委員会%",
            "%警察庁%",
            "%警視庁%",
            "%知事%",
        ),
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
        ) VALUES (?, 'enforcement', 'pref_police_kouan', NULL,
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
            primary_name[:500],
            url,
            domain,
            now_iso,
            raw_json,
        ),
    )


def insert_enforcement(
    conn: sqlite3.Connection,
    entity_id: str,
    row: EnfRow,
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
    limit: int | None = None,
    batch_size: int = 50,
) -> tuple[int, int, int]:
    """Insert rows in BEGIN IMMEDIATE blocks of ``batch_size`` for low
    contention with parallel writers. Returns (inserted, dup_db, dup_batch).
    """
    if not rows:
        return 0, 0, 0
    db_keys = existing_dedup_keys(conn)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = 0
    dup_db = 0
    dup_batch = 0

    chunks: list[list[EnfRow]] = []
    cur_chunk: list[EnfRow] = []
    for r in rows:
        cur_chunk.append(r)
        if len(cur_chunk) >= batch_size:
            chunks.append(cur_chunk)
            cur_chunk = []
    if cur_chunk:
        chunks.append(cur_chunk)

    for chunk_idx, chunk in enumerate(chunks):
        if limit is not None and inserted >= limit:
            break
        try:
            conn.execute("BEGIN IMMEDIATE")
            for idx, r in enumerate(chunk, 1):
                if limit is not None and inserted >= limit:
                    break
                key = (r.target_name, r.issuance_date, r.issuing_authority)
                if key in db_keys:
                    dup_db += 1
                    continue
                if key in batch_keys:
                    dup_batch += 1
                    continue
                batch_keys.add(key)
                seq = _slug8(
                    f"{r.target_name}|{r.issuance_date}|{r.issuing_authority}|{chunk_idx}|{idx}"
                )
                canonical_id = f"AM-ENF-PREFPOL-{r.issuance_date.replace('-', '')}-{seq}"
                primary_name = f"{r.target_name} ({r.issuance_date}) - {r.issuing_authority}"
                raw_json = json.dumps(
                    {
                        "target_name": r.target_name,
                        "issuance_date": r.issuance_date,
                        "issuing_authority": r.issuing_authority,
                        "enforcement_kind": r.enforcement_kind,
                        "related_law_ref": r.related_law_ref,
                        "reason_summary": r.reason_summary,
                        "source_url": r.source_url,
                        "extra": r.extra or {},
                        "source_attribution": r.issuing_authority,
                        "license": ("都道府県警察 / 公安委員会 公表資料（出典明記で転載引用可）"),
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
                    insert_enforcement(conn, canonical_id, r, now_iso)
                    inserted += 1
                except sqlite3.Error as exc:
                    _LOG.error(
                        "DB error name=%r date=%s: %s",
                        r.target_name,
                        r.issuance_date,
                        exc,
                    )
                    continue
            conn.commit()
        except sqlite3.Error as exc:
            _LOG.error("BEGIN/commit failed chunk=%d: %s", chunk_idx, exc)
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
    return inserted, dup_db, dup_batch


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--limit", type=int, default=None, help="Hard cap on inserted rows (default: no cap)"
    )
    ap.add_argument(
        "--source-filter",
        type=str,
        default=None,
        help="Only run sources whose parser name matches this substring (debug)",
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

    all_rows: list[EnfRow] = []
    per_source_count: dict[str, int] = {}
    for src in SOURCES:
        if args.source_filter and args.source_filter not in src.parser:
            continue
        rows = fetch_source(http, src)
        per_source_count[f"{src.prefecture}/{src.parser}"] = len(rows)
        _LOG.info("[%s] %s: %d rows", src.prefecture, src.parser, len(rows))
        all_rows.extend(rows)

    _LOG.info("total parsed rows=%d (sources=%d)", len(all_rows), len(SOURCES))

    if args.dry_run:
        for r in all_rows[:30]:
            _LOG.info(
                "sample: name=%r date=%s auth=%s kind=%s law=%s",
                r.target_name,
                r.issuance_date,
                r.issuing_authority,
                r.enforcement_kind,
                r.related_law_ref,
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
        limit=args.limit,
    )
    # Per-authority + per-law breakdown for caller report
    auth_counts: dict[str, int] = {}
    law_counts: dict[str, int] = {}
    for r in all_rows:
        auth_counts[r.issuing_authority] = auth_counts.get(r.issuing_authority, 0) + 1
        law_counts[r.related_law_ref] = law_counts.get(r.related_law_ref, 0) + 1
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
        f"PrefPolice 公安委員会 ingest: parsed={len(all_rows)} "
        f"inserted={inserted} dup_db={dup_db} dup_batch={dup_batch}"
    )
    print("breakdown by 都道府県警察:")
    for k in sorted(per_source_count.keys()):
        print(f"  {k}: parsed={per_source_count[k]}")
    print(f"breakdown by issuing_authority: {json.dumps(auth_counts, ensure_ascii=False)}")
    print(f"breakdown by 法: {json.dumps(law_counts, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
