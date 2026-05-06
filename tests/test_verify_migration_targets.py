#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_verify_migration_targets.py — DEEP-52 §6 acceptance tests.

8 cases (no LLM, no paid, no work-hour):
  1. marker missing → MARKER_MISSING
  2. marker invalid value → MARKER_INVALID
  3. rollback pair missing → ROLLBACK_PAIR_BROKEN
  4. forbidden table CREATE → BODY_TARGET_VIOLATION
  5. in-memory dry-run on a synthetic 6-file set → all PASS
  6. rollback idempotency → re-apply forward after rollback succeeds
  7. per-target isolation → autonomath migrations don't pollute jpintel handle
  8. LLM API import = 0 (static check on the verify script + this test)

Run as either:
  python -m unittest test_verify_migration_targets
  python test_verify_migration_targets.py
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Promoted layout: script lives under scripts/ops/, not next to this test.
# Fall back to the test dir for the in-tree draft layout.
_REPO_ROOT = HERE.parent
_OPS_DIR = _REPO_ROOT / "scripts" / "ops"
if (_OPS_DIR / "verify_migration_targets.py").exists():
    sys.path.insert(0, str(_OPS_DIR))
else:
    sys.path.insert(0, str(HERE))

import verify_migration_targets as vmt  # noqa: E402


