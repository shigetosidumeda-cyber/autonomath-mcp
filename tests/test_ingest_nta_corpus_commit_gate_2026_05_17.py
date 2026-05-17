from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ingest" / "ingest_nta_corpus.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ingest_nta_corpus_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed_shitsugi_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE nta_shitsugi (
                slug TEXT NOT NULL,
                category TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                related_law TEXT,
                source_url TEXT NOT NULL UNIQUE,
                license TEXT NOT NULL,
                ingested_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _patch_one_shitsugi_page(monkeypatch: pytest.MonkeyPatch, mod: ModuleType) -> str:
    url = "https://www.nta.go.jp/law/shitsugi/hojin/01/01.htm"
    html = """
    <html><body><div id="contents">
      <h1>法人税の質疑応答</h1>
      【照会要旨】これはテスト用の照会要旨です。
      【回答要旨】これはテスト用の回答要旨です。
      【関係法令通達】法人税法テスト条
    </div></body></html>
    """
    monkeypatch.setattr(mod, "SHITSUGI_CATEGORIES", ["hojin"])
    monkeypatch.setattr(mod, "DELAY_SEC", 0)
    monkeypatch.setattr(mod, "discover_shitsugi_pages", lambda category: [url])
    monkeypatch.setattr(mod, "fetch", lambda fetched_url: html)
    return url


def test_shitsugi_dry_run_does_not_write_db_or_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_module()
    _patch_one_shitsugi_page(monkeypatch, mod)
    db = tmp_path / "autonomath.db"
    cursor_dir = tmp_path / "cursors"
    _seed_shitsugi_db(db)

    conn = mod.connect(db, readonly=True)
    try:
        summary = mod.ingest_shitsugi(conn, max_seconds=60, dry_run=True, cursor_dir=cursor_dir)
    finally:
        conn.close()

    assert summary == {"pages_seen": 1, "pages_inserted": 1, "categories_done": 1}
    verify = sqlite3.connect(db)
    try:
        assert verify.execute("SELECT COUNT(*) FROM nta_shitsugi").fetchone()[0] == 0
    finally:
        verify.close()
    assert not cursor_dir.exists()


def test_shitsugi_commit_writes_db_and_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _load_module()
    url = _patch_one_shitsugi_page(monkeypatch, mod)
    db = tmp_path / "autonomath.db"
    cursor_dir = tmp_path / "cursors"
    _seed_shitsugi_db(db)

    conn = mod.connect(db, readonly=False)
    try:
        summary = mod.ingest_shitsugi(conn, max_seconds=60, dry_run=False, cursor_dir=cursor_dir)
    finally:
        conn.close()

    assert summary == {"pages_seen": 1, "pages_inserted": 1, "categories_done": 1}
    verify = sqlite3.connect(db)
    try:
        row = verify.execute("SELECT slug, category, source_url FROM nta_shitsugi").fetchone()
    finally:
        verify.close()
    assert row == ("hojin-01-01", "hojin", url)
    assert (cursor_dir / "_nta_shitsugi_cursor.txt").read_text(encoding="utf-8") == (
        "partial:done:hojin"
    )


def test_readonly_connect_rejects_writes(tmp_path: Path) -> None:
    mod = _load_module()
    db = tmp_path / "autonomath.db"
    _seed_shitsugi_db(db)

    conn = mod.connect(db, readonly=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(
                """
                INSERT INTO nta_shitsugi (
                    slug, category, question, answer, source_url, license, ingested_at
                ) VALUES ('x', 'hojin', 'q', 'a', 'https://www.nta.go.jp/x', 'gov_standard', 'now')
                """
            )
    finally:
        conn.close()
