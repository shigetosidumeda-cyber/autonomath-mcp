from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import hf_laws_jp_export as export  # noqa: E402
from hf_export_safety_gate import HfSafetyIssue  # noqa: E402


def _create_laws_db(path: Path) -> None:
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
            unified_id, law_number, law_title, law_type, article_count,
            source_url, confidence, fetched_at, updated_at
        ) VALUES
            (
                'LAW-0000000001',
                '令和元年法律第一号',
                'テスト法',
                'act',
                12,
                'https://laws.e-gov.go.jp/law/001',
                0.95,
                '2026-05-01T00:00:00Z',
                '2026-05-01T00:00:00Z'
            ),
            (
                'LAW-0000000002',
                '令和元年法律第二号',
                '別のテスト法',
                'act',
                NULL,
                'https://laws.e-gov.go.jp/law/002',
                0.9,
                '2026-05-01T00:00:00Z',
                '2026-05-01T00:00:00Z'
            );
        """
    )
    conn.close()


def test_export_laws_jp_writes_laws_only_with_explicit_cc_by_license(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "jpintel.db"
    out_dir = tmp_path / "hf-laws-jp"
    _create_laws_db(db_path)
    parquet_frames = []

    def fake_to_parquet(self, path, *args, **kwargs) -> None:
        parquet_frames.append(self.copy())
        Path(path).write_bytes(b"fake parquet")

    monkeypatch.setattr(export.pd.DataFrame, "to_parquet", fake_to_parquet)

    rows, parquet_bytes = export.run_export(db_path, out_dir)

    assert rows == 2
    assert parquet_bytes == len(b"fake parquet")
    assert sorted(path.name for path in out_dir.iterdir()) == [
        "README.md",
        "laws.parquet",
        "manifest.json",
    ]

    frame = parquet_frames[0]
    assert list(frame["unified_id"]) == ["LAW-0000000001", "LAW-0000000002"]
    assert set(frame["license"]) == {"cc_by_4.0"}
    assert "license" in frame.columns

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset"] == "laws-jp"
    assert manifest["exports"] == [
        {
            "table": "laws",
            "file": "laws.parquet",
            "rows": 2,
            "bytes": len(b"fake parquet"),
            "license": "cc_by_4.0",
            "safety_gate": "passed",
        }
    ]
    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    assert "license: cc-by-4.0" in readme
    assert "Rows: 2" in readme


def test_export_runs_safety_gate_before_writing(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "jpintel.db"
    out_dir = tmp_path / "hf-laws-jp"
    _create_laws_db(db_path)
    calls = []

    def fake_gate(conn, exports):
        calls.append((conn, list(exports)))
        raise export.HfExportSafetyError(
            [
                HfSafetyIssue(
                    "laws",
                    "blocked_license",
                    "test failure",
                )
            ]
        )

    monkeypatch.setattr(export, "assert_hf_export_safe", fake_gate)

    try:
        export.run_export(db_path, out_dir)
    except export.HfExportSafetyError:
        pass
    else:
        raise AssertionError("expected safety gate failure")

    assert calls
    assert calls[0][1] == [("laws", export.LAWS_QUERY)]
    assert not out_dir.exists()


def test_main_returns_one_when_db_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(
        sys, "argv", ["hf_laws_jp_export.py", "--db", str(missing), "--output", str(tmp_path)]
    )

    assert export.main() == 1
    assert "DB not found" in capsys.readouterr().err
