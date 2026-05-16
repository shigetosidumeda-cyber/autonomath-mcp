#!/usr/bin/env python3
"""Read-only production deploy readiness gate.

This gate composes the production-adjacent checks that must stay green before a
deploy can mutate Fly production: Cloudflare Pages functions typecheck, release
capsule route/pointer validation, OpenAPI/MCP drift gates, and the local
AWS-credit preflight blocked state. It does not write files, apply migrations,
read secret values, or call deployed endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_CAPSULE_ID = "rc1-p0-bootstrap-2026-05-15"
ACTIVE_CAPSULE_DIR = "rc1-p0-bootstrap"
AWS_BLOCKED_STATE = "AWS_BLOCKED_PRE_FLIGHT"
# Stream W concern separation (2026-05-16): the scorecard is allowed to be in
# either AWS_BLOCKED_PRE_FLIGHT or AWS_CANARY_READY before deploy, as long as
# ``live_aws_commands_allowed`` is False. AWS_CANARY_READY means preflight
# passed; the operator unlock (Stream I) is what flips live commands.
AWS_PREFLIGHT_ALLOWED_STATES = frozenset({"AWS_BLOCKED_PRE_FLIGHT", "AWS_CANARY_READY"})


def _maybe_reexec_venv() -> None:
    """Use the repo virtualenv when invoked by a bare system python.

    uv-managed venvs symlink to a shared interpreter, so ``Path.resolve()``
    collapses ``.venv/bin/python`` and the global ``python3.12`` to the same
    file. Detect "already in venv" via ``sys.prefix`` instead.
    """

    venv_dir = REPO_ROOT / ".venv"
    venv_python = venv_dir / "bin" / "python"
    if (
        venv_python.exists()
        and Path(sys.prefix).resolve() != venv_dir.resolve()
        and os.environ.get("JPCITE_NO_VENV_REEXEC") != "1"
    ):
        os.environ["JPCITE_NO_VENV_REEXEC"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_maybe_reexec_venv()

for path in (REPO_ROOT, REPO_ROOT / "src"):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


@dataclass(frozen=True)
class GateCheck:
    name: str
    ok: bool
    issues: list[str]
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "issues": self.issues,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class CommandCheck:
    name: str
    argv: list[str]
    timeout_seconds: int = 600


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_command(repo_root: Path, command: CommandCheck) -> GateCheck:
    try:
        completed = subprocess.run(
            command.argv,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=command.timeout_seconds,
        )
    except FileNotFoundError as exc:
        return GateCheck(
            command.name,
            False,
            [f"command_not_found:{exc.filename}"],
            {"command": command.argv, "timeout_seconds": command.timeout_seconds},
        )
    except subprocess.TimeoutExpired as exc:
        return GateCheck(
            command.name,
            False,
            [f"timeout_seconds:{command.timeout_seconds}"],
            {
                "command": command.argv,
                "stdout_tail": (exc.stdout or "")[-4000:],
                "stderr_tail": (exc.stderr or "")[-4000:],
                "timeout_seconds": command.timeout_seconds,
            },
        )

    issues = [] if completed.returncode == 0 else [f"exit_code:{completed.returncode}"]
    if command.name == "functions_typecheck" and completed.returncode != 0:
        issues.append("hint:run npm ci --prefix functions before the readiness gate")
    return GateCheck(
        command.name,
        completed.returncode == 0,
        issues,
        {
            "command": command.argv,
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
            "timeout_seconds": command.timeout_seconds,
        },
    )


def _command_checks(repo_root: Path) -> list[CommandCheck]:
    py = sys.executable
    return [
        CommandCheck(
            "functions_typecheck",
            ["npm", "run", "--prefix", "functions", "typecheck"],
            timeout_seconds=180,
        ),
        CommandCheck(
            "release_capsule_validator",
            [
                py,
                str(repo_root / "scripts" / "ops" / "validate_release_capsule.py"),
                "--repo-root",
                str(repo_root),
            ],
            timeout_seconds=60,
        ),
        CommandCheck(
            "agent_runtime_contracts",
            [
                py,
                str(repo_root / "scripts" / "check_agent_runtime_contracts.py"),
                "--repo-root",
                str(repo_root),
            ],
            timeout_seconds=60,
        ),
        CommandCheck(
            "openapi_drift",
            [py, str(repo_root / "scripts" / "check_openapi_drift.py")],
            timeout_seconds=900,
        ),
        CommandCheck(
            "mcp_drift",
            [py, str(repo_root / "scripts" / "check_mcp_drift.py")],
            timeout_seconds=600,
        ),
    ]


def check_release_capsule_route(repo_root: Path) -> GateCheck:
    issues: list[str] = []
    function_path = repo_root / "functions" / "release" / "[[path]].ts"
    routes_path = repo_root / "site" / "_routes.json"
    headers_path = repo_root / "site" / "_headers"

    try:
        source = _read_text(function_path)
    except FileNotFoundError:
        source = ""
        issues.append(f"missing:{function_path.relative_to(repo_root)}")

    required_source_tokens = [
        'ACTIVE_POINTER_PATH = "/releases/current/runtime_pointer.json"',
        f'ACTIVE_CAPSULE_ID = "{ACTIVE_CAPSULE_ID}"',
        f'ACTIVE_CAPSULE_DIR = "{ACTIVE_CAPSULE_DIR}"',
        "live_aws_commands_allowed !== false",
        "aws_runtime_dependency_allowed !== false",
        "capsule_pointer_invalid",
        'request.method !== "GET" && request.method !== "HEAD"',
        "`/releases/${ACTIVE_CAPSULE_DIR}/release_capsule_manifest.json`",
        "/release/current/capsule_manifest.json",
        "/release/current/agent_surface/p0_facade.json",
        "/release/current/preflight_scorecard.json",
        "/release/current/zero_aws_posture_manifest.json",
    ]
    missing_tokens = [token for token in required_source_tokens if token not in source]
    issues.extend(f"release_function_missing_token:{token}" for token in missing_tokens)

    try:
        routes = _load_json(routes_path)
        include = routes.get("include") if isinstance(routes, dict) else None
        if not isinstance(include, list) or "/release/*" not in include:
            issues.append("routes_missing:/release/*")
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        issues.append(f"routes_unreadable:{exc}")

    try:
        headers = _read_text(headers_path)
        for token in (
            "/release/current/*",
            f"/release/{ACTIVE_CAPSULE_DIR}/*",
            "/releases/current/*",
            f"/releases/{ACTIVE_CAPSULE_DIR}/*",
        ):
            if token not in headers:
                issues.append(f"headers_missing:{token}")
    except FileNotFoundError:
        issues.append(f"missing:{headers_path.relative_to(repo_root)}")

    return GateCheck(
        "release_capsule_route",
        not issues,
        issues,
        {
            "function": str(function_path.relative_to(repo_root)),
            "routes": str(routes_path.relative_to(repo_root)),
            "headers": str(headers_path.relative_to(repo_root)),
            "active_capsule_id": ACTIVE_CAPSULE_ID,
            "active_capsule_dir": ACTIVE_CAPSULE_DIR,
        },
    )


def check_aws_blocked_preflight_state(repo_root: Path) -> GateCheck:
    issues: list[str] = []
    fixture = repo_root / "tests" / "fixtures" / "aws_credit" / "blocked_default.json"
    scorecard_path = (
        repo_root / "site" / "releases" / ACTIVE_CAPSULE_DIR / "preflight_scorecard.json"
    )

    try:
        from jpintel_mcp.agent_runtime.aws_credit_simulation import GATE_BLOCKED
        from scripts.ops.aws_credit_local_preflight import build_report

        report = build_report(fixture)
        if report.get("gate_state") != GATE_BLOCKED:
            issues.append(f"aws_preflight_fixture_state_mismatch:{report.get('gate_state')!r}")
        if report.get("live_aws_commands_allowed") is not False:
            issues.append("aws_preflight_fixture_allows_live_commands")
    except Exception as exc:
        report = {"error": repr(exc)}
        issues.append(f"aws_preflight_fixture_unreadable:{exc}")

    try:
        scorecard = _load_json(scorecard_path)
        if not isinstance(scorecard, dict):
            issues.append("preflight_scorecard_not_object")
        else:
            # Stream W (2026-05-16): accept either AWS_BLOCKED_PRE_FLIGHT or
            # AWS_CANARY_READY so the Stream Q promote is compatible with the
            # production gate. The hard invariant is that
            # live_aws_commands_allowed MUST remain False until the operator
            # unlock (Stream I) — that flip is what truly opens deploy risk.
            if scorecard.get("state") not in AWS_PREFLIGHT_ALLOWED_STATES:
                issues.append(f"preflight_scorecard_state_mismatch:{scorecard.get('state')!r}")
            if scorecard.get("live_aws_commands_allowed") is not False:
                issues.append("preflight_scorecard_allows_live_aws_commands")
            if scorecard.get("cash_bill_guard_enabled") is not True:
                issues.append("preflight_scorecard_cash_bill_guard_disabled")
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        scorecard = {"error": repr(exc)}
        issues.append(f"preflight_scorecard_unreadable:{exc}")

    return GateCheck(
        "aws_blocked_preflight_state",
        not issues,
        issues,
        {
            "fixture": str(fixture.relative_to(repo_root)),
            "scorecard": str(scorecard_path.relative_to(repo_root)),
            "expected_state": AWS_BLOCKED_STATE,
            "allowed_preflight_states": sorted(AWS_PREFLIGHT_ALLOWED_STATES),
            "fixture_gate_state": report.get("gate_state") if isinstance(report, dict) else None,
            "scorecard_state": scorecard.get("state") if isinstance(scorecard, dict) else None,
            "live_aws_commands_allowed": False,
        },
    )


def build_report(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    root = repo_root.resolve()
    checks = [_run_command(root, command) for command in _command_checks(root)]
    checks.append(check_release_capsule_route(root))
    checks.append(check_aws_blocked_preflight_state(root))

    failing = [check for check in checks if not check.ok]
    return {
        "scope": (
            "production deploy readiness; local commands only; no mutation; "
            "no deployed endpoints; no secret values"
        ),
        "generated_at": _utc_now(),
        "repo_root": str(root),
        "ok": not failing,
        "summary": {
            "pass": sum(1 for check in checks if check.ok),
            "fail": len(failing),
            "total": len(checks),
        },
        "checks": [check.to_dict() for check in checks],
        "issues": [{"name": check.name, "issues": check.issues} for check in failing],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only production deploy readiness gate."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--warn-only", action="store_true", help="Always exit 0.")
    args = parser.parse_args(argv)

    report = build_report(args.repo_root)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if args.warn_only:
        return 0
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
