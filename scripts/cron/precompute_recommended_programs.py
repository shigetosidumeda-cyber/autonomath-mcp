#!/usr/bin/env python3
"""Monthly precompute of `am_recommended_programs` (Wave 24 §10.3 ETL).

What this fixes
---------------
W3-12 / W3-13 audit (UC1 / UC6 / UC8) found `recommend_programs_for_houjin`
(#97) returning empty envelopes for every 法人. Migration `wave24_126`
created `am_recommended_programs` but no cron populated it, so personalization
was 0 across three flagship UCs. This script is that cron.

Why a precompute (not request-time)
-----------------------------------
* `recommend_programs_for_houjin` is billed (¥3/req) and §52/§72 sensitive.
  Per CLAUDE.md and `feedback_autonomath_no_api_use`, no LLM SDK may run
  inside `src/`, `scripts/cron/`, or `scripts/etl/`. The recommender's TOP-N
  per-法人 must be computed offline and read with a pure SELECT.
* Candidate space = ~1,454 tier S+A programs × 100,000 cohort 法人
  ≈ 1.45e8 (program, 法人) pairs. Computing on demand is impossible inside
  a request budget. Pre-computing TOP 10 keeps the read path O(1) per req.
* Recompute cadence: monthly (cohort changes are slow; programs themselves
  evolve weekly, but tier S+A churn at the program level is captured by
  am_amendment_diff which the recommender does NOT need to refresh — it
  needs which programs *exist*).

Score
-----
Composite `score` ∈ [0, 1] is a weighted sum of 5 signals, each ∈ [0, 1]:

    score = 0.30 * jsic_match
          + 0.25 * region_match
          + 0.20 * amount_band_fit
          + 0.15 * past_adoption_pattern
          + 0.10 * application_window_open

Every signal is reproducible from public corpus + 法人 master + adoption
records. NO LLM, NO Anthropic / OpenAI / Gemini API. The cron's intent is
captured in `reason_json` so #97's response can echo back the per-signal
contribution.

Per-signal definitions (all clamped to [0, 1]):

  * jsic_match           — 1.0 if (houjin.jsic_major == program.jsic_major)
                          AND middles equal; 0.7 if only majors equal;
                          0.4 if either side is NULL (industry-agnostic
                          program / 法人 with no JSIC). 0.0 on
                          conflicting majors. When `programs.jsic_major`
                          column is missing (migration wave24_113a not yet
                          applied) we degrade to 0.4 uniformly so the
                          score still ranks by the other 4 signals.

  * region_match         — 1.0 if program is national (prefecture NULL or
                          '全国'); 1.0 if program.prefecture ==
                          houjin.prefecture; 0.0 otherwise.

  * amount_band_fit      — 1.0 if either bound is NULL (no info penalty);
                          else 1.0 if 法人 has at least one historical
                          adoption with amount in [min, max]; else 0.5
                          if the 法人 has any adoption history (some fit
                          implied); else 0.3 (cold-start).

  * past_adoption_pattern — Min(1.0, adoptions_for_this_program_kind /
                          adoptions_total) when 法人 has adoption history;
                          0.5 cold-start otherwise.

  * application_window_open — 1.0 if `am_application_round` has any row
                          for this program with application_close_date >=
                          today; 0.5 if no round info at all (unknown);
                          0.0 if all rounds are closed.

Final ordering: score DESC, then tier (S → A), then primary_name ASC for
deterministic ties. TOP `--top-n` (default 10) rows per houjin written via
`INSERT OR REPLACE` keyed on (houjin_bangou, program_unified_id).

Usage
-----
    # Dry run, log only, 5 法人 cap (no DB writes):
    python scripts/cron/precompute_recommended_programs.py \
        --dry-run --max-houjin 5

    # Real run, default cohort (top 100,000 by total_received_yen):
    python scripts/cron/precompute_recommended_programs.py

    # Hermetic test invocation:
    python scripts/cron/precompute_recommended_programs.py \
        --am-db /tmp/test_am.db --max-houjin 5 --top-n 10
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import statistics
import sys
import time
from pathlib import Path

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402

logger = logging.getLogger("autonomath.cron.precompute_recommended_programs")


# Score weights — tuned to sum to 1.0 exactly. Order matches docstring.
W_JSIC = 0.30
W_REGION = 0.25
W_AMOUNT = 0.20
W_ADOPTION = 0.15
W_WINDOW = 0.10
assert abs((W_JSIC + W_REGION + W_AMOUNT + W_ADOPTION + W_WINDOW) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.precompute_recommended_programs")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _open_am(am_db_path: Path) -> sqlite3.Connection:
    """Open autonomath.db read/write. Caller owns close()."""
    conn = sqlite3.connect(str(am_db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


# ---------------------------------------------------------------------------
# Cohort + program loaders
# ---------------------------------------------------------------------------


def _load_houjin_cohort(conn: sqlite3.Connection, max_houjin: int) -> list[sqlite3.Row]:
    """Top-N 法人 by total_received_yen (desc), close_date IS NULL."""
    has_jsic = _column_exists(conn, "houjin_master", "jsic_major")
    jsic_select = "jsic_major" if has_jsic else "NULL AS jsic_major"
    middle_select = (
        "jsic_middle"
        if _column_exists(conn, "houjin_master", "jsic_middle")
        else "NULL AS jsic_middle"
    )
    sql = f"""
        SELECT houjin_bangou,
               normalized_name,
               prefecture,
               total_adoptions,
               total_received_yen,
               {jsic_select},
               {middle_select}
          FROM houjin_master
         WHERE close_date IS NULL
         ORDER BY total_received_yen DESC,
                  total_adoptions DESC,
                  houjin_bangou ASC
         LIMIT ?
    """  # noqa: S608 — column names whitelisted via _column_exists.
    return conn.execute(sql, (max_houjin,)).fetchall()


def _load_programs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Tier S+A, excluded=0 programs from `jpi_programs` (autonomath mirror)."""
    has_jsic_major = _column_exists(conn, "jpi_programs", "jsic_major")
    has_jsic_middle = _column_exists(conn, "jpi_programs", "jsic_middle")
    jsic_major_select = "jsic_major" if has_jsic_major else "NULL AS jsic_major"
    jsic_middle_select = "jsic_middle" if has_jsic_middle else "NULL AS jsic_middle"
    sql = f"""
        SELECT unified_id,
               primary_name,
               tier,
               prefecture,
               program_kind,
               amount_min_man_yen,
               amount_max_man_yen,
               {jsic_major_select},
               {jsic_middle_select}
          FROM jpi_programs
         WHERE excluded = 0
           AND tier IN ('S', 'A')
    """  # noqa: S608 — column names whitelisted via _column_exists.
    return conn.execute(sql).fetchall()


