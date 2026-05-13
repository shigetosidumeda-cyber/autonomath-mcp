"""Round-trip tests for scripts/publish_hf_datasets.py.

Each test seeds a tiny mock DB, runs the publish script in --dry-run, and
verifies the parquet + README + dataset_infos.json round-trip cleanly.

No HF push is exercised — that path is gated by the HF_TOKEN env var.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import publish_hf_datasets as publish  # noqa: E402

# ---------------------------------------------------------------------------
# Mock DB fixtures
# ---------------------------------------------------------------------------


def _seed_jpintel_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE laws (
            unified_id TEXT PRIMARY KEY,
            law_number TEXT NOT NULL,
            law_title TEXT NOT NULL,
            law_short_title TEXT,
            law_type TEXT NOT NULL,
            ministry TEXT,
            promulgated_date TEXT,
            enforced_date TEXT,
            last_amended_date TEXT,
            revision_status TEXT NOT NULL DEFAULT 'current',
            superseded_by_law_id TEXT,
            article_count INTEGER,
            full_text_url TEXT,
            summary TEXT,
            subject_areas_json TEXT,
            source_url TEXT NOT NULL,
            source_checksum TEXT,
            confidence REAL NOT NULL DEFAULT 0.95,
            fetched_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        INSERT INTO laws (
            unified_id, law_number, law_title, law_type, source_url,
            confidence, fetched_at, updated_at, enforced_date, last_amended_date
        ) VALUES
            ('LAW-aaaaaaaaaa', '令和元年法律第一号', 'テスト法', 'act',
             'https://laws.e-gov.go.jp/law/aaa', 0.95,
             '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', '2024-04-01', '2024-04-01'),
            ('LAW-bbbbbbbbbb', '令和元年法律第二号', '別のテスト法', 'act',
             'https://laws.e-gov.go.jp/law/bbb', 0.9,
             '2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', '2024-04-01', '2024-04-01');

        CREATE TABLE invoice_registrants (
            invoice_registration_number TEXT PRIMARY KEY,
            houjin_bangou TEXT,
            normalized_name TEXT NOT NULL,
            address_normalized TEXT,
            prefecture TEXT,
            registered_date TEXT NOT NULL,
            revoked_date TEXT,
            expired_date TEXT,
            registrant_kind TEXT NOT NULL,
            trade_name TEXT,
            last_updated_nta TEXT,
            source_url TEXT NOT NULL,
            source_checksum TEXT,
            confidence REAL NOT NULL DEFAULT 0.98,
            fetched_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO invoice_registrants (
            invoice_registration_number, houjin_bangou, normalized_name,
            address_normalized, prefecture, registered_date, registrant_kind,
            source_url, fetched_at, updated_at
        ) VALUES
            ('T1010001024632', '1010001024632', 'テスト株式会社',
             '東京都中央区築地1丁目13番1号', '東京都', '2023-10-01', 'corporation',
             'https://www.invoice-kohyo.nta.go.jp/download/test1.zip',
             '2026-04-24T09:07:32Z', '2026-04-24T09:07:32Z'),
            ('T9999999999999', NULL, '個人事業者太郎',
             '京都府京都市左京区一乗寺燈籠本町4', '京都府', '2023-10-01', 'sole_proprietor',
             'https://www.invoice-kohyo.nta.go.jp/download/test2.zip',
             '2026-04-24T09:07:32Z', '2026-04-24T09:07:32Z');

        CREATE TABLE enforcement_cases (
            case_id TEXT PRIMARY KEY,
            event_type TEXT,
            program_name_hint TEXT,
            recipient_name TEXT,
            recipient_kind TEXT,
            recipient_houjin_bangou TEXT,
            is_sole_proprietor INTEGER,
            bureau TEXT,
            intermediate_recipient TEXT,
            prefecture TEXT,
            ministry TEXT,
            occurred_fiscal_years_json TEXT,
            amount_yen INTEGER,
            amount_project_cost_yen INTEGER,
            amount_grant_paid_yen INTEGER,
            amount_improper_grant_yen INTEGER,
            amount_improper_project_cost_yen INTEGER,
            reason_excerpt TEXT,
            legal_basis TEXT,
            source_url TEXT,
            source_section TEXT,
            source_title TEXT,
            disclosed_date TEXT,
            disclosed_until TEXT,
            fetched_at TEXT,
            confidence REAL,
            valid_from TEXT,
            valid_until TEXT
        );
        INSERT INTO enforcement_cases (
            case_id, event_type, recipient_name, ministry, prefecture, amount_yen,
            legal_basis, reason_excerpt, source_url, disclosed_date, fetched_at,
            confidence
        ) VALUES
            ('test_case_001', 'clawback', 'テスト株式会社', '内閣府', '東京都',
             1000000, '補助金等に係る予算の執行の適正化に関する法律 第17条',
             'テスト reason', 'https://example.go.jp/case1',
             '2025-01-01', '2026-04-23T13:40:00Z', 0.9);
        """
    )
    conn.commit()
    conn.close()


