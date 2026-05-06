#!/usr/bin/env python3
"""Ingest 補助金返還命令 / 不正受給認定 / 補助事業 不当事項 into ``am_enforcement_detail``.

Source strategy
---------------

The richest single source for **per-entity, per-amount** enforcement of public
subsidies / loans is the Board of Audit (会計検査院) decennial report:

    https://report.jbaudit.go.jp/org/{rXX}/{YYYY}-{rXX}-{NNNN}-0.htm

Each report covers a fiscal year of audit findings. The key chapter is
**第3章 個別の検査結果 / 不当事項 (補助金等)** where each entity that received
improperly disbursed subsidies is published with name, prefecture, fiscal
year, 補助対象事業費, 不当事業費, 不当補助金額, and the relevant statute
(typically 補助金等に係る予算の執行の適正化に関する法律 第17条 + the
specific 事業実施要綱).

The portion of the report we care about for AutonoMath
(JFC / NEDO / IPA / AMED / METI 中小企業庁 / MAFF 等):

* 中小企業基盤整備機構本部 (中小機構, METI 中小企業庁 系) — IT導入補助金,
  ものづくり補助金, 事業再構築補助金, 地域企業再起支援事業 等
* 経済産業本省 + 経済産業局 — 中小企業創業支援等
* 農林水産本省 + 農政局 — 経営所得安定対策, 6次産業化, 畜産・酪農, 水産
* 林野庁, 水産庁
* 観光庁
* 内閣府本府 — 地域就職氷河期世代支援加速化交付金
* 国土交通本省 + 地方整備局
* 厚生労働本省 — 雇用調整助成金, 人材開発支援助成金, 緊急包括支援交付金
* 文部科学本省 — 科研費, 各種研究助成
* 環境本省

Existing rows in ``am_enforcement_detail`` (as of 2026-04-25): 12,257.
The audit board contributed ~1,200 rows from r03/r04/r05 selectively.
**r06 (FY2024) is NOT yet ingested at all.**

This script's design:

* Probe every ``r{XX}/2{YY}-r{XX}-{NNNN}-0.htm`` (NNNN ∈ 0001..0800)
  for r03..r06 in parallel; keep only HTTP 200 pages.
* For each page, parse the entity table (`<table class="table0">`) and every
  ``<tr>`` whose first ``<th scope="row">`` matches ``(NNNNN)``. Extract
  target_name, prefecture, 不当補助金額(千円→×1000), 摘要.
* Authority is the 中央省庁 / 局 listed in the page <h1>/breadcrumb. We
  normalise to a fixed mapping covering METI/中小企業庁/JFC/NEDO/IPA/AMED/
  MAFF/MHLW/MEXT/MLIT 等 + 都道府県.
* enforcement_kind = ``grant_refund`` (most rows) — these are public
  enforcement findings against subsidy recipients. A small fraction
  (措置要求/是正改善) get ``subsidy_exclude``.
* Schema target: ``am_enforcement_detail`` w/ FK to ``am_entities``.

curl works without bot block on jbaudit (no Akamai). We use plain requests
with rate limit + retry.

Per repository directive 2026-04-25: TOS 無視で獲得優先. License + attribution
preserved in raw_json (PDL v1.0 — 政府標準利用規約 2.0 互換).

Schema CHECK enum is:
    subsidy_exclude, grant_refund, contract_suspend, business_improvement,
    license_revoke, fine, investigation, other

Dedup key: (issuance_date[:10], target_name, issuing_authority).
Concurrency: BEGIN IMMEDIATE + busy_timeout=300000 (per 2026-04-22 directive).

CLI:
    python scripts/ingest/ingest_enforcement_grant_refund.py
    python scripts/ingest/ingest_enforcement_grant_refund.py --years r06
    python scripts/ingest/ingest_enforcement_grant_refund.py --max-rows 500
    python scripts/ingest/ingest_enforcement_grant_refund.py --dry-run
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import random
import re
import sqlite3
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Allow connecting to JP government sites with system-default TLS roots that
# may be missing on macOS Python builds. Use a permissive context — the data is
# public and we are only reading.
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install bs4", file=sys.stderr)
    sys.exit(1)

_LOG = logging.getLogger("autonomath.ingest_grant_refund")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

YEAR_FULL = {"r03": "2021", "r04": "2022", "r05": "2023", "r06": "2024"}
# Publication date of each report (会計検査院 announces in early Nov).
# Match existing rows in autonomath.db that already use these dates.
YEAR_PUB_DATE = {
    "r03": "2022-11-07",
    "r04": "2023-11-07",
    "r05": "2024-11-05",
    "r06": "2025-11-07",  # FY2024 audit report (報告書 published 2025年11月)
}

# Authority breadcrumb → (issuing_authority, authority_canonical)
# We keep `issuing_authority` close to the raw audit-board page label so the
# string matches existing rows (e.g. "厚生労働本省" not "厚生労働省"). The
# canonical_id is the FK to am_authority and uses normalised IDs.
AUTHORITY_MAP = {
    # 中央省庁 / 国の機関
    "中小企業基盤整備機構": ("中小企業庁", "authority:meti-chusho"),
    "中小企業庁": ("中小企業庁", "authority:meti-chusho"),
    "経済産業本省": ("経済産業本省", "authority:meti"),
    "経済産業局": ("経済産業省", "authority:meti"),
    "九州経済産業局": ("九州経済産業局", "authority:meti"),
    "関東経済産業局": ("関東経済産業局", "authority:meti"),
    "中部経済産業局": ("中部経済産業局", "authority:meti"),
    "近畿経済産業局": ("近畿経済産業局", "authority:meti"),
    "東北経済産業局": ("東北経済産業局", "authority:meti"),
    "中国経済産業局": ("中国経済産業局", "authority:meti"),
    "四国経済産業局": ("四国経済産業局", "authority:meti"),
    "資源エネルギー庁": ("資源エネルギー庁", "authority:meti"),
    "新エネルギー・産業技術総合開発機構": ("新エネルギー・産業技術総合開発機構", "authority:nedo"),
    "NEDO": ("新エネルギー・産業技術総合開発機構", "authority:nedo"),
    "情報処理推進機構": ("情報処理推進機構", "authority:ipa"),
    "日本医療研究開発機構": ("日本医療研究開発機構", "authority:amed"),
    "日本政策金融公庫": ("日本政策金融公庫", "authority:jfc"),
    "農林水産本省": ("農林水産本省", "authority:maff"),
    "東北農政局": ("東北農政局", "authority:maff"),
    "関東農政局": ("関東農政局", "authority:maff"),
    "東海農政局": ("東海農政局", "authority:maff"),
    "近畿農政局": ("近畿農政局", "authority:maff"),
    "中国四国農政局": ("中国四国農政局", "authority:maff"),
    "九州農政局": ("九州農政局", "authority:maff"),
    "北陸農政局": ("北陸農政局", "authority:maff"),
    "農政局": ("農林水産省", "authority:maff"),
    "林野庁": ("林野庁", "authority:maff-ringyo"),
    "水産庁": ("水産庁", "authority:maff-suisan"),
    "厚生労働本省": ("厚生労働本省", "authority:mhlw"),
    "近畿厚生局": ("近畿厚生局", "authority:mhlw"),
    "関東信越厚生局": ("関東信越厚生局", "authority:mhlw"),
    "九州厚生局": ("九州厚生局", "authority:mhlw"),
    "東海北陸厚生局": ("東海北陸厚生局", "authority:mhlw"),
    "中国四国厚生局": ("中国四国厚生局", "authority:mhlw"),
    "北海道厚生局": ("北海道厚生局", "authority:mhlw"),
    "東北厚生局": ("東北厚生局", "authority:mhlw"),
    "厚生局": ("厚生労働本省", "authority:mhlw"),
    "労働局": ("厚生労働本省", "authority:mhlw"),
    "文部科学本省": ("文部科学本省", "authority:mext"),
    "国土交通本省": ("国土交通本省", "authority:mlit"),
    "関東地方整備局": ("関東地方整備局", "authority:mlit"),
    "近畿地方整備局": ("近畿地方整備局", "authority:mlit"),
    "中国地方整備局": ("中国地方整備局", "authority:mlit"),
    "九州地方整備局": ("九州地方整備局", "authority:mlit"),
    "北陸地方整備局": ("北陸地方整備局", "authority:mlit"),
    "中部地方整備局": ("中部地方整備局", "authority:mlit"),
    "東北地方整備局": ("東北地方整備局", "authority:mlit"),
    "四国地方整備局": ("四国地方整備局", "authority:mlit"),
    "地方整備局": ("国土交通本省", "authority:mlit"),
    "観光庁": ("観光庁", "authority:jta"),
    "海上保安庁": ("海上保安庁", "authority:mlit"),
    "気象庁": ("気象庁", "authority:mlit"),
    "環境本省": ("環境本省", "authority:moe"),
    "総務本省": ("総務本省", "authority:soumu"),
    "総務省": ("総務本省", "authority:soumu"),
    "内閣府本府": ("内閣府本府", "authority:cabinet-office"),
    "金融庁": ("金融庁", "authority:cao-fsa"),
    "復興庁": ("復興庁", "authority:reconstruction"),
    "防衛本省": ("防衛本省", "authority:mod"),
    "外務本省": ("外務本省", "authority:mofa"),
    "法務本省": ("法務本省", "authority:moj"),
    "国家公安委員会": ("国家公安委員会", "authority:npa"),
    "警察庁": ("警察庁", "authority:npa"),
    "沖縄総合事務局": ("沖縄総合事務局", "authority:pref:okinawa"),
    # 道府県
    "北海道": ("北海道", "authority:pref:hokkaido"),
    "青森県": ("青森県", "authority:pref:aomori"),
    "岩手県": ("岩手県", "authority:pref:iwate"),
    "宮城県": ("宮城県", "authority:pref:miyagi"),
    "秋田県": ("秋田県", "authority:pref:akita"),
    "山形県": ("山形県", "authority:pref:yamagata"),
    "福島県": ("福島県", "authority:pref:fukushima"),
    "茨城県": ("茨城県", "authority:pref:ibaraki"),
    "栃木県": ("栃木県", "authority:pref:tochigi"),
    "群馬県": ("群馬県", "authority:pref:gunma"),
    "埼玉県": ("埼玉県", "authority:pref:saitama"),
    "千葉県": ("千葉県", "authority:pref:chiba"),
    "東京都": ("東京都", "authority:pref:tokyo"),
    "神奈川県": ("神奈川県", "authority:pref:kanagawa"),
    "新潟県": ("新潟県", "authority:pref:niigata"),
    "富山県": ("富山県", "authority:pref:toyama"),
    "石川県": ("石川県", "authority:pref:ishikawa"),
    "福井県": ("福井県", "authority:pref:fukui"),
    "山梨県": ("山梨県", "authority:pref:yamanashi"),
    "長野県": ("長野県", "authority:pref:nagano"),
    "岐阜県": ("岐阜県", "authority:pref:gifu"),
    "静岡県": ("静岡県", "authority:pref:shizuoka"),
    "愛知県": ("愛知県", "authority:pref:aichi"),
    "三重県": ("三重県", "authority:pref:mie"),
    "滋賀県": ("滋賀県", "authority:pref:shiga"),
    "京都府": ("京都府", "authority:pref:kyoto"),
    "大阪府": ("大阪府", "authority:pref:osaka"),
    "兵庫県": ("兵庫県", "authority:pref:hyogo"),
    "奈良県": ("奈良県", "authority:pref:nara"),
    "和歌山県": ("和歌山県", "authority:pref:wakayama"),
    "鳥取県": ("鳥取県", "authority:pref:tottori"),
    "島根県": ("島根県", "authority:pref:shimane"),
    "岡山県": ("岡山県", "authority:pref:okayama"),
    "広島県": ("広島県", "authority:pref:hiroshima"),
    "山口県": ("山口県", "authority:pref:yamaguchi"),
    "徳島県": ("徳島県", "authority:pref:tokushima"),
    "香川県": ("香川県", "authority:pref:kagawa"),
    "愛媛県": ("愛媛県", "authority:pref:ehime"),
    "高知県": ("高知県", "authority:pref:kochi"),
    "福岡県": ("福岡県", "authority:pref:fukuoka"),
    "佐賀県": ("佐賀県", "authority:pref:saga"),
    "長崎県": ("長崎県", "authority:pref:nagasaki"),
    "熊本県": ("熊本県", "authority:pref:kumamoto"),
    "大分県": ("大分県", "authority:pref:oita"),
    "宮崎県": ("宮崎県", "authority:pref:miyazaki"),
    "鹿児島県": ("鹿児島県", "authority:pref:kagoshima"),
    "沖縄県": ("沖縄県", "authority:pref:okinawa"),
}

# Default fallback when no match
DEFAULT_AUTHORITY = ("国（会計検査院 検査報告）", "authority:generic-minister-meti")

# Fiscal year (年度) labels in 摘要 → 西暦 (Reiwa baseline 2019=R1)
# Pages cite "3、4" = 令和3,4 年度 etc.

# Patterns
ROW_HEADER_RE = re.compile(r"^\s*[(（]\s*([0-9０-９]+)\s*[)）]\s*$")
NUMERIC_RE = re.compile(r"^\s*([0-9,，]+)\s*$")
PREF_RE = re.compile(r"[（(]([^)）]+?)[)）]")
HOUJIN_RE = re.compile(r"\b([0-9]{13})\b")

# 都道府県 + 政令指定都市 normalisation
_PREF_SUFFIX = ("県", "府", "都", "道")


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def _hash8(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _parse_int(text: str) -> int | None:
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text).replace(",", "").replace("、", "")
    m = NUMERIC_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (ValueError, IndexError):
        return None


def _classify_authority(breadcrumb: str, h1: str) -> tuple[str, str]:
    """Pick (issuing_authority, authority_canonical) from breadcrumb / h1."""
    blob = (breadcrumb or "") + "\n" + (h1 or "")
    blob = unicodedata.normalize("NFKC", blob)
    # First, look for the most specific match
    for key, val in AUTHORITY_MAP.items():
        if key in blob:
            return val
    return DEFAULT_AUTHORITY


def _classify_kind(breadcrumb: str, h1: str) -> str:
    blob = (breadcrumb or "") + "\n" + (h1 or "")
    blob = unicodedata.normalize("NFKC", blob)
    if "不当事項" in blob:
        return "grant_refund"
    if "意見を表示し" in blob or "処置を要求した" in blob:
        return "subsidy_exclude"
    if "是正改善" in blob:
        return "business_improvement"
    return "grant_refund"


# -------------------------- HTTP fetch --------------------------


class Fetcher:
    """Plain HTTP fetcher with rate limiting + retry. jbaudit has no bot block."""

    def __init__(self, qps: float = 4.0) -> None:
        self._min_interval = 1.0 / qps if qps > 0 else 0.0
        self._last_t = 0.0

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_t
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def fetch(self, url: str, retries: int = 3) -> tuple[int, str]:
        for attempt in range(retries):
            self._pace()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:  # noqa: S310
                    body = resp.read().decode("utf-8", errors="replace")
                    self._last_t = time.monotonic()
                    return resp.status, body
            except urllib.error.HTTPError as exc:
                self._last_t = time.monotonic()
                if exc.code == 404:
                    return 404, ""
                _LOG.debug("HTTPError %s %s (attempt %d)", exc.code, url, attempt + 1)
            except (urllib.error.URLError, TimeoutError) as exc:
                self._last_t = time.monotonic()
                _LOG.debug("URLError %s %s (attempt %d)", exc, url, attempt + 1)
            time.sleep(0.5 + random.random())
        return 0, ""


# -------------------------- Probe valid IDs --------------------------


def probe_valid_ids(year_code: str, max_id: int = 800, workers: int = 30) -> list[str]:
    """Probe NNNN-0.htm for NNNN in 1..max_id; return 200-OK IDs (sorted)."""
    year_full = YEAR_FULL[year_code]
    base = f"https://report.jbaudit.go.jp/org/{year_code}/{year_full}-{year_code}-"

    def _probe(nid: int) -> str | None:
        url = f"{base}{nid:04d}-0.htm"
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=12, context=_SSL_CTX) as resp:  # noqa: S310
                    if resp.status == 200:
                        return f"{nid:04d}"
                    return None
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None
            except Exception:
                pass
            time.sleep(0.3 + random.random() * 0.5)
        return None

    valid: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_probe, nid): nid for nid in range(1, max_id + 1)}
        for fut in concurrent.futures.as_completed(futs):
            r = fut.result()
            if r:
                valid.append(r)
    valid.sort()
    return valid


# -------------------------- Page parser --------------------------


def parse_page(html: str, source_url: str, year_code: str) -> list[dict[str, Any]]:
    """Parse a single audit board page; return list of entity records.

    Pages where there's no entity table (e.g. summary / chapter intro pages)
    return an empty list.
    """
    soup = BeautifulSoup(html, "html.parser")
    h1_el = soup.find("h1")
    h1_text = _normalize(h1_el.get_text() if h1_el else "")
    breadcrumb_el = soup.find("div", id="headline")
    breadcrumb = _normalize(breadcrumb_el.get_text() if breadcrumb_el else "")

    # Filter: must be 不当事項 / 意見表示 / 補助金 (subsidy / grant) related
    blob = h1_text + "\n" + breadcrumb
    is_subsidy = any(
        k in blob
        for k in [
            "補助金",
            "交付金",
            "助成金",
            "補助事業",
            "補助対象",
            "貸付金",
            "委託費",
            "補助事業者",
            "事業再構築",
            "ものづくり",
            "IT導入",
            "持続化",
            "雇用調整",
            "緊急包括支援",
            "地方創生",
            "農業",
            "漁業",
            "畜産",
            "林業",
            "研究費",
            "科研費",
        ]
    )
    is_enforcement_topic = any(
        k in blob
        for k in [
            "不当事項",
            "不正受給",
            "不正利用",
            "返還",
            "過大に交付",
            "過大に支給",
            "意見を表示",
            "処置を要求",
            "是正改善",
        ]
    )
    if not (is_subsidy and is_enforcement_topic):
        return []

    issuing_authority, authority_canonical = _classify_authority(breadcrumb, h1_text)
    enforcement_kind = _classify_kind(breadcrumb, h1_text)

    # Subsidy program name from H1 — find the "<...>補助金" / "<...>交付金" etc.
    program_name = None
    for m in re.finditer(
        r"([一-鿿ぁ-んァ-ヶー・A-Za-z0-9]+(?:補助金|交付金|助成金|事業費補助金|促進補助金))",
        h1_text,
    ):
        program_name = m.group(1)
        break

    out: list[dict[str, Any]] = []

    # Each entity is a <tr> containing <th scope="row">(NNN)</th>
    tables = soup.find_all("table", class_="table0")
    for table in tables:
        # Detect column layout from <th scope="col"> headers in the first row.
        # Some pages have a 部局等 column before the entity name (e.g. 0033).
        col_headers: list[str] = []
        first_header_tr = table.find("tr")
        if first_header_tr:
            for th_col in first_header_tr.find_all("th", attrs={"scope": "col"}):
                col_headers.append(_normalize(th_col.get_text()))
        # Determine which td index holds the target name.
        # Default: tds[0] is the recipient. But many tables prepend a
        # 部局等 / 局名 / 都道府県名 / 区分 column (the issuing agency or
        # the prefecture issuing the subsidy). In that case the actual
        # recipient is in tds[1]. We look at the first non-empty col header.
        name_td_idx = 0
        org_td_idx: int | None = None
        non_empty_cols = [c for c in col_headers if c]
        if non_empty_cols:
            first_col = non_empty_cols[0]
            if any(
                k in first_col
                for k in [
                    "部局等",
                    "局名",
                    "都道府県名",
                    "区分",
                    "省名",
                    "実施機関",
                    "交付者",
                ]
            ):
                name_td_idx = 1
                org_td_idx = 0
        # Carry forward "同" rows within a single table.
        last_row_authority: str | None = None
        last_row_authority_canonical: str | None = None

        for tr in table.find_all("tr"):
            th = tr.find("th", attrs={"scope": "row"})
            if not th:
                continue
            ref_text = _normalize(th.get_text())
            if not ROW_HEADER_RE.match(ref_text):
                continue
            ref_no = ROW_HEADER_RE.match(ref_text).group(1)
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue

            # If there's a 部局等/局名/都道府県名 column, take it as the
            # row-level authority refinement. "同" means "same as above" — we
            # then carry the previous row's authority.
            row_authority = None
            row_authority_canonical = None
            if org_td_idx is not None and org_td_idx < len(tds):
                org_cell = _normalize(tds[org_td_idx].get_text(separator=" "))
                if org_cell and org_cell not in ("同", "‐", "—", "-", "―", "‑"):
                    row_authority = org_cell
                    rauth, rcan = _classify_authority(org_cell, "")
                    if rcan != DEFAULT_AUTHORITY[1]:
                        row_authority_canonical = rcan
                    last_row_authority = row_authority
                    last_row_authority_canonical = row_authority_canonical
                elif last_row_authority is not None:
                    row_authority = last_row_authority
                    row_authority_canonical = last_row_authority_canonical

            # Cell at name_td_idx: target_name + (所在地)
            if name_td_idx >= len(tds):
                continue
            cell0_html = tds[name_td_idx]
            # remove inner styling but keep text + line breaks
            for br in cell0_html.find_all("br"):
                br.replace_with("\n")
            cell0_text = _normalize(cell0_html.get_text(separator="\n"))
            # Split off prefecture in parens
            target_name = cell0_text
            prefecture = None
            m = PREF_RE.search(cell0_text)
            if m:
                # Remove all parenthesised parts from name
                prefecture = m.group(1).strip()
                target_name = re.sub(r"[（(][^)）]+[)）]", "", cell0_text).strip()
                # Strip residual whitespace + line breaks
                target_name = re.sub(r"[\n\s　]+", "", target_name)

            if not target_name:
                continue
            # Single-letter rows like "A", "B", "C" — these are 個人事業主 stand-ins
            if re.fullmatch(r"[A-Za-zＡ-Ｚａ-ｚ]", target_name):
                target_name = f"個人事業主{target_name}"

            # Year cell (try to recover 年度)
            # tds layout for 中小機構: [name, 間接補助事業者, 年度, 事業費,
            #                       補助金交付額, 不当事業費, 不当補助金額, 摘要]
            # for 都道府県:     [name, ..., 年度, 事業費, 補助金, 不当事業費,
            #                       不当補助金額, 摘要]
            year_cell_text = None
            unfair_amount_yen = None  # 不当補助金額 (千円 → ×1000)
            tekiyo = None

            # Find the LAST numeric td → that's 不当補助金額 (千円)
            numeric_tds: list[tuple[int, int]] = []
            for i, td in enumerate(tds):
                text = _normalize(td.get_text(separator=" "))
                # remove parenthesised numbers like "(45,373)"
                stripped = re.sub(r"[（(][\d,，]+[)）]", "", text)
                m_num = re.search(r"^([\d,，]+)$", stripped.strip())
                if m_num:
                    val = _parse_int(m_num.group(1))
                    if val is not None:
                        numeric_tds.append((i, val))
            # 不当補助金額 column is the last non-trailing numeric.
            # 摘要 is the trailing td (often just "同" or pattern label).
            if numeric_tds:
                # take the last numeric td as 不当補助金額 (in 千円)
                last_idx, last_val = numeric_tds[-1]
                unfair_amount_yen = last_val * 1000

            # Tekiyo (摘要) — text in last td if it's not numeric
            last_td_text = _normalize(tds[-1].get_text(separator=" "))
            if not re.search(r"\d", last_td_text):
                tekiyo = last_td_text

            # year cell — first td after name that contains "年度"-ish digits
            # (these are short numbers like "3、4", "5", "4、5")
            for td in tds[1:5]:
                t = _normalize(td.get_text(separator=" "))
                if re.fullmatch(r"[\d、，,]+", t) and len(t) <= 6:
                    year_cell_text = t
                    break

            # houjin_bangou — search the row text for 13-digit number
            row_text = _normalize(tr.get_text(separator=" "))
            houjin = None
            for cand in HOUJIN_RE.findall(row_text):
                houjin = cand
                break

            # reason_summary — combine page H1 + tekiyo + year
            summary_parts = [h1_text]
            if tekiyo:
                summary_parts.append(f"摘要: {tekiyo}")
            if year_cell_text:
                summary_parts.append(f"対象年度: 令和{year_cell_text}年度")
            if program_name:
                summary_parts.append(f"対象補助金: {program_name}")
            reason_summary = " | ".join(summary_parts)[:1900]

            # Use row-level authority if it gave a non-default canonical_id.
            final_authority = row_authority or issuing_authority
            final_canonical = row_authority_canonical or authority_canonical
            out.append(
                {
                    "ref_no": ref_no,
                    "target_name": target_name,
                    "houjin_bangou": houjin,
                    "prefecture": prefecture,
                    "amount_yen": unfair_amount_yen,
                    "issuance_date": YEAR_PUB_DATE[year_code],
                    "issuing_authority": final_authority,
                    "authority_canonical": final_canonical,
                    "issuing_authority_h1": issuing_authority,
                    "enforcement_kind": enforcement_kind,
                    "program_name": program_name,
                    "year_code": year_code,
                    "title": h1_text,
                    "tekiyo": tekiyo,
                    "reason_summary": reason_summary,
                    "source_url": source_url,
                    "related_law_ref": "補助金等に係る予算の執行の適正化に関する法律 第17条 等",
                }
            )

    return out


# -------------------------- DB write --------------------------


def existing_dedup_keys(cur: sqlite3.Cursor) -> set[tuple[str, str, str]]:
    cur.execute("""
        SELECT issuance_date, target_name, issuing_authority
          FROM am_enforcement_detail
    """)
    out: set[tuple[str, str, str]] = set()
    for d, n, a in cur.fetchall():
        out.add(((d or "")[:10], _normalize(n), _normalize(a)))
    return out


def existing_canonical_ids(cur: sqlite3.Cursor) -> set[str]:
    cur.execute("SELECT canonical_id FROM am_entities WHERE record_kind='enforcement'")
    return {r[0] for r in cur.fetchall()}


def build_canonical_id(rec: dict[str, Any]) -> str:
    payload_parts = [
        rec.get("year_code", ""),
        rec.get("ref_no", ""),
        rec.get("target_name", ""),
        rec.get("source_url", ""),
        str(rec.get("amount_yen") or ""),
    ]
    h = _hash8("|".join(payload_parts))
    yyyymmdd = (rec.get("issuance_date") or "").replace("-", "")[:8] or "00000000"
    return f"enforcement:jbaudit-{rec['year_code']}-{rec['ref_no']}-{yyyymmdd}-{h}"


def upsert_record(
    cur: sqlite3.Cursor,
    rec: dict[str, Any],
    now_iso: str,
    seen_canonical: set[str],
) -> bool:
    canonical_id = build_canonical_id(rec)
    if canonical_id in seen_canonical:
        return False
    seen_canonical.add(canonical_id)

    raw_json = {
        "source": "jbaudit:annual_report",
        "year_code": rec["year_code"],
        "ref_no": rec["ref_no"],
        "title": rec.get("title"),
        "target_name": rec["target_name"],
        "houjin_bangou": rec.get("houjin_bangou"),
        "prefecture": rec.get("prefecture"),
        "issuance_date": rec["issuance_date"],
        "amount_yen": rec.get("amount_yen"),
        "amount_text_thousands_yen": (
            int(rec["amount_yen"] / 1000) if rec.get("amount_yen") else None
        ),
        "issuing_authority": rec["issuing_authority"],
        "authority_canonical": rec["authority_canonical"],
        "enforcement_kind": rec["enforcement_kind"],
        "program_name": rec.get("program_name"),
        "tekiyo": rec.get("tekiyo"),
        "related_law_ref": rec.get("related_law_ref"),
        "reason_summary": rec.get("reason_summary"),
        "source_url": rec["source_url"],
        "license": "PDL v1.0 (政府標準利用規約 第2.0版 互換)",
        "attribution": f"出典: 会計検査院決算検査報告 ({rec['source_url']})",
        "fetched_at": now_iso,
    }

    cur.execute(
        """INSERT OR IGNORE INTO am_entities
           (canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence, source_url,
            source_url_domain, fetched_at, raw_json)
           VALUES (?, 'enforcement', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            f"jbaudit_{rec['year_code']}_grant_refund",
            int(rec["ref_no"]),
            (rec["target_name"] or "")[:255],
            rec["authority_canonical"],
            0.85,
            rec["source_url"],
            "report.jbaudit.go.jp",
            now_iso,
            json.dumps(raw_json, ensure_ascii=False),
        ),
    )
    if cur.rowcount == 0:
        return False
    cur.execute(
        """INSERT INTO am_enforcement_detail
           (entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, exclusion_start, exclusion_end,
            reason_summary, related_law_ref, amount_yen, source_url,
            source_fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            rec.get("houjin_bangou"),
            rec["target_name"][:500] if rec.get("target_name") else None,
            rec["enforcement_kind"],
            rec["issuing_authority"],
            rec["issuance_date"],
            None,
            None,
            (rec.get("reason_summary") or "")[:2000] or None,
            rec.get("related_law_ref"),
            rec.get("amount_yen"),
            rec["source_url"],
            now_iso,
        ),
    )
    return True


# -------------------------- main flow --------------------------


def run(
    db_path: Path,
    years: list[str],
    max_rows: int,
    dry_run: bool,
    verbose: bool,
    cached_id_dir: Path | None,
) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    now_iso = datetime.now(tz=UTC).isoformat(timespec="seconds")

    fetcher = Fetcher(qps=10.0)

    # 1. Discover valid IDs (from cache file if available, else probe).
    valid_by_year: dict[str, list[str]] = {}
    for yc in years:
        cache_file = (cached_id_dir / f"{yc}_ids.txt") if cached_id_dir else None
        if cache_file and cache_file.exists():
            ids = [line.strip() for line in cache_file.read_text().splitlines() if line.strip()]
            _LOG.info("[%s] using cached %d ids from %s", yc, len(ids), cache_file)
        else:
            _LOG.info("[%s] probing valid page IDs (1..800)...", yc)
            ids = probe_valid_ids(yc, max_id=800)
            _LOG.info("[%s] found %d valid IDs", yc, len(ids))
            if cached_id_dir:
                cached_id_dir.mkdir(parents=True, exist_ok=True)
                (cached_id_dir / f"{yc}_ids.txt").write_text("\n".join(ids))
        valid_by_year[yc] = ids

    # 2. Fetch + parse every page in parallel.
    all_records: list[dict[str, Any]] = []
    pages_seen = 0
    pages_with_data = 0

    def _one(yc: str, nid: str) -> list[dict[str, Any]]:
        year_full = YEAR_FULL[yc]
        url = f"https://report.jbaudit.go.jp/org/{yc}/{year_full}-{yc}-{nid}-0.htm"
        # Use a thread-local Fetcher (no shared state) — light, no rate-limit
        # since jbaudit has no throttling and we cap parallelism via workers.
        local = Fetcher(qps=20.0)
        status, html = local.fetch(url)
        if status != 200 or not html:
            return []
        try:
            return parse_page(html, url, yc)
        except Exception as exc:  # pragma: no cover
            _LOG.warning("parse failed %s: %s", url, exc)
            return []

    tasks = [(yc, nid) for yc, ids in valid_by_year.items() for nid in ids]
    _LOG.info("fetching %d pages in parallel...", len(tasks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(_one, yc, nid): (yc, nid) for yc, nid in tasks}
        for fut in concurrent.futures.as_completed(futs):
            pages_seen += 1
            recs = fut.result()
            if recs:
                pages_with_data += 1
                all_records.extend(recs)
            if pages_seen % 50 == 0:
                _LOG.info(
                    "progress: %d/%d pages fetched, %d with data, %d records",
                    pages_seen,
                    len(tasks),
                    pages_with_data,
                    len(all_records),
                )
    _LOG.info(
        "collected: %d records from %d/%d pages", len(all_records), pages_with_data, pages_seen
    )

    if not all_records:
        _LOG.error("no records collected — aborting")
        return 0

    if dry_run:
        # show summary by authority
        by_auth: dict[str, int] = {}
        by_year: dict[str, int] = {}
        for r in all_records:
            by_auth[r["issuing_authority"]] = by_auth.get(r["issuing_authority"], 0) + 1
            by_year[r["year_code"]] = by_year.get(r["year_code"], 0) + 1
        _LOG.info("== dry-run summary ==")
        for k in sorted(by_year):
            _LOG.info("  year %s: %d", k, by_year[k])
        for k, v in sorted(by_auth.items(), key=lambda kv: -kv[1])[:20]:
            _LOG.info("  authority %s: %d", k, v)
        for r in all_records[:5]:
            _LOG.info(
                "  sample: %s %s | %s | %s | ¥%s",
                r["year_code"],
                r["ref_no"],
                r["target_name"][:30],
                r["issuing_authority"][:30],
                r.get("amount_yen") or "?",
            )
        return 0

    # 3. Write to DB with batched BEGIN IMMEDIATE.
    inserted = 0
    skipped_dup = 0
    skipped_constraint = 0
    by_auth: dict[str, int] = {}
    by_year: dict[str, int] = {}

    def _open_conn() -> sqlite3.Connection:
        c = sqlite3.connect(str(db_path), timeout=600.0, isolation_level=None)
        c.execute("PRAGMA busy_timeout=300000")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def _begin_immediate(c: sqlite3.Connection) -> None:
        last_err: Exception | None = None
        deadline = time.monotonic() + 600.0
        while time.monotonic() < deadline:
            try:
                c.execute("BEGIN IMMEDIATE")
                return
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                if "lock" not in msg and "busy" not in msg:
                    raise
                last_err = exc
                time.sleep(0.5 + random.random() * 1.5)
        raise RuntimeError(f"BEGIN IMMEDIATE failed: {last_err}")

    BATCH = 100
    con = _open_conn()
    try:
        cur = con.cursor()
        existing_dedup = existing_dedup_keys(cur)
        seen_canonical = existing_canonical_ids(cur)
        cur.close()
        _LOG.info(
            "loaded %d existing dedup keys + %d canonical_ids",
            len(existing_dedup),
            len(seen_canonical),
        )

        batch: list[dict[str, Any]] = []
        for r in all_records:
            if inserted >= max_rows:
                break
            key = (
                (r["issuance_date"] or "")[:10],
                _normalize(r.get("target_name") or ""),
                _normalize(r["issuing_authority"]),
            )
            if key in existing_dedup:
                skipped_dup += 1
                continue
            existing_dedup.add(key)
            batch.append(r)
            if len(batch) >= BATCH:
                _begin_immediate(con)
                cur = con.cursor()
                for rec in batch:
                    try:
                        ok = upsert_record(cur, rec, now_iso, seen_canonical)
                    except sqlite3.IntegrityError as exc:
                        _LOG.warning("integrity %s: %s", rec.get("target_name"), exc)
                        skipped_constraint += 1
                        continue
                    if ok:
                        inserted += 1
                        by_auth[rec["issuing_authority"]] = (
                            by_auth.get(rec["issuing_authority"], 0) + 1
                        )
                        by_year[rec["year_code"]] = by_year.get(rec["year_code"], 0) + 1
                cur.close()
                con.execute("COMMIT")
                _LOG.info("batch commit: inserted=%d (so far)", inserted)
                batch.clear()
        if batch:
            _begin_immediate(con)
            cur = con.cursor()
            for rec in batch:
                try:
                    ok = upsert_record(cur, rec, now_iso, seen_canonical)
                except sqlite3.IntegrityError as exc:
                    _LOG.warning("integrity %s: %s", rec.get("target_name"), exc)
                    skipped_constraint += 1
                    continue
                if ok:
                    inserted += 1
                    by_auth[rec["issuing_authority"]] = by_auth.get(rec["issuing_authority"], 0) + 1
                    by_year[rec["year_code"]] = by_year.get(rec["year_code"], 0) + 1
            cur.close()
            con.execute("COMMIT")
            _LOG.info("final batch commit: inserted=%d", inserted)
        _LOG.info(
            "INSERT done inserted=%d skipped_dup=%d skipped_err=%d total_seen=%d",
            inserted,
            skipped_dup,
            skipped_constraint,
            len(all_records),
        )
        for k in sorted(by_year):
            _LOG.info("  year %s inserted: %d", k, by_year[k])
        for k, v in sorted(by_auth.items(), key=lambda kv: -kv[1]):
            _LOG.info("  authority %s inserted: %d", k, v)
    except Exception:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        con.close()
    return inserted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--years",
        type=str,
        default="r06,r05,r04,r03",
        help="comma-separated year codes (e.g. r06,r05)",
    )
    ap.add_argument("--max-rows", type=int, default=10000)
    ap.add_argument(
        "--cached-id-dir",
        type=Path,
        default=Path("/tmp"),
        help="directory holding {yc}_ids.txt cache files",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    years = [y.strip() for y in args.years.split(",") if y.strip()]
    invalid = [y for y in years if y not in YEAR_FULL]
    if invalid:
        ap.error(f"unknown year codes: {invalid}")

    inserted = run(
        args.db,
        years,
        args.max_rows,
        args.dry_run,
        args.verbose,
        args.cached_id_dir,
    )
    return 0 if (args.dry_run or inserted >= 1) else 1


if __name__ == "__main__":
    sys.exit(main())
