# scripts/bench/ — P5 LIVE benchmark harness (deterministic, NO LLM).
#
# This package is **production-safe**: it never imports any LLM SDK,
# never spawns any LLM provider client, never reads `ANTHROPIC_API_KEY`
# or any equivalent. CI guard `tests/test_no_llm_in_production.py` is
# expected to keep passing after this lane lands.
#
# The Opus 4.7 7-turn ground-truth fixture lives under
# `data/p5_benchmark/opus_4_7_outputs/` and is generated **out of band**
# by the operator using Claude Code Max Pro. See
# `docs/_internal/P5_BENCHMARK_GROUND_TRUTH_GENERATION_2026_05_17.md`.
