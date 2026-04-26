#!/usr/bin/env python3
"""ingest_nedo_programs.py — Ingest NEDO 公募 programs into jpintel.db.programs.

Source: www.nedo.go.jp
  - koubo index: https://www.nedo.go.jp/form/event.php?f=koubo.html&p={1..N}
  - per page : 10 anchors → /koubo/<CODE>_<NUM>.html

License: NEDO /qinf/copyright.html — 出典明記での「引用」可。商用複製は要書面許可。
        Per recon §5.2, AutonoMath ¥3/req は外形メタデータ (program name / issuer /
        application dates / source_url) のみ再配布する。本文 abstract は **≤200 char**
        まで。コピーレフトな本文格納は禁止。

Idempotent UPSERT against jpintel.db.programs:
  - unified_id = "UNI-ext-" + sha256(source_url)[:10]
  - BEGIN IMMEDIATE + busy_timeout=300_000

Tier scoring:
  - 公募 / 予告 (募集中 or 募集前) → tier S
  - 決定 (採択公表済) → tier A

NO Anthropic API. NO LLM.

Rate: 1 req/sec/host. UA: AutonoMath/0.1.0 (+https://bookyou.net).

CLI:
    .venv/bin/python scripts/ingest/ingest_nedo_programs.py
    .venv/bin/python scripts/ingest/ingest_nedo_programs.py --pages 5 --dry-run
    .venv/bin/python scripts/ingest/ingest_nedo_programs.py --pages 8 --max 80
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


_LOG = logging.getLogger("ingest_nedo_programs")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = REPO_ROOT / "data" / "jpintel.db"

USER_AGENT = "AutonoMath/0.1.0 (+https://bookyou.net)"
RATE_LIMIT_SEC = 1.0
HTTP_TIMEOUT = 30
MAX_RETRIES = 3

ATTRIBUTION = "出典: 国立研究開発法人 新エネルギー・産業技術総合開発機構 (NEDO)"
LICENSE_NOTE = (
    "NEDO /qinf/copyright.html: 引用は出典明記で可。商用複製は要許可。"
    "本データは外形メタデータ (program name / issuer / 期間 / 担当部署 / URL / status) "
    "のみ再配布、本文 ≤200char。"
)
NEDO_HOJIN_BANGOU = "2020005008480"

KOUBO_INDEX = "https://www.nedo.go.jp/form/event.php?f=koubo.html&p={page}"
KOUBO_DETAIL_RE = re.compile(r"/koubo/([A-Z]{1,3}\d?_\d{6,7})\.html")

ISSUER_NAME = "国立研究開発法人 新エネルギー・産業技術総合開発機構 (NEDO)"
AUTHORITY_LEVEL = "national"

MAX_BODY_EXCERPT = 200  # char cap per TOS (景表法 fair-use-equivalent)

TIER_OPEN = "S"        # 公募 / 予告
TIER_DECIDED = "A"     # 決定 (採択公表済)


def fetch(client: httpx.Client, url: str, host_clock: dict[str, float]) -> bytes | None:
    """1 req/sec/host pacing + 3-retry backoff."""
    from urllib.parse import urlparse
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
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 200:
            return r.content
        if r.status_code in (404, 403, 410):
            _LOG.info("skip url=%s status=%d", url, r.status_code)
            return None
        if r.status_code in (429, 503) and attempt < MAX_RETRIES:
            ra = r.headers.get("retry-after")
            try:
                wait = float(ra) if ra else 2 ** attempt
            except ValueError:
                wait = 2 ** attempt
            _LOG.info("backoff url=%s status=%d wait=%.1fs", url, r.status_code, wait)
            time.sleep(wait)
            continue
        _LOG.warning("status url=%s status=%d", url, r.status_code)
        return None
    return None


def collect_koubo_links(html: bytes) -> list[tuple[str, str]]:
    """Extract [(detail_url, anchor_text), ...] from koubo index page."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not KOUBO_DETAIL_RE.search(href):
            continue
        full = urljoin("https://www.nedo.go.jp/", href)
        if full in seen:
            continue
        seen.add(full)
        text = a.get_text(strip=True)
        if not text:
            continue
        out.append((full, text))
    return out


_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")


def _normalize_date(jp: str | None) -> str | None:
    if not jp:
        return None
    m = _DATE_RE.search(jp)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"


