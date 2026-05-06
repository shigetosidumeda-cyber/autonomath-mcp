"""AutonoMath analytics package (P5-attribution / Bayesian confidence).

Houses the Bayesian Discovery+Use confidence model that computes
posterior probabilities of (a) a customer finding a relevant tool
(Discovery) and (b) returning to it within 7 days (Use), per-tool and
per-cohort. Outputs feed both the public confidence dashboard
(/v1/stats/confidence + site/confidence.html) and the daily snapshot
log under analytics/confidence_<YYYY-MM-DD>.json.

Pure-math + scipy only — no LLM / SDK calls.

Numerical targets (v8 plan):
  - Discovery >= 90% by T+90d, >= 95% by Y1
  - Use       >= 80% by T+90d, >= 92% by Y1

The methodology document lives at docs/confidence_methodology.md.
"""

from __future__ import annotations

from jpintel_mcp.analytics.bayesian import (
    beta_posterior,
    confidence_interval_95,
    discovery_confidence,
    overall_confidence,
    use_confidence,
)

__all__ = [
    "beta_posterior",
    "confidence_interval_95",
    "discovery_confidence",
    "overall_confidence",
    "use_confidence",
]
