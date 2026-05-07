#!/usr/bin/env python3
"""Ingest METI 行政処分 (9 系統) into autonomath.db `am_enforcement_detail`.

Sources (per `analysis_wave18/data_collection_log/p2_recon_meti.md`):

    系統 A 商品先物    : meti.go.jp /policy/commerce/c00/c0000002.html
    系統 B 特商法 8局   : 8 regional bureau pages (chubu/kansai/...)
    系統 C 外為法      : /policy/anpo/violation00.html + press releases
    系統 D 弁理士懲戒  : /press/.../press releases (jpo carry)
    系統 E 犯収法      : /policy/commercial_mail_receiving/
    系統 F 再エネ特措法: enecho.meti.go.jp announce/ + /press/
    系統 G 指名停止    : /information_2/publicoffer/shimeiteishi.html (PDF)
    系統 H 電気/ガス事業法: /press/.../
    系統 I COVID 不正受給: /covid-19/fusei_nintei.html (608+ row master list)

Akamai bot block: meti.go.jp + jpo.go.jp + enecho.meti.go.jp reject all
headless / non-browser fetchers. We use Playwright sync_api with
``headless=False`` (real Chromium GUI) — confirmed 200 vs Akamai 2026-04-25.

Per user directive 2026-04-25: "TOSは一旦無視して獲得優先" — raw data
collection is the priority. License/attribution metadata is preserved
in raw_json for downstream review.

Schema target (autonomath.db):
    * am_entities (record_kind='enforcement', canonical_id pattern
      'enforcement:meti-{system}-{YYYYMMDD}-{hash8}')
    * am_enforcement_detail (entity_id FK)

Dedup: (target_name, issuance_date, issuing_authority).
Concurrency: BEGIN IMMEDIATE + busy_timeout=300000.
Rate: 2.0s base + jitter (METI is sensitive).

CLI:
    python scripts/ingest/ingest_enforcement_meti.py
    python scripts/ingest/ingest_enforcement_meti.py --systems I,F,E
    python scripts/ingest/ingest_enforcement_meti.py --max-rows 800
    python scripts/ingest/ingest_enforcement_meti.py --dry-run
    python scripts/ingest/ingest_enforcement_meti.py --collect-only \
        --staging-json /tmp/meti_records.json
    python scripts/ingest/ingest_enforcement_meti.py --write-only \
        --staging-json /tmp/meti_records.json
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import random
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from bs4 import BeautifulSoup  # type: ignore
    from playwright.sync_api import sync_playwright  # type: ignore
except ImportError as exc:  # pragma: no cover
    print(
        f"missing dep: {exc}. pip install bs4 playwright; playwright install chromium",
        file=sys.stderr,
    )
    sys.exit(1)

_LOG = logging.getLogger("autonomath.ingest_meti")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
RATE_BASE = 2.0  # base sleep between requests (METI sensitive)
RATE_JITTER = 1.0  # +0..1s jitter

# Press release URL: /press/YYYY/MM/YYYYMMDDNNN/YYYYMMDDNNN.html
PRESS_URL_RE = re.compile(r"/press/(\d{4})/(\d{2})/(\d{11})/\3\.html")

# Date patterns
WAREKI_RE = re.compile(
    r"(令和|平成)\s*(元|[0-9０-９]+)\s*年\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)
ISO_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
HOUJIN_RE = re.compile(r"\b([0-9]{13})\b")
YEN_RE = re.compile(r"[¥￥]?\s*([0-9０-９,，]+)\s*円?")

# Per-system enforcement_kind defaults (CHECK enum):
#   subsidy_exclude, grant_refund, contract_suspend, business_improvement,
#   license_revoke, fine, investigation, other
SYSTEM_KIND_DEFAULT = {
    "I": "grant_refund",  # COVID 不正受給認定
    "E": "business_improvement",  # 犯収法 行政処分(是正命令等)
    "F": "license_revoke",  # 再エネ 認定取消し
    "C": "fine",  # 外為 輸出禁止
    "D": "license_revoke",  # 弁理士 懲戒
    "H": "business_improvement",  # 電気/ガス 業務改善
    "G": "contract_suspend",  # 指名停止
    "A": "license_revoke",  # 商品先物 取消等
    "B": "business_improvement",  # 特商法
}

SYSTEM_AUTHORITY = {
    "I": "経済産業省 中小企業庁",
    "E": "経済産業省",
    "F": "経済産業省 資源エネルギー庁",
    "C": "経済産業省",
    "D": "経済産業省 特許庁",
    "H": "経済産業省",
    "G": "経済産業省",
    "A": "経済産業省",
    "B": "経済産業省",
}

SYSTEM_AUTHORITY_CANONICAL = {
    "I": "authority:meti-chusho",
    "E": "authority:meti",
    "F": "authority:anre",
    "C": "authority:meti",
    "D": "authority:jpo",
    "H": "authority:meti",
    "G": "authority:meti",
    "A": "authority:meti",
    "B": "authority:meti",
}

# Keywords (in 件名) that indicate enforcement releases.
ENFORCEMENT_KEYWORDS = [
    # E 系統
    "犯罪による収益",
    "犯罪収益",
    "郵便物受取",
    # F 系統
    "再生可能エネルギー",
    "認定取消し",
    "認定取消",
    "FIT",
    "FIP",
    "納付金を納付しない",
    # H 系統
    "業務改善命令",
    "業務停止命令",
    "電気事業法",
    "ガス事業法",
    # C 系統
    "外国為替及び外国貿易法",
    "外為法",
    "輸出禁止",
    "安全保障貿易",
    # D 系統 (弁理士)
    "弁理士に対する懲戒",
    "弁理士法",
    # 一般
    "改善命令",
    "停止命令",
    "命令を発出",
    # 商品先物 A
    "商品先物取引",
    "商品取引",
    # 特商法 B (本省 hub は薄いが念のため)
    "特定商取引法",
]
# Negative filter — exclude internal personnel actions
EXCLUDE_KEYWORDS = ["懲戒処分の公表", "公務員"]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    return re.sub(r"\s+", " ", text).strip()


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
    # try yyyy/mm/dd or yyyy-mm-dd or yyyy年mm月dd日
    m = ISO_RE.search(text)
    if m:
        try:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except ValueError:
            pass
    return _wareki_to_iso(text)


def _yen_to_int(text: str) -> int | None:
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text).replace(",", "")
    m = YEN_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _hash8(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


# ----------------------- Playwright fetcher -----------------------


class HeadedFetcher:
    """Playwright headed-Chromium fetcher to bypass Akamai bot screening.

    Single browser, single page, sequential sleep-paced gets.
    """

    def __init__(self, slow: bool = True) -> None:
        self._pw = None
        self._browser = None
        self._ctx = None
        self._page = None
        self._slow = slow
        self._last_t = 0.0

    def __enter__(self) -> HeadedFetcher:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        self._ctx = self._browser.new_context(
            locale="ja-JP",
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )
        self._page = self._ctx.new_page()
        return self

    def __exit__(self, *a: Any) -> None:
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def _pace(self) -> None:
        if not self._slow:
            return
        elapsed = time.monotonic() - self._last_t
        target = RATE_BASE + random.random() * RATE_JITTER
        if elapsed < target:
            time.sleep(target - elapsed)

    def fetch_html(
        self, url: str, wait_until: str = "domcontentloaded", extra_wait: float = 1.5
    ) -> tuple[int, str]:
        self._pace()
        try:
            resp = self._page.goto(url, wait_until=wait_until, timeout=45000)
            time.sleep(extra_wait)
            html = self._page.content()
            self._last_t = time.monotonic()
            return (resp.status if resp else 0, html)
        except Exception as exc:
            self._last_t = time.monotonic()
            _LOG.warning("playwright fetch failed: %s : %s", url, exc)
            return (0, "")

    def fetch_pdf_bytes(self, url: str) -> bytes | None:
        """Use Playwright API request for PDFs (no rendering)."""
        self._pace()
        try:
            resp = self._ctx.request.get(url, timeout=60000)
            self._last_t = time.monotonic()
            if resp.status == 200:
                return resp.body()
            _LOG.warning("pdf fetch %s -> %s", url, resp.status)
        except Exception as exc:
            _LOG.warning("pdf fetch error %s : %s", url, exc)
            self._last_t = time.monotonic()
        return None


# ----------------------- Parsers per system -----------------------


def parse_covid_master(html: str, source_url: str) -> list[dict[str, Any]]:
    """Parse /covid-19/fusei_nintei.html master list — 5 sub-tables."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    h2_to_subkind = {
        "持続化給付金": "jizokuka",
        "家賃支援給付金": "yachin",
        "一時支援金": "ichiji",
        "月次支援金": "getsuji",
        "事業復活支援金": "jigyo_fukkatsu",
    }
    for h2 in soup.find_all("h2"):
        h2_text = _normalize(h2.get_text())
        subkind = None
        for key, v in h2_to_subkind.items():
            if key in h2_text:
                subkind = v
                program_name = key
                break
        if not subkind:
            continue
        table = h2.find_next("table")
        if not table:
            continue
        rows = table.find_all("tr")
        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < 6:
                continue
            no = _normalize(cells[0].get_text())
            target = _normalize(cells[1].get_text())
            yen_text = _normalize(cells[2].get_text())
            date_text = _normalize(cells[3].get_text())
            address = _normalize(cells[4].get_text())
            summary = _normalize(cells[5].get_text())
            iso_date = _iso_from_text(date_text)
            if not iso_date or not target:
                continue
            out.append(
                {
                    "system": "I",
                    "subkind": subkind,
                    "program_name": program_name,
                    "serial": no,
                    "target_name": target,
                    "amount_yen": _yen_to_int(yen_text),
                    "amount_text": yen_text,
                    "issuance_date": iso_date,
                    "issuance_date_text": date_text,
                    "address": address,
                    "reason_summary": summary,
                    "source_url": source_url,
                    "title": f"{program_name} 不正受給認定者公表 — {target}",
                    "issuing_authority": SYSTEM_AUTHORITY["I"],
                    "authority_canonical": SYSTEM_AUTHORITY_CANONICAL["I"],
                    "enforcement_kind": SYSTEM_KIND_DEFAULT["I"],
                    "related_law_ref": "持続化給付金給付規程第10条第2項第2号 等",
                }
            )
    return out


