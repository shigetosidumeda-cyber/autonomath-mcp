"""Tests for products.product_a3_subsidy_roadmap + products.product_a4_shuugyou_kisoku.

Validates A3 (¥500 subsidy roadmap) + A4 (¥300 就業規則生成) against an
isolated on-disk autonomath fixture so the suite does not depend on the
live 9.7 GB autonomath.db.

Covered scenarios (≥10):
  A3-1  scope_year=12 happy path (deep portfolio, multiple buckets filled).
  A3-2  scope_year=6 narrower window.
  A3-3  no portfolio rows → status=no_portfolio.
  A3-4  amendment alerts filtered to roadmap programs only.
  A3-5  billing envelope = 10 units = ¥30 (Pricing V3 Tier D Deep).
  A3-6  agent_next_actions deterministic 3-step.
  A3-7  required_documents per program (IT 導入補助金 specific docs).
  A3-8  disclaimer envelope (§52 / §47条の2 / §72).
  A4-1  default employee_count_band (10-29) + auto industry inference.
  A4-2  industry explicit override.
  A4-3  small band (1-4) surfaces obligation_label=kisoku_optional.
  A4-4  invalid employee_count_band → invalid_argument envelope.
  A4-5  billing envelope = 10 units = ¥30 (Pricing V3 Tier D).
  A4-6  bundle returns 4 artifacts with proper artifact_type slugs.
  A4-7  disclaimer includes 社労士法.
  A4-8  agent_next_actions three-step + aggregate summary shape.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import importlib
import json
import sqlite3
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

HOUJIN = "8010001213708"
HOUJIN_NO_PORTFOLIO = "9999999999999"


@pytest.fixture
def fixture_db(tmp_path: Path) -> Path:
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
            {"key": "COMPANY_NAME", "source": "mcp"},
            {"key": "HOUJIN_BANGOU", "source": "session"},
            {"key": "FISCAL_YEAR", "source": "session"},
            {"key": "REPRESENTATIVE", "source": "mcp", "fallback": "代表取締役"},
        ],
        ensure_ascii=False,
    )
    seeds = [
        ("社労士", "shuugyou_kisoku", "就業規則", "労基法 §89", "社労士法 §27"),
        ("社労士", "sanroku_kyoutei", "36協定書", "労基法 §36", "社労士法 §27"),
        ("社労士", "koyou_keiyaku", "雇用契約書", "労基法 §15", "社労士法 §27"),
        ("社労士", "roudou_jouken", "労働条件通知書", "労基法 §15", "社労士法 §27"),
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
            license TEXT NOT NULL DEFAULT 'jpcite-scaffold-cc0'
        )
        """
    )
    mapping_rows = [
        ("{{HOUJIN_BANGOU}}", "context", "{}", "$", None, "text", "法人番号"),
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
        ("{{FISCAL_YEAR}}", "context", "{}", "$", "2026", "text", "会計年度"),
        ("{{CURRENT_DATE}}", "computed", "{}", "$", None, "date", "現在日付"),
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
    conn.execute(
        """
        INSERT INTO am_legal_reasoning_chain
          (chain_id, topic_id, topic_label, tax_category, conclusion_text,
           confidence, citations)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "LRC-LAB01",
            "labor:rodo_jikan",
            "労働時間",
            "labor",
            "1日8時間 / 1週40時間を超えるには36協定が必要",
            0.99,
            '{"law":[{"unified_id":"laws:roukihou:36","source_url":"https://laws.e-gov.go.jp/law/322AC0000000049"}],"tsutatsu":[],"hanrei":[]}',
        ),
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
    conn.execute(
        """
        INSERT INTO am_window_directory
          (jurisdiction_kind, name, postal_address, tel, url,
           jurisdiction_houjin_filter_regex, jurisdiction_region_code,
           source_url, license)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
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
    )

    # ---- am_entities + am_entity_facts ------------------------------------
    conn.execute(
        "CREATE TABLE am_entities (canonical_id TEXT PRIMARY KEY, record_kind TEXT NOT NULL)"
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
        (f"houjin:{HOUJIN}", "corporate_entity"),
    )
    for field, value in (
        ("corp.registered_address", "東京都千代田区"),
        ("corp.jsic_major", "E"),
        ("corp.size_band", "中小"),
        ("corp.prefecture", "東京都"),
    ):
        conn.execute(
            "INSERT INTO am_entity_facts (entity_id, field_name, value_text) VALUES (?, ?, ?)",
            (f"houjin:{HOUJIN}", field, value),
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
    portfolio_rows = [
        (HOUJIN, "P-IT-DOUNYU-2026", 0.92, "unapplied", "2026-09-30", "fixed", 1),
        (HOUJIN, "P-MONOZUKURI-2026", 0.85, "unapplied", "2026-11-15", "fixed", 2),
        (HOUJIN, "P-SAIKOUCHIKU-2026", 0.78, "unapplied", "2027-01-20", "fixed", 3),
        (HOUJIN, "P-SHOUENE-2026", 0.65, "unapplied", "2027-03-10", "rolling", 4),
    ]
    for row in portfolio_rows:
        conn.execute(
            """
            INSERT INTO am_houjin_program_portfolio
              (houjin_bangou, program_id, applicability_score, applied_status,
               deadline, deadline_kind, priority_rank)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    # ---- am_application_round (N4 calendar) -------------------------------
    conn.execute(
        """
        CREATE TABLE am_application_round (
            round_id INTEGER PRIMARY KEY AUTOINCREMENT,
            program_entity_id TEXT NOT NULL,
            round_label TEXT NOT NULL,
            round_seq INTEGER,
            application_open_date TEXT,
            application_close_date TEXT,
            announced_date TEXT,
            disbursement_start_date TEXT,
            budget_yen INTEGER,
            status TEXT,
            source_url TEXT,
            source_fetched_at TEXT,
            UNIQUE (program_entity_id, round_label)
        )
        """
    )
    today = _dt.date.today()
    rounds = [
        (
            "P-IT-DOUNYU-2026",
            "第1回",
            1,
            (today + _dt.timedelta(days=30)).isoformat(),
            (today + _dt.timedelta(days=90)).isoformat(),
            (today + _dt.timedelta(days=150)).isoformat(),
            (today + _dt.timedelta(days=180)).isoformat(),
            5_000_000,
            "upcoming",
            "https://example/it_dounyu",
        ),
        (
            "P-IT-DOUNYU-2026",
            "第2回",
            2,
            (today + _dt.timedelta(days=120)).isoformat(),
            (today + _dt.timedelta(days=200)).isoformat(),
            (today + _dt.timedelta(days=260)).isoformat(),
            (today + _dt.timedelta(days=290)).isoformat(),
            5_000_000,
            "upcoming",
            "https://example/it_dounyu/2",
        ),
        (
            "P-MONOZUKURI-2026",
            "第18次公募",
            18,
            (today + _dt.timedelta(days=60)).isoformat(),
            (today + _dt.timedelta(days=180)).isoformat(),
            (today + _dt.timedelta(days=240)).isoformat(),
            (today + _dt.timedelta(days=270)).isoformat(),
            10_000_000,
            "upcoming",
            "https://example/monozukuri",
        ),
        (
            "P-SAIKOUCHIKU-2026",
            "第12回",
            12,
            (today + _dt.timedelta(days=90)).isoformat(),
            (today + _dt.timedelta(days=210)).isoformat(),
            (today + _dt.timedelta(days=290)).isoformat(),
            (today + _dt.timedelta(days=320)).isoformat(),
            15_000_000,
            "upcoming",
            "https://example/saikouchiku",
        ),
        (
            "P-SHOUENE-2026",
            "第1回",
            1,
            (today + _dt.timedelta(days=150)).isoformat(),
            (today + _dt.timedelta(days=300)).isoformat(),
            (today + _dt.timedelta(days=350)).isoformat(),
            None,
            3_000_000,
            "upcoming",
            "https://example/shouene",
        ),
    ]
    for row in rounds:
        conn.execute(
            """
            INSERT INTO am_application_round
              (program_entity_id, round_label, round_seq,
               application_open_date, application_close_date,
               announced_date, disbursement_start_date, budget_yen,
               status, source_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
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
            HOUJIN,
            80,
            '["P-IT-DOUNYU-2026", "P-MONOZUKURI-2026"]',
            "[]",
            (_dt.date.today() - _dt.timedelta(days=10)).isoformat() + " 09:00:00",
            None,
        ),
    )
    conn.execute(
        """
        INSERT INTO am_amendment_alert_impact
          (amendment_diff_id, houjin_bangou, impact_score,
           impacted_program_ids, impacted_tax_rule_ids, detected_at, notified_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            2,
            HOUJIN,
            40,
            '["P-UNRELATED-2026"]',
            "[]",
            (_dt.date.today() - _dt.timedelta(days=5)).isoformat() + " 09:00:00",
            None,
        ),
    )

    # ---- am_segment_view (N7) ---------------------------------------------
    conn.execute(
        """
        CREATE TABLE am_segment_view (
            segment_key TEXT PRIMARY KEY,
            jsic_major TEXT NOT NULL,
            jsic_name_ja TEXT,
            size_band TEXT NOT NULL,
            prefecture TEXT NOT NULL,
            program_count INTEGER NOT NULL DEFAULT 0,
            judgment_count INTEGER NOT NULL DEFAULT 0,
            tsutatsu_count INTEGER NOT NULL DEFAULT 0,
            popularity_rank INTEGER,
            adoption_count INTEGER NOT NULL DEFAULT 0,
            program_ids_json TEXT,
            judgment_ids_json TEXT,
            tsutatsu_ids_json TEXT,
            computed_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO am_segment_view
          (segment_key, jsic_major, jsic_name_ja, size_band, prefecture,
           program_count, judgment_count, tsutatsu_count, popularity_rank,
           adoption_count, program_ids_json, judgment_ids_json,
           tsutatsu_ids_json, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "E-中小-東京都",
            "E",
            "製造業",
            "中小",
            "東京都",
            40,
            6,
            12,
            1,
            21,
            "[]",
            "[]",
            "[]",
            "2026-05-17",
        ),
    )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def a3_mod(monkeypatch: pytest.MonkeyPatch, fixture_db: Path) -> Any:
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(fixture_db))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    import jpintel_mcp.mcp.products.product_a3_subsidy_roadmap as m

    return importlib.reload(m)


@pytest.fixture
def a4_mod(monkeypatch: pytest.MonkeyPatch, fixture_db: Path) -> Any:
    monkeypatch.setenv("JPCITE_AUTONOMATH_DB_PATH", str(fixture_db))
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    import jpintel_mcp.mcp.moat_lane_tools.he2_workpaper as he2

    importlib.reload(he2)
    import jpintel_mcp.mcp.products.product_a4_shuugyou_kisoku as m

    return importlib.reload(m)


def _impl(tool: Any) -> Any:
    for attr in ("fn", "func", "_fn"):
        inner = getattr(tool, attr, None)
        if callable(inner):
            return inner
    return tool


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# --------------------------------------------------------------------------- #
# A3 — 補助金活用ロードマップ                                                  #
# --------------------------------------------------------------------------- #


def test_a3_scope_12_happy_path(a3_mod: Any) -> None:
    fn = _impl(a3_mod.product_subsidy_roadmap_12month)
    out = fn(houjin_bangou=HOUJIN, scope_year=12)
    assert out["primary_result"]["status"] == "ok"
    assert out["product_id"] == "A3"
    assert out["primary_result"]["scope_months"] == 12
    assert len(out["months"]) == 12
    assert out["aggregate"]["total_program_rounds"] >= 1
    assert out["aggregate"]["total_estimated_subsidy_yen"] > 0
    assert any(b["item_count"] > 0 for b in out["months"])


def test_a3_scope_6_narrow_window(a3_mod: Any) -> None:
    fn = _impl(a3_mod.product_subsidy_roadmap_12month)
    out = fn(houjin_bangou=HOUJIN, scope_year=6)
    assert out["primary_result"]["status"] == "ok"
    assert out["primary_result"]["scope_months"] == 6
    assert len(out["months"]) == 6


def test_a3_no_portfolio_path(a3_mod: Any) -> None:
    fn = _impl(a3_mod.product_subsidy_roadmap_12month)
    out = fn(houjin_bangou=HOUJIN_NO_PORTFOLIO, scope_year=12)
    assert out["primary_result"]["status"] == "no_portfolio"
    assert out["months"] == []
    assert out["aggregate"]["total_program_rounds"] == 0


def test_a3_amendment_alerts_filtered(a3_mod: Any) -> None:
    fn = _impl(a3_mod.product_subsidy_roadmap_12month)
    out = fn(houjin_bangou=HOUJIN, scope_year=12)
    alert_ids = [a["alert_id"] for a in out["amendment_alerts"]]
    assert 1 in alert_ids
    assert 2 not in alert_ids


def test_a3_billing_envelope_167_units(a3_mod: Any) -> None:
    fn = _impl(a3_mod.product_subsidy_roadmap_12month)
    out = fn(houjin_bangou=HOUJIN, scope_year=12)
    assert out["_billing_unit"] == 10
    assert out["billing"]["unit"] == 10
    assert out["billing"]["yen"] == 30
    assert out["billing"]["product_id"] == "A3"
    assert out["billing"]["tier"] == "D"
    assert out["billing"]["pricing_version"] == "v3"


def test_a3_agent_next_actions_three_steps(a3_mod: Any) -> None:
    fn = _impl(a3_mod.product_subsidy_roadmap_12month)
    out = fn(houjin_bangou=HOUJIN, scope_year=12)
    actions = out["agent_next_actions"]
    assert len(actions) == 3
    assert actions[0]["step"] == "review upcoming deadlines"
    assert actions[1]["step"] == "subscribe to amendment alerts"
    assert actions[2]["step"] == "engage 士業"


def test_a3_disclaimer_envelope(a3_mod: Any) -> None:
    fn = _impl(a3_mod.product_subsidy_roadmap_12month)
    out = fn(houjin_bangou=HOUJIN, scope_year=12)
    assert "§52" in out["_disclaimer"]
    assert "§47条の2" in out["_disclaimer"]
    assert "§72" in out["_disclaimer"]


def test_a3_required_documents_per_program(a3_mod: Any) -> None:
    fn = _impl(a3_mod.product_subsidy_roadmap_12month)
    out = fn(houjin_bangou=HOUJIN, scope_year=12)
    found_it_item = None
    for bucket in out["months"]:
        for item in bucket["items"]:
            if "IT" in item["program_id"] or "DOUNYU" in item["program_id"]:
                found_it_item = item
                break
        if found_it_item:
            break
    assert found_it_item is not None
    docs = " | ".join(found_it_item["required_documents"])
    assert "登記事項証明書" in docs


# --------------------------------------------------------------------------- #
# A4 — 就業規則生成 Pack                                                       #
# --------------------------------------------------------------------------- #


def test_a4_default_band_industry_inference(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(fn(houjin_bangou=HOUJIN, employee_count_band="10-29"))
    assert out["primary_result"]["status"] == "ok"
    assert out["product_id"] == "A4"
    assert out["primary_result"]["industry_resolved"] == "製造業"
    assert out["primary_result"]["obligation_label"] == "labeling_required_kisoku_89"
    assert len(out["bundle"]) == 4


def test_a4_industry_override(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(
        fn(
            houjin_bangou=HOUJIN,
            employee_count_band="30-49",
            industry="建設業",
        )
    )
    assert out["primary_result"]["industry_resolved"] == "建設業"
    assert out["industry"] == "建設業"


def test_a4_small_band_obligation_optional(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(fn(houjin_bangou=HOUJIN, employee_count_band="1-4"))
    assert out["primary_result"]["obligation_label"] == "kisoku_optional"


def test_a4_invalid_band(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(fn(houjin_bangou=HOUJIN, employee_count_band="bogus-band"))
    assert out["primary_result"]["status"] == "invalid_argument"
    assert out["bundle"] == []


def test_a4_billing_envelope_100_units(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(fn(houjin_bangou=HOUJIN, employee_count_band="10-29"))
    assert out["_billing_unit"] == 10
    assert out["billing"]["unit"] == 10
    assert out["billing"]["yen"] == 30
    assert out["billing"]["product_id"] == "A4"
    assert out["billing"]["tier"] == "D"
    assert out["billing"]["pricing_version"] == "v3"


def test_a4_bundle_artifact_types(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(fn(houjin_bangou=HOUJIN, employee_count_band="10-29"))
    slugs = {b["artifact_type"] for b in out["bundle"]}
    assert slugs == {"shuugyou_kisoku", "sanroku_kyoutei", "koyou_keiyaku", "roudou_jouken"}


def test_a4_disclaimer_includes_sharoushi(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(fn(houjin_bangou=HOUJIN, employee_count_band="10-29"))
    assert "社労士法" in out["_disclaimer"]
    assert "労基法" in out["_disclaimer"]


def test_a4_agent_next_actions_three_steps(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(fn(houjin_bangou=HOUJIN, employee_count_band="10-29"))
    actions = out["agent_next_actions"]
    assert len(actions) == 3
    assert actions[0]["step"].startswith("fill manual_input")
    assert actions[1]["step"].startswith("verify 労基法")
    assert actions[2]["step"].startswith("engage 社労士")


def test_a4_aggregate_summary_shape(a4_mod: Any) -> None:
    fn = _impl(a4_mod.product_shuugyou_kisoku_pack)
    out = _run(fn(houjin_bangou=HOUJIN, employee_count_band="10-29"))
    agg = out["aggregate"]
    assert agg["artifact_count"] == 4
    assert agg["completed_artifact_count"] >= 1
    assert isinstance(agg["statutory_fence"], list)
    assert any("社労士法" in s for s in agg["statutory_fence"])
