"""O4 — programs_active_at_v2 endpoint + amendment_snapshot honesty caveat.

Two cases:

1. `GET /v1/am/programs/active_v2` returns rows from the
   `programs_active_at_v2` view, honoring the three temporal axes
   (effective + application_open_by + application_close_by) and the
   prefecture filter.

2. Every endpoint that surfaces amendment data carries the
   `_lifecycle_caveat` field declaring the snapshot is point-in-time
   only (eligibility_hash uniformity gotcha from CLAUDE.md).

The test builds a self-contained `autonomath.db` fixture (tiny — 3
program rows, 2 application rounds, 2 amendment snapshots, 1 law
article) so it does not contend with the 8.3 GB production DB which
parallel agents may be writing to.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixture — build a minimal autonomath.db with the schema needed for the
# view + the by_law / law_article surfaces.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def fake_autonomath_db() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="o4-autonomath-"))
    db_path = tmp / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE am_authority (
            canonical_id TEXT PRIMARY KEY,
            primary_name TEXT
        );
        CREATE TABLE am_entities (
            canonical_id        TEXT PRIMARY KEY,
            record_kind         TEXT NOT NULL,
            primary_name        TEXT NOT NULL,
            authority_canonical TEXT,
            confidence          REAL,
            source_url          TEXT,
            source_url_domain   TEXT,
            fetched_at          TEXT,
            raw_json            TEXT NOT NULL,
            created_at          TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
            canonical_status    TEXT NOT NULL DEFAULT 'active',
            citation_status     TEXT NOT NULL DEFAULT 'ok'
        );
        CREATE TABLE am_application_round (
            round_id                INTEGER PRIMARY KEY AUTOINCREMENT,
            program_entity_id       TEXT NOT NULL,
            round_label             TEXT NOT NULL,
            round_seq               INTEGER,
            application_open_date   TEXT,
            application_close_date  TEXT,
            announced_date          TEXT,
            disbursement_start_date TEXT,
            budget_yen              INTEGER,
            status                  TEXT,
            source_url              TEXT,
            source_fetched_at       TEXT
        );
        CREATE TABLE am_amendment_snapshot (
            snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id           TEXT NOT NULL,
            version_seq         INTEGER NOT NULL,
            observed_at         TEXT NOT NULL,
            effective_from      TEXT,
            effective_until     TEXT,
            amount_max_yen      INTEGER,
            subsidy_rate_max    REAL,
            target_set_json     TEXT,
            eligibility_hash    TEXT,
            summary_hash        TEXT,
            source_url          TEXT,
            source_fetched_at   TEXT,
            raw_snapshot_json   TEXT,
            UNIQUE (entity_id, version_seq)
        );
        CREATE TABLE am_law_article (
            article_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            law_canonical  TEXT,
            article_number TEXT,
            text           TEXT,
            last_amended   TEXT,
            effective_from TEXT
        );
        """
    )

    # Three programs in 東京都 / 大阪府 / 北海道 with progressively wider
    # application windows.
    raw_a = json.dumps({"prefecture": "東京都", "tier": "S"}, ensure_ascii=False)
    raw_b = json.dumps({"prefecture": "大阪府", "tier": "A"}, ensure_ascii=False)
    raw_c = json.dumps({"prefecture": "北海道", "tier": "B"}, ensure_ascii=False)
    conn.executemany(
        "INSERT INTO am_entities(canonical_id, record_kind, primary_name, "
        "authority_canonical, confidence, source_url, source_url_domain, "
        "fetched_at, raw_json) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("program:test:tokyo_a", "program", "テスト都心補助金", None,
             0.9, "https://example.go.jp/a", "example.go.jp",
             "2024-01-01T00:00:00Z", raw_a),
            ("program:test:osaka_b", "program", "テスト大阪補助金", None,
             0.8, "https://example.go.jp/b", "example.go.jp",
             "2024-06-01T00:00:00Z", raw_b),
            ("program:test:hokkai_c", "program", "テスト北海道補助金", None,
             0.7, "https://example.go.jp/c", "example.go.jp",
             "2024-09-01T00:00:00Z", raw_c),
        ],
    )

    # Open round for tokyo_a (2026 active), closed round for osaka_b (past).
    conn.executemany(
        "INSERT INTO am_application_round(program_entity_id, round_label, "
        "round_seq, application_open_date, application_close_date, status, "
        "source_url, source_fetched_at) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("program:test:tokyo_a", "1次", 1, "2026-01-01", "2026-12-31",
             "open", "https://example.go.jp/a", "2024-01-01T00:00:00Z"),
            ("program:test:osaka_b", "0次", 0, "2023-04-01", "2023-09-30",
             "closed", "https://example.go.jp/b", "2024-06-01T00:00:00Z"),
            # hokkai_c has no application round => LEFT JOIN keeps it.
        ],
    )

    # Two amendment snapshots: tokyo_a v1 + v2 with same eligibility_hash
    # (canonical CLAUDE.md gotcha).
    same_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    conn.executemany(
        "INSERT INTO am_amendment_snapshot(entity_id, version_seq, observed_at, "
        "effective_from, effective_until, eligibility_hash, summary_hash, "
        "source_url, source_fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("program:test:tokyo_a", 1, "2024-04-01T00:00:00Z",
             "2024-04-01", None, same_hash, same_hash,
             "https://example.go.jp/a", "2024-04-01T00:00:00Z"),
            ("program:test:tokyo_a", 2, "2025-04-01T00:00:00Z",
             "2025-04-01", None, same_hash, same_hash,
             "https://example.go.jp/a", "2025-04-01T00:00:00Z"),
        ],
    )

    # One law article so the law_article endpoint has something to return.
    conn.execute(
        "INSERT INTO am_law_article(law_canonical, article_number, text, "
        "last_amended, effective_from) VALUES (?,?,?,?,?)",
        ("law:test:租税特別措置法", "41の19",
         "テスト条文本文",
         "令5課消2-9",
         "2023-04-01"),
    )

    # Build the view (mirror of migration 070).
    conn.executescript(
        """
        DROP VIEW IF EXISTS programs_active_at_v2;
        CREATE VIEW programs_active_at_v2 AS
        SELECT
            p.canonical_id                                        AS unified_id,
            p.primary_name                                        AS primary_name,
            json_extract(p.raw_json, '$.tier')                    AS tier,
            json_extract(p.raw_json, '$.prefecture')              AS prefecture,
            p.authority_canonical                                 AS authority_canonical,
            ar.round_id                                           AS application_round_id,
            ar.round_label                                        AS application_round_label,
            ar.application_open_date                              AS application_open_date,
            ar.application_close_date                             AS application_close_date,
            ar.status                                             AS application_status,
            s.snapshot_id                                         AS amendment_snapshot_id,
            s.version_seq                                         AS amendment_version_seq,
            s.effective_from                                      AS effective_from,
            s.effective_until                                     AS effective_until,
            CASE
                WHEN s.effective_from IS NOT NULL THEN 'amendment_snapshot'
                WHEN p.fetched_at IS NOT NULL     THEN 'fetched_at_fallback'
                ELSE                                   'unknown'
            END                                                   AS effective_from_source,
            CASE
                WHEN COALESCE(s.effective_from, p.fetched_at, '0000-01-01') <= datetime('now')
                 AND (s.effective_until IS NULL OR datetime('now') < s.effective_until)
                THEN 1 ELSE 0
            END                                                   AS is_effective_now,
            CASE
                WHEN ar.application_open_date IS NOT NULL
                 AND ar.application_open_date <= datetime('now')
                 AND (ar.application_close_date IS NULL
                      OR datetime('now') < ar.application_close_date)
                THEN 1 ELSE 0
            END                                                   AS is_application_open_now
        FROM am_entities p
        LEFT JOIN am_application_round ar
            ON ar.program_entity_id = p.canonical_id
        LEFT JOIN am_amendment_snapshot s
            ON s.entity_id    = p.canonical_id
           AND s.version_seq  = (
                SELECT MAX(version_seq)
                  FROM am_amendment_snapshot
                 WHERE entity_id = p.canonical_id
               )
        WHERE p.record_kind = 'program'
          AND p.canonical_status = 'active';
        """
    )
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# Test 1 — programs_active_at_v2 endpoint returns rows that match the
#          three-axis filter, with the lifecycle caveat attached.
# ---------------------------------------------------------------------------
def test_programs_active_v2_three_axis(
    fake_autonomath_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Point the autonomath connector at the fixture before importing
    # anything that caches the path. Then purge cached jpintel_mcp
    # imports so connect_autonomath() re-resolves.
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fake_autonomath_db))
    # graph.sqlite isn't queried by this endpoint but the helper expects
    # it to exist for unrelated paths; create a placeholder.
    graph_path = fake_autonomath_db.parent / "graph.sqlite"
    if not graph_path.exists():
        sqlite3.connect(graph_path).close()
    monkeypatch.setenv("AUTONOMATH_GRAPH_DB_PATH", str(graph_path))
    monkeypatch.setenv("AUTONOMATH_ENABLED", "1")

    # Force module reload so `AUTONOMATH_DB_PATH` resolves to fixture.
    for mod in list(sys.modules):
        if mod.startswith("jpintel_mcp.mcp.autonomath_tools.db"):
            del sys.modules[mod]

    from fastapi.testclient import TestClient

    from jpintel_mcp.api.main import create_app

    client = TestClient(create_app())

    # Filter: as_of=2026-06-01 (effective for tokyo_a + osaka_b + hokkai_c
    # via fetched_at_fallback), application_close_by=2026-09-30 → only
    # tokyo_a's open round (2026-12-31 close >= 2026-09-30). osaka_b's
    # close (2023-09-30) and hokkai_c's NULL close are filtered out.
    resp = client.get(
        "/v1/am/programs/active_v2",
        params={
            "as_of": "2026-06-01",
            "application_close_by": "2026-09-30",
            "limit": 10,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Lifecycle caveat must be present.
    assert "_lifecycle_caveat" in body, body
    assert "point-in-time" in body["_lifecycle_caveat"]

    # Exactly one program (tokyo_a) survives the close-by filter.
    rows = body["results"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["unified_id"] == "program:test:tokyo_a"
    assert row["application_close_date"] == "2026-12-31"
    assert row["effective_from"] == "2025-04-01"  # latest version_seq
    assert row["amendment_version_seq"] == 2
    assert row["effective_from_source"] == "amendment_snapshot"

    # Prefecture filter further narrows.
    resp2 = client.get(
        "/v1/am/programs/active_v2",
        params={"as_of": "2026-06-01", "prefecture": "大阪府"},
    )
    assert resp2.status_code == 200, resp2.text
    body2 = resp2.json()
    assert all(r["prefecture"] == "大阪府" for r in body2["results"])
    assert len(body2["results"]) == 1
    assert body2["results"][0]["unified_id"] == "program:test:osaka_b"


# ---------------------------------------------------------------------------
# Test 2 — by_law and law_article responses both carry the lifecycle
#          caveat (am_amendment_snapshot honesty surface).
# ---------------------------------------------------------------------------
def test_amendment_lifecycle_caveat_injected() -> None:
    """The caveat helper is idempotent and surfaces on both amendment-touching paths."""
    from jpintel_mcp.api.autonomath import (
        _LIFECYCLE_CAVEAT_TEXT,
        _attach_lifecycle_caveat,
    )

    # Idempotent: empty dict gets caveat.
    body: dict = {}
    out = _attach_lifecycle_caveat(body)
    assert out["_lifecycle_caveat"] == _LIFECYCLE_CAVEAT_TEXT

    # Idempotent: pre-set caveat is preserved.
    body2 = {"_lifecycle_caveat": "custom override"}
    out2 = _attach_lifecycle_caveat(body2)
    assert out2["_lifecycle_caveat"] == "custom override"

    # Non-dict bodies (lists, strings) pass through unchanged.
    assert _attach_lifecycle_caveat([1, 2, 3]) == [1, 2, 3]
    assert _attach_lifecycle_caveat("scalar") == "scalar"

    # The helper text mentions the eligibility_hash gotcha so downstream
    # LLMs can reason about the constraint.
    assert "eligibility_hash" in _LIFECYCLE_CAVEAT_TEXT
    assert "point-in-time" in _LIFECYCLE_CAVEAT_TEXT

    # Assert the helper is wired into both endpoints by inspecting the
    # source — cheap-but-sufficient guard against future regressions
    # where someone removes the call site.
    src_path = Path(__file__).resolve().parents[1] / (
        "src/jpintel_mcp/api/autonomath.py"
    )
    src = src_path.read_text(encoding="utf-8")
    # search_by_law endpoint wires the caveat after tools.search_by_law.
    assert "_attach_lifecycle_caveat(result)" in src
    # Both endpoints share the same call shape; count must be >= 3 (active_v2,
    # by_law, law_article).
    assert src.count("_attach_lifecycle_caveat") >= 4  # 1 helper + >=3 callsites
