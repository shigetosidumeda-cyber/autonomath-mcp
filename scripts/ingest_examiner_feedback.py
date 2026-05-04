#!/usr/bin/env python3
"""Ingest jpcite operator examiner feedback into ``am_entity_annotation``.

The jpcite operator workflow emits one JSONL record per申請フォーム審査:

    {
      "program_name": "就農準備資金",
      "timestamp": "2026-04-13T14:26:27.793767",
      "quality_score": 0.18,
      "sections": [{"section_title": "...", "char_count": 31}, ...],
      "auto_corrections": [...],
      "quality_warnings": ["⚠️ ...の内容が短すぎます(31文字)", ...]
    }

Per record we materialise three annotation kinds against the matched
``am_entities`` row (kind enum seeded by migration 046):

  * ``quality_score``       — 1 row, severity=info, score=quality_score, meta=sections
  * ``examiner_warning``    — N rows, severity=warning, text_ja=warning string
  * ``examiner_correction`` — M rows, severity=info,    text_ja=correction string

Entity resolution
-----------------

Source rows carry only ``program_name`` (free text). Resolution path:

    program_name → jpi_programs.primary_name (exact)
                 → jpi_programs.unified_id
                 → entity_id_map.am_canonical_id  (1..N rows)
                 → am_entities.canonical_id

We accept multiple matches: a given primary_name may map to several jpi rows
(prefectural variants etc.) and each maps to one or more am_entities. Every
matched entity gets the annotation. ``--strict-resolution`` collapses this to
"only emit when exactly 1 entity resolves" if the user wants tight provenance.

Idempotence
-----------

``am_entity_annotation`` has no UNIQUE constraint (annotation streams are
append-only by design — see 046_annotation_layer.sql). To stay safe across
re-runs we maintain a per-run dedup set keyed by:

    (entity_id, kind, observed_at, COALESCE(score, -1.0), substr(text_ja, 1, 50))

For pre-existing rows we EXISTS-check the same tuple against the table before
INSERT. The check is `O(N)` per row, but we batch and the index
``idx_am_annot_entity_kind`` covers it.

Source row
----------

A single ``am_source`` row is created (INSERT OR IGNORE on UNIQUE source_url):

    source_url   = 'internal://autonomath/examiner_feedback'
    source_type  = 'reference'   (operator-internal, not a primary citation)
    domain       = 'autonomath.internal'

Flags
-----

* ``--dry-run``           — count + resolve only, no INSERT
* ``--limit N``           — read first N records only
* ``--batch-size N``      — commit every N records (default 1000)
* ``--strict-resolution`` — skip records that resolve to >1 am_entity
* ``--db PATH``           — override autonomath.db path
* ``--input PATH``        — override JSONL input path

Exit codes
----------

0 on success, 1 on schema/IO error.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "autonomath.db"
DEFAULT_INPUT = (
    Path.home() / "Autonomath" / "data" / "runtime" / "examiner_feedback.jsonl"
)

SOURCE_URL = "internal://autonomath/examiner_feedback"
SOURCE_TYPE = "reference"
SOURCE_DOMAIN = "autonomath.internal"

ANNOT_VISIBILITY = "internal"  # operator-internal per migration 046 default

DEDUP_TEXT_PREFIX = 50


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


def iter_records(path: Path, limit: int | None) -> Iterator[dict]:
    """Yield dict per JSONL line. Skip blank lines. Surface parse errors loud."""
    with path.open("r", encoding="utf-8") as fp:
        for lineno, raw in enumerate(fp, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError as exc:
                print(
                    f"[warn] line {lineno}: JSON parse failed ({exc}); skipping",
                    file=sys.stderr,
                )
                continue
            if limit is not None and lineno >= limit:
                return


# ---------------------------------------------------------------------------
# Schema preflight
# ---------------------------------------------------------------------------


def preflight(conn: sqlite3.Connection) -> None:
    """Verify migration 046 has been applied. Bail loudly otherwise."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name IN ('am_entity_annotation','am_annotation_kind',"
        "'am_entities','am_source','jpi_programs','entity_id_map')"
    )
    have = {row[0] for row in cur.fetchall()}
    required = {
        "am_entity_annotation",
        "am_annotation_kind",
        "am_entities",
        "am_source",
        "jpi_programs",
        "entity_id_map",
    }
    missing = required - have
    if missing:
        raise SystemExit(
            f"[fatal] missing tables: {sorted(missing)}. "
            f"Apply migration 046_annotation_layer.sql first."
        )

    # Confirm seed kinds exist
    cur = conn.execute(
        "SELECT kind FROM am_annotation_kind "
        "WHERE kind IN ('examiner_warning','examiner_correction','quality_score')"
    )
    seeded = {row[0] for row in cur.fetchall()}
    expected = {"examiner_warning", "examiner_correction", "quality_score"}
    if seeded != expected:
        raise SystemExit(
            f"[fatal] am_annotation_kind missing seed rows: {expected - seeded}"
        )


