from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
_ETL = _SCRIPTS / "etl"
for _path in (_SCRIPTS, _ETL):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import hf_estat_statistics_export as export  # noqa: E402
from hf_export_safety_gate import HfSafetyIssue  # noqa: E402


def _create_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE am_entities (
            canonical_id TEXT PRIMARY KEY,
            record_kind TEXT NOT NULL,
            source_topic TEXT,
            source_record_index INTEGER,
            primary_name TEXT NOT NULL,
            source_url TEXT,
            source_url_domain TEXT,
            fetched_at TEXT,
            confidence REAL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE am_entity_facts (
            id INTEGER PRIMARY KEY,
            entity_id TEXT NOT NULL,
            field_name TEXT NOT NULL,
            field_value_text TEXT,
            field_value_json TEXT,
            field_value_numeric REAL,
            field_kind TEXT NOT NULL,
            unit TEXT,
            source_url TEXT,
            source_id INTEGER,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'primary',
            domain TEXT,
            first_seen TEXT,
            last_verified TEXT,
            license TEXT
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO am_source (
            id, source_url, source_type, domain, first_seen, last_verified, license
        ) VALUES (?, ?, 'primary', 'e-stat.go.jp', '2026-05-01T00:00:00Z', NULL, ?)
        """,
        [
            (1, "https://www.e-stat.go.jp/safe", "gov_standard_v2.0"),
            (2, "https://www.e-stat.go.jp/unknown", "unknown"),
            (3, "https://www.e-stat.go.jp/proprietary", "proprietary"),
            (4, "", "gov_standard_v2.0"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO am_entities (
            canonical_id, record_kind, source_topic, source_record_index,
            primary_name, source_url, source_url_domain, fetched_at, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "stat:one",
                "statistic",
                export.ESTAT_SOURCE_TOPIC,
                1,
                "e-Stat row one",
                "https://www.e-stat.go.jp/safe",
                "e-stat.go.jp",
                "2026-05-01T00:00:00Z",
                0.95,
            ),
            (
                "stat:other",
                "statistic",
                "other_topic",
                2,
                "Other statistic",
                "https://www.e-stat.go.jp/safe",
                "e-stat.go.jp",
                "2026-05-01T00:00:00Z",
                0.95,
            ),
        ],
    )
    conn.executemany(
        """
        INSERT INTO am_entity_facts (
            id, entity_id, field_name, field_value_text, field_value_json,
            field_value_numeric, field_kind, unit, source_url, source_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                "stat:one",
                "establishment_count",
                None,
                None,
                42,
                "number",
                "count",
                None,
                1,
            ),
            (
                2,
                "stat:one",
                "employee_count",
                None,
                None,
                8,
                "number",
                "persons",
                "https://www.e-stat.go.jp/safe",
                None,
            ),
            (3, "stat:one", "unknown_license", "x", None, None, "text", None, None, 2),
            (4, "stat:one", "proprietary_license", "x", None, None, "text", None, None, 3),
            (5, "stat:one", "blank_source_url", "x", None, None, "text", None, None, 4),
            (
                6,
                "stat:other",
                "ignored_other_topic",
                None,
                None,
                99,
                "number",
                "count",
                None,
                1,
            ),
        ],
    )
    conn.commit()
    conn.close()


def _create_full_ready_db(path: Path) -> None:
    _create_db(path)
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM am_entity_facts WHERE id IN (2, 3, 4, 5)")
    conn.commit()
    conn.close()


