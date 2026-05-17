# BB1 + BB2 — M5 v2 + M6 v2 ML Training Cycle (2026-05-17)

Status: scripts landed, awaiting v1 cascade terminal state.

## What this lane does

Extends the M5 SimCSE BERT and M6 cross-encoder reranker training
loops with **v2 hyperparameter + corpus deltas**. The v1 cycle
(landed earlier 2026-05-17) is the input; v2 lifts epochs, lowers
lr, and adds AA1+AA2 supplemental corpus + AA5 narrative pairs.

## Pre-condition state (snapshot)

| signal | value | source |
|--------|-------|--------|
| M5 v1 job | `jpcite-bert-simcse-finetune-20260517T022501Z` | `aws sagemaker describe-training-job` |
| M5 v1 status | InProgress (Training) | same |
| M5 v1 elapsed | ~20,863 s (~5.8 h of 12 h cap) | same |
| M5 v1 output | `s3://jpcite-credit-993693061769-202605-derived/models/jpcite-bert-v1/` | same |
| M6 v1 watcher PID | 44116 | `ps -p 44116` |
| M6 v1 watcher uptime | ~4 h | same |
| M6 v1 watcher cmd | `sagemaker_m6_auto_submit_after_m5.py --poll-interval 300 --max-wait 50400 --commit` | same |

## v1 corpus baseline (sha-locked)

From `s3://.../finetune_corpus/_manifest.json`:

| table | raw | kept |
|-------|-----|------|
| programs | 12,753 | 12,707 |
| am_law_article | 353,278 | 353,278 |
| adoption_records | 160,376 | 160,151 |
| court_decisions | 848 | 848 |
| nta_saiketsu | 137 | 137 |
| nta_tsutatsu_index | 3,232 | 3,232 |
| invoice_registrants | 13,801 | 13,801 |
| **total** | **544,425** | **544,154** |

Train: 516,946 / Val: 27,208 / SHA train: `f5ee5f76...`.

## v2 deltas

### M5 v2 (SimCSE BERT v2)

| dim | v1 | v2 | delta |
|-----|----|----|-------|
| epochs | 3 | 5 | +1.67x |
| lr | 3e-5 | 1e-5 | -3x (finer fine-tune) |
| batch_size | 64 | 64 | -- |
| max_runtime | 12 h | 18 h | +1.5x |
| corpus train | 516,946 | 516,946 + AA1/AA2 supplemental (target 26K = 5.0%) | +5% |
| output S3 | `models/jpcite-bert-v1/` | `models/jpcite-bert-v2/` | new |
| instance | ml.g4dn.12xlarge | ml.g4dn.12xlarge | -- |
| cost cap | $46 | $70 | +52% |

AA1/AA2 supplemental table caps (skipped silently if S3 prefix empty):

| table | cap | source |
|-------|-----|--------|
| nta_qa | 2,000 | NTA Q&A |
| nta_saiketsu_extra | 3,000 | beyond v1 137 |
| asbj_kaikei_kijun | 120 | ASBJ PDF |
| jicpa_audit_committee | 90 | JICPA PDF |
| edinet_disclosure | 3,800 | EDINET excerpts |

Dry-run verified end-to-end on 2026-05-17 17:06 JST: when AA1/AA2
prefixes are absent, the v2 corpus prep falls back to v1 SHA exactly
(`f5ee5f76...`) and records `source_missing=True` per table.

### M6 v2 (cross-encoder reranker v2)

| dim | v1 | v2 | delta |
|-----|----|----|-------|
| epochs | 5 | 10 | +2x |
| lr | 1e-5 | 1e-5 | -- |
| batch_size | 32 | 32 | -- |
| max_runtime | 24 h | 48 h | +2x |
| pairs (target) | 285K | 285K + AA5 100K = 385K | +35% |
| output S3 | `models/jpcite-cross-encoder-v1/` | `models/jpcite-cross-encoder-v2/` | new |
| instance | ml.g4dn.12xlarge | ml.g4dn.12xlarge | -- |
| cost cap | $94 | $187 | +99% |

AA5 narrative pairs come from `am_law_reasoning_chain`
(rule-based extraction by `scripts/build_legal_reasoning_chain.py`);
absent table is detected and AA5 contribution falls to 0 (manifest
records `aa5_pairs=0`).

## Pipeline scripts (all landed, mypy-strict + ruff clean)

| file | purpose |
|------|---------|
| `scripts/aws_credit_ops/simcse_corpus_prep_v2_2026_05_17.py` | aggregate v1 tables + AA1/AA2 supplemental into `finetune_corpus_v2/{train,val}.jsonl` |
| `scripts/aws_credit_ops/sagemaker_simcse_v2_finetune_2026_05_17.py` | submit M5 v2 SimCSE training (epochs=5, lr=1e-5, 18 h) |
| `scripts/aws_credit_ops/cross_encoder_pair_gen_2026_05_17.py` | M6 v1 pair generator from autonomath.db (court/program -> law) |
| `scripts/aws_credit_ops/cross_encoder_pair_gen_v2_2026_05_17.py` | M6 v2 pair generator = v1 + AA5 narrative-derived 100K |
| `scripts/aws_credit_ops/cross_encoder_train_entry.py` | SageMaker container entrypoint for both M6 v1 + v2 |
| `scripts/aws_credit_ops/sagemaker_cross_encoder_finetune_2026_05_17.py` | M6 v1 SageMaker submit (target of watcher) |
| `scripts/aws_credit_ops/sagemaker_cross_encoder_v2_finetune_2026_05_17.py` | M6 v2 SageMaker submit (wraps v1 driver with --version v2) |
| `scripts/aws_credit_ops/simcse_eval_v2_vs_v1_2026_05_17.py` | 50-query recall@10 base vs v1 vs v2 comparison; target +5-15% lift |

