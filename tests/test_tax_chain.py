"""Tests for GET /v1/tax_rules/{rule_id}/full_chain.

Covers:
1. Happy path — a tax_ruleset with seeded laws / hanrei / history (jpintel)
   and tsutatsu / saiketsu (autonomath) returns all 6 axes + the standard
   envelope keys (corpus_snapshot_id / _disclaimer / _billing_unit:1).
2. ``include`` filter — passing ``include=laws,hanrei`` only returns those
   axes; the other 3 axes are empty lists.
3. 404 for an unknown TAX-* id.
4. 422 for a malformed unified id.
5. Disclaimer surfaces 税理士法 §52 + 弁護士法 §72 + 公認会計士法 §47条の2 fences.
6. MCP tool wrapper hits the same envelope contract.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from pathlib import Path

# Stable ids used across this test module. The TAX-* id must match
# `^TAX-[0-9a-f]{10}$` (regex enforced by the router).
RULE_ID = "TAX-c1d2e3f4a5"
RULE_NAME = "テスト消費税2割特例 (チェイン用)"
LAW_ID = "LAW-taxchain01"
RULE_PREDECESSOR_ID = "TAX-aaaaaaaaaa"
HAN_ID_RECENT = "HAN-taxchain01"


def _augment_jpintel(seeded_db: Path) -> None:
    """Seed jpintel.db with a tax_rulesets row + companion law +
    sibling history row + court_decisions row referencing the same law.
    """
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    now = datetime.now(UTC).isoformat()
    try:
        # --- tax_rulesets canonical row -------------------------------------
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                "INSERT OR IGNORE INTO tax_rulesets("
                "  unified_id, ruleset_name, tax_category, ruleset_kind, "
                "  effective_from, effective_until, related_law_ids_json, "
                "  eligibility_conditions, eligibility_conditions_json, "
                "  rate_or_amount, calculation_formula, filing_requirements, "
                "  authority, authority_url, source_url, source_excerpt, "
                "  source_checksum, confidence, fetched_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    RULE_ID,
                    RULE_NAME,
                    "consumption",
                    "exemption",
                    "2023-10-01",
                    "2026-09-30",
                    json.dumps([LAW_ID], ensure_ascii=False),
                    "免税事業者から登録した小規模事業者の特例。",
                    json.dumps(
                        {
                            "op": "all",
                            "of": [
                                {
                                    "op": "lte",
                                    "field": "taxable_sales_jpy_base_period",
                                    "value": 10000000,
                                },
                            ],
                        },
                        ensure_ascii=False,
                    ),
                    "課税売上消費税 × 20%",
                    "納付税額 = 課税売上消費税 × 0.2",
                    "確定申告書「2割特例」欄に記入。届出書 不要。",
                    "国税庁",
                    "https://www.nta.go.jp/",
                    "https://www.nta.go.jp/tax_chain_test",
                    "テスト用 source excerpt",
                    None,
                    0.95,
                    now,
                    now,
                ),
            )
        # --- predecessor row (same name, older effective_from) -------------
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                "INSERT OR IGNORE INTO tax_rulesets("
                "  unified_id, ruleset_name, tax_category, ruleset_kind, "
                "  effective_from, effective_until, related_law_ids_json, "
                "  eligibility_conditions, source_url, authority, "
                "  confidence, fetched_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    RULE_PREDECESSOR_ID,
                    RULE_NAME,  # same ruleset_name => surfaces in history
                    "consumption",
                    "exemption",
                    "2019-10-01",
                    "2023-09-30",
                    json.dumps([LAW_ID], ensure_ascii=False),
                    "旧版 (経過措置 開始前)。",
                    "https://www.nta.go.jp/tax_chain_test_pre",
                    "国税庁",
                    0.9,
                    now,
                    now,
                ),
            )

        # --- laws root + companion --------------------------------------
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                "INSERT OR IGNORE INTO laws("
                "  unified_id, law_number, law_title, law_short_title, "
                "  law_type, ministry, promulgated_date, enforced_date, "
                "  last_amended_date, revision_status, article_count, "
                "  full_text_url, summary, subject_areas_json, source_url, "
                "  confidence, fetched_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    LAW_ID,
                    "昭和六十三年法律第百八号",
                    "テスト消費税法",
                    "テスト消費税法",
                    "act",
                    "財務省",
                    "1988-12-30",
                    "1989-04-01",
                    "2023-03-31",
                    "current",
                    100,
                    "https://laws.e-gov.go.jp/test_consumption",
                    "テスト消費税法のサマリ。snippet として現れる本文。",
                    json.dumps(["consumption_tax"], ensure_ascii=False),
                    "https://laws.e-gov.go.jp/test_consumption",
                    0.95,
                    now,
                    now,
                ),
            )

        # --- court_decisions referencing the same LAW-* ------------------
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                "INSERT OR IGNORE INTO court_decisions("
                "  unified_id, case_name, case_number, court, court_level, "
                "  decision_date, decision_type, subject_area, "
                "  related_law_ids_json, key_ruling, parties_involved, "
                "  impact_on_business, precedent_weight, full_text_url, "
                "  pdf_url, source_url, source_excerpt, confidence, "
                "  fetched_at, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    HAN_ID_RECENT,
                    "テスト消費税2割特例事件",
                    "令和7年(行ヒ)第1号",
                    "東京地方裁判所",
                    "district",
                    "2025-09-01",
                    "判決",
                    "租税",
                    json.dumps([LAW_ID], ensure_ascii=False),
                    "テスト判例の判示事項要約。tax_chain hanrei axis に出る。",
                    "甲 vs 国",
                    "実務影響",
                    "informational",
                    "https://courts.go.jp/test_taxchain",
                    "https://courts.go.jp/test_taxchain.pdf",
                    "https://courts.go.jp/test_taxchain",
                    "原文抜粋",
                    0.9,
                    now,
                    now,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _build_autonomath_slice(tmp_path: Path) -> Path:
    """Build a tmp autonomath.db with nta_tsutatsu_index + nta_saiketsu rows
    that match the rule_name kanji tokens (テスト / 消費税 / 特例 / 経過 / etc.).
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE nta_tsutatsu_index (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            code              TEXT NOT NULL UNIQUE,
            law_canonical_id  TEXT NOT NULL,
            article_number    TEXT NOT NULL,
            title             TEXT,
            body_excerpt      TEXT,
            parent_code       TEXT,
            source_url        TEXT NOT NULL,
            last_amended      TEXT,
            refreshed_at      TEXT NOT NULL
        );
        CREATE TABLE nta_saiketsu (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            volume_no        INTEGER NOT NULL,
            case_no          TEXT NOT NULL,
            decision_date    TEXT,
            fiscal_period    TEXT,
            tax_type         TEXT,
            title            TEXT,
            decision_summary TEXT,
            fulltext         TEXT,
            source_url       TEXT NOT NULL UNIQUE,
            license          TEXT NOT NULL DEFAULT 'gov_standard',
            ingested_at      TEXT NOT NULL,
            UNIQUE (volume_no, case_no)
        );
        """
    )
    # nta_tsutatsu_index entry whose title contains "消費税" matches the
    # rule_name tokens (RULE_NAME = "テスト消費税2割特例 (チェイン用)").
    conn.execute(
        "INSERT INTO nta_tsutatsu_index("
        "  code, law_canonical_id, article_number, title, body_excerpt, "
        "  source_url, last_amended, refreshed_at"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (
            "消基通-1-1-3",
            "law:shouhi-zei-tsutatsu",
            "1-1-3",
            "テスト消費税 2割特例関連通達",
            "本通達は2割特例の適用要件について述べる。snippet 用 body excerpt。",
            "https://www.nta.go.jp/law/tsutatsu/test_taxchain",
            "2024-12-01",
            "2026-04-29T00:00:00Z",
        ),
    )
    # nta_saiketsu row with tax_type=消費税 + matching title token.
    conn.execute(
        "INSERT INTO nta_saiketsu("
        "  volume_no, case_no, decision_date, fiscal_period, tax_type, "
        "  title, decision_summary, fulltext, source_url, license, ingested_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            140,
            "07",
            "2025-09-26",
            "令和7年7月分から9月分",
            "消費税",
            "テスト消費税 2割特例 適用可否",
            "請求人の主張を支持し2割特例適用を認めた事案の要旨。",
            "全文",
            "https://www.kfs.go.jp/test_taxchain/07.html",
            "gov_standard",
            "2026-04-29T00:00:00Z",
        ),
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def chain_client(
    seeded_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """TestClient with seeded jpintel.db (tax_rulesets + laws + court_decisions)
    + tmp autonomath.db slice (nta_tsutatsu_index + nta_saiketsu)."""
    _augment_jpintel(seeded_db)
    am_db_path = _build_autonomath_slice(tmp_path)

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(am_db_path))
    # Drop the cached thread-local autonomath conn so the next request
    # sees the tmp DB.
    try:
        from jpintel_mcp.mcp.autonomath_tools import db as am_db_mod

        if hasattr(am_db_mod, "_local"):
            with contextlib.suppress(Exception):
                conn = getattr(am_db_mod._local, "autonomath", None)
                if conn is not None:
                    conn.close()
                am_db_mod._local.autonomath = None
                am_db_mod._local.autonomath_path = None
    except ImportError:
        pass
    try:
        from jpintel_mcp.config import settings

        monkeypatch.setattr(settings, "autonomath_db_path", am_db_path)
    except (ImportError, AttributeError):
        pass

    from jpintel_mcp.api.main import create_app

    return TestClient(create_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_chain_happy_path(chain_client: TestClient) -> None:
    """All 6 axes populated when default include is used."""
    r = chain_client.get(f"/v1/tax_rules/{RULE_ID}/full_chain")
    assert r.status_code == 200, r.text
    body = r.json()

    # rule axis
    assert body["rule"]["unified_id"] == RULE_ID
    assert body["rule"]["ruleset_name"] == RULE_NAME
    assert body["rule"]["tax_category"] == "consumption"
    assert body["rule"]["effective_from"] == "2023-10-01"

    # laws axis — pulls the LAW-* via related_law_ids_json IN-list path.
    laws = body["laws"]
    assert len(laws) >= 1
    assert any(law["unified_id"] == LAW_ID for law in laws)

    # hanrei axis — court_decisions whose related_law_ids_json contains LAW-*
    # OR whose case_name matches the rule_name kanji tokens (e.g. 消費税).
    han_ids = {h["unified_id"] for h in body["hanrei"]}
    assert HAN_ID_RECENT in han_ids

    # history axis — sibling tax_rulesets share ruleset_name.
    history_ids = {h["unified_id"] for h in body["history"]}
    assert RULE_PREDECESSOR_ID in history_ids
    # The current row must NOT appear in its own history.
    assert RULE_ID not in history_ids

    # tsutatsu axis — nta_tsutatsu_index row whose title contains 消費税.
    tsu_codes = {t["code"] for t in body["tsutatsu"]}
    assert "消基通-1-1-3" in tsu_codes

    # saiketsu axis — nta_saiketsu row whose title contains 消費税 / 2割特例.
    assert any("消費税" in (s.get("tax_type") or "") for s in body["saiketsu"])

    # Envelope keys
    assert body["_billing_unit"] == 1
    assert "税理士法 §52" in body["_disclaimer"]
    assert "弁護士法 §72" in body["_disclaimer"]
    assert "公認会計士法 §47条の2" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body
    # Coverage summary
    cov = body["coverage_summary"]
    assert cov["axis_counts"]["laws"] == len(body["laws"])
    assert cov["axis_counts"]["history"] == len(body["history"])
    # All 5 backing tables present in this fixture, so missing_types is empty.
    assert cov["missing_types"] == []
    assert cov["total_refs"] == sum(cov["axis_counts"].values())


def test_full_chain_include_filter_subset(chain_client: TestClient) -> None:
    """include=laws,hanrei returns only those axes; others empty."""
    r = chain_client.get(
        f"/v1/tax_rules/{RULE_ID}/full_chain?include=laws,hanrei",
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert len(body["laws"]) >= 1
    assert len(body["hanrei"]) >= 1
    # Filtered axes are empty lists, NOT missing_types entries.
    assert body["tsutatsu"] == []
    assert body["saiketsu"] == []
    assert body["history"] == []
    # Filtered axes are still considered "present" because the table exists.
    assert body["coverage_summary"]["missing_types"] == []


def test_full_chain_404_unknown_rule(chain_client: TestClient) -> None:
    """A well-formed but missing TAX-* id surfaces 404."""
    r = chain_client.get("/v1/tax_rules/TAX-0000000000/full_chain")
    assert r.status_code == 404, r.text
    assert "tax_ruleset not found" in r.json()["detail"]


def test_full_chain_422_malformed_id(chain_client: TestClient) -> None:
    """A malformed unified_id surfaces 422 (regex / length)."""
    # Length violates min/max=14 -> FastAPI returns its own 422 envelope.
    r = chain_client.get("/v1/tax_rules/TAX-bad/full_chain")
    assert r.status_code == 422, r.text


def test_full_chain_max_per_axis_clamp(chain_client: TestClient) -> None:
    """max_per_axis above hard ceiling rejected with 422."""
    r = chain_client.get(
        f"/v1/tax_rules/{RULE_ID}/full_chain?max_per_axis=999",
    )
    assert r.status_code == 422, r.text


def test_mcp_tool_wrapper_happy_path(chain_client: TestClient) -> None:
    """The MCP wrapper calls the same impl helpers; the chain_client fixture
    pins the autonomath DB path that the wrapper picks up via env."""
    from jpintel_mcp.mcp.autonomath_tools.tax_chain_tools import (
        _tax_rule_full_chain_impl,
    )

    res = _tax_rule_full_chain_impl(rule_id=RULE_ID, include=["laws", "history"])
    assert res.get("error") is None, res
    assert res["rule"]["unified_id"] == RULE_ID
    assert any(h["unified_id"] == RULE_PREDECESSOR_ID for h in res["history"])
    assert res["_billing_unit"] == 1
    assert "税理士法 §52" in res["_disclaimer"]


def test_mcp_tool_wrapper_invalid_rule_id() -> None:
    """Bad shape -> invalid_input error envelope (no DB hit needed)."""
    from jpintel_mcp.mcp.autonomath_tools.tax_chain_tools import (
        _tax_rule_full_chain_impl,
    )

    res = _tax_rule_full_chain_impl(rule_id="TAX-bad")
    assert res["error"]["code"] == "invalid_input"
    assert res["error"]["field"] == "rule_id"


def test_mcp_tool_wrapper_invalid_include() -> None:
    """Unknown include value -> invalid_enum error envelope."""
    from jpintel_mcp.mcp.autonomath_tools.tax_chain_tools import (
        _tax_rule_full_chain_impl,
    )

    res = _tax_rule_full_chain_impl(rule_id=RULE_ID, include=["bogus"])
    assert res["error"]["code"] == "invalid_enum"
    assert res["error"]["field"] == "include"
