"""Tests for the manifest-version drift gate in `scripts/check_mcp_drift.py`.

Backs the R4 audit P0-1 fix (2026-05-13): `mcp-server.full.json`,
`mcp-server.composition.json`, `mcp-server.core.json` (and their `site/`
mirrors) carried `"version": "0.3.5"` while `pyproject.toml`, `server.json`,
`dxt/manifest.json`, `smithery.yaml`, `mcp-server.json`,
`site/server.json`, `site/mcp-server.json` were already `0.4.0`. The previous
`check_mcp_drift.py` only validated tool counts so the divergence slipped
past the release gate.

Test plan:

  1. `_pyproject_version()` reads `[project].version` correctly.
  2. Every manifest in `VERSION_MANIFESTS` that exists on disk matches the
     `pyproject.toml` version both at the top level and (where applicable)
     at every `packages[].version` mirror.
  3. A synthetic 0.3.5 drift introduced into a tmp copy of one manifest
     causes `_check_manifest_versions` to append a fail row — the new gate
     must actually fail when drift is present.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
DRIFT_SCRIPT = SCRIPTS_DIR / "check_mcp_drift.py"


def _load_module():
    """Import `scripts/check_mcp_drift.py` without triggering venv re-exec.

    The script eagerly calls `_maybe_reexec_venv()` at import time; flipping
    the `JPCITE_NO_VENV_REEXEC` env var (which the script honours) keeps us
    in-process so we can poke the helpers directly.
    """

    import os

    os.environ["JPCITE_NO_VENV_REEXEC"] = "1"
    spec = importlib.util.spec_from_file_location("_check_mcp_drift_under_test", DRIFT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def drift_module():
    return _load_module()


def test_pyproject_version_parses(drift_module) -> None:
    version = drift_module._pyproject_version()
    assert isinstance(version, str)
    assert version  # non-empty
    # Sanity: must look like a semver-ish triple (e.g. "0.4.0"). The gate's
    # job is detecting drift, not policing version shape, but a missing dot
    # here would indicate a parsing regression.
    assert version.count(".") >= 1


def test_live_manifest_versions_agree_with_pyproject(drift_module) -> None:
    """The repo on disk must pass the new drift gate.

    Catches both the original R4 P0-1 finding and any future re-introduction
    of the same drift shape.
    """

    fails: list[str] = []
    drift_module._check_manifest_versions(fails)
    assert fails == [], "manifest version drift detected vs pyproject.toml: " + "; ".join(fails)


def test_drift_gate_catches_synthetic_regression(
    drift_module, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A synthetic 0.3.5 in any one manifest must trip the gate.

    Copies the live repo's pyproject.toml + manifest set into tmp, mutates
    one manifest (`mcp-server.full.json`) back to 0.3.5, and asserts the
    gate emits a failure that names the regressed file.
    """

    # Mirror pyproject + every manifest listed in VERSION_MANIFESTS into tmp.
    (tmp_path / "pyproject.toml").write_text(
        (REPO_ROOT / "pyproject.toml").read_text("utf-8"), encoding="utf-8"
    )
    for rel in drift_module.VERSION_MANIFESTS:
        src = REPO_ROOT / rel
        if not src.exists():
            continue
        dest = tmp_path / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    target_rel = "mcp-server.full.json"
    target_path = tmp_path / target_rel
    assert target_path.exists(), "fixture manifest missing in tmp copy"
    spec = json.loads(target_path.read_text("utf-8"))
    spec["version"] = "0.3.5"
    # Also drift any packages[].version mirror so the gate is exercised on
    # both axes; if only the top-level is mutated, the test still passes,
    # but mutating both reflects the real-world R4 finding.
    for pkg in spec.get("packages", []) or []:
        if isinstance(pkg, dict) and "version" in pkg:
            pkg["version"] = "0.3.5"
    target_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), "utf-8")

    monkeypatch.setattr(drift_module, "ROOT", tmp_path)
    fails: list[str] = []
    drift_module._check_manifest_versions(fails)
    assert fails, "drift gate failed to catch synthetic 0.3.5 regression"
    assert any(target_rel in row and "0.3.5" in row for row in fails), (
        "drift fail row does not name the regressed file or value: " + str(fails)
    )


def test_version_manifests_list_covers_known_public_surfaces(drift_module) -> None:
    """Guard against accidentally dropping a manifest from the gate.

    If a future refactor renames or removes one of these surfaces, this
    test will fail loudly so the gate keeps covering the full release set.
    """

    listed = set(drift_module.VERSION_MANIFESTS)
    must_cover = {
        "server.json",
        "site/server.json",
        "mcp-server.json",
        "mcp-server.full.json",
        "mcp-server.core.json",
        "mcp-server.composition.json",
        "dxt/manifest.json",
    }
    missing = must_cover - listed
    assert not missing, f"VERSION_MANIFESTS lost coverage: {sorted(missing)}"


# Make sure module-state side effects (sys.path injection from the drift
# script) do not leak into other tests.
@pytest.fixture(autouse=True)
def _restore_sys_path():
    before = list(sys.path)
    yield
    sys.path[:] = before
