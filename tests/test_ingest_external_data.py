"""Tests for scripts/ingest_external_data.py.

Exercised on a scratch DB built with `schema.sql` + `migrate.run_migrations`
so we hit the real 011 migration path that the production ingest will use.
Writes mini JSONL fixtures into a tmp dir that mirrors the 2026-04-23
collection layout, runs the ingest, and asserts on:

1. one row lands in each of the six new/modified tables;
2. a second ingest on the same inputs is a no-op (idempotent);
3. UPSERT into existing `programs` rows updates `enriched_json` /
   `source_url` without clobbering pre-existing non-null fields.

We keep the fixtures tiny (1-2 rows per directory) on purpose — the goal
is behavioural, not throughput.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

# ingest_external_data lives under scripts/, which is not a package.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import ingest_external_data as ext  # noqa: E402
import migrate  # noqa: E402

# Reuse session.init_db to stamp schema.sql onto a fresh file.
from jpintel_mcp.db.session import init_db  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


@pytest.fixture()
def scratch_db(tmp_path: Path) -> Path:
    """Fresh DB with schema.sql + all migrations applied."""
    db_path = tmp_path / "ingest_test.db"
    init_db(db_path)
    applied = migrate.run_migrations(db_path)
    # 011 must have executed so the new tables exist.
    assert any("011_external_data_tables" in a for a in applied) or _has_table(
        db_path, "program_documents"
    ), "migration 011 did not run"
    return db_path


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Mini data collection tree; one record per directory."""
    root = tmp_path / "collection"
    _write_jsonl(
        root / "03_exclusion_rules" / "records.jsonl",
        [
            {
                "program_name_a": "ものづくり補助金 (第23次公募)",
                "rule_type": "exclude",
                "excluded_programs": [
                    "国（独立行政法人等を含む）が目的を指定して支出する他の補助金"
                ],
                "condition": "同一の補助対象経費",
                "source_url": "https://example.gov.jp/hojyo/23th.pdf",
                "source_excerpt": "同一の補助対象経費を含む事業",
                "fetched_at": "2026-04-23T04:30:00Z",
                "confidence": 0.95,
            }
        ],
    )
    _write_jsonl(
        root / "04_program_documents" / "records.jsonl",
        [
            {
                "program_name": "ものづくり補助金 23次締切",
                "form_name": "公募要領",
                "form_type": "required",
                "form_format": "pdf",
                "form_url_direct": "https://example.gov.jp/form.pdf",
                "pages": 50,
                "signature_required": False,
                "support_org_needed": None,
                "completion_example_url": None,
                "source_url": "https://example.gov.jp/about",
                "fetched_at": "2026-04-23T04:33:00Z",
                "confidence": 0.98,
            }
        ],
    )
    _write_jsonl(
        root / "06_prefecture_programs" / "records.jsonl",
        [
            {
                "program_name": "テスト県 助成金",
                "authority_level": "prefecture",
                "authority_name": "テスト県産業労働局",
                "prefecture": "テスト県",
                "program_kind": "subsidy",
                "amount_max_man_yen": 2000,
                "subsidy_rate": 0.667,
                "target_types": ["中小企業", "個人事業主"],
                "official_url": "https://test-pref.example.jp/prog",
                "source_excerpt": "助成上限2,000万円",
                "fetched_at": "2026-04-23T12:00:00Z",
                "confidence": 0.92,
            }
        ],
    )
    _write_jsonl(
        root / "07_new_program_candidates" / "records.jsonl",
        [
            {
                "candidate_name": "特定生産性向上設備等投資促進税制",
                "mentioned_in": "令和8年度税制改正の大綱",
                "ministry": "経産省/財務省",
                "budget_yen": None,
                "program_kind_hint": "tax_credit",
                "expected_start": "令和8年度",
                "policy_background_excerpt": "産業競争力強化法の改正...",
                "source_url": "https://example.gov.jp/tax/outline.pdf",
                "source_pdf_page": "56-58",
                "fetched_at": "2026-04-23T04:36:00Z",
                "confidence": 0.98,
            }
        ],
    )
    _write_jsonl(
        root / "08_loan_programs" / "records.jsonl",
        [
            {
                "program_name": "テスト開業資金",
                "provider": "日本政策金融公庫 国民生活事業",
                "loan_type": "special_rate",
                "amount_max_yen": 72000000,
                "loan_period_years_max": 20,
                "grace_period_years_max": 5,
                "interest_rate_base_annual": 0.041,
                "interest_rate_special_annual": None,
                "rate_names": "基準利率,特別利率",
                "security_required": "要相談",
                "target_conditions": "新規事業者向け",
                "official_url": "https://example.jfc.go.jp/loan",
                "source_excerpt": "上限7,200万円",
                "fetched_at": "2026-04-23T04:32:55Z",
                "confidence": 0.9,
            }
        ],
    )
    _write_jsonl(
        root / "13_enforcement_cases" / "records.jsonl",
        [
            {
                "case_id": "jbaudit_test_001",
                "event_type": "clawback",
                "program_name_hint": "テスト交付金",
                "recipient_name": "テスト市",
                "recipient_houjin_bangou": None,
                "recipient_kind": "municipality",
                "is_sole_proprietor": False,
                "bureau": "テスト県",
                "intermediate_recipient": "",
                "prefecture": "テスト県",
                "ministry": "テスト省",
                "occurred_fiscal_years": [2019],
                "amount_yen": 89073000,
                "amount_project_cost_yen": 3329065000,
                "amount_grant_paid_yen": 1110837000,
                "amount_improper_grant_yen": 89073000,
                "amount_improper_project_cost_yen": None,
                "reason_excerpt": "交付要件不備",
                "legal_basis": "補助金等に係る予算の執行の適正化に関する法律 第17条",
                "source_url": "https://report.example.jp/case/001.htm",
                "source_section": "2021-r03-0046-0",
                "source_title": "交付金の過大交付",
                "disclosed_date": "2022-11-07",
                "disclosed_until": "2027-11-06",
                "fetched_at": "2026-04-23T13:40:00Z",
                "confidence": 0.9,
            }
        ],
    )
    _write_jsonl(
        root / "22_mirasapo_cases" / "records.jsonl",
        [
            {
                "case_id": "mirasapo_case_test_1",
                "company_name": "テスト株式会社",
                "houjin_bangou": "3260001025496",
                "is_sole_proprietor": False,
                "prefecture": "テスト県",
                "municipality": None,
                "industry_jsic": "D06",
                "industry_name": "総合工事業",
                "employees": 13,
                "founded_year": 2011,
                "capital_yen": 35000000,
                "case_title": "災害復旧事例",
                "case_summary": "豪雨被害から再建した事業者。",
                "programs_used": [],
                "total_subsidy_received_yen": None,
                "outcomes": [],
                "patterns": ["BCP/災害対応"],
                "publication_date": "2020-03-23",
                "source_url": "https://mirasapo.example.jp/case/1",
                "source_excerpt": "被災翌日から復旧に着手。",
                "fetched_at": "2026-04-23T05:00:17Z",
                "confidence": 0.9,
            }
        ],
    )
    return root


