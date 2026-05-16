#!/usr/bin/env python3
"""check_mcp_drift: assert published MCP/static manifests are current.

The range check catches implausible tool-count changes. The runtime checks
catch stale-but-valid manifests that still parse but no longer match the
FastMCP tool registry used by the package.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "data" / "facts_registry.json"


def _maybe_reexec_venv() -> None:
    """Use the repo virtualenv when invoked by a bare system python.

    uv-managed venvs symlink to a shared interpreter, so ``Path.resolve()``
    collapses ``.venv/bin/python`` and the global ``python3.12`` to the same
    file. Detect "already in venv" via ``sys.prefix`` instead.
    """

    venv_dir = ROOT / ".venv"
    venv_python = venv_dir / "bin" / "python"
    if (
        venv_python.exists()
        and pathlib.Path(sys.prefix).resolve() != venv_dir.resolve()
        and os.environ.get("JPCITE_NO_VENV_REEXEC") != "1"
    ):
        os.environ["JPCITE_NO_VENV_REEXEC"] = "1"
        os.execv(str(venv_python), [str(venv_python), *sys.argv])


_maybe_reexec_venv()

SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TARGETS = [
    "site/.well-known/mcp.json",
    "server.json",
    "site/server.json",
    "mcp-server.json",
    "mcp-server.full.json",
    "site/mcp-server.json",
    "site/mcp-server.full.json",
]

FULL_TOOL_MANIFESTS = [
    "mcp-server.json",
    "mcp-server.full.json",
    "site/mcp-server.json",
    "site/mcp-server.full.json",
]

SUBSET_TOOL_MANIFESTS = [
    "mcp-server.core.json",
    "mcp-server.composition.json",
]

SERVER_MANIFESTS = [
    "server.json",
    "site/server.json",
]

# All public manifests whose `version` field (and any nested
# `packages[].version` mirror) must agree with `pyproject.toml`.  Drift here
# slipped past the gate before — `pyproject.toml` / `server.json` / `dxt/manifest.json`
# bumped to 0.4.0 while `mcp-server.full|core|composition.json` stayed at 0.3.5.
VERSION_MANIFESTS = [
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

STATIC_DISCOVERY_URLS = [
    (
        "site/.well-known/mcp.json",
        ("mcp", "registry_manifest"),
        "https://jpcite.com/server.json",
    ),
    (
        "site/.well-known/mcp.json",
        ("mcp", "tool_manifest"),
        "https://jpcite.com/mcp-server.json",
    ),
    (
        "site/.well-known/llms.json",
        ("mcp", "registry_manifest"),
        "https://jpcite.com/server.json",
    ),
    (
        "site/.well-known/llms.json",
        ("mcp", "tool_manifest"),
        "https://jpcite.com/mcp-server.json",
    ),
]


def _tool_count(spec: dict) -> int | None:
    for key in ("tools", "tool_count"):
        if key in spec:
            v = spec[key]
            if isinstance(v, list):
                return len(v)
            if isinstance(v, int):
                return v
    pricing = spec.get("pricing") or {}
    if isinstance(pricing.get("tool_count"), int):
        return pricing["tool_count"]
    meta = spec.get("_meta") or {}
    if isinstance(meta, dict) and isinstance(meta.get("tool_count"), int):
        return meta["tool_count"]
    publisher = _publisher_meta(spec)
    if isinstance(publisher.get("tool_count"), int):
        return publisher["tool_count"]
    return None


def _publisher_meta(spec: dict) -> dict:
    meta = spec.get("_meta") or {}
    if not isinstance(meta, dict):
        return {}
    publisher = meta.get("io.modelcontextprotocol.registry/publisher-provided") or {}
    return publisher if isinstance(publisher, dict) else {}


def _pyproject_version() -> str:
    """Return the canonical version string declared in `pyproject.toml`.

    Hand-parsed (string-search) rather than via `tomllib` so this drift check
    stays runnable on any Python the operator happens to invoke it with.
    """

    text = (ROOT / "pyproject.toml").read_text("utf-8")
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
            if value.startswith(("'", '"')) and value[0] == value[-1]:
                return value[1:-1]
            return value
    raise RuntimeError("pyproject.toml has no [project].version declaration")


def _check_manifest_versions(fails: list[str]) -> None:
    """Assert every published manifest reports the same version as pyproject.toml.

    Catches the failure mode the 2026-05-13 R4 audit (P0-1) hit: `pyproject.toml`,
    `server.json`, `dxt/manifest.json`, `smithery.yaml`, `mcp-server.json`,
    `site/server.json`, `site/mcp-server.json` were bumped to 0.4.0 while
    `mcp-server.full.json`, `mcp-server.composition.json`, `mcp-server.core.json`
    (and any `site/` mirrors) were still pinned at 0.3.5.  The previous gate
    only validated tool counts, so the divergence slipped through.

    Compares the top-level `version` plus every nested `packages[].version`
    mirror.  Any drift fails the gate.
    """

    expected = _pyproject_version()
    print(f"OK pyproject.toml: project version = {expected}")
    for rel in VERSION_MANIFESTS:
        path = ROOT / rel
        if not path.exists():
            print(f"SKIP {rel} (not present)")
            continue
        try:
            spec = json.loads(path.read_text("utf-8"))
        except Exception as e:
            fails.append(f"{rel}: parse error {e}")
            continue
        if not isinstance(spec, dict):
            fails.append(f"{rel}: top-level JSON is not an object")
            continue
        top_version = spec.get("version")
        if top_version != expected:
            fails.append(
                f"{rel}: version={top_version!r} does not match pyproject.toml {expected!r}"
            )
        else:
            print(f"OK {rel}: version={top_version}")
        packages = spec.get("packages") or []
        if isinstance(packages, list):
            for idx, pkg in enumerate(packages):
                if not isinstance(pkg, dict):
                    continue
                pkg_version = pkg.get("version")
                if pkg_version is None:
                    continue
                if pkg_version != expected:
                    fails.append(
                        f"{rel}: packages[{idx}].version={pkg_version!r} "
                        f"does not match pyproject.toml {expected!r}"
                    )


async def _runtime_tool_names_async() -> list[str]:
    from jpintel_mcp.mcp.server import mcp

    tools = await mcp.list_tools()
    return [tool.name for tool in tools]


def _runtime_tool_names() -> list[str]:
    return asyncio.run(_runtime_tool_names_async())


def _load_json(rel: str, fails: list[str]) -> dict | None:
    path = ROOT / rel
    if not path.exists():
        fails.append(f"{rel}: missing")
        return None
    try:
        loaded = json.loads(path.read_text("utf-8"))
    except Exception as e:
        fails.append(f"{rel}: parse error {e}")
        return None
    if not isinstance(loaded, dict):
        fails.append(f"{rel}: top-level JSON is not an object")
        return None
    return loaded


def _nested_get(spec: dict, keys: tuple[str, ...]) -> object:
    node: object = spec
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _check_runtime_manifest_sync(runtime_names: list[str], fails: list[str]) -> None:
    runtime_set = set(runtime_names)
    if len(runtime_names) != len(runtime_set):
        duplicates = sorted({name for name in runtime_names if runtime_names.count(name) > 1})
        fails.append(f"runtime tool names are not unique: {duplicates}")
        return
    stale_intel = [name for name in runtime_names if name.startswith("intel_")]
    if stale_intel:
        fails.append(f"runtime still exposes stale intel_* tools: {stale_intel}")

    for rel in FULL_TOOL_MANIFESTS:
        spec = _load_json(rel, fails)
        if spec is None:
            continue
        tools = spec.get("tools")
        if not isinstance(tools, list):
            fails.append(f"{rel}: tools must be a list matching runtime")
            continue
        names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
        if names != runtime_names:
            missing = sorted(runtime_set - set(names))
            extra = sorted(set(names) - runtime_set)
            fails.append(
                f"{rel}: tools list does not match runtime "
                f"(manifest={len(names)}, runtime={len(runtime_names)}, "
                f"missing={missing[:10]}, extra={extra[:10]})"
            )
        else:
            print(f"OK {rel}: tools list matches runtime ({len(runtime_names)})")
        for label, count in (
            ("_meta.tool_count", (spec.get("_meta") or {}).get("tool_count")),
            ("publisher.tool_count", _publisher_meta(spec).get("tool_count")),
        ):
            if count != len(runtime_names):
                fails.append(
                    f"{rel}: {label}={count!r} does not match runtime {len(runtime_names)}"
                )

    for rel in SUBSET_TOOL_MANIFESTS:
        spec = _load_json(rel, fails)
        if spec is None:
            continue
        tools = spec.get("tools")
        if not isinstance(tools, list):
            fails.append(f"{rel}: tools must be a list")
            continue
        names = [tool.get("name") for tool in tools if isinstance(tool, dict)]
        unknown = sorted(
            name for name in names if isinstance(name, str) and name not in runtime_set
        )
        if unknown:
            fails.append(f"{rel}: subset references tools absent from runtime: {unknown[:20]}")
        else:
            print(f"OK {rel}: subset tool names all exist in runtime ({len(names)})")
        declared = (spec.get("_meta") or {}).get("tool_count")
        if isinstance(declared, int) and declared != len(names):
            fails.append(f"{rel}: _meta.tool_count={declared} but tools list has {len(names)}")

    for rel in SERVER_MANIFESTS:
        spec = _load_json(rel, fails)
        if spec is None:
            continue
        for label, count in (
            ("_meta.tool_count", (spec.get("_meta") or {}).get("tool_count")),
            ("publisher.tool_count", _publisher_meta(spec).get("tool_count")),
        ):
            if count != len(runtime_names):
                fails.append(
                    f"{rel}: {label}={count!r} does not match runtime {len(runtime_names)}"
                )
        print(f"OK {rel}: registry tool counts match runtime ({len(runtime_names)})")


def _check_static_discovery_manifests(fails: list[str]) -> None:
    for rel, keys, expected in STATIC_DISCOVERY_URLS:
        spec = _load_json(rel, fails)
        if spec is None:
            continue
        actual = _nested_get(spec, keys)
        dotted = ".".join(keys)
        if actual != expected:
            fails.append(f"{rel}: {dotted}={actual!r} does not match {expected!r}")
        else:
            print(f"OK {rel}: {dotted} -> {expected}")


def main() -> int:
    reg = json.loads(REGISTRY.read_text("utf-8"))
    lo, hi = reg["guards"]["numeric_ranges"]["mcp_tools"]
    fails: list[str] = []

    for rel in TARGETS:
        p = ROOT / rel
        if not p.exists():
            print(f"SKIP {rel} (not present)")
            continue
        try:
            spec = json.loads(p.read_text("utf-8"))
        except Exception as e:
            fails.append(f"{rel}: parse error {e}")
            continue
        n = _tool_count(spec)
        if n is None:
            print(f"SKIP {rel} (no tools / tool_count key)")
            continue
        if not lo <= n <= hi:
            fails.append(f"{rel}: tools={n} not in [{lo},{hi}]")
        else:
            print(f"OK {rel}: tools={n} in [{lo},{hi}]")

    _check_manifest_versions(fails)

    runtime_names = _runtime_tool_names()
    if not lo <= len(runtime_names) <= hi:
        fails.append(f"runtime: tools={len(runtime_names)} not in [{lo},{hi}]")
    else:
        print(f"OK runtime: tools={len(runtime_names)} in [{lo},{hi}]")
    _check_runtime_manifest_sync(runtime_names, fails)
    _check_static_discovery_manifests(fails)

    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("OK: mcp drift gates passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
