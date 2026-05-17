"""AA1-G1 NTA tax-advisor cohort ETL test suite (2026-05-17).

Covers:
  * Manifest JSON shape + 10-gap enumeration.
  * Migration DDL idempotency (wave24_212 / 213 / 214).
  * Aggregator-host rejection in each ingest helper.
  * Allowlist regex coverage for nta.go.jp + kfs.go.jp + pref.*.lg.jp.
  * JSONL parsing + INSERT OR IGNORE round-trip on in-memory SQLite.
  * Textract submitter cost projection + budget guard.
  * Crawler runbook emission for the 10 gaps.

NO LLM. No network. All tests use in-memory SQLite + frozen fixtures.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

# Insert the crawler + ingest dirs onto sys.path so the modules import
# as flat names without dragging the rest of the etl package.
_ETL_DIR = REPO_ROOT / "scripts" / "etl"
_AWS_DIR = REPO_ROOT / "scripts" / "aws_credit_ops"
for _candidate in (_ETL_DIR, _AWS_DIR):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import crawl_nta_corpus_2026_05_17 as crawler  # noqa: E402
import ingest_chihouzei_tsutatsu_2026_05_17 as chihouzei_ingest  # noqa: E402
import ingest_nta_qa_to_db_2026_05_17 as qa_ingest  # noqa: E402
import ingest_tax_amendment_history_2026_05_17 as amendment_ingest  # noqa: E402
import textract_nta_bulk_2026_05_17 as textract  # noqa: E402

MANIFEST_PATH: Final = REPO_ROOT / "data" / "etl_g1_nta_manifest_2026_05_17.json"


# ---------------------------------------------------------------------------
# 1. Manifest shape (3 tests)
# ---------------------------------------------------------------------------


def test_manifest_file_exists() -> None:
    assert MANIFEST_PATH.exists(), f"manifest missing: {MANIFEST_PATH}"


def test_manifest_is_valid_json_object() -> None:
    obj = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(obj, dict)
    assert obj["manifest_id"] == "etl_g1_nta_manifest_2026_05_17"
    assert obj["task_id"] == "AA1-G1"


def test_manifest_has_10_gaps() -> None:
    obj = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    gaps = obj.get("gap_top_10")
    assert isinstance(gaps, dict)
    assert len(gaps) == 10
    expected_ids = {f"g{i}_" for i in range(1, 11)}
    matched = sum(1 for gid in gaps if any(gid.startswith(prefix) for prefix in expected_ids))
    assert matched == 10


# ---------------------------------------------------------------------------
# 2. Migration DDL (3 tests — one per migration)
# ---------------------------------------------------------------------------


def _apply_sql_file(conn: sqlite3.Connection, sql_path: Path) -> None:
    body = sql_path.read_text(encoding="utf-8")
    conn.executescript(body)


def test_migration_212_am_nta_qa_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    sql_path = REPO_ROOT / "scripts" / "migrations" / "wave24_212_am_nta_qa.sql"
    _apply_sql_file(conn, sql_path)
    _apply_sql_file(conn, sql_path)  # re-apply for idempotency
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_nta_qa'"
    ).fetchall()
    assert len(rows) == 1
    cols = {r[1] for r in conn.execute("PRAGMA table_info(am_nta_qa)").fetchall()}
    assert {"qa_kind", "tax_category", "slug", "source_url", "license"}.issubset(cols)
    conn.close()


def test_migration_213_am_chihouzei_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    sql_path = REPO_ROOT / "scripts" / "migrations" / "wave24_213_am_chihouzei_tsutatsu.sql"
    _apply_sql_file(conn, sql_path)
    _apply_sql_file(conn, sql_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_chihouzei_tsutatsu'"
    ).fetchall()
    assert len(rows) == 1
    cols = {r[1] for r in conn.execute("PRAGMA table_info(am_chihouzei_tsutatsu)").fetchall()}
    assert {"prefecture_code", "prefecture_name", "tax_kind", "source_url", "license"}.issubset(
        cols
    )
    conn.close()


def test_migration_214_am_amendment_idempotent() -> None:
    conn = sqlite3.connect(":memory:")
    sql_path = REPO_ROOT / "scripts" / "migrations" / "wave24_214_am_tax_amendment_history.sql"
    _apply_sql_file(conn, sql_path)
    _apply_sql_file(conn, sql_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='am_tax_amendment_history'"
    ).fetchall()
    assert len(rows) == 1
    cols = {r[1] for r in conn.execute("PRAGMA table_info(am_tax_amendment_history)").fetchall()}
    assert {"fiscal_year", "tax_kind", "statute_kind", "source_url", "license"}.issubset(cols)
    conn.close()


# ---------------------------------------------------------------------------
# 3. Allowlist + aggregator rejection (5 tests)
# ---------------------------------------------------------------------------


def test_crawler_allowlist_accepts_nta_go_jp() -> None:
    assert crawler._is_primary_host("https://www.nta.go.jp/law/shitsugi/hojin/01.htm")


def test_crawler_allowlist_accepts_kfs_go_jp() -> None:
    assert crawler._is_primary_host("https://www.kfs.go.jp/service/JP/idx/100.html")


def test_crawler_allowlist_rejects_aggregator_zeiken() -> None:
    assert not crawler._is_primary_host("https://www.zeiken.jp/saiketsu/2024/05/01.html")


def test_crawler_allowlist_rejects_aggregator_tabisland() -> None:
    assert not crawler._is_primary_host("https://www.tabisland.ne.jp/explain/2024/01.html")


def test_crawler_allowlist_accepts_metro_tokyo() -> None:
    assert crawler._is_primary_host("https://www.metro.tokyo.lg.jp/tosei/hodohappyo/index.html")


# ---------------------------------------------------------------------------
# 4. Ingest JSONL parsing + INSERT OR IGNORE (5 tests)
# ---------------------------------------------------------------------------


def _bootstrap_am_nta_qa(conn: sqlite3.Connection) -> None:
    sql_path = REPO_ROOT / "scripts" / "migrations" / "wave24_212_am_nta_qa.sql"
    conn.executescript(sql_path.read_text(encoding="utf-8"))


def test_qa_ingest_rejects_non_primary_host(tmp_path: Path) -> None:
    record = {
        "qa_kind": "shitsugi",
        "tax_category": "hojin",
        "slug": "hojin-1",
        "question": "Q",
        "answer": "A",
        "source_url": "https://zeiken.jp/article/1",
    }
    p = tmp_path / "in.jsonl"
    p.write_text(json.dumps(record) + "\n", encoding="utf-8")
    records = list(qa_ingest._load_jsonl_records(p))
    assert records == []


def test_qa_ingest_accepts_primary_host(tmp_path: Path) -> None:
    record = {
        "qa_kind": "shitsugi",
        "tax_category": "hojin",
        "slug": "hojin-1",
        "question": "Q",
        "answer": "A",
        "source_url": "https://www.nta.go.jp/law/shitsugi/hojin/01.htm",
    }
    p = tmp_path / "in.jsonl"
    p.write_text(json.dumps(record) + "\n", encoding="utf-8")
    records = list(qa_ingest._load_jsonl_records(p))
    assert len(records) == 1
    assert records[0].tax_category == "hojin"


def test_qa_ingest_insert_or_ignore_idempotent(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    _bootstrap_am_nta_qa(conn)
    rec = qa_ingest.QaRecord(
        qa_kind="shitsugi",
        tax_category="hojin",
        slug="hojin-1",
        question="Q",
        answer="A",
        related_law=None,
        decision_date=None,
        source_url="https://www.nta.go.jp/law/shitsugi/hojin/01.htm",
    )
    inserted_1, _ = qa_ingest._insert_batch(conn, [rec], dry_run=False)
    inserted_2, skipped_2 = qa_ingest._insert_batch(conn, [rec], dry_run=False)
    assert inserted_1 == 1
    assert inserted_2 == 0
    assert skipped_2 == 1
    conn.close()


def test_chihouzei_ingest_canonical_pref_table() -> None:
    assert len(chihouzei_ingest.CANONICAL_PREFECTURES) == 47
    assert chihouzei_ingest.CANONICAL_PREFECTURES["13"] == "東京都"
    assert chihouzei_ingest.CANONICAL_PREFECTURES["47"] == "沖縄県"


def test_amendment_ingest_filters_fy_window(tmp_path: Path) -> None:
    record = {
        "fiscal_year": 1985,  # before window
        "tax_kind": "hojin",
        "amendment_title": "T",
        "amendment_summary": "S",
        "statute_kind": "tax_law",
        "source_url": "https://www.nta.go.jp/law/joho/1985.htm",
    }
    p = tmp_path / "in.jsonl"
    p.write_text(json.dumps(record) + "\n", encoding="utf-8")
    records = list(amendment_ingest._load_jsonl(p))
    assert records == []  # 1985 < 1989 CHECK floor


# ---------------------------------------------------------------------------
# 5. Textract submitter cost guard (3 tests)
# ---------------------------------------------------------------------------


def test_textract_cost_projection_within_band() -> None:
    pdfs = [
        textract.PdfJob(
            source_url=f"https://www.kfs.go.jp/service/JP/{i}.pdf",
            sha256_hex=f"{i:064d}",
            expected_pages=30,
            cost_usd_estimated=30 * textract.DEFAULT_PER_PAGE_USD,
        )
        for i in range(3000)
    ]
    pages, cost = textract._project_cost(pdfs)
    assert pages == 90000
    assert cost == pytest.approx(4500.0, rel=1e-6)


def test_textract_budget_guard_stops_at_daily_cap() -> None:
    assert textract._enforce_budget_guard(650.0, daily_cap=700.0, hard_stop=19490.0)
    assert not textract._enforce_budget_guard(750.0, daily_cap=700.0, hard_stop=19490.0)


def test_textract_budget_guard_stops_at_hard_stop() -> None:
    assert not textract._enforce_budget_guard(19500.0, daily_cap=20000.0, hard_stop=19490.0)


# ---------------------------------------------------------------------------
# 6. Crawler runbook + gap selection (3 tests)
# ---------------------------------------------------------------------------


def test_crawler_loads_manifest_and_enumerates_10_gaps() -> None:
    manifest = crawler._load_manifest(MANIFEST_PATH)
    plans = crawler._enumerate_gaps(manifest)
    assert len(plans) == 10


def test_crawler_select_gaps_all() -> None:
    manifest = crawler._load_manifest(MANIFEST_PATH)
    plans = crawler._enumerate_gaps(manifest)
    selected = crawler._select_gaps(plans, "all")
    assert len(selected) == 10


def test_crawler_select_gaps_by_id() -> None:
    manifest = crawler._load_manifest(MANIFEST_PATH)
    plans = crawler._enumerate_gaps(manifest)
    selected = crawler._select_gaps(plans, "g1_shitsugi_hojin,g6_saiketsu_vol_1_to_120")
    selected_ids = {p.gap_id for p in selected}
    assert "g1_shitsugi_hojin" in selected_ids
    assert "g6_saiketsu_vol_1_to_120" in selected_ids
    assert len(selected) == 2


# ---------------------------------------------------------------------------
# 7. Workflow file landed (1 test)
# ---------------------------------------------------------------------------


def test_weekly_saiketsu_workflow_landed() -> None:
    workflow = REPO_ROOT / ".github" / "workflows" / "nta-saiketsu-weekly.yml"
    assert workflow.exists()
    body = workflow.read_text(encoding="utf-8")
    assert "nta-saiketsu-weekly" in body
    assert "cron:" in body
    # 03:00 JST Monday == 18:00 UTC Sunday
    assert "0 18 * * 0" in body


# ---------------------------------------------------------------------------
# 8. Aggregator hostname guard on chihouzei ingest (1 test)
# ---------------------------------------------------------------------------


def test_chihouzei_ingest_rejects_aggregator_host(tmp_path: Path) -> None:
    record = {
        "prefecture_code": "13",
        "tax_kind": "kojin_juminzei",
        "title": "T",
        "source_url": "https://www.zeiken.jp/chihouzei/tokyo/01.html",
    }
    p = tmp_path / "in.jsonl"
    p.write_text(json.dumps(record) + "\n", encoding="utf-8")
    records = list(chihouzei_ingest._load_jsonl(p))
    assert records == []  # rejected by primary-host regex
