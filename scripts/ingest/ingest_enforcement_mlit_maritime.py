#!/usr/bin/env python3
"""Ingest 国土交通省 海事局 + 各地方運輸局 海事振興部 / 海上安全環境部
の海事関係行政処分 (船員法 / 船舶安全法 / 海上運送法 / 内航海運業法 /
港湾運送事業法 / 海事代理士法) records into ``am_enforcement_detail``.

This complements ``ingest_enforcement_mlit_unyu.py`` (which targets
自動車運送事業 = バス / タクシー / トラック on 運輸局 page3) by walking
the parallel maritime hubs published by the 海事振興部 / 海上安全環境部
and the central 海事局.

Hubs walked:

  Central 海事局 (UTF-8):
    https://www.mlit.go.jp/maritime/maritime_fr4_000012.html
        — 船員法等関係法令違反船舶所有者 quarterly disclosure
          (links to /maritime/content/*.pdf and to per-quarter
           /report/press/kaiji06_hh_*.html press release pages)

  関東運輸局 (Shift_JIS):
    https://wwwtb.mlit.go.jp/kanto/page3/ryokakusen/index_1.html
    https://wwwtb.mlit.go.jp/kanto/page3/kamotusen/index.html
    https://wwwtb.mlit.go.jp/kanto/page3/kouun/index.html
    https://wwwtb.mlit.go.jp/kanto/page3/senin/index.html

  北海道運輸局 (Shift_JIS):
    https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/ryokakusen/index.html
    https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/kaiji/index.html

  東北運輸局 (Shift_JIS):
    https://wwwtb.mlit.go.jp/tohoku/gyouseisyobun.html  (links 海事 nega-inf)

  中国運輸局 (Shift_JIS):
    https://wwwtb.mlit.go.jp/chugoku/kaian/shobun.html       (旅客船)
    https://wwwtb.mlit.go.jp/chugoku/kaian/shobun02.html     (内航海運)
    https://wwwtb.mlit.go.jp/chugoku/kaian/shobun03.html     (港湾運送)
    https://wwwtb.mlit.go.jp/chugoku/kaian/shipownershobun.html (船員法違反船舶所有者)

  四国運輸局 (Shift_JIS):
    https://wwwtb.mlit.go.jp/shikoku/soshiki/kaijyou/syobun.html

  九州運輸局 (Shift_JIS):
    https://wwwtb.mlit.go.jp/kyushu/kaijiseikyu/body.htm
    (sparse — most maritime PDFs are linked from the central 海事局
     quarterly press releases for 九州 region.)

  沖縄総合事務局 (UTF-8):
    https://www.ogb.go.jp/unyu/gyousei/naiko-kaiun-jigyo
    https://www.ogb.go.jp/unyu/gyousei/kowanunso

PDF layouts encountered:

  (A) Kanto / Shikoku narrative single-record format::

        （１）行政処分等の年月日   令和８年４月２４日
        （２）事業者の氏名又は名称  株式会社XXX
        （３）処分等の種類          輸送の安全の確保に関する命令
        （４）原因となった事故等の概要
        （５）処分等の内容
            <prose>
        （６）違反点数付与状況
            <points>

  (B) Chugoku / Hokkaido / Shikoku-newer / 海事局-senin tabular format::

        処分等年月日 | 事業者名 | 事業者所在地 | 処分等の種類 |
        違反等の概要 | 命令又は指導の内容 | 違反点数

      pdfminer flattens this into header words followed by per-row
      blocks separated by row dates.

  (C) 海事局 quarterly senin format (船員法等関係法令違反船舶所有者)::

        公表年月日 | 船名 | 船種 | 船舶所有者名(法人番号) | 所在地 |
        処分を行った日 | 違反理由 | 行政処分内容(条項等) | 所管局

Schema mapping:

    enforcement_kind CHECK ∈ {subsidy_exclude, grant_refund,
        contract_suspend, business_improvement, license_revoke,
        fine, investigation, other}

    Maritime mapping:
      許可取消 / 登録取消 / 事業許可の取消         → license_revoke
      事業停止 / 業務停止 / 船舶等の使用停止       → business_improvement
      輸送の安全(の)確保に関する命令               → business_improvement
      サービス改善命令                              → business_improvement
      警告 / 戒告 / 文書警告 / 文書指導 / 行政指導 → other

    related_law_ref:
      旅客船 / 貨物船 / 内航海運 hubs            → 海上運送法 / 内航海運業法
      港湾運送 hub                                 → 港湾運送事業法
      船員法等関係法令違反 / senin hubs           → 船員法
      海事代理士違反 (when present)               → 海事代理士法
      Article tail captured via 第..条(?項)?(?号)?

    issuing_authority comes from the hub label
    (国土交通省 海事局 / 関東運輸局 海事振興部 / etc.)

    canonical_id: AM-ENF-MLIT-MARITIME-<region>-<seq>
                  region ∈ {hq,kanto,hokkaido,tohoku,chubu,kinki,
                            kyushu,chugoku,shikoku,hokushin,okinawa}

Idempotency: dedup on (issuing_authority, issuance_date, target_name,
enforcement_kind) via existing row scan + canonical_id INSERT OR IGNORE.

Per-write transaction: BEGIN IMMEDIATE + busy_timeout=300000 + 50-row
periodic commit so the parallel ingest writers can interleave.

CLI:
    python scripts/ingest/ingest_enforcement_mlit_maritime.py \
        --db autonomath.db [--regions kanto,chugoku,...] \
        [--limit 300] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import logging
import re
import sqlite3
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

try:
    import httpx
except ImportError as e:  # pragma: no cover
    sys.exit(f"httpx required: {e}")

try:
    from pdfminer.high_level import extract_text  # type: ignore
except ImportError as e:  # pragma: no cover
    sys.exit(f"pdfminer.six required: {e}")


_LOG = logging.getLogger("autonomath.ingest.enforcement_mlit_maritime")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = "jpintel-mcp-ingest/1.0 (+https://jpcite.com; contact=ops@jpcite.com)"
PER_REQUEST_DELAY_SEC = 0.6
HTTP_TIMEOUT_SEC = 60.0
MAX_RETRIES = 3


# Hub configuration. Each hub knows its encoding, its issuing authority
# label, the dominant law, and an optional "drill" flag for index pages
# that link to per-quarter / per-year press release subpages.
@dataclass(frozen=True)
class Hub:
    region_code: str
    region_label: str  # for issuing_authority
    encoding: str
    url: str
    primary_law: str  # default related_law_ref
    drill_press: bool = False  # for 海事局 quarterly press releases


HUBS: list[Hub] = [
    # --- 海事局 central ---
    Hub(
        "hq",
        "国土交通省 海事局",
        "utf-8",
        "https://www.mlit.go.jp/maritime/maritime_fr4_000012.html",
        "船員法",
        drill_press=True,
    ),
    # --- 関東運輸局 ---
    Hub(
        "kanto",
        "関東運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/kanto/page3/ryokakusen/index_1.html",
        "海上運送法",
    ),
    Hub(
        "kanto",
        "関東運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/kanto/page3/kamotusen/index.html",
        "内航海運業法",
    ),
    Hub(
        "kanto",
        "関東運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/kanto/page3/kouun/index.html",
        "港湾運送事業法",
    ),
    Hub(
        "kanto",
        "関東運輸局 運航労務監理官",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/kanto/page3/senin/index.html",
        "船員法",
    ),
    # --- 北海道運輸局 ---
    Hub(
        "hokkaido",
        "北海道運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/ryokakusen/index.html",
        "海上運送法",
    ),
    Hub(
        "hokkaido",
        "北海道運輸局 運航労務監理官",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/kaiji/index.html",
        "船員法",
    ),
    # --- 中国運輸局 ---
    Hub(
        "chugoku",
        "中国運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/chugoku/kaian/shobun.html",
        "海上運送法",
    ),
    Hub(
        "chugoku",
        "中国運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/chugoku/kaian/shobun02.html",
        "内航海運業法",
    ),
    Hub(
        "chugoku",
        "中国運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/chugoku/kaian/shobun03.html",
        "港湾運送事業法",
    ),
    Hub(
        "chugoku",
        "中国運輸局 運航労務監理官",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/chugoku/kaian/shipownershobun.html",
        "船員法",
    ),
    # --- 四国運輸局 ---
    Hub(
        "shikoku",
        "四国運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/shikoku/soshiki/kaijyou/syobun.html",
        "海上運送法",
    ),
    # --- 九州運輸局 ---
    Hub(
        "kyushu",
        "九州運輸局 海事振興部",
        "shift_jis",
        "https://wwwtb.mlit.go.jp/kyushu/kaijiseikyu/body.htm",
        "海上運送法",
    ),
    # --- 沖縄総合事務局 ---
    Hub(
        "okinawa",
        "沖縄総合事務局運輸部",
        "utf-8",
        "https://www.ogb.go.jp/unyu/gyousei/naiko-kaiun-jigyo",
        "内航海運業法",
    ),
    Hub(
        "okinawa",
        "沖縄総合事務局運輸部",
        "utf-8",
        "https://www.ogb.go.jp/unyu/gyousei/kowanunso",
        "港湾運送事業法",
    ),
]


# ---------------------------------------------------------------------------
# Punishment / law mapping
# ---------------------------------------------------------------------------

# Order matters — most specific first.
PUNISH_PATTERNS: list[tuple[str, str]] = [
    ("事業許可の取消", "license_revoke"),
    ("事業の許可の取消", "license_revoke"),
    ("事業許可取消", "license_revoke"),
    ("事業登録の取消", "license_revoke"),
    ("登録の取消", "license_revoke"),
    ("許可の取消", "license_revoke"),
    ("許可取消", "license_revoke"),
    ("登録取消", "license_revoke"),
    ("船舶等の使用停止", "business_improvement"),
    ("輸送施設の使用停止", "business_improvement"),
    ("事業停止命令", "business_improvement"),
    ("事業停止", "business_improvement"),
    ("業務停止", "business_improvement"),
    ("輸送の安全の確保に関する命令", "business_improvement"),
    ("輸送の安全確保に関する命令", "business_improvement"),
    ("サービス改善命令", "business_improvement"),
    ("文書警告", "other"),
    ("文書指導", "other"),
    ("行政指導", "other"),
    ("戒告", "other"),
    ("警告", "other"),
    ("勧告", "other"),
    ("命令書", "business_improvement"),
]

LAW_KEYWORDS_TO_NAME: list[tuple[str, str]] = [
    ("船員災害防止活動の促進に関する法律", "船員災害防止活動の促進に関する法律"),
    ("賃金の支払の確保等に関する法律", "賃金の支払の確保等に関する法律"),
    ("最低賃金法", "最低賃金法"),
    ("船舶安全法", "船舶安全法"),
    ("海上運送法", "海上運送法"),
    ("内航海運業法", "内航海運業法"),
    ("港湾運送事業法", "港湾運送事業法"),
    ("海事代理士法", "海事代理士法"),
    ("船員法", "船員法"),
    ("労働基準法", "労働基準法"),
]

# 13-digit 法人番号 with optional whitespace / FW digits / line breaks.
HOUJIN_DIGIT_RE = re.compile(r"法\s*人\s*番\s*号\s*[（(：:]?\s*([\d０-９\s　\n]{13,40})\s*[）)]?")


def _normalize_houjin_block(block: str) -> str | None:
    out: list[str] = []
    for ch in block:
        if ch.isdigit():
            out.append(ch)
        elif "０" <= ch <= "９":
            out.append(chr(ord("0") + (ord(ch) - 0xFF10)))
    digits = "".join(out)
    return digits[:13] if len(digits) >= 13 else None


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

DATE_REIWA_KANJI_RE = re.compile(
    r"令和\s*([０-９\d]+)\s*年\s*([０-９\d]+)\s*月\s*([０-９\d]+)\s*日"
)
DATE_HEISEI_KANJI_RE = re.compile(
    r"平成\s*([０-９\d]+)\s*年\s*([０-９\d]+)\s*月\s*([０-９\d]+)\s*日"
)
DATE_PLAIN_KANJI_RE = re.compile(r"(20\d\d)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def _to_halfwidth_int(s: str) -> int:
    out: list[str] = []
    for ch in s:
        if "０" <= ch <= "９":
            out.append(chr(ord("0") + (ord(ch) - 0xFF10)))
        elif ch.isdigit():
            out.append(ch)
    return int("".join(out)) if out else 0


def parse_any_date_iso(token: str) -> str | None:
    token = token.strip()
    m = DATE_REIWA_KANJI_RE.search(token)
    if m:
        try:
            y = 2018 + _to_halfwidth_int(m.group(1))
            return dt.date(
                y, _to_halfwidth_int(m.group(2)), _to_halfwidth_int(m.group(3))
            ).isoformat()
        except ValueError:
            return None
    m = DATE_HEISEI_KANJI_RE.search(token)
    if m:
        try:
            y = 1988 + _to_halfwidth_int(m.group(1))
            return dt.date(
                y, _to_halfwidth_int(m.group(2)), _to_halfwidth_int(m.group(3))
            ).isoformat()
        except ValueError:
            return None
    m = DATE_PLAIN_KANJI_RE.search(token)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    return None


# Match the start of every record-row date in the body. We scan for any
# of the three formats anywhere in the text and use sequence to bound
# row blocks.
ANY_DATE_RE = re.compile(
    r"(令和\s*[０-９\d]+\s*年\s*[０-９\d]+\s*月\s*[０-９\d]+\s*日|"
    r"平成\s*[０-９\d]+\s*年\s*[０-９\d]+\s*月\s*[０-９\d]+\s*日|"
    r"20\d\d\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)"
)


def map_punishment(text: str) -> tuple[str | None, str | None]:
    for kw, kind in PUNISH_PATTERNS:
        if kw in text:
            idx = text.find(kw)
            tail = text[idx : idx + 80]
            for stop in ("\n", "○", "■", "・", "事業者", "船員"):
                pos = tail.find(stop, len(kw))
                if pos > 0:
                    tail = tail[:pos]
            return tail.strip(), kind
    return None, None


def extract_law_ref(text: str, default_law: str | None = None) -> str | None:
    found_law: str | None = None
    found_at = -1
    for kw, name in LAW_KEYWORDS_TO_NAME:
        idx = text.find(kw)
        if idx >= 0 and (found_at == -1 or idx < found_at):
            found_law = name
            found_at = idx
    if found_law is None:
        found_law = default_law
        found_at = -1
    if found_law is None:
        return None
    if found_at >= 0:
        after = text[found_at + len(found_law) : found_at + len(found_law) + 60]
        m = re.match(
            r"\s*第\s*[\d０-９]+\s*条"
            r"(?:\s*第\s*[\d０-９]+\s*項)?"
            r"(?:\s*第\s*[\d０-９]+\s*号)?",
            after,
        )
        if m:
            return f"{found_law} {m.group(0).strip()}"
    return found_law


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class MaritimeRecord:
    region: str
    issuing_authority: str
    issuance_date: str
    target_name: str
    houjin_bangou: str | None
    address: str | None
    punishment_raw: str
    enforcement_kind: str
    related_law_ref: str | None
    reason_summary: str | None
    source_url: str
    source_hub_url: str


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class MaritimeHttpClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.5",
            },
            timeout=HTTP_TIMEOUT_SEC,
            follow_redirects=True,
        )
        self._last: float = 0.0

    def _pace(self) -> None:
        now = time.monotonic()
        wait = PER_REQUEST_DELAY_SEC - (now - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get_text(self, url: str, encoding: str = "utf-8") -> tuple[int, str]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.get(url)
                if r.status_code == 200:
                    raw = r.content
                    for enc in (encoding, "shift_jis", "utf-8", "cp932"):
                        try:
                            return r.status_code, raw.decode(enc, errors="strict")
                        except UnicodeDecodeError:
                            continue
                    return r.status_code, raw.decode("shift_jis", errors="replace")
                return r.status_code, ""
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    break
                time.sleep(2**attempt)
        _LOG.warning("GET text failed url=%s err=%s", url, last_exc)
        return 0, ""

    def get_bytes(self, url: str) -> tuple[int, bytes]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.get(url)
                return r.status_code, r.content
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    break
                time.sleep(2**attempt)
        _LOG.warning("GET bytes failed url=%s err=%s", url, last_exc)
        return 0, b""

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Hub crawl
# ---------------------------------------------------------------------------

PDF_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+\.pdf)["\']', re.IGNORECASE)
ANY_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
PRESS_HREF_RE = re.compile(
    r'href\s*=\s*["\']([^"\']*kaiji0\d+_hh_\d+\.html?)["\']',
    re.IGNORECASE,
)


def absolute_url(base: str, ref: str) -> str:
    return urllib.parse.urljoin(base, ref.strip())


def collect_pdfs_for_hub(
    http: MaritimeHttpClient,
    hub: Hub,
) -> list[tuple[str, str]]:
    """Return list of (pdf_url, source_hub_url). For ``drill_press``
    hubs we also fetch each kaiji0X_hh_*.html press release page and
    harvest its attached PDFs."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    status, html = http.get_text(hub.url, hub.encoding)
    if status != 200 or not html:
        _LOG.warning("hub fetch failed url=%s status=%s", hub.url, status)
        return out

    for href in PDF_HREF_RE.findall(html):
        absu = absolute_url(hub.url, href)
        if absu in seen:
            continue
        seen.add(absu)
        out.append((absu, hub.url))

    if hub.drill_press:
        # MLIT central senin hub also provides links to per-quarter
        # press release subpages that wrap additional 別紙 PDFs.
        for href in PRESS_HREF_RE.findall(html):
            sub = absolute_url(hub.url, href)
            sstatus, shtml = http.get_text(sub, "utf-8")
            if sstatus != 200 or not shtml:
                continue
            for href2 in PDF_HREF_RE.findall(shtml):
                absu = absolute_url(sub, href2)
                if absu in seen:
                    continue
                seen.add(absu)
                out.append((absu, sub))

    return out


