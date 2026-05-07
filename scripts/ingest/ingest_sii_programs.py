#!/usr/bin/env python3
"""ingest_sii_programs.py — Ingest SII (一般社団法人 環境共創イニシアチブ) 補助金 programs.

Source: sii.or.jp
  - active list: https://sii.or.jp/information/division.html (12 programs)
  - closed list: https://sii.or.jp/information/close_division.html (~157 program-year slugs)

License: SII /opendata/notice.html — 出典記載 + 第三者権利非侵害 を条件に複製・翻案・再配布 OK.
        We retain attribution string `出典: SII (一般社団法人 環境共創イニシアチブ)` in source_mentions_json.

Idempotent UPSERT against jpintel.db.programs:
  - unified_id = "UNI-ext-" + sha256(source_url)[:10]
  - existing rows preserved per _upsert_program semantics in ingest_external_data.py
  - BEGIN IMMEDIATE + busy_timeout=300_000 for parallel-safe writes

NO Anthropic API. NO LLM. Pure HTML scrape with BeautifulSoup.

Rate: 1 req/sec, UA "AutonoMath/0.1.0 (+https://bookyou.net)".

CLI:
    .venv/bin/python scripts/ingest/ingest_sii_programs.py
    .venv/bin/python scripts/ingest/ingest_sii_programs.py --db data/jpintel.db
    .venv/bin/python scripts/ingest/ingest_sii_programs.py --dry-run
    .venv/bin/python scripts/ingest/ingest_sii_programs.py --max 60
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    import httpx
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    print(f"missing dep: {exc}. pip install httpx beautifulsoup4", file=sys.stderr)
    sys.exit(1)


_LOG = logging.getLogger("ingest_sii_programs")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
RATE_LIMIT_SEC = 1.0
HTTP_TIMEOUT = 30
MAX_RETRIES = 3

ATTRIBUTION = "出典: SII (一般社団法人 環境共創イニシアチブ)"
LICENSE_NOTE = "SII /opendata/notice.html: 出典記載 + 第三者権利非侵害 で複製・翻案・再配布可"

ACTIVE_INDEX = "https://sii.or.jp/information/division.html"
CLOSED_INDEX = "https://sii.or.jp/information/close_division.html"

# Authority — SII is METI/ENV's executor. Default authority_name reflects this.
ISSUER_NAME = "一般社団法人 環境共創イニシアチブ (SII)"
AUTHORITY_LEVEL = "national"

# Tier defaults — see CLAUDE.md / ext upsert semantics.
TIER_ACTIVE = "S"  # 現行公募中 (R7補正 / R8 / 都ゼロエミ)
TIER_RECENT = "A"  # 直近 (R7/R8 で執行終了 or close 移行直後)
TIER_BACK = "B"  # 過去 5 年 (R3〜R6)
TIER_OLD = "C"  # 5 年超前 (H30 以前)

# Skip non-program slugs that appear in the index header/footer.
NAV_SLUGS = {
    "kobo",
    "sitemap",
    "newsrelease",
    "opendata",
    "information",
    "company",
    "logo",
    "privacy",
    "anonymous_processing",
    "customer_harassment_policy",
    "policy",
    "blog",
}


def fetch(client: httpx.Client, url: str, host_clock: dict[str, float]) -> bytes | None:
    """Fetch with 1 req/sec/host pacing + 3-retry backoff."""
    from urllib.parse import urlparse

    host = urlparse(url).netloc
    last = host_clock.get(host)
    if last is not None:
        wait = RATE_LIMIT_SEC - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)

    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        host_clock[host] = time.monotonic()
        try:
            r = client.get(url)
        except httpx.HTTPError as exc:
            last_err = exc
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


def collect_slug_links(html: bytes, *, base: str = "https://sii.or.jp") -> list[tuple[str, str]]:
    """Return [(slug_url, anchor_text), ...] from a SII index html."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    pat = re.compile(r"^/?([A-Za-z][A-Za-z0-9_]+)/?(?:index\.html)?$")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if not text or not href:
            continue
        # Normalize to relative slug
        if href.startswith("http"):
            if "sii.or.jp" not in href:
                continue
            # extract path
            from urllib.parse import urlparse as _up

            href = _up(href).path
        m = pat.match(href)
        if not m:
            continue
        slug = m.group(1)
        if slug in NAV_SLUGS:
            continue
        # Build canonical URL
        full = urljoin(base + "/", slug + "/")
        if full in seen:
            continue
        seen.add(full)
        out.append((full, text))
    return out


