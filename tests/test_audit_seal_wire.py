"""§17.D audit-seal wiring tests (2026-04-30).

Plan reference: docs/_internal/llm_resilient_business_plan_2026-04-30.md
Section 17 step 5 + Section 18 row "audit seal".

What we pin:

  1. Paid responses (dd_batch as the spec example) carry an ``audit_seal``
     envelope with the §17.D shape:
       seal_id / issued_at / subject_hash / key_hash_prefix /
       corpus_snapshot_id / verify_endpoint / _disclaimer.
  2. ``GET /v1/audit/seals/{seal_id}`` returns 200 for an existing seal
     (verified=true when the persisted HMAC binds back to the secret) and
     404 for a missing seal.
  3. ``corpus_snapshot_id`` is stable across calls within the 6h cache window
     AND is exposed at ``GET /v1/meta/corpus_snapshot``.
  4. Anonymous responses do NOT carry the ``audit_seal`` envelope —
     sealing is paid-only (verify is anon-allowed but issue is paid-only).
"""
from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _ensure_audit_seal_tables(seeded_db: Path):
    """Apply migration 089 (audit_seals base) + 119 (seal_id columns) onto
    the seeded test DB so the persistence path lands rows we can verify.

    The session-scoped ``seeded_db`` only has the schema.sql baseline, so
    we layer the relevant migrations here. ``IF NOT EXISTS`` + the
    swallow-duplicate-column posture in entrypoint.sh means re-applying
    is safe.
    """
    repo = Path(__file__).resolve().parent.parent
    base = repo / "scripts" / "migrations"
    for mig in ("089_audit_seal_table.sql", "119_audit_seal_seal_id_columns.sql"):
        sql_path = base / mig
        sql = sql_path.read_text(encoding="utf-8")
        c = sqlite3.connect(seeded_db)
        try:
            with contextlib.suppress(sqlite3.OperationalError):
                # Migration 119 ALTERs are non-idempotent — duplicate column
                # name on re-run is the documented swallow path.
                c.executescript(sql)
            c.commit()
        finally:
            c.close()
    # Reset the corpus_snapshot cache so each test sees a fresh derivation.
    from jpintel_mcp.api._audit_seal import _reset_corpus_snapshot_cache_for_tests

    _reset_corpus_snapshot_cache_for_tests()


# ---------------------------------------------------------------------------
# Test 1: dd_batch paid response carries the §17.D audit_seal envelope.
# ---------------------------------------------------------------------------


_FIVE_HOUJIN: tuple[str, ...] = (
    "1010001000001",
    "2010001000002",
    "3010001000003",
    "4010001000004",
    "5010001000005",
)


def _seed_ma_pillar(seeded_db: Path) -> None:
    """Layer the migration 088 schema so dd_batch returns 200 (not 500).

    Lifted from tests/test_ma_pillar_e2e.py::_ensure_ma_pillar_tables.
    """
    repo = Path(__file__).resolve().parent.parent
    for mig in ("080_customer_webhooks.sql", "088_houjin_watch.sql"):
        sql_path = repo / "scripts" / "migrations" / mig
        sql = sql_path.read_text(encoding="utf-8")
        c = sqlite3.connect(seeded_db)
        try:
            c.executescript(sql)
            c.commit()
        finally:
            c.close()