# ---------------------------------------------------------------------------
# PDF parsing — narrative single-record (Kanto-style)
# ---------------------------------------------------------------------------

NARRATIVE_NAME_RE = re.compile(
    r"（\s*[2２]\s*）\s*事業者の(?:氏名又は名称|氏名|名称)(?:及び所在地)?\s*\n+"
    r"\s*([^\n（）]{1,80})"
)
# Date marker for narrative format (1) header
NARRATIVE_DATE_RE = re.compile(
    r"（\s*[1１]\s*）\s*行政処分等の年月日\s*\n+\s*"
    r"(令和\s*[０-９\d]+\s*年\s*[０-９\d]+\s*月\s*[０-９\d]+\s*日|"
    r"平成\s*[０-９\d]+\s*年\s*[０-９\d]+\s*月\s*[０-９\d]+\s*日)"
)
# Punishment kind for narrative format (3)
NARRATIVE_PUNISH_RE = re.compile(r"（\s*[3３]\s*）\s*処分等の種類\s*\n+\s*([^\n（）]{2,60})")


def parse_narrative_pdf(
    text: str,
    *,
    hub: Hub,
    pdf_url: str,
) -> list[MaritimeRecord]:
    """Parse the Kanto-style narrative single-record format.

    A single PDF may concatenate multiple records (each preceded by a
    header date and a fresh （１） block). We split on the leading
    header date pattern at line-start.
    """
    records: list[MaritimeRecord] = []
    # Split into segments at each occurrence of "（１）行政処分等の年月日".
    # Anchor on that explicit header to avoid fluke matches in prose.
    splits = list(re.finditer(r"（\s*[1１]\s*）\s*行政処分等の年月日", text))
    if not splits:
        return records
    for i, m in enumerate(splits):
        seg_start = m.start()
        seg_end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
        seg = text[seg_start:seg_end]

        dm = NARRATIVE_DATE_RE.search(seg)
        if not dm:
            continue
        date_iso = parse_any_date_iso(dm.group(1))
        if not date_iso:
            continue
        try:
            year = int(date_iso[:4])
            if year < 2018 or year > 2027:
                continue
        except ValueError:
            continue

        nm = NARRATIVE_NAME_RE.search(seg)
        target_name: str | None = None
        if nm:
            target_name = re.sub(r"\s+", "", nm.group(1)).strip()
            target_name = target_name.strip("（()【】 　,、")
        if not target_name or len(target_name) < 2 or len(target_name) > 100:
            continue
        if any(
            noise in target_name
            for noise in (
                "氏名又は名称",
                "事業者",
                "原因となった",
                "違反点数",
                "処分等の種類",
            )
        ):
            continue

        pm = NARRATIVE_PUNISH_RE.search(seg)
        if pm:
            punish_text = re.sub(r"\s+", "", pm.group(1))
            kind = None
            for kw, k in PUNISH_PATTERNS:
                if kw in punish_text:
                    kind = k
                    break
            if not kind:
                # fallback: scan whole seg
                _, kind = map_punishment(seg)
            punish_raw = punish_text[:60]
        else:
            punish_raw, kind = map_punishment(seg)
        if not punish_raw or not kind:
            continue

        # 法人番号
        houjin = None
        hm = HOUJIN_DIGIT_RE.search(seg)
        if hm:
            houjin = _normalize_houjin_block(hm.group(1))

        # Reason summary: 処分等の内容 (5) prose block, up to 600 chars
        summary: str | None = None
        sm = re.search(r"（\s*[5５]\s*）\s*処分等の内容", seg)
        if sm:
            tail = seg[sm.end() : sm.end() + 800]
            tail = re.sub(r"\s+", " ", tail).strip()
            summary = tail[:600]

        related_law = extract_law_ref(seg, default_law=hub.primary_law)
        if related_law:
            related_law = re.sub(r"\s+", " ", related_law).strip()

        records.append(
            MaritimeRecord(
                region=hub.region_code,
                issuing_authority=hub.region_label,
                issuance_date=date_iso,
                target_name=target_name,
                houjin_bangou=houjin,
                address=None,
                punishment_raw=punish_raw,
                enforcement_kind=kind,
                related_law_ref=related_law,
                reason_summary=summary,
                source_url=pdf_url,
                source_hub_url="",  # filled by caller
            )
        )
    return records