_FY_RE = re.compile(r"令和(\d+)年度(?:補正)?|平成(\d+)年度(?:補正)?")


def classify_tier(slug_text: str, slug_url: str, *, is_active: bool) -> str:
    """Tier S = active. Otherwise tier from year suffix."""
    if is_active:
        return TIER_ACTIVE
    txt = slug_text + " " + slug_url
    # Reiwa year
    m_r = re.search(r"令和(\d+)", txt)
    m_h = re.search(r"平成(\d+)", txt)
    if m_r:
        try:
            yr_r = int(m_r.group(1))
        except ValueError:
            yr_r = 0
        # 令和7,8 = recent
        if yr_r >= 7:
            return TIER_RECENT
        if yr_r >= 3:
            return TIER_BACK
        return TIER_OLD
    if m_h:
        return TIER_OLD
    # No year info: default backstop
    return TIER_BACK


def parse_slug_page(html: bytes, *, slug_url: str, fallback_name: str) -> dict[str, Any]:
    """Parse a SII slug page and extract canonical fields."""
    soup = BeautifulSoup(html, "html.parser")
    name = fallback_name
    title_tag = soup.find("title")
    if title_tag:
        ttl = title_tag.get_text(strip=True)
        # Pattern: "SII：…｜事業トップ（<NAME>）". <NAME> may contain inner full-width parens,
        # so match from after 事業トップ（ to the FINAL closing ） (balanced strip).
        idx = ttl.find("事業トップ（")
        if idx >= 0:
            inner = ttl[idx + len("事業トップ（") :]
            if inner.endswith("）"):
                inner = inner[:-1]
            cand = inner.strip()
            if 4 < len(cand) < 250:
                name = cand
        else:
            # Fallback: chunk after final ｜
            parts = re.split(r"[｜|]", ttl)
            if len(parts) > 1:
                cand = parts[-1].strip()
                if 4 < len(cand) < 250:
                    name = cand

    return {
        "primary_name": name[:300],
    }


def compute_unified_id(source_url: str) -> str:
    """Deterministic unified_id from source URL → re-runs upsert same row."""
    h = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:10]
    return f"UNI-ext-{h}"


def already_present(conn: sqlite3.Connection, uid: str) -> tuple[bool, bool]:
    """(exists, excluded)."""
    row = conn.execute("SELECT excluded FROM programs WHERE unified_id = ?", (uid,)).fetchone()
    if row is None:
        return False, False
    return True, bool(row[0])


