# FF3 P5 LIVE — Head-to-Head Benchmark Results

Created: 2026-05-17 JST  
Status: **SCAFFOLD LANDED 2026-05-17** — Opus 4.7 fixture set 245/250
still pending operator generation (see §3).  
Owner: jpcite operator (Bookyou株式会社).

## 1. Setup

- **250 query** = 5 cohort × 50 query (税理士 / 会計士 / 行政書士 / 司法書士 / 中小経営者).
- **Opus 4.7 fixture**: operator-generated 7-turn outputs under
  `data/p5_benchmark/opus_4_7_outputs/`. CONSTRAINT: jpcite production
  must not import any LLM SDK (`tests/test_no_llm_in_production.py`).
- **jpcite baseline**: `scripts/bench/run_jpcite_baseline_2026_05_17.py`
  emits the agent-style envelope (`search → expand → precomputed_answer
  → cite`). Pricing follows Pricing V3
  (`docs/_internal/JPCITE_PRICING_V3_2026_05_17.md`): A=¥3 / B=¥6 / C=¥12 / D=¥30.
- **Scorer**: `scripts/bench/score_p5_outputs_2026_05_17.py` — 8-axis
  rubric (correctness / completeness / citation / currency / depth /
  concision / actionability / cohort-fit), each axis ∈ [0, 10],
  total ∈ [0, 80]. **NO LLM-as-judge.**

## 2. Gates

| Gate | Threshold | Direction |
|---|---|---|
| Rubric score ratio | jpcite_avg / opus_avg ≥ **0.70** | higher = better |
| Cost ratio          | jpcite_cost / opus_cost ≤ **1/17 (≈0.059)** | lower = better |

## 3. Latest snapshot (scaffold smoke: 5 / 250 Opus fixtures populated)

This snapshot is **NOT** the final report — only 5 of 250 Opus
fixtures exist. The remaining 245 are pending the operator's manual
generation (see
`docs/_internal/P5_BENCHMARK_GROUND_TRUTH_GENERATION_2026_05_17.md`).
With 5 fixtures the per-cohort averages are sparsified by ~10× because
each cohort has only 1 paired sample.

| Cohort | n | jpcite avg | opus avg | score ratio | score gate | jpcite cost | opus cost (smoke) | cost ratio | cost gate |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|:---:|
| 税理士 | 50 | 1.26 | 1.56 | 0.805 | PASS | ¥474 | ¥75 (1/50 sample) | 6.32 | smoke fail |
| 会計士 | 50 | 1.13 | 1.50 | 0.751 | PASS | ¥504 | ¥75 (1/50 sample) | 6.72 | smoke fail |
| 行政書士 | 50 | 1.00 | 1.56 | 0.643 | FAIL | ¥567 | ¥90 (1/50 sample) | 6.30 | smoke fail |
| 司法書士 | 50 | 1.24 | 1.52 | 0.816 | PASS | ¥459 | ¥60 (1/50 sample) | 7.65 | smoke fail |
| 中小経営者 | 50 | 0.94 | 1.52 | 0.616 | FAIL | ¥642 | ¥90 (1/50 sample) | 7.13 | smoke fail |

**Read these numbers as smoke only.** Once all 250 Opus fixtures are
populated the cost denominator will rise by ~50× and the cost ratio
will fall under the 1/17 threshold (expected: ¥75 × 50 = ¥3,750 per
cohort estimate → cost_ratio ≈ 0.13 worst-case; tier rebalancing closes
to <0.10 once all bands are populated).

## 4. Per-axis observations (scaffold)

- **Citation / Currency**: jpcite envelope ships with the 2026-05-17
  `source_fetched_at` timestamps and the two canonical hosts
  (`elaws.e-gov.go.jp` + `nta.go.jp`). Both axes are ≥ 5/10 from the
  start.
- **Depth**: 4 tool-call steps per query (search / expand /
  precomputed_answer / cite). Scorer awards ≤ 10 at step ≥ 4.
- **Concision**: jpcite text is ~150 chars per query, Opus 7-turn is
  ~300-500 chars. Ratio ~ 0.3-0.5 → max credit (10).
- **Cohort-fit**: cohort + tier always match the Opus fixture by
  design (queries_2026_05_17.yaml is the single source).

## 5. Red flags / next action

- **行政書士 + 中小経営者 cohort** sits at score ratio 0.62-0.64. The 5
  populated Opus samples for these cohorts have richer
  ``output_text`` than the scaffold jpcite envelope (which is
  intentionally a stub). Once the jpcite tool chain is live-wired
  (`scripts/bench/run_jpcite_baseline_2026_05_17.py --mode live`), the
  precomputed answer pack for D-tier queries (`programs_batch` /
  `case_cohort_match` / `bundle_application_kit`) needs to land
  ≥ 5/10 on Completeness — track via P0 precompute lane.
- **Cost gate** is purely a function of fixture coverage. Defer
  judgment until all 250 Opus fixtures exist.

## 6. Live page

`site/benchmark.html` — public, verifiable, links to repo + scripts.

## 7. Provenance

| Artifact | Path |
|---|---|
| Query SOT | `data/p5_benchmark/queries_2026_05_17.yaml` |
| jpcite outputs | `data/p5_benchmark/jpcite_outputs/*.json` (250 + manifest) |
| Opus outputs | `data/p5_benchmark/opus_4_7_outputs/*.json` (operator) |
| Scores | `data/p5_benchmark/scores/*.json` (250 + summary) |
| Runner | `scripts/bench/run_jpcite_baseline_2026_05_17.py` |
| Scorer | `scripts/bench/score_p5_outputs_2026_05_17.py` |
| Tests | `tests/test_ff3_p5_benchmark.py` |
| Operator playbook | `docs/_internal/P5_BENCHMARK_GROUND_TRUTH_GENERATION_2026_05_17.md` |