# ---------------------------------------------------------------------------
# PDF parsing — tabular (Chugoku / Hokkaido / Shikoku-newer / 海事局-senin)
# ---------------------------------------------------------------------------

# Column-header tokens that mark a tabular layout. Presence of >=3 of
# these in the first 800 chars triggers the tabular parser.
TABULAR_HEADER_TOKENS = (
    "処分等年月日",
    "処分年月日",
    "事業者名",
    "事業者住所",
    "本社所在地",
    "処分等の種類",
    "処分等の内容",
    "違反等の概要",
    "命令又は指導の内容",
    "違反点数",
    "公表年月日",
    "船舶所有者名",
    "船種",
    "業種",
    "船名",
    "処分を行った日",
    "行政処分内容",
    "備考",
    "所管局",
)


def looks_tabular(text: str) -> bool:
    head = text[:1500]
    return sum(1 for t in TABULAR_HEADER_TOKENS if t in head) >= 3


# Strip column-header / page-header tokens that pdfminer leaves inline
# in tabular extractions. Run before regex matching.
TABLE_NOISE_TOKENS = (
    "令和４年度 海上運送法に基づく行政処分等一覧",
    "令和５年度 海上運送法に基づく行政処分等一覧",
    "令和６年度 海上運送法に基づく行政処分等一覧",
    "令和７年度 海上運送法に基づく行政処分等一覧",
    "海上運送法に基づく行政処分等",
    "番号 処分等年月日 事業者名 事業者住所 処分等の種類 違反等の概要 命令又は指導の内容 是正状況",
    "番号 処分等年月日 事業者名 事業者住所 処分等の種類",
    "公表年月日 船 名 船 種 又は 業 種 船舶所有者名",
    "公表年月日 船 名 船 種 業 種",
    "船舶所有者名 (法人にあっては 代表者名） 法人番号",
    "船舶所有者名 (法人にあっては代表者名）",
    "船舶所有者名",
    "（別紙） 船 名 船 種 又は 業 種 船舶所有者名",
    "○ 海上運送法に基づく行政処分等",
    "（旅客船事業者）",
    "本社所在地",
    "違反等の概要",
    "命令又は指導の内容",
    "是正状況",
    "処分等の種類",
    "違反点数",
    "備考",
)


