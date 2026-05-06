"""Tests for POST /v1/intel/audit_chain composite endpoint.

The audit_chain endpoint merges three legacy reads into one POST so
監査担当者 (auditor / 税務調査官) can paste verify_chain booleans into a
監査調書 without 3 round trips and without re-implementing the verifier
fold themselves.

Coverage:
    1. Happy path — known epid returns merkle.root + proof_path +
       source_urls (with content_hash + fetched_at) + verify_chain with
       all 5 steps + corpus_snapshot_id + audit_seal + _disclaimer +
       _billing_unit:1.
    2. 404 — unknown epid returns a structured detail (not a 500), so
       the customer LLM can recover without retrying.
    3. 400 — malformed evidence_packet_id (no 'evp_' prefix) returns
       422 from pydantic field validation BEFORE the regex check fires.

The fixture builds a 2-leaf Merkle tree in a tmp autonomath.db slice so
proof_path verification has a real sibling to walk against.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def seeded_audit_merkle_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_db: Path,
) -> tuple[Path, str, str]:
    """Build a 2-leaf Merkle tree in a tmp autonomath.db.

    Returns (db_path, target_epid, root_hex) where target_epid is the
    leaf at index 0 (the leaf the test will query).

    The tree uses the same Bitcoin-style folding as the cron + the
    /v1/audit/proof endpoint so the verify_chain step3 returns True.
    """
    db_path = tmp_path / "autonomath.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE audit_merkle_anchor (
            daily_date          TEXT PRIMARY KEY,
            row_count           INTEGER NOT NULL,
            merkle_root         TEXT NOT NULL,
            ots_proof           BLOB,
            github_commit_sha   TEXT,
            twitter_post_id     TEXT,
            created_at          TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE audit_merkle_leaves (
            daily_date          TEXT NOT NULL,
            leaf_index          INTEGER NOT NULL,
            evidence_packet_id  TEXT NOT NULL,
            leaf_hash           TEXT NOT NULL,
            PRIMARY KEY (daily_date, leaf_index)
        );
        CREATE TABLE am_source (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url        TEXT NOT NULL UNIQUE,
            source_type       TEXT NOT NULL DEFAULT 'primary',
            domain            TEXT,
            is_pdf            INTEGER NOT NULL DEFAULT 0,
            content_hash      TEXT,
            first_seen        TEXT NOT NULL DEFAULT (datetime('now')),
            last_verified     TEXT,
            promoted_at       TEXT NOT NULL DEFAULT (datetime('now')),
            canonical_status  TEXT NOT NULL DEFAULT 'active',
            license           TEXT
        );
        """
    )

    daily_date = "2026-05-04"
    target_epid = "evp_audit_chain_target"
    sibling_epid = "evp_audit_chain_sibling"

    # Two leaves with deterministic, syntactically-valid hex hashes.
    leaf0 = hashlib.sha256(target_epid.encode()).hexdigest()
    leaf1 = hashlib.sha256(sibling_epid.encode()).hexdigest()
    # Bitcoin-style fold: parent = sha256(left_bytes || right_bytes).
    parent = hashlib.sha256(bytes.fromhex(leaf0) + bytes.fromhex(leaf1)).hexdigest()

    conn.execute(
        "INSERT INTO audit_merkle_anchor "
        "(daily_date, row_count, merkle_root, ots_proof, github_commit_sha, twitter_post_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            daily_date,
            2,
            parent,
            b"\x00\x01\x02ots-proof-blob",
            "abc123def456abc123def456abc123def456abcd",
            None,
        ),
    )
    conn.executemany(
        "INSERT INTO audit_merkle_leaves "
        "(daily_date, leaf_index, evidence_packet_id, leaf_hash) "
        "VALUES (?, ?, ?, ?)",
        [
            (daily_date, 0, target_epid, leaf0),
            (daily_date, 1, sibling_epid, leaf1),
        ],
    )
    conn.execute(
        "INSERT INTO am_source (source_url, content_hash, last_verified) VALUES (?, ?, ?)",
        (
            "https://nta.go.jp/example/notice.html",
            "sha256:fedcba9876543210",
            "2026-05-03T12:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("AUTONOMATH_DB_PATH", str(db_path))
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_path)
    return db_path, target_epid, parent


def _seed_audit_seal_with_url(seeded_db: Path, epid: str, url: str) -> None:
    """Seed one audit_seals row whose source_urls_json references the epid.

    Migration 089 + 119 may not be applied on the bare seeded_db, so we
    apply them via the same `IF NOT EXISTS` / ALTER swallow path used by
    other audit-seal tests.
    """
    repo = Path(__file__).resolve().parent.parent
    base = repo / "scripts" / "migrations"
    for mig in ("089_audit_seal_table.sql", "119_audit_seal_seal_id_columns.sql"):
        sql = (base / mig).read_text(encoding="utf-8")
        c = sqlite3.connect(seeded_db)
        try:
            with contextlib.suppress(sqlite3.OperationalError):
                # ALTER TABLE ADD COLUMN raises duplicate-column on re-run;
                # the entrypoint loop swallows the same way.
                c.executescript(sql)
            c.commit()
        finally:
            c.close()

    c = sqlite3.connect(seeded_db)
    c.execute(
        "INSERT INTO audit_seals "
        "(call_id, api_key_hash, ts, endpoint, query_hash, response_hash, "
        " source_urls_json, hmac, retention_until) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"call_{epid}",
            "hash_test_key",
            "2026-05-04T01:23:45+00:00",
            "intel.audit_chain",
            "qhash",
            "rhash",
            json.dumps([url, f"https://example.com/{epid}"], ensure_ascii=False),
            "deadbeef",
            "2033-05-04T01:23:45+00:00",
        ),
    )
    c.commit()
    c.close()


