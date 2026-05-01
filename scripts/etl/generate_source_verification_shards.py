#!/usr/bin/env python3
"""Generate A5 quick-domain shell shards from precomputed plan artifacts.

This generator is deliberately offline: it reads the quick-domain CSV/JSON
created by ``list_source_verification_quick_domains.py`` and writes shell
wrappers for later operator execution. It performs no HTTP probes and does not
run any generated command.
"""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DATE = "2026-05-01"
RUN_STAMP = RUN_DATE.replace("-", "")

DEFAULT_JSON_INPUT = (
    REPO_ROOT / "analysis_wave18" / f"source_verification_quick_domains_{RUN_DATE}.json"
)
DEFAULT_CSV_INPUT = (
    REPO_ROOT / "analysis_wave18" / f"source_verification_quick_domains_{RUN_DATE}.csv"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "research" / "loops" / "runs" / RUN_STAMP
DEFAULT_LOG_DIR = Path("analysis_wave18")

BACKFILL_SCRIPT = "scripts/etl/backfill_am_source_last_verified.py"
DEFAULT_SHARD_COUNT = 4
DEFAULT_THRESHOLD = 50

CSV_REQUIRED_FIELDS = {
    "shard_id",
    "domain",
    "unverified_http_rows",
    "apply_command",
}


@dataclass(frozen=True)
class DomainCommand:
    shard_id: int
    domain: str
    unverified_http_rows: int
    apply_command: str


@dataclass(frozen=True)
class ShardScript:
    shard_id: int
    path: Path
    log_path: Path
    domains: tuple[DomainCommand, ...]

    @property
    def unverified_http_rows(self) -> int:
        return sum(domain.unverified_http_rows for domain in self.domains)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _positive_int(value: object, *, field: str, row_number: int | None = None) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        location = f" on CSV row {row_number}" if row_number is not None else ""
        raise ValueError(f"{field}{location} must be an integer") from exc
    if parsed <= 0:
        location = f" on CSV row {row_number}" if row_number is not None else ""
        raise ValueError(f"{field}{location} must be positive")
    return parsed


def _read_json_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError(f"JSON input {path} must contain an object")
    return report


def _threshold_from_report(report: dict[str, Any], fallback: int) -> int:
    selection = report.get("selection")
    if not isinstance(selection, dict):
        return fallback
    value = selection.get("threshold_unverified_http_rows_per_domain", fallback)
    return _positive_int(value, field="threshold_unverified_http_rows_per_domain")


def _json_shard_membership(report: dict[str, Any]) -> dict[str, int]:
    shards = report.get("shards")
    if not isinstance(shards, list):
        return {}

    membership: dict[str, int] = {}
    for index, shard in enumerate(shards, start=1):
        if not isinstance(shard, dict):
            raise ValueError(f"JSON shard entry {index} must be an object")
        shard_id = _positive_int(shard.get("shard_id"), field="JSON shard_id")
        domains = shard.get("domains", [])
        if not isinstance(domains, list):
            raise ValueError(f"JSON shard {shard_id} domains must be a list")
        for raw_domain in domains:
            domain = str(raw_domain).strip().lower()
            if not domain:
                continue
            if domain in membership:
                previous = membership[domain]
                raise ValueError(
                    f"JSON shards are not disjoint: {domain} appears in "
                    f"shards {previous} and {shard_id}"
                )
            membership[domain] = shard_id
    return membership


def load_domain_commands(csv_path: Path) -> list[DomainCommand]:
    """Load domain command rows from the quick-domain CSV artifact."""
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = sorted(CSV_REQUIRED_FIELDS - fieldnames)
        if missing:
            raise ValueError(f"CSV input {csv_path} is missing fields: {missing}")

        rows: list[DomainCommand] = []
        for row_number, row in enumerate(reader, start=2):
            domain = str(row.get("domain") or "").strip().lower()
            if not domain:
                raise ValueError(f"domain on CSV row {row_number} must not be empty")
            rows.append(
                DomainCommand(
                    shard_id=_positive_int(
                        row.get("shard_id"),
                        field="shard_id",
                        row_number=row_number,
                    ),
                    domain=domain,
                    unverified_http_rows=_positive_int(
                        row.get("unverified_http_rows"),
                        field="unverified_http_rows",
                        row_number=row_number,
                    ),
                    apply_command=str(row.get("apply_command") or "").strip(),
                )
            )
    return rows


def _option_value(args: list[str], flag: str, *, domain: str) -> str:
    try:
        index = args.index(flag)
    except ValueError as exc:
        raise ValueError(f"apply command for {domain} is missing {flag}") from exc
    try:
        value = args[index + 1]
    except IndexError as exc:
        raise ValueError(f"apply command for {domain} is missing a value for {flag}") from exc
    if value.startswith("--"):
        raise ValueError(f"apply command for {domain} is missing a value for {flag}")
    return value


def _validated_apply_command(command: DomainCommand) -> str:
    if not command.apply_command:
        raise ValueError(f"apply command for {command.domain} must not be empty")
    try:
        args = shlex.split(command.apply_command)
    except ValueError as exc:
        raise ValueError(f"apply command for {command.domain} is not shell-parseable") from exc

    if BACKFILL_SCRIPT not in args:
        raise ValueError(f"apply command for {command.domain} must call {BACKFILL_SCRIPT}")
    if "--apply" not in args:
        raise ValueError(f"apply command for {command.domain} must include --apply")
    if "--dry-run" in args:
        raise ValueError(f"apply command for {command.domain} must not include --dry-run")

    command_domain = _option_value(args, "--domain", domain=command.domain).strip().lower()
    if command_domain != command.domain:
        raise ValueError(
            f"apply command domain {command_domain} does not match CSV domain "
            f"{command.domain}"
        )

    limit = _positive_int(
        _option_value(args, "--limit", domain=command.domain),
        field=f"apply command limit for {command.domain}",
    )
    if limit < command.unverified_http_rows:
        raise ValueError(
            f"apply command limit for {command.domain} is less than "
            f"unverified_http_rows {command.unverified_http_rows}"
        )

    return " ".join(shlex.quote(arg) for arg in args)


def _build_shards(
    rows: list[DomainCommand],
    *,
    report: dict[str, Any],
    threshold: int,
    shard_count: int,
) -> tuple[list[ShardScript], int]:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")

    json_membership = _json_shard_membership(report)
    seen_domains: dict[str, int] = {}
    grouped: dict[int, list[DomainCommand]] = {shard_id: [] for shard_id in range(1, shard_count + 1)}
    excluded_over_threshold = 0

    for row in rows:
        if row.unverified_http_rows > threshold:
            excluded_over_threshold += 1
            continue
        if row.domain in seen_domains:
            previous = seen_domains[row.domain]
            raise ValueError(
                f"duplicate domain {row.domain} appears in shards {previous} and {row.shard_id}"
            )
        if row.shard_id not in grouped:
            raise ValueError(
                f"domain {row.domain} has shard_id {row.shard_id}; expected 1..{shard_count}"
            )
        json_shard_id = json_membership.get(row.domain)
        if json_membership and json_shard_id is None:
            raise ValueError(f"domain {row.domain} is missing from JSON shard assignments")
        if json_shard_id is not None and json_shard_id != row.shard_id:
            raise ValueError(
                f"CSV shard_id {row.shard_id} for {row.domain} does not match "
                f"JSON shard_id {json_shard_id}"
            )

        seen_domains[row.domain] = row.shard_id
        grouped[row.shard_id].append(
            replace(row, apply_command=_validated_apply_command(row))
        )

    scripts = [
        ShardScript(
            shard_id=shard_id,
            path=Path(),
            log_path=Path(),
            domains=tuple(grouped[shard_id]),
        )
        for shard_id in range(1, shard_count + 1)
    ]
    return scripts, excluded_over_threshold


def _script_path(output_dir: Path, *, shard_id: int, run_date: str) -> Path:
    return output_dir / f"source_verification_shard_{shard_id}_{run_date}.sh"


def _log_path(log_dir: Path, *, shard_id: int, run_date: str) -> Path:
    return log_dir / f"source_verification_shard_{shard_id}_{run_date}.log"


def _render_script(
    script: ShardScript,
    *,
    repo_root: Path,
    run_date: str,
    generated_at: str,
) -> str:
    log_arg = shlex.quote(str(script.log_path))
    log_parent_arg = shlex.quote(str(script.log_path.parent))
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"cd {shlex.quote(str(repo_root))}",
        f"mkdir -p {log_parent_arg}",
        f"exec > >(tee {log_arg}) 2>&1",
        "",
        "# Generated command wrapper only; generation did not run these commands.",
        "echo "
        + shlex.quote(
            " ".join(
                [
                    f"source_verification_shard={script.shard_id}",
                    f"run_date={run_date}",
                    f"generated_at={generated_at}",
                    f"domain_count={len(script.domains)}",
                    f"unverified_http_rows={script.unverified_http_rows}",
                ]
            )
        ),
    ]

    for domain in script.domains:
        lines.extend(
            [
                "",
                "echo "
                + shlex.quote(
                    f"domain={domain.domain} "
                    f"unverified_http_rows={domain.unverified_http_rows}"
                ),
                domain.apply_command,
            ]
        )

    lines.extend(
        [
            "",
            "echo " + shlex.quote(f"source_verification_shard={script.shard_id} complete"),
        ]
    )
    return "\n".join(lines) + "\n"


