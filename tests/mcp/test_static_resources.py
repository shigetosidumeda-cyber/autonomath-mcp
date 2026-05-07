"""Tests for autonomath_tools.static_resources — pure file-read tools.

NOTE: We intentionally bypass `from jpintel_mcp.mcp.autonomath_tools import ...`
because that package's `__init__.py` triggers MCP-tool registration which has a
pre-existing import chain dependency unrelated to this module. This test file
loads `static_resources.py` directly via importlib so it stays isolated and
remains green even when the wider MCP wiring is being refactored.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[2]
_TARGET = _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "autonomath_tools" / "static_resources.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_sr_under_test", _TARGET)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sr = _load_module()


def test_list_static_resources_returns_at_least_six():
    items = sr.list_static_resources()
    assert isinstance(items, list)
    assert len(items) >= 6, (
        f"expected ≥6 static resources on disk, got {len(items)}: {[i['id'] for i in items]}"
    )
    for item in items:
        assert "id" in item
        assert "filename" in item
        assert "path_relative" in item
        assert "size_bytes" in item
        assert isinstance(item["size_bytes"], int) and item["size_bytes"] > 0


def test_get_static_resource_seido_returns_data():
    result = sr.get_static_resource("seido")
    assert isinstance(result, dict)
    assert "data" in result
    assert result["id"] == "seido"
    assert "license" in result
    assert "source_origin" in result
    data = result["data"]
    if isinstance(data, (list, dict)):
        assert len(data) > 0
    else:
        pytest.fail(f"unexpected data type: {type(data)}")


def test_get_static_resource_unknown_raises():
    with pytest.raises(sr.ResourceNotFoundError):
        sr.get_static_resource("does_not_exist")


def test_list_example_profiles_returns_at_least_four():
    items = sr.list_example_profiles()
    assert isinstance(items, list)
    assert len(items) >= 4, (
        f"expected ≥4 example profiles, got {len(items)}: {[i['id'] for i in items]}"
    )
    for item in items:
        assert "id" in item
        assert "filename" in item
        assert "size_bytes" in item
        assert isinstance(item["size_bytes"], int) and item["size_bytes"] > 0


def test_get_example_profile_minimal_returns_valid_dict():
    result = sr.get_example_profile("minimal")
    assert isinstance(result, dict)
    assert result["id"] == "minimal"
    assert "profile" in result
    assert isinstance(result["profile"], (dict, list))
    assert "license" in result
    assert "purpose" in result


def test_get_example_profile_unknown_raises():
    with pytest.raises(sr.ResourceNotFoundError):
        sr.get_example_profile("unknown")


def test_load_json_caching_returns_same_object():
    """_load_json is lru_cache decorated — same path returns identical object."""
    path = sr.STATIC_DIR / sr._STATIC_RESOURCES["seido"]
    first = sr._load_json(path)
    second = sr._load_json(path)
    assert first is second, "lru_cache should return identical object on repeat call"