def _has_table(db_path: Path, name: str) -> bool:
    c = sqlite3.connect(str(db_path))
    try:
        r = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (name,),
        ).fetchone()
        return r is not None
    finally:
        c.close()


def _count(db_path: Path, table: str) -> int:
    c = sqlite3.connect(str(db_path))
    try:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_one_row_in_each_of_six_tables(scratch_db: Path, data_dir: Path) -> None:
    """First-pass ingest writes one row per directory to the right table."""
    results = ext.run_ingest(
        data_dir=data_dir, db_path=scratch_db, dry_run=False
    )

    # Spec-called-out tables (≥ 6 per task description).
    assert _count(scratch_db, "program_documents") == 1
    assert _count(scratch_db, "case_studies") == 1
    assert _count(scratch_db, "enforcement_cases") == 1
    assert _count(scratch_db, "new_program_candidates") == 1
    assert _count(scratch_db, "loan_programs") == 1

    # exclusion_rules: fan-out expands excluded_programs. Our fixture has
    # a 1-element list so exactly 1 new row.
    c = sqlite3.connect(str(scratch_db))
    try:
        rows = c.execute(
            "SELECT rule_id, source_excerpt, condition FROM exclusion_rules "
            "WHERE rule_id LIKE 'excl-ext-%'"
        ).fetchall()
    finally:
        c.close()
    assert len(rows) == 1
    assert rows[0][1] == "同一の補助対象経費を含む事業"
    assert rows[0][2] == "同一の補助対象経費"

    # programs: 06 + 08 (loan mirror) = 2 inserts.
    c = sqlite3.connect(str(scratch_db))
    try:
        n = c.execute(
            "SELECT COUNT(*) FROM programs WHERE unified_id LIKE 'UNI-ext-%'"
        ).fetchone()[0]
    finally:
        c.close()
    assert n == 2

    # Dispatcher report sanity check.
    assert "06_prefecture_programs" in results
    assert results["06_prefecture_programs"].get("insert", 0) == 1
    assert results["13_enforcement_cases"]["insert"] == 1


