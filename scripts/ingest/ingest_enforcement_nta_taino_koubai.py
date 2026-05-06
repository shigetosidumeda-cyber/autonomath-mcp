#!/usr/bin/env python3
"""Ingest 国税庁 公売情報 (差押え物件) into autonomath.db `am_enforcement_detail`.

Sources (primary, nta.go.jp / koubai.nta.go.jp only):

  * https://www.koubai.nta.go.jp/ — 公売情報システム
      - hp0241.php (不動産 — real estate, 53 items / Apr 2026)
      - hp0341.php (動産 — movables: 自動車・有価証券・債権・電話加入権 等)
      - hp0441.php (その他 — receivables / その他)
      - Each search page paginates `pageid=0..N` (≈30 hits/page).
      - Each item detail at hp0201.php?kyoku_no=XXXXX&koubai_nendo=YYYY&
        koubai_no=NN&koubai_kind=N&baikyaku_no=XXXXX
      - Detail pages include: 実施局署 / 公売公告番号 / 売却区分番号 / 入札期間 /
        売却決定の日時 / 住居表示等 / 種別 / 主たる地目 etc.

  * Per-item record  → am_enforcement_detail row, kind='investigation'
        (差押財産公売 = 国税徴収法に基づく財産差押え後の換価処分)
  * Per-公告 record  → am_enforcement_detail row, kind='other' (公売公告 itself)
        deduped by (kyoku_no, koubai_nendo, koubai_no)

Per user directive 2026-04-25: TOS は一旦無視して獲得優先. License/attribution
metadata is preserved in raw_json for downstream review.

Schema target (autonomath.db):
    * am_entities (record_kind='enforcement', canonical_id pattern
      'enforcement:nta-koubai-{kyoku}-{nendo}-{koubai}-{baikyaku}-{hash6}'
      'enforcement:nta-koukoku-{kyoku}-{nendo}-{koubai}-{hash6}'
    * am_enforcement_detail (entity_id FK)

Dedup: (target_name, issuance_date, issuing_authority).
Concurrency: BEGIN IMMEDIATE + busy_timeout=300000.
Rate: 1 req/sec (KOUBAI_DELAY).
UA:    "AutonoMath/0.1.0 (+https://bookyou.net)".

CLI:
    python scripts/ingest/ingest_enforcement_nta_taino_koubai.py
    python scripts/ingest/ingest_enforcement_nta_taino_koubai.py --max-rows 400
    python scripts/ingest/ingest_enforcement_nta_taino_koubai.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

_LOG = logging.getLogger("autonomath.ingest_nta_koubai")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
KOUBAI_BASE = "https://www.koubai.nta.go.jp/auctionx/public"
KOUBAI_DELAY = 1.0  # 1 req/sec per directive

# Map kyoku_no (実施局署 code in hp0201.php) -> canonical bureau name.
# Verified 2026-04-25 by walking detail pages in each kyoku.
KYOKU_MAP: dict[str, str] = {
    "01001": "東京国税局",
    "02001": "関東信越国税局",
    "03001": "札幌国税局",
    "04001": "仙台国税局",
    "05001": "金沢国税局",
    "06001": "名古屋国税局",
    "07001": "大阪国税局",
    "08001": "広島国税局",
    "09001": "高松国税局",
    "10001": "福岡国税局",
    "11001": "熊本国税局",
    "12001": "沖縄国税事務所",
}

# am_authority canonical_id for each bureau (best-effort namespacing).
KYOKU_AUTHORITY_CANONICAL: dict[str, str] = {
    code: f"authority:nta-{slug}"
    for code, slug in [
        ("01001", "tokyo"),
        ("02001", "kantoshinetsu"),
        ("03001", "sapporo"),
        ("04001", "sendai"),
        ("05001", "kanazawa"),
        ("06001", "nagoya"),
        ("07001", "osaka"),
        ("08001", "hiroshima"),
        ("09001", "takamatsu"),
        ("10001", "fukuoka"),
        ("11001", "kumamoto"),
        ("12001", "okinawa"),
    ]
}

# Parent in am_authority for all 12 (verified existing): 'authority:mof-nta'
NTA_AUTHORITY_PARENT = "authority:mof-nta"


def ensure_bureau_authorities(cur: sqlite3.Cursor) -> None:
    """Insert (idempotent) am_authority rows for each NTA regional bureau.

    Done within the same BEGIN IMMEDIATE block as the enforcement inserts
    so the FK targets exist before any am_entities row references them.
    """
    for code, name in KYOKU_MAP.items():
        canonical = KYOKU_AUTHORITY_CANONICAL[code]
        # 沖縄国税事務所 is technically not a 国税局; it's level 'agency'.
        # All others are bureau-level. Map accordingly.
        level = "agency" if code == "12001" else "bureau"
        cur.execute(
            """INSERT OR IGNORE INTO am_authority
               (canonical_id, canonical_name, canonical_en, level, parent_id,
                website, note)
               VALUES (?, ?, NULL, ?, ?, ?, ?)""",
            (
                canonical,
                name,
                level,
                NTA_AUTHORITY_PARENT,
                "https://www.nta.go.jp/",
                "Created by ingest_enforcement_nta_taino_koubai.py 2026-04-25",
            ),
        )


# Search list URLs — three categories. Empty pages stop pagination.
LIST_URLS = {
    "real_estate": (
        f"{KOUBAI_BASE}/hp0241.php"
        "?addr_id=0&addr_area=0&addr_wide=0&addr_or_line=0&addr_name=0"
        "&zaisan_bunrui_chk%5B999%5D=1"
    ),
    "movables": (
        f"{KOUBAI_BASE}/hp0341.php"
        "?zaisan_bunrui_chk%5B200%5D=1&zaisan_bunrui_chk%5B201%5D=1"
        "&zaisan_bunrui_chk%5B220%5D=1&zaisan_bunrui_chk%5B221%5D=1"
        "&zaisan_bunrui_chk%5B230%5D=1&zaisan_bunrui_chk%5B240%5D=1"
        "&zaisan_bunrui_chk%5B241%5D=1&zaisan_bunrui_chk%5B260%5D=1"
        "&zaisan_bunrui_chk%5B265%5D=1&zaisan_bunrui_chk%5B266%5D=1"
        "&zaisan_bunrui_chk%5B290%5D=1&kensaku_keyword="
    ),
    "receivables": (
        f"{KOUBAI_BASE}/hp0441.php"
        "?addr_id=0&addr_area=0&addr_wide=0&addr_name=0"
        "&zaisan_bunrui_chk%5B300%5D=1&zaisan_bunrui_chk%5B301%5D=1"
        "&zaisan_bunrui_chk%5B310%5D=1"
    ),
}

# Date patterns
WAREKI_RE = re.compile(
    r"(令和|平成)\s*(元|[0-9０-９]+)\s*年\s*([0-9０-９]+)\s*月\s*([0-9０-９]+)\s*日"
)

ITEM_LINK_RE = re.compile(
    r'href="(hp0[0-9]+\.php\?'
    r"kyoku_no=(\d+)&(?:amp;)?koubai_nendo=(\d+)"
    r"&(?:amp;)?koubai_no=(\d+)&(?:amp;)?koubai_kind=(\d+)"
    r'&(?:amp;)?baikyaku_no=(\d+))"'
)


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


def _yen_to_int(text: str) -> int | None:
    if not text:
        return None
    text = unicodedata.normalize("NFKC", text).replace(",", "").replace("，", "")
    m = re.search(r"([0-9]+)", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _hash6(payload: str) -> str:
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:6]


# ----------------------- Fetcher -----------------------


class KoubaiFetcher:
    """1 req/sec httpx fetcher with the AutonoMath UA."""

    def __init__(self, delay: float = KOUBAI_DELAY) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ja,en;q=0.5",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=30.0,
            follow_redirects=True,
        )
        self._delay = delay
        self._last_t = 0.0

    def __enter__(self) -> KoubaiFetcher:
        # Seed session: visit landing page once to acquire PHPSESSID + master_session.
        self.get(f"{KOUBAI_BASE}/hp001.php")
        return self

    def __exit__(self, *a: Any) -> None:
        self._client.close()

    def _pace(self) -> None:
        elapsed = time.monotonic() - self._last_t
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)

    def get(self, url: str, *, max_retries: int = 3) -> str | None:
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            self._pace()
            try:
                resp = self._client.get(url)
                self._last_t = time.monotonic()
                if resp.status_code == 200:
                    # koubai responses are utf-8; trust httpx
                    return resp.text
                if resp.status_code in (429, 503):
                    wait = (2**attempt) + random.uniform(0, 1)
                    _LOG.info("rate-limit %s -> %s, wait %.1fs", url, resp.status_code, wait)
                    time.sleep(wait)
                    continue
                _LOG.warning("HTTP %s for %s", resp.status_code, url)
                return None
            except httpx.HTTPError as exc:
                last_exc = exc
                self._last_t = time.monotonic()
                if attempt < max_retries - 1:
                    wait = (2**attempt) + random.uniform(0, 1)
                    _LOG.info("fetch error %s err=%s wait %.1fs", url, exc, wait)
                    time.sleep(wait)
                    continue
        _LOG.warning("fetch failed url=%s err=%s", url, last_exc)
        return None


# ----------------------- Parsers -----------------------


def parse_list_page(html: str) -> list[tuple[str, str, str, str, str, str]]:
    """Return list of (relpath, kyoku, nendo, koubai, kind, baikyaku) tuples.

    relpath is the detail .php filename (hp0201/hp0307/hp0411 etc.) plus
    its querystring as it appears in the list page <a href> — pre-decoded
    of HTML entities. Caller composes full URL.
    """
    html_decoded = html.replace("&amp;", "&")
    out: list[tuple[str, str, str, str, str, str]] = []
    seen = set()
    for m in ITEM_LINK_RE.finditer(html_decoded):
        relpath, kyoku, nendo, koubai, kind, baikyaku = m.groups()
        ids = (kyoku, nendo, koubai, kind, baikyaku)
        if ids in seen:
            continue
        seen.add(ids)
        out.append((relpath, *ids))
    return out


def _row_text(soup: BeautifulSoup, label: str) -> str | None:
    for tr in soup.find_all("tr"):
        th = tr.find("th")
        td = tr.find("td")
        if not th or not td:
            continue
        kt = _normalize(th.get_text())
        if kt == label or kt.startswith(label):
            return _normalize(td.get_text(separator=" "))
    return None


def parse_detail(
    html: str, source_url: str, ids: tuple[str, str, str, str, str]
) -> dict[str, Any] | None:
    """Parse hp0201/hp0307/hp0411 detail page → dict.

    Field labels are uniform across all three detail page variants —
    they share the same row-by-row 〈label〉:〈value〉 schema.
    """
    kyoku, nendo, koubai, kind, baikyaku = ids
    soup = BeautifulSoup(html, "html.parser")

    title = soup.find("title")
    title_text = _normalize(title.get_text()) if title else ""

    # Strip "｜公売情報" suffix
    if "｜" in title_text:
        title_text = title_text.split("｜")[0].strip()

    bureau = KYOKU_MAP.get(kyoku)
    if not bureau:
        # Try to infer from page text
        kyoku_text = _row_text(soup, "実施局署") or ""
        if "国税局" in kyoku_text:
            bureau = re.sub(r"\s+", "", kyoku_text)
            if not bureau.endswith("国税局") and not bureau.endswith("国税事務所"):
                bureau = bureau + "国税局"
        else:
            return None

    issuing_authority = f"国税庁 {bureau}"
    authority_canonical = KYOKU_AUTHORITY_CANONICAL.get(kyoku, "authority:nta")

    # Issuance date — first 入札期間 wareki
    nyusatsu = _row_text(soup, "入札期間")
    iso_date = _wareki_to_iso(nyusatsu) if nyusatsu else None

    # If no 入札期間, fall back to 売却決定の日時 (for sales finalized only)
    if not iso_date:
        baikyaku_kettei = _row_text(soup, "売却決定の日時")
        iso_date = _wareki_to_iso(baikyaku_kettei) if baikyaku_kettei else None

    # If still nothing, fall back to 開札期日
    if not iso_date:
        kaisatsu = _row_text(soup, "開札期日")
        iso_date = _wareki_to_iso(kaisatsu) if kaisatsu else None

    if not iso_date:
        _LOG.debug("no date for %s", source_url)
        return None

    # 売却区分番号 — primary identifier
    bunru = _row_text(soup, "売却区分番号") or f"{baikyaku}号"
    # 種別 (土地, 建物, 自動車, 債権, etc.)
    shubetu = _row_text(soup, "種別") or _row_text(soup, "主たる地目") or ""
    # 住居表示 (real estate) or 所在 (movables) etc.
    shozai = (
        _row_text(soup, "住居表示等") or _row_text(soup, "所在") or _row_text(soup, "所在地") or ""
    )
    # 公売公告番号
    koukoku_no = _row_text(soup, "公売公告番号") or f"{koubai}号"

    # 見積価額
    mitsumori = _row_text(soup, "見積価額") or _row_text(soup, "見積（売却）価額")
    amount = _yen_to_int(mitsumori) if mitsumori else None

    # 公売保証金
    hoshokin = _row_text(soup, "公売保証金")

    # target_name = 売却区分番号 + 種別 + 簡易所在 (滞納者氏名は非開示)
    parts = [bunru]
    if shubetu:
        parts.append(shubetu)
    if shozai:
        parts.append(shozai[:40])
    target_name = " / ".join(parts)[:200]

    if not title_text:
        title_text = f"公売物件: {target_name}"

    # Reason summary: brief multi-line excerpt
    summary_parts = []
    if shozai:
        summary_parts.append(f"所在: {shozai}")
    if shubetu:
        summary_parts.append(f"種別: {shubetu}")
    if mitsumori:
        summary_parts.append(f"見積価額: {mitsumori}")
    if hoshokin:
        summary_parts.append(f"公売保証金: {hoshokin}")
    if nyusatsu:
        summary_parts.append(f"入札期間: {nyusatsu}")
    summary = " | ".join(summary_parts)[:1500]

    return {
        "level": "item",
        "kyoku": kyoku,
        "nendo": nendo,
        "koubai_no": koubai,
        "koubai_kind": kind,
        "baikyaku_no": baikyaku,
        "title": title_text,
        "target_name": target_name,
        "issuance_date": iso_date,
        "issuance_date_text": nyusatsu or "",
        "issuing_authority": issuing_authority,
        "authority_canonical": authority_canonical,
        "bureau": bureau,
        "enforcement_kind": "investigation",
        "related_law_ref": "国税徴収法第94条 (公売)",
        "amount_yen": amount,
        "reason_summary": summary,
        "source_url": source_url,
        "shozai": shozai,
        "shubetu": shubetu,
        "koukoku_no": koukoku_no,
        "houshokin": hoshokin,
    }


def make_koukoku_record(item: dict[str, Any]) -> dict[str, Any]:
    """Per-公告 (publication act) row, distinct from per-item rows."""
    kyoku = item["kyoku"]
    nendo = item["nendo"]
    koubai = item["koubai_no"]
    bureau = item["bureau"]
    iso_date = item["issuance_date"]
    koukoku_no = item["koukoku_no"]
    return {
        "level": "koukoku",
        "kyoku": kyoku,
        "nendo": nendo,
        "koubai_no": koubai,
        "koubai_kind": item["koubai_kind"],
        "baikyaku_no": "",
        "title": f"公売公告 {koukoku_no} ({bureau} 令和{nendo}年度 第{koubai}号)",
        "target_name": f"公売公告: {bureau} 令和{nendo}年度 第{koubai}号 {koukoku_no}",
        "issuance_date": iso_date,
        "issuance_date_text": item.get("issuance_date_text", ""),
        "issuing_authority": item["issuing_authority"],
        "authority_canonical": item["authority_canonical"],
        "bureau": bureau,
        "enforcement_kind": "other",
        "related_law_ref": "国税徴収法第95条 (公売の公告)",
        "amount_yen": None,
        "reason_summary": (
            f"国税徴収法第95条に基づく公売公告。"
            f"発行: {bureau}、年度: 令和{nendo}年度、番号: {koukoku_no}。"
        )[:1500],
        "source_url": (
            f"{KOUBAI_BASE}/hp001_01.php?doc=8&kyoku_no={kyoku}"
            f"&koubai_nendo={nendo}&koubai_no={koubai}"
        ),
    }


# ----------------------- DB write -----------------------


def existing_dedup_keys(cur: sqlite3.Cursor) -> set[tuple[str, str, str]]:
    cur.execute("""
        SELECT issuance_date, target_name, issuing_authority
          FROM am_enforcement_detail
         WHERE issuing_authority LIKE '%国税局%'
            OR issuing_authority LIKE '%国税事務所%'
            OR issuing_authority LIKE '%税務署%'
            OR issuing_authority LIKE '%国税庁%'
    """)
    out: set[tuple[str, str, str]] = set()
    for d, n, a in cur.fetchall():
        out.add(((d or "")[:10], _normalize(n or ""), _normalize(a or "")))
    return out


def build_canonical_id(rec: dict[str, Any]) -> str:
    if rec["level"] == "item":
        payload = (
            f"{rec['kyoku']}|{rec['nendo']}|{rec['koubai_no']}|"
            f"{rec['koubai_kind']}|{rec['baikyaku_no']}|{rec['target_name']}"
        )
        h = _hash6(payload)
        return (
            f"enforcement:nta-koubai-{rec['kyoku']}-{rec['nendo']}-"
            f"{rec['koubai_no']}-{rec['baikyaku_no']}-{h}"
        )
    payload = f"{rec['kyoku']}|{rec['nendo']}|{rec['koubai_no']}|koukoku"
    h = _hash6(payload)
    return f"enforcement:nta-koukoku-{rec['kyoku']}-{rec['nendo']}-{rec['koubai_no']}-{h}"


def upsert_record(
    cur: sqlite3.Cursor,
    rec: dict[str, Any],
    now_iso: str,
) -> bool:
    canonical_id = build_canonical_id(rec)
    raw_json = {
        "source": "nta:koubai" if rec["level"] == "item" else "nta:koubai_koukoku",
        "level": rec["level"],
        "kyoku_no": rec["kyoku"],
        "kyoku_name": rec["bureau"],
        "koubai_nendo": rec["nendo"],
        "koubai_no": rec["koubai_no"],
        "koubai_kind": rec["koubai_kind"],
        "baikyaku_no": rec.get("baikyaku_no"),
        "title": rec["title"],
        "target_name": rec["target_name"],
        "issuance_date": rec["issuance_date"],
        "issuance_date_text": rec.get("issuance_date_text"),
        "issuing_authority": rec["issuing_authority"],
        "authority_canonical": rec["authority_canonical"],
        "enforcement_kind": rec["enforcement_kind"],
        "related_law_ref": rec.get("related_law_ref"),
        "amount_yen": rec.get("amount_yen"),
        "reason_summary": rec.get("reason_summary"),
        "shozai": rec.get("shozai"),
        "shubetu": rec.get("shubetu"),
        "koukoku_no": rec.get("koukoku_no"),
        "houshokin": rec.get("houshokin"),
        "source_url": rec["source_url"],
        "license": "出典: 国税庁 公売情報 (koubai.nta.go.jp)",
        "attribution": (f"出典: {rec['issuing_authority']} 公売情報 ({rec['source_url']})"),
        "fetched_at": now_iso,
        "tos_status": (
            "TOS無視/獲得優先 (2026-04-25 user directive); "
            "出典明記し再配布時の責任は AutonoMath 側で負う"
        ),
    }

    cur.execute(
        """INSERT OR IGNORE INTO am_entities
           (canonical_id, record_kind, source_topic, source_record_index,
            primary_name, authority_canonical, confidence, source_url,
            source_url_domain, fetched_at, raw_json)
           VALUES (?, 'enforcement', ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
        (
            canonical_id,
            "nta_koubai" if rec["level"] == "item" else "nta_koubai_koukoku",
            (rec["target_name"] or "")[:255],
            rec["authority_canonical"],
            0.85,
            rec["source_url"],
            "koubai.nta.go.jp",
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
            None,  # 滞納者氏名 = 非開示, 法人番号 = なし
            rec["target_name"][:500],
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


# ----------------------- crawl orchestration -----------------------


def walk_lists(
    fetcher: KoubaiFetcher,
) -> list[tuple[str, str, str, str, str, str]]:
    """Walk all 3 search categories with pagination → unique items.

    Each tuple is (relpath, kyoku, nendo, koubai, kind, baikyaku) where
    relpath embeds the per-category detail page (hp0201/hp0307/hp0411).
    """
    seen_ids: set[tuple[str, str, str, str, str]] = set()
    out: list[tuple[str, str, str, str, str, str]] = []
    for cat, base_url in LIST_URLS.items():
        for page in range(20):
            sep = "&" if "?" in base_url else "?"
            url = f"{base_url}{sep}pageid={page}"
            html = fetcher.get(url)
            if not html:
                break
            tuples = parse_list_page(html)
            if not tuples:
                _LOG.info("[list] %s page=%d empty -> stop", cat, page)
                break
            new = 0
            for t in tuples:
                ids = t[1:]
                if ids not in seen_ids:
                    seen_ids.add(ids)
                    out.append(t)
                    new += 1
            _LOG.info(
                "[list] %s page=%d items=%d new=%d total=%d",
                cat,
                page,
                len(tuples),
                new,
                len(out),
            )
            if new == 0:
                break
    return out


def fetch_details(
    fetcher: KoubaiFetcher,
    item_records: list[tuple[str, str, str, str, str, str]],
    max_items: int,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, t in enumerate(item_records[:max_items], 1):
        relpath = t[0]
        ids = t[1:]
        url = f"{KOUBAI_BASE}/{relpath}"
        html = fetcher.get(url)
        if not html:
            continue
        rec = parse_detail(html, url, ids)
        if rec:
            out.append(rec)
        if i % 25 == 0:
            _LOG.info("[detail] fetched %d / %d items", i, len(item_records))
    _LOG.info("[detail] parsed %d / %d items", len(out), len(item_records))
    return out


# ----------------------- main -----------------------


def run(
    db_path: Path,
    max_rows: int,
    dry_run: bool,
    verbose: bool,
) -> int:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    now_iso = datetime.now(tz=UTC).isoformat(timespec="seconds")

    with KoubaiFetcher() as fetcher:
        ids = walk_lists(fetcher)
        _LOG.info("collected %d unique item id tuples", len(ids))
        items = fetch_details(fetcher, ids, max_items=max_rows)

    if not items:
        _LOG.error("no item records collected — aborting")
        return 0

    # Build aggregate per-公告 records (one per (kyoku,nendo,koubai_no))
    by_koukoku: dict[tuple[str, str, str], dict[str, Any]] = {}
    for it in items:
        key = (it["kyoku"], it["nendo"], it["koubai_no"])
        # keep the earliest 入札期間 date as the publication date
        cur = by_koukoku.get(key)
        if cur is None or it["issuance_date"] < cur["issuance_date"]:
            by_koukoku[key] = it
    koukoku_records = [make_koukoku_record(v) for v in by_koukoku.values()]

    all_records = items + koukoku_records
    _LOG.info(
        "records: items=%d koukoku=%d total=%d", len(items), len(koukoku_records), len(all_records)
    )

    if dry_run:
        for r in all_records[:5]:
            _LOG.info(
                "  sample: %s | %s | %s | %s",
                r["level"],
                r["issuance_date"],
                r["issuing_authority"],
                r["target_name"][:60],
            )
        by_bureau: dict[str, int] = {}
        for r in all_records:
            by_bureau[r["bureau"]] = by_bureau.get(r["bureau"], 0) + 1
        for b, c in sorted(by_bureau.items(), key=lambda kv: -kv[1]):
            _LOG.info("  bureau %s: %d", b, c)
        return len(all_records)

    # Write — BEGIN IMMEDIATE + busy_timeout=300000.
    inserted = 0
    skipped_dup = 0
    skipped_constraint = 0
    by_bureau_inserted: dict[str, int] = {}
    by_kind_inserted: dict[str, int] = {}

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
        raise RuntimeError(f"BEGIN IMMEDIATE failed after 600s: {last_err}")

    BATCH = 50
    con = _open_conn()
    try:
        cur = con.cursor()
        existing = existing_dedup_keys(cur)
        cur.close()

        # Ensure FK targets (12 bureaus) exist in am_authority.
        _begin_immediate(con)
        cur = con.cursor()
        ensure_bureau_authorities(cur)
        cur.close()
        con.execute("COMMIT")
        _LOG.info("ensured 12 NTA bureau authority rows")

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
                        by_bureau_inserted[rec["bureau"]] = (
                            by_bureau_inserted.get(rec["bureau"], 0) + 1
                        )
                        by_kind_inserted[rec["enforcement_kind"]] = (
                            by_kind_inserted.get(rec["enforcement_kind"], 0) + 1
                        )
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
                    by_bureau_inserted[rec["bureau"]] = by_bureau_inserted.get(rec["bureau"], 0) + 1
                    by_kind_inserted[rec["enforcement_kind"]] = (
                        by_kind_inserted.get(rec["enforcement_kind"], 0) + 1
                    )
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
        for b, c in sorted(by_bureau_inserted.items(), key=lambda kv: -kv[1]):
            _LOG.info("  bureau %s inserted: %d", b, c)
        for k, c in sorted(by_kind_inserted.items()):
            _LOG.info("  kind %s inserted: %d", k, c)
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
    ap.add_argument("--max-rows", type=int, default=2000, help="cap on rows inserted in this run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    inserted = run(args.db, args.max_rows, args.dry_run, args.verbose)
    return 0 if (args.dry_run or inserted >= 1) else 1


if __name__ == "__main__":
    sys.exit(main())
