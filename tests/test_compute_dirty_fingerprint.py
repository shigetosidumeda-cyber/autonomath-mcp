"""
Tests for compute_dirty_fingerprint.

8 cases (DEEP-56 spec §7 acceptance + spec §10 constraint compliance):
  1. 7-field coverage
  2. lane classification accuracy across 7 lanes
  3. >10 MB file is recorded in content_hash_skipped_large_files
  4. SHA256 reproducibility (same dirty state -> same hashes)
  5. parallel hashing thread safety (16-worker == 1-worker output)
  6. format switch (json <-> yaml) emits same 7 fields
  7. LLM API import count = 0 (regex grep over source)
  8. speed budget — 821 synthetic entries hash in < 60 s

Run:
  pytest test_compute_dirty_fingerprint.py -v
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
SCRIPT_DIR = REPO_ROOT / "tools" / "offline" / "operator_review"
SCRIPT = SCRIPT_DIR / "compute_dirty_fingerprint.py"

# Make the script importable for in-process tests
sys.path.insert(0, str(SCRIPT_DIR))

import compute_dirty_fingerprint as cdf  # noqa: E402

REQUIRED_FIELDS = [
    "current_head",
    "dirty_entries",
    "status_counts",
    "lane_counts",
    "path_sha256",
    "content_sha256",
    "content_hash_skipped_large_files",
]

# Lanes the canonical SOT classifier (16-lane taxonomy in
# scripts/ops/repo_dirty_lane_report.classify_path) is allowed to emit. The
# operator-side fingerprint must mirror the gate's lane vocabulary so the
# `dirty_fingerprint_mismatch:lane_counts` issue stays at zero — see
# tests/test_dirty_fingerprint_consistency.py for the bit-for-bit lock-in.
ALLOWED_LANES = {
    "runtime_code",
    "billing_auth_security",
    "migrations",
    "cron_etl_ops",
    "tests",
    "workflows",
    "generated_public_site",
    "openapi_distribution",
    "sdk_distribution",
    "public_docs",
    "internal_docs",
    "operator_offline",
    "benchmarks_monitoring",
    "data_or_local_seed",
    "root_release_files",
    "misc_review",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> Path:
    """Build a tiny git repo with 1 file per lane + an 'other' fallback."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")

    # First commit — clean baseline
    (repo / "README.md").write_text("seed\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "seed")

    # Now create dirty entries — one per lane
    files = {
        "src/jpintel_mcp/billing/stripe.py": "billing\n",
        "src/jpintel_mcp/api/routes.py": "runtime\n",
        "scripts/migrations/123_add.sql": "-- mig\n",
        "scripts/cron/refresh.py": "cron\n",
        ".github/workflows/ci.yml": "name: ci\n",
        "pyproject.toml": "[project]\n",
        "docs/some_other_doc.md": "other\n",
    }
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    return repo


@pytest.fixture
def synthetic_repo_with_large(tmp_path: Path) -> Path:
    """Synthetic repo with one untracked file above the SOT skip threshold.

    The canonical helper in ``scripts/ops/repo_dirty_lane_report`` uses
    64 MiB as the threshold (matches the gate's
    ``_dirty_tree_fingerprint``). We generate a 65 MiB sparse blob so the
    skip branch fires.
    """
    repo = tmp_path / "repo_large"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("x\n")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")

    big = repo / "big_blob.bin"
    # 65 MiB sparse-style — slightly above the 64 MiB SOT threshold.
    with big.open("wb") as fh:
        fh.truncate(65 * 1024 * 1024)

    (repo / "small.txt").write_text("hi\n")
    return repo


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_01_seven_field_coverage(synthetic_repo: Path) -> None:
    """All 7 required fields appear in the output."""
    fp = cdf.compute_fingerprint(synthetic_repo)
    for field in REQUIRED_FIELDS:
        assert field in fp, f"missing field {field}"
    # current_head is full 40-char sha1
    assert isinstance(fp["current_head"], str) and len(fp["current_head"]) == 40
    assert isinstance(fp["dirty_entries"], int) and fp["dirty_entries"] >= 1
    assert isinstance(fp["status_counts"], dict)
    assert isinstance(fp["lane_counts"], dict)
    assert isinstance(fp["path_sha256"], str) and len(fp["path_sha256"]) == 64
    assert isinstance(fp["content_sha256"], str) and len(fp["content_sha256"]) == 64
    assert isinstance(fp["content_hash_skipped_large_files"], list)


def test_02_lane_classification(synthetic_repo: Path) -> None:
    """Each synthetic dirty path lands in the correct lane (canonical SOT)."""
    fp = cdf.compute_fingerprint(synthetic_repo)

    # Every emitted lane must be in the SOT 16-lane vocabulary.
    assert set(fp["lane_counts"].keys()).issubset(ALLOWED_LANES)

    # Sum equals dirty_entries
    assert sum(fp["lane_counts"].values()) == fp["dirty_entries"]

    # Spot-check via classify_lane on individual paths. The SOT classifier
    # only flags `billing_auth_security` for paths under
    # `src/jpintel_mcp/api/` or `src/jpintel_mcp/mcp/` that include billing /
    # auth / middleware keywords — `src/jpintel_mcp/billing/...` itself
    # falls through to the generic `src/` rule and lands on `runtime_code`.
    cases = [
        ("src/jpintel_mcp/api/billing.py", "billing_auth_security"),
        ("src/jpintel_mcp/api/anon_limit.py", "billing_auth_security"),
        ("src/jpintel_mcp/api/origin_enforcement.py", "billing_auth_security"),
        ("src/jpintel_mcp/api/idempotency.py", "billing_auth_security"),
        ("src/jpintel_mcp/api/audit_seal.py", "billing_auth_security"),
        ("src/jpintel_mcp/billing/stripe.py", "runtime_code"),
        ("src/jpintel_mcp/middleware/cors.py", "runtime_code"),
        ("src/jpintel_mcp/api/routes.py", "runtime_code"),
        ("src/jpintel_mcp/mcp/server.py", "runtime_code"),
        ("src/jpintel_mcp/tools/foo.py", "runtime_code"),
        ("src/jpintel_mcp/ingest/bar.py", "runtime_code"),
        ("src/jpintel_mcp/misc.py", "runtime_code"),
        ("scripts/migrations/123_add.sql", "migrations"),
        ("scripts/cron/refresh.py", "cron_etl_ops"),
        ("scripts/etl/translate.py", "cron_etl_ops"),
        ("scripts/ops/refresh_sources.py", "cron_etl_ops"),
        ("tests/test_things.py", "tests"),
        (".github/workflows/ci.yml", "workflows"),
        ("pyproject.toml", "root_release_files"),
        ("smithery.yaml", "sdk_distribution"),
        ("dxt/manifest.json", "sdk_distribution"),
        ("mcp-server.json", "sdk_distribution"),
        ("server.json", "sdk_distribution"),
        ("CHANGELOG.md", "misc_review"),
        ("uv.lock", "root_release_files"),
        ("docs/_internal/notes.md", "internal_docs"),
        ("docs/anything.md", "public_docs"),
        ("data/snapshot.db", "data_or_local_seed"),
        ("README.md", "root_release_files"),
    ]
    for path, expected in cases:
        assert cdf.classify_lane(path) == expected, (
            f"{path} -> {cdf.classify_lane(path)} != {expected}"
        )


def test_03_large_file_skip(synthetic_repo_with_large: Path) -> None:
    """A file above the SOT threshold lands in ``content_hash_skipped_large_files``.

    ``path_sha256`` must still account for the file so the path manifest
    stays exhaustive even when the content hash collapses to a marker.
    """
    fp = cdf.compute_fingerprint(synthetic_repo_with_large)
    skipped = fp["content_hash_skipped_large_files"]
    assert "big_blob.bin" in skipped
    # small.txt is also dirty but must NOT be in the skip list
    assert "small.txt" not in skipped

    # path_sha256 = sha256 of "\n".join(sorted raw porcelain lines) per SOT.
    import sys as _sys

    _sys.path.insert(0, str(SCRIPT.parent.parent.parent / "scripts" / "ops"))
    from repo_dirty_lane_report import collect_status_lines  # noqa: E402

    raw_lines = collect_status_lines(synthetic_repo_with_large)
    expected_path_sha = hashlib.sha256("\n".join(sorted(raw_lines)).encode("utf-8")).hexdigest()
    assert fp["path_sha256"] == expected_path_sha


def test_04_reproducibility(synthetic_repo: Path) -> None:
    """Two consecutive runs over the same working tree match on path/content sha256."""
    fp1 = cdf.compute_fingerprint(synthetic_repo)
    fp2 = cdf.compute_fingerprint(synthetic_repo)
    assert fp1["path_sha256"] == fp2["path_sha256"]
    assert fp1["content_sha256"] == fp2["content_sha256"]
    assert fp1["lane_counts"] == fp2["lane_counts"]
    assert fp1["status_counts"] == fp2["status_counts"]


def test_05_parallel_thread_safety(synthetic_repo: Path) -> None:
    """16-worker run matches 1-worker run on path/content sha256."""
    fp1 = cdf.compute_fingerprint(synthetic_repo, workers=1)
    fp16 = cdf.compute_fingerprint(synthetic_repo, workers=16)
    assert fp1["path_sha256"] == fp16["path_sha256"]
    assert fp1["content_sha256"] == fp16["content_sha256"]
    assert fp1["content_hash_skipped_large_files"] == fp16["content_hash_skipped_large_files"]


def test_06_format_switch(synthetic_repo: Path) -> None:
    """JSON and YAML serialisations carry identical 7 fields."""
    fp = cdf.compute_fingerprint(synthetic_repo)
    j = cdf.dump_json(fp)
    parsed_j = json.loads(j)
    for field in REQUIRED_FIELDS:
        assert field in parsed_j

    try:
        import yaml  # type: ignore
    except ImportError:
        pytest.skip("PyYAML not installed")
    y = cdf.dump_yaml(fp)
    parsed_y = yaml.safe_load(y)
    for field in REQUIRED_FIELDS:
        assert field in parsed_y
    assert parsed_j == parsed_y


def test_07_no_llm_api_imports() -> None:
    """Source must have zero LLM API / paid-API imports."""
    src = SCRIPT.read_text(encoding="utf-8")
    forbidden = re.compile(
        r"\b(anthropic|openai|google\.generativeai|claude_agent_sdk)\b|"
        r"requests\.(get|post)|httpx\.(get|post|AsyncClient)",
        re.IGNORECASE,
    )
    matches = [m.group(0) for m in forbidden.finditer(src)]
    assert matches == [], f"forbidden import/call found: {matches}"


def test_08_speed_budget(tmp_path: Path) -> None:
    """821 synthetic dirty entries hash in <60 s."""
    repo = tmp_path / "speed_repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n")
    _git(repo, "add", "seed.txt")
    _git(repo, "commit", "-q", "-m", "seed")

    # 821 untracked files distributed across the 7 lanes
    template_dirs = [
        "src/jpintel_mcp/billing",
        "src/jpintel_mcp/api/auth",
        "src/jpintel_mcp/middleware",
        "src/jpintel_mcp/api",
        "src/jpintel_mcp/mcp",
        "src/jpintel_mcp/tools",
        "src/jpintel_mcp/ingest",
        "scripts/migrations",
        "scripts/cron",
        "scripts/etl",
        ".github/workflows",
        "docs/auto",
    ]
    # Create one tracked seed file per dir so git lists untracked siblings
    # individually instead of summarising the whole directory as one entry.
    for d in template_dirs:
        (repo / d).mkdir(parents=True, exist_ok=True)
        seed = repo / d / ".gitkeep"
        seed.write_text("")
        _git(repo, "add", str(seed.relative_to(repo)))
    _git(repo, "commit", "-q", "-m", "scaffold")

    payload = b"# synthetic dirty entry\n" * 32  # ~768 bytes per file
    n = 821
    for i in range(n):
        d = template_dirs[i % len(template_dirs)]
        (repo / d / f"f_{i:04d}.txt").write_bytes(payload)

    start = time.perf_counter()
    fp = cdf.compute_fingerprint(repo, workers=8)
    elapsed = time.perf_counter() - start

    assert fp["dirty_entries"] == n
    assert sum(fp["lane_counts"].values()) == n
    assert elapsed < 60.0, f"speed budget exceeded: {elapsed:.2f}s > 60s"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
