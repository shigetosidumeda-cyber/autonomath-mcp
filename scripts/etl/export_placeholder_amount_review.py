#!/usr/bin/env python3
"""Export suspicious placeholder amount rows for manual review.

D2 is intentionally review-only.  It does not mutate SQLite data and does not
blanket-null amount values such as ``100``.  The detector is conservative: it
only queues program maximum amount rows that are stored as tiny JPY integers,
which is a strong signal that a ``万円`` source value may have been promoted as
raw yen.
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
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "placeholder_amount_review.csv"

REASON_TINY_JPY_PROGRAM_MAX = "tiny_jpy_program_max"
MAX_SUSPICIOUS_YEN = 999

CSV_FIELDS = [
    "reason",
    "amount_condition_id",
    "entity_id",
    "record_kind",
    "primary_name",
    "source_topic",
    "source_url",
    "condition_label",
    "source_field",
    "fixed_yen",
    "numeric_value",
    "unit",
    "currency",
    "evidence_fact_id",
    "fact_field_name",
    "fact_value_text",
    "fact_value_numeric",
    "fact_unit",
    "source_id",
    "source_license",
    "source_domain",
    "source_type",
    "review_note",
]


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _require_tables(conn: sqlite3.Connection) -> None:
    missing = [
        table
        for table in ("am_amount_condition", "am_entities", "am_entity_facts")
        if not _table_exists(conn, table)
    ]
    if missing:
        raise RuntimeError("missing required table(s): " + ", ".join(missing))


def collect_placeholder_amount_review_rows(
    conn: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Return review rows without mutating the database.

    The only D2 pattern currently queued is a program-level maximum amount
    promoted as ``amount_max_yen`` with an implausibly tiny JPY value.  This
    catches values like ``100`` without treating every amount of 100 as bad.
    """

    _require_tables(conn)
    rows = conn.execute(
        """
        SELECT
            ac.id AS amount_condition_id,
            ac.entity_id,
            e.record_kind,
            e.primary_name,
            e.source_topic,
            COALESCE(f.source_url, e.source_url) AS source_url,
            ac.condition_label,
            ac.source_field,
            ac.fixed_yen,
            ac.numeric_value,
            ac.unit,
            ac.currency,
            ac.evidence_fact_id,
            f.field_name AS fact_field_name,
            f.field_value_text AS fact_value_text,
            f.field_value_numeric AS fact_value_numeric,
            f.unit AS fact_unit,
            f.source_id,
            s.license AS source_license,
            s.domain AS source_domain,
            s.source_type AS source_type
          FROM am_amount_condition ac
          JOIN am_entities e ON e.canonical_id = ac.entity_id
          LEFT JOIN am_entity_facts f ON f.id = ac.evidence_fact_id
          LEFT JOIN am_source s ON s.id = f.source_id
         WHERE e.record_kind = 'program'
           AND ac.condition_label = 'max'
           AND ac.source_field = 'amount_max_yen'
           AND ac.fixed_yen BETWEEN 1 AND ?
           AND COALESCE(ac.currency, 'JPY') = 'JPY'
         ORDER BY ac.fixed_yen, e.primary_name, ac.entity_id, ac.id
        """,
        (MAX_SUSPICIOUS_YEN,),
    ).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["reason"] = REASON_TINY_JPY_PROGRAM_MAX
        item["review_note"] = (
            "Program max amount is stored as a tiny JPY integer; review source "
            "before any correction. Do not blanket-null this value."
        )
        out.append({field: item.get(field, "") for field in CSV_FIELDS})
    return out


def _counts_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def export_placeholder_amount_review(
    conn: sqlite3.Connection,
    output: Path,
    *,
    apply: bool,
) -> dict[str, Any]:
    rows = collect_placeholder_amount_review_rows(conn)
    if apply:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    return {
        "mode": "apply" if apply else "dry_run",
        "output": str(output),
        "review_rows": len(rows),
        "by_reason": _counts_by(rows, "reason"),
        "by_fixed_yen": _counts_by(rows, "fixed_yen"),
        "amount_100_review_rows": sum(
            1 for row in rows if str(row.get("fixed_yen")) == "100"
        ),
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
        result = export_placeholder_amount_review(
            conn,
            args.output,
            apply=args.apply,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"review_rows={result['review_rows']}")
        print(f"amount_100_review_rows={result['amount_100_review_rows']}")
        print(f"by_reason={result['by_reason']}")
        print(f"by_fixed_yen={result['by_fixed_yen']}")
        print(f"output={result['output']}")
        print(f"mode={result['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
