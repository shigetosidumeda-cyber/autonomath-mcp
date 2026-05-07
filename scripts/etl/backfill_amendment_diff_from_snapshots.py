#!/usr/bin/env python3
"""Backfill am_amendment_diff from paired am_amendment_snapshot rows.

A3 needs the existing v1/v2 snapshot pairs materialized into the append-only
``am_amendment_diff`` table. This script compares typed snapshot fields and
inserts one row per changed field. It is deterministic and idempotent.

No network. No LLM. No DELETE/UPDATE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"

SNAPSHOT_FIELDS: tuple[str, ...] = (
    "amount_max_yen",
    "subsidy_rate_max",
    "target_set_json",
    "source_url",
    "source_fetched_at",
)

RAW_TYPED_FIELDS: tuple[str, ...] = (
    "amount_max_yen",
    "subsidy_rate_max",
    "target_set_json",
    "source_url",
)


@dataclass(frozen=True)
class SnapshotDiff:
    entity_id: str
    field_name: str
    prev_value: str | None
    new_value: str | None
    prev_hash: str | None
    new_hash: str | None
    source_url: str | None


def _hash_value(value: str | None) -> str | None:
    if value is None:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_value(field_name: str, value: Any) -> str | None:
    if field_name == "target_set_json":
        if value is None or str(value).strip() == "":
            return "[]"
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return str(value).strip()
        if parsed is None or parsed == "":
            return "[]"
        if isinstance(parsed, list):
            return _canonical_json_value(sorted(str(v) for v in parsed))
        return _canonical_json_value(parsed)
    if value is None:
        return None
    return str(value)


def should_record_field_change(
    field_name: str,
    prev_value: Any,
    new_value: Any,
) -> bool:
    return canonical_value(field_name, prev_value) != canonical_value(field_name, new_value)


def collect_snapshot_diffs(conn: sqlite3.Connection) -> list[SnapshotDiff]:
    rows = conn.execute(
        """SELECT p.entity_id,
                  p.amount_max_yen AS prev_amount_max_yen,
                  n.amount_max_yen AS new_amount_max_yen,
                  p.subsidy_rate_max AS prev_subsidy_rate_max,
                  n.subsidy_rate_max AS new_subsidy_rate_max,
                  p.target_set_json AS prev_target_set_json,
                  n.target_set_json AS new_target_set_json,
                  p.source_url AS prev_source_url,
                  n.source_url AS new_source_url,
                  p.source_fetched_at AS prev_source_fetched_at,
                  n.source_fetched_at AS new_source_fetched_at,
                  p.eligibility_hash AS prev_eligibility_hash,
                  n.eligibility_hash AS new_eligibility_hash,
                  p.summary_hash AS prev_summary_hash,
                  n.summary_hash AS new_summary_hash,
                  p.raw_snapshot_json AS prev_raw_snapshot_json,
                  n.raw_snapshot_json AS new_raw_snapshot_json
             FROM am_amendment_snapshot p
             JOIN am_amendment_snapshot n
               ON n.entity_id = p.entity_id
              AND n.version_seq = 2
            WHERE p.version_seq = 1
         ORDER BY p.entity_id"""
    )
    diffs: list[SnapshotDiff] = []
    for row in rows:
        for field_name in SNAPSHOT_FIELDS:
            prev_raw = row[f"prev_{field_name}"]
            new_raw = row[f"new_{field_name}"]
            if not should_record_field_change(field_name, prev_raw, new_raw):
                continue
            prev = canonical_value(field_name, prev_raw)
            new = canonical_value(field_name, new_raw)
            diffs.append(
                SnapshotDiff(
                    entity_id=row["entity_id"],
                    field_name=field_name,
                    prev_value=prev,
                    new_value=new,
                    prev_hash=_hash_value(prev),
                    new_hash=_hash_value(new),
                    source_url=row["new_source_url"] or row["prev_source_url"],
                )
            )
        raw_typed_changes: dict[str, dict[str, Any]] = {}
        for field_name in RAW_TYPED_FIELDS:
            prev_raw = row[f"prev_{field_name}"]
            new_raw = row[f"new_{field_name}"]
            if prev_raw != new_raw:
                raw_typed_changes[field_name] = {
                    "prev": prev_raw,
                    "new": new_raw,
                }
        if (
            raw_typed_changes
            and row["prev_raw_snapshot_json"] == row["new_raw_snapshot_json"]
            and row["prev_eligibility_hash"] == row["new_eligibility_hash"]
            and row["prev_summary_hash"] == row["new_summary_hash"]
        ):
            prev = None
            new = _canonical_json_value(raw_typed_changes)
            diffs.append(
                SnapshotDiff(
                    entity_id=row["entity_id"],
                    field_name="projection_regression_candidate",
                    prev_value=prev,
                    new_value=new,
                    prev_hash=_hash_value(prev),
                    new_hash=_hash_value(new),
                    source_url=row["new_source_url"] or row["prev_source_url"],
                )
            )
    return diffs


def _existing_keys(conn: sqlite3.Connection) -> set[tuple[str, str, str | None, str | None]]:
    return {
        (row["entity_id"], row["field_name"], row["prev_hash"], row["new_hash"])
        for row in conn.execute(
            """SELECT entity_id, field_name, prev_hash, new_hash
                 FROM am_amendment_diff"""
        )
    }


def insert_snapshot_diffs(
    conn: sqlite3.Connection,
    diffs: list[SnapshotDiff],
    *,
    apply: bool,
) -> dict[str, int]:
    before = conn.execute("SELECT COUNT(*) FROM am_amendment_diff").fetchone()[0]
    existing = _existing_keys(conn)
    candidates = [
        diff
        for diff in diffs
        if (diff.entity_id, diff.field_name, diff.prev_hash, diff.new_hash) not in existing
    ]
    inserted = 0
    if apply and candidates:
        detected_at = datetime.now(UTC).isoformat(timespec="seconds")
        started_tx = not conn.in_transaction
        if started_tx:
            conn.execute("BEGIN IMMEDIATE")
        try:
            for diff in candidates:
                conn.execute(
                    """INSERT INTO am_amendment_diff
                       (entity_id, field_name, prev_value, new_value,
                        prev_hash, new_hash, detected_at, source_url)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        diff.entity_id,
                        diff.field_name,
                        diff.prev_value,
                        diff.new_value,
                        diff.prev_hash,
                        diff.new_hash,
                        detected_at,
                        diff.source_url,
                    ),
                )
                inserted += 1
            fk_errors = conn.execute("PRAGMA foreign_key_check(am_amendment_diff)").fetchall()
            if fk_errors:
                raise RuntimeError(f"foreign_key_check failed: {fk_errors[:3]}")
            if started_tx:
                conn.commit()
        except Exception:
            if started_tx:
                conn.rollback()
            raise
    after = conn.execute("SELECT COUNT(*) FROM am_amendment_diff").fetchone()[0]
    return {
        "am_amendment_diff_before": before,
        "candidate_diffs_total": len(diffs),
        "candidate_diffs_new": len(candidates),
        "inserted_diffs": inserted,
        "am_amendment_diff_after": after,
    }


def run(*, db_path: Path, apply: bool) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        diffs = collect_snapshot_diffs(conn)
        summary = insert_snapshot_diffs(conn, diffs, apply=apply)
        return {
            "mode": "apply" if apply else "dry_run",
            "db": str(db_path),
            **summary,
            "sample_diffs": [asdict(diff) for diff in diffs[:5]],
        }
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    summary = run(db_path=args.db, apply=args.apply)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        for key, value in summary.items():
            if key != "sample_diffs":
                print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
