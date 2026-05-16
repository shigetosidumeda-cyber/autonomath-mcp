"""Wave 49 tick#1 hot-fix — boot manifest gate for migration 288.

PR #189 (feat(wave49/dim-n): k=10 strict view + 7-pattern PII redact)
landed `scripts/migrations/288_dim_n_k10_strict.sql` into main as
commit ``e59486eb9443e2f3e7e40ce0d913456c5b218158`` but did NOT add the
288 filename to the preferred ``scripts/migrations/jpcite_boot_manifest.txt``.
``entrypoint.sh`` defaults to ``AUTONOMATH_BOOT_MIGRATION_MODE=manifest``
and only applies filenames listed in that allowlist — so a missing entry
means the k=10 strict view is silently skipped on every prod boot,
blocking the Dim N hardening surface from going LIVE.

This test guards the manifest entry permanently:

  * the migration SQL file MUST exist on disk;
  * the manifest text MUST list ``288_dim_n_k10_strict.sql`` exactly once
    on its own line in the preferred jpcite manifest (no commented-out
    duplicate);
  * the manifest MUST still list the migration 274 substrate
    (``274_anonymized_query.sql``) so the k=5 view from
    ``feedback_anonymized_query_pii_redact`` is preserved
    (destruction-free: k=5 floor cannot be lowered at runtime).

Per ``feedback_destruction_free_organization`` the test is append-only:
it only asserts presence, never re-orders or rewrites the manifest.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PREFERRED_MANIFEST = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MIG_288 = REPO_ROOT / "scripts" / "migrations" / "288_dim_n_k10_strict.sql"
MIG_274 = REPO_ROOT / "scripts" / "migrations" / "274_anonymized_query.sql"

ENTRY_288 = "288_dim_n_k10_strict.sql"
ENTRY_274 = "274_anonymized_query.sql"


def _active_entries(text: str) -> list[str]:
    """Return non-comment, non-blank manifest lines (the active allowlist)."""
    return [
        stripped
        for line in text.splitlines()
        if (stripped := line.strip()) and not stripped.startswith("#")
    ]


def test_mig288_sql_file_exists() -> None:
    """SQL file landed via PR #189 must remain on disk."""
    assert MIG_288.is_file(), f"missing migration SQL: {MIG_288}"


def test_mig288_listed_in_boot_manifest() -> None:
    """288 filename must appear exactly once in the active allowlist."""
    assert PREFERRED_MANIFEST.is_file(), f"missing manifest file: {PREFERRED_MANIFEST}"
    entries = _active_entries(PREFERRED_MANIFEST.read_text(encoding="utf-8"))
    occurrences = entries.count(ENTRY_288)
    assert occurrences == 1, (
        f"expected exactly 1 active manifest entry for {ENTRY_288}; "
        f"found {occurrences} in {PREFERRED_MANIFEST}"
    )


def test_mig274_substrate_preserved() -> None:
    """k=5 substrate from mig 274 must remain (destruction-free)."""
    assert MIG_274.is_file(), f"missing prerequisite migration: {MIG_274}"
    entries = _active_entries(PREFERRED_MANIFEST.read_text(encoding="utf-8"))
    assert ENTRY_274 in entries, (
        f"manifest must continue to list {ENTRY_274} alongside {ENTRY_288} "
        f"(k=5 floor preserved alongside k=10 strict)"
    )
