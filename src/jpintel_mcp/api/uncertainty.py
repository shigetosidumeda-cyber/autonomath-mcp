"""Per-fact Bayesian uncertainty (O8, 2026-04-25).

Goal
----
Given a row from `am_entity_facts` (joined with `am_source` via
`am_uncertainty_view`), produce a Beta(α, β) posterior + 95% CI +
discrete confidence band so AI agents can decide whether to quote a
fact verbatim or surface an "確認推奨" prompt.

Pure-math + SQL only. No Anthropic API call, no LLM inference. Customer
LLMs do their own reasoning over the score we hand back — this module
is what lets AutonoMath stay ¥3/req metered without burning Anthropic
tokens.

Math model
----------
For each fact f, we treat one source observation as a single Bernoulli
trial whose expected probability of being correct is::

    evidence_w(f, s) = w_lic(license)  ×  w_fresh(days)  ×  w_kind(field_kind)
    doubt_w(f, s)    = 1 − evidence_w(f, s)

Posterior under flat Beta(1, 1) prior, with cross-source agreement
bonus added directly to α::

    α = 1 + evidence_w + 0.1 × max(0, n_sources − 1)
    β = 1 + doubt_w
    score      = α / (α + β)
    ci_95      = scipy.stats.beta.interval(0.95, α, β)

The bonus rule "+0.1 × (n − 1)" is the design's cross-source agreement
multiplier — it fires only when the SQL view sets `agreement = 1`
(distinct values among ≥2 sources collapse to a single string).

Bands (UI-side cohorts)::

    score ≥ 0.85      → high     (gov_standard ≤ 30d + cross-source agree)
    0.65 ≤ score < .85 → medium   (pdl ≤ 180d / gov ≤ 365d)
    0.40 ≤ score < .65 → low      (proprietary / 1y+ / single-source text)
    score < 0.40      → unknown  (NULL source / unknown license)

Honesty knobs
-------------
- `LICENSE_W` mirrors the design's 6 enum: gov standard 1.00 down to
  unknown 0.40; explicit `None` (source_id NULL → 81.7% facts today)
  drops to 0.30. Penalising NULL sources is intentional — backfill
  later auto-improves the score without redeploy.
- `KIND_W` follows the design's "structured > free text" rule, but the
  task spec only fixed enum/amount/text values. The 5 remaining kinds
  (bool/date/number/url/list) inherit the closest neighbour weight.
- Freshness decay is `exp(-days / 365)` clamped to a 0.2 floor; first-
  party law / standard PDFs stay useful even at 2 years old, so we
  never drop below 0.2 even when `last_verified` stays NULL (currently
  99.999% NULL, see CLAUDE.md am_source notes).

PII / cost posture
------------------
- No raw text leaves this module — only enum labels and integer days.
- No network call; every score is computed from one SQLite row.
- L4 cache is unnecessary at the per-fact granularity; the API layer
  calls `get_uncertainty_for_fact` lazily, only when a fact is about
  to be returned to the customer.

The high-level surface is split into:

* `score_fact(...)`  — pure-math, takes the raw column values, returns a
  serialisable dict including α / β / score / label / 95% CI / evidence
  breakdown.
* `get_uncertainty_for_fact(fact_id, conn)` — SQL helper that joins
  `am_uncertainty_view` for one fact and feeds its row into
  `score_fact`. Returns None if the fact does not exist.

Both functions are deliberately framework-free so the response envelope
wrapper (server.json + MCP) and the FastAPI route can share them.
"""
from __future__ import annotations

import math
import sqlite3
from typing import Any

from jpintel_mcp.analytics.bayesian import (
    PRIOR_ALPHA,
    PRIOR_BETA,
    beta_posterior,
    confidence_interval_95,
)

# ---------------------------------------------------------------------------
# Weights (see module docstring)
# ---------------------------------------------------------------------------

# License → evidence multiplier. NULL license falls back to "_NULL" → 0.30.
LICENSE_W: dict[str, float] = {
    "gov_standard_v2.0": 1.00,
    "cc_by_4.0":         0.95,
    "pdl_v1.0":          0.90,
    "public_domain":     0.85,
    "proprietary":       0.60,
    "unknown":           0.40,
}
LICENSE_W_NULL: float = 0.30

# field_kind → evidence multiplier. Structured > free text.
KIND_W: dict[str, float] = {
    "enum":   0.95,
    "bool":   0.95,
    "date":   0.90,
    "amount": 0.90,
    "number": 0.90,
    "url":    0.85,
    "list":   0.80,
    "text":   0.70,
}
KIND_W_DEFAULT: float = 0.70  # unknown field_kind → treat as free text

# Freshness decay floor (per design: 730d → 0.14 clamped to 0.2).
FRESHNESS_FLOOR: float = 0.20
FRESHNESS_HALF_LIFE_DAYS: float = 365.0

# Cross-source agreement bonus (added directly to α).
AGREEMENT_ALPHA_BONUS: float = 0.10

# Score band thresholds.
BAND_HIGH: float = 0.85
BAND_MEDIUM: float = 0.65
BAND_LOW: float = 0.40

# Versioned model tag for forward compatibility (Dirichlet upgrade path).
MODEL_TAG: str = "beta_posterior_v1"