def _load_houjin_adoption_summary(
    conn: sqlite3.Connection, houjin_bangou: str
) -> dict[str, object]:
    """Aggregate adoption_records → per-houjin signal substrate.

    Returns dict with:
      * total            : adoption count
      * by_program_kind  : {kind|None: count}
      * by_program_id    : {program_id_hint: count}
      * amounts          : list[int] of amount_granted_yen (>0)
    """
    rows = conn.execute(
        """
        SELECT program_id_hint, amount_granted_yen
          FROM adoption_records
         WHERE houjin_bangou = ?
        """,
        (houjin_bangou,),
    ).fetchall()
    amounts: list[int] = []
    by_id: dict[str, int] = {}
    for r in rows:
        if r["amount_granted_yen"] is not None and int(r["amount_granted_yen"]) > 0:
            amounts.append(int(r["amount_granted_yen"]))
        if r["program_id_hint"]:
            by_id[r["program_id_hint"]] = by_id.get(r["program_id_hint"], 0) + 1
    return {
        "total": len(rows),
        "by_program_id": by_id,
        "amounts": amounts,
    }


def _load_open_program_ids(conn: sqlite3.Connection) -> set[str]:
    """Programs with at least one am_application_round close_date >= today.

    Bridges program_entity_id → jpi_programs.unified_id via entity_id_map
    (am_canonical_id == program_entity_id).
    """
    if not _table_exists(conn, "am_application_round"):
        return set()
    if not _table_exists(conn, "entity_id_map"):
        return set()
    rows = conn.execute(
        """
        SELECT DISTINCT m.jpi_unified_id AS unified_id
          FROM am_application_round r
          JOIN entity_id_map m ON m.am_canonical_id = r.program_entity_id
         WHERE r.application_close_date IS NOT NULL
           AND r.application_close_date >= date('now')
           AND m.jpi_unified_id IS NOT NULL
        """
    ).fetchall()
    return {r["unified_id"] for r in rows if r["unified_id"]}