def test_reingest_is_idempotent(scratch_db: Path, data_dir: Path) -> None:
    """Re-running on the same inputs must not grow any table."""
    ext.run_ingest(data_dir=data_dir, db_path=scratch_db, dry_run=False)

    counts_before = {
        t: _count(scratch_db, t)
        for t in (
            "programs",
            "exclusion_rules",
            "program_documents",
            "case_studies",
            "enforcement_cases",
            "new_program_candidates",
            "loan_programs",
        )
    }

    # Second pass, identical inputs.
    ext.run_ingest(data_dir=data_dir, db_path=scratch_db, dry_run=False)

    counts_after = {
        t: _count(scratch_db, t)
        for t in counts_before
    }
    assert counts_before == counts_after, (
        f"idempotent re-ingest grew the DB: {counts_before} -> {counts_after}"
    )


def test_existing_program_source_excerpt_only_updated(
    scratch_db: Path, data_dir: Path
) -> None:
    """Pre-existing programs row (non-excluded) gets its enriched_json /
    source_url refreshed on re-ingest, but curator-owned fields like
    `primary_name` and `amount_max_man_yen` survive when the external
    record leaves them unchanged.

    This mirrors the spec's "既存 program の source_excerpt だけ更新される"
    contract — external-ingest never clobbers canonical fields.
    """
    # Seed a canonical row with a synthetic unified_id that matches what
    # _ext_unified_id() will derive for the fixture's 06 record.
    uid = ext._ext_unified_id(
        "テスト県 助成金", "テスト県産業労働局", "テスト県"
    )
    now = datetime.now(UTC).isoformat()
    c = sqlite3.connect(str(scratch_db))
    try:
        c.execute(
            """INSERT INTO programs (
                unified_id, primary_name, aliases_json,
                authority_level, authority_name, prefecture, municipality,
                program_kind, official_url,
                amount_max_man_yen, amount_min_man_yen, subsidy_rate,
                trust_level, tier, coverage_score, gap_to_tier_s_json, a_to_j_coverage_json,
                excluded, exclusion_reason,
                crop_categories_json, equipment_category,
                target_types_json, funding_purpose_json,
                amount_band, application_window_json,
                enriched_json, source_mentions_json,
                source_url, source_fetched_at, source_checksum,
                updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                uid,
                "CANONICAL 上書き禁止 Name",   # <-- must not change
                None,
                "prefecture",
                "テスト県産業労働局",
                "テスト県",
                None,
                "subsidy",
                None,
                9999,                           # <-- must not change
                None,
                None,
                None,
                "S",                            # <-- must not change
                None, None, None,
                0,                              # excluded = 0 (updatable)
                None,
                None, None,
                None, None,
                None, None,
                None, None,                     # enriched_json starts null
                None,                           # source_url starts null
                now,
                None,
                now,
            ),
        )
        c.commit()
    finally:
        c.close()

    ext.run_ingest(data_dir=data_dir, db_path=scratch_db, dry_run=False)

    c = sqlite3.connect(str(scratch_db))
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT primary_name, amount_max_man_yen, tier, "
            "source_url, enriched_json FROM programs WHERE unified_id = ?",
            (uid,),
        ).fetchone()
    finally:
        c.close()

    assert row is not None
    # Curator fields preserved.
    assert row["primary_name"] == "CANONICAL 上書き禁止 Name"
    assert row["amount_max_man_yen"] == 9999
    assert row["tier"] == "S"
    # External fields populated.
    assert row["source_url"] == "https://test-pref.example.jp/prog"
    assert row["enriched_json"] is not None
    enriched = json.loads(row["enriched_json"])
    assert enriched.get("source_excerpt") == "助成上限2,000万円"


def test_banned_aggregator_urls_rejected(
    scratch_db: Path, tmp_path: Path
) -> None:
    """Rows whose source_url/official_url points at a banned aggregator
    (biz.stayway, hojyokin-portal, noukaweb, ...) must be dropped before
    they ever hit the DB. CLAUDE.md names these as 詐欺-risk sources.
    """
    root = tmp_path / "banned_collection"
    # A prefecture program with a biz.stayway official_url (4 such rows were
    # caught in the 2026-04-23 live ingest).
    _write_jsonl(
        root / "06_prefecture_programs" / "records.jsonl",
        [
            {
                "program_name": "banned-pref-prog",
                "authority_level": "prefecture",
                "authority_name": "テスト県",
                "prefecture": "テスト県",
                "program_kind": "subsidy",
                "official_url": "https://biz.stayway.jp/hojyo_detail/99999/",
                "source_excerpt": "aggregator",
                "fetched_at": "2026-04-23T05:00:00Z",
                "confidence": 0.5,
            }
        ],
    )
    # A candidate with hojyokin-portal source (32 such rows caught live).
    _write_jsonl(
        root / "07_new_program_candidates" / "records.jsonl",
        [
            {
                "candidate_name": "banned-candidate",
                "mentioned_in": "columns page",
                "ministry": "財務省",
                "source_url": "https://hojyokin-portal.jp/columns/foo",
                "fetched_at": "2026-04-23T05:00:00Z",
                "confidence": 0.5,
            }
        ],
    )
    # A factory-dispatched program with a noukaweb URL.
    _write_jsonl(
        root / "11_mhlw_employment_grants" / "records.jsonl",
        [
            {
                "program_name": "banned-mhlw",
                "authority": "厚労省",
                "official_url": "https://noukaweb.com/something",
                "fetched_at": "2026-04-23T05:00:00Z",
            }
        ],
    )

    results = ext.run_ingest(data_dir=root, db_path=scratch_db, dry_run=False)

    # Nothing should have landed in any table.
    assert _count(scratch_db, "programs") == 0
    assert _count(scratch_db, "new_program_candidates") == 0

    # Dispatcher should report skip_banned for each affected dir.
    assert results["06_prefecture_programs"]["skip_banned"] == 1
    assert results["07_new_program_candidates"]["skip_banned"] == 1
    assert results["11_mhlw_employment_grants"]["skip_banned"] == 1


def test_case_law_ingest_and_idempotency(
    scratch_db: Path, tmp_path: Path
) -> None:
    """49_case_law_judgments routes to the `case_law` table keyed on
    (case_number, court). Rows missing case_number are skipped; re-ingest
    on the same inputs is a no-op.
    """
    root = tmp_path / "case_law_collection"
    _write_jsonl(
        root / "49_case_law_judgments" / "records.jsonl",
        [
            {
                "case_name": "行政処分取消請求事件",
                "court": "最高裁判所第三小法廷",
                "decision_date": "令和8年3月27日",
                "case_number": "令和7(行ヒ)25",
                "subject_area": "administrative",
                "key_ruling": "破棄自判 (取消)",
                "parties_involved": "masked",
                "impact_on_business": "事業者への影響あり",
                "source_url": "https://www.courts.go.jp/app/hanrei_jp/detail2/95768",
                "source_excerpt": "令和7(行ヒ)25 行政処分取消請求事件",
                "confidence": "high",
                "pdf_url": "https://www.courts.go.jp/assets/hanrei/hanrei-pdf-95768.pdf",
                "category": "最高裁判例",
                "fetched_at": "2026-04-23T08:00:00Z",
            },
            # Missing case_number — must be skipped (cannot dedupe).
            {
                "case_name": "ダミー事件",
                "court": "地方裁判所",
                "category": "下級裁裁判例",
                "fetched_at": "2026-04-23T08:00:00Z",
            },
        ],
    )

    r1 = ext.run_ingest(data_dir=root, db_path=scratch_db, dry_run=False)
    assert r1["49_case_law_judgments"]["insert"] == 1
    assert r1["49_case_law_judgments"]["skip"] == 1
    assert _count(scratch_db, "case_law") == 1

    # Re-ingest: no inserts, the one valid row becomes an update (COALESCE
    # no-op) and the dummy still skips.
    r2 = ext.run_ingest(data_dir=root, db_path=scratch_db, dry_run=False)
    assert r2["49_case_law_judgments"]["insert"] == 0
    assert r2["49_case_law_judgments"]["update"] == 1
    assert r2["49_case_law_judgments"]["skip"] == 1
    assert _count(scratch_db, "case_law") == 1


def test_classify_loan_security_axes() -> None:
    """_classify_loan_security splits Japanese collateral/guarantor phrasing
    into three orthogonal axes. Regression-guards the specific phrasings
    our 08_loan_programs collector agent emits today.
    """
    c = ext._classify_loan_security

    # 無担保・無保証 (combined) → collateral + third-party both not_required.
    # Personal guarantor still unknown because the phrase doesn't commit on it.
    r = c("無担保・無保証", None)
    assert r["collateral_required"] == "not_required"
    assert r["third_party_guarantor_required"] == "not_required"
    assert r["personal_guarantor_required"] == "unknown"
    assert r["security_notes"] == "無担保・無保証"

    # 要相談（担保・保証） → all three axes land on "negotiable".
    r = c("要相談（担保・保証）", None)
    assert r == {
        "collateral_required": "negotiable",
        "personal_guarantor_required": "negotiable",
        "third_party_guarantor_required": "negotiable",
        "security_notes": "要相談（担保・保証）",
    }

    # Bare 要相談 → same negotiable-all outcome (topic is on the table).
    r = c("要相談", None)
    assert r["collateral_required"] == "negotiable"
    assert r["personal_guarantor_required"] == "negotiable"
    assert r["third_party_guarantor_required"] == "negotiable"

    # 経営者保証免除 → personal not_required overrides 要相談 default.
    r = c("要相談", "経営者保証免除特例制度の要件を満たす方")
    assert r["personal_guarantor_required"] == "not_required"
    # Other axes stay on the 要相談 default.
    assert r["collateral_required"] == "negotiable"
    assert r["third_party_guarantor_required"] == "negotiable"

    # Missing / empty → all unknown.
    r = c(None, None)
    assert r == {
        "collateral_required": "unknown",
        "personal_guarantor_required": "unknown",
        "third_party_guarantor_required": "unknown",
        "security_notes": None,
    }

    # 無担保 alone (without 無保証) → only collateral flips; 3rd-party guarantor
    # stays unknown even without 要相談 context.
    r = c("無担保", None)
    assert r["collateral_required"] == "not_required"
    assert r["third_party_guarantor_required"] == "unknown"


def test_loan_risk_columns_populated_on_ingest(
    scratch_db: Path, tmp_path: Path
) -> None:
    """Ingest writes the three risk axes into the loan_programs table,
    not just the legacy free-text `security_required` column.
    """
    root = tmp_path / "loan_risk"
    _write_jsonl(
        root / "08_loan_programs" / "records.jsonl",
        [
            {
                "program_name": "マル経融資",
                "provider": "日本政策金融公庫 国民生活事業",
                "loan_type": "base_rate",
                "amount_max_yen": 20000000,
                "security_required": "無担保・無保証",
                "official_url": "https://www.jfc.go.jp/n/finance/search/maruk_m.html",
                "fetched_at": "2026-04-23T06:00:00Z",
            },
            {
                "program_name": "一般貸付",
                "provider": "日本政策金融公庫 国民生活事業",
                "loan_type": "base_rate",
                "security_required": "要相談（担保・保証）",
                "official_url": "https://www.jfc.go.jp/n/finance/search/01_g_m.html",
                "fetched_at": "2026-04-23T06:00:00Z",
            },
        ],
    )

    ext.run_ingest(data_dir=root, db_path=scratch_db, dry_run=False)

    c = sqlite3.connect(str(scratch_db))
    c.row_factory = sqlite3.Row
    try:
        rows = {
            r["program_name"]: r
            for r in c.execute(
                "SELECT program_name, collateral_required, "
                "personal_guarantor_required, third_party_guarantor_required, "
                "security_notes FROM loan_programs"
            ).fetchall()
        }
    finally:
        c.close()

    assert rows["マル経融資"]["collateral_required"] == "not_required"
    assert rows["マル経融資"]["third_party_guarantor_required"] == "not_required"
    assert rows["マル経融資"]["security_notes"] == "無担保・無保証"

    assert rows["一般貸付"]["collateral_required"] == "negotiable"
    assert rows["一般貸付"]["personal_guarantor_required"] == "negotiable"
    assert rows["一般貸付"]["third_party_guarantor_required"] == "negotiable"


def test_case_law_banned_pdf_url_rejected(
    scratch_db: Path, tmp_path: Path
) -> None:
    """If either source_url or pdf_url points at a banned aggregator,
    the case_law row is dropped before write.
    """
    root = tmp_path / "case_law_banned"
    _write_jsonl(
        root / "49_case_law_judgments" / "records.jsonl",
        [
            {
                "case_name": "aggregator-case",
                "court": "テスト裁判所",
                "case_number": "BAN-1",
                "source_url": "https://www.courts.go.jp/ok",
                "pdf_url": "https://hojyokin-portal.jp/leaked.pdf",
                "fetched_at": "2026-04-23T08:00:00Z",
            }
        ],
    )

    r = ext.run_ingest(data_dir=root, db_path=scratch_db, dry_run=False)
    assert r["49_case_law_judgments"]["skip_banned"] == 1
    assert _count(scratch_db, "case_law") == 0
