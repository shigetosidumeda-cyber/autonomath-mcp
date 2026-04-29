#!/usr/bin/env python3
"""ingest_maff.py — 農林水産省 (MAFF) 補助金・交付金 制度を jpintel.db へ取り込む。

Source: https://www.maff.go.jp/  (一次資料のみ)
        + 補助事業参加者公募ページ https://www.maff.go.jp/j/supply/hozyo/

License: 政府標準利用規約 (gov_standard) — 出典明示で再配布可。
         license_attribution に "© 農林水産省, 政府標準利用規約 2.0" を明記。

Recon (2026-04-29):
  * /j/supply/hozyo/ : ~200+ 公募 entries (HTML テーブル形式、令和8年度 R8 多数)
  * /j/budget/r8/    : R8 当初予算 補助事業 概要 (PDF + HTML)
  * /j/aid/          : 交付決定情報 ハブ
  * RSS: なし。メールマガジン (https://www.maff.go.jp/j/pr/e-mag/index.html) のみ。

Strategy:
  * 公募一覧 HTML を fetch → 公告日/締切日/件名/詳細 URL を <table> から抽出。
  * 各詳細ページ (./<bureau>/<YYMMDD>_<id>-<seq>.html) を 1 req/s で fetch。
  * <title> + meta + 本文先頭 N 字から: 制度名, 締切, 上限額 (man yen), 対象 (法人/個人/自治体)。
  * Tier:
      S = 詳細 200 OK + 締切 90 日以内 + amount_max + target_types すべて埋まる
      A = 200 OK + 締切 or amount いずれか埋まる
      B = 200 OK だが詳細不足
      X = 取得失敗 / 締切経過 (excluded=1, exclusion_reason='deadline_passed')
  * 冪等: source_checksum (sha1(url|name|deadline|amount)) が一致なら skip。

Constraints:
  * NO Anthropic API. NO claude CLI. urllib + bs4 のみ。
  * Rate-limit: 1 req/s to maff.go.jp.
  * BEGIN IMMEDIATE + busy_timeout=300_000.
  * Aggregator (noukaweb / hojyokin-portal) ban 厳守: source_url は maff.go.jp 限定。

Run:
  .venv/bin/python scripts/ingest_maff.py
  .venv/bin/python scripts/ingest_maff.py --dry-run
  .venv/bin/python scripts/ingest_maff.py --limit 50  # smoke test
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup

try:
    import certifi  # type: ignore[import-untyped]

    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CTX = ssl.create_default_context()

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "data" / "jpintel.db"

UA = "AutonoMath/0.1.0 (+https://bookyou.net)"
RATE_DELAY = 1.0
HTTP_TIMEOUT = 30

INDEX_URL = "https://www.maff.go.jp/j/supply/hozyo/"
BASE_URL = "https://www.maff.go.jp/j/supply/hozyo/"

LICENSE_ATTR = "© 農林水産省 / 政府標準利用規約 2.0 (gov_standard) — 出典明示で再配布可"


# ---------------------------------------------------------------------------
# Curated bureau → authority_name mapping (MAFF internal directory structure).
# ---------------------------------------------------------------------------
BUREAU_AUTHORITY: dict[str, str] = {
    "kanbo": "農林水産省 大臣官房",
    "nousan": "農林水産省 農産局",
    "chikusan": "農林水産省 畜産局",
    "nousin": "農林水産省 農村振興局",
    "yusyutu_kokusai": "農林水産省 輸出・国際局",
    "shokusan": "農林水産省 食料産業局",
    "rinya": "農林水産省 林野庁",
    "suisan": "農林水産省 水産庁",
    "shokuhin_anzen": "農林水産省 食品安全局",
    "syouhi_anzen": "農林水産省 消費・安全局",
    "keiei": "農林水産省 経営局",
    "seisaku": "農林水産省 政策統括官",
}


@dataclasses.dataclass
class MaffEntry:
    title: str
    detail_url: str
    announce_date: str | None  # ISO 8601 date or None
    deadline: str | None       # ISO 8601 date or None
    bureau: str | None         # path segment, e.g. "nousan"


# ---------------------------------------------------------------------------
# HTTP fetch (UTF-8 / Shift_JIS aware)
# ---------------------------------------------------------------------------

def fetch(url: str, *, retries: int = 2) -> tuple[int, str]:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_SSL_CTX) as resp:
                raw = resp.read()
                charset = resp.headers.get_content_charset() or "utf-8"
                try:
                    text = raw.decode(charset, errors="replace")
                except LookupError:
                    text = raw.decode("utf-8", errors="replace")
                return resp.status, text
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code in (404, 410):
                return exc.code, ""
            time.sleep(2.0 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2.0 * (attempt + 1))
    print(f"  [WARN] fetch failed: {url}: {last_err}", file=sys.stderr)
    return 0, ""


# ---------------------------------------------------------------------------
# Wareki (令和YY) → ISO date
# ---------------------------------------------------------------------------
WAREKI_RE = re.compile(r"令和(\d+)年(\d+)月(\d+)日")


def wareki_to_iso(s: str) -> str | None:
    m = WAREKI_RE.search(s)
    if not m:
        return None
    yy, mm, dd = (int(x) for x in m.groups())
    # 令和 = 2019 + (yy - 1)
    yyyy = 2018 + yy
    try:
        return date(yyyy, mm, dd).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Index page parser
# ---------------------------------------------------------------------------

def parse_index(html: str) -> list[MaffEntry]:
    """Extract entries from /j/supply/hozyo/ index. Each 公募 row is
    [公告日, 締切日, 件名(link)] in a table; both cells[0] and cells[1] MUST
    contain Wareki dates — otherwise it's a header / nav row we should skip."""
    soup = BeautifulSoup(html, "html.parser")
    entries: list[MaffEntry] = []
    seen_urls: set[str] = set()
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            announce = wareki_to_iso(cells[0].get_text(" ", strip=True))
            deadline = wareki_to_iso(cells[1].get_text(" ", strip=True))
            # Require BOTH dates to look like real 公募 — eliminates header rows
            # and the topical-section nav table that lives near the page top.
            if not announce or not deadline:
                continue
            # Some cells contain a leading <a id="..."> anchor with no href —
            # walk all <a> tags and pick the first one with a real href attr.
            link = None
            for cand in cells[2].find_all("a"):
                if cand.get("href"):
                    link = cand
                    break
            if not link:
                continue
            href = link["href"]
            title = link.get_text(" ", strip=True)
            if not title or len(title) < 6:
                continue
            # Skip generic anchor texts that aren't program names.
            if title in {"結果はこちらから", "詳細はこちら", "こちら"}:
                continue
            full_url = urllib.parse.urljoin(BASE_URL, href)
            # Only keep maff.go.jp URLs (aggregator ban).
            if "maff.go.jp" not in full_url:
                continue
            # Dedup within a single index pass (some 公募 appear in multiple sections).
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            bureau = None
            m = re.search(r"/(?:j/supply/hozyo/)?([a-z_]+)/\d{6}", full_url)
            if m:
                bureau = m.group(1)
            entries.append(MaffEntry(
                title=title, detail_url=full_url,
                announce_date=announce, deadline=deadline, bureau=bureau,
            ))
    return entries


