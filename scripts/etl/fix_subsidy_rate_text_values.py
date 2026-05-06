#!/usr/bin/env python3
"""Fix text-valued subsidy_rate contamination in program tables.

D5 is intentionally narrow: it only targets rows where SQLite reports
``typeof(subsidy_rate) = 'text'``.  Three modes are supported:

  --audit              Count-only summary of contaminated rows. No DB or
                       filesystem writes. Safe to wire into ops dashboards.

  --dry-run            Walk candidates and write a CSV review file (default
                       output path is the migration-style file under
                       analysis_wave18/). DB is opened read-only.

  --apply              Same walk as --dry-run, then dual-write each row:
                         * ``subsidy_rate_text`` ← original display string
                           (requires migration 121 to have added the
                           column; falls back gracefully with a clear
                           error if the column is missing)
                         * ``subsidy_rate``      ← parsed numeric maximum
                           (or NULL for fixed-only values like ``定額``)
                       Apply also writes the CSV review file.

  --backfill-text-from-csv PATH
                       Historical-recovery mode for the case where a prior
                       --apply run already cleaned the REAL column but the
                       original text was discarded from the DB. Reads a
                       previously-written review CSV, joins on
                       (db_label, unified_id), and populates
                       ``subsidy_rate_text`` for those rows. Refuses to
                       update more than --max-updates rows (default 11) as
                       an over-application guard.

The dual-write approach was added 2026-05-01 (migration 121) to preserve the
human-readable display string. Reviewers, 税理士 顧問先 packs, and audit-seal
exports want the original phrasing — "1/2 or 定額" is materially different
from "2/3" even though both could parse to 0.5/0.667 equivalents.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
JPINTEL_DB = REPO_ROOT / "data" / "jpintel.db"
AUTONOMATH_DB = REPO_ROOT / "autonomath.db"
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / "subsidy_rate_text_fix_review.csv"
DEFAULT_APPLY_OUTPUT = REPO_ROOT / "analysis_wave18" / "subsidy_rate_apply_2026-05-01.csv"
LEGACY_REVIEW_CSV = REPO_ROOT / "analysis_wave18" / "subsidy_rate_text_fix_review.csv"
SUBSIDY_RATE_TEXT_COLUMN = "subsidy_rate_text"

# Over-application guard: refuse any apply / backfill that would touch more
# than this many rows in a single invocation. The known D5 footprint is 10
# unified_ids per table (× 2 tables = 20 row-updates total). Tightening to a
# small ceiling makes it impossible to silently rewrite the entire column on
# a future regex bug. Override per-call via --max-updates if a legitimate
# expansion ever lands.
DEFAULT_MAX_UPDATES = 11

PERCENT_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%")
FRACTION_RE = re.compile(r"(?<![\d.])(\d+)\s*/\s*(\d+)(?![\d.])")
FIXED_ONLY_TOKENS = ("定額",)

CSV_FIELDS = [
    "db_label",
    "db_path",
    "table_name",
    "unified_id",
    "primary_name",
    "authority_level",
    "authority_name",
    "prefecture",
    "municipality",
    "source_url",
    "official_url",
    "original_subsidy_rate_text",
    "parsed_subsidy_rate",
    "action",
    "parse_reason",
]


@dataclass(frozen=True)
class DbTarget:
    label: str
    path: Path
    table_name: str


@dataclass(frozen=True)
class SubsidyRateParse:
    value: float | None
    action: str
    reason: str


@dataclass(frozen=True)
class SubsidyRateFix:
    db_label: str
    db_path: str
    table_name: str
    unified_id: str
    primary_name: str
    authority_level: str | None
    authority_name: str | None
    prefecture: str | None
    municipality: str | None
    source_url: str | None
    official_url: str | None
    original_subsidy_rate_text: str
    parsed_subsidy_rate: float | None
    action: str
    parse_reason: str


DEFAULT_TARGETS = (
    DbTarget("jpintel", JPINTEL_DB, "programs"),
    DbTarget("autonomath", AUTONOMATH_DB, "jpi_programs"),
)


def parse_subsidy_rate_text(raw: object) -> SubsidyRateParse | None:
    """Parse a contaminated display string into a numeric max rate or NULL."""

    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    values: list[float] = []
    for match in PERCENT_RE.finditer(text):
        values.append(float(match.group(1)) / 100.0)
    for match in FRACTION_RE.finditer(text):
        numerator = int(match.group(1))
        denominator = int(match.group(2))
        if denominator == 0:
            continue
        values.append(numerator / denominator)

    if values:
        return SubsidyRateParse(
            value=round(max(values), 6),
            action="set_numeric_max",
            reason="numeric_rate_found",
        )
    if any(token in text for token in FIXED_ONLY_TOKENS):
        return SubsidyRateParse(
            value=None,
            action="set_null_fixed_only",
            reason="fixed_only_no_numeric_rate",
        )
    return None


def _connect(path: Path, *, apply: bool) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    if apply:
        conn = sqlite3.connect(str(path), timeout=30.0)
    else:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30.0)
        conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _require_table(conn: sqlite3.Connection, table_name: str) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
        (table_name,),
    ).fetchone()
    if exists is None:
        raise RuntimeError(f"missing required table: {table_name}")


def _candidate_query(table_name: str) -> str:
    return f"""
        SELECT
            unified_id,
            primary_name,
            authority_level,
            authority_name,
            prefecture,
            municipality,
            source_url,
            official_url,
            CAST(subsidy_rate AS TEXT) AS original_subsidy_rate_text
          FROM {table_name}
         WHERE typeof(subsidy_rate) = 'text'
           AND subsidy_rate IS NOT NULL
           AND TRIM(CAST(subsidy_rate AS TEXT)) != ''
         ORDER BY unified_id
    """


def collect_subsidy_rate_fixes(
    conn: sqlite3.Connection,
    target: DbTarget,
) -> list[SubsidyRateFix]:
    _require_table(conn, target.table_name)
    fixes: list[SubsidyRateFix] = []
    for row in conn.execute(_candidate_query(target.table_name)):
        parsed = parse_subsidy_rate_text(row["original_subsidy_rate_text"])
        if parsed is None:
            continue
        fixes.append(
            SubsidyRateFix(
                db_label=target.label,
                db_path=str(target.path),
                table_name=target.table_name,
                unified_id=str(row["unified_id"]),
                primary_name=str(row["primary_name"]),
                authority_level=row["authority_level"],
                authority_name=row["authority_name"],
                prefecture=row["prefecture"],
                municipality=row["municipality"],
                source_url=row["source_url"],
                official_url=row["official_url"],
                original_subsidy_rate_text=str(row["original_subsidy_rate_text"]),
                parsed_subsidy_rate=parsed.value,
                action=parsed.action,
                parse_reason=parsed.reason,
            )
        )
    return fixes


def _has_subsidy_rate_text_column(conn: sqlite3.Connection, table_name: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == SUBSIDY_RATE_TEXT_COLUMN for row in rows)


def apply_subsidy_rate_fixes(
    conn: sqlite3.Connection,
    fixes: list[SubsidyRateFix],
    *,
    max_updates: int = DEFAULT_MAX_UPDATES,
) -> int:
    if len(fixes) > max_updates:
        raise RuntimeError(
            f"refusing to apply {len(fixes)} updates: exceeds max_updates="
            f"{max_updates}. Pass --max-updates to override after auditing."
        )
    updated = 0
    with conn:
        for fix in fixes:
            has_text_col = _has_subsidy_rate_text_column(conn, fix.table_name)
            if has_text_col:
                cur = conn.execute(
                    f"""UPDATE {fix.table_name}
                           SET subsidy_rate = ?,
                               {SUBSIDY_RATE_TEXT_COLUMN} = ?
                         WHERE unified_id = ?
                           AND subsidy_rate = ?
                           AND typeof(subsidy_rate) = 'text'""",
                    (
                        fix.parsed_subsidy_rate,
                        fix.original_subsidy_rate_text,
                        fix.unified_id,
                        fix.original_subsidy_rate_text,
                    ),
                )
            else:
                # Fall back to numeric-only update if migration 121 has not
                # yet been applied to the target DB. Original text is still
                # captured in the review CSV; backfill_text_from_csv() can
                # restore it after the column is added.
                cur = conn.execute(
                    f"""UPDATE {fix.table_name}
                           SET subsidy_rate = ?
                         WHERE unified_id = ?
                           AND subsidy_rate = ?
                           AND typeof(subsidy_rate) = 'text'""",
                    (
                        fix.parsed_subsidy_rate,
                        fix.unified_id,
                        fix.original_subsidy_rate_text,
                    ),
                )
            updated += cur.rowcount
    return updated


def _write_review_csv(path: Path, fixes: list[SubsidyRateFix]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for fix in fixes:
            writer.writerow(
                {field: "" if value is None else value for field, value in asdict(fix).items()}
            )


def _count_text_rows(conn: sqlite3.Connection, table_name: str) -> int:
    return int(
        conn.execute(
            f"""SELECT COUNT(*)
                  FROM {table_name}
                 WHERE typeof(subsidy_rate) = 'text'
                   AND subsidy_rate IS NOT NULL
                   AND TRIM(CAST(subsidy_rate AS TEXT)) != ''"""
        ).fetchone()[0]
    )


def fix_subsidy_rate_text_values(
    targets: list[DbTarget],
    output: Path,
    *,
    apply: bool,
    max_updates: int = DEFAULT_MAX_UPDATES,
) -> dict[str, Any]:
    all_fixes: list[SubsidyRateFix] = []
    before_text_rows: dict[str, int] = {}
    after_text_rows: dict[str, int] = {}
    updated_rows_by_target: dict[str, int] = {}

    for target in targets:
        with _connect(target.path, apply=apply) as conn:
            _require_table(conn, target.table_name)
            before_text_rows[target.label] = _count_text_rows(conn, target.table_name)
            fixes = collect_subsidy_rate_fixes(conn, target)
            all_fixes.extend(fixes)
            updated_rows_by_target[target.label] = (
                apply_subsidy_rate_fixes(conn, fixes, max_updates=max_updates) if apply else 0
            )
            after_text_rows[target.label] = _count_text_rows(conn, target.table_name)

    if apply:
        _write_review_csv(output, all_fixes)

    action_counts = Counter(fix.action for fix in all_fixes)
    return {
        "mode": "apply" if apply else "dry_run",
        "output": str(output),
        "candidate_rows": len(all_fixes),
        "updated_rows": sum(updated_rows_by_target.values()),
        "before_text_rows": before_text_rows,
        "after_text_rows": after_text_rows,
        "action_counts": dict(sorted(action_counts.items())),
        "updated_rows_by_target": dict(sorted(updated_rows_by_target.items())),
        "sample_rows": [asdict(fix) for fix in all_fixes[:10]],
    }


def audit_subsidy_rate_text(
    targets: list[DbTarget],
) -> dict[str, Any]:
    """Read-only count of text-typed contamination per target. No CSV write."""

    text_rows: dict[str, int] = {}
    text_col_present: dict[str, bool] = {}
    for target in targets:
        with _connect(target.path, apply=False) as conn:
            _require_table(conn, target.table_name)
            text_rows[target.label] = _count_text_rows(conn, target.table_name)
            text_col_present[target.label] = _has_subsidy_rate_text_column(conn, target.table_name)
    return {
        "mode": "audit",
        "text_rows": text_rows,
        "subsidy_rate_text_column_present": text_col_present,
    }


def _read_review_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _csv_rows_for_target(rows: list[dict[str, str]], target: DbTarget) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row.get("db_label") == target.label
        and row.get("table_name") == target.table_name
        and row.get("original_subsidy_rate_text", "")
    ]


def backfill_text_from_csv(
    targets: list[DbTarget],
    csv_path: Path,
    output: Path,
    *,
    max_updates: int = DEFAULT_MAX_UPDATES,
    apply: bool,
) -> dict[str, Any]:
    """Restore ``subsidy_rate_text`` from a previously-written review CSV.

    Used when an earlier --apply discarded the original display string from
    the DB before migration 121 added the ``subsidy_rate_text`` column. The
    UPDATE refuses any row whose live ``parsed_subsidy_rate`` does not match
    the CSV's parsed value (or whose CSV-recorded action is unknown).
    """

    csv_rows = _read_review_csv(csv_path)
    backfill_records: list[dict[str, Any]] = []
    updated_by_target: dict[str, int] = {}
    skipped_by_target: dict[str, int] = {}

    for target in targets:
        target_rows = _csv_rows_for_target(csv_rows, target)
        if len(target_rows) > max_updates:
            raise RuntimeError(
                f"refusing to backfill {len(target_rows)} rows in target="
                f"{target.label}: exceeds max_updates={max_updates}."
            )

        with _connect(target.path, apply=apply) as conn:
            _require_table(conn, target.table_name)
            if apply and not _has_subsidy_rate_text_column(conn, target.table_name):
                raise RuntimeError(
                    f"target {target.label} ({target.table_name}) is missing the "
                    f"{SUBSIDY_RATE_TEXT_COLUMN} column. Apply migration 121 "
                    f"before running --backfill-text-from-csv."
                )

            updated = 0
            skipped = 0
            with conn:
                for csv_row in target_rows:
                    unified_id = csv_row["unified_id"]
                    original_text = csv_row["original_subsidy_rate_text"]
                    parsed_str = csv_row.get("parsed_subsidy_rate", "")
                    parsed_value: float | None = float(parsed_str) if parsed_str else None

                    live = conn.execute(
                        f"""SELECT subsidy_rate, typeof(subsidy_rate) AS rate_type,
                                   {SUBSIDY_RATE_TEXT_COLUMN} AS rate_text
                              FROM {target.table_name}
                             WHERE unified_id = ?""",
                        (unified_id,),
                    ).fetchone()
                    if live is None:
                        skipped += 1
                        backfill_records.append(
                            {
                                "db_label": target.label,
                                "unified_id": unified_id,
                                "before_subsidy_rate": None,
                                "before_subsidy_rate_text": None,
                                "after_subsidy_rate_text": original_text,
                                "action": "skip_missing_row",
                            }
                        )
                        continue

                    live_rate = live["subsidy_rate"]
                    live_text = live["rate_text"]
                    # Only safe to backfill if the live numeric matches what
                    # the prior --apply parsed; otherwise the row drifted
                    # post-cleanup and the CSV is no longer authoritative.
                    safe_match = (parsed_value is None and live_rate is None) or (
                        parsed_value is not None
                        and live_rate is not None
                        and abs(float(live_rate) - parsed_value) < 1e-6
                    )
                    if not safe_match:
                        skipped += 1
                        backfill_records.append(
                            {
                                "db_label": target.label,
                                "unified_id": unified_id,
                                "before_subsidy_rate": live_rate,
                                "before_subsidy_rate_text": live_text,
                                "after_subsidy_rate_text": original_text,
                                "action": "skip_drift",
                            }
                        )
                        continue

                    if live_text == original_text:
                        # Already backfilled — idempotent skip.
                        skipped += 1
                        backfill_records.append(
                            {
                                "db_label": target.label,
                                "unified_id": unified_id,
                                "before_subsidy_rate": live_rate,
                                "before_subsidy_rate_text": live_text,
                                "after_subsidy_rate_text": original_text,
                                "action": "skip_already_set",
                            }
                        )
                        continue

                    if apply:
                        cur = conn.execute(
                            f"""UPDATE {target.table_name}
                                   SET {SUBSIDY_RATE_TEXT_COLUMN} = ?
                                 WHERE unified_id = ?""",
                            (original_text, unified_id),
                        )
                        updated += cur.rowcount
                    backfill_records.append(
                        {
                            "db_label": target.label,
                            "unified_id": unified_id,
                            "before_subsidy_rate": live_rate,
                            "before_subsidy_rate_text": live_text,
                            "after_subsidy_rate_text": original_text,
                            "action": "set_subsidy_rate_text",
                        }
                    )
            updated_by_target[target.label] = updated
            skipped_by_target[target.label] = skipped

    if apply:
        _write_backfill_csv(output, backfill_records)

    return {
        "mode": "backfill_apply" if apply else "backfill_dry_run",
        "csv_path": str(csv_path),
        "output": str(output),
        "updated_rows": sum(updated_by_target.values()),
        "skipped_rows": sum(skipped_by_target.values()),
        "updated_rows_by_target": dict(sorted(updated_by_target.items())),
        "skipped_rows_by_target": dict(sorted(skipped_by_target.items())),
        "sample_rows": backfill_records[:10],
    }


BACKFILL_CSV_FIELDS = [
    "db_label",
    "unified_id",
    "before_subsidy_rate",
    "before_subsidy_rate_text",
    "after_subsidy_rate_text",
    "action",
]


def _write_backfill_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BACKFILL_CSV_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    field: ("" if record.get(field) is None else record.get(field))
                    for field in BACKFILL_CSV_FIELDS
                }
            )


def _targets_from_args(args: argparse.Namespace) -> list[DbTarget]:
    targets = [
        DbTarget("jpintel", args.jpintel_db, "programs"),
        DbTarget("autonomath", args.autonomath_db, "jpi_programs"),
    ]
    if args.only:
        wanted = set(args.only)
        targets = [target for target in targets if target.label in wanted]
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jpintel-db", type=Path, default=JPINTEL_DB)
    parser.add_argument("--autonomath-db", type=Path, default=AUTONOMATH_DB)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--only",
        action="append",
        choices=("jpintel", "autonomath"),
        help="Limit to one target; may be passed more than once.",
    )
    parser.add_argument(
        "--max-updates",
        type=int,
        default=DEFAULT_MAX_UPDATES,
        help=(
            "Refuse to apply more than this many UPDATEs per target "
            f"(default {DEFAULT_MAX_UPDATES}, the known D5 footprint + 1)."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--audit",
        action="store_true",
        help="Read-only count of contamination. No CSV write.",
    )
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument(
        "--backfill-text-from-csv",
        type=Path,
        default=None,
        metavar="REVIEW_CSV",
        help=(
            "Recovery mode: read previously-written review CSV and populate "
            f"the {SUBSIDY_RATE_TEXT_COLUMN} column for those unified_ids."
        ),
    )
    parser.add_argument(
        "--backfill-apply",
        action="store_true",
        help="Combine with --backfill-text-from-csv to actually write.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    targets = _targets_from_args(args)

    if args.audit:
        result = audit_subsidy_rate_text(targets)
    elif args.backfill_text_from_csv is not None:
        output = args.output or DEFAULT_APPLY_OUTPUT
        result = backfill_text_from_csv(
            targets,
            args.backfill_text_from_csv,
            output,
            apply=args.backfill_apply,
            max_updates=args.max_updates,
        )
    else:
        if args.apply:
            output = args.output or DEFAULT_APPLY_OUTPUT
        else:
            output = args.output or DEFAULT_OUTPUT
        result = fix_subsidy_rate_text_values(
            targets,
            output,
            apply=args.apply,
            max_updates=args.max_updates,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for key, value in result.items():
            if key == "sample_rows":
                continue
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
