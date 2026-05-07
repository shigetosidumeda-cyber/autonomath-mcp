#!/usr/bin/env python3
"""ingest_jst_programs.py — Ingest JST 公募 programs into jpintel.db.programs.

Source: www.jst.go.jp (科学技術振興機構)
  - Active list   : https://www.jst.go.jp/bosyu/bosyu.html (現在募集中)
  - Year archives : https://www.jst.go.jp/bosyu/bosyu-{YYYY}.html  (2019..2026)
  - Atom feed     : https://www.jst.go.jp/rss/bosyu.xml (公募中の補強)

Strategy:
  - Walk active page + 4-year archive (2023..2026) + Atom feed.
  - Each row = one anchor (掲載日 or 締切日, 分野, タイトル, href).
  - Resolve relative '../' hrefs against bosyu/.
  - Some links escape jst.go.jp (biosciencedbc, inouesho, miraikan); per task spec
    "source_url=jst.go.jp/*" filter, we keep only links whose final URL host ends
    with jst.go.jp.
  - 採用情報 / 株式運用委託 / 債券 主幹事 / 外部評価委員 / 委託契約 / 入札 等は除外.
  - dedup by source_url.

License (TOS context):
  - JST site_policy (R1.12.27) は商用使用に事前承認要 (PDL ではない).
  - 2026-04-25 user directive: "TOSは一旦無視してどんどん獲得してください".
    → raw acquisition phase. 再配布判断は launch 直前まで保留.
  - 出典: 「(発行年) 科学技術振興機構 (JST)」をクレジットとして enriched_json に保持.

Idempotent UPSERT:
  - unified_id = "UNI-ext-" + sha256(source_url)[:10]
  - BEGIN IMMEDIATE + busy_timeout=300_000

Tier rule (per task spec):
  S = open now + verified live URL
  A = within 90d
  B = otherwise

Rate: 1 req/sec/host. UA: AutonoMath/0.1.0 (+https://bookyou.net).
NO Anthropic API. NO LLM.

CLI:
  .venv/bin/python scripts/ingest/ingest_jst_programs.py
  .venv/bin/python scripts/ingest/ingest_jst_programs.py --years 2023,2024,2025,2026
  .venv/bin/python scripts/ingest/ingest_jst_programs.py --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install httpx beautifulsoup4", file=sys.stderr)
    sys.exit(1)


_LOG = logging.getLogger("ingest_jst_programs")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
RATE_LIMIT_SEC = 1.0
HTTP_TIMEOUT = 30
MAX_RETRIES = 3

ATTRIBUTION = "出典: 国立研究開発法人 科学技術振興機構 (JST)"
LICENSE_NOTE = (
    "JST site_policy (R1.12.27): 商用使用は事前承認要 (非PDL)。"
    "本データは外形メタデータ (program name / category / 掲載日 / source_url) "
    "のみを保持。引用は出典明記で可、再配布は launch 前に法務確認。"
)
JST_HOJIN_BANGOU = "4013401000813"
ISSUER_NAME = "国立研究開発法人 科学技術振興機構 (JST)"
AUTHORITY_LEVEL = "national"

ACTIVE_URL = "https://www.jst.go.jp/bosyu/bosyu.html"
ARCHIVE_URL_TPL = "https://www.jst.go.jp/bosyu/bosyu-{year}.html"
RSS_URL = "https://www.jst.go.jp/rss/bosyu.xml"

# 除外する分野/タイトル keyword (採用 / 入札 / 株式運用委託 / 委員 等)
EXCLUDE_TITLE_KEYWORDS = (
    "採用情報",
    "新卒採用",
    "中途採用",
    "外部評価委員",
    "委員の公募",
    "委員公募",
    "監事候補",
    "株式運用委託",
    "株式運用受託",
    "主幹事証券",
    "主幹事会社",
    "債券主幹事",
    "債券（主幹事）",
    "債券発行",
    "資金運用受託機関",
    "資金運用業務委託",
    "総合調達契約",
    "一般競争入札",
    "公開買付け",
    "売買代理",
    "信託受託",
    "信託銀行",
    "受託銀行",
    "貸出受託",
    "売買取引",
    "行政機関等匿名加工情報",
)

# Source-derived program category mapping (URL prefix → broad category)
_CATEGORY_MAP = (
    ("/a-step/", "a-step"),
    ("/kisoken/", "戦略創造研究"),
    ("/souhatsu/", "創発的研究"),
    ("/start/", "start"),
    ("/aspire/", "aspire"),
    ("/inter/", "国際共同研究"),
    ("/ristex/", "ristex"),
    ("/moonshot/", "ムーンショット"),
    ("/k-program/", "k-program"),
    ("/alca/", "alca"),
    ("/gtex/", "gtex"),
    ("/jisedai/", "次世代研究者"),
    ("/erato/", "erato"),
    ("/global/", "satreps"),
    ("/diversity/", "diversity"),
    ("/sis/", "sis"),
    ("/program/", "program"),
    ("/innov-jinzai/", "innov-jinzai"),
    ("/cpse/", "cpse"),
)

TIER_OPEN = "S"  # 募集中 + URL live
TIER_RECENT = "A"  # 90 日以内
TIER_OTHER = "B"  # 古い archive


# ---------------------------------------------------------------------------
# fetch (1 req/sec/host)
# ---------------------------------------------------------------------------


def fetch(client: httpx.Client, url: str, host_clock: dict[str, float]) -> bytes | None:
    host = urlparse(url).netloc
    last = host_clock.get(host)
    if last is not None:
        wait = RATE_LIMIT_SEC - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)

    for attempt in range(1, MAX_RETRIES + 1):
        host_clock[host] = time.monotonic()
        try:
            r = client.get(url)
        except httpx.HTTPError as exc:
            _LOG.warning("fetch_err url=%s attempt=%d err=%s", url, attempt, exc)
            if attempt == MAX_RETRIES:
                return None
            time.sleep(2**attempt)
            continue

        if r.status_code == 200:
            return r.content
        if r.status_code in (404, 403, 410):
            _LOG.info("skip url=%s status=%d", url, r.status_code)
            return None
        if r.status_code in (429, 503) and attempt < MAX_RETRIES:
            ra = r.headers.get("retry-after")
            try:
                wait = float(ra) if ra else 2**attempt
            except ValueError:
                wait = 2**attempt
            _LOG.info("backoff url=%s status=%d wait=%.1fs", url, r.status_code, wait)
            time.sleep(wait)
            continue
        _LOG.warning("status url=%s status=%d", url, r.status_code)
        return None
    return None


def head_check(client: httpx.Client, url: str, host_clock: dict[str, float]) -> int | None:
    """HEAD / GET liveness check. Returns status_code or None on net err."""
    host = urlparse(url).netloc
    last = host_clock.get(host)
    if last is not None:
        wait = RATE_LIMIT_SEC - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
    host_clock[host] = time.monotonic()
    try:
        r = client.head(url)
        if r.status_code in (405, 501) or r.status_code >= 500:
            r = client.get(url)
        return r.status_code
    except httpx.HTTPError:
        return None


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------


_JP_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_JP_YYMM_RE = re.compile(r"(\d{4})年(\d{1,2})月")


def parse_jp_date(s: str | None) -> date | None:
    if not s:
        return None
    m = _JP_DATE_RE.search(s)
    if m:
        y, mo, d = m.groups()
        try:
            return date(int(y), int(mo), int(d))
        except ValueError:
            return None
    m = _JP_YYMM_RE.search(s)
    if m:
        y, mo = m.groups()
        try:
            return date(int(y), int(mo), 1)
        except ValueError:
            return None
    return None


def category_from_url(url: str) -> str | None:
    p = urlparse(url).path
    for prefix, label in _CATEGORY_MAP:
        if prefix in p:
            return label
    return None


def is_excluded_title(title: str) -> bool:
    return any(kw in title for kw in EXCLUDE_TITLE_KEYWORDS)


def normalize_url(href: str, base: str) -> str:
    href = href.strip()
    if not href:
        return ""
    return urljoin(base, href)


def parse_table_page(html: bytes, base_url: str) -> list[dict[str, Any]]:
    """Parse bosyu.html / bosyu-YYYY.html `<table class="tableDesign1">`.

    Each row: [掲載日 or 締切日, 分野, <a>タイトル</a>]
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="tableDesign1")
    if not table:
        return []
    out: list[dict[str, Any]] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        date_text = tds[0].get_text(" ", strip=True)
        category_jp = tds[1].get_text(" ", strip=True)
        a = tds[2].find("a", href=True)
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        if not title:
            continue
        href = normalize_url(a["href"], base_url)
        out.append(
            {
                "title": title,
                "url": href,
                "date_text": date_text,
                "category_jp": category_jp,
            }
        )
    return out


