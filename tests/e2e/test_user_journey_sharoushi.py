"""D4 E2E user-journey simulation — 社労士 就業規則 シナリオ.

Flow (agent → jpcite MCP):

    1. get_artifact_template("社労士", "shuugyou_kisoku")
    2. resolve_placeholder({{COMPANY_NAME}}) + dispatch get_houjin_360_am
    3. resolve_placeholder({{ADDRESS}}) + dispatch get_houjin_360_am
    4. Fill 36協定 metadata fields from session.
    5. render draft, assert closure.

D4 audit note
-------------
The 36協定 sub-template (LEGAL_BASIS_LABOR_89 placeholder, originally bound
to ``get_law_article_am``) is gated by AUTONOMATH_36_KYOTEI_ENABLED in
production. For the journey simulation we substitute the law-reference
value with a deterministic 一次URL pointer so the test does not depend
on the gated tool surfacing. The integration gap is recorded in the
MOAT_E2E_JOURNEY_2026_05_17.md gap matrix.
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
        "segment": "社労士",
        "artifact_type": "shuugyou_kisoku",
        "artifact_name_ja": "就業規則",
        "authority": "労基法 §89",
        "sensitive_act": "社労士法 §27",
        "structure": {
            "sections": [
                {
                    "id": "general",
                    "title": "総則",
                    "paragraphs": [
                        "事業所: {{COMPANY_NAME}}",
                        "所在地: {{ADDRESS}}",
                        "施行日: {{EFFECTIVE_DATE}}",
                    ],
                },
                {
                    "id": "work_hours",
                    "title": "労働時間・休憩・休日",
                    "paragraphs": [
                        "所定労働時間: {{WORKING_HOURS_DAILY}} 時間/日",
                    ],
                },
                {
                    "id": "leave",
                    "title": "休暇",
                    "paragraphs": ["年次有給休暇: {{ANNUAL_LEAVE_DAYS}} 日"],
                },
                {
                    "id": "legal",
                    "title": "法的根拠",
                    "paragraphs": ["根拠条文: {{LEGAL_BASIS_LABOR_89}}"],
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
                "key": "ADDRESS",
                "type": "string",
                "required": True,
                "source": "mcp",
                "mcp_query_spec": {
                    "tool": "get_houjin_360_am",
                    "args": {"houjin_bangou": "{{HOUJIN_BANGOU}}", "field": "address"},
                },
                "description": "本店所在地",
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
                "key": "EFFECTIVE_DATE",
                "type": "date",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "施行日",
            },
            {
                "key": "WORKING_HOURS_DAILY",
                "type": "decimal",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "所定労働時間 (時間/日)",
            },
            {
                "key": "ANNUAL_LEAVE_DAYS",
                "type": "integer",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "年次有給休暇 (日数)",
            },
            {
                "key": "LEGAL_BASIS_LABOR_89",
                "type": "law_ref",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "労基法 §89 (一次URL pointer)",
            },
        ],
    },
]


@pytest.fixture()
def sharoushi_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "autonomath_sharoushi.db"
    seed_journey_db(db_path, templates=_TEMPLATES)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    return db_path


def test_sharoushi_journey_resolves_all_placeholders(sharoushi_db: Path) -> None:
    agent = JourneyAgent(registry=build_mcp_registry())

    # Step 1: fetch 就業規則 template.
    tpl_envelope = agent.invoke(
        "get_artifact_template",
        {"segment": "社労士", "artifact_type": "shuugyou_kisoku"},
    )
    assert tpl_envelope["total"] == 1
    template = tpl_envelope["primary_result"]
    assert template["authority"] == "労基法 §89"

    # Steps 2-3: resolve + dispatch COMPANY_NAME + ADDRESS.
    context: dict[str, object] = {
        "HOUJIN_BANGOU": TEST_HOUJIN_BANGOU,
        "EFFECTIVE_DATE": "2026-06-01",
        "WORKING_HOURS_DAILY": "8.0",
        "ANNUAL_LEAVE_DAYS": "20",
        # AUTONOMATH_36_KYOTEI_ENABLED is gated; use a 一次URL pointer
        # so the scaffold remains honest about the legal basis.
        "LEGAL_BASIS_LABOR_89": "https://elaws.e-gov.go.jp/document?lawid=322AC0000000049 §89",
    }
    for placeholder_key, field_name in (
        ("COMPANY_NAME", "name"),
        ("ADDRESS", "address"),
    ):
        mapping_envelope = agent.invoke(
            "resolve_placeholder",
            {
                "placeholder_name": "{{" + placeholder_key + "}}",
                "context_dict_json": '{"houjin_bangou": "' + TEST_HOUJIN_BANGOU + '"}',
            },
        )
        mapping = mapping_envelope["primary_result"]
        assert mapping["mcp_tool_name"] == "get_houjin_360_am"
        args = dict(mapping["args_substituted"])
        args["field"] = field_name
        value_envelope = agent.invoke("get_houjin_360_am", args)
        value = value_envelope.get(field_name) or value_envelope["primary_result"].get(field_name)
        assert value
        context[placeholder_key] = value

    # Step 4: render the draft.
    expected_keys = collect_template_placeholders(template["structure"])
    assert set(expected_keys) <= set(context)
    draft, unresolved = render_artifact(template["structure"], context)
    assert unresolved == [], f"unresolved placeholders: {unresolved}"
    assert "8.0 時間/日" in draft
    assert "20 日" in draft
    assert "elaws.e-gov.go.jp" in draft

    # Step 5: cost & call accounting.
    #   get_artifact_template      (1)
    #   resolve_placeholder × 2
    #   get_houjin_360_am × 2
    # → 5 calls × ¥3 = ¥15
    assert agent.ledger.total_calls == 5
    assert agent.ledger.total_cost_jpy == 15
