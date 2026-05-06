#!/usr/bin/env python3
"""Ingest 海難審判所 (Maritime Accident Tribunal) 裁決 records into
``am_enforcement_detail``.

Scope (2026-04-25):
    The 海難審判所 publishes ruling PDFs (裁決) that impose
    administrative discipline on individual mariners (海技士 /
    小型船舶操縦士) under 海難審判法第4条 and the
    船舶職員及び小型船舶操縦者法. This complements
    ``ingest_enforcement_mlit_maritime.py`` which targets
    法人船舶所有者 (corporate ship owners) under 船員法 / 海上運送法.

    The two surfaces do not overlap: this script captures the
    individual-license axis (anonymized受審人 a/b/c labels), while
    ``mlit_maritime`` captures the corporate axis (法人 names + 法人番号).

Hubs walked:

    * 海難審判所 (本所 / Tokyo)         /jmat/saiketsu/saiketsu_kako/tokyou/saiketsu.htm
    * 函館地方海難審判所 (Hakodate)    /jmat/saiketsu/saiketsu_kako/R0Xnen/1hd/hdR0Xsaiketsu.htm
    * 仙台地方海難審判所 (Sendai)      /jmat/saiketsu/saiketsu_kako/R0Xnen/2sd/sdR0Xsaiketsu.htm
    * 横浜地方海難審判所 (Yokohama)    /jmat/saiketsu/saiketsu_kako/R0Xnen/3yh/yhR0Xsaiketsu.htm
    * 神戸地方海難審判所 (Kobe)        /jmat/saiketsu/saiketsu_kako/R0Xnen/4kb/kbR0Xsaiketsu.htm
    * 広島地方海難審判所 (Hiroshima)   /jmat/saiketsu/saiketsu_kako/R0Xnen/5hs/hsR0Xsaiketsu.htm
    * 門司地方海難審判所 (Moji)        /jmat/saiketsu/saiketsu_kako/R0Xnen/6mj/mjR0Xsaiketsu.htm
    * 長崎地方海難審判所 (Nagasaki)    /jmat/saiketsu/saiketsu_kako/R0Xnen/7ns/nsR0Xsaiketsu.htm
    * 那覇支所 (門司)                  /jmat/saiketsu/saiketsu_kako/R0Xnen/8nh/nhR0Xsaiketsu.htm

PDF format (per /jmat/saiketsu/...):

    令和X年{region}審第NN号
                          裁        決
    {船種A}{船種B}衝突事件

        受    審    人    a
            職    名  A船長
            操縦免許  小型船舶操縦士

      本件について、…審理し、次のとおり裁決する。

                          主        文

      受審人aを戒告する。       (戒告 → other)
      受審人aの小型船舶操縦士の業務を1か月停止する。  (停止 → business_improvement)
      受審人aの海技免許を取り消す。   (取消 → license_revoke)
      受審人aを懲戒しない。     (skip — no enforcement)

                          理        由
    ...

      令和X年M月D日
          {region}地方海難審判所
                審 判 官    …

Schema mapping:

    enforcement_kind:
        免許取消 / 海技免許を取消 / 操縦免許を取消        → license_revoke
        業務を{N}か月停止 / 業務停止                       → business_improvement
        戒告                                                → other
        懲戒しない (no discipline)                          → skipped

    target_name (anonymized): "{職名 || 受審人} 海技士/小型船舶操縦士 #{seq:03d} (氏名非公表)"
                              受審人 a/b/c labels are already anonymized by tribunal.
                              We add a global sequence number per region.

    issuing_authority:        "{region}地方海難審判所" or "海難審判所"
    issuance_date:            裁決言渡日 (ISO yyyy-mm-dd)
    related_law_ref:          "海難審判法第4条" + suffix (船員法 / 船舶職員及び小型船舶操縦者法)
    reason_summary:           主文 + 事件名 + 事件発生日 + 事件発生場所
    source_url:               PDF URL (mlit.go.jp/jmat/saiketsu/...)

Idempotency:
    Dedup on (issuing_authority, issuance_date, target_name,
    enforcement_kind) via existing am_enforcement_detail scan.
    canonical_id pattern AM-ENF-KAIGI-{region}-{seq:06d} prevents
    am_entities collision under INSERT OR IGNORE.

Per-write transaction:
    BEGIN IMMEDIATE + busy_timeout=300000 + 50-row periodic commit so
    parallel writers can interleave.

CLI:
    python scripts/ingest/ingest_enforcement_kaiho_kaigi.py \
        --db autonomath.db [--regions tokyou,3yh,4kb,...] \
        [--limit 500] [--years R07,R08] [--dry-run]
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


_LOG = logging.getLogger("autonomath.ingest.enforcement_kaiho_kaigi")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = "jpintel-mcp-ingest/1.0 (+https://jpcite.com; contact=ops@jpcite.com)"
PER_REQUEST_DELAY_SEC = 0.5
HTTP_TIMEOUT_SEC = 60.0
MAX_RETRIES = 3

BASE = "https://www.mlit.go.jp"


# ---------------------------------------------------------------------------
# Hub config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Hub:
    region_code: str  # 1hd / 2sd / 3yh / 4kb / 5hs / 6mj / 7ns / 8nh / tokyou
    region_label: str  # 函館地方海難審判所 etc
    prefix: str  # PDF file prefix: hd / sd / yh / kb / hs / mj / ns / nh / tk


REGIONAL_HUBS: list[Hub] = [
    Hub("1hd", "函館地方海難審判所", "hd"),
    Hub("2sd", "仙台地方海難審判所", "sd"),
    Hub("3yh", "横浜地方海難審判所", "yh"),
    Hub("4kb", "神戸地方海難審判所", "kb"),
    Hub("5hs", "広島地方海難審判所", "hs"),
    Hub("6mj", "門司地方海難審判所", "mj"),
    Hub("7ns", "長崎地方海難審判所", "ns"),
    Hub("8nh", "門司地方海難審判所那覇支所", "nh"),
]
TOKYO_HUB = Hub("tokyou", "海難審判所", "tk")

DEFAULT_YEARS = ["R07", "R08"]  # the 2-year live archive window


# ---------------------------------------------------------------------------
# Disposition / law mapping
# ---------------------------------------------------------------------------

# Order matters — most specific first. Patterns are matched against the
# disposition sentence after digits/whitespace are normalized.
DISPOSITION_PATTERNS: list[tuple[str, str]] = [
    ("海技免許を取り消す", "license_revoke"),
    ("海技免状を取り消す", "license_revoke"),
    ("操縦免許を取り消す", "license_revoke"),
    ("免許を取り消す", "license_revoke"),
    ("免許の取消", "license_revoke"),
    ("業務停止", "business_improvement"),  # 業務を{N}か月停止 → matches after digit strip
    ("業務の停止", "business_improvement"),
    ("業務を停止", "business_improvement"),
    ("を戒告する", "other"),
    ("戒告する", "other"),
    ("戒告", "other"),
]


def _strip_digits_and_punct(s: str) -> str:
    """Strip digits + punctuation so '業務を１か月停止' folds to '業務をか月停止'.
    Used as a second matching layer for time-bounded suspensions."""
    out: list[str] = []
    for ch in s:
        if ch.isdigit() or "０" <= ch <= "９" or ch in "、。, ":
            continue
        out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Date helpers (Reiwa / Heisei)
# ---------------------------------------------------------------------------

DATE_REIWA_RE = re.compile(r"令和\s*([０-９\d元]+)\s*年\s*([０-９\d]+)\s*月\s*([０-９\d]+)\s*日")
DATE_HEISEI_RE = re.compile(r"平成\s*([０-９\d元]+)\s*年\s*([０-９\d]+)\s*月\s*([０-９\d]+)\s*日")


def _to_halfwidth_int(s: str) -> int:
    if "元" in s:
        return 1
    out: list[str] = []
    for ch in s:
        if "０" <= ch <= "９":
            out.append(chr(ord("0") + (ord(ch) - 0xFF10)))
        elif ch.isdigit():
            out.append(ch)
    return int("".join(out)) if out else 0


def parse_any_date_iso(token: str) -> str | None:
    token = token.strip()
    m = DATE_REIWA_RE.search(token)
    if m:
        try:
            y = 2018 + _to_halfwidth_int(m.group(1))
            return dt.date(
                y, _to_halfwidth_int(m.group(2)), _to_halfwidth_int(m.group(3))
            ).isoformat()
        except ValueError:
            return None
    m = DATE_HEISEI_RE.search(token)
    if m:
        try:
            y = 1988 + _to_halfwidth_int(m.group(1))
            return dt.date(
                y, _to_halfwidth_int(m.group(2)), _to_halfwidth_int(m.group(3))
            ).isoformat()
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class TribunalRecord:
    region_code: str
    issuing_authority: str
    issuance_date: str
    target_label: str  # anonymized: "{職名} {免許種別}"
    license_type: str  # "海技士" / "小型船舶操縦士"
    enforcement_kind: str  # license_revoke / business_improvement / other
    disposition_text: str  # main 主文 line for this 受審人
    case_title: str  # ヨットＡ岸壁衝突事件 etc
    incident_date: str | None  # 事件発生年月日
    incident_place: str | None  # 事件発生場所
    related_law_ref: str
    source_url: str
    source_hub_url: str


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class HttpClient:
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

    def get_text(self, url: str) -> tuple[int, str]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.get(url)
                if r.status_code == 200:
                    raw = r.content
                    for enc in ("utf-8", "shift_jis", "cp932"):
                        try:
                            return r.status_code, raw.decode(enc, errors="strict")
                        except UnicodeDecodeError:
                            continue
                    return r.status_code, raw.decode("utf-8", errors="replace")
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
# Regional index page → list of (pdf_url, hub_url)
# ---------------------------------------------------------------------------

PDF_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+\.pdf)["\']', re.IGNORECASE)


def collect_pdfs_for_regional_hub(http: HttpClient, hub: Hub, year: str) -> list[tuple[str, str]]:
    """Year is like ``R07``/``R08`` (zero-padded). Return [(pdf_url, hub_url)]."""
    if hub.region_code == "tokyou":
        # Single-page archive irrespective of year argument.
        hub_url = f"{BASE}/jmat/saiketsu/saiketsu_kako/tokyou/saiketsu.htm"
    else:
        hub_url = (
            f"{BASE}/jmat/saiketsu/saiketsu_kako/"
            f"{year}nen/{hub.region_code}/{hub.prefix}{year}saiketsu.htm"
        )
    status, html = http.get_text(hub_url)
    if status != 200 or not html:
        _LOG.warning("hub fetch failed url=%s status=%s", hub_url, status)
        return []
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href in PDF_HREF_RE.findall(html):
        # Skip "hp" reference-diagram PDFs (they are figures, not rulings).
        if "hp.pdf" in href.lower():
            continue
        absu = urllib.parse.urljoin(hub_url, href.strip())
        if absu in seen:
            continue
        seen.add(absu)
        out.append((absu, hub_url))
    return out


# ---------------------------------------------------------------------------
# Tokyo (central) hub: traverses its own old-year archives
# ---------------------------------------------------------------------------


def collect_pdfs_for_tokyo(http: HttpClient) -> list[tuple[str, str]]:
    """The Tokyo central tribunal saiketsu.htm lists PDFs from R02..R08
    inline, no year drill needed."""
    return collect_pdfs_for_regional_hub(http, TOKYO_HUB, year="R08")


# ---------------------------------------------------------------------------
# PDF text parsing
# ---------------------------------------------------------------------------

# Marker boundary helpers
SHUBUN_RE = re.compile(r"主\s*文")
RIYU_RE = re.compile(r"理\s*由")

# Per-defendant disposition lines after 主文. Each typically begins with
# "受審人{a/b/...}" and ends with "する。" / "停止する。" / "懲戒しない。".
DEFENDANT_LINE_RE = re.compile(
    r"受\s*審\s*人\s*([ａ-ｚa-z0-9０-９１２]{1,4})\s*"
    r"([^。\n]*?[。．])"
)

# 受審人 block in heading: 受 審 人 a / 職 名 X船長 / (海技|操縦)免許 …
DEFENDANT_HEAD_RE = re.compile(
    r"受\s*審\s*人\s*([ａ-ｚa-z0-9０-９１２]{1,4})\s*"
    r".*?職\s*名\s*([^\n]+?)\s*"
    r"(?:海\s*技\s*免\s*許|操\s*縦\s*免\s*許)\s*([^\n]+)",
    re.DOTALL,
)

# Generic "受審人X" + "職名Y" + (海技|操縦)免許 (less greedy fallback)
DEFENDANT_HEAD_LOOSE_RE = re.compile(r"受\s*審\s*人\s*([ａ-ｚa-z0-9０-９１２]{1,4})")

# 事件発生 block extractor
INCIDENT_DATE_RE = re.compile(
    r"事件発生の?年月日(?:時刻)?(?:及び場所)?\s*\n+\s*"
    r"(令和[０-９\d元]+年[０-９\d]+月[０-９\d]+日"
    r"|平成[０-９\d元]+年[０-９\d]+月[０-９\d]+日)"
)
# Place line: usually next non-empty line after the date inside the
# "事件発生" block.
INCIDENT_PLACE_RE = re.compile(
    r"(令和[０-９\d元]+年[０-９\d]+月[０-９\d]+日"
    r"|平成[０-９\d元]+年[０-９\d]+月[０-９\d]+日)"
    r"[^\n]*\n+\s*([^\n]{2,80})"
)

# 案件タイトル (just below 裁決 marker)
CASE_TITLE_RE = re.compile(r"裁\s*決\s*\n+\s*(?:（[第１２一二]）)?\s*([^\n]{3,80}事件)")

# Top-of-doc 言渡日 marker (used as fallback if we cannot read it from
# the index page). Format: 令和X年M月D日 followed by tribunal name.
ISSUE_DATE_RE = re.compile(
    r"(令和[０-９\d元]+年[０-９\d]+月[０-９\d]+日)\s*\n+\s*"
    r"([^\n]*海難審判所[^\n]*)"
)

# Case number at top: "令和7年横審第25号"
CASE_NO_RE = re.compile(r"令和\s*([０-９\d元]+)\s*年\s*([^第\n]+第\s*[０-９\d]+\s*号)")


def _strip_all_ws(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _norm_label(s: str) -> str:
    return _strip_all_ws(s).replace("（", "(").replace("）", ")")


def classify_disposition(line: str) -> str | None:
    """Map the single 受審人 disposition sentence to enforcement_kind.
    Returns None when the line says the defendant is not disciplined."""
    norm = _strip_all_ws(line)
    if "懲戒しない" in norm:
        return None
    # 取消 / 取り消す anywhere → license_revoke (most severe; check first).
    if (
        "免許を取り消す" in norm
        or "免許の取消" in norm
        or "免状を取り消す" in norm
        or "免許を取消す" in norm
        or "免状の取消" in norm
    ):
        return "license_revoke"
    # 停止 anywhere following 業務 (with optional period digits) →
    # business_improvement. Catches "業務を停止" / "業務を１か月停止" /
    # "業務を２年停止".
    if "停止" in norm and "業務" in norm:
        return "business_improvement"
    # 戒告 → other (least severe).
    if "戒告" in norm:
        return "other"
    return None


def extract_shubun_block(text: str) -> str | None:
    """Return the slice between 主文 and 理由."""
    sm = SHUBUN_RE.search(text)
    if not sm:
        return None
    rm = RIYU_RE.search(text, sm.end())
    if not rm:
        return text[sm.end() : sm.end() + 800]
    return text[sm.end() : rm.start()]


def extract_defendants_heading(text: str) -> dict[str, dict[str, str]]:
    """Map each defendant letter (a / b / a1 / b2) → {role:..., license:...}.

    The PDF 受審人ヘッダ section appears between 裁決言渡日や事件タイトル
    and the 主文 marker. Walk all "受審人X" markers in that prefix region
    and capture the next "職名" + "海技免許/操縦免許" lines.
    """
    cap: dict[str, dict[str, str]] = {}
    sm = SHUBUN_RE.search(text)
    head = text[: sm.start()] if sm else text[:3000]

    # Each block looks like:
    #   受 審 人 a
    #       職 名 A船長
    #       操縦免許 小型船舶操縦士
    blocks = re.split(r"受\s*審\s*人\s*", head)
    for blk in blocks[1:]:
        m_letter = re.match(r"([ａ-ｚa-z0-9０-９１２]{1,4})", blk)
        if not m_letter:
            continue
        letter = _strip_all_ws(m_letter.group(1)).lower()
        # Normalize fullwidth letters to halfwidth for mapping.
        letter = letter.translate(
            str.maketrans(
                "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
                "abcdefghijklmnopqrstuvwxyz",
            )
        ).translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        # Look for 職名 within first 200 chars
        m_job = re.search(r"職\s*名\s*([^\n]+)", blk[:400])
        m_lic = re.search(r"(海\s*技\s*免\s*許|操\s*縦\s*免\s*許)\s*([^\n]+)", blk[:600])
        if not m_job or not m_lic:
            continue
        job = _norm_label(m_job.group(1)).strip()
        lic_kind = _norm_label(m_lic.group(1))  # 海技免許 / 操縦免許
        lic_text = _norm_label(m_lic.group(2)).strip()
        # Trim trailing job noise like "海技免許" leakage if regex was greedy
        for stop in ("海技免許", "操縦免許", "補佐人"):
            i = job.find(stop)
            if i > 0:
                job = job[:i]
        # license_type bucket
        if "海技免許" in lic_kind or "海技士" in lic_text:
            license_type = "海技士"
        elif "操縦免許" in lic_kind or "小型船舶操縦士" in lic_text:
            license_type = "小型船舶操縦士"
        else:
            license_type = "海技士"  # safe default
        cap[letter] = {
            "job": job,
            "license_kind": lic_kind,
            "license_text": lic_text,
            "license_type": license_type,
        }
    return cap


def extract_case_title(text: str) -> str | None:
    m = CASE_TITLE_RE.search(text)
    if not m:
        return None
    title = _norm_label(m.group(1))
    return title[:100]


def extract_incident_date_place(text: str) -> tuple[str | None, str | None]:
    iso_date: str | None = None
    place: str | None = None
    md = INCIDENT_DATE_RE.search(text)
    if md:
        iso_date = parse_any_date_iso(md.group(1))
    mp = INCIDENT_PLACE_RE.search(text)
    if mp:
        place = _norm_label(mp.group(2))
        # Strip noisy trailing words
        for stop in ("船舶の要目", "船 種", "船種", "事実の経過"):
            i = place.find(stop)
            if i > 0:
                place = place[:i]
        place = place.strip(" 　、,。")
        if not place or len(place) < 2:
            place = None
    return iso_date, place


def extract_issue_date(text: str, default: str | None = None) -> str | None:
    """Use the bottom-of-doc 裁決言渡日 if present; else default (from index)."""
    # Search from the back since the issue date appears after the 主文.
    for m in ISSUE_DATE_RE.finditer(text):
        d = parse_any_date_iso(m.group(1))
        if d:
            return d
    return default


def parse_ruling_pdf(
    pdf_bytes: bytes,
    *,
    hub: Hub,
    pdf_url: str,
    hub_url: str,
    fallback_issue_date: str | None,
) -> list[TribunalRecord]:
    """Extract one or more enforcement records from a single ruling PDF."""
    try:
        text = extract_text(io.BytesIO(pdf_bytes))
    except Exception as exc:
        _LOG.warning("pdf parse failed url=%s err=%s", pdf_url, exc)
        return []
    if not text or len(text) < 200:
        return []
    text = text.replace("　", " ")

    shubun = extract_shubun_block(text)
    if not shubun:
        return []
    head_map = extract_defendants_heading(text)
    if not head_map:
        return []

    issue_date = extract_issue_date(text, default=fallback_issue_date)
    if not issue_date:
        return []
    case_title = extract_case_title(text) or "海難審判事件"
    incident_date, incident_place = extract_incident_date_place(text)

    records: list[TribunalRecord] = []
    matched_letters: set[str] = set()
    for m in DEFENDANT_LINE_RE.finditer(shubun):
        letter_raw = m.group(1)
        letter = (
            letter_raw.lower()
            .translate(
                str.maketrans(
                    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
                    "abcdefghijklmnopqrstuvwxyz",
                )
            )
            .translate(str.maketrans("０１２３４５６７８９", "0123456789"))
        )
        sentence = m.group(2)
        if letter in matched_letters:
            continue
        matched_letters.add(letter)

        kind = classify_disposition(sentence)
        if kind is None:
            # 懲戒しない or unclassifiable — skip.
            continue

        info = head_map.get(letter)
        if not info:
            # Heading lookup failed; synthesize a generic label.
            license_type = "海技士" if hub.region_code == "tokyou" else "小型船舶操縦士"
            job = "船員"
        else:
            license_type = info["license_type"]
            job = info["job"] or "船員"

        # Build law reference based on license_type and disposition kind.
        if license_type == "小型船舶操縦士":
            base_law = "船舶職員及び小型船舶操縦者法"
        else:
            base_law = "船舶職員及び小型船舶操縦者法"
        # All discipline derives from 海難審判法第4条; tribunal page calls
        # for it explicitly. Combine it with the substantive law.
        related_law = f"海難審判法第4条 / {base_law}第10条"

        target_label = f"{job} {license_type} (受審人{letter}) #SEQ (氏名非公表)"

        records.append(
            TribunalRecord(
                region_code=hub.region_code,
                issuing_authority=hub.region_label,
                issuance_date=issue_date,
                target_label=target_label,
                license_type=license_type,
                enforcement_kind=kind,
                disposition_text=_norm_label(sentence)[:200],
                case_title=case_title,
                incident_date=incident_date,
                incident_place=incident_place,
                related_law_ref=related_law,
                source_url=pdf_url,
                source_hub_url=hub_url,
            )
        )
    return records


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


def load_existing_keys(
    conn: sqlite3.Connection,
) -> set[tuple[str, str, str, str]]:
    keys: set[tuple[str, str, str, str]] = set()
    for r in conn.execute(
        "SELECT IFNULL(issuing_authority, ''), issuance_date, "
        "       IFNULL(target_name, ''), IFNULL(enforcement_kind, '') "
        "FROM am_enforcement_detail"
    ):
        keys.add((r[0], r[1], r[2], r[3]))
    return keys


def next_seq(conn: sqlite3.Connection, region: str) -> int:
    prefix = f"AM-ENF-KAIGI-{region}-"
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
    rec: TribunalRecord,
    canonical_id: str,
    fetched_at: str,
    target_name: str,
) -> str:
    raw_json = {
        "region_code": rec.region_code,
        "issuing_authority": rec.issuing_authority,
        "target_label": target_name,
        "license_type": rec.license_type,
        "issuance_date": rec.issuance_date,
        "enforcement_kind": rec.enforcement_kind,
        "disposition_text": rec.disposition_text,
        "case_title": rec.case_title,
        "incident_date": rec.incident_date,
        "incident_place": rec.incident_place,
        "related_law_ref": rec.related_law_ref,
        "source_url": rec.source_url,
        "source_hub_url": rec.source_hub_url,
        "fetched_at": fetched_at,
        "source": "kaiho_kaigi_saiketsu_pdf",
    }
    domain = urllib.parse.urlparse(rec.source_url).netloc

    cur = conn.execute(
        "INSERT OR IGNORE INTO am_entities ("
        "  canonical_id, record_kind, source_topic, primary_name, "
        "  confidence, source_url, source_url_domain, fetched_at, raw_json"
        ") VALUES (?, 'enforcement', ?, ?, ?, ?, ?, ?, ?)",
        (
            canonical_id,
            f"kaigi_{rec.region_code}",
            target_name,
            0.85,
            rec.source_url,
            domain,
            fetched_at,
            json.dumps(raw_json, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    if cur.rowcount == 0:
        return "skip"

    summary = (
        f"{rec.case_title}: {rec.disposition_text}"
        + (f" (発生 {rec.incident_date}" if rec.incident_date else "")
        + (
            f" / {rec.incident_place})"
            if rec.incident_place
            else (")" if rec.incident_date else "")
        )
    )

    conn.execute(
        "INSERT INTO am_enforcement_detail ("
        "  entity_id, target_name, enforcement_kind, "
        "  issuing_authority, issuance_date, reason_summary, "
        "  related_law_ref, source_url, source_fetched_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            canonical_id,
            target_name,
            rec.enforcement_kind,
            rec.issuing_authority,
            rec.issuance_date,
            summary[:500],
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
        default="",
        help="comma-separated region codes (default: all hubs). "
        "Use 'tokyou' for the central Tokyo tribunal.",
    )
    ap.add_argument(
        "--years",
        type=str,
        default=",".join(DEFAULT_YEARS),
        help="comma-separated years (e.g. R07,R08). Tokyo "
        "central hub ignores this — it walks its own "
        "single archive page.",
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="stop after this many INSERTs across all hubs"
    )
    ap.add_argument(
        "--per-hub-pdf-limit",
        type=int,
        default=None,
        help="cap PDFs walked per hub per year (smoke tests)",
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

    all_hubs = REGIONAL_HUBS + [TOKYO_HUB]
    if args.regions.strip():
        wanted = {r.strip() for r in args.regions.split(",") if r.strip()}
        hubs = [h for h in all_hubs if h.region_code in wanted]
    else:
        hubs = list(all_hubs)
    if not hubs:
        _LOG.error("no hubs selected")
        return 2

    years = [y.strip() for y in args.years.split(",") if y.strip()]
    if not years:
        years = list(DEFAULT_YEARS)

    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")

    http = HttpClient()
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
    kind_breakdown: dict[str, int] = {}
    samples: list[TribunalRecord] = []
    total_inserts = 0

    try:
        for hub in hubs:
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
            iter_years = ["R08"] if hub.region_code == "tokyou" else years
            for yr in iter_years:
                _LOG.info(
                    "hub region=%s label=%s year=%s",
                    hub.region_code,
                    hub.region_label,
                    yr,
                )
                pdf_pairs = collect_pdfs_for_regional_hub(http, hub, yr)
                cs["pdfs_seen"] += len(pdf_pairs)
                _LOG.info(
                    "  pdfs_found=%d",
                    len(pdf_pairs),
                )
                if args.per_hub_pdf_limit is not None:
                    pdf_pairs = pdf_pairs[: args.per_hub_pdf_limit]

                # Newest URLs first as a heuristic.
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
                    recs = parse_ruling_pdf(
                        body,
                        hub=hub,
                        pdf_url=pdf_url,
                        hub_url=hub_url,
                        fallback_issue_date=None,
                    )
                    cs["records_extracted"] += len(recs)
                    _LOG.debug(
                        "  pdf=%s extracted=%d",
                        pdf_url.rsplit("/", 1)[-1],
                        len(recs),
                    )
                    for r in recs:
                        # Substitute SEQ placeholder with the per-region
                        # sequence to anonymize while keeping uniqueness.
                        target_name = r.target_label.replace(
                            "#SEQ",
                            f"#{seq_counter:03d}",
                        )
                        dedup_key = (
                            r.issuing_authority,
                            r.issuance_date,
                            target_name,
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
                            kind_breakdown[r.enforcement_kind] = (
                                kind_breakdown.get(r.enforcement_kind, 0) + 1
                            )
                            law_breakdown[r.related_law_ref] = (
                                law_breakdown.get(r.related_law_ref, 0) + 1
                            )
                            seq_counter += 1
                            if len(samples) < 8:
                                samples.append(r)
                            if cs["insert"] <= 3:
                                _LOG.info(
                                    "DRY %s | %s | %s | %s | %s",
                                    hub.region_code,
                                    r.issuance_date,
                                    target_name,
                                    r.enforcement_kind,
                                    r.disposition_text[:60],
                                )
                            continue
                        canonical_id = f"AM-ENF-KAIGI-{hub.region_code}-{seq_counter:06d}"
                        try:
                            verdict = upsert_record(
                                conn,
                                r,
                                canonical_id,
                                fetched_at,
                                target_name,
                            )
                        except sqlite3.Error as exc:
                            _LOG.warning(
                                "DB insert err name=%s err=%s",
                                target_name,
                                exc,
                            )
                            continue
                        if verdict == "insert":
                            cs["insert"] += 1
                            total_inserts += 1
                            region_breakdown[r.issuing_authority] = (
                                region_breakdown.get(r.issuing_authority, 0) + 1
                            )
                            kind_breakdown[r.enforcement_kind] = (
                                kind_breakdown.get(r.enforcement_kind, 0) + 1
                            )
                            law_breakdown[r.related_law_ref] = (
                                law_breakdown.get(r.related_law_ref, 0) + 1
                            )
                            seq_counter += 1
                            if len(samples) < 8:
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
    _LOG.info("PER KIND: %s", json.dumps(kind_breakdown, ensure_ascii=False))
    _LOG.info("PER LAW: %s", json.dumps(law_breakdown, ensure_ascii=False))
    _LOG.info("HUB STATS: %s", json.dumps(stats, ensure_ascii=False))
    print(
        "\n".join(
            [
                f"== sample {i + 1} ==\n"
                f"  date={s.issuance_date}\n"
                f"  authority={s.issuing_authority}\n"
                f"  target={s.target_label.replace('#SEQ', '#xxx')}\n"
                f"  kind={s.enforcement_kind}\n"
                f"  case_title={s.case_title}\n"
                f"  disposition={s.disposition_text[:100]}\n"
                f"  law_ref={s.related_law_ref}\n"
                f"  url={s.source_url}"
                for i, s in enumerate(samples[:8])
            ]
        )
    )

    if args.log_file is not None:
        with open(args.log_file, "a") as f:
            f.write(
                f"\n## {fetched_at} 海難審判 enforcement ingest\n"
                f"  hubs={len(hubs)} years={','.join(years)} "
                f"limit={args.limit}\n"
                f"  total_inserts={total_inserts}\n"
                f"  per_region="
                f"{json.dumps(region_breakdown, ensure_ascii=False)}\n"
                f"  per_kind="
                f"{json.dumps(kind_breakdown, ensure_ascii=False)}\n"
                f"  per_law="
                f"{json.dumps(law_breakdown, ensure_ascii=False)}\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
