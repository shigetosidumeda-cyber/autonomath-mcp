#!/usr/bin/env python3
"""Validate the offline execution resume ledger.

The checker is intentionally local-only: it reads JSON artifacts, validates the
resume gates, and exits non-zero if live AWS is enabled before preflight.
"""

from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path
from typing import Any

DEFAULT_STATE_PATH = (
    Path("docs") / "_internal" / "execution" / "rc1-p0-bootstrap" / "execution_state.json"
)
AWS_CANARY_READY = "AWS_CANARY_READY"
REQUIRED_SAFETY_GATES = {
    "preflight_scorecard_state",
    "cash_bill_guard_enabled",
    "no_mutating_aws_commands",
    "spend_simulation_pass_state",
    "teardown_simulation_pass_state",
}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _as_bool(payload: dict[str, Any], key: str) -> bool:
    return payload.get(key) is True


def _command_starts_with_aws(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    return bool(parts) and parts[0] == "aws"


def _preflight_passed(state: dict[str, Any], scorecard: dict[str, Any]) -> bool:
    preflight = state.get("preflight")
    if not isinstance(preflight, dict):
        return False
    blocking_gates = scorecard.get("blocking_gates", [])
    return (
        preflight.get("status") == "passed"
        and scorecard.get("state") == AWS_CANARY_READY
        and scorecard.get("cash_bill_guard_enabled") is True
        and blocking_gates == []
    )


def validate_state(repo_root: Path, state_path: Path) -> list[str]:
    errors: list[str] = []
    state = _load_json(state_path)

    if state.get("schema_version") != "jpcite.execution_state.v1":
        errors.append("schema_version must be jpcite.execution_state.v1")
    if state.get("owner_scope") != "resumable_execution_ledger_runbook_only":
        errors.append("owner_scope must stay limited to the resume ledger/runbook")
    if not isinstance(state.get("current_phase"), str) or not state["current_phase"]:
        errors.append("current_phase is required")
    if not isinstance(state.get("status"), str) or not state["status"]:
        errors.append("status is required")

    preflight = state.get("preflight")
    if not isinstance(preflight, dict):
        errors.append("preflight object is required")
        preflight = {}

    scorecard_path_value = preflight.get("scorecard_path")
    if not isinstance(scorecard_path_value, str) or not scorecard_path_value:
        errors.append("preflight.scorecard_path is required")
        scorecard = {}
    else:
        scorecard_path = repo_root / scorecard_path_value
        if not scorecard_path.exists():
            errors.append(f"preflight scorecard missing: {scorecard_path_value}")
            scorecard = {}
        else:
            scorecard = _load_json(scorecard_path)

    live_aws = state.get("live_aws")
    if not isinstance(live_aws, dict):
        errors.append("live_aws object is required")
        live_aws = {}

    safety_gates = state.get("safety_gates")
    if not isinstance(safety_gates, list):
        errors.append("safety_gates must be a list")
        safety_gates = []
    gate_names = {
        gate.get("gate")
        for gate in safety_gates
        if isinstance(gate, dict) and isinstance(gate.get("gate"), str)
    }
    missing_gates = sorted(REQUIRED_SAFETY_GATES - gate_names)
    if missing_gates:
        errors.append(f"missing safety gates: {', '.join(missing_gates)}")

    next_commands = state.get("next_commands")
    if not isinstance(next_commands, list) or not next_commands:
        errors.append("next_commands must be a non-empty list")
        next_commands = []

    for index, command_entry in enumerate(next_commands):
        if not isinstance(command_entry, dict):
            errors.append(f"next_commands[{index}] must be an object")
            continue
        command = command_entry.get("command")
        if not isinstance(command, str) or not command:
            errors.append(f"next_commands[{index}].command is required")
            continue
        if command_entry.get("mutating_aws") is True:
            errors.append(f"next_commands[{index}] declares mutating_aws=true")
        if command_entry.get("live_aws") is True:
            errors.append(f"next_commands[{index}] declares live_aws=true")
        if _command_starts_with_aws(command):
            errors.append(f"next_commands[{index}] starts with aws before preflight")

    live_enabled = (
        _as_bool(live_aws, "enabled")
        or _as_bool(live_aws, "mutating_commands_allowed")
        or _as_bool(preflight, "live_aws_commands_allowed")
        or _as_bool(scorecard, "live_aws_commands_allowed")
    )
    if live_enabled and not _preflight_passed(state, scorecard):
        errors.append("live AWS is enabled before preflight passed")

    if (
        scorecard.get("state") != AWS_CANARY_READY
        and scorecard.get("live_aws_commands_allowed") is True
    ):
        errors.append("scorecard allows live AWS while state is not AWS_CANARY_READY")
    if (
        preflight.get("cash_bill_guard_required") is True
        and scorecard.get("cash_bill_guard_enabled") is not True
    ):
        errors.append("cash bill guard is required but not enabled in scorecard")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the resumable execution state ledger.")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    state_path = args.state
    if not state_path.is_absolute():
        state_path = repo_root / state_path

    errors = validate_state(repo_root, state_path)
    if errors:
        for error in errors:
            print(f"execution resume state: error: {error}")
        return 1

    print("execution resume state: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
