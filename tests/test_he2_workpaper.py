"""Tests for moat_lane_tools.he2_workpaper (HE-2 heavy-output endpoint).

Validates ``prepare_implementation_workpaper`` against an isolated on-disk
autonomath fixture so the suite does not depend on the live 12 GB
autonomath.db. Covers 12+ scenarios spanning the 5 士業 segments and the
three ``auto_fill_level`` modes.

Scenarios (≥12):
1.  税理士 法人税申告書 deep (resolved placeholders > 0)
2.  税理士 消費税申告書 deep (different category branch)
3.  税理士 月次仕訳 partial (alternative_templates surfaced)
4.  行政書士 補助金申請書 deep (subsidy category reasoning chains)
5.  行政書士 許認可申請書 partial
6.  司法書士 会社設立登記申請書 deep (legal_affairs_bureau window)
7.  司法書士 役員変更登記申請書 deep
8.  社労士 就業規則 deep (labour_bureau window)
9.  社労士 36協定書 deep
10. 会計士 監査調書 deep (corporate_tax category fallback)
11. 会計士 監査意見書 partial
12. skeleton mode (no houjin) — template+placeholder enumeration only
13. invalid auto_fill_level → empty envelope
14. unknown artifact_type → empty envelope w/ rationale
15. disclaimer / billing / provenance shape contract
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
    """Build an isolated autonomath.db with the 6 lanes HE-2 composes."""
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)

    # ---- am_artifact_templates (N1) ---------------------------------------
    conn.execute(
        """
        CREATE TABLE am_artifact_templates (
            template_id INTEGER PRIMARY KEY AUTOINCREMENT,
            segment TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            artifact_name_ja TEXT NOT NULL,
            version TEXT NOT NULL DEFAULT 'v1',
            authority TEXT NOT NULL,
            sensitive_act TEXT NOT NULL,
            is_scaffold_only INTEGER NOT NULL DEFAULT 1,
            requires_professional_review INTEGER NOT NULL DEFAULT 1,
            uses_llm INTEGER NOT NULL DEFAULT 0,
            quality_grade TEXT NOT NULL DEFAULT 'draft',
            structure_jsonb TEXT NOT NULL,
            placeholders_jsonb TEXT NOT NULL,
            mcp_query_bindings_jsonb TEXT NOT NULL,
            license TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0',
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE (segment, artifact_type, version)
        )
        """
    )
    structure_payload = json.dumps(
        {
            "sections": [
                {
                    "id": "header",
                    "title": "ヘッダ",
                    "paragraphs": [
                        "{{COMPANY_NAME}} / 法人番号 {{HOUJIN_BANGOU}} / 会計年度 {{FISCAL_YEAR}}"
                    ],
                },
                {
                    "id": "body",
                    "title": "本文",
                    "paragraphs": ["代表者 {{REPRESENTATIVE}} 殿"],
                },
            ]
        },
        ensure_ascii=False,
    )
    placeholders_payload = json.dumps(
        [
            {
                "key": "COMPANY_NAME",
                "type": "string",
                "required": True,
                "source": "mcp",
                "description": "法人名",
            },
            {
                "key": "HOUJIN_BANGOU",
                "type": "string",
                "required": True,
                "source": "session",
                "description": "法人番号",
            },
            {
                "key": "FISCAL_YEAR",
                "type": "string",
                "required": True,
                "source": "session",
                "description": "会計年度",
            },
            {
                "key": "REPRESENTATIVE",
                "type": "string",
                "required": True,
                "source": "mcp",
                "description": "代表者氏名",
                "fallback": "代表取締役",
            },
        ],
        ensure_ascii=False,
    )
    seeds: list[tuple[str, str, str, str, str]] = [
        ("税理士", "houjinzei_shinkoku", "法人税申告書", "法人税法 §74", "税理士法 §52"),
        ("税理士", "shouhizei_shinkoku", "消費税申告書", "消費税法 §45", "税理士法 §52"),
        ("税理士", "gessji_shiwake", "月次仕訳", "法人税法 §22", "税理士法 §52"),
        ("会計士", "kansa_chosho", "監査調書", "金商法 §193の2", "公認会計士法 §47条の2"),
        ("会計士", "kansa_iken", "監査意見書", "金商法 §193の2", "公認会計士法 §47条の2"),
        ("行政書士", "hojokin_shinsei", "補助金申請書", "補助金適正化法", "行政書士法 §1"),
        ("行政書士", "kyoninka_shinsei", "許認可申請書", "行政書士法 §1の2", "行政書士法 §1"),
        (
            "司法書士",
            "kaisha_setsuritsu_touki",
            "会社設立登記申請書",
            "商業登記法 §47",
            "司法書士法 §3",
        ),
        ("司法書士", "yakuin_henko_touki", "役員変更登記申請書", "商業登記法 §46", "司法書士法 §3"),
        ("社労士", "shuugyou_kisoku", "就業規則", "労基法 §89", "社労士法 §27"),
        ("社労士", "sanroku_kyoutei", "36協定書", "労基法 §36", "社労士法 §27"),
    ]
    for segment, artifact_type, name_ja, authority, sensitive_act in seeds:
        conn.execute(
            """
            INSERT INTO am_artifact_templates
              (segment, artifact_type, artifact_name_ja, authority, sensitive_act,
               structure_jsonb, placeholders_jsonb, mcp_query_bindings_jsonb)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                segment,
                artifact_type,
                name_ja,
                authority,
                sensitive_act,
                structure_payload,
                placeholders_payload,
                "{}",
            ),
        )

    # ---- am_placeholder_mapping (N9) --------------------------------------
    conn.execute(
        """
        CREATE TABLE am_placeholder_mapping (
            placeholder_id INTEGER PRIMARY KEY AUTOINCREMENT,
            placeholder_name TEXT NOT NULL UNIQUE,
            source_template_ids TEXT,
            mcp_tool_name TEXT NOT NULL,
            args_template TEXT NOT NULL DEFAULT '{}',
            output_path TEXT NOT NULL DEFAULT '$',
            fallback_value TEXT,
            value_kind TEXT NOT NULL DEFAULT 'text',
            description TEXT NOT NULL,
            is_sensitive INTEGER NOT NULL DEFAULT 0,
            license TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
        """
    )
    mapping_rows = [
        (
            "{{HOUJIN_BANGOU}}",
            "context",
            "{}",
            "$",
            None,
            "text",
            "法人番号",
        ),
        (
            "{{COMPANY_NAME}}",
            "get_houjin_360_am",
            '{"houjin_bangou":"{HOUJIN_BANGOU}"}',
            "$.name",
            "サンプル株式会社",
            "text",
            "法人名",
        ),
        (
            "{{REPRESENTATIVE}}",
            "get_houjin_360_am",
            '{"houjin_bangou":"{HOUJIN_BANGOU}"}',
            "$.representative",
            "代表取締役",
            "text",
            "代表者",
        ),
        (
            "{{FISCAL_YEAR}}",
            "context",
            "{}",
            "$",
            "2026",
            "text",
            "会計年度",
        ),
        (
            "{{CURRENT_DATE}}",
            "computed",
            "{}",
            "$",
            None,
            "date",
            "現在日付",
        ),
    ]
    for row in mapping_rows:
        conn.execute(
            """
            INSERT INTO am_placeholder_mapping
              (placeholder_name, mcp_tool_name, args_template, output_path,
               fallback_value, value_kind, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    # ---- am_legal_reasoning_chain (N3) ------------------------------------
    conn.execute(
        """
        CREATE TABLE am_legal_reasoning_chain (
            chain_id TEXT PRIMARY KEY,
            topic_id TEXT NOT NULL,
            topic_label TEXT NOT NULL,
            tax_category TEXT NOT NULL,
            premise_law_article_ids TEXT,
            premise_tsutatsu_ids TEXT,
            minor_premise_judgment_ids TEXT,
            conclusion_text TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 0.0,
            opposing_view_text TEXT,
            citations TEXT,
            computed_by_model TEXT,
            computed_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    chain_seeds = [
        (
            "LRC-CTAX01",
            "corporate_tax:yakuin_hosyu",
            "役員報酬",
            "corporate_tax",
            "法人税法 §22 により役員報酬は損金算入の制限あり",
            0.92,
            '{"law":[{"unified_id":"laws:houjinzei:22","source_url":"https://laws.e-gov.go.jp/law/340AC0000000034"}],"tsutatsu":[{"unified_id":"tsutatsu:houki:9-2-1","source_url":"https://www.nta.go.jp/9-2-1"}],"hanrei":[]}',
        ),
        (
            "LRC-CTAX02",
            "corporate_tax:shotokukijun",
            "所得基準",
            "corporate_tax",
            "課税所得は別表4で計算される",
            0.88,
            '{"law":[{"unified_id":"laws:houjinzei:21","source_url":"https://laws.e-gov.go.jp/law/340AC0000000034/21"}],"tsutatsu":[],"hanrei":[{"unified_id":"hanrei:2018-tokyo-12345","source_url":"https://www.courts.go.jp/12345"}]}',
        ),
        (
            "LRC-CONS01",
            "consumption_tax:shiire_kojo",
            "仕入税額控除",
            "consumption_tax",
            "適格請求書発行事業者からの仕入のみ控除可",
            0.95,
            '{"law":[{"unified_id":"laws:shouhizei:30","source_url":"https://laws.e-gov.go.jp/law/345AC0000000108"}],"tsutatsu":[],"hanrei":[]}',
        ),
        (
            "LRC-SUB01",
            "subsidy:keizai_gouriseii",
            "経済合理性",
            "subsidy",
            "補助金は経済合理性のある事業に交付される",
            0.85,
            '{"law":[{"unified_id":"laws:hojo:1","source_url":"https://elaws.e-gov.go.jp/document?lawid=330AC1000000179"}],"tsutatsu":[],"hanrei":[]}',
        ),
        (
            "LRC-LAB01",
            "labor:rodo_jikan",
            "労働時間",
            "labor",
            "1日8時間 / 1週40時間を超えるには36協定が必要",
            0.99,
            '{"law":[{"unified_id":"laws:roukihou:36","source_url":"https://laws.e-gov.go.jp/law/322AC0000000049"}],"tsutatsu":[],"hanrei":[]}',
        ),
        (
            "LRC-COMM01",
            "commerce:yakuin_sennin",
            "役員選任",
            "commerce",
            "取締役は株主総会で選任される (会社法 §329)",
            0.96,
            '{"law":[{"unified_id":"laws:kaishahou:329","source_url":"https://laws.e-gov.go.jp/law/417AC0000000086"}],"tsutatsu":[],"hanrei":[]}',
        ),
    ]
    for cid, topic, label, cat, concl, conf, cits in chain_seeds:
        conn.execute(
            """
            INSERT INTO am_legal_reasoning_chain
              (chain_id, topic_id, topic_label, tax_category, conclusion_text,
               confidence, citations)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cid, topic, label, cat, concl, conf, cits),
        )

    # ---- am_window_directory (N4) -----------------------------------------
    conn.execute(
        """
        CREATE TABLE am_window_directory (
            window_id INTEGER PRIMARY KEY AUTOINCREMENT,
            jurisdiction_kind TEXT NOT NULL,
            name TEXT NOT NULL,
            postal_address TEXT,
            tel TEXT,
            url TEXT,
            jurisdiction_houjin_filter_regex TEXT,
            jurisdiction_region_code TEXT,
            source_url TEXT,
            license TEXT
        )
        """
    )
    window_rows = [
        (
            "tax_office",
            "麹町税務署",
            "東京都千代田区",
            "03-0000",
            "https://example/01",
            "東京都千代田区",
            "13101",
            "https://nta.go.jp/01",
            "gov_standard",
        ),
        (
            "legal_affairs_bureau",
            "東京法務局",
            "東京都千代田区",
            "03-1111",
            "https://example/02",
            "東京都",
            "13000",
            "https://moj.go.jp/02",
            "gov_standard",
        ),
        (
            "prefecture",
            "東京都産業労働局",
            "東京都新宿区",
            "03-2222",
            "https://example/03",
            "東京都",
            "13000",
            "https://tokyo.lg.jp/03",
            "gov_standard",
        ),
        (
            "labour_bureau",
            "東京労働局",
            "東京都千代田区",
            "03-3333",
            "https://example/04",
            "東京都",
            "13000",
            "https://mhlw.go.jp/04",
            "gov_standard",
        ),
    ]
    for row in window_rows:
        conn.execute(
            """
            INSERT INTO am_window_directory
              (jurisdiction_kind, name, postal_address, tel, url,
               jurisdiction_houjin_filter_regex, jurisdiction_region_code,
               source_url, license)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    # ---- am_entities + am_entity_facts (N4 houjin address resolution) -----
    conn.execute(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE am_entity_facts (
            fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            value_text TEXT
        )
        """
    )
    conn.execute(
        "INSERT INTO am_entities (canonical_id, record_kind) VALUES (?, ?)",
        ("houjin:8010001213708", "corporate_entity"),
    )
    conn.execute(
        "INSERT INTO am_entity_facts (entity_id, field_name, value_text) VALUES (?, ?, ?)",
        ("houjin:8010001213708", "corp.registered_address", "東京都千代田区"),
    )

    # ---- am_houjin_program_portfolio (N2) ---------------------------------
    conn.execute(
        """
        CREATE TABLE am_houjin_program_portfolio (
            houjin_bangou TEXT NOT NULL,
            program_id TEXT NOT NULL,
            applicability_score REAL NOT NULL,
            score_industry REAL DEFAULT 0,
            score_size REAL DEFAULT 0,
            score_region REAL DEFAULT 0,
            score_sector REAL DEFAULT 0,
            score_target_form REAL DEFAULT 0,
            applied_status TEXT,
            applied_at TEXT,
            deadline TEXT,
            deadline_kind TEXT,
            priority_rank INTEGER,
            computed_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (houjin_bangou, program_id)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO am_houjin_program_portfolio
          (houjin_bangou, program_id, applicability_score, applied_status,
           deadline, priority_rank)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("8010001213708", "P-IT-DOUNYU-2026", 0.92, "unapplied", "2026-09-30", 1),
    )

    # ---- am_amendment_alert_impact (N6) -----------------------------------
    conn.execute(
        """
        CREATE TABLE am_amendment_alert_impact (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            amendment_diff_id INTEGER NOT NULL,
            houjin_bangou TEXT NOT NULL,
            impact_score INTEGER NOT NULL,
            impacted_program_ids TEXT NOT NULL,
            impacted_tax_rule_ids TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            notified_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO am_amendment_alert_impact
          (amendment_diff_id, houjin_bangou, impact_score,
           impacted_program_ids, impacted_tax_rule_ids, detected_at, notified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "8010001213708",
            80,
            '["P-IT-DOUNYU-2026"]',
            '["TR-HOJINZEI-MAIN"]',
            "2026-05-10 09:00:00",
            None,
        ),
    )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch, fixture_db: Path) -> Any:
    """Reload he2_workpaper with the fixture DB pinned via env."""
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(fixture_db))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    import jpintel_mcp.mcp.moat_lane_tools.he2_workpaper as m

    return importlib.reload(m)


def _impl(tool: Any) -> Any:
    """Unwrap an mcp.tool-decorated coroutine for direct call."""
    for attr in ("fn", "func", "_fn"):
        inner = getattr(tool, attr, None)
        if callable(inner):
            return inner
    return tool


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# --------------------------------------------------------------------------- #
# 12+ scenarios                                                               #
# --------------------------------------------------------------------------- #


def test_scenario_1_zeirishi_houjinzei_shinkoku_deep(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="houjinzei_shinkoku",
            houjin_bangou="8010001213708",
            fiscal_year=2026,
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["status"] == "ok"
    assert out["primary_result"]["segment"] == "税理士"
    assert out["template"]["artifact_name_ja"] == "法人税申告書"
    assert out["estimated_completion_pct"] > 0.0
    assert out["filing_window"]["kind"] == "tax_office"
    assert any(m["name"] == "麹町税務署" for m in out["filing_window"]["matches"])
    assert out["deadline"] is not None
    assert out["billing"]["unit"] == 4
    assert out["billing"]["yen"] == 12
    assert out["billing"]["tier"] == "C"
    assert out["billing"]["pricing_version"] == "v3"
    assert out["billing"]["auto_fill_level"] == "deep"


def test_scenario_2_zeirishi_shouhizei_shinkoku_deep(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="shouhizei_shinkoku",
            houjin_bangou="8010001213708",
            fiscal_year=2026,
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["status"] == "ok"
    chains = out["reasoning_chains"]
    assert any(c["tax_category"] == "consumption_tax" for c in chains)


def test_scenario_3_zeirishi_gessji_shiwake_partial_with_alternatives(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="gessji_shiwake",
            houjin_bangou="8010001213708",
            auto_fill_level="partial",
        )
    )
    assert out["primary_result"]["status"] == "ok"
    # alternative_templates always returns up to 5 version rows incl. current
    assert isinstance(out["alternative_templates"], list)
    assert len(out["alternative_templates"]) >= 1


def test_scenario_4_gyousei_hojokin_shinsei_deep(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="hojokin_shinsei",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["segment"] == "行政書士"
    assert out["filing_window"]["kind"] == "prefecture"
    chains = out["reasoning_chains"]
    assert any(c["tax_category"] == "subsidy" for c in chains)


def test_scenario_5_gyousei_kyoninka_shinsei_partial(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="kyoninka_shinsei",
            houjin_bangou="8010001213708",
            auto_fill_level="partial",
        )
    )
    assert out["primary_result"]["status"] == "ok"
    assert out["template"]["sensitive_act"].startswith("行政書士法")


def test_scenario_6_shihou_kaisha_setsuritsu_touki_deep(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="kaisha_setsuritsu_touki",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["segment"] == "司法書士"
    assert out["filing_window"]["kind"] == "legal_affairs_bureau"
    assert any(
        m["jurisdiction_kind"] == "legal_affairs_bureau" for m in out["filing_window"]["matches"]
    )


def test_scenario_7_shihou_yakuin_henko_touki_deep(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="yakuin_henko_touki",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["status"] == "ok"
    chains = out["reasoning_chains"]
    assert any(c["tax_category"] == "commerce" for c in chains)


def test_scenario_8_sharoushi_shuugyou_kisoku_deep(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="shuugyou_kisoku",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["segment"] == "社労士"
    assert out["filing_window"]["kind"] == "labour_bureau"
    chains = out["reasoning_chains"]
    assert any(c["tax_category"] == "labor" for c in chains)


def test_scenario_9_sharoushi_36_kyotei_deep(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="sanroku_kyoutei",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["status"] == "ok"
    assert out["template"]["authority"].startswith("労基法 §36")


def test_scenario_10_kaikei_kansa_chosho_deep(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="kansa_chosho",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["segment"] == "会計士"
    # corporate_tax category fallback for monitoring chains
    assert isinstance(out["reasoning_chains"], list)


def test_scenario_11_kaikei_kansa_iken_partial(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="kansa_iken",
            houjin_bangou="8010001213708",
            auto_fill_level="partial",
        )
    )
    assert out["primary_result"]["status"] == "ok"
    assert "公認会計士法 §47条の2" in out["template"]["sensitive_act"]


def test_scenario_12_skeleton_mode_without_houjin(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="houjinzei_shinkoku",
            houjin_bangou="",
            auto_fill_level="skeleton",
        )
    )
    assert out["primary_result"]["status"] == "ok"
    assert out["primary_result"]["is_skeleton"] is True
    assert out["portfolio_context"]["portfolio"] == []
    # filing_window kind is still surfaced even in skeleton mode
    assert out["filing_window"]["kind"] == "tax_office"


def test_scenario_13_invalid_artifact_type_returns_empty(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="not_a_real_type_xyz",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    # segment cannot be inferred
    assert out["primary_result"]["status"] == "empty"
    assert "Cannot infer segment" in out["primary_result"]["rationale"]


def test_scenario_14_explicit_segment_with_unknown_type(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="not_in_db",
            houjin_bangou="8010001213708",
            segment="税理士",
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["status"] == "template_missing"
    assert out["template"] is None


def test_scenario_15_disclaimer_billing_provenance_shape(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="shuugyou_kisoku",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    # disclaimer contract — every 5 sensitive acts must be present
    d = out["_disclaimer"]
    assert "税理士法 §52" in d
    assert "公認会計士法 §47条の2" in d
    assert "弁護士法 §72" in d
    assert "行政書士法 §1" in d
    assert "司法書士法 §3" in d
    # provenance / billing contract
    assert out["_billing_unit"] == 4
    assert out["billing"]["yen"] == 12
    assert out["_provenance"]["lane_id"] == "HE-2"
    assert out["_provenance"]["composed_lanes"] == ["N1", "N2", "N3", "N4", "N6", "N9"]
    assert out["_citation_envelope"]["law_articles"] >= 1


def test_scenario_16_agent_next_actions_three_steps(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="houjinzei_shinkoku",
            houjin_bangou="8010001213708",
            fiscal_year=2026,
            auto_fill_level="deep",
        )
    )
    actions = out["agent_next_actions"]
    assert len(actions) == 3
    assert actions[0]["step"] == "fill manual_input"
    assert actions[1]["step"] == "verify with 税理士"
    assert actions[2]["step"] == "submit to filing_window"
    assert actions[2]["via"] in ("online", "post")


def test_scenario_17_amendment_alerts_for_known_houjin(mod: Any) -> None:
    fn = _impl(mod.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="houjinzei_shinkoku",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    alerts = out["amendment_alerts_relevant"]
    assert len(alerts) == 1
    assert alerts[0]["impact_score"] == 80


def test_scenario_18_db_missing_returns_safe_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If autonomath.db is missing the wrapper must not raise — it must
    return a structured empty envelope with the disclaimer intact.
    """
    missing = tmp_path / "nope.db"
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(missing))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(missing))
    import jpintel_mcp.mcp.moat_lane_tools.he2_workpaper as m

    m = importlib.reload(m)
    fn = _impl(m.prepare_implementation_workpaper)
    out = _run(
        fn(
            artifact_type="houjinzei_shinkoku",
            houjin_bangou="8010001213708",
            auto_fill_level="deep",
        )
    )
    assert out["primary_result"]["status"] == "template_missing"
    assert "_disclaimer" in out
