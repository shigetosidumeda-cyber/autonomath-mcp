#!/usr/bin/env python3
"""History-based amendment diff refresher (W3-12 / W3-13).

What it does
------------
Walks every program in `am_program_eligibility_history` (populated by
`scripts/etl/rebuild_amendment_snapshot.py` at JST 04:00). For each
program, JOINs consecutive (captured_at-ordered) rows. When the
`eligibility_hash` of two adjacent rows differs, computes the per-
predicate diff from `eligibility_struct` JSON (added / removed /
changed predicates) and INSERTs ONE row per detected change kind into
`am_amendment_diff`.

Why this exists
---------------
W3-13 / W3-12 base data audit found:

  * D1 (W1-6) populated `am_program_eligibility_history` with real
    eligibility hashes + structured predicates.
  * `am_amendment_diff` (Wave 22 substrate, migration 075) shipped with
    a per-fact refresher (`refresh_amendment_diff.py`) that reads from
    `am_entity_facts` directly. The fact-level walk catches scalar
    drift (amount_max_yen, subsidy_rate_max, etc.) but does NOT carry
    eligibility-predicate diff hash series.
  * UC1 / UC2 SPA monitoring therefore detects amendments at the field
    level only, missing the structured "predicate added / removed /
    changed" signal that consultants and 税理士 actually want when an
    eligibility chain mutates.

This refresher complements the existing per-fact walk with a per-
predicate walk derived from the history corpus. The two crons share
the `am_amendment_diff` table but write into a distinct `field_name`
namespace (`eligibility:added` / `eligibility:removed` /
`eligibility:changed`) so a downstream consumer can filter to either
the scalar-fact stream or the predicate stream.

Hard constraints
----------------
* NO `import anthropic` / `import openai` / `import google.generativeai` /
  `import claude_agent_sdk`. CI guard `tests/test_no_llm_in_production.py`
  scans this file (it is under `scripts/cron/`).
* NO `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` /
  `GOOGLE_API_KEY` env-var reads.
* Pure SQLite + standard library. No network egress.
* Idempotent: every detected change inserts at most ONE row per
  (entity_id, field_name, prev_hash, new_hash) — re-running on a stable
  history corpus is a no-op.

Field-name namespace (for `am_amendment_diff.field_name`)
---------------------------------------------------------
We write three dedicated names so consumers can filter by change kind
without parsing the JSON `new_value`:

  * `eligibility:added`   — at least one predicate group key appears in
    new_struct that was absent from prev_struct.
  * `eligibility:removed` — at least one predicate group key disappears
    from new_struct that was present in prev_struct.
  * `eligibility:changed` — at least one predicate group key has a
    different value between prev_struct and new_struct.

A single hash transition can land all three rows in one cron run. Each
row's `new_value` carries a JSON object listing the affected predicate
group keys (subsidy_rules / application_rounds / amount_conditions /
target_profile / target_types / funding_purpose) and the old / new
canonical strings for the changed kind.

Usage
-----
    python scripts/cron/refresh_amendment_diff_history.py
    python scripts/cron/refresh_amendment_diff_history.py --dry-run --max-programs 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlite3

# Allow running as a script without `pip install -e .`.
_REPO = Path(__file__).resolve().parent.parent.parent
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jpintel_mcp.config import settings  # noqa: E402
from jpintel_mcp.db.session import connect  # noqa: E402
from jpintel_mcp.observability import heartbeat  # noqa: E402

logger = logging.getLogger("autonomath.cron.refresh_amendment_diff_history")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Predicate group keys we recognize inside `eligibility_struct.eligibility`.
# Mirrors `_extract_envelope` in scripts/etl/rebuild_amendment_snapshot.py.
PREDICATE_GROUPS: tuple[str, ...] = (
    "subsidy_rules",
    "application_rounds",
    "amount_conditions",
    "target_profile",
    "target_types",
    "funding_purpose",
)

CHANGE_KIND_ADDED = "added"
CHANGE_KIND_REMOVED = "removed"
CHANGE_KIND_CHANGED = "changed"

FIELD_NAME_BY_KIND: dict[str, str] = {
    CHANGE_KIND_ADDED: "eligibility:added",
    CHANGE_KIND_REMOVED: "eligibility:removed",
    CHANGE_KIND_CHANGED: "eligibility:changed",
}


def _configure_logging() -> None:
    root = logging.getLogger("autonomath.cron.refresh_amendment_diff_history")
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    sh = logging.StreamHandler(stream=sys.stderr)
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _canonical_json(obj: Any) -> str:
    """Sorted-keys JSON for deterministic hashing + diff comparison."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha256(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_eligibility(raw: str | None) -> dict[str, Any]:
    """Load the eligibility subtree from a stored eligibility_struct JSON.

    The ETL persists ``{"body": ..., "eligibility": ...}``; older rows
    sometimes store the eligibility dict directly. Both shapes resolve
    to a flat ``{group_key: value}`` dict.
    """
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    if "eligibility" in decoded and isinstance(decoded["eligibility"], dict):
        return decoded["eligibility"]
    # Heuristic fallback: if every recognized predicate group key is at the top
    # level, treat the whole dict as the eligibility subtree.
    if any(k in decoded for k in PREDICATE_GROUPS):
        return {k: decoded.get(k) for k in PREDICATE_GROUPS if k in decoded}
    return {}