def _seed_autonomath_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL,
            source_topic TEXT,
            source_record_index INTEGER,
            primary_name TEXT NOT NULL,
            authority_canonical TEXT,
            confidence REAL,
            source_url TEXT,
            source_url_domain TEXT,
            fetched_at TEXT,
            raw_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            canonical_status TEXT NOT NULL DEFAULT 'active',
            citation_status TEXT NOT NULL DEFAULT 'ok',
            valid_from TEXT,
            valid_until TEXT
        );
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, confidence, source_url, source_url_domain, fetched_at,
            raw_json
        ) VALUES
            ('statistic:test:000:abc', 'statistic', '18_estat_industry_distribution',
             0, 'e-Stat テスト統計', 0.98,
             'https://www.e-stat.go.jp/stat-search/file-download?statInfId=test',
             'e-stat.go.jp', '2026-04-23T04:52:26Z', '{"sample": true}');

        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT NOT NULL UNIQUE,
            source_type TEXT NOT NULL DEFAULT 'primary',
            domain TEXT,
            is_pdf INTEGER NOT NULL DEFAULT 0,
            content_hash TEXT,
            first_seen TEXT NOT NULL DEFAULT (datetime('now')),
            last_verified TEXT,
            promoted_at TEXT NOT NULL DEFAULT (datetime('now')),
            canonical_status TEXT NOT NULL DEFAULT 'active',
            license TEXT
        );
        INSERT INTO am_source (source_url, domain, license, last_verified)
        VALUES
            ('https://www.e-stat.go.jp/stat-search/file-download?statInfId=test',
             'e-stat.go.jp', 'gov_standard_v2.0', '2026-04-30');

        CREATE TABLE am_enforcement_detail (
            enforcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id TEXT NOT NULL,
            houjin_bangou TEXT,
            target_name TEXT,
            enforcement_kind TEXT,
            issuing_authority TEXT,
            issuance_date TEXT NOT NULL,
            exclusion_start TEXT,
            exclusion_end TEXT,
            reason_summary TEXT,
            related_law_ref TEXT,
            amount_yen INTEGER,
            source_url TEXT,
            source_fetched_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO am_enforcement_detail (
            entity_id, houjin_bangou, target_name, enforcement_kind,
            issuing_authority, issuance_date, reason_summary, source_url,
            source_fetched_at
        ) VALUES
            ('enforcement:test:000', '1234567890123', 'AM テスト株式会社',
             'subsidy_exclude', '経済産業省', '2025-01-15', 'AM reason',
             'https://example.meti.go.jp/case_am1', '2026-04-23T13:40:00Z');
        INSERT INTO am_source (source_url, domain, license)
        VALUES ('https://example.meti.go.jp/case_am1', 'example.meti.go.jp',
                'gov_standard_v2.0');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def mock_dbs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    jpintel = tmp_path / "jpintel.db"
    autonomath = tmp_path / "autonomath.db"
    output_root = tmp_path / "out"
    blacklist_csv = tmp_path / "blacklist.csv"
    _seed_jpintel_db(jpintel)
    _seed_autonomath_db(autonomath)
    blacklist_csv.write_text("source_id,license,domain,source_type,source_url\n")
    return jpintel, autonomath, output_root, blacklist_csv


# ---------------------------------------------------------------------------
# Per-dataset round-trip tests
# ---------------------------------------------------------------------------


def _read_round_trip(out_dir: Path) -> tuple[pd.DataFrame, dict, dict]:
    parquet = pd.read_parquet(out_dir / "data.parquet")
    dataset_infos = json.loads((out_dir / "dataset_infos.json").read_text())
    manifest = json.loads((out_dir / "manifest.json").read_text())
    return parquet, dataset_infos, manifest


def test_publish_laws_jp_round_trip(mock_dbs):
    jpintel, autonomath, output_root, blacklist = mock_dbs
    rc = publish.main(
        [
            "--dataset",
            "laws-jp",
            "--jpintel-db",
            str(jpintel),
            "--autonomath-db",
            str(autonomath),
            "--output-root",
            str(output_root),
            "--blacklist-csv",
            str(blacklist),
            "--limit",
            "10",
            "--dry-run",
            "--skip-safety-gate",
        ]
    )
    assert rc == 0
    out_dir = output_root / "laws-jp"
    df, infos, manifest = _read_round_trip(out_dir)
    assert len(df) == 2
    assert set(df["license"]) == {"cc_by_4.0"}
    assert "law_id" in df.columns
    assert manifest["dataset"] == "laws-jp"
    assert manifest["dry_run"] is True
    assert manifest["hf_repo_id"] == "bookyou/laws-jp"
    assert "bookyou/laws-jp" in infos


def test_publish_invoice_registrants_kojin_redaction(mock_dbs):
    jpintel, autonomath, output_root, blacklist = mock_dbs
    rc = publish.main(
        [
            "--dataset",
            "invoice-registrants",
            "--jpintel-db",
            str(jpintel),
            "--autonomath-db",
            str(autonomath),
            "--output-root",
            str(output_root),
            "--blacklist-csv",
            str(blacklist),
            "--limit",
            "10",
            "--dry-run",
            "--skip-safety-gate",
        ]
    )
    assert rc == 0
    out_dir = output_root / "invoice-registrants"
    df, _infos, _manifest = _read_round_trip(out_dir)
    # 2 rows seeded; both active
    assert len(df) == 2
    # houjin keeps its full address; kojin drops to prefecture-only
    houjin_row = df[df["type"] == "houjin"].iloc[0]
    kojin_row = df[df["type"] == "kojin"].iloc[0]
    assert "中央区築地" in houjin_row["address"]
    assert kojin_row["address"] == kojin_row["prefecture"] == "京都府"


def test_publish_statistics_estat_round_trip(mock_dbs):
    jpintel, autonomath, output_root, blacklist = mock_dbs
    rc = publish.main(
        [
            "--dataset",
            "statistics-estat",
            "--jpintel-db",
            str(jpintel),
            "--autonomath-db",
            str(autonomath),
            "--output-root",
            str(output_root),
            "--blacklist-csv",
            str(blacklist),
            "--limit",
            "10",
            "--dry-run",
            "--skip-safety-gate",
        ]
    )
    assert rc == 0
    out_dir = output_root / "statistics-estat"
    df, _infos, manifest = _read_round_trip(out_dir)
    assert len(df) == 1
    assert df.iloc[0]["source_domain"] == "e-stat.go.jp"
    assert df.iloc[0]["license"] == "gov_standard_v2.0"
    assert manifest["hf_repo_id"] == "bookyou/statistics-estat"


def test_publish_statistics_estat_drops_pending_and_unknown_licenses(mock_dbs):
    jpintel, autonomath, output_root, blacklist = mock_dbs
    conn = sqlite3.connect(autonomath)
    conn.executescript(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, confidence, source_url, source_url_domain, fetched_at,
            raw_json
        ) VALUES
            ('statistic:test:pending', 'statistic', '18_estat_industry_distribution',
             1, 'pending e-Stat row', 0.98,
             'https://www.e-stat.go.jp/stat-search/file-download?statInfId=pending',
             'e-stat.go.jp', '2026-04-23T04:52:26Z', '{"sample": "pending"}'),
            ('statistic:test:unknown', 'statistic', '18_estat_industry_distribution',
             2, 'unknown e-Stat row', 0.98,
             'https://www.e-stat.go.jp/stat-search/file-download?statInfId=unknown',
             'e-stat.go.jp', '2026-04-23T04:52:26Z', '{"sample": "unknown"}');
        INSERT INTO am_source (source_url, domain, license)
        VALUES
            ('https://www.e-stat.go.jp/stat-search/file-download?statInfId=pending',
             'e-stat.go.jp', 'pending_review'),
            ('https://www.e-stat.go.jp/stat-search/file-download?statInfId=unknown',
             'e-stat.go.jp', 'unknown');
        """
    )
    conn.commit()
    conn.close()

    rc = publish.main(
        [
            "--dataset",
            "statistics-estat",
            "--jpintel-db",
            str(jpintel),
            "--autonomath-db",
            str(autonomath),
            "--output-root",
            str(output_root),
            "--blacklist-csv",
            str(blacklist),
            "--limit",
            "10",
            "--dry-run",
            "--skip-safety-gate",
        ]
    )

    assert rc == 0
    df, _infos, _manifest = _read_round_trip(output_root / "statistics-estat")
    assert set(df["entity_id"]) == {"statistic:test:000:abc"}
    assert set(df["license"]) == {"gov_standard_v2.0"}


def test_publish_corp_enforcement_unions_both_dbs(mock_dbs):
    jpintel, autonomath, output_root, blacklist = mock_dbs
    rc = publish.main(
        [
            "--dataset",
            "corp-enforcement",
            "--jpintel-db",
            str(jpintel),
            "--autonomath-db",
            str(autonomath),
            "--output-root",
            str(output_root),
            "--blacklist-csv",
            str(blacklist),
            "--limit",
            "10",
            "--dry-run",
            "--skip-safety-gate",
        ]
    )
    assert rc == 0
    out_dir = output_root / "corp-enforcement"
    df, _infos, _manifest = _read_round_trip(out_dir)
    assert len(df) == 2  # 1 from jpintel + 1 from autonomath
    sources = set(df["source_table"])
    assert sources == {
        "jpintel.enforcement_cases",
        "autonomath.am_enforcement_detail",
    }
    assert set(df["license"]) <= {"gov_standard_v2.0"}


# ---------------------------------------------------------------------------
# License + blacklist filter behaviour
# ---------------------------------------------------------------------------


def test_blacklist_drops_matching_url(tmp_path, mock_dbs):
    jpintel, autonomath, output_root, _ = mock_dbs
    blacklist = tmp_path / "blacklist_active.csv"
    blacklist.write_text(
        "source_id,license,domain,source_type,source_url\n"
        "1,unknown,e-gov.go.jp,primary,https://laws.e-gov.go.jp/law/aaa\n"
    )

    rc = publish.main(
        [
            "--dataset",
            "laws-jp",
            "--jpintel-db",
            str(jpintel),
            "--autonomath-db",
            str(autonomath),
            "--output-root",
            str(output_root),
            "--blacklist-csv",
            str(blacklist),
            "--limit",
            "10",
            "--dry-run",
            "--skip-safety-gate",
        ]
    )
    assert rc == 0
    df, _, _ = _read_round_trip(output_root / "laws-jp")
    # one of the 2 seeded rows is blacklisted → exactly 1 row should remain
    assert len(df) == 1
    assert df.iloc[0]["law_id"] == "LAW-bbbbbbbbbb"


def test_push_without_token_raises(monkeypatch, mock_dbs):
    jpintel, autonomath, output_root, blacklist = mock_dbs
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        publish.main(
            [
                "--dataset",
                "laws-jp",
                "--jpintel-db",
                str(jpintel),
                "--autonomath-db",
                str(autonomath),
                "--output-root",
                str(output_root),
                "--blacklist-csv",
                str(blacklist),
                "--limit",
                "5",
                "--push",
                "--skip-safety-gate",
            ]
        )