def upsert_program(
    conn: sqlite3.Connection,
    *,
    uid: str,
    name: str,
    source_url: str,
    tier: str,
    enriched: dict[str, Any],
    now_iso: str,
) -> str:
    """Idempotent upsert. Returns 'insert' | 'update' | 'skip'."""
    exists, excluded = already_present(conn, uid)
    if exists and excluded:
        return "skip"

    enriched_json = json.dumps(enriched, ensure_ascii=False)
    source_mentions = json.dumps(
        [{"source": "sii.or.jp", "attribution": ATTRIBUTION, "license": LICENSE_NOTE}],
        ensure_ascii=False,
    )

    if not exists:
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
                "subsidy",
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
                None,
                enriched_json,
                source_mentions,
                source_url,
                now_iso,
                None,
                now_iso,
            ),
        )
        # FTS row
        conn.execute(
            "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
            "VALUES (?,?,?,?)",
            (uid, name, "", name),
        )
        return "insert"

    # UPDATE: only refresh source_fetched_at + enriched_json + name when name was empty.
    cur = conn.execute(
        "SELECT primary_name, enriched_json, source_url FROM programs WHERE unified_id = ?",
        (uid,),
    ).fetchone()
    sets = ["source_fetched_at = ?", "enriched_json = ?", "updated_at = ?"]
    vals: list[Any] = [now_iso, enriched_json, now_iso]
    if cur and (cur[0] is None or cur[0] == ""):
        sets.insert(0, "primary_name = ?")
        vals.insert(0, name)
    if cur and cur[2] != source_url:
        sets.append("source_url = ?")
        vals.append(source_url)
    vals.append(uid)
    conn.execute(f"UPDATE programs SET {', '.join(sets)} WHERE unified_id = ?", vals)
    return "update"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--max", type=int, default=200, help="cap programs to ingest")
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

    client = httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "ja,en;q=0.5"},
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    )
    host_clock: dict[str, float] = {}

    # Step 1: collect candidate slug URLs from active + closed indexes
    candidates: list[tuple[str, str, bool]] = []  # (url, anchor_text, is_active)
    seen_urls: set[str] = set()
    for idx_url, is_active in [(ACTIVE_INDEX, True), (CLOSED_INDEX, False)]:
        body = fetch(client, idx_url, host_clock)
        if body is None:
            _LOG.warning("index unreachable: %s", idx_url)
            continue
        links = collect_slug_links(body)
        _LOG.info("index=%s slugs=%d", idx_url, len(links))
        for slug_url, anchor_text in links:
            if slug_url in seen_urls:
                continue
            seen_urls.add(slug_url)
            candidates.append((slug_url, anchor_text, is_active))

    _LOG.info("total unique slug candidates: %d", len(candidates))

    if args.max:
        candidates = candidates[: args.max]

    # Step 2: open DB w/ parallel-safe pragmas
    conn = sqlite3.connect(args.db, timeout=300)
    conn.execute("PRAGMA busy_timeout = 300000;")
    if args.dry_run:
        _LOG.info("dry-run: no DB writes")

    inserted = updated = skipped = errors = 0

    try:
        if not args.dry_run:
            conn.execute("BEGIN IMMEDIATE;")

        for slug_url, anchor_text, is_active in candidates:
            body = fetch(client, slug_url, host_clock)
            if body is None:
                errors += 1
                continue
            try:
                meta = parse_slug_page(body, slug_url=slug_url, fallback_name=anchor_text)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("parse fail %s err=%s", slug_url, exc)
                errors += 1
                continue

            tier = classify_tier(anchor_text, slug_url, is_active=is_active)
            uid = compute_unified_id(slug_url)
            now_iso = datetime.now(UTC).isoformat(timespec="seconds")

            enriched = {
                "anchor_text": anchor_text,
                "is_active": is_active,
                "issuer": ISSUER_NAME,
                "fetched_at": now_iso,
                "license_note": LICENSE_NOTE,
            }

            if args.dry_run:
                _LOG.info(
                    "dry-run: tier=%s uid=%s name=%s url=%s",
                    tier,
                    uid,
                    meta["primary_name"][:60],
                    slug_url,
                )
                continue

            try:
                outcome = upsert_program(
                    conn,
                    uid=uid,
                    name=meta["primary_name"],
                    source_url=slug_url,
                    tier=tier,
                    enriched=enriched,
                    now_iso=now_iso,
                )
            except sqlite3.Error as exc:
                _LOG.warning("upsert fail %s err=%s", slug_url, exc)
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
        len(candidates),
    )
    print(
        f"sii_ingest inserted={inserted} updated={updated} skipped={skipped} "
        f"errors={errors} candidates={len(candidates)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
