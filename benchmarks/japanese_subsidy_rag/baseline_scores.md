# Baseline Scores

Template for the submitter's own benchmark result. **Empty until P1
evaluation harness (`tests/eval/run_eval.py`) is wired up and produces a
public-reportable number.**

Per the benchmark's fairness rules:

- The submitter's "baseline" must be evaluated under the **same fairness
  constraints** as any other submission — no AutonoMath API access during
  the run, deterministic scorer, self-reported retrieval stack.
- We deliberately publish a baseline that may not be the highest-possible
  score for AutonoMath. The point of the benchmark is honest measurement,
  not a vanity metric.

## Run record (fill in after P1 harness completes)

### Submitter result

| Field                     | Value           |
| ------------------------- | --------------- |
| Submitter                 | Bookyou K.K.    |
| Product                   | AutonoMath      |
| Run date (JST)            | _TBD_           |
| Benchmark version         | 1.0.0           |
| Canary string in corpus?  | _TBD (audit)_   |

### Stack disclosure

| Field                     | Value           |
| ------------------------- | --------------- |
| Model                     | _TBD_           |
| Retriever                 | _TBD_           |
| Corpus / source mix       | _TBD_           |
| Knowledge cutoff          | _TBD_           |
| Used AutonoMath API?      | **NO** (forbidden by fairness rule) |

### Tier A (30 examples)

| Metric              | Score   | Threshold | Pass? |
| ------------------- | ------- | --------- | ----- |
| precision@1         | _TBD_   | ≥ 0.85    | _TBD_ |
| recall@5            | _TBD_   | ≥ 0.95    | _TBD_ |
| citation_rate       | _TBD_   | = 1.00    | _TBD_ |
| hallucination_rate  | _TBD_   | ≤ 0.02    | _TBD_ |

### Tier C (60 examples)

| Metric                       | Score   | Threshold | Pass? |
| ---------------------------- | ------- | --------- | ----- |
| refusal_or_correction_acc    | _TBD_   | ≥ 0.90    | _TBD_ |

### Per-category breakdown (Tier A)

| Category       | n  | precision@1 | citation_rate |
| -------------- | -- | ----------- | ------------- |
| deadline       | 6  | _TBD_       | _TBD_         |
| amount         | 6  | _TBD_       | _TBD_         |
| eligibility    | 4  | _TBD_       | _TBD_         |
| law_citation   | 14 | _TBD_       | _TBD_         |

### Per-vertical breakdown (Tier C)

| Vertical    | n  | refusal_or_correction_acc |
| ----------- | -- | ------------------------- |
| 補助金      | 10 | _TBD_                     |
| 税制        | 10 | _TBD_                     |
| 融資        | 10 | _TBD_                     |
| 認定        | 10 | _TBD_                     |
| 行政処分    | 10 | _TBD_                     |
| 法令        | 10 | _TBD_                     |

### Per-audience breakdown (Tier C)

| Audience    | n  | refusal_or_correction_acc |
| ----------- | -- | ------------------------- |
| 税理士      | 12 | _TBD_                     |
| 行政書士    | 12 | _TBD_                     |
| SMB         | 12 | _TBD_                     |
| VC          | 12 | _TBD_                     |
| Dev         | 12 | _TBD_                     |

## Update procedure

1. Run P1 harness against a known-good model + retrieval stack:
   ```
   .venv/bin/python -m tests.eval.run_eval --tier=all --report=json \
     > benchmarks/japanese_subsidy_rag/_baseline_run.json
   ```
2. Fill in each `_TBD_` cell from `_baseline_run.json`.
3. Add a row to the **Run history** section below (do not overwrite — append).
4. Commit with message `bench(japanese_subsidy_rag): baseline run YYYY-MM-DD`.

## Run history (append-only)

_(none yet — first entry will be the P1 harness output)_

## Reference: external runs

If a third party publishes a result against this benchmark, link it here.
We will not verify external numbers; we will only link to the published
write-up. Inclusion is not endorsement.

| Date | Submitter | Model / Stack | Tier A precision@1 | Tier C refusal_acc | Link |
| ---- | --------- | ------------- | ------------------ | ------------------ | ---- |
| _none yet_ | | | | | |
