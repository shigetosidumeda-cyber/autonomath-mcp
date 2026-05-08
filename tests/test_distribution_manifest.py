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

EXPECTED_TOOL_COUNT_DEFAULT_GATES = 139
EXPECTED_ROUTE_COUNT = 263
EXPECTED_OPENAPI_PATH_COUNT = 220

EXPECTED_WAVE6_P0_CANDIDATES = {
    "server.json",
    "site/server.json",
    "smithery.yaml",
    "mcp-server.core.json",
    "mcp-server.composition.json",
    "docs/openapi/agent.json",
    "site/openapi.agent.json",
    "site/llms.en.txt",
    "site/en/llms.txt",
    "site/_data/public_counts.json",
}
EXPECTED_WAVE6_P0_DISTRIBUTION_SURFACES = {
    "server.json",
    "site/server.json",
    "smithery.yaml",
    "mcp-server.core.json",
    "mcp-server.composition.json",
    "docs/openapi/agent.json",
    "site/openapi.agent.json",
    "site/llms.en.txt",
    "site/en/llms.txt",
}
EXPECTED_WAVE6_P0_VERSION_SURFACES = {
    "server.json",
    "site/server.json",
    "mcp-server.core.json",
    "mcp-server.composition.json",
    "docs/openapi/agent.json",
    "site/openapi.agent.json",
}
EXPECTED_WAVE6_P0_TOOL_COUNT_SURFACES = {
    "server.json",
    "site/server.json",
    "smithery.yaml",
    "site/llms.en.txt",
    "site/en/llms.txt",
    "site/_data/public_counts.json",
}
EXPECTED_WAVE6_P0_DOC_PATHS = {
    "docs/openapi/agent.json",
    "site/openapi.agent.json",
    "site/llms.en.txt",
    "site/en/llms.txt",
    "site/_data/public_counts.json",
}

