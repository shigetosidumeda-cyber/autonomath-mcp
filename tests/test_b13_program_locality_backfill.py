from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_program_locality_metadata as backfill  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE programs (
            unified_id TEXT PRIMARY KEY,
            primary_name TEXT NOT NULL,
            authority_name TEXT,
            prefecture TEXT,
            municipality TEXT,
            official_url TEXT,
            source_url TEXT
        );
        """
    )
    return conn


def _write_json(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_extract_prefecture_from_url_pref_host() -> None:
    assert backfill.extract_prefecture_from_url(
        "https://www.pref.aichi.jp/soshiki/"
    ) == "愛知県"
    assert backfill.extract_prefecture_from_url(
        "https://www.city.akiruno.tokyo.jp/0001.html"
    ) == "東京都"


def test_backfill_uses_existing_municipality_without_overwrite(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            "UNI-1",
            "南相馬市中小企業賃上げ緊急一時支援金",
            "",
            None,
            "南相馬市",
            "",
            "",
        ),
    )
    muni = _write_json(tmp_path / "muni.json", {"福島県": ["南相馬市"]})
    overrides = _write_json(tmp_path / "overrides.json", {})

    result = backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )

    assert result["updated_rows"] == 1
    row = conn.execute("SELECT prefecture, municipality FROM programs").fetchone()
    assert row["prefecture"] == "福島県"
    assert row["municipality"] == "南相馬市"


def test_backfill_can_extract_municipality_from_primary_name(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("UNI-1", "朝倉市新規就農者営農支援補助金", "", None, None, "", ""),
    )
    muni = _write_json(tmp_path / "muni.json", {"福岡県": ["朝倉市"]})
    overrides = _write_json(tmp_path / "overrides.json", {})

    backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )

    row = conn.execute("SELECT prefecture, municipality FROM programs").fetchone()
    assert row["prefecture"] == "福岡県"
    assert row["municipality"] == "朝倉市"


def test_authority_level_override_nationwide_is_skipped(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("UNI-1", "全国向け制度", "", None, None, "", ""),
    )
    muni = _write_json(tmp_path / "muni.json", {})
    overrides = _write_json(
        tmp_path / "overrides.json",
        {
            "UNI-1": {
                "confidence": 1.0,
                "prefecture": "全国",
                "source": "authority_level",
                "evidence": "authority_level=national",
            }
        },
    )

    result = backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )

    assert result["updated_rows"] == 0
    assert conn.execute("SELECT prefecture FROM programs").fetchone()[0] is None


def test_non_authority_override_is_allowed(tmp_path: Path) -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO programs VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("UNI-1", "地域制度", "", None, None, "", ""),
    )
    muni = _write_json(tmp_path / "muni.json", {})
    overrides = _write_json(
        tmp_path / "overrides.json",
        {
            "UNI-1": {
                "confidence": 0.95,
                "prefecture": "佐賀県",
                "source": "contact_address",
                "evidence": "contacts.address=佐賀県武雄市",
            }
        },
    )

    backfill.backfill_program_locality(
        conn,
        apply=True,
        muni_to_pref_path=muni,
        overrides_path=overrides,
    )

    assert conn.execute("SELECT prefecture FROM programs").fetchone()[0] == "佐賀県"
