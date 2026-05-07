#!/usr/bin/env python3
"""Export proprietary / unknown source rows for license review.

E1 requires an explicit queue before any HuggingFace dataset export.  This
script does not modify the DB; it materializes all ``am_source`` rows whose
license is not redistributable into a CSV with linked-entity counts.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "license_review_queue.csv"
BLOCKED_LICENSES = {"proprietary", "unknown"}


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def collect_license_review_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT s.id AS source_id,
                  s.license,
                  s.domain,
                  s.source_url,
                  s.source_type,
                  s.first_seen,
                  s.last_verified,
                  COUNT(DISTINCT es.entity_id) AS linked_entity_count,
                  GROUP_CONCAT(DISTINCT es.entity_id) AS linked_entity_ids
             FROM am_source s
             LEFT JOIN am_entity_source es ON es.source_id = s.id
            WHERE s.license IN ('proprietary', 'unknown')
         GROUP BY s.id
         ORDER BY s.license, s.domain, s.id"""
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        linked = [item for item in str(row["linked_entity_ids"] or "").split(",") if item]
        out.append(
            {
                "source_id": row["source_id"],
                "license": row["license"],
                "domain": row["domain"] or "",
                "source_type": row["source_type"] or "",
                "source_url": row["source_url"],
                "first_seen": row["first_seen"] or "",
                "last_verified": row["last_verified"] or "",
                "linked_entity_count": int(row["linked_entity_count"] or 0),
                "sample_entity_ids": " ".join(linked[:10]),
            }
        )
    return out


def export_license_review_queue(
    conn: sqlite3.Connection,
    output: Path,
    *,
    apply: bool,
) -> dict[str, Any]:
    rows = collect_license_review_rows(conn)
    distinct_linked_entity_count = conn.execute(
        """SELECT COUNT(DISTINCT es.entity_id)
             FROM am_entity_source es
             JOIN am_source s ON s.id = es.source_id
            WHERE s.license IN ('proprietary', 'unknown')"""
    ).fetchone()[0]
    by_license: dict[str, int] = {}
    for row in rows:
        by_license[row["license"]] = by_license.get(row["license"], 0) + 1
    if apply:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "source_id",
                    "license",
                    "domain",
                    "source_type",
                    "source_url",
                    "first_seen",
                    "last_verified",
                    "linked_entity_count",
                    "sample_entity_ids",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
    return {
        "mode": "apply" if apply else "dry_run",
        "output": str(output),
        "blocked_source_rows": len(rows),
        "by_license": dict(sorted(by_license.items())),
        "linked_entities_total": sum(row["linked_entity_count"] for row in rows),
        "distinct_linked_entity_count": int(distinct_linked_entity_count or 0),
        "sample_rows": rows[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with _connect(args.db) as conn:
        result = export_license_review_queue(
            conn,
            args.output,
            apply=args.apply,
        )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"blocked_source_rows={result['blocked_source_rows']}")
        print(f"by_license={result['by_license']}")
        print(f"output={result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
