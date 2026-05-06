"""Tests for GET /v1/intel/regulatory_context/{program_id}.

Covers:

1. Happy path — a program with seeded law / tsutatsu / kessai / hanrei /
   gyosei_shobun rows returns all 5 axes + the standard envelope keys
   (corpus_snapshot_id / _disclaimer / _billing_unit:1).
2. ``include`` filter — passing ``include=law`` only returns the law
   axis; the other 4 axes are empty lists and the per-type counters
   reflect that.
3. ``since_date`` filter — old rows (decision_date < cutoff) are
   excluded; recent rows pass through.
4. Disclaimer surfaces 弁護士法 §72 / 税理士法 §52 fences (sensitive
   business-law territory).
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from jpintel_mcp.api.deps import hash_api_key

if TYPE_CHECKING:
    from pathlib import Path

PROGRAM_ID = "UNI-test-regctx-1"
LAW_ID = "LAW-regctx0001"
PROGRAM_NAME = "規制コンテキスト テスト補助金"


def _augment_jpintel_for_regulatory_context(seeded_db: Path) -> None:
    """Seed jpintel.db with a program + law + program_law_refs +
    court_decision + enforcement_case slice that the endpoint can join.

    The shared ``seeded_db`` fixture sets up `programs` + `programs_fts`
    via init_db; we layer the regulatory tables we need on top.
    """
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    try:
        # --- programs row -------------------------------------------------
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO programs("
            "  unified_id, primary_name, aliases_json, "
            "  authority_level, authority_name, prefecture, municipality, "
            "  program_kind, official_url, "
            "  amount_max_man_yen, amount_min_man_yen, subsidy_rate, "
            "  trust_level, tier, coverage_score, gap_to_tier_s_json, "
            "  a_to_j_coverage_json, excluded, exclusion_reason, "
            "  crop_categories_json, equipment_category, "
            "  target_types_json, funding_purpose_json, "
            "  amount_band, application_window_json, "
            "  enriched_json, source_mentions_json, updated_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                PROGRAM_ID,
                PROGRAM_NAME,
                None,
                "国",
                "経済産業省",
                None,
                None,
                "補助金",
                "https://example.gov/regctx",
                1000,
                None,
                None,
                None,
                "A",
                None,
                None,
                None,
                0,
                None,
                None,
                None,
                json.dumps(["corporation"], ensure_ascii=False),
                json.dumps(["設備投資"], ensure_ascii=False),
                None,
                None,
                None,
                None,
                now,
            ),
        )

        # --- laws table + program_law_refs --------------------------------
        # Tables may not be present on a minimal seeded_db variant — the
        # test will then exercise the missing_types degradation path
        # instead, so we suppress OperationalError per insert block.
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
                    "昭和三十年法律第百七十九号",
                    "規制コンテキスト テスト法",
                    "テスト法",
                    "act",
                    "経済産業省",
                    "1955-08-27",
                    "1955-09-01",
                    "2024-06-17",
                    "current",
                    100,
                    "https://laws.e-gov.go.jp/test",
                    "テスト用の法令サマリ。検索結果に snippet として現れる本文。",
                    json.dumps(["subsidy_clawback"], ensure_ascii=False),
                    "https://laws.e-gov.go.jp/test",
                    0.95,
                    now,
                    now,
                ),
            )

        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                "INSERT OR IGNORE INTO program_law_refs("
                "  program_unified_id, law_unified_id, ref_kind, "
                "  article_citation, source_url, fetched_at, confidence"
                ") VALUES (?,?,?,?,?,?,?)",
                (
                    PROGRAM_ID,
                    LAW_ID,
                    "authority",
                    "第5条",
                    "https://laws.e-gov.go.jp/test#Mp-At_5",
                    now,
                    0.9,
                ),
            )

        # --- court_decisions (判例) — recent + old ------------------------
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
                    "HAN-regctx0001",
                    "規制コンテキストテスト事件",
                    "令和5年(行ヒ)第99号",
                    "東京地方裁判所",
                    "district",
                    "2025-03-01",
                    "判決",
                    "行政",
                    json.dumps([LAW_ID], ensure_ascii=False),
                    "テスト判例の判示事項要約。snippet 用 holding 文字列を入れる。",
                    "甲 vs 国",
                    "テスト用の実務影響",
                    "informational",
                    "https://courts.go.jp/test",
                    "https://courts.go.jp/test.pdf",
                    "https://courts.go.jp/test",
                    "原文抜粋",
                    0.9,
                    now,
                    now,
                ),
            )
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
                    "HAN-regctx0002",
                    "古い規制テスト事件",
                    "平成20年(行ヒ)第1号",
                    "最高裁判所第三小法廷",
                    "supreme",
                    "2008-12-01",
                    "判決",
                    "行政",
                    json.dumps([LAW_ID], ensure_ascii=False),
                    "古い判例。since_date フィルタで除外されるべき。",
                    "甲 vs 国",
                    "古い実務影響",
                    "binding",
                    None,
                    None,
                    "https://courts.go.jp/old",
                    None,
                    0.9,
                    now,
                    now,
                ),
            )

        # --- enforcement_cases (行政処分) ---------------------------------
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(
                "INSERT OR IGNORE INTO enforcement_cases("
                "  case_id, event_type, program_name_hint, recipient_name, "
                "  recipient_kind, recipient_houjin_bangou, "
                "  is_sole_proprietor, bureau, intermediate_recipient, "
                "  prefecture, ministry, occurred_fiscal_years_json, "
                "  amount_yen, amount_project_cost_yen, "
                "  amount_grant_paid_yen, amount_improper_grant_yen, "
                "  amount_improper_project_cost_yen, reason_excerpt, "
                "  legal_basis, source_url, source_section, source_title, "
                "  disclosed_date, disclosed_until, fetched_at, confidence"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "enf-regctx001",
                    "subsidy_clawback",
                    PROGRAM_NAME,
                    "テスト株式会社",
                    "corporation",
                    "1234567890123",
                    0,
                    None,
                    None,
                    "東京都",
                    "経済産業省",
                    json.dumps(["2024"], ensure_ascii=False),
                    1000000,
                    None,
                    None,
                    None,
                    None,
                    "不正受給につき返還命令。",
                    "規制コンテキスト テスト法 第10条",
                    "https://meti.go.jp/test",
                    None,
                    None,
                    "2025-04-15",
                    None,
                    now,
                    0.9,
                ),
            )

        conn.commit()
    finally:
        conn.close()


def _build_autonomath_slice(tmp_path: Path) -> Path:
    """Build a tmp autonomath.db with the 3 tables we need: am_law_article,
    nta_tsutatsu_index, nta_saiketsu (+ FTS shadow). Layered with rows the
    happy-path test asserts on.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE am_law (
            canonical_id    TEXT PRIMARY KEY,
            canonical_name  TEXT NOT NULL,
            short_name      TEXT,
            law_number      TEXT,
            category        TEXT,
            first_enforced  TEXT,
            egov_url        TEXT,
            status          TEXT DEFAULT 'active',
            note            TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            ministry        TEXT,
            superseded_by   TEXT,
            effective_from  TEXT,
            effective_until TEXT,
            last_amended_at TEXT,
            subject_areas_json TEXT,
            e_gov_lawid     TEXT
        );

        CREATE TABLE am_law_article (
            article_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            law_canonical_id    TEXT NOT NULL,
            article_number      TEXT NOT NULL,
            article_number_sort REAL,
            title               TEXT,
            text_summary        TEXT,
            text_full           TEXT,
            effective_from      TEXT,
            effective_until     TEXT,
            last_amended        TEXT,
            source_url          TEXT,
            source_fetched_at   TEXT,
            article_kind        TEXT DEFAULT 'main',
            body_en             TEXT,
            body_en_source_url  TEXT,
            body_en_fetched_at  TEXT,
            body_en_license     TEXT DEFAULT 'cc_by_4.0',
            UNIQUE (law_canonical_id, article_number)
        );

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

    # Seed an am_law_article row keyed on the article_number "第5条" so the
    # law-axis's article enrichment branch is exercised.
    conn.execute(
        "INSERT INTO am_law(canonical_id, canonical_name) VALUES (?, ?)",
        ("law:regctx-test", "規制コンテキストテスト法"),
    )
    conn.execute(
        "INSERT INTO am_law_article("
        "  law_canonical_id, article_number, title, text_summary, text_full, "
        "  last_amended, source_url, source_fetched_at"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (
            "law:regctx-test",
            "第5条",
            "対象事業者",
            "対象事業者は中小企業者であって、第3条各号に掲げる要件を満たすものとする。",
            "対象事業者は中小企業者であって、第3条各号に掲げる要件を満たすものとする。" * 3,
            "2024-06-17",
            "https://laws.e-gov.go.jp/test#Mp-At_5",
            "2026-04-30T00:00:00Z",
        ),
    )

    # Seed a recent + old 通達 row.
    conn.execute(
        "INSERT INTO nta_tsutatsu_index("
        "  code, law_canonical_id, article_number, title, body_excerpt, "
        "  source_url, last_amended, refreshed_at"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (
            "法基通-9-2-3",
            "law:hojin-zei-tsutatsu",
            "9-2-3",
            "規制コンテキスト関連通達",
            "規制コンテキスト関連の本文 excerpt。snippet として 200 字以内。",
            "https://www.nta.go.jp/law/tsutatsu/test",
            "2024-12-01",
            "2026-04-29T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO nta_tsutatsu_index("
        "  code, law_canonical_id, article_number, title, body_excerpt, "
        "  source_url, last_amended, refreshed_at"
        ") VALUES (?,?,?,?,?,?,?,?)",
        (
            "法基通-1-1-old",
            "law:hojin-zei-tsutatsu",
            "1-1",
            "古い通達",
            "古い 通達 本文",
            "https://www.nta.go.jp/law/tsutatsu/old",
            "2010-01-01",
            "2010-01-01T00:00:00Z",
        ),
    )

    # Seed a recent + old 裁決 row.
    conn.execute(
        "INSERT INTO nta_saiketsu("
        "  volume_no, case_no, decision_date, fiscal_period, tax_type, "
        "  title, decision_summary, fulltext, source_url, license, ingested_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            140,
            "01",
            "2025-09-26",
            "令和7年7月分から9月分",
            "国税通則",
            "規制コンテキストテスト裁決",
            "請求人の主張を全面的に支持し原処分を取消した事案。要旨は規制コンテキストの判断基準を述べる。",
            "全文",
            "https://www.kfs.go.jp/test/01.html",
            "gov_standard",
            "2026-04-29T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO nta_saiketsu("
        "  volume_no, case_no, decision_date, fiscal_period, tax_type, "
        "  title, decision_summary, fulltext, source_url, license, ingested_at"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            80,
            "05",
            "2010-05-01",
            "平成22年度",
            "所得税",
            "古い裁決",
            "古い裁決の要旨",
            "古い全文",
            "https://www.kfs.go.jp/old/05.html",
            "gov_standard",
            "2010-05-01T00:00:00Z",
        ),
    )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def regctx_client(
    seeded_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """TestClient with seeded jpintel.db + tmp autonomath.db slice."""
    _augment_jpintel_for_regulatory_context(seeded_db)
    am_db_path = _build_autonomath_slice(tmp_path)

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(am_db_path))
    # Reset cached thread-local connection so the next request opens
    # the tmp DB.
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


