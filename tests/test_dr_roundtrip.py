"""DR roundtrip tests: backup -> verify -> restore -> integrity_check.

Audit a37f6226fe319dc40 P1: runbook claims 30-min RTO but it was untested.
This suite exercises scripts/backup.py + scripts/restore.py end-to-end
against a fixture SQLite DB, asserting bit-identical row counts post-restore.

Network / R2 paths are NOT exercised — local filesystem only.
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup.py"
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore.py"


# Skip the entire module if either script is missing.
if not BACKUP_SCRIPT.is_file() or not RESTORE_SCRIPT.is_file():
    pytest.skip(
        f"DR scripts not present (backup={BACKUP_SCRIPT.is_file()}, "
        f"restore={RESTORE_SCRIPT.is_file()})",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_fixture_db(
    db_path: Path, *, n_programs: int = 40, n_keys: int = 20, n_events: int = 60
) -> dict[str, int]:
    """Build a small but realistic schema mirror with ~100 rows total."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                tier TEXT,
                prefecture TEXT,
                amount_max_man_yen INTEGER,
                updated_at TEXT
            );
            CREATE TABLE api_keys (
                key_id TEXT PRIMARY KEY,
                customer_id TEXT,
                tier TEXT,
                created_at TEXT
            );
            CREATE TABLE usage_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                key_id TEXT,
                endpoint TEXT,
                created_at TEXT
            );
            """
        )
        now = datetime.now(UTC).isoformat()
        for i in range(n_programs):
            tier = ["S", "A", "B", "C"][i % 4]
            conn.execute(
                "INSERT INTO programs VALUES (?,?,?,?,?,?)",
                (
                    f"UNI-fix-{i:04d}",
                    f"DR fixture program #{i}",
                    tier,
                    "東京都",
                    100 * (i + 1),
                    now,
                ),
            )
        for i in range(n_keys):
            conn.execute(
                "INSERT INTO api_keys VALUES (?,?,?,?)",
                (f"key_{i:04d}", f"cus_{i:04d}", "paid" if i % 3 == 0 else "free", now),
            )
        for i in range(n_events):
            conn.execute(
                "INSERT INTO usage_events(key_id, endpoint, created_at) VALUES (?,?,?)",
                (f"key_{i % n_keys:04d}", "/v1/programs/search", now),
            )
        conn.commit()
    finally:
        conn.close()
    return {"programs": n_programs, "api_keys": n_keys, "usage_events": n_events}


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, int]]:
    d = tmp_path_factory.mktemp("dr_src")
    db = d / "fixture.db"
    counts = _seed_fixture_db(db)
    return db, counts


@pytest.fixture(scope="module")
def backup_artifact(
    fixture_db: tuple[Path, dict[str, int]],
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, dict[str, int]]:
    """Run scripts/backup.py once for the module, return (gz_path, sha_path, counts)."""
    src_db, counts = fixture_db
    out_dir = tmp_path_factory.mktemp("dr_out")
    proc = subprocess.run(
        [
            sys.executable,
            str(BACKUP_SCRIPT),
            "--db",
            str(src_db),
            "--out",
            str(out_dir),
            "--keep",
            "0",
            "--gzip",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"backup.py failed: stderr={proc.stderr}\nstdout={proc.stdout}"

    artifact_line = proc.stdout.strip().splitlines()[-1]
    gz_path = Path(artifact_line)
    sha_path = gz_path.with_name(gz_path.name + ".sha256")
    return gz_path, sha_path, counts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_backup_produces_gz_and_sha256(
    backup_artifact: tuple[Path, Path, dict[str, int]],
) -> None:
    gz_path, sha_path, _ = backup_artifact
    assert gz_path.is_file(), f"gz artifact missing: {gz_path}"
    assert gz_path.suffix == ".gz", f"unexpected suffix: {gz_path.suffix}"
    assert sha_path.is_file(), f"sha256 sidecar missing: {sha_path}"
    assert gz_path.stat().st_size > 0
    assert sha_path.stat().st_size > 0


def test_sha256_sidecar_matches_artifact(
    backup_artifact: tuple[Path, Path, dict[str, int]],
) -> None:
    gz_path, sha_path, _ = backup_artifact
    expected = sha_path.read_text(encoding="utf-8").strip().split()[0]
    actual = _sha256_of(gz_path)
    assert expected == actual, f"sha256 mismatch: sidecar={expected} actual={actual}"


def test_decompress_yields_valid_sqlite(
    backup_artifact: tuple[Path, Path, dict[str, int]],
    tmp_path: Path,
) -> None:
    gz_path, _, _ = backup_artifact
    decompressed = tmp_path / "decompressed.db"
    with gzip.open(gz_path, "rb") as f_in, decompressed.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    # SQLite header magic
    with decompressed.open("rb") as f:
        magic = f.read(16)
    assert magic.startswith(b"SQLite format 3"), f"unexpected header: {magic!r}"


def test_restore_to_new_target_preserves_row_counts(
    backup_artifact: tuple[Path, Path, dict[str, int]],
    tmp_path: Path,
) -> None:
    gz_path, _, counts = backup_artifact
    target = tmp_path / "restored.db"
    proc = subprocess.run(
        [
            sys.executable,
            str(RESTORE_SCRIPT),
            str(gz_path),
            "--target",
            str(target),
            "--yes",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"restore.py failed: stderr={proc.stderr}\nstdout={proc.stdout}"
    assert target.is_file(), f"restored DB missing: {target}"

    conn = sqlite3.connect(str(target))
    try:
        for table, expected in counts.items():
            got = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert got == expected, f"{table}: expected {expected}, got {got}"
    finally:
        conn.close()


def test_restored_db_passes_integrity_check(
    backup_artifact: tuple[Path, Path, dict[str, int]],
    tmp_path: Path,
) -> None:
    gz_path, _, _ = backup_artifact
    target = tmp_path / "restored_integrity.db"
    proc = subprocess.run(
        [sys.executable, str(RESTORE_SCRIPT), str(gz_path), "--target", str(target), "--yes"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"restore failed: {proc.stderr}"

    conn = sqlite3.connect(str(target))
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    assert result is not None and result[0] == "ok", f"integrity_check: {result!r}"


def test_restore_refuses_corrupted_backup(
    backup_artifact: tuple[Path, Path, dict[str, int]],
    tmp_path: Path,
) -> None:
    """Truncate the gz by 1 byte: gzip CRC will fail or sha256 will mismatch.
    Either way restore.py must exit non-zero and not write the target."""
    gz_path, sha_path, _ = backup_artifact

    corrupt_dir = tmp_path / "corrupt"
    corrupt_dir.mkdir()
    corrupt_gz = corrupt_dir / gz_path.name
    corrupt_sha = corrupt_dir / sha_path.name

    # Copy the sha sidecar verbatim, but truncate the gz body by 1 byte.
    shutil.copy2(sha_path, corrupt_sha)
    data = gz_path.read_bytes()
    corrupt_gz.write_bytes(data[:-1])

    target = tmp_path / "should_not_exist.db"
    proc = subprocess.run(
        [sys.executable, str(RESTORE_SCRIPT), str(corrupt_gz), "--target", str(target), "--yes"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0, (
        f"restore.py accepted a truncated backup (rc=0). stdout={proc.stdout} stderr={proc.stderr}"
    )
    # Either checksum mismatch or decompression error must surface in logs.
    combined = (proc.stderr + proc.stdout).lower()
    assert any(
        keyword in combined
        for keyword in ("sha256", "checksum", "mismatch", "crc", "gzip", "restore_failed")
    ), f"corruption log signal missing: stderr={proc.stderr}"
    assert not target.is_file(), f"target was written despite corrupt backup: {target}"