def _strip_table_noise(text: str) -> str:
    out = text
    for tok in TABLE_NOISE_TOKENS:
        out = out.replace(tok, " ")
    return out


# Hokkaido-yearly-summary 行頭 row-number marker. Lines are like::
#
#     1\n
#     令和4年6月3日\n
#     （法人番号：\n
#     有限会社フォックス\n
#     2460302001210）\n
#     北海道斜里郡斜里町ウ\n
#     トロ東９６番地５\n
#     文書指導\n
#
# The row-number lines uniquely separate records (1..2..3..N).
HOKKAIDO_ROW_RE = re.compile(
    r"^(\d{1,3})\s*\n+\s*(令和\d+年\d+月\d+日|平成\d+年\d+月\d+日|20\d\d年\d{1,2}月\d{1,2}日)",
    re.MULTILINE,
)


_ADDRESS_PREFIXES = (
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
)
_LEGAL_FORMS = (
    "株式会社",
    "有限会社",
    "合同会社",
    "合資会社",
    "合名会社",
    "協同組合",
    "事業協同組合",
    "一般社団法人",
    "公益社団法人",
    "一般財団法人",
    "公益財団法人",
    "特定非営利活動法人",
    "ＮＰＯ法人",
    "学校法人",
    "医療法人",
    "社会福祉法人",
    "宗教法人",
)


def _is_address_line(line: str) -> bool:
    if not line:
        return False
    if line.startswith(_ADDRESS_PREFIXES):
        return True
    # Continuation address lines: digits/banchi/丁目/番地/号 only
    return bool(re.fullmatch(r"[\d０-９〇一二三四五六七八九十丁目番地号 　\-－]+", line))


def _is_punishment_line(line: str) -> bool:
    return bool(line) and any(
        p in line
        for p in (
            "文書指導",
            "口頭指導",
            "警告",
            "戒告",
            "事業停止",
            "業務停止",
            "事業の停止",
            "業務の停止",
            "許可取消",
            "許可の取消",
            "登録取消",
            "登録の取消",
            "命令",
            "勧告",
        )
    )


def _is_metadata_line(line: str) -> bool:
    return any(
        kw in line
        for kw in (
            "番号",
            "処分等年月日",
            "事業者名",
            "事業者住所",
            "処分等の種類",
            "違反等の概要",
            "命令又は指導の内容",
            "是正状況",
            "氏名又は名称",
            "本社所在地",
            "海上運送法に基づく行政処分等一覧",
            "公表年月日",
            "備考",
            "別紙",
            "船 名",
            "業 種",
            "船 種",
            "船種",
            "船名",
        )
    )


