"""Emergency kill-switch scripts: existence + executable + token gate + DRY_RUN.

Stream I/E hardening (Wave 50, 2026-05-16). Three shell scripts materialize
the one-command panic-button surface that operators hit during the live
AWS canary phase:

* ``scripts/teardown/00_emergency_stop.sh`` — terminate every AWS Batch /
  ECS / Bedrock / OpenSearch / EC2 surface + lock every S3 bucket.
* ``scripts/ops/cf_pages_emergency_rollback.sh`` — rewrite
  ``site/releases/current/runtime_pointer.json`` to the previous capsule,
  purge CF cache, sleep 60s for propagation, probe healthz.
* ``scripts/ops/emergency_kill_switch.sh`` — common entry that selects
  ``aws`` / ``cf`` / ``both`` and runs both children in parallel.

Tests assert:

1. existence + chmod +x + canonical bash shebang,
2. ``DRY_RUN="${DRY_RUN:-true}"`` safe-by-default invariant,
3. ``JPCITE_EMERGENCY_TOKEN`` two-stage gate (live mode without token
   exits 64 BEFORE any side effect),
4. ``bash -n`` syntax check passes (no parse errors),
5. ``DRY_RUN=true`` invocation produces zero live AWS / CF API calls.

The token-gate + DRY_RUN tests do NOT need network, AWS creds, or CF
creds — they exercise the gate logic and dry-run echo path only.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EMERGENCY_SCRIPTS: tuple[tuple[str, Path], ...] = (
    (
        "aws_stop",
        REPO_ROOT / "scripts" / "teardown" / "00_emergency_stop.sh",
    ),
    (
        "cf_rollback",
        REPO_ROOT / "scripts" / "ops" / "cf_pages_emergency_rollback.sh",
    ),
    (
        "entry_point",
        REPO_ROOT / "scripts" / "ops" / "emergency_kill_switch.sh",
    ),
)

REQUIRED_SHEBANG = "#!/usr/bin/env bash"
DRY_RUN_DEFAULT_TOKEN = 'DRY_RUN="${DRY_RUN:-true}"'
TOKEN_ENV_VAR = "JPCITE_EMERGENCY_TOKEN"


# ---------------------------------------------------------------------------
# 1. Existence + executable + shebang
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "path"), EMERGENCY_SCRIPTS)
def test_emergency_script_exists(label: str, path: Path) -> None:
    """Every emergency script must exist as a regular file."""
    assert path.is_file(), (
        f"emergency script missing: {path} ({label}). Re-run Stream I/E materialization."
    )


@pytest.mark.parametrize(("label", "path"), EMERGENCY_SCRIPTS)
def test_emergency_script_executable(label: str, path: Path) -> None:
    """Every emergency script must carry the user-executable bit."""
    mode = path.stat().st_mode
    assert mode & 0o100, (
        f"emergency script not executable: {path} ({label}, mode={oct(mode)}). "
        f"Run `chmod +x {path}`."
    )


@pytest.mark.parametrize(("label", "path"), EMERGENCY_SCRIPTS)
def test_emergency_script_shebang(label: str, path: Path) -> None:
    """First line must be canonical ``#!/usr/bin/env bash``."""
    with path.open("r", encoding="utf-8") as fp:
        first_line = fp.readline().rstrip("\n")
    assert first_line == REQUIRED_SHEBANG, (
        f"{path} ({label}) shebang={first_line!r}, expected {REQUIRED_SHEBANG!r}."
    )


# ---------------------------------------------------------------------------
# 2. DRY_RUN=true safe-by-default invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "path"), EMERGENCY_SCRIPTS)
def test_emergency_script_dry_run_default(label: str, path: Path) -> None:
    """Each script must default DRY_RUN=true. Live execution must be opt-in."""
    body = path.read_text(encoding="utf-8")
    assert DRY_RUN_DEFAULT_TOKEN in body, (
        f"{path} ({label}) missing `{DRY_RUN_DEFAULT_TOKEN}` default. "
        f"Live mutation must be opt-in via DRY_RUN=false + {TOKEN_ENV_VAR}."
    )


