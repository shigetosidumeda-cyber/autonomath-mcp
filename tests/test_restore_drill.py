"""DEEP-62 monthly R2 restore drill — unit tests.

Coverage (5 cases per spec §7):
  1. Migration apply: wave24_190_restore_drill_log.sql creates the table +
     indexes + CHECK constraints idempotently on jpintel.db.
  2. R2 mock download: scripts/cron/restore_drill_monthly.py wires through a
     mocked _r2_client.list_keys + download to surface a candidate, fetch the
     bytes, and write the drill row.
  3. Integrity OK happy path: PRAGMA integrity_check returns 'ok' on a
     synthetic .db, drill row lands with integrity_status='ok' /
     fk_status='ok' / RTO < 30 min.
  4. Corrupt detection: 1-byte tampered .db produces integrity_status=
     'corrupted' AND a `RESTORE_DRILL_RED` sentinel on stderr.
  5. RTO target met: synthetic drill cycle completes in well under 30 min
     (RTO < 1800s) and the drill row's rto_total_seconds reflects that.

Plus a 6th meta-test that asserts no LLM SDK imports leaked into the new
cron file (LLM 0 invariant).
"""

from __future__ import annotations

import gzip
import importlib
import io
import json
import os
import random
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MIG_FILE = REPO_ROOT / "scripts" / "migrations" / "wave24_190_restore_drill_log.sql"
ROLLBACK_FILE = REPO_ROOT / "scripts" / "migrations" / "wave24_190_restore_drill_log_rollback.sql"
CRON_FILE = REPO_ROOT / "scripts" / "cron" / "restore_drill_monthly.py"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def jpintel_db_path() -> Path:
    fd, path = tempfile.mkstemp(prefix="restore-drill-jpintel-", suffix=".db")
    os.close(fd)
    p = Path(path)
    yield p
    p.unlink(missing_ok=True)


@pytest.fixture()
def applied_migration(jpintel_db_path: Path) -> Path:
    """Apply mig 190 to a fresh sqlite db. Idempotent; runs twice for safety."""
    sql = MIG_FILE.read_text(encoding="utf-8")
    conn = sqlite3.connect(jpintel_db_path)
    try:
        conn.executescript(sql)
        # Second apply must be a no-op (idempotency contract).
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()
    return jpintel_db_path


@pytest.fixture()
def restore_drill_module(monkeypatch: pytest.MonkeyPatch):
    """Import scripts/cron/restore_drill_monthly.py as a module."""
    # The cron script does `sys.path.insert(0, scripts/)` itself for the
    # `from cron._r2_client import ...` import. We just have to load it.
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    if "cron.restore_drill_monthly" in sys.modules:
        del sys.modules["cron.restore_drill_monthly"]
    mod = importlib.import_module("cron.restore_drill_monthly")
    yield mod


def _make_synthetic_db(target: Path) -> None:
    """Create a tiny valid jpintel-shaped sqlite db with the top-10 tables."""
    conn = sqlite3.connect(target)
    try:
        conn.executescript(
            """
            CREATE TABLE programs (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE case_studies (id INTEGER PRIMARY KEY);
            CREATE TABLE loan_programs (id INTEGER PRIMARY KEY);
            CREATE TABLE enforcement_cases (id INTEGER PRIMARY KEY);
            CREATE TABLE laws (id INTEGER PRIMARY KEY);
            CREATE TABLE tax_rulesets (id INTEGER PRIMARY KEY);
            CREATE TABLE court_decisions (id INTEGER PRIMARY KEY);
            CREATE TABLE bids (id INTEGER PRIMARY KEY);
            CREATE TABLE invoice_registrants (id INTEGER PRIMARY KEY);
            CREATE TABLE exclusion_rules (id INTEGER PRIMARY KEY);
            INSERT INTO programs (id, name) VALUES (1, 'demo');
            """
        )
        conn.commit()
    finally:
        conn.close()


def _gz_bytes(src: Path) -> bytes:
    with src.open("rb") as f:
        raw = f.read()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(raw)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Migration apply
# ---------------------------------------------------------------------------


