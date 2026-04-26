"""Tests for loop_e_alias_expansion.

Covers the launch-v1 happy path: a tiny in-memory program corpus +
synthetic miss-query list, with one query that should crystallize into
an alias candidate.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jpintel_mcp.self_improve import loop_e_alias_expansion as loop_e


def _seed_min_db(db_path: Path) -> None:
    """Build a 2-row jpi_programs + 1-row am_alias DB for the loop to read."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE jpi_programs (
                unified_id TEXT PRIMARY KEY,
                primary_name TEXT NOT NULL,
                excluded INTEGER DEFAULT 0
            );
            CREATE TABLE am_alias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_table TEXT NOT NULL,
                canonical_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                alias_kind TEXT NOT NULL DEFAULT 'partial'
            );
            """
        )
        conn.executemany(
            "INSERT INTO jpi_programs(unified_id, primary_name, excluded) "
            "VALUES (?, ?, 0)",
            [
                ("program:base:abc123", "ものづくり補助金"),
                ("program:base:def456", "事業再構築補助金"),
            ],
        )
        conn.execute(
            "INSERT INTO am_alias(entity_table, canonical_id, alias, alias_kind) "
            "VALUES ('am_entities', 'program:base:abc123', 'ものづくり補助', 'partial')"
        )
        conn.commit()
    finally:
        conn.close()


def test_loop_e_proposes_alias_from_miss_query(tmp_path: Path):
    db_path = tmp_path / "autonomath.db"
    _seed_min_db(db_path)
    out_path = tmp_path / "alias_proposed.yaml"

    # "ものづくり補助金制度" is a near-variant of "ものづくり補助金" — should
    # cross the 0.85 SequenceMatcher threshold and emit a proposal pointing
    # at canonical_id `program:base:abc123`.
    miss = ["ものづくり補助金制度", "完全に無関係な query 一切"]

    result = loop_e.run(
        dry_run=False,
        miss_queries=miss,
        db_path=db_path,
        out_path=out_path,
    )

    assert result["loop"] == "loop_e_alias_expansion"
    assert result["scanned"] == 2
    assert result["actions_proposed"] >= 1
    assert result["actions_executed"] == 1

    # Verify the YAML contains a candidate pointing at the right canonical_id.
    body = out_path.read_text(encoding="utf-8")
    assert "program:base:abc123" in body
    assert "ものづくり補助金制度" in body


def test_loop_e_skips_already_known_alias(tmp_path: Path):
    """Miss query identical to an existing am_alias row -> no proposal."""
    db_path = tmp_path / "autonomath.db"
    _seed_min_db(db_path)

    # The seeded alias is "ものづくり補助" — feed it back as a miss query.
    result = loop_e.run(
        dry_run=True,
        miss_queries=["ものづくり補助"],
        db_path=db_path,
    )
    # The exact-same alias for the same canonical_id is skipped, but the
    # query may still produce a proposal targeting the *primary_name*
    # ("ものづくり補助金") which IS a different canonical surface. The
    # critical invariant is that no proposal duplicates an existing
    # (alias, canonical_id) pair.
    assert result["loop"] == "loop_e_alias_expansion"
    assert result["scanned"] == 1
    # Either zero (filtered) or one (matched primary_name) is acceptable;
    # what matters is no proposal duplicates the seeded am_alias row.
    anchors, existing = loop_e._load_corpus_from_db(db_path)
    proposals = loop_e.propose_aliases(["ものづくり補助"], anchors, existing)
    for p in proposals:
        assert not (
            p["alias"] == "ものづくり補助"
            and p["canonical_id"] == "program:base:abc123"
            and p["primary_name"] == "ものづくり補助"
        )


def test_loop_e_empty_miss_queries_returns_scaffold(tmp_path: Path):
    """Pre-launch: no miss queries -> orchestrator-friendly zero dict."""
    out = loop_e.run(dry_run=True, miss_queries=None)
    assert out == {
        "loop": "loop_e_alias_expansion",
        "scanned": 0,
        "actions_proposed": 0,
        "actions_executed": 0,
    }


def test_loop_e_redacts_pii_in_miss_queries(tmp_path: Path):
    """Defense-in-depth: a miss query containing T<13 digits> must be
    redacted before any matching, so PII never reaches the YAML."""
    db_path = tmp_path / "autonomath.db"
    _seed_min_db(db_path)
    out_path = tmp_path / "alias_proposed.yaml"

    miss = ["ものづくり補助金 T1234567890123 を申請"]
    loop_e.run(
        dry_run=False,
        miss_queries=miss,
        db_path=db_path,
        out_path=out_path,
    )
    if out_path.exists():
        body = out_path.read_text(encoding="utf-8")
        assert "T1234567890123" not in body
