"""Tests for the bulk Evidence Packet surface (REST + MCP).

Covers:
  * POST /v1/evidence/packets/batch wire contract (envelope shape, billing
    unit, audit_seal, corpus_snapshot_id, _disclaimer, _next_calls).
  * 100-lookup happy path.
  * 101+ lookup hard cap (422).
  * Partial failure rollup (1 unknown id + 99 valid).
  * MCP / REST parity — same lookups produce the same envelope shape on
    both surfaces.

Fixture posture mirrors tests/test_evidence_packet.py — we build a small
autonomath.db inline so the composer reads from a real-shaped store.
"""

from __future__ import annotations

import contextlib
import sqlite3
import sys
from pathlib import Path  # noqa: TC003 — runtime fixture annotation
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture autonomath.db builder — N programs (default 105) + 1 houjin row.
# ---------------------------------------------------------------------------


def _build_fixture_autonomath_db(path: Path, n_programs: int = 105) -> None:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(
            """
            CREATE TABLE am_source (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url   TEXT NOT NULL UNIQUE,
                source_type  TEXT NOT NULL DEFAULT 'primary',
                domain       TEXT,
                content_hash TEXT,
                first_seen   TEXT NOT NULL DEFAULT (datetime('now')),
                last_verified TEXT,
                license      TEXT
            );
            CREATE TABLE am_entities (
                canonical_id  TEXT PRIMARY KEY,
                primary_name  TEXT NOT NULL,
                record_kind   TEXT,
                source_url    TEXT,
                fetched_at    TEXT,
                confidence    REAL
            );
            CREATE TABLE am_entity_facts (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id                TEXT NOT NULL,
                field_name               TEXT NOT NULL,
                field_value_text         TEXT,
                field_value_json         TEXT,
                field_value_numeric      REAL,
                field_kind               TEXT NOT NULL DEFAULT 'text',
                source_id                INTEGER REFERENCES am_source(id),
                confirming_source_count  INTEGER DEFAULT 1,
                created_at               TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE am_entity_source (
                entity_id    TEXT NOT NULL,
                source_id    INTEGER NOT NULL,
                role         TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (entity_id, source_id, role)
            );
            CREATE TABLE jpi_programs (
                unified_id        TEXT PRIMARY KEY,
                primary_name      TEXT NOT NULL,
                aliases_json      TEXT,
                authority_name    TEXT,
                prefecture        TEXT,
                tier              TEXT,
                source_url        TEXT,
                source_fetched_at TEXT,
                updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE am_alias (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_table TEXT,
                canonical_id TEXT NOT NULL,
                alias        TEXT NOT NULL,
                alias_kind   TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                language     TEXT NOT NULL DEFAULT 'ja'
            );
            CREATE TABLE entity_id_map (
                jpi_unified_id   TEXT NOT NULL,
                am_canonical_id  TEXT NOT NULL,
                match_method     TEXT NOT NULL,
                confidence       REAL NOT NULL,
                PRIMARY KEY (jpi_unified_id, am_canonical_id)
            );
            CREATE TABLE am_compat_matrix (
                program_a_id      TEXT NOT NULL,
                program_b_id      TEXT NOT NULL,
                compat_status     TEXT NOT NULL,
                conditions_text   TEXT,
                rationale_short   TEXT,
                source_url        TEXT,
                confidence        REAL,
                inferred_only     INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (program_a_id, program_b_id)
            );
            CREATE TABLE am_amendment_diff (
                diff_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id    TEXT NOT NULL,
                field_name   TEXT NOT NULL,
                prev_value   TEXT,
                new_value    TEXT,
                source_url   TEXT,
                detected_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE am_program_summary (
                entity_id        TEXT PRIMARY KEY,
                primary_name     TEXT,
                summary_50       TEXT,
                summary_200      TEXT,
                summary_800      TEXT,
                token_50_est     INT,
                token_200_est    INT,
                token_800_est    INT,
                generated_at     TEXT DEFAULT (datetime('now')),
                source_quality   REAL
            );
            """
        )
        con.execute(
            "INSERT INTO am_source(source_url, source_type, domain, "
            "content_hash, first_seen, last_verified, license) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                "https://www.maff.go.jp/policy/batch.html",
                "primary",
                "www.maff.go.jp",
                "sha256:batch1aaa",
                "2026-04-25T00:00:00",
                "2026-04-28T00:00:00",
                "gov_standard_v2.0",
            ),
        )
        rows: list[tuple[str, str, str, str, str, float]] = []
        for i in range(n_programs):
            cid = f"program:batch:p{i:03d}"
            rows.append(
                (
                    cid,
                    f"バッチテスト P{i:03d} 補助金",
                    "program",
                    "https://www.maff.go.jp/policy/batch.html",
                    "2026-04-25T00:00:00",
                    1.0,
                )
            )
        con.executemany(
            "INSERT INTO am_entities("
            "canonical_id, primary_name, record_kind, source_url, "
            "fetched_at, confidence) VALUES (?,?,?,?,?,?)",
            rows,
        )
        # 1 fact per program with a source_id so the gate keeps the row.
        con.executemany(
            "INSERT INTO am_entity_facts("
            "entity_id, field_name, field_value_text, field_kind, "
            "source_id, confirming_source_count) "
            "VALUES (?,?,?,?,?,?)",
            [
                (
                    f"program:batch:p{i:03d}",
                    "amount_max_yen",
                    f"P{i:03d}-amount",
                    "text",
                    1,
                    1,
                )
                for i in range(n_programs)
            ],
        )
        # entity_id_map for UNI- ↔ canonical resolution.
        con.executemany(
            "INSERT INTO entity_id_map(jpi_unified_id, am_canonical_id, "
            "match_method, confidence) VALUES (?,?,?,?)",
            [
                (f"UNI-batch-p{i:03d}", f"program:batch:p{i:03d}", "exact_name", 1.0)
                for i in range(n_programs)
            ],
        )
        # jpi_programs entries (used by the program resolver).
        con.executemany(
            "INSERT INTO jpi_programs(unified_id, primary_name, "
            "authority_name, prefecture, tier, source_url, "
            "source_fetched_at) VALUES (?,?,?,?,?,?,?)",
            [
                (
                    f"UNI-batch-p{i:03d}",
                    f"バッチテスト P{i:03d} 補助金",
                    "農林水産省",
                    "東京都",
                    "S",
                    "https://www.maff.go.jp/policy/batch.html",
                    "2026-04-25T00:00:00",
                )
                for i in range(n_programs)
            ],
        )
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fixture_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    p = tmp_path_factory.mktemp("evidence_batch") / "autonomath.db"
    _build_fixture_autonomath_db(p)
    return p


