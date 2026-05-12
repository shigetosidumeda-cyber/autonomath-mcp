"""Tests for Wave 46 dim 19 EJ booster — Dim J foreign_fdi_mcp wrapper.

Covers the new MCP wrapper module at
``src/jpintel_mcp/mcp/autonomath_tools/foreign_fdi_mcp.py`` that
exposes two tools (``foreign_fdi_list_am`` + ``foreign_fdi_country_am``)
over the existing REST surface ``api/foreign_fdi_v2.py``.

Assertions:

  * Module file exists at the expected path.
  * NO LLM imports (anthropic / openai / google.generativeai /
    claude_agent_sdk) and NO LLM API-key env-var references.
  * Both impl helpers (``_foreign_fdi_list_am_impl`` and
    ``_foreign_fdi_country_am_impl``) are defined.
  * Tool docstrings follow the いつ使う/入力/出力/エラー schema.
  * ISO regex / region enum / limit-bound validation paths return
    canonical ``invalid_input`` envelopes (no exception leakage).
  * Module is registered in ``autonomath_tools/__init__.py``.
  * The wrapper delegates to ``api.foreign_fdi_v2`` helpers — single
    source of truth invariant with the REST surface.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import re
import sqlite3
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MCP_MOD_PATH = (
    REPO_ROOT
    / "src"
    / "jpintel_mcp"
    / "mcp"
    / "autonomath_tools"
    / "foreign_fdi_mcp.py"
)
REST_MOD_PATH = (
    REPO_ROOT / "src" / "jpintel_mcp" / "api" / "foreign_fdi_v2.py"
)
INIT_PATH = (
    REPO_ROOT
    / "src"
    / "jpintel_mcp"
    / "mcp"
    / "autonomath_tools"
    / "__init__.py"
)
MIG_265 = REPO_ROOT / "scripts" / "migrations" / "265_cross_source_agreement.sql"
MIG_266 = REPO_ROOT / "scripts" / "migrations" / "266_fdi_country_80.sql"


def _import_module(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_am_fixture(tmp_path: pathlib.Path) -> sqlite3.Connection:
    """Apply migration 265 + 266 to a tmp DB so v_fdi_country_public exists."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Stub required upstream table referenced by some 265 helpers.
    conn.executescript(
        """
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            confirming_source_count INTEGER NOT NULL DEFAULT 1
        );
        """
    )
    for mig in (MIG_265, MIG_266):
        conn.executescript(mig.read_text(encoding="utf-8"))
    return conn


# ---------------------------------------------------------------------------
# Static / structural assertions
# ---------------------------------------------------------------------------


def test_module_file_exists() -> None:
    assert MCP_MOD_PATH.exists(), f"missing {MCP_MOD_PATH}"


def test_two_tools_and_two_impls() -> None:
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    assert "def _foreign_fdi_list_am_impl(" in src
    assert "def _foreign_fdi_country_am_impl(" in src
    assert "def foreign_fdi_list_am(" in src
    assert "def foreign_fdi_country_am(" in src
    # Two FastMCP registrations.
    assert src.count("@mcp.tool") >= 2


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
                f"foreign_fdi_mcp: forbidden import {mod!r} matches {banned!r}"
            )


def test_no_llm_env_var_refs() -> None:
    text = MCP_MOD_PATH.read_text(encoding="utf-8")
    for banned_var in BANNED_ENV_VARS:
        assert banned_var not in text, (
            f"foreign_fdi_mcp must not reference {banned_var}"
        )


def test_delegates_to_rest_module() -> None:
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    assert "from jpintel_mcp.api.foreign_fdi_v2 import" in src
    assert "_build_list_query" in src
    assert "_open_autonomath_ro" in src
    assert "_row_to_dict" in src


def test_tool_docstring_schema() -> None:
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    for tool_name in ("foreign_fdi_list_am", "foreign_fdi_country_am"):
        m = re.search(
            rf'def {tool_name}\(.*?\).*?"""(.+?)"""', src, re.S
        )
        assert m is not None, f"docstring on {tool_name} not found"
        body = m.group(1)
        assert "いつ使う" in body
        assert "入力" in body
        assert "出力" in body
        assert "エラー" in body
        assert len(body) >= 50


def test_env_gate_default_on() -> None:
    src = MCP_MOD_PATH.read_text(encoding="utf-8")
    assert (
        'os.environ.get("AUTONOMATH_FOREIGN_FDI_MCP_ENABLED", "1") == "1"'
        in src
    )


def test_init_registers_module() -> None:
    init_src = INIT_PATH.read_text(encoding="utf-8")
    assert "foreign_fdi_mcp," in init_src, (
        "foreign_fdi_mcp must be imported in autonomath_tools/__init__.py"
    )


def test_module_loc_under_budget() -> None:
    n = len(MCP_MOD_PATH.read_text(encoding="utf-8").splitlines())
    assert n <= 260, f"foreign_fdi_mcp.py grew to {n} LOC (>260 budget)"


# ---------------------------------------------------------------------------
# Functional impl assertions
# ---------------------------------------------------------------------------


def test_list_impl_rejects_bad_region(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.foreign_fdi_mcp", MCP_MOD_PATH
    )
    out = mod._foreign_fdi_list_am_impl(region="atlantis")
    assert "error" in out
    assert out["error"]["code"] == "invalid_input"


def test_list_impl_rejects_oversize_limit(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.foreign_fdi_mcp_b", MCP_MOD_PATH
    )
    out = mod._foreign_fdi_list_am_impl(limit=99999)
    assert out["error"]["code"] == "invalid_input"


def test_list_impl_happy_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.foreign_fdi_mcp_c", MCP_MOD_PATH
    )
    out = mod._foreign_fdi_list_am_impl(is_g7=1, limit=20)
    assert "items" in out
    assert out["total"] == 7  # G7 = 7 countries by migration spec
    assert out["_billing_unit"] == 1
    assert "_disclaimer" in out
    isos = {it["country_iso"] for it in out["items"]}
    assert {"US", "JP", "DE"}.issubset(isos)


def test_country_impl_rejects_bad_iso(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.foreign_fdi_mcp_d", MCP_MOD_PATH
    )
    # Lower-case input must still normalize to upper before regex; passing
    # an invalid 3-letter code should fail.
    out = mod._foreign_fdi_country_am_impl(country_iso="USA")
    assert out["error"]["code"] == "invalid_input"


def test_country_impl_happy_path(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.foreign_fdi_mcp_e", MCP_MOD_PATH
    )
    out = mod._foreign_fdi_country_am_impl(country_iso="jp")
    assert out["country_iso"] == "JP"
    assert out["country_name_ja"] == "日本"
    assert out["_billing_unit"] == 1
    assert "_disclaimer" in out
    assert out["license"] == "gov_standard"


def test_country_impl_not_found(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _build_am_fixture(tmp_path).close()
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(tmp_path / "autonomath.db"))
    mod = _import_module(
        "jpintel_mcp.mcp.autonomath_tools.foreign_fdi_mcp_f", MCP_MOD_PATH
    )
    out = mod._foreign_fdi_country_am_impl(country_iso="ZZ")
    assert out["error"]["code"] == "not_found"
