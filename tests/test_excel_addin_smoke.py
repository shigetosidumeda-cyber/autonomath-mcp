"""Smoke tests for sdk/integrations/excel/.

Pure offline checks — we never hit the live API from CI
(feedback_autonomath_no_api_use). The Excel add-in ships in two flavours:

1. XLAM (VBA) — `sdk/integrations/excel/xlam/jpcite.bas`
2. Office Add-in (Office.js) — `sdk/integrations/excel/office-addin/`

VBA cannot be unit-tested without an Office host, so the .bas file gets a
static structural check (presence of the 5 UDFs, no LLM imports, no
hard-coded API key). The Office Add-in side gets a manifest XML schema
sniff + functions.json schema check + the same LLM ban.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXCEL_DIR = REPO_ROOT / "sdk" / "integrations" / "excel"
XLAM_DIR = EXCEL_DIR / "xlam"
OFFICE_DIR = EXCEL_DIR / "office-addin"

VBA_FILE = XLAM_DIR / "jpcite.bas"
MANIFEST = OFFICE_DIR / "manifest.xml"
FUNCTIONS_JSON = OFFICE_DIR / "src" / "functions.json"
FUNCTIONS_TS = OFFICE_DIR / "src" / "functions.ts"
TASKPANE_HTML = OFFICE_DIR / "src" / "taskpane.html"
README = EXCEL_DIR / "README.md"

# The five functions are part of the public contract — the README, manifest,
# functions.json, .bas, and .ts must all agree on these exact names.
EXPECTED_FUNCTIONS = (
    "HOUJIN",
    "HOUJIN_FULL",
    "PROGRAMS",
    "LAW",
    "ENFORCEMENT",
)


# --- existence ---------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [VBA_FILE, MANIFEST, FUNCTIONS_JSON, FUNCTIONS_TS, TASKPANE_HTML, README],
)
def test_required_file_exists(path: Path) -> None:
    assert path.is_file(), f"missing required file: {path.relative_to(REPO_ROOT)}"


# --- VBA static check --------------------------------------------------------


def test_vba_module_attribute() -> None:
    text = VBA_FILE.read_text(encoding="utf-8")
    assert text.startswith('Attribute VB_Name = "JPCITE"'), (
        "jpcite.bas must start with VBE module attribute (so Import File works)"
    )


@pytest.mark.parametrize("name", EXPECTED_FUNCTIONS)
def test_vba_exposes_each_function(name: str) -> None:
    text = VBA_FILE.read_text(encoding="utf-8")
    expected = f"Public Function JPCITE_{name}"
    assert expected in text, f"VBA module missing UDF: {expected}"


def test_vba_no_llm_imports() -> None:
    text = VBA_FILE.read_text(encoding="utf-8").lower()
    forbidden = ("anthropic", "openai", "gemini", "claude.ai/api", "googleapis.com/v1beta")
    for token in forbidden:
        assert token not in text, f".bas must not reference LLM provider: {token}"


def test_vba_uses_jpcite_api_base() -> None:
    text = VBA_FILE.read_text(encoding="utf-8")
    assert "https://api.jpcite.com" in text
    # legacy brands must not leak into user-visible code
    assert "autonomath.ai" not in text.lower()
    assert "zeimu-kaikei.ai" not in text.lower()


def test_vba_uses_x_api_key_header() -> None:
    text = VBA_FILE.read_text(encoding="utf-8")
    assert "X-API-Key" in text, "VBA must send X-API-Key header"


def test_vba_no_hardcoded_api_key() -> None:
    """API keys are jpc_live_/jpc_test_ prefixed; module must never embed one."""
    text = VBA_FILE.read_text(encoding="utf-8")
    assert not re.search(r"jpc_(live|test)_[A-Za-z0-9]{8,}", text), (
        "VBA module must not embed an API key"
    )


def test_vba_volatile_disabled() -> None:
    """All five UDFs must explicitly opt out of Excel volatility to keep the
    recalc-storm cost bounded."""
    text = VBA_FILE.read_text(encoding="utf-8")
    # crude but effective: count Application.Volatile False per public function
    public_funcs = re.findall(r"^Public Function JPCITE_\w+", text, flags=re.M)
    volatile_marks = re.findall(r"Application\.Volatile\s+False", text)
    assert len(public_funcs) == len(EXPECTED_FUNCTIONS)
    assert len(volatile_marks) >= len(public_funcs), (
        "every public UDF must call Application.Volatile False"
    )


# --- Office Add-in manifest --------------------------------------------------


def _load_manifest() -> ET.Element:
    return ET.parse(MANIFEST).getroot()


def test_manifest_parses() -> None:
    root = _load_manifest()
    assert root.tag.endswith("OfficeApp")


def test_manifest_xsi_type_is_taskpane() -> None:
    root = _load_manifest()
    xsi = "{http://www.w3.org/2001/XMLSchema-instance}type"
    assert root.attrib.get(xsi) == "TaskPaneApp"


def test_manifest_has_required_top_level_blocks() -> None:
    root = _load_manifest()
    ns = "{http://schemas.microsoft.com/office/appforoffice/1.1}"
    for tag in ("Id", "Version", "ProviderName", "DisplayName", "Description", "Hosts"):
        assert root.find(f"{ns}{tag}") is not None, f"manifest missing <{tag}>"


def test_manifest_id_is_uuid() -> None:
    root = _load_manifest()
    ns = "{http://schemas.microsoft.com/office/appforoffice/1.1}"
    el = root.find(f"{ns}Id")
    assert el is not None, "manifest missing <Id>"
    val = el.text or ""
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", val), (
        f"manifest <Id> must be a UUID; got {val!r}"
    )


def test_manifest_provider_is_bookyou() -> None:
    root = _load_manifest()
    ns = "{http://schemas.microsoft.com/office/appforoffice/1.1}"
    el = root.find(f"{ns}ProviderName")
    assert el is not None, "manifest missing <ProviderName>"
    provider = el.text or ""
    # T8010001213708 must appear so the operator is unambiguous to AppSource reviewers
    assert "Bookyou" in provider
    assert "T8010001213708" in provider


def test_manifest_targets_workbook_host() -> None:
    root = _load_manifest()
    ns = "{http://schemas.microsoft.com/office/appforoffice/1.1}"
    hosts = root.find(f"{ns}Hosts")
    assert hosts is not None
    names = [h.attrib.get("Name") for h in hosts.findall(f"{ns}Host")]
    assert "Workbook" in names, f"manifest must target Workbook host; got {names}"


def test_manifest_appdomains_only_jpcite() -> None:
    root = _load_manifest()
    ns = "{http://schemas.microsoft.com/office/appforoffice/1.1}"
    block = root.find(f"{ns}AppDomains")
    assert block is not None, "AppDomains required for X-API-Key fetch"
    domains = [d.text for d in block.findall(f"{ns}AppDomain")]
    assert any("jpcite.com" in (d or "") for d in domains)
    assert not any("autonomath.ai" in (d or "") for d in domains)


def test_manifest_namespace_is_jpcite() -> None:
    """Functions appear as =JPCITE.HOUJIN(...). The namespace shortstring must
    be JPCITE so the worksheet contract matches the README + functions.json."""
    text = MANIFEST.read_text(encoding="utf-8")
    assert "JPCITE.Namespace" in text
    # the shortstring DefaultValue is on a self-closing element so we look for
    # the attribute pattern rather than a textual ">JPCITE<" pair
    assert 'id="JPCITE.Namespace" DefaultValue="JPCITE"' in text


def test_manifest_no_llm_references() -> None:
    text = MANIFEST.read_text(encoding="utf-8").lower()
    for token in ("anthropic", "openai", "gemini", "claude.ai/api"):
        assert token not in text


# --- functions.json (custom-functions metadata) ------------------------------


def test_functions_json_parses() -> None:
    with FUNCTIONS_JSON.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert isinstance(data, dict)
    assert isinstance(data.get("functions"), list)


def test_functions_json_has_5_functions() -> None:
    with FUNCTIONS_JSON.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    ids = sorted(f["id"] for f in data["functions"])
    assert ids == sorted(EXPECTED_FUNCTIONS)


@pytest.mark.parametrize("required", ("id", "name", "description", "result", "parameters"))
def test_functions_json_entry_shape(required: str) -> None:
    with FUNCTIONS_JSON.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for fn in data["functions"]:
        assert required in fn, f"functions.json entry {fn.get('id')} missing {required}"


def test_functions_json_help_urls_point_to_jpcite() -> None:
    with FUNCTIONS_JSON.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    for fn in data["functions"]:
        url = fn.get("helpUrl", "")
        assert url.startswith("https://jpcite.com/"), (
            f"helpUrl must be jpcite.com domain; got {url!r}"
        )


# --- functions.ts ------------------------------------------------------------


@pytest.mark.parametrize("name", EXPECTED_FUNCTIONS)
def test_functions_ts_associates_each_id(name: str) -> None:
    text = FUNCTIONS_TS.read_text(encoding="utf-8")
    assert f'CustomFunctions.associate("{name}"' in text, (
        f"functions.ts missing CustomFunctions.associate({name!r}, ...)"
    )


def test_functions_ts_uses_jpcite_api_base() -> None:
    text = FUNCTIONS_TS.read_text(encoding="utf-8")
    assert "https://api.jpcite.com" in text
    assert "X-API-Key" in text


def test_functions_ts_no_llm_imports() -> None:
    text = FUNCTIONS_TS.read_text(encoding="utf-8").lower()
    for token in ("anthropic", "openai", "gemini", "claude_agent_sdk"):
        assert token not in text


# --- README contract ---------------------------------------------------------


def test_readme_documents_5_step_install() -> None:
    text = README.read_text(encoding="utf-8")
    # Both flavours need a 5-step section
    assert "Install — XLAM (5 steps)" in text
    assert "Install — Office Add-in (5 steps)" in text


@pytest.mark.parametrize("name", EXPECTED_FUNCTIONS)
def test_readme_documents_each_function(name: str) -> None:
    text = README.read_text(encoding="utf-8")
    assert f"JPCITE_{name}" in text or f"JPCITE.{name}" in text, (
        f"README must mention JPCITE_{name} or JPCITE.{name}"
    )


def test_readme_warns_about_recalc_storm() -> None:
    text = README.read_text(encoding="utf-8")
    assert "Recalc storm" in text
    # the storm formula must be visible verbatim
    assert "cell_count" in text and "¥3" in text


def test_readme_calls_out_bookyou_operator() -> None:
    text = README.read_text(encoding="utf-8")
    assert "Bookyou株式会社" in text
    assert "T8010001213708" in text


def test_readme_pricing_is_3yen_per_request() -> None:
    text = README.read_text(encoding="utf-8")
    assert "¥3/req" in text
    # honest about 税込 since the customer-facing copy states it
    assert "税込" in text and "¥3.30" in text
    # banned tier vocabulary
    forbidden = ("Pro plan", "Starter plan", "tier-badge", "Free tier")
    for token in forbidden:
        assert token not in text, f"pricing copy regressed to tiered SKU: {token}"