def _write_script(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def generate_shard_scripts(
    *,
    json_input: Path = DEFAULT_JSON_INPUT,
    csv_input: Path = DEFAULT_CSV_INPUT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    repo_root: Path = REPO_ROOT,
    log_dir: Path = DEFAULT_LOG_DIR,
    run_date: str = RUN_DATE,
    threshold: int | None = None,
    shard_count: int = DEFAULT_SHARD_COUNT,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Generate shell shard scripts and return a machine-readable summary."""
    report = _read_json_report(json_input)
    effective_threshold = (
        _positive_int(threshold, field="threshold")
        if threshold is not None
        else _threshold_from_report(report, DEFAULT_THRESHOLD)
    )
    rows = load_domain_commands(csv_input)
    scripts, excluded_over_threshold = _build_shards(
        rows,
        report=report,
        threshold=effective_threshold,
        shard_count=shard_count,
    )

    generated_at = generated_at or _utc_now()
    materialized_scripts: list[ShardScript] = []
    for script in scripts:
        materialized = replace(
            script,
            path=_script_path(output_dir, shard_id=script.shard_id, run_date=run_date),
            log_path=_log_path(log_dir, shard_id=script.shard_id, run_date=run_date),
        )
        content = _render_script(
            materialized,
            repo_root=repo_root,
            run_date=run_date,
            generated_at=generated_at,
        )
        _write_script(materialized.path, content)
        materialized_scripts.append(materialized)

    return {
        "ok": True,
        "complete": False,
        "json_input": str(json_input),
        "csv_input": str(csv_input),
        "threshold_unverified_http_rows_per_domain": effective_threshold,
        "script_count": len(materialized_scripts),
        "domain_count": sum(len(script.domains) for script in materialized_scripts),
        "unverified_http_rows": sum(
            script.unverified_http_rows for script in materialized_scripts
        ),
        "excluded_over_threshold_domain_count": excluded_over_threshold,
        "shards": [
            {
                "shard_id": script.shard_id,
                "path": str(script.path),
                "log_path": str(script.log_path),
                "domain_count": len(script.domains),
                "unverified_http_rows": script.unverified_http_rows,
                "domains": [domain.domain for domain in script.domains],
            }
            for script in materialized_scripts
        ],
        "completion_status": {
            "A5": "generated_scripts_only",
            "complete": False,
            "reason": "Generated shell commands only; no source verification probes were run.",
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-input", type=Path, default=DEFAULT_JSON_INPUT)
    parser.add_argument("--csv-input", type=Path, default=DEFAULT_CSV_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--run-date", default=RUN_DATE)
    parser.add_argument("--threshold", type=int, default=None)
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--json", action="store_true", help="print full JSON summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = generate_shard_scripts(
        json_input=args.json_input,
        csv_input=args.csv_input,
        output_dir=args.output_dir,
        repo_root=args.repo_root,
        log_dir=args.log_dir,
        run_date=args.run_date,
        threshold=args.threshold,
        shard_count=args.shards,
    )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"script_count={summary['script_count']}")
        print(f"domain_count={summary['domain_count']}")
        print(f"unverified_http_rows={summary['unverified_http_rows']}")
        print(
            "excluded_over_threshold_domain_count="
            f"{summary['excluded_over_threshold_domain_count']}"
        )
        print("complete=False")
        for shard in summary["shards"]:
            print(
                f"shard_{shard['shard_id']}="
                f"{shard['domain_count']} domains, "
                f"{shard['unverified_http_rows']} rows, "
                f"{shard['path']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
