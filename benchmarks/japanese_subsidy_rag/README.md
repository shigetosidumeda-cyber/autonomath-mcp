# Japanese Subsidy & Tax-Law RAG Benchmark

A **BIG-bench / HELM compatible** benchmark for evaluating LLM retrieval-augmented
generation against authoritative Japanese public-program corpora (subsidies /
loans / tax incentives / certifications / enforcement / case law).

- **Language**: Japanese (ja-JP)
- **Domains**: 補助金 (subsidy), 融資 (loan), 税制 (tax incentive), 認定 (certification),
  行政処分 (enforcement), 法令 (statute), 判例 (case law)
- **Examples**: 90 (30 Tier A hand-curated gold + 60 Tier C adversarial / refusal)
- **License**: CC-BY 4.0 (questions); gold answers cite primary sources whose
  licenses are listed per row (PDL v1.0 NTA bulk, e-Gov CC-BY 4.0, govt-standard
  v2.0, etc.)
- **Submitter**: Bookyou株式会社 (法人番号 T8010001213708, contact: info@bookyou.net)
- **Product context**: gold answers are reproducible from the AutonoMath dataset
  (`autonomath.db` 8.29 GB, `data/jpintel.db` 316 MB), but the benchmark itself
  does **not** require AutonoMath access — see "Fair comparison" below.

## Why this benchmark?

LLMs frequently hallucinate on Japanese public-program questions because:

1. **Primary sources are scattered.** Subsidy schemes live across 中小企業庁 /
   経産省 / 農水省 / 都道府県 / 商工会, each with its own URL pattern, deadline
   format, and amount notation (万円 vs ¥). No canonical aggregator existed
   before 2025.
2. **Aggregator pollution.** Common training-data aggregators (noukaweb,
   hojyokin-portal, biz.stayway) republish stale or inaccurate copies. Models
   that memorize aggregator phrasing produce confidently wrong answers ("採択
   されれば即入金", "全業種で利用可" — both flagged in `hallucination_guard.yaml`).
3. **Confident wrongness costs money.** A misstated 締切日 or 上限額 directly
   harms an SMB applicant. Existing eval suites (MMLU-ja, JGLUE, JCommonsenseQA)
   do **not** cover deadline arithmetic, citation discipline, or refusal behavior
   on out-of-distribution program names.
4. **Refusal is undertested.** Most JA benchmarks reward answering. This task
   rewards "I don't know" when the program does not exist (Tier C) — closer to
   real RAG production loss.

## Task structure

| Tier | Count | Purpose                              | Pass criterion                      |
| ---- | ----- | ------------------------------------ | ----------------------------------- |
| A    | 30    | Hand-verified gold (deadline / amount / law citation) | precision@1 ≥ 0.85, citation = 1.00 |
| C    | 60    | Adversarial misconceptions (refusal / correction)     | refusal_or_correction_acc ≥ 0.90    |

(Tier B — 220 DB-derived synthetic questions — is **excluded from the public
benchmark** because gold answers depend on AutonoMath's internal DB snapshot
and cannot be reproduced without redistributing primary-source data under
mixed licenses. Tier B is retained internally for AutonoMath regression CI.)

### Categories (per-example `category` field)

- `deadline` — 公募締切日 / 終了日 / 経過措置 (date arithmetic)
- `amount` — 上限額 / 補助率 / 控除上限 (numeric)
- `eligibility` — 対象事業者 / 業種 / 規模 (boolean / set)
- `law_citation` — 根拠法令 + 条番号 (string match)
- `refusal` — does-not-exist / unanswerable (Tier C)
- `correction` — common misconception requiring rebuttal (Tier C)

## Scoring methodology

Each example exposes a deterministic `target` (string or JSON). Scorers:

- **precision@1** (Tier A): exact-match on the primary `gold_value`.
  Permissive normalizers: yen vs 万円 unification, ISO vs 和暦 date unification
  (provided in `task.json` `metric_metadata.normalizers`).
- **recall@5** (Tier A subset that returns ranked results): gold appears in
  top-5 of model output.
- **citation_rate** (Tier A): model output contains a URL substring matching
  `gold_source_url_host` (registrable-domain match, not full URL — accommodates
  path drift on government sites).
- **hallucination_rate** (Tier A): `answered_confidently AND NOT precision@1`.
  Lower is better. Maximum 0.02 to pass.
- **refusal_or_correction_acc** (Tier C): one of —
    1. model declines to answer ("I don't know" / "情報なし" / empty), or
    2. model output contains the `correction` text (substring match), or
    3. model output cites the `law_basis` and rebuts the misconception.

All metrics are deterministic given the model's text output. No human grading.
No LLM-as-judge (which would re-introduce hallucination into the scorer).

## Expected baseline

| Model class                             | Tier A precision@1 | Tier C refusal_acc |
| --------------------------------------- | ------------------ | ------------------ |
| Closed-book frontier LLM (no retrieval) | 0.10 – 0.30        | 0.20 – 0.40        |
| Generic web-search RAG                  | 0.30 – 0.55        | 0.40 – 0.65        |
| Domain-tuned RAG over MAFF/METI/NTA     | 0.65 – 0.85        | 0.75 – 0.90        |

These are **expected ranges, not validated baselines.** The submitter's own
result is recorded in `baseline_scores.md` (template until P1 evaluation harness
runs).

## Fair comparison rules

- **Canary string.** `task.json` declares
  `BENCHMARK_DATA_SHOULD_NOT_BE_INCLUDED_IN_TRAINING_DATA_jpsubsidy_rag_v1` so
  contamination can be detected by string search in training corpora.
- **No AutonoMath API access during evaluation.** Although the gold answers
  derive from AutonoMath, evaluators MUST NOT call the AutonoMath API
  (`/v1/am/*`) or MCP tools (`autonomath-mcp` stdio) during a run. The whole
  point is to test the model's own retrieval — not to benchmark our product
  against itself.
- **Self-reporting required.** Submitters declare their retrieval stack
  (model, retriever, corpus, cutoff date) in their result write-up.
- **No paid API to grade.** The scorer is pure Python/regex; running the
  benchmark does not consume Anthropic / OpenAI / Google budget.

## How to run

```bash
# 1. Generate model outputs as JSONL (one line per example, with `id` and `output`)
python my_runner.py --task benchmarks/japanese_subsidy_rag/task.json \
                    > my_outputs.jsonl

# 2. Score
python -m benchmarks.japanese_subsidy_rag.score \
       --task benchmarks/japanese_subsidy_rag/task.json \
       --predictions my_outputs.jsonl \
       --report json
```

(Scorer is intentionally short — under 200 lines — so reviewers can audit it
in one sitting. See HELM-format variant `helm_format.json` for an alternate
runner contract.)

## Submission

See `PR_TEMPLATE.md` for the BIG-bench / HELM PR submission templates.

## Citation

```bibtex
@misc{autonomath2026japanesesubsidyrag,
  title  = {Japanese Subsidy & Tax-Law RAG Benchmark},
  author = {Bookyou K.K.},
  year   = {2026},
  note   = {AutonoMath project — benchmarks/japanese_subsidy_rag},
  url    = {https://github.com/bookyou-net/autonomath-mcp}
}
```

## Files

- `README.md` — this file
- `task.json` — BIG-bench task spec (canary, examples, metrics, normalizers)
- `examples.jsonl` — 90 examples (30 Tier A + 60 Tier C)
- `helm_format.json` — HELM scenario manifest (parallel format)
- `PR_TEMPLATE.md` — PR template for BIG-bench and HELM repositories
- `baseline_scores.md` — empty template for submitter baseline (P1 harness)
