#!/usr/bin/env python3
"""Ingest 総務省 + 全国 10 総合通信局 + 沖縄総合通信事務所 の電気通信事業法・
電波法・放送法 違反による行政処分を ``am_enforcement_detail`` に追加する。

Sources
-------

* 総務本省 報道資料 (Shift_JIS): /menu_news/s-news/{YYMM}m.html (annual)
* 関東総合通信局: /soutsu/kanto/release{YYYY}.html (2014–current)
* 信越総合通信局: /soutsu/shinetsu/sbt/hodo/{h25..h30,r01..r07}houdo.html
                + /soutsu/shinetsu/sbt/hodo/houdou1.html (current)
* 東海総合通信局: /soutsu/tokai/kohosiryo/{YYYY}/index.html
* 近畿総合通信局: /soutsu/kinki/new/index{YYYY}.html (+ index.html=current)
* 中国総合通信局: /soutsu/chugoku/hodo/index{YYYY}.html
* 四国総合通信局: /soutsu/shikoku/press/index{YYYY}.html
* 九州総合通信局: /soutsu/kyushu/press/index{YYYY}.html
* 東北総合通信局: /soutsu/tohoku/hodo/index{YYYY}.html
* 北海道総合通信局: /soutsu/hokkaido/houdou{YYYY}.htm
                  + /soutsu/hokkaido/houdou_release.htm (current)
* 北陸総合通信局: /soutsu/hokuriku/press/{YYYY}/index.html
* 沖縄総合通信事務所: /soutsu/okinawa/hodo/index{YYYY}.html

ALL pages are Shift_JIS encoded. soumu.go.jp has no Akamai screening — plain
``urllib.request`` works (verified 2026-04-25).

Per repository directive 2026-04-25 (TOS 無視で獲得優先): we collect raw
press releases for AutonoMath ¥3/req launch (2026-05-06).
PDL v1.0 attribution preserved in raw_json.

Coverage estimate (2015..2026 × 11 regions): ~1,275 enforcement-keyword anchors
(reality-checked 2026-04-25). Target: +200 minimum.

enforcement_kind mapping (CHECK constraint):
    business_improvement (業務改善命令)
    license_revoke       (認定/登録/免許 取消)
    contract_suspend     (運用停止 / 業務停止 / 従事停止)
    fine                 (罰金 — まれ)
    investigation        (摘発 / 取締り)
    other                (指導 / 文書注意 等)

法 mapping:
    電気通信事業法
    電波法
    放送法
    電気通信事業者協会協約 (二次)
    信書便事業 (信書の送達に関する法律)

Schema target: am_entities + am_enforcement_detail.
Concurrency: BEGIN IMMEDIATE + busy_timeout=300000.
Dedup: (issuance_date[:10], target_name, issuing_authority).

CLI:
    python scripts/ingest/ingest_enforcement_soumu_telecom.py
    python scripts/ingest/ingest_enforcement_soumu_telecom.py --years 2020-2026
    python scripts/ingest/ingest_enforcement_soumu_telecom.py --regions kanto,kinki
    python scripts/ingest/ingest_enforcement_soumu_telecom.py --max-rows 500
    python scripts/ingest/ingest_enforcement_soumu_telecom.py --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import html as html_module
import json
import logging
import random
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("autonomath.ingest_soumu_telecom")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# ---------- Region archive registry ------------------------------------------

# Each region defines the URL templates for its annual archive index pages.
# Format strings use ``{}`` for the year (西暦 4-digit) unless otherwise noted.
# Notes:
#   - shinetsu has split: h25..h30 (Heisei) + r01..r07 (Reiwa) + houdou1.html (current)
#   - kinki/hokkaido/shinetsu have a separate "current year" index
#   - hokuriku has YYYY in directory not query string

REGION_INDEX: dict[str, dict[str, Any]] = {
    "kanto": {
        "name": "関東総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/kanto/release{}.html",
        "year_range": (2014, 2026),  # release2026.html exists if/when
        "current": "https://www.soumu.go.jp/soutsu/kanto/release_press.html",
    },
    "kinki": {
        "name": "近畿総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/kinki/new/index{}.html",
        "year_range": (2013, 2025),
        "current": "https://www.soumu.go.jp/soutsu/kinki/new/index.html",
    },
    "tokai": {
        "name": "東海総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/tokai/kohosiryo/{}/index.html",
        "year_range": (2019, 2026),
        "current": None,  # the per-year index includes current year
    },
    "chugoku": {
        "name": "中国総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/chugoku/hodo/index{}.html",
        "year_range": (2014, 2026),
        "current": None,
    },
    "shikoku": {
        "name": "四国総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/shikoku/press/index{}.html",
        "year_range": (2015, 2026),
        "current": "https://www.soumu.go.jp/soutsu/shikoku/press/index.html",
    },
    "kyushu": {
        "name": "九州総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/kyushu/press/index{}.html",
        "year_range": (2014, 2026),
        "current": "https://www.soumu.go.jp/soutsu/kyushu/press/index.html",
    },
    "tohoku": {
        "name": "東北総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/tohoku/hodo/index{}.html",
        "year_range": (2014, 2026),
        "current": None,
    },
    "hokkaido": {
        "name": "北海道総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/hokkaido/houdou{}.htm",
        "year_range": (2013, 2025),
        "current": "https://www.soumu.go.jp/soutsu/hokkaido/houdou_release.htm",
    },
    "hokuriku": {
        "name": "北陸総合通信局",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/hokuriku/press/{}/index.html",
        "year_range": (2014, 2026),
        "current": None,
    },
    "okinawa": {
        "name": "沖縄総合通信事務所",
        "authority_canonical": "authority:soumu-sogotsushin",
        "tmpl": "https://www.soumu.go.jp/soutsu/okinawa/hodo/index{}.html",
        "year_range": (2014, 2025),
        "current": "https://www.soumu.go.jp/soutsu/okinawa/",
    },
}

# 信越 uses Wareki-coded archive paths
SHINETSU_HEISEI_RANGE = list(range(25, 31))  # h25..h30 = 2013..2018
SHINETSU_REIWA_RANGE = list(range(1, 8))  # r01..r07 = 2019..2025
SHINETSU_TMPL_H = "https://www.soumu.go.jp/soutsu/shinetsu/sbt/hodo/h{:02d}houdo.html"
SHINETSU_TMPL_R = "https://www.soumu.go.jp/soutsu/shinetsu/sbt/hodo/r{:02d}houdo.html"
SHINETSU_CURRENT = "https://www.soumu.go.jp/soutsu/shinetsu/sbt/hodo/houdou1.html"

# 総務本省 月次 archive: /menu_news/s-news/{YY}{MM}m.html (Shift_JIS)
SOUMU_MAIN_TMPL = "https://www.soumu.go.jp/menu_news/s-news/{yy:02d}{mm:02d}m.html"

# ---------- Keyword filters --------------------------------------------------

# Anchor text must contain at least one of these keywords to be considered.
# These are tight enforcement-action keywords (not just topic mentions).
ENFORCEMENT_KEYWORDS = [
    # 電気通信事業法 系
    "業務改善命令",
    "業務停止命令",
    "電気通信事業の登録の取消",
    "電気通信事業の登録取消",
    "電気通信事業の登録抹消",
    "電気通信業務の休止",
    "電気通信業務の廃止",
    "業務の休止及び廃止の周知義務",
    "周知義務",
    # 電波法 系 (enforcement-style only)
    "電波法違反",
    "電波法に違反",
    "不法無線局",
    "不法電波",
    "違法電波",
    "妨害電波",
    "無線局を不法",
    "従事停止",
    "従事停止処分",
    "免許の取消",
    "免許取消し",
    "免許取消",
    "運用停止",
    # 取締り系 (police+kyoku coordinated raids)
    "摘発",
    "取締り",
    "取締",
    # 放送法 系
    "認定放送持株会社の認定",
    "認定放送持株会社の認定取消",
    "基幹放送局の認定取消",
    "コミュニティ放送局の免許取消",
    "コミュニティ放送局の認定取消",
    # 信書便 (enforcement-style only — 取消 / 命令)
    "信書便事業の許可取消",
    "信書便事業の認定取消",
    "信書便事業者に対する業務改善命令",
    # 一般行政処分
    "行政処分",
    "改善命令",
    "停止命令",
    "業務命令",
    "認定の取消",
    "許可取消",
    "登録取消",
    "認可取消",
    "認定取消",
    "厳重注意",
    "文書注意",
]

# Negative filter — these reject the anchor unless a STRONG_POSITIVE also
# matches. Catches announcements, demos, appointments, awards.
EXCLUDE_KEYWORDS = [
    "意見募集",
    "公募",
    "募集中",
    "募集の",
    "募集について",
    "シンポジウム",
    "セミナー",
    "講演",
    "委員の任命",
    "任命",
    "派遣",
    "委嘱",
    "調査結果",
    "アンケート",
    "予備免許",
    "免許状等のデジタル化",
    "免許の付与",
    "免許を付与",
    "免許付与",
    "感謝状",
    "表彰",
    "贈呈",
    "周知啓発",
    "電波利用環境保護",
    "STOP",
    "白書",
    "年次報告",
    "答申",
    "意見公募",
    "意見公募手続",
    "防災訓練",
    "防災フェスタ",
    "総合防災訓練",
    "水防演習",
    "展示",
    "試験運用",
    "災害対策用",
    "情報通信月間",
    "電波の日",
    "記念講演会",
    "テレワーク",
    "コンテスト",
    "認定証",
    "認定状",
    "新規参入",
    "公衆無線LAN環境整備支援事業",
    "事業計画の変更の認可",  # 通常の認可 — 取消ではない
    "提案の公募",
    "予算",
    "決算",
    # 信書便/電気通信 license GRANTS (NOT enforcement)
    "特定信書便事業の許可",
    "信書便事業の許可",
    "信書便約款の変更の認可",
    "信書便事業の認可",
    "電気通信事業の登録",  # 登録 = grant (取消 caught by STRONG_POSITIVE first)
    "電気通信事業の届出",
    "申請者 役務の種類",
    "申請者役務の種類",  # 信書便許可 list table title
    "提供区域 兼業する事業",
    "免許状",
    "免許の交付",
    "免許状の交付",
    "事業開始予定日",
]

# Strong-positive overrides — these guarantee inclusion even if a negative
# keyword is also present in the title.
STRONG_POSITIVE = [
    "業務改善命令",
    "業務停止命令",
    "認定取消",
    "認定の取消",
    "認定取消し",
    "登録取消",
    "登録の取消",
    "登録取消し",
    "許可取消",
    "許可の取消",
    "許可取消し",
    "免許取消",
    "免許の取消",
    "免許取消し",
    "運用停止",
    "電波法違反",
    "電波法に違反",
    "従事停止処分",
    "従事停止",
    "不法無線局",
    "不法電波",
    "違法電波",
    "妨害電波",
    "摘発",
    "行政処分",
    "改善命令",
    "電気通信業務の休止",
    "電気通信業務の廃止",
    "周知義務",
]

# ---------- Date parsing -----------------------------------------------------

WAREKI_RE = re.compile(
    r"(令和|平成)\s*(元|[0-9０-９]+)\s*年\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)
ISO_RE = re.compile(r"(20\d{2})[-/年.]\s*(\d{1,2})[-/月.]\s*(\d{1,2})")
HOUJIN_RE = re.compile(r"\b([0-9]{13})\b")


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = html_module.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _hash8(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def _wareki_to_iso(text: str) -> str | None:
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    m = WAREKI_RE.search(text)
    if not m:
        return None
    era, yr, mo, dy = m.group(1), m.group(2), m.group(3), m.group(4)
    yr_i = 1 if yr == "元" else int(yr)
    if era == "令和":
        year = 2018 + yr_i
    elif era == "平成":
        year = 1988 + yr_i
    else:
        return None
    try:
        return f"{year:04d}-{int(mo):02d}-{int(dy):02d}"
    except ValueError:
        return None


def _iso_from_text(text: str) -> str | None:
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text)
    m = ISO_RE.search(text)
    if m:
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            pass
    return _wareki_to_iso(text)


# ---------- HTTP fetcher -----------------------------------------------------


class Fetcher:
    """Plain HTTP fetcher with rate limiting + retry. soumu.go.jp has no
    Akamai screening — verified 2026-04-25.
    """

    def __init__(self, qps: float = 4.0) -> None:
        self._min_interval = 1.0 / qps if qps > 0 else 0.0
        self._last_t = 0.0

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_t
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def fetch(self, url: str, retries: int = 3, encoding: str = "shift_jis") -> tuple[int, str]:
        for attempt in range(retries):
            self._pace()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
                    raw = resp.read()
                    self._last_t = time.monotonic()
                    # try Shift_JIS first; fall back to utf-8 if obvious garbage
                    try:
                        body = raw.decode(encoding, errors="replace")
                    except Exception:
                        body = raw.decode("utf-8", errors="replace")
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


# ---------- Anchor extraction from index page --------------------------------

ANCHOR_RE = re.compile(
    r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)


_HARD_EXCLUDES = (
    "周知啓発",
    "強化期間",
    "電波利用環境保護",
    "STOP THE",
    "防災訓練",
    "防災フェスタ",
    "総合防災訓練",
    "水防演習",
    "情報通信月間",
    "電波の日",
    "記念講演",
    "セミナー",
    "シンポジウム",
    "募集",
    "意見公募",
    "感謝状",
    "表彰",
    "贈呈",
    "授与",
    "白書",
    "年次報告",
    "答申",
    "免許の付与",
    "免許を付与",
    "コンテスト",
    "テレワーク",
    "公衆無線LAN環境整備支援事業",
    "申請者 役務の種類",
    "申請者役務の種類",
    "提案の公募",
)


def is_enforcement_anchor(anchor_text: str) -> bool:
    """Decide whether an index-page anchor describes an enforcement action."""
    txt = _normalize(anchor_text)
    if not txt or len(txt) < 6:
        return False
    # Hard exclude — never include even if STRONG_POSITIVE matches.
    if any(h in txt for h in _HARD_EXCLUDES):
        return False
    # Strong positive override — always include
    if any(s in txt for s in STRONG_POSITIVE):
        return True
    # Otherwise: must match enforcement keyword AND not an exclude keyword
    if not any(k in txt for k in ENFORCEMENT_KEYWORDS):
        return False
    return not any(e in txt for e in EXCLUDE_KEYWORDS)


def extract_anchors(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return list of (absolute_url, anchor_text) for every anchor on the page."""
    out: list[tuple[str, str]] = []
    for m in ANCHOR_RE.finditer(html):
        href = m.group(1)
        # strip inline tags to get plain text
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        text = _normalize(text)
        if not href or href.startswith("#"):
            continue
        abs_url = urllib.parse.urljoin(base_url, href)
        if "soumu.go.jp" not in abs_url:
            continue
        out.append((abs_url, text))
    return out