def parse_atom(xml_bytes: bytes) -> list[dict[str, Any]]:
    """Parse /rss/bosyu.xml Atom feed."""
    out: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_bytes)  # nosec B314 - input is trusted gov-source XML; not user-supplied
    except ET.ParseError as exc:
        _LOG.warning("atom parse err: %s", exc)
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        pub_el = entry.find("atom:published", ns)
        title = (title_el.text or "").strip() if title_el is not None else ""
        href = ""
        if link_el is not None:
            href = (link_el.get("href") or "").strip()
        if not title or not href:
            continue
        out.append(
            {
                "title": title,
                "url": href,
                "published": (pub_el.text or "").strip() if pub_el is not None else "",
            }
        )
    return out


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------


def compute_unified_id(source_url: str) -> str:
    h = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:10]
    return f"UNI-ext-{h}"


def upsert_program(
    conn: sqlite3.Connection,
    *,
    uid: str,
    name: str,
    source_url: str,
    tier: str,
    enriched: dict[str, Any],
    application_window_json: str | None,
    now_iso: str,
) -> str:
    row = conn.execute(
        "SELECT excluded, primary_name FROM programs WHERE unified_id = ?", (uid,)
    ).fetchone()

    enriched_json = json.dumps(enriched, ensure_ascii=False)
    source_mentions = json.dumps(
        [
            {
                "source": "jst.go.jp",
                "attribution": ATTRIBUTION,
                "license": LICENSE_NOTE,
                "issuer_hojin_bangou": JST_HOJIN_BANGOU,
            }
        ],
        ensure_ascii=False,
    )

    if row is None:
        conn.execute(
            """INSERT INTO programs (
                unified_id, primary_name, aliases_json,
                authority_level, authority_name, prefecture, municipality,
                program_kind, official_url,
                amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                trust_level, tier, coverage_score, gap_to_tier_s_json,
                a_to_j_coverage_json,
                excluded, exclusion_reason,
                crop_categories_json, equipment_category,
                target_types_json, funding_purpose_json,
                amount_band, application_window_json,
                enriched_json, source_mentions_json,
                source_url, source_fetched_at, source_checksum,
                updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                uid,
                name,
                None,
                AUTHORITY_LEVEL,
                ISSUER_NAME,
                None,
                None,
                "research_grant",
                source_url,
                None,
                None,
                None,
                None,
                tier,
                None,
                None,
                None,
                0,
                None,
                None,
                None,
                None,
                None,
                None,
                application_window_json,
                enriched_json,
                source_mentions,
                source_url,
                now_iso,
                None,
                now_iso,
            ),
        )
        # FTS table may not exist in some setups
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
                "VALUES (?,?,?,?)",
                (uid, name, "", name),
            )
        return "insert"

    if row[0]:
        return "skip"

    sets = ["source_fetched_at = ?", "enriched_json = ?", "updated_at = ?"]
    vals: list[Any] = [now_iso, enriched_json, now_iso]
    if application_window_json:
        sets.append("application_window_json = COALESCE(application_window_json, ?)")
        vals.append(application_window_json)
    if not row[1]:
        sets.append("primary_name = ?")
        vals.append(name)
    # Update tier upward (S > A > B)
    sets.append("tier = ?")
    vals.append(tier)
    vals.append(uid)
    conn.execute(f"UPDATE programs SET {', '.join(sets)} WHERE unified_id = ?", vals)
    return "update"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument(
        "--years",
        type=str,
        default="2022,2023,2024,2025,2026",
        help="comma-separated archive years to walk",
    )
    p.add_argument("--max", type=int, default=300, help="cap programs to ingest")
    p.add_argument(
        "--no-verify", action="store_true", help="skip HEAD liveness check (faster local test)"
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.db.exists():
        _LOG.error("db not found: %s", args.db)
        return 2

    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]

    client = httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.5"},
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    )
    host_clock: dict[str, float] = {}

    # ----- Step 1: collect candidate {url -> meta} -----
    candidates: dict[str, dict[str, Any]] = {}

    # 1a: Atom RSS (active programs, structured published date)
    rss_body = fetch(client, RSS_URL, host_clock)
    if rss_body:
        for item in parse_atom(rss_body):
            url = item["url"].strip()
            host = urlparse(url).netloc
            if not host.endswith("jst.go.jp"):
                continue
            if is_excluded_title(item["title"]):
                continue
            candidates.setdefault(
                url,
                {
                    "title": item["title"],
                    "url": url,
                    "published_at": item["published"],
                    "source_kind": "active_rss",
                    "year": None,
                    "category_jp": None,
                    "date_text": "",
                },
            )
        _LOG.info("rss collected=%d", len(candidates))

    # 1b: Active table (bosyu.html)
    active_body = fetch(client, ACTIVE_URL, host_clock)
    if active_body:
        before = len(candidates)
        for it in parse_table_page(active_body, ACTIVE_URL):
            url = it["url"]
            host = urlparse(url).netloc
            if not host.endswith("jst.go.jp"):
                continue
            if is_excluded_title(it["title"]):
                continue
            existing = candidates.get(url)
            if existing:
                if not existing.get("date_text"):
                    existing["date_text"] = it["date_text"]
                if not existing.get("category_jp"):
                    existing["category_jp"] = it["category_jp"]
                existing["source_kind"] = "active_table"
            else:
                candidates[url] = {
                    "title": it["title"],
                    "url": url,
                    "published_at": "",
                    "source_kind": "active_table",
                    "year": None,
                    "category_jp": it["category_jp"],
                    "date_text": it["date_text"],
                }
        _LOG.info("active +%d (total=%d)", len(candidates) - before, len(candidates))

    # 1c: Year archives
    for yr in sorted(years, reverse=True):
        url = ARCHIVE_URL_TPL.format(year=yr)
        body = fetch(client, url, host_clock)
        if not body:
            continue
        before = len(candidates)
        for it in parse_table_page(body, url):
            ahref = it["url"]
            host = urlparse(ahref).netloc
            if not host.endswith("jst.go.jp"):
                continue
            if is_excluded_title(it["title"]):
                continue
            existing = candidates.get(ahref)
            if existing:
                if not existing.get("year"):
                    existing["year"] = yr
                if not existing.get("date_text"):
                    existing["date_text"] = it["date_text"]
                if not existing.get("category_jp"):
                    existing["category_jp"] = it["category_jp"]
            else:
                candidates[ahref] = {
                    "title": it["title"],
                    "url": ahref,
                    "published_at": "",
                    "source_kind": f"archive_{yr}",
                    "year": yr,
                    "category_jp": it["category_jp"],
                    "date_text": it["date_text"],
                }
        _LOG.info("archive %d +%d (total=%d)", yr, len(candidates) - before, len(candidates))

    # Cap candidates
    cands = list(candidates.values())[: args.max]
    _LOG.info("total candidates: %d", len(cands))

    # ----- Step 2: open DB & upsert -----
    conn = sqlite3.connect(args.db, timeout=300)
    conn.execute("PRAGMA busy_timeout = 300000;")

    inserted = updated = skipped = errors = 0
    today = date.today()
    cutoff_90d = today - timedelta(days=90)

    try:
        if not args.dry_run:
            conn.execute("BEGIN IMMEDIATE;")

        for c in cands:
            url = c["url"]
            title = c["title"][:300]
            uid = compute_unified_id(url)
            now_iso = datetime.now(UTC).isoformat(timespec="seconds")

            # --- tier judgment ---
            #   S = active list (rss or active_table) and (no_verify OR liveness 200)
            #   A = within 90d (date_text or published_at parses to a date <90d old)
            #   B = otherwise
            is_active_listing = c["source_kind"] in ("active_rss", "active_table")

            ref_date: date | None = None
            if c.get("published_at"):
                # ISO 8601 published from RSS
                try:
                    ref_date = datetime.fromisoformat(
                        c["published_at"].replace("Z", "+00:00")
                    ).date()
                except ValueError:
                    ref_date = parse_jp_date(c["published_at"])
            if ref_date is None:
                ref_date = parse_jp_date(c.get("date_text", ""))

            tier = TIER_OTHER
            live_status: int | None = None
            if is_active_listing:
                if args.no_verify:
                    tier = TIER_OPEN
                else:
                    live_status = head_check(client, url, host_clock)
                    if live_status == 200:
                        tier = TIER_OPEN
                    elif ref_date and ref_date >= cutoff_90d:
                        tier = TIER_RECENT
                    else:
                        tier = TIER_OTHER
            elif ref_date and ref_date >= cutoff_90d:
                tier = TIER_RECENT
            else:
                tier = TIER_OTHER

            # --- application_window_json ---
            window: dict[str, Any] = {}
            if ref_date:
                if is_active_listing and c.get("date_text"):
                    # active table: 締切 (deadline)
                    window["close_date"] = ref_date.isoformat()
                else:
                    # archive table: 掲載日 (publication date)
                    window["page_date"] = ref_date.isoformat()
            window_json = json.dumps(window, ensure_ascii=False) if window else None

            # --- enriched_json ---
            enriched = {
                "issuer": ISSUER_NAME,
                "issuer_hojin_bangou": JST_HOJIN_BANGOU,
                "category": category_from_url(url),
                "category_jp": c.get("category_jp"),
                "source_kind": c["source_kind"],
                "year": c.get("year"),
                "date_text": c.get("date_text"),
                "published_at": c.get("published_at"),
                "live_status": live_status,
                "fetched_at": now_iso,
                "license_note": LICENSE_NOTE,
            }

            if args.dry_run:
                _LOG.info(
                    "dry-run tier=%s kind=%s name=%s url=%s",
                    tier,
                    c["source_kind"],
                    title[:50],
                    url,
                )
                continue

            try:
                outcome = upsert_program(
                    conn,
                    uid=uid,
                    name=title,
                    source_url=url,
                    tier=tier,
                    enriched=enriched,
                    application_window_json=window_json,
                    now_iso=now_iso,
                )
            except sqlite3.Error as exc:
                _LOG.warning("upsert fail %s err=%s", url, exc)
                errors += 1
                continue
            if outcome == "insert":
                inserted += 1
            elif outcome == "update":
                updated += 1
            else:
                skipped += 1

        if not args.dry_run:
            conn.execute("COMMIT;")
    except Exception:
        if not args.dry_run:
            conn.execute("ROLLBACK;")
        raise
    finally:
        conn.close()
        client.close()

    _LOG.info(
        "done inserted=%d updated=%d skipped=%d errors=%d (candidates=%d)",
        inserted,
        updated,
        skipped,
        errors,
        len(cands),
    )
    print(
        f"jst_ingest inserted={inserted} updated={updated} skipped={skipped} "
        f"errors={errors} candidates={len(cands)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
