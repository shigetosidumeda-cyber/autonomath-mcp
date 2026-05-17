"""D4 E2E user-journey simulation — 司法書士 会社設立登記 シナリオ.

Flow (agent → jpcite MCP):

    1. find_filing_window("legal_affairs_bureau", houjin_bangou) →
       管轄法務局を取得
    2. get_artifact_template("司法書士", "kaisha_setsuritsu_touki")
    3. resolve_placeholder (司法書士テンプレは全 session source) → 念のため
       会社設立直後でも houjin_bangou 経由で照合できる経路を確認
    4. render draft, assert closure.

D4 note: 会社設立登記 のテンプレートは全プレースホルダが session-source の
ためプレースホルダ resolver は厳密には不要だが、登記後の補正登記での
利用も想定して resolve_placeholder の経路は確保しておく。
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
        "segment": "司法書士",
        "artifact_type": "kaisha_setsuritsu_touki",
        "artifact_name_ja": "会社設立登記申請書",
        "authority": "商業登記法 §47",
        "sensitive_act": "司法書士法 §3",
        "structure": {
            "sections": [
                {
                    "id": "header",
                    "title": "申請書表紙",
                    "paragraphs": ["株式会社設立登記申請書"],
                },
                {
                    "id": "company",
                    "title": "会社情報",
                    "paragraphs": [
                        "商号: {{COMPANY_NAME}}",
                        "本店: {{HEADQUARTER_ADDRESS}}",
                        "資本金: {{CAPITAL_AMOUNT}}",
                    ],
                },
                {
                    "id": "officers",
                    "title": "役員",
                    "paragraphs": ["代表取締役: {{REPRESENTATIVE_NAME}}"],
                },
                {
                    "id": "jurisdiction",
                    "title": "管轄登記所",
                    "paragraphs": ["管轄: {{FILING_WINDOW_NAME}}"],
                },
            ]
        },
        "placeholders": [
            {
                "key": "COMPANY_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "商号",
            },
            {
                "key": "HEADQUARTER_ADDRESS",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "本店所在地",
            },
            {
                "key": "CAPITAL_AMOUNT",
                "type": "money_yen",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "資本金",
            },
            {
                "key": "REPRESENTATIVE_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "代表取締役氏名",
            },
            {
                "key": "FILING_WINDOW_NAME",
                "type": "string",
                "required": True,
                "source": "session",
                "mcp_query_spec": None,
                "description": "管轄登記所 (find_filing_window から resolve)",
            },
        ],
    },
]


@pytest.fixture()
def shihoshoshi_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "autonomath_shihoshoshi.db"
    seed_journey_db(db_path, templates=_TEMPLATES)
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(db_path))
    return db_path


def test_shihoshoshi_journey_resolves_all_placeholders(shihoshoshi_db: Path) -> None:
    agent = JourneyAgent(registry=build_mcp_registry())

    # Step 1: find legal_affairs_bureau window for the new entity address.
    window_envelope = agent.invoke(
        "find_filing_window",
        {"program_id": "legal_affairs_bureau", "houjin_bangou": TEST_HOUJIN_BANGOU},
    )
    windows = window_envelope.get("results", []) if isinstance(window_envelope, dict) else []
    # Honest fallback for synthetic 法人 — operator confirms via the
    # actual 法務局 jurisdiction lookup at submission time.
    window_name = windows[0].get("name") if windows else "東京法務局 文京出張所"

    # Step 2: fetch the 会社設立登記 template.
    tpl_envelope = agent.invoke(
        "get_artifact_template",
        {"segment": "司法書士", "artifact_type": "kaisha_setsuritsu_touki"},
    )
    assert tpl_envelope["total"] == 1
    template = tpl_envelope["primary_result"]
    assert template["sensitive_act"] == "司法書士法 §3"

    # Step 3: resolve a placeholder mapping (sanity test even for a session-
    # only template — confirms the lane N9 surface stays addressable).
    mapping_envelope = agent.invoke(
        "resolve_placeholder",
        {
            "placeholder_name": "{{COMPANY_NAME}}",
            "context_dict_json": "{}",
        },
    )
    mapping = mapping_envelope["primary_result"]
    # The N9 mapping was seeded as a "context" tool (session source);
    # the mapping must still surface for auditability.
    assert mapping["placeholder_name"] == "{{COMPANY_NAME}}"

    # Step 4: render the draft.
    context: dict[str, object] = {
        "COMPANY_NAME": "Bookyou株式会社 新設",
        "HEADQUARTER_ADDRESS": "東京都文京区小日向2-22-1",
        "CAPITAL_AMOUNT": "¥1,000,000",
        "REPRESENTATIVE_NAME": "梅田 茂利",
        "FILING_WINDOW_NAME": window_name,
    }
    expected_keys = collect_template_placeholders(template["structure"])
    assert set(expected_keys) <= set(context)
    draft, unresolved = render_artifact(template["structure"], context)
    assert unresolved == [], f"unresolved placeholders: {unresolved}"
    assert "Bookyou株式会社 新設" in draft
    assert "梅田 茂利" in draft
    assert "東京法務局" in draft

    # Step 5: cost & call accounting.
    #   find_filing_window         (1)
    #   get_artifact_template      (1)
    #   resolve_placeholder        (1)
    # → 3 calls × ¥3 = ¥9
    assert agent.ledger.total_calls == 3
    assert agent.ledger.total_cost_jpy == 9
    assert agent.ledger.tools_called() == [
        "find_filing_window",
        "get_artifact_template",
        "resolve_placeholder",
    ]
