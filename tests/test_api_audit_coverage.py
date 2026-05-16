"""Coverage push for `src/jpintel_mcp/api/audit.py` + `_audit_seal` helpers.

Stream UU — non-FastAPI, pure-function targets only. We touch the high-density
helpers that drive the seal/work-paper/CSV/MD rendering branches:

* `_audit_seal.build_seal` / `compute_hmac` / `verify_hmac` (seal value
  computation + binding + rotation across migration 089 / 119 schemas).
* `audit._audit_period_token` / `_api_key_id_redacted` / `_kaikei_*` /
  `_render_csv` / `_render_md` / `_render_pdf` (deterministic renderers).
* `lookup_seal` over a tmp_path SQLite seeded with migration 089 + 119
  schema (the public verify endpoint backbone).

NO FastAPI TestClient. NO LLM imports. NO Stripe. tmp_path + monkeypatch only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from jpintel_mcp.api import _audit_seal
from jpintel_mcp.api import audit as audit_mod
from jpintel_mcp.api._audit_seal import (
    build_seal,
    compute_hmac,
    extract_source_urls,
    lookup_seal,
    persist_seal,
    sign,
    verify,
    verify_hmac,
)

# ---------------------------------------------------------------------------
# Migration 089 + 119 seed helper for a fresh tmp SQLite.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MIG_089 = _REPO_ROOT / "scripts" / "migrations" / "089_audit_seal_table.sql"
_MIG_119 = _REPO_ROOT / "scripts" / "migrations" / "119_audit_seal_seal_id_columns.sql"


def _seed_audit_seals_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "audit.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Migration 089 — core schema (target_db: jpintel).
    conn.executescript(_MIG_089.read_text())
    # Migration 119 — ADD COLUMN seal_id + corpus_snapshot_id. The file
    # has line-comment blocks before each SQL statement; we strip the
    # comment prefix then split on `;` so each ALTER / CREATE INDEX lands.
    raw = _MIG_119.read_text()
    cleaned = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("--")
    )
    for stmt in cleaned.split(";"):
        s = stmt.strip()
        if not s:
            continue
        try:
            conn.execute(s)
        except sqlite3.OperationalError:
            # ADD COLUMN can be no-op on re-run; ignore.
            pass
    # Add the seal_persist_fail telemetry sibling table the source touches
    # so log_seal_persist_failure's `with contextlib.suppress` is exercised
    # without spurious noise.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS audit_log_section52 ("
        "  sampled_at TEXT, tool TEXT, request_hash TEXT, response_hash TEXT,"
        "  disclaimer_present INTEGER, advisory_terms_in_response TEXT,"
        "  violation INTEGER)"
    )
    # Migration 089 + 119 may leave a few columns nullable that the source
    # depends on; ensure key_version exists (some 089 variants omit it).
    cols = {r[1] for r in conn.execute("PRAGMA table_info(audit_seals)").fetchall()}
    if "key_version" not in cols:
        try:
            conn.execute("ALTER TABLE audit_seals ADD COLUMN key_version INTEGER")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


@pytest.fixture
def seal_db(tmp_path: Path) -> sqlite3.Connection:
    conn = _seed_audit_seals_db(tmp_path)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _stable_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the HMAC secret + clear the rotation key env var so every test
    starts from a deterministic single-key baseline."""
    monkeypatch.delenv("JPINTEL_AUDIT_SEAL_KEYS", raising=False)
    monkeypatch.setenv("AUDIT_SEAL_SECRET", "test_secret_v1")
    from jpintel_mcp import config

    monkeypatch.setattr(config.settings, "audit_seal_secret", "test_secret_v1")
    # Also reset the corpus-snapshot process cache so the tests do not see
    # a stale "corpus-YYYY-MM-DD" value from an earlier collection.
    _audit_seal._reset_corpus_snapshot_cache_for_tests()


# ---------------------------------------------------------------------------
# 1. seal value computation — audit_seal HMAC bind + sign/verify pair
# ---------------------------------------------------------------------------


def test_compute_hmac_deterministic() -> None:
    """Same inputs ⇒ same HMAC (constant-time stable)."""
    a = compute_hmac("c1", "2026-01-01T00:00:00+00:00", "qh", "rh")
    b = compute_hmac("c1", "2026-01-01T00:00:00+00:00", "qh", "rh")
    assert a == b
    assert isinstance(a, str)
    assert len(a) == 64  # sha256 hex


def test_verify_hmac_round_trip() -> None:
    sig = compute_hmac("call_x", "ts_x", "qh_x", "rh_x")
    assert verify_hmac("call_x", "ts_x", "qh_x", "rh_x", sig) is True
    # Flip one bit of expected_hmac → False.
    assert verify_hmac("call_x", "ts_x", "qh_x", "rh_x", "0" * 64) is False


