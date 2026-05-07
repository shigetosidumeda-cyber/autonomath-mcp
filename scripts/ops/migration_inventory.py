#!/usr/bin/env python3
"""Inventory SQL migrations without applying or editing them."""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS = REPO_ROOT / "scripts" / "migrations"
DEFAULT_OUT = REPO_ROOT / "docs" / "_internal" / "migration_inventory_latest.md"
JST = timezone(timedelta(hours=9))

NUMERIC_RE = re.compile(r"^(?P<num>\d+)_.*\.sql(?:\.draft)?$")
WAVE_RE = re.compile(r"^wave(?P<wave>\d+)_(?P<num>\d+[a-z]?)_.*\.sql$")
DANGEROUS_PATTERNS = {
    "drop_table": re.compile(r"\bdrop\s+table\b", re.IGNORECASE),
    "drop_index": re.compile(r"\bdrop\s+index\b", re.IGNORECASE),
    "drop_column": re.compile(r"\bdrop\s+column\b", re.IGNORECASE),
    "delete_from": re.compile(r"\bdelete\s+from\b", re.IGNORECASE),
    "truncate": re.compile(r"\btruncate\b", re.IGNORECASE),
}
TARGET_DB_RE = re.compile(r"^\s*--\s*target_db:\s*(?P<target>\S+)", re.IGNORECASE | re.MULTILINE)
BOOT_TIME_MANUAL_RE = re.compile(r"^\s*--\s*boot_time:\s*manual\b", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class MigrationFile:
    name: str
    family: str
    number: str
    is_rollback: bool
    is_draft: bool
    is_manual: bool
    target_db: str
    sha256_12: str
    dangerous: tuple[str, ...]


def _base_name(name: str) -> str:
    if name.endswith("_rollback.sql"):
        return name.removesuffix("_rollback.sql") + ".sql"
    return name


def classify_filename(name: str) -> tuple[str, str]:
    numeric = NUMERIC_RE.match(name)
    if numeric:
        return "numeric", numeric.group("num")
    wave = WAVE_RE.match(name)
    if wave:
        return f"wave{wave.group('wave')}", wave.group("num")
    return "other", ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _sql_without_line_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))


def _runner_header(text: str) -> str:
    return "\n".join(text.splitlines()[:5])


def _target_db(text: str) -> str:
    match = TARGET_DB_RE.search(_runner_header(text))
    return match.group("target") if match else "unmarked"


def _dangerous_markers(text: str) -> tuple[str, ...]:
    body = _sql_without_line_comments(text)
    return tuple(name for name, pattern in DANGEROUS_PATTERNS.items() if pattern.search(body))


def collect_migrations(root: Path = DEFAULT_MIGRATIONS) -> list[MigrationFile]:
    items: list[MigrationFile] = []
    for path in sorted(root.glob("*.sql*")):
        if not path.is_file():
            continue
        text = _read_text(path)
        family, number = classify_filename(path.name)
        items.append(
            MigrationFile(
                name=path.name,
                family=family,
                number=number,
                is_rollback=path.name.endswith("_rollback.sql"),
                is_draft=path.name.endswith(".draft"),
                is_manual=bool(BOOT_TIME_MANUAL_RE.search(_runner_header(text))),
                target_db=_target_db(text),
                sha256_12=hashlib.sha256(text.encode("utf-8")).hexdigest()[:12],
                dangerous=_dangerous_markers(text),
            )
        )
    return items