@pytest.fixture(autouse=True)
def _override_paths(fixture_db: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point both REST + MCP composers at the fixture autonomath.db."""
    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(fixture_db))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", fixture_db)

    # Reset singletons + caches.
    if "jpintel_mcp.services.evidence_packet" in sys.modules:
        from jpintel_mcp.services import evidence_packet as _evp

        _evp._reset_cache_for_tests()
    if "jpintel_mcp.api.evidence" in sys.modules:
        from jpintel_mcp.api import evidence as _evp_api

        _evp_api.reset_composer()
    if "jpintel_mcp.mcp.autonomath_tools.evidence_packet_tools" in sys.modules:
        from jpintel_mcp.mcp.autonomath_tools import (
            evidence_packet_tools as _evp_mcp,
        )

        _evp_mcp._reset_composer()
    yield


@pytest.fixture(autouse=True)
def _ensure_audit_seal_tables(seeded_db: Path) -> None:
    migrations = Path(__file__).resolve().parents[1] / "scripts" / "migrations"
    conn = sqlite3.connect(seeded_db)
    try:
        for mig in ("089_audit_seal_table.sql", "119_audit_seal_seal_id_columns.sql"):
            with contextlib.suppress(sqlite3.OperationalError):
                conn.executescript((migrations / mig).read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()

    from jpintel_mcp.api._audit_seal import _reset_corpus_snapshot_cache_for_tests

    _reset_corpus_snapshot_cache_for_tests()


def _usage_count(db_path: Path, raw_key: str, endpoint: str) -> int:
    from jpintel_mcp.api.deps import hash_api_key

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = ?",
            (hash_api_key(raw_key), endpoint),
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def _usage_quantity_sum(db_path: Path, raw_key: str, endpoint: str) -> int:
    from jpintel_mcp.api.deps import hash_api_key

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) FROM usage_events "
            "WHERE key_hash = ? AND endpoint = ?",
            (hash_api_key(raw_key), endpoint),
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def _audit_seal_count(db_path: Path, raw_key: str, endpoint: str) -> int:
    from jpintel_mcp.api.deps import hash_api_key

    conn = sqlite3.connect(db_path)
    try:
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_seals'",
        ).fetchone()
        if has_table is None:
            return 0
        row = conn.execute(
            "SELECT COUNT(*) FROM audit_seals WHERE api_key_hash = ? AND endpoint = ?",
            (hash_api_key(raw_key), endpoint),
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def _batch_headers(raw_key: str, idem: str, *, cap_yen: int = 1000) -> dict[str, str]:
    return {
        "X-API-Key": raw_key,
        "X-Cost-Cap-JPY": str(cap_yen),
        "Idempotency-Key": f"evidence-batch-{idem}",
    }


# ---------------------------------------------------------------------------
# REST tests
# ---------------------------------------------------------------------------


def test_batch_100_lookup_returns_100_packets(
    client: TestClient,
    paid_key: str,
) -> None:
    """100 valid lookups → 100 packets, _billing_unit=100, no errors."""
    payload = {
        "lookups": [{"kind": "program", "id": f"UNI-batch-p{i:03d}"} for i in range(100)],
    }
    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "100"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 100
    assert body["successful"] == 100
    assert body["failed"] == 0
    assert body["errors"] == []
    assert body["_billing_unit"] == 100
    assert len(body["results"]) == 100
    # Every result is a valid Evidence Packet envelope.
    for pkt in body["results"]:
        assert pkt["api_version"] == "v1"
        assert "records" in pkt
        assert "_disclaimer" in pkt


def test_batch_101_returns_422(
    client: TestClient,
    paid_key: str,
) -> None:
    """101+ entries → 422, no billing."""
    payload = {
        "lookups": [{"kind": "program", "id": f"UNI-batch-p{i:03d}"} for i in range(101)],
    }
    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "too-large", cap_yen=1000),
    )
    assert r.status_code == 422, r.text


def test_paid_batch_requires_idempotency_key(
    client: TestClient,
    paid_key: str,
) -> None:
    payload = {"lookups": [{"kind": "program", "id": "UNI-batch-p000"}]}
    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers={"X-API-Key": paid_key, "X-Cost-Cap-JPY": "3"},
    )
    assert r.status_code == 428, r.text
    assert r.json()["error"] == "idempotency_key_required"


def test_paid_batch_requires_cost_cap(
    client: TestClient,
    paid_key: str,
) -> None:
    payload = {"lookups": [{"kind": "program", "id": "UNI-batch-p000"}]}
    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers={
            "X-API-Key": paid_key,
            "Idempotency-Key": "evidence-batch-missing-cap",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "cost_cap_required"


def test_paid_batch_rejects_low_cost_cap_before_billing(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
) -> None:
    payload = {
        "lookups": [
            {"kind": "program", "id": "UNI-batch-p000"},
            {"kind": "program", "id": "UNI-batch-p001"},
        ]
    }
    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "low-cap", cap_yen=3),
    )
    assert r.status_code == 402, r.text
    body = r.json()
    assert body["detail"]["code"] == "cost_cap_exceeded"
    assert body["detail"]["predicted_yen"] == 6
    assert _usage_count(seeded_db, paid_key, "evidence.packet.batch") == 0


def test_batch_with_partial_failures(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
) -> None:
    """1 unknown id + 99 valid → successful=99, failed=1, _billing_unit=99."""
    payload = {
        "lookups": [
            {"kind": "program", "id": "UNI-batch-MISSING"},
            *[{"kind": "program", "id": f"UNI-batch-p{i:03d}"} for i in range(99)],
        ],
    }
    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "partial"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 100
    assert body["successful"] == 99
    assert body["failed"] == 1
    assert body["_billing_unit"] == 99
    assert len(body["errors"]) == 1
    err = body["errors"][0]
    assert err["index"] == 0
    assert err["error"] == "not_found"
    assert err["lookup"] == {"kind": "program", "id": "UNI-batch-MISSING"}
    assert len(body["results"]) == 99

    # Billing — exactly one usage_events row with quantity=99.
    assert _usage_count(seeded_db, paid_key, "evidence.packet.batch") == 1
    assert _usage_quantity_sum(seeded_db, paid_key, "evidence.packet.batch") == 99


def test_batch_billing_unit_equals_lookup_count(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
) -> None:
    """A pure-success batch bills ¥3 × N — Stripe quantity = N."""
    payload = {
        "lookups": [{"kind": "program", "id": f"UNI-batch-p{i:03d}"} for i in range(50)],
    }
    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "billing-50"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["_billing_unit"] == 50
    assert body["successful"] == 50
    # ONE row in usage_events with quantity=50 (consultant-pattern: 1 audit
    # row, N billed units rather than N rows × quantity 1).
    assert _usage_count(seeded_db, paid_key, "evidence.packet.batch") == 1
    assert _usage_quantity_sum(seeded_db, paid_key, "evidence.packet.batch") == 50


def test_paid_batch_fails_closed_when_final_metering_cap_rejects(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delivered paid batch must never become a silent unmetered 200."""
    from jpintel_mcp.api.middleware import customer_cap

    monkeypatch.setattr(
        customer_cap,
        "metered_charge_within_cap",
        lambda *args, **kwargs: False,
    )
    payload = {"lookups": [{"kind": "program", "id": "UNI-batch-p000"}]}

    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "final-metering-cap", cap_yen=1000),
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "billing_cap_final_check_failed"
    assert _usage_count(seeded_db, paid_key, "evidence.packet.batch") == 0
    assert _audit_seal_count(seeded_db, paid_key, "evidence.packet.batch") == 0


