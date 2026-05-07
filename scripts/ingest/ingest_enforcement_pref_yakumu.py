#!/usr/bin/env python3
"""Ingest 都道府県 / 政令指定都市 薬務課 (and 衛生主管部) administrative
dispositions under 薬機法 (医薬品医療機器等法) into ``am_enforcement_detail``.

Background:
  PMDA agent #17 covers 中央 enforcement (PMDA / 厚生労働大臣) and recall
  orders (回収命令). This script targets the orthogonal layer: pref / city
  level administrative dispositions:

    - 薬局 (pharmacy) 業務停止 / 業務改善 / 許可取消
    - 店舗販売業 / 配置販売業 / 卸売販売業 (drug store / itinerant / wholesale)
    - 医療機器製造販売業 / 医療機器販売業 (medical device manufacturer/seller)
    - 化粧品製造販売業 (cosmetics manufacturer)
    - 医薬品製造業 / 製造販売業 (drug manufacturer)

  Sources are TWO classes:
    A. **Curated pref / city press release URLs**:
       直接 prefecture press release pages discovered via search
       (Tokushima, Saitama, Toyama, Hiroshima, Osaka City, Tokyo, ...).
    B. **H-CRISIS aggregator** (h-crisis.niph.go.jp), which is the
       国立保健医療科学院 directory of MHLW health-crisis announcements —
       a primary government resource (NOT a private aggregator). It
       reproduces pref-level press releases verbatim with the original
       lg.jp source URL preserved, so it counts as 一次資料 mirror.

Critical (per mission):
  - **PMDA agent #17 dedup**: drop any row whose authority resolves to
    "PMDA" or "厚生労働大臣" / "厚生労働省" — those are central, already
    covered.
  - **Aggregators ban** (CLAUDE.md): noukaweb / hojyokin-portal / yakuji /
    rei-law / monolith etc. are **forbidden** as source_url. The only
    aggregator we touch is h-crisis.niph.go.jp because it's a NIPH
    (国立保健医療科学院) site — a 厚労省 affiliated 国立研究所.

Schema mapping:
  - enforcement_kind:
       'license_revoke'        : 許可取消 / 承認取消
       'business_improvement'  : 業務改善命令
       'contract_suspend'      : 業務停止命令 (短期業務停止)
       'fine'                  : 課徴金 / 罰金 (rare for pref level)
       'other'                 : 注意指示 / 警告 / その他
  - issuing_authority: "{県/都/府/道} 薬務課" or "{市} 健康局" pattern;
       default to prefecture name when sub-bureau unknown.
  - related_law_ref: always contains "薬機法" so verification query
       (related_law_ref LIKE '%薬機法%' OR reason_summary LIKE '%薬機法%')
       captures all rows.

Parallel-write:
  - BEGIN IMMEDIATE + busy_timeout=300000 (per CLAUDE.md §5).
  - Per-source small commits.

Dedup:
  - (target_name, issuance_date, issuing_authority) tuple (DB + batch).
  - Cross-agent dedup: rows with authority LIKE '%PMDA%' or '%厚生労働%'
    are dropped at parse time (PMDA agent #17 owns those).

CLI:
    python scripts/ingest/ingest_enforcement_pref_yakumu.py \
        [--db autonomath.db] [--dry-run] [--verbose] [--limit-urls N]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import contextlib

from scripts.lib.http import HttpClient  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.pref_yakumu")

DEFAULT_DB = REPO_ROOT / "autonomath.db"
USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"

# ---------------------------------------------------------------------------
# H-CRISIS search queries — directory of pref-level pharma dispositions
# ---------------------------------------------------------------------------

HCRISIS_BASE = "https://h-crisis.niph.go.jp"
# Use WordPress REST API instead of search HTML — way faster, returns JSON.
# Query terms cover the full pharma-enforcement corpus on h-crisis.
HCRISIS_REST_QUERIES = [
    "行政処分",  # 113 posts
    "業務停止",  # 18 posts
    "業務改善",  # 28 posts
    "改善命令",  # 23 posts
    "薬機法",  # 48 posts
    "医薬品医療機器等法",  # 258 posts (some overlap)
    "違反業者",  # 9 posts
    "違反者",  # 6 posts
    "課徴金",  # 2 posts
]


# ---------------------------------------------------------------------------
# Curated pref / city URLs (direct, no aggregator)
#   These were discovered via Google site: search and confirmed live as
#   primary government press releases.
# ---------------------------------------------------------------------------

CURATED_URLS: list[tuple[str, str]] = [
    # Tokushima (long-running 後発医薬品 GMP issue)
    ("徳島県", "https://www.pref.tokushima.lg.jp/kenseijoho/hodoteikyoshiryo/5051178/"),
    # Toyama (Nichi-Iko)
    ("富山県", "https://www.pref.toyama.jp/1208/20240426.html"),
    # Niigata (NMI 27 pharmacies)
    ("新潟県", "https://www.pref.niigata.lg.jp/sec/kanyaku/1356906829370.html"),
    # Osaka City
    ("大阪市", "https://www.city.osaka.lg.jp/hodoshiryo/kenko/0000657071.html"),
    ("大阪市", "https://www.city.osaka.lg.jp/hodoshiryo/kenko/0000638562.html"),
    ("大阪市", "https://www.city.osaka.lg.jp/hodoshiryo/kenko/0000672785.html"),
    # Hiroshima City
    ("広島市", "https://www.city.hiroshima.lg.jp/houdou/houdou/371332.html"),
    # Tokyo Metropolitan Government (older but still 一次資料)
    ("東京都", "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2018/04/09/03.html"),
    ("東京都", "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2018/03/08/09.html"),
    ("東京都", "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2017/04/12/09.html"),
    ("東京都", "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2017/03/28/11.html"),
    ("東京都", "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/press/2018/11/01/17.html"),
    # Hyogo
    ("兵庫県", "https://web.pref.hyogo.lg.jp/press/20220328_9915.html"),
    # Osaka Pref
    ("大阪府", "https://www.pref.osaka.lg.jp/hodo/fumin/o100100/prs_49735.html"),
    ("大阪府", "https://www.pref.osaka.lg.jp/hodo/fumin/o100100/prs_50463.html"),
    # Sakai City PDF (ウェーブ薬局 2024-11-27)
    (
        "堺市",
        "https://www.city.sakai.lg.jp/shisei/koho/hodo/hodoteikyoshiryo/kakohodo/teikyoshiryo_r6/r611/061127_01.files/1127_01.pdf",
    ),
    # Ishikawa (辰巳化学 2022-09-02 業務改善命令)
    ("石川県", "https://www.pref.ishikawa.lg.jp/kisya/r4/documents/0902yakuzi.pdf"),
    # Saitama (タキザワ漢方廠 2024-01-25)
    ("埼玉県", "https://www.pref.saitama.lg.jp/a0707/news/page/news2024012502.html"),
    # Fukui (薬務関連処分一覧)
    ("福井県", "https://www.pref.fukui.lg.jp/doc/iei/yakumu/syobun.html"),
]


# ---------------------------------------------------------------------------
# Date / wareki parsing
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

PREF_NAMES = [
    "北海道",
    "青森県",
    "岩手県",
    "宮城県",
    "秋田県",
    "山形県",
    "福島県",
    "茨城県",
    "栃木県",
    "群馬県",
    "埼玉県",
    "千葉県",
    "東京都",
    "神奈川県",
    "新潟県",
    "富山県",
    "石川県",
    "福井県",
    "山梨県",
    "長野県",
    "岐阜県",
    "静岡県",
    "愛知県",
    "三重県",
    "滋賀県",
    "京都府",
    "大阪府",
    "兵庫県",
    "奈良県",
    "和歌山県",
    "鳥取県",
    "島根県",
    "岡山県",
    "広島県",
    "山口県",
    "徳島県",
    "香川県",
    "愛媛県",
    "高知県",
    "福岡県",
    "佐賀県",
    "長崎県",
    "熊本県",
    "大分県",
    "宮崎県",
    "鹿児島県",
    "沖縄県",
]
# Major designated cities (政令指定都市) with their own 薬務課 / 健康局
DESIGNATED_CITIES = [
    "札幌市",
    "仙台市",
    "さいたま市",
    "千葉市",
    "横浜市",
    "川崎市",
    "相模原市",
    "新潟市",
    "静岡市",
    "浜松市",
    "名古屋市",
    "京都市",
    "大阪市",
    "堺市",
    "神戸市",
    "岡山市",
    "広島市",
    "北九州市",
    "福岡市",
    "熊本市",
]
PREF_RE = re.compile("(" + "|".join(PREF_NAMES + DESIGNATED_CITIES) + ")")
PREF_SHORT_TO_FULL = {p[:-1]: p for p in PREF_NAMES if p.endswith(("県", "都", "府", "道"))}
PREF_SHORT_TO_FULL["北海"] = "北海道"

# Authority dedup against PMDA agent #17
PMDA_LIKE = re.compile(r"PMDA|医薬品医療機器総合機構|厚生労働大臣|厚生労働省|厚労省|MHLW")

# Action-kind classifiers (Japanese keywords)
KIND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "license_revoke",
        re.compile(r"許可(取消|の取消|取り消し)|承認(取消|取り消し)|登録(取消|取り消し)"),
    ),
    ("business_improvement", re.compile(r"業務改善命令|改善命令|改善措置命令|業務改善")),
    (
        "contract_suspend",
        re.compile(r"業務(の)?停止(命令)?|営業停止|販売停止|販売自粛|業務一部停止"),
    ),
    ("fine", re.compile(r"課徴金|罰金|過料|科料")),
    ("other", re.compile(r"注意|指示|警告|戒告")),
]

# Pharma-related law markers (must match at least one)
PHARMA_LAW_RE = re.compile(
    r"医薬品医療機器等法|医薬品医療機器法|薬機法|薬事法|"
    r"医薬品、医療機器等の品質、有効性及び安全性の確保等に関する法律"
)

# Reason summary keywords that confirm 薬務 (pharmacy/drug regulation)
PHARMA_TOPIC_RE = re.compile(
    r"薬局|医薬品|医療機器|化粧品|医薬部外品|店舗販売業|卸売販売業|"
    r"配置販売業|薬剤師|製造販売業|薬事監視|薬機法|医薬品医療機器等法|"
    r"医薬品、医療機器等の品質"
)

# Title-level filters: must match enforcement keywords, must NOT match
# topical advisories / Q&A / safety bulletins.
ENFORCEMENT_TITLE_RE = re.compile(
    r"行政処分|業務停止|業務改善|営業停止|許可取消|承認取消|登録取消|"
    r"違反業者|違反者|課徴金|措置命令|改善命令|改善措置命令|行政指導|"
    r"処分について|処分の公表"
)
EXCLUDE_TITLE_RE = re.compile(
    r"新型コロナ|COVID|ワクチン|薬価|供給停止|安全性速報|Q&A|Q&A|"
    r"ガイドライン|議事|審議会|お知らせ|通知|事務連絡|情報提供|"
    r"研修|セミナー|募集|公募|表彰|報告書|調査結果|統計|アンケート|"
    r"申請|手続|届出|認可|許可基準|採用|人事|退職|入札|落札|契約|"
    r"求人|名簿|名鑑|料金表|入賞|大会|行事|イベント|"
    r"食中毒|食品衛生|食品衛生法|食肉処理|HACCP"
)


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
# Company name extraction
# ---------------------------------------------------------------------------

# Same heuristic shape as pref_shimei_teishi: capture 株式会社 / 有限会社
# / 合同会社 / etc. + optional kanji/katakana stem.
_NAME_CHARS = r"[A-Za-z0-9Ａ-Ｚａ-ｚ０-９ー・\-゠-ヿ一-鿿\s]"
_COMPANY_RE = re.compile(
    r"((?:株式会社|有限会社|合同会社|合資会社|合名会社|"
    r"一般社団法人|公益社団法人|一般財団法人|公益財団法人|"
    r"学校法人|医療法人|社会福祉法人|特定非営利活動法人|"
    r"独立行政法人|地方独立行政法人)"
    r"[一-鿿ァ-ヿA-Za-zＡ-Ｚａ-ｚ０-９0-9ー・]{1,30}|"
    r"[一-鿿ァ-ヿA-Za-zＡ-Ｚａ-ｚ０-９0-9ー・]{1,30}"
    r"(?:株式会社|有限会社|合同会社|（株）|\(株\)|（有）|\(有\)))"
)
# Pharmacy-specific: 薬局 / drug store names
_YAKKYOKU_RE = re.compile(
    r"([一-鿿ァ-ヿA-Za-zＡ-Ｚａ-ｚ０-９0-9ー・]{1,30}(?:薬局|ドラッグ|薬店|店舗))"
)


def _is_valid_company_name(s: str) -> bool:
    """Reject pure numerics, pure ascii, generic words, etc."""
    if not s or len(s) < 2:
        return False
    # Must contain at least one kanji or katakana stem character.
    if not re.search(r"[一-鿿ァ-ヿ]", s):
        return False
    # Reject "27薬局", "各薬局", "本薬局", "当薬局" — these are generic refs.
    if re.fullmatch(r"[0-9０-９]+(?:薬局|ドラッグ|薬店|店舗)", s):
        return False
    return s not in {"各薬局", "本薬局", "当薬局", "同薬局", "他薬局", "本店舗", "当店舗", "同店舗", "他店舗", "本店", "当店", "同店"}


def find_companies_in_text(text: str) -> list[str]:
    """Return all plausible company / pharmacy names from text."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _COMPANY_RE.finditer(text):
        cand = m.group(1).strip()
        if 2 <= len(cand) <= 80 and cand not in seen and _is_valid_company_name(cand):
            seen.add(cand)
            out.append(cand)
    for m in _YAKKYOKU_RE.finditer(text):
        cand = m.group(1).strip()
        # Reject overlap with already-captured 株式会社 names
        if (
            2 <= len(cand) <= 80
            and cand not in seen
            and "薬局" in cand
            and _is_valid_company_name(cand)
        ):
            seen.add(cand)
            out.append(cand)
    return out


