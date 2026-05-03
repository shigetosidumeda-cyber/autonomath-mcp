"""会計士 work-paper bundle tests — 3 features, §47条の2 + §52 envelope.

Coverage focus
--------------

1. **Workpaper PDF** — POST /v1/audit/workpaper returns a PDF whose
   inline body contains the §47条の2 wording, the corpus_snapshot_id pin,
   and the auditor's sha256 manifest. WeasyPrint is preferred when
   available (the cache lands at data/workpapers/{api_key_id}_{period}.pdf);
   the hand-rolled PDF1.4 fallback still exposes the §47-2 disclaimer
   in plain ASCII.

2. **batch_evaluate** — POST /v1/audit/batch_evaluate over 5 client
   profiles × 1 ruleset = 5 evaluations → ¥3 × 1 unit (the K=10 fan-out
   factor lets a 5-cell batch bill as 1 unit; the asserts pin the
   per-yen math + the new ``kaikei_summary`` block + per-cell
   ``kaikei_fields`` rollup).

3. **cite_chain auto-resolve** — GET /v1/audit/cite_chain/{ruleset_id}
   returns a ≥2-level provenance tree (ruleset → law → 通達 / 質疑応答 /
   文書回答). Asserts the depth + that every seed citation is
   classified into one of the resolved kinds.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from jpintel_mcp.api.deps import hash_api_key
from jpintel_mcp.billing.keys import issue_key

_REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kaikei_key(seeded_db: Path) -> str:
    """Issue a paid key for /v1/audit/* (which is auth-gated)."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_kaikei_test",
        tier="paid",
        stripe_subscription_id="sub_kaikei_test",
    )
    c.commit()
    c.close()
    return raw


@pytest.fixture()
def kaikei_trial_key(seeded_db: Path) -> str:
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(c, customer_id="cus_kaikei_trial", tier="trial")
    c.commit()
    c.close()
    return raw


@pytest.fixture(autouse=True)
def _seed_tax_rulesets(seeded_db: Path):
    """Seed two tax_rulesets onto the test DB so audit endpoints have
    something to evaluate / chain. seeded_db's session-scoped init only
    loads schema.sql (no migration data), and tax_rulesets in particular
    is empty by default."""
    c = sqlite3.connect(seeded_db)
    try:
        # tax_rulesets table is part of schema.sql (loaded by seeded_db
        # session-scoped fixture). It carries CHECK constraints on
        # tax_category / ruleset_kind so the inserted values must
        # match the canonical enums (see schema.sql).
        c.executemany(
            """
            INSERT OR REPLACE INTO tax_rulesets (
                unified_id, ruleset_name, tax_category, ruleset_kind,
                effective_from, effective_until,
                related_law_ids_json,
                eligibility_conditions, eligibility_conditions_json,
                rate_or_amount, calculation_formula, filing_requirements,
                authority, source_url, fetched_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    "TAX-aaaaaaaaaa",
                    "テスト判定セット 2割特例",
                    "consumption",
                    "exemption",
                    "2024-04-01",
                    None,
                    json.dumps(["LAW-0123456789", "TSUTATSU-消基通-5-1-1"]),
                    "課税売上 5000万円以下の事業者を対象とする 2割特例。",
                    json.dumps(
                        {
                            "op": "lte",
                            "field": "annual_revenue_yen",
                            "value": 50_000_000,
                            "cite": ["LAW-0123456789"],
                        }
                    ),
                    "2割",
                    "課税売上 × 2割",
                    "確定申告書 別表",
                    "国税庁",
                    "https://www.nta.go.jp/",
                    "2026-04-29T00:00:00Z",
                    "2026-04-29T00:00:00Z",
                ),
                (
                    "TAX-bbbbbbbbbb",
                    "テスト判定セット 適格請求書発行事業者登録",
                    "consumption",
                    "registration",
                    "2023-10-01",
                    None,
                    json.dumps(["LAW-0123456789"]),
                    "適格請求書発行事業者登録の要件。",
                    json.dumps(
                        {
                            "op": "has_invoice_registration",
                            "field": "invoice_registration_number",
                        }
                    ),
                    "10%",
                    "売上 × 10%",
                    "適格請求書",
                    "国税庁",
                    "https://www.nta.go.jp/",
                    "2026-04-29T00:00:00Z",
                    "2026-04-29T00:00:00Z",
                ),
            ],
        )
        # Seed the matching law row so cite_chain LAW- resolution hits.
        # The laws table is part of schema.sql; only fill the columns
        # the resolver reads.
        c.execute(
            "INSERT OR REPLACE INTO laws (unified_id, law_title, "
            "law_short_title, law_number, law_type, ministry, "
            "full_text_url, source_url, fetched_at, updated_at) VALUES "
            "(?,?,?,?,?,?,?,?,?,?)",
            (
                "LAW-0123456789",
                "消費税法",
                "消費税法",
                "昭和63年法律第108号",
                "act",
                "財務省",
                "https://elaws.e-gov.go.jp/document?lawid=363AC0000000108",
                "https://elaws.e-gov.go.jp/document?lawid=363AC0000000108",
                "2026-04-29T00:00:00Z",
                "2026-04-29T00:00:00Z",
            ),
        )
        c.commit()
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 1. Workpaper PDF
# ---------------------------------------------------------------------------


def _idem_headers(api_key: str | None, suffix: str, **extra: str) -> dict[str, str]:
    headers = {"Idempotency-Key": f"kaikei-{suffix}"}
    if api_key is not None:
        headers["X-API-Key"] = api_key
    headers.update(extra)
    return headers


def test_audit_metered_routes_reject_anonymous(client):
    workpaper_payload = {
        "client_id": "client-anon-blocked",
        "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
        "business_profile": {"annual_revenue_yen": 30_000_000},
        "report_format": "pdf",
        "audit_period": "2026-Q1",
    }
    r = client.post(
        "/v1/audit/workpaper",
        headers=_idem_headers(None, "anon-workpaper"),
        json=workpaper_payload,
    )
    assert r.status_code == 401

    batch_payload = {
        "audit_firm_id": "firm-anon-blocked",
        "profiles": [
            {
                "client_id": "client-anon-001",
                "profile": {"annual_revenue_yen": 30_000_000},
            }
        ],
        "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
    }
    r = client.post(
        "/v1/audit/batch_evaluate",
        headers=_idem_headers(None, "anon-batch"),
        json=batch_payload,
    )
    assert r.status_code == 401

    r = client.get("/v1/audit/snapshot_attestation?year=2026")
    assert r.status_code == 401


def test_audit_metered_routes_reject_trial_key(client, kaikei_trial_key):
    r = client.get(
        "/v1/audit/snapshot_attestation?year=2026",
        headers=_idem_headers(
            kaikei_trial_key,
            "trial-attestation",
            **{"X-Cost-Cap-JPY": "30000"},
        ),
    )
    assert r.status_code == 402
    assert r.json()["detail"]["required_tier"] == "paid"


def test_snapshot_attestation_requires_idempotency_key(client, kaikei_key):
    r = client.get(
        "/v1/audit/snapshot_attestation?year=2026",
        headers={"X-API-Key": kaikei_key, "X-Cost-Cap-JPY": "30000"},
    )

    assert r.status_code == 428
    assert r.json()["detail"]["code"] == "idempotency_key_required"


def test_snapshot_attestation_idempotency_dedupes_billing(
    client, kaikei_key, seeded_db
):
    key_hash = hash_api_key(kaikei_key)
    headers = _idem_headers(
        kaikei_key,
        "snapshot-dedupe",
        **{"X-Cost-Cap-JPY": "30000"},
    )

    first = client.get("/v1/audit/snapshot_attestation?year=2026", headers=headers)
    assert first.status_code == 200, first.text
    second = client.get("/v1/audit/snapshot_attestation?year=2026", headers=headers)
    assert second.status_code == 200, second.text

    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT quantity FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'audit.snapshot_attestation'",
            (key_hash,),
        ).fetchall()
    finally:
        c.close()
    assert rows == [(10_000,)]


def test_snapshot_attestation_same_idempotency_key_rejects_changed_year(
    client, kaikei_key, seeded_db
):
    key_hash = hash_api_key(kaikei_key)
    headers = _idem_headers(
        kaikei_key,
        "snapshot-mismatch",
        **{"X-Cost-Cap-JPY": "30000"},
    )

    first = client.get("/v1/audit/snapshot_attestation?year=2026", headers=headers)
    assert first.status_code == 200, first.text
    second = client.get("/v1/audit/snapshot_attestation?year=2027", headers=headers)
    assert second.status_code == 409, second.text
    assert second.json()["error"] == "idempotency_key_in_use"

    c = sqlite3.connect(seeded_db)
    try:
        rows = c.execute(
            "SELECT quantity FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'audit.snapshot_attestation'",
            (key_hash,),
        ).fetchall()
    finally:
        c.close()
    assert rows == [(10_000,)]


def test_workpaper_pdf_contains_47_2_wording(client, kaikei_key):
    """PDF body (decoded base64) must contain the §47条の2 fence string.

    Both renderers (WeasyPrint UTF-8 PDF + the hand-rolled PDF1.4
    fallback) embed the boundary phrase. WeasyPrint encodes the kanji
    directly; the fallback writes the ASCII shim "Sec.47-2 boundary".
    Asserting BOTH substring forms keeps the test green on either path.
    """
    import base64

    r = client.post(
        "/v1/audit/workpaper",
        headers=_idem_headers(kaikei_key, "pdf-contains"),
        json={
            "client_id": "client-abc-001",
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
            "business_profile": {"annual_revenue_yen": 30_000_000},
            "report_format": "pdf",
            "audit_period": "2026-Q1",
            "max_cost_jpy": 33,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["report_format"] == "pdf"
    assert body["report_mime"] == "application/pdf"
    assert body["audit_period"] == "2026-Q1"
    assert body["api_key_id"]  # non-empty
    assert body["report_bytes_sha256"]
    assert body["corpus_snapshot_id"]
    pdf_bytes = base64.b64decode(body["report_inline_base64"])
    assert pdf_bytes.startswith(b"%PDF-")
    text = pdf_bytes.decode("latin-1", errors="replace")
    # Either the WeasyPrint UTF-8 path emits §47条の2 directly, or the
    # hand-rolled PDF1.4 fallback emits "Sec.47-2 boundary" / "Sec.47-2".
    has_kanji = "§47条の2" in text or "公認会計士法" in text
    has_ascii = "Sec.47-2" in text or "47-2" in text
    assert has_kanji or has_ascii, (
        "PDF must carry §47条の2 wording (WeasyPrint) or Sec.47-2 ASCII shim (PDF1.4 fallback)"
    )
    # Disclaimer envelope is also surfaced JSON-side so MCP / curl
    # consumers see it without parsing the PDF.
    assert "47条の2" in body["_disclaimer"]
    assert "47-2" in body["_disclaimer_en"]


def test_workpaper_pdf_cache_hit_is_free(client, kaikei_key, tmp_path):
    """Second call with same audit_period reads from cache + bills 0 units.

    The cache file lives at data/workpapers/{api_key_id}_{audit_period}.pdf —
    both calls share the same key so the second response should set
    pdf_cache_hit=True and units=0. Test runs work-relative, so we
    redirect the cache dir to tmp_path to keep the workspace clean.
    """
    # Force the cache dir relative to a tmp dir (so each test starts cold).
    cache_dir = tmp_path / "workpapers"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Simple monkeypatch: replace the module attr for the test scope.
    from jpintel_mcp.api import audit as _audit_mod

    orig = _audit_mod._WORKPAPER_CACHE_DIR
    _audit_mod._WORKPAPER_CACHE_DIR = cache_dir
    try:
        first = client.post(
            "/v1/audit/workpaper",
            headers=_idem_headers(kaikei_key, "cache-first"),
            json={
                "client_id": "client-cache-001",
                "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
                "business_profile": {"annual_revenue_yen": 30_000_000},
                "report_format": "pdf",
                "audit_period": "2026-Q2",
                "max_cost_jpy": 33,
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["billing"]["units"] >= 1  # cold render → bill

        # Only check the cache flow if WeasyPrint actually wrote a file.
        # The PDF1.4 fallback path does NOT cache (it writes nothing).
        cache_files = list(cache_dir.glob("*.pdf"))
        if not cache_files:
            pytest.skip("WeasyPrint not installed — fallback path skips cache")

        second = client.post(
            "/v1/audit/workpaper",
            headers=_idem_headers(kaikei_key, "cache-second"),
            json={
                "client_id": "client-cache-001",
                "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
                "business_profile": {"annual_revenue_yen": 30_000_000},
                "report_format": "pdf",
                "audit_period": "2026-Q2",
                "max_cost_jpy": 33,
            },
        )
        assert second.status_code == 200, second.text
        body = second.json()
        assert body["pdf_cache_hit"] is True
        assert body["billing"]["units"] == 0
        assert body["billing"]["cache_hit_free"] is True
    finally:
        _audit_mod._WORKPAPER_CACHE_DIR = orig


def test_workpaper_billing_failure_does_not_publish_pdf_cache(
    client, kaikei_key, tmp_path, monkeypatch
):
    cache_dir = tmp_path / "workpapers"

    from jpintel_mcp.api import audit as _audit_mod

    monkeypatch.setattr(_audit_mod, "_WORKPAPER_CACHE_DIR", cache_dir)

    def _fake_weasyprint(*, out_path: Path, **_kwargs) -> bool:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"%PDF-1.4\n% rendered before billing\n")
        return True

    def _fail_billing(*_args, **_kwargs):
        raise HTTPException(status_code=503, detail="billing unavailable")

    monkeypatch.setattr(_audit_mod, "_render_pdf_weasyprint", _fake_weasyprint)
    monkeypatch.setattr(_audit_mod, "log_usage", _fail_billing)

    response = client.post(
        "/v1/audit/workpaper",
        headers=_idem_headers(kaikei_key, "cache-billing-failure"),
        json={
            "client_id": "client-cache-fail-001",
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
            "business_profile": {"annual_revenue_yen": 30_000_000},
            "report_format": "pdf",
            "audit_period": "2026-Q2",
            "max_cost_jpy": 33,
        },
    )

    assert response.status_code == 503, response.text
    assert not list(cache_dir.glob("*.pdf"))
    assert not list(cache_dir.glob("*.tmp"))


def test_workpaper_unknown_ruleset_404(client, kaikei_key):
    """Unknown ruleset id → 404."""
    r = client.post(
        "/v1/audit/workpaper",
        headers=_idem_headers(kaikei_key, "unknown-ruleset"),
        json={
            "client_id": "client-unknown-1",
            "target_ruleset_ids": ["TAX-deadbeef00"],
            "business_profile": {},
        },
    )
    assert r.status_code == 404
    body = r.json()
    assert body["detail"]["error"] == "ruleset_not_found"
    assert body["detail"]["missing_ids"] == ["TAX-deadbeef00"]


def test_workpaper_records_full_quantity_in_usage_events(client, kaikei_key, seeded_db):
    """Cold workpaper billing must be one usage_events row with quantity=N."""
    r = client.post(
        "/v1/audit/workpaper",
        headers=_idem_headers(kaikei_key, "quantity"),
        json={
            "client_id": "client-quantity-001",
            "target_ruleset_ids": ["TAX-aaaaaaaaaa", "TAX-bbbbbbbbbb"],
            "business_profile": {"annual_revenue_yen": 30_000_000},
            "report_format": "md",
            "audit_period": "2026-Q3",
            "max_cost_jpy": 36,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["billing"]["units"] == 12

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT endpoint, quantity, metered FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'audit.workpaper' "
            "ORDER BY id DESC LIMIT 1",
            (hash_api_key(kaikei_key),),
        ).fetchone()
    finally:
        c.close()
    assert row == ("audit.workpaper", 12, 1)


def test_workpaper_requires_cost_cap(client, kaikei_key):
    r = client.post(
        "/v1/audit/workpaper",
        headers=_idem_headers(kaikei_key, "requires-cap"),
        json={
            "client_id": "client-requires-cap-001",
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
            "business_profile": {"annual_revenue_yen": 30_000_000},
            "report_format": "md",
            "audit_period": "2026-05",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "cost_cap_required"


def test_workpaper_low_cost_cap_rejects_before_billing(client, kaikei_key, seeded_db):
    key_hash = hash_api_key(kaikei_key)
    r = client.post(
        "/v1/audit/workpaper",
        headers=_idem_headers(kaikei_key, "low-cap", **{"X-Cost-Cap-JPY": "3"}),
        json={
            "client_id": "client-low-cap-001",
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
            "business_profile": {"annual_revenue_yen": 30_000_000},
            "report_format": "md",
            "audit_period": "2026-06",
        },
    )
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["code"] == "cost_cap_exceeded"

    c = sqlite3.connect(seeded_db)
    try:
        count = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = 'audit.workpaper'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        c.close()
    assert count == 0


def test_workpaper_multi_unit_cap_rejects_before_billing(client, kaikei_key, seeded_db):
    """Monthly caps must price the whole audit bundle, not just 1 request."""
    key_hash = hash_api_key(kaikei_key)
    c = sqlite3.connect(seeded_db)
    try:
        c.execute(
            "UPDATE api_keys SET monthly_cap_yen = ? WHERE key_hash = ?",
            (3, key_hash),
        )
        c.commit()
    finally:
        c.close()

    r = client.post(
        "/v1/audit/workpaper",
        headers=_idem_headers(kaikei_key, "multi-unit-cap"),
        json={
            "client_id": "client-cap-001",
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
            "business_profile": {"annual_revenue_yen": 30_000_000},
            "report_format": "md",
            "audit_period": "2026-Q4",
            "max_cost_jpy": 33,
        },
    )
    assert r.status_code == 503, r.text

    c = sqlite3.connect(seeded_db)
    try:
        count = c.execute(
            "SELECT COUNT(*) FROM usage_events WHERE key_hash = ? AND endpoint = 'audit.workpaper'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        c.close()
    assert count == 0


# ---------------------------------------------------------------------------
# 2. batch_evaluate — ¥3 × N math + kaikei_fields rollup
# ---------------------------------------------------------------------------


def test_batch_evaluate_5_clients_billing(client, kaikei_key):
    """5 profiles × 1 ruleset = 5 evaluations.

    With K=10 fan-out (¥3 ÷ 10 evals per unit), 5 evals ceil to 1 unit
    = ¥3. The endpoint also returns the new ``kaikei_summary`` block
    with per-risk-level counts, AND every cell in `results` carries a
    `kaikei_fields` rollup with workpaper_required / materiality_threshold
    / audit_risk fields populated.
    """
    profiles = [
        {"client_id": f"client-{i:03d}", "profile": {"annual_revenue_yen": rev}}
        for i, rev in enumerate([10_000_000, 30_000_000, 60_000_000, 80_000_000, 120_000_000])
    ]
    r = client.post(
        "/v1/audit/batch_evaluate",
        headers=_idem_headers(kaikei_key, "batch-5"),
        json={
            "audit_firm_id": "firm-test-1",
            "profiles": profiles,
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
            "max_cost_jpy": 3,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile_count"] == 5
    assert body["ruleset_count"] == 1
    assert body["evaluations"] == 5
    # K=10 fan-out: ceil(5/10) = 1 unit = ¥3.
    assert body["billing"]["units"] == 1
    assert body["billing"]["yen_excl_tax"] == 3
    assert body["billing"]["fan_out_factor"] == 10
    # kaikei_summary surfaces the audit-risk rollup.
    assert "kaikei_summary" in body
    assert set(body["kaikei_summary"]["audit_risk_counts"].keys()) == {
        "low",
        "medium",
        "high",
    }
    assert body["kaikei_summary"]["evaluations"] == 5
    # Every cell carries kaikei_fields.
    for entry in body["results"]:
        for cell in entry["results"]:
            kf = cell.get("kaikei_fields")
            assert kf is not None
            assert "workpaper_required" in kf
            assert "materiality_threshold" in kf
            assert "audit_risk" in kf
            assert kf["audit_risk"]["level"] in {"low", "medium", "high"}
    # §47条の2 envelope rendered JSON-side.
    assert "47条の2" in body["_disclaimer"]


def test_batch_evaluate_records_fanout_quantity(client, kaikei_key, seeded_db):
    """11 profile/ruleset evaluations ceil to quantity=2, not 1+direct Stripe."""
    profiles = [
        {"client_id": f"batch-q-{i:03d}", "profile": {"annual_revenue_yen": 1_000_000}}
        for i in range(11)
    ]
    r = client.post(
        "/v1/audit/batch_evaluate",
        headers=_idem_headers(kaikei_key, "batch-quantity"),
        json={
            "audit_firm_id": "firm-quantity-1",
            "profiles": profiles,
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
            "max_cost_jpy": 6,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["billing"]["units"] == 2

    c = sqlite3.connect(seeded_db)
    try:
        row = c.execute(
            "SELECT endpoint, quantity, metered FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'audit.batch_evaluate' "
            "ORDER BY id DESC LIMIT 1",
            (hash_api_key(kaikei_key),),
        ).fetchone()
    finally:
        c.close()
    assert row == ("audit.batch_evaluate", 2, 1)


def test_batch_evaluate_requires_cost_cap(client, kaikei_key):
    r = client.post(
        "/v1/audit/batch_evaluate",
        headers=_idem_headers(kaikei_key, "batch-requires-cap"),
        json={
            "audit_firm_id": "firm-requires-cap-1",
            "profiles": [
                {
                    "client_id": "client-requires-cap-001",
                    "profile": {"annual_revenue_yen": 30_000_000},
                }
            ],
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["code"] == "cost_cap_required"


def test_batch_evaluate_low_cost_cap_rejects_before_billing(client, kaikei_key, seeded_db):
    key_hash = hash_api_key(kaikei_key)
    r = client.post(
        "/v1/audit/batch_evaluate",
        headers=_idem_headers(kaikei_key, "batch-low-cap", **{"X-Cost-Cap-JPY": "0"}),
        json={
            "audit_firm_id": "firm-low-cap-1",
            "profiles": [
                {
                    "client_id": "client-low-cap-001",
                    "profile": {"annual_revenue_yen": 30_000_000},
                }
            ],
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
        },
    )
    assert r.status_code == 402, r.text
    assert r.json()["detail"]["code"] == "cost_cap_exceeded"

    c = sqlite3.connect(seeded_db)
    try:
        count = c.execute(
            "SELECT COUNT(*) FROM usage_events "
            "WHERE key_hash = ? AND endpoint = 'audit.batch_evaluate'",
            (key_hash,),
        ).fetchone()[0]
    finally:
        c.close()
    assert count == 0


def test_batch_evaluate_anomaly_detection(client, kaikei_key):
    """Profile that diverges from the population mode is flagged.

    4 of 5 profiles have annual_revenue_yen ≤ 50M (applicable=True for
    2割特例). The 5th has 120M (applicable=False). Population size ≥ 3
    + the deviation should produce one anomaly entry.
    """
    profiles = [
        {"client_id": "c-1", "profile": {"annual_revenue_yen": 10_000_000}},
        {"client_id": "c-2", "profile": {"annual_revenue_yen": 20_000_000}},
        {"client_id": "c-3", "profile": {"annual_revenue_yen": 30_000_000}},
        {"client_id": "c-4", "profile": {"annual_revenue_yen": 40_000_000}},
        {"client_id": "c-5", "profile": {"annual_revenue_yen": 120_000_000}},
    ]
    r = client.post(
        "/v1/audit/batch_evaluate",
        headers=_idem_headers(kaikei_key, "batch-anomaly"),
        json={
            "audit_firm_id": "firm-test-2",
            "profiles": profiles,
            "target_ruleset_ids": ["TAX-aaaaaaaaaa"],
            "max_cost_jpy": 3,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["anomalies"], "expected at least 1 anomaly for the 120M outlier"
    assert any(a["client_id"] == "c-5" for a in body["anomalies"])


# ---------------------------------------------------------------------------
# 3. cite_chain auto-resolve
# ---------------------------------------------------------------------------


def test_cite_chain_returns_multi_level_tree(client, kaikei_key):
    """GET /v1/audit/cite_chain/{ruleset_id} → ≥2-level tree.

    The seeded ruleset references a LAW + a TSUTATSU citation. The
    chain therefore has at least 2 distinct kinds at level 1 (law +
    tsutatsu). Depth ≥ 1 always; depth ≥ 2 when child cites surface
    via the NTA corpus walk (autonomath.db; the test DB does not
    necessarily have it, so we assert ≥1 and pin per-kind classification).
    """
    r = client.get(
        "/v1/audit/cite_chain/TAX-aaaaaaaaaa",
        headers={"X-API-Key": kaikei_key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ruleset"]["unified_id"] == "TAX-aaaaaaaaaa"
    assert body["seed_count"] >= 2  # LAW-0123456789 + TSUTATSU-消基通-5-1-1
    assert body["depth"] >= 1
    # Every level-1 node has a kind out of the supported set.
    seen_kinds = {n["kind"] for n in body["tree"]}
    assert seen_kinds <= {
        "law",
        "court_decision",
        "tsutatsu",
        "shitsugi",
        "bunsho_kaitou",
        "pending",
        "unknown",
    }
    # The LAW seed must resolve (we seeded the row).
    law_nodes = [n for n in body["tree"] if n["kind"] == "law"]
    assert law_nodes, "LAW-0123456789 should resolve to a 'law' kind node"
    assert law_nodes[0]["status"] == "resolved"
    assert law_nodes[0]["title"] == "消費税法"
    # §47条の2 envelope on the response.
    assert "47条の2" in body["_disclaimer"]
    assert body["billing"]["units"] == 1


def test_cite_chain_404_for_unknown_ruleset(client, kaikei_key):
    r = client.get(
        "/v1/audit/cite_chain/TAX-deadbeef00",
        headers={"X-API-Key": kaikei_key},
    )
    assert r.status_code == 404


def test_cite_chain_422_for_malformed_id(client, kaikei_key):
    # 14 chars but not the TAX-<10 hex> pattern (caps + extra dash)
    r = client.get(
        "/v1/audit/cite_chain/TAX-AAAAAAAAAA",
        headers={"X-API-Key": kaikei_key},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 4. MCP tool registration sanity
# ---------------------------------------------------------------------------


def test_mcp_tools_registered():
    """The 3 kaikei tools must appear on the FastMCP tool surface."""
    from jpintel_mcp.mcp.server import mcp

    names = {t.name for t in mcp._tool_manager.list_tools()}
    assert "compose_audit_workpaper" in names
    assert "audit_batch_evaluate" in names
    assert "resolve_citation_chain" in names


def test_mcp_tools_in_sensitive_set():
    """The 3 kaikei tools must be in the §47条の2 + §52 SENSITIVE_TOOLS set."""
    from jpintel_mcp.mcp.autonomath_tools.envelope_wrapper import SENSITIVE_TOOLS

    assert "compose_audit_workpaper" in SENSITIVE_TOOLS
    assert "audit_batch_evaluate" in SENSITIVE_TOOLS
    assert "resolve_citation_chain" in SENSITIVE_TOOLS