# ---------------------------------------------------------------------------
# Detail page parser (best-effort extraction)
# ---------------------------------------------------------------------------
AMOUNT_RE = re.compile(
    r"(?:上限|限度|最大)[\s:]*([0-9,，]+)\s*(?:万円|百万円|億円|千円|円)"
)
TARGET_HINTS: dict[str, str] = {
    "農業者": "individual_farmer",
    "農業法人": "agricultural_corporation",
    "個人": "individual",
    "法人": "corporation",
    "市町村": "municipality",
    "都道府県": "prefecture",
    "農協": "agricultural_cooperative",
    "JA": "agricultural_cooperative",
    "森林組合": "forestry_cooperative",
    "漁協": "fishery_cooperative",
    "漁業者": "fisherman",
    "民間団体": "private_organization",
}


def parse_detail(html: str, entry: MaffEntry) -> dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    # Title fallback (use index title if richer)
    title_tag = soup.find("title")
    parsed_title = title_tag.get_text(" ", strip=True) if title_tag else None

    body_text = soup.get_text(" ", strip=True)
    # Limit to first 8000 chars to keep regex reasonable
    body_text = body_text[:8000]

    amount_max_man_yen: float | None = None
    m = AMOUNT_RE.search(body_text)
    if m:
        num = m.group(1).replace(",", "").replace("，", "")
        try:
            v = float(num)
            unit = m.group(0)[-3:]
            if "百万円" in unit:
                amount_max_man_yen = v * 100.0
            elif "億円" in unit:
                amount_max_man_yen = v * 10000.0
            elif "千円" in unit:
                amount_max_man_yen = v / 10.0
            elif "万円" in unit:
                amount_max_man_yen = v
            elif "円" in unit:
                amount_max_man_yen = v / 10000.0
        except ValueError:
            pass

    targets: list[str] = []
    for kw, code in TARGET_HINTS.items():
        if kw in body_text and code not in targets:
            targets.append(code)

    return {
        "parsed_title": parsed_title,
        "amount_max_man_yen": amount_max_man_yen,
        "target_types": targets,
        "body_excerpt": body_text[:600],
    }


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