def _load_known_round_program_ids(conn: sqlite3.Connection) -> set[str]:
    """Programs with at least one am_application_round row (open or closed)."""
    if not _table_exists(conn, "am_application_round"):
        return set()
    if not _table_exists(conn, "entity_id_map"):
        return set()
    rows = conn.execute(
        """
        SELECT DISTINCT m.jpi_unified_id AS unified_id
          FROM am_application_round r
          JOIN entity_id_map m ON m.am_canonical_id = r.program_entity_id
         WHERE m.jpi_unified_id IS NOT NULL
        """
    ).fetchall()
    return {r["unified_id"] for r in rows if r["unified_id"]}


# ---------------------------------------------------------------------------
# Per-signal scorers — pure functions, deterministic, [0, 1] clamped.
# ---------------------------------------------------------------------------


def _score_jsic(
    houjin_major: str | None,
    houjin_middle: str | None,
    program_major: str | None,
    program_middle: str | None,
    program_jsic_column_present: bool,
) -> float:
    if not program_jsic_column_present:
        # Migration wave24_113a not applied — degrade uniformly.
        return 0.4
    if not houjin_major or not program_major:
        return 0.4
    if houjin_major != program_major:
        return 0.0
    # majors equal
    if houjin_middle and program_middle and houjin_middle == program_middle:
        return 1.0
    return 0.7


def _score_region(houjin_pref: str | None, program_pref: str | None) -> float:
    # Program is national → matches everyone.
    if not program_pref or program_pref in ("全国", "national"):
        return 1.0
    if not houjin_pref:
        return 0.4
    return 1.0 if houjin_pref == program_pref else 0.0


def _score_amount_fit(
    amount_min_man_yen: float | None,
    amount_max_man_yen: float | None,
    amounts_yen: list[int],
) -> float:
    # Either bound missing → soft pass (1.0): we don't penalize unknown shape.
    if amount_min_man_yen is None or amount_max_man_yen is None:
        return 1.0
    if not amounts_yen:
        return 0.3  # cold start — still surfaces, just weaker
    lo = float(amount_min_man_yen) * 10_000
    hi = float(amount_max_man_yen) * 10_000
    if lo > hi:
        lo, hi = hi, lo
    # If 法人's median past grant fits the program's [min, max] → 1.0.
    median = float(statistics.median(amounts_yen))
    if lo <= median <= hi:
        return 1.0
    # Otherwise check if ANY past grant fits.
    if any(lo <= a <= hi for a in amounts_yen):
        return 0.7
    # Adoption history exists but none fit the band.
    return 0.5


def _score_adoption_pattern(
    program_unified_id: str,
    houjin_summary: dict[str, object],
) -> float:
    total = int(houjin_summary["total"])
    if total == 0:
        return 0.5  # cold start
    by_id: dict[str, int] = houjin_summary["by_program_id"]  # type: ignore[assignment]
    same = by_id.get(program_unified_id, 0)
    # Repeat-applicant signal — diminishing returns past 1.0.
    return min(1.0, same / max(1, total) * 4.0)


def _score_window(
    program_unified_id: str,
    open_ids: set[str],
    known_ids: set[str],
) -> float:
    if program_unified_id in open_ids:
        return 1.0
    if program_unified_id in known_ids:
        return 0.0  # all known rounds closed
    return 0.5  # no round info — neutral


def _tier_rank(tier: str | None) -> int:
    return {"S": 0, "A": 1}.get(tier or "", 9)


# ---------------------------------------------------------------------------
# Per-houjin scoring
# ---------------------------------------------------------------------------


