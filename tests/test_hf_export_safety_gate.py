from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ETL = _ROOT / "scripts" / "etl"
_SCRIPTS = _ROOT / "scripts"
for _path in (_ETL, _SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import hf_dataset_export  # noqa: E402
import hf_export_safety_gate as gate  # noqa: E402


def test_gate_blocks_unknown_and_proprietary_licenses() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE public_rows (
            name TEXT,
            license TEXT
        );
        INSERT INTO public_rows VALUES
            ('ok', 'gov_standard_v2.0'),
            ('unknown-row', 'unknown'),
            ('proprietary-row', 'proprietary');
        """
    )

    issues = gate.collect_hf_export_safety_issues(
        conn,
        [("public_rows", "SELECT name, license FROM public_rows")],
    )

    assert [issue.code for issue in issues] == ["blocked_license"]
    assert "unknown=1" in issues[0].detail
    assert "proprietary=1" in issues[0].detail


def test_gate_fails_closed_when_license_metadata_is_missing() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE public_rows (
            name TEXT,
            source_url TEXT
        );
        INSERT INTO public_rows VALUES ('row', 'https://example.test/source');
        """
    )

    issues = gate.collect_hf_export_safety_issues(
        conn,
        [("public_rows", "SELECT name, source_url FROM public_rows")],
    )

    assert [issue.code for issue in issues] == ["missing_license_metadata"]


def test_gate_uses_am_source_license_when_rows_have_source_urls() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE public_rows (
            name TEXT,
            source_url TEXT
        );
        CREATE TABLE am_source (
            source_url TEXT PRIMARY KEY,
            license TEXT
        );
        INSERT INTO public_rows VALUES
            ('ok', 'https://example.test/ok'),
            ('blocked', 'https://example.test/blocked'),
            ('unmapped', 'https://example.test/unmapped');
        INSERT INTO am_source VALUES
            ('https://example.test/ok', 'pdl_v1.0'),
            ('https://example.test/blocked', 'unknown');
        """
    )

    issues = gate.collect_hf_export_safety_issues(
        conn,
        [("public_rows", "SELECT name, source_url FROM public_rows")],
    )

    assert [issue.code for issue in issues] == ["blocked_source_license"]
    assert "unknown=1" in issues[0].detail
    assert "<MISSING>=1" in issues[0].detail


def test_gate_blocks_row_level_adoption_identifiers_even_with_safe_license() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE case_studies (
            company_name TEXT,
            prefecture TEXT,
            license TEXT
        );
        INSERT INTO case_studies VALUES ('Example KK', 'Tokyo', 'gov_standard_v2.0');
        """
    )

    issues = gate.collect_hf_export_safety_issues(
        conn,
        [("case_studies", "SELECT company_name, prefecture, license FROM case_studies")],
    )

    assert [issue.code for issue in issues] == ["row_level_deanonymization_risk"]
    assert "company_name" in issues[0].detail


def test_gate_allows_sensitive_exports_only_when_safely_aggregated() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE invoice_registrants (
            prefecture TEXT,
            row_count INTEGER,
            license TEXT
        );
        INSERT INTO invoice_registrants VALUES
            ('Tokyo', 3, 'public_domain'),
            ('Tokyo', 2, 'public_domain'),
            ('Osaka', 7, 'public_domain');
        """
    )

    issues = gate.collect_hf_export_safety_issues(
        conn,
        [
            (
                "invoice_registrants",
                """
                SELECT prefecture, SUM(row_count) AS row_count, license
                  FROM invoice_registrants
              GROUP BY prefecture, license
                """,
            )
        ],
    )

    assert issues == []


def test_gate_blocks_small_sensitive_aggregate_cells() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE enforcement_cases (
            prefecture TEXT,
            row_count INTEGER,
            license TEXT
        );
        INSERT INTO enforcement_cases VALUES
            ('Tokyo', 4, 'gov_standard_v2.0'),
            ('Osaka', 5, 'gov_standard_v2.0');
        """
    )

    issues = gate.collect_hf_export_safety_issues(
        conn,
        [
            (
                "enforcement_cases",
                """
                SELECT prefecture, SUM(row_count) AS row_count, license
                  FROM enforcement_cases
              GROUP BY prefecture, license
                """,
            )
        ],
    )

    assert [issue.code for issue in issues] == ["small_aggregate_cell"]
    assert "below k=5" in issues[0].detail


def test_hf_dataset_export_runs_gate_before_writing_parquet(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "jpintel.db"
    out_dir = tmp_path / "hf"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE programs (unified_id TEXT, tier TEXT, excluded INTEGER);
        CREATE TABLE laws (unified_id TEXT);
        CREATE TABLE case_studies (case_id TEXT, company_name TEXT);
        CREATE TABLE enforcement_cases (case_id TEXT, recipient_name TEXT);
        INSERT INTO programs VALUES ('P-1', 'S', 0);
        INSERT INTO laws VALUES ('LAW-1');
        INSERT INTO case_studies VALUES ('CS-1', 'Example KK');
        INSERT INTO enforcement_cases VALUES ('EC-1', 'Example KK');
        """
    )
    conn.close()
    monkeypatch.setattr(
        sys,
        "argv",
        ["hf_dataset_export.py", "--db", str(db_path), "--output", str(out_dir)],
    )

    assert hf_dataset_export.main() == 1
    assert not out_dir.exists()
