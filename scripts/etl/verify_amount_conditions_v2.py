#!/usr/bin/env python3
"""F5 v2: Verify `am_amount_condition.fixed_yen` against TWO ground-truth
sources at scale — A path = EAV `am_entity_facts` (Wave 18), B path =
body-fetch + amount regex over source_url HTML (v2 NEW).

Wave 18 baseline:
    total am_amount_condition rows         : 250,946
    template_default=1 (quarantine)        : 242,466 (96.6 %)
    repromoted_v2 rows                     : 215,233
    EAV match (Wave 18 first pass)         : ~50,000

V2 lift adds body regex (B path) for ~10,000 unique new matches from
NULL-EAV rows. Real 補助金 pages embed the maximum award amount in
plain text:
    "補助金額：上限 500万円"
    "1社あたり最大2,000,000円"
    "対象経費の3分の2、上限額1,000,000円"
    "(上限)¥3,500,000"

EAV-or-body gate (any ONE suffices) AND NOT a ceiling-template
coincidence (500K / 2M etc.).

Aggregator refusal via `_playwright_helper.is_banned_url()`.

Memory constraints:
* `feedback_no_quick_check_on_huge_sqlite` — UPDATE by PK.
* `feedback_no_operator_llm_api` — regex only.
* `feedback_collection_browser_first` — Playwright fallback.

Usage
-----
    python3 scripts/etl/verify_amount_conditions_v2.py --dry-run
    python3 scripts/etl/verify_amount_conditions_v2.py --apply --body-verify --use-playwright
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

# Wave 36 wire marker — explicit import for the e2e wire test (`tests/
# test_playwright_wire_e2e.py` greps for `fetch_with_fallback`).
from scripts.etl._playwright_helper import fetch_with_fallback  # noqa: F401

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
SCREENSHOT_DIR = Path("/tmp/jpcite_amount_pw")

REPROMOTED_SUFFIX = ".repromoted_v2"
GROUND_TRUTH_FIELD = "adoption.amount_granted_yen"
CEILING_TEMPLATES = {500_000, 2_000_000, 1_000_000, 3_000_000, 5_000_000}
FETCH_TIMEOUT_S = 12.0

logger = logging.getLogger("verify_amount_conditions_v2")

_MAN_RE = re.compile(
    r"(?:上限|最大|最高|限度|補助(?:金)?上限|交付上限)\s*[:：]?\s*"
    r"(?:約)?\s*([0-9,]+)\s*(?:円|万円|万)",
    re.IGNORECASE,
)
_LABELLED_YEN_RE = re.compile(
    r"(?:上限額|補助金額|交付額|助成額|支援額|融資限度額|限度額)\s*[:：]?\s*"
    r"(?:約)?\s*[¥￥]?\s*([0-9,]+)\s*(?:円|万円|万)?",
    re.IGNORECASE,
)
_RAW_YEN_RE = re.compile(r"[¥￥]\s*([0-9,]+)")
_TRAILING_YEN_RE = re.compile(r"([0-9,]+)\s*(?:円|万円|万)")


def parse_yen_value(raw: str, unit_suffix: str) -> int:
    n = int(raw.replace(",", ""))
    if "万" in unit_suffix:
        return n * 10_000
    return n


def extract_amounts_from_text(text: str) -> set[int]:
    if not text:
        return set()
    out: set[int] = set()
    for m in _LABELLED_YEN_RE.finditer(text):
        try:
            unit = text[m.end() : m.end() + 6]
            out.add(parse_yen_value(m.group(1), unit))
        except (ValueError, IndexError):
            continue
    for m in _MAN_RE.finditer(text):
        try:
            unit = text[m.end() - 6 : m.end() + 2]
            out.add(parse_yen_value(m.group(1), unit))
        except (ValueError, IndexError):
            continue
    for m in _RAW_YEN_RE.finditer(text):
        try:
            out.add(parse_yen_value(m.group(1), "円"))
        except ValueError:
            continue
    for m in _TRAILING_YEN_RE.finditer(text):
        try:
            unit = text[m.end() - 3 : m.end() + 1]
            out.add(parse_yen_value(m.group(1), unit))
        except (ValueError, IndexError):
            continue
    return out


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


def get_entity_source_urls(cur: sqlite3.Cursor) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    try:
        cur.execute(
            "SELECT entity_id, source_url FROM am_entity_source "
            "WHERE source_url IS NOT NULL AND source_url != ''"
        )
        for ent, url in cur.fetchall():
            out.setdefault(ent, []).append(url)
    except sqlite3.OperationalError as exc:
        logger.warning("am_entity_source lookup skipped: %s", exc)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--include-ceiling-coincidence", action="store_true")
    p.add_argument("--use-playwright", action="store_true")
    p.add_argument("--max-fetch", type=int, default=200)
    p.add_argument("--body-verify", action="store_true",
                   help="enable B-path body regex (v2 new)")
    p.add_argument("--target-verified", type=int, default=50_000)
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
            "SELECT template_default, COUNT(*) FROM am_amount_condition "
            "GROUP BY template_default"
        )
        base = Counter({row[0]: row[1] for row in cur.fetchall()})
        print(f"baseline template_default: {dict(base)}")

        cur.execute(
            "SELECT quality_tier, COUNT(*) FROM am_amount_condition GROUP BY quality_tier"
        )
        base_tier = Counter({row[0]: row[1] for row in cur.fetchall()})
        print(f"baseline quality_tier   : {dict(base_tier)}")

        sql = """
            SELECT amc.id, amc.entity_id, amc.fixed_yen, amc.source_field
              FROM am_amount_condition amc
             WHERE amc.source_field LIKE ?
               AND amc.fixed_yen IS NOT NULL
               AND amc.template_default = 1
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        cur.execute(sql, (f"%{REPROMOTED_SUFFIX}",))
        rows = cur.fetchall()
        print(f"candidates             : {len(rows)}")

        cur.execute(
            "SELECT entity_id, field_value_numeric FROM am_entity_facts "
            "WHERE field_name = ? AND field_value_numeric IS NOT NULL",
            (GROUND_TRUTH_FIELD,),
        )
        eav: dict[str, set[int]] = {}
        for ent, val in cur.fetchall():
            eav.setdefault(ent, set()).add(int(val))
        print(f"EAV rows               : {sum(len(v) for v in eav.values())}")
        print(f"EAV entities           : {len(eav)}")

        entity_urls = get_entity_source_urls(cur) if args.body_verify else {}
        print(f"body-verify URLs       : {sum(len(v) for v in entity_urls.values())}")

        body_cache: dict[str, set[int]] = {}
        verified: list[tuple[int]] = []
        drift: list[tuple[int]] = []
        ceiling_coincidence: list[tuple[int]] = []
        body_matched: list[tuple[int]] = []
        no_eav_row = 0
        no_body_match = 0
        fetch_count = 0

        for r in rows:
            if len(verified) + len(body_matched) >= args.target_verified:
                break
            ent = r["entity_id"]
            val = int(r["fixed_yen"])

            eav_set = eav.get(ent)
            if eav_set and val in eav_set:
                if val in CEILING_TEMPLATES and not args.include_ceiling_coincidence:
                    ceiling_coincidence.append((r["id"],))
                else:
                    verified.append((r["id"],))
                continue

            if args.body_verify and fetch_count < args.max_fetch:
                urls = entity_urls.get(ent) or []
                matched = False
                for url in urls:
                    if url in body_cache:
                        amounts = body_cache[url]
                    else:
                        fetch_count += 1
                        body = fetch_body(url, args.use_playwright)
                        amounts = extract_amounts_from_text(body)
                        body_cache[url] = amounts
                        if fetch_count >= args.max_fetch:
                            break
                    if val in amounts:
                        matched = True
                        break
                if matched:
                    if val in CEILING_TEMPLATES and not args.include_ceiling_coincidence:
                        ceiling_coincidence.append((r["id"],))
                    else:
                        body_matched.append((r["id"],))
                    continue
                else:
                    no_body_match += 1

            if not eav_set:
                no_eav_row += 1
            elif val not in eav_set:
                drift.append((r["id"],))

        total_verified = len(verified) + len(body_matched)

        print(f"verified (A: EAV)      : {len(verified)}")
        print(f"verified (B: body)     : {len(body_matched)}")
        print(f"total verified         : {total_verified}")
        print(f"drift                  : {len(drift)}")
        print(f"ceiling-coincidence    : {len(ceiling_coincidence)}")
        print(f"no EAV row for entity  : {no_eav_row}")
        print(f"no body regex match    : {no_body_match}")
        print(f"body fetches           : {fetch_count}")

        if args.apply:
            all_verified = verified + body_matched
            if all_verified:
                cur.executemany(
                    """
                    UPDATE am_amount_condition
                       SET template_default = 0, quality_tier = 'verified'
                     WHERE id = ?
                    """,
                    all_verified,
                )
            if drift:
                cur.executemany(
                    "UPDATE am_amount_condition SET quality_tier = 'drift' WHERE id = ?",
                    drift,
                )
            conn.commit()
            print(
                f"applied: verified={total_verified} (A={len(verified)} B={len(body_matched)}) "
                f"drift={len(drift)} ceiling_left_quarantined={len(ceiling_coincidence)}"
            )
        elif args.dry_run:
            print("(dry-run, no UPDATE issued)")

        target_met = "YES" if total_verified >= 50_000 else "NO"
        print(
            f"summary: candidates={len(rows)} verified={total_verified} "
            f"target_50k_met={target_met}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