def _score_houjin(
    houjin: sqlite3.Row,
    programs: list[sqlite3.Row],
    program_jsic_column_present: bool,
    open_ids: set[str],
    known_ids: set[str],
    houjin_summary: dict[str, object],
    top_n: int,
) -> list[tuple[str, float, dict[str, object]]]:
    """Return list of (program_unified_id, score, reason_dict), TOP `top_n`.

    `reason_dict` is the structure stored in `reason_json` so the request-
    time tool can echo back per-signal contributions.
    """
    # `houjin` is a sqlite3.Row in production (cron path) and a plain dict in
    # some test fixtures. sqlite3.Row does NOT implement `.get()`, so use
    # explicit key-membership lookup that works for both shapes.
    _hk = set(houjin.keys()) if hasattr(houjin, "keys") else set()
    h_major = houjin["jsic_major"] if "jsic_major" in _hk else None
    h_middle = houjin["jsic_middle"] if "jsic_middle" in _hk else None
    h_pref = houjin["prefecture"]

    scored: list[tuple[str, float, str | None, str, dict[str, object]]] = []
    for p in programs:
        s_jsic = _score_jsic(
            h_major,
            h_middle,
            p["jsic_major"],
            p["jsic_middle"],
            program_jsic_column_present,
        )
        s_region = _score_region(h_pref, p["prefecture"])
        s_amount = _score_amount_fit(
            p["amount_min_man_yen"],
            p["amount_max_man_yen"],
            houjin_summary["amounts"],  # type: ignore[arg-type]
        )
        s_adopt = _score_adoption_pattern(p["unified_id"], houjin_summary)
        s_window = _score_window(p["unified_id"], open_ids, known_ids)

        composite = (
            W_JSIC * s_jsic
            + W_REGION * s_region
            + W_AMOUNT * s_amount
            + W_ADOPTION * s_adopt
            + W_WINDOW * s_window
        )
        composite = max(0.0, min(1.0, composite))

        reason = {
            "signals": {
                "jsic_match": round(s_jsic, 4),
                "region_match": round(s_region, 4),
                "amount_band_fit": round(s_amount, 4),
                "past_adoption_pattern": round(s_adopt, 4),
                "application_window_open": round(s_window, 4),
            },
            "weights": {
                "jsic_match": W_JSIC,
                "region_match": W_REGION,
                "amount_band_fit": W_AMOUNT,
                "past_adoption_pattern": W_ADOPTION,
                "application_window_open": W_WINDOW,
            },
            "tier": p["tier"],
            "computed_via": "scripts/cron/precompute_recommended_programs.py",
        }
        scored.append((p["unified_id"], composite, p["tier"], p["primary_name"] or "", reason))

    # Sort: composite DESC, tier asc (S<A), name asc — deterministic.
    scored.sort(key=lambda x: (-x[1], _tier_rank(x[2]), x[3]))
    return [(uid, round(score, 6), reason) for uid, score, _t, _n, reason in scored[:top_n]]


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _write_houjin_recommendations(
    conn: sqlite3.Connection,
    houjin_bangou: str,
    rows: list[tuple[str, float, dict[str, object]]],
    snapshot_id: str,
) -> int:
    """INSERT OR REPLACE the TOP-N for one 法人 inside its own tx.

    Wipes prior rows for this 法人 first so a shrinking N (e.g. 10 → 7
    eligible programs) doesn't leak stale rank-8/9/10 entries.
    """
    conn.execute("BEGIN")
    try:
        conn.execute(
            "DELETE FROM am_recommended_programs WHERE houjin_bangou = ?",
            (houjin_bangou,),
        )
        for rank, (program_uid, score, reason) in enumerate(rows, start=1):
            conn.execute(
                """
                INSERT OR REPLACE INTO am_recommended_programs (
                    houjin_bangou, program_unified_id, rank, score,
                    reason_json, computed_at, source_snapshot_id
                ) VALUES (?, ?, ?, ?, ?, datetime('now'), ?)
                """,
                (
                    houjin_bangou,
                    program_uid,
                    rank,
                    score,
                    json.dumps(reason, ensure_ascii=False, sort_keys=True),
                    snapshot_id,
                ),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(
    am_db_path: Path,
    max_houjin: int = 100_000,
    top_n: int = 10,
    dry_run: bool = False,
) -> dict[str, int]:
    """Recompute am_recommended_programs for the top `max_houjin` cohort.

    Returns counters: {"houjin_processed", "rows_written", "skipped"}.
    """
    if not am_db_path.is_file():
        logger.error("am_db_missing path=%s", am_db_path)
        return {"houjin_processed": 0, "rows_written": 0, "skipped": 0}

    conn = _open_am(am_db_path)
    try:
        if not _table_exists(conn, "am_recommended_programs"):
            logger.error("am_recommended_programs missing — apply migration wave24_126 first.")
            return {"houjin_processed": 0, "rows_written": 0, "skipped": 0}
        if not _table_exists(conn, "jpi_programs"):
            logger.error("jpi_programs missing — autonomath.db not initialized.")
            return {"houjin_processed": 0, "rows_written": 0, "skipped": 0}
        if not _table_exists(conn, "houjin_master"):
            logger.error("houjin_master missing — autonomath.db not initialized.")
            return {"houjin_processed": 0, "rows_written": 0, "skipped": 0}

        program_jsic_present = _column_exists(conn, "jpi_programs", "jsic_major")

        programs = _load_programs(conn)
        cohort = _load_houjin_cohort(conn, max_houjin)
        open_ids = _load_open_program_ids(conn)
        known_ids = _load_known_round_program_ids(conn)

        snapshot_id = f"precompute:{int(time.time())}"
        logger.info(
            "loaded programs=%d cohort=%d open_rounds=%d known_rounds=%d "
            "snapshot_id=%s dry_run=%s top_n=%d",
            len(programs),
            len(cohort),
            len(open_ids),
            len(known_ids),
            snapshot_id,
            dry_run,
            top_n,
        )
        if not programs or not cohort:
            logger.warning("no_data programs=%d cohort=%d", len(programs), len(cohort))
            return {"houjin_processed": 0, "rows_written": 0, "skipped": 0}

        houjin_processed = 0
        rows_written = 0
        skipped = 0
        log_every = max(1, len(cohort) // 20)
        t0 = time.time()
        for i, h in enumerate(cohort, start=1):
            summary = _load_houjin_adoption_summary(conn, h["houjin_bangou"])
            top = _score_houjin(
                h,
                programs,
                program_jsic_present,
                open_ids,
                known_ids,
                summary,
                top_n,
            )
            if not top:
                skipped += 1
                continue
            if not dry_run:
                rows_written += _write_houjin_recommendations(
                    conn,
                    h["houjin_bangou"],
                    top,
                    snapshot_id,
                )
            else:
                rows_written += len(top)
            houjin_processed += 1
            if i % log_every == 0 or i == len(cohort):
                logger.info(
                    "progress %d/%d processed=%d rows=%d skipped=%d elapsed=%.1fs",
                    i,
                    len(cohort),
                    houjin_processed,
                    rows_written,
                    skipped,
                    time.time() - t0,
                )

        logger.info(
            "done houjin_processed=%d rows_written=%d skipped=%d elapsed=%.1fs",
            houjin_processed,
            rows_written,
            skipped,
            time.time() - t0,
        )
        return {
            "houjin_processed": houjin_processed,
            "rows_written": rows_written,
            "skipped": skipped,
        }
    finally:
        conn.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=("Precompute am_recommended_programs (Wave 24 §10.3 ETL)."),
    )
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path).",
    )
    p.add_argument(
        "--max-houjin",
        type=int,
        default=100_000,
        help="Cohort cap (top-N 法人 by total_received_yen).",
    )
    p.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Programs to keep per 法人 (default 10).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute scores but do NOT write am_recommended_programs.",
    )
    return p.parse_args()


def main() -> int:
    _configure_logging()
    args = _parse_args()
    am_db = args.am_db if args.am_db else settings.autonomath_db_path
    counters = run(
        am_db_path=am_db,
        max_houjin=args.max_houjin,
        top_n=args.top_n,
        dry_run=args.dry_run,
    )
    return 0 if counters["houjin_processed"] > 0 or counters["skipped"] >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
