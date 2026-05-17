"""H9 P1.3 — REST meta import drift fail-closed regression.

Background
----------
``src/jpintel_mcp/api/meta.py`` aggregates MCP resources + prompts from three
registries (``jpcite_resources`` / ``cohort_resources`` /
``autonomath_tools.resources`` + ``.prompts``). Until 2026-05-17, the
autonomath branch imported hallucinated names ``list_autonomath_resources``
/ ``list_autonomath_prompts`` whose actual canonical exports are
``list_resources`` / ``list_prompts``. The wrapping ``except Exception:
pass`` silently swallowed the ``ImportError``, so the REST surface returned
0 autonomath resources / 0 autonomath prompts indefinitely — a fail-open
drift that REST discovery clients would never see.

The fix in ``api/meta.py`` rebinds via ``from .resources import
list_resources as list_autonomath_resources``. This test pins both
invariants:

  1. The canonical export names exist (``list_resources`` /
     ``list_prompts``) and return non-empty payloads.
  2. The REST loader source carries the ``as list_autonomath_resources`` /
     ``as list_autonomath_prompts`` alias forms — so a future agent
     re-introducing the bare hallucinated import is caught at pytest
     collection.

If a future refactor renames the canonical export back to a
``list_autonomath_*`` form (or any other identifier), this test will fail
fast at pytest collection time, blocking the silent-drift regression.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_autonomath_resources_module_exports_canonical_name() -> None:
    """``autonomath_tools.resources.list_resources`` must exist + return a list."""
    mod = importlib.import_module("jpintel_mcp.mcp.autonomath_tools.resources")
    assert hasattr(mod, "list_resources"), (
        "canonical export `list_resources` missing from "
        "autonomath_tools.resources; api/meta.py imports this name as "
        "`list_autonomath_resources` — rename will silently regress REST "
        "/v1/meta/resources to 0 autonomath entries."
    )
    payload = mod.list_resources()
    assert isinstance(payload, list)
    assert len(payload) > 0, (
        "`list_resources()` returned empty list — REST surface would "
        "aggregate 0 autonomath resources; fail-closed gate engaged."
    )


def test_autonomath_prompts_module_exports_canonical_name() -> None:
    """``autonomath_tools.prompts.list_prompts`` must exist + return a list."""
    mod = importlib.import_module("jpintel_mcp.mcp.autonomath_tools.prompts")
    assert hasattr(mod, "list_prompts"), (
        "canonical export `list_prompts` missing from "
        "autonomath_tools.prompts; api/meta.py imports this name as "
        "`list_autonomath_prompts` — rename will silently regress REST "
        "/v1/meta/prompts to 0 autonomath entries."
    )
    payload = mod.list_prompts()
    assert isinstance(payload, list)
    assert len(payload) > 0, (
        "`list_prompts()` returned empty list — REST surface would "
        "aggregate 0 autonomath prompts; fail-closed gate engaged."
    )


def test_meta_loader_imports_under_alias_not_hallucinated_name() -> None:
    """``api/meta.py`` must NOT import hallucinated ``list_autonomath_*`` bare names.

    The fix at H9 P1.3 binds via ``from ...resources import list_resources
    as list_autonomath_resources``. If a future agent restores the
    hallucinated name on the source side (importing something that does
    not exist on the target module), the resulting ``ImportError`` would
    once again be swallowed by the existing ``except Exception`` band-aid.
    To guard the source pattern, we read the file and assert the alias
    form is present.
    """
    meta_src = Path("src/jpintel_mcp/api/meta.py").read_text(encoding="utf-8")
    assert "list_resources as list_autonomath_resources" in meta_src, (
        "api/meta.py no longer binds `list_resources as "
        "list_autonomath_resources`; either restore the alias or refactor "
        "away from the legacy public name."
    )
    assert "list_prompts as list_autonomath_prompts" in meta_src, (
        "api/meta.py no longer binds `list_prompts as "
        "list_autonomath_prompts`; either restore the alias or refactor "
        "away from the legacy public name."
    )


def test_meta_loader_aggregates_autonomath_resources() -> None:
    """``_load_mcp_resources`` must yield at least one autonomath URI.

    Guards against silent fail-open: even if the import works, an
    unrelated refactor that registers 0 autonomath resources at
    module-load time would not be caught by the alias check above.
    """
    from jpintel_mcp.api import meta

    meta._RESOURCES_PROMPTS_CACHE["resources"] = None
    out = meta._load_mcp_resources()
    assert isinstance(out, list)
    assert any(
        isinstance(r, dict) and "autonomath" in str(r.get("uri", "")).lower() for r in out
    ), (
        "`_load_mcp_resources` returned 0 autonomath:// URIs; either the "
        "registry is empty (data regression) or the import drift is back."
    )


def test_meta_loader_aggregates_autonomath_prompts() -> None:
    """``_load_mcp_prompts`` must yield at least one prompt entry."""
    from jpintel_mcp.api import meta

    meta._RESOURCES_PROMPTS_CACHE["prompts"] = None
    out = meta._load_mcp_prompts()
    assert isinstance(out, list)
    assert len(out) > 0, (
        "`_load_mcp_prompts` returned 0 entries; either the registry is "
        "empty (data regression) or the import drift is back."
    )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