# ---------- Per-page parsing -------------------------------------------------


def classify_kind(title: str) -> str:
    """Pick enforcement_kind from press release title."""
    t = title
    # license_revoke
    if any(
        k in t
        for k in [
            "認定取消",
            "認定の取消",
            "登録取消",
            "登録の取消",
            "許可取消",
            "許可の取消",
            "免許取消",
            "免許の取消",
        ]
    ):
        return "license_revoke"
    # contract_suspend
    if any(k in t for k in ["業務停止命令", "業務停止", "運用停止", "従事停止", "停止命令"]):
        return "contract_suspend"
    # business_improvement
    if any(
        k in t for k in ["業務改善命令", "業務改善", "改善命令", "周知義務", "厳重注意", "文書注意"]
    ):
        return "business_improvement"
    # investigation (摘発・取締り — 個人の電波法違反摘発が大半)
    if any(k in t for k in ["摘発", "取締り", "取締", "捜索"]):
        return "investigation"
    # fine
    if any(k in t for k in ["罰金", "課徴金"]):
        return "fine"
    # default for "行政処分" etc.
    if "行政処分" in t:
        return "contract_suspend"  # 大半が従事停止
    if any(k in t for k in ["指導"]):
        return "business_improvement"
    return "other"


def classify_law(title: str, body: str) -> str | None:
    """Pick relevant law citation from title + body."""
    blob = title + " " + body
    laws = []
    if "電波法" in blob:
        # try to extract specific article
        m = re.search(r"電波法第\s*([0-9０-９]+)\s*条", blob)
        if m:
            article = unicodedata.normalize("NFKC", m.group(1))
            laws.append(f"電波法第{article}条")
        else:
            laws.append("電波法")
    if "電気通信事業法" in blob:
        m = re.search(r"電気通信事業法第\s*([0-9０-９]+)\s*条", blob)
        if m:
            article = unicodedata.normalize("NFKC", m.group(1))
            laws.append(f"電気通信事業法第{article}条")
        else:
            laws.append("電気通信事業法")
    if "放送法" in blob:
        m = re.search(r"放送法第\s*([0-9０-９]+)\s*条", blob)
        if m:
            article = unicodedata.normalize("NFKC", m.group(1))
            laws.append(f"放送法第{article}条")
        else:
            laws.append("放送法")
    if "信書便" in blob or "信書の送達" in blob:
        laws.append("信書の送達に関する法律")
    if not laws:
        return None
    return " / ".join(laws)


