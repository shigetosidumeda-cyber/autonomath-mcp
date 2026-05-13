#!/usr/bin/env python3
"""Aggregate local pre-deploy verification commands.

This wrapper is read-only: it only runs existing local verification scripts and
summarizes their JSON output. It performs no network calls by itself and does
not request deployed endpoints.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class VerificationCommand:
    name: str
    argv: list[str]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def build_commands(
    repo_root: Path,
    *,
    preflight_db: Path | None = None,
    preflight_migrations_dir: Path | None = None,
) -> list[VerificationCommand]:
    scripts_dir = repo_root / "scripts" / "ops"
    preflight_argv = [
        sys.executable,
        str(scripts_dir / "preflight_production_improvement.py"),
        "--warn-only",
        "--json",
    ]
    if preflight_db is not None:
        preflight_argv.extend(["--db", str(preflight_db)])
    if preflight_migrations_dir is not None:
        preflight_argv.extend(["--migrations-dir", str(preflight_migrations_dir)])

    return [
        VerificationCommand(
            "release_readiness",
            [
                sys.executable,
                str(scripts_dir / "release_readiness.py"),
                "--repo-root",
                str(repo_root),
                "--warn-only",
            ],
        ),
        VerificationCommand(
            "production_improvement_preflight",
            preflight_argv,
        ),
        VerificationCommand(
            "pre_deploy_manifest_verify",
            [
                sys.executable,
                str(scripts_dir / "pre_deploy_manifest_verify.py"),
                "--warn-only",
            ],
        ),
        VerificationCommand(
            "perf_smoke",
            [
                sys.executable,
                str(scripts_dir / "perf_smoke.py"),
                "--samples",
                "1",
                "--warmups",
                "0",
                "--threshold-ms",
                "10000",
                "--json",
            ],
        ),
    ]


def _parse_json_output(stdout: str) -> tuple[Any | None, str | None]:
    try:
        return json.loads(stdout), None
    except json.JSONDecodeError as exc:
        return None, f"json_parse_error:{exc.msg}:line={exc.lineno}:column={exc.colno}"


def _payload_ok(name: str, payload: Any) -> tuple[bool, list[str]]:
    if name == "perf_smoke":
        if not isinstance(payload, list):
            return False, ["perf_smoke:expected_json_list"]
        failures = [
            str(item.get("name", index))
            for index, item in enumerate(payload)
            if not isinstance(item, dict) or not item.get("passed", False)
        ]
        return not failures, [f"perf_smoke:endpoint_failed:{failure}" for failure in failures]

    if not isinstance(payload, dict):
        return False, [f"{name}:expected_json_object"]
    issues = payload.get("issues", [])
    if payload.get("ok") is True:
        return True, []
    if isinstance(issues, list):
        return False, [str(issue) for issue in issues]
    return False, [f"{name}:ok_false"]


def run_command(command: VerificationCommand, repo_root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command.argv,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    payload, parse_error = _parse_json_output(completed.stdout)
    issues: list[str] = []
    payload_ok = False
    if parse_error is None:
        payload_ok, issues = _payload_ok(command.name, payload)
    else:
        issues.append(parse_error)

    if completed.returncode != 0:
        issues.append(f"exit_code:{completed.returncode}")

    return {
        "name": command.name,
        "command": command.argv,
        "returncode": completed.returncode,
        "ok": completed.returncode == 0 and payload_ok,
        "issues": issues,
        "stdout_json": payload,
        "stderr": completed.stderr,
    }


def build_report(
    repo_root: Path = REPO_ROOT,
    *,
    preflight_db: Path | None = None,
    preflight_migrations_dir: Path | None = None,
) -> dict[str, Any]:
    resolved_root = repo_root.resolve()
    results = [
        run_command(command, resolved_root)
        for command in build_commands(
            resolved_root,
            preflight_db=preflight_db,
            preflight_migrations_dir=preflight_migrations_dir,
        )
    ]
    failing = [result for result in results if not result["ok"]]
    return {
        "scope": "pre-deploy verification; local commands only; no mutation",
        "generated_at": _utc_now(),
        "repo_root": str(resolved_root),
        "ok": not failing,
        "summary": {
            "pass": sum(1 for result in results if result["ok"]),
            "fail": len(failing),
            "total": len(results),
        },
        "checks": results,
        "issues": [{"name": result["name"], "issues": result["issues"]} for result in failing],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local pre-deploy verification.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--preflight-db",
        type=Path,
        help="Database path passed through to preflight_production_improvement.py.",
    )
    parser.add_argument(
        "--preflight-migrations-dir",
        type=Path,
        help="Migrations dir passed through to preflight_production_improvement.py.",
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Always exit 0 after printing JSON, even when verification fails.",
    )
    args = parser.parse_args(argv)

    report = build_report(
        args.repo_root,
        preflight_db=args.preflight_db,
        preflight_migrations_dir=args.preflight_migrations_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.warn_only:
        return 0
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
