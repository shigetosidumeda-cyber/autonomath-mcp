"""DEEP-34 cohort persona kit — 10-case contract test (no LLM).

Loads ``src/jpintel_mcp/mcp/cohort_resources.py`` directly via importlib so
the test stays green even when the wider MCP wiring is being refactored
(same isolation pattern as ``tests/mcp/test_static_resources.py``).

Coverage maps to DEEP-34 §8 acceptance criteria:
  1. 8 cohort SystemPrompt generation (parameterized → 8 sub-cases).
  2. forbidden_phrases sync with DEEP-23 base (推測 / 予測 / 保証 always present).
  3. bilingual JP/EN switch (lang="en" returns EN body when defined; falls back JP).
  4. default-fallback behavior — unknown cohort_id raises KeyError gracefully.
  5. Personalized overlay — customization dict overwrites top-level keys but
     never `disclaimer_envelope`.
  6. LLM-call 0 — ``anthropic`` / ``openai`` / ``google.generativeai`` /
     ``claude_agent_sdk`` not imported by the module.
  7. ``list_cohort_resources()`` schema validation (MCP 2025-06-18 fields).
  8. ``read_cohort_resource`` graceful 404 — unknown URI raises KeyError.
  9. yaml schema (8 required keys per DEEP-34 §1) for every cohort.
 10. tool_routing dict has at least 1 intent + tool pair per cohort
     (DEEP-29 sync placeholder — every cohort declares a routing surface).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[1]
_TARGET = _REPO_ROOT / "src" / "jpintel_mcp" / "mcp" / "cohort_resources.py"


def _load_module():
    # Register in sys.modules BEFORE exec so dataclass()'s _is_type can
    # resolve the module from cls.__module__ during class body execution.
    name = "_cohort_under_test"
    spec = importlib.util.spec_from_file_location(name, _TARGET)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


cr = _load_module()


# ---------------------------------------------------------------------------
# Case 1: 8 cohort SystemPrompt generation (parametrized — 8 sub-cases)
# ---------------------------------------------------------------------------


_COHORT_IDS = (
    "tax_pro",
    "cpa",
    "judicial",
    "admin",
    "lawyer",
    "foreign_fdi",
    "smb_line",
    "industry_pack",
)


@pytest.mark.parametrize("cohort_id", _COHORT_IDS)
def test_persona_for_each_cohort_returns_systemprompt(cohort_id):
    """Case 1 — every one of the 8 cohort_ids resolves to a non-empty SystemPrompt."""
    sp = cr.persona_for_cohort(cohort_id)
    assert sp.cohort_id == cohort_id
    assert sp.cohort, f"cohort name empty for {cohort_id}"
    assert sp.business_law, f"business_law empty for {cohort_id}"
    assert sp.system_prompt.strip(), f"system_prompt empty for {cohort_id}"
    assert isinstance(sp.forbidden_phrases, tuple)
    assert isinstance(sp.few_shot_queries, tuple)
    assert isinstance(sp.tool_routing, tuple)
    assert isinstance(sp.disclaimer_envelope, dict)
    assert sp.source == "common"


# ---------------------------------------------------------------------------
# Case 2: forbidden_phrases sync with DEEP-23 base
# ---------------------------------------------------------------------------


def test_forbidden_phrases_includes_global_base():
    """Case 2 — every kit's forbidden_phrases contains DEEP-23 global base
    (推測 / 予測 / 保証) after _merge_forbidden().
    """
    base = set(cr.GLOBAL_FORBIDDEN_BASE)
    for cohort_id in _COHORT_IDS:
        sp = cr.persona_for_cohort(cohort_id)
        merged = set(sp.forbidden_phrases)
        missing = base - merged
        assert not missing, f"cohort {cohort_id} missing global forbidden tokens: {missing}"


# ---------------------------------------------------------------------------
# Case 3: bilingual JP/EN switch
# ---------------------------------------------------------------------------


def test_bilingual_lang_switch():
    """Case 3 — lang="en" returns the EN body when present; JP fallback when absent."""
    # tax_advisor has both JP + EN — lang="en" must return the EN string.
    sp_ja = cr.persona_for_cohort("tax_pro", lang="ja")
    sp_en = cr.persona_for_cohort("tax_pro", lang="en")
    assert sp_en.lang == "en"
    # Both bodies populated, but EN string differs from JP.
    assert sp_en.system_prompt.strip()
    assert sp_en.system_prompt != sp_ja.system_prompt
    # Specifically the EN string mentions "tax accountant" or "税理士法 §52" rendered.
    assert "Japanese tax accountants" in sp_en.system_prompt or "税理士" in sp_en.system_prompt


# ---------------------------------------------------------------------------
# Case 4: default-fallback / unknown cohort raises KeyError
# ---------------------------------------------------------------------------


def test_unknown_cohort_raises_keyerror():
    """Case 4 — unknown cohort_id surfaces as KeyError (graceful 404 contract)."""
    with pytest.raises(KeyError) as exc:
        cr.persona_for_cohort("nonexistent_cohort_xyz")
    assert "unknown cohort_id" in str(exc.value)


# ---------------------------------------------------------------------------
# Case 5: personalized overlay (mig 096 cohort_kit_yaml ALTER)
# ---------------------------------------------------------------------------


def test_personalized_overlay_overwrites_but_envelope_stays():
    """Case 5 — customization dict overwrites top-level keys (e.g.
    ``forbidden_phrases``) but never ``disclaimer_envelope``.
    """
    base = cr.persona_for_cohort("tax_pro")
    overlay = {
        "forbidden_phrases": ["custom_word_only"],
        "disclaimer_envelope": {"primary": "FAKE", "secondary": [], "routing_required": []},
    }
    custom = cr.persona_for_cohort("tax_pro", customization=overlay)
    assert custom.source == "personalized"
    # custom forbidden contains overlay word + global base (always merged).
    assert "custom_word_only" in custom.forbidden_phrases
    for tok in cr.GLOBAL_FORBIDDEN_BASE:
        assert tok in custom.forbidden_phrases
    # The original disclaimer envelope stays — server-side sensitive-tool
    # branches must always see the canonical fence.
    assert custom.disclaimer_envelope == base.disclaimer_envelope
    assert custom.disclaimer_envelope.get("primary") != "FAKE"


# ---------------------------------------------------------------------------
# Case 6: LLM-call 0 — module imports no forbidden LLM SDK
# ---------------------------------------------------------------------------


def test_no_llm_imports_in_cohort_module():
    """Case 6 — ``cohort_resources`` module has not imported any forbidden LLM SDK.

    Mirrors the ``tests/test_no_llm_in_production.py`` invariant: pure
    sqlite + yaml + json. Anything else would mean the kit module is
    burning Anthropic / OpenAI / Gemini quota at request time.
    """
    forbidden = {"anthropic", "openai", "google.generativeai", "claude_agent_sdk"}
    for mod_name in list(sys.modules.keys()):
        head = mod_name.split(".")[0]
        if head in forbidden:
            # If anything imported them, the cohort_resources file must not be
            # the cause — read its source and assert no actual import statement.
            src = _TARGET.read_text(encoding="utf-8")
            for token in forbidden:
                assert f"import {token}" not in src and f"from {token}" not in src, (
                    f"cohort_resources imports forbidden LLM SDK: {token}"
                )


# ---------------------------------------------------------------------------
# Case 7: list_cohort_resources schema (MCP 2025-06-18)
# ---------------------------------------------------------------------------


def test_list_cohort_resources_schema():
    """Case 7 — list_cohort_resources returns 9 entries (8 kits + 1 cohort_index)
    with each row carrying uri / name / description / mimeType / updateFrequency.
    """
    items = cr.list_cohort_resources()
    assert isinstance(items, list)
    assert len(items) == 9, f"expected 9 cohort resources (28→36), got {len(items)}"
    expected_kit_uris = {f"autonomath://cohort/{slug}.yaml" for slug in cr.COHORT_SLUGS}
    seen = {item["uri"] for item in items}
    assert expected_kit_uris.issubset(seen)
    assert "autonomath://cohort/index.json" in seen
    for item in items:
        for key in ("uri", "name", "description", "mimeType", "updateFrequency"):
            assert key in item, f"resource entry missing key {key}: {item}"


# ---------------------------------------------------------------------------
# Case 8: read_cohort_resource graceful 404
# ---------------------------------------------------------------------------


def test_read_cohort_resource_unknown_raises_keyerror():
    """Case 8 — unknown URI surfaces as KeyError (graceful 404)."""
    with pytest.raises(KeyError):
        cr.read_cohort_resource("autonomath://cohort/does_not_exist.yaml")


def test_read_cohort_resource_known_returns_text():
    """Case 8b — known URI returns MCP-shaped {"contents": [{uri, mimeType, text}]}."""
    payload = cr.read_cohort_resource("autonomath://cohort/tax_advisor.yaml")
    assert "contents" in payload
    assert len(payload["contents"]) == 1
    entry = payload["contents"][0]
    assert entry["uri"] == "autonomath://cohort/tax_advisor.yaml"
    assert entry["mimeType"] == "application/yaml"
    assert "tax_pro" in entry["text"]


# ---------------------------------------------------------------------------
# Case 9: yaml schema (8 required keys per cohort)
# ---------------------------------------------------------------------------


def test_yaml_schema_required_keys_for_all_cohorts():
    """Case 9 — every cohort yaml carries the 8 DEEP-34 §1 required keys."""
    for slug in cr.COHORT_SLUGS:
        kit = cr._load_cohort_kit(slug)
        missing = cr.REQUIRED_KEYS - set(kit.keys())
        assert not missing, f"cohort {slug} missing required keys: {missing}"


# ---------------------------------------------------------------------------
# Case 10: tool_routing has at least 1 entry per cohort (DEEP-29 sync)
# ---------------------------------------------------------------------------


def test_tool_routing_present_for_each_cohort():
    """Case 10 — every cohort declares ≥1 tool_routing entry with intent + tool fields."""
    for cohort_id in _COHORT_IDS:
        sp = cr.persona_for_cohort(cohort_id)
        assert sp.tool_routing, f"cohort {cohort_id} has empty tool_routing"
        for entry in sp.tool_routing:
            assert isinstance(entry, dict)
            assert "intent" in entry, f"cohort {cohort_id} routing missing intent: {entry}"
            assert "tool" in entry, f"cohort {cohort_id} routing missing tool: {entry}"


# ---------------------------------------------------------------------------
# Index helper sanity
# ---------------------------------------------------------------------------


def test_index_json_has_8_cohorts():
    """index.json carries 8 cohort entries — sanity check (not numbered case)."""
    idx = cr.get_cohort_index()
    assert idx.get("cohort_count") == 8
    assert len(idx.get("cohorts") or []) == 8
