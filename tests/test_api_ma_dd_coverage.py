"""Coverage push for `src/jpintel_mcp/api/ma_dd.py`.

Stream UU — pure-function targets: 法人番号 normalisation, cost cap, DD profile
composer, audit-bundle ZIP assembler, source-receipt graph rollup, tier
evaluation via `_BUNDLE_CLASS_UNITS`. tmp_path + monkeypatch only.

NO FastAPI route exercise (the routes need full middleware + DB stack — out
of scope for an isolated coverage push). NO LLM imports. NO Stripe / R2.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException

from jpintel_mcp.api import ma_dd as md

# ---------------------------------------------------------------------------
# 1. _normalize_houjin — 13-digit canonical form
# ---------------------------------------------------------------------------


def test_normalize_houjin_strips_t_prefix_and_hyphens() -> None:
    assert md._normalize_houjin("T1234567890123") == "1234567890123"
    assert md._normalize_houjin("1234-567890-123") == "1234567890123"
    assert md._normalize_houjin("  1234567890123 ") == "1234567890123"


def test_normalize_houjin_accepts_fullwidth_digits() -> None:
    # Full-width digits NFKC-normalised to ASCII (13 digits).
    assert md._normalize_houjin("１２３４５６７８９０１２３") == "1234567890123"


def test_normalize_houjin_rejects_invalid() -> None:
    """Non-13-digit / non-numeric input returns None."""
    assert md._normalize_houjin(None) is None
    assert md._normalize_houjin("") is None
    assert md._normalize_houjin("12345") is None
    assert md._normalize_houjin("not-a-number") is None
    # 14 digits is too long.
    assert md._normalize_houjin("12345678901234") is None


# ---------------------------------------------------------------------------
# 2. Cost cap helpers — header parse + cap binding
# ---------------------------------------------------------------------------


def test_parse_cost_cap_header_int() -> None:
    assert md._parse_cost_cap_header("500") == 500


def test_parse_cost_cap_header_invalid_returns_none() -> None:
    assert md._parse_cost_cap_header(None) is None
    assert md._parse_cost_cap_header("") is None
    assert md._parse_cost_cap_header("not-int") is None
    assert md._parse_cost_cap_header("-1") is None


def test_check_cost_cap_passthrough_when_below() -> None:
    """No raise when predicted ≤ min(caps)."""
    # Just shouldn't raise.
    md._check_cost_cap(predicted_yen=50, header_cap=100, body_cap=200)
    md._check_cost_cap(predicted_yen=50, header_cap=None, body_cap=None)


def test_check_cost_cap_raises_400_when_over() -> None:
    """Predicted > smaller cap → 400 with cost_cap_exceeded envelope."""
    with pytest.raises(HTTPException) as ei:
        md._check_cost_cap(predicted_yen=300, header_cap=200, body_cap=None)
    assert ei.value.status_code == 400
    detail = ei.value.detail
    assert detail["error"]["code"] == "cost_cap_exceeded"
    assert detail["error"]["cost_cap_yen"] == 200


# ---------------------------------------------------------------------------
# 3. Tier evaluation — bundle class → quantity multiplier
# ---------------------------------------------------------------------------


def test_bundle_class_units_canonical_values() -> None:
    """Pricing memo: standard=333, deal=1000, case=3333 (¥3-multiplied)."""
    assert md._BUNDLE_CLASS_UNITS["standard"] == 333
    assert md._BUNDLE_CLASS_UNITS["deal"] == 1_000
    assert md._BUNDLE_CLASS_UNITS["case"] == 3_333
    # Legacy compat: _AUDIT_BUNDLE_FEE_YEN = standard × ¥3 = ¥999.
    assert md._AUDIT_BUNDLE_FEE_YEN == 333 * 3


def test_unit_price_is_3_yen() -> None:
    """¥3/req metered only (CLAUDE.md non-negotiable)."""
    assert md._UNIT_PRICE_YEN == 3


# ---------------------------------------------------------------------------
# 4. DD profile builder — uses tmp SQLite to drive the composer
# ---------------------------------------------------------------------------


def _make_tmp_dbs(tmp_path: Path) -> tuple[sqlite3.Connection, sqlite3.Connection]:
    """Build minimal tmp jpintel.db + autonomath.db schemas to drive
    `_build_dd_profile` through both the empty + populated branches.
    """
    # jpintel.db side — enforcement_cases / invoice_registrants / bids / case_studies.
    jp_conn = sqlite3.connect(tmp_path / "jpintel.db")
    jp_conn.row_factory = sqlite3.Row
    jp_conn.executescript(
        """
        CREATE TABLE enforcement_cases (
          recipient_houjin_bangou TEXT,
          source_url TEXT,
          unified_id TEXT,
          decided_at TEXT,
          action TEXT
        );
        CREATE TABLE invoice_registrants (
          houjin_bangou TEXT PRIMARY KEY,
          registered_at TEXT,
          status TEXT
        );
        CREATE TABLE bids (
          unified_id TEXT,
          winner_houjin_bangou TEXT,
          procuring_houjin_bangou TEXT,
          source_url TEXT,
          awarded_at TEXT,
          amount_yen INTEGER
        );
        CREATE TABLE case_studies (id INTEGER PRIMARY KEY);
        """
    )
    jp_conn.commit()

    # autonomath.db side — am_entities + am_amendment_diff.
    am_conn = sqlite3.connect(tmp_path / "am.db")
    am_conn.row_factory = sqlite3.Row
    am_conn.executescript(
        """
        CREATE TABLE am_entities (
          canonical_id TEXT PRIMARY KEY,
          record_kind TEXT NOT NULL,
          primary_name TEXT,
          source_topic TEXT,
          raw_json TEXT
        );
        CREATE TABLE am_amendment_diff (
          diff_id INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_id TEXT,
          field TEXT,
          before_value TEXT,
          after_value TEXT,
          source_url TEXT,
          captured_at TEXT
        );
        """
    )
    am_conn.commit()
    return jp_conn, am_conn


def test_build_dd_profile_empty_corpus(tmp_path: Path) -> None:
    """Empty tmp DBs → composer returns the canonical zero-row shape."""
    jp, am = _make_tmp_dbs(tmp_path)
    try:
        prof = md._build_dd_profile(
            jp_conn=jp, am_conn=am, houjin_bangou="1234567890123", depth="summary"
        )
        assert prof["houjin_bangou"] == "1234567890123"
        assert prof["entity"] is None
        assert prof["adoptions_summary"]["total"] == 0
        assert prof["enforcement"]["found"] is False
        assert prof["bids_summary"]["total_won"] == 0
        # Composer adds heuristic dd_flags (e.g. unknown_company /
        # no_adoption_history) when the corpus is empty — pin shape, not
        # value-by-value.
        assert isinstance(prof["dd_flags"], list)
    finally:
        jp.close()
        am.close()


def test_build_dd_profile_resolves_corporate_entity(tmp_path: Path) -> None:
    """Seed a corporate_entity + adoption row; composer returns hits."""
    jp, am = _make_tmp_dbs(tmp_path)
    try:
        hj = "1234567890123"
        am.execute(
            "INSERT INTO am_entities VALUES (?, ?, ?, ?, ?)",
            (
                "ce-001",
                "corporate_entity",
                "テスト株式会社",
                None,
                json.dumps(
                    {
                        "houjin_bangou": hj,
                        "name": "テスト株式会社",
                        "prefecture_name": "東京都",
                        "category": "manufacturing",
                    }
                ),
            ),
        )
        am.execute(
            "INSERT INTO am_entities VALUES (?, ?, ?, ?, ?)",
            (
                "ad-001",
                "adoption",
                "ものづくり補助金 2026 R2",
                "adoption",
                json.dumps({"houjin_bangou": hj, "program_name": "ものづくり補助金"}),
            ),
        )
        am.commit()

        prof = md._build_dd_profile(
            jp_conn=jp, am_conn=am, houjin_bangou=hj, depth="summary"
        )
        assert prof["entity"]["canonical_id"] == "ce-001"
        assert prof["entity"]["prefecture"] == "東京都"
        assert prof["adoptions_summary"]["total"] == 1
    finally:
        jp.close()
        am.close()


# ---------------------------------------------------------------------------
# 5. Source receipt graph — _build_audit_bundle_zip + cite_chain rollup
# ---------------------------------------------------------------------------


def test_build_audit_bundle_zip_gate_off_emits_all_profiles() -> None:
    """`apply_license_gate=False` writes every profile JSONL."""
    profiles = [
        {
            "houjin_bangou": "1111111111111",
            "license": "unknown",  # would be blocked under gate
            "publisher": "X",
            "source_url": "https://a.gov/x",
            "enforcement": {"recent_history": [{"source_url": "https://a.gov/x", "case_id": "C1"}]},
        },
        {
            "houjin_bangou": "2222222222222",
            "license": "cc_by_4.0",
            "enforcement": {"recent_history": []},
        },
    ]
    raw, sha_hex, gate = md._build_audit_bundle_zip(
        deal_id="DEAL-A",
        profiles=profiles,
        snapshot_id="corpus-2026-05-16",
        checksum="ck1",
        apply_license_gate=False,
    )
    # Valid zip.
    zf = zipfile.ZipFile(BytesIO(raw))
    names = set(zf.namelist())
    assert "profiles/1111111111111.jsonl" in names
    assert "profiles/2222222222222.jsonl" in names
    assert "manifest.json" in names
    assert "cite_chain.json" in names
    assert "sha256.manifest" in names
    # Gate summary mirrors the input shape.
    assert gate["allowed_count"] == 2
    assert gate["blocked_count"] == 0
    # SHA-256 is the hash of the whole ZIP bytes.
    assert sha_hex == hashlib.sha256(raw).hexdigest()
    # Cite-chain captured the enforcement url.
    chain = json.loads(zf.read("cite_chain.json").decode("utf-8"))
    assert any(c["url"] == "https://a.gov/x" for c in chain)


def test_build_audit_bundle_zip_gate_on_blocks_unknown_license() -> None:
    """`apply_license_gate=True` only writes JSONL for ALLOWED rows."""
    profiles = [
        {
            "houjin_bangou": "1111111111111",
            "license": "proprietary",  # blocked
            "enforcement": {},
        },
        {
            "houjin_bangou": "2222222222222",
            "license": "pdl_v1.0",  # allowed
            "publisher": "NTA",
            "source_url": "https://nta.go.jp/x",
            "fetched_at": "2026-05-16",
            "enforcement": {},
        },
    ]
    raw, _sha, gate = md._build_audit_bundle_zip(
        deal_id="DEAL-B",
        profiles=profiles,
        snapshot_id="corpus-2026-05-16",
        checksum="ck2",
        apply_license_gate=True,
    )
    zf = zipfile.ZipFile(BytesIO(raw))
    names = set(zf.namelist())
    assert "profiles/2222222222222.jsonl" in names
    assert "profiles/1111111111111.jsonl" not in names  # blocked row never leaks
    assert "MANIFEST.json" in names
    assert "attribution.txt" in names
    assert gate["allowed_count"] == 1
    assert gate["blocked_count"] == 1
    # Blocked-reason rollup carries the offending license value.
    assert gate["blocked_reasons"].get("proprietary") == 1
    # MANIFEST.json is the license_gate.v1 schema, NOT the file-map manifest.
    license_manifest = json.loads(zf.read("MANIFEST.json").decode("utf-8"))
    assert license_manifest["schema_version"] == "license_gate.v1"
    assert "policy" in license_manifest
    # Attribution line carries the CC-BY 4.0 §3 format.
    attribution = zf.read("attribution.txt").decode("utf-8")
    assert "出典:" in attribution
    assert "license=pdl_v1.0" in attribution


def test_audit_bundle_disclaimer_and_brand_in_manifest() -> None:
    """Every artifact carries the §52 disclaimer + brand identity."""
    raw, _sha, _gate = md._build_audit_bundle_zip(
        deal_id="DEAL-C",
        profiles=[{"houjin_bangou": "3333333333333", "license": "cc_by_4.0"}],
        snapshot_id="corpus-x",
        checksum="ck3",
        apply_license_gate=True,
    )
    zf = zipfile.ZipFile(BytesIO(raw))
    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["brand"] == "jpcite"
    assert manifest["operator"] == "Bookyou株式会社"
    assert manifest["operator_houjin_bangou"] == "T8010001213708"
    assert "本情報は税務助言ではありません" in manifest["_disclaimer"]
    # README references the §52 fence + coverage scope verbatim.
    readme = zf.read("README.txt").decode("utf-8")
    assert "§52" in readme or "税理士法" in readme
    assert "役員一覧" in readme  # coverage_scope negative-space text
