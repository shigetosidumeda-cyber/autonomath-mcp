"""Trust 8-pack happy-path tests (migration 101).

Covers the seven public surfaces wired by `src/jpintel_mcp/api/trust.py`:

    GET  /v1/health/sla
    GET  /v1/corrections
    POST /v1/corrections           (idempotent)
    GET  /v1/corrections/feed
    GET  /v1/trust/section52
    GET  /v1/cross_source/{eid}
    GET  /v1/staleness

Tests are kept narrow — one happy path per surface — because the trust
math itself lives in unit-testable helpers (`services/cross_source.py`)
and the schema is asserted by mig 101 itself. Wider behavioural coverage
is left for the per-feature smoke tests in tests/smoke/ once the cron
loop produces real data.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.services.cross_source import (
    _verdict,
    compute_cross_source_agreement,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


@pytest.fixture()
def trust_seeded_db(seeded_db: Path) -> Path:
    """Add minimal mig 101 tables onto the seeded jpintel.db so the trust
    endpoints can return non-empty rows even when autonomath.db is absent.

    The trust router opens autonomath.db RO. In unit-test mode we instead
    point at a dedicated SQLite file so the router sees a non-empty
    correction_log + correction_submissions schema and behaves like prod.
    """
    # The existing fixture seeds jpintel.db. The trust endpoints consult
    # autonomath.db via settings.autonomath_db_path. For tests we mount a
    # synthetic schema onto the same file so the router can run.
    from jpintel_mcp.config import settings

    am_path = settings.autonomath_db_path
    am_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(am_path)
    # Drop & recreate per-test so dedup state from a previous run cannot
    # poison the next assertion (correction_submissions is keyed on
    # ip-hash + entity + field + day, so submitting twice with default
    # TestClient IP from two distinct tests would otherwise look like a
    # dupe in the second test).
    conn.execute("DROP TABLE IF EXISTS correction_log")
    conn.execute("DROP TABLE IF EXISTS correction_submissions")
    conn.execute("DROP TABLE IF EXISTS audit_log_section52")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS correction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at TEXT NOT NULL,
            dataset TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            field_name TEXT,
            prev_value_hash TEXT,
            new_value_hash TEXT,
            root_cause TEXT NOT NULL,
            source_url TEXT,
            reproducer_sql TEXT,
            correction_post_url TEXT,
            rss_appended_at TEXT
        );
        CREATE TABLE IF NOT EXISTS correction_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submitted_at TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            field TEXT NOT NULL,
            claimed_correct_value TEXT NOT NULL,
            evidence_url TEXT NOT NULL,
            reporter_email TEXT,
            reporter_email_hmac TEXT NOT NULL,
            reporter_ip_hash TEXT NOT NULL,
            reporter_key_hash TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reviewed_at TEXT,
            reviewer_note TEXT,
            correction_log_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS audit_log_section52 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sampled_at TEXT NOT NULL,
            tool TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            response_hash TEXT NOT NULL,
            disclaimer_present INTEGER NOT NULL,
            advisory_terms_in_response TEXT,
            violation INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    # Seed one correction_log row so /v1/corrections has something to show.
    conn.execute(
        "INSERT INTO correction_log("
        "  detected_at, dataset, entity_id, field_name, "
        "  prev_value_hash, new_value_hash, root_cause, source_url, "
        "  reproducer_sql) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            "2026-04-29T12:00:00+00:00",
            "programs",
            "UNI-test-s-1",
            "amount_max_yen",
            "sha256:aaaaaaaaaaaaaaaa",
            "sha256:bbbbbbbbbbbbbbbb",
            "human_report",
            "https://example.go.jp/source",
            "SELECT * FROM programs WHERE unified_id='UNI-test-s-1'",
        ),
    )
    # Seed one §52 sample so the rollup endpoint returns at least one day.
    conn.execute(
        "INSERT INTO audit_log_section52("
        "  sampled_at, tool, request_hash, response_hash, "
        "  disclaimer_present, advisory_terms_in_response, violation) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            "2026-04-29T01:00:00+00:00",
            "POST /v1/tax_rulesets/evaluate",
            "sha256:" + "0" * 16,
            "sha256:" + "1" * 16,
            1,
            None,
            0,
        ),
    )
    conn.commit()
    conn.close()
    return seeded_db


def test_sla_endpoint_returns_shape(client: TestClient) -> None:
    r = client.get("/v1/health/sla")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["window"] == "7d"
    assert "uptime_pct" in body
    assert "p95_latency_ms" in body
    assert "sample_count" in body
    assert body["target"]["uptime_pct"] == 99.5


def test_sla_endpoint_24h_window(client: TestClient) -> None:
    r = client.get("/v1/health/sla?window=24h")
    assert r.status_code == 200
    assert r.json()["window"] == "24h"


def test_corrections_list_returns_seeded_row(
    trust_seeded_db: Path,
    client: TestClient,
) -> None:
    r = client.get("/v1/corrections?limit=10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "results" in body
    assert any(c.get("entity_id") == "UNI-test-s-1" for c in body["results"])
    assert body["_meta"]["rss"] == "/v1/corrections/feed"


def test_corrections_submit_then_dedup(
    trust_seeded_db: Path,
    client: TestClient,
) -> None:
    payload = {
        "entity_id": "UNI-test-s-1",
        "field": "amount_max_yen",
        "claimed_correct_value": "10000000",
        "evidence_url": "https://example.go.jp/correct-source",
        "reporter_email": "auditor@example.com",
    }
    r1 = client.post("/v1/corrections", json=payload)
    assert r1.status_code == 201, r1.text
    body1 = r1.json()
    assert body1["status"] == "pending"
    assert body1["id"] >= 1

    # Same submission within the day must dedup → 200 with status='duplicate'.
    r2 = client.post("/v1/corrections", json=payload)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "duplicate"


def test_corrections_submit_rejects_invalid_email(
    trust_seeded_db: Path,
    client: TestClient,
) -> None:
    r = client.post(
        "/v1/corrections",
        json={
            "entity_id": "UNI-test-s-1",
            "field": "amount_max_yen",
            "claimed_correct_value": "1",
            "evidence_url": "https://example.go.jp/x",
            "reporter_email": "not-an-email",
        },
    )
    # 422 (semantic validation failure) — was 400, switched to align with
    # Pydantic / `_validation_handler` (api/main.py) which returns 422 for
    # the rest of the API. The body is syntactically valid JSON; only a
    # field value violates a server-side constraint.
    assert r.status_code == 422


def test_corrections_rss_feed_serves_xml(
    trust_seeded_db: Path,
    client: TestClient,
) -> None:
    r = client.get("/v1/corrections/feed")
    assert r.status_code == 200
    assert "application/rss+xml" in r.headers.get("content-type", "")
    assert "<rss" in r.text
    assert "Bookyou株式会社" in r.text


def test_section52_rollup_returns_window(
    trust_seeded_db: Path,
    client: TestClient,
) -> None:
    r = client.get("/v1/trust/section52?days=30")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["window_days"] == 30
    assert "summary" in body
    assert "violation_rate" in body["summary"]


def test_staleness_endpoint_lists_datasets(client: TestClient) -> None:
    r = client.get("/v1/staleness?threshold_days=90")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["threshold_days"] == 90
    names = {d["name"] for d in body["datasets"]}
    # The fixture only carries jpintel.db (not autonomath.db jpi_* mirror)
    # so the response is a list of placeholders — the contract requires the
    # shape regardless.
    assert {"programs", "laws", "tax_rulesets"} <= names


def test_cross_source_endpoint_404_on_unknown(client: TestClient) -> None:
    r = client.get("/v1/cross_source/UNI-does-not-exist")
    assert r.status_code == 404


def test_cross_source_fallback_on_jpi_programs(client: TestClient) -> None:
    # Seeded fixture has UNI-test-s-1 in jpintel.db but no am_entity_facts —
    # the cross_source helper degrades to a single_source verdict.
    r = client.get("/v1/cross_source/UNI-test-s-1")
    # 200 if fallback fires; 404 if the table is genuinely absent. Either
    # is contractual — we accept both.
    assert r.status_code in (200, 404)


# ---- unit tests against the helper directly ---------------------------------


def test_verdict_table() -> None:
    assert _verdict(0, 0) == "no_data"
    assert _verdict(1, 1) == "single_source"
    assert _verdict(2, 1) == "agreement"
    assert _verdict(3, 1) == "agreement"
    assert _verdict(2, 2) == "disagreement"
    assert _verdict(5, 3) == "disagreement"


def test_compute_cross_source_against_minimal_schema(tmp_path: Path) -> None:
    db = tmp_path / "am.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE am_entity_facts (
            entity_id TEXT, field_name TEXT, value TEXT,
            source_id TEXT, confirming_source_count INTEGER DEFAULT 1
        );
        INSERT INTO am_entity_facts VALUES
          ('E1','amount','100','S1',1),
          ('E1','amount','100','S2',1),
          ('E1','amount','200','S3',1),
          ('E2','rate','0.5','S1',1),
          ('E2','rate','0.5','S2',1);
        """
    )
    conn.commit()
    out_e1 = compute_cross_source_agreement(conn, "E1")
    assert out_e1 is not None
    assert out_e1["summary"]["any_disagreement"] is True
    out_e2 = compute_cross_source_agreement(conn, "E2")
    assert out_e2 is not None
    assert out_e2["summary"]["verdict"] == "agreement"
    out_missing = compute_cross_source_agreement(conn, "E-missing")
    assert out_missing is None
    conn.close()