def parse_hokkaido_yearly(
    text: str,
    *,
    hub: Hub,
    pdf_url: str,
) -> list[MaritimeRecord]:
    """Hokkaido yearly summary parser.

    Layout per row (column order in text after pdfminer extraction):
      <row_num>
      <date>
      [<name_part_a>?]   ← may also wrap from the previous block's tail
      （法人番号：
      <name_part_b>      ← when 法人番号 opener is on its own line
      <13_digits>）       ← OR ``<name>（法人番号：<digits>）`` on same line
      <address_line_1>
      [<address_line_2>?]
      <punish_word>
      <violation_summary…>

    Strategy:
      - Block = [row_marker .. next_row_marker)
      - Try to find ``（法人番号：[\\s]*<digits>[\\s]*）`` (corp case)
        - name = stuff between row marker end and 法人番号 opener,
          minus headers, minus addresses; ALSO peek 60 chars before
          row marker to catch wrap-from-previous-block.
        - if name is empty (because 法人番号 sits right after date),
          take the line(s) AFTER opener, before digits.
      - Fallback (個人): name = line right after date, sans punish/address.
    """
    out: list[MaritimeRecord] = []
    text2 = text  # do NOT strip table noise here — line structure matters
    markers = list(HOKKAIDO_ROW_RE.finditer(text2))
    if not markers:
        return out

    for i, m in enumerate(markers):
        try:
            row_num = int(m.group(1))
        except ValueError:
            continue
        if row_num < 1 or row_num > 200:
            continue
        date_iso = parse_any_date_iso(m.group(2))
        if not date_iso:
            continue
        try:
            year = int(date_iso[:4])
            if year < 2018 or year > 2027:
                continue
        except ValueError:
            continue

        block_start = m.start()
        block_end = (
            markers[i + 1].start() if i + 1 < len(markers) else min(len(text2), block_start + 2500)
        )
        block = text2[block_start:block_end]
        # Look-behind window for name wrap from previous block.
        # We accept up to 1 short line (≤ 14 chars) immediately before
        # the row marker IF it does not look like punishment / address /
        # metadata, and IF it does not contain digits / 是正 / 監査.
        wrap_prefix = ""
        prev_end = markers[i - 1].end() if i > 0 else max(0, block_start - 200)
        prev_chunk = text2[prev_end:block_start]
        prev_lines = [ln.strip() for ln in prev_chunk.split("\n") if ln.strip()]
        if prev_lines:
            last = prev_lines[-1]
            ok = (
                len(last) <= 14
                and not _is_address_line(last)
                and not _is_punishment_line(last)
                and not _is_metadata_line(last)
                and not re.search(r"[0-9０-９]", last)
                and not any(
                    bad in last
                    for bad in (
                        "監査",
                        "違反",
                        "事故",
                        "実施",
                        "改善",
                        "事項",
                        "確認",
                        "報告",
                        "措置",
                        "通達",
                        "輸送",
                        "安全",
                        "管理",
                        "規程",
                        "教育",
                        "訓練",
                        "周知",
                        "徹底",
                        "経営",
                        "運航",
                        "船舶",
                        "旅客",
                        "適正",
                        "船員",
                        "上記",
                        "以上",
                        "なお",
                        "また",
                        "命じ",
                        "了知",
                        "詳細",
                        "別紙",
                        "概要",
                    )
                )
                and not last.endswith(("。", "、"))
            )
            if ok:
                # The fragment must look like the head of a 法人名:
                # contain 株式会社 / 有限会社 etc. OR end with a kanji
                # that could connect to a tail like "ホワイトリ" → "リー旭川".
                wrap_prefix = last
        # houjin extraction
        houjin = None
        houjin_pos = -1
        hm = re.search(
            r"（法人番号：[\s\n]*([\d０-９][\d０-９\s\n]{12,28})[\s\n]*）",
            block,
        )
        if hm:
            houjin = _normalize_houjin_block(hm.group(1))
            houjin_pos = hm.start()

        target_name: str | None = None
        if houjin_pos >= 0:
            # Stuff between row date end and houjin opener
            row_text_end = m.end()
            head = block[row_text_end:houjin_pos]
            # stuff between houjin opener and 13-digit number
            mid_text = re.sub(
                r"^[（(][^（()）]*?[:：][\s\n]*",
                "",
                block[hm.start() : hm.end()],
            )
            mid_text = re.sub(r"[\d０-９]{13}）?$", "", mid_text).strip()
            mid_text = mid_text.strip("（()）] 　\n")

            head_lines = [ln.strip() for ln in head.split("\n") if ln.strip()]
            mid_lines = [ln.strip() for ln in mid_text.split("\n") if ln.strip()]

            # Filter head_lines: drop addresses, punish, metadata, dates,
            # pure digits.
            kept: list[str] = []
            if wrap_prefix:
                kept.append(wrap_prefix)
            for ln in head_lines:
                if _is_address_line(ln):
                    continue
                if _is_punishment_line(ln):
                    continue
                if _is_metadata_line(ln):
                    continue
                if re.fullmatch(r"\d+", ln):
                    continue
                if "令和" in ln or "平成" in ln:
                    continue
                if "（法人番号" in ln or "法人番号" in ln:
                    pre = re.split(r"[（(]?法人番号", ln)[0].rstrip("（() 　")
                    if pre and len(pre) >= 2:
                        kept.append(pre)
                    continue
                kept.append(ln)
            # Append mid_lines (text between opener and digit close)
            for ln in mid_lines:
                if re.fullmatch(r"[\d０-９\s]+", ln):
                    continue
                if _is_address_line(ln):
                    continue
                if _is_metadata_line(ln):
                    continue
                kept.append(ln)

            joined = "".join(kept).strip()
            joined = joined.strip("（()）【】 　,、\n")

            # If joined contains a 法人 keyword that does NOT start at
            # position 0, walk back to capture full 法人名 (in case
            # preceding chars are part of name, e.g. continuation prefix).
            for kw in _LEGAL_FORMS:
                idx = joined.find(kw)
                if idx >= 0:
                    # 法人 keyword may appear at start → use whole joined.
                    # If at end (e.g. "知床らうすリンクル株式会社"), keep
                    # all preceding text.
                    # If somewhere in the middle, strip leading address
                    # fragment if any.
                    if idx > 0:
                        # Walk back to a boundary or up to 16 chars
                        start = max(0, idx - 16)
                        # Trim to not include digits / address kanji
                        for boundary in (" ", "　", "（", "(", "【", "・", "、", "「", "『"):
                            bidx = joined.rfind(boundary, 0, idx)
                            if bidx >= 0 and bidx >= start:
                                start = bidx + 1
                        joined = joined[start:]
                    break

            # Strip any trailing address fragments
            for pref in _ADDRESS_PREFIXES:
                if pref in joined:
                    aidx = joined.find(pref)
                    if aidx > 0:
                        joined = joined[:aidx]
                        break
            target_name = joined.strip()

            # Reject if still address-like
            if target_name and (
                target_name.startswith(_ADDRESS_PREFIXES)
                or re.fullmatch(r"[\d０-９]+", target_name)
            ):
                target_name = None
        else:
            # 個人 case: look on the row's date line for name suffix.
            # PDF often emits "令和4年6月20日 天神英二" on one line OR
            # "令和4年6月20日\n天神英二\n北海道目梨郡羅臼町".
            after_date = block[m.end() :]
            after_lines = [ln.strip() for ln in after_date.split("\n") if ln.strip()]
            cand: str | None = None
            for ln in after_lines[:6]:
                if _is_address_line(ln):
                    continue
                if _is_punishment_line(ln):
                    continue
                if _is_metadata_line(ln):
                    continue
                if "令和" in ln or "平成" in ln:
                    continue
                if "番号" in ln or "違反" in ln or "監査" in ln:
                    continue
                if re.fullmatch(r"\d+", ln):
                    continue
                # Drop lines starting with " " punctuation
                if not ln or ln[0] in ("、", "及", "監", "公", "○", "・", "※", "「", "『"):
                    continue
                # name should be ≤ 30 chars and have at least 1 kanji
                if 2 <= len(ln) <= 30 and re.search(r"[一-龯ぁ-んァ-ンー]", ln):
                    cand = ln
                    break
            target_name = cand

        if not target_name:
            continue
        target_name = re.sub(r"\s+", "", target_name).strip()
        target_name = target_name.strip("（()【】 　,、\n")
        # Drop leading single "日" / "に" / "月" residue (date-suffix bleed)
        target_name = re.sub(r"^[日月年に]+(?=[一-龯ぁ-んァ-ンー])", "", target_name)
        if len(target_name) < 2 or len(target_name) > 80:
            continue
        if target_name[0] in ("、", "及", "監", "公", "○", "・", "※"):
            continue
        if any(
            bad in target_name
            for bad in (
                "違反等の概要",
                "命令又は指導の内容",
                "違反点数",
                "氏名又は名称",
                "船種",
                "業種",
                "備考",
                "本社所在地",
                "事業者住所",
                "公表年月日",
                "処分等の種類",
            )
        ):
            continue
        # Reject if the cleaned name reduces to a pure 法人 form keyword
        if target_name in (
            "株式会社",
            "有限会社",
            "合同会社",
            "協同組合",
            "合資会社",
            "合名会社",
            "（株）",
            "(株)",
        ):
            continue
        # Hokkaido yearly column-flow PDFs garble names so badly that
        # truncated candidates ("知床らうすリンクル株", "有限会社ホワイトリ",
        # narrative leak "たところ、…") survive earlier filters. Apply a
        # stricter post-validation:
        #   1) ends with 法人 form keyword AND has at least 2 chars before
        #      that keyword (rejects bare "有限会社"), OR
        #   2) starts with 法人 form keyword AND has at least 4 chars
        #      after that keyword (rejects "株式会社" and "有限会社ホワイトリ"
        #      where tail "ホワイトリ" alone is too short to commit to), OR
        #   3) plausible 個人 (≤8 chars, all kanji/hiragana, no houjin).
        legal_suffix = next(
            (
                s
                for s in (
                    "株式会社",
                    "有限会社",
                    "合同会社",
                    "協同組合",
                    "合資会社",
                    "合名会社",
                    "（株）",
                    "(株)",
                )
                if target_name.endswith(s)
            ),
            None,
        )
        legal_prefix = next(
            (
                s
                for s in (
                    "株式会社",
                    "有限会社",
                    "合同会社",
                    "協同組合",
                    "合資会社",
                    "合名会社",
                )
                if target_name.startswith(s)
            ),
            None,
        )
        # Plausible 個人 (Japanese personal name): ≤8 chars, contains
        # at least 2 kanji (surname is normally kanji), no 法人 keywords,
        # and is NOT a stop-word fragment that often appears in prose
        # (filter explicit blacklist of common prose-leak fragments).
        kanji_count = sum(1 for ch in target_name if "一" <= ch <= "鿿")
        prose_blacklist = (
            "情報",
            "事項",
            "記録",
            "状況",
            "概要",
            "結果",
            "場合",
            "範囲",
            "対象",
            "確認",
            "措置",
            "処分",
            "教育",
            "訓練",
            "周知",
            "徹底",
            "適切",
            "最新",
            "経営",
            "運航",
            "事業",
            "事故",
            "違反",
            "命令",
            "勧告",
            "是正",
            "監査",
            "報告",
            "輸送",
            "安全",
            "管理",
        )
        plausible_individual = (
            houjin is None
            and 2 <= len(target_name) <= 8
            and re.fullmatch(r"[一-龯ぁ-んァ-ンー]+", target_name) is not None
            and kanji_count >= 2
            and not any(
                kw in target_name
                for kw in (
                    "株式会社",
                    "有限会社",
                    "合同会社",
                    "協同組合",
                    "合資会社",
                    "合名会社",
                    "（株）",
                    "(株)",
                    "会社",
                )
            )
            and not any(bad in target_name for bad in prose_blacklist)
        )
        accept = False
        if legal_suffix and len(target_name) - len(legal_suffix) >= 2:
            accept = True
        elif legal_prefix and len(target_name) - len(legal_prefix) >= 4:
            # Need name part to look like a real business name, not address fragment
            tail = target_name[len(legal_prefix) :]
            if not tail.startswith(_ADDRESS_PREFIXES) and not re.fullmatch(
                r"[一-龯ぁ-んァ-ンー]{1,3}", tail
            ):
                accept = True
        elif plausible_individual:
            accept = True
        if not accept:
            continue
        # If still contains an embedded address prefix, cut.
        for pref in _ADDRESS_PREFIXES:
            aidx = target_name.find(pref)
            if aidx > 0:
                target_name = target_name[:aidx]
                break

        # Punishment kind
        punish_raw, kind = map_punishment(block)
        if not punish_raw or not kind:
            continue

        # Reason summary
        summary: str | None = None
        for marker in (
            "通常監査を実施",
            "特別監査を実施",
            "違反事実",
            "違反行為",
            "違反が認められた",
            "事故が発生",
            "事実が確認",
            "を確認した",
        ):
            pos = block.find(marker)
            if pos >= 0:
                tail = block[pos : pos + 700]
                tail = re.sub(r"\s+", " ", tail).strip()
                summary = tail[:500]
                break

        related_law = extract_law_ref(block, default_law=hub.primary_law)
        if related_law:
            related_law = re.sub(r"\s+", " ", related_law).strip()

        out.append(
            MaritimeRecord(
                region=hub.region_code,
                issuing_authority=hub.region_label,
                issuance_date=date_iso,
                target_name=target_name,
                houjin_bangou=houjin,
                address=None,
                punishment_raw=punish_raw,
                enforcement_kind=kind,
                related_law_ref=related_law,
                reason_summary=summary,
                source_url=pdf_url,
                source_hub_url="",
            )
        )
    return out


