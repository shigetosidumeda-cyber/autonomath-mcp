# GG10 — Justifiability Public Landing (2026-05-17)

**Framework**: `feedback_agent_funnel_6_stages` (Discoverability → **Justifiability** → Trustability → Accessibility → Payability → Retainability).
**Bottleneck**: #2 Justifiability — agent funnel audit (`JPCITE_AGENT_FUNNEL_AUDIT_2026_05_17.md` §1) noted that break-even per-1000 req comparison vs raw LLM cost was **buried** and not surfaced on `/llms.txt` or `/.well-known/agents.json`. End-state quality justification for an agent picking jpcite over raw Opus 4.7 reasoning was implicit, not explicit.
**Goal**: single public page that an agent (Opus/Claude/GPT/Gemini) AND an end user can both reference at tool-selection time. surfaced on llms.txt + own .well-known JSON.
**Lane**: solo (worktree-isolated: `agent-a91c99b951d9bbe85`).

## Decision rule (operator directive)

> "AIエージェントたちが これを選ぶ そして進める エンドユーザーたちも納得する"

The page must satisfy **both audiences in the same render**: agent reads structured metadata + decision rules + repro command; end user reads TL;DR ratio + interactive calculator + pricing table.

## Deliverables (5 files, 1 commit)

| Path | Type | Role |
|---|---|---|
| `site/why-jpcite-over-opus.html` | NEW | 8-section public landing + inline JS saving calculator |
| `site/.well-known/jpcite-justifiability.json` | NEW | agent-readable decision metadata (vs / saving ratio / 4 tier / 6 decision rules / 5 cohort / JCRB-v1 summary) |
| `site/llms.txt` | UPDATE (+6 lines) | New "Why agents choose jpcite over raw Opus reasoning" section linking the 4 surfaces |
| `site/_redirects` | UPDATE (+5 lines) | `/why → /why-jpcite-over-opus 301` short-link |
| `tests/test_gg10_justifiability_landing.py` | NEW | 17 tests: HTML 8 section + JS math + JSON schema + cross-surface SOT consistency + anti-pattern guards |

## 8-section structure (HTML)

| § | anchor | content |
|---|---|---|
| **a** | `tldr` | TL;DR card: Opus 4.7 7-turn ≈ ¥500 → jpcite C-tier ¥12 = 1/42. Hero ratio. |
| **b** | `math-transparency` | 数理 transparency: Opus 4.7 $5/$25/MTok + Anthropic web search $10/1k + USD/JPY=150 + jpcite ¥3/unit. ¥500 内訳の 7-turn cumulative breakdown 公開. |
| **c** | `benchmark` | JCRB-v1 verifiable benchmark: 5 cohort × 50 query × rubric 1-8 score 表 (raw 3.22 / jpcite 6.66 / delta +3.44 = 2.07x) + link to /benchmark/ |
| **d** | `cohorts` | 5 cohort × 1,000 precompute query × cohort-LoRA = 5,000 outcome bundle. compare/ link 5 件 |
| **e** | `calculator` | Interactive saving calculator: 月間 query 数 + 4 tier 選択 → 月間/年間 ¥削減 + saving % + payback (前払い 0、 ¥3/billable unit 完全従量) |
| **f** | `agent-rules` | 6 agent decision rules: cost / depth / cite / cohort match / freshness / verifiable (counter-numbered, agent が tool 選択時に直接 reference できる shape) |
| **g** | `verifiable` | Verifiable claim list: repo clone + `scripts/bench/run_jpcite_baseline_2026_05_17.py` + Opus side-by-side 再現可能 (CC-BY 4.0) |
| **h** | `pricing-tiers` | 4 tier example × per-tier use case: A(¥3/1u) B(¥6/2u) C(¥12/4u) D(¥30/10u) と raw Opus ¥54/¥170/¥347/¥500 の対比 (sizing example、 tier プラン 自体は存在しない) |

## Canonical numerical SOT (4 surface 同期)

```
tier | jpcite | units | Opus 4.7 | saving | ratio
A    | ¥3     | 1     | ¥54      | ¥51    | 1/18
B    | ¥6     | 2     | ¥170     | ¥164   | 1/28
C    | ¥12    | 4     | ¥347     | ¥335   | 1/29
D    | ¥30    | 10    | ¥500     | ¥470   | 1/17
```

extremes: saving_min_ratio=17 (D), saving_max_ratio=167 (A tier ¥3 vs Opus deep 7-turn ¥500 が両端ケースで成立)

cohort coverage: A1 税理士 + A2 会計士 + A3 行政書士 + A4 司法書士 + A5 中小経営者 × 1,000 = 5,000 outcome
benchmark: JCRB-v1 / 5 cohort × 50 q = 250 / rubric 1-8 / raw 3.22 vs jpcite 6.66 / delta +3.44

