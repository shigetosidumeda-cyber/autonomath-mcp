# FF3 P5 LIVE — Opus 4.7 7-turn Ground-Truth Generation Playbook

Created: 2026-05-17 JST  
Status: LANDED 2026-05-17 (FF3 P5 LIVE benchmark scaffold)  
Owner: jpcite operator (Bookyou株式会社, info@bookyou.net)

## 0. Why this doc exists

The FF3 P5 LIVE benchmark must produce a **rigorous head-to-head** between
Opus 4.7 (7-turn agent workflow) and the jpcite production tool chain
(`search → expand → precomputed_answer → cite`). User directive:

> "story きれいに見せて + 実際のサービスもそれに正確に厳密に伴う必要があります"

If the cost-saving story diverges from the actual answer-quality story
by more than the threshold (jpcite ≥ Opus 70% on rubric; jpcite cost ≤
Opus 1/17 on cost), the commitment is NG and the tier must be
re-precomputed or the pricing must be re-considered.

## 1. Hard constraint: jpcite production has NO LLM API

Every production code path (`src/`, `scripts/cron/`, `scripts/etl/`,
`tests/`) is forbidden from importing `anthropic`, `openai`,
`claude_agent_sdk`, etc. (CLAUDE.md §3, enforced by
`tests/test_no_llm_in_production.py`). Therefore the Opus 4.7
ground-truth fixture is **operator-generated, out-of-band** through
Claude Code Max Pro, and laid down as static JSON files under
`data/p5_benchmark/opus_4_7_outputs/<query_id>.json`.

`scripts/bench/run_jpcite_baseline_2026_05_17.py` and
`scripts/bench/score_p5_outputs_2026_05_17.py` use stdlib only + PyYAML
(non-LLM). They are intentionally callable from CI / `pytest`.

## 2. Fixture schema (per `<query_id>.json`)

```json
{
  "query_id": "zeirishi_001",
  "cohort": "zeirishi",
  "query": "<verbatim query text from queries_2026_05_17.yaml>",
  "engine": "opus-4-7",
  "tool_calls": [
    {"step": 1, "verb": "think_through", "endpoint": null, "args": {}},
    {"step": 2, "verb": "outline", "endpoint": null, "args": {}},
    {"step": 3, "verb": "fetch_rule", "endpoint": "tax_rule_full_chain", "args": {}},
    {"step": 4, "verb": "synthesize", "endpoint": null, "args": {}},
    {"step": 5, "verb": "cite", "endpoint": "evidence_packets_query", "args": {}},
    {"step": 6, "verb": "review", "endpoint": null, "args": {}},
    {"step": 7, "verb": "render", "endpoint": null, "args": {}}
  ],
  "output_text": "<full 7-turn Opus 4.7 answer in Japanese>",
  "checklist_must_have": ["必須キーワード", "判定の核心"],
  "referenced_endpoints": ["tax_rule_full_chain", "am_by_law"],
  "citations": [
    {
      "source_url": "https://elaws.e-gov.go.jp/...",
      "source_fetched_at": "2026-05-17T00:00:00+09:00",
      "label": "e-Gov 法令検索"
    }
  ],
  "self_reported_score": 80.0,
  "cost_jpy_estimate": 75,
  "tier": "C"
}
```

* `tool_calls.step` is 1-indexed and must equal **7** exactly.
* `output_text` is the rendered answer Claude 4.7 produces at turn 7
  after `think_through → outline → fetch_rule → synthesize → cite →
  review → render`.
* `checklist_must_have` is operator-curated and represents the
  must-appear tokens in the jpcite output for Completeness credit.
* `referenced_endpoints` is the union of jpcite-equivalent endpoint
  surfaces the Opus answer references — used by the Actionability axis.
* `self_reported_score` is the operator's own 0-80 estimate of the Opus
  answer (used as the denominator for ``score_ratio``).
* `cost_jpy_estimate` is the operator-captured cost from the Claude
  Code Max Pro session (¥ equivalent for the same query as a single
  API call). The Pricing V3 dispatch references "jpcite cost ≤ Opus
  1/17" so this number anchors the cost gate.

## 3. Operator generation workflow

For each of the 250 queries in
`data/p5_benchmark/queries_2026_05_17.yaml`:

1. Open Claude Code Max Pro on a fresh session.
2. Paste the verbatim query text + the 7-turn scaffold prompt
   (see §5 below).
3. Capture the 7-turn run's final `output_text`, the steps' verbs,
   and any cited URLs.
4. Estimate `cost_jpy_estimate` from the Claude Code Max Pro session
   cost report (operator visually inspects, NOT a programmatic API
   call — that would violate `feedback_no_operator_llm_api`).
5. Author `data/p5_benchmark/opus_4_7_outputs/<query_id>.json` with the
   schema above.
6. Validate with `pytest tests/test_ff3_p5_benchmark.py` — the schema
   guard test must remain green.

## 4. Suggested schedule

| Day | Cohort | Queries |
|----:|-------|--------:|
| 1   | 税理士 | 50 |
| 2   | 会計士 | 50 |
| 3   | 行政書士 | 50 |
| 4   | 司法書士 | 50 |
| 5   | 中小経営者 | 50 |
| 6   | Re-validate + rubric pass | full sweep |

Approximate effort per query: **5-10 min** (one fresh Max Pro session
+ JSON authoring). Total: 25-50 hours over the 6-day window.

## 5. 7-turn scaffold prompt (for the operator)

```
あなたは日本の士業向けの公的制度・税務・登記・補助金 リサーチアシスタントです。
以下の質問に **7 turn** で構造化された回答をしてください。各 turn の役割は次の通り:

  turn 1 (think_through): 問題の構成要素を分解。
  turn 2 (outline):       回答骨子を箇条書きで提示。
  turn 3 (fetch_rule):    一次資料 (e-Gov / 国税庁 / 経産省 / 政策金融公庫) を
                          想定して根拠条文 / ルール名を引用 (URL は実在のものに限る)。
  turn 4 (synthesize):    引用と問題を結合し本文を生成。
  turn 5 (cite):          出典 URL を本文と紐付け。
  turn 6 (review):        漏れ・誤り・士業独占越権 (税務代理・申請書面作成
                          ・法律解釈・監査意見) のチェック。
  turn 7 (render):        最終回答。

最終 turn 7 の本文を `output_text` に格納。必須キーワード ≥ 3 を
`checklist_must_have` に格納。
```

## 6. Score / cost gate

The scorer (`scripts/bench/score_p5_outputs_2026_05_17.py`) computes per
cohort:

* `jpcite_avg_score / opus_avg_score` (rubric out of 80) → must be ≥ 0.70.
* `jpcite_total_cost / opus_total_cost_estimate` → must be ≤ 1/17.

Per-cohort failure → re-precompute that tier's answer pack OR re-think
the price band in Pricing V3.

## 7. References

- `data/p5_benchmark/queries_2026_05_17.yaml` — 250-query SOT.
- `scripts/bench/run_jpcite_baseline_2026_05_17.py` — jpcite baseline.
- `scripts/bench/score_p5_outputs_2026_05_17.py` — rubric scorer.
- `tests/test_ff3_p5_benchmark.py` — schema + invariant guards.
- `site/benchmark.html` — public-facing benchmark page (verifiable).
- `docs/_internal/JPCITE_PRICING_V3_2026_05_17.md` — V3 unit ladder.
- `docs/_internal/JPCITE_COHORT_PERSONAS_2026_05_17.md` — cohort
  workflow map (used to design the 5 × 50 split).