def parse_tabular_pdf(
    text: str,
    *,
    hub: Hub,
    pdf_url: str,
) -> list[MaritimeRecord]:
    """Parse tabular formats (Chugoku / 海事局-senin / Shikoku-newer).

    Strategy: scrub column-header noise, then pair date markers with
    法人 names by sequence index. For senin format we pair every other
    date with a houjin (公表年月日 + 処分日 alternation).
    """
    records: list[MaritimeRecord] = []
    cleaned = _strip_table_noise(text)

    date_matches = list(ANY_DATE_RE.finditer(cleaned))
    houjin_matches = list(HOUJIN_DIGIT_RE.finditer(cleaned))

    if not (houjin_matches and date_matches):
        return parse_tabular_no_houjin(cleaned, hub=hub, pdf_url=pdf_url)

    # Filter out dates that only appear inside reason prose (no
    # punishment kw within next 700 chars). Also drop dates whose
    # immediate next char is 「、」 (prose continuation).
    row_dates: list[re.Match[str]] = []
    for dm in date_matches:
        next_ch = cleaned[dm.end() : dm.end() + 1]
        if next_ch == "、":
            continue
        window = cleaned[dm.start() : dm.start() + 700]
        if any(kw in window for (kw, _) in PUNISH_PATTERNS):
            row_dates.append(dm)

    if not row_dates:
        return records

    n_h = len(houjin_matches)
    n_d = len(row_dates)
    ratio = n_d / max(1, n_h)
    step = 2 if (1.6 <= ratio <= 2.4 and n_h >= 1) else 1

    for i, hm in enumerate(houjin_matches):
        di = i * step
        if di >= len(row_dates):
            break
        dm = row_dates[di]
        date_iso = parse_any_date_iso(dm.group(1))
        if not date_iso:
            continue
        try:
            year = int(date_iso[:4])
            if year < 2018 or year > 2027:
                continue
        except ValueError:
            continue

        end_pos = (
            row_dates[(i + 1) * step].start()
            if (i + 1) * step < len(row_dates)
            else min(len(cleaned), dm.start() + 1500)
        )
        block = cleaned[dm.start() : end_pos]

        # Target name: scan ~250 chars BEFORE houjin for a 法人-suffix
        # token, OR the line directly preceding 「（法人番号」.
        head = cleaned[max(0, hm.start() - 250) : hm.start()]
        # Drop leading column-header noise
        head = _strip_table_noise(head)
        head = re.sub(r"\s+", " ", head).strip()
        head = head.rstrip("（()【】 　,、")
        # Strip trailing 「（法人番号」 fragment if present
        head = re.sub(r"[（(]?\s*法人番号\s*[：:]?\s*$", "", head).strip()

        target_name: str | None = None
        # Prefer 法人 keyword: take the longest run ending in 法人-suffix.
        kw_match = re.search(
            r"([一-鿿ぁ-んァ-ヶ々ヶー（）()・〇\d０-９]{2,40}"
            r"(?:株式会社|有限会社|合同会社|協同組合))",
            head,
        )
        if kw_match:
            target_name = kw_match.group(1)
        else:
            # No 法人 keyword: take the LAST whitespace-separated token
            # that doesn't look like a date / column header / address.
            tokens = [t for t in re.split(r"\s+", head) if t]
            for tok in reversed(tokens):
                if re.fullmatch(r"[\d０-９]+", tok):
                    continue
                if any(
                    kw in tok
                    for kw in (
                        "年",
                        "月",
                        "日",
                        "番号",
                        "事業者",
                        "船種",
                        "業種",
                        "船 名",
                        "船名",
                        "本社",
                        "所在地",
                        "備考",
                        "所管",
                        "違反",
                        "命令",
                        "概要",
                        "公表",
                        "北海道",
                        "都",
                        "府",
                        "県",
                    )
                ):
                    continue
                if len(tok) >= 2:
                    target_name = tok
                    break
        if not target_name:
            continue
        # Cleanup: strip whitespace & punctuation; drop trailing parens
        target_name = re.sub(r"\s+", "", target_name).strip()
        target_name = target_name.strip("（()【】 　,、")
        # Drop leading date fragments like "令和7年8月5日" or "2025年8月5日"
        target_name = re.sub(
            r"^(?:令和\s*\d+年\s*\d+月\s*\d+日"
            r"|平成\s*\d+年\s*\d+月\s*\d+日"
            r"|20\d\d年\s*\d{1,2}月\s*\d{1,2}日"
            r"|\d+年\s*\d+月\s*\d+日)",
            "",
            target_name,
        ).strip("（()【】 　,、")
        # Drop leading "○" / digits up to length 2
        target_name = re.sub(r"^[○・※\d]+", "", target_name)
        # Drop leading single "日" / "に" / "月" residue (date-suffix bleed)
        target_name = re.sub(r"^[日月年に]+", "", target_name)
        if not target_name or len(target_name) < 2 or len(target_name) > 80:
            continue
        if any(
            bad in target_name
            for bad in (
                "違反等の概要",
                "命令又は指導の内容",
                "違反点数",
                "氏名又は名称",
                "船種",
                "業種",
                "備考",
                "本社所在地",
                "事業者住所",
                "公表年月日",
                "処分等の種類",
                "船舶所有者名",
                "輸送の安全",
            )
        ):
            continue
        if target_name[0] in ("、", "及", "監", "公", "○", "・", "※"):
            continue
        # Reject if the cleaned name reduces to a pure 法人 form keyword
        if target_name in (
            "株式会社",
            "有限会社",
            "合同会社",
            "協同組合",
            "合資会社",
            "合名会社",
            "（株）",
            "(株)",
        ):
            continue

        houjin = _normalize_houjin_block(hm.group(1))

        punish_raw, kind = map_punishment(block)
        if not punish_raw or not kind:
            continue

        summary: str | None = None
        for marker in (
            "違反等の概要",
            "違反事実",
            "違反行為",
            "監査を実施",
            "を確認した",
            "事故が発生",
            "違反が認められた",
            "違反に関する累積",
            "通常監査",
            "特別監査",
        ):
            pos = block.find(marker)
            if pos >= 0:
                tail = block[pos : pos + 700]
                tail = re.sub(r"\s+", " ", tail).strip()
                summary = tail[:500]
                break
        if not summary:
            tail = re.sub(r"\s+", " ", block).strip()
            summary = tail[:400]

        related_law = extract_law_ref(block, default_law=hub.primary_law)
        if related_law:
            related_law = re.sub(r"\s+", " ", related_law).strip()

        records.append(
            MaritimeRecord(
                region=hub.region_code,
                issuing_authority=hub.region_label,
                issuance_date=date_iso,
                target_name=target_name,
                houjin_bangou=houjin,
                address=None,
                punishment_raw=punish_raw,
                enforcement_kind=kind,
                related_law_ref=related_law,
                reason_summary=summary,
                source_url=pdf_url,
                source_hub_url="",
            )
        )
    return records


