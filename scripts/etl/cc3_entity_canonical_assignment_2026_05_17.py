#!/usr/bin/env python3
"""CC3 cross-corpus entity canonical-id assignment + compat-matrix upgrade.

Phase 1 — Entity canonical-id assignment (soft-merge)
-----------------------------------------------------
Reads am_entities + am_entity_facts and builds duplicate groups by normalized
houjin_bangou across record_kind ∈ {corporate_entity, adoption, case_study}.
For each group of >=2 members, the lowest-canonical_id (ASCII order) member
becomes the anchor; every group member's ``entity_id_canonical`` is set to
the anchor id. Singleton groups set ``entity_id_canonical = canonical_id``
so the column is fully populated and downstream JOINs can use a single axis.

Phase 2 — am_compat_matrix heuristic→sourced upgrade
----------------------------------------------------
Rows with ``inferred_only=1`` are scanned in parallel. A row is upgraded to
``inferred_only=0`` (sourced) when EITHER:
  * a confirming ``am_relation`` exists between (program_a, program_b) with
    relation_type IN ('compatible','incompatible','prerequisite'); OR
  * both programs share at least one ``references_law`` target (legal
    overlap evidence); OR
  * both programs have ``part_of`` relations to the same parent program.

The upgrade is deterministic, rule-based, and ZERO-LLM.

CONSTRAINTS
-----------
* No LLM API. Pure Python.
* No PRAGMA quick_check on the 16GB autonomath.db (memory:
  feedback_no_quick_check_on_huge_sqlite).
* WAL mode tolerated; uses ``PRAGMA busy_timeout`` for resilience.
* multiprocessing for the upgrade scan (default 8 workers).
* Idempotent — re-runs only flip rows that are NOT already canonical/sourced.
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing as mp
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
BUSY_TIMEOUT_MS = 60_000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("cc3_entity_canonical")


# ---------------------------------------------------------------------------
# Phase 1 — canonical-id assignment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuplicateGroup:
    """One houjin_bangou cluster across record_kind."""

    houjin_bangou: str
    anchor_id: str
    members: tuple[str, ...]


def _connect_rw(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")
    return conn


def _connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};")
    return conn


def collect_duplicate_groups(conn: sqlite3.Connection) -> list[DuplicateGroup]:
    """Walk am_entity_facts.field_name='houjin_bangou' and bucket by TRIM-normalized value.

    Returns ONLY groups with size >= 2 (i.e. true duplicates needing canonical anchor).
    Singletons are handled separately by ``assign_singletons`` so we don't
    allocate 503K group objects in memory.
    """
    cur = conn.execute(
        """
        SELECT TRIM(f.field_value_text) AS hb, f.entity_id, e.record_kind
        FROM am_entity_facts f
        JOIN am_entities e ON e.canonical_id = f.entity_id
        WHERE f.field_name = 'houjin_bangou'
          AND f.field_value_text IS NOT NULL
          AND TRIM(f.field_value_text) <> ''
          AND e.record_kind IN ('corporate_entity', 'adoption', 'case_study')
        """
    )
    bucket: dict[str, list[str]] = defaultdict(list)
    for hb, entity_id, _kind in cur:
        bucket[hb].append(entity_id)

    groups: list[DuplicateGroup] = []
    for hb, members in bucket.items():
        if len(members) < 2:
            continue
        anchor = min(members)  # ASCII-min is deterministic
        groups.append(
            DuplicateGroup(
                houjin_bangou=hb,
                anchor_id=anchor,
                members=tuple(sorted(set(members))),
            )
        )
    return groups


def write_canonical_anchors(
    conn: sqlite3.Connection,
    groups: list[DuplicateGroup],
    batch_size: int = 2_000,
) -> int:
    """Set entity_id_canonical=anchor for every member of every group."""
    updated = 0
    cur = conn.cursor()
    pairs: list[tuple[str, str]] = []
    for g in groups:
        for member in g.members:
            pairs.append((g.anchor_id, member))
    log.info("phase1: writing %d (anchor,member) canonical assignments", len(pairs))

    for i in range(0, len(pairs), batch_size):
        chunk = pairs[i : i + batch_size]
        cur.executemany(
            "UPDATE am_entities SET entity_id_canonical = ? WHERE canonical_id = ?",
            chunk,
        )
        updated += cur.rowcount if cur.rowcount > 0 else len(chunk)
    conn.commit()
    return updated


def assign_singletons(conn: sqlite3.Connection) -> int:
    """For every row where entity_id_canonical IS NULL, set it = canonical_id.

    Single UPDATE statement — covers all kinds (programs, laws, statistics, etc.)
    not just the cross-corpus three. Idempotent.
    """
    cur = conn.cursor()
    cur.execute(
        "UPDATE am_entities SET entity_id_canonical = canonical_id "
        "WHERE entity_id_canonical IS NULL"
    )
    updated = cur.rowcount
    conn.commit()
    return updated


# ---------------------------------------------------------------------------
# Phase 2 — compat-matrix heuristic→sourced upgrade
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompatRow:
    program_a_id: str
    program_b_id: str
    compat_status: str


def collect_heuristic_compat_rows(conn: sqlite3.Connection) -> list[CompatRow]:
    cur = conn.execute(
        """
        SELECT program_a_id, program_b_id, compat_status
        FROM am_compat_matrix
        WHERE inferred_only = 1
        """
    )
    return [CompatRow(a, b, s) for a, b, s in cur]


def _chunkify(rows: list[CompatRow], n_workers: int) -> Iterator[list[CompatRow]]:
    size = max(1, len(rows) // n_workers)
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


_WORKER_DB_PATH: Path | None = None


def _worker_init(db_path: str) -> None:
    """multiprocessing worker initializer: pin a read-only handle."""
    global _WORKER_DB_PATH
    _WORKER_DB_PATH = Path(db_path)


def _verify_chunk(rows: list[CompatRow]) -> list[tuple[str, str]]:
    """Return (program_a, program_b) pairs that can be upgraded to sourced.

    Verification rules (deterministic, no LLM):
      R1. am_relation directly links (a -> b) or (b -> a) with
          relation_type IN ('compatible', 'incompatible', 'prerequisite').
      R2. Both programs share >= 1 'references_law' target (legal overlap).
      R3. Both programs share a 'part_of' parent (same authority bundle).
    """
    if _WORKER_DB_PATH is None:
        return []
    conn = _connect_ro(_WORKER_DB_PATH)
    confirmed: list[tuple[str, str]] = []
    try:
        for row in rows:
            a, b = row.program_a_id, row.program_b_id
            # R1
            r1 = conn.execute(
                """
                SELECT 1 FROM am_relation
                WHERE ((source_entity_id=? AND target_entity_id=?)
                    OR (source_entity_id=? AND target_entity_id=?))
                  AND relation_type IN ('compatible','incompatible','prerequisite')
                LIMIT 1
                """,
                (a, b, b, a),
            ).fetchone()
            if r1 is not None:
                confirmed.append((a, b))
                continue
            # R2 — shared references_law target
            r2 = conn.execute(
                """
                SELECT 1
                FROM am_relation ra
                JOIN am_relation rb
                  ON ra.target_entity_id = rb.target_entity_id
                WHERE ra.source_entity_id=?
                  AND rb.source_entity_id=?
                  AND ra.relation_type='references_law'
                  AND rb.relation_type='references_law'
                  AND ra.target_entity_id IS NOT NULL
                LIMIT 1
                """,
                (a, b),
            ).fetchone()
            if r2 is not None:
                confirmed.append((a, b))
                continue
            # R3 — shared part_of parent
            r3 = conn.execute(
                """
                SELECT 1
                FROM am_relation ra
                JOIN am_relation rb
                  ON ra.target_entity_id = rb.target_entity_id
                WHERE ra.source_entity_id=?
                  AND rb.source_entity_id=?
                  AND ra.relation_type='part_of'
                  AND rb.relation_type='part_of'
                  AND ra.target_entity_id IS NOT NULL
                LIMIT 1
                """,
                (a, b),
            ).fetchone()
            if r3 is not None:
                confirmed.append((a, b))
    finally:
        conn.close()
    return confirmed


def upgrade_heuristic_to_sourced(
    db_path: Path,
    n_workers: int = 8,
) -> int:
    ro_conn = _connect_ro(db_path)
    rows = collect_heuristic_compat_rows(ro_conn)
    ro_conn.close()
    log.info(
        "phase2: scanning %d heuristic rows for sourced upgrade (workers=%d)",
        len(rows),
        n_workers,
    )
    if not rows:
        return 0

    chunks: list[list[CompatRow]] = list(_chunkify(rows, n_workers))
    confirmed: list[tuple[str, str]] = []
    if n_workers <= 1:
        _worker_init(str(db_path))
        for in_chunk in chunks:
            confirmed.extend(_verify_chunk(in_chunk))
    else:
        with mp.get_context("spawn").Pool(
            processes=n_workers,
            initializer=_worker_init,
            initargs=(str(db_path),),
        ) as pool:
            for partial in pool.imap_unordered(_verify_chunk, chunks):
                confirmed.extend(partial)
    log.info("phase2: confirmed %d rows for sourced upgrade", len(confirmed))
    if not confirmed:
        return 0

    rw_conn = _connect_rw(db_path)
    cur = rw_conn.cursor()
    for i in range(0, len(confirmed), 1_000):
        out_chunk: list[tuple[str, str]] = confirmed[i : i + 1_000]
        cur.executemany(
            "UPDATE am_compat_matrix SET inferred_only=0 "
            "WHERE program_a_id=? AND program_b_id=? AND inferred_only=1",
            out_chunk,
        )
    rw_conn.commit()
    rw_conn.close()
    return len(confirmed)


# ---------------------------------------------------------------------------
# CLI driver
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=AUTONOMATH_DB,
        help="path to autonomath.db (default: repo root)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="multiprocessing pool size for phase 2 (default 8)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report planned changes without writing",
    )
    parser.add_argument(
        "--skip-phase1",
        action="store_true",
        help="skip canonical-id assignment (rare — testing only)",
    )
    parser.add_argument(
        "--skip-phase2",
        action="store_true",
        help="skip compat-matrix upgrade (rare — testing only)",
    )
    args = parser.parse_args(argv)

    db_path = args.db
    if not db_path.exists():
        log.error("autonomath.db not found at %s", db_path)
        return 2

    started = datetime.now(UTC)
    log.info("CC3 entity canonical assignment starting (db=%s)", db_path)

    # Phase 1 -----------------------------------------------------------------
    canonical_assigned = 0
    duplicate_groups_count = 0
    if not args.skip_phase1:
        ro_conn = _connect_ro(db_path)
        groups = collect_duplicate_groups(ro_conn)
        ro_conn.close()
        duplicate_groups_count = len(groups)
        log.info("phase1: found %d duplicate groups", duplicate_groups_count)
        if not args.dry_run:
            rw_conn = _connect_rw(db_path)
            canonical_assigned = write_canonical_anchors(rw_conn, groups)
            singleton_filled = assign_singletons(rw_conn)
            rw_conn.close()
            log.info(
                "phase1: anchors written=%d, singletons filled=%d",
                canonical_assigned,
                singleton_filled,
            )

    # Phase 2 -----------------------------------------------------------------
    upgraded = 0
    if not args.skip_phase2:
        if args.dry_run:
            ro_conn = _connect_ro(db_path)
            rows = collect_heuristic_compat_rows(ro_conn)
            ro_conn.close()
            log.info("phase2 (dry): %d heuristic rows would be scanned", len(rows))
        else:
            upgraded = upgrade_heuristic_to_sourced(db_path, n_workers=args.workers)

    elapsed = (datetime.now(UTC) - started).total_seconds()
    log.info(
        "CC3 done: duplicate_groups=%d, canonical_assigned=%d, sourced_upgrade=%d, elapsed=%.2fs",
        duplicate_groups_count,
        canonical_assigned,
        upgraded,
        elapsed,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
