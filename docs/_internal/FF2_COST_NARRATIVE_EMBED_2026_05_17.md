# FF2 — Cost-Saving Narrative Embed (2026-05-17 lane:solo)

> **Status**: LANDED 2026-05-17.
> **Predecessor**: `JPCITE_COST_ROI_SOT_2026_05_17.md` (FF1 SOT — the canonical numbers).
> **CRITICAL invariant**: "story きれいに見せて + 実際のサービスもそれに正確に厳密に伴う必要があります" (operator).
> **Service ↔ Narrative match** is gated by `scripts/validate_cost_saving_claims_consistency.py`
> and the GHA workflow `.github/workflows/cost-saving-consistency.yml`.

## 1. Goal

Make every agent-facing jpcite surface advertise the same machine-readable
cost-saving narrative so an LLM agent reading a tool description, an OpenAPI
operation, or `.well-known/agents.json` reaches the identical conclusion:
"this jpcite call returns the structured answer for ¥3-30, equivalent to a
3-7 turn Opus 4.7 evidence chain at 1/17 - 1/167 the cost."

## 2. Surfaces touched

| Surface | Files | Mutation |
|---|---|---|
| MCP descriptions | `mcp-server*.json` (4 files) | Footer with tier + ¥ + opus_yen + saving |
| OpenAPI | `site/openapi*.json`, `site/openapi/*.json`, `site/docs/openapi/*.json` (6 files, 766 ops) | `x-cost-saving` extension per operation |
| llms.txt | `site/llms.txt`, `site/llms-full.txt` | New `## Cost saving claim (machine readable)` section |
| agents.json | `site/.well-known/agents.json` | New `cost_efficiency_claim` block (tier map + ratio envelope) |
| pricing.html | `site/pricing.html` | Tier table + 5 cohort matrix + JS calculator + "1/83 example" link |
| Product cards (A1..A5) | `site/products/A1..A5_*.html` | `<section class="cost-saving-card" data-cost-saving-card="FF2">` |

Tier classifier (same code path on every store):

```
Tier D: evidence_packet_full / portfolio_analysis / regulatory_impact_chain / HE-1_full / HE1_full
Tier C: precomputed_answer / agent_briefing / HE-1 / HE-3 / cohort / regulatory_impact / jpcite_route|preview|execute
Tier B: search_v2_ / expand_ / get_with_relations_ / batch_get_ / semantic_ / match_
Tier A: everything else (search_, list_, get_simple_, enum_, find_, check_, count_, get_)
```

Quintuple table (mirrors FF1 SOT §3 exactly):

| Tier | jpcite ¥ | Opus turns | Opus ¥ | Saving % | Saving ¥ |
|---|---|---|---|---|---|
| A | 3 | 3 | 54 | 94.4 % | 51 |
| B | 6 | 5 | 170 | 96.5 % | 164 |
| C | 12 | 7 | 347 | 96.5 % | 335 |
| D | 30 | 7 | 500 | 94.0 % | 470 |

## 3. Scripts

- `scripts/ff2_embed_cost_saving_footer.py` — MCP footer injector (idempotent).
- `scripts/ff2_embed_openapi_cost_saving.py` — OpenAPI `x-cost-saving` injector.
- `scripts/ff2_embed_llms_narrative.py` — llms.txt + llms-full.txt narrative injector.
- `scripts/ff2_embed_html_cards.py` — pricing.html calc + product saving cards.
- `scripts/ff2_apply_all.py` — orchestrator. Runs all 4 injectors + agents.json upsert + validator.
- `scripts/validate_cost_saving_claims_consistency.py` — drift gate. Non-zero exit on any mismatch.

## 4. Tests

`tests/test_ff2_cost_saving_narrative.py` — 24 tests in 11 cases:

1. FF1 SOT exists & cites every tier price
2. MCP footer present on every tool (4 manifests)
3. MCP footer cites SOT doc reference
4. OpenAPI x-cost-saving present (6 OpenAPI files)
5. agents.json cost_efficiency_claim exact-match SOT §3 quintuple
6. validator returns 0 on clean tree
7. Tier ratio envelope (17 / 167) consistent with arithmetic
8. llms.txt section present
9. llms-full.txt section present
10. pricing.html calculator + cohort table + SOT link present
11. Product A1..A5 cards present
12. Distribution manifest pricing untouched (`¥3/req` flat preserved)

All 24 tests pass at landing. Each Python file is mypy --strict 0 and ruff 0.

## 5. GHA workflow

`.github/workflows/cost-saving-consistency.yml` runs the validator on every
PR that touches: mcp-server*.json / site/openapi*.json / site/.well-known/agents.json /
the FF1 SOT / the FF2 scripts themselves. Concurrency group keeps the gate
single-flight per ref.

## 6. Idempotency contract

All injectors are idempotent and re-run safe. Re-run order on any drift:

```
.venv/bin/python scripts/ff2_apply_all.py
```

The orchestrator prints per-store `changed` counts and ends with the
validator output: `TOTAL_ERR=0` is the only acceptable terminal state.

## 7. What this is NOT

- **Not a price change.** Billing remains flat ¥3 / billable unit. Tier
  labels A/B/C/D advertise the *bundle cost* of a typical agent action
  (multi-step chain) and the depth-equivalence to an Opus chain.
  No commercial-tier UI, no seat counters, no annual minimum.
- **Not aggregator-friendly.** Aggregators (noukaweb, hojyokin-portal,
  etc.) remain banned per AGENTS.md §2.5.
- **Not an LLM call.** The `cost-saving-claim` text is precomputed and
  rendered at build time — no production-path LLM is invoked.

## 8. Cross-refs

- FF1 SOT: `docs/_internal/JPCITE_COST_ROI_SOT_2026_05_17.md`
- Pricing V3: `docs/_internal/JPCITE_PRICING_V3_2026_05_17.md` (Tier A/B/C/D wire prices)
- Cost-saving public examples: `docs/canonical/cost_saving_examples.md`
- Memory anchors: `feedback_cost_saving_v2_quantified`, `feedback_cost_saving_not_roi`