def parse_koubo_detail(html: bytes, *, url: str, anchor_text: str) -> dict[str, Any]:
    """Extract canonical fields from a NEDO koubo detail page.

    Per TOS, body excerpt is hard-capped to MAX_BODY_EXCERPT char.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Name: prefer h1 (cleaning the prefix 「本公募」), then anchor_text fallback
    h1 = soup.find("h1")
    name = anchor_text
    if h1:
        h1_text = h1.get_text(strip=True)
        # NEDO h1 prefix patterns: "本公募「<NAME>」の公募について"
        m = re.search(r"[「『]([^」』]+)[」』]", h1_text)
        if m:
            name = m.group(1).strip()
        else:
            name = h1_text
    # Strip excessive trailing 「の公募について」 if anchor was the source
    name = re.sub(r"の公募について(?:[（(][^）)]+[)）])?$", "", name).strip()
    name = name[:300]

    text = soup.get_text("\n", strip=True)

    # Status: 予告 / 公募 / 決定 — look at h1 or first lines, plus title
    status = "公募"
    title_tag = soup.find("title")
    title_text = title_tag.get_text(strip=True) if title_tag else ""
    blob = (title_text + " " + (h1.get_text(strip=True) if h1 else "")).strip()
    if "予告" in blob:
        status = "予告"
    elif "決定" in blob or "採択" in blob or "実施体制の決定" in blob:
        status = "決定"
    elif "公募" in blob:
        status = "公募"

    # Application dates: 応募期限 / 受付締切 / 受付開始
    open_m = re.search(r"受付開始[：:]\s*\n?\s*(\d{4}年\d{1,2}月\d{1,2}日)", text)
    close_m = re.search(
        r"(?:応募期限|受付締切|公募期間.{0,20}まで)[：:]\s*\n?\s*(\d{4}年\d{1,2}月\d{1,2}日)",
        text,
    )
    period_m = re.search(
        r"公募期間[：:]\s*\n?\s*(\d{4}年\d{1,2}月\d{1,2}日)\s*[～~〜\-－]+\s*(\d{4}年\d{1,2}月\d{1,2}日)",
        text,
    )
    application_open = _normalize_date(open_m.group(1) if open_m else None)
    application_close = _normalize_date(
        close_m.group(1) if close_m else (period_m.group(2) if period_m else None)
    )
    if application_open is None and period_m:
        application_open = _normalize_date(period_m.group(1))

    # Released-on header date (page-published)
    pub_m = re.search(
        r"本公募\s*\n[^\n]*\n(\d{4}年\d{1,2}月\d{1,2}日)", text, flags=re.S
    )
    page_date = _normalize_date(pub_m.group(1) if pub_m else None)

    # Department / unit hint — common phrasings:
    #   "担当：NEDO XX部 XXユニット" / "問合せ先：XX部"
    dept = None
    dept_m = re.search(r"担当[：:]\s*([^\n。]{1,80})", text)
    if dept_m:
        dept = dept_m.group(1).strip()
    if dept is None:
        dept_m2 = re.search(r"NEDO\s*([^\n、。]{1,30}部[^\n、。]{0,40})", text)
        if dept_m2:
            dept = dept_m2.group(1).strip()

    # Field code (first 2 chars of program code in URL)
    code_m = KOUBO_DETAIL_RE.search(url)
    program_code = code_m.group(1) if code_m else None
    field_code = re.match(r"([A-Z]{1,3})", program_code).group(1) if program_code else None

    # Body excerpt, hard-capped per TOS.
    excerpt = ""
    # Skip nav junk; pick first paragraph after h1 with substantive text.
    for line in text.split("\n"):
        ln = line.strip()
        if len(ln) >= 20 and "NEDO" in ln and ("という" in ln or "公募" in ln):
            excerpt = ln[:MAX_BODY_EXCERPT]
            break
    if not excerpt:
        # fallback: first paragraph >= 30 char
        for line in text.split("\n"):
            ln = line.strip()
            if len(ln) >= 30 and not ln.startswith(("ホーム", "本文へ", "English", "検索")):
                excerpt = ln[:MAX_BODY_EXCERPT]
                break

    return {
        "primary_name": name,
        "status": status,
        "application_open_date": application_open,
        "application_close_date": application_close,
        "page_date": page_date,
        "department": dept,
        "program_code": program_code,
        "field_code": field_code,
        "excerpt": excerpt,
    }


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
    """Idempotent upsert (insert/update/skip)."""
    row = conn.execute(
        "SELECT excluded, primary_name FROM programs WHERE unified_id = ?", (uid,)
    ).fetchone()

    enriched_json = json.dumps(enriched, ensure_ascii=False)
    source_mentions = json.dumps(
        [{
            "source": "nedo.go.jp",
            "attribution": ATTRIBUTION,
            "license": LICENSE_NOTE,
            "issuer_hojin_bangou": NEDO_HOJIN_BANGOU,
        }],
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
                uid, name, None,
                AUTHORITY_LEVEL, ISSUER_NAME, None, None,
                "subsidy", source_url,
                None, None, None,
                None, tier, None, None, None,
                0, None,
                None, None,
                None, None,
                None, application_window_json,
                enriched_json, source_mentions,
                source_url, now_iso, None,
                now_iso,
            ),
        )
        conn.execute(
            "INSERT INTO programs_fts(unified_id, primary_name, aliases, enriched_text) "
            "VALUES (?,?,?,?)",
            (uid, name, "", name),
        )
        return "insert"

    if row[0]:  # excluded
        return "skip"

    sets = ["source_fetched_at = ?", "enriched_json = ?", "updated_at = ?"]
    vals: list[Any] = [now_iso, enriched_json, now_iso]
    if application_window_json:
        sets.append("application_window_json = COALESCE(application_window_json, ?)")
        vals.append(application_window_json)
    if not row[1]:
        sets.append("primary_name = ?")
        vals.append(name)
    vals.append(uid)
    conn.execute(f"UPDATE programs SET {', '.join(sets)} WHERE unified_id = ?", vals)
    return "update"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--pages", type=int, default=5,
                   help="number of koubo index pages to walk (10 entries each)")
    p.add_argument("--max", type=int, default=80, help="cap programs to ingest")
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

    # Step 1: walk N koubo index pages → collect detail urls
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pg in range(1, args.pages + 1):
        idx = KOUBO_INDEX.format(page=pg)
        body = fetch(client, idx, host_clock)
        if body is None:
            _LOG.warning("page %d unreachable", pg)
            continue
        for url, text in collect_koubo_links(body):
            if url in seen:
                continue
            seen.add(url)
            candidates.append((url, text))
        _LOG.info("page=%d cumulative=%d", pg, len(candidates))
        if len(candidates) >= args.max:
            break

    if args.max:
        candidates = candidates[: args.max]
    _LOG.info("total koubo candidates: %d", len(candidates))

    # Step 2: open DB
    conn = sqlite3.connect(args.db, timeout=300)
    conn.execute("PRAGMA busy_timeout = 300000;")

    inserted = updated = skipped = errors = 0
    try:
        if not args.dry_run:
            conn.execute("BEGIN IMMEDIATE;")

        for url, anchor_text in candidates:
            body = fetch(client, url, host_clock)
            if body is None:
                errors += 1
                continue
            try:
                meta = parse_koubo_detail(body, url=url, anchor_text=anchor_text)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("parse fail %s err=%s", url, exc)
                errors += 1
                continue

            tier = TIER_OPEN if meta["status"] in ("公募", "予告") else TIER_DECIDED
            uid = compute_unified_id(url)
            now_iso = datetime.now(UTC).isoformat(timespec="seconds")

            window: dict[str, Any] = {}
            if meta["application_open_date"]:
                window["open_date"] = meta["application_open_date"]
            if meta["application_close_date"]:
                window["close_date"] = meta["application_close_date"]
            if meta["page_date"]:
                window["page_date"] = meta["page_date"]
            window_json = json.dumps(window, ensure_ascii=False) if window else None

            enriched = {
                "anchor_text": anchor_text,
                "status": meta["status"],
                "department": meta["department"],
                "program_code": meta["program_code"],
                "field_code": meta["field_code"],
                "issuer": ISSUER_NAME,
                "issuer_hojin_bangou": NEDO_HOJIN_BANGOU,
                "fetched_at": now_iso,
                "license_note": LICENSE_NOTE,
                "excerpt_<=200char": meta["excerpt"][:MAX_BODY_EXCERPT],
            }

            if args.dry_run:
                _LOG.info(
                    "dry-run: tier=%s status=%s name=%s url=%s",
                    tier, meta["status"], meta["primary_name"][:60], url,
                )
                continue

            try:
                outcome = upsert_program(
                    conn,
                    uid=uid,
                    name=meta["primary_name"],
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
        inserted, updated, skipped, errors, len(candidates),
    )
    print(
        f"nedo_ingest inserted={inserted} updated={updated} skipped={skipped} "
        f"errors={errors} candidates={len(candidates)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