def test_regulatory_context_happy_path_all_types(regctx_client: TestClient) -> None:
    """Default include returns all 5 axes + the standard envelope."""
    r = regctx_client.get(f"/v1/intel/regulatory_context/{PROGRAM_ID}")
    assert r.status_code == 200, r.text
    body = r.json()

    # Top-level shape
    assert body["program"]["id"] == PROGRAM_ID
    assert body["program"]["name"] == PROGRAM_NAME
    assert body["_billing_unit"] == 1
    assert isinstance(body["_disclaimer"], str)
    # Sensitive disclaimer must reference 弁護士法 §72 + 税理士法 §52
    # + 行政書士法 §1 fences.
    assert "弁護士法 §72" in body["_disclaimer"]
    assert "税理士法 §52" in body["_disclaimer"]
    assert "行政書士法 §1" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body
    assert "generated_at" in body

    bundle = body["regulatory_bundle"]
    assert set(bundle.keys()) == {
        "law",
        "tsutatsu",
        "kessai",
        "hanrei",
        "gyosei_shobun",
    }

    # Law axis must surface our seeded program_law_refs row.
    assert len(bundle["law"]) >= 1
    law0 = bundle["law"][0]
    assert law0["law_name"] == "規制コンテキスト テスト法"
    # article_id is "<LAW-*>::第5条" when an article is captured.
    assert "::" in law0["article_id"]
    assert law0["last_amended"] == "2024-06-17"

    # Tsutatsu axis carries the recent 通達.
    assert len(bundle["tsutatsu"]) >= 1
    tsu_codes = {t["doc_no"] for t in bundle["tsutatsu"]}
    assert "法基通-9-2-3" in tsu_codes

    # Kessai axis surfaces the recent 裁決.
    assert len(bundle["kessai"]) >= 1
    kes0 = bundle["kessai"][0]
    assert kes0["court"] == "国税不服審判所"
    assert kes0["docket"].startswith("第")  # "第NNN集第NN号"

    # Hanrei axis surfaces both court_decisions seeded against this law.
    assert len(bundle["hanrei"]) >= 1
    han_ids = {h["id"] for h in bundle["hanrei"]}
    assert "HAN-regctx0001" in han_ids

    # Gyosei_shobun axis surfaces the enforcement_cases row.
    assert len(bundle["gyosei_shobun"]) >= 1
    gyo0 = bundle["gyosei_shobun"][0]
    assert gyo0["target"] == "テスト株式会社"

    # Coverage summary is honest.
    cov = body["coverage_summary"]
    assert cov["total_refs"] == sum(len(v) for v in bundle.values())
    assert cov["oldest_doc_date"] is not None
    assert cov["newest_doc_date"] is not None
    # All 5 axes present in this fixture, so missing_types is empty.
    assert cov["missing_types"] == []

    counts = body["citation_count_per_type"]
    assert set(counts.keys()) == {
        "law",
        "tsutatsu",
        "kessai",
        "hanrei",
        "gyosei_shobun",
    }
    assert counts["law"] == len(bundle["law"])