# ---------------------------------------------------------------------------
# Test 1: Happy path
# ---------------------------------------------------------------------------


def test_audit_chain_happy_path(client, seeded_db, seeded_audit_merkle_db):
    """Known epid returns full envelope with all 5 verify steps green."""
    _db_path, epid, expected_root = seeded_audit_merkle_db
    _seed_audit_seal_with_url(seeded_db, epid, "https://nta.go.jp/example/notice.html")

    resp = client.post(
        "/v1/intel/audit_chain",
        json={"evidence_packet_id": epid},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Top-level shape
    assert body["evidence_packet_id"] == epid
    assert body["_billing_unit"] == 1
    assert isinstance(body["_disclaimer"], str)
    assert "税理士法 §52" in body["_disclaimer"]
    assert "corpus_snapshot_id" in body

    # Merkle envelope
    merkle = body["merkle"]
    assert merkle["root"] == f"sha256:{expected_root}"
    assert merkle["leaf_index"] == 0
    assert merkle["daily_date"] == "2026-05-04"
    assert merkle["row_count"] == 2
    assert merkle["github_commit_sha"].startswith("abc123")
    assert merkle["github_commit_url"].startswith("https://github.com/")
    assert merkle["ots_url"] == "https://opentimestamps.org/"
    # The proof_path has exactly one sibling for a 2-leaf tree.
    assert len(merkle["proof_path"]) == 1
    assert merkle["proof_path"][0]["position"] in ("left", "right")

    # source_urls — the seal-seeded URL is enriched with am_source data,
    # the second seal URL has no am_source row so content_hash is null.
    urls = {u["url"]: u for u in body["source_urls"]}
    assert "https://nta.go.jp/example/notice.html" in urls
    enriched = urls["https://nta.go.jp/example/notice.html"]
    assert enriched["content_hash"] == "sha256:fedcba9876543210"
    assert enriched["fetched_at"] == "2026-05-03T12:00:00Z"

    # 5-step verify chain
    vc = body["verify_chain"]
    assert vc["step1_recompute_leaf"] is True
    assert vc["step2_walk_proof"] is True
    assert vc["step3_verify_root"] is True
    assert vc["step4_ots_verified"] == "https://opentimestamps.org/"
    assert vc["step5_github_anchor_found"] is True
    assert vc["all_steps_pass"] is True


# ---------------------------------------------------------------------------
# Test 2: 404 unknown epid (not yet anchored)
# ---------------------------------------------------------------------------


def test_audit_chain_unknown_epid_returns_404(client, seeded_audit_merkle_db):
    """Unknown but well-formed epid returns 404 with structured detail."""
    resp = client.post(
        "/v1/intel/audit_chain",
        json={"evidence_packet_id": "evp_does_not_exist_anywhere"},
    )
    assert resp.status_code == 404, resp.text
    body = resp.json()
    assert "evp_does_not_exist_anywhere" in body["detail"]
    assert "audit_merkle_leaves" in body["detail"]


# ---------------------------------------------------------------------------
# Test 3: malformed evidence_packet_id rejected before DB hit
# ---------------------------------------------------------------------------


def test_audit_chain_malformed_epid_rejected(client, seeded_audit_merkle_db):
    """Missing 'evp_' prefix is rejected by the regex (400) — never reaches DB."""
    resp = client.post(
        "/v1/intel/audit_chain",
        json={"evidence_packet_id": "not_an_epid_at_all"},
    )
    # The pydantic Field min_length/max_length passes (>=5 chars), so the
    # regex check inside the handler fires and returns 400.
    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert "evidence_packet_id" in body["detail"]
    assert "evp_" in body["detail"]
