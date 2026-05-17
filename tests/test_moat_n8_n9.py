"""Tests for Moat N8 (recipe bank) + N9 (placeholder resolver) MCP tools.

Covers:

  N8 (``moat_n8_recipe``)
    - 15 recipe YAMLs load (file-backed, no DB).
    - ``list_recipes(segment)`` returns 3 recipes per segment + 15 for "all".
    - ``get_recipe(recipe_name)`` returns full step sequence + disclaimer.
    - bare-slug / traversal / unknown-name → empty envelope (not raise).
    - Disclaimer envelope present on every response.

  N9 (``moat_n9_placeholder``)
    - ``resolve_placeholder("{{HOUJIN_NAME}}", context)`` resolves to
      get_houjin_360_am + substituted args.
    - canonical-brace requirement enforced.
    - invalid JSON context → empty envelope.
    - unknown placeholder → empty envelope.
    - DB missing → empty envelope (graceful).
    - Sensitive placeholder carries is_sensitive=True flag (the §-aware
      disclaimer is contributed by the canonical DISCLAIMER constant).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Lane N8 — file-backed recipe bank tests
# ---------------------------------------------------------------------------


def test_n8_load_15_recipes() -> None:
    """All 15 recipe yamls under data/recipes/ load successfully."""
    from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import _load_recipes

    recipes = _load_recipes()
    assert len(recipes) == 15, f"expected 15 recipes, got {len(recipes)}"
    segments = {r.get("segment") for r in recipes}
    assert segments == {"tax", "audit", "gyousei", "shihoshoshi", "ax_fde"}


def test_n8_list_recipes_per_segment_returns_three() -> None:
    """Every segment must surface exactly 3 recipes."""
    from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import list_recipes

    for seg in ("tax", "audit", "gyousei", "shihoshoshi", "ax_fde"):
        out = list_recipes(segment=seg)
        assert out["total"] == 3, f"segment {seg} should have 3 recipes"
        for r in out["results"]:
            assert r["segment"] == seg
            assert r["recipe_name"].startswith("recipe_")
            assert r["step_count"] >= 9
            assert r["billable_units"] >= 9
            assert r["no_llm_required"] is True


def test_n8_list_recipes_all_returns_fifteen() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import list_recipes

    out = list_recipes(segment="all", limit=50)
    assert out["total"] == 15
    seen = {r["recipe_name"] for r in out["results"]}
    assert "recipe_tax_monthly_closing" in seen
    assert "recipe_audit_workpaper_compile" in seen
    assert "recipe_subsidy_application_draft" in seen
    assert "recipe_corporate_setup_registration" in seen
    assert "recipe_client_onboarding" in seen


def test_n8_get_recipe_full_payload() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import get_recipe

    out = get_recipe(recipe_name="recipe_tax_monthly_closing")
    assert out["total"] == 1
    recipe = out["primary_result"]
    assert recipe["recipe_name"] == "recipe_tax_monthly_closing"
    assert recipe["segment"] == "tax"
    assert "disclaimer" in recipe
    steps = recipe["steps"]
    assert isinstance(steps, list)
    assert len(steps) >= 13
    first = steps[0]
    assert "tool_name" in first
    assert "purpose" in first
    assert "_disclaimer" in out


def test_n8_get_recipe_unknown_returns_empty() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import get_recipe

    out = get_recipe(recipe_name="recipe_does_not_exist_xyz")
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"


def test_n8_get_recipe_rejects_traversal() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import get_recipe

    for bad in (
        "recipe_../etc/passwd",
        "recipe_foo/bar",
        "not_a_recipe",
    ):
        out = get_recipe(recipe_name=bad)
        assert out["total"] == 0
        assert out["primary_result"]["status"] == "empty"


def test_n8_disclaimer_present_on_every_response() -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import get_recipe, list_recipes

    for seg in ("tax", "audit", "gyousei", "shihoshoshi", "ax_fde", "all"):
        envelope = list_recipes(segment=seg)
        assert "_disclaimer" in envelope
    out = get_recipe(recipe_name="recipe_audit_workpaper_compile")
    assert "_disclaimer" in out
    assert "税理士法" in out["_disclaimer"]
    assert "公認会計士法" in out["_disclaimer"]


# ---------------------------------------------------------------------------
# Lane N9 — DB-backed placeholder mapper tests
# ---------------------------------------------------------------------------


_N9_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS am_placeholder_mapping (
    placeholder_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    placeholder_name     TEXT NOT NULL UNIQUE,
    source_template_ids  TEXT,
    mcp_tool_name        TEXT NOT NULL,
    args_template        TEXT NOT NULL DEFAULT '{}',
    output_path          TEXT NOT NULL DEFAULT '$',
    fallback_value       TEXT,
    value_kind           TEXT NOT NULL DEFAULT 'text',
    description          TEXT NOT NULL,
    is_sensitive         INTEGER NOT NULL DEFAULT 0,
    license              TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0',
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_N9_FIXTURE_ROWS = [
    (
        "{{HOUJIN_NAME}}",
        "get_houjin_360_am",
        '{"houjin_bangou": "{houjin_bangou}"}',
        "houjin.name",
        "(法人名未取得)",
        "text",
        "国税庁登録法人名",
        0,
        "pdl_v1.0",
    ),
    (
        "{{TAX_RULE_RATE}}",
        "get_am_tax_rule",
        '{"ruleset_id": "{tax_rule_id}"}',
        "rule.credit_rate",
        None,
        "percentage",
        "税額控除率",
        1,
        "gov_standard",
    ),
    (
        "{{CURRENT_DATE}}",
        "computed",
        '{"compute": "today_iso"}',
        "$",
        None,
        "date",
        "現在日付 JST",
        0,
        "jpcite-scaffold-cc0",
    ),
]


def _seed_n9_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_N9_SCHEMA_SQL)
        for row in _N9_FIXTURE_ROWS:
            conn.execute(
                """
                INSERT INTO am_placeholder_mapping (
                    placeholder_name, mcp_tool_name, args_template, output_path,
                    fallback_value, value_kind, description, is_sensitive, license
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def n9_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "autonomath_n9.db"
    _seed_n9_db(db)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db))
    return db


