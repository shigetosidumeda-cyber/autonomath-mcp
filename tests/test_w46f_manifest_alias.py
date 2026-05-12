"""Wave 46 task 46.F regression test.

Verifies the destruction-free rename of
``scripts/migrations/autonomath_boot_manifest.txt`` into the dual-named pair

* ``scripts/migrations/autonomath_boot_manifest.txt`` (legacy, still present)
* ``scripts/migrations/jpcite_boot_manifest.txt``    (alias, byte-identical)

and the corresponding dual-read fallback inserted into ``entrypoint.sh``.

Goals:

1. Both manifest files exist and are byte-identical (hash + diff).
2. ``entrypoint.sh`` defines ``am_mig_manifest`` using a dual-candidate loop
   that prefers ``jpcite_boot_manifest.txt`` then ``autonomath_boot_manifest.txt``.
3. ``entrypoint.sh`` still respects the ``AUTONOMATH_BOOT_MIGRATION_MANIFEST``
   env override (back-compat guarantee for existing deploys).
4. ``entrypoint.sh`` survives ``bash -n`` syntax check after the patch.

This test is offline-only and never imports ``anthropic``/``openai`` (per the
``feedback_no_operator_llm_api`` repository rule).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"
AUTONOMATH_MANIFEST = MIGRATIONS_DIR / "autonomath_boot_manifest.txt"
JPCITE_MANIFEST = MIGRATIONS_DIR / "jpcite_boot_manifest.txt"
ENTRYPOINT = REPO_ROOT / "entrypoint.sh"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_both_manifests_exist() -> None:
    assert AUTONOMATH_MANIFEST.is_file(), (
        f"legacy manifest missing: {AUTONOMATH_MANIFEST}"
    )
    assert JPCITE_MANIFEST.is_file(), (
        f"jpcite alias manifest missing: {JPCITE_MANIFEST}"
    )


def test_manifests_are_byte_identical() -> None:
    """Hash + raw-bytes equality. The pair MUST be kept in lock-step."""
    a_hash = _sha256(AUTONOMATH_MANIFEST)
    j_hash = _sha256(JPCITE_MANIFEST)
    assert a_hash == j_hash, (
        f"manifest drift detected:\n"
        f"  {AUTONOMATH_MANIFEST.name}: {a_hash}\n"
        f"  {JPCITE_MANIFEST.name}: {j_hash}"
    )
    assert AUTONOMATH_MANIFEST.read_bytes() == JPCITE_MANIFEST.read_bytes()


def test_manifest_payload_nonempty() -> None:
    """The alias copy MUST inherit the live boot allowlist, not an empty stub."""
    payload_lines = [
        ln
        for ln in JPCITE_MANIFEST.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert payload_lines, (
        "jpcite_boot_manifest.txt has zero active migration entries — "
        "expected the same allowlist as autonomath_boot_manifest.txt"
    )


def test_entrypoint_dual_read_block_present() -> None:
    """The dual-candidate loop must be wired in entrypoint.sh."""
    src = ENTRYPOINT.read_text(encoding="utf-8")
    assert "jpcite_boot_manifest.txt" in src, (
        "entrypoint.sh does not reference jpcite_boot_manifest.txt"
    )
    assert "autonomath_boot_manifest.txt" in src, (
        "entrypoint.sh dropped the legacy autonomath_boot_manifest.txt fallback"
    )
    # The candidate loop must list jpcite FIRST (preferred) and autonomath
    # SECOND (fallback) — verify by raw substring order.
    jpcite_pos = src.find("jpcite_boot_manifest.txt")
    autonomath_pos = src.find("autonomath_boot_manifest.txt")
    assert jpcite_pos != -1 and autonomath_pos != -1
    assert jpcite_pos < autonomath_pos, (
        "entrypoint.sh must check jpcite_boot_manifest.txt BEFORE the legacy "
        "autonomath_boot_manifest.txt so the new brand name wins on disk"
    )
    # Loop hallmarks must be present.
    assert "am_mig_manifest_candidate" in src, (
        "expected for-loop variable am_mig_manifest_candidate in entrypoint.sh"
    )


def test_entrypoint_env_override_still_respected() -> None:
    """Explicit AUTONOMATH_BOOT_MIGRATION_MANIFEST must still win over autodetect."""
    src = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'AUTONOMATH_BOOT_MIGRATION_MANIFEST' in src
    # The override branch must be evaluated BEFORE the dual-candidate loop.
    override_pos = src.find('AUTONOMATH_BOOT_MIGRATION_MANIFEST:-')
    loop_pos = src.find("am_mig_manifest_candidate")
    assert override_pos != -1, "explicit env override branch dropped"
    assert loop_pos != -1, "dual-candidate loop missing"
    assert override_pos < loop_pos, (
        "AUTONOMATH_BOOT_MIGRATION_MANIFEST env override must short-circuit the "
        "dual-candidate loop"
    )


@pytest.mark.skipif(
    shutil.which("bash") is None,
    reason="bash not available on this runner",
)
def test_entrypoint_bash_syntax_ok() -> None:
    """`bash -n entrypoint.sh` must succeed after the 46.F patch."""
    result = subprocess.run(
        ["bash", "-n", str(ENTRYPOINT)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"bash -n entrypoint.sh failed (rc={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