def classify(detail: dict[str, object], entry: MaffEntry, http_status: int) -> tuple[str, int, str | None]:
    """Return (tier, excluded, exclusion_reason)."""
    if http_status != 200:
        return "X", 1, "dead_source_url"
    today = date.today()
    deadline_obj: date | None = None
    if entry.deadline:
        try:
            deadline_obj = date.fromisoformat(entry.deadline)
        except ValueError:
            deadline_obj = None
    if deadline_obj and deadline_obj < today:
        return "X", 1, "deadline_passed"

    has_amount = detail.get("amount_max_man_yen") is not None
    has_targets = bool(detail.get("target_types"))
    has_deadline = deadline_obj is not None
    within_90 = bool(deadline_obj and (deadline_obj - today).days <= 90)

    if has_amount and has_targets and within_90:
        return "S", 0, None
    if (has_amount or has_targets) and has_deadline:
        return "A", 0, None
    if http_status == 200:
        return "B", 0, None
    return "X", 1, "no_amount_data"


# ---------------------------------------------------------------------------
# Build row & UPSERT
# ---------------------------------------------------------------------------

def make_unified_id(detail_url: str) -> str:
    h = hashlib.sha1(f"maff:{detail_url}".encode("utf-8")).hexdigest()[:10]
    return f"UNI-{h}"


