#!/usr/bin/env python3
"""DEEP-60 lane policy enforcer test stub (8 cases, stdlib unittest).

Run:
    python3 -m unittest test_lane_policy_enforcer.py -v

LLM API calls = 0; uses tempfile + subprocess + stdlib only.
"""

from __future__ import annotations

import csv
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
ENFORCER = REPO_ROOT / "scripts/ops/lane_policy_enforcer.py"
POLICY = REPO_ROOT / "scripts/ops/lane_policy.json"
HOOK = REPO_ROOT / "tools/offline/operator_review/pre-commit-hook.sh"
GHA = REPO_ROOT / ".github/workflows/lane-enforcer-ci.yml"


def _git(repo: pathlib.Path, *args: str, env: dict | None = None) -> str:
    e = os.environ.copy()
    e["GIT_AUTHOR_NAME"] = "deep60-test"
    e["GIT_AUTHOR_EMAIL"] = "test@example.invalid"
    e["GIT_COMMITTER_NAME"] = "deep60-test"
    e["GIT_COMMITTER_EMAIL"] = "test@example.invalid"
    if env:
        e.update(env)
    out = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
        env=e,
    )
    return out.stdout


def _make_fake_repo(tmp: pathlib.Path) -> pathlib.Path:
    """Create a tiny repo with the enforcer + policy mirrored at the canonical path."""
    repo = tmp / "fake_repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    # mirror canonical enforcer path so tests resemble real layout
    target = (
        repo
        / "tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_07/deep60_lane_enforcer"
    )
    target.mkdir(parents=True)
    shutil.copy(ENFORCER, target / "lane_policy_enforcer.py")
    shutil.copy(POLICY, target / "lane_policy.json")
    # commit baseline so HEAD exists
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo


def _run_enforcer(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    enf = (
        repo
        / "tools/offline/_inbox/value_growth_dual/_executable_artifacts_2026_05_07/deep60_lane_enforcer/lane_policy_enforcer.py"
    )
    return subprocess.run(
        [sys.executable, str(enf), *args],
        capture_output=True,
        text=True,
        cwd=str(repo),
    )


class LanePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # 1. allowed path -> OK
    def test_allowed_path_session_a_ok(self) -> None:
        repo = _make_fake_repo(self.tmp)
        f = repo / "tools/offline/_inbox/value_growth_dual/note.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("hello", encoding="utf-8")
        _git(repo, "add", str(f.relative_to(repo)))
        cp = _run_enforcer(repo, "--check", "--lane", "session_a")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("OK", cp.stdout)

    # 2. forbidden path -> reject
    def test_forbidden_path_session_a_blocks(self) -> None:
        repo = _make_fake_repo(self.tmp)
        f = repo / "src/jpcite_api/x.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# bad", encoding="utf-8")
        _git(repo, "add", str(f.relative_to(repo)))
        cp = _run_enforcer(repo, "--check", "--lane", "session_a")
        self.assertEqual(cp.returncode, 1)
        self.assertIn("FAIL", cp.stderr)

    # 3. bypass-with-reason override -> OK + ledger row
    def test_bypass_with_reason_overrides(self) -> None:
        repo = _make_fake_repo(self.tmp)
        f = repo / "src/jpcite_api/x.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# bad", encoding="utf-8")
        _git(repo, "add", str(f.relative_to(repo)))
        cp = _run_enforcer(
            repo,
            "--check",
            "--lane",
            "session_a",
            "--bypass-with-reason",
            "operator override: cross-lane doc fix verified",
            "--operator-signoff",
            "umeda",
        )
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("OVERRIDE accepted", cp.stdout)
        ledger = repo / "tools/offline/_inbox/value_growth_dual/AGENT_LEDGER.csv"
        self.assertTrue(ledger.exists())
        with ledger.open(encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertGreaterEqual(len(rows), 2)  # header + at least one record
        self.assertEqual(rows[0][0], "agent_run_id")
        last = rows[-1]
        self.assertEqual(last[3], "session_a")
        self.assertIn("operator override", last[6])
        self.assertEqual(last[7], "umeda")

    # 4. lane_policy.json parses + has both lanes
    def test_lane_policy_json_parses(self) -> None:
        with POLICY.open(encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("lanes", data)
        self.assertIn("session_a", data["lanes"])
        self.assertIn("codex", data["lanes"])
        self.assertGreaterEqual(len(data["lanes"]["session_a"]["allowed_paths"]), 1)
        self.assertGreaterEqual(len(data["lanes"]["codex"]["forbidden_paths"]), 1)

    # 5. GHA workflow YAML syntax (best-effort: PyYAML if available, else grep)
    def test_gha_workflow_syntax(self) -> None:
        text = GHA.read_text(encoding="utf-8")
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
            self.assertIn("jobs", data)
            self.assertIn("enforce-lane", data["jobs"])
        except ImportError:
            # fallback: ensure top-level keys we need are textually present
            for key in ("name:", "on:", "jobs:", "enforce-lane:", "uses: actions/checkout@v4"):
                self.assertIn(key, text)

    # 6. pre-commit hook bash syntax (bash -n)
    def test_pre_commit_hook_bash_syntax(self) -> None:
        cp = subprocess.run(
            ["bash", "-n", str(HOOK)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)

    # 7. LLM API import = 0
    def test_no_llm_api_imports(self) -> None:
        text = ENFORCER.read_text(encoding="utf-8")
        for forbidden in (
            "import anthropic",
            "from anthropic",
            "import openai",
            "from openai",
            "google.generativeai",
            "import requests",
        ):
            self.assertNotIn(forbidden, text, f"forbidden import found: {forbidden}")

    # 8. AGENT_LEDGER append on clean run
    def test_ledger_appended_on_clean_run(self) -> None:
        repo = _make_fake_repo(self.tmp)
        f = repo / "tools/offline/_inbox/value_growth_dual/note2.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("hi", encoding="utf-8")
        _git(repo, "add", str(f.relative_to(repo)))
        cp = _run_enforcer(repo, "--check", "--lane", "session_a", "--session", "test_run")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        ledger = repo / "tools/offline/_inbox/value_growth_dual/AGENT_LEDGER.csv"
        self.assertTrue(ledger.exists())
        with ledger.open(encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        # header + 1 record
        self.assertEqual(
            rows[0],
            [
                "agent_run_id",
                "timestamp_utc",
                "session",
                "lane",
                "write_paths",
                "violation_count",
                "override_reason",
                "operator_signoff",
            ],
        )
        self.assertEqual(rows[-1][2], "test_run")
        self.assertEqual(rows[-1][3], "session_a")
        self.assertEqual(rows[-1][5], "0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