# ---------------------------------------------------------------------------
# Anonymize personal pharmacist names — never store individuals
# ---------------------------------------------------------------------------

PERSONAL_NAME_RE = re.compile(r"^[^\s（(]{2,4}\s*[一-鿿]{1,4}$")


def is_personal_name_only(s: str) -> bool:
    """Heuristic: short kanji string that looks like 個人氏名 only (no 株式会社)."""
    if not s:
        return False
    if "株式会社" in s or "有限会社" in s or "薬局" in s or "ドラッグ" in s:
        return False
    if "（株）" in s or "(株)" in s:
        return False
    return bool(PERSONAL_NAME_RE.match(s))


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    target_name: str
    enforcement_kind: str  # license_revoke | business_improvement | contract_suspend | fine | other
    issuing_authority: str  # "{pref}" or "{pref} 薬務課"
    issuance_date: str  # ISO yyyy-mm-dd
    reason_summary: str
    related_law_ref: str  # always contains 薬機法 or 医薬品医療機器等法
    source_url: str  # original press-release URL
    extra: dict | None = None


# ---------------------------------------------------------------------------
# H-CRISIS extraction
# ---------------------------------------------------------------------------


def hcrisis_search_archive_urls(http: HttpClient) -> list[tuple[str, str]]:
    """Use H-CRISIS WordPress REST API to discover enforcement archives.

    Returns [(archive_url, title)] tuples — the title is used for early
    filtering before fetching the full body.
    """
    out: dict[str, str] = {}  # id -> title
    for q in HCRISIS_REST_QUERIES:
        encoded = urllib.parse.quote(q)
        for page in range(1, 11):  # cap at 10 pages × 100 = 1000 posts/query
            url = (
                f"{HCRISIS_BASE}/wp-json/wp/v2/posts"
                f"?search={encoded}&per_page=100&page={page}"
                f"&_fields=id,title,link"
            )
            res = http.get(url, max_bytes=10 * 1024 * 1024)
            if not res.ok:
                break
            try:
                data = json.loads(res.body.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                break
            if not isinstance(data, list) or not data:
                break
            for item in data:
                aid = item.get("id")
                title = (item.get("title") or {}).get("rendered", "")
                link = item.get("link", "")
                if not aid or not link:
                    continue
                # Pre-filter by title to avoid wasted body fetches
                title_norm = _normalize(re.sub(r"<[^>]+>", "", title))
                if EXCLUDE_TITLE_RE.search(title_norm):
                    continue
                if not ENFORCEMENT_TITLE_RE.search(title_norm):
                    continue
                out[link] = title_norm
            if len(data) < 100:
                break
    return sorted(out.items())


def parse_hcrisis_archive(html: str, archive_url: str) -> list[EnfRow]:
    """Parse an h-crisis archive page into 0..N EnfRows.

    Returns multiple rows when the page lists multiple companies on the
    same disposition date (e.g. Aile Pharmaceutical + Daiko Pharmaceutical
    in the Harvoni counterfeit case)."""
    # Extract title
    m_title = re.search(r"<title>([^<]+)</title>", html)
    title = (m_title.group(1) if m_title else "").replace(" – H・CRISIS", "").strip()
    title = title.replace("&#8211;", "-")
    title_norm = _normalize(title)

    # Filter: must look like enforcement, must not be excluded topic
    if EXCLUDE_TITLE_RE.search(title_norm):
        return []
    if not ENFORCEMENT_TITLE_RE.search(title_norm):
        return []

    # Extract entry-content body
    body_html = ""
    for pat in (
        r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)<footer',
        r"<article[^>]*>(.*?)</article>",
        r'<div[^>]*class="[^"]*post[^"]*"[^>]*>(.*?)<aside',
    ):
        m = re.search(pat, html, re.DOTALL)
        if m:
            body_html = m.group(1)
            break
    if not body_html:
        return []

    body = re.sub(r"<[^>]+>", " ", body_html)
    body = re.sub(r"\s+", " ", body).strip()
    body_norm = _normalize(body)

    # Confirm pharma law context
    if not (
        PHARMA_LAW_RE.search(title_norm + body_norm)
        or PHARMA_TOPIC_RE.search(title_norm + body_norm)
    ):
        return []

    # Confirm enforcement keywords in body too
    if not ENFORCEMENT_TITLE_RE.search(body_norm):
        return []

    # Pref / city extraction
    pref_match = PREF_RE.search(title_norm) or PREF_RE.search(body_norm)
    if not pref_match:
        return []
    pref = pref_match.group(1)

    # Drop pure central announcements: must show pref-level action verbs
    pref_action_marks = [
        f"{pref}が",
        f"{pref}は",
        f"{pref}より",
        f"{pref}知事",
        f"{pref} 知事",
        f"{pref}市長",
        f"{pref}保健",
        f"{pref}健康",
        f"{pref}庁",
        f"{pref}を",
    ]
    has_pref_action = any(mk in body_norm for mk in pref_action_marks)
    has_central_only = (
        "厚生労働大臣" in body_norm
        or "厚労省より" in body_norm
        or "厚生労働省より" in body_norm
        or "厚生労働省は" in body_norm
        or "厚生労働省が" in body_norm
    ) and not has_pref_action
    if has_central_only:
        return []

    # Title-driven date (look in both title and body, prefer the OLDEST
    # wareki in the body which is typically the disposition date).
    date_iso = None
    for m in WAREKI_RE.finditer(body_norm):
        cand = _parse_date(m.group(0))
        if cand and "2000" <= cand <= "2030":
            date_iso = cand
            break
    if not date_iso:
        # Fallback: Wareki in title
        for m in WAREKI_RE.finditer(title_norm):
            cand = _parse_date(m.group(0))
            if cand and "2000" <= cand <= "2030":
                date_iso = cand
                break
    if not date_iso:
        return []

    # Action kind
    kind = "other"
    for k, pat in KIND_PATTERNS:
        if pat.search(body_norm):
            kind = k
            break

    # Companies
    companies = find_companies_in_text(body_norm)
    if not companies:
        companies = find_companies_in_text(title_norm)
    if not companies:
        return []

    # Authority: prefer 薬務課 / 健康局 if mentioned
    authority = pref
    for sub in (
        "薬務課",
        "薬事課",
        "薬務薬事課",
        "医薬安全課",
        "健康安全部",
        "健康局",
        "生活衛生課",
    ):
        if sub in body_norm:
            authority = f"{pref} {sub}"
            break

    related = "薬機法（医薬品医療機器等法）"
    art = re.search(r"第\s*(\d{1,3})\s*条(?:の\d+)?", body_norm)
    if art:
        related += f" 第{art.group(1)}条"

    reason = re.sub(r"\s+", " ", body_norm)[:1500]

    rows: list[EnfRow] = []
    seen: set[str] = set()
    for co in companies[:6]:  # Cap per page
        if co in seen:
            continue
        seen.add(co)
        target = co
        if is_personal_name_only(target):
            target = "（個人薬剤師：氏名匿名化）"
        rows.append(
            EnfRow(
                target_name=target[:200],
                enforcement_kind=kind,
                issuing_authority=authority,
                issuance_date=date_iso,
                reason_summary=reason,
                related_law_ref=related,
                source_url=archive_url,
                extra={
                    "title": title,
                    "feed": "h-crisis",
                    "all_companies": companies[:6],
                },
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Curated direct URL extraction
# ---------------------------------------------------------------------------


def _extract_pdf_text(blob: bytes) -> str:
    """Extract text from a PDF blob via pdfplumber.

    Returns "" on parse failure or for image-only PDFs (e.g. CCITT Fax).
    """
    try:
        import io

        import pdfplumber
    except ImportError:
        _LOG.warning("pdfplumber not installed; skip PDF")
        return ""
    try:
        with pdfplumber.open(io.BytesIO(blob)) as pdf:
            chunks: list[str] = []
            for page in pdf.pages:
                t = page.extract_text() or ""
                if t:
                    chunks.append(t)
            return "\n".join(chunks)
    except Exception as exc:
        _LOG.warning("pdf extract failed: %s", exc)
        return ""


def parse_direct_text(
    text: str,
    *,
    source_url: str,
    default_pref: str,
) -> list[EnfRow]:
    """Same shape as parse_direct_html but the input is already plain text
    (e.g. extracted from a PDF). Wraps parse_direct_html's logic by feeding
    a synthetic single-block HTML so existing filters apply.
    """
    # Wrap as a single HTML body so parse_direct_html can normalise.
    fake_html = "<html><body>" + text + "</body></html>"
    return parse_direct_html(
        fake_html,
        source_url=source_url,
        default_pref=default_pref,
    )


def parse_direct_html(
    html: str,
    *,
    source_url: str,
    default_pref: str,
) -> list[EnfRow]:
    """Parse any pref / city HTML page; emit one row per company found.

    The shape varies by city, but the common signal is:
      - One date on the page (the disposition date)
      - One or more company / pharmacy names
      - At least one of: 業務停止 / 業務改善 / 取消 / 課徴金 keyword
    """
    # Strip tags
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<[^>]+>", " ", text)
    body = re.sub(r"&nbsp;", " ", body)
    body = re.sub(r"&amp;", "&", body)
    body = re.sub(r"\s+", " ", body).strip()

    if not (PHARMA_LAW_RE.search(body) or PHARMA_TOPIC_RE.search(body)):
        return []
    # Confirm enforcement signal
    if not ENFORCEMENT_TITLE_RE.search(body):
        return []

    # Multiple actions may co-exist on a press release; assign per company
    companies = find_companies_in_text(body)
    if not companies:
        return []

    # All wareki dates on the page
    date_iso = None
    for m in WAREKI_RE.finditer(body):
        cand = _parse_date(m.group(0))
        if cand and "2000" <= cand <= "2030":
            date_iso = cand
            break
    if not date_iso:
        date_iso = _parse_date(body)
    if not date_iso:
        return []

    # Determine action kind — pick the strongest
    kind = "other"
    for k, pat in KIND_PATTERNS:
        if pat.search(body):
            kind = k
            break

    # Authority refinement
    authority = default_pref
    for sub in (
        "薬務課",
        "薬事課",
        "薬務薬事課",
        "医薬安全課",
        "生活衛生課",
        "健康局",
        "保健所",
        "薬務薬事グループ",
    ):
        if sub in body:
            authority = f"{default_pref} {sub}"
            break

    related = "薬機法（医薬品医療機器等法）"
    art = re.search(r"第\s*(\d{1,3})\s*条(?:の\d+)?", body)
    if art:
        related += f" 第{art.group(1)}条"

    out: list[EnfRow] = []
    seen_co: set[str] = set()
    reason = body[:1500]
    for co in companies[:6]:  # cap per source
        if co in seen_co:
            continue
        seen_co.add(co)
        target = co
        if is_personal_name_only(target):
            target = "（個人薬剤師：氏名匿名化）"
        out.append(
            EnfRow(
                target_name=target[:200],
                enforcement_kind=kind,
                issuing_authority=authority,
                issuance_date=date_iso,
                reason_summary=reason,
                related_law_ref=related,
                source_url=source_url,
                extra={"feed": "direct_press", "default_pref": default_pref},
            )
        )
    return out


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def _slug8(target: str, date: str, extra: str = "") -> str:
    h = hashlib.sha1(f"{target}|{date}|{extra}".encode()).hexdigest()
    return h[:8]


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
    """Universe of (target_name, issuance_date, issuing_authority) we should
    NOT re-insert. Loads broadly across the table to be safe."""
    out: set[tuple[str, str, str]] = set()
    cur = conn.execute(
        "SELECT IFNULL(target_name,''), issuance_date, "
        "IFNULL(issuing_authority,'') FROM am_enforcement_detail"
    )
    for n, d, a in cur.fetchall():
        if n and d:
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
    domain = urllib.parse.urlparse(url).netloc or None
    conn.execute(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence,
            source_url, source_url_domain, fetched_at, raw_json,
            canonical_status, citation_status
        ) VALUES (?, 'enforcement', 'pref_yakumu_yakkihou', NULL,
                  ?, NULL, 0.85, ?, ?, ?, ?, 'active', 'ok')
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
) -> tuple[int, int, int]:
    """Insert rows in retryable BEGIN IMMEDIATE blocks.

    Returns (inserted, dup_db, dup_batch)."""
    if not rows:
        return 0, 0, 0
    db_keys = existing_dedup_keys(conn)
    batch_keys: set[tuple[str, str, str]] = set()
    inserted = 0
    dup_db = 0
    dup_batch = 0

    last_err: Exception | None = None
    for attempt in range(6):
        try:
            conn.execute("BEGIN IMMEDIATE")
            local_inserted = 0
            for r in rows:
                # Mission-critical: drop PMDA-agent overlap by authority
                if PMDA_LIKE.search(r.issuing_authority):
                    continue
                key = (r.target_name, r.issuance_date, r.issuing_authority)
                if key in db_keys:
                    dup_db += 1
                    continue
                if key in batch_keys:
                    dup_batch += 1
                    continue
                batch_keys.add(key)

                slug = _slug8(r.target_name, r.issuance_date, r.source_url)
                date_compact = r.issuance_date.replace("-", "")
                canonical_id = f"enforcement:pref-yakumu-{date_compact}-{slug}"
                primary_name = (
                    f"{r.target_name} ({r.issuance_date}) - 薬機法処分 / {r.issuing_authority}"
                )
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
                        "license": ("政府機関の著作物（出典明記で転載引用可）"),
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
                    local_inserted += 1
                    if local_inserted % 50 == 0:
                        conn.commit()
                        conn.execute("BEGIN IMMEDIATE")
                except sqlite3.IntegrityError as exc:
                    _LOG.warning(
                        "integrity error name=%r date=%s: %s",
                        r.target_name,
                        r.issuance_date,
                        exc,
                    )
                    continue
                except sqlite3.Error as exc:
                    _LOG.error(
                        "DB error name=%r date=%s: %s",
                        r.target_name,
                        r.issuance_date,
                        exc,
                    )
                    continue
            conn.commit()
            return inserted, dup_db, dup_batch
        except sqlite3.OperationalError as exc:
            last_err = exc
            with contextlib.suppress(sqlite3.Error):
                conn.rollback()
            wait = 5 * (attempt + 1)
            _LOG.warning("write contention attempt=%d wait=%ds: %s", attempt, wait, exc)
            time.sleep(wait)
    if last_err is not None:
        raise last_err
    return inserted, dup_db, dup_batch


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def harvest(
    http: HttpClient,
    *,
    limit_urls: int | None = None,
) -> list[EnfRow]:
    out: list[EnfRow] = []

    # 1. H-CRISIS aggregator (NIPH primary mirror) — REST-API discovery
    archive_pairs = hcrisis_search_archive_urls(http)
    _LOG.info("h-crisis archive urls discovered: %d", len(archive_pairs))
    if limit_urls:
        archive_pairs = archive_pairs[:limit_urls]
    for i, (au, _title) in enumerate(archive_pairs, 1):
        res = http.get(au)
        if not res.ok:
            continue
        try:
            rows = parse_hcrisis_archive(res.text, au)
        except Exception as exc:
            _LOG.warning("parse h-crisis fail %s: %s", au, exc)
            continue
        if not rows:
            continue
        out.extend(rows)
        if i % 25 == 0:
            _LOG.info("h-crisis progress %d/%d rows=%d", i, len(archive_pairs), len(out))

    # 2. Curated pref / city URLs
    for pref, url in CURATED_URLS:
        is_pdf = url.lower().endswith(".pdf")
        res = http.get(
            url,
            max_bytes=10 * 1024 * 1024 if is_pdf else None,
        )
        if not res.ok:
            _LOG.debug("curated fetch fail %s status=%s", url, res.status)
            continue
        try:
            if is_pdf:
                text = _extract_pdf_text(res.body)
                if not text:
                    _LOG.warning("pdf empty %s", url)
                    continue
                rows = parse_direct_text(
                    text,
                    source_url=url,
                    default_pref=pref,
                )
            else:
                rows = parse_direct_html(
                    res.text,
                    source_url=url,
                    default_pref=pref,
                )
        except Exception as exc:
            _LOG.warning("parse direct fail %s: %s", url, exc)
            continue
        out.extend(rows)
        _LOG.info("direct pref=%s url=%s rows=%d", pref, url, len(rows))

    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument(
        "--limit-urls",
        type=int,
        default=None,
        help="cap H-CRISIS URLs for smoke test",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    http = HttpClient(user_agent=USER_AGENT)
    now_iso = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    rows = harvest(http, limit_urls=args.limit_urls)
    _LOG.info("total parsed rows=%d", len(rows))

    if args.dry_run:
        for r in rows[:8]:
            _LOG.info(
                "DRY: name=%s | date=%s | auth=%s | kind=%s | reason=%s",
                r.target_name,
                r.issuance_date,
                r.issuing_authority,
                r.enforcement_kind,
                r.reason_summary[:80],
            )
        http.close()
        # Per-prefecture breakdown for visibility
        bucket: dict[str, int] = {}
        for r in rows:
            bucket[r.issuing_authority] = bucket.get(r.issuing_authority, 0) + 1
        for k, v in sorted(bucket.items(), key=lambda x: -x[1])[:30]:
            print(f"  {k}: {v}")
        return 0

    if not args.db.exists():
        _LOG.error("autonomath.db missing: %s", args.db)
        http.close()
        return 2

    conn = sqlite3.connect(str(args.db), timeout=300.0)
    conn.execute("PRAGMA busy_timeout=300000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_tables(conn)

    inserted, dup_db, dup_batch = write_rows(conn, rows, now_iso=now_iso)
    with contextlib.suppress(sqlite3.Error):
        conn.close()
    http.close()

    _LOG.info(
        "done parsed=%d inserted=%d dup_db=%d dup_batch=%d",
        len(rows),
        inserted,
        dup_db,
        dup_batch,
    )
    print(
        f"pref 薬務 ingest: parsed={len(rows)} inserted={inserted} "
        f"dup_db={dup_db} dup_batch={dup_batch}"
    )
    # Per-authority breakdown
    bucket: dict[str, int] = {}
    for r in rows:
        if PMDA_LIKE.search(r.issuing_authority):
            continue
        bucket[r.issuing_authority] = bucket.get(r.issuing_authority, 0) + 1
    for k, v in sorted(bucket.items(), key=lambda x: -x[1])[:30]:
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
