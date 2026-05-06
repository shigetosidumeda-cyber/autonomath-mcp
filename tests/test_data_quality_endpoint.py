"""Tests for ``/v1/stats/data_quality`` snapshot fast-path (W14-4 fix).

The handler used to walk ``am_uncertainty_view`` + 97k+ ``am_source``
rows on every request, which exceeded Fly's 60 s grace window on the
9.4 GB autonomath.db production volume — same failure shape as the
2026-05-03 SQLite quick_check incident captured in memory
``feedback_no_quick_check_on_huge_sqlite``.

The fix moves aggregation to a daily cron
(``scripts/cron/precompute_data_quality.py``) that parks one row in
``am_data_quality_snapshot`` (migration ``wave24_145``); the handler
now serves that single row in ~1 ms.

Coverage:
    1. snapshot fast-path returns the parked row + responds in <1 s
    2. cron compute → persist → handler read round-trip is consistent
    3. snapshot table missing → handler still works (legacy fallback)
    4. snapshot table empty   → handler still works (legacy fallback)
    5. precompute cron is idempotent (UPSERT on snapshot_at)
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers — minimal autonomath fixture (faithful to migrations 049 + 069).
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parent.parent

_AM_SCHEMA_SQL = """
CREATE TABLE am_source (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url    TEXT NOT NULL UNIQUE,
    source_type   TEXT NOT NULL DEFAULT 'primary',
    domain        TEXT,
    is_pdf        INTEGER NOT NULL DEFAULT 0,
    content_hash  TEXT,
    first_seen    TEXT NOT NULL DEFAULT (datetime('now')),
    last_verified TEXT,
    promoted_at   TEXT NOT NULL DEFAULT (datetime('now')),
    canonical_status TEXT NOT NULL DEFAULT 'active',
    license       TEXT
);