def _freshness_weight(days_since_fetch: int | None) -> float:
    """Return exp(-days/365) clamped to [FRESHNESS_FLOOR, 1.0].

    Unknown freshness (None) lands at the floor — we cannot distinguish
    "fresh but undated" from "stale and undated", so be conservative.
    """
    if days_since_fetch is None or days_since_fetch < 0:
        return FRESHNESS_FLOOR
    decay = math.exp(-float(days_since_fetch) / FRESHNESS_HALF_LIFE_DAYS)
    return max(FRESHNESS_FLOOR, min(1.0, decay))


def _license_weight(license_value: str | None) -> float:
    if license_value is None:
        return LICENSE_W_NULL
    return LICENSE_W.get(license_value, LICENSE_W_NULL)


def _kind_weight(field_kind: str | None) -> float:
    if not field_kind:
        return KIND_W_DEFAULT
    return KIND_W.get(field_kind, KIND_W_DEFAULT)


def _label_for(score: float) -> str:
    if score >= BAND_HIGH:
        return "high"
    if score >= BAND_MEDIUM:
        return "medium"
    if score >= BAND_LOW:
        return "low"
    return "unknown"


def score_fact(
    *,
    field_kind: str | None,
    license_value: str | None,
    days_since_fetch: int | None,
    n_sources: int = 0,
    agreement: int = 0,
) -> dict[str, Any]:
    """Compute the per-fact uncertainty payload (pure math).

    Parameters
    ----------
    field_kind:
        am_entity_facts.field_kind (enum 8 buckets).
    license_value:
        am_source.license (6 enum + NULL).
    days_since_fetch:
        Integer days since am_source.first_seen, or None when source_id
        is NULL (unknown source).
    n_sources:
        Distinct source_id count for (entity_id, field_name).
    agreement:
        1 iff n_sources >= 2 AND all those sources agree on a single
        value string. Anything else → 0.

    Returns
    -------
    dict with keys:
        ``score`` (float in (0, 1)), ``label`` (one of high/medium/low/
        unknown), ``ci_95`` (list[float, float]), ``alpha``, ``beta``,
        ``model``, ``evidence`` (list of axis breakdowns).

    The dict is JSON-serialisable and deliberately includes ``alpha`` /
    ``beta`` so downstream code can run a Monte-Carlo joint Bayes when
    multiple facts compose a claim.
    """
    w_lic   = _license_weight(license_value)
    w_fresh = _freshness_weight(days_since_fetch)
    w_kind  = _kind_weight(field_kind)
    evidence_w = w_lic * w_fresh * w_kind
    doubt_w    = max(0.0, 1.0 - evidence_w)

    bonus_alpha = 0.0
    if agreement and n_sources and n_sources > 1:
        bonus_alpha = AGREEMENT_ALPHA_BONUS * (n_sources - 1)

    a, b = beta_posterior(PRIOR_ALPHA, PRIOR_BETA, 0, 0)
    a = a + evidence_w + bonus_alpha
    b = b + doubt_w
    lo, hi = confidence_interval_95(a, b)
    score = a / (a + b)
    return {
        "score": float(score),
        "label": _label_for(score),
        "ci_95": [float(lo), float(hi)],
        "alpha": float(a),
        "beta": float(b),
        "evidence": [
            {"axis": "license",
             "value": license_value,
             "weight": round(w_lic, 4)},
            {"axis": "freshness",
             "days_since_fetch": days_since_fetch,
             "weight": round(w_fresh, 4)},
            {"axis": "field_kind",
             "value": field_kind,
             "weight": round(w_kind, 4)},
            {"axis": "cross_source_agreement",
             "n_sources": int(n_sources or 0),
             "bonus_alpha": round(bonus_alpha, 4)},
        ],
        "model": MODEL_TAG,
    }


def get_uncertainty_for_fact(
    fact_id: int,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Read one row of am_uncertainty_view and run score_fact() on it.

    Returns None when the fact_id does not exist (or when the view is
    missing — pre-migration safety). Callers should treat None as
    "uncertainty unknown" and drop the `_uncertainty` envelope key.
    """
    try:
        row = conn.execute(
            "SELECT field_kind, license, days_since_fetch, "
            "       n_sources, agreement "
            "  FROM am_uncertainty_view "
            " WHERE fact_id = ? LIMIT 1",
            (int(fact_id),),
        ).fetchone()
    except sqlite3.OperationalError:
        # View missing on this volume (migration not applied yet).
        return None
    if row is None:
        return None
    # sqlite3.Row supports either dict-like access or tuple unpacking;
    # be defensive for both fixture styles.
    try:
        field_kind = row["field_kind"]
        license_value = row["license"]
        days_since_fetch = row["days_since_fetch"]
        n_sources = row["n_sources"]
        agreement = row["agreement"]
    except (TypeError, IndexError):
        field_kind, license_value, days_since_fetch, n_sources, agreement = (
            row[0], row[1], row[2], row[3], row[4]
        )
    return score_fact(
        field_kind=field_kind,
        license_value=license_value,
        days_since_fetch=(
            int(days_since_fetch) if days_since_fetch is not None else None
        ),
        n_sources=int(n_sources or 0),
        agreement=int(agreement or 0),
    )


__all__ = [
    "LICENSE_W",
    "LICENSE_W_NULL",
    "KIND_W",
    "KIND_W_DEFAULT",
    "FRESHNESS_FLOOR",
    "AGREEMENT_ALPHA_BONUS",
    "MODEL_TAG",
    "score_fact",
    "get_uncertainty_for_fact",
]
