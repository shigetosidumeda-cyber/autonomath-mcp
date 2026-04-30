"""Citation Verifier tests (§8.2 + §28.9 No-Go #1).

Covers the pure verifier (substring + Japanese numeric-form match), the
SHA256 stability contract, the REST endpoint with monkeypatched fetch,
and the 422 fences (citation count + excerpt length).

Network is NEVER touched in this suite — every URL fetch is monkeypatched
through ``CitationVerifier.fetch_source``.
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from jpintel_mcp.billing.keys import issue_key
from jpintel_mcp.services.citation_verifier import CitationVerifier

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def verifier() -> CitationVerifier:
    """Fresh verifier per test — keeps the in-memory cache scoped."""
    return CitationVerifier()


@pytest.fixture()
def paid_key_for_citations(seeded_db: Path) -> str:
    """Dedicated paid key — the citations endpoint requires auth."""
    c = sqlite3.connect(seeded_db)
    c.row_factory = sqlite3.Row
    raw = issue_key(
        c,
        customer_id="cus_citation_test",
        tier="paid",
        stripe_subscription_id="sub_citation_test",
    )
    c.commit()
    c.close()
    return raw


# ---------------------------------------------------------------------------
# Test 1 — excerpt verbatim hit → verified
# ---------------------------------------------------------------------------


def test_verify_excerpt_hit_yields_verified(verifier: CitationVerifier) -> None:
    result = verifier.verify(
        {"excerpt": "AAA"},
        "noise prefix AAA noise suffix",
    )
    assert result["verification_status"] == "verified"
    assert result["matched_form"] == "AAA"
    assert result["error"] is None
    assert isinstance(result["source_checksum"], str)
    assert len(result["source_checksum"]) == 64  # sha256 hex


# ---------------------------------------------------------------------------
# Test 2 — excerpt absent → inferred (NOT verified, NOT unknown)
# ---------------------------------------------------------------------------


def test_verify_excerpt_absent_yields_inferred(verifier: CitationVerifier) -> None:
    result = verifier.verify(
        {"excerpt": "AAA"},
        "the source body talks about BBB and CCC, never the first one",
    )
    assert result["verification_status"] == "inferred"
    assert result["matched_form"] is None
    # Per §28.9 No-Go #1: an excerpt that fails to match must NOT silently
    # downgrade to verified via some other path. inferred = "we can't
    # prove the claim — caller decides whether to surface it".
    assert result["verification_status"] != "verified"


# ---------------------------------------------------------------------------
# Test 3 — numeric value matched as comma form
# ---------------------------------------------------------------------------


def test_verify_numeric_comma_form_yields_verified(
    verifier: CitationVerifier,
) -> None:
    result = verifier.verify(
        {"field_value": 5_000_000},
        "上限額は 5,000,000円 です。詳細は別表参照。",
    )
    assert result["verification_status"] == "verified"
    assert result["matched_form"] == "5,000,000円"
    assert result["error"] is None


# ---------------------------------------------------------------------------
# Test 4 — numeric value matched as 万 form
# ---------------------------------------------------------------------------


def test_verify_numeric_man_form_yields_verified(
    verifier: CitationVerifier,
) -> None:
    # Source uses '500万' (no 円). The verifier should still match.
    result = verifier.verify(
        {"field_value": 5_000_000},
        "補助金は最大500万まで支給される予定です",
    )
    assert result["verification_status"] == "verified"
    # Either '500万' or '500万円' could match first — both are accepted.
    assert result["matched_form"] in ("500万", "500万円")


# ---------------------------------------------------------------------------
# Test 5 — numeric value with NO form present → unknown
# ---------------------------------------------------------------------------


def test_verify_numeric_absent_yields_unknown(
    verifier: CitationVerifier,
) -> None:
    result = verifier.verify(
        {"field_value": 5_000_000},
        "本制度は上限額を別途定める。実額は事業計画で算出。",
    )
    assert result["verification_status"] == "unknown"
    assert result["matched_form"] is None
    # Numeric absence is "unknown" not "inferred" — no excerpt was supplied.
    # The distinction matters per §28.2 envelope.
    assert result["verification_status"] != "inferred"


# ---------------------------------------------------------------------------
# Test 6 — NFKC normalization (full-width digits + 全角空白)
# ---------------------------------------------------------------------------


def test_verify_nfkc_normalization_full_width_digits(
    verifier: CitationVerifier,
) -> None:
    # Source uses full-width digits ５００ and full-width 万 + 円.
    # Post-NFKC these become '500万円' so the verifier should hit.
    result = verifier.verify(
        {"field_value": 5_000_000},
        "上限額は ５００万円 です",  # full-width digits + a 全角空白
    )
    assert result["verification_status"] == "verified"
    # The form we report back is the half-width canonical form because
    # we generate forms in half-width and compare in normalized space.
    assert result["matched_form"] in ("500万", "500万円")


# ---------------------------------------------------------------------------
# Test 7 — SHA256 source_checksum stability across calls
# ---------------------------------------------------------------------------


def test_source_checksum_is_stable_across_calls(
    verifier: CitationVerifier,
) -> None:
    body = "上限額は 5,000,000円 です"
    r1 = verifier.verify({"excerpt": "5,000,000"}, body)
    r2 = verifier.verify({"excerpt": "5,000,000"}, body)
    r3 = verifier.verify({"field_value": 5_000_000}, body)
    assert r1["source_checksum"] == r2["source_checksum"]
    # Different claims against same body still get the same checksum —
    # checksum is over the source, not the claim.
    assert r1["source_checksum"] == r3["source_checksum"]


# ---------------------------------------------------------------------------
# Test 8 — REST endpoint with monkeypatched fetch_source
# ---------------------------------------------------------------------------


def test_rest_endpoint_with_monkeypatched_fetch(
    client,
    paid_key_for_citations: str,
    monkeypatch,
) -> None:
    """Hit POST /v1/citations/verify with a mix of citations.

    fetch_source is monkeypatched on the verifier class so no real HTTP
    happens. We expect: 5 verified / 2 inferred / 2 unknown (one with
    a fetch failure, one with no claim to verify).
    """
    fake_pages: dict[str, str | None] = {
        "https://example.com/a": "上限額は 5,000,000円 です。対象は中小企業。",
        "https://example.com/b": "対象事業者: 中小企業者 (法人 / 個人事業主)",
        "https://example.com/c": "本制度は補助率1/2で、上限500万円。",
        "https://example.com/d": "expense cap 500 man yen",  # no JP form, no excerpt match
        "https://example.com/e": "別途定める。実額は事業計画で算出。",
        "https://example.com/f": None,  # simulated 404 / unreachable
    }

    def _fake_fetch(self, url, timeout=5):  # noqa: ARG001
        return fake_pages.get(url)

    monkeypatch.setattr(
        "jpintel_mcp.services.citation_verifier.CitationVerifier.fetch_source",
        _fake_fetch,
    )

    payload = {
        "citations": [
            # 1. excerpt hit → verified
            {"source_url": "https://example.com/a", "excerpt": "5,000,000円"},
            # 2. excerpt hit on b → verified
            {"source_url": "https://example.com/b", "excerpt": "中小企業者"},
            # 3. numeric hit on c (500万円) → verified
            {"source_url": "https://example.com/c", "field_value": 5_000_000},
            # 4. excerpt + numeric, both hit on a → verified
            {
                "source_url": "https://example.com/a",
                "excerpt": "上限額",
                "field_value": 5_000_000,
            },
            # 5. excerpt hit on c → verified
            {"source_url": "https://example.com/c", "excerpt": "補助率1/2"},
            # 6. excerpt absent on d → inferred
            {"source_url": "https://example.com/d", "excerpt": "存在しない引用"},
            # 7. excerpt absent on e → inferred
            {"source_url": "https://example.com/e", "excerpt": "missing claim"},
            # 8. numeric absent on e → unknown
            {"source_url": "https://example.com/e", "field_value": 5_000_000},
            # 9. fetch fails on f → unknown (source_unreachable)
            {"source_url": "https://example.com/f", "excerpt": "AAA"},
        ]
    }

    r = client.post(
        "/v1/citations/verify",
        json=payload,
        headers={"X-API-Key": paid_key_for_citations},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["verified_count"] == 5
    assert body["inferred_count"] == 2
    assert body["unknown_count"] == 2
    assert len(body["verifications"]) == 9

    # Index round-trip: the order must be preserved.
    statuses = [v["verification_status"] for v in body["verifications"]]
    assert statuses == [
        "verified",
        "verified",
        "verified",
        "verified",
        "verified",
        "inferred",
        "inferred",
        "unknown",
        "unknown",
    ]
    # Last entry is the failed fetch — error string must surface.
    assert body["verifications"][-1]["error"] == "source_unreachable"


# ---------------------------------------------------------------------------
# Test 9 — > 10 citations → 422
# ---------------------------------------------------------------------------


def test_rest_endpoint_rejects_more_than_10_citations(
    client,
    paid_key_for_citations: str,
) -> None:
    payload = {
        "citations": [
            {"source_url": f"https://example.com/{i}", "excerpt": "x"}
            for i in range(11)
        ]
    }
    r = client.post(
        "/v1/citations/verify",
        json=payload,
        headers={"X-API-Key": paid_key_for_citations},
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# Test 10 — excerpt > 500 chars → 422
# ---------------------------------------------------------------------------


def test_rest_endpoint_rejects_long_excerpt(
    client,
    paid_key_for_citations: str,
) -> None:
    long_excerpt = "x" * 501
    payload = {
        "citations": [
            {
                "source_url": "https://example.com/a",
                "excerpt": long_excerpt,
            }
        ]
    }
    r = client.post(
        "/v1/citations/verify",
        json=payload,
        headers={"X-API-Key": paid_key_for_citations},
    )
    assert r.status_code == 422, r.text
