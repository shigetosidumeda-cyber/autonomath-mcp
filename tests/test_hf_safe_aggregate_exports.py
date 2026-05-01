from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import hf_safe_aggregate_exports as hf_aggregates  # noqa: E402


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE invoice_registrants (
            invoice_registration_number TEXT PRIMARY KEY,
            normalized_name TEXT NOT NULL,
            prefecture TEXT,
            registered_date TEXT NOT NULL,
            registrant_kind TEXT NOT NULL,
            source_url TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE enforcement_cases (
            case_id TEXT PRIMARY KEY,
            recipient_name TEXT,
            ministry TEXT,
            source_url TEXT
        );
        """
    )
    conn.close()


def _insert_invoice_rows(path: Path, prefecture: str, count: int) -> None:
    conn = sqlite3.connect(path)
    rows = [
        (
            f"T{idx:013d}",
            f"Registrant {idx}",
            prefecture,
            "2026-01-01",
            "corporation",
            "https://www.invoice-kohyo.nta.go.jp/download/",
            "2026-01-02T00:00:00Z",
            "2026-01-02T00:00:00Z",
        )
        for idx in range(1, count + 1)
    ]
    conn.executemany(
        """
        INSERT INTO invoice_registrants (
            invoice_registration_number, normalized_name, prefecture,
            registered_date, registrant_kind, source_url, fetched_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def _insert_enforcement_rows(path: Path, ministry: str, count: int) -> None:
    conn = sqlite3.connect(path)
    rows = [
        (
            f"EC-{idx}",
            f"Recipient {idx}",
            ministry,
            "https://example.go.jp/enforcement",
        )
        for idx in range(1, count + 1)
    ]
    conn.executemany(
        """
        INSERT INTO enforcement_cases (
            case_id, recipient_name, ministry, source_url
        ) VALUES (?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()


def test_safe_aggregate_export_blocks_cells_below_k(tmp_path: Path) -> None:
    db_path = tmp_path / "jpintel.db"
    out_dir = tmp_path / "hf"
    _create_db(db_path)
    _insert_invoice_rows(db_path, "東京都", 4)
    _insert_enforcement_rows(db_path, "経済産業省", 4)

    manifest = hf_aggregates.export_safe_aggregates(db_path, out_dir)

    assert [dataset["rows"] for dataset in manifest["datasets"]] == [0, 0]
    invoice = pd.read_parquet(out_dir / "invoice_registrants_by_prefecture.parquet")
    enforcement = pd.read_parquet(out_dir / "enforcement_cases_by_ministry.parquet")
    assert invoice.empty
    assert enforcement.empty


def test_safe_aggregate_export_writes_k_anonymous_parquet_and_manifest(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "jpintel.db"
    out_dir = tmp_path / "hf"
    _create_db(db_path)
    _insert_invoice_rows(db_path, "東京都", 5)
    _insert_enforcement_rows(db_path, "経済産業省", 6)

    manifest = hf_aggregates.export_safe_aggregates(db_path, out_dir)

    assert (out_dir / "manifest.json").exists()
    assert {dataset["license"] for dataset in manifest["datasets"]} == {
        "gov_standard_v2.0",
        "pdl_v1.0",
    }
    assert all(dataset["min_k"] == 5 for dataset in manifest["datasets"])
    assert all(dataset["min_exported_cell_count"] >= 5 for dataset in manifest["datasets"])
    assert manifest["aggregate_only"] is True
    assert manifest["row_level_sensitive_data_exported"] is False

    invoice = pd.read_parquet(out_dir / "invoice_registrants_by_prefecture.parquet")
    enforcement = pd.read_parquet(out_dir / "enforcement_cases_by_ministry.parquet")

    assert invoice.to_dict(orient="records") == [
        {"prefecture": "東京都", "registrant_count": 5, "license": "pdl_v1.0"}
    ]
    assert enforcement.to_dict(orient="records") == [
        {"ministry": "経済産業省", "enforcement_count": 6, "license": "gov_standard_v2.0"}
    ]
    assert "invoice_registration_number" not in invoice.columns
    assert "recipient_name" not in enforcement.columns