def test_regulatory_context_include_filter_law_only(
    regctx_client: TestClient,
) -> None:
    """``include=law`` returns law axis only; the other 4 axes empty."""
    r = regctx_client.get(
        f"/v1/intel/regulatory_context/{PROGRAM_ID}?include=law",
    )
    assert r.status_code == 200, r.text
    body = r.json()

    bundle = body["regulatory_bundle"]
    assert len(bundle["law"]) >= 1
    # Other axes returned as empty lists when filtered out.
    assert bundle["tsutatsu"] == []
    assert bundle["kessai"] == []
    assert bundle["hanrei"] == []
    assert bundle["gyosei_shobun"] == []

    counts = body["citation_count_per_type"]
    assert counts["tsutatsu"] == 0
    assert counts["kessai"] == 0
    assert counts["hanrei"] == 0
    assert counts["gyosei_shobun"] == 0
    assert counts["law"] >= 1
    # Filtered axes are NOT considered missing infrastructure.
    assert body["coverage_summary"]["missing_types"] == []


def test_regulatory_context_since_date_filter_excludes_old(
    regctx_client: TestClient,
) -> None:
    """``since_date=2020-01-01`` excludes the 2008 / 2010 rows."""
    r = regctx_client.get(f"/v1/intel/regulatory_context/{PROGRAM_ID}?since_date=2020-01-01")
    assert r.status_code == 200, r.text
    body = r.json()
    bundle = body["regulatory_bundle"]

    # The old hanrei (HAN-regctx0002, 2008-12-01) must be filtered.
    han_ids = {h["id"] for h in bundle["hanrei"]}
    assert "HAN-regctx0002" not in han_ids
    # The recent hanrei (HAN-regctx0001, 2025-03-01) must remain.
    assert "HAN-regctx0001" in han_ids

    # Old kessai (volume 80, decision 2010-05-01) excluded.
    kes_dockets = {k["docket"] for k in bundle["kessai"]}
    assert not any("80" in d for d in kes_dockets)
    # Recent kessai (volume 140) present.
    assert any("140" in d for d in kes_dockets)

    # Old 通達 (法基通-1-1-old, 2010) excluded.
    tsu_codes = {t["doc_no"] for t in bundle["tsutatsu"]}
    assert "法基通-1-1-old" not in tsu_codes
    assert "法基通-9-2-3" in tsu_codes


