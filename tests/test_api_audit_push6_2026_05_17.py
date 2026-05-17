"""Coverage push #6 — ``api.audit`` private helper bands not yet exercised.

CL15 task #276 — focus on the helper bands the prior UU stream skipped:
``_lookup_citation`` for LAW / HAN / TSUTATSU / SHITSUGI / BUNSHO / SAI /
PENDING resolution, the cite-cache LRU, ``_kaikei_fields`` composition,
``_workpaper_template_html`` rendering, ``_render_docx`` zip assembly,
``_base64_encode`` round-trip, ``_signed_url_for``, ``_audit_period_token``
extra branches, ``_require_high_value_idempotency_key`` raises, and the
``_non_metered_context`` / ``_usage_context_for_units`` ApiContext walk.

Rules (memory feedback):
* **NO LLM API import** — every test is pure-Python or tmp_path SQLite.
* **NO mock DB** — real SQLite seeded via direct SQL.
* New file only — never touches ``src/`` or other ``tests/`` files.
"""

from __future__ import annotations

import base64
import sqlite3
import zipfile
from io import BytesIO
from typing import TYPE_CHECKING

import pytest
from fastapi import HTTPException

from jpintel_mcp.api import audit as audit_mod
from jpintel_mcp.api.deps import ApiContext

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helper: build a tmp jpintel-side DB with the citation tables.
# ---------------------------------------------------------------------------


def _make_cite_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE laws (
            unified_id TEXT PRIMARY KEY,
            law_title TEXT,
            law_short_title TEXT,
            law_number TEXT,
            ministry TEXT,
            full_text_url TEXT,
            source_url TEXT
        );
        CREATE TABLE court_decisions (
            unified_id TEXT PRIMARY KEY,
            case_name TEXT,
            case_number TEXT,
            court TEXT,
            decision_date TEXT,
            precedent_weight TEXT,
            full_text_url TEXT,
            source_url TEXT
        );
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def cite_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = tmp_path / "cite.db"
    _make_cite_db(db)
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _reset_cite_cache() -> None:
    """Clear the module-local citation LRU before each test so the cache-hit
    counter starts from 0 and tests don't pollute each other."""
    audit_mod._CITE_CACHE.clear()


# ---------------------------------------------------------------------------
# _lookup_citation — LAW + HAN + TSUTATSU/QA/BUNSHO/SAI/PENDING + cache
# ---------------------------------------------------------------------------


def test_lookup_citation_law_resolved(cite_conn: sqlite3.Connection) -> None:
    cite_conn.execute(
        "INSERT INTO laws(unified_id, law_title, law_short_title, law_number, ministry, "
        "full_text_url, source_url) VALUES (?,?,?,?,?,?,?)",
        ("LAW-001", "法人税法", "法税", "S40-34", "MOF", "https://elaws.go.jp/law/001", None),
    )
    cite_conn.commit()
    out = audit_mod._lookup_citation(cite_conn, "LAW-001")
    assert out["kind"] == "law"
    assert out["status"] == "resolved"
    assert out["title"] == "法人税法"
    assert out["url"] == "https://elaws.go.jp/law/001"


def test_lookup_citation_law_unresolved_when_missing(cite_conn: sqlite3.Connection) -> None:
    out = audit_mod._lookup_citation(cite_conn, "LAW-MISSING")
    assert out["status"] == "unresolved"


def test_lookup_citation_court_decision_resolved(cite_conn: sqlite3.Connection) -> None:
    cite_conn.execute(
        "INSERT INTO court_decisions(unified_id, case_name, case_number, court, decision_date, "
        "precedent_weight, full_text_url, source_url) VALUES (?,?,?,?,?,?,?,?)",
        (
            "HAN-001",
            "ABC事件",
            "平成26年(行ヒ)第123号",
            "最高裁",
            "2014-04-01",
            "high",
            "https://courts.go.jp/h001",
            None,
        ),
    )
    cite_conn.commit()
    out = audit_mod._lookup_citation(cite_conn, "HAN-001")
    assert out["kind"] == "court_decision"
    assert out["status"] == "resolved"
    assert out["title"] == "ABC事件"
    assert out["court"] == "最高裁"