## v2 launch sequence (operator-driven)

1. Wait for M5 v1 (`jpcite-bert-simcse-finetune-20260517T022501Z`)
   to reach terminal state. Watcher PID 44116 auto-fires
   `sagemaker_cross_encoder_finetune_2026_05_17.py --version v1`
   on M5 terminal state.
2. Wait for M6 v1 (`jpcite-cross-encoder-finetune-*`) terminal state.
3. (Optional) Land AA1+AA2 ETL feeding `corpus_export_aa12/*`; rerun
   corpus prep if you want the 5% supplemental lift.
4. Land AA5 narrative chain (`am_law_reasoning_chain`) if not already
   present; required for the 100K AA5 pair lift.
5. `cross_encoder_pair_gen_v2_2026_05_17.py --commit` to emit
   `s3://.../cross_encoder_pairs/v2/{train,val}.jsonl`.
6. `simcse_corpus_prep_v2_2026_05_17.py --commit` to emit
   `s3://.../finetune_corpus_v2/{train,val}.jsonl`.
7. `sagemaker_simcse_v2_finetune_2026_05_17.py --commit`.
8. `sagemaker_cross_encoder_v2_finetune_2026_05_17.py --commit`
   (after step 7 completes -- single quota slot for g4dn.12xlarge).
9. Download v1 + v2 model artefacts locally, then run
   `simcse_eval_v2_vs_v1_2026_05_17.py --val-path ... --v1-model-path ... --v2-model-path ...`
   -- exit code 0 iff v2 lift over v1 in [+5%, +15%].

## Cohort-aware integration (BB4 hand-off)

When v2 lands, BB4 lane consumes the new artefacts:

- `models/jpcite-bert-v2/` + the 5 LoRA adapters become the encoder
  for `HE-1 search_chunks` (replacing v1).
- `models/jpcite-cross-encoder-v2/` becomes the rerank head for
  `search_v2` (replacing v1).

Integration is read-only on this lane's side -- BB4 lane owns the
endpoint/MCP wiring.

## Cost projection

| stage | hours | rate | dollars |
|-------|-------|------|---------|
| M5 v2 train | 18 | $3.91/h | $70 |
| M6 v1 train (auto) | 24 | $3.91/h | $94 |
| M6 v2 train | 48 | $3.91/h | $187 |
| **subtotal** | **90 h** | -- | **$351** |

MTD at script-land time: $0.0000 (verified
`aws ce get-cost-and-usage`). $19,490 Never-Reach absolute is safely
preserved (any v2 launch is gated by `HARD_STOP_USD=18000` preflight
inside each submit script).

## Constraints honoured

- [x] NO LLM API anywhere (encoder fine-tune + cross-encoder rerank only).
- [x] mypy --strict 0 errors across 8 new files.
- [x] ruff 0 errors across 8 new files.
- [x] `[lane:solo]` markers on all 8 files.
- [x] DRY_RUN-by-default; `--commit` opt-in for any AWS-mutating call.
- [x] HARD_STOP_USD=18000 preflight on every SageMaker submit.
- [x] Each submit ties EnableManagedSpotTraining=False (predictable schedule).

## What this lane explicitly does NOT do

- Does NOT trigger v2 SageMaker jobs (gated by v1 cascade not yet
  terminal -- single g4dn.12xlarge quota slot).
- Does NOT land AA1+AA2 ETL (separate lane, separate data-collection
  workstream); v2 corpus prep is parameterised so it degrades safely
  when AA1/AA2 prefixes are empty.
- Does NOT modify v1 corpus / v1 model -- those stay SHA-locked for
  reproducibility.
- Does NOT touch BB4 integration -- that lane owns endpoint wiring.

## Cross-references

- v1 cycle SOT: `s3://.../finetune_corpus/_manifest.json`
- v1 SimCSE submit: `scripts/aws_credit_ops/sagemaker_simcse_finetune_2026_05_17.py`
- v1 train entry: `scripts/aws_credit_ops/simcse_train_entry.py`
- v1 corpus prep: `scripts/aws_credit_ops/simcse_corpus_prep_2026_05_17.py`
- v1 recall@10 eval: `scripts/aws_credit_ops/simcse_eval_recall_at_10_2026_05_17.py`
- M6 watcher: `scripts/aws_credit_ops/sagemaker_m6_auto_submit_after_m5.py`
- M8 (M6 inference bridge): `scripts/aws_credit_ops/sagemaker_citation_rerank_2026_05_17.py`