# ---------------------------------------------------------------------------
# 3. Token gate referenced in body (defense-in-depth — actual behaviour
#    tested separately below).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "path"), EMERGENCY_SCRIPTS)
def test_emergency_script_token_var_referenced(label: str, path: Path) -> None:
    """Each script must reference ``JPCITE_EMERGENCY_TOKEN`` (the two-stage gate)."""
    body = path.read_text(encoding="utf-8")
    assert TOKEN_ENV_VAR in body, (
        f"{path} ({label}) does not reference {TOKEN_ENV_VAR}. "
        f"Two-stage gate is the contractual safety lever."
    )


# ---------------------------------------------------------------------------
# 4. bash -n syntax check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "path"), EMERGENCY_SCRIPTS)
def test_emergency_script_bash_syntax_check(label: str, path: Path) -> None:
    """``bash -n <script>`` must succeed (no parse errors)."""
    result = subprocess.run(
        ["bash", "-n", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"{path} ({label}) failed bash -n syntax check:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# 5. Token gate behaviour: DRY_RUN=false without token => exit 64 BEFORE
#    any side effect. We override ATTESTATION_DIR to a tmp location so the
#    test does not write into the repo's site/releases/ tree.
# ---------------------------------------------------------------------------


def _run_script(
    path: Path, env: dict[str, str], *, args: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run an emergency script with a controlled env + capture output."""
    full_env = dict(os.environ)
    full_env.update(env)
    return subprocess.run(
        ["bash", str(path), *(args or [])],
        capture_output=True,
        text=True,
        check=False,
        env=full_env,
    )


@pytest.mark.parametrize(
    ("label", "path", "args"),
    [
        ("aws_stop", REPO_ROOT / "scripts" / "teardown" / "00_emergency_stop.sh", []),
        (
            "cf_rollback",
            REPO_ROOT / "scripts" / "ops" / "cf_pages_emergency_rollback.sh",
            ["fake-prev-capsule-2026-05-16"],
        ),
        (
            "entry_point",
            REPO_ROOT / "scripts" / "ops" / "emergency_kill_switch.sh",
            ["aws"],
        ),
    ],
)
def test_emergency_script_live_without_token_exits_64(
    tmp_path: Path,
    label: str,
    path: Path,
    args: list[str],
) -> None:
    """DRY_RUN=false without JPCITE_EMERGENCY_TOKEN must exit 64 BEFORE any AWS call.

    We additionally unset CF_API_TOKEN / CF_ZONE_ID so the CF rollback
    script does not attempt a cache-purge call before the gate is hit.
    """
    attestation_dir = tmp_path / "attestation"
    env = {
        "DRY_RUN": "false",
        "ATTESTATION_DIR": str(attestation_dir),
        "JPCITE_EMERGENCY_TOKEN": "",
        # Make sure no inherited token from the dev shell leaks in.
        "CF_API_TOKEN": "",
        "CF_ZONE_ID": "",
    }
    result = _run_script(path, env, args=args)
    assert result.returncode == 64, (
        f"{path} ({label}) live-without-token exit={result.returncode}, "
        f"expected 64 (gate). stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # No AWS calls should have been executed. We assert by looking at the
    # attestation log: the only lines should be the ABORT messages.
    log_path = attestation_dir / f"{_step_label(path)}.log"
    if log_path.exists():
        log_body = log_path.read_text(encoding="utf-8")
        assert "EXEC aws " not in log_body, (
            f"{label} attempted aws EXEC before token gate: {log_body!r}"
        )


# ---------------------------------------------------------------------------
# 6. DRY_RUN=true default invocation: zero live AWS / CF calls.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "path", "args"),
    [
        ("aws_stop", REPO_ROOT / "scripts" / "teardown" / "00_emergency_stop.sh", []),
        (
            "cf_rollback",
            REPO_ROOT / "scripts" / "ops" / "cf_pages_emergency_rollback.sh",
            ["fake-prev-capsule-2026-05-16"],
        ),
        (
            "entry_point",
            REPO_ROOT / "scripts" / "ops" / "emergency_kill_switch.sh",
            ["aws"],
        ),
    ],
)
def test_emergency_script_dry_run_clean_exit(
    tmp_path: Path,
    label: str,
    path: Path,
    args: list[str],
) -> None:
    """DRY_RUN=true default produces a clean exit + only DRY_RUN-prefixed echoes."""
    attestation_dir = tmp_path / "attestation"
    env = {
        "DRY_RUN": "true",
        "ATTESTATION_DIR": str(attestation_dir),
        # Token should be irrelevant in dry-run.
        "JPCITE_EMERGENCY_TOKEN": "",
        "CF_API_TOKEN": "",
        "CF_ZONE_ID": "",
    }
    result = _run_script(path, env, args=args)
    assert result.returncode == 0, (
        f"{path} ({label}) DRY_RUN=true exit={result.returncode}. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    log_path = attestation_dir / f"{_step_label(path)}.log"
    assert log_path.exists(), f"attestation log missing for {label}: {log_path}"
    log_body = log_path.read_text(encoding="utf-8")
    # No EXEC aws / EXEC curl lines may appear in dry-run.
    assert "EXEC aws " not in log_body, f"{label} attempted EXEC aws in DRY_RUN=true: {log_body!r}"
    assert "EXEC purge_everything" not in log_body, (
        f"{label} attempted EXEC purge_everything in DRY_RUN=true: {log_body!r}"
    )


# ---------------------------------------------------------------------------
# 7. WARNING banner present (operator-facing safety doc)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "path"), EMERGENCY_SCRIPTS)
def test_emergency_script_warning_banner_present(label: str, path: Path) -> None:
    """Each script must carry a ``WARNING`` comment block + token doc."""
    body = path.read_text(encoding="utf-8")
    assert "WARNING" in body, (
        f"{path} ({label}) missing WARNING banner; operators need a visible "
        f"safety call-out at the top of the file."
    )
    # The token usage doc must be present so an operator who shells in
    # cold can understand the gate without reading the test suite.
    assert "JPCITE_EMERGENCY_TOKEN" in body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step_label(path: Path) -> str:
    """Return the STEP variable each script writes its attestation under."""
    stem = path.stem  # filename without extension
    # 00_emergency_stop.sh -> 00_emergency_stop
    # cf_pages_emergency_rollback.sh -> cf_pages_emergency_rollback
    # emergency_kill_switch.sh -> emergency_kill_switch
    return stem


# ---------------------------------------------------------------------------
# 8. Entry-point routing: usage-check rejects bad MODE
# ---------------------------------------------------------------------------


def test_entry_point_rejects_invalid_mode(tmp_path: Path) -> None:
    """``emergency_kill_switch.sh frobnicate`` must exit non-zero and emit usage."""
    path = REPO_ROOT / "scripts" / "ops" / "emergency_kill_switch.sh"
    attestation_dir = tmp_path / "attestation"
    env = {
        "DRY_RUN": "true",
        "ATTESTATION_DIR": str(attestation_dir),
        "JPCITE_EMERGENCY_TOKEN": "",
    }
    result = _run_script(path, env, args=["frobnicate"])
    assert result.returncode != 0, (
        f"entry-point accepted invalid mode 'frobnicate' "
        f"(exit={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r})"
    )
    # usage banner should reference the three valid modes.
    combined = (result.stderr or "") + (result.stdout or "")
    assert "aws" in combined and "cf" in combined and "both" in combined, (
        f"usage banner did not enumerate aws/cf/both: {combined!r}"
    )


def test_entry_point_missing_mode_exits_nonzero(tmp_path: Path) -> None:
    """No mode arg => usage + non-zero exit (operator typo guardrail)."""
    path = REPO_ROOT / "scripts" / "ops" / "emergency_kill_switch.sh"
    attestation_dir = tmp_path / "attestation"
    env = {
        "DRY_RUN": "true",
        "ATTESTATION_DIR": str(attestation_dir),
        "JPCITE_EMERGENCY_TOKEN": "",
    }
    result = _run_script(path, env, args=[])
    assert result.returncode != 0, f"entry-point accepted empty mode (exit={result.returncode})"


if __name__ == "__main__":  # pragma: no cover - manual run convenience
    sys.exit(pytest.main([__file__, "-v"]))
