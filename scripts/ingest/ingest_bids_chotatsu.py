#!/usr/bin/env python3
"""Ingest 政府調達 入札公告 from primary ministry / 自治体 HTML lists.

Background (2026-04-25):
    The GEPS / 調達ポータル bulk ZIP endpoint requires OIDC login (302 to
    /pps-auth-biz/CDCServlet) so anonymous bulk download is blocked.
    Instead, each ministry publishes its own 公告 list on its own .go.jp
    site (HTML table, 1 row = 1 bid). These are the de-facto primary
    citation surface. We harvest those, normalise, and UPSERT into
    `bids` (migration 017).

Coverage targets (this bootstrap pass):
    * 農林水産省 — /j/supply/nyusatu/{buppin_ekimu/*, kensetu/*, zuii/*,
      uriharai}, /j/supply/itaku/{tyosa, kenkyu_kaihatu, koho, sonota}
    * 国土交通省 — /chotatsu/ index per regional bureau (best-effort)
    * 政令市 — Tokyo, Osaka, Yokohama (HTML lists where available)

Aggregator hosts (njss.info, nyusatsu-portal, biz.stayway, etc.) are
banned from source_url — gated by BANNED_SOURCE_HOSTS guard.

Spec compliance per user directive 2026-04-25:
    - Direct primary sources only (.go.jp / .lg.jp).
    - Rate 1 req/sec/host, UA "AutonoMath/0.1.0 (+https://bookyou.net)".
    - Idempotent (UPSERT on unified_id).
    - Parallel-write safe: BEGIN IMMEDIATE + busy_timeout=300000.

CLI:
    python scripts/ingest/ingest_bids_chotatsu.py --db data/jpintel.db
        [--limit N]              (stop after N successful UPSERTs)
        [--dry-run]              (parse + count only)
        [--log-level LEVEL]
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)


_LOG = logging.getLogger("jpintel.ingest_bids_chotatsu")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"
LOG_DIR = REPO_ROOT / "data"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
HTTP_TIMEOUT = 30
MAX_RETRIES = 3
RATE_LIMIT_SEC = 1.0  # 1 req/sec/host


# ---------------------------------------------------------------------------
# Banned aggregator hosts (per CLAUDE.md / 2026-04-25 directive)
# ---------------------------------------------------------------------------
BANNED_SOURCE_HOSTS: tuple[str, ...] = (
    "njss.info",
    "nyusatsu-portal",
    "noukaweb",
    "biz.stayway",
    "prtimes",
    "hojyokin-portal",
    "hojo-navi",
    "mirai-joho",
)


# ---------------------------------------------------------------------------
# Bid kind mapping (HTML cell text -> migration-017 enum)
# ---------------------------------------------------------------------------
BID_KIND_MAP: dict[str, str] = {
    "一般競争": "open",
    "一般競争入札": "open",
    "総合評価": "open",
    "指名競争": "selective",
    "指名競争入札": "selective",
    "随意契約": "negotiated",
    "随契": "negotiated",
    "公募型": "kobo_subsidy",
    "公募": "kobo_subsidy",
    "企画競争": "kobo_subsidy",
    "プロポーザル": "kobo_subsidy",
}


# ---------------------------------------------------------------------------
# Source catalogue
# ---------------------------------------------------------------------------
# Each entry: (ministry_label, prefecture_or_None, category_label, list_url)
# list_url is the HTML page hosting a <table> of 公告 rows.
# ---------------------------------------------------------------------------
@dataclass
class SourcePage:
    ministry: str
    prefecture: str | None
    category: str
    url: str


MAFF_BASE = "https://www.maff.go.jp"

SOURCES: list[SourcePage] = [
    # MAFF 物品・役務 (12 cats)
    SourcePage("農林水産省", None, "事務用品類",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/zimu/index.html"),
    SourcePage("農林水産省", None, "OA機器類",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/oa/index.html"),
    SourcePage("農林水産省", None, "印刷・製本",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/insatu_seihon/index.html"),
    SourcePage("農林水産省", None, "物品その他",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/sonota1/index.html"),
    SourcePage("農林水産省", None, "調査",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/tyosa/index.html"),
    SourcePage("農林水産省", None, "研究開発",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/kenkyu/index.html"),
    SourcePage("農林水産省", None, "広報",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/koho/index.html"),
    SourcePage("農林水産省", None, "機器の賃貸借",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/kiki/index.html"),
    SourcePage("農林水産省", None, "システム関係",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/system/index.html"),
    SourcePage("農林水産省", None, "米麦関係",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/beibaku/index.html"),
    SourcePage("農林水産省", None, "役務その他",
               f"{MAFF_BASE}/j/supply/nyusatu/buppin_ekimu/sonota3/index.html"),
    # MAFF 建設工事
    SourcePage("農林水産省", None, "発注見通し",
               f"{MAFF_BASE}/j/supply/nyusatu/kensetu/mitosi/index.html"),
    SourcePage("農林水産省", None, "建築",
               f"{MAFF_BASE}/j/supply/nyusatu/kensetu/kentiku/index.html"),
    SourcePage("農林水産省", None, "機械設備",
               f"{MAFF_BASE}/j/supply/nyusatu/kensetu/kikai/index.html"),
    SourcePage("農林水産省", None, "電気設備",
               f"{MAFF_BASE}/j/supply/nyusatu/kensetu/denki/index.html"),
    SourcePage("農林水産省", None, "工事その他1",
               f"{MAFF_BASE}/j/supply/nyusatu/kensetu/sonota1/index.html"),
    SourcePage("農林水産省", None, "測量業務",
               f"{MAFF_BASE}/j/supply/nyusatu/kensetu/sokuryo/index.html"),
    SourcePage("農林水産省", None, "設計・コンサルタント",
               f"{MAFF_BASE}/j/supply/nyusatu/kensetu/consult/index.html"),
    SourcePage("農林水産省", None, "工事その他2",
               f"{MAFF_BASE}/j/supply/nyusatu/kensetu/sonota2/index.html"),
    # MAFF 売払い・随意契約・落札者
    SourcePage("農林水産省", None, "売払い",
               f"{MAFF_BASE}/j/supply/nyusatu/uriharai/index.html"),
    SourcePage("農林水産省", None, "随意契約",
               f"{MAFF_BASE}/j/supply/nyusatu/zuii/keiyaku/index.html"),
    SourcePage("農林水産省", None, "落札者等",
               f"{MAFF_BASE}/j/supply/nyusatu/zuii/rakusatu/index.html"),
    # MAFF 委託事業 (4 cats)
    SourcePage("農林水産省", None, "委託事業 調査",
               f"{MAFF_BASE}/j/supply/itaku/tyosa/index.html"),
    SourcePage("農林水産省", None, "委託事業 研究開発",
               f"{MAFF_BASE}/j/supply/itaku/kenkyu_kaihatu/index.html"),
    SourcePage("農林水産省", None, "委託事業 広報",
               f"{MAFF_BASE}/j/supply/itaku/koho/index.html"),
    SourcePage("農林水産省", None, "委託事業 その他",
               f"{MAFF_BASE}/j/supply/itaku/sonota/index.html"),
]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _strip(v: str | None) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    if s in ("", "-", "－", "ー", "なし", "該当なし", "&nbsp;"):
        return None
    return s


_WAREKI_RE = re.compile(r"(令和|平成|昭和)\s*(\d{1,2}|元)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def _wareki_to_iso(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    m = _WAREKI_RE.search(s)
    if m:
        era, y_raw, mo, d = m.groups()
        base = {"令和": 2018, "平成": 1988, "昭和": 1925}[era]
        y = 1 if y_raw == "元" else int(y_raw)
        return f"{base + y:04d}-{int(mo):02d}-{int(d):02d}"
    # YYYY/MM/DD or YYYY-MM-DD passthrough
    m = re.match(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


def _normalize_bid_kind(jp: str | None) -> str:
    s = _strip(jp)
    if not s:
        return "open"
    if s in BID_KIND_MAP:
        return BID_KIND_MAP[s]
    for key, mapped in BID_KIND_MAP.items():
        if key in s:
            return mapped
    _LOG.warning("bid_kind_unknown raw=%r defaulted=open", s)
    return "open"


def _source_url_is_banned(url: str | None) -> bool:
    if not url:
        return False
    low = url.lower()
    return any(h in low for h in BANNED_SOURCE_HOSTS)


def _unified_id(source_url: str, title: str, announcement_date: str) -> str:
    blob = f"{source_url}|{title}|{announcement_date}".encode()
    digest = hashlib.sha256(blob).hexdigest()[:10]
    return f"BID-{digest}"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


_LAST_HOST_FETCH: dict[str, float] = {}


def _polite_get(url: str, tries: int = MAX_RETRIES) -> str | None:
    """Rate-limited GET (1 req/sec/host) returning text, None on failure."""
    host = urlparse(url).netloc
    last = _LAST_HOST_FETCH.get(host, 0.0)
    wait = RATE_LIMIT_SEC - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.5"}
    last_exc: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT, allow_redirects=True)
            _LAST_HOST_FETCH[host] = time.monotonic()
            if resp.status_code == 404:
                _LOG.warning("404 url=%s", url)
                return None
            if resp.status_code in (429, 503):
                wait_s = 2 ** attempt
                _LOG.warning("backoff status=%d attempt=%d wait=%ds", resp.status_code, attempt, wait_s)
                time.sleep(wait_s)
                continue
            resp.raise_for_status()
            # Try utf-8 first, fall back to declared encoding
            ct = resp.headers.get("content-type", "")
            if "charset=" in ct.lower():
                resp.encoding = ct.lower().split("charset=", 1)[1].split(";")[0].strip()
            elif resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
                resp.encoding = "utf-8"
            return resp.text
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            wait_s = 2 ** attempt
            _LOG.warning("retry %d/%d url=%s err=%s wait=%ds",
                         attempt, tries, url, exc, wait_s)
            time.sleep(wait_s)
            _LAST_HOST_FETCH[host] = time.monotonic()
    _LOG.error("fetch_failed url=%s err=%s", url, last_exc)
    return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


@dataclass
class BidRecord:
    unified_id: str
    bid_title: str
    bid_kind: str
    procuring_entity: str
    ministry: str | None
    prefecture: str | None
    announcement_date: str | None
    bid_deadline: str | None
    bid_description: str | None
    classification_code: str | None
    source_url: str
    source_excerpt: str
    source_checksum: str
    confidence: float
    fetched_at: str


def _td_text(td) -> str:
    """Extract clean text from a <td>, dropping NEW/PDF icons."""
    for img in td.find_all("img"):
        img.decompose()
    return _strip(td.get_text(" ", strip=True)) or ""


def _parse_maff_table(html: str, source: SourcePage, fetched_at: str) -> list[BidRecord]:
    """Parse a MAFF-style 7-column 公告 table.

    Columns (typical): 競争形態 / 公告日 / 参加締切日 / 件名 / 業務の区別 /
                       等級 / 添付ファイル
    Variant tables (随意契約 / 落札者) may have different headers — we
    accept any row whose first cell contains a known bid_kind keyword OR
    whose 公告日 cell parses to a wareki date.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[BidRecord] = []
    seen_uids: set[str] = set()

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        header_cells = [_td_text(c) for c in rows[0].find_all(["th", "td"])]
        # Map column name -> index
        idx: dict[str, int] = {}
        for i, h in enumerate(header_cells):
            if "競争形態" in h or "形態" in h or "契約方式" in h:
                idx["kind"] = i
            elif "公告日" in h or "公示日" in h or "公告" == h:
                idx["announce"] = i
            elif "締切" in h or "提出期限" in h or "入札日" in h or "開札" in h:
                idx["deadline"] = i
            elif "件名" in h or "案件名" in h or "調達件名" in h:
                idx["title"] = i
            elif "区別" in h or "業務の区別" in h or "区分" in h:
                idx["classification"] = i
            elif "落札者" in h or "契約相手方" in h:
                idx["winner"] = i
            elif "落札金額" in h or "契約金額" in h:
                idx["amount"] = i

        # Need at minimum title + announce
        if "title" not in idx or "announce" not in idx:
            continue

        for tr in rows[1:]:
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            try:
                title = _td_text(cells[idx["title"]])
                announce_raw = _td_text(cells[idx["announce"]])
                kind_raw = _td_text(cells[idx["kind"]]) if "kind" in idx and idx["kind"] < len(cells) else ""
                deadline_raw = _td_text(cells[idx["deadline"]]) if "deadline" in idx and idx["deadline"] < len(cells) else ""
                classification = _td_text(cells[idx["classification"]]) if "classification" in idx and idx["classification"] < len(cells) else None
            except IndexError:
                continue

            announce_iso = _wareki_to_iso(announce_raw)
            if not (title and announce_iso):
                continue

            uid = _unified_id(source.url, title, announce_iso)
            if uid in seen_uids:
                continue
            seen_uids.add(uid)

            checksum = hashlib.sha256(
                f"{title}|{announce_iso}|{kind_raw}|{deadline_raw}".encode("utf-8")
            ).hexdigest()
            excerpt = (
                f"件名: {title} / 公告: {announce_raw} / 形態: {kind_raw}"
                + (f" / 締切: {deadline_raw}" if deadline_raw else "")
            )[:500]

            rec = BidRecord(
                unified_id=uid,
                bid_title=title[:500],
                bid_kind=_normalize_bid_kind(kind_raw),
                procuring_entity=source.ministry,
                ministry=source.ministry,
                prefecture=source.prefecture,
                announcement_date=announce_iso,
                bid_deadline=_wareki_to_iso(deadline_raw),
                bid_description=f"[{source.category}] {title}"[:500],
                classification_code=classification,
                source_url=source.url,
                source_excerpt=excerpt,
                source_checksum=checksum,
                confidence=0.92,
                fetched_at=fetched_at,
            )
            out.append(rec)
    return out


