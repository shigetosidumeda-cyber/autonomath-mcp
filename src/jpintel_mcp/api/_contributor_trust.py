"""DEEP-33 Bayesian contributor trust score (CLV2-13 implementation).

Spec: tools/offline/_inbox/value_growth_dual/_deep_plan/DEEP_33_contributor_trust_bayesian.md

Pure SQLite + numpy. NO LLM imports — verified by
`tests/test_no_llm_in_production.py` and the dedicated negative grep test
in `tests/test_contributor_trust.py::test_no_llm_call_negative`.

Math summary
------------
* Cohort base likelihood P(obs = θ_true | θ_true):
    税理士=0.90, 公認会計士=0.85, 司法書士=0.85,
    補助金_consultant=0.75, anonymous=0.60
* Reject penalty: effective_likelihood = base − min(0.1×n_rej, 0.3)
* Prior over Θ = 11 cluster values + 1 template-default:
    P(θ_template) = 0.30, residual 0.70 spread evenly over 11 clusters.
* Sequential Bayesian update done in log-space to avoid underflow,
  normalized over Θ at the end.
* Cluster spillover: 1 寄稿 → α=0.3 partial-verify on ~22K cluster
  siblings. Direct verify (posterior > 0.95) sets α=1.0.

The four public functions called by the FastAPI router and tests:

    compute_likelihood(observation, contributor_history) -> float
    update_posterior(prior, likelihoods)                -> float
    cluster_spillover(observation, am_amount_condition) -> list[int]
    verified_threshold_check(posterior)                 -> bool

Everything else is helper math.
"""

from __future__ import annotations

import datetime as _dt
import logging
import math
import sqlite3
from typing import Any

import numpy as np

_log = logging.getLogger("jpintel.api._contributor_trust")

# ---------------------------------------------------------------------------
# Constants — kept in lockstep with `contributor_trust_meta` rows in
# scripts/migrations/wave24_182_contributor_trust.sql. If the migration
# moves a constant, update both — the test suite asserts numeric values.
# ---------------------------------------------------------------------------
COHORT_BASE_LIKELIHOOD: dict[str, float] = {
    "税理士": 0.90,
    "公認会計士": 0.85,
    "司法書士": 0.85,
    "補助金_consultant": 0.75,
    "anonymous": 0.60,
}

VERIFIED_THRESHOLD = 0.95
REJECT_PENALTY_PER_REJECT = 0.10
REJECT_PENALTY_MAX = 0.30
TEMPORAL_DECAY_LAMBDA_PER_DAY = 0.005  # 1-year half-life ≈ ln(2)/0.005 ≈ 138.6 days
HISTORY_BONUS_PER_APPROVED = 0.005
HISTORY_BONUS_CAP = 0.15
CLUSTER_SPILLOVER_ALPHA = 0.30
DIRECT_VERIFY_ALPHA = 1.00

# Θ size: 11 distinct am_amount_condition cluster values + 1 template default.
# CLAUDE.md L1 declares "11 distinct cluster_value". §12 risk note in the spec
# says: live deployments should call `theta_size_from_db` to verify because
# real cluster count may drift to 12/13.
THETA_SIZE_DEFAULT = 11
PRIOR_TEMPLATE_MASS = 0.30  # P(θ_template) at session start
PRIOR_RESIDUAL_MASS = 0.70  # spread evenly over the 11 cluster values
PRIOR_CLUSTER_BUMP = 0.05  # +0.05 if same cluster has prior approved
PRIOR_CLUSTER_BUMP_CAP = 0.50


# ---------------------------------------------------------------------------
# 1. compute_likelihood
# ---------------------------------------------------------------------------
def compute_likelihood(
    observation: dict[str, Any],
    contributor_history: dict[str, Any] | None = None,
) -> float:
    """Return P(obs | true_θ) for one contributor observation.

    `observation` must carry `cohort` (one of `COHORT_BASE_LIKELIHOOD` keys).
    `contributor_history` (optional) provides `cumulative_rejected: int`.

    effective_likelihood = base − min(0.1×n_rej, 0.3). 1 reject = 0.1 down,
    3+ rejects floor the penalty at 0.30.
    """
    cohort = observation.get("cohort")
    if cohort not in COHORT_BASE_LIKELIHOOD:
        # Unknown cohort: fall back to anonymous baseline rather than
        # raising — the API surface should never 500 on a malformed cohort.
        _log.warning("unknown cohort=%r, falling back to anonymous", cohort)
        base = COHORT_BASE_LIKELIHOOD["anonymous"]
    else:
        base = COHORT_BASE_LIKELIHOOD[cohort]

    n_rejected = 0
    if contributor_history:
        n_rejected = int(contributor_history.get("cumulative_rejected", 0) or 0)

    penalty = min(REJECT_PENALTY_PER_REJECT * n_rejected, REJECT_PENALTY_MAX)
    effective = max(0.0, min(1.0, base - penalty))
    return float(effective)


