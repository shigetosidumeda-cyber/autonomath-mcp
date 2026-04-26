"""Self-improvement loops package.

Ten zero-LLM closed-loop pipelines that run on a daily/weekly/monthly cadence
post-launch. Each loop:

  * Reads structured signals from telemetry / DB tables
  * Optionally clusters with e5-small + DBSCAN (local model, no API calls)
  * Proposes actions (label / row update / SEO copy / cache entry)
  * Writes them as `dry_run` JSON for operator review before any production
    write — operator promotes them by re-running the loop with `dry_run=False`.

NEVER call any LLM provider (Anthropic / OpenAI / Gemini). Inference is local
or rules-based only — see `feedback_autonomath_no_api_use` in operator memory.

Cadence summary
---------------
- Loop A — hallucination_guard expansion       weekly
- Loop B — testimonial -> SEO/GEO              monthly
- Loop C — personalized cache                  weekly
- Loop D — forecast accuracy                   monthly
- Loop E — multi-language alias expansion      weekly
- Loop F — channel ROI                         weekly
- Loop G — invariant expansion                 monthly
- Loop H — cache warming (Zipf)                daily
- Loop I — doc freshness re-fetch priority     weekly
- Loop J — gold.yaml expansion candidates      monthly

Implementation status: scaffolding only (T+30d for real ML wiring).
"""

from __future__ import annotations

__all__ = [
    "loop_a_hallucination_guard",
    "loop_b_testimonial_seo",
    "loop_c_personalized_cache",
    "loop_d_forecast_accuracy",
    "loop_e_alias_expansion",
    "loop_f_channel_roi",
    "loop_g_invariant_expansion",
    "loop_h_cache_warming",
    "loop_i_doc_freshness",
    "loop_j_gold_expansion",
]

LOOP_NAMES: tuple[str, ...] = (
    "loop_a_hallucination_guard",
    "loop_b_testimonial_seo",
    "loop_c_personalized_cache",
    "loop_d_forecast_accuracy",
    "loop_e_alias_expansion",
    "loop_f_channel_roi",
    "loop_g_invariant_expansion",
    "loop_h_cache_warming",
    "loop_i_doc_freshness",
    "loop_j_gold_expansion",
)
