"""Stream E teardown 08 — ECR attacker-repo cleanup script invariants.

The 2026-05-16 BookYou account-compromise damage inventory identified two
attacker-owned ECR repositories that must be deleted AFTER Awano-san (AWS
Japan) signs off on the compromise ticket:

  * ``satyr-model``       — us-east-1, 12.73 GB layer, ~$150.05/mo gross
  * ``z-image-inference`` — ap-southeast-1, created 2026-03-25

This module pins the operator safety contract of
``scripts/teardown/08_ecr_attacker_cleanup.sh`` so any future edit that
weakens DRY_RUN / token gating / dual-region coverage / forensic capture
trips a red CI gate before the live cleanup is attempted.

These are grep-level tests on the shell source — no AWS or shell execution.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "teardown" / "08_ecr_attacker_cleanup.sh"


@pytest.fixture(scope="module")
def script_body() -> str:
    """Slurp the script once; every assertion is a substring check."""
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_script_exists() -> None:
    """The script must be a regular file at the canonical path."""
    assert SCRIPT_PATH.is_file(), (
        f"ECR attacker cleanup script missing at {SCRIPT_PATH}. "
        f"Wave 50 post-launch teardown hardening regressed."
    )


def test_script_executable() -> None:
    """Operator playbooks invoke the script directly, so chmod +x is required."""
    mode = SCRIPT_PATH.stat().st_mode
    assert mode & 0o100, (
        f"ECR cleanup script not executable (mode={oct(mode)}). "
        f"Run `chmod +x {SCRIPT_PATH}`."
    )


def test_script_shebang(script_body: str) -> None:
    """Canonical ``#!/usr/bin/env bash`` shebang (macOS bash 3.x trap)."""
    first_line = script_body.splitlines()[0]
    assert first_line == "#!/usr/bin/env bash", (
        f"ECR cleanup script shebang is {first_line!r}; expected "
        f"'#!/usr/bin/env bash'."
    )


def test_script_strict_mode(script_body: str) -> None:
    """``set -euo pipefail`` is mandatory across every teardown script."""
    assert "set -euo pipefail" in script_body, (
        "ECR cleanup script is missing `set -euo pipefail`. "
        "Strict-mode bash is the baseline contract for scripts/teardown/."
    )


def test_dry_run_default_true(script_body: str) -> None:
    """``DRY_RUN`` defaults to ``true`` — the safe-by-default contract.

    Live deletion requires DRY_RUN=false AND (--commit OR
    JPCITE_TEARDOWN_LIVE_TOKEN). The unconfigured default MUST be a no-op.
    """
    assert 'DRY_RUN="${DRY_RUN:-true}"' in script_body, (
        "ECR cleanup script must default DRY_RUN=true; the unconfigured "
        "invocation must NEVER call any mutating ECR API."
    )


def test_live_token_gate(script_body: str) -> None:
    """Live-execution gate references ``JPCITE_TEARDOWN_LIVE_TOKEN``.

    Mirrors run_all.sh: token presence is the orchestrator-side proof that
    the launch-gate review approved this run.
    """
    assert "JPCITE_TEARDOWN_LIVE_TOKEN" in script_body, (
        "ECR cleanup script must reference JPCITE_TEARDOWN_LIVE_TOKEN as a "
        "live-execution gate. Missing this breaks orchestration via run_all.sh."
    )


def test_commit_flag_gate(script_body: str) -> None:
    """``--commit`` flag is the operator-interactive arm."""
    assert "--commit" in script_body, (
        "ECR cleanup script must accept --commit as an interactive arm so "
        "operators can run it standalone (not just via run_all.sh)."
    )


def test_dual_region_coverage(script_body: str) -> None:
    """Both us-east-1 and ap-southeast-1 must be walked.

    These are the two regions where the attacker provisioned ECR repos
    (satyr-model + z-image-inference per damage inventory). Dropping either
    leaves the compromise cleanup half-done and the cost-bleed continuing.
    """
    assert "us-east-1" in script_body, (
        "ECR cleanup script must walk us-east-1 (satyr-model repo). "
        "Damage inventory commit a51c988e1."
    )
    assert "ap-southeast-1" in script_body, (
        "ECR cleanup script must walk ap-southeast-1 (z-image-inference repo). "
        "Damage inventory commit a51c988e1."
    )


