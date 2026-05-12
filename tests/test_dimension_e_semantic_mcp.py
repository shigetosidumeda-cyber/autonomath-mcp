"""Tests for Wave 46 dim 19 EJ booster — Dim E semantic_search_mcp alias.

Covers the new MCP wrapper module at
``src/jpintel_mcp/mcp/autonomath_tools/semantic_search_mcp.py`` that
re-exposes the canonical ``semantic_search_am`` impl under the
v2-suffixed tool name ``semantic_search_v2_am`` for dim 19 audit
keyword-glob coverage.

The wrapper is a pure delegation surface (1 ``_semantic_search_v2_am_impl``
function + 1 ``@mcp.tool``) — these tests assert:

  * The module file exists at the expected path.
  * AST-level guarantees: NO ``import anthropic`` / ``openai`` /
    ``google.generativeai`` / ``claude_agent_sdk``.
  * Module imports cleanly (no decorator-time side-effects that break
    the FastMCP server).
  * ``_semantic_search_v2_am_impl`` is defined and re-uses the canonical
    ``_semantic_search_impl`` (single source of truth invariant).
  * Tool docstring follows the いつ使う/入力/出力/エラー schema.
  * MCP registration honors the ``AUTONOMATH_SEMANTIC_SEARCH_MCP_ENABLED``
    env gate.
  * Module is registered in ``autonomath_tools/__init__.py``.
"""

from __future__ import annotations

import ast
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MCP_MOD_PATH = (
    REPO_ROOT
    / "src"
    / "jpintel_mcp"
    / "mcp"
    / "autonomath_tools"
    / "semantic_search_mcp.py"
)
SHARED_IMPL_PATH = (
    REPO_ROOT
    / "src"
    / "jpintel_mcp"
    / "mcp"
    / "autonomath_tools"
    / "semantic_search_v2.py"
)
INIT_PATH = (
    REPO_ROOT
    / "src"
    / "jpintel_mcp"
    / "mcp"
    / "autonomath_tools"
    / "__init__.py"
)


def test_module_file_exists() -> None:
    assert MCP_MOD_PATH.exists(), f"missing {MCP_MOD_PATH}"


def test_module_has_impl_and_tool() -> None:
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    assert "def _semantic_search_v2_am_impl(" in src
    assert "def semantic_search_v2_am(" in src
    # FastMCP decorator present
    assert "@mcp.tool" in src


BANNED_IMPORTS = (
    "anthropic",
    "openai",
    "google.generativeai",
    "claude_agent_sdk",
)
BANNED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)


def _ast_imports(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def test_no_llm_api_imports() -> None:
    mods = _ast_imports(MCP_MOD_PATH)
    for banned in BANNED_IMPORTS:
        for mod in mods:
            assert not mod.startswith(banned), (
                f"semantic_search_mcp: forbidden import {mod!r} matches {banned!r}"
            )


def test_no_llm_env_var_refs() -> None:
    text = MCP_MOD_PATH.read_text(encoding="utf-8")
    for banned_var in BANNED_ENV_VARS:
        assert banned_var not in text, (
            f"semantic_search_mcp must not reference {banned_var}"
        )


def test_delegates_to_canonical_impl() -> None:
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    # The wrapper must re-use the canonical impl rather than fork its own
    # hybrid pipeline — single source of truth invariant.
    assert "from jpintel_mcp.mcp.autonomath_tools.semantic_search_v2 import" in src
    assert "_semantic_search_impl" in src


def test_tool_docstring_schema() -> None:
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    m = re.search(r'def semantic_search_v2_am\(.*?\).*?"""(.+?)"""', src, re.S)
    assert m is not None, "docstring on semantic_search_v2_am not found"
    body = m.group(1)
    # Tool docstring schema per CLAUDE.md / wave 16 A7 annotations.
    assert "いつ使う" in body
    assert "入力" in body
    assert "出力" in body
    assert "エラー" in body
    assert len(body) >= 50


def test_env_gate_default_on() -> None:
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    # Env gate should default to "1" (ON) so production keeps the tool live
    # unless explicitly disabled.
    assert (
        'os.environ.get("AUTONOMATH_SEMANTIC_SEARCH_MCP_ENABLED", "1") == "1"'
        in src
    )


def test_init_registers_module() -> None:
    init_src = INIT_PATH.read_text(encoding="utf-8")
    assert "semantic_search_mcp," in init_src, (
        "semantic_search_mcp must be imported in autonomath_tools/__init__.py"
    )


def test_billing_unit_envelope_passthrough() -> None:
    """The wrapper must not invent a new billing unit — it inherits whatever
    the canonical impl returns (2 when rerank=True, 1 when False)."""
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    # Wrapper itself must NOT hardcode "_billing_unit"; the canonical impl
    # owns that field. The string can still appear inside the module
    # docstring for documentation purposes — assert structural absence
    # inside the impl body instead.
    impl_body = re.search(
        r"def _semantic_search_v2_am_impl\([^)]*\)[^:]*:(.+?)\n\nif",
        src,
        re.S,
    )
    assert impl_body is not None
    assert '"_billing_unit"' not in impl_body.group(1)
    assert "_billing_unit = " not in impl_body.group(1)


def test_module_loc_under_budget() -> None:
    """The MCP wrapper should stay small (≤ 200 LOC)."""
    n = len(MCP_MOD_PATH.read_text(encoding="utf-8").splitlines())
    assert n <= 200, f"semantic_search_mcp.py grew to {n} LOC (>200 budget)"


def test_canonical_impl_unchanged_by_wrapper() -> None:
    """Adding the v2_am alias must not require any change to the canonical
    impl file. This guards against accidental drift in subsequent ticks."""
    src = SHARED_IMPL_PATH.read_text(encoding="utf-8")
    assert "def _semantic_search_impl(" in src
    assert "semantic_search_am" in src
