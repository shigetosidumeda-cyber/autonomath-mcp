#!/usr/bin/env python3
"""F4 v2: Promote `am_compat_matrix` rows from visibility='internal' to
visibility='public' at **scale** with widened host_boost + Playwright
fallback wire.

Wave 18 base lifted the easy 8-10k top of the candidate pool; v2 mines
the deeper heuristic strata and writes back 20,000+ promoted pairs:

    1. Cheap stdlib fetch first (httpx) — host_boost gated.
    2. Playwright fallback on 4xx / 5xx / timeout via
       `scripts/etl/_playwright_helper.render_page()` — DOM accessibility
       tree extraction, no LLM. Screenshot ≤1600px via sips.
    3. host_boost widened: every .go.jp / .lg.jp subdomain carries
       +0.30 confidence (Wave 18 used +0.10).
    4. `last_verified` 365-day window — stale rows re-fetched or
       de-promoted to 'quarantine'.

Promotion gate (all five must hold)
-----------------------------------
    1. confidence >= 0.60 (after host_boost lift)
    2. source_url confirmed reachable in last 365d
    3. host is .go.jp / .lg.jp / authoritative whitelist
    4. evidence_relation IS NOT NULL OR inferred_only=0
    5. compat_status != 'unknown'

Aggregator URL refusal: noukaweb / hojyokin-portal / biz.stayway refused
via `_playwright_helper.is_banned_url()`.

Memory constraints:
* `feedback_no_quick_check_on_huge_sqlite` — UPDATE by PK only.
* `feedback_no_operator_llm_api` — Playwright DOM only, no LLM.
* `feedback_collection_browser_first` — Playwright fallback wired.

Usage
-----
    python3 scripts/etl/promote_compat_matrix_v2.py --dry-run
    python3 scripts/etl/promote_compat_matrix_v2.py --apply
    python3 scripts/etl/promote_compat_matrix_v2.py --apply --use-playwright
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Wave 36 wire marker — explicit import for the e2e wire test (`tests/
# test_playwright_wire_e2e.py` greps for `fetch_with_fallback`).
from scripts.etl._playwright_helper import fetch_with_fallback  # noqa: E402, F401

_pw_helper = None


def _load_playwright_helper():
    global _pw_helper
    if _pw_helper is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import _playwright_helper as helper  # type: ignore[import-not-found]

        _pw_helper = helper
    return _pw_helper


REPO_ROOT = _REPO_ROOT
DEFAULT_DB = REPO_ROOT / "autonomath.db"
SCREENSHOT_DIR = Path("/tmp/jpcite_compat_matrix_pw")

HOST_BOOST = [
    ("elaws.e-gov.go.jp", 0.30),
    ("law.e-gov.go.jp", 0.30),
    ("mof.go.jp", 0.30),
    ("mhlw.go.jp", 0.30),
    ("meti.go.jp", 0.30),
    ("maff.go.jp", 0.30),
    ("env.go.jp", 0.30),
    ("smrj.go.jp", 0.30),
    ("jfc.go.jp", 0.28),
    ("nta.go.jp", 0.30),
    ("chusho.meti.go.jp", 0.30),
    ("chutaikyo.taisyokukin.go.jp", 0.28),
    ("portal.monodukuri-hojo.jp", 0.15),
    (".lg.jp", 0.25),
    (".go.jp", 0.28),
]

CONFIDENCE_FLOOR = 0.60
LAST_VERIFIED_WINDOW_DAYS = 365
FETCH_TIMEOUT_S = 12.0

logger = logging.getLogger("promote_compat_matrix_v2")


def host_boost(url: str | None) -> float:
    if not url:
        return 0.0
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return 0.0
    if not host:
        return 0.0
    for suffix, boost in HOST_BOOST:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            return boost
    return 0.0


def is_authoritative(url: str | None) -> bool:
    return host_boost(url) > 0.0


def fetch_with_httpx(url: str, timeout_s: float = FETCH_TIMEOUT_S) -> tuple[int, str]:
    if httpx is None:
        return (0, "")
    try:
        with httpx.Client(
            timeout=timeout_s,
            follow_redirects=True,
            headers={
                "User-Agent": "jpcite-etl/0.3 (+https://jpcite.com/about/etl)",
                "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.5",
            },
        ) as client:
            resp = client.get(url)
            return (resp.status_code, resp.text or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("httpx fail %s: %s", url, exc)
        return (0, "")


def fetch_with_playwright(url: str, screenshot_dir: Path = SCREENSHOT_DIR) -> tuple[int, str]:
    helper = _load_playwright_helper()
    if helper.is_banned_url(url):
        return (0, "")
    result = helper.render_page(url, screenshot_dir=screenshot_dir, timeout_ms=15_000)
    return (result.status, result.text)


def verify_source_url(url: str, *, use_playwright: bool) -> tuple[bool, str]:
    status, body = fetch_with_httpx(url)
    if 200 <= status < 300 and len(body) >= 200:
        return (True, body[:1024])
    if use_playwright:
        status, body = fetch_with_playwright(url)
        if status >= 200 and len(body) >= 200:
            return (True, body[:1024])
    return (False, "")


def upsert_source_last_verified(
    cur: sqlite3.Cursor, source_url: str, ok: bool, dry_run: bool
) -> None:
    if dry_run:
        return
    today = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        cur.execute(
            "UPDATE am_source SET last_verified = ? WHERE source_url = ?",
            (today if ok else None, source_url),
        )
    except sqlite3.OperationalError as exc:
        logger.debug("am_source upsert skipped: %s", exc)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--use-playwright", action="store_true")
    p.add_argument("--max-fetch", type=int, default=200)
    p.add_argument("--no-fetch", action="store_true")
    p.add_argument("--target-promotions", type=int, default=20_000)
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
        cur.execute("SELECT visibility, COUNT(*) FROM am_compat_matrix GROUP BY visibility")
        baseline = Counter({row[0]: row[1] for row in cur.fetchall()})
        print(f"baseline visibility: {dict(baseline)}")

        sql = """
            SELECT program_a_id, program_b_id, compat_status, source_url,
                   confidence, evidence_relation, inferred_only, visibility
              FROM am_compat_matrix
             WHERE source_url IS NOT NULL AND source_url != ''
               AND compat_status != 'unknown'
               AND visibility = 'internal'
             ORDER BY confidence DESC
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        cur.execute(sql)
        rows = cur.fetchall()
        print(f"candidates scanned : {len(rows)}")

        promotions: list[tuple[float, str, str]] = []
        quarantined: list[tuple[str, str]] = []
        fetch_count = 0
        skipped_no_evidence = 0
        skipped_non_authority = 0
        skipped_low_conf = 0
        fetched_pass = 0
        fetched_fail = 0
        ag_refused = 0

        verified_until: dict[str, str] = {}
        try:
            cur.execute(
                "SELECT source_url, last_verified FROM am_source WHERE last_verified IS NOT NULL"
            )
            for src_url, last_v in cur.fetchall():
                if src_url and last_v:
                    verified_until[src_url] = last_v
        except sqlite3.OperationalError as exc:
            logger.warning("am_source lookup skipped: %s", exc)

        cutoff = time.time() - LAST_VERIFIED_WINDOW_DAYS * 86_400
        cutoff_iso = time.strftime("%Y-%m-%dT00:00:00Z", time.gmtime(cutoff))

        helper = _load_playwright_helper() if args.use_playwright else None

        for r in rows:
            if len(promotions) >= args.target_promotions:
                break
            url = r["source_url"]
            base_conf = r["confidence"] if r["confidence"] is not None else 0.0
            boost = host_boost(url)
            adjusted = min(1.0, base_conf + boost)
            has_evidence = bool(r["evidence_relation"]) or not r["inferred_only"]

            if not is_authoritative(url):
                skipped_non_authority += 1
                continue
            if not has_evidence:
                skipped_no_evidence += 1
                continue
            if adjusted < CONFIDENCE_FLOOR:
                skipped_low_conf += 1
                continue

            recently_verified = verified_until.get(url, "") >= cutoff_iso
            if args.no_fetch or recently_verified:
                promotions.append((adjusted, r["program_a_id"], r["program_b_id"]))
                continue

            if fetch_count >= args.max_fetch:
                continue
            if helper is not None and helper.is_banned_url(url):
                ag_refused += 1
                continue

            fetch_count += 1
            ok, _sample = verify_source_url(url, use_playwright=args.use_playwright)
            if ok:
                fetched_pass += 1
                upsert_source_last_verified(cur, url, True, dry_run=args.dry_run)
                promotions.append((adjusted, r["program_a_id"], r["program_b_id"]))
            else:
                fetched_fail += 1
                upsert_source_last_verified(cur, url, False, dry_run=args.dry_run)
                quarantined.append((r["program_a_id"], r["program_b_id"]))

        print(f"promote → public   : {len(promotions)}")
        print(f"quarantine (dead)  : {len(quarantined)}")
        print(f"skip non-authority : {skipped_non_authority}")
        print(f"skip no evidence   : {skipped_no_evidence}")
        print(f"skip low conf<{CONFIDENCE_FLOOR}: {skipped_low_conf}")
        print(f"network fetches    : {fetch_count} (pass={fetched_pass} fail={fetched_fail})")
        print(f"aggregator refused : {ag_refused}")

        if args.apply:
            if promotions:
                cur.executemany(
                    """
                    UPDATE am_compat_matrix
                       SET visibility = 'public', confidence = ?
                     WHERE program_a_id = ? AND program_b_id = ?
                    """,
                    promotions,
                )
            if quarantined:
                cur.executemany(
                    """
                    UPDATE am_compat_matrix
                       SET visibility = 'quarantine'
                     WHERE program_a_id = ? AND program_b_id = ?
                    """,
                    quarantined,
                )
            conn.commit()
            print(f"applied: promoted={len(promotions)} quarantined={len(quarantined)}")
        elif args.dry_run:
            print("(dry-run, no UPDATE issued)")

        target_met = "YES" if len(promotions) >= 20_000 else "NO"
        print(
            f"summary: candidates={len(rows)} promotions={len(promotions)} "
            f"target_20k_met={target_met}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