def test_lookup_citation_tsutatsu_unresolved_stub_when_no_autonomath(
    cite_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an autonomath connection the 通達 path returns a stub."""
    monkeypatch.setattr(audit_mod, "_nta_open", lambda: None)
    out = audit_mod._lookup_citation(cite_conn, "TSUTATSU-法基通-9-2-3")
    assert out["kind"] == "tsutatsu"
    assert out["status"] == "unresolved_pending_ingestion"


def test_lookup_citation_qa_unresolved_when_no_autonomath(
    cite_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit_mod, "_nta_open", lambda: None)
    out = audit_mod._lookup_citation(cite_conn, "QA-2024-100")
    assert out["kind"] == "shitsugi"
    assert out["status"] == "unresolved"


def test_lookup_citation_bunsho_unresolved_when_no_autonomath(
    cite_conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit_mod, "_nta_open", lambda: None)
    out = audit_mod._lookup_citation(cite_conn, "BUNSHO-2024-x1")
    assert out["kind"] == "bunsho_kaitou"
    assert out["status"] == "unresolved"


def test_lookup_citation_saiketsu_stub(cite_conn: sqlite3.Connection) -> None:
    out = audit_mod._lookup_citation(cite_conn, "SAI-2024-99")
    assert out["kind"] == "saiketsu"
    assert out["status"] == "unresolved_pending_ingestion"


def test_lookup_citation_pending_carries_text(cite_conn: sqlite3.Connection) -> None:
    out = audit_mod._lookup_citation(cite_conn, "PENDING:消費税法第30条")
    assert out["kind"] == "pending"
    assert out["title"] == "消費税法第30条"
    assert out["status"] == "unresolved_pending_text_match"


def test_lookup_citation_cache_hit_uses_lru(cite_conn: sqlite3.Connection) -> None:
    """A second lookup hits the in-process LRU rather than the DB."""
    cite_conn.execute(
        "INSERT INTO laws(unified_id, law_title) VALUES (?,?)",
        ("LAW-CACHE", "Test"),
    )
    cite_conn.commit()
    a = audit_mod._lookup_citation(cite_conn, "LAW-CACHE")
    assert a["status"] == "resolved"
    # Drop the row and confirm the cache still answers the same payload.
    cite_conn.execute("DELETE FROM laws WHERE unified_id = ?", ("LAW-CACHE",))
    cite_conn.commit()
    b = audit_mod._lookup_citation(cite_conn, "LAW-CACHE")
    assert b is a  # same dict from the cache


# ---------------------------------------------------------------------------
# _cache_citation eviction band
# ---------------------------------------------------------------------------


def test_cache_citation_evicts_when_full() -> None:
    """When the cache hits _CITE_CACHE_MAX, drop ~1/16 of keys on next insert."""
    audit_mod._CITE_CACHE.clear()
    # Fill the cache to capacity.
    for i in range(audit_mod._CITE_CACHE_MAX):
        audit_mod._cache_citation(f"LAW-{i:05d}", {"cite_id": f"LAW-{i:05d}"})
    assert len(audit_mod._CITE_CACHE) == audit_mod._CITE_CACHE_MAX
    audit_mod._cache_citation("LAW-evict-trigger", {"cite_id": "LAW-evict-trigger"})
    # After eviction the cache has shrunk by the deterministic 1/16 batch.
    assert len(audit_mod._CITE_CACHE) < audit_mod._CITE_CACHE_MAX
    assert "LAW-evict-trigger" in audit_mod._CITE_CACHE


# ---------------------------------------------------------------------------
# _kaikei_fields composition
# ---------------------------------------------------------------------------


def test_kaikei_fields_bundles_three_axes_consistently() -> None:
    row = {
        "applicable": True,
        "conditions_matched": ["c1", "c2"],
        "conditions_unmatched": ["c3"],
        "citation_tree": [{"cite_id": "LAW-1"}],
        "reasons": [],
    }
    out = audit_mod._kaikei_fields(row, None, is_anomaly=False)
    assert out["workpaper_required"] is True
    assert out["materiality_threshold"]["tier"] == "tier_unknown"
    assert "level" in out["audit_risk"]


def test_kaikei_materiality_threshold_high_tier_from_300m_marker() -> None:
    """Use a sqlite3.Row stand-in built from a real SELECT."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE rs (unified_id TEXT, ruleset_name TEXT, eligibility_conditions_json TEXT)"
    )
    conn.execute(
        "INSERT INTO rs VALUES (?,?,?)",
        ("TAX-x", "上限金額 3億円 制度", "[]"),
    )
    row = conn.execute("SELECT * FROM rs").fetchone()
    out = audit_mod._kaikei_materiality_threshold(row)
    assert out["tier"] == "tier_high"
    assert out["threshold_yen"] == 300_000_000
    conn.close()