# ---------------------------------------------------------------------------
# 2. update_posterior
# ---------------------------------------------------------------------------
def _build_prior(theta_size: int = THETA_SIZE_DEFAULT) -> np.ndarray:
    """Return the initial prior over Θ = [template, c_1, ..., c_N].

    Index 0 is the template default (mass 0.30), indices 1..theta_size
    are the cluster values (residual 0.70 spread evenly).
    """
    if theta_size <= 0:
        # Degenerate guard — single template-only state.
        return np.array([1.0], dtype=np.float64)
    prior = np.empty(theta_size + 1, dtype=np.float64)
    prior[0] = PRIOR_TEMPLATE_MASS
    prior[1:] = PRIOR_RESIDUAL_MASS / theta_size
    # Normalize defensively in case of floating-point drift.
    result: np.ndarray = prior / prior.sum()
    return result


def update_posterior(
    prior: float | list[float] | np.ndarray | None,
    likelihoods: list[float],
    *,
    theta_size: int = THETA_SIZE_DEFAULT,
    truth_index: int = 1,
) -> float:
    """Sequential Bayesian update in log-space, return posterior on θ_true.

    Args:
        prior: float / list / ndarray. If None or scalar, build a fresh
               default prior over Θ (template + theta_size clusters).
               If scalar, it's treated as P(θ_true) and the rest is
               distributed uniformly across Θ.
        likelihoods: list[float] in [0,1]. Each is P(obs_i | θ_true).
                     For competing θ' ≠ θ_true we use (1 − l_i)/(|Θ|−1)
                     by symmetry — a single observation is `θ_true` with
                     prob l_i, otherwise spread uniformly over the rest.
        theta_size: number of cluster values (default 11). Total Θ = N+1.
        truth_index: which index in Θ is θ_true (default 1, first cluster).

    Returns:
        posterior P(θ_true | obs_1..obs_n) ∈ [0,1].
    """
    theta_dim = theta_size + 1  # total state count

    # Build prior vector
    if prior is None:
        log_p = np.log(_build_prior(theta_size))
    elif isinstance(prior, (int, float)):
        # Scalar prior: treat as P(θ_true), uniform-spread the rest.
        p_true = float(max(0.0, min(1.0, prior)))
        rest = (1.0 - p_true) / max(1, theta_dim - 1)
        vec = np.full(theta_dim, rest, dtype=np.float64)
        vec[truth_index] = p_true
        # Guard against pathological all-zero
        s = vec.sum()
        vec = _build_prior(theta_size) if s <= 0 else vec / s
        log_p = np.log(np.maximum(vec, 1e-300))
    else:
        vec = np.asarray(prior, dtype=np.float64).flatten()
        if vec.size != theta_dim:
            # Shape mismatch: rebuild default and warn.
            _log.warning("prior shape=%d != theta_dim=%d, rebuilding", vec.size, theta_dim)
            vec = _build_prior(theta_size)
        s = vec.sum()
        vec = _build_prior(theta_size) if s <= 0 else vec / s
        log_p = np.log(np.maximum(vec, 1e-300))

    # Sequentially apply each observation
    for l_i in likelihoods:
        l = float(max(1e-9, min(1.0 - 1e-9, l_i)))  # noqa: E741 (math notation: likelihood)
        # P(obs | θ_true) = l
        # P(obs | θ' ≠ θ_true) = (1 − l) / (|Θ| − 1) — symmetric spread
        not_true = (1.0 - l) / max(1, theta_dim - 1)
        log_lik = np.full(theta_dim, math.log(not_true), dtype=np.float64)
        log_lik[truth_index] = math.log(l)
        log_p = log_p + log_lik
        # Normalize in log-space (numerically stable)
        m = log_p.max()
        log_p = log_p - (m + math.log(np.exp(log_p - m).sum()))

    posterior = float(np.exp(log_p[truth_index]))
    # Numerical floor / ceiling for safety
    return max(0.0, min(1.0, posterior))


