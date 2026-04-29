#!/usr/bin/env python3
"""Ingest MLIT 建築士法 / 宅地建物取引業法 監督処分 records into
``am_enforcement_detail``.

Background:
  The existing MLIT ingester (``ingest_enforcement_mlit.py``) already covers
  建設業 (kensetugyousya), 指名停止 (shimeiteishi), 旅行業 (kankocho xlsx)
  but not the parallel 建築士 / 宅建業 universes which use the same
  nega-inf 検索CGI but with different ``jigyoubunya`` codes and different
  table column layouts.

  Categories walked here (all served by the same search.cgi backend):

    建築士法 / 関連:
      ikkyuu              一級建築士
      siteikakunin        指定確認検査機関
      kentikukijun        建築基準適合判定資格者
      kenchikuchosakensa  建築物調査検査資格者
      siteikouzou         指定構造計算適合性判定機関
      kouzoukeisan        構造計算適合性判定資格者
      tourokujuutaku      登録住宅性能評価機関

    宅地建物取引業法 / 関連:
      takuti              宅地建物取引業者     ← primary 宅建業 feed
      mansyon             マンション管理業者 (建物の区分所有等に関する法律)
      tintai              賃貸住宅管理業者     (賃貸住宅の管理業務等の適正化法)

  二級建築士 / 木造建築士 are 都道府県知事登録なので 国交省CGI には載らず、
  pref_shimei_teishi 系の別系統に乗る — this script does not target them.

Per-category column layouts (head -A20 of the result table):

  ikkyuu (4 cols):
    date / name+(登録番号) / punish / detail
    →  被処分者 = 個人 (建築士). issuer = 国交省 (中央) or 整備局 (地整).
    →  名前は実名公開 (建築士法第10条). Houjin = NULL. PII OK because
       公的処分情報.

  takuti (6 cols):
    date / 処分等を行った者 / name+(法人番号) / address / punish / detail
    →  処分庁 = 都道府県知事 (大半) or 国交大臣 (大規模業者).
    →  Houjin captured if 13-digit span present.

  mansyon / tintai (similar 6-col tables).

  siteikakunin / kentikukijun / kouzoukeisan etc. = 4-col like ikkyuu.

Schema mapping (am_enforcement_detail.enforcement_kind CHECK):
    免許取消 / 登録取消        → license_revoke
    業務停止                    → business_improvement
    戒告 / 指示 / 行政指導     → other / business_improvement
    監督処分 (catch-all)        → other

related_law_ref:
  ikkyuu / kentikukijun / siteikakunin / kenchikuchosakensa
  / siteikouzou / kouzoukeisan / tourokujuutaku  → 建築士法 (or 該当業法)
  takuti                                          → 宅地建物取引業法
  mansyon                                         → マンションの管理の適正化の推進に関する法律
  tintai                                          → 賃貸住宅の管理業務等の適正化に関する法律

issuing_authority:
  takuti/mansyon/tintai     ← parsed from 処分等を行った者 column
                              (e.g. "群馬県" → "群馬県" / "国土交通大臣"
                              → "国土交通省")
  ikkyuu / 建築士関連       ← "国土交通省" (default) — 個人建築士の処分
                              は国交大臣 OR 整備局長. We surface "国土交通省"
                              for top level; integrity 大臣 fingering goes
                              into raw_json.

Detail page (overview only) provides 根拠法令 prose; we fetch it for the
first ~150 rows then skip detail to keep total run time bounded for
T-11d launch.

Parallel-write contract:
  - BEGIN IMMEDIATE
  - PRAGMA busy_timeout = 300000
  - 50-row periodic commit
  - dedup against existing am_enforcement_detail (target_name + issuance_date
    + enforcement_kind + entity_id_prefix='enforcement:mlit') so we don't
    collide with kensetugyousya rows already inserted.

Stop condition: --stop-at INSERTED (default 500).

CLI:
    python scripts/ingest/ingest_enforcement_mlit_kenchikushi_takken.py \
        --db autonomath.db [--stop-at 500] [--dry-run] [--verbose]
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
from typing import Any

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    sys.exit(f"httpx required: {exc}")


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "autonomath.db"

_LOG = logging.getLogger("autonomath.ingest.mlit_kenchikushi_takken")

MLIT_SEARCH_URL = "https://www.mlit.go.jp/nega-inf/cgi-bin/search.cgi"
USER_AGENT = (
    "jpintel-mcp-ingest/1.0 "
    "(+https://zeimu-kaikei.ai; contact=ops@zeimu-kaikei.ai)"
)

PER_REQUEST_DELAY_SEC = 0.7
HTTP_TIMEOUT_SEC = 30.0
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Category metadata
# ---------------------------------------------------------------------------

# kind="kenchikushi" → 建築士法 universe
# kind="takken"     → 宅建業法 universe
CATEGORIES: dict[str, dict[str, str]] = {
    # 建築士関連 (個人 / 4-column tables)
    "ikkyuu": {
        "kind": "kenchikushi",
        "label": "一級建築士",
        "law": "建築士法",
        "table_cols": "4",
    },
    "siteikakunin": {
        "kind": "kenchikushi",
        "label": "指定確認検査機関",
        "law": "建築基準法",
        "table_cols": "4",
    },
    "kentikukijun": {
        "kind": "kenchikushi",
        "label": "建築基準適合判定資格者",
        "law": "建築基準法",
        "table_cols": "4",
    },
    "kenchikuchosakensa": {
        "kind": "kenchikushi",
        "label": "建築物調査検査資格者",
        "law": "建築基準法",
        "table_cols": "4",
    },
    "siteikouzou": {
        "kind": "kenchikushi",
        "label": "指定構造計算適合性判定機関",
        "law": "建築基準法",
        "table_cols": "4",
    },
    "kouzoukeisan": {
        "kind": "kenchikushi",
        "label": "構造計算適合性判定資格者",
        "law": "建築基準法",
        "table_cols": "4",
    },
    "tourokujuutaku": {
        "kind": "kenchikushi",
        "label": "登録住宅性能評価機関",
        "law": "住宅の品質確保の促進等に関する法律",
        "table_cols": "4",
    },
    # 宅建業関連 (法人 / 6-column tables)
    "takuti": {
        "kind": "takken",
        "label": "宅地建物取引業者",
        "law": "宅地建物取引業法",
        "table_cols": "6",
    },
    "mansyon": {
        "kind": "takken",
        "label": "マンション管理業者",
        "law": "マンションの管理の適正化の推進に関する法律",
        "table_cols": "6",
    },
    "tintai": {
        "kind": "takken",
        "label": "賃貸住宅管理業者",
        "law": "賃貸住宅の管理業務等の適正化に関する法律",
        "table_cols": "6",
    },
}

# 処分等の種類 → am_enforcement_detail.enforcement_kind enum
PUNISH_KIND_MAP: dict[str, str] = {
    "免許取消": "license_revoke",
    "登録取消": "license_revoke",
    "登録の取消し": "license_revoke",
    "業務停止": "business_improvement",
    "戒告": "other",
    "指示": "business_improvement",
    "行政指導": "business_improvement",
    "監督処分": "other",
}

DEFAULT_ISSUING_AUTHORITY = "国土交通省"

# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

RESULT_COUNT_RE = re.compile(
    r'<h3 class="title">検索結果：\s*(\d+)\s*件</h3>'
)

# 4-col row (建築士関連): date / name(+登録番号 in span) / punish / detail
ROW_RE_4COL = re.compile(
    r'<tr>\s*<td class="date">([^<]+)</td>'
    r'\s*<td class="name">([^<]+?)(?:<span>（([^）]*)）</span>)?</td>'
    r'\s*<td class="punish">([^<]+)</td>'
    r'\s*<td class="detail">(.*?)</td>\s*</tr>',
    re.DOTALL,
)

# 6-col row (宅建業関連): date / agency / name(+法人番号) / address / punish / detail
ROW_RE_6COL = re.compile(
    r'<tr>\s*<td class="date">([^<]+)</td>'
    r'\s*<td class="date">([^<]+)</td>'
    r'\s*<td class="name">([^<]+?)(?:<span>（([^）]*)）</span>)?</td>'
    r'\s*<td class="address">([^<]*)</td>'
    r'\s*<td class="punish">([^<]+)</td>'
    r'\s*<td class="detail">(.*?)</td>\s*</tr>',
    re.DOTALL,
)

# Detail anchor inside <td class="detail">...
OVERVIEW_HREF_RE = re.compile(
    r'<a[^>]+class="overview"[^>]+href="([^"]+)"'
)
DETAIL_HREF_RE = re.compile(
    r'<a[^>]+class="details"[^>]+href="([^"]+)"'
)

# Detail page dt/dd pair
DL_RE = re.compile(
    r'<dt class="title">([^<]+)</dt><dd class="text">([^<]*)</dd>',
    re.DOTALL,
)

DATE_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
HOUJIN_13_RE = re.compile(r"\d{13}")


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------


class MlitHttpClient:
    """Lightweight rate-limited httpx wrapper (1 req/host/sec)."""

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
        delta = time.monotonic() - self._last_fetch
        if delta < PER_REQUEST_DELAY_SEC:
            time.sleep(PER_REQUEST_DELAY_SEC - delta)
        self._last_fetch = time.monotonic()

    def get(self, url: str) -> tuple[int, str]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.get(url)
                return r.status_code, r.text
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    break
                time.sleep(2 ** attempt)
        _LOG.warning("GET failed url=%s err=%s", url, last_exc)
        return 0, ""

    def post(self, url: str, data: dict[str, str]) -> tuple[int, str]:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            self._pace()
            try:
                r = self._client.post(url, data=data)
                return r.status_code, r.text
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    break
                time.sleep(2 ** attempt)
        _LOG.warning("POST failed url=%s err=%s", url, last_exc)
        return 0, ""

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class EnfRow:
    category: str               # ikkyuu / takuti / ...
    kind: str                   # kenchikushi / takken
    target_name: str
    houjin_bangou: str | None   # 13-digit (only for 法人, takken side)
    address: str | None
    issuance_date: str          # ISO yyyy-mm-dd
    issuing_authority: str
    punishment_raw: str
    enforcement_kind: str       # mapped enum
    related_law_ref: str
    overview_url: str           # search.cgi?jigyoubunya=...&no=...
    external_detail_url: str | None  # 詳細 anchor (pref site / press release)
    register_no: str | None     # 建築士登録番号 (for ikkyuu) — span content
    reason_summary: str | None = None  # filled from detail page if fetched
    period_raw: str | None = None
    detail_law_ref: str | None = None  # 根拠法令 from detail page

    @property
    def source_url(self) -> str:
        return self.overview_url


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def ja_date_to_iso(s: str) -> str | None:
    m = DATE_RE.search(s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def map_enforcement_kind(punish: str) -> str:
    p = punish.strip()
    if p in PUNISH_KIND_MAP:
        return PUNISH_KIND_MAP[p]
    for kw, k in PUNISH_KIND_MAP.items():
        if kw in p:
            return k
    return "other"


def _abs_overview(href: str) -> str:
    href = href.strip()
    if href.startswith("http"):
        return href
    return "https://www.mlit.go.jp/nega-inf/cgi-bin/" + href.lstrip("/")


def _extract_overview_url(td_inner: str) -> str | None:
    m = OVERVIEW_HREF_RE.search(td_inner)
    if not m:
        return None
    return _abs_overview(m.group(1))


def _extract_external_detail_url(td_inner: str) -> str | None:
    m = DETAIL_HREF_RE.search(td_inner)
    if not m:
        return None
    return m.group(1).strip()


def _normalize_authority(raw: str) -> str:
    """`大阪府` → `大阪府`. `国土交通大臣` → `国土交通省`. Empty → default."""
    s = raw.strip()
    if not s:
        return DEFAULT_ISSUING_AUTHORITY
    if "国土交通大臣" in s or "大臣" in s:
        return DEFAULT_ISSUING_AUTHORITY
    if "整備局" in s:
        return f"国土交通省 {s}"
    return s


def parse_list_page(html: str, *, cols: int) -> tuple[int | None, list[dict[str, Any]]]:
    """Return (total_count, rows). cols ∈ {4, 6}."""
    total: int | None = None
    m = RESULT_COUNT_RE.search(html)
    if m:
        total = int(m.group(1))

    rows: list[dict[str, Any]] = []
    if cols == 4:
        for rm in ROW_RE_4COL.finditer(html):
            date_ja = rm.group(1).strip()
            name = rm.group(2).strip()
            span = (rm.group(3) or "").strip()
            punish = rm.group(4).strip()
            td_detail = rm.group(5)
            rows.append({
                "date_ja": date_ja,
                "agency_raw": "",
                "target_name": name,
                "span": span,
                "address": "",
                "punish": punish,
                "td_detail": td_detail,
            })
    elif cols == 6:
        for rm in ROW_RE_6COL.finditer(html):
            date_ja = rm.group(1).strip()
            agency = rm.group(2).strip()
            name = rm.group(3).strip()
            span = (rm.group(4) or "").strip()
            address = rm.group(5).strip()
            punish = rm.group(6).strip()
            td_detail = rm.group(7)
            rows.append({
                "date_ja": date_ja,
                "agency_raw": agency,
                "target_name": name,
                "span": span,
                "address": address,
                "punish": punish,
                "td_detail": td_detail,
            })
    return total, rows


def normalize_row(
    raw: dict[str, Any],
    *,
    category: str,
) -> EnfRow | None:
    meta = CATEGORIES[category]
    iso = ja_date_to_iso(raw["date_ja"])
    if not iso:
        return None
    target = raw["target_name"].strip()
    span = (raw.get("span") or "").strip()
    span_digits = "".join(ch for ch in span if ch.isdigit())

    houjin: str | None = None
    register_no: str | None = None
    if meta["table_cols"] == "6":
        if HOUJIN_13_RE.fullmatch(span_digits):
            houjin = span_digits
    else:
        # 4-col → span is 建築士登録番号 / 機関番号 / etc.
        if span:
            register_no = span

    punishment = raw["punish"].strip()
    kind = map_enforcement_kind(punishment)
    issuer_raw = raw.get("agency_raw") or ""
    if meta["table_cols"] == "6":
        issuing_authority = _normalize_authority(issuer_raw)
    else:
        # 建築士関連 — 国交省 (本省 or 整備局)。詳細URL から見ると「国交省」で
        # 統一 OK.
        issuing_authority = DEFAULT_ISSUING_AUTHORITY

    overview_url = _extract_overview_url(raw["td_detail"])
    if not overview_url:
        return None
    ext_detail = _extract_external_detail_url(raw["td_detail"])

    return EnfRow(
        category=category,
        kind=meta["kind"],
        target_name=target,
        houjin_bangou=houjin,
        address=raw.get("address") or None,
        issuance_date=iso,
        issuing_authority=issuing_authority,
        punishment_raw=punishment,
        enforcement_kind=kind,
        related_law_ref=meta["law"],
        overview_url=overview_url,
        external_detail_url=ext_detail,
        register_no=register_no,
    )


def fetch_detail(http: MlitHttpClient, url: str) -> dict[str, str]:
    """Fetch overview detail and return dt/dd dict."""
    status, html = http.get(url)
    if status != 200:
        return {}
    out: dict[str, str] = {}
    for m in DL_RE.finditer(html):
        k = m.group(1).strip()
        v = m.group(2).strip()
        out[k] = v
    return out


def enrich_detail(http: MlitHttpClient, row: EnfRow) -> None:
    """Mutate row with detail-page fields. Best effort."""
    d = fetch_detail(http, row.overview_url)
    if not d:
        return
    row.detail_law_ref = d.get("根拠法令") or None
    row.period_raw = d.get("処分等の期間") or None
    # Build reason_summary so the row is searchable.
    parts: list[str] = []
    pname = d.get("被処分者名") or d.get("事業者名") or ""
    if pname:
        parts.append(f"被処分者: {pname}")
    if row.detail_law_ref:
        parts.append(f"根拠法令: {row.detail_law_ref}")
    if row.period_raw:
        parts.append(f"期間: {row.period_raw}")
    parts.append(f"処分種別: {row.punishment_raw}")
    if d.get("処分等の内容"):
        parts.append(f"内容: {d['処分等の内容'][:200]}")
    if d.get("処分の原因となった事実"):
        parts.append(f"原因: {d['処分の原因となった事実'][:300]}")
    row.reason_summary = " / ".join(parts)[:1500]
    if row.detail_law_ref and row.detail_law_ref not in row.related_law_ref:
        # detail-page 根拠法令 is more precise — append as suffix.
        row.related_law_ref = (
            f"{row.related_law_ref} ({row.detail_law_ref})"
        )[:200]


def walk_year(
    http: MlitHttpClient,
    category: str,
    year: int,
) -> list[EnfRow]:
    meta = CATEGORIES[category]
    cols = int(meta["table_cols"])
    form = {
        "jigyoubunya": category,
        "EID": "search",
        "start_year": str(year),
        "start_month": "1",
        "end_year": str(year),
        "end_month": "12",
        "shobun": "",
    }
    if cols == 6:
        form["pref"] = ""
        form["jigyousya"] = ""
    else:
        form["jigyousya"] = ""

    status, html = http.post(MLIT_SEARCH_URL, form)
    if status != 200:
        _LOG.warning("cat=%s year=%d POST status=%s", category, year, status)
        return []
    total, rows = parse_list_page(html, cols=cols)
    if total is None:
        _LOG.warning("cat=%s year=%d no total found", category, year)
        return []
    if total == 0:
        return []

    out: list[EnfRow] = []
    for r in rows:
        norm = normalize_row(r, category=category)
        if norm is not None:
            out.append(norm)
    if total <= len(rows):
        return out

    pages = (total + 9) // 10
    for page in range(2, pages + 1):
        qs = dict(form)
        qs["page"] = str(page)
        url = MLIT_SEARCH_URL + "?" + urllib.parse.urlencode(qs)
        status, html = http.get(url)
        if status != 200:
            _LOG.warning("cat=%s year=%d page=%d GET status=%s",
                         category, year, page, status)
            break
        _, prows = parse_list_page(html, cols=cols)
        for r in prows:
            n = normalize_row(r, category=category)
            if n is not None:
                out.append(n)
    return out


# ---------------------------------------------------------------------------
# DB layer
# ---------------------------------------------------------------------------


def open_db(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"DB missing: {path}")
    conn = sqlite3.connect(str(path), timeout=300.0)
    conn.execute("PRAGMA busy_timeout = 300000")
    conn.execute("PRAGMA foreign_keys = ON")
    row = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='am_enforcement_detail'"
    ).fetchone()
    if not row:
        conn.close()
        raise SystemExit("am_enforcement_detail missing")
    return conn


def load_dedup(conn: sqlite3.Connection) -> set[tuple[str, str, str]]:
    out: set[tuple[str, str, str]] = set()
    for r in conn.execute(
        "SELECT IFNULL(target_name,''), issuance_date, "
        "       IFNULL(enforcement_kind,'') "
        "  FROM am_enforcement_detail"
    ):
        if r[0] and r[1]:
            out.add((r[0], r[1], r[2]))
    return out


def make_canonical_id(row: EnfRow) -> str:
    """Stable ID. Compatible naming with existing kensetugyousya rows
    (`enforcement:mlit:DATE:KEY:KIND:HASH`)."""
    if row.houjin_bangou:
        key = row.houjin_bangou
    elif row.register_no:
        # Distinguish 建築士 個人 namespace from generic hash.
        key = f"r{row.register_no}"
    else:
        key = hashlib.sha1(row.target_name.encode("utf-8")).hexdigest()[:12]
    punish_hash = hashlib.sha1(row.punishment_raw.encode("utf-8")).hexdigest()[:6]
    return (
        f"enforcement:mlit:{row.issuance_date}:{key}:"
        f"{row.enforcement_kind}:{punish_hash}"
    )


def upsert(
    conn: sqlite3.Connection,
    row: EnfRow,
    fetched_at: str,
) -> str:
    canonical_id = make_canonical_id(row)
    raw_json = {
        "category": row.category,
        "kind": row.kind,
        "category_label": CATEGORIES[row.category]["label"],
        "target_name": row.target_name,
        "houjin_bangou": row.houjin_bangou,
        "register_no": row.register_no,
        "address": row.address,
        "issuance_date": row.issuance_date,
        "issuing_authority": row.issuing_authority,
        "punishment_raw": row.punishment_raw,
        "enforcement_kind": row.enforcement_kind,
        "related_law_ref": row.related_law_ref,
        "detail_law_ref": row.detail_law_ref,
        "period_raw": row.period_raw,
        "reason_summary": row.reason_summary,
        "overview_url": row.overview_url,
        "external_detail_url": row.external_detail_url,
        "fetched_at": fetched_at,
        "source": "mlit_nega_inf",
        "source_attribution": "国土交通省 ネガティブ情報等検索サイト",
        "license": "政府機関の著作物（出典明記で転載引用可）",
    }
    src_url = row.overview_url
    src_domain = urllib.parse.urlparse(src_url).netloc

    cur = conn.execute(
        """INSERT OR IGNORE INTO am_entities (
            canonical_id, record_kind, source_topic, primary_name,
            confidence, source_url, source_url_domain, fetched_at, raw_json
        ) VALUES (?, 'enforcement', ?, ?, 0.95, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            f"mlit_{row.category}",
            row.target_name[:500],
            src_url,
            src_domain,
            fetched_at,
            json.dumps(raw_json, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    inserted_entity = cur.rowcount > 0

    existing = conn.execute(
        "SELECT enforcement_id FROM am_enforcement_detail WHERE entity_id=?",
        (canonical_id,),
    ).fetchone()
    if existing:
        return "skip"

    conn.execute(
        """INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, reason_summary,
            related_law_ref, source_url, source_fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            canonical_id,
            row.houjin_bangou,
            row.target_name[:500],
            row.enforcement_kind,
            row.issuing_authority,
            row.issuance_date,
            (row.reason_summary or
             f"{CATEGORIES[row.category]['law']}に基づく{row.punishment_raw}"
             f"（{CATEGORIES[row.category]['label']}）"
             )[:4000],
            row.related_law_ref[:1000],
            src_url,
            fetched_at,
        ),
    )
    return "insert" if inserted_entity else "update"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


# Default walk order: prioritize categories with known volume so we hit
# the +500 stop quickly and have time left for enrichment of remaining rows.
DEFAULT_CATEGORY_ORDER = (
    "takuti",        # 246+ rows over 5y
    "ikkyuu",        # 125+
    "kentikukijun",  # 48
    "siteikakunin",  # 36
    "mansyon",       # 16
    "tintai",        # 6
    "kenchikuchosakensa",
    "siteikouzou",
    "kouzoukeisan",
    "tourokujuutaku",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--year-from", type=int, default=2021)
    ap.add_argument("--year-to", type=int, default=2025)
    ap.add_argument(
        "--categories",
        type=str,
        default=",".join(DEFAULT_CATEGORY_ORDER),
        help="comma-separated jigyoubunya codes",
    )
    ap.add_argument("--stop-at", type=int, default=500,
                    help="stop after N inserts (default 500)")
    ap.add_argument("--enrich-detail", action="store_true",
                    help="also fetch overview detail page (slow)")
    ap.add_argument("--enrich-cap", type=int, default=120,
                    help="cap on number of rows to enrich with detail")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    unknown = [c for c in cats if c not in CATEGORIES]
    if unknown:
        _LOG.error("unknown categories: %s (allowed=%s)",
                   unknown, list(CATEGORIES))
        return 2

    fetched_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    http = MlitHttpClient()
    conn: sqlite3.Connection | None = None
    if not args.dry_run:
        conn = open_db(args.db)
        conn.execute("BEGIN IMMEDIATE")
    dedup = load_dedup(conn) if conn is not None else set()

    walked = 0
    inserted = 0
    skipped_db = 0
    skipped_batch = 0
    detail_count = 0
    by_law: dict[str, int] = {"建築士法系": 0, "宅地建物取引業法系": 0}
    by_authority: dict[str, int] = {}
    samples: list[EnfRow] = []
    batch_keys: set[tuple[str, str, str]] = set()

    try:
        for cat in cats:
            if inserted >= args.stop_at:
                break
            for year in range(args.year_to, args.year_from - 1, -1):
                if inserted >= args.stop_at:
                    break
                rows = walk_year(http, cat, year)
                walked += len(rows)
                _LOG.info(
                    "walk cat=%s year=%d -> %d rows (running insert=%d)",
                    cat, year, len(rows), inserted,
                )
                if not rows:
                    continue
                for row in rows:
                    if inserted >= args.stop_at:
                        break
                    key = (row.target_name, row.issuance_date,
                           row.enforcement_kind)
                    if key in dedup:
                        skipped_db += 1
                        continue
                    if key in batch_keys:
                        skipped_batch += 1
                        continue
                    batch_keys.add(key)

                    if args.enrich_detail and detail_count < args.enrich_cap:
                        try:
                            enrich_detail(http, row)
                            detail_count += 1
                        except Exception as exc:  # noqa: BLE001
                            _LOG.debug(
                                "enrich fail %s: %s", row.overview_url, exc,
                            )

                    if conn is None:
                        # dry-run path
                        inserted += 1
                        verdict = "DRY"
                    else:
                        try:
                            verdict = upsert(conn, row, fetched_at)
                        except sqlite3.Error as exc:
                            _LOG.error(
                                "DB upsert fail name=%r date=%s: %s",
                                row.target_name, row.issuance_date, exc,
                            )
                            continue
                        if verdict in ("insert", "update"):
                            inserted += 1
                        elif verdict == "skip":
                            skipped_db += 1
                            continue

                    # Stats
                    if CATEGORIES[row.category]["kind"] == "kenchikushi":
                        by_law["建築士法系"] += 1
                    else:
                        by_law["宅地建物取引業法系"] += 1
                    by_authority[row.issuing_authority] = (
                        by_authority.get(row.issuing_authority, 0) + 1
                    )
                    if len(samples) < 6:
                        samples.append(row)

                    if conn is not None and inserted % 50 == 0:
                        conn.commit()
                        conn.execute("BEGIN IMMEDIATE")
    finally:
        http.close()
        if conn is not None:
            try:
                conn.commit()
            except sqlite3.Error:
                pass
            conn.close()

    print("=" * 70)
    print(
        f"MLIT 建築士法/宅建業法 ingest: walked={walked} "
        f"inserted={inserted} dup_db={skipped_db} dup_batch={skipped_batch} "
        f"detail_fetched={detail_count}"
    )
    print(f"by_law: {json.dumps(by_law, ensure_ascii=False)}")
    print(
        f"by_issuing_authority (top 15): {json.dumps(dict(sorted(by_authority.items(), key=lambda kv: -kv[1])[:15]), ensure_ascii=False)}"
    )
    print("samples:")
    for s in samples[:5]:
        print(
            f"  - [{s.category}/{s.kind}] {s.issuance_date} | "
            f"{s.target_name} | {s.punishment_raw} → {s.enforcement_kind} | "
            f"law={s.related_law_ref} | auth={s.issuing_authority} | "
            f"houjin={s.houjin_bangou or '-'} | "
            f"overview={s.overview_url}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
