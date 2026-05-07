"""
Tests that verify gate-side and ACK-CLI-side dirty tree fingerprint output
binds bit-for-bit on the same git working tree.

Background: before consolidation, the two implementations had drifted:
  - lane taxonomy (16 lanes vs 7)
  - path_sha256 input (sorted raw porcelain lines vs sorted unique paths)
  - content_sha256 algorithm (status+size+per-file sha vs path+SKIP marker)
  - dirty_entries count (raw lines vs unique paths)
  - status_counts keying (raw porcelain XY vs canonicalised single-char)
  - --untracked-files=all flag (gate uses it, CLI omitted it)

The result: ``operator_ack_signoff.py --all --commit`` would emit a YAML
that the production deploy gate then rejected with
``dirty_fingerprint_mismatch`` issues — operators stalled at 4/5 PASS.

After consolidation, both call into
``scripts/ops/repo_dirty_lane_report.compute_canonical_dirty_fingerprint``.
This test exercises 5 realistic synthetic dirty trees and asserts the gate
helper (``production_deploy_go_gate._dirty_tree_fingerprint``), the canonical
SOT helper, and the operator-side CLI module all return the same fingerprint
on the same commit.

Run:
  pytest tests/test_dirty_fingerprint_consistency.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
GATE_DIR = REPO_ROOT / "scripts" / "ops"
CLI_SCRIPT = REPO_ROOT / "tools" / "offline" / "operator_review" / "compute_dirty_fingerprint.py"
CLI_DIR = CLI_SCRIPT.parent

# Make both gate-side and CLI-side modules importable in-process.
for d in (str(GATE_DIR), str(CLI_DIR)):
    if d not in sys.path:
        sys.path.insert(0, d)

# Imports below depend on the sys.path inserts above.
import compute_dirty_fingerprint as cdf  # noqa: E402
import production_deploy_go_gate as gate  # noqa: E402
import repo_dirty_lane_report as sot  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


def _seed_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("seed\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")


def _commit_baseline(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", "baseline")


def _gate_lines(repo: Path) -> list[str]:
    """Mimic the gate's _git_status helper without subprocess gymnastics."""
    return sot.collect_status_lines(repo)


def _cli_via_subprocess(repo: Path) -> dict:
    """Invoke the operator-side CLI exactly as operator_ack_signoff.py does."""
    proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), "--repo", str(repo), "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


# Ignore fields that legitimately differ (e.g., evidence-only fields the
# gate adds but the ACK YAML doesn't echo) when comparing fingerprints.
GATE_REQUIRED_FIELDS = (
    "current_head",
    "dirty_entries",
    "status_counts",
    "lane_counts",
    "path_sha256",
    "content_sha256",
    "content_hash_skipped_large_files",
)


def _compare(fp_a: dict, fp_b: dict) -> None:
    for field in GATE_REQUIRED_FIELDS:
        assert field in fp_a, f"missing field {field} on left"
        assert field in fp_b, f"missing field {field} on right"
        assert fp_a[field] == fp_b[field], (
            f"fingerprint drift on {field}: {fp_a[field]!r} != {fp_b[field]!r}"
        )


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "case_clean"
    _seed_repo(repo)
    return repo


@pytest.fixture
def dirty_repo_modified(tmp_path: Path) -> Path:
    """Modified tracked files across runtime / billing / migrations lanes."""
    repo = tmp_path / "case_modified"
    _seed_repo(repo)
    _commit_baseline(
        repo,
        {
            "src/jpintel_mcp/api/programs.py": "v1\n",
            "src/jpintel_mcp/billing/stripe_client.py": "v1\n",
            "scripts/migrations/100_add.sql": "-- v1\n",
        },
    )
    # Modify each in-place
    (repo / "src/jpintel_mcp/api/programs.py").write_text("v2\n")
    (repo / "src/jpintel_mcp/billing/stripe_client.py").write_text("v2\n")
    (repo / "scripts/migrations/100_add.sql").write_text("-- v2\n")
    return repo


@pytest.fixture
def dirty_repo_untracked(tmp_path: Path) -> Path:
    """Mix of untracked files spanning workflows, root_release_files, docs."""
    repo = tmp_path / "case_untracked"
    _seed_repo(repo)
    files = {
        ".github/workflows/ci.yml": "name: ci\n",
        "pyproject.toml": "[project]\n",
        "docs/_internal/notes.md": "x\n",
        "scripts/cron/foo.py": "print(1)\n",
    }
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return repo


@pytest.fixture
def dirty_repo_deleted(tmp_path: Path) -> Path:
    """Deleted tracked files (force the <deleted-or-not-file> branch)."""
    repo = tmp_path / "case_deleted"
    _seed_repo(repo)
    _commit_baseline(
        repo,
        {
            "src/jpintel_mcp/mcp/server.py": "old\n",
            "scripts/etl/translate.py": "old\n",
        },
    )
    (repo / "src/jpintel_mcp/mcp/server.py").unlink()
    (repo / "scripts/etl/translate.py").unlink()
    return repo


