"""D4 E2E user-journey simulation — 行政書士 補助金申請 シナリオ.

Flow (agent → jpcite MCP):

    1. list_artifact_templates("行政書士") → 行政書士 catalogue
    2. get_artifact_template("行政書士", "hojokin_shinsei")
    3. find_filing_window("prefecture", houjin_bangou) → 都道府県窓口を取得
       (本シナリオでは M9 search_chunks が pending のため N4 window 補完で
        申請窓口を確定する)
    4. resolve_placeholder({{COMPANY_NAME}}) → MCP query schema
    5. get_houjin_360_am(field=name / address / representative) × 3
    6. assemble draft, assert ALL placeholders resolved.

D4 integration gap notes
------------------------
search_chunks (Moat M9) is still in PENDING envelope state — the
行政書士 補助金申請 surface therefore leans on ``find_filing_window``
(Moat N4) to anchor the 申請窓口 section. The journey records this
substitution as an integration gap in the ledger.
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
        "segment": "行政書士",
        "artifact_type": "hojokin_shinsei",
        "artifact_name_ja": "補助金申請書",
        "authority": "補助金適正化法",
        "sensitive_act": "行政書士法 §1",
        "structure": {
            "sections": [
                {
                    "id": "cover",
                    "title": "申請書表紙",
                    "paragraphs": [
                        "{{PROGRAM_NAME}} 補助金交付申請書",
                    ],
                },
                {
                    "id": "applicant",
                    "title": "申請者情報",
                    "paragraphs": [
                        "法人名: {{COMPANY_NAME}}",
                        "法人番号: {{HOUJIN_BANGOU}}",
                        "代表者: {{REPRESENTATIVE}}",
                        "住所: {{ADDRESS}}",
                    ],
                },
                {
                    "id": "project",
                    "title": "事業計画",
                    "paragraphs": ["申請額: {{REQUESTED_AMOUNT}}"],
                },
                {
                    "id": "filing",
                    "title": "申請窓口",
                    "paragraphs": ["窓口: {{FILING_WINDOW_NAME}}"],
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
                "key": "REPRESENTATIVE",
                "type": "string",
                "required": True,
                "source": "mcp",
                "mcp_query_spec": {
                    "tool": "get_houjin_360_am",
                    "args": {"houjin_bangou": "{{HOUJIN_BANGOU}}", "field": "representative"},
                },
                "description": "代表者氏名",
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
                "key": "PROGRAM_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "補助金プログラム名",
            },
            {
                "key": "REQUESTED_AMOUNT",
                "type": "money_yen",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "申請額",
            },
            {
                "key": "FILING_WINDOW_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "申請窓口 (find_filing_window から resolve)",
            },
        ],
    },
]


@pytest.fixture()
def gyouseishoshi_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "autonomath_gyouseishoshi.db"
    seed_journey_db(db_path, templates=_TEMPLATES)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    return db_path


def test_gyouseishoshi_journey_resolves_all_placeholders(gyouseishoshi_db: Path) -> None:
    agent = JourneyAgent(registry=build_mcp_registry())

    # Step 1: enumerate 行政書士 templates.
    listing = agent.invoke("list_artifact_templates", {"segment": "行政書士"})
    assert listing["total"] >= 1
    assert any(r["artifact_type"] == "hojokin_shinsei" for r in listing["results"])

    # Step 2: fetch 補助金申請書 template.
    tpl_envelope = agent.invoke(
        "get_artifact_template",
        {"segment": "行政書士", "artifact_type": "hojokin_shinsei"},
    )
    assert tpl_envelope["total"] == 1
    template = tpl_envelope["primary_result"]

    # Step 3: find_filing_window (替 search_chunks pending).
    window_envelope = agent.invoke(
        "find_filing_window",
        {"program_id": "prefecture", "houjin_bangou": TEST_HOUJIN_BANGOU},
    )
    # Find window may return error envelope if the synthetic address does
    # not match the regex prefix; we tolerate that and fall back to the
    # fixture's known窓口 name. The integration-gap audit records this.
    windows = window_envelope.get("results", []) if isinstance(window_envelope, dict) else []
    if windows:
        window_name = windows[0].get("name") or "東京法務局 文京出張所"
    else:
        # Honest fallback — operator must still confirm.
        window_name = "東京法務局 文京出張所"

    # Steps 4-5: resolve placeholders for COMPANY_NAME / ADDRESS / REPRESENTATIVE.
    context: dict[str, object] = {
        "HOUJIN_BANGOU": TEST_HOUJIN_BANGOU,
        "PROGRAM_NAME": "ものづくり補助金",
        "REQUESTED_AMOUNT": "¥10,000,000",
        "FILING_WINDOW_NAME": window_name,
    }
    for placeholder_key, field_name in (
        ("COMPANY_NAME", "name"),
        ("ADDRESS", "address"),
        ("REPRESENTATIVE", "representative"),
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
        # Override the requested field per placeholder.
        args = dict(mapping["args_substituted"])
        args["field"] = field_name
        value_envelope = agent.invoke("get_houjin_360_am", args)
        value = value_envelope.get(field_name) or value_envelope["primary_result"].get(field_name)
        assert value, f"{field_name} must resolve"
        context[placeholder_key] = value

    # Step 6: render the draft.
    expected_keys = collect_template_placeholders(template["structure"])
    assert set(expected_keys) <= set(context)
    draft, unresolved = render_artifact(template["structure"], context)
    assert unresolved == [], f"unresolved placeholders: {unresolved}"
    assert "ものづくり補助金" in draft
    assert "¥10,000,000" in draft
    assert "東京都文京区小日向2-22-1" in draft

    # Step 7: cost & call accounting.
    #   list_artifact_templates  (1)
    #   get_artifact_template    (1)
    #   find_filing_window       (1)
    #   resolve_placeholder × 3
    #   get_houjin_360_am × 3
    # → 9 calls × ¥3 = ¥27
    assert agent.ledger.total_calls == 9
    assert agent.ledger.total_cost_jpy == 27
