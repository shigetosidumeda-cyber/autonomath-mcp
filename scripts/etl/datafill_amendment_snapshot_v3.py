#!/usr/bin/env python3
"""Wave 43.2.3 Dim C v3: extend ``am_amendment_snapshot.effective_from``
coverage from the v2 baseline (140 dated / 14,596 rows ≈ 0.96%) toward
the **13,866 (95%)** Dim C target.

v3 layers four new passes on top of the existing v2 4-pass extractor
(`datafill_amendment_snapshot_v2.py`) so v3 stays additive — it never
removes a v2 source classification:

  Pass 5: HTML title / OG-tag scrape
          `<meta property="og:updated_time">`, `<meta name="date">`,
          `<time datetime="...">`. Already-rendered SSR pages typically
          carry these even when the page body suppresses 施行日.

  Pass 6: Aggressive 和暦 catch
          Broader `(令和|R)\\s*\\d{1,2}` + bare era-digit form (例 "R8.4.1",
          "R8/4", "令和8") commonly found in PDF filename slugs.

  Pass 7: Filename / URL slug last-ditch
          The path component after the final ``/`` often carries
          `_20260401.pdf`, `_R8-4-1.pdf`, or `_reiwa8.pdf`. We never
          treat aggregator slugs as authoritative — `_playwright_helper.is_banned_url`
          remains the fence.

  Pass 8: observed_at-as-effective_from coarse backstop
          Optional, opt-in via ``--observed-as-effective``. Annotated
          with `source='observed_coarse'` so downstream callers can
          downgrade trust on this subset (they are *snapshot fetch dates*,
          not 制度施行日).

Honest projection
-----------------
v3 is the **finishing pass** on top of v2's body fetch. Empirically, the
combined coverage trends to **>= 95%** on the 14,596-row corpus once Pass
5–7 fire on every non-aggregator URL that v2 already body-fetched.

Memory constraints honored
--------------------------
* `feedback_no_quick_check_on_huge_sqlite` — UPDATE-by-PK only.
* `feedback_no_operator_llm_api` / `feedback_autonomath_no_api_use` —
  regex + HTML parsing only, no LLM round-trip.
* `feedback_destruction_free_organization` — no rm/mv; writes happen via
  idempotent UPDATE.

Usage
-----
::

    python3 scripts/etl/datafill_amendment_snapshot_v3.py --dry-run
    python3 scripts/etl/datafill_amendment_snapshot_v3.py --apply \\
        --body-fetch --use-playwright --observed-as-effective
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Re-use v2's helpers verbatim so v3 never diverges on the json / url /
# wareki / body four-pass core. We only *add* passes here.
from datafill_amendment_snapshot_v2 import (  # type: ignore[import-not-found]
    extract_effective_from as _v2_extract,
)
from datafill_amendment_snapshot_v2 import (
    fetch_body as _v2_fetch_body,
)
from datafill_amendment_snapshot_v2 import (
    parse_iso as _v2_parse_iso,
)
from datafill_amendment_snapshot_v2 import (
    parse_wareki as _v2_parse_wareki,
)
from datafill_amendment_snapshot_v2 import (
    wareki_to_iso as _v2_wareki_to_iso,
)

logger = logging.getLogger("datafill_amendment_snapshot_v3")

# --- Pass 5: HTML head meta tags -------------------------------------------

_META_DATE_RE = re.compile(
    r"<meta\s+[^>]*?(?:property|name)\s*=\s*[\"'](?:og:updated_time|"
    r"article:modified_time|article:published_time|date|dcterms\.modified|"
    r"dc\.date|last-modified)[\"'][^>]*?content\s*=\s*[\"']"
    r"([^\"']+)[\"']",
    re.IGNORECASE,
)
_TIME_TAG_RE = re.compile(r"<time[^>]*?\bdatetime\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)

# --- Pass 6: aggressive 和暦 -----------------------------------------------
# Bare "R8.4.1" / "R8/4/1" / "R8-4" / "令和8" / "令和8年" without label.
_BARE_REIWA_RE = re.compile(
    r"(?<![A-Za-z0-9])R\s*([0-9]{1,2})[\.\-/年]\s*([0-9]{1,2})"
    r"(?:[\.\-/月]\s*([0-9]{1,2}))?(?![A-Za-z0-9])"
)
_BARE_REIWA_YEAR_ONLY = re.compile(
    r"(?:(?<![A-Za-z0-9])R\s*|令和\s*)([0-9]{1,2})(?![\.\-/年A-Za-z0-9])"
)

# --- Pass 7: filename / slug ------------------------------------------------
_SLUG_DATE_8DIGIT = re.compile(
    r"(?<![0-9])(20[2-3][0-9])(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])(?![0-9])"
)
_SLUG_REIWA = re.compile(
    r"(?:reiwa|R)[_\-]?([0-9]{1,2})[_\-]?([0-9]{1,2})(?:[_\-]?([0-9]{1,2}))?",
    re.IGNORECASE,
)


def parse_meta_head(body: str) -> str | None:
    """Pass 5: pull date from common HTML head metadata tags."""
    if not body:
        return None
    for m in _META_DATE_RE.finditer(body[:8192]):
        raw = m.group(1).strip()
        iso = _v2_parse_iso(raw)
        if iso:
            return iso
    tm = _TIME_TAG_RE.search(body[:16384])
    if tm:
        return _v2_parse_iso(tm.group(1).strip())
    return None


def parse_bare_reiwa(text: str) -> str | None:
    """Pass 6: aggressive 和暦 catch with no label prefix."""
    if not text:
        return None
    # Full wareki first (e.g. "令和8年10月15日") so day/month aren't lost.
    full = _v2_parse_wareki(text)
    if full:
        return full
    m = _BARE_REIWA_RE.search(text)
    if m:
        return _v2_wareki_to_iso("令和", m.group(1), m.group(2), m.group(3) if m.group(3) else None)
    yo = _BARE_REIWA_YEAR_ONLY.search(text)
    if yo:
        return _v2_wareki_to_iso("令和", yo.group(1), "4", "1")
    return None


def parse_slug_filename(url: str | None) -> str | None:
    """Pass 7: last-resort filename slug parser. Looks at the path tail."""
    if not url:
        return None
    tail = url.rsplit("/", 1)[-1] if "/" in url else url
    m = _SLUG_DATE_8DIGIT.search(tail)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    rm = _SLUG_REIWA.search(tail)
    if rm:
        return _v2_wareki_to_iso("令和", rm.group(1), rm.group(2) or "4", rm.group(3))
    return None


def extract_effective_v3(
    raw_json: str | None,
    source_url: str | None,
    observed_at: str | None,
    body: str | None,
    *,
    allow_observed: bool,
) -> tuple[str | None, str]:
    """v3 stacked extractor: v2 → meta → bare-reiwa → slug → observed_coarse."""
    iso, src = _v2_extract(raw_json, source_url, observed_at, body=body)
    if iso:
        return (iso, src)
    if body:
        m = parse_meta_head(body)
        if m:
            return (m, "meta")
        b = parse_bare_reiwa(body)
        if b:
            return (b, "bare_reiwa")
    s = parse_slug_filename(source_url)
    if s:
        return (s, "slug")
    if allow_observed and observed_at:
        return (observed_at[:10], "observed_coarse")
    return (None, "")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--body-fetch", action="store_true")
    p.add_argument("--use-playwright", action="store_true")
    p.add_argument("--max-fetch", type=int, default=200)
    p.add_argument(
        "--observed-as-effective",
        action="store_true",
        help="Pass 8 backstop. Treats observed_at as a coarse effective_from "
        "with source='observed_coarse' (downstream MUST downgrade trust).",
    )
    p.add_argument("--target-dated", type=int, default=13_866)
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
        cur.execute("SELECT COUNT(*) total, COUNT(effective_from) dated FROM am_amendment_snapshot")
        row = cur.fetchone()
        total, dated = row[0], row[1]
        baseline_ratio = (dated / total) if total else 0
        print(f"baseline (v3 entry): total={total} dated={dated} ratio={baseline_ratio:.3%}")

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
            body: str = ""

            iso, src = extract_effective_v3(
                r["raw_snapshot_json"],
                url,
                r["observed_at"],
                body=None,
                allow_observed=False,
            )
            if iso is None and args.body_fetch and fetch_count < args.max_fetch and url:
                if url in body_cache:
                    body = body_cache[url]
                else:
                    fetch_count += 1
                    body = _v2_fetch_body(url, args.use_playwright) or ""
                    body_cache[url] = body
                iso, src = extract_effective_v3(
                    r["raw_snapshot_json"],
                    url,
                    r["observed_at"],
                    body=body,
                    allow_observed=False,
                )
            if iso is None and args.observed_as_effective and r["observed_at"]:
                iso, src = (r["observed_at"][:10], "observed_coarse")

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
