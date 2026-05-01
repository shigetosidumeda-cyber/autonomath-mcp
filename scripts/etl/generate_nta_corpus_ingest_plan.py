#!/usr/bin/env python3
"""Generate the B10 NTA corpus ingest runbook and target shard wrappers.

This is an offline planning helper. It reads the existing B10 coverage JSON
plus local source constants, then writes a JSON runbook and shell wrappers for
later operator execution. It does not crawl NTA/KFS, does not call an LLM API,
and does not execute the generated ingest commands.
"""

from __future__ import annotations

import argparse
import ast
import json
import shlex
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DATE = "2026-05-01"
RUN_STAMP = RUN_DATE.replace("-", "")

DEFAULT_COVERAGE_INPUT = (
    REPO_ROOT / "analysis_wave18" / f"nta_corpus_coverage_{RUN_DATE}.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "analysis_wave18" / f"nta_corpus_ingest_plan_{RUN_DATE}.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "research" / "loops" / "runs" / RUN_STAMP
DEFAULT_LOG_DIR = Path("analysis_wave18")
DEFAULT_AUTONOMATH_DB = Path("autonomath.db")
DEFAULT_JPINTEL_DB = Path("data") / "jpintel.db"
DEFAULT_PYTHON_BIN = ".venv/bin/python"

INGEST_SOURCE = REPO_ROOT / "scripts" / "ingest" / "ingest_nta_corpus.py"
CRON_SCRIPT = "scripts/cron/ingest_nta_corpus_incremental.py"

TARGETS = ("shitsugi", "bunsho", "saiketsu")
TARGET_TABLES = {
    "shitsugi": "nta_shitsugi",
    "bunsho": "nta_bunsho_kaitou",
    "saiketsu": "nta_saiketsu",
}
TABLE_DIMENSIONS = {
    "nta_shitsugi": ("category", "category"),
    "nta_bunsho_kaitou": ("category", "category"),
    "nta_saiketsu": ("tax_type", "tax_type"),
    "nta_tsutatsu_index": ("tax_type", "law_canonical_id"),
}

MIN_MAX_MINUTES = 1.0
MAX_MAX_MINUTES = 20.0
DEFAULT_MAX_MINUTES = 20.0
DEFAULT_DUPLICATE_SAMPLE_LIMIT = 10


@dataclass(frozen=True)
class CategoryPlan:
    target: str
    table: str
    dimension: str
    category: str
    current_rows: int
    priority: int
    boundary: str


@dataclass(frozen=True)
class ShardPlan:
    shard_id: str
    target: str
    table: str
    path: Path
    stdout_log_path: Path
    cron_jsonl_log_path: Path
    max_minutes: float
    current_rows: int
    category_count: int
    zero_row_category_count: int
    category_queue: tuple[CategoryPlan, ...]
    dry_run_command: str
    command: str


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_json_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid coverage JSON {path}: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError(f"coverage JSON {path} must contain an object")
    return report


def _extract_literal_assignment(source_path: Path, name: str) -> Any:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise ValueError(f"{source_path} is missing {name}")


def load_expected_categories(ingest_source: Path = INGEST_SOURCE) -> dict[str, tuple[str, ...]]:
    """Read shitsugi/bunsho category constants from the local ingest source."""
    shitsugi_raw = _extract_literal_assignment(ingest_source, "SHITSUGI_CATEGORIES")
    bunsho_raw = _extract_literal_assignment(ingest_source, "BUNSHO_CATEGORIES")

    shitsugi = tuple(str(item).strip() for item in shitsugi_raw if str(item).strip())
    bunsho = tuple(str(item[0]).strip() for item in bunsho_raw if str(item[0]).strip())
    if not shitsugi:
        raise ValueError("SHITSUGI_CATEGORIES produced no categories")
    if not bunsho:
        raise ValueError("BUNSHO_CATEGORIES produced no categories")
    return {
        "shitsugi": shitsugi,
        "bunsho": bunsho,
    }


def _table_report(report: dict[str, Any], table: str) -> dict[str, Any]:
    tables = report.get("tables")
    if not isinstance(tables, dict):
        raise ValueError("coverage report is missing tables object")
    item = tables.get(table)
    if not isinstance(item, dict):
        return {
            "exists": False,
            "counts_by_dimension": [],
            "metadata_completeness": {"total_rows": 0},
        }
    return item


def _table_total_rows(report: dict[str, Any], table: str) -> int:
    metadata = _table_report(report, table).get("metadata_completeness", {})
    if not isinstance(metadata, dict):
        return 0
    try:
        return int(metadata.get("total_rows") or 0)
    except (TypeError, ValueError):
        return 0


def _dimension_rows(report: dict[str, Any], table: str, *, dimension_key: str) -> dict[str, int]:
    item = _table_report(report, table)
    raw_rows = item.get("counts_by_dimension", [])
    if not isinstance(raw_rows, list):
        return {}

    rows: dict[str, int] = {}
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        value = str(raw.get(dimension_key) or "").strip()
        if not value:
            continue
        try:
            row_count = int(raw.get("rows") or 0)
        except (TypeError, ValueError):
            row_count = 0
        rows[value] = row_count
    return rows


def _target_category_rows(
    report: dict[str, Any],
    *,
    target: str,
    expected_categories: dict[str, tuple[str, ...]],
) -> dict[str, int]:
    table = TARGET_TABLES[target]
    dimension_key, _ = TABLE_DIMENSIONS[table]
    rows = _dimension_rows(report, table, dimension_key=dimension_key)

    if target in expected_categories:
        merged = dict.fromkeys(expected_categories[target], 0)
        merged.update(rows)
        return merged
    return rows


def _validate_max_minutes(max_minutes: float) -> float:
    try:
        parsed = float(max_minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_minutes must be a number") from exc
    if parsed < MIN_MAX_MINUTES or parsed > MAX_MAX_MINUTES:
        raise ValueError(
            f"max_minutes must be between {MIN_MAX_MINUTES:g} and {MAX_MAX_MINUTES:g}"
        )
    return parsed


def _duration_minutes(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)


def _shell_command(
    *,
    target: str,
    max_minutes: float,
    autonomath_db: Path,
    jpintel_db: Path,
    log_file: Path,
    python_bin: str,
    dry_run: bool,
) -> str:
    args = [
        python_bin,
        CRON_SCRIPT,
        "--target",
        target,
        "--max-minutes",
        _duration_minutes(max_minutes),
        "--autonomath-db",
        str(autonomath_db),
        "--jpintel-db",
        str(jpintel_db),
        "--log-file",
        str(log_file),
    ]
    if dry_run:
        args.append("--dry-run")
    return " ".join(shlex.quote(arg) for arg in args)


def _script_path(output_dir: Path, *, target: str, run_date: str) -> Path:
    return output_dir / f"nta_corpus_{target}_{run_date}.sh"


def _stdout_log_path(log_dir: Path, *, target: str, run_date: str) -> Path:
    return log_dir / f"nta_corpus_{target}_{run_date}.log"


def _cron_log_path(log_dir: Path, *, target: str, run_date: str) -> Path:
    return log_dir / f"nta_corpus_{target}_{run_date}.jsonl"


def _build_category_plan(
    report: dict[str, Any],
    *,
    target: str,
    expected_categories: dict[str, tuple[str, ...]],
) -> tuple[CategoryPlan, ...]:
    table = TARGET_TABLES[target]
    dimension_label, _ = TABLE_DIMENSIONS[table]
    rows_by_category = _target_category_rows(
        report,
        target=target,
        expected_categories=expected_categories,
    )
    boundary = (
        "advisory: ingest_nta_corpus_incremental.py currently exposes --target "
        "only, so the generated command advances the target cursor rather than "
        "hard-filtering this category"
    )
    sorted_items = sorted(rows_by_category.items(), key=lambda item: (item[1], item[0]))
    return tuple(
        CategoryPlan(
            target=target,
            table=table,
            dimension=dimension_label,
            category=category,
            current_rows=rows,
            priority=index,
            boundary=boundary,
        )
        for index, (category, rows) in enumerate(sorted_items, start=1)
    )


def _build_shards(
    report: dict[str, Any],
    *,
    expected_categories: dict[str, tuple[str, ...]],
    output_dir: Path,
    log_dir: Path,
    run_date: str,
    max_minutes: float,
    autonomath_db: Path,
    jpintel_db: Path,
    python_bin: str,
) -> list[ShardPlan]:
    shards: list[ShardPlan] = []
    for index, target in enumerate(TARGETS, start=1):
        table = TARGET_TABLES[target]
        category_queue = _build_category_plan(
            report,
            target=target,
            expected_categories=expected_categories,
        )
        cron_log = _cron_log_path(log_dir, target=target, run_date=run_date)
        command = _shell_command(
            target=target,
            max_minutes=max_minutes,
            autonomath_db=autonomath_db,
            jpintel_db=jpintel_db,
            log_file=cron_log,
            python_bin=python_bin,
            dry_run=False,
        )
        dry_run_command = _shell_command(
            target=target,
            max_minutes=max_minutes,
            autonomath_db=autonomath_db,
            jpintel_db=jpintel_db,
            log_file=cron_log,
            python_bin=python_bin,
            dry_run=True,
        )
        shards.append(
            ShardPlan(
                shard_id=f"nta-corpus-{index:02d}-{target}",
                target=target,
                table=table,
                path=_script_path(output_dir, target=target, run_date=run_date),
                stdout_log_path=_stdout_log_path(log_dir, target=target, run_date=run_date),
                cron_jsonl_log_path=cron_log,
                max_minutes=max_minutes,
                current_rows=_table_total_rows(report, table),
                category_count=len(category_queue),
                zero_row_category_count=sum(
                    1 for item in category_queue if item.current_rows == 0
                ),
                category_queue=category_queue,
                dry_run_command=dry_run_command,
                command=command,
            )
        )
    return shards


def _duplicate_source_issue(
    report: dict[str, Any],
    *,
    sample_limit: int = DEFAULT_DUPLICATE_SAMPLE_LIMIT,
) -> dict[str, Any]:
    duplicates = report.get("duplicates", {})
    if not isinstance(duplicates, dict):
        duplicates = {}
    within_count = int(duplicates.get("within_table_count") or 0)
    across_count = int(duplicates.get("across_table_count") or 0)
    samples = duplicates.get("within_table", [])
    if not isinstance(samples, list):
        samples = []
    return {
        "severity": "blocker" if within_count or across_count else "none",
        "within_table_group_count": within_count,
        "across_table_group_count": across_count,
        "description": (
            "Coverage shows duplicate source_url groups. Most current samples are in "
            "nta_tsutatsu_index, whose schema keys by code rather than source_url."
            if within_count or across_count
            else "No duplicate source_url groups were reported."
        ),
        "top_groups": samples[:sample_limit],
    }


def _current_counts(report: dict[str, Any]) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for table in (
        "nta_shitsugi",
        "nta_bunsho_kaitou",
        "nta_saiketsu",
        "nta_tsutatsu_index",
    ):
        item = _table_report(report, table)
        metadata = item.get("metadata_completeness", {})
        if not isinstance(metadata, dict):
            metadata = {}
        dimension_key, dimension_label = TABLE_DIMENSIONS[table]
        tables[table] = {
            "exists": bool(item.get("exists")),
            "rows": int(metadata.get("total_rows") or 0),
            "source_url_missing": int(metadata.get("source_url_missing") or 0),
            "license_missing": metadata.get("license_missing"),
            "license_column_present": metadata.get("license_column_present"),
            "dimension": dimension_label,
            "counts_by_dimension": item.get("counts_by_dimension", []),
            "dimension_key": dimension_key,
        }
    return {
        "coverage_generated_at": report.get("generated_at"),
        "totals": report.get("totals", {}),
        "tables": tables,
    }


def _blockers(report: dict[str, Any], duplicate_issue: dict[str, Any]) -> list[dict[str, str]]:
    blockers = [
        {
            "id": "plan-only-no-crawl",
            "severity": "info",
            "scope": "B10",
            "issue": "This artifact only generates a runbook and shell wrappers.",
            "action": "Run the generated shell scripts later, then rerun coverage and acceptance queries.",
        },
        {
            "id": "category-boundaries-advisory",
            "severity": "warning",
            "scope": "scripts/cron/ingest_nta_corpus_incremental.py",
            "issue": "The cron supports --target but not --category.",
            "action": "Treat category rows as prioritization/monitoring until a category flag is added.",
        },
        {
            "id": "serial-execution-required",
            "severity": "warning",
            "scope": "generated shards",
            "issue": "Target cursors live under data/autonomath/_nta_{target}_cursor.txt.",
            "action": "Do not run multiple shards for the same target concurrently; prefer serial execution.",
        },
        {
            "id": "tsutatsu-not-in-cron",
            "severity": "warning",
            "scope": "nta_tsutatsu_index",
            "issue": "nta_tsutatsu_index is visible in coverage but not targetable via the incremental cron.",
            "action": "Use the separate local tsutatsu indexer path if tsutatsu coverage needs refresh.",
        },
    ]
    if duplicate_issue["severity"] == "blocker":
        blockers.append(
            {
                "id": "duplicate-source-url-groups",
                "severity": "blocker",
                "scope": "nta_tsutatsu_index/source_url",
                "issue": (
                    f"{duplicate_issue['within_table_group_count']} within-table and "
                    f"{duplicate_issue['across_table_group_count']} across-table duplicate "
                    "source_url groups are present in the coverage report."
                ),
                "action": (
                    "Resolve or formally accept the tsutatsu source_url grain before using "
                    "source_url uniqueness as an acceptance gate."
                ),
            }
        )

    tsutatsu_rows = _table_total_rows(report, "nta_tsutatsu_index")
    if tsutatsu_rows:
        blockers.append(
            {
                "id": "tsutatsu-license-column-absent",
                "severity": "info",
                "scope": "schema",
                "issue": "nta_tsutatsu_index has no license column in migration 103.",
                "action": "Interpret license_missing totals with this schema exception in mind.",
            }
        )
    return blockers


def _acceptance_queries() -> list[dict[str, str]]:
    return [
        {
            "name": "nta_table_counts",
            "db": "autonomath.db",
            "sql": (
                "SELECT 'nta_shitsugi' AS table_name, COUNT(*) AS rows FROM nta_shitsugi\n"
                "UNION ALL SELECT 'nta_bunsho_kaitou', COUNT(*) FROM nta_bunsho_kaitou\n"
                "UNION ALL SELECT 'nta_saiketsu', COUNT(*) FROM nta_saiketsu\n"
                "UNION ALL SELECT 'nta_tsutatsu_index', COUNT(*) FROM nta_tsutatsu_index;"
            ),
        },
        {
            "name": "nta_category_counts",
            "db": "autonomath.db",
            "sql": (
                "SELECT 'nta_shitsugi' AS table_name, category, COUNT(*) AS rows\n"
                "  FROM nta_shitsugi GROUP BY category\n"
                "UNION ALL\n"
                "SELECT 'nta_bunsho_kaitou', category, COUNT(*)\n"
                "  FROM nta_bunsho_kaitou GROUP BY category\n"
                "UNION ALL\n"
                "SELECT 'nta_saiketsu', tax_type, COUNT(*)\n"
                "  FROM nta_saiketsu GROUP BY tax_type\n"
                "ORDER BY table_name, rows DESC, category;"
            ),
        },
        {
            "name": "nta_source_url_and_license_completeness",
            "db": "autonomath.db",
            "sql": (
                "SELECT 'nta_shitsugi' AS table_name, COUNT(*) AS total_rows,\n"
                "       SUM(CASE WHEN source_url IS NULL OR TRIM(source_url) = '' THEN 1 ELSE 0 END) AS source_url_missing,\n"
                "       SUM(CASE WHEN license IS NULL OR TRIM(license) = '' THEN 1 ELSE 0 END) AS license_missing\n"
                "  FROM nta_shitsugi\n"
                "UNION ALL\n"
                "SELECT 'nta_bunsho_kaitou', COUNT(*),\n"
                "       SUM(CASE WHEN source_url IS NULL OR TRIM(source_url) = '' THEN 1 ELSE 0 END),\n"
                "       SUM(CASE WHEN license IS NULL OR TRIM(license) = '' THEN 1 ELSE 0 END)\n"
                "  FROM nta_bunsho_kaitou\n"
                "UNION ALL\n"
                "SELECT 'nta_saiketsu', COUNT(*),\n"
                "       SUM(CASE WHEN source_url IS NULL OR TRIM(source_url) = '' THEN 1 ELSE 0 END),\n"
                "       SUM(CASE WHEN license IS NULL OR TRIM(license) = '' THEN 1 ELSE 0 END)\n"
                "  FROM nta_saiketsu\n"
                "UNION ALL\n"
                "SELECT 'nta_tsutatsu_index', COUNT(*),\n"
                "       SUM(CASE WHEN source_url IS NULL OR TRIM(source_url) = '' THEN 1 ELSE 0 END),\n"
                "       NULL\n"
                "  FROM nta_tsutatsu_index;"
            ),
        },
        {
            "name": "nta_duplicate_source_url_groups",
            "db": "autonomath.db",
            "sql": (
                "WITH urls AS (\n"
                "  SELECT 'nta_shitsugi' AS table_name, TRIM(source_url) AS source_url FROM nta_shitsugi\n"
                "  UNION ALL SELECT 'nta_bunsho_kaitou', TRIM(source_url) FROM nta_bunsho_kaitou\n"
                "  UNION ALL SELECT 'nta_saiketsu', TRIM(source_url) FROM nta_saiketsu\n"
                "  UNION ALL SELECT 'nta_tsutatsu_index', TRIM(source_url) FROM nta_tsutatsu_index\n"
                ")\n"
                "SELECT table_name, source_url, COUNT(*) AS rows\n"
                "  FROM urls\n"
                " WHERE source_url IS NOT NULL AND source_url <> ''\n"
                " GROUP BY table_name, source_url\n"
                "HAVING COUNT(*) > 1\n"
                " ORDER BY rows DESC, table_name, source_url\n"
                " LIMIT 50;"
            ),
        },
        {
            "name": "nta_incremental_cron_recent_runs",
            "db": "data/jpintel.db",
            "sql": (
                "SELECT id, cron_name, started_at, finished_at, status,\n"
                "       rows_processed, rows_skipped, error_message\n"
                "  FROM cron_runs\n"
                " WHERE cron_name = 'ingest_nta_corpus_incremental'\n"
                " ORDER BY started_at DESC\n"
                " LIMIT 20;"
            ),
        },
    ]


def _runbook_steps(shards: list[ShardPlan], *, run_date: str) -> list[str]:
    commands = ", ".join(str(shard.path) for shard in shards)
    return [
        "Review blockers before running any networked ingest.",
        f"Run generated shard scripts serially from repo root: {commands}.",
        (
            ".venv/bin/python scripts/etl/report_nta_corpus_coverage.py "
            f"--db autonomath.db --output analysis_wave18/nta_corpus_coverage_{run_date}.json "
            "--write-report --json"
        ),
        "Run the acceptance SQL queries in this JSON against autonomath.db and data/jpintel.db.",
        "Keep B10 marked incomplete until ingest has actually run and the duplicate-source issue is resolved or accepted.",
    ]


def _shard_to_json(shard: ShardPlan) -> dict[str, Any]:
    data = asdict(shard)
    data["path"] = str(shard.path)
    data["stdout_log_path"] = str(shard.stdout_log_path)
    data["cron_jsonl_log_path"] = str(shard.cron_jsonl_log_path)
    data["category_queue"] = [asdict(item) for item in shard.category_queue]
    return data


def _render_script(
    shard: ShardPlan,
    *,
    repo_root: Path,
    python_bin: str,
    autonomath_db: Path,
    jpintel_db: Path,
    generated_at: str,
    run_date: str,
) -> str:
    category_summary = ", ".join(
        f"{item.category}:{item.current_rows}" for item in shard.category_queue[:20]
    )
    if len(shard.category_queue) > 20:
        category_summary += ", ..."

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"cd {shlex.quote(str(repo_root))}",
        f"PYTHON_BIN=${{PYTHON_BIN:-{shlex.quote(python_bin)}}}",
        f"AUTONOMATH_DB=${{AUTONOMATH_DB:-{shlex.quote(str(autonomath_db))}}}",
        f"JPINTEL_DB=${{JPINTEL_DB:-{shlex.quote(str(jpintel_db))}}}",
        f"STDOUT_LOG={shlex.quote(str(shard.stdout_log_path))}",
        f"CRON_JSONL_LOG={shlex.quote(str(shard.cron_jsonl_log_path))}",
        'mkdir -p "$(dirname "$STDOUT_LOG")" "$(dirname "$CRON_JSONL_LOG")"',
        'exec > >(tee "$STDOUT_LOG") 2>&1',
        "",
        "# Generated command wrapper only; generation did not run this ingest.",
        "# Category ordering is advisory because the cron supports --target, not --category.",
        "echo "
        + shlex.quote(
            " ".join(
                [
                    f"nta_corpus_shard={shard.shard_id}",
                    f"target={shard.target}",
                    f"run_date={run_date}",
                    f"generated_at={generated_at}",
                    f"max_minutes={_duration_minutes(shard.max_minutes)}",
                    f"current_rows={shard.current_rows}",
                    f"category_count={shard.category_count}",
                    f"zero_row_category_count={shard.zero_row_category_count}",
                    "complete=false",
                ]
            )
        ),
        "echo " + shlex.quote(f"category_queue={category_summary}"),
        "",
        '"$PYTHON_BIN" '
        + shlex.quote(CRON_SCRIPT)
        + " \\",
        f"  --target {shlex.quote(shard.target)} \\",
        f"  --max-minutes {shlex.quote(_duration_minutes(shard.max_minutes))} \\",
        '  --autonomath-db "$AUTONOMATH_DB" \\',
        '  --jpintel-db "$JPINTEL_DB" \\',
        '  --log-file "$CRON_JSONL_LOG"',
        "",
        "echo " + shlex.quote(f"nta_corpus_shard={shard.shard_id} complete"),
    ]
    return "\n".join(lines) + "\n"


def _write_script(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def write_plan(report: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def generate_ingest_plan(
    *,
    coverage_input: Path = DEFAULT_COVERAGE_INPUT,
    output: Path = DEFAULT_OUTPUT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    repo_root: Path = REPO_ROOT,
    log_dir: Path = DEFAULT_LOG_DIR,
    run_date: str = RUN_DATE,
    max_minutes: float = DEFAULT_MAX_MINUTES,
    autonomath_db: Path = DEFAULT_AUTONOMATH_DB,
    jpintel_db: Path = DEFAULT_JPINTEL_DB,
    python_bin: str = DEFAULT_PYTHON_BIN,
    ingest_source: Path = INGEST_SOURCE,
    generated_at: str | None = None,
    write_scripts: bool = True,
) -> dict[str, Any]:
    """Generate the ingest runbook JSON and optional shell wrappers."""
    max_minutes = _validate_max_minutes(max_minutes)
    coverage = _read_json_report(coverage_input)
    expected_categories = load_expected_categories(ingest_source)
    shards = _build_shards(
        coverage,
        expected_categories=expected_categories,
        output_dir=output_dir,
        log_dir=log_dir,
        run_date=run_date,
        max_minutes=max_minutes,
        autonomath_db=autonomath_db,
        jpintel_db=jpintel_db,
        python_bin=python_bin,
    )
    generated_at = generated_at or _utc_now()
    duplicate_issue = _duplicate_source_issue(coverage)

    if write_scripts:
        for shard in shards:
            _write_script(
                shard.path,
                _render_script(
                    shard,
                    repo_root=repo_root,
                    python_bin=python_bin,
                    autonomath_db=autonomath_db,
                    jpintel_db=jpintel_db,
                    generated_at=generated_at,
                    run_date=run_date,
                ),
            )

    target_category_count = sum(shard.category_count for shard in shards)
    plan = {
        "ok": True,
        "complete": False,
        "network_used": False,
        "generated_at": generated_at,
        "run_date": run_date,
        "coverage_input": str(coverage_input),
        "output": str(output),
        "current_counts": _current_counts(coverage),
        "expected_categories_from": str(ingest_source),
        "duplicate_source_issue": duplicate_issue,
        "blockers": _blockers(coverage, duplicate_issue),
        "max_minutes_boundary": {
            "min": MIN_MAX_MINUTES,
            "max": MAX_MAX_MINUTES,
            "selected_per_target": max_minutes,
            "reason": "Matches the incremental cron's per-target wall-clock cap; generator rejects larger unbounded shards.",
        },
        "shard_count": len(shards),
        "target_category_count": target_category_count,
        "zero_row_category_count": sum(shard.zero_row_category_count for shard in shards),
        "shards": [_shard_to_json(shard) for shard in shards],
        "acceptance_queries": _acceptance_queries(),
        "runbook_steps": _runbook_steps(shards, run_date=run_date),
        "completion_status": {
            "B10": "plan_only",
            "complete": False,
            "reason": "Generated a runbook and shell wrappers only; no ingest/crawling was executed.",
        },
    }
    write_plan(plan, output)
    return plan


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-input", type=Path, default=DEFAULT_COVERAGE_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--run-date", default=RUN_DATE)
    parser.add_argument("--max-minutes", type=float, default=DEFAULT_MAX_MINUTES)
    parser.add_argument("--autonomath-db", type=Path, default=DEFAULT_AUTONOMATH_DB)
    parser.add_argument("--jpintel-db", type=Path, default=DEFAULT_JPINTEL_DB)
    parser.add_argument("--python-bin", default=DEFAULT_PYTHON_BIN)
    parser.add_argument("--ingest-source", type=Path, default=INGEST_SOURCE)
    parser.add_argument("--no-scripts", action="store_true")
    parser.add_argument("--json", action="store_true", help="print full JSON summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    plan = generate_ingest_plan(
        coverage_input=args.coverage_input,
        output=args.output,
        output_dir=args.output_dir,
        repo_root=args.repo_root,
        log_dir=args.log_dir,
        run_date=args.run_date,
        max_minutes=args.max_minutes,
        autonomath_db=args.autonomath_db,
        jpintel_db=args.jpintel_db,
        python_bin=args.python_bin,
        ingest_source=args.ingest_source,
        write_scripts=not args.no_scripts,
    )

    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"output={plan['output']}")
        print(f"shard_count={plan['shard_count']}")
        print(f"target_category_count={plan['target_category_count']}")
        print(f"zero_row_category_count={plan['zero_row_category_count']}")
        print("complete=False")
        for shard in plan["shards"]:
            print(
                f"{shard['shard_id']} target={shard['target']} "
                f"categories={shard['category_count']} path={shard['path']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