def test_kaikei_materiality_threshold_mid_tier_from_30m_marker() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE rs (unified_id TEXT, ruleset_name TEXT, eligibility_conditions_json TEXT)"
    )
    conn.execute(
        "INSERT INTO rs VALUES (?,?,?)",
        ("TAX-x", "中小企業 3000万 上限", "[]"),
    )
    row = conn.execute("SELECT * FROM rs").fetchone()
    out = audit_mod._kaikei_materiality_threshold(row)
    assert out["tier"] == "tier_mid"
    conn.close()


def test_kaikei_audit_risk_medium_score() -> None:
    """Conditions ≥5 + cite_count <5 + non-anomaly → score=1 → medium."""
    row = {
        "applicable": True,
        "conditions_matched": ["a", "b", "c"],
        "conditions_unmatched": ["d", "e"],
        "citation_tree": [],
        "reasons": [],
    }
    out = audit_mod._kaikei_audit_risk(row, is_anomaly=False)
    assert out["level"] == "medium"


# ---------------------------------------------------------------------------
# _workpaper_template_html / _render_docx
# ---------------------------------------------------------------------------


def test_workpaper_template_html_renders_brand_and_rows() -> None:
    rows = [
        {
            "unified_id": "TAX-0000000abc",
            "ruleset_name": "テスト制度",
            "applicable": True,
            "conditions_matched": ["c1"],
            "conditions_unmatched": [],
            "citation_tree": [
                {"cite_id": "LAW-1", "title": "法税", "status": "resolved", "url": "https://x"}
            ],
            "kaikei_fields": {
                "workpaper_required": True,
                "materiality_threshold": {"tier": "tier_high", "threshold_yen": 300_000_000},
                "audit_risk": {"level": "medium", "score": 1},
            },
        }
    ]
    html = audit_mod._workpaper_template_html(
        client_id="c1",
        snapshot_id="corpus-2026-05-17",
        checksum="sha256:abc",
        rows=rows,
        audit_period="2026",
        api_key_id="kid-xyz",
    )
    assert "<!DOCTYPE html>" in html
    assert "jpcite" in html
    assert "Bookyou株式会社" in html
    assert "TAX-0000000abc" in html
    assert "LAW-1" in html
    # kaikei block surfaced.
    assert "調書記載要否" in html
    # Audit period + api_key_id surfaced on cover.
    assert "2026" in html
    assert "kid-xyz" in html


