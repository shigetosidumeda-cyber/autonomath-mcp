from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

_ETL = Path(__file__).resolve().parent.parent / "scripts" / "etl"
if str(_ETL) not in sys.path:
    sys.path.insert(0, str(_ETL))

import backfill_am_source_content_hash as backfill  # noqa: E402


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_source (
            id INTEGER PRIMARY KEY,
            source_url TEXT NOT NULL UNIQUE,
            content_hash TEXT
        );
        """
    )
    return conn


def test_compute_source_content_hash_matches_corpus_convention() -> None:
    url = "https://www.example.go.jp/source.html"
    expected = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

    assert backfill.compute_source_content_hash(url) == expected
    assert len(expected) == 16


def test_backfill_content_hashes_updates_only_null_rows() -> None:
    conn = _build_db()
    existing_hash = "abc123abc123abcd"
    conn.executemany(
        "INSERT INTO am_source(id, source_url, content_hash) VALUES (?, ?, ?)",
        [
            (1, "https://www.example.go.jp/a.html", None),
            (2, "https://www.example.go.jp/b.html", existing_hash),
        ],
    )
    conn.commit()

    result = backfill.backfill_content_hashes(conn, apply=True)

    assert result["am_source_content_hash_null_before"] == 1
    assert result["updated_rows"] == 1
    assert result["am_source_content_hash_null_after"] == 0
    assert (
        conn.execute("SELECT content_hash FROM am_source WHERE id = 2").fetchone()[0]
        == existing_hash
    )


def test_backfill_content_hashes_is_idempotent() -> None:
    conn = _build_db()
    conn.execute(
        "INSERT INTO am_source(id, source_url, content_hash) VALUES (?, ?, ?)",
        (1, "https://www.example.go.jp/a.html", None),
    )
    conn.commit()

    first = backfill.backfill_content_hashes(conn, apply=True)
    second = backfill.backfill_content_hashes(conn, apply=True)

    assert first["updated_rows"] == 1
    assert second["candidate_updates"] == 0
    assert second["updated_rows"] == 0
    assert second["am_source_content_hash_null_after"] == 0


def test_backfill_blocks_digest_collisions() -> None:
    conn = _build_db()
    url = "https://www.example.go.jp/a.html"
    digest = backfill.compute_source_content_hash(url)
    conn.executemany(
        "INSERT INTO am_source(id, source_url, content_hash) VALUES (?, ?, ?)",
        [
            (1, url, None),
            (2, "https://www.example.go.jp/b.html", digest),
        ],
    )
    conn.commit()

    result = backfill.backfill_content_hashes(conn, apply=True)

    assert result["status"] == "collision_blocked"
    assert conn.execute("SELECT content_hash FROM am_source WHERE id = 1").fetchone()[0] is None
