"""Tests for the public ROI calculator endpoint (`/v1/calculator/savings`).

Exercises:

- Envelope shape (every documented field is present, types are correct, the
  honest_caveat is non-empty and surfaces the required qualifiers).
- Unknown-model handling (must 422, never silently fall back to a wrong
  pricing tier).
- Honest-caveat content (verbatim phrases the marketing site relies on so
  the LLM agent can't strip the qualifier when summarising).

NO Anthropic API call. NO DB writes. The endpoint is pure arithmetic.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from jpintel_mcp.api import calculator as calc


def test_returns_valid_envelope(client: TestClient) -> None:
    """Happy path. All documented response fields are present + well-typed."""
    r = client.get(
        "/v1/calculator/savings",
        params={
            "model": "claude-opus-4-7",
            "queries_per_month": 6000,
            "domain_mix": "balanced",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    expected_top = {
        "model",
        "queries_per_month",
        "breakdown",
        "estimated_monthly_savings_usd",
        "estimated_monthly_savings_jpy",
        "jpcite_cost_jpy",
        "net_savings_jpy",
        "roi_pct",
        "honest_caveat",
        "methodology",
    }
    assert expected_top.issubset(body.keys()), sorted(set(body.keys()))

    assert body["model"] == "claude-opus-4-7"
    assert body["queries_per_month"] == 6000
    # ¥3.30 × 6000 = ¥19,800 exact (¥3 税別 + 10% JCT, locked at
    # project_autonomath_business_model).
    assert body["jpcite_cost_jpy"] == 19_800

    # Per-query token + USD breakdown surfaces honest math.
    bd = body["breakdown"]
    expected_bd = {
        "closed_input_tokens",
        "closed_output_tokens",
        "with_jpcite_input_tokens",
        "with_jpcite_output_tokens",
        "closed_usd_per_query",
        "with_jpcite_usd_per_query",
    }
    assert expected_bd.issubset(bd.keys())
    assert bd["closed_input_tokens"] > 0
    assert bd["with_jpcite_output_tokens"] < bd["closed_output_tokens"], (
        "with_jpcite output should be smaller — model quotes a cited row "
        "instead of speculating; if this regresses the bench input drifted."
    )
    assert bd["closed_usd_per_query"] > 0
    assert bd["with_jpcite_usd_per_query"] > 0

    # Methodology block must declare its source so auditors can verify.
    meta = body["methodology"]
    assert meta["benchmark"] == "JCRB-v1 50-question batch"
    assert meta["row_source"] in {"direct", "family_fallback"}
    assert meta["domain_mix"] == "balanced"
    assert meta["fx_rate_jpy_per_usd"] > 0

    # Sign discipline: net_savings = monthly_savings - jpcite_cost. JPY
    # math is integer, so equality (not approx) is exact.
    assert (
        body["net_savings_jpy"] == body["estimated_monthly_savings_jpy"] - body["jpcite_cost_jpy"]
    )
    # ROI = gross token-spend savings / jpcite metering cost (NOT net).
    # By design ROI can be POSITIVE even when net_savings is NEGATIVE — the
    # whole honest-framing point is: "your token savings are real, but they
    # do not cover ¥3/req on raw token math alone". For Opus + 6000 q/mo +
    # FX 150 we expect ROI ≈ 25-35% (positive) and net ≈ -¥14k (negative).
    assert body["roi_pct"] > 0, "Opus token savings should be positive USD."
    assert body["net_savings_jpy"] < 0, (
        "Token savings should NOT cover ¥3/req at Opus pricing — this is "
        "the honest framing the caveat warns about."
    )


def test_unknown_model_returns_422(client: TestClient) -> None:
    """Typo/unknown model must 422 — silent fallback would mis-quote."""
    r = client.get(
        "/v1/calculator/savings",
        params={
            "model": "claude-totally-fake-99",
            "queries_per_month": 100,
        },
    )
    assert r.status_code == 422, r.text


def test_honest_caveat_present(client: TestClient) -> None:
    """The honest_caveat is the load-bearing qualifier on this surface.

    It MUST contain (verbatim) the phrases the marketing site uses to
    cross-link methodology, so an LLM agent that fetches this endpoint can
    pass the qualifier through to the human user without paraphrasing it
    into something weaker.
    """
    r = client.get(
        "/v1/calculator/savings",
        params={"model": "gpt-5", "queries_per_month": 1000},
    )
    assert r.status_code == 200, r.text
    caveat = r.json()["honest_caveat"]

    assert isinstance(caveat, str) and len(caveat) > 100
    # Honest framing: explicit "estimated", explicit "individual results",
    # explicit "raw token math" non-amortisation, explicit methodology link.
    assert "estimated" in caveat
    assert "individual results may vary" in caveat
    assert "raw token math" in caveat.lower()
    # Customer should be able to find the full methodology page.
    assert "context-savings" in caveat


def test_compute_savings_pure_function_is_deterministic() -> None:
    """Same input → same output. Guards against a future I/O sneak-in."""
    a = calc.compute_savings(
        model="gemini-2.5-pro",
        queries_per_month=1234,
        domain_mix="tax_heavy",
        fx_rate=152.0,
    )
    b = calc.compute_savings(
        model="gemini-2.5-pro",
        queries_per_month=1234,
        domain_mix="tax_heavy",
        fx_rate=152.0,
    )
    assert a.model_dump() == b.model_dump()
