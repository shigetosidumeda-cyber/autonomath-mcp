#!/usr/bin/env python3
"""Ingest 警察庁 / 都道府県警察 公安委員会 行政処分・公示 records into
``am_enforcement_detail``.

Background:
  Police-issued enforcement / publication records under five flagship laws:

    1. 暴力団員による不当な行為の防止等に関する法律 (暴対法) — 中止命令/再発防止命令
    2. 古物営業法 — 古物商等の営業停止命令、許可取消し
    3. 風俗営業等の規制及び業務の適正化等に関する法律 (風適法) — 営業停止命令、
       許可取消し、第41条第2項に基づく公示等
    4. 警備業法 — 警備業者に対する指示、営業停止命令、認定の取消し、
       第50条第2項に基づく公示
    5. 銃砲刀剣類所持等取締法 — 所持許可の取消し等

  Reality check (verified 2026-04-25):
    Per-record disposition lists across 47 prefectural police are extremely
    sparse — most prefectures publish only the 処分基準 (criteria) without
    naming individual 業者. The handful of prefectures that DO list named
    cases (Hyogo /sc/order.htm + Hyogo /sc/koji/index.htm) yield <30 rows
    in total. This ingest harvests those primary-source records honestly
    rather than synthesizing aggregate stats as if they were per-record
    dispositions (see `feedback_no_fake_data.md`).

  Approach:
    - Walk a curated SOURCES list of police-site pages that are confirmed
      to contain *named* business entities + date + disposition kind.
    - Two parsers:
        * `hyogo_order_pdf` — extracts the structured "認定証・届出証明書番号 /
          氏名又は名称 / 処分年月日 / 処分内容 / 根拠法令" pattern from the
          Hyogo 警備業法 行政処分 PDF series.
        * `hyogo_koji_html` — parses the inline HTML table in
          /sc/koji/index.htm (特例施設占有者の指定 — this is a 公示 not a
          punishment, so we record `enforcement_kind='other'` with
          reason_summary explaining it is 公示 not 処分).
        * `aichi_kouhyou_html` — Aichi 安全なまちづくり条例 第32条第6項 公表
          (currently empty, but parser is forward-compatible).
        * `tokyo_shobun_html` — 警視庁 性風俗 / 風適 第41条第2項 公表
          (currently empty, but parser is forward-compatible).

Schema mapping:
    - enforcement_kind:
        * 営業停止 / 営業の停止命令          → 'business_improvement'
        * 中止命令 / 再発防止命令             → 'business_improvement'
        * 指示                                → 'business_improvement'
        * 許可の取消 / 認定の取消             → 'license_revoke'
        * 廃止命令                            → 'license_revoke'
        * 公示 (eg 風適41-2 / 警備50-2 / 特例施設占有者) → 'other'
    - issuing_authority: '{prefecture}公安委員会' or '警察庁'
    - related_law_ref: full statute name; multiple laws joined with ' / '
    - amount_yen: NULL (police orders rarely include monetary fines in
      the disposition publication; criminal fines are 検察 territory).

Parallel-write:
    BEGIN IMMEDIATE + busy_timeout=300000 (CLAUDE.md §5).

Dedup:
    (issuing_authority, issuance_date, target_name) tuple, both DB and batch.

CLI:
    python scripts/ingest/ingest_enforcement_npa.py \\
        [--db autonomath.db] [--dry-run] [--verbose] [--limit 200]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
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

import contextlib  # noqa: E402  (sys.path manipulation precedes)

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.npa")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
PDF_MAX_BYTES = 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Source:
    prefecture: str  # 兵庫県 / 東京都 / 大阪府 / etc.
    authority: str  # 兵庫県公安委員会 / 警視庁 / etc.
    url: str
    fmt: str  # 'html' | 'pdf' | 'html_with_pdfs'
    parser: str  # parser hint
    note: str = ""


@dataclass
class EnfRow:
    target_name: str
    issuance_date: str  # ISO yyyy-mm-dd
    issuing_authority: str
    enforcement_kind: str  # checked against am_enforcement_detail CHECK
    reason_summary: str
    related_law_ref: str
    source_url: str
    extra: dict | None = None


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------


SOURCES: list[Source] = [
    # Hyogo: confirmed primary 警備業法 行政処分 PDFs (2 records as of 2026-04-25)
    Source(
        "兵庫県",
        "兵庫県公安委員会",
        "https://www.police.pref.hyogo.lg.jp/sc/order.htm",
        "html_with_pdfs",
        "hyogo_order_html",
        note="兵庫県公安委員会 警備業法 行政処分公表",
    ),
    # Hyogo: 公安委員会 公示 (特例施設占有者の指定 + 風適法41-2 + 警備業50-2 + 道交法)
    Source(
        "兵庫県",
        "兵庫県公安委員会",
        "https://www.police.pref.hyogo.lg.jp/sc/koji/index.htm",
        "html",
        "hyogo_koji_html",
        note="兵庫県公安委員会 公示一覧 (特例施設占有者の指定等)",
    ),
    # Aichi: 安全なまちづくり条例 第32条第6項 公表 (currently empty,
    #         forward-compatible parser)
    Source(
        "愛知県",
        "愛知県公安委員会",
        "https://www.pref.aichi.jp/police/anzen/anmachi/kouhyou1.html",
        "html",
        "aichi_kouhyou_html",
        note="愛知県安全なまちづくり条例第32条第6項公表",
    ),
    # Tokyo: 性風俗営業等 場所提供 規制条例 第2条の10第3項 公表 (currently empty)
    Source(
        "東京都",
        "東京都公安委員会",
        "https://www.keishicho.metro.tokyo.lg.jp/about_mpd/keiyaku_horei_kohyo/oshirase/shobun.html",
        "html",
        "tokyo_shobun_html",
        note="性風俗営業等 場所提供 規制条例 第2条の10第3項 公表",
    ),
]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


WAREKI_RE = re.compile(
    r"(令和|平成|昭和|R|H|S)\s*(\d+|元)\s*[年.\-．／/]\s*"
    r"(\d{1,2})\s*[月.\-．／/]\s*(\d{1,2})\s*日?"
)
SEIREKI_RE = re.compile(r"(20\d{2}|19\d{2})\s*[年.\-／/]\s*(\d{1,2})\s*[月.\-／/]\s*(\d{1,2})")
ERA_OFFSET = {
    "令和": 2018,
    "R": 2018,
    "平成": 1988,
    "H": 1988,
    "昭和": 1925,
    "S": 1925,
}


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


# ---------------------------------------------------------------------------
# Parser: hyogo_order_html
#   Page lists 警備業法 / 探偵業法 行政処分 — table rows + PDF links.
#   Each PDF is structured 行政処分公表書 with target/date/kind/law fields.
# ---------------------------------------------------------------------------


def _resolve_url(href: str, base: str) -> str:
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        host = urlparse(base).netloc
        return f"https://{host}{href}"
    base_dir = base.rsplit("/", 1)[0] + "/"
    return base_dir + href


def _classify_kind(text: str) -> str:
    """Map 処分内容 keywords → enforcement_kind (matches CHECK constraint)."""
    t = text or ""
    if any(k in t for k in ("認定の取消", "許可の取消", "廃止命令")):
        return "license_revoke"
    if any(k in t for k in ("中止命令", "再発防止命令", "営業停止", "停止命令", "指示")):
        return "business_improvement"
    if "公示" in t or "指定" in t:
        return "other"
    return "other"


def parse_hyogo_order_html(html: str, source_url: str, http: HttpClient) -> list[EnfRow]:
    """Parse Hyogo 警備業法 / 探偵業法 行政処分 list HTML.

    The HTML lists rows inline; we cross-reference each row against the
    linked PDF for full detail (including 根拠法令).
    """
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    # The page has multiple sections; rows of interest contain at least a
    # 認定の番号 cell and a 株式会社 / 有限会社 / 合同会社 / 個人 name cell.
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
        if not any("公安委員会" in t for t in cell_texts):
            continue
        # Pattern: [認定番号, 処分内容, 氏名又は名称, 処分の年月日, 詳細(PDF)]
        # Find the columns.
        if len(cell_texts) < 4:
            continue
        # Heuristic: column with "公安委員会 第..." is 認定番号
        ninteibango = next(
            (t for t in cell_texts if "公安委員会" in t and "号" in t),
            None,
        )
        if not ninteibango:
            continue
        # The name column contains 株式会社/有限会社/合同会社; date column
        # contains 令和/平成; kind column contains 指示/営業停止/etc.
        target_name = next(
            (t for t in cell_texts if any(s in t for s in ("株式会社", "有限会社", "合同会社"))),
            None,
        )
        date_text = next(
            (t for t in cell_texts if WAREKI_RE.search(t) or SEIREKI_RE.search(t)),
            None,
        )
        kind_text = next(
            (
                t
                for t in cell_texts
                if any(
                    k in t
                    for k in (
                        "指示",
                        "営業停止",
                        "認定の取消",
                        "許可の取消",
                        "廃止命令",
                        "停止命令",
                    )
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
        # Pull PDF link if present
        pdf_url = None
        a = tr.find("a", href=True)
        if a:
            pdf_url = _resolve_url(a["href"], source_url)
        # Determine related law from page section heading. The page has
        # explicit "警備業法違反により..." and "探偵業の業務の適正化に関する..."
        # section labels. Walk up to the nearest preceding <h*> or <p>.
        section_law = None
        for prev in tr.find_all_previous(["h1", "h2", "h3", "h4", "p", "div"]):
            txt = _normalize(prev.get_text(" ", strip=True))
            if "警備業法" in txt and "違反" in txt:
                section_law = "警備業法"
                break
            if "探偵業" in txt and "適正化" in txt:
                section_law = "探偵業の業務の適正化に関する法律"
                break
            if "古物営業法" in txt and "違反" in txt:
                section_law = "古物営業法"
                break
            if "風俗営業" in txt and ("違反" in txt or "適正化" in txt):
                section_law = "風俗営業等の規制及び業務の適正化等に関する法律"
                break
        if not section_law:
            section_law = "警備業法"  # Hyogo /sc/order.htm primary section
        # Try to enrich from PDF if available.
        pdf_reason = None
        pdf_law = None
        if pdf_url and pdf_url.endswith(".pdf"):
            pdf_text = _download_pdf_text(http, pdf_url)
            if pdf_text:
                pdf_reason, pdf_law = _parse_hyogo_order_pdf_fields(pdf_text)
        reason = f"{section_law}違反による行政処分（{kind_text}） / 認定番号: {ninteibango}"
        if pdf_reason:
            reason += f" / 処分理由: {pdf_reason[:200]}"
        related_law = pdf_law or section_law
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="兵庫県公安委員会",
                enforcement_kind=kind,
                reason_summary=reason[:1500],
                related_law_ref=related_law[:500],
                source_url=source_url,
                extra={
                    "ninteibango": ninteibango,
                    "kind_text": kind_text,
                    "pdf_url": pdf_url,
                    "section_law": section_law,
                },
            )
        )
    return out


def _download_pdf_text(http: HttpClient, url: str) -> str | None:
    """Download a PDF and run pdftotext -layout. Returns None on failure."""
    if not shutil.which("pdftotext"):
        return None
    res = http.get(url, max_bytes=PDF_MAX_BYTES)
    if not res.ok:
        return None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fp:
            fp.write(res.body)
            tmp_path = fp.name
        try:
            proc = subprocess.run(
                ["pdftotext", "-layout", tmp_path, "-"],
                capture_output=True,
                timeout=30,
            )
            if proc.returncode == 0:
                return proc.stdout.decode("utf-8", errors="replace")
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except (subprocess.TimeoutExpired, OSError) as exc:
        _LOG.debug("pdftotext failed url=%s err=%s", url, exc)
    return None


def _parse_hyogo_order_pdf_fields(text: str) -> tuple[str | None, str | None]:
    """Extract (処分理由, 根拠法令) from Hyogo 警備業法 行政処分公表 PDF text."""
    if not text:
        return None, None
    reason_m = re.search(
        r"処分理由[\s\S]{0,5}○\s*処分理由\s*([\s\S]+?)○\s*根拠法令",
        text,
    )
    reason = None
    if reason_m:
        r = reason_m.group(1)
        r = re.sub(r"\s+", " ", r).strip()
        reason = r[:300]
    law_m = re.search(
        r"○\s*根拠法令\s*([\s\S]+?)(?:処分を行った|$)",
        text,
    )
    law = None
    if law_m:
        law_text = law_m.group(1)
        law_text = re.sub(r"\s+", " ", law_text).strip()
        law = law_text[:300]
    return reason, law


# ---------------------------------------------------------------------------
# Parser: hyogo_koji_html
#   公示 page — 特例施設占有者の指定, 風適法41-2 公示, 警備業50-2 公示, etc.
#   These are 公示 (notifications), NOT punitive 処分. We record them with
#   enforcement_kind='other' and explicit "公示" tagging in reason_summary
#   so consumers don't mistake them for sanctions.
# ---------------------------------------------------------------------------


def parse_hyogo_koji_html(html: str, source_url: str) -> list[EnfRow]:
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    # Walk all <table> with rows that have company-name cells.
    # Each section is preceded by an <h*> describing what the table is.
    section_label = "公示"
    # Walk top-down so we know which section we're in.
    for el in soup.find_all(True):
        if el.name in ("h1", "h2", "h3", "h4", "h5"):
            label = _normalize(el.get_text(" ", strip=True))
            if label:
                section_label = label
            continue
        if el.name == "p":
            label = _normalize(el.get_text(" ", strip=True))
            # Sections separated by descriptive paragraph
            if label and any(k in label for k in ("公示", "指定")):
                section_label = label
        if el.name != "table":
            continue
        for tr in el.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
            if not cell_texts or "名称" in cell_texts[0]:
                continue
            target_name = next(
                (
                    t
                    for t in cell_texts
                    if any(s in t for s in ("株式会社", "有限会社", "合同会社"))
                ),
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
            # Strip trailing remarks from name.
            target_name = re.sub(
                r"\s*変更事項.*$",
                "",
                target_name,
            ).strip()
            target_name = re.sub(
                r"\s*に係る公示.*$",
                "",
                target_name,
            ).strip()
            # Determine related law from section_label keywords.
            label = section_label
            if "風俗営業" in label or "風適" in label or "第41条" in label:
                related_law = "風俗営業等の規制及び業務の適正化等に関する法律"
            elif "警備業" in label or "第50条" in label:
                related_law = "警備業法"
            elif "特例施設占有者" in label:
                # 特例施設占有者 is defined in 風適法 第23条第3項
                # (typically for ぱちんこ等遊技場業者). NOT 古物営業法.
                related_law = "風俗営業等の規制及び業務の適正化等に関する法律"
            elif "道路交通法" in label or "道交法" in label or "型式検定" in label:
                related_law = "道路交通法"
            else:
                # Default fallback — keep generic instead of guessing.
                related_law = "風俗営業等の規制及び業務の適正化等に関する法律"
            # Find PDF link for this row.
            pdf_url = None
            a = tr.find("a", href=True)
            if a:
                pdf_url = _resolve_url(a["href"], source_url)
            reason = f"{related_law}に基づく公示 / 公示種別: {label[:80]} / 名称: {target_name}"
            out.append(
                EnfRow(
                    target_name=target_name,
                    issuance_date=date_iso,
                    issuing_authority="兵庫県公安委員会",
                    enforcement_kind="other",
                    reason_summary=reason[:1500],
                    related_law_ref=related_law[:500],
                    source_url=source_url,
                    extra={
                        "section_label": label,
                        "pdf_url": pdf_url,
                        "category": "公示",
                    },
                )
            )
    # Dedup within batch
    seen = set()
    deduped: list[EnfRow] = []
    for r in out:
        key = (r.target_name, r.issuance_date, r.issuing_authority)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# ---------------------------------------------------------------------------
# Parser: aichi_kouhyou_html / tokyo_shobun_html
#   Forward-compatible parsers; both pages currently empty.
# ---------------------------------------------------------------------------


def parse_aichi_kouhyou_html(html: str, source_url: str) -> list[EnfRow]:
    """Aichi 安全なまちづくり条例 第32条第6項 公表."""
    if not html:
        return []
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if "該当事業者はありません" in text or "現在の該当者はありません" in text:
        return []
    # Walk tables for actual records (forward-compatible).
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
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
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="愛知県公安委員会",
                enforcement_kind="other",
                reason_summary=(
                    f"愛知県安全なまちづくり条例第32条第6項に基づく公表 / 名称: {target_name}"
                )[:1500],
                related_law_ref="愛知県安全なまちづくり条例",
                source_url=source_url,
                extra={"category": "条例公表"},
            )
        )
    return out


def parse_tokyo_shobun_html(html: str, source_url: str) -> list[EnfRow]:
    """警視庁 性風俗営業等 場所提供 規制条例 第2条の10第3項 公表."""
    if not html:
        return []
    out: list[EnfRow] = []
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if "現在の該当者はありません" in text or "該当事業者はありません" in text:
        return []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        cell_texts = [_normalize(c.get_text(" ", strip=True)) for c in cells]
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
        out.append(
            EnfRow(
                target_name=target_name,
                issuance_date=date_iso,
                issuing_authority="東京都公安委員会",
                enforcement_kind="other",
                reason_summary=(
                    "性風俗営業等に係る不当な勧誘等の規制条例第2条の10第3項に"
                    f"基づく公表 / 名称: {target_name}"
                )[:1500],
                related_law_ref=(
                    "性風俗営業等に係る不当な勧誘、料金の取立て等及び性関連"
                    "禁止営業への場所の提供の規制に関する条例"
                ),
                source_url=source_url,
                extra={"category": "条例公表"},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Source dispatch
# ---------------------------------------------------------------------------


def fetch_source(http: HttpClient, src: Source) -> list[EnfRow]:
    res = http.get(src.url)
    if not res.ok:
        _LOG.warning("[%s] fetch failed status=%s url=%s", src.parser, res.status, src.url)
        return []
    if src.parser == "hyogo_order_html":
        return parse_hyogo_order_html(res.text, src.url, http)
    if src.parser == "hyogo_koji_html":
        return parse_hyogo_koji_html(res.text, src.url)
    if src.parser == "aichi_kouhyou_html":
        return parse_aichi_kouhyou_html(res.text, src.url)
    if src.parser == "tokyo_shobun_html":
        return parse_tokyo_shobun_html(res.text, src.url)
    _LOG.warning("unknown parser %s", src.parser)
    return []


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
    """Return the set of (target_name, issuance_date, issuing_authority)
    for the police-issued enforcement universe so we don't reinsert."""
    out: set[tuple[str, str, str]] = set()
    cur = conn.execute(
        "SELECT target_name, issuance_date, issuing_authority "
        "FROM am_enforcement_detail "
        "WHERE issuing_authority LIKE ? "
        "   OR issuing_authority LIKE ? "
        "   OR issuing_authority LIKE ? ",
        (
            "%公安委員会%",
            "%警察庁%",
            "%警視庁%",
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
        ) VALUES (?, 'enforcement', 'police_npa_kouan', NULL,
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
) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0
    db_keys = existing_dedup_keys(conn)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = 0
    dup_db = 0
    dup_batch = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for idx, r in enumerate(rows, 1):
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
            seq = _slug8(f"{r.target_name}|{r.issuance_date}|{r.issuing_authority}|{idx}")
            canonical_id = f"AM-ENF-NPA-{r.issuance_date.replace('-', '')}-{seq}"
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
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--limit", type=int, default=None, help="Hard cap on inserted rows (default: no cap)"
    )
    ap.add_argument(
        "--max-prefs", type=int, default=7, help="Walk at most N prefectures (per task spec)"
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

    seen_prefs: set[str] = set()
    all_rows: list[EnfRow] = []
    for src in SOURCES:
        if len(seen_prefs) >= args.max_prefs and src.prefecture not in seen_prefs:
            _LOG.info("[skip] max prefs reached, skipping %s", src.prefecture)
            continue
        seen_prefs.add(src.prefecture)
        rows = fetch_source(http, src)
        _LOG.info("[%s] %s: %d rows", src.prefecture, src.parser, len(rows))
        all_rows.extend(rows)

    _LOG.info("total parsed rows=%d (prefs=%d)", len(all_rows), len(seen_prefs))

    if args.dry_run:
        for r in all_rows[:10]:
            _LOG.info(
                "sample: name=%s date=%s auth=%s kind=%s law=%s",
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
    # Per-authority summary for caller report.
    breakdown: dict[str, int] = {}
    for r in all_rows[: inserted + dup_db + dup_batch]:
        breakdown[r.issuing_authority] = (
            breakdown.get(
                r.issuing_authority,
                0,
            )
            + 1
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
        f"NPA / 公安委員会 ingest: parsed={len(all_rows)} "
        f"inserted={inserted} dup_db={dup_db} dup_batch={dup_batch}"
    )
    print(f"breakdown: {json.dumps(breakdown, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
