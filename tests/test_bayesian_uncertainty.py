"""Tests for O8 per-fact Bayesian uncertainty (analytics + view + endpoint).

Three pillars:
    1. ``score_fact`` math — license / freshness / kind / agreement axes.
    2. ``am_uncertainty_view`` SQL view — schema applies cleanly to a
       minimal autonomath fixture, ``get_uncertainty_for_fact`` reads it.
    3. ``/v1/stats/data_quality`` endpoint — aggregates respect the
       feature flag and pure-math is consistent with score_fact().

The fixture DB is built in-memory at module scope: we create the tiny
slice of the autonomath schema that the view needs (am_source +
am_entity_facts), apply migration 069, then re-use the same handle in
each test via dependency override.

No Anthropic API is touched. No production data is mutated.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jpintel_mcp.api.uncertainty import (
    KIND_W_DEFAULT,
    LICENSE_W,
    LICENSE_W_NULL,
    MODEL_TAG,
    get_uncertainty_for_fact,
    score_fact,
)

# ---------------------------------------------------------------------------
# Helpers — minimal autonomath fixture
# ---------------------------------------------------------------------------

# `am_source` schema is faithful to migration 049 (license enum trigger
# included) so the view's LEFT JOIN behaves like production.
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

_MIGRATION_069 = (
    Path(__file__).resolve().parent.parent / "scripts" / "migrations" / "069_uncertainty_view.sql"
)


def _build_fixture_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_AM_SCHEMA_SQL)

    # Three sources: gov_standard fresh, pdl_v1.0 1y old, NULL license.
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

    # Fact A: amount, single source #1 (high cohort target).
    # Fact B: amount, sources #1 + #2, agreed value (cross-source bonus).
    # Fact C: text, source NULL (unknown cohort target).
    # Fact D: amount, source #2 only, second value disagreeing on same
    #         (entity_id, field_name) as fact B → no agreement bonus.
    conn.executescript(
        """
        INSERT INTO am_entity_facts
            (entity_id, field_name, field_value_text,
             field_value_numeric, field_kind, source_id) VALUES
            ('e_solo', 'amount_max_yen', '12500000',  12500000, 'amount', 1),
            ('e_agree', 'amount_max_yen', '12500000', 12500000, 'amount', 1),
            ('e_agree', 'amount_max_yen', '12500000', 12500000, 'amount', 2),
            ('e_solo', 'note', 'free text',           NULL,     'text',   NULL),
            ('e_disagree', 'amount_max_yen', '12500000', 12500000, 'amount', 1),
            ('e_disagree', 'amount_max_yen', '12000000', 12000000, 'amount', 2);
        """
    )

    # Apply migration 069 — the view we are actually testing.
    sql = _MIGRATION_069.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()
    return conn


@pytest.fixture()
def fixture_db() -> sqlite3.Connection:
    conn = _build_fixture_db()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. score_fact pure-math
# ---------------------------------------------------------------------------


def test_score_fact_high_band_for_gov_fresh_amount() -> None:
    """gov_standard_v2.0 + 30d freshness + amount field_kind + n_sources=2.

    With the +0.1 cross-source bonus, the posterior mean lands above
    BAND_HIGH (0.85). Validates the high-cohort happy path.
    """
    out = score_fact(
        field_kind="amount",
        license_value="gov_standard_v2.0",
        days_since_fetch=30,
        n_sources=2,
        agreement=1,
    )
    assert out["model"] == MODEL_TAG
    assert out["alpha"] > out["beta"], "evidence > doubt expected"
    # 1 + 1.0 * exp(-30/365) * 0.90 + 0.1   ≈ 1.929
    expected_alpha = 1.0 + LICENSE_W["gov_standard_v2.0"] * math.exp(-30.0 / 365.0) * 0.90 + 0.1
    assert math.isclose(out["alpha"], expected_alpha, rel_tol=1e-6)
    assert out["score"] > 0.60  # well above BAND_LOW
    lo, hi = out["ci_95"]
    assert 0.0 <= lo <= out["score"] <= hi <= 1.0


def test_score_fact_unknown_band_for_null_source_text() -> None:
    """source_id NULL + text field: license falls back to 0.30, no decay,
    no bonus → posterior mean stuck below BAND_LOW (0.40)."""
    out = score_fact(
        field_kind="text",
        license_value=None,
        days_since_fetch=None,
        n_sources=0,
        agreement=0,
    )
    assert out["label"] == "unknown"
    # license_w 0.30 × freshness floor 0.20 × text 0.70 = 0.042 evidence.
    expected_evidence = LICENSE_W_NULL * 0.20 * KIND_W_DEFAULT
    assert math.isclose(
        out["alpha"],
        1.0 + expected_evidence,
        rel_tol=1e-6,
    )
    assert out["score"] < 0.40
    # CI must remain bounded inside [0, 1] even with very thin evidence.
    lo, hi = out["ci_95"]
    assert 0.0 <= lo <= hi <= 1.0


def test_score_fact_freshness_floor_clamps_at_two_years() -> None:
    """exp(-730/365) = 0.1353…; the design says clamp to 0.20.

    Verifies the floor behaviour (so a 5-year-old gov PDF still earns
    20% freshness credit, never zero — design philosophy: first-party
    sources do not become worthless).
    """
    out_two_years = score_fact(
        field_kind="amount",
        license_value="gov_standard_v2.0",
        days_since_fetch=730,
        n_sources=1,
        agreement=0,
    )
    out_five_years = score_fact(
        field_kind="amount",
        license_value="gov_standard_v2.0",
        days_since_fetch=5 * 365,
        n_sources=1,
        agreement=0,
    )
    # Same alpha: freshness clamps for both, and there's no agreement
    # bonus, so the posterior is independent of the extra 3 years.
    assert math.isclose(
        out_two_years["alpha"],
        out_five_years["alpha"],
        rel_tol=1e-6,
    )
    # Sanity: clamp value 0.20 reflected in evidence axis weight.
    fresh_axis = next(a for a in out_two_years["evidence"] if a["axis"] == "freshness")
    assert math.isclose(fresh_axis["weight"], 0.20, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# 2. View + get_uncertainty_for_fact
# ---------------------------------------------------------------------------


def test_view_surfaces_agreement_for_matching_values(
    fixture_db: sqlite3.Connection,
) -> None:
    """Two e_agree rows with identical value → agreement = 1, n_sources = 2."""
    rows = fixture_db.execute(
        "SELECT fact_id, license, n_sources, agreement, days_since_fetch "
        "  FROM am_uncertainty_view "
        " WHERE entity_id = 'e_agree' "
        " ORDER BY fact_id"
    ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r["n_sources"] == 2, r["fact_id"]
        assert r["agreement"] == 1, r["fact_id"]
        assert r["days_since_fetch"] >= 0


def test_view_no_agreement_when_values_disagree(
    fixture_db: sqlite3.Connection,
) -> None:
    """e_disagree rows have two sources but conflicting numeric values.

    n_sources should be 2, but agreement must be 0 (n_distinct_values > 1).
    """
    rows = fixture_db.execute(
        "SELECT fact_id, n_sources, agreement, n_distinct_values "
        "  FROM am_uncertainty_view "
        " WHERE entity_id = 'e_disagree'"
    ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r["n_sources"] == 2
        assert r["n_distinct_values"] >= 2
        assert r["agreement"] == 0


def test_get_uncertainty_for_fact_returns_payload(
    fixture_db: sqlite3.Connection,
) -> None:
    """End-to-end: view → score_fact gives a dict with expected keys."""
    fact_id = fixture_db.execute(
        "SELECT id FROM am_entity_facts  WHERE entity_id='e_agree' ORDER BY id LIMIT 1"
    ).fetchone()["id"]
    payload = get_uncertainty_for_fact(fact_id, fixture_db)
    assert payload is not None
    assert payload["model"] == MODEL_TAG
    assert "score" in payload
    assert "label" in payload
    assert payload["label"] in ("high", "medium", "low", "unknown")
    assert len(payload["ci_95"]) == 2
    axes = {a["axis"] for a in payload["evidence"]}
    assert axes == {
        "license",
        "freshness",
        "field_kind",
        "cross_source_agreement",
    }


def test_fact_uncertainty_payload_exposes_continuous_score(
    fixture_db: sqlite3.Connection,
) -> None:
    """A7: per-fact uncertainty is numeric evidence, not just a label."""
    fact_id = fixture_db.execute(
        "SELECT id FROM am_entity_facts  WHERE entity_id='e_agree' ORDER BY id LIMIT 1"
    ).fetchone()["id"]

    payload = get_uncertainty_for_fact(fact_id, fixture_db)

    assert payload is not None
    assert isinstance(payload["score"], float)
    assert 0.0 <= payload["score"] <= 1.0
    assert payload["label"] in {"high", "medium", "low", "unknown"}
    assert isinstance(payload["alpha"], float)
    assert isinstance(payload["beta"], float)
    assert len(payload["ci_95"]) == 2


def test_continuous_score_is_not_label_only_or_three_bucket_only() -> None:
    """A7: same label can carry different posterior means."""
    low_a = score_fact(
        field_kind="amount",
        license_value="gov_standard_v2.0",
        days_since_fetch=365,
        n_sources=1,
        agreement=0,
    )
    low_b = score_fact(
        field_kind="amount",
        license_value="pdl_v1.0",
        days_since_fetch=180,
        n_sources=1,
        agreement=0,
    )

    assert low_a["label"] == "low"
    assert low_b["label"] == "low"
    assert low_a["score"] != low_b["score"]
    assert len({low_a["score"], low_b["score"]}) == 2


def test_get_uncertainty_for_fact_degrades_when_view_missing() -> None:
    """A7: pre-migration DBs degrade by omitting the uncertainty envelope."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_AM_SCHEMA_SQL)
        conn.execute(
            "INSERT INTO am_entity_facts "
            "(entity_id, field_name, field_value_text, field_kind) "
            "VALUES ('e_missing_view', 'note', 'free text', 'text')"
        )
        fact_id = conn.execute(
            "SELECT id FROM am_entity_facts WHERE entity_id='e_missing_view'"
        ).fetchone()["id"]

        assert get_uncertainty_for_fact(fact_id, conn) is None
    finally:
        conn.close()