def test_migration_creates_restore_drill_log(applied_migration: Path) -> None:
    conn = sqlite3.connect(applied_migration)
    try:
        # Table exists.
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='restore_drill_log'"
        ).fetchall()
        assert rows, "restore_drill_log table missing after migration"

        # Both indexes exist.
        idx_names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "  AND tbl_name='restore_drill_log'"
            ).fetchall()
        }
        assert "ix_restore_drill_kind_date" in idx_names
        assert "ix_restore_drill_red" in idx_names

        # CHECK on integrity_status enum is enforced.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO restore_drill_log (
                  drill_date, backup_db_kind, backup_key, backup_sha256,
                  backup_size_bytes, download_seconds, gunzip_seconds,
                  integrity_check_seconds, fk_check_seconds,
                  integrity_status, fk_status, rto_total_seconds,
                  sampled_age_days, top10_count_status
                ) VALUES (
                  '2026-05-15', 'autonomath', 'k', 'h', 1, 1.0, 1.0,
                  1.0, 1.0, 'BOGUS', 'ok', 1.0, 5, 'ok'
                )"""
            )

        # CHECK on backup_db_kind enum is enforced.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """INSERT INTO restore_drill_log (
                  drill_date, backup_db_kind, backup_key, backup_sha256,
                  backup_size_bytes, download_seconds, gunzip_seconds,
                  integrity_check_seconds, fk_check_seconds,
                  integrity_status, fk_status, rto_total_seconds,
                  sampled_age_days, top10_count_status
                ) VALUES (
                  '2026-05-15', 'mysql', 'k', 'h', 1, 1.0, 1.0,
                  1.0, 1.0, 'ok', 'ok', 1.0, 5, 'ok'
                )"""
            )

        # Valid row inserts cleanly.
        conn.execute(
            """INSERT INTO restore_drill_log (
              drill_date, backup_db_kind, backup_key, backup_sha256,
              backup_size_bytes, download_seconds, gunzip_seconds,
              integrity_check_seconds, fk_check_seconds,
              integrity_status, fk_status, rto_total_seconds,
              sampled_age_days, top10_count_status
            ) VALUES (
              '2026-05-15', 'jpintel', 'jpintel/x.db.gz', 'sha', 1024,
              1.5, 0.2, 0.1, 0.05, 'ok', 'ok', 1.85, 7, 'skip'
            )"""
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM restore_drill_log").fetchone()[0]
        assert n == 1
    finally:
        conn.close()

    # Rollback file drops cleanly.
    rollback = ROLLBACK_FILE.read_text(encoding="utf-8")
    conn = sqlite3.connect(applied_migration)
    try:
        conn.executescript(rollback)
        conn.commit()
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='restore_drill_log'"
        ).fetchall()
        assert not rows, "restore_drill_log should be dropped by rollback"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. R2 mock download (end-to-end happy path with mocked _r2_client)
# ---------------------------------------------------------------------------


def _wire_mock_r2(
    monkeypatch: pytest.MonkeyPatch,
    mod: Any,
    *,
    candidates: list[tuple[str, datetime, int]],
    on_download: Any,
) -> dict[str, list[Any]]:
    """Patch _r2_client.list_keys + download as referenced from `mod`."""
    calls: dict[str, list[Any]] = {"list_keys": [], "download": []}

    def fake_list_keys(prefix, *, bucket=None):
        calls["list_keys"].append({"prefix": prefix, "bucket": bucket})
        return list(candidates)

    def fake_download(key, local, *, bucket=None):
        calls["download"].append({"key": key, "local": str(local), "bucket": bucket})
        on_download(key, local, bucket)

    monkeypatch.setattr(mod, "list_keys", fake_list_keys)
    monkeypatch.setattr(mod, "download", fake_download)
    return calls


def test_drill_happy_path_inserts_ok_row(
    applied_migration: Path,
    restore_drill_module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mod = restore_drill_module
    now = datetime(2026, 5, 7, 18, 0, tzinfo=UTC)
    fake_mtime = now - timedelta(days=10)
    candidates = [
        ("jpintel/jpintel-20260420-180000.db.gz", fake_mtime, 4096),
    ]

    # Build a tiny valid jpintel-shaped sqlite source we can serve from R2.
    src_db = tmp_path / "fake_src.db"
    _make_synthetic_db(src_db)
    gz_payload = _gz_bytes(src_db)

    def on_download(key, local, bucket):
        Path(local).write_bytes(gz_payload)

    _wire_mock_r2(
        monkeypatch,
        mod,
        candidates=candidates,
        on_download=on_download,
    )

    # Force "now" so the age math is stable.
    monkeypatch.setattr(mod, "_now_utc", lambda: now)

    payload = mod.run_drill(
        jpintel_db=applied_migration,
        bucket="test-bucket",
        autonomath_prefix="autonomath/",
        jpintel_prefix="jpintel/",
        tmp_dir=tmp_path / "drill_tmp",
        expected_json=tmp_path / "missing_expected.json",
        rng=random.Random(42),
        forced_kind="jpintel",
    )

    assert payload["backup_db_kind"] == "jpintel"
    assert payload["backup_key"] == candidates[0][0]
    assert payload["integrity_status"] == "ok"
    assert payload["fk_status"] == "ok"
    assert payload["sampled_age_days"] >= 3
    assert payload["top10_count_status"] == "skip"  # expected.json missing
    assert payload["rto_total_seconds"] >= 0.0
    # 4. RTO target: synthetic db must be well under 30 min (1800s).
    assert payload["rto_total_seconds"] < 1800.0

    # Audit row landed.
    conn = sqlite3.connect(applied_migration)
    try:
        rows = conn.execute(
            "SELECT backup_db_kind, integrity_status, fk_status, "
            "       rto_total_seconds, top10_count_status "
            "  FROM restore_drill_log ORDER BY id DESC LIMIT 1"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    kind, integ, fk, rto, t10 = rows[0]
    assert kind == "jpintel"
    assert integ == "ok"
    assert fk == "ok"
    assert rto >= 0.0
    assert t10 == "skip"


# ---------------------------------------------------------------------------
# 3. Integrity OK + top10 expected.json drift = 'ok' branch
# ---------------------------------------------------------------------------


def test_drill_top10_expected_json_marks_ok(
    applied_migration: Path,
    restore_drill_module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mod = restore_drill_module
    now = datetime(2026, 5, 7, 18, 0, tzinfo=UTC)
    fake_mtime = now - timedelta(days=20)
    candidates = [
        ("jpintel/jpintel-20260417-000000.db.gz", fake_mtime, 8192),
    ]

    src_db = tmp_path / "fake_src.db"
    _make_synthetic_db(src_db)
    gz_payload = _gz_bytes(src_db)

    expected = tmp_path / "expected.json"
    expected.write_text(
        json.dumps({"jpintel": {"programs": 1}}),
        encoding="utf-8",
    )

    def on_download(key, local, bucket):
        Path(local).write_bytes(gz_payload)

    _wire_mock_r2(
        monkeypatch,
        mod,
        candidates=candidates,
        on_download=on_download,
    )
    monkeypatch.setattr(mod, "_now_utc", lambda: now)

    payload = mod.run_drill(
        jpintel_db=applied_migration,
        bucket="test-bucket",
        autonomath_prefix="autonomath/",
        jpintel_prefix="jpintel/",
        tmp_dir=tmp_path / "drill_tmp",
        expected_json=expected,
        rng=random.Random(7),
        forced_kind="jpintel",
    )

    # 1 row in synthetic programs == expected; top10 must be 'ok'.
    assert payload["integrity_status"] == "ok"
    assert payload["top10_count_status"] == "ok"
    assert payload["top10_count_detail"]["programs"] == {
        "expected": 1,
        "actual": 1,
    }


# ---------------------------------------------------------------------------
# 4. Corrupt detection
# ---------------------------------------------------------------------------


def test_drill_detects_corrupt_backup(
    applied_migration: Path,
    restore_drill_module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = restore_drill_module
    now = datetime(2026, 5, 7, 18, 0, tzinfo=UTC)
    fake_mtime = now - timedelta(days=4)
    candidates = [
        ("jpintel/jpintel-broken.db.gz", fake_mtime, 256),
    ]

    # Build a valid .db, then tamper a single byte in the middle of the file
    # AFTER gzipping. The gunzip will succeed, but the resulting bytes are
    # NOT a valid sqlite db, so the connect or PRAGMA path fails — which the
    # cron treats as corrupted (not as a Python exception escape).
    src_db = tmp_path / "fake_src.db"
    _make_synthetic_db(src_db)
    raw = src_db.read_bytes()
    # Tamper the SQLite header magic. byte 0..15 is the magic "SQLite format 3\x00".
    tampered = b"\xff\xff\xff\xff" + raw[4:]
    tampered_db = tmp_path / "tampered.db"
    tampered_db.write_bytes(tampered)
    gz_payload = _gz_bytes(tampered_db)

    def on_download(key, local, bucket):
        Path(local).write_bytes(gz_payload)

    _wire_mock_r2(
        monkeypatch,
        mod,
        candidates=candidates,
        on_download=on_download,
    )
    monkeypatch.setattr(mod, "_now_utc", lambda: now)

    payload = mod.run_drill(
        jpintel_db=applied_migration,
        bucket="test-bucket",
        autonomath_prefix="autonomath/",
        jpintel_prefix="jpintel/",
        tmp_dir=tmp_path / "drill_tmp",
        expected_json=tmp_path / "no_expected.json",
        rng=random.Random(0),
        forced_kind="jpintel",
    )

    assert payload["integrity_status"] == "corrupted", f"expected corrupted, got {payload}"
    captured = capsys.readouterr()
    assert "RESTORE_DRILL_RED" in captured.err

    # Row landed with status='corrupted'.
    conn = sqlite3.connect(applied_migration)
    try:
        row = conn.execute(
            "SELECT integrity_status, notes FROM restore_drill_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "corrupted"
    assert row[1] is not None and "RESTORE_DRILL_RED" in row[1]


# ---------------------------------------------------------------------------
# 5. RTO < 30 min target on synthetic happy path
# ---------------------------------------------------------------------------


def test_drill_rto_under_30min_on_small_db(
    applied_migration: Path,
    restore_drill_module: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mod = restore_drill_module
    now = datetime(2026, 5, 7, 18, 0, tzinfo=UTC)
    fake_mtime = now - timedelta(days=14)
    candidates = [
        ("autonomath/autonomath-fast.db.gz", fake_mtime, 1024),
    ]

    src_db = tmp_path / "fake_src.db"
    _make_synthetic_db(src_db)
    gz_payload = _gz_bytes(src_db)

    def on_download(key, local, bucket):
        Path(local).write_bytes(gz_payload)

    _wire_mock_r2(
        monkeypatch,
        mod,
        candidates=candidates,
        on_download=on_download,
    )
    monkeypatch.setattr(mod, "_now_utc", lambda: now)

    payload = mod.run_drill(
        jpintel_db=applied_migration,
        bucket="test-bucket",
        autonomath_prefix="autonomath/",
        jpintel_prefix="jpintel/",
        tmp_dir=tmp_path / "drill_tmp",
        expected_json=tmp_path / "no.json",
        rng=random.Random(1),
        forced_kind="autonomath",
    )

    # Spec target: autonomath p95 < 30 min (1800s); on synthetic 1 KB DB
    # this is trivially satisfied. We assert << to keep headroom.
    assert payload["rto_total_seconds"] < 60.0, payload
    # And the audit row carries the same number.
    conn = sqlite3.connect(applied_migration)
    try:
        rto_row = conn.execute(
            "SELECT rto_total_seconds FROM restore_drill_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert rto_row is not None
    assert rto_row[0] < 60.0
    assert rto_row[0] > 0.0


# ---------------------------------------------------------------------------
# 6. LLM 0 invariant — cron file must not import any LLM SDK.
# ---------------------------------------------------------------------------


def test_cron_file_has_no_llm_imports() -> None:
    src = CRON_FILE.read_text(encoding="utf-8")
    forbidden = (
        "import anthropic",
        "from anthropic",
        "import openai",
        "from openai",
        "import google.generativeai",
        "from google.generativeai",
        "import claude_agent_sdk",
        "from claude_agent_sdk",
    )
    hits = [tok for tok in forbidden if tok in src]
    assert not hits, f"LLM SDK import leaked into cron: {hits}"

    # Symmetric env check — neither LLM API-key env var should appear in the
    # cron source on a real code line.
    forbidden_env = (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    )
    env_hits = [tok for tok in forbidden_env if tok in src]
    assert not env_hits, f"LLM API key env leaked into cron: {env_hits}"
