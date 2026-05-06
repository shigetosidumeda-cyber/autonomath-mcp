#!/usr/bin/env python3
"""Ingest 国土交通省 各地方運輸局 自動車運送事業 (旅客・貨物) 行政処分

10 運輸局 + 沖縄総合事務局 publish individual-record monthly PDFs of
バス / タクシー / トラック 行政処分. Each PDF contains a table with:

    行政処分年月日 | 事業者名(法人番号) | 事業者所在地 |
    営業所名 | 営業所所在地 | 行政処分の内容 | 主な違反の条項 |
    違反行為の概要

Sources (HTML hub pages — first scraped, then PDFs walked):

    関東運輸局      https://wwwtb.mlit.go.jp/kanto/page3/
    中部運輸局      https://wwwtb.mlit.go.jp/chubu/syobun/
    近畿運輸局      https://wwwtb.mlit.go.jp/kinki/content/
    九州運輸局      https://wwwtb.mlit.go.jp/kyushu/jigyousya/
    北海道運輸局    https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/
    東北運輸局      https://wwwtb.mlit.go.jp/tohoku/jk/
    北陸信越運輸局  https://wwwtb.mlit.go.jp/hokushin/hrt54/
    中国運輸局      https://wwwtb.mlit.go.jp/chugoku/jidousha/
    四国運輸局      https://wwwtb.mlit.go.jp/shikoku/
    沖縄総合事務局  https://www.ogb.go.jp/unyu/gyousei/

Encoding: most regional MLIT pages serve Shift_JIS. OGB serves UTF-8.

Schema target (autonomath.db):
    am_entities (canonical_id = AM-ENF-MLIT-UNYU-<region>-<seq>,
                 record_kind='enforcement', primary_name=事業者名,
                 source_url=PDF URL, raw_json)
    am_enforcement_detail (entity_id, houjin_bangou, target_name,
                           enforcement_kind, issuing_authority,
                           issuance_date, reason_summary, related_law_ref)

enforcement_kind mapping (text => CHECK enum):
    事業停止 / 業務停止 / 輸送施設の使用停止 / 自動車使用停止 -> business_improvement
    許可取消 / 登録取消                                       -> license_revoke
    文書警告 / 文書勧告 / 警告 / 勧告 / 口頭注意              -> other

Idempotency: dedup on (issuing_authority, issuance_date, target_name,
enforcement_kind, source_url) via canonical_id.

Per-write transaction protocol: BEGIN IMMEDIATE + busy_timeout=300000 ms,
periodic flush every 50 inserts so other parallel writers can interleave.

CLI:
    python scripts/ingest/ingest_enforcement_mlit_unyu.py \
        --db autonomath.db [--regions kanto,chubu,...] \
        [--limit 400] [--dry-run]
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("autonomath.ingest.enforcement_mlit_unyu")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = "jpintel-mcp-ingest/1.0 (+https://jpcite.com; contact=ops@jpcite.com)"
PER_REQUEST_DELAY_SEC = 0.6
HTTP_TIMEOUT_SEC = 60.0
MAX_RETRIES = 3

# Each region: hub HTML pages we walk to find monthly PDFs.
# (hub_url, region_code, region_label, encoding hint)
REGION_HUBS: dict[str, dict] = {
    "kanto": {
        "label": "関東運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/kanto/page3/noriai/index.html",
            "https://wwwtb.mlit.go.jp/kanto/page3/kasikiri/index.html",
            "https://wwwtb.mlit.go.jp/kanto/page3/jyouyou/index.html",
            "https://wwwtb.mlit.go.jp/kanto/page3/kamotu/index.html",
        ],
    },
    "chubu": {
        "label": "中部運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/chubu/syobun/jidousya/kohyou-noriai.htm",
            "https://wwwtb.mlit.go.jp/chubu/syobun/jidousya/kohyou-kashikiri.htm",
            "https://wwwtb.mlit.go.jp/chubu/syobun/jidousya/kohyou-jouyou.htm",
            "https://wwwtb.mlit.go.jp/chubu/syobun/kamotu/kamotusyobun.htm",
        ],
    },
    "kinki": {
        "label": "近畿運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/kinki/content/shobun_truck.html",
            "https://wwwtb.mlit.go.jp/kinki/koutsu/penalty/taxi/txindex.htm",
        ],
    },
    "kyushu": {
        "label": "九州運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/kyushu/jigyousya/body.htm",
        ],
        # We also drill into the per-year subpages:
        "drill_in": True,
    },
    "hokkaido": {
        "label": "北海道運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/jidousha/noriai.html",
            "https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/jidousha/kasikiri.html",
            "https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/jidousha/jyouyou.html",
            "https://wwwtb.mlit.go.jp/hokkaido/kakusyu/gyoseisyobun/jidousha/kamotu.html",
        ],
    },
    "tohoku": {
        "label": "東北運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/tohoku/jk/jk-sub31.html",
            "https://wwwtb.mlit.go.jp/tohoku/jk/jk-sub32.html",
            "https://wwwtb.mlit.go.jp/tohoku/jk/jk-sub33.html",
            "https://wwwtb.mlit.go.jp/tohoku/jk/jk-sub59.html",
        ],
    },
    "hokushin": {
        "label": "北陸信越運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/hokushin/hrt54/track/disposition/deposition_b1.html",
            "https://wwwtb.mlit.go.jp/hokushin/hrt54/bus_taxi/disposition/deposition_a2_2.html",
            "https://wwwtb.mlit.go.jp/hokushin/hrt54/bus_taxi/disposition/deposition_a2_3.html",
        ],
    },
    "chugoku": {
        "label": "中国運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/chugoku/jidousha/joukyou01.html",
            "https://wwwtb.mlit.go.jp/chugoku/jidousha/joukyou02.html",
            "https://wwwtb.mlit.go.jp/chugoku/jidousha/joukyou03.html",
            "https://wwwtb.mlit.go.jp/chugoku/jidousha/joukyou04.html",
            "https://wwwtb.mlit.go.jp/chugoku/jidousha/joukyou04_k.html",
        ],
    },
    "shikoku": {
        "label": "四国運輸局",
        "encoding": "shift_jis",
        "hubs": [
            "https://wwwtb.mlit.go.jp/shikoku/soshiki/jidousya/index.html",
        ],
    },
    "okinawa": {
        "label": "沖縄総合事務局運輸部",
        "encoding": "utf-8",
        "hubs": [
            "https://www.ogb.go.jp/unyu/gyousei/004155/004179/004187",
            "https://www.ogb.go.jp/unyu/gyousei/004155/004179/004188",
            "https://www.ogb.go.jp/unyu/gyousei/004155/004179/004189",
            "https://www.ogb.go.jp/unyu/gyousei/004155/unyu_gyousei_kamotu/004193",
        ],
    },
}

# Map punishment text => enforcement_kind enum.
# Order matters — most specific first.
PUNISH_PATTERNS: list[tuple[str, str]] = [
    ("許可取消", "license_revoke"),
    ("登録取消", "license_revoke"),
    ("登録の取消", "license_revoke"),
    ("許可の取消", "license_revoke"),
    ("事業停止", "business_improvement"),
    ("業務停止", "business_improvement"),
    ("輸送施設の使用停止", "business_improvement"),
    ("車両使用停止", "business_improvement"),
    ("自動車使用停止", "business_improvement"),
    ("輸送施設の停止", "business_improvement"),
    ("文書警告", "other"),
    ("文書勧告", "other"),
    ("口頭注意", "other"),
    ("警告", "other"),
    ("勧告", "other"),
]

# Default related_law_ref by transport mode keyword in PDF text.
LAW_KEYWORDS_TO_NAME: list[tuple[str, str]] = [
    ("貨物利用運送事業法", "貨物利用運送事業法"),
    ("貨物自動車運送事業輸送安全規則", "貨物自動車運送事業輸送安全規則"),
    ("貨物自動車運送事業法", "貨物自動車運送事業法"),
    ("旅客自動車運送事業運輸規則", "旅客自動車運送事業運輸規則"),
    ("道路運送法", "道路運送法"),
    ("道路運送車両法", "道路運送車両法"),
]

HOUJIN_RE = re.compile(r"法\s*人\s*番\s*号\s*[（(:：]?\s*(\d{13})\s*[）)]?")
# 13-digit 法人番号 split by full/half-width digits and CJK newlines.
# Accept full-width or half-width opening paren or colon between
# 「法人番号」 and digits (Kanto form style uses 「法人番号：」). Allow
# whitespace within 「法人番号」 itself because pdfminer may insert
# newlines between 「法人」 and 「番号」 from column wraps.
HOUJIN_DIGIT_RE = re.compile(r"法\s*人\s*番\s*号\s*[（(：:]?\s*([\d０-９\s　\n]{13,40})\s*[）)]?")
DATE_8DIGIT_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
DATE_REIWA_DOTTED_RE = re.compile(r"R(\d+)\.(\d+)\.(\d+)")
DATE_REIWA_KANJI_RE = re.compile(r"令和(\d+)年(\d+)月(\d+)日")
DATE_HEISEI_KANJI_RE = re.compile(r"平成(\d+)年(\d+)月(\d+)日")
DATE_PLAIN_KANJI_RE = re.compile(r"(20\d\d)年(\d+)月(\d+)日")

# Block / segment splitter for individual rows in a PDF — match date
# at LINE START only so we don't catch dates embedded inside reason
# prose (which heavily references "令和7年X月Y日、監査を実施" text).
# Patterns:
#   YYYYMMDD (8-digit ASCII)  — used by Kanto/Chubu/Kinki rows
#   令和N年M月D日              — used by Hokushin/Kinki text rows
#   RN.M.D                    — used by Hokkaido / hokushin alternates
#
# Multi-line: we anchor to ^ (re.M) and allow a leading row-number
# ("1 ", "2 ") or 事業の種類 prefix ("一般貨物", "一般旅客", etc.).
DATE_ANY_RE = re.compile(
    r"^\s*(?:\d{1,3}\s+|一般貨物\s+|一般旅客\s+|一般乗合\s+|一般乗用\s+|一般貸切\s+|貨物軽\s+)?"
    r"(?P<dt>(?:20\d{6})|(?:令和\s*\d+年\s*\d+月\s*\d+日)|(?:平成\s*\d+年\s*\d+月\s*\d+日)|(?:R\s*\d+\.\d+\.\d+))",
    re.MULTILINE,
)


# Extract 法人番号 from a paren-grouped chunk. The 13 digits may span
# linebreaks because of layout extraction quirks.
def _normalize_houjin_block(block: str) -> str | None:
    digits = "".join(ch for ch in block if ch.isdigit() or "０" <= ch <= "９")
    # Convert full-width to half-width
    out = []
    for ch in digits:
        if "０" <= ch <= "９":
            out.append(chr(ord("0") + (ord(ch) - 0xFF10)))
        else:
            out.append(ch)
    digits = "".join(out)
    if len(digits) >= 13:
        return digits[:13]
    return None


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class UnyuHttpClient:
    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.5",
            },
            timeout=HTTP_TIMEOUT_SEC,
            follow_redirects=True,
        )
        self._last_fetch: float = 0.0

    def _pace(self) -> None:
        now = time.monotonic()
        wait = PER_REQUEST_DELAY_SEC - (now - self._last_fetch)
        if wait > 0:
            time.sleep(wait)
        self._last_fetch = time.monotonic()

    def get_text(self, url: str, encoding: str = "utf-8") -> tuple[int, str]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.get(url)
                if r.status_code == 200:
                    raw = r.content
                    for enc in (encoding, "shift_jis", "utf-8", "euc_jp"):
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
# Models
# ---------------------------------------------------------------------------


@dataclass
class UnyuRecord:
    region: str  # kanto/chubu/...
    region_label: str  # 関東運輸局
    issuance_date: str  # ISO yyyy-mm-dd
    target_name: str  # 事業者名 (cleaned)
    houjin_bangou: str | None
    address: str | None
    office_name: str | None
    office_address: str | None
    punishment_raw: str
    enforcement_kind: str
    related_law_ref: str | None
    reason_summary: str | None
    source_url: str  # PDF URL
    source_hub_url: str  # HTML hub URL


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def normalize_date(token: str) -> str | None:
    """Convert any of the supported date formats to ISO yyyy-mm-dd."""
    token = token.strip()
    m = DATE_8DIGIT_RE.fullmatch(token)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = DATE_REIWA_KANJI_RE.fullmatch(token)
    if m:
        y = 2018 + int(m.group(1))
        try:
            return dt.date(y, int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = DATE_HEISEI_KANJI_RE.fullmatch(token)
    if m:
        y = 1988 + int(m.group(1))
        try:
            return dt.date(y, int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = DATE_REIWA_DOTTED_RE.fullmatch(token)
    if m:
        y = 2018 + int(m.group(1))
        try:
            return dt.date(y, int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = DATE_PLAIN_KANJI_RE.fullmatch(token)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    return None


def map_punishment(text: str) -> tuple[str, str] | tuple[None, None]:
    """Return (punishment_raw, enforcement_kind) if a known punishment
    keyword is present, else (None, None). Caller must check."""
    for kw, kind in PUNISH_PATTERNS:
        if kw in text:
            idx = text.find(kw)
            tail = text[idx : idx + 80]
            for stop in ("\n", "○", "■", "・", "事業者", "営業所"):
                pos = tail.find(stop, len(kw))
                if pos > 0:
                    tail = tail[:pos]
            return tail.strip(), kind
    return None, None


def extract_law_ref(text: str) -> str | None:
    for kw, name in LAW_KEYWORDS_TO_NAME:
        if kw in text:
            # Try to capture an article reference.
            idx = text.find(kw)
            after = text[idx + len(kw) : idx + len(kw) + 40]
            m = re.match(r"\s*(第[\d\s]+条(?:第[\d\s]+項)?(?:第[\d\s]+号)?)", after)
            if m:
                return f"{name} {m.group(1).strip()}"
            return name
    return None


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------


def _parse_column_flow(
    *,
    text: str,
    row_dates: list[re.Match[str]],
    houjin_matches: list[re.Match[str]],
    region: str,
    region_label: str,
    pdf_url: str,
    hub_url: str,
) -> list["UnyuRecord"]:
    """Column-flow PDF layout (e.g. Hokkaido).

    Row-start dates appear in a leading column block; 事業者名 + 法人番号
    appear in a trailing column block. Pair them by sequence index when
    counts are comparable. The N-th date corresponds to the N-th houjin.

    For each pair, extract:
    - issuance_date from the date match
    - punishment + law from the ~250 chars AFTER the date
    - target_name from the text immediately BEFORE the houjin match
    - houjin from the regex group
    """
    records: list[UnyuRecord] = []

    # Use the smaller count as the pairing length.
    pair_n = min(len(row_dates), len(houjin_matches))

    for i in range(pair_n):
        dm = row_dates[i]
        hm = houjin_matches[i]

        # Date.
        dt_token = re.sub(r"\s+", "", dm.group("dt"))
        date_iso = normalize_date(dt_token)
        if not date_iso:
            continue
        try:
            year = int(date_iso[:4])
            if year < 2018 or year > 2027:
                continue
        except ValueError:
            continue

        # Punishment + law from the date-side block (everything from the
        # date marker up to the next row-start date, or +600 chars).
        next_pos = row_dates[i + 1].start() if i + 1 < len(row_dates) else dm.start() + 600
        date_block = text[dm.start() : next_pos]
        punish_raw, kind = map_punishment(date_block)
        if not punish_raw or not kind:
            continue
        law_ref = extract_law_ref(date_block)

        # Reason summary: scan the 600 chars *forward* for "監査を実施" /
        # "違反が認められた" prose. In column-flow layouts the reason text
        # is interleaved with the next row's date columns, but the segment
        # immediately following each row-start date is usually clean.
        summary = None
        for marker in ("監査を実施", "違反が認められた", "違反行為の概要"):
            pos = date_block.find(marker)
            if pos >= 0:
                tail = date_block[pos : pos + 700]
                tail = re.sub(r"\s+", " ", tail).strip()
                summary = tail[:600]
                break

        # Houjin number.
        houjin = _normalize_houjin_block(hm.group(1))

        # Target name = text immediately BEFORE the houjin match. Walk
        # back ~150 chars and trim parens / column noise.
        head_start = max(0, hm.start() - 150)
        head = text[head_start : hm.start()]
        # Strip whitespace and condense to single line.
        head = re.sub(r"\s+", "", head).strip()
        # Trim trailing 「（法人番号」 paren since regex matched at "法人番号".
        head = head.rstrip("（()【】 　,、")
        # In column-flow PDFs the previous row's reason/law text bleeds
        # in. Cut at well-known boundary tokens that appear AFTER previous
        # row's tail and BEFORE the current row's name:
        # - Row number prefix like "12" / "5" / "3" at end of prior record
        # - 【貨物軽自動車運送事業】 (Hokkaido sub-class header)
        # - 」  closing-quote of the previous row's 安全規則 reference
        # - 他 N 件 (e.g. "他１件")  marks end of previous row's law list
        # We pick the LATEST occurrence of any boundary marker to grab the
        # smallest possible name slice.
        boundary_idx = -1
        for marker in (
            "他１件",
            "他２件",
            "他３件",
            "他４件",
            "他５件",
            "他６件",
            "他７件",
            "他８件",
            "他９件",
            "他10件",
            "他１０件",
            "者小池信也",  # Hokkaido 日本郵便 representative tail
            "代表者",
            "】",  # 【貨物軽自動車運送事業】 close
        ):
            idx = head.rfind(marker)
            if idx >= 0:
                end = idx + len(marker)
                if end > boundary_idx:
                    boundary_idx = end
        if boundary_idx > 0:
            head = head[boundary_idx:]
        # Strip leading row-number digits like "12" / "5" — these are the
        # prior record's row count fields (Hokkaido).
        head = re.sub(r"^[\dー－‐\-]{1,3}", "", head)
        # Strip 【...】 sub-class header if it leads.
        head = re.sub(r"^【[^】]*】", "", head)
        # Strip leading row-number digits one more time (after 】 cut).
        head = re.sub(r"^[\dー－‐\-]{1,3}", "", head)
        # If the head looks like "<2-4 kanji><1-3 digits><name>", strip
        # the rep-name + row-number prefix. The digits indicate this is
        # the previous row's rep tail bleeding in.
        m_rep = re.match(r"^([一-鿿]{2,4})([\dー－‐\-]{1,3})", head)
        if m_rep:
            head = head[m_rep.end() :]
        # Drop column-header tokens if present.
        for header_token in (
            "事業者の氏名又は名称及び主たる事務所の位置",
            "事業者の氏名又は名称",
            "事業者の氏名",
            "事業者名",
            "氏名又は名称",
        ):
            pos = head.find(header_token)
            if pos >= 0:
                head = head[pos + len(header_token) :].strip()
        # Trim leading punctuation.
        target_name = head.lstrip("（()【】 　,、")
        # If "代表者" appears, cut it.
        for stop in ("代表者", "代 表 者", "代表"):
            pos = target_name.find(stop)
            if pos > 0:
                target_name = target_name[:pos].strip()
                break

        if not target_name or len(target_name) < 2 or len(target_name) > 120:
            continue
        if target_name[0] in ("、", "及", "監", "公", "○", "・", "※", " "):
            continue
        if "監査" in target_name or "違反" in target_name or "認められ" in target_name:
            continue
        if re.fullmatch(r"\d+", target_name):
            continue

        records.append(
            UnyuRecord(
                region=region,
                region_label=region_label,
                issuance_date=date_iso,
                target_name=target_name,
                houjin_bangou=houjin,
                address=None,
                office_name=None,
                office_address=None,
                punishment_raw=punish_raw,
                enforcement_kind=kind,
                related_law_ref=law_ref,
                reason_summary=summary,
                source_url=pdf_url,
                source_hub_url=hub_url,
            )
        )

    return records


def parse_pdf_records(
    pdf_bytes: bytes,
    *,
    region: str,
    region_label: str,
    pdf_url: str,
    hub_url: str,
) -> list[UnyuRecord]:
    """Extract individual enforcement records from a 運輸局 monthly PDF.

    Strategy: extract text, split into row-blocks at date markers
    (8-digit / 令和N年 / RN.M.D / 平成N年). Then within each block, pull
    the 法人番号 and 内容 / 違反条項 / 概要 by sequence.
    """
    import io

    try:
        text = extract_text(io.BytesIO(pdf_bytes))
    except Exception as exc:
        _LOG.warning("pdf parse failed url=%s err=%s", pdf_url, exc)
        return []
    if not text or len(text) < 200:
        return []

    # Replace full-width spaces with regular spaces for matching.
    text = text.replace("　", " ")

    # Find all date markers with positions.
    raw_matches = list(DATE_ANY_RE.finditer(text))
    if len(raw_matches) < 1:
        return []

    # Filter: only keep date markers that are real "row starts", i.e.
    # followed within ~280 chars by a 法人番号 (which is the universal
    # event-row signature). This eliminates dates embedded inside
    # reason-summary prose where 法人番号 isn't nearby. Reject also
    # any match whose immediate next char is 、 (prose continuation).
    #
    # Exception (form-style fallback): if there are <=3 date markers
    # total AND the document mentions 法人番号 once, treat as a single
    # form (older Kanto / OGB style: one PDF == one record). Pick the
    # date that has the smallest distance to 法人番号.
    matches: list[re.Match[str]] = []
    houjin_matches_all = list(HOUJIN_DIGIT_RE.finditer(text))
    houjin_positions = [m.start() for m in houjin_matches_all]
    has_houjin = bool(houjin_positions)

    if not has_houjin:
        return []

    if len(raw_matches) <= 3 and has_houjin:
        # form-style. Find the date closest to (but BEFORE) the first
        # 法人番号 — that's the issuance date.
        first_h = houjin_positions[0]
        candidates = [m for m in raw_matches if m.start() < first_h]
        if candidates:
            matches = [max(candidates, key=lambda m: m.start())]
        else:
            matches = raw_matches[:1]
    else:
        for m in raw_matches:
            after = text[m.end() : m.end() + 1]
            if after in ("、", "及"):
                continue
            window = text[m.end() : m.end() + 280]
            if HOUJIN_DIGIT_RE.search(window):
                matches.append(m)

    # Column-flow fallback (e.g. Hokkaido kamotu PDFs): the PDF text places
    # all date+address+punishment columns first, and all 事業者名+法人番号
    # in a separate trailing column block. In that layout, no row-start
    # date has 法人番号 within 280 chars, but the document overall has
    # several distinct houjins. Pair row-start dates with houjins by
    # sequence index.
    if (not matches) or len(matches) < max(2, len(houjin_positions) // 2):
        # Identify "row-start dates" robustly: dates where the next char is
        # NOT 、 (prose continuation) and NOT 及 (range continuation), and
        # which are followed by a punishment keyword within 250 chars.
        row_dates = []
        for m in raw_matches:
            after = text[m.end() : m.end() + 1]
            if after in ("、", "及"):
                continue
            window = text[m.end() : m.end() + 250]
            if any(
                kw in window
                for kw in (
                    "輸送施設の使用停止",
                    "事業停止",
                    "業務停止",
                    "車両使用停止",
                    "自動車使用停止",
                    "輸送施設の停止",
                    "許可取消",
                    "登録取消",
                    "文書警告",
                    "文書勧告",
                    "口頭注意",
                    "勧告",
                    "警告",
                )
            ):
                row_dates.append(m)
        # Only switch to column-flow if dates and houjins counts are
        # comparable (within 2x).
        if (
            len(row_dates) >= 2
            and len(houjin_matches_all) >= 2
            and max(len(row_dates), len(houjin_matches_all))
            <= 3 * min(len(row_dates), len(houjin_matches_all))
            and len(row_dates) > len(matches)
        ):
            return _parse_column_flow(
                text=text,
                row_dates=row_dates,
                houjin_matches=houjin_matches_all,
                region=region,
                region_label=region_label,
                pdf_url=pdf_url,
                hub_url=hub_url,
            )

    if not matches:
        return []

    records: list[UnyuRecord] = []
    for i, m in enumerate(matches):
        end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block_start = m.start()
        block = text[block_start : min(end_pos, block_start + 2500)]

        # Normalize: strip internal whitespace from date token
        dt_token = re.sub(r"\s+", "", m.group("dt"))
        date_iso = normalize_date(dt_token)
        if not date_iso:
            continue

        # Skip blocks where the date is wildly old (defensive).
        try:
            year = int(date_iso[:4])
            if year < 2018 or year > 2027:
                continue
        except ValueError:
            continue

        # Target name + 法人番号 — usually appears within first 300 chars.
        target_name = None
        houjin = None

        hm = HOUJIN_DIGIT_RE.search(block)
        if hm:
            houjin = _normalize_houjin_block(hm.group(1))
            # target_name = text just before "法人番号"
            head = block[: hm.start()]
            # Drop the date itself and any column header noise.
            # Use the matched length from the regex group span.
            date_match_len = m.end() - m.start()
            head = head[date_match_len:]
            # Strip newlines/whitespace.
            target_name = re.sub(r"\s+", " ", head).strip()
            # Trim leading parens or punctuation
            target_name = target_name.strip("（()【】 　,、")
            # Form-style PDFs interleave the column header with the value:
            # e.g. "(2)事業者の氏名又は名称 京成バスシステム株式会社". Trim
            # everything up to and including the column header words.
            for header_token in (
                "事業者の氏名又は名称及び主たる事務所の位置",
                "事業者の氏名又は名称及び主たる 事務所の位置",
                "事業者の氏名又は名称",
                "事業者の氏名",
                "事業者の名称",
                "事業者名",
                "氏名又は名称",
                "及び主たる 事務所の位置",
                "及び主たる事務所の位置",
                "事務所の位置",
            ):
                pos = target_name.find(header_token)
                if pos >= 0:
                    target_name = target_name[pos + len(header_token) :].strip()
                    break
            # Some Hokushin/Chubu rows have "代表者" suffix — strip it.
            for stop in ("代表者", "代 表 者", "代表"):
                pos = target_name.find(stop)
                if pos > 0:
                    target_name = target_name[:pos].strip()
                    break
            # Final cleanup: drop 株式会社 / 有限会社 dangling
            if target_name.endswith(("（", "(")):
                target_name = target_name[:-1].strip()
        else:
            # No 法人番号; take first 120 chars after date as name.
            date_match_len = m.end() - m.start()
            head = block[date_match_len:][:120]
            target_name = re.sub(r"\s+", " ", head).strip()
            # Heuristic: cut at 「事業者」「営業所」「代表」
            for stop in ("代表者", "代 表 者", "代表", "事業者の所在地", "事業者所在地"):
                pos = target_name.find(stop)
                if pos > 0:
                    target_name = target_name[:pos].strip()
                    break

        if not target_name or len(target_name) < 2 or len(target_name) > 120:
            continue
        # Skip header rows / boilerplate
        if target_name in ("事業者の氏名又は名称", "事業者の氏名又は名称及び主たる事務所の位置"):
            continue
        if any(
            noise in target_name
            for noise in ("行政処分等の年月日", "事業者の氏名", "営業所の名称", "違反行為の概要")
        ):
            continue
        # Reason-summary leakage: prose paragraphs start with 、 , 及び ,
        # 監査 , 公安 etc. Real 事業者名 starts with 株式会社 / 有限会社 /
        # 合同会社 / kanji or 法人.
        if target_name[0] in ("、", "及", "監", "公", "（", "(", "○", "・", "※", "・", " "):
            continue
        if target_name.startswith(
            ("(1)", "(2)", "（１）", "（２）", "により", "公安", "労働", "行政")
        ):
            continue
        # Reject prose continuations: too many parens or contains 「監査」
        if "監査" in target_name or "違反" in target_name or "認められ" in target_name:
            continue

        # Punishment extraction — search in whole block (not just header).
        punish_raw, kind = map_punishment(block)
        if not punish_raw or not kind:
            continue

        # Law ref + reason summary.
        law_ref = extract_law_ref(block)
        # Reason summary: prefer text after "違反行為の概要" or "監査"
        summary = None
        for marker in ("違反行為の概要", "監査実施の端緒", "監査を実施"):
            pos = block.find(marker)
            if pos >= 0:
                # Prefer the last occurrence of '令和' (which is the start of
                # the prose) and capture up to ~600 chars.
                tail = block[pos : pos + 700]
                tail = re.sub(r"\s+", " ", tail).strip()
                summary = tail[:600]
                break

        # Heuristic: drop near-empty hits where target_name is just a number.
        if re.fullmatch(r"\d+", target_name):
            continue

        records.append(
            UnyuRecord(
                region=region,
                region_label=region_label,
                issuance_date=date_iso,
                target_name=target_name,
                houjin_bangou=houjin,
                address=None,
                office_name=None,
                office_address=None,
                punishment_raw=punish_raw,
                enforcement_kind=kind,
                related_law_ref=law_ref,
                reason_summary=summary,
                source_url=pdf_url,
                source_hub_url=hub_url,
            )
        )

    return records


# ---------------------------------------------------------------------------
# Hub crawl
# ---------------------------------------------------------------------------


PDF_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+\.pdf)["\']', re.IGNORECASE)
ANY_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def absolute_url(base: str, ref: str) -> str:
    return urllib.parse.urljoin(base, ref)


def collect_pdfs_for_region(
    http: UnyuHttpClient,
    region_code: str,
    info: dict,
) -> list[tuple[str, str]]:
    """Return [(pdf_url, hub_url)] for the region. Walks hubs.

    For Kyushu (drill_in=True), hubs aggregate yearly subpages — we walk
    those to harvest PDFs.
    """
    pdf_pairs: list[tuple[str, str]] = []
    seen_pdfs: set[str] = set()

    for hub_url in info["hubs"]:
        status, html = http.get_text(hub_url, info["encoding"])
        if status != 200 or not html:
            _LOG.warning(
                "hub fetch failed region=%s url=%s status=%s", region_code, hub_url, status
            )
            continue
        # Extract direct PDFs.
        for href in PDF_HREF_RE.findall(html):
            absu = absolute_url(hub_url, href)
            if absu in seen_pdfs:
                continue
            seen_pdfs.add(absu)
            pdf_pairs.append((absu, hub_url))
        if not info.get("drill_in"):
            continue
        # Drill into subpages: any href with /jigyousya/.../*.htm or
        # /unyu/gyousei/*.html
        for href in ANY_HREF_RE.findall(html):
            if href.endswith((".htm", ".html")) and any(
                kw in href.lower()
                for kw in (
                    "noriai",
                    "kasikiri",
                    "kashikiri",
                    "jyouyou",
                    "jouyou",
                    "kamotu",
                    "kamotsu",
                    "kasekisai",
                    "track",
                )
            ):
                sub_url = absolute_url(hub_url, href)
                status2, html2 = http.get_text(sub_url, info["encoding"])
                if status2 != 200:
                    continue
                for href2 in PDF_HREF_RE.findall(html2):
                    absu = absolute_url(sub_url, href2)
                    if absu in seen_pdfs:
                        continue
                    seen_pdfs.add(absu)
                    pdf_pairs.append((absu, sub_url))
    return pdf_pairs


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
        "SELECT IFNULL(issuing_authority, ''), issuance_date, IFNULL(target_name, ''), IFNULL(enforcement_kind, '') "
        "FROM am_enforcement_detail"
    ):
        keys.add((r[0], r[1], r[2], r[3]))
    return keys


def make_canonical_id(rec: UnyuRecord, seq: int) -> str:
    # AM-ENF-MLIT-UNYU-{region}-{seq}
    return f"AM-ENF-MLIT-UNYU-{rec.region}-{seq:06d}"


def next_seq(conn: sqlite3.Connection, region: str) -> int:
    """Return the next sequence number for a region."""
    row = conn.execute(
        """SELECT MAX(CAST(SUBSTR(canonical_id, LENGTH(?) + 1) AS INTEGER))
           FROM am_entities
           WHERE canonical_id LIKE ? || '%'""",
        (
            f"AM-ENF-MLIT-UNYU-{region}-",
            f"AM-ENF-MLIT-UNYU-{region}-",
        ),
    ).fetchone()
    if row and row[0]:
        return int(row[0]) + 1
    return 1


def upsert_record(
    conn: sqlite3.Connection,
    rec: UnyuRecord,
    canonical_id: str,
    fetched_at: str,
) -> str:
    raw_json = {
        "region": rec.region,
        "region_label": rec.region_label,
        "target_name": rec.target_name,
        "houjin_bangou": rec.houjin_bangou,
        "address": rec.address,
        "office_name": rec.office_name,
        "office_address": rec.office_address,
        "issuance_date": rec.issuance_date,
        "punishment_raw": rec.punishment_raw,
        "enforcement_kind": rec.enforcement_kind,
        "related_law_ref": rec.related_law_ref,
        "reason_summary": rec.reason_summary,
        "source_url": rec.source_url,
        "source_hub_url": rec.source_hub_url,
        "fetched_at": fetched_at,
        "source": "mlit_unyu_pdf",
    }
    domain = urllib.parse.urlparse(rec.source_url).netloc

    cur = conn.execute(
        """INSERT OR IGNORE INTO am_entities (
            canonical_id, record_kind, source_topic, primary_name,
            confidence, source_url, source_url_domain, fetched_at, raw_json
        ) VALUES (?, 'enforcement', ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            f"mlit_unyu_{rec.region}",
            rec.target_name,
            0.9,
            rec.source_url,
            domain,
            fetched_at,
            json.dumps(raw_json, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    if cur.rowcount == 0:
        return "skip"

    conn.execute(
        """INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, reason_summary,
            related_law_ref, source_url, source_fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            rec.houjin_bangou,
            rec.target_name,
            rec.enforcement_kind,
            rec.region_label,
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
        "--regions",
        type=str,
        default=",".join(REGION_HUBS.keys()),
        help="comma-separated region codes",
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="stop after this many INSERTs (across all regions)"
    )
    ap.add_argument(
        "--per-region-pdf-limit",
        type=int,
        default=None,
        help="cap PDFs walked per region (smoke tests)",
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

    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    unknown = [r for r in regions if r not in REGION_HUBS]
    if unknown:
        _LOG.error("unknown regions: %s (allowed: %s)", unknown, list(REGION_HUBS))
        return 2

    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    http = UnyuHttpClient()
    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        conn = open_db(args.db)
        conn.execute("BEGIN IMMEDIATE")
        existing_keys = load_existing_keys(conn)
        _LOG.info("existing am_enforcement_detail keys=%d", len(existing_keys))
    else:
        existing_keys = set()

    stats: dict[str, dict[str, int]] = {}
    total_inserts = 0
    law_breakdown: dict[str, int] = {}

    try:
        for region_code in regions:
            info = REGION_HUBS[region_code]
            region_label = info["label"]
            cs = {
                "pdfs_seen": 0,
                "pdfs_fetched": 0,
                "records_extracted": 0,
                "insert": 0,
                "skip_dup": 0,
                "skip_existing": 0,
            }
            stats[region_code] = cs

            _LOG.info("region=%s label=%s walking hubs...", region_code, region_label)
            pdf_pairs = collect_pdfs_for_region(http, region_code, info)
            cs["pdfs_seen"] = len(pdf_pairs)
            _LOG.info("region=%s pdfs_seen=%d", region_code, len(pdf_pairs))

            if args.per_region_pdf_limit is not None:
                pdf_pairs = pdf_pairs[: args.per_region_pdf_limit]

            # Sort by URL desc so newest months come first (heuristic —
            # newer files usually have larger numeric IDs).
            pdf_pairs.sort(key=lambda p: p[0], reverse=True)

            seq_counter = next_seq(conn, region_code) if conn is not None else 1

            stop_region = False
            for pdf_url, hub_url in pdf_pairs:
                if args.limit is not None and total_inserts >= args.limit:
                    stop_region = True
                    break
                status, body = http.get_bytes(pdf_url)
                if status != 200 or not body:
                    continue
                cs["pdfs_fetched"] += 1
                recs = parse_pdf_records(
                    body,
                    region=region_code,
                    region_label=region_label,
                    pdf_url=pdf_url,
                    hub_url=hub_url,
                )
                cs["records_extracted"] += len(recs)
                _LOG.debug("pdf=%s extracted=%d", pdf_url, len(recs))
                for r in recs:
                    key = (r.region_label, r.issuance_date, r.target_name, r.enforcement_kind)
                    if key in existing_keys:
                        cs["skip_existing"] += 1
                        continue
                    existing_keys.add(key)
                    if args.dry_run or conn is None:
                        cs["insert"] += 1
                        total_inserts += 1
                        if r.related_law_ref:
                            law_breakdown[r.related_law_ref] = (
                                law_breakdown.get(r.related_law_ref, 0) + 1
                            )
                        if cs["insert"] <= 3:
                            _LOG.info(
                                "DRY %s | %s | %s | houjin=%s | %s | %s | law=%s",
                                region_code,
                                r.issuance_date,
                                r.target_name,
                                r.houjin_bangou,
                                r.punishment_raw,
                                r.enforcement_kind,
                                r.related_law_ref,
                            )
                        continue
                    canonical_id = f"AM-ENF-MLIT-UNYU-{region_code}-{seq_counter:06d}"
                    seq_counter += 1
                    try:
                        verdict = upsert_record(conn, r, canonical_id, fetched_at)
                    except sqlite3.Error as exc:
                        _LOG.warning("DB insert err name=%s err=%s", r.target_name, exc)
                        continue
                    if verdict == "insert":
                        cs["insert"] += 1
                        total_inserts += 1
                        if r.related_law_ref:
                            law_breakdown[r.related_law_ref] = (
                                law_breakdown.get(r.related_law_ref, 0) + 1
                            )
                    else:
                        cs["skip_dup"] += 1
                    if total_inserts > 0 and total_inserts % 50 == 0:
                        conn.commit()
                        conn.execute("BEGIN IMMEDIATE")
                    if args.limit is not None and total_inserts >= args.limit:
                        stop_region = True
                        break
                if stop_region:
                    break
            _LOG.info("region=%s done: %s", region_code, cs)
            if args.limit is not None and total_inserts >= args.limit:
                break

    finally:
        http.close()
        if conn is not None:
            conn.commit()
            conn.close()

    _LOG.info("SUMMARY total_inserts=%d", total_inserts)
    _LOG.info("PER REGION: %s", json.dumps(stats, ensure_ascii=False))
    _LOG.info("PER LAW: %s", json.dumps(law_breakdown, ensure_ascii=False))

    if args.log_file is not None:
        with open(args.log_file, "a") as f:
            f.write(
                f"\n## {fetched_at} MLIT 運輸局 enforcement ingest\n"
                f"  regions={regions} limit={args.limit}\n"
                f"  total_inserts={total_inserts}\n"
                f"  per_region={json.dumps(stats, ensure_ascii=False)}\n"
                f"  per_law={json.dumps(law_breakdown, ensure_ascii=False)}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
