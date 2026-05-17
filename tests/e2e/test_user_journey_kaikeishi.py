"""D4 E2E user-journey simulation — 会計士 監査調書 シナリオ.

Flow (agent → jpcite MCP):

    1. get_houjin_portfolio → fetch the audit target's program portfolio
    2. get_artifact_template("会計士", "kansa_chosho")
    3. walk_reasoning_chain("監査調書") → fetch the deterministic 監査基準 chain
    4. resolve_placeholder({{COMPANY_NAME}}) → MCP query schema
    5. get_houjin_360_am(field=name)
    6. render draft, assert closure.

The 会計士 surface is special because the reasoning chain step makes the
walk visible — auditors need a citation of the 監査基準委員会報告書 chain so
that the synthesized draft cites a deterministic precedent rather than a
hallucinated rationale.
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
        "segment": "会計士",
        "artifact_type": "kansa_chosho",
        "artifact_name_ja": "監査調書",
        "authority": "金商法 §193の2",
        "sensitive_act": "公認会計士法 §47条の2",
        "structure": {
            "sections": [
                {
                    "id": "header",
                    "title": "監査調書ヘッダ",
                    "paragraphs": [
                        "{{COMPANY_NAME}} 監査調書",
                        "会計年度: {{FISCAL_YEAR}}",
                    ],
                },
                {
                    "id": "scope",
                    "title": "監査範囲",
                    "paragraphs": [
                        "監査基準委員会報告書230に従い、監査の各段階で十分かつ適切な記録を残す。",
                    ],
                },
                {
                    "id": "signoff",
                    "title": "署名欄",
                    "paragraphs": [
                        "担当公認会計士: {{CPA_NAME}}",
                        "関与社員: {{PARTNER_NAME}}",
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
                "key": "FISCAL_YEAR",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "会計年度",
            },
            {
                "key": "CPA_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "担当公認会計士氏名",
            },
            {
                "key": "PARTNER_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "関与社員氏名",
            },
        ],
    },
]


@pytest.fixture()
def kaikeishi_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "autonomath_kaikeishi.db"
    seed_journey_db(db_path, templates=_TEMPLATES)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    return db_path


def test_kaikeishi_journey_resolves_all_placeholders(kaikeishi_db: Path) -> None:
    agent = JourneyAgent(registry=build_mcp_registry())

    # Step 1: audit target portfolio (sanity probe — confirms portfolio
    # surface is reachable for the auditor's risk-rank flow).
    portfolio = agent.invoke("get_houjin_portfolio", {"houjin_bangou": TEST_HOUJIN_BANGOU})
    # Even an empty/unhealthy portfolio is acceptable; we only assert the
    # envelope shape — the auditor decides downstream.
    assert "primary_result" in portfolio

    # Step 2: fetch the 監査調書 template.
    tpl_envelope = agent.invoke(
        "get_artifact_template",
        {"segment": "会計士", "artifact_type": "kansa_chosho"},
    )
    assert tpl_envelope["total"] == 1
    template = tpl_envelope["primary_result"]
    assert template["sensitive_act"] == "公認会計士法 §47条の2"

    # Step 3: walk the reasoning chain so the auditor cites the precedent
    # behind the 監査基準 selection.
    chain_envelope = agent.invoke(
        "walk_reasoning_chain",
        {"query": "監査調書", "category": "corporate_tax"},
    )
    # walk_reasoning_chain returns at least the canonical envelope shape;
    # the chain itself may be empty under sparse fixture data — we only
    # assert that the auditor's reasoning step was recorded.
    assert "primary_result" in chain_envelope or "results" in chain_envelope

    # Step 4-5: resolve + dispatch COMPANY_NAME.
    company_mapping = agent.invoke(
        "resolve_placeholder",
        {
            "placeholder_name": "{{COMPANY_NAME}}",
            "context_dict_json": '{"houjin_bangou": "' + TEST_HOUJIN_BANGOU + '"}',
        },
    )
    args = company_mapping["primary_result"]["args_substituted"]
    name_envelope = agent.invoke("get_houjin_360_am", args)
    company_name = name_envelope.get("name") or name_envelope["primary_result"].get("name")
    assert company_name == "Bookyou株式会社"

    # Step 6: assemble the rendered draft.
    context: dict[str, object] = {
        "HOUJIN_BANGOU": TEST_HOUJIN_BANGOU,
        "FISCAL_YEAR": "2026-04-01〜2027-03-31",
        "CPA_NAME": "佐藤 公認",
        "PARTNER_NAME": "鈴木 関与",
        "COMPANY_NAME": company_name,
    }
    expected_keys = collect_template_placeholders(template["structure"])
    assert set(expected_keys) <= set(context)
    draft, unresolved = render_artifact(template["structure"], context)
    assert unresolved == [], f"unresolved placeholders: {unresolved}"
    assert "監査基準委員会報告書230" in draft
    assert "佐藤 公認" in draft

    # Step 7: cost & call accounting.
    #   get_houjin_portfolio        (1)
    #   get_artifact_template       (1)
    #   walk_reasoning_chain        (1)
    #   resolve_placeholder         (1)
    #   get_houjin_360_am           (1)
    # → 5 calls × ¥3 = ¥15
    assert agent.ledger.total_calls == 5
    assert agent.ledger.total_cost_jpy == 15
    assert agent.ledger.tools_called() == [
        "get_houjin_portfolio",
        "get_artifact_template",
        "walk_reasoning_chain",
        "resolve_placeholder",
        "get_houjin_360_am",
    ]
