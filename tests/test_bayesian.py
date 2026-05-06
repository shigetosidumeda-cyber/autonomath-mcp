"""Tests for jpintel_mcp.analytics.bayesian (P5-attribution / Discovery+Use).

Coverage:
  1. beta_posterior arithmetic (flat prior + observed Bernoulli draws)
  2. beta_posterior input validation (negatives, hits>trials)
  3. confidence_interval_95 monotonicity (more trials → narrower band)
  4. confidence_interval_95 input validation (alpha/beta must be > 0)
  5. discovery_confidence per-tool aggregation + cohort split
  6. discovery_confidence treats result_count == 0 as miss
  7. discovery_confidence with empty input returns prior-only overall
  8. use_confidence — same key returning within 7 days = hit
  9. use_confidence — same key returning AFTER 7 days = miss
  10. use_confidence skips events without key_hash (anonymous)
  11. overall_confidence weights by trial count (chatty tool dominates)
"""

from __future__ import annotations

import math

import pytest

from jpintel_mcp.analytics.bayesian import (
    PRIOR_ALPHA,
    PRIOR_BETA,
    beta_posterior,
    confidence_interval_95,
    discovery_confidence,
    overall_confidence,
    use_confidence,
)

# ---------------------------------------------------------------------------
# beta_posterior
# ---------------------------------------------------------------------------


def test_beta_posterior_flat_prior_observed_80_of_100() -> None:
    """Beta(1,1) + 80 hit / 100 trial → Beta(81, 21).

    Posterior mean = 81/(81+21) = 0.794117…, comfortably above the 80%
    Use target so the math at least reads correctly when target_band
    bites.
    """
    a, b = beta_posterior(1.0, 1.0, 80, 100)
    assert a == 81.0
    assert b == 21.0
    mean = a / (a + b)
    assert math.isclose(mean, 81 / 102, rel_tol=1e-12)


def test_beta_posterior_zero_trials_returns_prior() -> None:
    a, b = beta_posterior(1.0, 1.0, 0, 0)
    assert (a, b) == (1.0, 1.0)


@pytest.mark.parametrize(
    ("hits", "trials"),
    [
        (-1, 10),
        (10, -1),
        (11, 10),
    ],
)
def test_beta_posterior_rejects_invalid(hits: int, trials: int) -> None:
    with pytest.raises(ValueError):
        beta_posterior(1.0, 1.0, hits, trials)


# ---------------------------------------------------------------------------
# confidence_interval_95
# ---------------------------------------------------------------------------


def test_ci95_more_trials_narrower_band() -> None:
    """As we accumulate evidence the 95% credible band must shrink."""
    a1, b1 = beta_posterior(1.0, 1.0, 8, 10)  # n=10
    a2, b2 = beta_posterior(1.0, 1.0, 80, 100)  # n=100
    a3, b3 = beta_posterior(1.0, 1.0, 800, 1000)  # n=1000
    lo1, hi1 = confidence_interval_95(a1, b1)
    lo2, hi2 = confidence_interval_95(a2, b2)
    lo3, hi3 = confidence_interval_95(a3, b3)
    assert (hi1 - lo1) > (hi2 - lo2) > (hi3 - lo3)
    # All three centred near 0.8 so the lower bound rises with n.
    assert lo1 < lo2 < lo3
    # Sanity: every interval clamped inside [0, 1].
    for lo, hi in [(lo1, hi1), (lo2, hi2), (lo3, hi3)]:
        assert 0.0 <= lo <= hi <= 1.0


def test_ci95_known_value_80_of_100() -> None:
    """Spot-check 80/100 against the documented sample run.

    The CI half-width for Beta(81,21) sits around 0.077 — i.e. the
    band is roughly [0.71, 0.86], which is what the public dashboard
    will show next to the 0.79 mean.
    """
    a, b = beta_posterior(1.0, 1.0, 80, 100)
    lo, hi = confidence_interval_95(a, b)
    assert 0.70 < lo < 0.74
    assert 0.84 < hi < 0.87


def test_ci95_rejects_non_positive() -> None:
    with pytest.raises(ValueError):
        confidence_interval_95(0.0, 1.0)
    with pytest.raises(ValueError):
        confidence_interval_95(1.0, -0.5)


# ---------------------------------------------------------------------------
# discovery_confidence
# ---------------------------------------------------------------------------