def build_row(
    entry: MaffEntry,
    detail: dict[str, object],
    http_status: int,
    fetched_at: str,
) -> dict[str, object]:
    tier, excluded, excl_reason = classify(detail, entry, http_status)
    authority = BUREAU_AUTHORITY.get(entry.bureau or "", "農林水産省 (MAFF)")

    application_window = None
    if entry.announce_date or entry.deadline:
        application_window = json.dumps(
            {"start_date": entry.announce_date, "end_date": entry.deadline},
            ensure_ascii=False,
        )

    enriched = {
        "_meta": {
            "program_id": make_unified_id(entry.detail_url),
            "program_name": entry.title,
            "source_format": "html",
            "source_urls": [entry.detail_url, INDEX_URL],
            "fetched_at": fetched_at,
            "model": "maff-html-scraper-v1",
            "worker_id": "ingest_maff",
            "fetch_method": "urllib",
            "primary_source_confirmed": http_status == 200,
            "http_status": http_status,
        },
        "extraction": {
            "basic": {
                "正式名称": entry.title,
                "_source_ref": {"url": entry.detail_url, "excerpt": detail.get("body_excerpt") or ""},
            },
            "money": {
                "amount_max_man_yen": detail.get("amount_max_man_yen"),
                "_source_ref": {"url": entry.detail_url},
            },
            "schedule": {
                "start_date": entry.announce_date,
                "end_date": entry.deadline,
                "_source_ref": {"url": entry.detail_url},
            },
        },
        "license_attribution": LICENSE_ATTR,
    }

    return {
        "unified_id": make_unified_id(entry.detail_url),
        "primary_name": entry.title,
        "aliases_json": None,
        "authority_level": "national",
        "authority_name": authority,
        "prefecture": None,
        "municipality": None,
        "program_kind": "subsidy",
        "official_url": entry.detail_url,
        "amount_max_man_yen": detail.get("amount_max_man_yen"),
        "amount_min_man_yen": None,
        "subsidy_rate": None,
        "trust_level": "1",
        "tier": tier,
        "coverage_score": None,
        "gap_to_tier_s_json": None,
        "a_to_j_coverage_json": None,
        "excluded": excluded,
        "exclusion_reason": excl_reason,
        "crop_categories_json": None,
        "equipment_category": None,
        "target_types_json": json.dumps(detail.get("target_types") or [], ensure_ascii=False)
        if detail.get("target_types") else None,
        "funding_purpose_json": None,
        "amount_band": None,
        "application_window_json": application_window,
        "enriched_json": json.dumps(enriched, ensure_ascii=False),
        "source_mentions_json": json.dumps({"maff_index": INDEX_URL}, ensure_ascii=False),
        "source_url": entry.detail_url,
        "source_fetched_at": fetched_at,
        "source_checksum": hashlib.sha1(
            f"{entry.detail_url}|{entry.title}|{entry.deadline}|{detail.get('amount_max_man_yen')}".encode("utf-8")
        ).hexdigest()[:16],
        "updated_at": fetched_at,
    }


UPSERT_SQL = """
INSERT INTO programs (
    unified_id, primary_name, aliases_json, authority_level, authority_name,
    prefecture, municipality, program_kind, official_url,
    amount_max_man_yen, amount_min_man_yen, subsidy_rate,
    trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
    excluded, exclusion_reason,
    crop_categories_json, equipment_category,
    target_types_json, funding_purpose_json, amount_band, application_window_json,
    enriched_json, source_mentions_json,
    source_url, source_fetched_at, source_checksum, updated_at
) VALUES (
    :unified_id, :primary_name, :aliases_json, :authority_level, :authority_name,
    :prefecture, :municipality, :program_kind, :official_url,
    :amount_max_man_yen, :amount_min_man_yen, :subsidy_rate,
    :trust_level, :tier, :coverage_score, :gap_to_tier_s_json, :a_to_j_coverage_json,
    :excluded, :exclusion_reason,
    :crop_categories_json, :equipment_category,
    :target_types_json, :funding_purpose_json, :amount_band, :application_window_json,
    :enriched_json, :source_mentions_json,
    :source_url, :source_fetched_at, :source_checksum, :updated_at
)
ON CONFLICT(unified_id) DO UPDATE SET
    primary_name = excluded.primary_name,
    authority_name = COALESCE(excluded.authority_name, programs.authority_name),
    program_kind = COALESCE(excluded.program_kind, programs.program_kind),
    official_url = COALESCE(excluded.official_url, programs.official_url),
    amount_max_man_yen = COALESCE(excluded.amount_max_man_yen, programs.amount_max_man_yen),
    target_types_json = COALESCE(excluded.target_types_json, programs.target_types_json),
    application_window_json = COALESCE(
        excluded.application_window_json, programs.application_window_json
    ),
    enriched_json = excluded.enriched_json,
    source_url = excluded.source_url,
    source_fetched_at = excluded.source_fetched_at,
    source_checksum = excluded.source_checksum,
    tier = CASE
        WHEN programs.tier IS NULL OR programs.tier IN ('X','C') THEN excluded.tier
        ELSE programs.tier
    END,
    excluded = excluded.excluded,
    exclusion_reason = excluded.exclusion_reason,
    updated_at = excluded.updated_at
WHERE programs.source_checksum IS NULL OR programs.source_checksum != excluded.source_checksum
"""