def test_paid_batch_audit_seal_persist_failure_does_not_bill_or_seal(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import jpintel_mcp.api._audit_seal as seal_mod

    def _raise(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("forced seal persist failure")

    monkeypatch.setattr(seal_mod, "persist_seal", _raise)
    payload = {"lookups": [{"kind": "program", "id": "UNI-batch-p000"}]}

    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "seal-persist-fail"),
    )

    assert r.status_code == 503, r.text
    assert r.json()["detail"]["code"] == "audit_seal_persist_failed"
    assert _usage_count(seeded_db, paid_key, "evidence.packet.batch") == 0
    assert _audit_seal_count(seeded_db, paid_key, "evidence.packet.batch") == 0


def test_paid_batch_all_failures_not_billed_or_sealed(
    client: TestClient,
    paid_key: str,
    seeded_db: Path,
) -> None:
    payload = {"lookups": [{"kind": "program", "id": "UNI-batch-MISSING"}]}

    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "all-fail"),
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["successful"] == 0
    assert body["_billing_unit"] == 0
    assert "audit_seal" not in body
    assert _usage_count(seeded_db, paid_key, "evidence.packet.batch") == 0
    assert _audit_seal_count(seeded_db, paid_key, "evidence.packet.batch") == 0


def test_batch_envelope_complies(
    client: TestClient,
    paid_key: str,
) -> None:
    """audit_seal + corpus_snapshot_id + _disclaimer all present + non-empty."""
    payload = {
        "lookups": [
            {"kind": "program", "id": "UNI-batch-p000"},
            {"kind": "program", "id": "UNI-batch-p001"},
        ],
    }
    r = client.post(
        "/v1/evidence/packets/batch",
        json=payload,
        headers=_batch_headers(paid_key, "envelope"),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # corpus_snapshot_id present (string, may be the fallback sentinel
    # depending on the fixture DB state).
    assert "corpus_snapshot_id" in body
    assert isinstance(body["corpus_snapshot_id"], str)
    # _disclaimer carries the same shape as single-record packets.
    assert "_disclaimer" in body
    assert body["_disclaimer"]["type"] == "information_only"
    assert body["_disclaimer"]["not_legal_or_tax_advice"] is True
    # audit_seal envelope on a paid response.
    assert "audit_seal" in body
    assert body["audit_seal"]["seal_id"].startswith("seal_")
    assert body["audit_seal"]["hmac"]
    assert body["audit_seal"]["alg"] == "HMAC-SHA256"
    # Top-level alias mirror.
    assert body["audit_seal_hmac"].startswith("hmac_")
    # _next_calls present and structured.
    assert "_next_calls" in body
    assert isinstance(body["_next_calls"], list)


def test_mcp_rest_parity(
    client: TestClient,
    paid_key: str,
) -> None:
    """Same batch produces identical envelope shape on REST + MCP."""
    from jpintel_mcp.mcp.autonomath_tools import evidence_batch as _mcp_batch

    lookups = [
        {"kind": "program", "id": "UNI-batch-p000"},
        {"kind": "program", "id": "UNI-batch-p001"},
        {"kind": "program", "id": "UNI-batch-MISSING"},
    ]

    # MCP path
    mcp_body = _mcp_batch._impl_get_evidence_packet_batch(lookups=lookups)

    # REST path
    r = client.post(
        "/v1/evidence/packets/batch",
        json={"lookups": lookups},
        headers=_batch_headers(paid_key, "parity"),
    )
    assert r.status_code == 200, r.text
    rest_body = r.json()

    # Identical envelope-level totals.
    for k in ("total", "successful", "failed", "_billing_unit"):
        assert mcp_body[k] == rest_body[k], f"divergent at {k}"
    assert len(mcp_body["results"]) == len(rest_body["results"])
    assert len(mcp_body["errors"]) == len(rest_body["errors"])

    # Errors carry the same lookup payload + indexes.
    mcp_err_keys = sorted((e["index"], e["error"]) for e in mcp_body["errors"])
    rest_err_keys = sorted((e["index"], e["error"]) for e in rest_body["errors"])
    assert mcp_err_keys == rest_err_keys

    # Both surface _disclaimer + corpus_snapshot_id + _next_calls.
    for k in ("_disclaimer", "corpus_snapshot_id", "_next_calls"):
        assert k in mcp_body
        assert k in rest_body
    assert mcp_body["_disclaimer"]["type"] == rest_body["_disclaimer"]["type"]
