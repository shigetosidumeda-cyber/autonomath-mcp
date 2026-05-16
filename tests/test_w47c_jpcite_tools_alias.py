"""Wave 46 task 47.C regression test — jpcite_tools → autonomath_tools alias.

Verifies the destruction-free file-path namespace alias created in
``src/jpintel_mcp/mcp/jpcite_tools/``:

* The legacy ``autonomath_tools/`` directory is still present and intact
  (no rm/mv per ``feedback_destruction_free_organization``).
* The new ``jpcite_tools/`` directory mirrors every ``*.py`` file in
  ``autonomath_tools/`` (one re-export wrapper per file plus its own
  ``__init__.py``).
* Each wrapper is a pure star-import from the matched
  ``autonomath_tools.<name>`` submodule — no additional side effects,
  no duplicate ``@mcp.tool`` registration (Python module cache makes
  the re-import idempotent).
* Importing ``jpintel_mcp.mcp.jpcite_tools.<X>`` returns a module whose
  public attribute surface is a superset of ``autonomath_tools.<X>``'s
  public surface (the alias may expose extra cross-module re-exports
  but MUST NOT shadow or break any canonical symbol).

This test is offline-only and never imports ``anthropic``/``openai``
(per the ``feedback_no_operator_llm_api`` repository rule). It also
must not touch the heavy SQLite database — only Python import paths.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "src" / "jpintel_mcp" / "mcp"
AUTONOMATH_DIR = SRC_ROOT / "autonomath_tools"
JPCITE_DIR = SRC_ROOT / "jpcite_tools"


# Submodules that are gated by AUTONOMATH_EXPERIMENTAL_MCP_ENABLED in
# the legacy __init__ — they are never imported eagerly, so the alias
# package must mirror them as wrappers but the integration import test
# below cannot assume they will succeed without the gate. We still
# verify the wrapper file exists; we just skip the live-import probe.
EXPERIMENTAL_GATED_MODULES: frozenset[str] = frozenset(
    {
        "intel_wave31",
        "intel_wave32",
        "cross_source_score_v2",
    }
)


def _autonomath_py_files() -> list[str]:
    """Return the ``*.py`` basenames (sans extension) of the legacy package."""
    return sorted(p.stem for p in AUTONOMATH_DIR.glob("*.py") if p.name != "__init__.py")


def test_legacy_autonomath_dir_untouched() -> None:
    """Destruction-free rule: the legacy package MUST still be on disk."""
    assert AUTONOMATH_DIR.is_dir(), (
        f"legacy autonomath_tools/ missing — destruction-free rename violated: {AUTONOMATH_DIR}"
    )
    assert (AUTONOMATH_DIR / "__init__.py").is_file(), (
        "autonomath_tools/__init__.py missing — registration entrypoint lost"
    )
    legacy_files = _autonomath_py_files()
    # Sanity: the legacy package is non-trivial. The exact count is
    # locked at 73 (74 .py minus __init__.py) at the time of Wave 46.47.C.
    assert len(legacy_files) >= 60, (
        f"autonomath_tools/ shrunk unexpectedly: {len(legacy_files)} *.py "
        f"files (expected ≥60). Did someone delete files?"
    )


def test_jpcite_alias_dir_exists() -> None:
    """The new jpcite_tools/ alias package MUST exist with its own __init__."""
    assert JPCITE_DIR.is_dir(), f"jpcite_tools/ alias missing: {JPCITE_DIR}"
    init = JPCITE_DIR / "__init__.py"
    assert init.is_file(), f"jpcite_tools/__init__.py missing: {init}"
    body = init.read_text(encoding="utf-8")
    assert "autonomath_tools" in body, (
        "jpcite_tools/__init__.py must re-export from autonomath_tools"
    )
    assert "import *" in body, "jpcite_tools/__init__.py must use a star-import re-export"


def test_jpcite_alias_mirrors_every_autonomath_file() -> None:
    """Every legacy ``*.py`` must have a matching wrapper in jpcite_tools/."""
    legacy = set(_autonomath_py_files())
    alias = {p.stem for p in JPCITE_DIR.glob("*.py") if p.name != "__init__.py"}
    missing = legacy - alias
    extra = alias - legacy
    assert not missing, (
        f"jpcite_tools/ is missing {len(missing)} wrappers for legacy modules: "
        f"{sorted(missing)[:10]}{'…' if len(missing) > 10 else ''}"
    )
    # `extra` is allowed in principle (new alias-only helpers), but for
    # 47.C the alias is strictly 1:1 — surface any drift loudly.
    assert not extra, (
        f"jpcite_tools/ has {len(extra)} unexpected files not in autonomath_tools/: {sorted(extra)}"
    )


def test_every_wrapper_is_pure_reexport() -> None:
    """Each wrapper body MUST be a star-import from the matched legacy module.

    Pure star-import keeps the alias side-effect-free; any extra logic
    would risk double-registering MCP tools or shadowing canonical
    symbols.
    """
    legacy_files = _autonomath_py_files()
    for stem in legacy_files:
        wrapper = JPCITE_DIR / f"{stem}.py"
        assert wrapper.is_file(), f"missing wrapper file: {wrapper}"
        body = wrapper.read_text(encoding="utf-8")
        expected_import = f"from jpintel_mcp.mcp.autonomath_tools.{stem} import *"
        assert expected_import in body, (
            f"wrapper {wrapper.name} is not a star-import from "
            f"autonomath_tools.{stem} — got body:\n"
            f"{body[:400]}"
        )


def test_jpcite_alias_package_imports() -> None:
    """``import jpintel_mcp.mcp.jpcite_tools`` must succeed at runtime."""
    # Drop any prior cached entry so we exercise the full import flow.
    for key in list(sys.modules):
        if key.startswith("jpintel_mcp.mcp.jpcite_tools"):
            del sys.modules[key]
    mod = importlib.import_module("jpintel_mcp.mcp.jpcite_tools")
    assert mod is not None
    assert mod.__name__ == "jpintel_mcp.mcp.jpcite_tools"


def test_jpcite_submodule_equivalence_smoke() -> None:
    """Importing ``jpcite_tools.<X>`` must expose the legacy module's tools.

    We probe a stable, lightweight handful of submodules (no DB I/O,
    no LLM, no heavy state). For each one, every *module-local* public
    callable defined in the canonical module — i.e. the actual MCP
    tool functions, not the third-party imports — must also resolve
    through the alias to the same object.

    We intentionally restrict the equality check to module-local names
    because Python's ``from X import *`` (without ``__all__``) drops
    the names that ``X`` itself imported from elsewhere (e.g. typing
    ``Annotated``, third-party ``Field``). The alias only needs to
    re-export the symbols the canonical module *owns*; transitively
    imported names are not part of the brand API.
    """
    sample_modules = (
        "health_tool",
        "tools",
        "tax_rule_tool",
        "snapshot_tool",
        "static_resources",
    )
    for stem in sample_modules:
        if stem in EXPERIMENTAL_GATED_MODULES:
            continue
        canonical = importlib.import_module(f"jpintel_mcp.mcp.autonomath_tools.{stem}")
        alias = importlib.import_module(f"jpintel_mcp.mcp.jpcite_tools.{stem}")
        canonical_qualname = f"jpintel_mcp.mcp.autonomath_tools.{stem}"
        # Collect names that the canonical module *owns* — i.e. callables
        # whose ``__module__`` matches the canonical qualname. These are
        # exactly the symbols the alias is expected to re-export via
        # ``from autonomath_tools.<stem> import *``.
        owned_callables: list[str] = []
        for name in dir(canonical):
            if name.startswith("_"):
                continue
            obj = getattr(canonical, name)
            if not callable(obj):
                continue
            obj_mod = getattr(obj, "__module__", None)
            if obj_mod == canonical_qualname:
                owned_callables.append(name)
        assert owned_callables, (
            f"autonomath_tools.{stem} has no module-local callables — "
            f"sample_modules tuple needs revision"
        )
        for name in owned_callables:
            canonical_obj = getattr(canonical, name)
            assert hasattr(alias, name), (
                f"jpcite_tools.{stem} missing re-exported callable "
                f"`{name}` from autonomath_tools.{stem}"
            )
            alias_obj = getattr(alias, name)
            assert alias_obj is canonical_obj, (
                f"jpcite_tools.{stem}.{name} is not the same object as "
                f"autonomath_tools.{stem}.{name} — re-export identity broken"
            )


def test_alias_does_not_duplicate_mcp_tool_registration() -> None:
    """Importing jpcite_tools after autonomath_tools must NOT double-count tools.

    The FastMCP instance lives in ``jpintel_mcp.mcp.server`` and tracks
    registered tools via its tool manager. Importing the alias package
    on top of the canonical package would only matter if it triggered a
    fresh import of any submodule — Python's module cache prevents
    that, so the tool count must stay flat across both imports.
    """
    # Force-import canonical first so its @mcp.tool decorators run.
    importlib.import_module("jpintel_mcp.mcp.autonomath_tools")
    server_mod = importlib.import_module("jpintel_mcp.mcp.server")
    mcp_instance = getattr(server_mod, "mcp", None)
    if mcp_instance is None:
        pytest.skip("server.mcp not available in this environment")

    # Best-effort: not every FastMCP build exposes the same tool registry
    # API. We probe a couple of attribute paths and accept whichever
    # surfaces a tools dict/list.
    def _tool_count(m: object) -> int | None:
        tm = getattr(m, "_tool_manager", None) or getattr(m, "tool_manager", None)
        if tm is None:
            return None
        tools_attr = getattr(tm, "_tools", None) or getattr(tm, "tools", None)
        if tools_attr is None:
            return None
        try:
            return len(tools_attr)
        except TypeError:
            return None

    before = _tool_count(mcp_instance)
    if before is None:
        pytest.skip("FastMCP build does not expose a probeable tool registry")
    # Now import the alias package; this should NOT increment the count.
    importlib.import_module("jpintel_mcp.mcp.jpcite_tools")
    after = _tool_count(mcp_instance)
    assert after == before, (
        f"importing jpcite_tools added {after - before} duplicate tool "
        f"registrations (before={before}, after={after}) — alias is not "
        f"a clean re-export"
    )


def test_wrapper_files_are_small_and_disciplined() -> None:
    """Each wrapper should be a 1-statement re-export (≤30 LOC budget).

    The strict size cap guards against accidentally pasting real logic
    into the alias layer.
    """
    for path in JPCITE_DIR.glob("*.py"):
        if path.name == "__init__.py":
            # __init__ has a longer docstring; cap it more generously.
            assert len(path.read_text(encoding="utf-8").splitlines()) <= 60, (
                "jpcite_tools/__init__.py grew past 60 LOC — keep it lean"
            )
            continue
        body = path.read_text(encoding="utf-8")
        lines = body.splitlines()
        assert len(lines) <= 30, (
            f"wrapper {path.name} exceeded 30 LOC ({len(lines)}): "
            f"re-export wrappers must stay 1-statement"
        )
        # Must contain exactly one `from … import *` statement.
        import_lines = [ln for ln in lines if ln.strip().startswith("from ") and " import *" in ln]
        assert len(import_lines) == 1, (
            f"wrapper {path.name} must contain exactly one star-import (got {len(import_lines)})"
        )


def test_alias_count_matches_canonical_count_exactly() -> None:
    """File count parity: alias dir's *.py count == legacy *.py count."""
    legacy_count = sum(1 for _ in AUTONOMATH_DIR.glob("*.py"))
    alias_count = sum(1 for _ in JPCITE_DIR.glob("*.py"))
    assert alias_count == legacy_count, (
        f"alias file count drift: jpcite_tools has {alias_count} *.py, "
        f"autonomath_tools has {legacy_count}"
    )


def test_no_legacy_brand_logic_imported_into_alias() -> None:
    """Wrappers must not import from anywhere other than autonomath_tools.

    The alias layer's job is strictly re-export. If a wrapper grew an
    extra ``import some_other_module`` line it would risk side effects
    on import — fail loudly so we catch it in review.
    """
    for path in JPCITE_DIR.glob("*.py"):
        if path.name == "__init__.py":
            continue
        body = path.read_text(encoding="utf-8")
        import_statements = [
            ln.strip() for ln in body.splitlines() if ln.strip().startswith(("import ", "from "))
        ]
        for stmt in import_statements:
            assert "autonomath_tools" in stmt, (
                f"wrapper {path.name} has a non-aliasing import: {stmt!r}"
            )