def _diff_predicates(
    prev_elig: dict[str, Any], new_elig: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Compute {change_kind: {group_key: {prev, new}}} between two predicate trees.

    A group key is considered:
      * added   — present in new, absent (or None) in prev
      * removed — present in prev, absent (or None) in new
      * changed — present in both with non-equal canonical JSON values
    """
    out: dict[str, dict[str, Any]] = {
        CHANGE_KIND_ADDED: {},
        CHANGE_KIND_REMOVED: {},
        CHANGE_KIND_CHANGED: {},
    }
    keys = set(prev_elig) | set(new_elig) | set(PREDICATE_GROUPS)
    for k in sorted(keys):
        p = prev_elig.get(k)
        n = new_elig.get(k)
        p_present = p is not None
        n_present = n is not None
        if p_present and not n_present:
            out[CHANGE_KIND_REMOVED][k] = {"prev": p, "new": None}
        elif n_present and not p_present:
            out[CHANGE_KIND_ADDED][k] = {"prev": None, "new": n}
        elif p_present and n_present:
            if _canonical_json(p) != _canonical_json(n):
                out[CHANGE_KIND_CHANGED][k] = {"prev": p, "new": n}
    # Drop empty kinds so callers can iterate non-empty change kinds only.
    return {kind: payload for kind, payload in out.items() if payload}


def _select_programs_with_history(conn: sqlite3.Connection, max_programs: int | None) -> list[str]:
    """Programs that have >=2 history rows (a diff requires two rows)."""
    sql = """
        SELECT program_id
          FROM am_program_eligibility_history
         GROUP BY program_id
        HAVING COUNT(*) >= 2
         ORDER BY program_id
    """
    if max_programs is not None:
        sql += f" LIMIT {int(max_programs)}"
    return [r["program_id"] for r in conn.execute(sql).fetchall()]


def _select_history_rows(conn: sqlite3.Connection, program_id: str) -> list[sqlite3.Row]:
    """All history rows for a program, oldest first."""
    return conn.execute(
        """
        SELECT history_id,
               captured_at,
               source_url,
               eligibility_hash,
               eligibility_struct
          FROM am_program_eligibility_history
         WHERE program_id = ?
         ORDER BY captured_at ASC, history_id ASC
        """,
        (program_id,),
    ).fetchall()


def _existing_diff_keys(
    conn: sqlite3.Connection, entity_id: str
) -> set[tuple[str, str | None, str | None]]:
    """All (field_name, prev_hash, new_hash) tuples already recorded for entity.

    Used to suppress duplicate INSERTs when the cron re-runs over an
    unchanged history corpus.
    """
    rows = conn.execute(
        """
        SELECT field_name, prev_hash, new_hash
          FROM am_amendment_diff
         WHERE entity_id = ?
        """,
        (entity_id,),
    ).fetchall()
    return {(r["field_name"], r["prev_hash"], r["new_hash"]) for r in rows}


def _diff_one_program(
    conn: sqlite3.Connection,
    program_id: str,
    dry_run: bool,
) -> int:
    """Walk consecutive history rows; INSERT diff rows on hash drift.

    Returns the number of am_amendment_diff rows inserted (or that would
    be inserted in dry-run mode).
    """
    rows = _select_history_rows(conn, program_id)
    if len(rows) < 2:
        return 0

    seen = _existing_diff_keys(conn, program_id)
    inserted = 0

    for prev_row, new_row in zip(rows, rows[1:], strict=False):
        prev_hash = prev_row["eligibility_hash"]
        new_hash = new_row["eligibility_hash"]
        if prev_hash == new_hash:
            # No eligibility movement — content_hash may have drifted but
            # the predicate tree is byte-identical. Skip.
            continue

        prev_elig = _load_eligibility(prev_row["eligibility_struct"])
        new_elig = _load_eligibility(new_row["eligibility_struct"])
        change_map = _diff_predicates(prev_elig, new_elig)
        if not change_map:
            # Hashes differ but no recognized predicate group changed —
            # likely a hash from a non-canonicalized source. Skip rather
            # than fabricate a diff.
            continue

        for change_kind, payload in change_map.items():
            field_name = FIELD_NAME_BY_KIND[change_kind]
            key = (field_name, prev_hash, new_hash)
            if key in seen:
                continue
            seen.add(key)

            summary = {
                "program_id": program_id,
                "change_kind": change_kind,
                "predicate_groups": sorted(payload.keys()),
                "prev_captured_at": prev_row["captured_at"],
                "new_captured_at": new_row["captured_at"],
                "details": payload,
            }
            new_value_json = _canonical_json(summary)
            prev_value_json = _canonical_json({k: v["prev"] for k, v in payload.items()})

            if dry_run:
                logger.info(
                    "would_insert program=%s field=%s prev_hash=%s new_hash=%s groups=%s",
                    program_id,
                    field_name,
                    (prev_hash or "")[:12],
                    (new_hash or "")[:12],
                    ",".join(sorted(payload.keys())),
                )
                inserted += 1
                continue

            conn.execute(
                """
                INSERT INTO am_amendment_diff (
                    entity_id, field_name,
                    prev_value, new_value,
                    prev_hash, new_hash,
                    source_url
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    program_id,
                    field_name,
                    prev_value_json,
                    new_value_json,
                    prev_hash,
                    new_hash,
                    new_row["source_url"],
                ),
            )
            inserted += 1

    return inserted


