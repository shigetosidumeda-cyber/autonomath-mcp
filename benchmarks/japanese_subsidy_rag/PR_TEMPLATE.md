# PR Submission Template

This file contains two ready-to-paste PR bodies — one for **BIG-bench** and one
for **HELM** (Stanford CRFM). Use whichever target you are submitting to.

---

## Option 1: BIG-bench (`google/BIG-bench`)

### Title

`task: japanese_subsidy_rag — JA RAG benchmark with refusal & citation metrics`

### Body

```markdown
## Task summary

`japanese_subsidy_rag` is a Japanese-language retrieval-augmented QA benchmark
covering public-program domains (subsidies, loans, tax incentives, certifications,
enforcement, statutes, case law). It exercises three behaviors that existing
JA benchmarks (MMLU-ja, JGLUE, JCommonsenseQA) do **not** cover:

1. **Deadline / amount arithmetic** with primary-source citation.
2. **Refusal** on out-of-distribution program names ("第99回" of a program with
   only 12 rounds).
3. **Correction** of widely-circulated misconceptions (60 phrases from a
   production hallucination guard, severity-tagged across 5 audiences ×
   6 verticals).

## Why this benchmark is needed

- LLMs frequently produce confidently-wrong answers on Japanese public-program
  questions because primary sources are scattered (中小企業庁 / 経産省 / 農水省 /
  47 prefectures) and aggregator copies in training data are stale.
- A misstated 公募締切 or 補助上限 directly harms an SMB applicant — this is a
  high-stakes RAG domain where current evals are silent.
- Existing JA benchmarks reward answering; this task rewards "I don't know"
  when the program does not exist. That mirrors the production loss surface.

## Number of examples

- **30** Tier A — hand-curated gold (deadline / amount / law citation).
- **60** Tier C — adversarial misconceptions with `correction` text and
  `law_basis` references.
- **Total: 90.**

(Tier B — DB-derived synthetic — was deliberately excluded from the public
benchmark because gold values depend on a versioned internal DB snapshot under
mixed source licenses.)

## What is the task trying to measure?

| Tier | Metric                            | Threshold |
| ---- | --------------------------------- | --------- |
| A    | precision@1                       | ≥ 0.85    |
| A    | citation_rate                     | = 1.00    |
| A    | hallucination_rate                | ≤ 0.02    |
| A    | recall@5                          | ≥ 0.95    |
| C    | refusal_or_correction_acc         | ≥ 0.90    |

The scorer is fully deterministic — pure regex / substring / canonical-form
normalization. **No LLM-as-judge.** That is intentional: an LLM judge would
re-introduce hallucination into the metric and break reproducibility.

## Behaviors of the model that are tested

- **Knowledge**: does the model know the 公募締切, 補助上限, 根拠条文 of named
  Japanese programs?
- **Retrieval**: when given access to retrieval, does it cite a primary source
  (registrable-domain match against `gold_source_host`)?
- **Refusal**: does the model decline to answer for nonexistent programs?
- **Correction**: when prompted with a misconception, does the model rebut it
  with the correct fact and law basis?

## Design considerations

- **Canary string** prevents training-data contamination:
  `BENCHMARK_DATA_SHOULD_NOT_BE_INCLUDED_IN_TRAINING_DATA_jpsubsidy_rag_v1__c0e7b3a4d8f29b1e7c5a4d63ef21b08a`
- **Normalizers** (yen/万円, ISO/和暦, law canonical-id) are spec'd in
  `task.json:metric_metadata.normalizers` so scoring is unambiguous.
- **Evaluator self-disclosure**: submitters must report `model_id`,
  `retriever_id`, `corpus_id`, `knowledge_cutoff`. We deliberately do not
  prescribe the retriever — we want to compare retrieval stacks.
- **No external API at score time.** The grader is local Python, no network.

## Limitations

- Single language (ja-JP). A bilingual or English-shadow variant is not
  included in v1.
- Gold answers reference primary-source URLs; if a government site reorganizes
  paths, the `citation_rate` metric uses **registrable-domain match** (not full
  URL) so cosmetic URL drift does not invalidate scores. Annual review will
  refresh the example set if any host migrates.
- Tier C correction phrasing is curated by domain experts (税理士 / 行政書士
  audience surveys); the 60 phrases reflect 2025-2026 production frequency
  and may shift over time.

## Conflict-of-interest disclosure

The submitter (Bookyou K.K., legal entity behind the AutonoMath product) maintains
a Japanese-program database used internally for product features. **The benchmark
does not require AutonoMath access** — gold answers are derived from publicly
available primary sources, and the scoring rules explicitly forbid evaluators
from calling the AutonoMath API or MCP tools during a run. The benchmark is
designed to evaluate any RAG stack honestly, not to advantage AutonoMath.

## Files

- `benchmarks/japanese_subsidy_rag/README.md` — task overview
- `benchmarks/japanese_subsidy_rag/task.json` — BIG-bench spec
- `benchmarks/japanese_subsidy_rag/examples.jsonl` — 90 examples
- `benchmarks/japanese_subsidy_rag/helm_format.json` — HELM scenario spec
- `benchmarks/japanese_subsidy_rag/baseline_scores.md` — submitter baseline (TBD)

## License

- Questions: CC-BY 4.0
- Gold answers cite primary sources whose individual licenses are listed
  per row (PDL v1.0 NTA bulk, e-Gov CC-BY 4.0, government-standard v2.0, etc.)

## Citation

```bibtex
@misc{autonomath2026japanesesubsidyrag,
  title  = {Japanese Subsidy & Tax-Law RAG Benchmark},
  author = {Bookyou K.K.},
  year   = {2026},
  url    = {https://github.com/bookyou-net/autonomath-mcp}
}
```
```

### Checklist (BIG-bench reviewers commonly ask for these)

- [x] Task name is unique and descriptive
- [x] `task.json` includes `canary_string`
- [x] Examples ≥ 32
- [x] Metrics are deterministic and machine-graded
- [x] No external API required at score time
- [x] Description explains why behavior is hard / interesting
- [x] License compatible with BIG-bench (CC-BY 4.0)
- [x] Submitter conflict-of-interest disclosed

---

## Option 2: HELM (`stanford-crfm/helm`)

### Title

`scenario: japanese_subsidy_rag — JA domain QA with refusal evaluation`

### Body

```markdown
## Scenario

`JapaneseSubsidyRagScenario` evaluates Japanese-language retrieval-augmented
QA over public-program corpora. Two splits:

- `tier_a` (30) — hand-curated gold, primary metric `precision_at_1`
- `tier_c` (60) — adversarial misconceptions, primary metric
  `refusal_or_correction_acc`

## What it adds to HELM

HELM currently has limited JA-specific scenarios and none focused on
domain-specific RAG with **citation discipline** and **refusal**. Existing
QA benchmarks treat refusal as failure; this scenario flips that —
hallucinating on a Tier C trap counts against you, refusing correctly
counts toward you.

## Adapter spec

`generation`, temperature 0, max_tokens 512, no in-context demonstrations
(`max_train_instances=0`) so the evaluation is zero-shot.

## Metrics

- `PrecisionAt1Metric` (Tier A) with normalizers (yen/万円, ISO/和暦,
  law canonical-id)
- `CitationRateMetric` (Tier A) — registrable-domain match
- `HallucinationRateMetric` (Tier A) — confident wrong answer rate
- `RefusalOrCorrectionAccMetric` (Tier C) — model declines, echoes
  correction, or cites law_basis

All metric classes are pure Python (no LLM-as-judge) so HELM's
deterministic-scoring guarantee holds.

## Files

- `helm_format.json` — scenario manifest
- `examples.jsonl` — same 90 examples as BIG-bench variant
- `README.md` — full task description

## License

CC-BY 4.0 questions; primary-source URLs cited per row.

## Reproducibility

`canary_string` is included so dataset contamination can be audited via
substring search in training corpora.
```

---

## Common review questions (preempted answers)

**Q: Why not include Tier B (220 DB-derived) in the public benchmark?**
A: Tier B gold answers depend on a versioned snapshot of the AutonoMath
internal DB (autonomath.db at 8.29 GB), and several constituent rows have
mixed source licenses that cannot be redistributed in aggregate without
case-by-case review. We retain Tier B for our own regression CI but exclude
it from the public benchmark to keep licensing clean.

**Q: How do we know the gold is correct?**
A: Each Tier A row carries a `gold_source_url` linking to the primary source
(e.g. `nta.go.jp`, `e-gov.go.jp`, `maff.go.jp`, `jfc.go.jp`). The internal
verification trail (`analysis_wave18/_q3_eval_harness_scaffold_2026-04-25.md`)
cross-checks each value against the AutonoMath DB; values not directly
verifiable against a primary source are excluded.

**Q: Won't models trained on AutonoMath outputs ace this?**
A: That's why the canary string exists — submitters can audit their training
data. Additionally, the scoring rules forbid AutonoMath API access during
a run, and the gold values come from primary sources, not AutonoMath
phrasings, so memorizing AutonoMath documentation alone won't help.

**Q: Will you accept community PRs for additional examples?**
A: Yes. Open an issue on the AutonoMath repo with the proposed example +
primary source URL. We accept community contributions under CC-BY 4.0.
