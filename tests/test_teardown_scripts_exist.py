"""Stream E teardown scripts: existence + executable bit + shebang line.

Asserts that the six shell scripts that materialize the Stream E AWS teardown
flow are present, executable, start with a `#!/usr/bin/env bash` shebang, and
honor the DRY_RUN-by-default contract. These properties matter because:

* Existence: the launch-gate review checks `scripts/teardown/*.sh` exists
  before flipping the live-execution token. A missing script silently skips
  a teardown step and leaves residual AWS resources billing.
* Executable bit: orchestrator `run_all.sh` invokes each child via `bash`,
  but downstream operator playbooks (and the verify gate) shell out via
  `./scripts/teardown/05_teardown_attestation.sh`, which requires `chmod +x`.
* Shebang: pre-commit shell-lint hooks require the canonical
  `#!/usr/bin/env bash` form; `#!/bin/bash` is rejected on macOS where the
  system bash is 3.x.
* DRY_RUN default: per noop_aws_command_plan.json
  (`live_aws_commands_allowed: false`), every step must be safe to run in
  CI without an AWS profile. `DRY_RUN="${DRY_RUN:-true}"` enforces that.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEARDOWN_DIR = REPO_ROOT / "scripts" / "teardown"

EXPECTED_SCRIPTS: tuple[str, ...] = (
    # Wave 50 Stream I/E emergency kill switch — fires alongside the
    # planned 01..05 sequence, but with a SEPARATE token (JPCITE_EMERGENCY_TOKEN)
    # so a leaked planned-teardown credential cannot also panic-stop AWS.
    "00_emergency_stop.sh",
    "01_identity_budget_inventory.sh",
    "02_artifact_lake_export.sh",
    "03_batch_playwright_drain.sh",
    "04_bedrock_ocr_stop.sh",
    "05_teardown_attestation.sh",
    "run_all.sh",
    "verify_zero_aws.sh",
)

REQUIRED_SHEBANG = "#!/usr/bin/env bash"
DRY_RUN_DEFAULT_TOKEN = 'DRY_RUN="${DRY_RUN:-true}"'


@pytest.mark.parametrize("script_name", EXPECTED_SCRIPTS)
def test_teardown_script_exists(script_name: str) -> None:
    """Every named script must exist as a regular file."""
    script_path = TEARDOWN_DIR / script_name
    assert script_path.is_file(), (
        f"Stream E teardown script missing: {script_path}. "
        f"Re-run scripts/teardown/ materialization."
    )


@pytest.mark.parametrize("script_name", EXPECTED_SCRIPTS)
def test_teardown_script_executable(script_name: str) -> None:
    """Every named script must carry the user-executable bit (chmod +x)."""
    script_path = TEARDOWN_DIR / script_name
    mode = script_path.stat().st_mode
    assert mode & 0o100, (
        f"Stream E teardown script not executable: {script_path} "
        f"(mode={oct(mode)}). Run `chmod +x {script_path}`."
    )


@pytest.mark.parametrize("script_name", EXPECTED_SCRIPTS)
def test_teardown_script_shebang(script_name: str) -> None:
    """First line must be the canonical `#!/usr/bin/env bash` shebang."""
    script_path = TEARDOWN_DIR / script_name
    with script_path.open("r", encoding="utf-8") as fp:
        first_line = fp.readline().rstrip("\n")
    assert first_line == REQUIRED_SHEBANG, (
        f"Stream E teardown script {script_path} has shebang {first_line!r}; "
        f"expected {REQUIRED_SHEBANG!r}. Pre-commit shell-lint hooks reject "
        f"non-canonical shebangs (macOS bash 3.x trap)."
    )


@pytest.mark.parametrize(
    "script_name",
    tuple(s for s in EXPECTED_SCRIPTS if s != "run_all.sh"),
)
def test_teardown_script_dry_run_default(script_name: str) -> None:
    """Per-step scripts must default DRY_RUN=true (safe-by-default contract).

    `run_all.sh` is excluded because it propagates DRY_RUN to the children;
    enforcement at the leaf level is what guarantees no AWS mutation when
    the orchestrator is bypassed.
    """
    script_path = TEARDOWN_DIR / script_name
    body = script_path.read_text(encoding="utf-8")
    assert DRY_RUN_DEFAULT_TOKEN in body, (
        f"Stream E teardown script {script_path} is missing the "
        f"`{DRY_RUN_DEFAULT_TOKEN}` default. Live AWS execution must be "
        f"opt-in via DRY_RUN=false + JPCITE_TEARDOWN_LIVE_TOKEN, never the "
        f"unconfigured default."
    )


def test_teardown_directory_present() -> None:
    """The materialized teardown directory must exist."""
    assert TEARDOWN_DIR.is_dir(), (
        f"scripts/teardown/ is missing at {TEARDOWN_DIR}. Re-run Stream E materialization."
    )


def test_teardown_directory_contents_match_expected() -> None:
    """No stray scripts in scripts/teardown/ — surface drift fast."""
    on_disk = {p.name for p in TEARDOWN_DIR.iterdir() if p.is_file() and p.suffix == ".sh"}
    expected = set(EXPECTED_SCRIPTS)
    extras = on_disk - expected
    missing = expected - on_disk
    assert not extras, f"Unexpected scripts/teardown/*.sh files: {sorted(extras)}"
    assert not missing, f"Missing scripts/teardown/*.sh files: {sorted(missing)}"


def test_teardown_directory_under_repo_root() -> None:
    """Defensive: ensure REPO_ROOT detection didn't escape the repo."""
    assert TEARDOWN_DIR.is_relative_to(REPO_ROOT), (
        f"Teardown dir resolution leaked: {TEARDOWN_DIR} not under "
        f"{REPO_ROOT}. Check tests/__file__ resolution."
    )
    # Sanity: scripts/teardown is shallow, never crossing a symlink boundary.
    assert os.path.realpath(TEARDOWN_DIR).startswith(os.path.realpath(REPO_ROOT)), (
        f"Teardown dir realpath escaped repo: {TEARDOWN_DIR}"
    )
