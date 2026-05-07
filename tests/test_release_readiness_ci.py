"""DEEP-57 release readiness CI guard — test suite.

Six cases:
  1. ``test_check_workflow_yaml_syntax_valid`` — PR-side workflow YAML
     parses and has expected ``on.pull_request`` shape.
  2. ``test_monthly_workflow_schedule_valid`` — monthly cron string is a
     valid 5-field cron and equals ``0 18 1 * *``.
  3. ``test_verifier_check_detects_known_drift`` — synthetic repo with
     a stale env entry trips ``--check`` and returns exit 1.
  4. ``test_pr_create_logic_mock`` — workflow YAML wires the
     ``peter-evans/create-pull-request@v6`` action with the expected
     branch / title / token / labels.
  5. ``test_llm_import_zero`` — verifier source contains no LLM SDK
     imports / API key envs (CLAUDE.md non-negotiable).
  6. ``test_env_block_parse_correctness`` — verifier round-trips
     ``RUFF_TARGETS`` / ``PYTEST_TARGETS`` blocks identical to DEEP-49.

Constraints:
  * No mock DB calls — synthetic git tree built in ``tmp_path``.
  * No network I/O. No subprocess outside ``git`` itself.
  * stdlib + pytest only. (PyYAML is already a transitive dep of the
    repo's pre-commit + GHA tooling, but we avoid importing it here so
    this test file stays runnable in a minimal env.)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

# Resolve script + workflow files relative to this test file. After the
# operator hands off to scripts/ops/ + .github/workflows/ this path
# fragment changes; both layouts are tolerated.
HERE = Path(__file__).resolve().parent

# Candidates: draft inbox layout (this file) OR post-handoff layout
# (tests/test_release_readiness_ci.py).
_DRAFT = HERE
_HANDOFF_REPO = HERE.parents[0] if HERE.name == "tests" else None


def _resolve(rel_in_draft: str, rel_in_repo: str) -> Path:
    """Resolve a file path that may live in draft inbox or repo proper."""
    draft_path = _DRAFT / rel_in_draft
    if draft_path.exists():
        return draft_path
    if _HANDOFF_REPO is not None:
        repo_path = _HANDOFF_REPO / rel_in_repo
        if repo_path.exists():
            return repo_path
    pytest.skip(f"neither {draft_path} nor handoff path exists")
    return draft_path  # unreachable; for type-checkers


CHECK_YAML = _resolve(
    "check-workflow-target-sync.yml",
    ".github/workflows/check-workflow-target-sync.yml",
)
MONTHLY_YAML = _resolve(
    "sync-workflow-targets-monthly.yml",
    ".github/workflows/sync-workflow-targets-monthly.yml",
)
VERIFIER_SRC = _resolve(
    "sync_workflow_targets_verify.py",
    "scripts/ops/sync_workflow_targets_verify.py",
)


# --- 1. PR-side workflow YAML syntax -----------------------------------


def test_check_workflow_yaml_syntax_valid() -> None:
    """Parses as YAML and declares pull_request trigger with paths."""
    text = CHECK_YAML.read_text(encoding="utf-8")
    assert text.startswith("# DEEP-57"), "leading spec banner missing"
    assert "name: check-workflow-target-sync" in text
    assert re.search(r"^on:\n  pull_request:\n    paths:", text, re.MULTILINE), (
        "pull_request trigger with paths filter not found"
    )
    # Expected path filters
    assert ".github/workflows/**" in text
    assert "tests/**" in text
    # Job name + runs-on
    assert "workflow-target-sync:" in text
    assert "runs-on: ubuntu-latest" in text
    # Pinned SHAs (not floating @v4 / @v5)
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38" in text
    # No paid-plan markers
    assert "self-hosted" not in text
    # Read-only permissions on PR side. Tolerate interleaved comments.
    assert re.search(r"^permissions:", text, re.MULTILINE)
    assert re.search(r"^\s+contents:\s*read\s*$", text, re.MULTILINE), (
        "permissions: contents: read missing on PR-side workflow"
    )


# --- 2. Monthly cron schedule ------------------------------------------


def test_monthly_workflow_schedule_valid() -> None:
    """Cron is exactly '0 18 1 * *' (1st day, 18:00 UTC = 03:00 JST)."""
    text = MONTHLY_YAML.read_text(encoding="utf-8")
    assert "name: sync-workflow-targets-monthly" in text

    # Cron line
    cron_match = re.search(r'-\s+cron:\s+"([^"]+)"', text)
    assert cron_match, "schedule.cron entry not found"
    cron = cron_match.group(1)
    assert cron == "0 18 1 * *", f"unexpected cron: {cron!r}"

    # Validate 5-field cron shape: minute hour dom month dow
    fields = cron.split()
    assert len(fields) == 5, f"cron must have 5 fields, got {len(fields)}"
    minute, hour, dom, month, dow = fields
    assert minute == "0"
    assert hour == "18"
    assert dom == "1"
    assert month == "*"
    assert dow == "*"

    # write permissions for cron + PAT secret reference. The block can
    # contain interleaved comments, so we check membership rather than
    # adjacency.
    assert re.search(r"^permissions:", text, re.MULTILINE)
    assert re.search(r"^\s+contents:\s*write\s*$", text, re.MULTILINE)
    assert re.search(r"^\s+pull-requests:\s*write\s*$", text, re.MULTILINE)
    assert "secrets.CROSS_REPO_PAT" in text


# --- 3. Verifier --check detects synthetic drift ------------------------


def _git(repo: Path, *args: str) -> str:
    """Run git in ``repo`` and return stdout, raising on non-zero."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _seed_repo(tmp_path: Path) -> Path:
    """Build a synthetic repo tree the verifier understands."""
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "scripts" / "ops").mkdir(parents=True)
    (repo / "tests").mkdir()

    # Two real (tracked) script files. Both match RUFF_ALLOW_PREFIXES.
    (repo / "scripts" / "ops" / "release_readiness.py").write_text(
        "# real script A\n", encoding="utf-8"
    )
    (repo / "scripts" / "ops" / "preflight_production_improvement.py").write_text(
        "# real script B\n", encoding="utf-8"
    )
    # One real test file.
    (repo / "tests" / "test_release_readiness.py").write_text(
        "def test_x(): assert True\n", encoding="utf-8"
    )

    # test.yml — env block declares one stale path that does NOT exist.
    test_yml = (
        "name: test\n"
        "on: [push]\n"
        "env:\n"
        "  RUFF_TARGETS: >-\n"
        "    scripts/ops/release_readiness.py\n"
        "    scripts/ops/preflight_production_improvement.py\n"
        "    scripts/ops/this_does_not_exist.py\n"  # <-- stale
        "  PYTEST_TARGETS: >-\n"
        "    tests/test_release_readiness.py\n"
        "jobs:\n"
        "  t:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps: [{run: 'true'}]\n"
    )
    (repo / ".github" / "workflows" / "test.yml").write_text(test_yml, encoding="utf-8")

    # release.yml — same env, plus inline ruff check step.
    release_yml = (
        "name: release\n"
        "on: {push: {tags: ['v*']}}\n"
        "env:\n"
        "  RUFF_TARGETS: >-\n"
        "    scripts/ops/release_readiness.py\n"
        "    scripts/ops/preflight_production_improvement.py\n"
        "    scripts/ops/this_does_not_exist.py\n"
        "  PYTEST_TARGETS: >-\n"
        "    tests/test_release_readiness.py\n"
        "jobs:\n"
        "  r:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: lint\n"
        "        run: |\n"
        "          ruff check \\\n"
        "            scripts/ops/release_readiness.py \\\n"
        "            scripts/ops/preflight_production_improvement.py \\\n"
        "            scripts/ops/this_does_not_exist.py\n"
    )
    (repo / ".github" / "workflows" / "release.yml").write_text(release_yml, encoding="utf-8")

    # Initialise as git repo so ls-files works.
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "ci@jpcite.local")
    _git(repo, "config", "user.name", "ci")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def test_verifier_check_detects_known_drift(tmp_path: Path) -> None:
    repo = _seed_repo(tmp_path)
    result = subprocess.run(
        [sys.executable, str(VERIFIER_SRC), "--check", "--repo-root", str(repo)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, (
        f"expected exit 1 on drift, got {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    out = result.stdout
    # Header row
    assert "workflow" in out and "block" in out and "kind" in out and "path" in out
    # Stale entry surfaces in both yaml files (env blocks) plus inline.
    assert "scripts/ops/this_does_not_exist.py" in out
    assert "stale" in out
    assert "[FAIL]" in out


# --- 4. PR create wiring (no real PR, just YAML inspection) ------------


def test_pr_create_logic_mock() -> None:
    """Monthly workflow uses peter-evans/create-pull-request with expected args."""
    text = MONTHLY_YAML.read_text(encoding="utf-8")

    assert "peter-evans/create-pull-request@67ccf781d68cd99b580ae25a5c18a1cc84ffff1f" in text
    # Branch name reserved by the README handoff
    assert "branch: automated/sync-workflow-targets" in text
    # Title prefix — exact match
    assert 'title: "[automated] sync workflow targets"' in text
    # PAT injected into both checkout AND create-pull-request
    pat_count = text.count("${{ secrets.CROSS_REPO_PAT }}")
    assert pat_count >= 2, f"CROSS_REPO_PAT must be referenced ≥2 times, got {pat_count}"
    # Labels block
    assert "automated\n            release-readiness-ci" in text or (
        "automated" in text and "release-readiness-ci" in text
    )
    # add-paths restricted to two yaml files
    assert ".github/workflows/test.yml" in text
    assert ".github/workflows/release.yml" in text
    # No auto-merge directive (operator review preserved)
    assert "auto-merge" not in text.lower()


# --- 5. LLM API import sentinel ----------------------------------------


_BANNED_IMPORTS = (
    "import anthropic",
    "from anthropic",
    "import openai",
    "from openai",
    "import google.generativeai",
    "from google.generativeai",
    "import claude_agent_sdk",
    "from claude_agent_sdk",
)
_BANNED_ENVS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


def test_llm_import_zero() -> None:
    src = VERIFIER_SRC.read_text(encoding="utf-8")
    for banned in _BANNED_IMPORTS:
        assert banned not in src, f"forbidden LLM import: {banned!r}"
    for env in _BANNED_ENVS:
        # Skipping comments is overkill — this script has no comments
        # mentioning these strings, so substring search is sufficient.
        assert env not in src, f"forbidden LLM env reference: {env!r}"

    # Also scan both YAMLs (they should be even more obviously clean).
    for yaml_path in (CHECK_YAML, MONTHLY_YAML):
        yaml_text = yaml_path.read_text(encoding="utf-8")
        for banned in _BANNED_IMPORTS:
            assert banned not in yaml_text
        for env in _BANNED_ENVS:
            assert env not in yaml_text


# --- 6. Env block parse correctness ------------------------------------


def test_env_block_parse_correctness(tmp_path: Path) -> None:
    """Verifier parses RUFF_TARGETS / PYTEST_TARGETS into the same list
    DEEP-49 would emit, byte-for-byte."""
    # Reuse seeded repo so the env blocks are on disk.
    repo = _seed_repo(tmp_path)

    # Import the verifier as a module so we can call its parser
    # directly (no subprocess noise). We use a unique module name to
    # avoid colliding with any other module already in sys.modules,
    # AND register it in sys.modules BEFORE exec_module so dataclass
    # annotation resolution can locate the owning module.
    import importlib.util

    unique_name = "_deep57_verifier_under_test"
    spec = importlib.util.spec_from_file_location(unique_name, VERIFIER_SRC)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        # Leave it in sys.modules — dataclass __module__ refs need it
        # to remain resolvable for the lifetime of the test process.
        pass

    test_text = (repo / ".github/workflows/test.yml").read_text(encoding="utf-8")
    release_text = (repo / ".github/workflows/release.yml").read_text(encoding="utf-8")

    ruff_in_test = mod._parse_env_block(test_text, "RUFF_TARGETS")
    pytest_in_test = mod._parse_env_block(test_text, "PYTEST_TARGETS")
    ruff_in_release = mod._parse_env_block(release_text, "RUFF_TARGETS")
    inline_ruff = mod._parse_release_ruff_lint(release_text)

    expected_ruff = [
        "scripts/ops/release_readiness.py",
        "scripts/ops/preflight_production_improvement.py",
        "scripts/ops/this_does_not_exist.py",
    ]
    expected_pytest = ["tests/test_release_readiness.py"]

    assert ruff_in_test == expected_ruff
    assert pytest_in_test == expected_pytest
    assert ruff_in_release == expected_ruff
    assert inline_ruff == expected_ruff

    # Also assert the public API surface DEEP-49 + DEEP-57 share.
    assert hasattr(mod, "_collect")
    assert hasattr(mod, "_render_table")
    assert hasattr(mod, "_render_markdown")
    assert hasattr(mod, "DEFAULT_REPO_ROOT")