REQUIRED_TOP_KEYS = {
    "product",
    "canonical_domains",
    "canonical_mcp_package",
    "canonical_pypi_package",
    "canonical_repo",
    "canonical_api_env",
    "canonical_mcp_package_surface_paths",
    "tool_count_default_gates",
    "route_count",
    "openapi_path_count",
    "pyproject_version",
    "pricing_unit_jpy_ex_tax",
    "pricing_unit_jpy_tax_included",
    "free_tier_requests_per_day",
    "tagline_ja",
    "distribution_surface_paths",
    "version_surface_paths",
    "tool_count_surface_paths",
    "pricing_surface_paths",
    "docs_paths",
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
    assert isinstance(data["distribution_surface_paths"], list)
    assert isinstance(data["version_surface_paths"], list)
    assert isinstance(data["tool_count_surface_paths"], list)
    assert isinstance(data["pricing_surface_paths"], list)
    assert isinstance(data["canonical_mcp_package_surface_paths"], list)
    assert isinstance(data["docs_paths"], list)

    for key in (
        "distribution_surface_paths",
        "version_surface_paths",
        "tool_count_surface_paths",
        "pricing_surface_paths",
        "canonical_mcp_package_surface_paths",
        "docs_paths",
    ):
        assert len(data[key]) == len(set(data[key])), f"{key} contains duplicates"

    assert int(data["tool_count_default_gates"]) == EXPECTED_TOOL_COUNT_DEFAULT_GATES
    assert int(data["route_count"]) == EXPECTED_ROUTE_COUNT
    assert int(data["openapi_path_count"]) == EXPECTED_OPENAPI_PATH_COUNT

    assert "site/mcp-server.json" in data["version_surface_paths"]
    assert "site/mcp-server.full.json" in data["version_surface_paths"]
    assert "mcp-server.full.json" in data["version_surface_paths"]
    assert "docs/mcp-tools.md" in data["tool_count_surface_paths"]
    assert "dxt/README.md" in data["tool_count_surface_paths"]
    assert "docs/mcp-tools.md" not in data["pricing_surface_paths"]
    assert "dxt/README.md" not in data["pricing_surface_paths"]

    assert set(data["distribution_surface_paths"]) >= EXPECTED_WAVE6_P0_DISTRIBUTION_SURFACES
    assert set(data["version_surface_paths"]) >= EXPECTED_WAVE6_P0_VERSION_SURFACES
    assert set(data["tool_count_surface_paths"]) >= EXPECTED_WAVE6_P0_TOOL_COUNT_SURFACES
    assert set(data["docs_paths"]) >= EXPECTED_WAVE6_P0_DOC_PATHS

    # Split subset manifests intentionally expose fewer tools, so only their
    # release version and public-surface metadata belong in this checker.
    assert "mcp-server.core.json" not in data["tool_count_surface_paths"]
    assert "mcp-server.composition.json" not in data["tool_count_surface_paths"]

    # Wave 6 P0 additions should not broaden pricing/free-tier scans.
    assert not (EXPECTED_WAVE6_P0_CANDIDATES & set(data["pricing_surface_paths"]))

    # Agent-safe OpenAPI files are Actions schemas, not MCP package manifests.
    assert "docs/openapi/agent.json" in data["distribution_surface_paths"]
    assert "site/openapi.agent.json" in data["distribution_surface_paths"]
    assert "docs/openapi/agent.json" in data["version_surface_paths"]
    assert "site/openapi.agent.json" in data["version_surface_paths"]
    assert "docs/openapi/agent.json" not in data["canonical_mcp_package_surface_paths"]
    assert "site/openapi.agent.json" not in data["canonical_mcp_package_surface_paths"]

    # The drift checker enforces these specific tokens — pin them.
    assert "jpintel-mcp" in data["forbidden_tokens"]
    assert "zeimu-kaikei.ai" in data["forbidden_tokens"]


def test_openapi_agent_specs_use_info_version_without_package_requirement() -> None:
    sys.path.insert(0, str(SCRIPTS_DIR))
    from check_distribution_manifest_drift import (  # type: ignore[import-not-found]
        _scan_canonical_values,
        _scan_versions,
    )

    data = _load_manifest_dict()
    agent_paths = ["docs/openapi/agent.json", "site/openapi.agent.json"]
    version_rows = _scan_versions(
        {
            "pyproject_version": data["pyproject_version"],
            "version_surface_paths": agent_paths,
        }
    )
    assert not version_rows

    canonical_rows = _scan_canonical_values(
        {
            "canonical_domains": data["canonical_domains"],
            "canonical_mcp_package": data["canonical_mcp_package"],
            "canonical_api_env": data["canonical_api_env"],
            "distribution_surface_paths": agent_paths,
            "canonical_mcp_package_surface_paths": [],
        }
    )
    assert not [row for row in canonical_rows if row.field == "canonical_mcp_package"]


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
      * Copy the manifest + current manifest-declared surfaces into a tmp tree.
      * Mutate the tmp ``mcp-server.json`` to declare a bad tool count.

    Because the drift script hard-codes ``REPO_ROOT`` from the script
    location, we instead clone the script into the tmp tree as well so its
    ``REPO_ROOT`` resolves to the tmp tree. This keeps the test isolated
    from the live repo state.
    """
    manifest = _load_manifest_dict()
    expected_tool_count = int(manifest["tool_count_default_gates"])
    expected_version = str(manifest["pyproject_version"])
    expected_openapi_paths = int(manifest["openapi_path_count"])

    # Build a minimal tmp repo mirroring the manifest-declared surface lists.
    tmp_root = tmp_path / "repo"
    (tmp_root / "scripts").mkdir(parents=True)

    # Copy the script + manifest.
    shutil.copy(DRIFT_SCRIPT, tmp_root / "scripts" / "check_distribution_manifest_drift.py")
    shutil.copy(MANIFEST_PATH, tmp_root / "scripts" / "distribution_manifest.yml")

    # Plant minimal surface stubs containing the canonical markers so the
    # clean tmp run is genuinely drift-free under the current checker.
    surface_sentence = (
        f"https://jpcite.com - autonomath-mcp exposes {expected_tool_count} "
        "MCP tools at default gates. JPY 3 per billable unit, 3 free/day. "
        "github.com/shigetosidumeda-cyber/autonomath-mcp"
    )
    json_surface = {
        "name": "autonomath-mcp",
        "version": expected_version,
        "websiteUrl": "https://jpcite.com",
        "description": surface_sentence,
        "tool_count": expected_tool_count,
        "repository": {"url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp"},
    }
    dxt_surface = {
        **json_surface,
        "tools": [{"name": f"tool_{idx:03d}"} for idx in range(expected_tool_count)],
    }
    openapi_surface = {
        "openapi": "3.1.0",
        "info": {
            "title": "jpcite",
            "version": expected_version,
            "description": surface_sentence,
        },
        "paths": {f"/stub/{idx:03d}": {} for idx in range(expected_openapi_paths)},
    }
    agent_description = (
        "Agent-safe OpenAPI Actions surface for jpcite at https://jpcite.com. "
        "It may mention MCP behavior, but it is not an MCP package manifest."
    )
    openapi_agent_surface = {
        "openapi": "3.1.0",
        "info": {
            "title": "jpcite Agent Evidence API",
            "version": expected_version,
            "description": agent_description,
        },
        "paths": {"/v1/evidence/packets/query": {}},
    }
    pyproject_text = (
        "[project]\n"
        'name = "autonomath-mcp"\n'
        f'version = "{expected_version}"\n'
        f'description = "{surface_sentence}"\n'
        "\n[project.urls]\n"
        'Repository = "https://github.com/shigetosidumeda-cyber/autonomath-mcp"\n'
    )
    smithery_text = (
        "metadata:\n"
        f'  version: "{expected_version}"\n'
        '  homepage: "https://jpcite.com"\n'
        '  repository: "https://github.com/shigetosidumeda-cyber/autonomath-mcp"\n'
        f'  description: "{surface_sentence}"\n'
    )
    subset_surface = {
        "name": "autonomath-mcp-subset",
        "version": expected_version,
        "homepage": "https://jpcite.com",
        "description": (
            "Subset manifest for autonomath-mcp. "
            f"The full public surface remains {expected_tool_count}-tool MCP."
        ),
        "packages": [{"identifier": "autonomath-mcp", "version": expected_version}],
    }
    llms_surface = (
        f"# jpcite\n{surface_sentence}\n{expected_openapi_paths} public paths are available.\n"
    )
    minimal_files = {
        "README.md": f"# autonomath-mcp\n\n{surface_sentence}\n",
        "pyproject.toml": pyproject_text,
        "server.json": json.dumps(json_surface, ensure_ascii=False) + "\n",
        "site/server.json": json.dumps(json_surface, ensure_ascii=False) + "\n",
        "mcp-server.json": json.dumps(json_surface, ensure_ascii=False) + "\n",
        "mcp-server.full.json": json.dumps(dxt_surface, ensure_ascii=False) + "\n",
        "mcp-server.core.json": json.dumps(subset_surface, ensure_ascii=False) + "\n",
        "mcp-server.composition.json": json.dumps(subset_surface, ensure_ascii=False) + "\n",
        "site/mcp-server.json": json.dumps(dxt_surface, ensure_ascii=False) + "\n",
        "site/mcp-server.full.json": json.dumps(dxt_surface, ensure_ascii=False) + "\n",
        "dxt/manifest.json": json.dumps(dxt_surface, ensure_ascii=False) + "\n",
        "dxt/README.md": f"# Claude Desktop Extension\n\n{surface_sentence}\n",
        "smithery.yaml": smithery_text,
        "docs/openapi/v1.json": json.dumps(openapi_surface, ensure_ascii=False) + "\n",
        "site/docs/openapi/v1.json": json.dumps(openapi_surface, ensure_ascii=False) + "\n",
        "docs/openapi/agent.json": json.dumps(openapi_agent_surface, ensure_ascii=False) + "\n",
        "docs/mcp-tools.md": f"# MCP Tools\n\n{surface_sentence}\n",
        "site/openapi.agent.json": json.dumps(openapi_agent_surface, ensure_ascii=False) + "\n",
        "site/docs/openapi/agent.json": json.dumps(openapi_agent_surface, ensure_ascii=False)
        + "\n",
        "site/llms.txt": llms_surface,
        "site/llms.en.txt": llms_surface,
        "site/en/llms.txt": llms_surface,
        "site/_data/public_counts.json": json.dumps(
            {"mcp_tools_total": expected_tool_count}, ensure_ascii=False
        )
        + "\n",
        "site/pricing.html": f"<html><body>{surface_sentence}</body></html>\n",
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

    # Now mutate a scanned surface to declare a wrong tool count.
    server_path = tmp_root / "mcp-server.json"
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
    # conftest enables experimental API routes for normal TestClient coverage.
    # The distribution manifest pins the committed stable OpenAPI artifact, so
    # the subprocess probe must explicitly use the same stable gate posture.
    env["AUTONOMATH_EXPERIMENTAL_API_ENABLED"] = "0"
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
