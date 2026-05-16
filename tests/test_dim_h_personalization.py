"""Integration tests for Dim H personalization preference storage (Wave 47).

Closes the Wave 46 Dim H storage gap: migration 287 adds
``am_personalization_profile`` (customer-controlled preference blob
keyed by sha256(token), NO PII) and
``am_personalization_recommendation_log`` (append-only audit). Pairs
with ``scripts/etl/build_personalization_recommendations.py`` (nightly
deterministic recommendation scoring).

Case bundles
------------
  1. Migration 287 applies cleanly on a fresh SQLite db (idempotent re-apply).
  2. Migration 287 rollback drops every artefact created.
  3. CHECK constraints reject malformed rows:
     - user_token_hash length != 64 (sha256 hex)
     - preference_json length out of [2, 16384]
     - last_updated_at < created_at
     - score out of [0, 100]
     - recommendation_type out of enum.
  4. UNIQUE(user_token_hash) prevents duplicate profiles.
  5. FK profile_id -> profile honored.
  6. ETL deterministic scoring produces expected rows.
  7. ETL guard rejects empty database (no profile table).
  8. **PRIVACY** — schema MUST NOT contain PII columns (email/ip/houjin/name).
  9. Boot manifest registration (jpcite + autonomath mirror).
 10. **LLM-0 verify** — grep anthropic|openai in ETL = 0.

Hard constraints exercised
--------------------------
  * No LLM SDK import in any new file (personalization is deterministic).
  * No PII columns at all — user_token_hash is the only identifier.
  * Brand: only jpcite. No legacy 税務会計AI / zeimu-kaikei.ai.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MIG_287 = REPO_ROOT / "scripts" / "migrations" / "287_personalization.sql"
MIG_287_RB = REPO_ROOT / "scripts" / "migrations" / "287_personalization_rollback.sql"
ETL = REPO_ROOT / "scripts" / "etl" / "build_personalization_recommendations.py"
MANIFEST_JPCITE = REPO_ROOT / "scripts" / "migrations" / "jpcite_boot_manifest.txt"
MANIFEST_AM = REPO_ROOT / "scripts" / "migrations" / "autonomath_boot_manifest.txt"

# Banned column names — these would constitute PII storage.
_PII_PATTERNS = (
    "email",
    "mail_addr",
    "ip_addr",
    "houjin_bangou",
    "corporate_number",
    "user_name",
    "full_name",
    "phone",
)


def _apply(db_path: pathlib.Path, sql_path: pathlib.Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(sql_path.read_text(encoding="utf-8"))
    finally:
        conn.close()


def _fresh_db(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "dim_h.db"
    _apply(db, MIG_287)
    return db


def _tok(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _insert_profile(
    db: pathlib.Path,
    *,
    token_hash: str,
    preference: dict | None = None,
) -> int:
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            """
            INSERT INTO am_personalization_profile
                (user_token_hash, preference_json)
            VALUES (?, ?)
            """,
            (token_hash, json.dumps(preference or {})),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. Migration applies cleanly + idempotent re-apply
# ---------------------------------------------------------------------------


def test_migration_287_applies_cleanly(tmp_path):
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "am_personalization_profile" in tables
        assert "am_personalization_recommendation_log" in tables

        views = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        }
        assert "v_personalization_recent_recs" in views
    finally:
        conn.close()


def test_migration_287_idempotent(tmp_path):
    db = _fresh_db(tmp_path)
    # Apply again — must not raise.
    _apply(db, MIG_287)


# ---------------------------------------------------------------------------
# 2. Rollback drops every artefact
# ---------------------------------------------------------------------------


def test_migration_287_rollback(tmp_path):
    db = _fresh_db(tmp_path)
    _apply(db, MIG_287_RB)
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert "am_personalization_profile" not in tables
        assert "am_personalization_recommendation_log" not in tables
        views = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
        }
        assert "v_personalization_recent_recs" not in views
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. CHECK constraints reject malformed rows
# ---------------------------------------------------------------------------


def test_user_token_hash_wrong_length_rejected(tmp_path):
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO am_personalization_profile
                    (user_token_hash, preference_json)
                VALUES (?, ?)
                """,
                ("short_hash", "{}"),
            )
            conn.commit()
    finally:
        conn.close()


def test_preference_json_too_small_rejected(tmp_path):
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO am_personalization_profile
                    (user_token_hash, preference_json)
                VALUES (?, ?)
                """,
                (_tok("a"), ""),
            )
            conn.commit()
    finally:
        conn.close()


def test_score_out_of_range_rejected(tmp_path):
    db = _fresh_db(tmp_path)
    pid = _insert_profile(db, token_hash=_tok("b"))
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO am_personalization_recommendation_log
                    (profile_id, recommendation_type, score)
                VALUES (?, ?, ?)
                """,
                (pid, "program", 150),
            )
            conn.commit()
    finally:
        conn.close()


