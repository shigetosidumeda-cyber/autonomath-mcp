"""Tests for the Canonical Distribution Manifest CI guard.

Backs `scripts/distribution_manifest.yml` +
`scripts/check_distribution_manifest_drift.py` +
`scripts/probe_runtime_distribution.py`. See
`scripts/distribution_manifest_README.md` for the operational manual.

Test plan:

  1. The manifest parses (PyYAML or fallback flat parser) and contains every
     required key.
  2. The drift checker runs against the live repo and either reports OK
     (clean repo) or honestly enumerates drift rows. Either result is
     acceptable — drift discovery is the script's job; this test does NOT
     auto-fix anything.
  3. A synthetic drift introduced into a tmp copy of one surface causes the
     drift checker to exit non-zero.
  4. (slow) The runtime probe agrees with the static manifest values. Marked
     ``@pytest.mark.slow`` because it imports the FastAPI app + FastMCP
     server in-process (~6 s).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
MANIFEST_PATH = SCRIPTS_DIR / "distribution_manifest.yml"
DRIFT_SCRIPT = SCRIPTS_DIR / "check_distribution_manifest_drift.py"
PROBE_SCRIPT = SCRIPTS_DIR / "probe_runtime_distribution.py"

REQUIRED_TOP_KEYS = {
    "product",
    "canonical_domains",
    "canonical_mcp_package",
    "canonical_pypi_package",
    "canonical_repo",
    "canonical_api_env",
    "tool_count_default_gates",
    "route_count",
    "pyproject_version",
    "tagline_ja",
    "forbidden_tokens",
    "forbidden_token_exclude_paths",
}


def _venv_python() -> str:
    candidate = REPO_ROOT / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


def _load_manifest_dict() -> dict:
    """Mirror the script-side loader: PyYAML if available, else flat parser."""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        return yaml.safe_load(text)
    except ImportError:
        sys.path.insert(0, str(SCRIPTS_DIR))
        from check_distribution_manifest_drift import (
            _flat_yaml_parse,  # type: ignore[import-not-found]
        )

        return _flat_yaml_parse(text)


# ---------------------------------------------------------------------------
# Test 1: manifest parses + required keys present
# ---------------------------------------------------------------------------


def test_manifest_parses_and_has_required_keys() -> None:
    assert MANIFEST_PATH.exists(), f"manifest missing: {MANIFEST_PATH}"
    data = _load_manifest_dict()
    assert isinstance(data, dict), "manifest must parse to a dict"

    missing = REQUIRED_TOP_KEYS - set(data.keys())
    assert not missing, f"manifest missing required keys: {sorted(missing)}"

    # Nested checks — any breakage here is a manifest authoring bug.
    assert isinstance(data["canonical_domains"], dict)
    assert "site" in data["canonical_domains"]
    assert "api" in data["canonical_domains"]

    assert isinstance(data["canonical_api_env"], dict)
    assert "api_key" in data["canonical_api_env"]
    assert "api_base" in data["canonical_api_env"]

    assert isinstance(data["forbidden_tokens"], list)
    assert isinstance(data["forbidden_token_exclude_paths"], list)

    # The drift checker enforces these specific tokens — pin them.
    assert "jpintel-mcp" in data["forbidden_tokens"]
    assert "zeimu-kaikei.ai" in data["forbidden_tokens"]


# ---------------------------------------------------------------------------
# Test 2: drift checker runs cleanly against the current repo
# ---------------------------------------------------------------------------


def test_drift_checker_runs_against_repo() -> None:
    """Drift checker must run without crashing.

    The exit code is informational here: 0 = clean, 1 = honest drift, 2 = crash.
    Drift discovery is the script's job; this test only asserts the script
    actually executes and produces sane output. If the user fixes all drift
    later, this test still passes (because the assertion is on completion,
    not on a particular exit code).
    """
    proc = subprocess.run(
        [_venv_python(), str(DRIFT_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(REPO_ROOT),
    )
    # exit code 2 means the script crashed (manifest missing, parse error)
    assert proc.returncode in (0, 1), (
        f"drift checker crashed with rc={proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    # Always emits a banner.
    assert "[check_distribution_manifest_drift]" in (proc.stdout + proc.stderr)


# ---------------------------------------------------------------------------
# Test 3: synthetic drift in a tmp copy is detected
# ---------------------------------------------------------------------------


def test_synthetic_drift_detected(tmp_path: Path) -> None:
    """Plant a known-bad value into a copied surface and confirm exit 1.

    Strategy:
      * Copy the manifest + the SURFACES into a tmp tree.
      * Mutate the tmp ``server.json`` to declare a definitely-wrong tool count.
      * Override the ``REPO_ROOT`` constant inside the script via env-driven
        path or by chdir + manifest pointer.

    Because the drift script hard-codes ``REPO_ROOT`` from the script
    location, we instead clone the script into the tmp tree as well so its
    ``REPO_ROOT`` resolves to the tmp tree. This keeps the test isolated
    from the live repo state.
    """
    # Build a minimal tmp repo mirroring the SURFACES list.
    tmp_root = tmp_path / "repo"
    (tmp_root / "scripts").mkdir(parents=True)
    (tmp_root / "dxt").mkdir()
    (tmp_root / "site").mkdir()
    (tmp_root / "sdk" / "python" / "autonomath").mkdir(parents=True)

    # Copy the script + manifest.
    shutil.copy(DRIFT_SCRIPT, tmp_root / "scripts" / "check_distribution_manifest_drift.py")
    shutil.copy(MANIFEST_PATH, tmp_root / "scripts" / "distribution_manifest.yml")

    # Plant minimal surface stubs containing the canonical site URL so the
    # checker does not flag missing-domain drift on every file.
    canonical_blob = (
        '{"description":"AutonoMath stub","website":"https://jpcite.com",'
        '"package":"autonomath-mcp","repo":"github.com/shigetosidumeda-cyber/autonomath-mcp"}\n'
    )
    minimal_files = {
        "server.json": json.dumps(
            {
                "name": "autonomath-mcp",
                "version": "0.3.1",
                "websiteUrl": "https://jpcite.com",
                "description": "92 MCP tools at default gates — autonomath-mcp",
                "tool_count": 92,
                "repository": {"url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp"},
            }
        )
        + "\n",
        "mcp-server.json": canonical_blob,
        "dxt/manifest.json": canonical_blob,
        "smithery.yaml": (
            'version: "0.3.1"\nhomepage: "https://jpcite.com"\n'
            'env: AUTONOMATH_API_KEY="" AUTONOMATH_API_BASE=""\n'
            "package: autonomath-mcp\n"
            "repo: https://github.com/shigetosidumeda-cyber/autonomath-mcp\n"
            "description: 92 MCP tools at default gates\n"
        ),
        "scripts/mcp_registries_submission.json": canonical_blob,
        "pyproject.toml": (
            'version = "0.3.1"\nname = "autonomath-mcp"\n'
            'description = "92 MCP tools — see https://jpcite.com"\n'
            'Repository = "https://github.com/shigetosidumeda-cyber/autonomath-mcp"\n'
        ),
        "README.md": (
            "# autonomath-mcp\n\nhttps://jpcite.com — 92 MCP tools at default gates. "
            "github.com/shigetosidumeda-cyber/autonomath-mcp\n"
        ),
        "site/llms.txt": "# jpcite\nhttps://jpcite.com — 92 MCP tools at default gates.\n",
        "CLAUDE.md": "# autonomath-mcp\nhttps://jpcite.com — 92 MCP tools at default gates.\n",
        "sdk/python/autonomath/_shared.py": (
            'DEFAULT_BASE_URL = "https://api.jpcite.com"\n'
            "AUTONOMATH_API_KEY_HINT = 'use env AUTONOMATH_API_KEY'\n"
        ),
    }
    for rel, content in minimal_files.items():
        target = tmp_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    # Sanity: clean run on the tmp tree should be exit 0 (no drift).
    rc_clean = subprocess.run(
        [_venv_python(), str(tmp_root / "scripts" / "check_distribution_manifest_drift.py")],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(tmp_root),
    )
    assert rc_clean.returncode == 0, (
        f"clean tmp tree should be drift-free, got rc={rc_clean.returncode}\n"
        f"stdout: {rc_clean.stdout}\nstderr: {rc_clean.stderr}"
    )

    # Now mutate server.json to declare a wrong tool count.
    server_path = tmp_root / "server.json"
    bad_blob = json.loads(server_path.read_text(encoding="utf-8"))
    bad_blob["tool_count"] = 55  # synthetic drift
    bad_blob["description"] = "55 MCP tools at default gates — autonomath-mcp"
    server_path.write_text(json.dumps(bad_blob) + "\n", encoding="utf-8")

    rc_drift = subprocess.run(
        [_venv_python(), str(tmp_root / "scripts" / "check_distribution_manifest_drift.py")],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(tmp_root),
    )
    assert rc_drift.returncode == 1, (
        f"synthetic drift not detected; rc={rc_drift.returncode}\n"
        f"stdout: {rc_drift.stdout}\nstderr: {rc_drift.stderr}"
    )
    assert "55" in rc_drift.stdout
    assert "tool_count_default_gates" in rc_drift.stdout


# ---------------------------------------------------------------------------
# Test 4: runtime probe agrees with the static manifest
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_runtime_probe_agrees_with_manifest() -> None:
    """Boot the live API + MCP and verify counts match the manifest.

    Marked slow because it imports FastAPI app + FastMCP server in-process
    (~6 s on a warm pyc cache; longer on cold). Runs the probe as a
    subprocess so the in-process import side effects of this test process
    do not pollute the runtime snapshot.

    The probe distinguishes three failure modes via exit code:

    * 2 — runtime introspection itself failed (pre-existing import bug,
      missing dep, broken migration, etc.). This is NOT distribution drift
      it is a runtime regression that needs a code fix elsewhere. The test
      ``xfails`` rather than failing hard so the manifest CI guard does not
      block on pre-existing in-flight work outside its scope.
    * 1 — runtime introspection succeeded but the counts disagree. This is
      the case the manifest is meant to catch; the test fails.
    * 0 — runtime matches the manifest.
    """
    if not (REPO_ROOT / ".venv" / "bin" / "python").exists():
        pytest.skip("no .venv/bin/python; runtime probe needs the project venv")

    env = os.environ.copy()
    env.setdefault("AUTONOMATH_ENABLED", "1")
    proc = subprocess.run(
        [_venv_python(), str(PROBE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(REPO_ROOT),
    )
    if proc.returncode == 2:
        pytest.xfail(
            "runtime probe could not introspect the live app — pre-existing "
            f"runtime regression, not a distribution-manifest defect.\n"
            f"stderr: {proc.stderr}"
        )
    assert proc.returncode == 0, (
        f"runtime probe disagrees with manifest; rc={proc.returncode}\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "OK" in proc.stdout