def extract_target_name(title: str, body: str) -> str:
    """Best-effort extraction of the target entity name from press release.

    Strategies (in order):
      1. 法人名 株式会社/合同会社/有限会社 contained in body or title.
      2. 都道府県 + 在住の○○歳 (個人 — anonymised).
      3. Title minus boilerplate.
    """
    # Strategy 1: corporate name
    m = re.search(
        r"([一-龥ぁ-んァ-ヶーA-Za-z0-9０-９ｱ-ﾝ・\(\)（）\s]{2,40}"
        r"(?:株式会社|有限会社|合同会社|合資会社|合名会社|"
        r"特定非営利活動法人|社団法人|財団法人|協同組合|商工会|"
        r"放送局|FM|エフエム))",
        body,
    )
    if m:
        name = _normalize(m.group(1))
        # trim leading お・ご・「
        name = re.sub(r"^[「『]+", "", name).strip()
        if 2 < len(name) <= 80:
            return name

    # Strategy 2: anonymised individual (電波法違反 typical pattern)
    m2 = re.search(
        r"([一-龥]{2,5}[県府都道][一-龥ぁ-んァ-ヶー]{0,30}在住の?)\s*"
        r"([0-9０-９]+)\s*歳",
        body,
    )
    if m2:
        return _normalize(m2.group(1) + m2.group(2) + "歳")

    # Strategy 3: from title — look for 「○○」
    m3 = re.search(r"[「『]([^」』]+)[」』]", title)
    if m3:
        return _normalize(m3.group(1))[:120]

    # Fallback: title prefix before dash/parens
    base = re.split(r"[−–\-(（]", title)[0]
    return _normalize(base)[:120]