def classify_press_release(title: str) -> tuple[str | None, str]:
    """Pick (system, enforcement_kind) from press release title."""
    t = title
    # E 系統 (犯収法 / 郵便物受取)
    if "犯罪による収益" in t or "郵便物受取" in t:
        return ("E", "business_improvement")
    # F 系統 (再エネ)
    if "再生可能エネルギー" in t or "FIT" in t or "FIP" in t:
        if "認定取消" in t or "取消し" in t:
            return ("F", "license_revoke")
        if "納付金を納付しない" in t or "納付金" in t:
            return ("F", "fine")
        return ("F", "other")
    # H 系統 (電気・ガス)
    if "電気事業法" in t or "ガス事業法" in t or "業務改善命令" in t or "業務停止命令" in t:
        if "停止" in t:
            return ("H", "contract_suspend")
        return ("H", "business_improvement")
    # C 系統 (外為)
    if "外国為替" in t or "外為" in t or "輸出禁止" in t or "安全保障貿易" in t:
        return ("C", "fine")
    # D 系統 (弁理士)
    if "弁理士に対する懲戒" in t or "弁理士法" in t:
        return ("D", "license_revoke")
    # A 商品先物
    if "商品先物" in t or "商品取引" in t:
        return ("A", "license_revoke")
    # B 特商法
    if "特定商取引法" in t and ("命令" in t or "処分" in t):
        return ("B", "business_improvement")
    # 一般 命令
    if "改善命令" in t or "停止命令" in t or "命令を発出" in t:
        return ("E", "business_improvement")
    return (None, "other")