FTS_INSERT_SQL = (
    "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
    "VALUES (?,?,?,?)"
)


def upsert(conn: sqlite3.Connection, row: dict[str, object]) -> str:
    prev = conn.execute(
        "SELECT source_checksum, excluded FROM programs WHERE unified_id = ?",
        (row["unified_id"],),
    ).fetchone()
    if prev is None:
        action = "insert"
    elif prev[0] == row["source_checksum"]:
        return "skip"
    else:
        action = "update"
    conn.execute(UPSERT_SQL, row)
    if action == "insert":
        conn.execute(
            FTS_INSERT_SQL,
            (
                row["unified_id"],
                row["primary_name"],
                row["aliases_json"] or "",
                row["primary_name"],
            ),
        )
    return action


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="No DB writes")
    ap.add_argument("--limit", type=int, default=None, help="Limit detail fetches (smoke test)")
    args = ap.parse_args()

    print(f"jpintel.db: {DB_PATH}")
    if not args.dry_run and not DB_PATH.exists():
        print(f"[ERROR] DB not found: {DB_PATH}", file=sys.stderr)
        return 2

    fetched_at = datetime.now(timezone.utc).isoformat()
    print(f"Fetching MAFF index: {INDEX_URL}")
    status, html = fetch(INDEX_URL)
    if status != 200:
        print(f"[ERROR] index fetch failed: HTTP {status}", file=sys.stderr)
        return 3
    entries = parse_index(html)
    print(f"  parsed {len(entries)} entries from index")
    if args.limit:
        entries = entries[: args.limit]

    rows: list[dict[str, object]] = []
    for i, e in enumerate(entries, 1):
        time.sleep(RATE_DELAY)
        d_status, d_html = fetch(e.detail_url)
        if d_status == 200 and d_html:
            detail = parse_detail(d_html, e)
        else:
            detail = {"parsed_title": None, "amount_max_man_yen": None,
                      "target_types": [], "body_excerpt": ""}
        rows.append(build_row(e, detail, d_status, fetched_at))
        ok = "OK" if d_status == 200 else f"HTTP {d_status}"
        print(f"  [{i:03d}/{len(entries)}] {ok} tier={rows[-1]['tier']} {e.title[:60]}")

    if args.dry_run:
        s_count = sum(1 for r in rows if r["tier"] == "S")
        a_count = sum(1 for r in rows if r["tier"] == "A")
        b_count = sum(1 for r in rows if r["tier"] == "B")
        x_count = sum(1 for r in rows if r["tier"] == "X")
        print(f"\nDRY RUN tier dist: S={s_count} A={a_count} B={b_count} X={x_count}")
        return 0

    conn = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=300.0)
    try:
        conn.execute("PRAGMA busy_timeout = 300000")
        conn.execute("BEGIN IMMEDIATE")
        ins = upd = skip = 0
        for r in rows:
            try:
                action = upsert(conn, r)
            except sqlite3.IntegrityError as exc:
                print(f"  [WARN] integrity: {r['unified_id']} {exc}", file=sys.stderr)
                skip += 1
                continue
            if action == "insert":
                ins += 1
            elif action == "update":
                upd += 1
            else:
                skip += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()

    print(f"\nDone: insert={ins} update={upd} skip={skip} (entries={len(rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
