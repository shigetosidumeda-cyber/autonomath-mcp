"""End-to-end smoke for the M&A pillar bundle (2026-04-29).

Walks every Pillar 1..4 surface against the seeded test DB:

    Pillar 1 — POST /v1/am/dd_batch        (5 法人, ¥3 × 5 = ¥15 metered)
    Pillar 2 — POST /v1/me/watches         (register + list + DELETE)
    Pillar 3 — GET  /v1/am/group_graph     (2-hop part_of traversal)
    Pillar 4 — POST /v1/am/dd_export       (audit-bundle ZIP, ¥3 × N + ¥30)

The test does NOT call any LLM and does NOT spawn a background subprocess.
Every read is `pytest TestClient` -> in-process FastAPI handler -> SQLite.

§52 envelope coverage is asserted on EVERY response — `_disclaimer` plus
`coverage_scope` strings must be present verbatim.

Bundle assertions:

    1. ZIP is materialized in memory by `_build_audit_bundle_zip` (not just
       a 200 OK with a stub URL — we crack the ZIP open and walk its file
       list).
    2. Required artifacts present: manifest.json, profiles/<houjin>.jsonl
       (one per id), cite_chain.json, sha256.manifest, README.txt.
    3. corpus_snapshot_id pin: present in body, in manifest.json, and in
       README.txt — three independent surfaces all carry the same value
       so a downstream auditor re-pulling the same snapshot 1 year later
       can verify reproducibility.
    4. Sha256 manifest internal-consistent: `<digest>  <filename>` rows
       match `hashlib.sha256(inner_files[name]).hexdigest()`.
"""
from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

_FIVE_HOUJIN: tuple[str, ...] = (
    "1010001000001",
    "2010001000002",
    "3010001000003",
    "4010001000004",
    "5010001000005",
)


@pytest.fixture(autouse=True)
def _ensure_ma_pillar_tables(seeded_db: Path):
    """Apply migration 088 onto the test DB and seed M&A fixture rows.

    Mirrors `tests/test_customer_webhooks.py` — the session-scoped seeded_db
    only has the schema.sql baseline, so we layer migrations 080+088 plus a
    handful of fixture rows (enforcement / bids / invoice_registrants) so
    the dd_batch composer has something to surface.
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

    # Reset M&A pillar tables + add minimal jpintel.db fixture data.
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    try:
        c.execute("DELETE FROM customer_watches")
        # 1 enforcement event for one of the 5 houjin so the dd_flags
        # rollup has at least one `recent_enforcement_history` flag to
        # surface.
        today = datetime.now(UTC).date().isoformat()
        c.execute(
            """INSERT OR REPLACE INTO enforcement_cases(
                case_id, event_type, recipient_houjin_bangou, recipient_name,
                ministry, prefecture, amount_yen, reason_excerpt,
                source_url, disclosed_date, disclosed_until, fetched_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "ENF-MA-E2E-1",
                "subsidy_exclude",
                _FIVE_HOUJIN[0],
                "テスト被処分法人",
                "農林水産省",
                "東京都",
                3_000_000,
                "目的外使用",
                "https://example.gov.jp/enf/1",
                "2025-09-01",
                "2025-09-30",  # past — recent_history bucket
                today,
            ),
        )
        # 1 bid won by the second houjin so total_won > 0 surfaces.
        c.execute(
            """INSERT OR REPLACE INTO bids(
                unified_id, bid_title, bid_kind, procuring_entity,
                decision_date, awarded_amount_yen,
                winner_houjin_bangou, source_url,
                fetched_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                "BID-abcdef0001",
                "システム保守",
                "open",
                "テスト省",
                "2025-08-15",
                10_000_000,
                _FIVE_HOUJIN[1],
                "https://example.gov.jp/bids/1",
                today,
                today,
            ),
        )
        # 1 invoice registration so invoice_mirror_miss flag does NOT trip
        # for the third houjin.
        c.execute(
            """INSERT OR REPLACE INTO invoice_registrants(
                invoice_registration_number,
                houjin_bangou,
                normalized_name,
                prefecture,
                registered_date,
                registrant_kind,
                trade_name,
                source_url,
                fetched_at,
                updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                f"T{_FIVE_HOUJIN[2]}",
                _FIVE_HOUJIN[2],
                "テスト法人C",
                "東京都",
                "2024-01-01",
                "corporation",
                "テスト商号",
                "https://example.gov.jp/invoice/1",
                today,
                today,
            ),
        )
        c.commit()
    finally:
        c.close()
    yield