def test_compute_hmac_binds_seal_id_and_snapshot() -> None:
    """seal_id + corpus_snapshot_id are part of the bound payload."""
    base = compute_hmac("c", "t", "q", "r")
    with_seal = compute_hmac(
        "c", "t", "q", "r", seal_id="seal_abc", corpus_snapshot_id="corpus-2026-05-16"
    )
    assert base != with_seal
    # Verify must use the same binding fields or it fails.
    assert verify_hmac("c", "t", "q", "r", with_seal) is False
    assert (
        verify_hmac(
            "c",
            "t",
            "q",
            "r",
            with_seal,
            seal_id="seal_abc",
            corpus_snapshot_id="corpus-2026-05-16",
        )
        is True
    )


def test_sign_verify_envelope() -> None:
    payload = b"the canonical bytes"
    env = sign(payload)
    assert env["alg"] == "HMAC-SHA256"
    assert env["key_version"] == 1
    assert verify(payload, env) is True
    # Tamper → False
    bad = dict(env)
    bad["sig"] = "f" * 64
    assert verify(payload, bad) is False


# ---------------------------------------------------------------------------
# 2. audit chain rotation — old seal verifies after rotation
# ---------------------------------------------------------------------------


def test_audit_chain_rotation_old_verifies_new_active(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rotation: v1 seal still verifies after v2 is added; new seals → v2."""
    payload = b"rotation-payload"
    v1_env = sign(payload)
    assert v1_env["key_version"] == 1

    rotated = json.dumps(
        [
            {"v": 1, "s": "test_secret_v1", "retired_at": "2026-05-15T00:00:00+00:00"},
            {"v": 2, "s": "rotated_secret_v2", "retired_at": None},
        ]
    )
    monkeypatch.setenv("JPINTEL_AUDIT_SEAL_KEYS", rotated)
    # Old v1 envelope still verifies.
    assert verify(payload, v1_env) is True
    # New active key is v2.
    v2_env = sign(payload)
    assert v2_env["key_version"] == 2
    assert v2_env["sig"] != v1_env["sig"]
    assert verify(payload, v2_env) is True


# ---------------------------------------------------------------------------
# 3. audit ledger append — persist_seal + lookup_seal round-trip
# ---------------------------------------------------------------------------


def test_build_seal_shape() -> None:
    """build_seal returns both legacy + §17.D customer-facing fields."""
    seal = build_seal(
        endpoint="programs.search",
        request_params={"q": "hello"},
        response_body={"ok": True, "source_url": "https://nta.go.jp/x"},
        client_tag="tenant-1",
        api_key_hash="abcd" * 16,
    )
    # §17.D fields
    assert seal["seal_id"].startswith("seal_")
    assert seal["subject_hash"].startswith("sha256:")
    assert seal["verify_endpoint"].startswith("/v1/audit/seals/")
    assert seal["key_hash_prefix"] == ("abcd" * 16)[:8]
    # Legacy fields
    assert len(seal["call_id"]) == 26
    assert seal["alg"] == "HMAC-SHA256"
    assert seal["client_tag"] == "tenant-1"
    # Source-url extraction walked the body.
    assert "https://nta.go.jp/x" in seal["source_urls"]


def test_persist_seal_and_lookup_round_trip(seal_db: sqlite3.Connection) -> None:
    """Insert one seal then look it up by seal_id."""
    seal = build_seal(
        endpoint="programs.search",
        request_params={"q": "foo"},
        response_body={"items": [{"source_url": "https://example.gov/a"}]},
        api_key_hash="khash" * 13,
    )
    persist_seal(seal_db, seal=seal, api_key_hash="khash" * 13)
    # Row exists.
    row = lookup_seal(seal_db, seal_id=seal["seal_id"])
    assert row is not None
    assert row["call_id"] == seal["call_id"]
    assert row["response_hash"] == seal["response_hash"]


def test_lookup_seal_missing(seal_db: sqlite3.Connection) -> None:
    """Unknown seal_id → None (caller renders 404)."""
    assert lookup_seal(seal_db, seal_id="seal_does_not_exist") is None


def test_extract_source_urls_walks_nested() -> None:
    """Extraction walks dict + list leaves, dedups, respects max_urls."""
    body = {
        "items": [
            {"source_url": "https://a.gov/x"},
            {"source_url": "https://a.gov/x"},  # duplicate
            {"primary_source_url": "https://b.gov/y"},
        ],
        "extra": {"source_urls": ["https://c.gov/z", "https://c.gov/z"]},
        "noise": "not a url",
    }
    out = extract_source_urls(body, max_urls=10)
    assert out == ["https://a.gov/x", "https://b.gov/y", "https://c.gov/z"]


# ---------------------------------------------------------------------------
# 4. audit.py pure renderer + kaikei helpers
# ---------------------------------------------------------------------------


def test_audit_period_token_default_year() -> None:
    """Empty period → falls back to current year (4-digit string)."""
    tok = audit_mod._audit_period_token(None)
    assert tok.isdigit()
    assert len(tok) == 4


def test_audit_period_token_sanitizes_dangerous_chars() -> None:
    """Slashes / dots stripped; ASCII alphanumerics + hyphen survive."""
    assert audit_mod._audit_period_token("2026-Q1") == "2026-Q1"
    assert audit_mod._audit_period_token("../../etc/passwd") == "etcpasswd"
    # Caller passes a >16-char token; we truncate to 16.
    assert len(audit_mod._audit_period_token("A" * 50)) == 16


def test_api_key_id_redacted_returns_anon_when_no_hash() -> None:
    class _Ctx:
        key_hash = None

    assert audit_mod._api_key_id_redacted(_Ctx()) == "anon"


def test_api_key_id_redacted_is_sha256_prefix() -> None:
    class _Ctx:
        key_hash = "the_full_key_hash"

    out = audit_mod._api_key_id_redacted(_Ctx())
    expected = hashlib.sha256(b"the_full_key_hash").hexdigest()[:16]
    assert out == expected


def test_kaikei_workpaper_required_branches() -> None:
    """workpaper_required True when applicable OR matched OR exclusion reason."""
    assert audit_mod._kaikei_workpaper_required({"applicable": True}) is True
    assert (
        audit_mod._kaikei_workpaper_required({"applicable": False, "conditions_matched": ["c1"]})
        is True
    )
    # Reason mentions 除外 → True (exclusion branch).
    assert (
        audit_mod._kaikei_workpaper_required(
            {"applicable": False, "conditions_matched": [], "reasons": ["除外: 大企業"]}
        )
        is True
    )
    # Nothing applicable, no matches, no exclusion-flavored reason → False.
    assert (
        audit_mod._kaikei_workpaper_required(
            {"applicable": False, "conditions_matched": [], "reasons": ["ok"]}
        )
        is False
    )


def test_kaikei_materiality_threshold_no_row() -> None:
    """ruleset_row=None → tier_unknown."""
    out = audit_mod._kaikei_materiality_threshold(None)
    assert out["tier"] == "tier_unknown"
    assert out["threshold_yen"] is None


def test_kaikei_audit_risk_anomaly_lifts_to_high() -> None:
    row = {
        "applicable": True,
        "conditions_matched": ["a", "b", "c"],
        "conditions_unmatched": ["x", "y"],
        "citation_tree": [{"a": 1}] * 5,
        "reasons": [],
    }
    out = audit_mod._kaikei_audit_risk(row, is_anomaly=True)
    assert out["level"] == "high"
    assert "anomaly_flag" in out["factors"]


def test_kaikei_audit_risk_low_when_clean() -> None:
    row = {
        "applicable": True,
        "conditions_matched": ["a"],
        "conditions_unmatched": [],
        "citation_tree": [],
        "reasons": [],
    }
    out = audit_mod._kaikei_audit_risk(row, is_anomaly=False)
    assert out["level"] == "low"
    assert out["score"] == 0


def test_render_csv_carries_disclaimer_and_brand() -> None:
    rows = [
        {
            "unified_id": "TAX-0000000001",
            "ruleset_name": "テスト税制",
            "applicable": True,
            "conditions_matched": ["c1"],
            "conditions_unmatched": [],
            "reasons": ["reason-a"],
            "citation_tree": [
                {"cite_id": "LAW-100", "status": "resolved"},
                {"cite_id": "LAW-200", "status": "unresolved"},
            ],
        }
    ]
    out = audit_mod._render_csv(
        client_id="c1",
        snapshot_id="corpus-2026-05-16",
        checksum="abc123",
        rows=rows,
    )
    s = out.decode("utf-8")
    assert "jpcite" in s
    assert "Bookyou株式会社" in s
    assert "TAX-0000000001" in s
    # citation_resolved_count = 1, citation_count = 2.
    assert ",2,1," in s
    # §52 disclaimer is on every csv row footer.
    assert "監査意見の根拠資料" in s


def test_render_md_includes_disclaimer_blocks_and_rows() -> None:
    rows = [
        {
            "unified_id": "TAX-0000000002",
            "ruleset_name": "テスト2",
            "applicable": False,
            "conditions_matched": [],
            "conditions_unmatched": ["c1"],
            "reasons": ["reason-b"],
            "citation_tree": [{"cite_id": "LAW-300", "status": "resolved", "title": "law"}],
        }
    ]
    out = audit_mod._render_md(
        client_id="c2",
        snapshot_id="corpus-2026-05-16",
        checksum="def456",
        rows=rows,
    )
    s = out.decode("utf-8")
    # Title block + brand + boundary clause + a citation line.
    assert s.startswith("# jpcite")
    assert "Bookyou株式会社" in s
    assert "§52 / §47条の2" in s
    assert "LAW-300" in s


def test_render_pdf_is_valid_pdf14_header() -> None:
    rows = [
        {
            "unified_id": f"TAX-{i:010d}",
            "ruleset_name": f"r{i}",
            "applicable": bool(i % 2),
            "conditions_matched": [],
            "conditions_unmatched": [],
            "reasons": [],
            "citation_tree": [],
        }
        for i in range(45)  # exercise >40 row cap branch
    ]
    out = audit_mod._render_pdf(
        client_id="c3",
        snapshot_id="corpus-x",
        checksum="check-x",
        rows=rows,
    )
    assert out.startswith(b"%PDF-1.")
    # Trailer marker present (hand-rolled PDF closes with %%EOF).
    assert b"%%EOF" in out