def run(
    am_db_path: Path,
    max_programs: int | None,
    dry_run: bool,
) -> dict[str, int]:
    """Iterate eligible programs, refresh predicate diffs, return counters."""
    if not am_db_path.is_file():
        logger.error("am_db_missing path=%s", am_db_path)
        return {
            "programs_scanned": 0,
            "diff_rows_inserted": 0,
            "programs_with_change": 0,
        }

    conn = connect(am_db_path)
    try:
        # Both source + sink tables must exist. Fail loudly if either
        # migration has not been applied — silently no-op'ing would mask
        # a deploy regression.
        for table, mig in (
            ("am_program_eligibility_history", "wave24_106"),
            ("am_amendment_diff", "075"),
        ):
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if exists is None:
                logger.error(
                    "%s_missing path=%s did_you_apply_migration=%s",
                    table,
                    am_db_path,
                    mig,
                )
                return {
                    "programs_scanned": 0,
                    "diff_rows_inserted": 0,
                    "programs_with_change": 0,
                }

        program_ids = _select_programs_with_history(conn, max_programs)
        logger.info(
            "history_diff_start db=%s programs=%d max_programs=%s dry_run=%s",
            am_db_path,
            len(program_ids),
            max_programs,
            dry_run,
        )

        total_inserted = 0
        with_change = 0

        if not dry_run:
            conn.execute("BEGIN")
        try:
            for pid in program_ids:
                n = _diff_one_program(conn=conn, program_id=pid, dry_run=dry_run)
                if n > 0:
                    with_change += 1
                    total_inserted += n
            if not dry_run:
                conn.execute("COMMIT")
        except Exception:
            if not dry_run:
                conn.execute("ROLLBACK")
            raise

        counters = {
            "programs_scanned": len(program_ids),
            "diff_rows_inserted": total_inserted,
            "programs_with_change": with_change,
        }
        logger.info(
            "history_diff_done programs=%d inserts=%d with_change=%d",
            counters["programs_scanned"],
            counters["diff_rows_inserted"],
            counters["programs_with_change"],
        )
        return counters
    finally:
        conn.close()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="History-based amendment diff refresher (W3-12 / W3-13)"
    )
    p.add_argument(
        "--am-db",
        type=Path,
        default=None,
        help="Path to autonomath.db (default: settings.autonomath_db_path)",
    )
    p.add_argument(
        "--max-programs",
        type=int,
        default=None,
        help="Process only the first N programs (test mode)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Log diffs but do not INSERT",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = _parse_args(argv)

    am_db_path = args.am_db if args.am_db else settings.autonomath_db_path

    with heartbeat("refresh_amendment_diff_history") as hb:
        try:
            counters = run(
                am_db_path=am_db_path,
                max_programs=args.max_programs,
                dry_run=bool(args.dry_run),
            )
        except Exception as e:
            logger.exception("amendment_diff_history_refresh_failed err=%s", e)
            return 1
        hb["rows_processed"] = int(counters.get("diff_rows_inserted", 0) or 0)
        hb["rows_skipped"] = int(
            (counters.get("programs_scanned", 0) or 0)
            - (counters.get("programs_with_change", 0) or 0)
        )
        hb["metadata"] = {
            "programs_scanned": counters.get("programs_scanned"),
            "programs_with_change": counters.get("programs_with_change"),
            "dry_run": bool(args.dry_run),
        }
    return 0


if __name__ == "__main__":
    sys.exit(main())