def test_discovery_per_tool_aggregation() -> None:
    rows = [
        # programs.search: 7/10 hits
        *[{"tool": "programs.search", "result_count": 5, "cohort": "smb"} for _ in range(7)],
        *[{"tool": "programs.search", "result_count": 0, "cohort": "smb"} for _ in range(3)],
        # enforcement.search: 1/2 hits, mixed cohort
        {"tool": "enforcement.search", "result_count": 1, "cohort": "vc"},
        {
            "tool": "enforcement.search",
            "result_count": 0,
            "cohort": "developer",
        },
    ]
    out = discovery_confidence(rows)
    by_tool = {r["tool"]: r for r in out["per_tool"]}
    assert by_tool["programs.search"]["hits"] == 7
    assert by_tool["programs.search"]["trials"] == 10
    # Posterior mean = (1+7)/(1+1+10) = 8/12 ≈ 0.6667
    assert math.isclose(by_tool["programs.search"]["discovery"], 8 / 12, rel_tol=1e-12)
    # Cohort breakdown stores smb but not vc/developer
    assert "smb" in by_tool["programs.search"]["by_cohort"]
    assert by_tool["programs.search"]["by_cohort"]["smb"]["trials"] == 10
    assert by_tool["enforcement.search"]["hits"] == 1
    assert by_tool["enforcement.search"]["trials"] == 2


def test_discovery_result_bucket_zero_is_miss() -> None:
    rows = [
        {"tool": "programs.search", "result_bucket": "0"},
        {"tool": "programs.search", "result_bucket": "1+"},
        {"tool": "programs.search", "result_bucket": "10+"},
    ]
    out = discovery_confidence(rows)
    by_tool = {r["tool"]: r for r in out["per_tool"]}
    assert by_tool["programs.search"]["hits"] == 2
    assert by_tool["programs.search"]["trials"] == 3


def test_discovery_empty_returns_prior_only_overall() -> None:
    out = discovery_confidence([])
    assert out["per_tool"] == []
    # With no data the prior mean is 0.5 (Beta(1,1)).
    assert math.isclose(out["overall"]["discovery"], 0.5, rel_tol=1e-12)
    assert out["overall"]["trials"] == 0


# ---------------------------------------------------------------------------
# use_confidence
# ---------------------------------------------------------------------------


def test_use_returns_within_7d_is_hit() -> None:
    t0 = 1_700_000_000.0
    rows = [
        {
            "tool": "programs.search",
            "key_hash": "kh1",
            "ts_unix": t0,
            "cohort": "smb",
        },
        {
            "tool": "programs.search",
            "key_hash": "kh1",
            "ts_unix": t0 + 86400 * 3,  # 3 days later
            "cohort": "smb",
        },
    ]
    out = use_confidence(rows)
    by_tool = {r["tool"]: r for r in out["per_tool"]}
    assert by_tool["programs.search"]["hits"] == 1
    assert by_tool["programs.search"]["trials"] == 1


def test_use_returns_after_7d_is_miss() -> None:
    t0 = 1_700_000_000.0
    rows = [
        {"tool": "programs.search", "key_hash": "kh1", "ts_unix": t0},
        {
            "tool": "programs.search",
            "key_hash": "kh1",
            "ts_unix": t0 + 86400 * 8,  # 8 days later → outside window
        },
    ]
    out = use_confidence(rows)
    by_tool = {r["tool"]: r for r in out["per_tool"]}
    assert by_tool["programs.search"]["hits"] == 0
    assert by_tool["programs.search"]["trials"] == 1


def test_use_skips_anonymous_events() -> None:
    rows = [
        {"tool": "programs.search", "key_hash": None, "ts_unix": 1.0},
        {"tool": "programs.search", "key_hash": "", "ts_unix": 2.0},
        {"tool": "programs.search", "key_hash": "kh1", "ts_unix": 3.0},
    ]
    out = use_confidence(rows)
    by_tool = {r["tool"]: r for r in out["per_tool"]}
    # Only kh1 was kept → 1 trial, 0 hits.
    assert by_tool["programs.search"]["trials"] == 1
    assert by_tool["programs.search"]["hits"] == 0


# ---------------------------------------------------------------------------
# overall_confidence
# ---------------------------------------------------------------------------


def test_overall_confidence_weights_by_trial_count() -> None:
    # tool A: 100 trials, 100% discovery
    # tool B: 1 trial, 0% discovery
    discovery = {
        "per_tool": [
            {"tool": "A", "discovery": 1.0, "trials": 100},
            {"tool": "B", "discovery": 0.0, "trials": 1},
        ],
        "overall": {"discovery": 100 / 101},
    }
    use = {"per_tool": [], "overall": {"use": 0.5}}
    summary = overall_confidence(discovery, use)
    # Weighted: (1.0*100 + 0.0*1) / 101 = 100/101 ≈ 0.9901, NOT 0.5.
    assert math.isclose(summary["discovery_weighted"], 100 / 101, rel_tol=1e-9)


def test_overall_confidence_handles_no_tools() -> None:
    summary = overall_confidence({"per_tool": []}, {"per_tool": []})
    # Should fall back to the flat prior mean (0.5) for both axes.
    assert math.isclose(summary["discovery_weighted"], 0.5, rel_tol=1e-12)
    assert math.isclose(summary["use_weighted"], 0.5, rel_tol=1e-12)


def test_prior_constants_are_uniform() -> None:
    """Sanity: the module-level prior must remain flat Beta(1,1)."""
    assert PRIOR_ALPHA == 1.0
    assert PRIOR_BETA == 1.0
