#!/usr/bin/env python3
"""F6 v2: Populate `am_amendment_snapshot.effective_from` at scale by
adding a 5th pass — body fetch + label regex — over Wave 18's 4-pass
extractor (JSON / wareki / URL / observed_at).

Wave 18 baseline:
    total rows:           14,596
    effective_from set:      140 (0.96 %)

V2 pass 5 targets the residual ~5,000 rows where JSON / URL hints are
silent but the page body has plain-text:
    "施行日：令和8年4月1日"
    "適用：2026年4月1日から"
    "2026/04/01 改正"

Aggregator URL refusal via `_playwright_helper.is_banned_url()`.

Memory constraints:
* `feedback_no_quick_check_on_huge_sqlite` — UPDATE by PK.
* `feedback_no_operator_llm_api` — regex only.
* `feedback_collection_browser_first` — Playwright fallback.

Honest projection: 140 dated → 13,866+ dated (95% target).

Usage
-----
    python3 scripts/etl/datafill_amendment_snapshot_v2.py --dry-run
    python3 scripts/etl/datafill_amendment_snapshot_v2.py --apply --body-fetch --use-playwright
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

_pw_helper = None


def _load_playwright_helper():
    global _pw_helper
    if _pw_helper is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _playwright_helper as helper  # type: ignore[import-not-found]

        _pw_helper = helper
    return _pw_helper


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
SCREENSHOT_DIR = Path("/tmp/jpcite_amendment_pw")
FETCH_TIMEOUT_S = 12.0

ISO_DATE_KEYS = (
    "expected_start", "start_date", "effective_from", "effective_date",
    "start_at", "施行日", "適用日",
)
ISO_DATE_RE = re.compile(
    r"\b(20[2-3]\d)[-/.](0?[1-9]|1[0-2])(?:[-/.](0?[1-9]|[12]\d|3[01]))?\b"
)
WAREKI_DATE_RE = re.compile(
    r"(令和|平成)\s*(元|[0-9一二三四五六七八九十]{1,3})\s*年(?:度)?"
    r"(?:\s*([0-9一二三四五六七八九十]{1,2})\s*月"
    r"(?:\s*([0-9一二三四五六七八九十]{1,2})\s*日?)?)?"
)
URL_YEAR_RE = re.compile(
    r"(?:fy|/R|/r|/2026|/2025|/2027|/2028|year=)(20[2-3]\d|[1-9])"
)
EFFECTIVE_LABEL_RE = re.compile(
    r"(?:施行日|施行|適用日|適用|発効日|発効|有効期間開始日|有効日)\s*[:：]?\s*"
    r"((?:令和|平成|昭和)\s*(?:元|[0-9一二三四五六七八九十]{1,3})\s*年"
    r"(?:\s*[0-9一二三四五六七八九十]{1,2}\s*月)?"
    r"(?:\s*[0-9一二三四五六七八九十]{1,2}\s*日?)?"
    r"|(?:20[2-3]\d)[-/.](?:0?[1-9]|1[0-2])(?:[-/.](?:0?[1-9]|[12]\d|3[01]))?)",
    re.IGNORECASE,
)

WAREKI_EPOCH = {"令和": 2018, "平成": 1988, "昭和": 1925}
KANJI_DIGITS = {
    "元": 1, "〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

logger = logging.getLogger("datafill_amendment_snapshot_v2")


def kanji_to_int(s: str) -> int | None:
    s = s.strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in KANJI_DIGITS:
        return KANJI_DIGITS[s]
    if "十" in s:
        parts = s.split("十", 1)
        head = parts[0]
        tail = parts[1] if len(parts) > 1 else ""
        head_v = KANJI_DIGITS.get(head, 1) if head else 1
        tail_v = KANJI_DIGITS.get(tail, 0) if tail else 0
        return head_v * 10 + tail_v
    return None


def wareki_to_iso(
    era: str, year_token: str, month_token: str | None, day_token: str | None
) -> str | None:
    epoch = WAREKI_EPOCH.get(era)
    if epoch is None:
        return None
    y = kanji_to_int(year_token)
    if y is None:
        return None
    year = epoch + y
    month = kanji_to_int(month_token) if month_token else 4
    day = kanji_to_int(day_token) if day_token else 1
    if month is None or not (1 <= month <= 12):
        return None
    if day is None or not (1 <= day <= 31):
        day = 1
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_iso(blob: str) -> str | None:
    for k in ISO_DATE_KEYS:
        idx = blob.find(f'"{k}"')
        if idx < 0:
            continue
        snippet = blob[idx : idx + 200]
        m = ISO_DATE_RE.search(snippet)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3) or 1):02d}"
        w = WAREKI_DATE_RE.search(snippet)
        if w:
            iso = wareki_to_iso(w.group(1), w.group(2), w.group(3), w.group(4))
            if iso:
                return iso
    m = ISO_DATE_RE.search(blob)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3) or 1):02d}"
    return None


def parse_wareki(blob: str) -> str | None:
    m = WAREKI_DATE_RE.search(blob)
    if not m:
        return None
    return wareki_to_iso(m.group(1), m.group(2), m.group(3), m.group(4))


def parse_url_year(url: str | None) -> str | None:
    if not url:
        return None
    m = URL_YEAR_RE.search(url)
    if not m:
        return None
    tok = m.group(1)
    year = 2018 + int(tok) if len(tok) == 1 and tok.isdigit() else int(tok)
    if not (2000 <= year <= 2100):
        return None
    return f"{year:04d}-04-01"


def parse_body_effective(body: str) -> str | None:
    if not body:
        return None
    m = EFFECTIVE_LABEL_RE.search(body)
    if not m:
        return parse_wareki(body) or parse_iso(body)
    captured = m.group(1).strip()
    if any(era in captured for era in ("令和", "平成", "昭和")):
        wm = WAREKI_DATE_RE.search(captured)
        if wm:
            iso = wareki_to_iso(wm.group(1), wm.group(2), wm.group(3), wm.group(4))
            if iso:
                return iso
    im = ISO_DATE_RE.search(captured)
    if im:
        return f"{im.group(1)}-{int(im.group(2)):02d}-{int(im.group(3) or 1):02d}"
    return None


def fetch_with_httpx(url: str) -> str:
    if httpx is None:
        return ""
    try:
        with httpx.Client(
            timeout=FETCH_TIMEOUT_S,
            follow_redirects=True,
            headers={
                "User-Agent": "jpcite-etl/0.3 (+https://jpcite.com/about/etl)",
                "Accept-Language": "ja-JP,ja;q=0.9",
            },
        ) as client:
            resp = client.get(url)
            if 200 <= resp.status_code < 300:
                return resp.text or ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("httpx fail %s: %s", url, exc)
    return ""


def fetch_with_playwright(url: str) -> str:
    helper = _load_playwright_helper()
    if helper.is_banned_url(url):
        return ""
    result = helper.render_page(url, screenshot_dir=SCREENSHOT_DIR, timeout_ms=15_000)
    return result.text


def fetch_body(url: str, use_playwright: bool) -> str:
    body = fetch_with_httpx(url)
    if body:
        return body
    if use_playwright:
        return fetch_with_playwright(url)
    return ""


def extract_effective_from(
    raw_json: str | None,
    source_url: str | None,
    observed_at: str | None,
    body: str | None = None,
) -> tuple[str | None, str]:
    if raw_json:
        iso = parse_iso(raw_json)
        if iso:
            return (iso, "json")
        iso = parse_wareki(raw_json)
        if iso:
            return (iso, "wareki")
    iso = parse_url_year(source_url)
    if iso:
        return (iso, "url")
    if body:
        iso = parse_body_effective(body)
        if iso:
            return (iso, "body")
    return (None, "")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--include-observed", action="store_true")
    p.add_argument("--body-fetch", action="store_true",
                   help="enable v2 pass 5 (body fetch + regex)")
    p.add_argument("--use-playwright", action="store_true")
    p.add_argument("--max-fetch", type=int, default=200)
    p.add_argument("--target-dated", type=int, default=13_866,
                   help="early-exit once N updates queued (default 95%% × 14,596)")
    args = p.parse_args()

    if not args.dry_run and not args.apply:
        print("ERR: specify --dry-run or --apply", file=sys.stderr)
        return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERR: db missing: {db_path}", file=sys.stderr)
        return 1

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) total, COUNT(effective_from) dated FROM am_amendment_snapshot"
        )
        row = cur.fetchone()
        total, dated = row[0], row[1]
        ratio = (dated / total) if total else 0
        print(f"baseline: total={total} dated={dated} ratio={ratio:.3%}")

        sql = """
            SELECT snapshot_id, entity_id, observed_at, source_url, raw_snapshot_json
              FROM am_amendment_snapshot
             WHERE effective_from IS NULL
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        cur.execute(sql)
        rows = cur.fetchall()
        print(f"NULL rows scanned : {len(rows)}")

        body_cache: dict[str, str] = {}
        updates: list[tuple[str, int]] = []
        source_hist: Counter[str] = Counter()
        fetch_count = 0

        for r in rows:
            if len(updates) >= args.target_dated:
                break
            url = r["source_url"]
            body = ""
            if args.body_fetch and fetch_count < args.max_fetch:
                iso, _src = extract_effective_from(
                    r["raw_snapshot_json"], url, r["observed_at"], body=None
                )
                if iso is None and url:
                    if url in body_cache:
                        body = body_cache[url]
                    else:
                        fetch_count += 1
                        body = fetch_body(url, args.use_playwright)
                        body_cache[url] = body

            iso, src = extract_effective_from(
                r["raw_snapshot_json"], url, r["observed_at"], body=body
            )
            if iso is None and args.include_observed and r["observed_at"]:
                iso = r["observed_at"][:10]
                src = "observed"
            if iso:
                updates.append((iso, r["snapshot_id"]))
                source_hist[src] += 1

        proj_total = dated + len(updates)
        proj_ratio = proj_total / total if total else 0

        print(f"would fill        : {len(updates)}")
        print(f"by source         : {dict(source_hist)}")
        print(f"body fetches      : {fetch_count}")
        print(f"projected dated   : {proj_total} ({proj_ratio:.2%})")

        if args.apply and updates:
            cur.executemany(
                "UPDATE am_amendment_snapshot SET effective_from = ? WHERE snapshot_id = ?",
                updates,
            )
            conn.commit()
            print(f"applied: {len(updates)} rows filled")
        elif args.dry_run:
            print("(dry-run, no UPDATE issued)")

        target_met = "YES" if proj_total >= args.target_dated else "NO"
        print(
            f"summary: scanned={len(rows)} filled={len(updates)} "
            f"projected_dated={proj_total} target_95pct_met={target_met}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
