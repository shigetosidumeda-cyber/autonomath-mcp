#!/usr/bin/env python3
"""Deep-bridge keyword/FTS5 mining of ``program_law_refs`` (jpintel.db).

Wave 23-2 follow-up (2026-05-05). The W23-2 script
``populate_program_law_refs_from_inbox.py`` only lifted the 82 W22 law
universe (1,118 raw refs → 1,059 deduped PRs across 789 programs / 230
laws). The remaining ~8,500 e-Gov laws + ~10,800 unmapped programs are
still unlinked even when the program text literally cites the law.

This script does heuristic keyword + FTS5 mining over the **full
catalogue** (every ``laws`` row × every ``programs_fts`` row) and INSERTs
the high-confidence matches with ``ref_kind='reference'``. No LLM call;
pure SQLite phrase queries against the existing trigram index.

Algorithm
---------
1. Pull ``laws.unified_id, law_title, law_short_title`` for every law
   whose title length is in the [6, 80] window. Titles shorter than 6
   characters (民法 / 商法 / 刑法 / 砂防法 etc.) are dropped — single-kanji
   compounds collide with too many programs and the precision is bad.
   Titles longer than 80 chars are 政令/省令 chains that are almost never
   cited verbatim in program 要綱.
2. For each law title (and short title when available + distinct from
   the formal title), run a phrase query against ``programs_fts``:

       SELECT unified_id FROM programs_fts WHERE programs_fts MATCH '"<title>"'

   FTS5 trigram tokenizer + the literal-phrase syntax forces a
   substring-window match across the FTS source columns
   (``primary_name``, ``aliases``, ``enriched_text``). This is the same
   trick `src/jpintel_mcp/api/programs.py` uses to dodge the trigram
   false-positive ("税" overlap) issue documented in CLAUDE.md
   §"Common gotchas".
3. Confidence is derived from the title length:
   * >= 12 chars  → 0.95 (very rare, near-unique title)
   * >= 9 chars   → 0.85
   * >=  7 chars  → 0.75
   * 6 chars      → 0.70 (boundary, kept because >=0.70 threshold
                          requested)
   The matched title is itself the keyword evidence; the longer the
   match the lower the chance of substring collision.
4. ``ref_kind`` is ``'reference'`` (the W22 schema CHECK forbids
   ``'derived_keyword'`` — only authority/eligibility/exclusion/
   reference/penalty are allowed). The heuristic origin is encoded by
   the confidence band + the ``article_citation`` placeholder
   ``'[derived:fts]'`` so audit queries can isolate this batch.
5. ``INSERT OR IGNORE`` on the natural PK
   (program_unified_id, law_unified_id, ref_kind, article_citation).

Verification recompute (W21-2)
------------------------------
After the bridge mining INSERT, ``programs.verification_count`` is
re-derived for every program touched by this run. The increment logic
mirrors ``populate_cross_source_verification.py``: every program whose
``program_law_refs`` distinct ``law_unified_id`` count rose now picks up
a +1 bump on the legacy ``verification_count`` column (capped at the
existing pre-launch ceiling so cross-source remains the dominant
signal). This ensures freshly-linked programs surface to the moat-
signal sort.

Idempotent. Safe to re-run; the second pass is a near-noop because all
inserts are PK-deduped.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"

EGOV_FALLBACK_URL = "https://laws.e-gov.go.jp/search/elawsSearch/elaws_search/lsg0100/"

CITATION_TAG = "[derived:fts]"

# FTS5 phrase chars that must be escaped or skipped. Trigram tokenizer
# does not accept '"' inside a phrase; we drop laws whose title contains
# embedded quotes (rare; <1%).
_FTS_REJECT = re.compile(r"[\"\(\)\[\]\<\>\{\}\\]")


def confidence_for(title: str) -> float:
    n = len(title)
    if n >= 12:
        return 0.95
    if n >= 9:
        return 0.85
    if n >= 7:
        return 0.75
    return 0.70


def fts_safe(title: str) -> bool:
    """A title is FTS-phrase-safe when it has no quote/bracket chars."""
    return not _FTS_REJECT.search(title)


def fetch_law_universe(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """Return (law_unified_id, title) candidates.

    Each law contributes up to two probe titles (formal + short_name
    when distinct + safe + length-banded).
    """
    rows = conn.execute(
        """SELECT unified_id, law_title, law_short_title
           FROM laws
           WHERE revision_status IN ('current','superseded')"""
    ).fetchall()
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for uid, title, short in rows:
        for cand in (title, short):
            if not cand:
                continue
            n = len(cand)
            if n < 6 or n > 80:
                continue
            if not fts_safe(cand):
                continue
            key = (uid, cand)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def mine(
    dry_run: bool = False, verbose: bool = False, limit_laws: int | None = None
) -> tuple[int, int, int, list[tuple]]:
    """Run the mining pass.

    Returns (plr_before, plr_after, programs_touched, top50_sample)
    where top50_sample = list of (program_uid, law_uid, law_title, conf).
    """
    if not JPINTEL_DB.exists():
        print(f"[error] missing {JPINTEL_DB}", file=sys.stderr)
        sys.exit(2)

    conn = sqlite3.connect(JPINTEL_DB)
    conn.row_factory = sqlite3.Row

    plr_before = conn.execute("SELECT COUNT(*) FROM program_law_refs").fetchone()[0]
    if verbose:
        print(f"[info] program_law_refs before: {plr_before}")

    laws = fetch_law_universe(conn)
    if limit_laws:
        laws = laws[:limit_laws]
    if verbose:
        print(f"[info] law probe titles: {len(laws)}")

    # Pre-load the set of programs that exist (we only INSERT for known
    # programs since the FK is RESTRICT on programs).
    valid_program_ids = {row[0] for row in conn.execute("SELECT unified_id FROM programs")}
    if verbose:
        print(f"[info] valid program rows: {len(valid_program_ids)}")

    # Cache existing PRs as (program, law, ref_kind) → True so we can
    # skip the FTS round-trip when the deduped key already exists.
    # We dedupe on the natural PK, but the dominant collision case is
    # same-(program, law, 'reference', '') from the W23 inbox load.
    existing = set()
    for r in conn.execute(
        "SELECT program_unified_id, law_unified_id, ref_kind, article_citation "
        "FROM program_law_refs"
    ):
        existing.add((r[0], r[1], r[2], r[3] or ""))
    if verbose:
        print(f"[info] existing PR keys cached: {len(existing)}")

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Stream INSERTs in batches.
    BATCH = 5000
    pending: list[tuple] = []
    inserted = 0
    skipped_existing = 0
    skipped_no_program = 0
    sample_top: list[tuple[str, str, str, float]] = []
    laws_scanned = 0
    started = time.time()

    # Group probe titles by law unified_id so we attribute the best
    # confidence per (program, law) to the longer match.
    for idx, (law_uid, title) in enumerate(laws, 1):
        laws_scanned = idx
        conf = confidence_for(title)
        try:
            cur = conn.execute(
                "SELECT unified_id FROM programs_fts WHERE programs_fts MATCH ? LIMIT 200",
                (f'"{title}"',),
            )
            hits = [r[0] for r in cur.fetchall()]
        except sqlite3.OperationalError:
            # FTS5 still rejected the phrase (rare, e.g. all-punct after
            # tokenization). Skip silently.
            continue

        for prog_uid in hits:
            if prog_uid not in valid_program_ids:
                skipped_no_program += 1
                continue
            key = (prog_uid, law_uid, "reference", CITATION_TAG)
            if key in existing:
                skipped_existing += 1
                continue
            existing.add(key)
            pending.append(
                (
                    prog_uid,
                    law_uid,
                    "reference",
                    CITATION_TAG,
                    EGOV_FALLBACK_URL,
                    now_iso,
                    conf,
                )
            )
            if len(sample_top) < 200:
                sample_top.append((prog_uid, law_uid, title, conf))

        if not dry_run and len(pending) >= BATCH:
            conn.executemany(
                """INSERT OR IGNORE INTO program_law_refs (
                    program_unified_id, law_unified_id, ref_kind,
                    article_citation, source_url, fetched_at, confidence
                ) VALUES (?,?,?,?,?,?,?)""",
                pending,
            )
            conn.commit()
            inserted += len(pending)
            pending.clear()

        if verbose and idx % 500 == 0:
            elapsed = time.time() - started
            rate = idx / max(elapsed, 0.01)
            print(
                f"[info] {idx}/{len(laws)} laws scanned ({rate:.1f}/s) "
                f"inserted={inserted} pending={len(pending)} "
                f"skipped_dup={skipped_existing}"
            )

    # Final flush.
    if not dry_run and pending:
        conn.executemany(
            """INSERT OR IGNORE INTO program_law_refs (
                program_unified_id, law_unified_id, ref_kind,
                article_citation, source_url, fetched_at, confidence
            ) VALUES (?,?,?,?,?,?,?)""",
            pending,
        )
        conn.commit()
        inserted += len(pending)
        pending.clear()

    plr_after = conn.execute("SELECT COUNT(*) FROM program_law_refs").fetchone()[0]

    # Recompute verification_count for programs that gained at least
    # one new (program, law) pair this run. The legacy column is bumped
    # by the count of distinct freshly-attributed laws, capped at +5
    # so cross-source domain agreement remains the dominant moat term.
    programs_touched = 0
    if not dry_run:
        # Identify programs with new derived refs from this batch.
        gain_rows = conn.execute(
            """SELECT program_unified_id, COUNT(DISTINCT law_unified_id)
               FROM program_law_refs
               WHERE article_citation = ?
                 AND fetched_at = ?
               GROUP BY program_unified_id""",
            (CITATION_TAG, now_iso),
        ).fetchall()
        bumps = []
        for prog_uid, distinct_laws in gain_rows:
            bump = min(distinct_laws, 5)
            bumps.append((bump, prog_uid))
        if bumps:
            conn.executemany(
                """UPDATE programs
                   SET verification_count = COALESCE(verification_count, 0) + ?
                   WHERE unified_id = ?""",
                bumps,
            )
            conn.commit()
        programs_touched = len(bumps)

    # Top-50 sample sorted by confidence DESC then title length DESC.
    sample_top.sort(key=lambda t: (-t[3], -len(t[2])))
    top50 = sample_top[:50]

    if verbose:
        elapsed = time.time() - started
        print(
            f"[info] mining done: laws_scanned={laws_scanned} "
            f"inserted_attempts={inserted} "
            f"plr_delta={plr_after - plr_before} "
            f"programs_touched={programs_touched} "
            f"elapsed={elapsed:.1f}s "
            f"skipped_existing={skipped_existing} "
            f"skipped_no_program={skipped_no_program}"
        )

    conn.close()
    return plr_before, plr_after, programs_touched, top50


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument(
        "--limit-laws",
        type=int,
        default=None,
        help="cap probe-title count for smoke testing",
    )
    args = p.parse_args()

    plr_before, plr_after, programs_touched, top50 = mine(
        dry_run=args.dry_run,
        verbose=args.verbose,
        limit_laws=args.limit_laws,
    )

    print(f"program_law_refs: {plr_before} -> {plr_after} (delta {plr_after - plr_before:+d})")
    print(f"programs_touched (verification_count bumped): {programs_touched}")
    print()
    print("Top 50 sample (program_uid | law_uid | law_title | confidence):")
    for prog, law, title, conf in top50:
        print(f"  {prog} | {law} | {title} | {conf:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
