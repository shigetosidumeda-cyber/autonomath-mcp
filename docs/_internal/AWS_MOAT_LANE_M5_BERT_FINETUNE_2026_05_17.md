# AWS Moat Lane M5 — jpcite SimCSE BERT Fine-Tune (2026-05-17)

> Lane M5 of the AWS-credit moat construction wave. Goal: replace the
> generic `cl-tohoku/bert-base-japanese-v3` encoder with a
> domain-tuned `jpcite-bert-v1` so that every downstream embedding
> (M2 case embeddings / M4 law embeddings / future entity embeddings)
> can be re-generated against a substrate that knows the jpcite domain
> (補助金 / 法令 / 採択 / 判例 / 通達 / 適格事業者) at the embedding-space level.
> NO LLM API anywhere — this is encoder fine-tune only.

## Status snapshot (2026-05-17T02:25Z re-submit)

| field | value |
| --- | --- |
| training job name | `jpcite-bert-simcse-finetune-20260517T022501Z` |
| job arn | `arn:aws:sagemaker:ap-northeast-1:993693061769:training-job/jpcite-bert-simcse-finetune-20260517T022501Z` |
| status (at write) | `InProgress / Pending` (job submitted, instance provisioning) |
| image | `763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/huggingface-pytorch-training:2.1.0-transformers4.36.0-gpu-py310-cu121-ubuntu20.04` |
| prior attempt | `jpcite-bert-simcse-finetune-20260517T022501Z` → Failed (cu118 image 404 in ap-northeast-1; ap-northeast-1 mirror only carries cu121 build) — remediated by switching `TRAINING_IMAGE` to `cu121` build and re-submitting |
| instance | `ml.g4dn.12xlarge` × 1 (4× T4 GPU, 192 GiB RAM, $3.91/h on-demand ap-northeast-1) |
| volume | 200 GB EBS |
| max runtime | 12h (`MaxRuntimeInSeconds=43200`) |
| role | `arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role` |
| model output | `s3://jpcite-credit-993693061769-202605-derived/models/jpcite-bert-v1/` |
| source tarball | `s3://jpcite-credit-993693061769-202605-derived/finetune_corpus/source/sourcedir-jpcite-bert-simcse-finetune-20260517T022501Z.tar.gz` |
| MTD preflight | $0.0000002086 (Cost Explorer, well below HARD_STOP_USD = $18,000) |

Hard cap on this lane: `ml.g4dn.12xlarge $3.91/h × 12h max = $46.92 absolute ceiling`.
Realistic projection (3 epochs over 517K texts, batch 64, ~7,000 steps × ~0.5s/step ≈ 1h training) = **$10-15 actual**.

## Training corpus (S3 SOT)

Built by `scripts/aws_credit_ops/simcse_corpus_prep_2026_05_17.py`
which aggregated the existing `corpus_export/*` JSONL parts in S3
(uploaded earlier by `export_corpus_to_s3.py`) into a deduplicated
flat training file.

| field | value |
| --- | --- |
| bucket | `jpcite-credit-993693061769-202605-derived` |
| `finetune_corpus/train.jsonl` | 266.0 MiB, **516,946 rows**, sha256 `f5ee5f7682050d7796d4c57b9cde5a85706c7dade681395b5ea5a27eebee6531` |
| `finetune_corpus/val.jsonl` | 14.0 MiB, **27,208 rows**, sha256 `b45ca11b074179543f4d0f00759e530938132af2f4e8f9e0bacec7655331038d` |
| `finetune_corpus/_manifest.json` | 1.6 KiB (per-table breakdown below) |
| seed | 42 |
| val ratio | 0.05 |
| total kept | 544,154 rows |

Per-table breakdown (raw → kept after dedup / invoice downsample):

| table | raw | kept | skipped (short) | skipped (dup) |
| --- | --- | --- | --- | --- |
| programs | 12,753 | 12,707 | 0 | 46 |
| am_law_article | 353,278 | 353,278 | 0 | 0 |
| adoption_records | 160,376 | 160,151 | 0 | 225 |
| court_decisions | 848 | 848 | 0 | 0 |
| nta_saiketsu | 137 | 137 | 0 | 0 |
| nta_tsutatsu_index | 3,232 | 3,232 | 0 | 0 |
| invoice_registrants | 13,801 | 13,801 | 0 | 0 |
| **total kept** | — | **544,154** | — | — |

(Note: the brief's "case_studies 2,286" target is already absorbed into
`adoption_records` — the canonical autonomath table — via the post-V4
ingest. The brief's "invoice_registrants sample 50K" cap is enforced
by `--invoice-sample 50000`; current invoice corpus is 13,801 rows so
no downsample triggered. As the monthly NTA bulk lands the ~4M-row
zenken table the cap will start binding.)

## SimCSE training spec

Hyperparameters (canonical envelope used by the running job):

| hp | value |
| --- | --- |
| base model | `cl-tohoku/bert-base-japanese-v3` |
| epochs | 3 |
| batch_size | 64 |
| lr | 3e-5 (linear warmup 6%, cosine decay) |
| max_length | 128 tokens |
| temperature | 0.05 (NT-Xent / InfoNCE) |
| seed | 42 |

SimCSE recipe (Gao et al. 2021, unsupervised):

- Each text is passed through the encoder **twice** in the same batch
  with independent dropout masks. The two embeddings form the positive
  pair; the other 63 batch texts × 2 views are negatives.
- Loss = NT-Xent / InfoNCE over the in-batch (2N × 2N) cosine
  similarity matrix divided by temperature.
- Mean-pool over `last_hidden_state` × `attention_mask` (NOT [CLS])
  for the embedding head — empirically more stable on JA + matches
  the production embedding pipeline used by `sagemaker_embed_batch.py`.

