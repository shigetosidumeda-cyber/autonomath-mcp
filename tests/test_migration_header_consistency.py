"""CI gate: every migration listed in autonomath_boot_manifest.txt must have
``-- target_db: autonomath`` as its first line.

Background — E10 audit finding (2026-05-13):
    Migration ``269_create_jpcite_views.sql`` shipped with a non-conforming
    first line (``-- 269_create_jpcite_views.sql`` instead of the
    ``-- target_db: autonomath`` marker). The entrypoint.sh §4 self-heal
    loop checks the FIRST line of every candidate migration with
    ``head -1 "$am_mig" | grep -q "target_db: autonomath"`` and silently
    skips files that fail that gate, even when they are otherwise listed
    in the boot manifest. The result was a manifest entry that was forced
    to stay commented out because the gate would have skipped it anyway.

This test pins both halves of the contract:
  1. Every uncommented entry in ``autonomath_boot_manifest.txt`` exists on
     disk.
  2. The very first line of that file matches the entrypoint gate
     (``-- target_db: autonomath``, with the marker on line 1 verbatim).
  3. Migration 269 specifically is uncommented, present, and conformant
     (regression marker for the E10 finding itself).

The test must remain LLM-0 by construction: no Anthropic / OpenAI SDK
imports, no Claude Agent SDK. Pure stdlib + pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "scripts" / "migrations"
MANIFEST = MIGRATIONS_DIR / "autonomath_boot_manifest.txt"

# Marker the entrypoint.sh §4 gate scans for on the FIRST line.
REQUIRED_FIRST_LINE_SUBSTRING = "target_db: autonomath"

# Regression marker for the E10 finding.
E10_MIGRATION = "269_create_jpcite_views.sql"


def _manifest_entries() -> list[str]:
    """Return the list of uncommented filenames in the boot manifest.

    Mirrors the exact ``grep -Ev '^[[:space:]]*(#|$)'`` filter that
    entrypoint.sh uses in ``am_mig_in_manifest()``.
    """
    assert MANIFEST.exists(), f"missing boot manifest: {MANIFEST}"
    entries: list[str] = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        entries.append(stripped)
    return entries


def test_manifest_file_exists() -> None:
    assert MANIFEST.exists(), MANIFEST


def test_manifest_has_at_least_one_entry() -> None:
    entries = _manifest_entries()
    assert entries, "boot manifest has zero uncommented entries — schema_guard would skip every autonomath migration on boot"


@pytest.mark.parametrize("entry", _manifest_entries())
def test_manifest_entry_file_exists(entry: str) -> None:
    """Every uncommented manifest entry must resolve to a file on disk."""
    path = MIGRATIONS_DIR / entry
    assert path.exists(), (
        f"boot manifest references missing file: {entry} (expected at {path})"
    )


@pytest.mark.parametrize("entry", _manifest_entries())
def test_manifest_entry_has_target_db_autonomath_first_line(entry: str) -> None:
    """Every manifest entry's FIRST line must contain ``target_db: autonomath``.

    This is the exact gate ``entrypoint.sh §4`` enforces:

        head -1 "$am_mig" | grep -q "target_db: autonomath"

    A file that fails this gate is silently skipped by the self-heal
    loop even when it is listed in the manifest — which is the bug
    pattern E10 caught for migration 269.
    """
    path = MIGRATIONS_DIR / entry
    if not path.exists():
        pytest.skip(f"missing file (covered by separate test): {entry}")
    with path.open(encoding="utf-8") as fh:
        first_line = fh.readline().rstrip("\r\n")
    assert REQUIRED_FIRST_LINE_SUBSTRING in first_line, (
        f"{entry}: first line must contain '{REQUIRED_FIRST_LINE_SUBSTRING}' "
        f"(entrypoint.sh §4 head -1 grep gate); got: {first_line!r}"
    )


def test_e10_migration_269_uncommented_in_manifest() -> None:
    """Regression marker: 269_create_jpcite_views.sql must be an active
    (uncommented) manifest entry.

    A commented-out entry (``# 269_create_jpcite_views.sql``) is treated
    by entrypoint.sh as absent — the migration would never auto-apply
    on boot, and schema_guard would fail at deploy time.
    """
    entries = _manifest_entries()
    assert E10_MIGRATION in entries, (
        f"{E10_MIGRATION} must appear uncommented in {MANIFEST.name} "
        f"(was the entry left as `# {E10_MIGRATION}`?). Current entries: {entries}"
    )


def test_e10_migration_269_first_line_is_target_db_autonomath() -> None:
    """Regression marker: 269 SQL must have target_db marker on line 1."""
    path = MIGRATIONS_DIR / E10_MIGRATION
    assert path.exists(), path
    with path.open(encoding="utf-8") as fh:
        first_line = fh.readline().rstrip("\r\n")
    assert first_line == "-- target_db: autonomath", (
        f"{E10_MIGRATION}: first line must be exactly "
        f"'-- target_db: autonomath' (entrypoint.sh §4 head -1 grep gate); "
        f"got: {first_line!r}"
    )


def test_manifest_does_not_list_rollback_companions() -> None:
    """Rollback files are excluded by entrypoint.sh case glob
    (``*_rollback.sql``); listing them in the manifest would be a
    confusing no-op and should be flagged."""
    for entry in _manifest_entries():
        assert not entry.endswith("_rollback.sql"), (
            f"manifest must not list rollback companion: {entry} "
            f"(entrypoint.sh skips *_rollback.sql via case glob)"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