def parse_tabular_no_houjin(
    text: str,
    *,
    hub: Hub,
    pdf_url: str,
) -> list[MaritimeRecord]:
    """Tabular fallback for PDFs that lack 法人番号 columns.

    Pair each date with the nearest 法人 keyword in its post-date
    window (~700 chars).
    """
    records: list[MaritimeRecord] = []
    NAME_RE = re.compile(
        r"([一-鿿ぁ-んァ-ヶ々ヶー（）()・\s]{2,50}?"
        r"(?:株式会社|有限会社|合同会社|協同組合|（株）|\(株\)))"
    )

    date_matches = list(ANY_DATE_RE.finditer(text))
    used_name_pos: set[int] = set()
    for dm in date_matches:
        date_iso = parse_any_date_iso(dm.group(1))
        if not date_iso:
            continue
        try:
            year = int(date_iso[:4])
            if year < 2018 or year > 2027:
                continue
        except ValueError:
            continue
        if text[dm.end() : dm.end() + 1] == "、":
            continue

        window = text[dm.start() : dm.start() + 800]
        if not any(kw in window for (kw, _) in PUNISH_PATTERNS):
            continue
        nm = NAME_RE.search(window)
        if not nm:
            continue
        # avoid reusing the same name across multiple dates
        abs_pos = dm.start() + nm.start()
        if abs_pos in used_name_pos:
            continue
        used_name_pos.add(abs_pos)
        target_name = re.sub(r"\s+", "", nm.group(1)).strip()
        target_name = target_name.strip("（()【】 　,、")
        target_name = re.sub(
            r"^(?:令和\s*\d+年\s*\d+月\s*\d+日"
            r"|平成\s*\d+年\s*\d+月\s*\d+日"
            r"|20\d\d年\s*\d{1,2}月\s*\d{1,2}日"
            r"|\d+年\s*\d+月\s*\d+日)",
            "",
            target_name,
        ).strip("（()【】 　,、")
        # Drop leading single "日" / "に" / "月" residue (date-suffix bleed)
        target_name = re.sub(r"^[日月年に]+(?=[一-龯ぁ-んァ-ンー])", "", target_name)
        if not target_name or len(target_name) < 3 or len(target_name) > 60:
            continue
        if any(
            bad in target_name
            for bad in (
                "違反等の概要",
                "命令又は指導の内容",
                "違反点数",
            )
        ):
            continue
        # Reject pure 法人 form keyword leftovers
        if target_name in (
            "株式会社",
            "有限会社",
            "合同会社",
            "協同組合",
            "合資会社",
            "合名会社",
            "（株）",
            "(株)",
        ):
            continue

        punish_raw, kind = map_punishment(window)
        if not punish_raw or not kind:
            continue
        related_law = extract_law_ref(window, default_law=hub.primary_law)
        if related_law:
            related_law = re.sub(r"\s+", " ", related_law).strip()
        summary = re.sub(r"\s+", " ", window[:500]).strip()

        records.append(
            MaritimeRecord(
                region=hub.region_code,
                issuing_authority=hub.region_label,
                issuance_date=date_iso,
                target_name=target_name,
                houjin_bangou=None,
                address=None,
                punishment_raw=punish_raw,
                enforcement_kind=kind,
                related_law_ref=related_law,
                reason_summary=summary,
                source_url=pdf_url,
                source_hub_url="",
            )
        )
    return records


def parse_pdf(
    pdf_bytes: bytes,
    *,
    hub: Hub,
    pdf_url: str,
    hub_url: str,
) -> list[MaritimeRecord]:
    try:
        text = extract_text(io.BytesIO(pdf_bytes))
    except Exception as exc:
        _LOG.warning("pdf parse failed url=%s err=%s", pdf_url, exc)
        return []
    if not text or len(text) < 200:
        return []
    text = text.replace("　", " ")

    if "（１）行政処分等の年月日" in text or "（1）行政処分等の年月日" in text:
        recs = parse_narrative_pdf(text, hub=hub, pdf_url=pdf_url)
        if recs:
            for r in recs:
                r.source_hub_url = hub_url
            return recs

    # Hokkaido yearly summary detection: header + multi-row markers.
    is_hokkaido_yearly = (
        "海上運送法に基づく行政処分等一覧" in text or "行政処分等一覧" in text
    ) and len(HOKKAIDO_ROW_RE.findall(text)) >= 5
    if is_hokkaido_yearly:
        recs = parse_hokkaido_yearly(text, hub=hub, pdf_url=pdf_url)
        if recs:
            for r in recs:
                r.source_hub_url = hub_url
            return recs

    if looks_tabular(text):
        recs = parse_tabular_pdf(text, hub=hub, pdf_url=pdf_url)
        if recs:
            for r in recs:
                r.source_hub_url = hub_url
            return recs

    # Last-ditch: try narrative anyway, then Hokkaido, then tabular fallbacks.
    recs = parse_narrative_pdf(text, hub=hub, pdf_url=pdf_url)
    if not recs:
        recs = parse_hokkaido_yearly(text, hub=hub, pdf_url=pdf_url)
    if not recs:
        recs = parse_tabular_pdf(text, hub=hub, pdf_url=pdf_url)
    if not recs:
        recs = parse_tabular_no_houjin(text, hub=hub, pdf_url=pdf_url)
    for r in recs:
        r.source_hub_url = hub_url
    return recs


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
        raise SystemExit("am_enforcement_detail table missing")
    return conn


def load_existing_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for r in conn.execute(
        "SELECT IFNULL(issuing_authority, ''), issuance_date, "
        "       IFNULL(target_name, ''), IFNULL(enforcement_kind, '') "
        "FROM am_enforcement_detail"
    ):
        keys.add((r[0], r[1], r[2], r[3]))
    return keys


def next_seq(conn: sqlite3.Connection, region: str) -> int:
    prefix = f"AM-ENF-MLIT-MARITIME-{region}-"
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(canonical_id, LENGTH(?) + 1) AS INTEGER)) "
        "FROM am_entities WHERE canonical_id LIKE ? || '%'",
        (prefix, prefix),
    ).fetchone()
    if row and row[0]:
        return int(row[0]) + 1
    return 1