CREATE TABLE am_entity_facts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id           TEXT NOT NULL,
    field_name          TEXT NOT NULL,
    field_value_text    TEXT,
    field_value_json    TEXT,
    field_value_numeric REAL,
    field_kind          TEXT NOT NULL,
    unit                TEXT,
    source_url          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    source_id           INTEGER REFERENCES am_source(id)
);
"""

_MIGRATION_069 = _REPO / "scripts" / "migrations" / "069_uncertainty_view.sql"
_MIGRATION_145 = _REPO / "scripts" / "migrations" / "wave24_145_am_data_quality_snapshot.sql"


def _build_am_db(path: Path) -> None:
    """Create on-disk autonomath.db with schema + migration 069 + 145."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_AM_SCHEMA_SQL)
        # Three sources spanning gov/pdl/null license + freshness span.
        conn.executescript(
            """
            INSERT INTO am_source (source_url, license, first_seen) VALUES
                ('https://chusho.meti.go.jp/x.pdf', 'gov_standard_v2.0',
                 datetime('now', '-30 days')),
                ('https://nta.go.jp/y.json',        'pdl_v1.0',
                 datetime('now', '-365 days')),
                ('https://example.invalid/z',       NULL,
                 datetime('now', '-3 days'));
            """
        )
        conn.executescript(
            """
            INSERT INTO am_entity_facts
                (entity_id, field_name, field_value_text,
                 field_value_numeric, field_kind, source_id) VALUES
                ('e_solo', 'amount_max_yen', '12500000',  12500000, 'amount', 1),
                ('e_agree', 'amount_max_yen', '12500000', 12500000, 'amount', 1),
                ('e_agree', 'amount_max_yen', '12500000', 12500000, 'amount', 2),
                ('e_solo', 'note', 'free text',           NULL,     'text',   NULL);
            """
        )
        conn.executescript(_MIGRATION_069.read_text(encoding="utf-8"))
        conn.executescript(_MIGRATION_145.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _client_for(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from jpintel_mcp.api import stats as stats_mod
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    # Bypass the L4 cache so each test sees a deterministic compute.
    monkeypatch.setattr(
        stats_mod,
        "_cache_get_or_compute",
        lambda key, compute: compute(),
    )
    app = FastAPI()
    app.include_router(stats_mod.router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Snapshot fast-path
# ---------------------------------------------------------------------------


def test_snapshot_read_returns_parked_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When a snapshot row exists the handler reads it back verbatim
    instead of running the inline aggregation."""
    db_file = tmp_path / "am_test.db"
    _build_am_db(db_file)

    # Park a deliberately-distinct snapshot so we can prove the handler
    # served it (rather than recomputing from the seeded facts).
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            """
            INSERT INTO am_data_quality_snapshot (
                snapshot_at, source_count, fact_count_total, mean_score,
                label_histogram_json, license_breakdown_json,
                freshness_buckets_json, field_kind_breakdown_json,
                cross_source_agreement_json, source_url_freshness_pct,
                fallback_source, fallback_note, am_source_total_rows,
                model, compute_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-05-04T20:05:00Z",
                42,
                7,
                0.7777,
                json.dumps({"high": 1, "medium": 2, "low": 3, "unknown": 1}),
                json.dumps({"gov_standard_v2.0": 4, "null_source": 1}),
                json.dumps({"<=30d": 5, "31-180d": 0, "181-365d": 0, ">365d": 0, "unknown": 0}),
                json.dumps({"amount": {"count": 5, "mean_score": 0.8}}),
                json.dumps(
                    {
                        "facts_with_n_sources_>=2": 2,
                        "facts_with_consistent_value": 2,
                        "agreement_rate": 1.0,
                    }
                ),
                0.5,
                None,
                None,
                None,
                "beta_posterior_v1",
                12,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    client = _client_for(db_file, monkeypatch)
    resp = client.get("/v1/stats/data_quality")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The parked row's distinctive numbers must surface unchanged.
    assert body["fact_count_total"] == 7
    assert body["mean_score"] == 0.7777
    assert body["label_histogram"]["medium"] == 2
    assert body["license_breakdown"]["gov_standard_v2.0"] == 4
    assert body["model"] == "beta_posterior_v1"
    assert body["generated_at"] == "2026-05-04T20:05:00Z"


def test_snapshot_read_responds_within_one_second(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Wall-clock budget: the snapshot SELECT must finish in <1 s.

    Fly grace is 60 s; we want orders-of-magnitude headroom so the
    failure mode in `feedback_no_quick_check_on_huge_sqlite` cannot
    recur as the autonomath corpus grows.
    """
    db_file = tmp_path / "am_test.db"
    _build_am_db(db_file)

    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO am_data_quality_snapshot "
            "(snapshot_at, label_histogram_json) VALUES (?, ?)",
            ("2026-05-04T20:05:00Z", json.dumps({"high": 1, "medium": 0, "low": 0, "unknown": 0})),
        )
        conn.commit()
    finally:
        conn.close()

    client = _client_for(db_file, monkeypatch)
    t0 = time.monotonic()
    resp = client.get("/v1/stats/data_quality")
    elapsed = time.monotonic() - t0
    assert resp.status_code == 200, resp.text
    assert elapsed < 1.0, f"snapshot read took {elapsed:.3f}s — gate is 1.0s"


# ---------------------------------------------------------------------------
# 2. Cron compute → persist → handler read round-trip
# ---------------------------------------------------------------------------


def test_cron_persists_snapshot_and_handler_serves_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End-to-end: precompute_data_quality.main() persists a row, the
    handler reads it back. Schema columns and JSON shape must align."""
    db_file = tmp_path / "am_test.db"
    _build_am_db(db_file)

    from jpintel_mcp.config import settings as cfg
    from scripts.cron import precompute_data_quality as cron

    monkeypatch.setattr(cfg, "autonomath_db_path", db_file)
    rc = cron.main(["--am-db", str(db_file)])
    assert rc == 0

    # Exactly one row present, with non-empty JSON aggregates.
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM am_data_quality_snapshot").fetchall()
        assert len(rows) == 1
        row = rows[0]
        assert row["model"] == "beta_posterior_v1"
        assert row["fact_count_total"] >= 4  # 4 fixture facts
        assert json.loads(row["label_histogram_json"])
        assert row["compute_ms"] is not None
    finally:
        conn.close()

    client = _client_for(db_file, monkeypatch)
    resp = client.get("/v1/stats/data_quality")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fact_count_total"] >= 4
    assert body["model"] == "beta_posterior_v1"


# ---------------------------------------------------------------------------
# 3 + 4. Legacy fallback paths
# ---------------------------------------------------------------------------


def test_handler_falls_back_when_snapshot_table_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pre-migration state: snapshot table doesn't exist. Handler must
    still serve via the inline compute (no 500)."""
    db_file = tmp_path / "am_test.db"
    # Build WITHOUT migration 145 so the snapshot table is absent.
    conn = sqlite3.connect(str(db_file))
    try:
        conn.executescript(_AM_SCHEMA_SQL)
        conn.executescript(
            """
            INSERT INTO am_source (source_url, license, first_seen) VALUES
                ('https://chusho.meti.go.jp/x.pdf', 'gov_standard_v2.0',
                 datetime('now', '-30 days'));
            INSERT INTO am_entity_facts
                (entity_id, field_name, field_value_text,
                 field_value_numeric, field_kind, source_id) VALUES
                ('e_x', 'amount_max_yen', '1', 1, 'amount', 1);
            """
        )
        conn.executescript(_MIGRATION_069.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()

    client = _client_for(db_file, monkeypatch)
    resp = client.get("/v1/stats/data_quality")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] == "beta_posterior_v1"
    assert body["fact_count_total"] >= 1


def test_handler_falls_back_when_snapshot_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Pre-first-cron-run state: table exists but holds zero rows.
    Handler falls through to inline compute."""
    db_file = tmp_path / "am_test.db"
    _build_am_db(db_file)
    # Confirm the snapshot table is empty.
    conn = sqlite3.connect(db_file)
    try:
        n = conn.execute("SELECT COUNT(*) FROM am_data_quality_snapshot").fetchone()[0]
        assert n == 0
    finally:
        conn.close()

    client = _client_for(db_file, monkeypatch)
    resp = client.get("/v1/stats/data_quality")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["model"] == "beta_posterior_v1"
    # Inline compute still aggregates the seeded fixture facts.
    assert body["fact_count_total"] >= 1


# ---------------------------------------------------------------------------
# 5. Cron idempotency
# ---------------------------------------------------------------------------


def test_cron_is_idempotent_within_same_second(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Running the cron twice back-to-back must not crash on the
    snapshot_at PRIMARY KEY — the script uses ON CONFLICT UPSERT."""
    db_file = tmp_path / "am_test.db"
    _build_am_db(db_file)

    from jpintel_mcp.config import settings as cfg
    from scripts.cron import precompute_data_quality as cron

    monkeypatch.setattr(cfg, "autonomath_db_path", db_file)

    assert cron.main(["--am-db", str(db_file)]) == 0
    # Second invocation in the same second must succeed via UPSERT.
    assert cron.main(["--am-db", str(db_file)]) == 0