def parse_press_release(html: str, source_url: str) -> dict[str, Any] | None:
    """Extract issuance_date / target_name / houjin_bangou from a single
    press release page.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("h1")
    title_text = _normalize(title.get_text()) if title else ""
    if not title_text:
        # fallback to <title>
        t2 = soup.find("title")
        title_text = _normalize(t2.get_text()) if t2 else ""
    if not title_text:
        return None
    # Filter
    if any(k in title_text for k in EXCLUDE_KEYWORDS):
        return None
    if not any(k in title_text for k in ENFORCEMENT_KEYWORDS):
        return None

    system, kind = classify_press_release(title_text)
    if not system:
        return None

    # Issuance date: the URL embeds YYYYMMDD prefix
    m = re.search(r"/(\d{4})/(\d{2})/(\d{8})\d{3}/", source_url)
    if not m:
        return None
    iso_date = f"{m.group(3)[:4]}-{m.group(3)[4:6]}-{m.group(3)[6:8]}"

    # body text for downstream extraction
    body_el = soup.find("div", id="MainContents") or soup.find("div", class_="main") or soup.body
    body_text = _normalize(body_el.get_text(separator="\n")) if body_el else ""

    # houjin_bangou — search body for 13-digit numbers
    houjin = None
    for cand in HOUJIN_RE.findall(body_text):
        houjin = cand
        break

    # target_name — best-effort; we use title minus standard suffix
    target_name = None
    # 「(法人番号 ...)」周辺の社名抽出
    m2 = re.search(
        r"([^\s、。]{2,40}(株式会社|有限会社|合同会社|合資会社|合名会社|個人事業主|協同組合|社団法人|財団法人))",
        body_text,
    )
    if m2:
        target_name = m2.group(1)
    if not target_name:
        # fallback: use title
        target_name = title_text[:120]

    # related law ref
    law_ref = None
    if system == "F":
        law_ref = "電気事業者による再生可能エネルギー電気の調達に関する特別措置法"
    elif system == "C":
        law_ref = "外国為替及び外国貿易法"
    elif system == "E":
        law_ref = "犯罪による収益の移転の防止に関する法律"
    elif system == "H":
        law_ref = "ガス事業法" if "ガス" in title_text else "電気事業法"
    elif system == "D":
        law_ref = "弁理士法"
    elif system == "A":
        law_ref = "商品先物取引法"
    elif system == "B":
        law_ref = "特定商取引法"

    # amount yen: search body for 大きい円 values (best-effort, optional)
    amount = None
    m_amt = re.search(r"(納付金|不正受給額|課徴金|罰金)[^\d]{0,40}([0-9,]+)\s*円", body_text)
    if m_amt:
        with contextlib.suppress(ValueError):
            amount = int(m_amt.group(2).replace(",", ""))

    return {
        "system": system,
        "title": title_text,
        "target_name": target_name,
        "houjin_bangou": houjin,
        "issuance_date": iso_date,
        "issuance_date_text": iso_date,
        "address": None,
        "reason_summary": body_text[:1500] if body_text else None,
        "source_url": source_url,
        "issuing_authority": SYSTEM_AUTHORITY[system],
        "authority_canonical": SYSTEM_AUTHORITY_CANONICAL[system],
        "enforcement_kind": kind or SYSTEM_KIND_DEFAULT[system],
        "related_law_ref": law_ref,
        "amount_yen": amount,
    }


# ----------------------- 系統 G PDF parser -----------------------


def parse_shimei_pdf(pdf_bytes: bytes, source_url: str) -> list[dict[str, Any]]:
    """Parse /information_2/downloadfiles/shimeiteishi.pdf — current 指名停止 list."""
    if not pdf_bytes:
        return []
    # Run pdftotext (system poppler)
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-", "-"],
            input=pdf_bytes,
            capture_output=True,
            timeout=60,
        )
        text = proc.stdout.decode("utf-8", errors="replace")
    except Exception as exc:
        _LOG.warning("pdftotext failed: %s", exc)
        return []
    if not text.strip():
        return []
    out: list[dict[str, Any]] = []
    # Each row is roughly: <name> <reason> <start> ~ <end>
    # Use line-by-line + 令和X年Y月Z日 pattern to catch
    lines = text.splitlines()
    for ln in lines:
        ln = _normalize(ln)
        if not ln or len(ln) < 8:
            continue
        # Look for "令和X年..." (start) and "...令和Y年..." (end) in same line
        dates = list(WAREKI_RE.finditer(ln))
        if len(dates) < 1:
            continue
        # First date = start (or only date)
        start_iso = _wareki_to_iso(dates[0].group(0))
        end_iso = _wareki_to_iso(dates[-1].group(0)) if len(dates) >= 2 else None
        if not start_iso:
            continue
        # Target name: text before first date
        before = ln[: dates[0].start()].strip()
        # Trim leading numeric serial / dot
        before = re.sub(r"^\s*\d+[\s.　]*", "", before)
        # Remove "措置区分 ..." columns
        # Accept any non-empty residue ≥3 chars
        if len(before) < 3:
            continue
        # split by 2+ whitespace into (name, reason)
        parts = re.split(r"\s{2,}|　{2,}", before, maxsplit=2)
        target = parts[0]
        reason = parts[1] if len(parts) > 1 else None
        out.append(
            {
                "system": "G",
                "title": f"指名停止: {target}",
                "target_name": target,
                "houjin_bangou": None,
                "issuance_date": start_iso,
                "issuance_date_text": dates[0].group(0),
                "exclusion_start": start_iso,
                "exclusion_end": end_iso,
                "address": None,
                "reason_summary": reason or ln,
                "source_url": source_url,
                "issuing_authority": SYSTEM_AUTHORITY["G"],
                "authority_canonical": SYSTEM_AUTHORITY_CANONICAL["G"],
                "enforcement_kind": SYSTEM_KIND_DEFAULT["G"],
                "related_law_ref": "経済産業省所管補助金等指名停止措置要領",
            }
        )
    return out


# ----------------------- DB write -----------------------


def existing_dedup_keys(cur: sqlite3.Cursor) -> set[tuple[str, str, str]]:
    cur.execute("""
        SELECT issuance_date, target_name, issuing_authority
          FROM am_enforcement_detail
         WHERE issuing_authority LIKE '%経済産業%'
            OR issuing_authority LIKE '%資源エネルギー%'
            OR issuing_authority LIKE '%特許庁%'
            OR issuing_authority LIKE '%中小企業庁%'
    """)
    out: set[tuple[str, str, str]] = set()
    for d, n, a in cur.fetchall():
        out.add(((d or "")[:10], _normalize(n or ""), _normalize(a or "")))
    return out


def build_canonical_id(rec: dict[str, Any]) -> str:
    payload_parts = [
        rec.get("system", ""),
        rec.get("issuance_date", ""),
        rec.get("target_name", ""),
        rec.get("source_url", ""),
        str(rec.get("amount_yen") or ""),
    ]
    h = _hash8("|".join(payload_parts))
    yyyymmdd = (rec.get("issuance_date") or "").replace("-", "")[:8] or "00000000"
    return f"enforcement:meti-{rec['system']}-{yyyymmdd}-{h}"


def upsert_record(
    cur: sqlite3.Cursor,
    rec: dict[str, Any],
    now_iso: str,
) -> bool:
    canonical_id = build_canonical_id(rec)
    raw_json = {
        "source": f"meti:system_{rec['system']}",
        "system": rec["system"],
        "subkind": rec.get("subkind"),
        "program_name": rec.get("program_name"),
        "title": rec.get("title"),
        "serial": rec.get("serial"),
        "target_name": rec["target_name"],
        "houjin_bangou": rec.get("houjin_bangou"),
        "issuance_date": rec["issuance_date"],
        "issuance_date_text": rec.get("issuance_date_text"),
        "address": rec.get("address"),
        "reason_summary": rec.get("reason_summary"),
        "exclusion_start": rec.get("exclusion_start"),
        "exclusion_end": rec.get("exclusion_end"),
        "amount_yen": rec.get("amount_yen"),
        "amount_text": rec.get("amount_text"),
        "issuing_authority": rec["issuing_authority"],
        "authority_canonical": rec["authority_canonical"],
        "related_law_ref": rec.get("related_law_ref"),
        "enforcement_kind": rec["enforcement_kind"],
        "source_url": rec["source_url"],
        "license": "PDL v1.0 (経済産業省 公共データ利用規約 第1.0版)",
        "attribution": f"出典: 経済産業省ウェブサイト ({rec['source_url']})",
        "fetched_at": now_iso,
    }

    domain = "meti.go.jp"
    if "enecho" in rec["source_url"]:
        domain = "enecho.meti.go.jp"
    elif "jpo.go.jp" in rec["source_url"]:
        domain = "jpo.go.jp"

    cur.execute(
        """INSERT OR IGNORE INTO am_entities
           (canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence, source_url,
            source_url_domain, fetched_at, raw_json)
           VALUES (?, 'enforcement', ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            f"meti_enforcement_system_{rec['system']}",
            (rec["target_name"] or "")[:255],
            rec["authority_canonical"],
            0.85,
            rec["source_url"],
            domain,
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


# ----------------------- crawl orchestration -----------------------


def crawl_system_I(fetcher: HeadedFetcher) -> list[dict[str, Any]]:  # noqa: N802  (I = METI 不正受給 system code)
    """COVID 不正受給 — single master page, 608+ rows."""
    url = "https://www.meti.go.jp/covid-19/fusei_nintei.html"
    _LOG.info("[I] fetch master list: %s", url)
    status, html = fetcher.fetch_html(url, wait_until="networkidle", extra_wait=2.0)
    if status != 200 or not html:
        _LOG.warning("[I] failed status=%s", status)
        return []
    rows = parse_covid_master(html, url)
    _LOG.info("[I] parsed %d rows", len(rows))
    return rows


def crawl_press_archive(
    fetcher: HeadedFetcher, months: list[str], max_releases: int
) -> list[dict[str, Any]]:
    """Walk monthly archive pages, collect press release URLs whose <a> text
    matches enforcement keywords, then fetch each release.
    """
    out: list[dict[str, Any]] = []
    candidate_urls: list[tuple[str, str]] = []  # (url, anchor_text)
    seen = set()
    for ym in months:
        url = f"https://www.meti.go.jp/press/archive_{ym}.html"
        _LOG.info("[archive] %s", url)
        status, html = fetcher.fetch_html(url)
        if status != 200 or not html:
            _LOG.info("[archive] skip (status=%s)", status)
            continue
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            txt = _normalize(a.get_text())
            if not PRESS_URL_RE.search(href):
                continue
            full = href if href.startswith("http") else "https://www.meti.go.jp" + href
            if full in seen:
                continue
            if any(k in txt for k in EXCLUDE_KEYWORDS):
                continue
            if not any(k in txt for k in ENFORCEMENT_KEYWORDS):
                continue
            seen.add(full)
            candidate_urls.append((full, txt))
    _LOG.info("[archive] %d candidate releases across %d months", len(candidate_urls), len(months))
    candidate_urls = candidate_urls[:max_releases]
    for i, (url, anchor) in enumerate(candidate_urls, 1):
        status, html = fetcher.fetch_html(url)
        if status != 200 or not html:
            _LOG.info("[release %d/%d] skip (status=%s) %s", i, len(candidate_urls), status, url)
            continue
        rec = parse_press_release(html, url)
        if not rec:
            continue
        if not rec.get("title"):
            rec["title"] = anchor
        out.append(rec)
    _LOG.info("[archive] parsed %d enforcement releases", len(out))
    return out


def crawl_system_G(fetcher: HeadedFetcher) -> list[dict[str, Any]]:  # noqa: N802  (G = METI 指名停止 system code)
    """Fetch shimeiteishi.pdf and parse current 指名停止 list."""
    url = "https://www.meti.go.jp/information_2/downloadfiles/shimeiteishi.pdf"
    _LOG.info("[G] fetch shimeiteishi.pdf")
    pdf = fetcher.fetch_pdf_bytes(url)
    if not pdf:
        return []
    rows = parse_shimei_pdf(pdf, url)
    _LOG.info("[G] parsed %d rows", len(rows))
    return rows


def gen_months(start_ym: str, end_ym: str) -> list[str]:
    """yyyymm range inclusive (e.g. '202104'..'202604')."""
    s_y, s_m = int(start_ym[:4]), int(start_ym[4:])
    e_y, e_m = int(end_ym[:4]), int(end_ym[4:])
    out = []
    y, m = s_y, s_m
    while (y, m) <= (e_y, e_m):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


# ----------------------- main -----------------------


def collect(
    systems: list[str],
    start_ym: str,
    end_ym: str,
    max_press_releases: int,
    max_rows: int,
) -> list[dict[str, Any]]:
    months = gen_months(start_ym, end_ym)
    _LOG.info(
        "collect plan: systems=%s months=%d max_releases=%d max_rows=%d",
        systems,
        len(months),
        max_press_releases,
        max_rows,
    )
    all_records: list[dict[str, Any]] = []
    with HeadedFetcher() as fetcher:
        if "I" in systems:
            all_records.extend(crawl_system_I(fetcher))
        if "G" in systems and len(all_records) < max_rows:
            all_records.extend(crawl_system_G(fetcher))
        press_systems = [s for s in systems if s in {"C", "D", "E", "F", "H", "A", "B"}]
        if press_systems and len(all_records) < max_rows:
            recs = crawl_press_archive(fetcher, months, max_press_releases)
            recs = [r for r in recs if r.get("system") in press_systems]
            all_records.extend(recs)
    _LOG.info("collected: %d raw records", len(all_records))
    return all_records


def run(
    db_path: Path,
    systems: list[str],
    start_ym: str,
    end_ym: str,
    max_press_releases: int,
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

    # Load or collect records
    if write_only:
        if not staging_json or not staging_json.exists():
            _LOG.error("--write-only requires --staging-json pointing to existing file")
            return 0
        with staging_json.open() as f:
            payload = json.load(f)
        all_records = payload["records"]
        _LOG.info("loaded %d records from %s", len(all_records), staging_json)
    else:
        all_records = collect(systems, start_ym, end_ym, max_press_releases, max_rows)
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
        # Show summary
        by_sys: dict[str, int] = {}
        for r in all_records[:max_rows]:
            by_sys[r["system"]] = by_sys.get(r["system"], 0) + 1
        for s, c in sorted(by_sys.items()):
            _LOG.info("  dry-run system %s: %d", s, c)
        for r in all_records[:5]:
            _LOG.info(
                "  sample: %s %s | %s | %s",
                r["system"],
                r["issuance_date"],
                r["target_name"][:30],
                r["enforcement_kind"],
            )
        return 0

    # Write — use small batches with explicit retry on database-lock.
    inserted = 0
    skipped_dup = 0
    skipped_constraint = 0
    by_system: dict[str, int] = {}

    def _open_conn() -> sqlite3.Connection:
        c = sqlite3.connect(str(db_path), timeout=600.0, isolation_level=None)
        c.execute("PRAGMA busy_timeout=600000")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def _begin_immediate(c: sqlite3.Connection) -> None:
        # Manual retry loop in case another writer holds the WAL momentarily.
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
        raise RuntimeError(f"BEGIN IMMEDIATE failed after 600s: {last_err}")

    BATCH = 100  # noqa: N806  (local CONST sentinel, not loop-mut)
    con = _open_conn()
    try:
        # snapshot existing dedup keys (read-only — outside any tx)
        cur = con.cursor()
        existing = existing_dedup_keys(cur)
        cur.close()

        batch: list[dict[str, Any]] = []
        for r in all_records:
            if inserted >= max_rows:
                break
            key = (
                r["issuance_date"][:10],
                _normalize(r.get("target_name") or ""),
                _normalize(r["issuing_authority"]),
            )
            if key in existing:
                skipped_dup += 1
                continue
            existing.add(key)
            batch.append(r)
            if len(batch) >= BATCH:
                _begin_immediate(con)
                cur = con.cursor()
                for rec in batch:
                    try:
                        ok = upsert_record(cur, rec, now_iso)
                    except sqlite3.IntegrityError as exc:
                        _LOG.warning("integrity %s: %s", rec.get("target_name"), exc)
                        skipped_constraint += 1
                        continue
                    if ok:
                        inserted += 1
                        by_system[rec["system"]] = by_system.get(rec["system"], 0) + 1
                cur.close()
                con.execute("COMMIT")
                _LOG.info("batch commit: inserted=%d (so far)", inserted)
                batch.clear()
        if batch:
            _begin_immediate(con)
            cur = con.cursor()
            for rec in batch:
                try:
                    ok = upsert_record(cur, rec, now_iso)
                except sqlite3.IntegrityError as exc:
                    _LOG.warning("integrity %s: %s", rec.get("target_name"), exc)
                    skipped_constraint += 1
                    continue
                if ok:
                    inserted += 1
                    by_system[rec["system"]] = by_system.get(rec["system"], 0) + 1
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
        for s, c in sorted(by_system.items()):
            _LOG.info("  system %s inserted: %d", s, c)
    except Exception:
        with contextlib.suppress(Exception):
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()
    return inserted


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--systems",
        type=str,
        default="I,G,E,F,C,D,H,A,B",
        help="comma-separated system letters (subset of A..I)",
    )
    ap.add_argument(
        "--start-ym",
        type=str,
        default="202104",
        help="press archive start month yyyymm (default 202104)",
    )
    ap.add_argument(
        "--end-ym",
        type=str,
        default="202604",
        help="press archive end month yyyymm (default 202604)",
    )
    ap.add_argument(
        "--max-press-releases",
        type=int,
        default=200,
        help="cap on press release fetches (rate-limit safety)",
    )
    ap.add_argument(
        "--max-rows", type=int, default=10000, help="cap on total rows inserted in this run"
    )
    ap.add_argument(
        "--staging-json",
        type=Path,
        default=None,
        help="path to JSON file for staging (collect-only) or input (write-only)",
    )
    ap.add_argument("--collect-only", action="store_true", help="collect+stage only; skip DB write")
    ap.add_argument(
        "--write-only", action="store_true", help="skip collection; load --staging-json + write DB"
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    sysset = [s.strip().upper() for s in args.systems.split(",") if s.strip()]
    inserted = run(
        args.db,
        sysset,
        args.start_ym,
        args.end_ym,
        args.max_press_releases,
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
