"""H12 independent pytest gate: manifest version consistency across ALL manifests.

This test asserts that EVERY public-distribution manifest reports the same
version string as ``pyproject.toml`` ``[project] version`` — both at the
top-level ``version`` field and at every nested ``packages[].version`` mirror
(server.json / mcp-server*.json families).

Background: B2 + F8 already gate this in ``scripts/check_mcp_drift.py``
(via ``_check_manifest_versions``).  H12 adds an **independent** pytest
gate that does **not** import ``check_mcp_drift`` so a regression in that
script — or accidental deletion of an entry from its
``VERSION_MANIFESTS`` list — cannot silently mask manifest drift.

The 2026-05-13 R4 audit P0-1 finding (``mcp-server.full.json`` /
``mcp-server.composition.json`` / ``mcp-server.core.json`` left at 0.3.5
while everything else moved to 0.4.0) is exactly the failure shape this
gate forbids.

Manifest set (read-only):

  * ``pyproject.toml`` (the SOT — its ``[project].version`` is the
    reference value).
  * ``server.json`` + ``site/server.json``
    (top-level ``version`` + ``packages[].version`` mirrors).
  * ``mcp-server.json`` + ``mcp-server.full.json`` + ``mcp-server.core.json``
    + ``mcp-server.composition.json`` (root + ``site/`` mirrors when present)
    (top-level ``version`` + ``packages[].version`` mirrors where they
    exist).
  * ``dxt/manifest.json`` (top-level ``version``).
  * ``smithery.yaml`` (``metadata.version`` — string-scraped, no PyYAML
    dependency to keep this gate cheap and import-light).

Missing files are SKIPPED, not failed, so this gate keeps working in
partial-checkout / packaging-strip scenarios.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


# Every JSON manifest whose ``version`` (top-level and any nested
# ``packages[].version`` mirror) must equal the pyproject ``[project].version``.
JSON_MANIFESTS: list[str] = [
    "server.json",
    "site/server.json",
    "mcp-server.json",
    "mcp-server.full.json",
    "mcp-server.core.json",
    "mcp-server.composition.json",
    "site/mcp-server.json",
    "site/mcp-server.full.json",
    "site/mcp-server.core.json",
    "site/mcp-server.composition.json",
    "dxt/manifest.json",
]

# YAML manifest — string-scraped (``metadata.version: "..."``) rather than
# parsed via PyYAML so this gate doesn't impose an extra import.
YAML_MANIFESTS: list[str] = [
    "smithery.yaml",
]


def _parse_pyproject_version() -> str:
    """Read the canonical version from ``pyproject.toml`` ``[project].version``.

    Hand-parsed (string-search) rather than via ``tomllib`` so this test
    runs under any Python the operator happens to invoke pytest with.
    The B2/F8 drift checker uses the same shape; H12 keeps an independent
    implementation so a regression in one parser doesn't mask the other.
    """

    text = (REPO_ROOT / "pyproject.toml").read_text("utf-8")
    in_project = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if not in_project:
            continue
        if line.startswith("version") and "=" in line:
            value = line.split("=", 1)[1].strip()
            # Strip a trailing inline comment (``version = "0.4.0"  # foo``)
            if "#" in value:
                value = value.split("#", 1)[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                return value[1:-1]
            return value
    raise RuntimeError("pyproject.toml has no [project].version declaration")


def _scrape_smithery_version(text: str) -> str | None:
    """Return the ``metadata.version`` string from ``smithery.yaml`` text.

    Looks for a top-level ``metadata:`` block then the first ``version:``
    under it.  Returns ``None`` if no match — caller decides whether that's
    a fail or a skip.  Quote-tolerant: handles ``version: "0.4.0"`` /
    ``version: '0.4.0'`` / ``version: 0.4.0``.
    """

    # Match the metadata block + the first version key indented under it.
    # ``metadata:`` is expected at column 0; ``version:`` indented by any
    # whitespace.  Anchored to start-of-line to avoid hitting nested
    # ``version:`` keys under unrelated blocks.
    in_metadata = False
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if not raw.startswith((" ", "\t")):  # back at column 0
            in_metadata = raw.rstrip().rstrip(":") == "metadata"
            continue
        if not in_metadata:
            continue
        m = re.match(r"version\s*:\s*(.+?)\s*(?:#.*)?$", stripped)
        if m:
            value = m.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            return value
    return None


@pytest.fixture(scope="module")
def pyproject_version() -> str:
    return _parse_pyproject_version()


def test_pyproject_version_is_parseable() -> None:
    """The SOT itself must parse to a non-empty semver-ish string.

    Guards against an accidental rewrite of ``pyproject.toml`` that drops
    the ``[project].version`` line or moves it under another section.
    """

    version = _parse_pyproject_version()
    assert isinstance(version, str)
    assert version, "pyproject.toml [project].version is empty"
    # Loose shape check: must look like a semver triple (``0.4.0``-ish).
    # The gate's job is detecting drift, not policing version shape, but a
    # missing dot here means the parser hit something it shouldn't have.
    assert version.count(".") >= 1, f"version {version!r} not semver-shaped"


@pytest.mark.parametrize("rel_path", JSON_MANIFESTS)
def test_json_manifest_version_matches_pyproject(
    rel_path: str, pyproject_version: str
) -> None:
    """Every JSON manifest must agree with pyproject at both axes.

    1. Top-level ``version`` (must exist and match).
    2. Every nested ``packages[].version`` mirror (must match if present).

    Missing manifest files SKIP rather than fail — partial checkouts and
    packaging strips remain valid.
    """

    path = REPO_ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path}: not present in this checkout")

    try:
        spec = json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError as e:
        pytest.fail(f"{rel_path}: JSON parse error: {e}")

    assert isinstance(spec, dict), f"{rel_path}: top-level JSON is not an object"

    top_version = spec.get("version")
    assert top_version == pyproject_version, (
        f"{rel_path}: top-level version={top_version!r} does not match "
        f"pyproject.toml [project].version={pyproject_version!r}"
    )

    packages = spec.get("packages")
    if isinstance(packages, list):
        for idx, pkg in enumerate(packages):
            if not isinstance(pkg, dict):
                continue
            pkg_version = pkg.get("version")
            if pkg_version is None:
                # ``packages[].version`` is optional in some schemas;
                # don't gate on absence.
                continue
            assert pkg_version == pyproject_version, (
                f"{rel_path}: packages[{idx}].version={pkg_version!r} "
                f"does not match pyproject.toml [project].version="
                f"{pyproject_version!r}"
            )


@pytest.mark.parametrize("rel_path", YAML_MANIFESTS)
def test_yaml_manifest_version_matches_pyproject(
    rel_path: str, pyproject_version: str
) -> None:
    """``smithery.yaml`` ``metadata.version`` must agree with pyproject.

    Scraped (no PyYAML import) to keep this gate cheap.  Skips when the
    file isn't present in the checkout.
    """

    path = REPO_ROOT / rel_path
    if not path.exists():
        pytest.skip(f"{rel_path}: not present in this checkout")

    text = path.read_text("utf-8")
    version = _scrape_smithery_version(text)
    assert version is not None, (
        f"{rel_path}: could not locate metadata.version (string scrape returned None)"
    )
    assert version == pyproject_version, (
        f"{rel_path}: metadata.version={version!r} does not match "
        f"pyproject.toml [project].version={pyproject_version!r}"
    )


def test_at_least_one_manifest_is_present() -> None:
    """Defensive: if EVERY manifest is missing the gate would silently
    pass via all-skips.  Assert at least one JSON manifest exists on disk.
    """

    present = [rel for rel in JSON_MANIFESTS if (REPO_ROOT / rel).exists()]
    assert present, (
        "no JSON manifest from the gate set is present on disk — this looks "
        "like a partial checkout that would let drift slip through silently"
    )