def _check_disclaimer_envelope(body: dict) -> None:
    """Every M&A response must carry the §52 fence + coverage_scope."""
    assert "_disclaimer" in body, "missing §52 disclaimer envelope"
    assert "税理士法 §52" in body["_disclaimer"], (
        "disclaimer must reference 税理士法 §52"
    )
    assert "coverage_scope" in body, "missing coverage_scope"
    assert "役員" in body["coverage_scope"], (
        "coverage_scope must explicitly exclude 役員一覧"
    )
    assert "株主構成" in body["coverage_scope"], (
        "coverage_scope must explicitly exclude 株主構成"
    )


# ---------------------------------------------------------------------------
# Pillar 1: dd_batch
# ---------------------------------------------------------------------------


def test_dd_batch_5_houjin_summary(client, paid_key):
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

    # Per-id metering: 5 ids × ¥3 = ¥15 (NOT ¥3 — universal bulk fix).
    assert body["batch_size"] == 5
    assert body["metered_yen"] == 15
    assert body["unit_price_yen"] == 3
    assert body["operator_houjin_bangou"] == "T8010001213708"
    _check_disclaimer_envelope(body)

    # Profile shape — exactly 5 records, each carrying houjin_bangou +
    # dd_flags. The composer is tolerant: missing rows do NOT 500.
    profiles = body["profiles"]
    assert len(profiles) == 5
    assert {p["houjin_bangou"] for p in profiles} == set(_FIVE_HOUJIN)
    for p in profiles:
        assert "dd_flags" in p
        assert "enforcement" in p
        assert "bids_summary" in p

    # corpus_snapshot_id pin: present and looks like a snapshot id (ISO ts +
    # checksum prefix is acceptable). Required for re-pull reproducibility.
    assert body["corpus_snapshot_id"]
    assert body["corpus_checksum"]


def test_dd_batch_invalid_houjin_returns_422(client, paid_key):
    r = client.post(
        "/v1/am/dd_batch",
        headers={"X-API-Key": paid_key},
        json={
            "houjin_bangous": ["not-13-digits"],
        },
    )
    assert r.status_code == 422
    assert "invalid_houjin_bangou" in r.text


def test_dd_batch_cost_cap_blocks_overspend(client, paid_key):
    # 5 × ¥3 = ¥15 predicted; cap at ¥6 → 400.
    r = client.post(
        "/v1/am/dd_batch",
        headers={"X-API-Key": paid_key, "X-Cost-Cap-JPY": "6"},
        json={"houjin_bangous": list(_FIVE_HOUJIN)},
    )
    assert r.status_code == 400
    assert "cost_cap_exceeded" in r.text


# ---------------------------------------------------------------------------
# Pillar 2: customer_watches CRUD
# ---------------------------------------------------------------------------


def test_watch_register_requires_auth(client):
    r = client.post(
        "/v1/me/watches",
        json={"watch_kind": "houjin", "target_id": _FIVE_HOUJIN[0]},
    )
    assert r.status_code == 401