def test_regulatory_context_disclaimer_contains_business_law_fences(
    regctx_client: TestClient,
) -> None:
    """The _disclaimer must surface 業法 fences for sensitive use-cases."""
    r = regctx_client.get(f"/v1/intel/regulatory_context/{PROGRAM_ID}")
    assert r.status_code == 200, r.text
    body = r.json()
    disc = body["_disclaimer"]
    # Every sensitive 業法 fence the customer LLM must respect:
    assert "弁護士法 §72" in disc
    assert "税理士法 §52" in disc
    assert "行政書士法 §1" in disc
    # Wording fences against advice relay
    assert "代替ではありません" in disc
    assert "確定判断" in disc


def test_regulatory_context_unknown_program_returns_404(
    regctx_client: TestClient,
) -> None:
    """Unknown program_id yields 404, not 500."""
    r = regctx_client.get("/v1/intel/regulatory_context/UNI-does-not-exist")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["error"] == "program_not_found"


def test_regulatory_context_invalid_include_returns_422(
    regctx_client: TestClient,
) -> None:
    """Unknown ``include`` value 422s with a structured detail."""
    r = regctx_client.get(f"/v1/intel/regulatory_context/{PROGRAM_ID}?include=invalid_axis")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error"] == "invalid_include_value"


def test_regulatory_context_paid_final_cap_failure_returns_503_without_usage_event(
    regctx_client: TestClient,
    seeded_db: Path,
    paid_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final cap rejection must fail closed, not return unmetered 200."""
    key_hash = hash_api_key(paid_key)
    endpoint = "intel.regulatory_context"

    def _reject_final_cap(*_args: object, **_kwargs: object) -> tuple[bool, bool]:
        return False, False

    import jpintel_mcp.api.deps as deps

    monkeypatch.setattr(deps, "_metered_cap_final_check", _reject_final_cap)

    conn = sqlite3.connect(seeded_db)
    try:
        (before,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()

    r = regctx_client.get(
        f"/v1/intel/regulatory_context/{PROGRAM_ID}",
        headers={"X-API-Key": paid_key},
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"

    conn = sqlite3.connect(seeded_db)
    try:
        (after,) = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (key_hash, endpoint),
        ).fetchone()
    finally:
        conn.close()
    assert after == before