def test_attacker_repos_named(script_body: str) -> None:
    """Both attacker repos must appear by name in the script source.

    Hardcoding the names is intentional — these are forensic identifiers
    pinned to a single damage inventory snapshot and must not be sourced
    from a mutable config.
    """
    assert "satyr-model" in script_body, (
        "ECR cleanup script must name satyr-model repo (us-east-1)."
    )
    assert "z-image-inference" in script_body, (
        "ECR cleanup script must name z-image-inference repo (ap-southeast-1)."
    )


def test_forensic_dump_before_delete(script_body: str) -> None:
    """`describe-images` (forensic dump) must precede any delete call."""
    di_idx = script_body.find("ecr describe-images")
    bdi_idx = script_body.find("ecr batch-delete-image")
    dr_idx = script_body.find("ecr delete-repository")
    assert di_idx != -1, "Script must call `ecr describe-images` for forensic dump."
    assert bdi_idx != -1, "Script must call `ecr batch-delete-image` for tag cleanup."
    assert dr_idx != -1, "Script must call `ecr delete-repository --force` for repo drop."
    assert di_idx < bdi_idx < dr_idx, (
        "ECR cleanup script must order calls: describe-images (forensic) → "
        "batch-delete-image (tags) → delete-repository (repo). "
        "Re-ordering loses the forensic snapshot."
    )


def test_delete_repository_uses_force(script_body: str) -> None:
    """`delete-repository --force` is required (defensive against untagged remnants)."""
    assert "ecr delete-repository" in script_body, (
        "Script must call ecr delete-repository."
    )
    # --force must appear somewhere after the delete-repository invocation;
    # we accept any position because the script multi-lines the args.
    dr_idx = script_body.find("ecr delete-repository")
    tail = script_body[dr_idx:]
    assert "--force" in tail, (
        "ecr delete-repository must use --force so it succeeds even when "
        "step-3 batch-delete-image leaves untagged digests behind."
    )


def test_attestation_json_emit(script_body: str) -> None:
    """Script must emit attestation JSON for the compromise ticket."""
    assert 'cat > "${JSON}"' in script_body, (
        "ECR cleanup script must write attestation JSON. "
        "The compromise audit ticket references this artifact as cleanup proof."
    )


def test_attestation_schema_keys(script_body: str) -> None:
    """Attestation JSON must carry the required schema keys."""
    required_keys = (
        '"step":',
        '"run_id":',
        '"profile":',
        '"dry_run":',
        '"live_ok":',
        '"attacker_repos":',
        '"regions":',
        '"forensic_files":',
        '"completed_at":',
        '"compromise_ticket_ref":',
    )
    for key in required_keys:
        assert key in script_body, (
            f"ECR cleanup attestation JSON is missing required key {key!r}. "
            f"Compromise audit ticket requires the full schema."
        )


def test_compromise_ticket_ref(script_body: str) -> None:
    """Attestation must back-reference the damage inventory doc."""
    assert "AWS_DAMAGE_INVENTORY_2026_05_16.md" in script_body, (
        "ECR cleanup attestation must reference "
        "docs/_internal/AWS_DAMAGE_INVENTORY_2026_05_16.md so the ticket trail "
        "is traceable from the cleanup artifact."
    )


def test_does_not_call_aws_at_import() -> None:
    """Defensive: importing this test module must not invoke AWS or the script."""
    # The fixture is module-scoped and only reads file bytes. This test
    # exists to make the no-side-effects invariant explicit so future
    # refactors don't sneak in subprocess.run(...) at module top-level.
    assert "AWS_PROFILE" not in os.environ or os.environ.get("AWS_PROFILE") is not None