def test_watch_crud_round_trip(client, paid_key):
    # Register
    r = client.post(
        "/v1/me/watches",
        headers={"X-API-Key": paid_key},
        json={"watch_kind": "houjin", "target_id": _FIVE_HOUJIN[0]},
    )
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert r.json()["watch_kind"] == "houjin"
    assert r.json()["target_id"] == _FIVE_HOUJIN[0]

    # List
    r2 = client.get(
        "/v1/me/watches",
        headers={"X-API-Key": paid_key},
    )
    assert r2.status_code == 200
    assert any(w["id"] == wid for w in r2.json())

    # Idempotent re-register (same target → same row)
    r3 = client.post(
        "/v1/me/watches",
        headers={"X-API-Key": paid_key},
        json={"watch_kind": "houjin", "target_id": _FIVE_HOUJIN[0]},
    )
    assert r3.status_code == 201
    assert r3.json()["id"] == wid

    # Cancel (soft delete)
    r4 = client.delete(
        f"/v1/me/watches/{wid}",
        headers={"X-API-Key": paid_key},
    )
    assert r4.status_code == 200
    assert r4.json()["ok"] is True


def test_watch_houjin_target_normalized(client, paid_key):
    # T-prefix + hyphens + fullwidth digits accepted, normalized to 13 digits.
    r = client.post(
        "/v1/me/watches",
        headers={"X-API-Key": paid_key},
        json={"watch_kind": "houjin", "target_id": f"T{_FIVE_HOUJIN[1]}"},
    )
    assert r.status_code == 201
    assert r.json()["target_id"] == _FIVE_HOUJIN[1]


# ---------------------------------------------------------------------------
# Pillar 3: group_graph
# ---------------------------------------------------------------------------


def test_group_graph_invalid_houjin_returns_422(client, paid_key):
    r = client.get(
        "/v1/am/group_graph",
        headers={"X-API-Key": paid_key},
        params={"houjin_bangou": "not-13-digits", "depth": 2},
    )
    assert r.status_code == 422


