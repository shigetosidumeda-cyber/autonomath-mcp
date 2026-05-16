import ast
import copy
import json
from pathlib import Path

from scripts.ops.check_execution_resume_state import main, validate_state

REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = (
    REPO_ROOT / "docs" / "_internal" / "execution" / "rc1-p0-bootstrap" / "execution_state.json"
)
CHECKER_PATH = REPO_ROOT / "scripts" / "ops" / "check_execution_resume_state.py"


def _load_state() -> dict:
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def test_execution_state_has_resume_surface() -> None:
    state = _load_state()

    assert state["schema_version"] == "jpcite.execution_state.v1"
    assert state["owner_scope"] == "resumable_execution_ledger_runbook_only"
    assert state["current_phase"]
    assert state["status"] == "blocked_before_aws_preflight"
    assert state["preflight"]["live_aws_commands_allowed"] is False
    assert state["live_aws"]["enabled"] is False
    assert state["live_aws"]["mutating_commands_allowed"] is False
    assert state["next_commands"]
    assert all(command["live_aws"] is False for command in state["next_commands"])
    assert all(command["mutating_aws"] is False for command in state["next_commands"])


def test_checker_passes_current_repo_state() -> None:
    assert validate_state(REPO_ROOT, STATE_PATH) == []
    assert main(["--repo-root", str(REPO_ROOT), "--state", str(STATE_PATH)]) == 0


def test_checker_fails_if_live_aws_enabled_before_preflight(tmp_path: Path) -> None:
    state = _load_state()
    state["live_aws"]["enabled"] = True
    temp_state = tmp_path / "execution_state.json"
    _write_json(temp_state, state)

    errors = validate_state(REPO_ROOT, temp_state)

    assert "live AWS is enabled before preflight passed" in errors


def test_checker_fails_if_scorecard_allows_live_aws_while_blocked(
    tmp_path: Path,
) -> None:
    state = _load_state()
    scorecard = json.loads(
        (REPO_ROOT / state["preflight"]["scorecard_path"]).read_text(encoding="utf-8")
    )
    scorecard["live_aws_commands_allowed"] = True

    temp_repo = tmp_path / "repo"
    temp_scorecard = temp_repo / state["preflight"]["scorecard_path"]
    temp_state = temp_repo / "execution_state.json"
    _write_json(temp_scorecard, scorecard)
    _write_json(temp_state, state)

    errors = validate_state(temp_repo, temp_state)

    assert "live AWS is enabled before preflight passed" in errors
    assert "scorecard allows live AWS while state is not AWS_CANARY_READY" in errors


def test_checker_fails_if_next_command_is_live_or_mutating_aws(
    tmp_path: Path,
) -> None:
    state = copy.deepcopy(_load_state())
    state["next_commands"][0]["command"] = "aws batch submit-job --job-name bad"
    state["next_commands"][0]["live_aws"] = True
    state["next_commands"][0]["mutating_aws"] = True
    temp_state = tmp_path / "execution_state.json"
    _write_json(temp_state, state)

    errors = validate_state(REPO_ROOT, temp_state)

    assert "next_commands[0] declares mutating_aws=true" in errors
    assert "next_commands[0] declares live_aws=true" in errors
    assert "next_commands[0] starts with aws before preflight" in errors


def test_checker_has_no_aws_sdk_or_subprocess_imports() -> None:
    forbidden_imports = {"boto3", "botocore", "subprocess", "requests", "urllib3"}
    tree = ast.parse(CHECKER_PATH.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = {alias.name.split(".", maxsplit=1)[0] for alias in node.names}
            assert imported.isdisjoint(forbidden_imports)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".", maxsplit=1)[0] not in forbidden_imports
