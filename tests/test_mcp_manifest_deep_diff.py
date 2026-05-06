from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "mcp_manifest_deep_diff.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("mcp_manifest_deep_diff", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_compare_manifests_finds_hard_and_soft_drift(tmp_path: Path) -> None:
    mod = _load_module()
    dxt = tmp_path / "dxt.json"
    registry = tmp_path / "registry.json"
    _write_json(
        dxt,
        {
            "version": "1.0",
            "resources": [{"name": "taxonomy"}],
            "tools": [
                {"name": "search_programs", "description": "DXT desc"},
                {"name": "only_dxt", "description": "Only DXT"},
            ],
        },
    )
    _write_json(
        registry,
        {
            "version": "1.0",
            "tools": [
                {"name": "search_programs", "description": "Registry desc"},
                {"name": "only_registry", "description": "Only registry"},
            ],
        },
    )

    diff = mod.compare_manifests(dxt, registry)

    assert diff.dxt_tool_count == 2
    assert diff.registry_tool_count == 2
    assert diff.missing_in_dxt == ["only_registry"]
    assert diff.missing_in_registry == ["only_dxt"]
    assert [item.name for item in diff.description_diffs] == ["search_programs"]
    assert diff.dxt_resource_count == 1
    assert diff.registry_resource_count == 0


def test_render_markdown_contains_gate_guidance(tmp_path: Path) -> None:
    mod = _load_module()
    dxt = tmp_path / "dxt.json"
    registry = tmp_path / "registry.json"
    payload = {"version": "1.0", "tools": [{"name": "t", "description": "same"}]}
    _write_json(dxt, payload)
    _write_json(registry, payload)

    text = mod.render_markdown(dxt, registry)

    assert "MCP Manifest Deep Diff" in text
    assert "hard_drift: `false`" in text
    assert "Recommended Gate" in text
