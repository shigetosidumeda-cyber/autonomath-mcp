#!/usr/bin/env python3
"""Runtime distribution probe.

Imports the live ``jpintel_mcp`` API + MCP entry points and verifies their
runtime counts against ``scripts/distribution_manifest.yml``. This is the
SECOND tier of the distribution drift guard — pair with
``check_distribution_manifest_drift.py`` (static-file scan).

Verifies:
  * ``len(app.routes)`` (FastAPI live route count) == manifest.route_count
  * ``len(mcp._tool_manager.list_tools())`` (FastMCP live tool count, default
    gates) == manifest.tool_count_default_gates

Exit codes:
  * 0 — runtime values match manifest
  * 1 — drift found (prints diff)
  * 2 — runtime introspection failed

Constraints:
  * No LLM imports.
  * Boots the in-process app/server but does NOT start a server socket.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent / "distribution_manifest.yml"


def _load_manifest(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        return yaml.safe_load(text)
    except ImportError:
        # Reuse the flat parser from the sibling drift checker.
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from check_distribution_manifest_drift import (
            _flat_yaml_parse,  # type: ignore[import-not-found]
        )

        return _flat_yaml_parse(text)


def _runtime_counts() -> tuple[int, int]:
    """Boot the in-process app + MCP server and return (route_count, tool_count).

    The import sequence matters — the MCP tool count is sensitive to whether
    ``api.main`` was imported first (which transitively pulls in
    ``autonomath_tools`` modules that side-effect-register additional tools
    the bare MCP boot path does not). The canonical distribution boot for
    the ``autonomath-mcp`` console script is ``jpintel_mcp.mcp.server:run``
    in isolation, so this probe imports MCP FIRST to mirror that surface.
    The API count is then taken from a separate ``app`` import to exercise
    the FastAPI surface used by ``autonomath-api``.
    """
    # Default gates: AUTONOMATH_ENABLED=1 mirrors the production gate set
    # CLAUDE.md describes (89 tools at default gates).
    os.environ.setdefault("AUTONOMATH_ENABLED", "1")

    # Canonical MCP boot — must come first for a deterministic tool count.
    from jpintel_mcp.mcp.server import mcp  # type: ignore[import-not-found]

    tool_count = len(mcp._tool_manager.list_tools())

    # Then API boot for the route count.
    from jpintel_mcp.api.main import app  # type: ignore[import-not-found]

    route_count = len(app.routes)
    return route_count, tool_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST_PATH),
        help="Path to distribution_manifest.yml.",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        sys.stderr.write(f"manifest not found: {manifest_path}\n")
        return 2

    manifest = _load_manifest(manifest_path)

    expected_routes = int(manifest.get("route_count", 0))
    expected_tools = int(manifest.get("tool_count_default_gates", 0))

    try:
        route_count, tool_count = _runtime_counts()
    except Exception as exc:  # pragma: no cover - the failure mode is the message
        sys.stderr.write(f"runtime probe failed: {type(exc).__name__}: {exc}\n")
        return 2

    drift: list[tuple[str, int, int]] = []
    if expected_routes != route_count:
        drift.append(("route_count", expected_routes, route_count))
    if expected_tools != tool_count:
        drift.append(("tool_count_default_gates", expected_tools, tool_count))

    if not drift:
        print(
            f"[probe_runtime_distribution] OK — runtime route_count={route_count}, "
            f"tool_count={tool_count} match the manifest."
        )
        return 0

    print("[probe_runtime_distribution] DRIFT — runtime disagrees with manifest:\n")
    print(f"  {'field':<32}  {'manifest':>10}  {'runtime':>10}")
    print(f"  {'-' * 32}  {'-' * 10}  {'-' * 10}")
    for field, expected, observed in drift:
        print(f"  {field:<32}  {expected:>10}  {observed:>10}")
    print(
        "\nUpdate scripts/distribution_manifest.yml to the runtime values "
        "(or fix the runtime regression) and re-run the static drift check."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