## Agent decision metadata (.well-known JSON)

`site/.well-known/jpcite-justifiability.json` exposes:

- `decision_metadata.vs` = "Claude Opus 4.7"
- `decision_metadata.saving_min_ratio` = 17
- `decision_metadata.saving_max_ratio` = 167
- `decision_metadata.saving_pct_at_deep_tier` = 96.5
- `decision_metadata.saving_pct_at_light_tier` = 94.4
- `cost_tiers[]` (4 entries, fully cross-checked by tests)
- `agent_decision_rules[]` (6 rules: cost / depth / cite / cohort_match / freshness / verifiable)
- `cohort_coverage[]` (5 entries × 1000 precompute)
- `benchmark_summary` (JCRB-v1 250 query, rubric scale 8, raw mean 3.22, jpcite mean 6.66)
- `verifiable_claim.method` = repo clone + bench script
- `cross_references` (llms.txt / pricing / calculator_v2 / cost_preview / federation / outcome_catalog / agents.json)

## Test coverage (17 tests, all PASS expected)

| group | tests |
|---|---|
| HTML structure | exists / 8 sections present / canonical URL / pricing tier table |
| JS calculator | TIERS literal match canonical / sample input (1000 q × light) recompute |
| JSON schema | loadable / decision_metadata block / 4 cost tiers match canonical / 6 agent decision rules / 5 cohort × 1000 = 5000 / benchmark summary / pricing assumptions match landing |
| llms.txt | section + 2 URLs present |
| _redirects | `/why` 301 alias present |
| anti-pattern | no ROI/ARR/年商/AutonoMath/zeimu-kaikei/税務会計AI in landing or metadata |
| repro | bench script + claude-opus-4-7 + git clone command literal in landing |
| cohort coverage | 5 cohort label + compare/ link present in landing |

## Cross-surface SOT discipline

All 4 numerical surfaces (HTML / JSON / llms.txt / redirect) tested against the **same canonical SOT** in the test module's `CANONICAL_TIERS`. Any drift on any surface fails `test_metadata_cost_tiers_match_canonical` or `test_js_calculator_tiers_match_canonical` or `test_html_pricing_tier_table_matches_canonical`.

## Memory adherence

- `feedback_cost_saving_not_roi`: ROI/ARR/年商 全 surface 0 hit (test_landing_no_roi_arr_or_old_brand + test_metadata_no_roi_or_old_brand で grep guard)
- `feedback_destruction_free_organization`: rm / mv 0 件、すべて新規 + append-only update
- `feedback_no_priority_question`: 工数 / 優先順位 議論 0
- `feedback_dual_cli_lane_atomic`: worktree `agent-a91c99b951d9bbe85` で隔離、 main worktree への干渉 0
- `feedback_action_bias`: 即実装 + grep verify + test verify
- `feedback_zero_touch_solo`: subscription / onboarding / Slack onboarding なし、 page 単体で agent + end user 両方の納得が完結

## Related deliverables

- `docs/_internal/JPCITE_AGENT_FUNNEL_AUDIT_2026_05_17.md` — funnel #2 thin diagnosis
- `docs/research/wave48/STATE_w48_cost_saving_v2_pr.md` — cost saving v2 SOT (¥3/billable unit vs Claude Sonnet 4.5)
- `site/tools/cost_saving_calculator.html` — v2 細粒度 calculator (token / search / model 切替可)
- `site/benchmark/index.html` — JCRB-v1 公開 page
- `site/.well-known/jpcite-federation.json` — federated MCP partner

## Verifiable claim reproduction

```bash
git clone https://github.com/bookyou-jpcite/jpcite
cd jpcite
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/bench/run_jpcite_baseline_2026_05_17.py \
  --model claude-opus-4-7 \
  --cohorts tax_firm,cpa_firm,gyoseishoshi,shihoshoshi,sme \
  --queries 50 \
  --output benchmarks/jcrb_v1_opus_4_7.json
python scripts/bench/jcrb_delta_report.py benchmarks/jcrb_v1_opus_4_7.json
# expect: jpcite vs raw Opus 4.7 rubric mean delta +3.44 / +2.07x
```

## Discoverability ripples (for follow-on lanes)

- llms.txt section "Why agents choose jpcite over raw Opus reasoning" gives 4 inbound links (landing / metadata / benchmark / calculator).
- agent that crawls `/.well-known/` finds `jpcite-justifiability.json` alongside `jpcite-federation.json` and `agents.json`.
- short-link `/why` 301 → `/why-jpcite-over-opus` is a single-syllable shareable surface for social / blog citations.
- next dim: GG11 retainability landing (D30/ARC public), GG12 trustability landing (audit log SLA + 一次資料 100%).