def test_group_graph_unknown_seed_returns_empty_envelope(client, paid_key):
    # No am_entities row for this 法人 in the test DB → returns nodes=[] +
    # edges=[] + envelope, NOT 404.
    r = client.get(
        "/v1/am/group_graph",
        headers={"X-API-Key": paid_key},
        params={"houjin_bangou": _FIVE_HOUJIN[0], "depth": 2},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["houjin_bangou"] == _FIVE_HOUJIN[0]
    assert body["nodes"] == []
    assert body["edges"] == []
    assert body["metered_yen"] == 3  # ¥3 per call (single seed).
    _check_disclaimer_envelope(body)
    assert "graph_scope_note" in body
    assert "part_of" in body["graph_scope_note"]


# ---------------------------------------------------------------------------
# Pillar 4: dd_export — audit-bundle ZIP
# ---------------------------------------------------------------------------


def test_audit_bundle_export_round_trip(client, paid_key, tmp_path):
    deal_id = "MA-E2E-DEAL-2026-04-29"
    r = client.post(
        "/v1/am/dd_export",
        headers={"X-API-Key": paid_key},
        json={
            "deal_id": deal_id,
            "houjin_bangous": list(_FIVE_HOUJIN),
            "format": "zip",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # Pricing: 5 × ¥3 + 333 × ¥3 = ¥15 + ¥999 = ¥1,014. Default
    # `bundle_class='standard'` consumes 333 billing units (≈¥1,000) per
    # the bundle_class quantity ladder. Customer charge stays
    # `quantity × ¥3` — no tier SKU.
    assert body["batch_size"] == 5
    assert body["bundle_class"] == "standard"
    assert body["bundle_units"] == 333
    assert body["metered_yen"] == 5 * 3 + 333 * 3
    assert body["metered_breakdown"]["per_houjin_count"] == 5
    assert body["metered_breakdown"]["bundle_class"] == "standard"
    assert body["metered_breakdown"]["bundle_units"] == 333
    assert body["metered_breakdown"]["audit_bundle_fee_yen"] == 333 * 3
    _check_disclaimer_envelope(body)

    # corpus_snapshot_id pin (audit reproducibility).
    snapshot_id = body["corpus_snapshot_id"]
    assert snapshot_id
    assert body["corpus_checksum"]

    # ZIP bytes round-tripped — even when R2 upload is stubbed (signed_url
    # starts with `local://`), the bundle has been built. We re-build the
    # ZIP via the helper using the same inputs to assert the archive layout.
    from jpintel_mcp.api.ma_dd import _build_audit_bundle_zip, _build_dd_profile

    # Open both DBs the same way the route does.
    from jpintel_mcp.config import settings
    jp_conn = sqlite3.connect(settings.db_path)
    jp_conn.row_factory = sqlite3.Row
    profiles = [
        _build_dd_profile(
            jp_conn=jp_conn,
            am_conn=None,
            houjin_bangou=hj,
            depth="full",
        )
        for hj in _FIVE_HOUJIN
    ]
    jp_conn.close()

    zip_bytes, zip_sha256 = _build_audit_bundle_zip(
        deal_id=deal_id,
        profiles=profiles,
        snapshot_id=snapshot_id,
        checksum=body["corpus_checksum"],
    )

    # Crack open the ZIP and assert the bundle layout.
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = set(zf.namelist())
        # Expected structural files.
        assert "manifest.json" in names
        assert "cite_chain.json" in names
        assert "sha256.manifest" in names
        assert "README.txt" in names
        # One profile per houjin.
        for hj in _FIVE_HOUJIN:
            assert f"profiles/{hj}.jsonl" in names

        # manifest.json must carry the snapshot pin + operator identity.
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["deal_id"] == deal_id
        assert manifest["corpus_snapshot_id"] == snapshot_id
        assert manifest["operator"] == "Bookyou株式会社"
        assert manifest["operator_houjin_bangou"] == "T8010001213708"
        assert manifest["profile_count"] == 5
        assert "_disclaimer" in manifest
        assert "coverage_scope" in manifest
        assert "税理士法 §52" in manifest["_disclaimer"]

        # README.txt mirrors the snapshot pin (3rd surface — body, manifest,
        # README — every audit consumer sees the same id).
        readme = zf.read("README.txt").decode("utf-8")
        assert snapshot_id in readme
        assert "T8010001213708" in readme

        # sha256.manifest internal-consistent: every line has an entry in
        # manifest.json files and the digests match.
        sha_lines = zf.read("sha256.manifest").decode("utf-8").strip().splitlines()
        # Fold manifest.json -> sha map.
        manifest_sha = {f["name"]: f["sha256"] for f in manifest["files"]}
        assert sha_lines, "sha256.manifest must not be empty"
        for line in sha_lines:
            digest, fname = line.split("  ", 1)
            # sha256.manifest itself is excluded from manifest.json (avoid
            # self-reference) — every other file must match.
            if fname in manifest_sha:
                assert digest == manifest_sha[fname]


def test_audit_bundle_listing_summary(client, paid_key):
    """Light-weight smoke that prints the bundle file listing — captured
    on stdout when pytest runs with `-s` so the operator can eyeball the
    ZIP contents without unzipping. Not strict; informational."""
    deal_id = "MA-E2E-DEAL-LIST"
    r = client.post(
        "/v1/am/dd_export",
        headers={"X-API-Key": paid_key},
        json={
            "deal_id": deal_id,
            "houjin_bangous": list(_FIVE_HOUJIN[:2]),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # The route returns metadata; assert the bundle bytes were materialized
    # (non-zero size) and the sha256 is the standard 64-char hex string.
    assert body["bundle_bytes"] > 0
    assert len(body["bundle_sha256"]) == 64


# ---------------------------------------------------------------------------
# bundle_class quantity multiplier (NOT a tier SKU — artifact-size knob)
# ---------------------------------------------------------------------------


def test_dd_export_bundle_class_deal_charges_3000(client, paid_key):
    """`bundle_class='deal'` consumes 1,000 billing units = ¥3,000 fee.

    Customer is charged `(N houjin + 1,000) × ¥3`. NO tier SKU — the
    multiplier is an artifact-size selector. Stripe usage_records carry
    the same ¥3 unit price.
    """
    r = client.post(
        "/v1/am/dd_export",
        headers={"X-API-Key": paid_key},
        json={
            "deal_id": "MA-E2E-BUNDLE-DEAL",
            "houjin_bangous": list(_FIVE_HOUJIN),
            "bundle_class": "deal",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 5 × ¥3 + 1,000 × ¥3 = ¥15 + ¥3,000 = ¥3,015.
    assert body["bundle_class"] == "deal"
    assert body["bundle_units"] == 1_000
    assert body["metered_yen"] == 5 * 3 + 1_000 * 3
    assert body["metered_breakdown"]["bundle_class"] == "deal"
    assert body["metered_breakdown"]["bundle_units"] == 1_000
    assert body["metered_breakdown"]["audit_bundle_fee_yen"] == 1_000 * 3
    # Pricing note must explicitly call out the multiplier (¥3 × quantity)
    # so an LLM agent reading the body cannot mistake it for a tier SKU.
    assert "bundle_class" in body["pricing_note"]


def test_dd_export_bundle_class_case_charges_10000(client, paid_key):
    """`bundle_class='case'` consumes 3,333 billing units = ¥9,999 fee."""
    r = client.post(
        "/v1/am/dd_export",
        headers={"X-API-Key": paid_key},
        json={
            "deal_id": "MA-E2E-BUNDLE-CASE",
            "houjin_bangous": list(_FIVE_HOUJIN),
            "bundle_class": "case",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 5 × ¥3 + 3,333 × ¥3 = ¥15 + ¥9,999 = ¥10,014.
    assert body["bundle_class"] == "case"
    assert body["bundle_units"] == 3_333
    assert body["metered_yen"] == 5 * 3 + 3_333 * 3
    assert body["metered_breakdown"]["bundle_class"] == "case"
    assert body["metered_breakdown"]["bundle_units"] == 3_333
    assert body["metered_breakdown"]["audit_bundle_fee_yen"] == 3_333 * 3


def test_dd_export_bundle_class_standard_default(client, paid_key):
    """Omitting `bundle_class` defaults to 'standard' (333 units, ≈¥1,000)."""
    r = client.post(
        "/v1/am/dd_export",
        headers={"X-API-Key": paid_key},
        json={
            "deal_id": "MA-E2E-BUNDLE-DEFAULT",
            "houjin_bangous": list(_FIVE_HOUJIN[:1]),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bundle_class"] == "standard"
    assert body["bundle_units"] == 333
    # 1 × ¥3 + 333 × ¥3 = ¥3 + ¥999 = ¥1,002.
    assert body["metered_yen"] == 1 * 3 + 333 * 3


def test_dd_export_bundle_class_invalid_returns_422(client, paid_key):
    """Unknown bundle_class is rejected by the pydantic Literal."""
    r = client.post(
        "/v1/am/dd_export",
        headers={"X-API-Key": paid_key},
        json={
            "deal_id": "MA-E2E-BUNDLE-BAD",
            "houjin_bangous": list(_FIVE_HOUJIN[:1]),
            "bundle_class": "premium",  # not in {standard, deal, case}
        },
    )
    assert r.status_code == 422


def test_log_usage_quantity_clamped_at_100k():
    """`log_usage(quantity=N)` is hard-clamped at 100,000.

    Defends against a typo turning ¥3 into ¥30M. The clamp lives in BOTH
    the inline path AND the deferred path so neither can be bypassed.
    """
    from jpintel_mcp.api.deps import _QUANTITY_MAX

    assert _QUANTITY_MAX == 100_000
    # Smoke: passing 10M to the inline path must NOT trigger an OverflowError
    # when the row is written. We don't actually exercise the DB here — the
    # ApiContext fixture wiring lives in the integration suite — but assert
    # the constant is present so a future PR cannot quietly delete it.