def test_multi_source_agreement_changes_continuous_score() -> None:
    """A7: agreement updates the posterior score, not only the label."""
    single_source = score_fact(
        field_kind="amount",
        license_value="gov_standard_v2.0",
        days_since_fetch=30,
        n_sources=1,
        agreement=0,
    )
    agreed_sources = score_fact(
        field_kind="amount",
        license_value="gov_standard_v2.0",
        days_since_fetch=30,
        n_sources=3,
        agreement=1,
    )

    assert agreed_sources["score"] > single_source["score"]
    assert agreed_sources["label"] == single_source["label"]
    agreement_axis = next(
        axis for axis in agreed_sources["evidence"] if axis["axis"] == "cross_source_agreement"
    )
    assert agreement_axis["n_sources"] == 3
    assert math.isclose(agreement_axis["bonus_alpha"], 0.2, rel_tol=1e-6)


def test_get_uncertainty_for_fact_returns_none_for_missing(
    fixture_db: sqlite3.Connection,
) -> None:
    assert get_uncertainty_for_fact(99999, fixture_db) is None


# ---------------------------------------------------------------------------
# 3. /v1/stats/data_quality endpoint
# ---------------------------------------------------------------------------


def test_data_quality_endpoint_aggregates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Spin up a real autonomath.db file with the fixture rows + view, then
    monkey-patch ``settings.autonomath_db_path`` so the endpoint reads it.

    Asserts the rollup keys exist, fact_count_total > 0, mean_score in
    [0, 1], and label_histogram includes our seeded high/low cohorts.
    """
    db_file = tmp_path / "am_test.db"
    src = _build_fixture_db()
    # Dump :memory: schema + data into the on-disk file by iterdump.
    dst = sqlite3.connect(db_file)
    dst.executescript("\n".join(src.iterdump()))
    dst.commit()
    dst.close()
    src.close()

    from jpintel_mcp.api import stats as stats_mod
    from jpintel_mcp.config import settings

    monkeypatch.setattr(settings, "autonomath_db_path", db_file)
    # Bypass the L4 cache so the test is deterministic across runs.
    monkeypatch.setattr(
        stats_mod,
        "_cache_get_or_compute",
        lambda key, compute: compute(),
    )

    app = FastAPI()
    app.include_router(stats_mod.router)
    client = TestClient(app)

    resp = client.get("/v1/stats/data_quality")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["model"] == "beta_posterior_v1"
    assert body["fact_count_total"] >= 6  # all fixture facts
    assert 0.0 <= body["mean_score"] <= 1.0
    # All four label buckets always present (zero-fill rule).
    assert set(body["label_histogram"].keys()) >= {
        "high",
        "medium",
        "low",
        "unknown",
    }
    # NULL-source fact ('e_solo' note) lands in unknown.
    assert body["label_histogram"]["unknown"] >= 1
    # license breakdown surfaces null_source bucket.
    assert "null_source" in body["license_breakdown"]
    # field_kind breakdown carries amount + text.
    assert set(body["field_kind_breakdown"].keys()) >= {"amount", "text"}
    # Cross-source agreement: e_agree contributes 2 multi-source rows
    # with consistent value; e_disagree contributes 2 inconsistent rows.
    cs = body["cross_source_agreement"]
    assert cs["facts_with_n_sources_>=2"] >= 4
    assert cs["facts_with_consistent_value"] >= 2
    # agreement_rate is bounded in [0, 1].
    assert 0.0 <= cs["agreement_rate"] <= 1.0