def test_workpaper_template_html_html_escapes_user_input() -> None:
    """HTML-injectable strings in ruleset_name come out as &lt;/&gt;."""
    rows = [
        {
            "unified_id": "TAX-x",
            "ruleset_name": "<script>alert('xss')</script>",
            "applicable": False,
            "conditions_matched": [],
            "conditions_unmatched": [],
            "citation_tree": [],
        }
    ]
    html = audit_mod._workpaper_template_html(
        client_id="c1",
        snapshot_id="snap",
        checksum="ck",
        rows=rows,
        audit_period="2026",
        api_key_id="kid",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_docx_is_valid_zip_with_document_xml() -> None:
    rows = [
        {
            "unified_id": "TAX-1",
            "ruleset_name": "test",
            "applicable": True,
            "conditions_matched": [],
            "conditions_unmatched": [],
            "reasons": [],
            "citation_tree": [],
        }
    ]
    out = audit_mod._render_docx(
        client_id="c1",
        snapshot_id="snap",
        checksum="ck",
        rows=rows,
    )
    assert isinstance(out, bytes)
    # Zip magic header.
    assert out[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(out)) as z:
        names = set(z.namelist())
        assert "word/document.xml" in names
        assert "[Content_Types].xml" in names
        assert "_rels/.rels" in names
        doc_xml = z.read("word/document.xml").decode("utf-8")
        assert "jpcite" in doc_xml
        assert "TAX-1" in doc_xml


# ---------------------------------------------------------------------------
# _base64_encode
# ---------------------------------------------------------------------------


def test_base64_encode_round_trips() -> None:
    payload = b"audit-attestation-bytes"
    encoded = audit_mod._base64_encode(payload)
    assert isinstance(encoded, str)
    assert base64.b64decode(encoded) == payload


def test_base64_encode_empty() -> None:
    assert audit_mod._base64_encode(b"") == ""


# ---------------------------------------------------------------------------
# _signed_url_for
# ---------------------------------------------------------------------------


def test_signed_url_for_includes_token_and_fmt() -> None:
    url = audit_mod._signed_url_for("abc123", "pdf")
    assert "/v1/audit/_workpaper_blob/abc123" in url
    assert "fmt=pdf" in url


def test_signed_url_for_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """When neither setting attribute is defined, helper uses the default base."""

    class _StubSettings:
        pass

    # The module reads `settings` at call time; replace with a bare stub so
    # both getattr lookups miss and the default branch runs.
    monkeypatch.setattr(audit_mod, "settings", _StubSettings())
    url = audit_mod._signed_url_for("xyz", "csv")
    assert url.startswith("https://api.jpcite.com/v1/audit/_workpaper_blob/xyz")
    assert "fmt=csv" in url


# ---------------------------------------------------------------------------
# _audit_period_token extra branches
# ---------------------------------------------------------------------------


def test_audit_period_token_keeps_yyyy_quarter_token() -> None:
    assert audit_mod._audit_period_token("2026-Q3") == "2026-Q3"


def test_audit_period_token_drops_to_year_when_only_unsafe_chars() -> None:
    """All-unsafe input (e.g. '////') sanitises to '' → falls back to year."""
    out = audit_mod._audit_period_token("////")
    assert out.isdigit()
    assert len(out) == 4


def test_audit_period_token_truncates_long_input() -> None:
    out = audit_mod._audit_period_token("Y" * 50)
    assert len(out) == 16
    assert out == "Y" * 16


# ---------------------------------------------------------------------------
# _require_high_value_idempotency_key raises
# ---------------------------------------------------------------------------


def test_require_high_value_idempotency_key_rejects_none() -> None:
    with pytest.raises(HTTPException) as exc:
        audit_mod._require_high_value_idempotency_key(None)
    assert exc.value.status_code == 428


def test_require_high_value_idempotency_key_rejects_whitespace() -> None:
    with pytest.raises(HTTPException) as exc:
        audit_mod._require_high_value_idempotency_key("   ")
    assert exc.value.status_code == 428


def test_require_high_value_idempotency_key_accepts_stripped() -> None:
    """Trailing whitespace is stripped."""
    assert audit_mod._require_high_value_idempotency_key("  abc123  ") == "abc123"


# ---------------------------------------------------------------------------
# _non_metered_context / _usage_context_for_units
# ---------------------------------------------------------------------------


def test_non_metered_context_flips_to_free_tier() -> None:
    paid = ApiContext(
        key_hash="kh",
        tier="paid",
        customer_id="cus-1",
        stripe_subscription_id="sub-1",
        key_id=42,
        parent_key_id=None,
    )
    free = audit_mod._non_metered_context(paid)
    assert free.tier == "free"
    assert free.stripe_subscription_id is None
    assert free.key_hash == "kh"
    assert free.customer_id == "cus-1"
    assert free.key_id == 42


def test_usage_context_for_units_zero_returns_non_metered() -> None:
    paid = ApiContext(
        key_hash="kh",
        tier="paid",
        customer_id="cus-1",
        stripe_subscription_id="sub-1",
    )
    free = audit_mod._usage_context_for_units(paid, 0)
    assert free.tier == "free"


def test_usage_context_for_units_positive_returns_same_ctx() -> None:
    paid = ApiContext(
        key_hash="kh",
        tier="paid",
        customer_id="cus-1",
        stripe_subscription_id="sub-1",
    )
    same = audit_mod._usage_context_for_units(paid, 7)
    assert same is paid
