#!/usr/bin/env python3
"""F4: Promote am_compat_matrix heuristic pairs to status='sourced' by mining
the `source_url` column and computing a confidence-adjusted promotion gate.

Background
----------
Wave 18 baseline (2026-05-11) state of `am_compat_matrix`:

    total:                43,966 pairs
    has source_url:        3,823 pairs (3,823 / 43,966 = 8.7 %)
    sourced  status:       N/A — compat_status only carries the relationship
                           (compatible / incompatible / case_by_case / unknown),
                           not the provenance grade.

A new column is NOT introduced. Instead, the visibility flag (one of
'public', 'internal', 'quarantine') is promoted from the default 'internal'
to 'public' when:

    1. source_url IS NOT NULL
    2. confidence >= 0.60
    3. compat_status != 'unknown'
    4. evidence_relation IS NOT NULL OR inferred_only = 0
    5. source URL host ∈ {go.jp, .lg.jp, *.smrj.go.jp, e-Gov, 日本政策金融公庫}

Rows that pass all five rails are marked visibility='public' (= sourced for
publication). Rows that pass 1+3+4 but fail the 0.60 confidence floor are left
visibility='internal' so consumers filtering visibility='public' get a clean
authoritative set without losing the audit trail.

Source URL → confidence boost map
---------------------------------
Each authoritative ministry hostname carries a small additive boost (capped
at 1.0) so that subsequent passes can re-sort:

    *.go.jp                +0.10   (national ministry)
    *.lg.jp                +0.08   (prefecture / municipality)
    smrj.go.jp             +0.10   (中小機構 — 補助金事業)
    elaws.e-gov.go.jp      +0.12   (一次法令)
    jfc.go.jp              +0.08   (日本政策金融公庫)
    portal.monodukuri-     +0.05   (補助金ポータル — quasi-official)
        hojo.jp
    chutaikyo.taisyo-      +0.08   (中退共 — 厚労省所管)
        kukin.go.jp
    mof.go.jp              +0.10   (財務省)
    other                  +0.00

Idempotent
----------
Re-running the script is a no-op for any row that already carries
visibility='public' AND a saturated confidence. The OLDEST visibility wins
on subsequent reruns so the operator can manually re-flag quarantines
without the ETL stomping the manual flag.

Read source
-----------
am_compat_matrix WHERE source_url IS NOT NULL AND source_url != ''

Write target
------------
SAME table, in-place UPDATE on (program_a_id, program_b_id) PK. No new rows.

Honest projection
-----------------
Worked baseline confidence histogram on 2026-05-11:

    source_url present    compat_status  N      mean_conf
    https://             compatible      1,959   0.63
    https://             case_by_case    1,559   0.58
    https://             incompatible      305   0.66

Target: promote 8,000-10,000 rows visibility='internal' → 'public' on first
run by combining source presence + boosted confidence ≥ 0.60.

Usage
-----
    python3 scripts/etl/promote_compat_matrix.py --dry-run
    python3 scripts/etl/promote_compat_matrix.py --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO_ROOT / "autonomath.db"

CONFIDENCE_FLOOR = 0.60

# Authoritative hostname → additive confidence boost. Suffix-match.
HOST_BOOST = [
    ("elaws.e-gov.go.jp", 0.12),
    ("mof.go.jp", 0.10),
    ("smrj.go.jp", 0.10),
    ("jfc.go.jp", 0.08),
    ("chutaikyo.taisyokukin.go.jp", 0.08),
    ("portal.monodukuri-hojo.jp", 0.05),
    (".lg.jp", 0.08),
    (".go.jp", 0.10),
]


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


def backfill_source_url_from_facts(cur, dry_run: bool) -> int:
    """Mine `am_entity_facts.field_name = 'source.url'` to fill blank
    `am_compat_matrix.source_url` rows where program_a_id has an upstream
    fact. The url chosen is the most-recently fetched .go.jp / .lg.jp
    candidate (authoritative bias).
    """
    cur.execute(
        """
        SELECT entity_id, field_value_text
          FROM am_entity_facts
         WHERE field_name = 'source.url'
           AND field_value_text IS NOT NULL
           AND field_value_text != ''
        """
    )
    fact_url: dict[str, str] = {}
    for ent, url in cur.fetchall():
        if not url:
            continue
        if ent in fact_url and host_boost(fact_url[ent]) >= host_boost(url):
            continue
        fact_url[ent] = url

    cur.execute(
        """
        SELECT program_a_id, program_b_id
          FROM am_compat_matrix
         WHERE (source_url IS NULL OR source_url = '')
        """
    )
    pairs = cur.fetchall()
    updates: list[tuple[str, str, str]] = []
    for a, b in pairs:
        url = fact_url.get(a) or fact_url.get(b)
        if not url:
            continue
        updates.append((url, a, b))

    if not dry_run and updates:
        cur.executemany(
            "UPDATE am_compat_matrix SET source_url = ? "
            "WHERE program_a_id = ? AND program_b_id = ?",
            updates,
        )
    return len(updates)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(DEFAULT_DB), help="autonomath.db path")
    p.add_argument("--dry-run", action="store_true", help="report counts, do not UPDATE")
    p.add_argument("--apply", action="store_true", help="commit the visibility flip")
    p.add_argument("--limit", type=int, default=0, help="cap rows scanned (0 = no cap)")
    p.add_argument(
        "--backfill-source-url",
        action="store_true",
        help="mine am_entity_facts source.url into NULL source_url rows first",
    )
    args = p.parse_args()

    if not args.dry_run and not args.apply:
        print("ERR: specify --dry-run or --apply", file=sys.stderr)
        return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERR: db missing: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()

        # Optional pre-pass: fill blank source_url from am_entity_facts.
        if args.backfill_source_url:
            filled = backfill_source_url_from_facts(cur, dry_run=args.dry_run)
            print(f"backfilled source_url: {filled}")
            if args.apply and filled:
                conn.commit()

        # Baseline counters
        cur.execute("SELECT visibility, COUNT(*) FROM am_compat_matrix GROUP BY visibility")
        baseline_visibility = Counter({row[0]: row[1] for row in cur.fetchall()})

        # Pull candidates: has URL + non-unknown status
        sql = """
            SELECT program_a_id, program_b_id, compat_status, source_url,
                   confidence, evidence_relation, inferred_only, visibility
            FROM am_compat_matrix
            WHERE source_url IS NOT NULL AND source_url != ''
              AND compat_status != 'unknown'
              AND visibility = 'internal'
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        cur.execute(sql)
        rows = cur.fetchall()

        candidates = 0
        promotions: list[tuple[float, str, str]] = []
        skipped_low_conf = 0
        skipped_no_evidence = 0
        skipped_non_authority = 0

        for r in rows:
            candidates += 1
            base_conf = r["confidence"] if r["confidence"] is not None else 0.0
            boost = host_boost(r["source_url"])
            adjusted = min(1.0, base_conf + boost)
            has_evidence = bool(r["evidence_relation"]) or not r["inferred_only"]

            if not is_authoritative(r["source_url"]):
                skipped_non_authority += 1
                continue
            if not has_evidence:
                skipped_no_evidence += 1
                continue
            if adjusted < CONFIDENCE_FLOOR:
                skipped_low_conf += 1
                continue

            promotions.append((adjusted, r["program_a_id"], r["program_b_id"]))

        print(f"baseline visibility: {dict(baseline_visibility)}")
        print(f"scanned candidates : {candidates}")
        print(f"promote → public   : {len(promotions)}")
        print(f"skip non-authority : {skipped_non_authority}")
        print(f"skip no evidence   : {skipped_no_evidence}")
        print(f"skip low conf<{CONFIDENCE_FLOOR}: {skipped_low_conf}")

        if args.apply and promotions:
            cur.executemany(
                """
                UPDATE am_compat_matrix
                   SET visibility = 'public',
                       confidence = ?
                 WHERE program_a_id = ?
                   AND program_b_id = ?
                """,
                promotions,
            )
            conn.commit()
            print(f"applied: {len(promotions)} rows promoted to visibility='public'")
        elif args.dry_run:
            print("(dry-run, no UPDATE issued)")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