def upsert_record(
    conn: sqlite3.Connection,
    rec: MaritimeRecord,
    canonical_id: str,
    fetched_at: str,
) -> str:
    raw_json = {
        "region": rec.region,
        "issuing_authority": rec.issuing_authority,
        "target_name": rec.target_name,
        "houjin_bangou": rec.houjin_bangou,
        "address": rec.address,
        "issuance_date": rec.issuance_date,
        "punishment_raw": rec.punishment_raw,
        "enforcement_kind": rec.enforcement_kind,
        "related_law_ref": rec.related_law_ref,
        "reason_summary": rec.reason_summary,
        "source_url": rec.source_url,
        "source_hub_url": rec.source_hub_url,
        "fetched_at": fetched_at,
        "source": "mlit_maritime_pdf",
    }
    domain = urllib.parse.urlparse(rec.source_url).netloc

    cur = conn.execute(
        "INSERT OR IGNORE INTO am_entities ("
        "  canonical_id, record_kind, source_topic, primary_name, "
        "  confidence, source_url, source_url_domain, fetched_at, raw_json"
        ") VALUES (?, 'enforcement', ?, ?, ?, ?, ?, ?, ?)",
        (
            canonical_id,
            f"mlit_maritime_{rec.region}",
            rec.target_name,
            0.85,
            rec.source_url,
            domain,
            fetched_at,
            json.dumps(raw_json, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    if cur.rowcount == 0:
        return "skip"

    conn.execute(
        "INSERT INTO am_enforcement_detail ("
        "  entity_id, houjin_bangou, target_name, enforcement_kind, "
        "  issuing_authority, issuance_date, reason_summary, "
        "  related_law_ref, source_url, source_fetched_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            canonical_id,
            rec.houjin_bangou,
            rec.target_name,
            rec.enforcement_kind,
            rec.issuing_authority,
            rec.issuance_date,
            rec.reason_summary,
            rec.related_law_ref,
            rec.source_url,
            fetched_at,
        ),
    )
    return "insert"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--regions", type=str, default="", help="comma-separated region codes (default: all hubs)"
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="stop after this many INSERTs across all hubs"
    )
    ap.add_argument(
        "--per-hub-pdf-limit", type=int, default=None, help="cap PDFs walked per hub (smoke tests)"
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--log-file", type=Path, default=None)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.regions.strip():
        wanted = {r.strip() for r in args.regions.split(",") if r.strip()}
        hubs = [h for h in HUBS if h.region_code in wanted]
    else:
        hubs = list(HUBS)
    if not hubs:
        _LOG.error("no hubs selected")
        return 2

    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    http = MaritimeHttpClient()
    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        conn = open_db(args.db)
        conn.execute("BEGIN IMMEDIATE")
        existing_keys = load_existing_keys(conn)
        _LOG.info(
            "existing am_enforcement_detail keys=%d",
            len(existing_keys),
        )
    else:
        existing_keys = set()

    stats: dict[str, dict[str, int]] = {}
    region_breakdown: dict[str, int] = {}
    law_breakdown: dict[str, int] = {}
    samples: list[MaritimeRecord] = []
    total_inserts = 0

    try:
        for hub in hubs:
            key = f"{hub.region_code}:{hub.url}"
            cs = stats.setdefault(
                hub.region_code,
                {
                    "pdfs_seen": 0,
                    "pdfs_fetched": 0,
                    "records_extracted": 0,
                    "insert": 0,
                    "skip_dup": 0,
                    "skip_existing": 0,
                },
            )
            _LOG.info(
                "hub region=%s label=%s url=%s",
                hub.region_code,
                hub.region_label,
                hub.url,
            )
            pdf_pairs = collect_pdfs_for_hub(http, hub)
            cs["pdfs_seen"] += len(pdf_pairs)
            _LOG.info(
                "  pdfs_found=%d",
                len(pdf_pairs),
            )
            if args.per_hub_pdf_limit is not None:
                pdf_pairs = pdf_pairs[: args.per_hub_pdf_limit]

            # Process newest URLs first as a heuristic.
            pdf_pairs.sort(key=lambda p: p[0], reverse=True)

            seq_counter = next_seq(conn, hub.region_code) if conn is not None else 1

            stop_hub = False
            for pdf_url, hub_url in pdf_pairs:
                if args.limit is not None and total_inserts >= args.limit:
                    stop_hub = True
                    break
                status, body = http.get_bytes(pdf_url)
                if status != 200 or not body:
                    continue
                cs["pdfs_fetched"] += 1
                recs = parse_pdf(
                    body,
                    hub=hub,
                    pdf_url=pdf_url,
                    hub_url=hub_url,
                )
                cs["records_extracted"] += len(recs)
                _LOG.debug(
                    "  pdf=%s extracted=%d",
                    pdf_url,
                    len(recs),
                )
                for r in recs:
                    dedup_key = (
                        r.issuing_authority,
                        r.issuance_date,
                        r.target_name,
                        r.enforcement_kind,
                    )
                    if dedup_key in existing_keys:
                        cs["skip_existing"] += 1
                        continue
                    existing_keys.add(dedup_key)
                    if args.dry_run or conn is None:
                        cs["insert"] += 1
                        total_inserts += 1
                        region_breakdown[r.issuing_authority] = (
                            region_breakdown.get(r.issuing_authority, 0) + 1
                        )
                        if r.related_law_ref:
                            law_breakdown[r.related_law_ref] = (
                                law_breakdown.get(r.related_law_ref, 0) + 1
                            )
                        if len(samples) < 5:
                            samples.append(r)
                        if cs["insert"] <= 3:
                            _LOG.info(
                                "DRY %s | %s | %s | houjin=%s | %s | %s | law=%s",
                                hub.region_code,
                                r.issuance_date,
                                r.target_name,
                                r.houjin_bangou,
                                r.punishment_raw,
                                r.enforcement_kind,
                                r.related_law_ref,
                            )
                        continue
                    canonical_id = f"AM-ENF-MLIT-MARITIME-{hub.region_code}-{seq_counter:06d}"
                    seq_counter += 1
                    try:
                        verdict = upsert_record(
                            conn,
                            r,
                            canonical_id,
                            fetched_at,
                        )
                    except sqlite3.Error as exc:
                        _LOG.warning(
                            "DB insert err name=%s err=%s",
                            r.target_name,
                            exc,
                        )
                        continue
                    if verdict == "insert":
                        cs["insert"] += 1
                        total_inserts += 1
                        region_breakdown[r.issuing_authority] = (
                            region_breakdown.get(r.issuing_authority, 0) + 1
                        )
                        if r.related_law_ref:
                            law_breakdown[r.related_law_ref] = (
                                law_breakdown.get(r.related_law_ref, 0) + 1
                            )
                        if len(samples) < 5:
                            samples.append(r)
                    else:
                        cs["skip_dup"] += 1
                    if total_inserts > 0 and total_inserts % 50 == 0:
                        conn.commit()
                        conn.execute("BEGIN IMMEDIATE")
                    if args.limit is not None and total_inserts >= args.limit:
                        stop_hub = True
                        break
                if stop_hub:
                    break
            _LOG.info("hub region=%s done: %s", hub.region_code, cs)
            if args.limit is not None and total_inserts >= args.limit:
                break

    finally:
        http.close()
        if conn is not None:
            conn.commit()
            conn.close()

    _LOG.info("SUMMARY total_inserts=%d", total_inserts)
    _LOG.info("PER REGION: %s", json.dumps(region_breakdown, ensure_ascii=False))
    _LOG.info("PER LAW: %s", json.dumps(law_breakdown, ensure_ascii=False))
    _LOG.info("HUB STATS: %s", json.dumps(stats, ensure_ascii=False))
    print(
        "\n".join(
            [
                f"== sample {i + 1} ==\n"
                f"  date={s.issuance_date}\n"
                f"  authority={s.issuing_authority}\n"
                f"  target={s.target_name}\n"
                f"  houjin={s.houjin_bangou}\n"
                f"  kind={s.enforcement_kind}\n"
                f"  punishment_raw={s.punishment_raw}\n"
                f"  law_ref={s.related_law_ref}\n"
                f"  url={s.source_url}"
                for i, s in enumerate(samples[:5])
            ]
        )
    )

    if args.log_file is not None:
        with open(args.log_file, "a") as f:
            f.write(
                f"\n## {fetched_at} MLIT 海事 enforcement ingest\n"
                f"  hubs={len(hubs)} limit={args.limit}\n"
                f"  total_inserts={total_inserts}\n"
                f"  per_region="
                f"{json.dumps(region_breakdown, ensure_ascii=False)}\n"
                f"  per_law="
                f"{json.dumps(law_breakdown, ensure_ascii=False)}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
