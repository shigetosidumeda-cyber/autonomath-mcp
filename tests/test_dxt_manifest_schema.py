"""DXT manifest schema validation gate.

Validates ``dxt/manifest.json`` against the Anthropic Desktop Extension
(DXT) schema spec at https://desktop.anthropic.com/dxt-schema.

The DXT manifest is a public-distribution surface (shipped inside the
``.mcpb`` bundle and consumed by Claude Desktop on install). A malformed
manifest silently breaks the extension store listing or installation —
the failure mode is "user sees nothing", not a stack trace, so we gate
shape + types + cross-manifest version agreement at CI time.

Scope (per DXT spec § Required fields):

* ``dxt_version`` — DXT schema revision. Spec says int; live manifest
  ships ``"0.1"`` (string). Both are tolerated by the official validator,
  so we accept either shape and only fail if missing/empty.
* ``name`` — package identifier (str, non-empty).
* ``display_name`` — human title (str, non-empty).
* ``version`` — semver (str, ``MAJOR.MINOR.PATCH`` shape).
* ``description`` — short description (str, non-empty).
* ``author.name`` — author display name (str, non-empty).
* ``server.type`` — runtime kind, one of ``{"node", "python", "binary"}``.
* ``server.entry_point`` — runtime entry (str, non-empty).
* ``server.mcp_config`` — Claude Desktop MCP launch config (object).

Cross-manifest version agreement:

* ``manifest.version`` must equal ``pyproject.toml [project].version``.
  This is independently gated by ``test_manifest_version_triple_match``,
  but we re-assert here so that running this single test file is
  sufficient to catch DXT-specific drift without depending on the H12
  gate being in the same suite.

Smoke check on ``server.entry_point``:

* For ``server.type == "python"`` the entry_point can legally be either
  a file path (e.g. ``server/main.py``) or a console-script name
  registered in ``pyproject.toml [project.scripts]``. Live manifest uses
  the console-script form (``autonomath-mcp``), so the smoke check
  tolerates both: the test passes if the entry_point resolves as a file
  on disk OR as a registered console-script name in pyproject.
* For ``server.type == "node"`` / ``"binary"`` the entry_point is
  expected to resolve as a file path on disk.

Read-only: this gate never edits ``dxt/manifest.json``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "dxt" / "manifest.json"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

ALLOWED_SERVER_TYPES = {"node", "python", "binary"}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+([-+].+)?$")


def _load_manifest() -> dict:
    """Parse the DXT manifest. Skips the suite if file is absent."""

    if not MANIFEST_PATH.exists():
        pytest.skip(f"{MANIFEST_PATH}: not present in this checkout")
    try:
        return json.loads(MANIFEST_PATH.read_text("utf-8"))
    except json.JSONDecodeError as e:
        pytest.fail(f"{MANIFEST_PATH}: JSON parse error: {e}")


def _parse_pyproject_version() -> str:
    """Hand-parse ``[project].version`` from ``pyproject.toml``.

    Mirrors ``test_manifest_version_triple_match._parse_pyproject_version``
    (intentionally re-implemented here so this gate can run standalone
    without importing the H12 helpers).
    """

    text = PYPROJECT_PATH.read_text("utf-8")
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
            if "#" in value:
                value = value.split("#", 1)[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                return value[1:-1]
            return value
    raise RuntimeError("pyproject.toml has no [project].version declaration")


def _pyproject_console_scripts() -> set[str]:
    """Return the set of console-script names declared under
    ``[project.scripts]`` in ``pyproject.toml``.

    Hand-parsed (no ``tomllib`` import) so this gate runs under whatever
    Python the operator happens to invoke pytest with.
    """

    text = PYPROJECT_PATH.read_text("utf-8")
    in_scripts = False
    names: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_scripts = line == "[project.scripts]"
            continue
        if not in_scripts:
            continue
        if not line or line.startswith("#"):
            continue
        # ``foo-bar = "module:fn"`` -> key="foo-bar"
        if "=" in line:
            key = line.split("=", 1)[0].strip()
            # strip optional quotes around the key (rare but legal in TOML)
            if len(key) >= 2 and key[0] == key[-1] and key[0] in ("'", '"'):
                key = key[1:-1]
            if key:
                names.add(key)
    return names


@pytest.fixture(scope="module")
def manifest() -> dict:
    return _load_manifest()


# --- Required-field presence + type checks --------------------------------


def test_manifest_is_a_json_object(manifest: dict) -> None:
    """Top-level manifest must parse as a JSON object (dict)."""

    assert isinstance(manifest, dict), f"{MANIFEST_PATH}: top-level JSON is not an object"


def test_dxt_version_present(manifest: dict) -> None:
    """``dxt_version`` is the DXT schema revision marker.

    Spec lists it as int; the live Anthropic validator also accepts the
    string form (``"0.1"``). We accept either shape and only fail on
    missing / empty / wrong-type values.
    """

    value = manifest.get("dxt_version")
    assert value is not None, "dxt_version is missing"
    assert isinstance(value, (int, str)), (
        f"dxt_version must be int or str, got {type(value).__name__}"
    )
    if isinstance(value, str):
        assert value.strip(), "dxt_version is an empty string"


def test_name_present_and_string(manifest: dict) -> None:
    name = manifest.get("name")
    assert isinstance(name, str) and name, f"name must be a non-empty string, got {name!r}"


def test_display_name_present_and_string(manifest: dict) -> None:
    display_name = manifest.get("display_name")
    assert isinstance(display_name, str) and display_name, (
        f"display_name must be a non-empty string, got {display_name!r}"
    )


def test_version_is_semver(manifest: dict) -> None:
    """``version`` must look like ``MAJOR.MINOR.PATCH`` (+ optional pre/build)."""

    version = manifest.get("version")
    assert isinstance(version, str) and version, (
        f"version must be a non-empty string, got {version!r}"
    )
    assert SEMVER_RE.match(version), (
        f"version {version!r} is not semver-shaped (expected MAJOR.MINOR.PATCH)"
    )


def test_description_present_and_string(manifest: dict) -> None:
    desc = manifest.get("description")
    assert isinstance(desc, str) and desc, f"description must be a non-empty string, got {desc!r}"


def test_author_name_present(manifest: dict) -> None:
    """``author`` must be an object with a non-empty ``name`` field."""

    author = manifest.get("author")
    assert isinstance(author, dict), f"author must be an object, got {type(author).__name__}"
    author_name = author.get("name")
    assert isinstance(author_name, str) and author_name, (
        f"author.name must be a non-empty string, got {author_name!r}"
    )


def test_server_block_present(manifest: dict) -> None:
    server = manifest.get("server")
    assert isinstance(server, dict), f"server must be an object, got {type(server).__name__}"


def test_server_type_is_allowed(manifest: dict) -> None:
    server = manifest.get("server") or {}
    server_type = server.get("type")
    assert server_type in ALLOWED_SERVER_TYPES, (
        f"server.type={server_type!r} not in {sorted(ALLOWED_SERVER_TYPES)}"
    )


def test_server_entry_point_present(manifest: dict) -> None:
    server = manifest.get("server") or {}
    entry_point = server.get("entry_point")
    assert isinstance(entry_point, str) and entry_point, (
        f"server.entry_point must be a non-empty string, got {entry_point!r}"
    )


def test_server_mcp_config_is_object(manifest: dict) -> None:
    """``server.mcp_config`` must be a (potentially empty) JSON object."""

    server = manifest.get("server") or {}
    mcp_config = server.get("mcp_config")
    assert isinstance(mcp_config, dict), (
        f"server.mcp_config must be an object, got {type(mcp_config).__name__}"
    )


# --- Cross-manifest version agreement -------------------------------------


def test_version_matches_pyproject(manifest: dict) -> None:
    """``manifest.version`` must equal ``pyproject.toml [project].version``.

    Independently re-asserted here even though
    ``test_manifest_version_triple_match`` (H12) also gates this — so
    that running ``pytest tests/test_dxt_manifest_schema.py`` in
    isolation is sufficient to catch DXT-specific drift.
    """

    manifest_version = manifest.get("version")
    pyproject_version = _parse_pyproject_version()
    assert manifest_version == pyproject_version, (
        f"dxt/manifest.json version={manifest_version!r} does not match "
        f"pyproject.toml [project].version={pyproject_version!r}"
    )


# --- Smoke check: entry_point resolves to a file or registered script -----


def test_entry_point_smoke_resolves(manifest: dict) -> None:
    """``server.entry_point`` must resolve.

    For ``python`` servers the entry_point is legally either:

    * a file path relative to ``dxt/`` or the repo root, OR
    * a console-script name registered in pyproject ``[project.scripts]``.

    For ``node`` / ``binary`` servers the entry_point is expected to be a
    file path on disk.
    """

    server = manifest.get("server") or {}
    server_type = server.get("type")
    entry_point = server.get("entry_point")
    assert isinstance(entry_point, str) and entry_point, (
        "server.entry_point missing (caught by an earlier test)"
    )

    # Candidate file paths: relative to dxt/, relative to repo root.
    candidates = [
        MANIFEST_PATH.parent / entry_point,
        REPO_ROOT / entry_point,
    ]
    resolves_as_file = any(p.exists() for p in candidates)

    if server_type == "python":
        scripts = _pyproject_console_scripts()
        resolves_as_console_script = entry_point in scripts
        assert resolves_as_file or resolves_as_console_script, (
            f"server.entry_point={entry_point!r} does not resolve to a file "
            f"(tried {[str(p) for p in candidates]}) and is not a registered "
            f"console-script in pyproject.toml [project.scripts] (known: "
            f"{sorted(scripts)})"
        )
    else:
        assert resolves_as_file, (
            f"server.entry_point={entry_point!r} (type={server_type!r}) does "
            f"not resolve to a file on disk; tried {[str(p) for p in candidates]}"
        )
