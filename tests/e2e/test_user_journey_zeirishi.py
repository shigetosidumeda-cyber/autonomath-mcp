"""D4 E2E user-journey simulation — 税理士 月次決算 シナリオ.

Flow (agent → jpcite MCP):

    1. get_houjin_360 (via wrapper) → fetch name / address / representative
    2. list_artifact_templates("税理士") → enumerate available templates
    3. get_artifact_template("税理士", "gessji_shiwake") → fetch the template
    4. resolve_placeholder per session placeholder → confirm canonical schema
    5. assemble the rendered draft from context dict
    6. assert all {{...}} placeholders resolve (no leftovers)
    7. assert total MCP cost = 3 * call_count

The test exercises the production moat_lane_tools modules against a
disposable in-memory autonomath.db fixture so the journey closes on a
fully rendered scaffold — proving the lane-N1 / lane-N9 contract is
e2e-coherent for the 税理士 surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from tests.e2e._journey_fixtures import (
    TEST_HOUJIN_BANGOU,
    JourneyAgent,
    build_mcp_registry,
    collect_template_placeholders,
    render_artifact,
    seed_journey_db,
)

_TEMPLATES = [
    {
        "segment": "税理士",
        "artifact_type": "gessji_shiwake",
        "artifact_name_ja": "月次仕訳",
        "authority": "法人税法 §22",
        "sensitive_act": "税理士法 §52",
        "structure": {
            "sections": [
                {
                    "id": "header",
                    "title": "ヘッダ",
                    "paragraphs": [
                        "{{COMPANY_NAME}} 月次仕訳帳",
                        "対象月: {{TARGET_MONTH}}",
                    ],
                },
                {
                    "id": "journal",
                    "title": "仕訳明細",
                    "paragraphs": ["勘定科目 / 借方 / 貸方 / 摘要"],
                },
                {
                    "id": "footer",
                    "title": "署名欄",
                    "paragraphs": [
                        "作成: {{PREPARER_NAME}} / 確認: 税理士 {{ZEIRISHI_NAME}}",
                    ],
                },
            ]
        },
        "placeholders": [
            {
                "key": "COMPANY_NAME",
                "type": "string",
                "required": True,
                "source": "mcp",
                "mcp_query_spec": {
                    "tool": "get_houjin_360_am",
                    "args": {"houjin_bangou": "{{HOUJIN_BANGOU}}", "field": "name"},
                },
                "description": "法人名 (houjin_bangou から resolve)",
            },
            {
                "key": "HOUJIN_BANGOU",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "法人番号",
            },
            {
                "key": "TARGET_MONTH",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "対象月 (YYYY-MM)",
            },
            {
                "key": "PREPARER_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "作成者氏名",
            },
            {
                "key": "ZEIRISHI_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "担当税理士氏名",
            },
        ],
    },
]


@pytest.fixture()
def zeirishi_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "autonomath_zeirishi.db"
    seed_journey_db(db_path, templates=_TEMPLATES)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    return db_path


def test_zeirishi_journey_resolves_all_placeholders(zeirishi_db: Path) -> None:
    """Run the full 税理士 月次決算 journey and assert closure."""

    agent = JourneyAgent(registry=build_mcp_registry())

    # Step 1: agent enumerates available templates for the 税理士 segment.
    listing = agent.invoke("list_artifact_templates", {"segment": "税理士"})
    assert listing["total"] >= 1
    artifact_types = [r["artifact_type"] for r in listing["results"]]
    assert "gessji_shiwake" in artifact_types

    # Step 2: agent fetches the chosen template.
    tpl_envelope = agent.invoke(
        "get_artifact_template",
        {"segment": "税理士", "artifact_type": "gessji_shiwake"},
    )
    assert tpl_envelope["total"] == 1
    template = tpl_envelope["primary_result"]
    assert template["uses_llm"] is False, "templates must be NO_LLM scaffolds"
    assert template["is_scaffold_only"] is True
    assert template["requires_professional_review"] is True

    # Step 3: agent gathers session-provided context (no MCP call needed)
    context: dict[str, object] = {
        "HOUJIN_BANGOU": TEST_HOUJIN_BANGOU,
        "TARGET_MONTH": "2026-05",
        "PREPARER_NAME": "経理担当 田中",
        "ZEIRISHI_NAME": "山田 太郎",
    }

    # Step 4: agent resolves the MCP-sourced placeholder ({{COMPANY_NAME}}).
    company_envelope = agent.invoke(
        "resolve_placeholder",
        {
            "placeholder_name": "{{COMPANY_NAME}}",
            "context_dict_json": '{"houjin_bangou": "' + TEST_HOUJIN_BANGOU + '"}',
        },
    )
    assert company_envelope["total"] == 1
    mapping = company_envelope["primary_result"]
    assert mapping["mcp_tool_name"] == "get_houjin_360_am"
    assert mapping["substitution_complete"] is True

    # Step 5: agent dispatches the resolved MCP call to fetch the actual value.
    name_envelope = agent.invoke(
        "get_houjin_360_am",
        mapping["args_substituted"],
    )
    company_name = name_envelope.get("name") or name_envelope["primary_result"].get("name")
    assert company_name, "company name must resolve to a real string"
    context["COMPANY_NAME"] = company_name

    # Step 6: render the draft and assert ALL placeholders are resolved.
    expected_keys = collect_template_placeholders(template["structure"])
    assert set(expected_keys) <= set(context), (
        f"context is missing placeholders: {set(expected_keys) - set(context)}"
    )
    draft, unresolved = render_artifact(template["structure"], context)
    assert unresolved == [], f"unresolved placeholders: {unresolved}"
    assert "Bookyou株式会社 月次仕訳帳" in draft
    assert "2026-05" in draft
    assert "山田 太郎" in draft

    # Step 7: cost & call accounting.
    #   - list_artifact_templates (1)
    #   - get_artifact_template   (1)
    #   - resolve_placeholder     (1) for COMPANY_NAME
    #   - get_houjin_360_am       (1) for COMPANY_NAME value
    #
    # Session placeholders (HOUJIN_BANGOU/TARGET_MONTH/PREPARER_NAME/ZEIRISHI_NAME)
    # do not require an MCP call. So total = 4 calls × ¥3 = ¥12.
    assert agent.ledger.total_calls == 4, agent.ledger.tools_called()
    assert agent.ledger.total_cost_jpy == 12

    # Sanity: every recorded call carries the canonical tool name.
    assert agent.ledger.tools_called() == [
        "list_artifact_templates",
        "get_artifact_template",
        "resolve_placeholder",
        "get_houjin_360_am",
    ]