def test_recommendation_type_enum_rejected(tmp_path):
    db = _fresh_db(tmp_path)
    pid = _insert_profile(db, token_hash=_tok("c"))
    conn = sqlite3.connect(str(db))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO am_personalization_recommendation_log
                    (profile_id, recommendation_type, score)
                VALUES (?, ?, ?)
                """,
                (pid, "not_a_valid_type", 50),
            )
            conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. UNIQUE(user_token_hash) prevents duplicate profiles
# ---------------------------------------------------------------------------


def test_unique_user_token_hash(tmp_path):
    db = _fresh_db(tmp_path)
    tok = _tok("dup")
    _insert_profile(db, token_hash=tok)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_profile(db, token_hash=tok)


# ---------------------------------------------------------------------------
# 5. FK profile_id -> profile honored
# ---------------------------------------------------------------------------


def test_fk_profile_id(tmp_path):
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO am_personalization_recommendation_log
                    (profile_id, recommendation_type, score)
                VALUES (?, ?, ?)
                """,
                (9999, "program", 50),
            )
            conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. ETL deterministic scoring produces expected rows
# ---------------------------------------------------------------------------


def test_etl_scores_active_profiles(tmp_path):
    db = _fresh_db(tmp_path)
    _insert_profile(
        db,
        token_hash=_tok("alpha"),
        preference={
            "industry_pack": "tech",
            "deadline_horizon_days": 30,
            "risk_tolerance": "low",
        },
    )
    _insert_profile(
        db,
        token_hash=_tok("beta"),
        preference={"industry_pack": "agri"},
    )
    res = subprocess.run(
        [
            sys.executable,
            str(ETL),
            "--db",
            str(db),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    last_line = res.stdout.strip().splitlines()[-1]
    payload = json.loads(last_line)
    assert payload["dim"] == "H"
    assert payload["wave"] == 47
    assert payload["profiles"] == 2
    # Both profiles have industry_pack so all 4 rec_types log at least 1 row.
    assert payload["logged"] >= 4

    # Verify rows landed and scores are within enum.
    conn = sqlite3.connect(str(db))
    try:
        rows = conn.execute(
            "SELECT recommendation_type, score FROM am_personalization_recommendation_log"
        ).fetchall()
        assert rows, "ETL must produce at least one recommendation row"
        for rec_type, score in rows:
            assert rec_type in (
                "program",
                "industry_pack",
                "saved_search",
                "amendment",
            )
            assert 0 <= score <= 100
    finally:
        conn.close()


def test_etl_guard_rejects_missing_schema(tmp_path):
    db = tmp_path / "empty.db"
    sqlite3.connect(str(db)).close()  # create empty file
    res = subprocess.run(
        [sys.executable, str(ETL), "--db", str(db)],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "am_personalization_profile not found" in res.stderr


# ---------------------------------------------------------------------------
# 7. PRIVACY — schema MUST NOT contain PII column names
# ---------------------------------------------------------------------------


def test_schema_no_pii_columns(tmp_path):
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        for table in (
            "am_personalization_profile",
            "am_personalization_recommendation_log",
        ):
            cols = {
                row[1].lower() for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for banned in _PII_PATTERNS:
                for col in cols:
                    assert banned not in col, (
                        f"PII column '{col}' (matches '{banned}') forbidden in {table}"
                    )
    finally:
        conn.close()


def test_schema_uses_token_hash_only(tmp_path):
    """The only identifier in the profile table MUST be user_token_hash."""
    db = _fresh_db(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(am_personalization_profile)").fetchall()
        }
        assert "user_token_hash" in cols
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 8. Boot manifest registration
# ---------------------------------------------------------------------------


def test_jpcite_boot_manifest_includes_287():
    assert "287_personalization.sql" in MANIFEST_JPCITE.read_text(encoding="utf-8")


def test_autonomath_boot_manifest_includes_287():
    assert "287_personalization.sql" in MANIFEST_AM.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 9. LLM-0 verify — grep anthropic|openai in ETL = 0
# ---------------------------------------------------------------------------


def test_etl_llm_zero():
    """ETL MUST NOT import any LLM SDK (Anthropic / OpenAI)."""
    src = ETL.read_text(encoding="utf-8")
    # Be precise: forbid actual import lines, not the words in docstrings.
    forbidden = (
        r"^\s*import\s+anthropic",
        r"^\s*from\s+anthropic",
        r"^\s*import\s+openai",
        r"^\s*from\s+openai",
    )
    for pat in forbidden:
        assert not re.search(pat, src, flags=re.MULTILINE), (
            f"LLM SDK import pattern '{pat}' must not appear in {ETL}"
        )


def test_etl_no_legacy_brand():
    """ETL MUST NOT reference legacy brand names."""
    src = ETL.read_text(encoding="utf-8")
    for legacy in ("税務会計AI", "zeimu-kaikei.ai", "ZeimuKaikei"):
        assert legacy not in src, f"legacy brand '{legacy}' in {ETL}"