def parse_press_release(
    html: str,
    source_url: str,
    region_key: str,
    region_name: str,
    authority_canonical: str,
    fallback_date: str | None = None,
    anchor_text: str | None = None,
) -> dict[str, Any] | None:
    """Parse a single soumu/soutsu press release into an enforcement record."""
    # title
    t_match = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    title_full = _normalize(t_match.group(1) if t_match else "")
    # strip leading "総務省｜<region>｜" prefix
    title = re.sub(r"^総務省[|｜]\s*[^|｜]+[|｜]\s*", "", title_full)
    if not title:
        title = anchor_text or ""
    if not title:
        return None

    # Filter by enforcement keywords (we may have followed a non-enforcement link)
    if not is_enforcement_anchor(title) and not is_enforcement_anchor(anchor_text or ""):
        return None

    # og:description for body summary
    og = re.search(r'property="og:description"\s+content="([^"]+)"', html)
    og_desc = _normalize(og.group(1)) if og else ""

    # Extract main body text (between common delimiters)
    body_text = ""
    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    if body_match:
        body_html = body_match.group(1)
        # remove scripts/styles
        body_html = re.sub(
            r"<script[^>]*>.*?</script>", " ", body_html, flags=re.DOTALL | re.IGNORECASE
        )
        body_html = re.sub(
            r"<style[^>]*>.*?</style>", " ", body_html, flags=re.DOTALL | re.IGNORECASE
        )
        body_text = re.sub(r"<[^>]+>", " ", body_html)
        body_text = _normalize(body_text)
        # trim to 8KB
        body_text = body_text[:8000]

    # Date — try body first (令和X年Y月Z日), then URL filename, then fallback
    iso_date = _iso_from_text(body_text) or _iso_from_text(title)
    if not iso_date:
        # URL patterns we know:
        #   /press/2025/0529k1.html  (kanto: MMDD)
        #   /press/2024/pre241125_01.html  (hokuriku: YYMMDD)
        #   /press/20240930.html  (shikoku: YYYYMMDD)
        #   /hodo/20260422a1001.html  (tohoku: YYYYMMDD)
        #   /hodo/2026/2026_04_20-001.html  (okinawa: YYYY_MM_DD)
        #   /hodo_2024/01sotsu08_01001847.html  (chugoku: no date — use index year)
        #   /soutsu/kinki/01sotsu07_01002454.html  (kinki: no date in URL)
        #   /sbt/hodo/241021.html  (shinetsu: YYMMDD)
        # try patterns
        for pat, transform in [
            (
                r"/press/(\d{4})/(\d{4})[a-z]+\.html",
                lambda m: f"{m.group(1)}-{m.group(2)[:2]}-{m.group(2)[2:]}",
            ),
            (
                r"/press/(\d{4})/pre(\d{2})(\d{2})(\d{2})_\d+\.html",
                lambda m: f"{m.group(1)}-{m.group(3)}-{m.group(4)}",
            ),
            (
                r"/press/(\d{8})\.html",
                lambda m: f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}",
            ),
            (
                r"/hodo/(\d{8})[a-z]?\d*\.html",
                lambda m: f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:8]}",
            ),
            (
                r"/hodo/(\d{4})/(\d{4})_(\d{2})_(\d{2})-\d+\.html",
                lambda m: f"{m.group(2)}-{m.group(3)}-{m.group(4)}",
            ),
            (
                r"/sbt/hodo/(\d{2})(\d{2})(\d{2})\.html",
                lambda m: f"20{m.group(1)}-{m.group(2)}-{m.group(3)}",
            ),
            (
                r"/(\d{4})/(\d{4})\.html",  # hokkaido /YYYY/MMDD.html
                lambda m: f"{m.group(1)}-{m.group(2)[:2]}-{m.group(2)[2:]}",
            ),
        ]:
            mm = re.search(pat, source_url)
            if mm:
                try:
                    iso_date = transform(mm)
                    break
                except Exception:
                    continue
        if not iso_date:
            iso_date = fallback_date

    if not iso_date:
        return None

    enforcement_kind = classify_kind(title + " " + og_desc)
    related_law_ref = classify_law(title, body_text or og_desc)
    target_name = extract_target_name(title, body_text or og_desc)

    # houjin_bangou — best-effort
    houjin = None
    for cand in HOUJIN_RE.findall(body_text):
        houjin = cand
        break

    issuing_authority = region_name

    reason_summary_parts: list[str] = [title]
    if og_desc:
        reason_summary_parts.append(og_desc[:600])
    reason_summary = " | ".join(reason_summary_parts)[:1900]

    return {
        "region_key": region_key,
        "region_name": region_name,
        "authority_canonical": authority_canonical,
        "issuing_authority": issuing_authority,
        "enforcement_kind": enforcement_kind,
        "issuance_date": iso_date,
        "target_name": target_name,
        "houjin_bangou": houjin,
        "title": title,
        "anchor_text": anchor_text,
        "related_law_ref": related_law_ref,
        "source_url": source_url,
        "reason_summary": reason_summary,
        "amount_yen": None,
        "exclusion_start": None,
        "exclusion_end": None,
    }