def test_dd_batch_response_carries_audit_seal(client, paid_key, seeded_db):
    _seed_ma_pillar(seeded_db)
    r = client.post(
        "/v1/am/dd_batch",
        headers={"X-API-Key": paid_key},
        json={
            "houjin_bangous": list(_FIVE_HOUJIN),
            "depth": "summary",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "audit_seal" in body, "paid response missing audit_seal envelope"
    seal = body["audit_seal"]
    # §17.D required surface — every customer-visible field present.
    for k in (
        "seal_id",
        "issued_at",
        "subject_hash",
        "key_hash_prefix",
        "corpus_snapshot_id",
        "verify_endpoint",
        "_disclaimer",
    ):
        assert k in seal, f"audit_seal missing field {k!r}"
    assert seal["seal_id"].startswith("seal_"), seal["seal_id"]
    assert seal["subject_hash"].startswith("sha256:"), seal["subject_hash"]
    assert seal["corpus_snapshot_id"].startswith("corpus-"), seal["corpus_snapshot_id"]
    assert seal["verify_endpoint"] == f"/v1/audit/seals/{seal['seal_id']}", (
        seal["verify_endpoint"]
    )
    # key_hash_prefix is exactly 8 chars (per §17.D copy "first 8 chars only").
    assert len(seal["key_hash_prefix"]) == 8, seal["key_hash_prefix"]


# ---------------------------------------------------------------------------
# Test 2: verify endpoint returns 200 for existing, 404 for missing.
# ---------------------------------------------------------------------------


def test_verify_endpoint_200_for_existing_seal(client, paid_key, seeded_db):
    _seed_ma_pillar(seeded_db)
    r = client.post(
        "/v1/am/dd_batch",
        headers={"X-API-Key": paid_key},
        json={
            "houjin_bangous": list(_FIVE_HOUJIN[:2]),
            "depth": "summary",
        },
    )
    assert r.status_code == 200, r.text
    seal = r.json()["audit_seal"]
    seal_id = seal["seal_id"]

    # Verify is anon-allowed — no X-API-Key needed.
    rv = client.get(f"/v1/audit/seals/{seal_id}")
    assert rv.status_code == 200, rv.text
    body = rv.json()
    assert body["seal_id"] == seal_id
    assert body["verified"] is True
    assert body["subject_hash"] == seal["subject_hash"]
    assert body["corpus_snapshot_id"] == seal["corpus_snapshot_id"]
    assert body["issued_at"] == seal["issued_at"]


def test_verify_endpoint_404_for_missing_seal(client):
    rv = client.get("/v1/audit/seals/seal_does_not_exist_0000000000000000")
    assert rv.status_code == 404, rv.text
    body = rv.json()
    assert body["verified"] is False
    assert body["seal_id"] == "seal_does_not_exist_0000000000000000"


# ---------------------------------------------------------------------------
# Test 3: corpus_snapshot_id stable within 6h, exposed at /v1/meta/corpus_snapshot.
# ---------------------------------------------------------------------------


def test_corpus_snapshot_id_stable_within_window():
    from jpintel_mcp.api._audit_seal import (
        _reset_corpus_snapshot_cache_for_tests,
        get_corpus_snapshot_id,
    )

    _reset_corpus_snapshot_cache_for_tests()
    a = get_corpus_snapshot_id()
    b = get_corpus_snapshot_id()
    c = get_corpus_snapshot_id()
    assert a == b == c, (a, b, c)
    assert a.startswith("corpus-"), a
    # Format is corpus-YYYY-MM-DD.
    rest = a[len("corpus-") :]
    parts = rest.split("-")
    assert len(parts) == 3 and len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2, a


def test_corpus_snapshot_meta_endpoint_returns_same_value(client):
    from jpintel_mcp.api._audit_seal import (
        _reset_corpus_snapshot_cache_for_tests,
        get_corpus_snapshot_id,
    )

    _reset_corpus_snapshot_cache_for_tests()
    expected = get_corpus_snapshot_id()
    r = client.get("/v1/meta/corpus_snapshot")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["corpus_snapshot_id"] == expected, (body, expected)


# ---------------------------------------------------------------------------
# Test 4: anon responses do NOT carry the audit_seal envelope.
# ---------------------------------------------------------------------------


def test_anon_response_does_not_carry_audit_seal(client, seeded_db):
    """Programs search hits as an anon caller (no X-API-Key) — the response
    must NOT carry an audit_seal envelope. Sealing is paid-only — anon has
    no api_key_hash to bind the seal to, and the 7-year retention surface
    is statutory evidence tied to a paid customer.
    """
    r = client.get("/v1/programs/search?q=test&limit=3")
    # Any 2xx is acceptable; we just want to assert the seal is absent.
    if r.status_code != 200:
        # Anon quota or empty result — still fine; nothing to seal.
        return
    body = r.json()
    # The body shape varies; we check both legacy + envelope shapes.
    assert "audit_seal" not in body, (
        f"anon response leaked audit_seal: {body.get('audit_seal')!r}"
    )
    if isinstance(body, dict) and "results" in body:
        for row in body.get("results") or []:
            if isinstance(row, dict):
                assert "audit_seal" not in row, "row-level seal leaked on anon"
