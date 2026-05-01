"""Smoke tests for the jpcite kintone plug-in scaffold.

Pure-static checks. No live kintone subdomain, no live jpcite API call.
The kintone runtime cannot be exercised without a real cybozu.com tenant,
so we instead verify that:

  1. ``manifest.json`` parses and conforms to kintone's plug-in manifest
     v1 contract (required keys, version is a SemVer-compatible string,
     uploaded_files lists every file referenced from desktop / mobile /
     config sections).
  2. The runtime entry script (``js/jpcite.js``) and the developer-facing
     ``index.js`` are byte-equivalent in their core source surface (we
     only assert that both register the kintone event hooks and call
     the same API base URL — drift between the two would mean the
     packed plug-in differs from the source the developer reads).
  3. ``config.html`` references both expected form fields.
  4. The branding / cost copy is consistent with the operator-side rules
     (¥3/req metered, jpcite brand, Bookyou株式会社 T8010001213708).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PLUGIN_ROOT / "manifest.json"
INDEX_JS = PLUGIN_ROOT / "index.js"
RUNTIME_JS = PLUGIN_ROOT / "js" / "jpcite.js"
CONFIG_JS = PLUGIN_ROOT / "js" / "config.js"
CONFIG_HTML = PLUGIN_ROOT / "config.html"
README = PLUGIN_ROOT / "README.md"

REQUIRED_TOP_KEYS = {
    "manifest_version",
    "version",
    "type",
    "name",
    "description",
    "icon",
    "desktop",
    "config",
    "uploaded_files",
}

EXPECTED_API_BASE = "https://api.jpcite.com"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


# ---- manifest schema --------------------------------------------------------

def test_manifest_required_keys(manifest: dict) -> None:
    missing = REQUIRED_TOP_KEYS - manifest.keys()
    assert not missing, f"manifest.json missing required keys: {sorted(missing)}"


def test_manifest_version_shape(manifest: dict) -> None:
    v = manifest["version"]
    assert isinstance(v, str), "version must be a string"
    parts = v.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), (
        f"version must be MAJOR.MINOR.PATCH (got {v!r})"
    )


def test_manifest_type_is_app(manifest: dict) -> None:
    assert manifest["type"] == "APP", "kintone plug-in type must be 'APP'"


def test_manifest_uploaded_files_cover_references(manifest: dict) -> None:
    """Every js/css/html path referenced from desktop / mobile / config
    must appear in ``uploaded_files``. kintone refuses to install
    plug-ins that reference an unlisted file."""
    listed = set(manifest["uploaded_files"])
    referenced: set[str] = set()
    for surface in ("desktop", "mobile"):
        for kind in ("js", "css"):
            for path in manifest.get(surface, {}).get(kind, []):
                if not path.startswith("http"):
                    referenced.add(path)
    cfg = manifest.get("config", {})
    if "html" in cfg:
        referenced.add(cfg["html"])
    for kind in ("js", "css"):
        for path in cfg.get(kind, []):
            referenced.add(path)
    missing = referenced - listed
    assert not missing, (
        f"uploaded_files is missing referenced files: {sorted(missing)}"
    )


def test_manifest_required_params(manifest: dict) -> None:
    params = set(manifest["config"].get("required_params", []))
    assert {"api_key", "houjin_field_code"} <= params


# ---- runtime parity ---------------------------------------------------------

def test_runtime_files_share_event_hook() -> None:
    """Both ``index.js`` (developer entry) and ``js/jpcite.js`` (packed
    runtime) must register the same kintone event hook so the packed
    artifact matches the source the developer reads."""
    assert "kintone.events.on" in INDEX_JS.read_text(encoding="utf-8")
    assert "kintone.events.on" in RUNTIME_JS.read_text(encoding="utf-8")


def test_runtime_targets_jpcite_api_base() -> None:
    body = RUNTIME_JS.read_text(encoding="utf-8")
    assert EXPECTED_API_BASE in body, (
        "runtime must call api.jpcite.com — never a hard-coded staging URL"
    )
    assert "/v1/houjin/" in body


def test_runtime_no_llm_imports() -> None:
    """No LLM SDK should be referenced from a customer-side runtime."""
    body = RUNTIME_JS.read_text(encoding="utf-8")
    for forbidden in ("anthropic", "openai", "claude_agent_sdk", "google.generativeai"):
        assert forbidden not in body, f"runtime must not embed {forbidden} SDK"


# ---- config screen ----------------------------------------------------------

def test_config_html_has_both_inputs() -> None:
    body = CONFIG_HTML.read_text(encoding="utf-8")
    assert 'id="jpcite-api-key"' in body
    assert 'id="jpcite-houjin-field-code"' in body


def test_config_js_persists_via_kintone_setconfig() -> None:
    body = CONFIG_JS.read_text(encoding="utf-8")
    assert "kintone.plugin.app.setConfig" in body


# ---- copy hygiene -----------------------------------------------------------

@pytest.mark.parametrize("path", [README, CONFIG_HTML])
def test_brand_and_cost_disclaimers_present(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "jpcite" in text
    assert "¥3/req" in text or "¥3 / req" in text
    assert "Bookyou" in text
    assert "T8010001213708" in text