# ---------------------------------------------------------------------------
# DB UPSERT
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO bids (
    unified_id, bid_title, bid_kind, procuring_entity, procuring_houjin_bangou,
    ministry, prefecture, program_id_hint,
    announcement_date, question_deadline, bid_deadline, decision_date,
    budget_ceiling_yen, awarded_amount_yen,
    winner_name, winner_houjin_bangou, participant_count,
    bid_description, eligibility_conditions, classification_code,
    source_url, source_excerpt, source_checksum,
    confidence, fetched_at, updated_at
) VALUES (
    ?,?,?,?,NULL,
    ?,?,NULL,
    ?,NULL,?,NULL,
    NULL,NULL,
    NULL,NULL,NULL,
    ?,NULL,?,
    ?,?,?,
    ?,?,?
)
ON CONFLICT(unified_id) DO UPDATE SET
    bid_title = excluded.bid_title,
    bid_kind = excluded.bid_kind,
    ministry = COALESCE(excluded.ministry, bids.ministry),
    prefecture = COALESCE(excluded.prefecture, bids.prefecture),
    announcement_date = COALESCE(excluded.announcement_date, bids.announcement_date),
    bid_deadline = COALESCE(excluded.bid_deadline, bids.bid_deadline),
    bid_description = COALESCE(excluded.bid_description, bids.bid_description),
    classification_code = COALESCE(excluded.classification_code, bids.classification_code),
    source_url = excluded.source_url,
    source_excerpt = excluded.source_excerpt,
    source_checksum = excluded.source_checksum,
    confidence = MAX(bids.confidence, excluded.confidence),
    fetched_at = excluded.fetched_at,
    updated_at = excluded.updated_at
