"""Bayesian confidence model — Beta(alpha, beta) posteriors over per-tool
Discovery and Use.

Mathematical model
------------------
For each tool T we keep two Bernoulli processes:

  Discovery_T = P(found_result | invoked)
      success = invocation that returned >=1 result row
      trial   = any invocation of the tool

  Use_T = P(returned_within_7d | first_invocation)
      success = same (api_key_hash, tool) seen again within 7 days
      trial   = first-ever invocation of (key, tool)

We start each tool with a flat Beta(1, 1) prior (= Uniform[0,1]); no
informative prior because we explicitly want to honor the new-tool
"unknown" state (target band 90%/80% is supposed to be _earned_ by data,
not preloaded).

After observing `hits` successes out of `trials` Bernoulli draws:

  posterior = Beta(alpha + hits, beta + trials - hits)

The 95% credible interval is `scipy.stats.beta.interval(0.95, a, b)`.

PII posture
-----------
Both inputs (query_log_v2, usage_events) are PII-redacted upstream
(INV-21, A5 wired). This module is pure-math and never reads raw text.
The only identifier we ever bin on is `tool` (string label, e.g.
"programs.search"). `cohort` is a coarse audience bucket, never a
per-customer key.

Constants
---------
The 5 cohort labels match the AutonoMath audience pillars:
  - tax_advisor
  - admin_scrivener
  - smb
  - vc
  - developer
Anything else falls into "other".
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _beta_dist():
    """Lazy-load scipy.stats.beta — saves ~2.5s on API boot.

    scipy is the dominant import cost in the API process (perf audit
    2026-04-30). Only this module + the /v1/confidence/* endpoint use it.
    The first call to confidence_interval() pays the import cost (~200ms);
    subsequent calls hit the lru_cache and are free.
    """
    from scipy.stats import beta as beta_dist  # type: ignore[import-untyped]

    return beta_dist


# Flat prior — see module docstring.
PRIOR_ALPHA: float = 1.0
PRIOR_BETA: float = 1.0

# Audience cohorts (P5 pitch). 5 buckets are the public-safe granularity:
# anything narrower would risk identifying a single customer.
KNOWN_COHORTS: tuple[str, ...] = (
    "tax_advisor",
    "admin_scrivener",
    "smb",
    "vc",
    "developer",
    "other",
)

# 7 days — the "Use" return-window. A customer who comes back within a
# week is treated as having converted the discovery into action; longer
# windows would conflate retention with one-shot trial usage.
USE_RETURN_WINDOW_SECONDS: int = 7 * 24 * 3600


def beta_posterior(
    prior_alpha: float, prior_beta: float, hits: int, trials: int
) -> tuple[float, float]:
    """Return the Beta posterior (alpha, beta) after Bernoulli observations.

    Raises ValueError if `hits < 0`, `trials < 0`, or `hits > trials`.
    The conjugate update is the closed-form
    Beta(prior_alpha + hits, prior_beta + trials - hits).
    """
    if hits < 0:
        raise ValueError("hits must be >= 0")
    if trials < 0:
        raise ValueError("trials must be >= 0")
    if hits > trials:
        raise ValueError("hits must be <= trials")
    return (prior_alpha + hits, prior_beta + trials - hits)


def confidence_interval_95(alpha: float, beta: float) -> tuple[float, float]:
    """Return the 95% equal-tail credible interval of Beta(alpha, beta).

    Uses scipy.stats.beta.interval (the inverse-CDF method). Both
    endpoints are clamped to [0.0, 1.0]; with finite alpha,beta > 0
    they always fall inside that range, but we round-trip through float
    so we never expose a NaN to JSON consumers.
    """
    if alpha <= 0 or beta <= 0:
        raise ValueError("alpha and beta must be > 0")
    lo, hi = _beta_dist().interval(0.95, alpha, beta)
    return (max(0.0, float(lo)), min(1.0, float(hi)))


def _posterior_mean(alpha: float, beta: float) -> float:
    """Beta posterior mean = a / (a + b). Always in (0, 1) for a,b > 0."""
    return float(alpha) / float(alpha + beta)


def _normalize_cohort(raw: str | None) -> str:
    if not raw:
        return "other"
    if raw in KNOWN_COHORTS:
        return raw
    return "other"


def discovery_confidence(query_log: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-tool Discovery posterior from a list of query-log rows.

    Each row must carry at minimum:
      - tool         (str)            — tool name e.g. "programs.search"
      - result_count (int) OR
        result_bucket (str: "0" / "1+" / etc.)
      - cohort       (str, optional)  — audience bucket; missing → "other"

    A row counts as "hit" if result_count > 0 (or result_bucket != "0").

    Returns:
        {
          "per_tool": [
            {"tool": "...", "hits": int, "trials": int,
             "discovery": float, "ci95": [lo, hi],
             "alpha": float, "beta": float, "by_cohort": {...}},
            ...
          ],
          "overall": {"hits": int, "trials": int, "discovery": float,
                      "ci95": [lo, hi]}
        }
    """
    by_tool: dict[str, dict[str, Any]] = {}
    by_tool_cohort: dict[tuple[str, str], dict[str, int]] = {}
    total_hits = 0
    total_trials = 0

    for row in query_log:
        tool = row.get("tool")
        if not tool:
            continue
        # Either field can carry the result signal.
        rc = row.get("result_count")
        bucket = row.get("result_bucket")
        if rc is None and bucket is None:
            # Cannot tell from this row whether it was a hit or miss.
            continue
        if rc is not None:
            try:
                hit = int(rc) > 0
            except (TypeError, ValueError):
                continue
        else:
            hit = str(bucket) not in ("", "0", "none")

        bag = by_tool.setdefault(tool, {"hits": 0, "trials": 0})
        bag["trials"] += 1
        if hit:
            bag["hits"] += 1

        cohort = _normalize_cohort(row.get("cohort"))
        ck = (tool, cohort)
        cbag = by_tool_cohort.setdefault(ck, {"hits": 0, "trials": 0})
        cbag["trials"] += 1
        if hit:
            cbag["hits"] += 1

        total_trials += 1
        if hit:
            total_hits += 1

    per_tool: list[dict[str, Any]] = []
    for tool in sorted(by_tool):
        agg = by_tool[tool]
        a, b = beta_posterior(PRIOR_ALPHA, PRIOR_BETA, agg["hits"], agg["trials"])
        lo, hi = confidence_interval_95(a, b)
        cohorts: dict[str, dict[str, Any]] = {}
        for cohort in KNOWN_COHORTS:
            cagg = by_tool_cohort.get((tool, cohort))
            if not cagg or cagg["trials"] == 0:
                continue
            ca, cb = beta_posterior(PRIOR_ALPHA, PRIOR_BETA, cagg["hits"], cagg["trials"])
            clo, chi = confidence_interval_95(ca, cb)
            cohorts[cohort] = {
                "hits": cagg["hits"],
                "trials": cagg["trials"],
                "discovery": _posterior_mean(ca, cb),
                "ci95": [clo, chi],
            }
        per_tool.append(
            {
                "tool": tool,
                "hits": agg["hits"],
                "trials": agg["trials"],
                "discovery": _posterior_mean(a, b),
                "ci95": [lo, hi],
                "alpha": a,
                "beta": b,
                "by_cohort": cohorts,
            }
        )

    if total_trials > 0:
        oa, ob = beta_posterior(PRIOR_ALPHA, PRIOR_BETA, total_hits, total_trials)
        ovr_lo, ovr_hi = confidence_interval_95(oa, ob)
        overall = {
            "hits": total_hits,
            "trials": total_trials,
            "discovery": _posterior_mean(oa, ob),
            "ci95": [ovr_lo, ovr_hi],
        }
    else:
        overall = {
            "hits": 0,
            "trials": 0,
            "discovery": _posterior_mean(PRIOR_ALPHA, PRIOR_BETA),
            "ci95": list(confidence_interval_95(PRIOR_ALPHA, PRIOR_BETA)),
        }

    return {"per_tool": per_tool, "overall": overall}


def use_confidence(usage_events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute per-tool Use posterior from usage events.

    Each event must carry:
      - tool         (str)
      - key_hash     (str)            — opaque api_key hash, never raw key
      - ts_unix      (float | int)    — event timestamp (epoch seconds)
      - cohort       (str, optional)

    For each (key_hash, tool):
      - the EARLIEST event is the "first invocation" (counts as 1 trial)
      - if ANY further event for the same (key_hash, tool) occurs within
        USE_RETURN_WINDOW_SECONDS of the first → 1 hit
    Anonymous events (no key_hash) are skipped — Use only makes sense
    against an identifiable returner.

    Returns the same shape as `discovery_confidence`.
    """
    by_pair: dict[tuple[str, str], list[float]] = {}
    cohort_of: dict[tuple[str, str], str] = {}
    for ev in usage_events:
        tool = ev.get("tool")
        kh = ev.get("key_hash")
        ts = ev.get("ts_unix")
        if not tool or not kh or ts is None:
            continue
        try:
            ts_f = float(ts)
        except (TypeError, ValueError):
            continue
        pair = (kh, tool)
        by_pair.setdefault(pair, []).append(ts_f)
        # First seen cohort wins — cohorts shouldn't legitimately flip
        # for the same key, but defensive default keeps later events
        # from overwriting an earlier classification.
        cohort_of.setdefault(pair, _normalize_cohort(ev.get("cohort")))

    by_tool: dict[str, dict[str, int]] = {}
    by_tool_cohort: dict[tuple[str, str], dict[str, int]] = {}
    total_hits = 0
    total_trials = 0

    for (_kh, tool), times in by_pair.items():
        times.sort()
        t0 = times[0]
        bag = by_tool.setdefault(tool, {"hits": 0, "trials": 0})
        bag["trials"] += 1
        cohort = cohort_of[(_kh, tool)]
        cbag = by_tool_cohort.setdefault((tool, cohort), {"hits": 0, "trials": 0})
        cbag["trials"] += 1
        # "Returned within window" = any subsequent event whose dt fits.
        returned = any(0 < (t - t0) <= USE_RETURN_WINDOW_SECONDS for t in times[1:])
        if returned:
            bag["hits"] += 1
            cbag["hits"] += 1
            total_hits += 1
        total_trials += 1

    per_tool: list[dict[str, Any]] = []
    for tool in sorted(by_tool):
        agg = by_tool[tool]
        a, b = beta_posterior(PRIOR_ALPHA, PRIOR_BETA, agg["hits"], agg["trials"])
        lo, hi = confidence_interval_95(a, b)
        cohorts: dict[str, dict[str, Any]] = {}
        for cohort in KNOWN_COHORTS:
            cagg = by_tool_cohort.get((tool, cohort))
            if not cagg or cagg["trials"] == 0:
                continue
            ca, cb = beta_posterior(PRIOR_ALPHA, PRIOR_BETA, cagg["hits"], cagg["trials"])
            clo, chi = confidence_interval_95(ca, cb)
            cohorts[cohort] = {
                "hits": cagg["hits"],
                "trials": cagg["trials"],
                "use": _posterior_mean(ca, cb),
                "ci95": [clo, chi],
            }
        per_tool.append(
            {
                "tool": tool,
                "hits": agg["hits"],
                "trials": agg["trials"],
                "use": _posterior_mean(a, b),
                "ci95": [lo, hi],
                "alpha": a,
                "beta": b,
                "by_cohort": cohorts,
            }
        )

    if total_trials > 0:
        oa, ob = beta_posterior(PRIOR_ALPHA, PRIOR_BETA, total_hits, total_trials)
        ovr_lo, ovr_hi = confidence_interval_95(oa, ob)
        overall = {
            "hits": total_hits,
            "trials": total_trials,
            "use": _posterior_mean(oa, ob),
            "ci95": [ovr_lo, ovr_hi],
        }
    else:
        overall = {
            "hits": 0,
            "trials": 0,
            "use": _posterior_mean(PRIOR_ALPHA, PRIOR_BETA),
            "ci95": list(confidence_interval_95(PRIOR_ALPHA, PRIOR_BETA)),
        }

    return {"per_tool": per_tool, "overall": overall}


def overall_confidence(discovery: dict[str, Any], use: dict[str, Any]) -> dict[str, Any]:
    """Collapse per-tool Discovery + Use to a single weighted scalar each.

    Weight = trial count of that tool (so chatty tools dominate the
    headline number, which is what we want — a 100% Discovery on a tool
    that's been called twice should not pull the headline into >90%).
    """

    def _weighted(rows: list[dict[str, Any]], key: str) -> float:
        if not rows:
            return _posterior_mean(PRIOR_ALPHA, PRIOR_BETA)
        num = 0.0
        den = 0
        for r in rows:
            t = int(r.get("trials") or 0)
            if t <= 0:
                continue
            num += float(r[key]) * t
            den += t
        if den == 0:
            return _posterior_mean(PRIOR_ALPHA, PRIOR_BETA)
        return num / den

    disc_rows = discovery.get("per_tool") or []
    use_rows = use.get("per_tool") or []
    return {
        "discovery_weighted": _weighted(disc_rows, "discovery"),
        "use_weighted": _weighted(use_rows, "use"),
        "discovery_overall": (discovery.get("overall") or {}).get("discovery"),
        "use_overall": (use.get("overall") or {}).get("use"),
    }