def render_markdown(root: Path = DEFAULT_MIGRATIONS) -> str:
    generated_at = datetime.now(UTC).astimezone(JST).isoformat(timespec="seconds")
    items = collect_migrations(root)
    family_counts = Counter(item.family for item in items)
    forward_numeric = [
        item
        for item in items
        if item.family == "numeric" and item.number and not item.is_rollback and not item.is_draft
    ]
    numeric_counts = Counter(item.number for item in forward_numeric)
    duplicate_numbers = sorted(number for number, count in numeric_counts.items() if count > 1)
    target_counts = Counter(item.target_db for item in items)

    names = {item.name for item in items}
    rollback_files = [item for item in items if item.is_rollback]
    forward_files = [item for item in items if not item.is_rollback and not item.is_draft]
    rollback_pairs = [item for item in rollback_files if _base_name(item.name) in names]
    orphan_rollbacks = [item for item in rollback_files if _base_name(item.name) not in names]
    paired_forward_names = {_base_name(item.name) for item in rollback_pairs}
    forward_missing_rollback = [
        item for item in forward_files if item.name not in paired_forward_names
    ]
    dangerous = [item for item in items if item.dangerous]
    dangerous_forward = [item for item in forward_files if item.dangerous]
    unmarked_target_db = [item for item in items if item.target_db == "unmarked"]
    manual = [item for item in items if item.is_manual]
    drafts = [item for item in items if item.is_draft]

    lines = [
        "# Migration Inventory",
        "",
        f"- generated_at: `{generated_at}`",
        f"- migrations_root: `{root}`",
        f"- migration_files: `{len(items)}`",
        f"- forward_files: `{len(forward_files)}`",
        f"- rollback_files: `{len(rollback_files)}`",
        f"- rollback_pairs: `{len(rollback_pairs)}`",
        f"- orphan_rollbacks: `{len(orphan_rollbacks)}`",
        f"- forward_missing_rollback: `{len(forward_missing_rollback)}`",
        f"- draft_files: `{len(drafts)}`",
        f"- manual_files: `{len(manual)}`",
        f"- duplicate_forward_numeric_prefixes: `{len(duplicate_numbers)}`",
        f"- files_with_dangerous_sql_markers: `{len(dangerous)}`",
        f"- forward_files_with_dangerous_sql_markers: `{len(dangerous_forward)}`",
        f"- unmarked_target_db_files: `{len(unmarked_target_db)}`",
        "",
        "## Family Counts",
        "",
        "| family | files |",
        "|---|---:|",
    ]
    for family, count in sorted(family_counts.items()):
        lines.append(f"| {family} | {count} |")

    lines.extend(
        [
            "",
            "## Target DB Counts",
            "",
            "| target_db | files |",
            "|---|---:|",
        ]
    )
    for target_db, count in sorted(target_counts.items()):
        lines.append(f"| {target_db} | {count} |")

    lines.extend(["", "## Duplicate Forward Numeric Prefixes", ""])
    if duplicate_numbers:
        for number in duplicate_numbers:
            files = [item.name for item in forward_numeric if item.number == number]
            lines.append(f"- `{number}`: " + ", ".join(f"`{name}`" for name in files))
    else:
        lines.append("- none")

    lines.extend(["", "## Orphan Rollbacks", ""])
    if orphan_rollbacks:
        lines.extend(
            f"- `{item.name}` expects `{_base_name(item.name)}`" for item in orphan_rollbacks
        )
    else:
        lines.append("- none")

    lines.extend(["", "## Manual And Draft Files", ""])
    if manual or drafts:
        for item in [*manual, *drafts]:
            flags = ", ".join(
                flag
                for flag, value in (("manual", item.is_manual), ("draft", item.is_draft))
                if value
            )
            lines.append(f"- `{item.name}` ({flags})")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Dangerous SQL Markers",
            "",
            "| file | markers |",
            "|---|---|",
        ]
    )
    for item in dangerous[:120]:
        lines.append(f"| `{item.name}` | {', '.join(item.dangerous)} |")
    overflow = len(dangerous) - 120
    if overflow > 0:
        lines.append(f"| ... | `{overflow}` more |")

    lines.extend(["", "## Unmarked Target DB Files", ""])
    if unmarked_target_db:
        for item in unmarked_target_db[:120]:
            lines.append(f"- `{item.name}`")
        overflow = len(unmarked_target_db) - 120
        if overflow > 0:
            lines.append(f"- ... `{overflow}` more")
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Review Rules",
            "",
            "1. Do not edit applied migrations; add a new migration instead.",
            "2. Keep rollback files paired with the exact forward migration name.",
            "3. Treat duplicate numeric prefixes and wave-prefixed migrations as release-order review items.",
            "4. Review `delete_from`, `drop_*`, and `truncate` markers before any production run.",
            "5. Treat `unmarked` target_db files as DB-boundary review items.",
            "",
        ]
    )
    return "\n".join(lines)


def preflight_failures(
    root: Path = DEFAULT_MIGRATIONS,
    *,
    fail_on_unmarked_target_db: bool = False,
    fail_on_dangerous_forward_sql: bool = False,
) -> list[str]:
    items = collect_migrations(root)
    forward_files = [item for item in items if not item.is_rollback and not item.is_draft]
    failures: list[str] = []
    if fail_on_unmarked_target_db:
        unmarked = [item for item in items if item.target_db == "unmarked"]
        if unmarked:
            failures.append(
                "unmarked target_db files: "
                + ", ".join(item.name for item in unmarked[:20])
                + (f", ... {len(unmarked) - 20} more" if len(unmarked) > 20 else "")
            )
    if fail_on_dangerous_forward_sql:
        dangerous_forward = [item for item in forward_files if item.dangerous]
        if dangerous_forward:
            failures.append(
                "dangerous forward SQL markers: "
                + ", ".join(
                    f"{item.name}({','.join(item.dangerous)})" for item in dangerous_forward[:20]
                )
                + (
                    f", ... {len(dangerous_forward) - 20} more"
                    if len(dangerous_forward) > 20
                    else ""
                )
            )
    return failures


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_MIGRATIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--fail-on-unmarked-target-db",
        action="store_true",
        help="Exit non-zero when any migration lacks a target_db directive in the runner header.",
    )
    parser.add_argument(
        "--fail-on-dangerous-forward-sql",
        action="store_true",
        help="Exit non-zero when a forward migration contains drop/delete/truncate markers.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    text = render_markdown(args.root)
    if args.dry_run:
        print(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
        print(args.out)
    failures = preflight_failures(
        args.root,
        fail_on_unmarked_target_db=args.fail_on_unmarked_target_db,
        fail_on_dangerous_forward_sql=args.fail_on_dangerous_forward_sql,
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
