"""Smoke tests for ``scripts/aws_credit_ops/continuous_burn_monitor.sh``.

The script needs network + AWS profile to do real work; these tests
exercise only the **structural** invariants that can be checked offline:

* The file exists, is executable, and has the canonical shebang.
* ``--help`` does not crash and prints the doc-comment block.
* The EventBridge schedule JSON sibling parses + carries the canonical
  knobs (hard-stop USD, slowdown USD, cooldown gates).
* The halt-sentinel mechanism short-circuits when present (the script
  must refuse to make any AWS calls and exit 0 with a ledger row).

NO LLM API. ``mypy --strict`` clean. ``[lane:solo]``.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "aws_credit_ops" / "continuous_burn_monitor.sh"
SCHEDULE_JSON = (
    REPO_ROOT / "infra" / "aws" / "eventbridge" / "jpcite_burn_monitor_schedule.json"
)


def test_script_exists_and_executable() -> None:
    assert SCRIPT.is_file(), f"missing {SCRIPT}"
    mode = SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "script must be executable by owner"


def test_script_has_bash_shebang() -> None:
    first_line = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#!/usr/bin/env bash"), first_line


def test_script_help_runs() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    # The --help path prints the comment block which mentions the loop steps.
    assert "continuous_burn_monitor.sh" in result.stdout
    assert "hard-stop" in result.stdout.lower() or "hard_stop" in result.stdout.lower()


def test_schedule_json_parses() -> None:
    assert SCHEDULE_JSON.is_file(), f"missing {SCHEDULE_JSON}"
    d = json.loads(SCHEDULE_JSON.read_text(encoding="utf-8"))
    rule = d["rule"]
    assert rule["schedule_expression"] == "rate(1 hour)"
    # Must be DISABLED by default — operator flips on after first dry-run validation.
    assert rule["state"] == "DISABLED"
    env = d["lambda_runner"]["env"]
    assert env["JPCITE_BURN_HARD_STOP_USD"] == "18900"
    assert env["JPCITE_BURN_SLOWDOWN_USD"] == "16065"
    assert int(env["JPCITE_SM_COOLDOWN_SEC"]) >= 600
    assert int(env["JPCITE_GPU_COOLDOWN_SEC"]) >= 1800


def test_halt_sentinel_short_circuits(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "HALTED").write_text("halted by test", encoding="utf-8")
    env = os.environ.copy()
    env["AWS_PROFILE"] = "bookyou-recovery-NONEXISTENT"
    # If the script honored the sentinel correctly, it never touches AWS;
    # bogus profile must not matter.
    result = subprocess.run(
        ["bash", str(SCRIPT), "--state-dir", str(state_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    assert result.returncode == 0
    ledger = state_dir / "tick_ledger.jsonl"
    assert ledger.is_file()
    row = json.loads(ledger.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["decision"] == "halted"


def test_script_no_llm_imports() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("anthropic", "openai", "claude_agent_sdk"):
        assert forbidden not in text.lower(), (
            f"continuous_burn_monitor.sh must not reference {forbidden!r}"
        )
