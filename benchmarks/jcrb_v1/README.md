# JCRB-v1 — Japan Compliance Reasoning Benchmark

A 100-question public benchmark for measuring LLM reasoning accuracy on
Japanese **public-program / tax / law / enforcement** questions.

- **Language**: Japanese (ja-JP)
- **Domains** (5 × 20 = 100):
  1. `subsidy_eligibility` — 業種 × 地域 × 規模 → 補助金対象判定
  2. `tax_application` — 税制適用 (R&D / 賃上げ / 経営強化 / インボイス経過措置)
  3. `law_citation` — 根拠条文番号 (e-Gov 一次資料)
  4. `adoption_statistics` — 申請数 / 採択数 / 採択率 (公開統計)
  5. `enforcement_risk` — 補助金返還命令 / 行政処分 / 加算金率
- **License**: CC-BY 4.0 (questions). Gold answers cite primary or official
  secretariat sources
  (e-gov.go.jp, nta.go.jp, maff.go.jp, meti.go.jp, mhlw.go.jp, monodukuri-hojo.jp, etc.)
  whose individual licenses include PDL v1.0 (NTA bulk), CC-BY 4.0
  (e-Gov), and government-standard v2.0.
- **Submitter**: Bookyou株式会社 (法人番号 T8010001213708, contact: info@bookyou.net)
- **Canary**: `BENCHMARK_DATA_SHOULD_NOT_BE_INCLUDED_IN_TRAINING_DATA_jcrb_v1`

## Why this benchmark?

The product hypothesis behind jpcite is that LLMs alone cannot reliably
answer Japanese public-program questions because (a) the primary sources
are spread across 中小企業庁 / 経産省 / 農水省 / 都道府県, (b) common
training-data aggregators republish stale or wrong copies, and (c)
deadlines and rates change frequently due to 経過措置 / 改正.

JCRB-v1 quantifies that hypothesis. Each model is evaluated under two
conditions:

| Condition | What's in the prompt |
| --- | --- |
| `without_jpcite` | The question only (closed-book frontier LLM). |
| `with_jpcite` | The question + top-5 `(name, source_url)` from `https://api.jpcite.com/v1/search` for that question. |

We expect a **30-50 percentage-point lift** in `exact_match` on this
benchmark for the same model when jpcite context is provided. The exact
gap depends on the model's pre-training cutoff and aggregator exposure.

See `expected_baseline.md` for the prediction made before any model
runs land.

## Files

| File | Purpose |
| --- | --- |
| `questions.jsonl` | 100 questions (5 domains × 20). One JSON per line. |
| `run.py` | Customer-side runner. Calls Anthropic / OpenAI / Gemini HTTP APIs. NO SDK imports. |
| `scoring.py` | Pure-Python deterministic scorer. NO LLM calls. |
| `expected_baseline.md` | Pre-registered baseline predictions and lift hypothesis. |
| `submissions/` | One JSON envelope per `(model, mode)` submission. |
| `submissions/SAMPLE_README.md` | Submission envelope schema. |

Operator-side cron (NOT in this directory): `scripts/cron/jcrb_publish_results.py`
reads `submissions/*.json`, dedupes, and writes `site/benchmark/results.json`
+ `results.csv`. The cron does not call any LLM provider.

## Question schema

```json
{
  "id": "JCRB-SUB-001",
  "domain": "subsidy_eligibility",
  "question": "事業再構築補助金 通常枠 において...",
  "expected_law_ids": ["LAW-bf14a37563"],
  "expected_program_ids": ["UNI-ext-fcffb68e28"],
  "expected_value": "対象",
  "expected_source_host": "jigyou-saikouchiku.go.jp",
  "scoring_rubric": "yes_with_source"
}
```

`expected_law_ids` and `expected_program_ids` reference the jpcite
internal corpus and are NOT required for scoring (they're informative —
they show which corpus row was the citation source). The two scoring
fields are `expected_value` (substring match after light normalization)
and `expected_source_host` (registrable-domain match on URLs in output).

## Scoring contract

```
exact_match = (expected_value substring in output, normalized)
              AND
              (expected_source_host appears in any URL in output)
citation_ok = (expected_source_host appears in any URL in output)
```

Normalization handles full-width ↔ half-width, 和暦 → ISO date, and
万円 ↔ 円. The full normalizer is ~20 lines in `scoring.py` so reviewers
can audit it in one sitting.

We deliberately do NOT prescribe an LLM judge for `factual_correctness`
because it would (a) re-introduce the hallucination layer the benchmark
exists to measure, and (b) couple the score to a paid API. The
`factual_correctness` field in the score CSV is set to `null` by the
reference scorer; submitters who want it can pass their own
`factual_judge` callable to `score_one()`.

## Running

```bash
# Customer side (your hardware, your API budget)
python benchmarks/jcrb_v1/run.py \
    --provider claude --model claude-opus-4-7 \
    --mode without_jpcite \
    --out predictions/claude_without.jsonl

JPCITE_API_KEY=sk_... python benchmarks/jcrb_v1/run.py \
    --provider claude --model claude-opus-4-7 \
    --mode with_jpcite \
    --out predictions/claude_with.jsonl

# Score both (operator side or customer side — same pure-Python script)
python benchmarks/jcrb_v1/scoring.py \
    --predictions predictions/claude_without.jsonl \
    --out reports/claude_without
python benchmarks/jcrb_v1/scoring.py \
    --predictions predictions/claude_with.jsonl \
    --out reports/claude_with

# Then PR the reports/*.json into benchmarks/jcrb_v1/submissions/
# (HTTP submission is not published yet; use GitHub PR for now)
```

## Operator non-negotiables

1. **Operator never calls an LLM provider** for this benchmark. The
   `scripts/cron/jcrb_publish_results.py` cron is forbidden from
   importing `anthropic` / `openai` / `google.generativeai` /
   `claude_agent_sdk` and from referencing `ANTHROPIC_API_KEY` /
   `OPENAI_API_KEY` / `GEMINI_API_KEY` / `GOOGLE_API_KEY`. Enforced by
   `tests/test_no_llm_in_production.py`.
2. **Free to reproduce**. Customers pay only their own provider costs
   and (optionally) the jpcite ¥3/req metering for `with_jpcite` runs.
3. **Aggregators banned** from `expected_source_host`. Only government
   primary-source or official secretariat hosts matching the JCRB allowlist qualify.

## Citation

```bibtex
@misc{bookyou2026jcrb,
  title  = {JCRB-v1: Japan Compliance Reasoning Benchmark},
  author = {Bookyou K.K.},
  year   = {2026},
  note   = {jpcite project — benchmarks/jcrb_v1},
  url    = {https://jpcite.com/benchmark/}
}
```
