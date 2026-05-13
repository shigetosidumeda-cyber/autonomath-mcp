"""Schema validation for ``smithery.yaml`` (Smithery MCP-server registry manifest).

Smithery (https://smithery.ai) is an MCP-server registry. The repo ships
``smithery.yaml`` so the jpcite MCP server can be listed there. This test
gates the manifest's structural correctness, version sync with
``pyproject.toml``, and the existence of the command-function backing
module — without editing the manifest itself.

Required fields validated:

  * ``metadata.name``         (accepts top-level ``name`` / ``qualifiedName``
                               as fallback — Smithery treats either as the
                               package identity)
  * ``metadata.version``      (must match ``pyproject.toml [project.version]``)
  * ``metadata.description``
  * Start contract — at least one of:
      - ``commands.start``                                    (legacy form)
      - ``startCommand.type`` + ``startCommand.commandFunction``
      - ``startCommand.type`` + top-level ``commandFunction``  (current form)
  * ``configuration.properties`` / ``configSchema.properties`` (only when
    the manifest declares any config knobs — Smithery accepts either key)

The smoke check additionally asserts the module backing the launched
binary (``autonomath-mcp`` console script → ``jpintel_mcp.mcp.server``)
resolves under ``importlib`` so the start contract isn't aimed at a
phantom module.

The test prefers PyYAML when available and falls back to a flat
string-scrape parser (mirroring the pattern in
``tests/test_distribution_manifest.py`` + ``tests/test_manifest_version_triple_match.py``)
so the gate keeps working in minimal CI envs.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SMITHERY_PATH = REPO_ROOT / "smithery.yaml"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

# Console script registered in `pyproject.toml [project.scripts]`:
#     autonomath-mcp = "jpintel_mcp.mcp.server:run"
# The Smithery start contract resolves to `uvx autonomath-mcp`, which in
# turn imports this module. If the module ever disappears the manifest is
# pointing at a phantom.
COMMAND_FUNCTION_MODULE = "jpintel_mcp.mcp.server"


# --------------------------------------------------------------------- #
# Loader                                                                #
# --------------------------------------------------------------------- #


def _load_smithery() -> dict:
    """Return the parsed manifest dict.

    Prefers PyYAML; falls back to a permissive flat parser so the test
    runs in minimal pytest CI envs that don't ship PyYAML.
    """
    text = SMITHERY_PATH.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        data = yaml.safe_load(text)
        assert isinstance(data, dict), "smithery.yaml top-level must be a mapping"
        return data
    except ImportError:
        return _fallback_parse(text)


def _fallback_parse(text: str) -> dict:
    """Permissive scraper for the subset of keys this test inspects.

    Recognises the top-level keys, the nested ``metadata.*`` /
    ``startCommand.*`` blocks, and the ``configSchema.properties`` /
    ``configuration.properties`` mapping. Multi-line literal/folded
    scalars are collapsed to a single string. Sufficient to drive every
    assertion below — not a general YAML reimplementation.
    """
    out: dict = {}
    current_top: str | None = None
    current_props: str | None = None  # 'configSchema' or 'configuration'
    in_metadata = False
    in_startcommand = False
    in_properties = False
    current_property: str | None = None
    pending_multiline_key: tuple[str | None, str] | None = None
    multiline_indent: int | None = None
    multiline_buf: list[str] = []

    def _flush_multiline() -> None:
        nonlocal pending_multiline_key, multiline_indent, multiline_buf
        if pending_multiline_key is None:
            return
        scope, key = pending_multiline_key
        joined = " ".join(s.strip() for s in multiline_buf if s.strip())
        if scope is None:
            out[key] = joined
        else:
            out.setdefault(scope, {})[key] = joined
        pending_multiline_key = None
        multiline_indent = None
        multiline_buf = []

    for raw_line in text.splitlines():
        # strip trailing comments outside quotes (cheap heuristic)
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            # blank/comment line breaks multiline collection only if the
            # next non-blank line dedents below the multiline indent
            continue

        stripped = line.lstrip()
        indent = len(line) - len(stripped)

        # multiline scalar accumulation
        if pending_multiline_key is not None:
            if multiline_indent is None:
                multiline_indent = indent
            if indent >= (multiline_indent or 0) and not stripped.endswith(":"):
                multiline_buf.append(stripped)
                continue
            _flush_multiline()
            # fall through to re-parse this line

        # detect top-level (zero-indent) keys
        if indent == 0:
            in_metadata = False
            in_startcommand = False
            in_properties = False
            current_props = None
            current_property = None
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", stripped)
            if not m:
                continue
            key, rest = m.group(1), m.group(2).strip()
            current_top = key
            if key == "metadata":
                in_metadata = True
                out.setdefault("metadata", {})
                continue
            if key == "startCommand":
                in_startcommand = True
                out.setdefault("startCommand", {})
                continue
            if key in ("configSchema", "configuration"):
                current_props = key
                out.setdefault(key, {})
                continue
            if rest == "" or rest == "|-" or rest == "|" or rest == ">-" or rest == ">":
                pending_multiline_key = (None, key)
                multiline_indent = None
                multiline_buf = []
                continue
            out[key] = _strip_quotes(rest)
            continue

        # nested key handling
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", stripped)
        if not m:
            continue
        key, rest = m.group(1), m.group(2).strip()

        if in_metadata:
            if rest in ("", "|-", "|", ">-", ">"):
                pending_multiline_key = ("metadata", key)
                multiline_indent = None
                multiline_buf = []
                continue
            out["metadata"][key] = _strip_quotes(rest)
            continue

        if in_startcommand:
            out["startCommand"][key] = _strip_quotes(rest)
            continue

        if current_props is not None:
            # nested: properties: <indent>+ name: { type: ..., description: ... }
            if key == "properties" and rest == "":
                in_properties = True
                out[current_props].setdefault("properties", {})
                continue
            if key == "required":
                # not load-bearing for this test
                continue
            if key == "type" and not in_properties:
                out[current_props]["type"] = _strip_quotes(rest)
                continue
            if in_properties:
                # heuristic: a property name line is one whose value is empty
                # and whose indent puts it under `properties:`
                if rest == "":
                    current_property = key
                    out[current_props]["properties"].setdefault(current_property, {})
                    continue
                if current_property is not None:
                    out[current_props]["properties"][current_property][key] = (
                        _strip_quotes(rest)
                    )
                continue

        # top-level continuation block (e.g. `commandFunction: |-` body)
        if current_top is not None and indent > 0:
            continue

    _flush_multiline()
    return out


def _strip_quotes(value: str) -> str:
    """Trim surrounding ASCII quotes from a YAML scalar fragment."""
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        return v[1:-1]
    return v


# --------------------------------------------------------------------- #
# pyproject helpers                                                     #
# --------------------------------------------------------------------- #


def _pyproject_version() -> str:
    """Read `[project] version` from pyproject.toml without importing tomllib edges."""
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = stripped == "[project]"
            continue
        if in_project:
            m = re.match(r'^version\s*=\s*"([^"]+)"\s*$', stripped)
            if m:
                return m.group(1)
    raise AssertionError("pyproject.toml [project] version not found")


# --------------------------------------------------------------------- #
# Fixtures                                                              #
# --------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert SMITHERY_PATH.exists(), f"smithery.yaml missing at {SMITHERY_PATH}"
    return _load_smithery()


# --------------------------------------------------------------------- #
# Tests                                                                 #
# --------------------------------------------------------------------- #


def test_manifest_file_present_and_nonempty() -> None:
    """smithery.yaml exists with non-trivial content."""
    assert SMITHERY_PATH.is_file(), f"missing {SMITHERY_PATH}"
    size = SMITHERY_PATH.stat().st_size
    assert size > 100, f"smithery.yaml suspiciously small ({size} bytes)"


def test_metadata_block_present(manifest: dict) -> None:
    """``metadata`` block exists and is a mapping."""
    assert "metadata" in manifest, "missing top-level 'metadata' block"
    assert isinstance(manifest["metadata"], dict), (
        "smithery.yaml 'metadata' must be a mapping"
    )


def test_metadata_name_present(manifest: dict) -> None:
    """``metadata.name`` (or top-level ``name``/``qualifiedName``) is set.

    Smithery accepts either: many published manifests put the identity at
    top-level (``name`` / ``qualifiedName``) and reserve ``metadata`` for
    display/descriptive fields. We accept either layout.
    """
    md = manifest.get("metadata", {})
    candidates = [
        md.get("name"),
        manifest.get("name"),
        manifest.get("qualifiedName"),
        manifest.get("id"),
    ]
    name = next((c for c in candidates if isinstance(c, str) and c.strip()), None)
    assert name, (
        "smithery.yaml must declare a name via metadata.name, top-level name, "
        "qualifiedName, or id"
    )


def test_metadata_version_present(manifest: dict) -> None:
    """``metadata.version`` is a non-empty string."""
    md = manifest.get("metadata", {})
    version = md.get("version")
    assert isinstance(version, str) and version.strip(), (
        "smithery.yaml metadata.version must be a non-empty string"
    )


def test_metadata_version_matches_pyproject(manifest: dict) -> None:
    """``metadata.version`` agrees with ``pyproject.toml [project] version``.

    Drift here breaks the registry — Smithery shows a version that doesn't
    match the actual PyPI release.
    """
    smithery_version = manifest["metadata"]["version"].strip()
    pyproject_version = _pyproject_version().strip()
    assert smithery_version == pyproject_version, (
        f"smithery.yaml metadata.version ({smithery_version!r}) != "
        f"pyproject.toml [project] version ({pyproject_version!r})"
    )


def test_metadata_description_present(manifest: dict) -> None:
    """``metadata.description`` is a non-trivial string."""
    md = manifest.get("metadata", {})
    description = md.get("description")
    assert isinstance(description, str), (
        "smithery.yaml metadata.description must be a string"
    )
    assert len(description.strip()) >= 20, (
        f"smithery.yaml metadata.description suspiciously short "
        f"({len(description.strip())} chars)"
    )


def test_start_command_contract(manifest: dict) -> None:
    """Manifest declares a runnable start contract.

    Accepts either Smithery layout:
      * ``commands.start`` (legacy YAML schema)
      * ``startCommand.type`` + ``startCommand.commandFunction`` (nested)
      * ``startCommand.type`` + top-level ``commandFunction`` (current jpcite layout)
    """
    commands = manifest.get("commands")
    has_commands_start = (
        isinstance(commands, dict)
        and isinstance(commands.get("start"), (str, dict))
        and (
            commands["start"].strip()
            if isinstance(commands.get("start"), str)
            else commands["start"]
        )
    )

    start_command = manifest.get("startCommand", {})
    has_startcommand_pair = (
        isinstance(start_command, dict)
        and isinstance(start_command.get("type"), str)
        and start_command["type"].strip()
        and (
            (
                isinstance(start_command.get("commandFunction"), str)
                and start_command["commandFunction"].strip()
            )
            or (
                isinstance(manifest.get("commandFunction"), str)
                and manifest["commandFunction"].strip()
            )
        )
    )

    assert has_commands_start or has_startcommand_pair, (
        "smithery.yaml must declare commands.start OR "
        "(startCommand.type + commandFunction)"
    )


def test_config_properties_well_formed(manifest: dict) -> None:
    """``configSchema.properties`` / ``configuration.properties`` is a mapping when present.

    Both keys are optional under Smithery — only fail if a config block
    exists but its ``properties`` is malformed.
    """
    for block_key in ("configuration", "configSchema"):
        block = manifest.get(block_key)
        if block is None:
            continue
        assert isinstance(block, dict), (
            f"smithery.yaml {block_key} must be a mapping when present"
        )
        properties = block.get("properties")
        if properties is None:
            # block exists with no properties — Smithery allows this (e.g.
            # `required: []` plus an empty `properties:`). Treat as OK.
            continue
        assert isinstance(properties, dict), (
            f"smithery.yaml {block_key}.properties must be a mapping"
        )
        for prop_name, prop_value in properties.items():
            assert isinstance(prop_name, str) and prop_name.strip(), (
                f"smithery.yaml {block_key}.properties has an empty/non-string key"
            )
            assert isinstance(prop_value, dict), (
                f"smithery.yaml {block_key}.properties.{prop_name} must be a "
                f"mapping (got {type(prop_value).__name__})"
            )


def test_command_function_module_importable() -> None:
    """Smoke: the module the start command launches actually exists.

    The smithery commandFunction invokes ``uvx autonomath-mcp``, which
    resolves to the ``autonomath-mcp`` console script registered in
    pyproject.toml against ``jpintel_mcp.mcp.server:run``. If that module
    disappears the manifest is pointing at a phantom binary.
    """
    spec = importlib.util.find_spec(COMMAND_FUNCTION_MODULE)
    assert spec is not None, (
        f"smithery.yaml start contract references module "
        f"{COMMAND_FUNCTION_MODULE!r} but it is not importable — "
        "console script `autonomath-mcp` would fail at uvx launch"
    )
