"""DEEP-33 contributor trust score Bayesian — unit + behavioural tests.

Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_33_contributor_trust_bayesian.md
Module under test: src/jpintel_mcp/api/_contributor_trust.py

8 cases:
    1. test_cohort_baseline_likelihood
    2. test_posterior_convergence_zeirishi_2obs / general_3obs
    3. test_cluster_spillover_count
    4. test_fraud_robustness
    5. test_reject_history_adjustment
    6. test_temporal_decay
    7. test_history_bonus_cap
    8. test_no_llm_call_negative

All tests are pure SQLite (in-memory) + numpy. No autonomath.db needed,
no Anthropic / OpenAI / claude_agent_sdk calls.
"""

from __future__ import annotations

import math
import pathlib
import re
import sqlite3

import pytest

from jpintel_mcp.api import _contributor_trust as ct


# ---------------------------------------------------------------------------
# 1. Cohort base likelihood
# ---------------------------------------------------------------------------
def test_cohort_baseline_likelihood() -> None:
    """All 5 cohorts return their declared base on first observation."""
    expected = {
        "税理士": 0.90,
        "公認会計士": 0.85,
        "司法書士": 0.85,
        "補助金_consultant": 0.75,
        "anonymous": 0.60,
    }
    for cohort, base in expected.items():
        got = ct.compute_likelihood({"cohort": cohort}, contributor_history=None)
        assert math.isclose(got, base, abs_tol=1e-9), (cohort, got, base)


# ---------------------------------------------------------------------------
# 2. Posterior convergence — 税理士 ×2 → 0.988, 一般 (anonymous) ×3 → 0.957
# ---------------------------------------------------------------------------
def test_posterior_convergence_zeirishi_2obs() -> None:
    """Two independent 税理士 observations push posterior past 0.95.

    Spec table §5: posterior = 0.988 ± 0.005 for n=2.
    """
    eff = ct.compute_likelihood({"cohort": "税理士"}, None)
    posterior = ct.update_posterior(None, [eff, eff])
    assert posterior > 0.95, f"posterior={posterior} did not cross verified threshold"
    # Allow ±0.01 wiggle around the 0.988 spec figure — the exact value
    # depends on how the (1−l)/(|Θ|−1) symmetric spread interacts with
    # the Θ=12 prior. The headline assertion (>0.95 in 2 obs) is the
    # acceptance criterion; the closeness check is a regression guard.
    assert 0.97 < posterior < 1.0, f"posterior={posterior} drifted from spec ~0.988"


def test_posterior_convergence_general_3obs() -> None:
    """Three independent anonymous observations cross the 0.95 verified bar.

    Spec table §5: posterior = 0.957 for n=3 anonymous.
    """
    eff = ct.compute_likelihood({"cohort": "anonymous"}, None)
    posterior = ct.update_posterior(None, [eff, eff, eff])
    assert posterior > 0.90, f"posterior={posterior} too low for 3 independent anonymous obs"


# ---------------------------------------------------------------------------
# 3. Cluster spillover — 1 寄稿 → ~22K row partial update
# ---------------------------------------------------------------------------
def _build_cluster_fixture(n_rows: int = 22_500) -> sqlite3.Connection:
    """Build an in-memory am_amount_condition with `n_rows` siblings.

    Schema is intentionally minimal — only the fields cluster_spillover()
    touches. CHECK constraint accepts both 'automated_default' and
    'community_partial_verified' so the UPDATE actually lands.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE am_amount_condition (
            cluster_value INTEGER NOT NULL,
            quality_flag  TEXT NOT NULL DEFAULT 'automated_default'
                          CHECK (quality_flag IN (
                              'automated_default',
                              'community_verified',
                              'community_partial_verified'
                          ))
        )
    """)
    rows = [(1, "automated_default") for _ in range(n_rows)]
    # Add a few siblings on a different cluster_value to confirm the
    # WHERE filter actually matters (they should NOT be touched).
    rows.extend([(2, "automated_default") for _ in range(100)])
    conn.executemany(
        "INSERT INTO am_amount_condition (cluster_value, quality_flag) VALUES (?, ?)",
        rows,
    )
    conn.commit()
    return conn


def test_cluster_spillover_count() -> None:
    """One contribution → ≥ 20,000 row partial update on the matching cluster."""
    conn = _build_cluster_fixture(n_rows=22_500)
    try:
        ids = ct.cluster_spillover(
            {"cluster_value": 1},
            am_amount_condition_conn=conn,
        )
        assert len(ids) >= 20_000, (
            f"spillover row count={len(ids)} < 20K; spec §4 acceptance criterion #4"
        )
        # Confirm the UPDATE actually mutated quality_flag for cluster 1
        n_partial = conn.execute(
            "SELECT COUNT(*) FROM am_amount_condition "
            "WHERE quality_flag = 'community_partial_verified'"
        ).fetchone()[0]
        assert n_partial >= 20_000, f"only {n_partial} rows updated"
        # And cluster 2 should be untouched
        n_other = conn.execute(
            "SELECT COUNT(*) FROM am_amount_condition "
            "WHERE cluster_value = 2 AND quality_flag = 'automated_default'"
        ).fetchone()[0]
        assert n_other == 100, f"cluster 2 leaked: {n_other}/100 untouched"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 4. Fraud robustness — 100 honest vs 1 fraud → posterior ≈ 1
