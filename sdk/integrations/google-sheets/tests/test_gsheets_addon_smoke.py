"""Smoke tests for the jpcite Google Sheets Apps Script add-on.

Apps Script source (Code.gs) cannot be executed without Google's V8
runtime, so we verify the file as text:

  1. Each declared `@customfunction` has a matching JS function declaration.
  2. The function surface mirrors the Excel office-addin 1:1 (same five
     names — drift would confuse consultants who use both).
  3. The manifest (`appsscript.json`) targets the Tokyo timezone, restricts
     `urlFetchWhitelist` to ``https://api.jpcite.com/``, and declares
     the minimal scope set needed (no Drive / Gmail).
  4. No LLM SDK string appears anywhere in the source.
  5. README + sidebar carry the brand + cost disclaimers.

We use a tiny hand-rolled JS function-signature parser so the suite runs
on stock CPython without bringing in `esprima` / `tree-sitter-js`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = PLUGIN_ROOT / "gsheets_addon"
CODE_GS = ADDON_DIR / "Code.gs"
SIDEBAR_HTML = ADDON_DIR / "Sidebar.html"
ADDON_MANIFEST = ADDON_DIR / "appsscript.json"
PROJECT_MANIFEST = PLUGIN_ROOT / "appsscript.json"
README = PLUGIN_ROOT / "README.md"

# Five custom functions must match Excel office-addin function ids
# (`../excel/office-addin/src/functions.json`):
EXPECTED_FUNCTIONS = {
    "JPCITE_HOUJIN",
    "JPCITE_HOUJIN_FULL",
    "JPCITE_PROGRAMS",
    "JPCITE_LAW",
    "JPCITE_ENFORCEMENT",
}

CUSTOMFUNCTION_BLOCK_RE = re.compile(
    r"/\*\*(?P<doc>[^*]*\*+(?:[^/*][^*]*\*+)*)/\s*function\s+(?P<name>[A-Z][A-Z0-9_]*)\s*\(",
    re.DOTALL,
)
FUNCTION_DECL_RE = re.compile(r"function\s+([A-Za-z_$][\w$]*)\s*\(", re.MULTILINE)


@pytest.fixture(scope="module")
def code_text() -> str:
    return CODE_GS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def addon_manifest() -> dict:
    return json.loads(ADDON_MANIFEST.read_text(encoding="utf-8"))


# ---- function surface ------------------------------------------------------


def test_all_expected_functions_declared(code_text: str) -> None:
    decls = set(FUNCTION_DECL_RE.findall(code_text))
    missing = EXPECTED_FUNCTIONS - decls
    assert not missing, f"Code.gs missing functions: {sorted(missing)}"


def test_each_public_function_carries_customfunction_tag(code_text: str) -> None:
    """JsDoc-tagged custom functions must use the `@customfunction`
    annotation; otherwise Apps Script will not surface them in the
    spreadsheet UI."""
    annotated = set()
    for match in CUSTOMFUNCTION_BLOCK_RE.finditer(code_text):
        if "@customfunction" in match.group("doc"):
            annotated.add(match.group("name"))
    missing = EXPECTED_FUNCTIONS - annotated
    assert not missing, f"functions missing @customfunction tag: {sorted(missing)}"


def test_excel_office_addin_function_ids_match() -> None:
    """If the Excel function set drifts, this guard fires so the
    consultant-facing surface stays consistent."""
    excel_manifest = PLUGIN_ROOT.parent / "excel" / "office-addin" / "src" / "functions.json"
    assert (
        excel_manifest.exists()
    ), "Excel manifest missing — google-sheets parity guard relies on it"
    excel = json.loads(excel_manifest.read_text(encoding="utf-8"))
    excel_ids = {f["id"] for f in excel["functions"]}
    expected_excel_ids = {name.removeprefix("JPCITE_") for name in EXPECTED_FUNCTIONS}
    assert (
        excel_ids == expected_excel_ids
    ), "Excel function id set drifted from Google Sheets surface"


def test_api_base_is_production_jpcite(code_text: str) -> None:
    assert "https://api.jpcite.com" in code_text


def test_no_llm_imports(code_text: str) -> None:
    for forbidden in (
        "anthropic",
        "openai",
        "claude_agent_sdk",
        "google.generativeai",
        "GenerativeAI",
    ):
        assert forbidden not in code_text, f"Code.gs must not embed {forbidden} reference"


# ---- manifest -------------------------------------------------------------


def test_addon_manifest_timezone_is_tokyo(addon_manifest: dict) -> None:
    assert addon_manifest["timeZone"] == "Asia/Tokyo"


def test_addon_manifest_runtime_is_v8(addon_manifest: dict) -> None:
    assert addon_manifest["runtimeVersion"] == "V8"


def test_addon_manifest_url_whitelist(addon_manifest: dict) -> None:
    wl = addon_manifest.get("urlFetchWhitelist", [])
    assert wl == [
        "https://api.jpcite.com/"
    ], f"urlFetchWhitelist must be exactly [https://api.jpcite.com/] (got {wl})"


def test_addon_manifest_oauth_scopes_minimal(addon_manifest: dict) -> None:
    scopes = set(addon_manifest.get("oauthScopes", []))
    required = {
        "https://www.googleapis.com/auth/spreadsheets.currentonly",
        "https://www.googleapis.com/auth/script.external_request",
        "https://www.googleapis.com/auth/script.container.ui",
    }
    forbidden = {
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/gmail.send",
        "https://mail.google.com/",
    }
    assert required <= scopes, f"missing required scopes: {sorted(required - scopes)}"
    assert not (
        scopes & forbidden
    ), f"manifest leaks excessive scopes: {sorted(scopes & forbidden)}"


def test_project_manifest_advertises_addon_homepage_trigger() -> None:
    """The top-level appsscript.json (used when packaging as a Workspace
    add-on) must declare the homepage trigger entry point so the sidebar
    is reachable from the Google Workspace launcher."""
    cfg = json.loads(PROJECT_MANIFEST.read_text(encoding="utf-8"))
    add_ons = cfg.get("addOns", {}).get("common", {})
    assert add_ons.get("name") == "jpcite"
    homepage = add_ons.get("homepageTrigger", {})
    assert homepage.get("runFunction") == "onHomepage"
    assert homepage.get("enabled") is True


# ---- copy hygiene ---------------------------------------------------------


@pytest.mark.parametrize("path", [README, SIDEBAR_HTML, CODE_GS])
def test_brand_disclaimers_present(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "jpcite" in text
    assert "¥3/req" in text or "¥3 / req" in text
    assert "Bookyou" in text
    assert "T8010001213708" in text
