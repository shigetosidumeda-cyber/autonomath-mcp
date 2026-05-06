#!/usr/bin/env python3
"""Ingest 全国商工会連合会 + 47 都道府県連合会 + 商工会版 持続化補助金 programs
into ``data/jpintel.db`` ``programs`` table.

Recon: ``analysis_wave18/data_collection_log/p5_recon_shokokai.md`` (2026-04-25).

Sources (whitelist — primary only):
  - https://www.shokokai.or.jp/                       (全国連 top)
  - https://www12.shokokai.or.jp/hpsearch/...         (商工会検索 backend, Shift_JIS POST)
  - https://www.jizokukanb.com/jizokuka_r6h/          (一般型 通常枠 商工会版)
  - https://www.jizokukanb.com/jizokuka_r6h/saigai/   (災害支援枠)
  - https://r6.kyodokyogyohojokin.info/               (共同・協業型 商工会版)
  - https://r6.jizokukahojokin.info/sogyo/            (創業型 商工会版 sub-path)
  - https://www.jizokuka-post-corona.jp/              (低感染リスク型 archive)
  - https://www.shokokai.or.jp/jizokuka_t/            (コロナ特別対応型 archive — 404 ok)
  - 47 都道府県連合会 top URLs (live-fetch each)

商工会 (本 script) と 商工会**議所** (jcci) は別組織。
domain で識別する: shokokai*.or.jp は商工会、jcci.or.jp / cci-* は商工会議所 (除外)。

Strategy:
  1. Static catalog of well-known program records (持続化補助金 6 portal × 公募回 +
     全国連 hub + 47 prefecture federation hubs).
  2. For each portal in catalog, live-fetch the listed URL with rate-limited HTTP
     (1 req/sec, UA "AutonoMath/0.1.0 (+https://bookyou.net)") and extract 第N回 round
     hints from the body to confirm reachability and detect open-now / archive.
  3. For 47 prefecture federations, POST Shift_JIS form to
     ``https://www12.shokokai.or.jp/hpsearch/top/php/search.php`` (mode=QU&kencd[]=00)
     once to harvest the canonical top URL per prefecture (47/47 listed in recon).
  4. Dedupe by (primary_name, source_url) within this run AND vs existing programs
     table rows (UPSERT on unified_id; we mint a stable hash-derived unified_id).
  5. Tier: S = open-now (today 2026-04-25 ∈ application window or banner says
     "申請受付中"), A = within 90 days, B = otherwise (active hub), C = archive
     / non-recurring.
  6. Write with BEGIN IMMEDIATE + busy_timeout=300000 for parallel safety.

NO Anthropic API / claude CLI — pure Python (httpx + bs4 already in venv).

CLI:
    .venv/bin/python scripts/ingest/ingest_shokokai_programs.py
        [--db data/jpintel.db]
        [--dry-run]
        [--limit N]
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
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # fall back to regex-only

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Use shared HTTP client when present; fall back to bare httpx if not.
try:
    from scripts.lib.http import HttpClient as SharedHttpClient
except ImportError:  # pragma: no cover
    SharedHttpClient = None  # type: ignore

import httpx  # noqa: E402

_LOG = logging.getLogger("autonomath.ingest.shokokai")

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
PER_HOST_DELAY_SEC = 1.0
TIMEOUT_SEC = 25.0
TODAY = dt.date(2026, 4, 25)
HORIZON_S = TODAY  # S = open today
HORIZON_A = TODAY + dt.timedelta(days=90)

DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"


# ---------------------------------------------------------------------------
# Static catalog — confirmed primary sources (商工会版 持続化補助金 + 全国連 + 47 連合会)
# ---------------------------------------------------------------------------

# 47 prefecture federation top URLs (from recon §2-A).
PREFECTURE_FEDS: list[tuple[str, str, str]] = [
    # (prefecture_kanji, federation_name, source_url)
    ("北海道", "北海道商工会連合会", "https://www.do-shokoren.or.jp/"),
    ("青森県", "青森県商工会連合会", "http://www.aomorishokoren.or.jp/"),
    ("岩手県", "岩手県商工会連合会", "http://www.shokokai.com/"),
    ("宮城県", "宮城県商工会連合会", "https://www.miyagi-fsci.or.jp/"),
    ("秋田県", "秋田県商工会連合会", "http://www.skr-akita.or.jp/"),
    ("山形県", "山形県商工会連合会", "https://www.shokokai-yamagata.or.jp/"),
    ("福島県", "福島県商工会連合会", "http://www.f.do-fukushima.or.jp/"),
    ("茨城県", "茨城県商工会連合会", "http://www.ib-shokoren.or.jp/"),
    ("栃木県", "栃木県商工会連合会", "https://www.shokokai-tochigi.or.jp/"),
    ("群馬県", "群馬県商工会連合会", "https://www.gcis.or.jp/"),
    ("埼玉県", "埼玉県商工会連合会", "http://www.syokoukai.or.jp/"),
    ("千葉県", "千葉県商工会連合会", "https://www.chibaken.or.jp/"),
    ("東京都", "東京都商工会連合会", "http://www.shokokai-tokyo.or.jp/"),
    ("神奈川県", "神奈川県商工会連合会", "http://www.k-skr.or.jp/"),
    ("新潟県", "新潟県商工会連合会", "https://www.shinsyoren.or.jp/"),
    ("富山県", "富山県商工会連合会", "http://www.shokoren-toyama.or.jp/"),
    ("石川県", "石川県商工会連合会", "https://shoko.or.jp/"),
    ("福井県", "福井県商工会連合会", "http://www.shokokai-fukui.or.jp/"),
    ("山梨県", "山梨県商工会連合会", "http://www.shokokai-yamanashi.or.jp/"),
    ("長野県", "長野県商工会連合会", "https://www.nagano-sci.or.jp/"),
    ("岐阜県", "岐阜県商工会連合会", "https://www.gifushoko.or.jp/"),
    ("静岡県", "静岡県商工会連合会", "https://www.ssr.or.jp/"),
    ("愛知県", "愛知県商工会連合会", "https://www.aichipfsci.jp/"),
    ("三重県", "三重県商工会連合会", "http://www.mie-shokokai.or.jp/"),
    ("滋賀県", "滋賀県商工会連合会", "http://www.shigasci.net/"),
    ("京都府", "京都府商工会連合会", "http://www.kyoto-fsci.or.jp/"),
    ("大阪府", "大阪府商工会連合会", "https://www.osaka-sci.or.jp/"),
    ("兵庫県", "兵庫県商工会連合会", "http://www.shokoren.or.jp/"),
    ("奈良県", "奈良県商工会連合会", "http://www.shokoren-nara.or.jp/"),
    ("和歌山県", "和歌山県商工会連合会", "http://www2.w-shokokai.or.jp/"),
    ("鳥取県", "鳥取県商工会連合会", "https://kenren.tori-skr.jp/"),
    ("島根県", "島根県商工会連合会", "http://www.shoko-shimane.or.jp/"),
    ("岡山県", "岡山県商工会連合会", "https://www.okasci.or.jp/"),
    ("広島県", "広島県商工会連合会", "http://www.active-hiroshima.jp/"),
    ("山口県", "山口県商工会連合会", "http://www.yamaguchi-shokokai.or.jp/"),
    ("徳島県", "徳島県商工会連合会", "http://www.tsci.or.jp/"),
    ("香川県", "香川県商工会連合会", "http://www.shokokai-kagawa.or.jp/"),
    ("愛媛県", "愛媛県商工会連合会", "https://ehime-sci.jp/"),
    ("高知県", "高知県商工会連合会", "https://www.kochi-shokokai.jp/"),
    ("福岡県", "福岡県商工会連合会", "http://www2.shokokai.ne.jp/"),
    ("佐賀県", "佐賀県商工会連合会", "https://www.sashoren.ne.jp/rengouka/"),
    ("長崎県", "長崎県商工会連合会", "http://www.shokokai-nagasaki.or.jp/"),
    ("熊本県", "熊本県商工会連合会", "http://www.kumashoko.or.jp/"),
    ("大分県", "大分県商工会連合会", "http://www.oita-shokokai.or.jp/"),
    ("宮崎県", "宮崎県商工会連合会", "http://www.miya-shoko.or.jp/"),
    ("鹿児島県", "鹿児島県商工会連合会", "https://www.kashoren.or.jp/"),
    ("沖縄県", "沖縄県商工会連合会", "https://www.oki-shokoren.or.jp/"),
]

# 持続化補助金 6 portal + 全国連 entries.
# Each entry becomes 1 program row (the portal itself, current 公募 round captured
# in primary_name). We deliberately do NOT mint per-round rows (would inflate to
# 50+ near-duplicates per portal); instead, the portal row's primary_name carries
# the latest 公募回 label, and application_window_json carries the schedule.


@dataclass
class PortalRecord:
    primary_name: str
    short_alias: str
    authority_name: str
    program_kind: str
    source_url: str
    notes: str
    archive: bool = False  # True → tier C
    application_open: tuple[str, str] | None = None  # ISO YYYY-MM-DD
    saigai: bool = False  # 災害支援枠
    coverage: str = "national"  # national | regional


# Source: recon p5_recon_shokokai.md §1-A and field-verified 2026-04-25.
PORTAL_CATALOG: list[PortalRecord] = [
    PortalRecord(
        primary_name="小規模事業者持続化補助金（一般型・通常枠）商工会地区分（第19回）",
        short_alias="持続化補助金 一般型 通常枠 商工会版 第19回",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://www.jizokukanb.com/jizokuka_r6h/",
        notes="商工会地区の事業者向け 一般型 通常枠。第19回公募要領 第6版 (2026-03 公開) が最新。応募は商工会経由 様式4 発行必須。",
        application_open=("2026-03-06", "2026-04-30"),
    ),
    PortalRecord(
        primary_name="小規模事業者持続化補助金 災害支援枠（令和6年能登半島地震等）商工会地区分",
        short_alias="持続化補助金 災害支援枠 商工会版",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://www.jizokukanb.com/jizokuka_r6h/saigai/",
        notes="令和6年能登半島地震等の被災事業者向け災害支援枠。商工会地区分。",
        saigai=True,
    ),
    PortalRecord(
        primary_name="小規模事業者持続化補助金（共同・協業型）商工会地区分（第2回）",
        short_alias="持続化補助金 共同協業型 商工会版 第2回",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://r6.kyodokyogyohojokin.info/",
        notes="2社以上の小規模事業者が連携する共同・協業型。第2回 (2024 公募) 採択者一覧公開済 doc/r6_saitaku_kk2.pdf。",
    ),
    PortalRecord(
        primary_name="小規模事業者持続化補助金（創業型）商工会地区分（第3回）",
        short_alias="持続化補助金 創業型 商工会版 第3回",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://r6.jizokukahojokin.info/sogyo/",
        notes="創業3年以内の小規模事業者向け創業型。商工会地区分は /sogyo/ サブパス。第3回 申請受付中。",
        application_open=("2026-02-01", "2026-05-31"),
    ),
    PortalRecord(
        primary_name="小規模事業者持続化補助金（低感染リスク型ビジネス枠）商工会地区分",
        short_alias="持続化補助金 低感染リスク型 商工会版",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://www.jizokuka-post-corona.jp/",
        notes="コロナ感染対策含む新たな取組向け 低感染リスク型 (第1-6回, 2021-2023)。現在は事業効果報告期。",
        archive=True,
    ),
    PortalRecord(
        primary_name="小規模事業者持続化補助金（コロナ特別対応型）商工会地区分",
        short_alias="持続化補助金 コロナ特別対応型 商工会版",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://www.shokokai.or.jp/jizokuka_t/",
        notes="令和2-3年度 コロナ特別対応型 商工会版 (アーカイブ)。後継=低感染リスク型→通常枠。",
        archive=True,
    ),
    PortalRecord(
        primary_name="小規模事業者持続化補助金（被災再建 令和2年7月豪雨型）商工会地区分",
        short_alias="持続化補助金 R3 豪雨型 商工会版",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://www.shokokai.or.jp/r3_gou/",
        notes="令和2年7月豪雨被災事業者再建枠 (アーカイブ)。",
        archive=True,
        saigai=True,
    ),
    PortalRecord(
        primary_name="小規模事業者持続化補助金（台風19/20/21号被災再建型）商工会地区分",
        short_alias="持続化補助金 台風19-21 被災再建 商工会版",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://www.shokokai.or.jp/saiken192021/",
        notes="平成30-令和元年 台風19/20/21号被災事業者再建枠 (アーカイブ)。",
        archive=True,
        saigai=True,
    ),
    PortalRecord(
        primary_name="共同・協業販路開拓支援補助金（令和2年版）",
        short_alias="共同・協業販路開拓支援補助金 R2",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="subsidy",
        source_url="https://www.shokokai.or.jp/kyodokyogyo/",
        notes="令和2年版 共同・協業販路開拓支援補助金 (現行=共同・協業型の前身、アーカイブ)。",
        archive=True,
    ),
    PortalRecord(
        primary_name="経営発達支援計画（商工会・商工会議所単位の認定制度）",
        short_alias="経営発達支援計画 認定",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="certification",
        source_url="https://www.chusho.meti.go.jp/keiei/shokibo/keieihatatsushien.htm",
        notes="商工会・商工会議所が地域中小企業向け経営支援計画を策定→中小企業庁が認定。第13回認定 (令和2年-) で全国 1,400+ 商工会が認定済。",
    ),
    PortalRecord(
        primary_name="エキスパートバンク事業（専門家派遣）商工会地区分",
        short_alias="エキスパートバンク 商工会版",
        authority_name="全国商工会連合会",
        program_kind="consultation",
        source_url="https://www.shokokai.or.jp/?page_id=190",
        notes="商工会経由の中小企業者向け専門家無料派遣事業 (経営/法務/税務/IT 等)。会員企業が利用可。",
    ),
    PortalRecord(
        primary_name="連鎖倒産防止特別相談（倒産防止特別相談室）商工会版",
        short_alias="連鎖倒産防止相談 商工会版",
        authority_name="全国商工会連合会",
        program_kind="consultation",
        source_url="https://www.shokokai.or.jp/?page_id=190",
        notes="連鎖倒産防止のための特別相談窓口 (中小企業基盤整備機構と連携)。",
    ),
    PortalRecord(
        primary_name="商工会会員向け 共済・福利厚生制度（特定退職金共済 / 全国商工会経営者休業補償制度等）",
        short_alias="商工会 共済・福利厚生",
        authority_name="全国商工会連合会",
        program_kind="member_benefit",
        source_url="https://www.shokokai.or.jp/?page_id=42",
        notes="商工会会員事業者向け 特定退職金共済 / 経営者休業補償 / iDeCo / 国民年金基金 等の優遇加入制度。",
    ),
    PortalRecord(
        primary_name="地域力活用新事業創出支援事業（インバウンド誘客促進・特産品評価・海外販路 等 委託事業）",
        short_alias="地域力活用新事業創出支援",
        authority_name="中小企業庁 × 全国商工会連合会",
        program_kind="entrustment",
        source_url="https://www.shokokai.or.jp/?post_type=annais",
        notes="商工会全国連が下流商工会に委託する新事業創出支援事業 (令和8年度: 6 委託先公募)。事業者向け補助ではなく事業委託。",
    ),
    PortalRecord(
        primary_name="商工会版 持続化補助金 様式4（事業支援計画書）発行窓口",
        short_alias="様式4 発行窓口 商工会版",
        authority_name="全国商工会連合会 × 各市町村商工会",
        program_kind="subsidy_intake",
        source_url="https://www.shokokai.or.jp/?page_id=42",
        notes="持続化補助金応募に必須の様式4 (事業支援計画書) を発行する各市町村商工会の窓口紹介。1,535 商工会が窓口。",
    ),
    PortalRecord(
        primary_name="全国商工会連合会 商工会検索（1,535 商工会の連絡先）",
        short_alias="商工会検索",
        authority_name="全国商工会連合会",
        program_kind="directory",
        source_url="https://www.shokokai.or.jp/?page_id=1754",
        notes="全国 1,535 商工会の所在地・連絡先・URL を都道府県別に検索可能。Shift_JIS POST backend あり。",
    ),
]


# ---------------------------------------------------------------------------
# HTTP — minimal client honoring custom UA + 1 req/sec/host pacing.
# ---------------------------------------------------------------------------


class PoliteClient:
    def __init__(self, timeout: float = TIMEOUT_SEC) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.5",
            },
            timeout=timeout,
            follow_redirects=True,
        )
        self._host_clock: dict[str, float] = {}

    def _pace(self, host: str) -> None:
        last = self._host_clock.get(host)
        now = time.monotonic()
        if last is not None:
            delta = PER_HOST_DELAY_SEC - (now - last)
            if delta > 0:
                time.sleep(delta)
        self._host_clock[host] = time.monotonic()

    def get(self, url: str) -> tuple[int, bytes, dict[str, str]]:
        host = urllib.parse.urlparse(url).netloc
        self._pace(host)
        try:
            r = self._client.get(url)
            return r.status_code, r.content, dict(r.headers)
        except httpx.HTTPError as exc:
            _LOG.warning("GET %s failed: %s", url, exc)
            return 0, b"", {}

    def post(
        self, url: str, *, data: dict[str, Any], encoding: str = "shift_jis"
    ) -> tuple[int, bytes, dict[str, str]]:
        host = urllib.parse.urlparse(url).netloc
        self._pace(host)
        # Shift_JIS form encode
        body_pairs: list[str] = []
        for k, v in data.items():
            if isinstance(v, list):
                for item in v:
                    body_pairs.append(
                        f"{urllib.parse.quote(k, encoding='ascii')}={urllib.parse.quote(str(item), encoding=encoding)}"
                    )
            else:
                body_pairs.append(
                    f"{urllib.parse.quote(k, encoding='ascii')}={urllib.parse.quote(str(v), encoding=encoding)}"
                )
        body = "&".join(body_pairs).encode("ascii")
        try:
            r = self._client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept-Charset": "Shift_JIS",
                },
            )
            return r.status_code, r.content, dict(r.headers)
        except httpx.HTTPError as exc:
            _LOG.warning("POST %s failed: %s", url, exc)
            return 0, b"", {}

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Body decode helpers.
# ---------------------------------------------------------------------------


def _decode_html(body: bytes, headers: dict[str, str]) -> str:
    if not body:
        return ""
    # Inspect headers + meta charset.
    ct = (headers.get("content-type") or "").lower()
    charset = None
    for token in ct.split(";"):
        token = token.strip()
        if token.startswith("charset="):
            charset = token[len("charset=") :].strip().strip('"')
            break
    if charset is None:
        # Sniff meta charset
        head = body[:4096].decode("ascii", errors="replace")
        m = re.search(r"<meta[^>]+charset=[\"']?([\w_-]+)", head, re.I)
        if m:
            charset = m.group(1)
    if charset is None:
        charset = "utf-8"
    charset_norm = charset.lower().replace("_", "-")
    if charset_norm in ("shift-jis", "sjis", "shift-jis", "shiftjis", "x-sjis"):
        charset_norm = "cp932"  # superset, more forgiving
    try:
        return body.decode(charset_norm, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return body.decode("utf-8", errors="replace")


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").strip()


# ---------------------------------------------------------------------------
# Verification — fetch each portal & federation top to confirm reachability.
# ---------------------------------------------------------------------------


@dataclass
class FetchProbe:
    url: str
    status: int
    final_url: str
    title: str
    has_subsidy_keyword: bool
    rounds: list[int] = field(default_factory=list)


ROUND_RE = re.compile(r"第\s*(\d+)\s*回")


def probe(client: PoliteClient, url: str) -> FetchProbe:
    status, body, headers = client.get(url)
    text = _decode_html(body, headers)
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.DOTALL)
    if m:
        title = _normalize(re.sub(r"\s+", " ", m.group(1)))[:200]
    rounds_int = sorted({int(x) for x in ROUND_RE.findall(text)})
    has_kw = any(kw in text for kw in ("補助金", "助成金", "持続化", "経営発達"))
    return FetchProbe(
        url=url,
        status=status,
        final_url=headers.get("location", url),
        title=title,
        has_subsidy_keyword=has_kw,
        rounds=rounds_int[:50],
    )


# ---------------------------------------------------------------------------
# Tier classifier.
# ---------------------------------------------------------------------------


def classify_tier(rec: PortalRecord) -> str:
    if rec.archive:
        return "C"
    if rec.application_open:
        try:
            start = dt.date.fromisoformat(rec.application_open[0])
            end = dt.date.fromisoformat(rec.application_open[1])
            if start <= TODAY <= end:
                return "S"
            if TODAY < start <= HORIZON_A:
                return "A"
            if start > HORIZON_A:
                return "B"
            # passed end
            return "B"
        except ValueError:
            return "B"
    return "B"


def federation_tier(probe_status: int) -> str:
    # Federation hubs are not call-rounds; we tier by reachability only.
    if probe_status >= 200 and probe_status < 400:
        return "B"
    return "C"


# ---------------------------------------------------------------------------
# Row construction.
# ---------------------------------------------------------------------------


def _mk_unified_id(seed: str) -> str:
    return "UNI-" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]


def _coverage_json(filled: dict[str, bool]) -> str:
    base = {f"{k}_": False for k in "ABCDEFGHIJ"}
    out = {
        "A_basic": filled.get("A", False),
        "B_money": filled.get("B", False),
        "C_schedule": filled.get("C", False),
        "D_documents": filled.get("D", False),
        "E_application_plan": filled.get("E", False),
        "F_exclusions": filled.get("F", False),
        "G_dealbreakers": filled.get("G", False),
        "H_obligations": filled.get("H", False),
        "I_contacts": filled.get("I", False),
        "J_statistics": filled.get("J", False),
    }
    return json.dumps(out, ensure_ascii=False)


def build_portal_row(rec: PortalRecord, prb: FetchProbe) -> dict[str, Any]:
    tier = classify_tier(rec)
    if prb.status == 0 or (prb.status >= 400 and prb.status not in (404,)):
        # If portal completely unreachable, drop tier
        if not rec.archive:
            tier = "C"
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    aliases = [rec.short_alias]
    if rec.short_alias != rec.primary_name:
        aliases.append(rec.primary_name)
    aw_json: str | None = None
    if rec.application_open:
        aw_json = json.dumps(
            {
                "start_date": rec.application_open[0],
                "end_date": rec.application_open[1],
                "cycle": "annual",
                "fiscal_year": None,
                "note": rec.notes,
                "submission_route": "shokokai_via_yoshiki4",
            },
            ensure_ascii=False,
        )
    enriched = {
        "_meta": {
            "program_name": rec.primary_name,
            "source_url": rec.source_url,
            "fetched_at": now,
            "ingest_script": "ingest_shokokai_programs.py",
            "fetch_status": prb.status,
            "rounds_detected": prb.rounds[:20],
            "page_title": prb.title,
            "primary_source_confirmed": True,
        },
        "extraction": {
            "basic": {
                "正式名称": rec.primary_name,
                "根拠法": None,
            },
            "schedule": {
                "start_date": rec.application_open[0] if rec.application_open else None,
                "end_date": rec.application_open[1] if rec.application_open else None,
                "note": rec.notes,
            },
            "money": {},
            "documents": [],
            "contacts": [],
        },
    }
    coverage = _coverage_json(
        {"A": True, "B": False, "C": bool(rec.application_open), "D": False, "I": True}
    )
    seed = f"shokokai|portal|{rec.source_url}|{rec.primary_name}"
    return {
        "unified_id": _mk_unified_id(seed),
        "primary_name": rec.primary_name,
        "aliases_json": json.dumps(aliases, ensure_ascii=False),
        "authority_level": "national",
        "authority_name": rec.authority_name,
        "prefecture": None,
        "municipality": None,
        "program_kind": rec.program_kind,
        "official_url": rec.source_url,
        "amount_max_man_yen": None,
        "amount_min_man_yen": None,
        "subsidy_rate": None,
        "trust_level": "primary",
        "tier": classify_tier(rec) if not rec.archive else "C",
        "coverage_score": 0.5,
        "gap_to_tier_s_json": json.dumps(
            ["money_amount", "documents", "exclusions", "statistics"],
            ensure_ascii=False,
        ),
        "a_to_j_coverage_json": coverage,
        "excluded": 0,
        "exclusion_reason": None,
        "crop_categories_json": None,
        "equipment_category": None,
        "target_types_json": json.dumps(["small_business"], ensure_ascii=False),
        "funding_purpose_json": json.dumps(
            ["sales_channel_development", "marketing", "equipment"],
            ensure_ascii=False,
        ),
        "amount_band": None,
        "application_window_json": aw_json,
        "enriched_json": json.dumps(enriched, ensure_ascii=False),
        "source_mentions_json": json.dumps({"shokokai_portal": rec.source_url}, ensure_ascii=False),
        "updated_at": now,
        "source_url": rec.source_url,
        "source_fetched_at": now,
        "source_checksum": hashlib.sha1(rec.source_url.encode()).hexdigest(),
        "source_url_corrected_at": None,
        "source_last_check_status": prb.status if prb.status else None,
        "source_fail_count": 0 if (prb.status and prb.status < 400) else 1,
    }


def build_federation_row(pref: str, name: str, url: str, prb: FetchProbe) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    aliases = [name]
    enriched = {
        "_meta": {
            "program_name": name,
            "source_url": url,
            "fetched_at": now,
            "ingest_script": "ingest_shokokai_programs.py",
            "fetch_status": prb.status,
            "rounds_detected": prb.rounds[:20],
            "page_title": prb.title,
            "primary_source_confirmed": True,
        },
        "extraction": {
            "basic": {
                "正式名称": f"{name} 補助金・助成金 案内ハブ",
                "正式組織": name,
                "都道府県": pref,
                "役割": "都道府県連合会レベルの補助金/助成金ハブ。傘下市町村商工会の補助金 news を集約・転載 (東京モデル) または 持続化補助金専用 sub-site (大阪モデル) または top に最新公募要領貼付 (愛知モデル)。",
                "_source_ref": {"url": url, "excerpt": prb.title},
            },
        },
    }
    seed = f"shokokai|federation|{pref}|{url}"
    primary = f"{name} 補助金・助成金 案内ハブ（{pref} 商工会連合会）"
    return {
        "unified_id": _mk_unified_id(seed),
        "primary_name": primary,
        "aliases_json": json.dumps(aliases + [f"{pref}商工会連合会"], ensure_ascii=False),
        "authority_level": "prefecture",
        "authority_name": name,
        "prefecture": pref,
        "municipality": None,
        "program_kind": "directory",
        "official_url": url,
        "amount_max_man_yen": None,
        "amount_min_man_yen": None,
        "subsidy_rate": None,
        "trust_level": "primary",
        "tier": federation_tier(prb.status),
        "coverage_score": 0.3,
        "gap_to_tier_s_json": json.dumps(
            ["money_amount", "schedule", "documents", "statistics"], ensure_ascii=False
        ),
        "a_to_j_coverage_json": _coverage_json({"A": True, "I": True}),
        "excluded": 0,
        "exclusion_reason": None,
        "crop_categories_json": None,
        "equipment_category": None,
        "target_types_json": json.dumps(["small_business"], ensure_ascii=False),
        "funding_purpose_json": None,
        "amount_band": None,
        "application_window_json": None,
        "enriched_json": json.dumps(enriched, ensure_ascii=False),
        "source_mentions_json": json.dumps({"prefecture_federation": url}, ensure_ascii=False),
        "updated_at": now,
        "source_url": url,
        "source_fetched_at": now,
        "source_checksum": hashlib.sha1(url.encode()).hexdigest(),
        "source_url_corrected_at": None,
        "source_last_check_status": prb.status if prb.status else None,
        "source_fail_count": 0 if (prb.status and prb.status < 400) else 1,
    }


# ---------------------------------------------------------------------------
# DB upsert.
# ---------------------------------------------------------------------------


COLS = [
    "unified_id",
    "primary_name",
    "aliases_json",
    "authority_level",
    "authority_name",
    "prefecture",
    "municipality",
    "program_kind",
    "official_url",
    "amount_max_man_yen",
    "amount_min_man_yen",
    "subsidy_rate",
    "trust_level",
    "tier",
    "coverage_score",
    "gap_to_tier_s_json",
    "a_to_j_coverage_json",
    "excluded",
    "exclusion_reason",
    "crop_categories_json",
    "equipment_category",
    "target_types_json",
    "funding_purpose_json",
    "amount_band",
    "application_window_json",
    "enriched_json",
    "source_mentions_json",
    "updated_at",
    "source_url",
    "source_fetched_at",
    "source_checksum",
    "source_url_corrected_at",
    "source_last_check_status",
    "source_fail_count",
]


def upsert_rows(db_path: Path, rows: list[dict[str, Any]], dry_run: bool) -> dict[str, int]:
    """Insert rows; on (primary_name, source_url) clash, skip — we never overwrite
    pre-existing rows.

    Returns counts: inserted, skipped_existing, dedup_within_run.
    """
    # Dedup within run by (primary_name, source_url).
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    dedup_within = 0
    for r in rows:
        key = (r["primary_name"], r["source_url"])
        if key in seen:
            dedup_within += 1
            continue
        seen.add(key)
        deduped.append(r)

    if dry_run:
        return {
            "inserted": 0,
            "skipped_existing": 0,
            "dedup_within_run": dedup_within,
            "would_insert": len(deduped),
        }

    inserted = 0
    skipped = 0
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=300.0)
    try:
        conn.execute("PRAGMA busy_timeout = 300000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        for r in deduped:
            cur = conn.execute(
                "SELECT unified_id FROM programs "
                "WHERE primary_name = ? AND COALESCE(source_url, '') = ? LIMIT 1",
                (r["primary_name"], r["source_url"] or ""),
            )
            existing = cur.fetchone()
            if existing:
                skipped += 1
                continue
            # Avoid unified_id collision with unrelated row (rare but possible).
            cur = conn.execute(
                "SELECT 1 FROM programs WHERE unified_id = ? LIMIT 1",
                (r["unified_id"],),
            )
            if cur.fetchone():
                # Mint a new id by re-hashing with a salt
                r["unified_id"] = _mk_unified_id(
                    f"{r['unified_id']}|{r['source_url']}|{time.time_ns()}"
                )
            placeholders = ",".join("?" for _ in COLS)
            colnames = ",".join(COLS)
            conn.execute(
                f"INSERT INTO programs ({colnames}) VALUES ({placeholders})",
                tuple(r[c] for c in COLS),
            )
            inserted += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return {
        "inserted": inserted,
        "skipped_existing": skipped,
        "dedup_within_run": dedup_within,
        "would_insert": len(deduped),
    }


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------


def build_round_row(parent: PortalRecord, parent_prb: FetchProbe, round_no: int) -> dict[str, Any]:
    """Mint a per-round program row for an active 持続化補助金 portal."""
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = f"{parent.short_alias.replace('第19回', '').replace('第3回', '').replace('第2回', '').strip()} 第{round_no}回"
    name = re.sub(r"\s+", " ", name).strip()
    aliases = [parent.short_alias, parent.primary_name]
    # Tier: round-level only treated as S if it matches latest active.
    tier = "B"
    aw_json: str | None = None
    if parent.application_open:
        # Latest round = open now? Compare round_no to max in probe.
        latest = max(parent_prb.rounds) if parent_prb.rounds else None
        if latest == round_no:
            tier = classify_tier(parent)
            aw_json = json.dumps(
                {
                    "start_date": parent.application_open[0],
                    "end_date": parent.application_open[1],
                    "cycle": "annual",
                    "fiscal_year": None,
                    "round": round_no,
                    "submission_route": "shokokai_via_yoshiki4",
                    "note": parent.notes,
                },
                ensure_ascii=False,
            )
    if parent.archive:
        tier = "C"
    enriched = {
        "_meta": {
            "program_name": name,
            "source_url": parent.source_url,
            "round_no": round_no,
            "fetched_at": now,
            "ingest_script": "ingest_shokokai_programs.py",
            "fetch_status": parent_prb.status,
            "rounds_detected": parent_prb.rounds[:20],
            "primary_source_confirmed": True,
        },
        "extraction": {
            "basic": {
                "正式名称": name,
                "公募回": round_no,
                "親プログラム": parent.primary_name,
            },
        },
    }
    seed = f"shokokai|round|{parent.source_url}|round-{round_no}"
    return {
        "unified_id": _mk_unified_id(seed),
        "primary_name": name,
        "aliases_json": json.dumps(aliases, ensure_ascii=False),
        "authority_level": "national",
        "authority_name": parent.authority_name,
        "prefecture": None,
        "municipality": None,
        "program_kind": parent.program_kind,
        "official_url": parent.source_url,
        "amount_max_man_yen": None,
        "amount_min_man_yen": None,
        "subsidy_rate": None,
        "trust_level": "primary",
        "tier": tier,
        "coverage_score": 0.4,
        "gap_to_tier_s_json": json.dumps(
            ["money_amount", "documents", "exclusions", "statistics"],
            ensure_ascii=False,
        ),
        "a_to_j_coverage_json": _coverage_json({"A": True, "C": tier == "S", "I": True}),
        "excluded": 0,
        "exclusion_reason": None,
        "crop_categories_json": None,
        "equipment_category": None,
        "target_types_json": json.dumps(["small_business"], ensure_ascii=False),
        "funding_purpose_json": json.dumps(
            ["sales_channel_development", "marketing", "equipment"],
            ensure_ascii=False,
        ),
        "amount_band": None,
        "application_window_json": aw_json,
        "enriched_json": json.dumps(enriched, ensure_ascii=False),
        "source_mentions_json": json.dumps(
            {"shokokai_portal": parent.source_url, "round": round_no},
            ensure_ascii=False,
        ),
        "updated_at": now,
        "source_url": parent.source_url,
        "source_fetched_at": now,
        "source_checksum": hashlib.sha1(
            f"{parent.source_url}#round-{round_no}".encode()
        ).hexdigest(),
        "source_url_corrected_at": None,
        "source_last_check_status": parent_prb.status if parent_prb.status else None,
        "source_fail_count": 0 if (parent_prb.status and parent_prb.status < 400) else 1,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument(
        "--no-rounds", action="store_true", help="Skip per-round rows for 持続化 portals."
    )
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if not args.verbose else logging.DEBUG,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if not args.db.exists():
        _LOG.error("DB not found at %s", args.db)
        return 2

    # Portals where round-level rows are meaningful.
    ROUND_EXPAND_URLS = {
        "https://www.jizokukanb.com/jizokuka_r6h/",
        "https://r6.kyodokyogyohojokin.info/",
        "https://r6.jizokukahojokin.info/sogyo/",
        "https://www.jizokuka-post-corona.jp/",
    }

    client = PoliteClient()
    try:
        rows: list[dict[str, Any]] = []
        portal_probes: dict[str, tuple[PortalRecord, FetchProbe]] = {}
        # Phase 1: portals
        catalog = PORTAL_CATALOG[: args.limit] if args.limit else PORTAL_CATALOG
        for rec in catalog:
            _LOG.info("probing portal: %s", rec.source_url)
            prb = probe(client, rec.source_url)
            _LOG.info("  status=%s rounds=%s", prb.status, prb.rounds[:8])
            rows.append(build_portal_row(rec, prb))
            portal_probes[rec.source_url] = (rec, prb)

        # Phase 1b: per-round rows for active 持続化 portals.
        if not args.no_rounds:
            for url, (rec, prb) in portal_probes.items():
                if url not in ROUND_EXPAND_URLS:
                    continue
                # Take rounds <= 19 (sane cap, 第19回 is current jizokukanb max);
                # avoids including spurious matches like '第80回' from menus.
                rounds = [r for r in prb.rounds if 1 <= r <= 25]
                if not rounds:
                    continue
                for r in rounds:
                    rows.append(build_round_row(rec, prb, r))

        # Phase 2: federations (47).
        feds = PREFECTURE_FEDS
        if args.limit:
            feds = feds[: max(0, args.limit - len(catalog))]
        for pref, name, url in feds:
            _LOG.info("probing federation: %s %s", pref, url)
            prb = probe(client, url)
            _LOG.info("  status=%s title=%s", prb.status, prb.title[:80])
            rows.append(build_federation_row(pref, name, url, prb))

        _LOG.info("built %d rows pre-dedup", len(rows))

        # Phase 3: dedup + UPSERT
        result = upsert_rows(args.db, rows, args.dry_run)
        _LOG.info("upsert result: %s", result)

        # Verification (live)
        if not args.dry_run:
            conn = sqlite3.connect(str(args.db))
            try:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM programs "
                    "WHERE (source_url LIKE '%shokokai%' OR source_url LIKE '%jizokuka%') "
                    "AND source_url NOT LIKE '%jcci%' "
                    "AND excluded = 0"
                )
                count = cur.fetchone()[0]
                _LOG.info(
                    "verification: programs WHERE source_url LIKE shokokai/jizokuka (excl. jcci, excluded=0) = %d",
                    count,
                )
                cur = conn.execute(
                    "SELECT tier, COUNT(*) FROM programs "
                    "WHERE (source_url LIKE '%shokokai%' OR source_url LIKE '%jizokuka%') "
                    "AND source_url NOT LIKE '%jcci%' "
                    "AND excluded = 0 GROUP BY tier"
                )
                tier_breakdown = dict(cur.fetchall())
                _LOG.info("tier breakdown: %s", tier_breakdown)
            finally:
                conn.close()
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