def _patch_parquet(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    frames: list[object] = []

    def fake_to_parquet(self, path, *args, **kwargs) -> None:
        frames.append(self.copy())
        Path(path).write_bytes(b"fake parquet")

    monkeypatch.setattr(export.pd.DataFrame, "to_parquet", fake_to_parquet)
    return frames


def test_preview_exports_only_source_complete_safe_rows_and_manifest_flags_b9(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath.db"
    out_dir = tmp_path / "hf-statistics-estat"
    _create_db(db_path)
    frames = _patch_parquet(monkeypatch)

    result = export.run_export(db_path, out_dir, preview=True)

    assert frames
    frame = frames[0]
    assert frame["fact_id"].astype(int).tolist() == [1]
    assert frame["field_name"].tolist() == ["establishment_count"]
    assert frame["source_url"].tolist() == ["https://www.e-stat.go.jp/safe"]
    assert set(frame["license"]) == {"gov_standard_v2.0"}

    manifest = result.manifest
    assert manifest["preview_only"] is True
    assert manifest["publish_performed"] is False
    assert manifest["f3_full_publish_ready"] is False
    assert manifest["b9_provenance_complete"] is False
    assert (
        "B9 e-Stat fact provenance is not 100% complete"
        in (manifest["full_f3_gate_incomplete_reason"])
    )
    assert manifest["total_exported_rows"] == 1
    assert manifest["license_values"] == ["gov_standard_v2.0"]
    assert manifest["license_counts"] == {"gov_standard_v2.0": 1}
    assert manifest["all_estat_fact_license_counts"] == {
        "<MISSING>": 1,
        "gov_standard_v2.0": 2,
        "proprietary": 1,
        "unknown": 1,
    }

    completeness = manifest["source_completeness"]
    assert completeness["total_estat_fact_rows"] == 5
    assert completeness["facts_missing_source_id"] == 1
    assert completeness["source_complete_safe_fact_rows"] == 1
    assert completeness["exported_rows"] == 1

    saved_manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert saved_manifest["total_exported_rows"] == 1
    assert (out_dir / "README.md").exists()


def test_default_full_mode_fails_closed_when_b9_is_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath.db"
    out_dir = tmp_path / "hf-statistics-estat"
    _create_db(db_path)
    _patch_parquet(monkeypatch)

    with pytest.raises(export.F3ReadinessError) as excinfo:
        export.run_export(db_path, out_dir)

    assert "B9 e-Stat fact provenance is not 100% complete" in str(excinfo.value)
    assert not out_dir.exists()


def test_full_mode_writes_when_every_estat_fact_is_source_complete_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath.db"
    out_dir = tmp_path / "hf-statistics-estat"
    _create_full_ready_db(db_path)
    frames = _patch_parquet(monkeypatch)

    result = export.run_export(db_path, out_dir)

    assert frames[0]["fact_id"].astype(int).tolist() == [1]
    manifest = result.manifest
    assert manifest["mode"] == "full"
    assert manifest["preview_only"] is False
    assert manifest["f3_full_publish_ready"] is True
    assert manifest["b9_provenance_complete"] is True
    assert manifest["full_f3_gate_incomplete_reason"] is None
    assert manifest["source_completeness"]["total_estat_fact_rows"] == 1
    assert manifest["source_completeness"]["source_complete_safe_fact_rows"] == 1


def test_safety_gate_runs_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "autonomath.db"
    out_dir = tmp_path / "hf-statistics-estat"
    _create_full_ready_db(db_path)
    _patch_parquet(monkeypatch)
    calls = []

    def fake_gate(conn, exports):
        calls.append((conn, list(exports)))
        raise export.HfExportSafetyError(
            [HfSafetyIssue(export.EXPORT_TABLE, "blocked_license", "test failure")]
        )

    monkeypatch.setattr(export, "assert_hf_export_safe", fake_gate)

    with pytest.raises(export.HfExportSafetyError):
        export.run_export(db_path, out_dir)

    assert calls
    assert calls[0][1] == export.EXPORTS
    assert not out_dir.exists()


def test_main_returns_one_for_incomplete_full_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "autonomath.db"
    out_dir = tmp_path / "hf-statistics-estat"
    _create_db(db_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hf_estat_statistics_export.py",
            "--db",
            str(db_path),
            "--output",
            str(out_dir),
        ],
    )

    assert export.main() == 1
    assert "B9 e-Stat fact provenance is not 100% complete" in capsys.readouterr().err
    assert not out_dir.exists()