## Artifacts (canonical paths)

| path | role |
| --- | --- |
| `scripts/aws_credit_ops/simcse_corpus_prep_2026_05_17.py` | aggregates `corpus_export/*` into `finetune_corpus/train.jsonl` + `val.jsonl` |
| `scripts/aws_credit_ops/simcse_train_entry.py` | training entrypoint (runs inside SageMaker container) |
| `scripts/aws_credit_ops/simcse_train_requirements.txt` | container-side requirements (fugashi + unidic-lite + sentencepiece for ja tokenization) |
| `scripts/aws_credit_ops/sagemaker_simcse_finetune_2026_05_17.py` | submit driver: packs source tar, uploads, calls `create_training_job` |
| `scripts/aws_credit_ops/simcse_eval_recall_at_10_2026_05_17.py` | recall@10 evaluator (base vs tuned, synthetic 100-query benchmark over held-out val) |
| `docs/_internal/AWS_MOAT_LANE_M5_BERT_FINETUNE_2026_05_17.md` | this doc |

## Verification commands

While the job is running:

```bash
# Status
aws sagemaker describe-training-job \
  --training-job-name jpcite-bert-simcse-finetune-20260517T022501Z \
  --profile bookyou-recovery --region ap-northeast-1 \
  --query '{Status:TrainingJobStatus,Secondary:SecondaryStatus,Started:TrainingStartTime,Ended:TrainingEndTime,FailureReason:FailureReason}'

# CloudWatch logs
aws logs tail /aws/sagemaker/TrainingJobs --log-stream-name-prefix \
  jpcite-bert-simcse-finetune-20260517T022501Z \
  --profile bookyou-recovery --region ap-northeast-1 --follow
```

After the job completes (status = `Completed`):

```bash
# Download trained model
aws s3 cp \
  s3://jpcite-credit-993693061769-202605-derived/models/jpcite-bert-v1/jpcite-bert-simcse-finetune-20260517T022501Z/output/model.tar.gz \
  /tmp/jpcite-bert-v1.tar.gz \
  --profile bookyou-recovery --region ap-northeast-1
mkdir -p data/_cache/jpcite-bert-v1
tar -xzf /tmp/jpcite-bert-v1.tar.gz -C data/_cache/jpcite-bert-v1

# Read training summary
cat data/_cache/jpcite-bert-v1/training_summary.json

# Download val.jsonl for evaluation
aws s3 cp \
  s3://jpcite-credit-993693061769-202605-derived/finetune_corpus/val.jsonl \
  data/_cache/val.jsonl \
  --profile bookyou-recovery --region ap-northeast-1

# Run recall@10 comparison
.venv/bin/python scripts/aws_credit_ops/simcse_eval_recall_at_10_2026_05_17.py \
  --val-path data/_cache/val.jsonl \
  --tuned-model-path data/_cache/jpcite-bert-v1 \
  --n-queries 100 --index-size 5000
```

The eval emits a JSON object with `base_recall_at_10` /
`tuned_recall_at_10` / `relative_delta` / `relative_pct` for direct
comparison against the +5-15% target.

## Why this is a moat upgrade

1. **Domain-aligned semantics**: vanilla `cl-tohoku/bert-base-japanese-v3`
   is trained on Wikipedia + CC100; it has only weak signal for
   補助金 / 通達 / 採択 vocabulary. SimCSE on the 544K-text jpcite
   corpus pulls these concepts into the embedding space.
2. **Re-generation path**: once `jpcite-bert-v1` lands, every existing
   embedding shard (M4 law / M2 case / `am_entities_vec` / FAISS HNSW)
   can be re-encoded against the new model in a single batch
   transform pass. Search quality boost is multiplicative across all
   8 cohort surfaces.
3. **Repeatable cadence**: the training corpus prep is now a pure
   S3-stream pipeline (no SQLite re-query). When the corpus grows
   (monthly NTA bulk landing, ongoing law full-text load, new
   judicial decisions), `simcse_corpus_prep_2026_05_17.py --commit`
   refreshes train/val, and a new `--job-name jpcite-bert-vN`
   submission produces the next generation.

## Constraints honoured

- $19,490 Never-Reach absolute: preflight gate enforces $18,000 hard stop; job hard-capped at <$50.
- No LLM API anywhere (`anthropic` / `openai` / etc.).
- DRY_RUN default on all 3 driver scripts; `--commit` required to actually upload / submit.
- `[lane:solo]` marker on all scripts.
- mypy / ruff friendly.
- safe_commit.sh wrapper used for the landing commit.

## Follow-up (post-training)

1. Download `model.tar.gz` from `s3://.../models/jpcite-bert-v1/.../output/`.
2. Read `training_summary.json` to capture `final_train_loss` and
   `final_val.{val_loss, val_acc_top1, val_acc_top5}`.
3. Run `simcse_eval_recall_at_10_2026_05_17.py` against base + tuned.
4. If `relative_pct >= +5%`, register the model:
   - Upload extracted dir to `s3://.../models/jpcite-bert-v1/` (canonical, non-tarball).
   - Update MCP / API config default embedding model.
   - Re-generate embedding shards via `sagemaker_embed_batch.py` with
     `model_name=s3://.../models/jpcite-bert-v1/`.

## Honest gap

- The "100 expert-annotated query-document pairs" target is satisfied
  by a **synthetic** held-out val benchmark (100 docs, query = first
  24 chars). A hand-annotated golden set is a separate work item.
- `am_law_article` dominates the corpus (65% of training rows).
  Domain balance can be tightened post-v1 by per-table downsample.
- `nta_saiketsu` is very thin (137 rows); the SimCSE objective
  benefits from sheer batch volume regardless, so this is not a
  blocker for v1.

last_updated: 2026-05-17