@pytest.fixture
def dirty_repo_renamed(tmp_path: Path) -> Path:
    """A staged rename across two lanes (old in cron_etl_ops, new in runtime_code)."""
    repo = tmp_path / "case_renamed"
    _seed_repo(repo)
    _commit_baseline(repo, {"scripts/cron/old_name.py": "x\n"})
    # git mv refuses to create intermediate directories; pre-create the parent
    (repo / "src" / "jpintel_mcp" / "api").mkdir(parents=True, exist_ok=True)
    _git(repo, "mv", "scripts/cron/old_name.py", "src/jpintel_mcp/api/new_name.py")
    return repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    [
        "clean_repo",
        "dirty_repo_modified",
        "dirty_repo_untracked",
        "dirty_repo_deleted",
        "dirty_repo_renamed",
    ],
)
def test_gate_and_sot_helper_agree(fixture_name: str, request: pytest.FixtureRequest) -> None:
    """Gate's _dirty_tree_fingerprint and SOT helper produce identical output."""
    repo: Path = request.getfixturevalue(fixture_name)
    lines = _gate_lines(repo)
    fp_gate = gate._dirty_tree_fingerprint(repo, lines)
    fp_sot = sot.compute_canonical_dirty_fingerprint(repo, lines)
    _compare(fp_gate, fp_sot)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "dirty_repo_modified",
        "dirty_repo_untracked",
        "dirty_repo_deleted",
        "dirty_repo_renamed",
    ],
)
def test_cli_module_and_gate_agree_in_process(
    fixture_name: str, request: pytest.FixtureRequest
) -> None:
    """The in-process CLI module and the gate produce identical output."""
    repo: Path = request.getfixturevalue(fixture_name)
    fp_cli = cdf.compute_fingerprint(repo)
    lines = _gate_lines(repo)
    fp_gate = gate._dirty_tree_fingerprint(repo, lines)
    _compare(fp_cli, fp_gate)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "dirty_repo_modified",
        "dirty_repo_untracked",
        "dirty_repo_renamed",
    ],
)
def test_cli_subprocess_and_gate_agree(fixture_name: str, request: pytest.FixtureRequest) -> None:
    """Subprocess invocation (the operator_ack_signoff.py pathway) matches the gate."""
    repo: Path = request.getfixturevalue(fixture_name)
    fp_cli = _cli_via_subprocess(repo)
    lines = _gate_lines(repo)
    fp_gate = gate._dirty_tree_fingerprint(repo, lines)
    _compare(fp_cli, fp_gate)


def test_lane_taxonomy_is_16_lanes() -> None:
    """The CLI's classify_lane shim must return values inside the 16-lane SOT."""
    # Spot-check the SOT 16-lane classifier (see repo_dirty_lane_report.classify_path).
    # Note: ``src/jpintel_mcp/billing/`` is _not_ under api/ or mcp/, so the SOT
    # falls through to the generic ``src/`` rule and lands on ``runtime_code``.
    # Only billing modules embedded in the api/mcp surfaces flip to
    # ``billing_auth_security`` (see ``api/_audit_seal.py`` etc.).
    cases = [
        ("src/jpintel_mcp/api/programs.py", "runtime_code"),
        ("src/jpintel_mcp/api/billing.py", "billing_auth_security"),
        ("src/jpintel_mcp/api/audit_seal_handler.py", "billing_auth_security"),
        ("src/jpintel_mcp/billing/stripe_client.py", "runtime_code"),
        ("scripts/migrations/100_add.sql", "migrations"),
        ("scripts/cron/foo.py", "cron_etl_ops"),
        ("scripts/etl/foo.py", "cron_etl_ops"),
        ("scripts/ops/foo.py", "cron_etl_ops"),
        ("tests/test_x.py", "tests"),
        (".github/workflows/ci.yml", "workflows"),
        ("docs/_internal/notes.md", "internal_docs"),
        ("docs/something.md", "public_docs"),
        ("tools/offline/operator_review/foo.py", "operator_offline"),
        ("benchmarks/x.py", "benchmarks_monitoring"),
        ("data/snapshot.db", "data_or_local_seed"),
        ("pyproject.toml", "root_release_files"),
        ("README.md", "root_release_files"),
        ("uv.lock", "root_release_files"),
    ]
    for path, expected in cases:
        actual = cdf.classify_lane(path)
        assert actual == expected, f"{path} -> {actual} != {expected}"
        # Same answer must come from the SOT directly.
        assert sot.classify_path(path) == expected
