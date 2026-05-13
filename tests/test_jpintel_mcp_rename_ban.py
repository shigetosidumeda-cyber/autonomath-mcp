"""CI gate: enforce CLAUDE.md "Never rename `src/jpintel_mcp/`" gotcha.

CLAUDE.md gotcha (quote):
    Never rename `src/jpintel_mcp/` to `src/autonomath_mcp/` — the PyPI
    package name is `autonomath-mcp`, but the import path is the legacy
    `jpintel_mcp` and changing it will break every consumer.

This test file is the CI gate enforcing that gotcha. Any PR that tries
to rename the source directory or alter the canonical entry point will
trip these assertions before deploy.

Scope guard:
- DO NOT add LLM imports here (anthropic / openai / google.generativeai /
  claude_agent_sdk) — covered separately by
  `tests/test_no_llm_in_production.py`.
- DO NOT widen this file beyond the rename ban; new gotchas get their
  own dedicated test files.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

# Resolve repo root relative to this file so the gate works regardless
# of pytest invocation cwd (`uv run pytest -q tests/...` vs CI worker
# from elsewhere).
REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
JPINTEL_PKG_DIR = SRC_DIR / "jpintel_mcp"
JPINTEL_INIT = JPINTEL_PKG_DIR / "__init__.py"
AUTONOMATH_PKG_DIR = SRC_DIR / "autonomath_mcp"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"

# Canonical entry point per CLAUDE.md §Key files / §Console scripts.
# This is the contract every downstream consumer of the
# `autonomath-mcp` PyPI package expects in `[project.scripts]`.
CANONICAL_MCP_SCRIPT_NAME = "autonomath-mcp"
CANONICAL_MCP_ENTRYPOINT = "jpintel_mcp.mcp.server:run"


def test_jpintel_mcp_init_exists() -> None:
    """`src/jpintel_mcp/__init__.py` must exist.

    Renaming the package away from `jpintel_mcp` removes this file and
    breaks every `import jpintel_mcp` in scripts/, tests/, console
    scripts, and downstream consumers (MCP clients, dxt manifest,
    smithery.yaml, mcp-server.json).
    """
    assert JPINTEL_INIT.is_file(), (
        f"{JPINTEL_INIT} is missing. "
        "CLAUDE.md gotcha: never rename `src/jpintel_mcp/` — the import "
        "path is load-bearing for every consumer (PyPI distribution name "
        "is `autonomath-mcp` but the Python package stays `jpintel_mcp`)."
    )


def test_autonomath_mcp_dir_does_not_exist() -> None:
    """`src/autonomath_mcp/` must NOT exist.

    Symptom of an attempted rename: someone moved the package alongside
    the PyPI distribution name. This breaks all imports because the
    distribution name and the import path are deliberately divergent
    here (PyPI = `autonomath-mcp`, import = `jpintel_mcp`).
    """
    assert not AUTONOMATH_PKG_DIR.exists(), (
        f"{AUTONOMATH_PKG_DIR} must not exist. "
        "CLAUDE.md gotcha: the source directory stays `src/jpintel_mcp/` "
        "even though the PyPI package is `autonomath-mcp`. Renaming the "
        "source dir to match the distribution name breaks every "
        "`import jpintel_mcp` in scripts, tests, console scripts, and "
        "downstream MCP consumers."
    )


def test_pyproject_canonical_entrypoint() -> None:
    """`pyproject.toml` `[project.scripts]` must declare the canonical
    `autonomath-mcp` console script pointing at `jpintel_mcp.mcp.server:run`.

    This is the contract `pip install autonomath-mcp` registers and what
    `.venv/bin/autonomath-mcp` resolves to. Changing it silently breaks
    every MCP client that launches the stdio server via the console
    script name.
    """
    assert PYPROJECT_TOML.is_file(), f"{PYPROJECT_TOML} missing"
    with PYPROJECT_TOML.open("rb") as fh:
        data = tomllib.load(fh)
    scripts = data.get("project", {}).get("scripts", {})
    assert CANONICAL_MCP_SCRIPT_NAME in scripts, (
        f"`[project.scripts]` is missing `{CANONICAL_MCP_SCRIPT_NAME}`. "
        "This console script is the canonical entry point for the "
        "MCP stdio server and is referenced by manifests + docs."
    )
    actual = scripts[CANONICAL_MCP_SCRIPT_NAME]
    assert actual == CANONICAL_MCP_ENTRYPOINT, (
        f"`[project.scripts].{CANONICAL_MCP_SCRIPT_NAME}` is "
        f"`{actual}`, expected `{CANONICAL_MCP_ENTRYPOINT}`. "
        "CLAUDE.md gotcha: the import path stays `jpintel_mcp.*` even "
        "when the PyPI package is `autonomath-mcp`. Do not rewrite the "
        "entry point to a hypothetical `autonomath_mcp.mcp.server:run`."
    )
    # Defense in depth: literal grep against the raw TOML text, so a
    # future migration to a TOML preprocessor or alternative config
    # surface cannot silently bypass the structured assertion above.
    raw = PYPROJECT_TOML.read_text(encoding="utf-8")
    pattern = re.compile(
        rf'^\s*{re.escape(CANONICAL_MCP_SCRIPT_NAME)}\s*=\s*"'
        rf'{re.escape(CANONICAL_MCP_ENTRYPOINT)}"\s*$',
        re.MULTILINE,
    )
    assert pattern.search(raw), (
        f"pyproject.toml raw text does not contain the canonical line "
        f'`{CANONICAL_MCP_SCRIPT_NAME} = "{CANONICAL_MCP_ENTRYPOINT}"`.'
    )


def test_jpintel_mcp_importable() -> None:
    """Smoke import: `import jpintel_mcp` must succeed.

    Final consumer-facing check — even if the directory and pyproject
    entry are in place, a broken `__init__.py` would still break every
    downstream import. Run inside the test process so it picks up the
    `src/` layout via the standard editable install.
    """
    # Make sure src/ is importable even when the package is not yet
    # editable-installed (e.g. fresh `uv run` cold cache). pyproject
    # already declares `package-dir = {"" = "src"}` so an installed
    # build resolves naturally; this guard only adds the path if the
    # import would otherwise miss.
    src_path = str(SRC_DIR)
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    import jpintel_mcp  # noqa: F401  (smoke import — load-bearing assertion)
    # Sanity-check: the imported module resolves to our source tree,
    # not some stale site-packages shadow.
    module_file = getattr(jpintel_mcp, "__file__", None)
    assert module_file is not None, "jpintel_mcp.__file__ is None"
    assert Path(module_file).resolve().is_relative_to(SRC_DIR), (
        f"jpintel_mcp imported from {module_file}, expected under "
        f"{SRC_DIR}. A stale install is shadowing the source tree."
    )