# ---------------------------------------------------------------------------
# Source row
# ---------------------------------------------------------------------------


def ensure_source(conn: sqlite3.Connection, dry_run: bool) -> int | None:
    """Insert (or fetch) the synthetic am_source row and return its id."""
    if dry_run:
        cur = conn.execute(
            "SELECT id FROM am_source WHERE source_url = ?", (SOURCE_URL,)
        )
        row = cur.fetchone()
        return row[0] if row else None

    conn.execute(
        "INSERT OR IGNORE INTO am_source(source_url, source_type, domain) "
        "VALUES (?, ?, ?)",
        (SOURCE_URL, SOURCE_TYPE, SOURCE_DOMAIN),
    )
    cur = conn.execute("SELECT id FROM am_source WHERE source_url = ?", (SOURCE_URL,))
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Entity resolution
# ---------------------------------------------------------------------------


class EntityResolver:
    """LRU-ish cache: program_name → tuple[am_entities.canonical_id, ...]."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._cache: dict[str, tuple[str, ...]] = {}

    def resolve(self, program_name: str) -> tuple[str, ...]:
        if program_name in self._cache:
            return self._cache[program_name]

        cur = self.conn.execute(
            """
            SELECT DISTINCT eim.am_canonical_id
              FROM jpi_programs p
              JOIN entity_id_map eim ON eim.jpi_unified_id = p.unified_id
              JOIN am_entities e     ON e.canonical_id     = eim.am_canonical_id
             WHERE p.primary_name = ?
            """,
            (program_name,),
        )
        result = tuple(row[0] for row in cur.fetchall())
        self._cache[program_name] = result
        return result


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------


def annotation_key(
    entity_id: str,
    kind: str,
    observed_at: str,
    score: float | None,
    text_ja: str | None,
) -> tuple:
    return (
        entity_id,
        kind,
        observed_at,
        float(score) if score is not None else -1.0,
        (text_ja or "")[:DEDUP_TEXT_PREFIX],
    )


def annotation_exists(conn: sqlite3.Connection, key: tuple) -> bool:
    entity_id, kind, observed_at, score_norm, text_prefix = key
    score_param = None if score_norm == -1.0 else score_norm
    if score_param is None:
        score_clause = "score IS NULL"
        params: tuple = (entity_id, kind, observed_at)
    else:
        score_clause = "score = ?"
        params = (entity_id, kind, observed_at, score_param)
    cur = conn.execute(
        f"""
        SELECT 1 FROM am_entity_annotation
         WHERE entity_id = ?
           AND kind = ?
           AND observed_at = ?
           AND {score_clause}
           AND substr(COALESCE(text_ja,''), 1, ?) = ?
         LIMIT 1
        """,
        (*params, DEDUP_TEXT_PREFIX, text_prefix),
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Annotation builders
# ---------------------------------------------------------------------------


def build_annotations(
    record: dict,
    entity_ids: Iterable[str],
    source_id: int | None,
) -> Iterator[tuple]:
    """Yield (entity_id, kind, severity, text_ja, score, meta_json,
    visibility, source_id, observed_at) tuples for INSERT.
    """
    timestamp = record.get("timestamp")
    if not timestamp:
        return  # cannot annotate without a temporal anchor
    quality_score = record.get("quality_score")
    sections = record.get("sections") or []
    warnings = record.get("quality_warnings") or []
    corrections = record.get("auto_corrections") or []

    sections_meta = json.dumps({"sections": sections}, ensure_ascii=False)

    for entity_id in entity_ids:
        # 1. quality_score (always emitted, even if score is None — reduces
        #    silent gaps in the time-series)
        yield (
            entity_id,
            "quality_score",
            "info",
            None,
            float(quality_score) if quality_score is not None else None,
            sections_meta,
            ANNOT_VISIBILITY,
            source_id,
            timestamp,
        )

        # 2. examiner_warning (one row per warning)
        for w in warnings:
            text = w if isinstance(w, str) else json.dumps(w, ensure_ascii=False)
            yield (
                entity_id,
                "examiner_warning",
                "warning",
                text,
                None,
                None,
                ANNOT_VISIBILITY,
                source_id,
                timestamp,
            )

        # 3. examiner_correction (one row per correction; meta carries before/after)
        for c in corrections:
            if isinstance(c, str):
                text = c
                meta = None
            elif isinstance(c, dict):
                # operator emits {"before": ..., "after": ...} or similar;
                # render a short text_ja and keep the full dict in meta_json
                text = (
                    c.get("description")
                    or c.get("text")
                    or c.get("after")
                    or json.dumps(c, ensure_ascii=False)[:200]
                )
                meta = json.dumps(c, ensure_ascii=False)
            else:
                text = json.dumps(c, ensure_ascii=False)[:200]
                meta = None
            yield (
                entity_id,
                "examiner_correction",
                "info",
                text,
                None,
                meta,
                ANNOT_VISIBILITY,
                source_id,
                timestamp,
            )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


INSERT_SQL = """
INSERT INTO am_entity_annotation(
    entity_id, kind, severity, text_ja, score, meta_json,
    visibility, source_id, observed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="autonomath.db path")
    ap.add_argument(
        "--input", type=Path, default=DEFAULT_INPUT, help="examiner_feedback.jsonl path"
    )
    ap.add_argument("--dry-run", action="store_true", help="count only, no INSERT")
    ap.add_argument("--limit", type=int, default=None, help="read first N records only")
    ap.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="commit every N records (default 1000)",
    )
    ap.add_argument(
        "--strict-resolution",
        action="store_true",
        help="skip records that resolve to >1 am_entity",
    )
    args = ap.parse_args(argv)

    if not args.db.exists():
        print(f"[fatal] db not found: {args.db}", file=sys.stderr)
        return 1
    if not args.input.exists():
        print(f"[fatal] input not found: {args.input}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    preflight(conn)

    source_id = ensure_source(conn, args.dry_run)
    if not args.dry_run:
        conn.commit()

    resolver = EntityResolver(conn)

    counters: Counter[str] = Counter()
    seen_keys: set[tuple] = set()
    unresolved_names: Counter[str] = Counter()

    inserted_since_commit = 0

    for idx, record in enumerate(iter_records(args.input, args.limit), start=1):
        counters["total_records"] += 1
        program_name = record.get("program_name")
        if not program_name:
            counters["skipped_no_name"] += 1
            continue

        entity_ids = resolver.resolve(program_name)
        if not entity_ids:
            counters["skipped_unresolved"] += 1
            unresolved_names[program_name] += 1
            continue
        if args.strict_resolution and len(entity_ids) > 1:
            counters["skipped_ambiguous"] += 1
            continue

        counters["resolved_records"] += 1
        counters["entity_fanout"] += len(entity_ids)

        for row in build_annotations(record, entity_ids, source_id):
            (
                entity_id,
                kind,
                _severity,
                text_ja,
                score,
                _meta,
                _visibility,
                _src,
                observed_at,
            ) = row
            key = annotation_key(entity_id, kind, observed_at, score, text_ja)

            # in-run dedup
            if key in seen_keys:
                counters["dup_skipped_run"] += 1
                continue
            seen_keys.add(key)

            # cross-run dedup against existing rows
            if not args.dry_run and annotation_exists(conn, key):
                counters["dup_skipped_db"] += 1
                continue

            counters[f"would_insert_{kind}"] += 1
            counters["would_insert_total"] += 1

            if args.dry_run:
                continue

            conn.execute(INSERT_SQL, row)
            inserted_since_commit += 1
            counters[f"inserted_{kind}"] += 1
            counters["inserted_total"] += 1

            if inserted_since_commit >= args.batch_size:
                conn.commit()
                inserted_since_commit = 0

        if idx % 1000 == 0:
            print(
                f"[progress] {idx} records | "
                f"resolved={counters['resolved_records']} "
                f"unresolved={counters['skipped_unresolved']} "
                f"inserted={counters['inserted_total']} "
                f"would_insert={counters['would_insert_total']} "
                f"dup_db={counters['dup_skipped_db']} "
                f"dup_run={counters['dup_skipped_run']}",
                file=sys.stderr,
            )

    if not args.dry_run and inserted_since_commit:
        conn.commit()

    # --- summary ---
    print("=== summary ===")
    print(f"input               : {args.input}")
    print(f"db                  : {args.db}")
    print(f"dry_run             : {args.dry_run}")
    print(f"strict_resolution   : {args.strict_resolution}")
    print(f"total_records       : {counters['total_records']}")
    print(f"resolved_records    : {counters['resolved_records']}")
    print(f"  entity_fanout     : {counters['entity_fanout']}")
    print(f"skipped_no_name     : {counters['skipped_no_name']}")
    print(f"skipped_unresolved  : {counters['skipped_unresolved']}")
    print(f"skipped_ambiguous   : {counters['skipped_ambiguous']}")
    print(f"dup_skipped_run     : {counters['dup_skipped_run']}")
    print(f"dup_skipped_db      : {counters['dup_skipped_db']}")
    if args.dry_run:
        print(f"would_insert_total  : {counters['would_insert_total']}")
        print(f"  quality_score     : {counters['would_insert_quality_score']}")
        print(f"  examiner_warning  : {counters['would_insert_examiner_warning']}")
        print(f"  examiner_correction: {counters['would_insert_examiner_correction']}")
    else:
        print(f"inserted_total      : {counters['inserted_total']}")
        print(f"  quality_score     : {counters['inserted_quality_score']}")
        print(f"  examiner_warning  : {counters['inserted_examiner_warning']}")
        print(f"  examiner_correction: {counters['inserted_examiner_correction']}")

    if unresolved_names:
        print("\ntop 20 unresolved program_name (frequency):")
        for name, n in unresolved_names.most_common(20):
            print(f"  {n:>5}  {name}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