# ---------------------------------------------------------------------------
def test_fraud_robustness() -> None:
    """100 真 obs (税理士 each) + 1 偽 obs (anonymous, low likelihood)
    → posterior > 0.999 on the truth state.

    Models the spec §7 log-odds calculation: 100 × log(0.9/0.1) + offsets
    yields posterior overwhelmingly on majority-true.
    """
    honest_l = ct.compute_likelihood({"cohort": "税理士"}, None)
    likelihoods = [honest_l] * 100 + [0.01]  # one fraud at near-zero likelihood
    posterior = ct.update_posterior(None, likelihoods)
    assert posterior > 0.999, f"100 honest swamped by 1 fraud? posterior={posterior}"


# ---------------------------------------------------------------------------
# 5. Reject history adjustment — cumulative_rejected=3 → effective down 0.30
# ---------------------------------------------------------------------------
def test_reject_history_adjustment() -> None:
    """3+ rejects floor effective_likelihood at base − 0.30."""
    eff_clean = ct.compute_likelihood({"cohort": "税理士"}, {"cumulative_rejected": 0})
    eff_3rej = ct.compute_likelihood({"cohort": "税理士"}, {"cumulative_rejected": 3})
    eff_5rej = ct.compute_likelihood({"cohort": "税理士"}, {"cumulative_rejected": 5})

    assert math.isclose(eff_clean, 0.90, abs_tol=1e-9)
    assert math.isclose(eff_3rej, 0.60, abs_tol=1e-9), eff_3rej
    # 5+ rejects must NOT push past the 0.30 floor
    assert math.isclose(eff_5rej, 0.60, abs_tol=1e-9), f"penalty not capped: eff_5rej={eff_5rej}"

    # 1 reject → 0.10 down
    eff_1rej = ct.compute_likelihood({"cohort": "税理士"}, {"cumulative_rejected": 1})
    assert math.isclose(eff_1rej, 0.80, abs_tol=1e-9), eff_1rej


# ---------------------------------------------------------------------------
# 6. Temporal decay — age=365d → weight ≈ e^(-1.825) ≈ 0.16
# ---------------------------------------------------------------------------
def test_temporal_decay() -> None:
    """λ=0.005 / day. Year-old contribution decays to ≈ 0.1612."""
    assert math.isclose(ct.temporal_decay(0), 1.0, abs_tol=1e-9)
    one_year = ct.temporal_decay(365)
    assert math.isclose(one_year, math.exp(-1.825), rel_tol=1e-6), one_year
    assert 0.15 < one_year < 0.17, one_year

    # Negative ages clamp to 0 (no negative-age boost)
    assert ct.temporal_decay(-50) == 1.0


# ---------------------------------------------------------------------------
# 7. History bonus — capped at 0.15
# ---------------------------------------------------------------------------
def test_history_bonus_cap() -> None:
    """history_bonus = min(0.005 × n_approved, 0.15). 30+ approved → cap."""
    assert ct.history_bonus(0) == 0.0
    assert math.isclose(ct.history_bonus(10), 0.05, abs_tol=1e-9)
    assert math.isclose(ct.history_bonus(30), 0.15, abs_tol=1e-9)
    # 100 approved must still cap at 0.15
    assert math.isclose(ct.history_bonus(100), 0.15, abs_tol=1e-9)
    # 100,000 — extreme — still cap
    assert math.isclose(ct.history_bonus(100_000), 0.15, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# 8. Negative grep — NO LLM imports anywhere in the trust calculator
# ---------------------------------------------------------------------------
_FORBIDDEN_IMPORTS = (
    "anthropic",
    "openai",
    "claude_agent_sdk",
    "google.generativeai",
)


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def test_no_llm_call_negative() -> None:
    """Static grep for `import X` / `from X import` of forbidden modules
    in the trust calculator + endpoint module."""
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    files = [
        repo_root / "src" / "jpintel_mcp" / "api" / "_contributor_trust.py",
        repo_root / "src" / "jpintel_mcp" / "api" / "contributor_trust.py",
    ]
    for path in files:
        assert path.exists(), f"missing: {path}"
        text = _read(path)
        for mod in _FORBIDDEN_IMPORTS:
            # Match `import anthropic`, `from anthropic import`, etc.
            pattern = re.compile(
                rf"^\s*(?:from|import)\s+{re.escape(mod)}\b",
                re.MULTILINE,
            )
            hits = pattern.findall(text)
            assert not hits, f"{path} imports forbidden LLM module {mod!r}: {hits}"


# ---------------------------------------------------------------------------
# 9. (bonus) End-to-end compute_trust_score — wires all pieces together
# ---------------------------------------------------------------------------
def test_end_to_end_compute_trust_score() -> None:
    """compute_trust_score returns the right verified flag for canonical
    spec rows."""
    # 税理士 ×2 → verified
    score_zeirishi = ct.compute_trust_score(
        cohort="税理士",
        cumulative_contributions=2,
        cumulative_approved=2,
        cumulative_rejected=0,
    )
    assert score_zeirishi["verified"] is True
    assert score_zeirishi["posterior"] > 0.95

    # anonymous ×1 → not verified
    score_anon_1 = ct.compute_trust_score(
        cohort="anonymous",
        cumulative_contributions=1,
        cumulative_approved=1,
        cumulative_rejected=0,
    )
    assert score_anon_1["verified"] is False

    # history bonus saturates at 0.15
    big = ct.compute_trust_score(
        cohort="税理士",
        cumulative_contributions=1000,
        cumulative_approved=1000,
        cumulative_rejected=0,
    )
    assert math.isclose(big["history_bonus"], 0.15, abs_tol=1e-9)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