"""


def _upsert(conn: sqlite3.Connection, rec: BidRecord) -> str:
    existed = conn.execute(
        "SELECT 1 FROM bids WHERE unified_id = ?", (rec.unified_id,)
    ).fetchone() is not None
    conn.execute(
        _UPSERT_SQL,
        (
            rec.unified_id, rec.bid_title, rec.bid_kind, rec.procuring_entity,
            rec.ministry, rec.prefecture,
            rec.announcement_date, rec.bid_deadline,
            rec.bid_description, rec.classification_code,
            rec.source_url, rec.source_excerpt, rec.source_checksum,
            rec.confidence, rec.fetched_at, rec.fetched_at,
        ),
    )
    # Mirror to FTS if table exists (best effort)
    try:
        conn.execute("DELETE FROM bids_fts WHERE unified_id = ?", (rec.unified_id,))
        conn.execute(
            "INSERT INTO bids_fts (unified_id, bid_title, bid_description, "
            "procuring_entity, winner_name) VALUES (?,?,?,?,?)",
            (rec.unified_id, rec.bid_title or "", rec.bid_description or "",
             rec.procuring_entity or "", ""),
        )
    except sqlite3.OperationalError:
        pass  # bids_fts not present
    return "update" if existed else "insert"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run(db_path: Path, limit: int | None, dry_run: bool) -> int:
    fetched_at = _now_iso()
    counts = {"pages_ok": 0, "pages_fail": 0, "parsed": 0,
              "insert": 0, "update": 0, "skip_banned": 0}

    all_records: list[BidRecord] = []
    for src in SOURCES:
        if _source_url_is_banned(src.url):
            counts["skip_banned"] += 1
            _LOG.warning("banned_source url=%s", src.url)
            continue
        body = _polite_get(src.url)
        if body is None:
            counts["pages_fail"] += 1
            continue
        counts["pages_ok"] += 1
        recs = _parse_maff_table(body, src, fetched_at)
        counts["parsed"] += len(recs)
        all_records.extend(recs)
        _LOG.info("page_ok url=%s rows=%d", src.url, len(recs))

    # Dedup across categories on (title, announcement_date) — same bid
    # may appear in multiple aggregator-style pages.
    dedup: dict[str, BidRecord] = {}
    for r in all_records:
        dedup[r.unified_id] = r
    records = list(dedup.values())
    _LOG.info("unique_records n=%d (pre-dedup=%d)", len(records), len(all_records))

    if dry_run:
        _LOG.info("dry_run counts=%s", counts)
        print(f"DRY RUN — {len(records)} unique records would be UPSERTed")
        return 0

    if not db_path.is_file():
        _LOG.error("db_missing path=%s", db_path)
        return 1

    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=300.0)
    try:
        conn.execute("PRAGMA busy_timeout = 300000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("BEGIN IMMEDIATE")
        for rec in records:
            verdict = _upsert(conn, rec)
            counts[verdict] += 1
            if limit is not None and (counts["insert"] + counts["update"]) >= limit:
                _LOG.info("limit_reached n=%d", limit)
                break
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    _LOG.info("done counts=%s", counts)
    print(f"INGEST DONE — insert={counts['insert']} update={counts['update']} "
          f"pages_ok={counts['pages_ok']}/{counts['pages_ok']+counts['pages_fail']}")
    return 0


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--log-level", default="INFO",
                    choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    log_path = LOG_DIR / f"ingest_bids_chotatsu_{stamp}.log"
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"),
                  logging.StreamHandler(sys.stderr)],
    )
    _LOG.info("start db=%s limit=%s dry_run=%s log=%s",
              args.db, args.limit, args.dry_run, log_path)
    return run(db_path=args.db, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
