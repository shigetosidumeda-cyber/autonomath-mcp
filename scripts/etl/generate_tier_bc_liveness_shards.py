#!/usr/bin/env python3
"""Generate E3 Tier B/C URL liveness shell shards without running probes.

The generated shell scripts call ``scan_program_url_liveness.py`` later, one
domain at a time, using the domain-exclusive shard plan. Generation itself only
reads the JSON plan and writes shell wrappers; it does not probe URLs or mutate
SQLite.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DATE = "2026-05-01"
RUN_STAMP = RUN_DATE.replace("-", "")

DEFAULT_PLAN_INPUT = REPO_ROOT / "analysis_wave18" / f"tier_bc_liveness_plan_{RUN_DATE}.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "research" / "loops" / "runs" / RUN_STAMP
DEFAULT_RESULT_DIR = Path("analysis_wave18") / f"tier_bc_liveness_shards_{RUN_DATE}"
DEFAULT_LOG_DIR = Path("analysis_wave18")
DEFAULT_DB = Path("data") / "jpintel.db"
DEFAULT_PYTHON_BIN = ".venv/bin/python"
SCANNER_SCRIPT = "scripts/etl/scan_program_url_liveness.py"
MAX_PER_DOMAIN_RPS = 1.0
CSV_HEADER = (
    "unified_id,primary_name,tier,source_url,domain,previous_status,final_url,"
    "status_code,classification,method,error"
)


@dataclass(frozen=True)
class DomainPlan:
    domain: str
    row_count: int


@dataclass(frozen=True)
class ShardPlan:
    shard_number: int
    plan_shard_id: str
    row_count: int
    domains: tuple[DomainPlan, ...]

    @property
    def domain_count(self) -> int:
        return len(self.domains)


@dataclass(frozen=True)
class ShardScript:
    shard: ShardPlan
    path: Path
    log_path: Path
    output_csv: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _read_json_report(path: Path) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(report, dict):
        raise ValueError(f"JSON input {path} must contain an object")
    return report


def _positive_int(value: object, *, field: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return parsed


def _normalize_domain(value: object, *, field: str) -> str:
    domain = str(value or "").strip().lower().rstrip(".")
    if not domain:
        raise ValueError(f"{field} must not be empty")
    if "://" in domain or "/" in domain or any(char.isspace() for char in domain):
        raise ValueError(f"{field} must be a bare domain, got {domain!r}")
    return domain


def _domain_row_counts(report: dict[str, Any]) -> dict[str, int]:
    raw_domain_counts = report.get("domain_counts")
    if not isinstance(raw_domain_counts, list):
        raise ValueError("plan JSON is missing domain_counts list")

    counts: dict[str, int] = {}
    for index, item in enumerate(raw_domain_counts, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"domain_counts[{index}] must be an object")
        domain = _normalize_domain(item.get("domain"), field=f"domain_counts[{index}].domain")
        if domain in counts:
            raise ValueError(f"duplicate domain_counts entry for {domain}")
        counts[domain] = _positive_int(
            item.get("row_count"),
            field=f"domain_counts[{index}].row_count",
        )
    return counts


def _parse_shard_number(raw_shard_id: object, *, fallback: int) -> int:
    shard_id = str(raw_shard_id or "")
    suffix = shard_id.rsplit("-", maxsplit=1)[-1]
    if suffix.isdigit():
        return int(suffix)
    return fallback


def load_shard_plan(plan_input: Path) -> list[ShardPlan]:
    """Load and validate domain-exclusive liveness shards from a plan JSON."""
    report = _read_json_report(plan_input)
    counts_by_domain = _domain_row_counts(report)

    batching = report.get("safe_batching_plan")
    if not isinstance(batching, dict):
        raise ValueError("plan JSON is missing safe_batching_plan object")
    if batching.get("domain_exclusive") is not True:
        raise ValueError("safe_batching_plan.domain_exclusive must be true")

    raw_shards = batching.get("shards")
    if not isinstance(raw_shards, list):
        raise ValueError("safe_batching_plan.shards must be a list")

    seen_domains: dict[str, str] = {}
    seen_shard_numbers: set[int] = set()
    shards: list[ShardPlan] = []
    for index, raw_shard in enumerate(raw_shards, start=1):
        if not isinstance(raw_shard, dict):
            raise ValueError(f"safe_batching_plan.shards[{index}] must be an object")

        plan_shard_id = str(raw_shard.get("shard_id") or f"tier-bc-liveness-{index:02d}")
        shard_number = _parse_shard_number(plan_shard_id, fallback=index)
        if shard_number in seen_shard_numbers:
            raise ValueError(f"duplicate shard number {shard_number}")
        seen_shard_numbers.add(shard_number)

        raw_domains = raw_shard.get("domains")
        if not isinstance(raw_domains, list):
            raise ValueError(f"{plan_shard_id}.domains must be a list")

        domains: list[DomainPlan] = []
        seen_within_shard: set[str] = set()
        for domain_index, raw_domain in enumerate(raw_domains, start=1):
            domain = _normalize_domain(
                raw_domain,
                field=f"{plan_shard_id}.domains[{domain_index}]",
            )
            if domain in seen_within_shard:
                raise ValueError(f"duplicate domain {domain} within {plan_shard_id}")
            if domain in seen_domains:
                raise ValueError(
                    f"domain {domain} appears in both {seen_domains[domain]} and {plan_shard_id}"
                )
            if domain not in counts_by_domain:
                raise ValueError(
                    f"domain {domain} from {plan_shard_id} is missing from domain_counts"
                )

            seen_within_shard.add(domain)
            seen_domains[domain] = plan_shard_id
            domains.append(DomainPlan(domain=domain, row_count=counts_by_domain[domain]))

        row_count = _positive_int(raw_shard.get("row_count"), field=f"{plan_shard_id}.row_count")
        actual_row_count = sum(domain.row_count for domain in domains)
        if actual_row_count != row_count:
            raise ValueError(
                f"{plan_shard_id}.row_count {row_count} does not match domain_counts "
                f"sum {actual_row_count}"
            )

        declared_domain_count = _positive_int(
            raw_shard.get("domain_count"),
            field=f"{plan_shard_id}.domain_count",
        )
        if declared_domain_count != len(domains):
            raise ValueError(
                f"{plan_shard_id}.domain_count {declared_domain_count} does not match "
                f"domains list length {len(domains)}"
            )

        shards.append(
            ShardPlan(
                shard_number=shard_number,
                plan_shard_id=plan_shard_id,
                row_count=row_count,
                domains=tuple(domains),
            )
        )

    return sorted(shards, key=lambda shard: shard.shard_number)


def _script_path(output_dir: Path, *, shard_number: int, run_date: str) -> Path:
    return output_dir / f"tier_bc_liveness_shard_{shard_number:02d}_{run_date}.sh"


def _log_path(log_dir: Path, *, shard_number: int, run_date: str) -> Path:
    return log_dir / f"tier_bc_liveness_shard_{shard_number:02d}_{run_date}.log"


def _output_csv_path(result_dir: Path, *, shard_number: int, run_date: str) -> Path:
    return (
        result_dir
        / f"shard_{shard_number:02d}"
        / f"tier_bc_liveness_shard_{shard_number:02d}_{run_date}.csv"
    )


def _shell_assign(name: str, value: str | Path) -> str:
    return f"{name}={shlex.quote(str(value))}"


def _render_script(
    script: ShardScript,
    *,
    repo_root: Path,
    db_path: Path,
    python_bin: str,
    per_host_delay_sec: float,
    run_date: str,
    generated_at: str,
) -> str:
    shard_number = script.shard.shard_number
    result_dir = script.output_csv.parent
    output_filename = script.output_csv.name
    delay = str(per_host_delay_sec)

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"cd {shlex.quote(str(repo_root))}",
        f"PYTHON_BIN=${{PYTHON_BIN:-{shlex.quote(python_bin)}}}",
        f"DB_PATH=${{DB_PATH:-{shlex.quote(str(db_path))}}}",
        _shell_assign("LOG_PATH", script.log_path),
        _shell_assign("RESULT_DIR", result_dir),
        f'SHARD_CSV="$RESULT_DIR/{output_filename}"',
        'mkdir -p "$(dirname "$LOG_PATH")" "$RESULT_DIR"',
        'exec > >(tee "$LOG_PATH") 2>&1',
        "",
        "# Generated command wrapper only; generation did not run these probes.",
        "# Domain-exclusive shards are safe for parallel workers at <=1 req/sec/domain.",
        "echo "
        + shlex.quote(
            " ".join(
                [
                    f"tier_bc_liveness_shard={shard_number:02d}",
                    f"plan_shard_id={script.shard.plan_shard_id}",
                    f"run_date={run_date}",
                    f"generated_at={generated_at}",
                    f"domain_count={script.shard.domain_count}",
                    f"candidate_rows={script.shard.row_count}",
                    "complete=false",
                ]
            )
        ),
        'rm -f "$SHARD_CSV"',
        "HEADER_WRITTEN=0",
        "",
        "run_domain() {",
        '  local domain="$1"',
        '  local limit="$2"',
        '  local tmp_name="$3"',
        '  local tmp_csv="$RESULT_DIR/$tmp_name"',
        '  echo "domain=${domain} limit=${limit} tmp_output=${tmp_csv}"',
        '  "$PYTHON_BIN" ' + shlex.quote(SCANNER_SCRIPT) + " \\",
        '    --db "$DB_PATH" \\',
        '    --output "$tmp_csv" \\',
        '    --domain "$domain" \\',
        '    --limit "$limit" \\',
        f"    --per-host-delay-sec {shlex.quote(delay)} \\",
        "    --json",
        '  if [[ "$HEADER_WRITTEN" -eq 0 ]]; then',
        '    cat "$tmp_csv" > "$SHARD_CSV"',
        "    HEADER_WRITTEN=1",
        "  else",
        '    tail -n +2 "$tmp_csv" >> "$SHARD_CSV"',
        "  fi",
        '  rm -f "$tmp_csv"',
        "}",
    ]

    for index, domain in enumerate(script.shard.domains, start=1):
        lines.append("")
        lines.append(
            f"run_domain {shlex.quote(domain.domain)} {domain.row_count} domain_{index:03d}.csv.tmp"
        )

    lines.extend(
        [
            "",
            'if [[ "$HEADER_WRITTEN" -eq 0 ]]; then',
            f"  printf '%s\\n' {shlex.quote(CSV_HEADER)} > \"$SHARD_CSV\"",
            "fi",
            'echo "output_csv=${SHARD_CSV}"',
            "echo " + shlex.quote(f"tier_bc_liveness_shard={shard_number:02d} complete"),
        ]
    )
    return "\n".join(lines) + "\n"


def _write_script(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def generate_shard_scripts(
    *,
    plan_input: Path = DEFAULT_PLAN_INPUT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    repo_root: Path = REPO_ROOT,
    db_path: Path = DEFAULT_DB,
    result_dir: Path = DEFAULT_RESULT_DIR,
    log_dir: Path = DEFAULT_LOG_DIR,
    run_date: str = RUN_DATE,
    python_bin: str = DEFAULT_PYTHON_BIN,
    per_host_delay_sec: float = MAX_PER_DOMAIN_RPS,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Generate liveness shard scripts and return a machine-readable summary."""
    if per_host_delay_sec <= 0 or per_host_delay_sec > MAX_PER_DOMAIN_RPS:
        raise ValueError("per_host_delay_sec must be > 0 and <= 1.0")

    shards = load_shard_plan(plan_input)
    generated_at = generated_at or _utc_now()
    materialized_scripts: list[ShardScript] = []

    for shard in shards:
        script = ShardScript(
            shard=shard,
            path=_script_path(output_dir, shard_number=shard.shard_number, run_date=run_date),
            log_path=_log_path(log_dir, shard_number=shard.shard_number, run_date=run_date),
            output_csv=_output_csv_path(
                result_dir,
                shard_number=shard.shard_number,
                run_date=run_date,
            ),
        )
        content = _render_script(
            script,
            repo_root=repo_root,
            db_path=db_path,
            python_bin=python_bin,
            per_host_delay_sec=per_host_delay_sec,
            run_date=run_date,
            generated_at=generated_at,
        )
        _write_script(script.path, content)
        materialized_scripts.append(script)

    all_domains = [
        domain.domain for script in materialized_scripts for domain in script.shard.domains
    ]
    return {
        "ok": True,
        "complete": False,
        "plan_input": str(plan_input),
        "script_count": len(materialized_scripts),
        "domain_count": len(all_domains),
        "candidate_rows": sum(script.shard.row_count for script in materialized_scripts),
        "domain_exclusive": len(all_domains) == len(set(all_domains)),
        "per_host_delay_sec": per_host_delay_sec,
        "network_used": False,
        "db_mutation": False,
        "shards": [
            {
                "shard_number": script.shard.shard_number,
                "plan_shard_id": script.shard.plan_shard_id,
                "path": str(script.path),
                "log_path": str(script.log_path),
                "output_csv": str(script.output_csv),
                "domain_count": script.shard.domain_count,
                "candidate_rows": script.shard.row_count,
                "domains": [domain.domain for domain in script.shard.domains],
            }
            for script in materialized_scripts
        ],
        "completion_status": {
            "E3": "generated_scripts_only",
            "complete": False,
            "reason": "Generated scanner wrappers only; no URL liveness probes were run.",
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-input", type=Path, default=DEFAULT_PLAN_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULT_DIR)
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--run-date", default=RUN_DATE)
    parser.add_argument("--python-bin", default=DEFAULT_PYTHON_BIN)
    parser.add_argument("--per-host-delay-sec", type=float, default=MAX_PER_DOMAIN_RPS)
    parser.add_argument("--json", action="store_true", help="print full JSON summary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = generate_shard_scripts(
        plan_input=args.plan_input,
        output_dir=args.output_dir,
        repo_root=args.repo_root,
        db_path=args.db,
        result_dir=args.result_dir,
        log_dir=args.log_dir,
        run_date=args.run_date,
        python_bin=args.python_bin,
        per_host_delay_sec=args.per_host_delay_sec,
    )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"script_count={summary['script_count']}")
        print(f"domain_count={summary['domain_count']}")
        print(f"candidate_rows={summary['candidate_rows']}")
        print(f"domain_exclusive={summary['domain_exclusive']}")
        print("complete=False")
        for shard in summary["shards"]:
            print(
                f"shard_{shard['shard_number']:02d}="
                f"{shard['domain_count']} domains, "
                f"{shard['candidate_rows']} rows, "
                f"{shard['path']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
