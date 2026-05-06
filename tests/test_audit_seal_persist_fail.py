from __future__ import annotations

import sqlite3
import uuid
from urllib.parse import quote

import pytest


def _audit_conn(*, section52: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE audit_seals (
            call_id TEXT PRIMARY KEY,
            api_key_hash TEXT NOT NULL,
            ts TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            query_hash TEXT NOT NULL,
            response_hash TEXT NOT NULL,
            source_urls_json TEXT NOT NULL DEFAULT '[]',
            client_tag TEXT,
            hmac TEXT NOT NULL,
            retention_until TEXT NOT NULL,
            seal_id TEXT,
            corpus_snapshot_id TEXT,
            key_version INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    if section52:
        conn.execute(
            """
            CREATE TABLE audit_log_section52 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sampled_at TEXT NOT NULL,
                tool TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                response_hash TEXT NOT NULL,
                disclaimer_present INTEGER NOT NULL,
                advisory_terms_in_response TEXT,
                violation INTEGER NOT NULL DEFAULT 0
            )
            """
        )
    return conn


def test_persist_success_returns_seal():
    from jpintel_mcp.api._audit_seal import attach_seal_to_body

    conn = _audit_conn()
    body = {"answer": "ok"}
    out = attach_seal_to_body(
        body,
        endpoint="dd03.success",
        request_params={"q": "x"},
        api_key_hash="k" * 64,
        conn=conn,
    )

    assert "audit_seal" in out
    seal_id = out["audit_seal"]["seal_id"]
    row = conn.execute(
        "SELECT seal_id FROM audit_seals WHERE seal_id = ?",
        (seal_id,),
    ).fetchone()
    assert row is not None


def test_persist_failure_returns_no_seal(monkeypatch):
    from jpintel_mcp.api import _audit_seal as seal_mod

    conn = _audit_conn()

    def _raise(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated disk full")

    monkeypatch.setattr(seal_mod, "persist_seal", _raise)
    body = {"answer": "still useful"}
    out = seal_mod.attach_seal_to_body(
        body,
        endpoint="dd03.failure",
        request_params={"q": "x"},
        api_key_hash="k" * 64,
        conn=conn,
    )

    assert out["_seal_unavailable"] is True
    assert "audit_seal" not in out
    assert conn.execute("SELECT COUNT(*) FROM audit_seals").fetchone()[0] == 0


@pytest.mark.parametrize(
    "forged_id",
    [
        "seal_" + "0" * 32,
        "seal_deadbeef",
        "01HW2J3" + "X" * 19,
        "../../etc/passwd",
        "'; DROP TABLE audit_seals; --",
    ],
)
def test_verify_endpoint_returns_404_for_unpersisted(client, forged_id):
    r = client.get(f"/v1/audit/seals/{quote(forged_id, safe='')}")
    assert r.status_code == 404, r.text
    body = r.json()
    if "verified" in body:
        assert body["verified"] is False


def test_response_atomicity(monkeypatch):
    from jpintel_mcp.api import _audit_seal as seal_mod

    conn = _audit_conn()
    fixed = uuid.UUID("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    monkeypatch.setattr(seal_mod.uuid, "uuid4", lambda: fixed)

    results = [
        seal_mod.attach_seal_to_body(
            {"i": i},
            endpoint="dd03.atomic",
            request_params={"i": i},
            api_key_hash="k" * 64,
            conn=conn,
        )
        for i in range(5)
    ]

    assert sum(1 for body in results if "audit_seal" in body) == 1
    assert sum(1 for body in results if body.get("_seal_unavailable")) == 4
    assert conn.execute("SELECT COUNT(*) FROM audit_seals").fetchone()[0] == 1


def test_section52_audit_event_emitted_on_fail(monkeypatch):
    from jpintel_mcp.api import _audit_seal as seal_mod

    conn = _audit_conn(section52=True)

    def _raise(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated disk full")

    monkeypatch.setattr(seal_mod, "persist_seal", _raise)
    seal_mod.attach_seal_to_body(
        {"answer": "ok"},
        endpoint="dd03.section52",
        request_params={"q": "x"},
        api_key_hash="k" * 64,
        conn=conn,
    )
    row = conn.execute(
        "SELECT tool, advisory_terms_in_response, violation "
        "FROM audit_log_section52 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["tool"] == "audit_seal.persist:dd03.section52"
    assert "seal_persist_fail" in row["advisory_terms_in_response"]
    assert row["violation"] == 1


def test_no_double_charge_on_seal_fail(monkeypatch):
    from jpintel_mcp.api import _audit_seal as seal_mod

    conn = _audit_conn()
    conn.execute("CREATE TABLE usage_events (id INTEGER PRIMARY KEY AUTOINCREMENT, endpoint TEXT)")

    def _raise(*_args, **_kwargs):
        raise sqlite3.OperationalError("simulated")

    monkeypatch.setattr(seal_mod, "persist_seal", _raise)
    seal_mod.attach_seal_to_body(
        {"answer": "ok"},
        endpoint="dd03.charge",
        request_params={"q": "x"},
        api_key_hash="k" * 64,
        conn=conn,
    )

    assert conn.execute("SELECT COUNT(*) FROM usage_events").fetchone()[0] == 0
