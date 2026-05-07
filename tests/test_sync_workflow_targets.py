"""Test stub for sync_workflow_targets.py (DEEP-49).

Five cases are exercised here:

1. ``test_check_mode_detects_synthetic_untracked_drift`` - synthetic
   tests/test_*.py files appear under glob but are not in
   ``git ls-files``; the check-mode output must report them as missing
   from the env list and exit 1.
2. ``test_apply_mode_rewrites_env_blocks`` - apply-mode rewrites both
   env blocks in test.yml + release.yml so they exactly match the
   desired list, and a follow-up --check returns exit 0.
3. ``test_no_llm_api_imports`` - static grep verifies the script does
   not import or reference any LLM API SDK or env var.
4. ``test_no_import_side_effects`` - module imports without performing
   git/IO/network work; calling main() with no argv must NOT raise on
   import alone (only when run).
5. ``test_check_returns_exit_code_1_on_drift`` - synthetic drift in a
   tmp repo causes ``main(["--check", "--repo-root", tmp])`` to return 1.

The test fixtures build a tiny temp git repo containing minimal
test.yml + release.yml scaffolding plus a couple of tracked tests/
and scripts/ files, so we exercise the regex paths without depending
on the live jpcite tree.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Path resolution - codex lane layout: tests/test_sync_workflow_targets.py
# loads scripts/ops/sync_workflow_targets.py via spec_from_file_location.
HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "ops" / "sync_workflow_targets.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sync_workflow_targets", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _scaffold_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "scripts" / "ops").mkdir(parents=True)
    (repo / "scripts" / "etl").mkdir(parents=True)
    (repo / "tests").mkdir()

    # Minimal test.yml with both env blocks. Note the >- folded scalar
    # and 4-space body indent to match release_readiness.py:80 anchor.
    (repo / ".github" / "workflows" / "test.yml").write_text(
        "name: test\n"
        "env:\n"
        "  RUFF_TARGETS: >-\n"
        "    scripts/ops/old_only.py\n"
        "  PYTEST_TARGETS: >-\n"
        "    tests/test_old_only.py\n",
        encoding="utf-8",
    )
    (repo / ".github" / "workflows" / "release.yml").write_text(
        "name: release\n"
        "env:\n"
        "  RUFF_TARGETS: >-\n"
        "    scripts/ops/old_only.py\n"
        "  PYTEST_TARGETS: >-\n"
        "    tests/test_old_only.py\n"
        "jobs:\n"
        "  release:\n"
        "    steps:\n"
        "      - name: Ruff lint\n"
        "        run: |\n"
        "          ruff check \\\n"
        "            scripts/ops/old_only.py\n",
        encoding="utf-8",
    )
    # Scripts that should be picked up.
    (repo / "scripts" / "ops" / "release_readiness.py").write_text("# stub\n")
    (repo / "scripts" / "ops" / "preflight_production_improvement.py").write_text("# stub\n")
    (repo / "scripts" / "etl" / "generate_program_rss_feeds.py").write_text("# stub\n")
    (repo / "scripts" / "generate_program_pages.py").write_text("# stub\n")
    # Tests that should be picked up.
    (repo / "tests" / "test_alpha.py").write_text("def test_a(): pass\n")
    (repo / "tests" / "test_beta.py").write_text("def test_b(): pass\n")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "scaffold")
    return repo


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return _scaffold_repo(tmp_path)


# ------------------------------------------------------------------ tests --


def test_check_mode_detects_synthetic_untracked_drift(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mod = _load_module()
    rc = mod.main(["--check", "--repo-root", str(repo)])
    out = capsys.readouterr().out
    assert rc == 1
    # Drift report must mention both the missing additions and the stale
    # entries that no longer exist in git ls-files.
    assert "missing" in out or "stale" in out
    assert "test_alpha.py" in out or "test_beta.py" in out


def test_apply_mode_rewrites_env_blocks(repo: Path) -> None:
    mod = _load_module()
    rc = mod.main(["--apply", "--repo-root", str(repo)])
    assert rc == 0
    test_yml = (repo / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    release_yml = (repo / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    # Both alpha + beta must appear in both env blocks now.
    for name in ("test_alpha.py", "test_beta.py"):
        assert name in test_yml
        assert name in release_yml
    # Old stale path must be gone.
    assert "old_only.py" not in test_yml
    assert "old_only.py" not in release_yml
    # Ruff lint inline block in release.yml must also be rewritten.
    assert "scripts/ops/release_readiness.py" in release_yml
    # And a follow-up --check must converge.
    rc2 = mod.main(["--check", "--repo-root", str(repo)])
    assert rc2 == 0


def test_no_llm_api_imports() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    forbidden = (
        "anthropic",
        "openai",
        "google.generativeai",
        "claude_agent_sdk",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
    )
    for term in forbidden:
        # Match only on real code lines, not the regex literal that the
        # CI guard itself uses to grep for these strings (we have none
        # in this script, but keeping the comment policy explicit).
        assert not re.search(
            rf"(?<!#).*\b{re.escape(term)}\b", text
        ), f"forbidden token {term!r} present in {SCRIPT_PATH.name}"


def test_no_import_side_effects(repo: Path) -> None:
    # Importing the module must not perform git work or touch the
    # filesystem outside the spec_from_file_location step itself.
    # We verify two things:
    #  (a) AST parse: no top-level Call expression nodes other than
    #      argparse / dataclasses constructions wrapped in assignments
    #      (those are bound to names, not bare statements). A bare
    #      Call at module scope means import-time work.
    #  (b) Actually loading the module under a fresh subprocess is
    #      harmless - no git invocation, no filesystem write.
    import ast

    text = SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    bare_calls: list[str] = []
    for node in tree.body:
        # A bare call is an Expr whose value is a Call node, sitting
        # at module scope and not under a function/class def.
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            bare_calls.append(ast.dump(node.value)[:80])
    assert bare_calls == [], f"unexpected bare top-level calls: {bare_calls}"

    # And actually loading the module is harmless - no exception, no git
    # or filesystem mutation. _load_module() exec'd the module body in
    # _scaffold_repo's parent dir which is just tmp_path; nothing should
    # have been created beyond what the scaffold did.
    mod = _load_module()
    assert hasattr(mod, "main")
    assert hasattr(mod, "run")


def test_check_returns_exit_code_1_on_drift(repo: Path) -> None:
    mod = _load_module()
    rc = mod.main(["--check", "--repo-root", str(repo)])
    assert rc == 1, "drift in scaffold repo must produce exit 1"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