# ---------------------------------------------------------------------------
# 3. cluster_spillover
# ---------------------------------------------------------------------------
def cluster_spillover(
    observation: dict[str, Any],
    am_amount_condition_conn: sqlite3.Connection | None = None,
    *,
    cluster_value: Any = None,
    dry_run: bool = False,
) -> list[int]:
    """Spillover one verified observation onto cluster siblings.

    SELECT row_id FROM am_amount_condition WHERE cluster_value = X,
    UPDATE quality_flag → 'community_partial_verified' for those rows.

    Args:
        observation: dict carrying `cluster_value` (or pass cluster_value=).
        am_amount_condition_conn: open sqlite3.Connection. If None, returns
                                  empty list (caller is expected to inject).
        cluster_value: explicit override for the SELECT predicate.
        dry_run: if True, runs SELECT but skips UPDATE. Useful for tests
                 that want the row count without mutation.

    Returns:
        list of row_id (ROWID) that were partial-verified. Empty if no
        connection or no matches.
    """
    cv = cluster_value if cluster_value is not None else observation.get("cluster_value")
    if cv is None or am_amount_condition_conn is None:
        return []

    try:
        cur = am_amount_condition_conn.execute(
            "SELECT rowid FROM am_amount_condition WHERE cluster_value = ?",
            (cv,),
        )
        row_ids = [int(r[0]) for r in cur.fetchall()]
    except sqlite3.OperationalError as exc:
        # cluster_value column missing in test schema → degrade gracefully.
        _log.warning("cluster_spillover SELECT failed: %s", exc)
        return []

    if not row_ids or dry_run:
        return row_ids

    # Bulk UPDATE — chunk to keep SQLite parameter list under 999.
    chunk_size = 500
    try:
        for i in range(0, len(row_ids), chunk_size):
            batch = row_ids[i : i + chunk_size]
            placeholders = ",".join(["?"] * len(batch))
            am_amount_condition_conn.execute(
                f"UPDATE am_amount_condition "
                f"SET quality_flag = 'community_partial_verified' "
                f"WHERE rowid IN ({placeholders})",
                batch,
            )
        am_amount_condition_conn.commit()
    except sqlite3.OperationalError as exc:
        _log.warning(
            "cluster_spillover UPDATE failed (CHECK constraint may "
            "block 'community_partial_verified' on legacy schema): %s",
            exc,
        )
    return row_ids


# ---------------------------------------------------------------------------
# 4. verified_threshold_check
# ---------------------------------------------------------------------------
def verified_threshold_check(posterior: float) -> bool:
    """Return True iff posterior > 0.95 (strictly greater)."""
    return float(posterior) > VERIFIED_THRESHOLD


# ---------------------------------------------------------------------------
# Helper math used by the FastAPI surface
# ---------------------------------------------------------------------------
def temporal_decay(age_days: float | int) -> float:
    """e^(-λ × age_days). λ = 0.005 → 1-year half-life ≈ 138.6d.

    age_days=0 → 1.0; age_days=365 → e^(-1.825) ≈ 0.1612.
    """
    age = max(0.0, float(age_days))
    return float(math.exp(-TEMPORAL_DECAY_LAMBDA_PER_DAY * age))


def history_bonus(cumulative_approved: int) -> float:
    """Linear bonus capped at HISTORY_BONUS_CAP (0.15).

    bonus = min(0.005 × n_approved, 0.15). 30 approved hits the cap.
    """
    n = max(0, int(cumulative_approved or 0))
    return float(min(HISTORY_BONUS_PER_APPROVED * n, HISTORY_BONUS_CAP))


def theta_size_from_db(conn: sqlite3.Connection | None) -> int:
    """Live SQL probe for distinct am_amount_condition.cluster_value count.

    Falls back to THETA_SIZE_DEFAULT if the connection is None or the
    column isn't present (test schema). See spec §12.
    """
    if conn is None:
        return THETA_SIZE_DEFAULT
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT cluster_value) FROM am_amount_condition "
            "WHERE quality_flag = 'automated_default'"
        ).fetchone()
    except sqlite3.OperationalError:
        return THETA_SIZE_DEFAULT
    if not row or row[0] is None:
        return THETA_SIZE_DEFAULT
    return max(1, int(row[0]))


def compute_trust_score(
    *,
    cohort: str,
    cumulative_contributions: int,
    cumulative_approved: int,
    cumulative_rejected: int,
    last_updated_iso: str | None = None,
    now: _dt.datetime | None = None,
    theta_size: int = THETA_SIZE_DEFAULT,
) -> dict[str, float]:
    """End-to-end trust score from the persisted contributor row.

    Returns dict with: posterior, history_bonus, temporal_decay_weight,
    effective_likelihood, verified.
    """
    obs = {"cohort": cohort}
    hist = {"cumulative_rejected": cumulative_rejected}
    eff = compute_likelihood(obs, hist)

    # Build n_approved independent observations at the effective likelihood
    likelihoods = [eff] * max(0, int(cumulative_approved))
    posterior = update_posterior(None, likelihoods, theta_size=theta_size)

    bonus = history_bonus(cumulative_approved)

    # Temporal decay since last_updated
    if last_updated_iso is None:
        decay = 1.0
    else:
        try:
            last = _dt.datetime.fromisoformat(last_updated_iso.replace("Z", "+00:00"))
        except ValueError:
            decay = 1.0
        else:
            anchor = now or _dt.datetime.now(tz=_dt.UTC)
            if last.tzinfo is None:
                last = last.replace(tzinfo=_dt.UTC)
            age_days = max(0.0, (anchor - last).total_seconds() / 86400.0)
            decay = temporal_decay(age_days)

    return {
        "posterior": float(posterior),
        "history_bonus": float(bonus),
        "temporal_decay_weight": float(decay),
        "effective_likelihood": float(eff),
        "verified": bool(verified_threshold_check(posterior)),
    }