# ---------- DB write ---------------------------------------------------------


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
        rec.get("region_key", ""),
        rec.get("issuance_date", ""),
        rec.get("target_name", ""),
        rec.get("source_url", ""),
        rec.get("enforcement_kind", ""),
    ]
    h = _hash8("|".join(payload_parts))
    yyyymmdd = (rec.get("issuance_date") or "").replace("-", "")[:8] or "00000000"
    region = rec.get("region_key") or "main"
    return f"enforcement:soumu-telecom-{region}-{yyyymmdd}-{h}"


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
        "source": "soumu:telecom_enforcement",
        "region_key": rec["region_key"],
        "region_name": rec["region_name"],
        "title": rec.get("title"),
        "anchor_text": rec.get("anchor_text"),
        "target_name": rec["target_name"],
        "houjin_bangou": rec.get("houjin_bangou"),
        "issuance_date": rec["issuance_date"],
        "issuing_authority": rec["issuing_authority"],
        "authority_canonical": rec["authority_canonical"],
        "enforcement_kind": rec["enforcement_kind"],
        "related_law_ref": rec.get("related_law_ref"),
        "reason_summary": rec.get("reason_summary"),
        "amount_yen": rec.get("amount_yen"),
        "exclusion_start": rec.get("exclusion_start"),
        "exclusion_end": rec.get("exclusion_end"),
        "source_url": rec["source_url"],
        "license": "PDL v1.0 (政府標準利用規約 第2.0版 互換)",
        "attribution": (f"出典: {rec['issuing_authority']} 報道資料 ({rec['source_url']})"),
        "fetched_at": now_iso,
    }

    cur.execute(
        """INSERT OR IGNORE INTO am_entities
           (canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence, source_url,
            source_url_domain, fetched_at, raw_json)
           VALUES (?, 'enforcement', ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            f"soumu_telecom_{rec['region_key']}",
            (rec["target_name"] or "")[:255],
            rec["authority_canonical"],
            0.80,
            rec["source_url"],
            "www.soumu.go.jp",
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
            rec.get("exclusion_start"),
            rec.get("exclusion_end"),
            (rec.get("reason_summary") or "")[:2000] or None,
            rec.get("related_law_ref"),
            rec.get("amount_yen"),
            rec["source_url"],
            now_iso,
        ),
    )
    return True


# ---------- Crawl orchestration ----------------------------------------------


def collect_index_urls(
    region_keys: list[str],
    year_lo: int,
    year_hi: int,
) -> list[tuple[str, str, str]]:
    """Return list of (region_key, region_name, index_url) to crawl."""
    out: list[tuple[str, str, str]] = []
    for rk in region_keys:
        if rk == "shinetsu":
            # Heisei 25..30 = 2013..2018
            for h in SHINETSU_HEISEI_RANGE:
                yr = 1988 + h
                if yr < year_lo or yr > year_hi:
                    continue
                out.append((rk, "信越総合通信局", SHINETSU_TMPL_H.format(h)))
            # Reiwa 1..7 = 2019..2025
            for r in SHINETSU_REIWA_RANGE:
                yr = 2018 + r
                if yr < year_lo or yr > year_hi:
                    continue
                out.append((rk, "信越総合通信局", SHINETSU_TMPL_R.format(r)))
            # current (2026)
            if year_lo <= 2026 and year_hi >= 2026:
                out.append((rk, "信越総合通信局", SHINETSU_CURRENT))
            continue

        cfg = REGION_INDEX.get(rk)
        if not cfg:
            continue
        lo, hi = cfg["year_range"]
        for yr in range(max(lo, year_lo), min(hi, year_hi) + 1):
            out.append((rk, cfg["name"], cfg["tmpl"].format(yr)))
        if cfg.get("current") and year_hi >= 2026:
            out.append((rk, cfg["name"], cfg["current"]))
    return out


def crawl_index_page(
    fetcher: Fetcher,
    region_key: str,
    region_name: str,
    index_url: str,
) -> list[tuple[str, str]]:
    """Fetch the index page, return list of (press_url, anchor_text)."""
    status, html = fetcher.fetch(index_url)
    if status != 200 or not html:
        _LOG.debug("[%s] index %s -> %s", region_key, index_url, status)
        return []
    anchors = extract_anchors(html, index_url)
    # filter to enforcement
    out: list[tuple[str, str]] = []
    seen = set()
    for url, txt in anchors:
        if url in seen:
            continue
        if not is_enforcement_anchor(txt):
            continue
        # restrict to same region's path (avoid links to /menu_news/s-news/)
        # but allow soumu main news links if they're enforcement-style
        if (
            f"/soutsu/{region_key}/" in url
            or "/menu_news/s-news/" in url
            or
            # shinetsu uses /sbt/
            (region_key == "shinetsu" and "/shinetsu/" in url)
        ):
            seen.add(url)
            out.append((url, txt))
    return out


def fetch_and_parse_press_releases(
    fetcher: Fetcher,
    indexes: list[tuple[str, str, str]],
    max_releases: int,
) -> list[dict[str, Any]]:
    """Fetch all index pages, harvest enforcement anchors, fetch each press
    release, parse into records.
    """
    candidates: list[tuple[str, str, str, str]] = []  # (region_key, region_name, url, anchor)
    seen_press_urls: set[str] = set()
    for rk, rn, idx_url in indexes:
        anchors = crawl_index_page(fetcher, rk, rn, idx_url)
        _LOG.info("[%s] index %s -> %d enforcement anchors", rk, idx_url[-50:], len(anchors))
        for url, txt in anchors:
            if url in seen_press_urls:
                continue
            seen_press_urls.add(url)
            candidates.append((rk, rn, url, txt))
            if len(candidates) >= max_releases:
                break
        if len(candidates) >= max_releases:
            break
    _LOG.info("collected %d candidate press release URLs", len(candidates))

    out: list[dict[str, Any]] = []
    for i, (rk, rn, url, anchor) in enumerate(candidates, 1):
        cfg = REGION_INDEX.get(rk, {})
        auth_canonical = cfg.get("authority_canonical", "authority:soumu-sogotsushin")
        # try to derive a fallback date from the URL
        fallback_date = None
        for pat, transform in [
            (r"/press/(\d{4})/(\d{4})", lambda m: f"{m.group(1)}-01-01"),
            (r"/press/(\d{4})/", lambda m: f"{m.group(1)}-01-01"),
            (r"/(\d{4})/", lambda m: f"{m.group(1)}-01-01"),
        ]:
            mm = re.search(pat, url)
            if mm:
                try:
                    fallback_date = transform(mm)
                    break
                except Exception:
                    pass

        status, html = fetcher.fetch(url)
        if status != 200 or not html:
            _LOG.debug("[%s] press %s -> %s", rk, url, status)
            continue
        rec = parse_press_release(
            html,
            url,
            rk,
            rn,
            auth_canonical,
            fallback_date=fallback_date,
            anchor_text=anchor,
        )
        if rec:
            out.append(rec)
        if i % 50 == 0:
            _LOG.info(
                "progress: %d/%d press releases parsed (%d records)", i, len(candidates), len(out)
            )
    _LOG.info("parsed %d enforcement records", len(out))
    return out


# ---------- main flow --------------------------------------------------------


def run(
    db_path: Path,
    region_keys: list[str],
    year_lo: int,
    year_hi: int,
    max_releases: int,
    max_rows: int,
    dry_run: bool,
    verbose: bool,
    staging_json: Path | None,
    collect_only: bool,
    write_only: bool,
) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    now_iso = datetime.now(tz=UTC).isoformat(timespec="seconds")

    # --- collect / load records ---
    if write_only:
        if not staging_json or not staging_json.exists():
            _LOG.error("--write-only requires --staging-json existing file")
            return 0
        with staging_json.open() as f:
            payload = json.load(f)
        all_records = payload["records"]
        _LOG.info("loaded %d records from %s", len(all_records), staging_json)
    else:
        fetcher = Fetcher(qps=4.0)
        indexes = collect_index_urls(region_keys, year_lo, year_hi)
        _LOG.info(
            "regions=%s years=%d..%d → %d index URLs", region_keys, year_lo, year_hi, len(indexes)
        )
        all_records = fetch_and_parse_press_releases(fetcher, indexes, max_releases)
        if staging_json:
            staging_json.parent.mkdir(parents=True, exist_ok=True)
            with staging_json.open("w") as f:
                json.dump({"collected_at": now_iso, "records": all_records}, f, ensure_ascii=False)
            _LOG.info("staged %d records to %s", len(all_records), staging_json)
        if collect_only:
            return len(all_records)

    if not all_records:
        _LOG.error("no records — aborting")
        return 0

    if dry_run:
        by_kind: dict[str, int] = {}
        by_region: dict[str, int] = {}
        by_law: dict[str, int] = {}
        for r in all_records:
            by_kind[r["enforcement_kind"]] = by_kind.get(r["enforcement_kind"], 0) + 1
            by_region[r["region_key"]] = by_region.get(r["region_key"], 0) + 1
            law = r.get("related_law_ref") or "(none)"
            # group by primary law
            primary = law.split("/")[0].strip()
            primary = primary.split("第")[0].strip() or primary
            by_law[primary] = by_law.get(primary, 0) + 1
        _LOG.info("== dry-run summary ==")
        _LOG.info("  total: %d", len(all_records))
        for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]):
            _LOG.info("  kind %s: %d", k, v)
        for k, v in sorted(by_region.items(), key=lambda kv: -kv[1]):
            _LOG.info("  region %s: %d", k, v)
        for k, v in sorted(by_law.items(), key=lambda kv: -kv[1]):
            _LOG.info("  law %s: %d", k, v)
        for r in all_records[:8]:
            _LOG.info(
                "  sample: %s %s | %s | %s | %s",
                r["region_key"],
                r["issuance_date"],
                r["target_name"][:30],
                r["enforcement_kind"],
                r.get("related_law_ref") or "",
            )
        return 0

    # --- write to DB with batched BEGIN IMMEDIATE ---
    inserted = 0
    skipped_dup = 0
    skipped_constraint = 0
    by_kind: dict[str, int] = {}
    by_region: dict[str, int] = {}
    by_law: dict[str, int] = {}

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
        for rec in all_records:
            if inserted >= max_rows:
                break
            key = (
                (rec.get("issuance_date") or "")[:10],
                _normalize(rec.get("target_name") or ""),
                _normalize(rec["issuing_authority"]),
            )
            if key in existing_dedup:
                skipped_dup += 1
                continue
            existing_dedup.add(key)
            batch.append(rec)
            if len(batch) >= BATCH:
                inserted = _flush_batch(
                    con,
                    batch,
                    now_iso,
                    seen_canonical,
                    by_kind,
                    by_region,
                    by_law,
                    inserted,
                    _begin_immediate,
                )
                batch.clear()
                _LOG.info("batch commit: inserted=%d", inserted)
        if batch:
            inserted = _flush_batch(
                con,
                batch,
                now_iso,
                seen_canonical,
                by_kind,
                by_region,
                by_law,
                inserted,
                _begin_immediate,
            )
            _LOG.info("final batch commit: inserted=%d", inserted)

        _LOG.info(
            "INSERT done inserted=%d skipped_dup=%d total_seen=%d",
            inserted,
            skipped_dup,
            len(all_records),
        )
        _LOG.info("== breakdown by enforcement_kind ==")
        for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]):
            _LOG.info("  %s: %d", k, v)
        _LOG.info("== breakdown by region ==")
        for k, v in sorted(by_region.items(), key=lambda kv: -kv[1]):
            _LOG.info("  %s: %d", k, v)
        _LOG.info("== breakdown by 法 ==")
        for k, v in sorted(by_law.items(), key=lambda kv: -kv[1]):
            _LOG.info("  %s: %d", k, v)
    except Exception:
        with contextlib.suppress(Exception):
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return inserted


def _flush_batch(
    con: sqlite3.Connection,
    batch: list[dict[str, Any]],
    now_iso: str,
    seen_canonical: set[str],
    by_kind: dict[str, int],
    by_region: dict[str, int],
    by_law: dict[str, int],
    inserted: int,
    _begin_immediate,
) -> int:
    _begin_immediate(con)
    cur = con.cursor()
    for rec in batch:
        try:
            ok = upsert_record(cur, rec, now_iso, seen_canonical)
        except sqlite3.IntegrityError as exc:
            _LOG.warning("integrity %s: %s", rec.get("target_name"), exc)
            continue
        if ok:
            inserted += 1
            by_kind[rec["enforcement_kind"]] = by_kind.get(rec["enforcement_kind"], 0) + 1
            by_region[rec["region_key"]] = by_region.get(rec["region_key"], 0) + 1
            law = rec.get("related_law_ref") or "(none)"
            primary = law.split("/")[0].split("第")[0].strip() or law
            by_law[primary] = by_law.get(primary, 0) + 1
    cur.close()
    con.execute("COMMIT")
    return inserted


def _parse_year_range(spec: str) -> tuple[int, int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return int(a), int(b)
    y = int(spec)
    return y, y


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--regions",
        type=str,
        default="kanto,kinki,tokai,chugoku,shikoku,kyushu,tohoku,hokkaido,hokuriku,okinawa,shinetsu",
        help="comma-separated region keys",
    )
    ap.add_argument(
        "--years",
        type=str,
        default="2013-2026",
        help="year range, e.g. 2020-2026 or 2024",
    )
    ap.add_argument(
        "--max-releases",
        type=int,
        default=2000,
        help="cap on press release fetches",
    )
    ap.add_argument(
        "--max-rows",
        type=int,
        default=10000,
        help="cap on rows inserted in this run",
    )
    ap.add_argument("--staging-json", type=Path, default=None)
    ap.add_argument("--collect-only", action="store_true")
    ap.add_argument("--write-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    region_keys = [r.strip() for r in args.regions.split(",") if r.strip()]
    year_lo, year_hi = _parse_year_range(args.years)
    inserted = run(
        args.db,
        region_keys,
        year_lo,
        year_hi,
        args.max_releases,
        args.max_rows,
        args.dry_run,
        args.verbose,
        args.staging_json,
        args.collect_only,
        args.write_only,
    )
    return 0 if (args.dry_run or args.collect_only or inserted >= 1) else 1


if __name__ == "__main__":
    sys.exit(main())