def test_n9_resolve_houjin_name_with_context(n9_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    out = resolve_placeholder(
        placeholder_name="{{HOUJIN_NAME}}",
        context_dict_json='{"houjin_bangou": "8010001213708"}',
    )
    assert out["total"] == 1
    mapping = out["primary_result"]
    assert mapping["placeholder_name"] == "{{HOUJIN_NAME}}"
    assert mapping["mcp_tool_name"] == "get_houjin_360_am"
    assert mapping["args_substituted"] == {"houjin_bangou": "8010001213708"}
    assert mapping["output_path"] == "houjin.name"
    assert mapping["fallback_value"] == "(法人名未取得)"
    assert mapping["value_kind"] == "text"
    assert mapping["is_sensitive"] is False
    assert mapping["substitution_complete"] is True
    assert mapping["missing_context_keys"] == []


def test_n9_resolve_with_missing_context_marks_incomplete(n9_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    out = resolve_placeholder(
        placeholder_name="{{HOUJIN_NAME}}",
        context_dict_json="{}",
    )
    mapping = out["primary_result"]
    # houjin_bangou is missing → token left in place → substitution_complete=False.
    assert mapping["substitution_complete"] is False
    assert "houjin_bangou" in mapping["missing_context_keys"]


def test_n9_sensitive_placeholder_flag_set(n9_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    out = resolve_placeholder(
        placeholder_name="{{TAX_RULE_RATE}}",
        context_dict_json='{"tax_rule_id": "TAX-RD-001"}',
    )
    mapping = out["primary_result"]
    assert mapping["is_sensitive"] is True
    assert mapping["value_kind"] == "percentage"
    # Disclaimer envelope must be present (canonical DISCLAIMER constant).
    assert "_disclaimer" in out


def test_n9_context_free_placeholder(n9_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    out = resolve_placeholder(
        placeholder_name="{{CURRENT_DATE}}",
        context_dict_json="{}",
    )
    mapping = out["primary_result"]
    assert mapping["mcp_tool_name"] == "computed"
    assert mapping["substitution_complete"] is True
    assert mapping["args_substituted"] == {"compute": "today_iso"}


def test_n9_unknown_placeholder_returns_empty(n9_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    out = resolve_placeholder(
        placeholder_name="{{UNKNOWN_NEVER_SEEDED}}",
        context_dict_json="{}",
    )
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"


def test_n9_rejects_unbraced_name(n9_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    for bad in ("HOUJIN_NAME", "{HOUJIN_NAME}", "{{HOUJIN_NAME"):
        out = resolve_placeholder(
            placeholder_name=bad,
            context_dict_json="{}",
        )
        assert out["total"] == 0
        assert out["primary_result"]["status"] == "empty"


def test_n9_rejects_invalid_context_json(n9_db: Path) -> None:
    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    out = resolve_placeholder(
        placeholder_name="{{HOUJIN_NAME}}",
        context_dict_json="not json at all",
    )
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"


def test_n9_db_missing_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "definitely_not_here.db"
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(missing))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(missing))

    from jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder import resolve_placeholder

    out = resolve_placeholder(
        placeholder_name="{{HOUJIN_NAME}}",
        context_dict_json="{}",
    )
    assert out["total"] == 0
    assert out["primary_result"]["status"] == "empty"
    assert "_disclaimer" in out


# ---------------------------------------------------------------------------
# Catalog SOT consistency
# ---------------------------------------------------------------------------


def test_recipe_yaml_catalog_15_files_across_5_segments() -> None:
    """data/recipes/recipe_*.yaml has 15 files spread across 5 segments."""
    rdir = _REPO_ROOT / "data" / "recipes"
    if not rdir.exists():
        pytest.skip("data/recipes/ not present in this checkout")
    files = sorted(rdir.glob("recipe_*.yaml"))
    assert len(files) == 15
    from jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe import _load_recipes

    recipes = _load_recipes()
    seg_counts: dict[str, int] = {}
    for r in recipes:
        seg = str(r.get("segment", ""))
        seg_counts[seg] = seg_counts.get(seg, 0) + 1
    assert seg_counts == {
        "tax": 3,
        "audit": 3,
        "gyousei": 3,
        "shihoshoshi": 3,
        "ax_fde": 3,
    }


def test_placeholder_mappings_json_has_at_least_200_entries() -> None:
    """data/placeholder_mappings.json catalog must hold ~200 entries."""
    import json

    path = _REPO_ROOT / "data" / "placeholder_mappings.json"
    if not path.exists():
        pytest.skip("data/placeholder_mappings.json not present in this checkout")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    mappings = data["mappings"]
    assert isinstance(mappings, list)
    assert len(mappings) >= 200
    names = {m["placeholder_name"] for m in mappings}
    assert len(names) == len(mappings), "placeholder names must be unique"
    # Canonical brace shape on every entry.
    for m_row in mappings:
        n = m_row["placeholder_name"]
        assert n.startswith("{{") and n.endswith("}}"), f"bad shape: {n}"


def test_no_llm_imports_in_moat_n8_n9() -> None:
    """N8 + N9 modules must NOT import any LLM SDK."""
    import jpintel_mcp.mcp.moat_lane_tools.moat_n8_recipe as n8
    import jpintel_mcp.mcp.moat_lane_tools.moat_n9_placeholder as n9

    forbidden = ("anthropic", "openai", "google.generativeai", "claude_agent_sdk")
    for mod in (n8, n9):
        path = Path(mod.__file__)
        src = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in src, f"{path.name} imports forbidden LLM SDK: {needle}"