def _write(path: str, body: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


# -------- synthetic migration corpus -----------------------------------------

GOOD_AUTONOMATH_FORWARD = """\
-- target_db: autonomath
-- migration wave24_200_am_demo_index
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS am_demo (
    id INTEGER PRIMARY KEY,
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_am_demo_note ON am_demo(note);
"""

GOOD_AUTONOMATH_ROLLBACK = """\
-- target_db: autonomath
-- migration wave24_200_am_demo_index_rollback
PRAGMA foreign_keys = ON;
DROP INDEX IF EXISTS idx_am_demo_note;
DROP TABLE IF EXISTS am_demo;
"""

GOOD_JPINTEL_FORWARD = """\
-- target_db: jpintel
-- migration wave24_201_jpi_demo
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS jpi_demo (
    id INTEGER PRIMARY KEY,
    label TEXT
);
"""

GOOD_JPINTEL_ROLLBACK = """\
-- target_db: jpintel
-- migration wave24_201_jpi_demo_rollback
PRAGMA foreign_keys = ON;
DROP TABLE IF EXISTS jpi_demo;
"""

# An autonomath-marked file that illegally CREATEs `programs` (jpintel-only).
BAD_AUTONOMATH_BODY = """\
-- target_db: autonomath
-- migration wave24_202_bad_programs
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY
);
"""

NO_MARKER = """\
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS am_orphan (id INTEGER PRIMARY KEY);
"""

INVALID_MARKER = """\
-- target_db: legacy_db
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS legacy_demo (id INTEGER PRIMARY KEY);
"""


class _Fixture:
    """Builds a tmp migrations dir with a 6-file healthy set + extras."""

    def __init__(self, root: str):
        self.root = root
        self.mig_dir = os.path.join(root, "migrations")
        os.makedirs(self.mig_dir, exist_ok=True)

    def write_healthy(self) -> None:
        _write(os.path.join(self.mig_dir, "wave24_200_am_demo_index.sql"), GOOD_AUTONOMATH_FORWARD)
        _write(
            os.path.join(self.mig_dir, "wave24_200_am_demo_index_rollback.sql"),
            GOOD_AUTONOMATH_ROLLBACK,
        )
        _write(os.path.join(self.mig_dir, "wave24_201_jpi_demo.sql"), GOOD_JPINTEL_FORWARD)
        _write(
            os.path.join(self.mig_dir, "wave24_201_jpi_demo_rollback.sql"), GOOD_JPINTEL_ROLLBACK
        )

    def write_extras(self) -> None:
        _write(os.path.join(self.mig_dir, "wave24_203_no_marker.sql"), NO_MARKER)
        _write(os.path.join(self.mig_dir, "wave24_204_invalid_marker.sql"), INVALID_MARKER)
        _write(
            os.path.join(self.mig_dir, "wave24_205_lonely_forward.sql"),
            GOOD_AUTONOMATH_FORWARD.replace("am_demo", "am_lonely"),
        )
        _write(os.path.join(self.mig_dir, "wave24_206_bad_programs.sql"), BAD_AUTONOMATH_BODY)


# -------- tests --------------------------------------------------------------


class MarkerMissing(unittest.TestCase):
    def test_marker_missing_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.write_extras()
            target = os.path.join(f.mig_dir, "wave24_203_no_marker.sql")
            r = vmt.check_file(target, vmt.EMBEDDED_RULES)
            self.assertIn("MARKER_MISSING", r.errors)
            self.assertIsNone(r.marker)


class MarkerInvalid(unittest.TestCase):
    def test_marker_outside_enum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.write_extras()
            target = os.path.join(f.mig_dir, "wave24_204_invalid_marker.sql")
            r = vmt.check_file(target, vmt.EMBEDDED_RULES)
            self.assertEqual(r.marker, "legacy_db")
            self.assertTrue(any(e.startswith("MARKER_INVALID") for e in r.errors), r.errors)


class RollbackPairMissing(unittest.TestCase):
    def test_lonely_forward(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.write_extras()
            target = os.path.join(f.mig_dir, "wave24_205_lonely_forward.sql")
            r = vmt.check_file(target, vmt.EMBEDDED_RULES)
            self.assertTrue(any("ROLLBACK_PAIR_BROKEN" in e for e in r.errors), r.errors)


class ForbiddenTableCreate(unittest.TestCase):
    def test_autonomath_creating_jpintel_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.write_extras()
            target = os.path.join(f.mig_dir, "wave24_206_bad_programs.sql")
            r = vmt.check_file(target, vmt.EMBEDDED_RULES)
            self.assertIn("programs", r.body_tables)
            self.assertTrue(
                any(e.startswith("BODY_TARGET_VIOLATION") and "programs" in e for e in r.errors),
                r.errors,
            )


class DryRunAllPass(unittest.TestCase):
    def test_in_memory_dry_run_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.write_healthy()
            files = vmt.discover_migrations(f.mig_dir)
            reports, rollup = vmt.run_check(files, vmt.EMBEDDED_RULES, target_filter=None)
            self.assertEqual(rollup["files_with_errors"], 0, [r for r in reports if r.errors])
            for tgt in vmt.VALID_TARGETS:
                forwards = [r for r in reports if r.marker == tgt]
                res = vmt.dry_run_target(tgt, forwards, vmt.EMBEDDED_RULES)
                self.assertEqual(res["errors"], [], f"{tgt} dry-run errors: {res['errors']}")
                self.assertGreaterEqual(res["forward_count"], 1)
                self.assertGreaterEqual(res["rollback_count"], 1)


class RollbackIdempotency(unittest.TestCase):
    def test_forward_reapply_after_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.write_healthy()
            files = vmt.discover_migrations(f.mig_dir)
            reports, _ = vmt.run_check(files, vmt.EMBEDDED_RULES, target_filter=None)
            forwards = [r for r in reports if r.marker == "autonomath"]
            res = vmt.dry_run_target("autonomath", forwards, vmt.EMBEDDED_RULES)
            self.assertGreaterEqual(res["idempotency_count"], 1)
            for entry in res["idempotency_log"]:
                self.assertIsNone(entry["error"], f"idempotency error: {entry}")


class PerTargetIsolation(unittest.TestCase):
    def test_targets_run_in_separate_handles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = _Fixture(tmp)
            f.write_healthy()
            files = vmt.discover_migrations(f.mig_dir)
            reports, _ = vmt.run_check(files, vmt.EMBEDDED_RULES, target_filter=None)
            am_forwards = [r for r in reports if r.marker == "autonomath"]
            jp_forwards = [r for r in reports if r.marker == "jpintel"]
            am_res = vmt.dry_run_target("autonomath", am_forwards, vmt.EMBEDDED_RULES)
            jp_res = vmt.dry_run_target("jpintel", jp_forwards, vmt.EMBEDDED_RULES)

            self.assertEqual(am_res["errors"], [])
            self.assertEqual(jp_res["errors"], [])

            # Each handle was independent; we re-create them here and verify
            # that applying autonomath SQL leaves no jpi_* tables in the
            # autonomath handle, and vice-versa.
            for target, forwards in (("autonomath", am_forwards), ("jpintel", jp_forwards)):
                handle = sqlite3.connect(":memory:")
                for r in sorted(forwards, key=vmt._sort_key):
                    if r.is_rollback:
                        continue
                    with open(r.path, "r", encoding="utf-8") as fh:
                        handle.executescript(fh.read())
                cur = handle.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cur.fetchall()]
                handle.close()
                if target == "autonomath":
                    for t in tables:
                        self.assertFalse(
                            t.startswith("jpi_"), f"autonomath handle leaked jpintel table {t}"
                        )
                else:
                    for t in tables:
                        self.assertFalse(
                            t.startswith("am_"), f"jpintel handle leaked autonomath table {t}"
                        )


class LLMImportZero(unittest.TestCase):
    """DEEP-52 §6 acceptance #5 — LLM API call count = 0."""

    FORBIDDEN_IMPORTS = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    )

    def _scan(self, path: Path) -> list:
        text = path.read_text(encoding="utf-8")
        # strip line comments + docstrings before scanning to avoid false
        # hits on "this script must not import anthropic" prose.
        no_comments = re.sub(r"#[^\n]*", "", text)
        no_docstrings = re.sub(r'"""(?:.|\n)*?"""', "", no_comments)
        no_docstrings = re.sub(r"'''(?:.|\n)*?'''", "", no_docstrings)
        hits = []
        for token in self.FORBIDDEN_IMPORTS:
            if token in no_docstrings:
                hits.append(token)
        return hits

    def test_verify_script_has_no_llm_imports(self) -> None:
        target = _OPS_DIR / "verify_migration_targets.py"
        if not target.exists():
            target = HERE / "verify_migration_targets.py"
        self.assertEqual(self._scan(target), [])

    def test_test_module_has_no_llm_imports(self) -> None:
        target = HERE / "test_verify_migration_targets.py"
        self.assertEqual(self._scan(target), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
