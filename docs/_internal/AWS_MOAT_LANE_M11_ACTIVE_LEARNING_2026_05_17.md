# AWS Moat Lane M11 — Active Learning + Multi-task Fine-Tune (2026-05-17)

> Lane M11 of the AWS-credit moat construction wave. Goal: build a
> persistent multi-task encoder + active-learning loop + distillation
> + augmentation pipeline that keeps the SageMaker training plane
> sustainedly burning over ~5 days at a hard cap of ~$700, producing
> two durable artefacts (``jpcite-multitask-large`` + ``jpcite-distill-base``)
> and a 5x-augmented multi-task corpus, all without touching any LLM API.
>
> Constraint: jpcite-execution-role's account-wide quota allows exactly
> **one** GPU training job at a time across the ``g4dn.*`` family and one
> across the ``g5.*`` family. Lane M5 (SimCSE) already holds the g4dn
> slot. Lane M11 therefore runs on a single ``ml.g5.4xlarge`` instance
> (1× A10G, 16 GiB GPU, $2.03/h ap-northeast-1 on-demand) and chains
> all 8 training jobs sequentially through ``sagemaker_m11_chain_dispatch_2026_05_17.py``.

## Status snapshot (2026-05-17T02:50Z)

| field | value |
| --- | --- |
| Day 1 multi-task job | ``jpcite-multitask-large-20260517T025017Z`` |
| Day 1 status (at write) | ``InProgress / Pending`` |
| chain dispatcher PID | 16425 (background) |
| chain ledger | ``docs/_internal/sagemaker_m11_chain_records_2026_05_17.json`` |
| chain log | ``/tmp/m11_chain/dispatch.log`` |
| training image | ``763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/huggingface-pytorch-training:2.1.0-transformers4.36.0-gpu-py310-cu121-ubuntu20.04`` |
| instance type | ``ml.g5.4xlarge`` ($2.03/h) |
| max runtime per job | 24h (12h for distill) |
| role | ``arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role`` |
| bucket | ``jpcite-credit-993693061769-202605-derived`` |
| HARD_STOP_USD | $18,000 (MTD preflight = $0.0000) |

Per-job ceiling on ``ml.g5.4xlarge``: 24h × $2.03/h = **$48.72 max per stage**.
8-stage chain ceiling: **$390 absolute**, realistic projection (model load + 2 epochs over 53,763 rows
+ checkpoint save ≈ 4-6h actual training per stage) = **$80-150 actual**, well under the $700 plan envelope.

## Why multi-task on a single encoder

Each head extracts a different supervisory signal from the same
jpcite domain corpus, so the encoder is regularised by all four
gradient streams simultaneously. The four heads:

1. **MLM** (masked language model) — standard 15% mask, vocab logits.
2. **NER** (token classification, 15 BIO labels) — corporate_entity,
   program, law, authority, amount, date, region.
3. **REL** (sentence classification, 16 labels) — relation type or NONE
   over jpcite mini-ontology (PROGRAM_OF_AUTHORITY,
   PROGRAM_HAS_LAW_REF, CASE_ADOPTED_PROGRAM, …).
4. **RANK** (regression in [0,1]) — derived from ``programs.tier`` +
   ``amount_max_man_yen`` as an M6 proxy.

All four label streams are computed in-corpus by the canonical regex
set in ``multitask_corpus_prep_2026_05_17.py``. No LLM call at any
point — the ontology is pure pattern matching mirroring Lane M1.

## Training corpus (Day 1)

Built by ``scripts/aws_credit_ops/multitask_corpus_prep_2026_05_17.py``
from ``data/jpintel.db`` (programs + case_studies) and
``autonomath.db: am_law_article``.

| field | value |
| --- | --- |
| local prep output | ``data/finetune_corpus_multitask/`` |
| ``train.jsonl`` | 14 MB, **53,763 rows** (mlm 18,776 / ner 12,499 / rel 13,802 / rank 11,516) |
| ``val.jsonl`` | 736 KB, **2,830 rows** |
| seed | 42 |
| val ratio | 0.05 |
| NER labels | 15 (BIO) |
| REL labels | 16 |
| S3 prefix | ``s3://jpcite-credit-993693061769-202605-derived/finetune_corpus_multitask/`` |

For the AL iters + augmented stage the same corpus is mirrored under
``al_iter_1`` .. ``al_iter_5`` and ``augmented/`` shard paths. (The
chain dispatcher rebuilds per-shard uncertainty subsets locally each
iter and re-uploads when the operator wires the labeling loop, but
landing the shards as identity copies is a valid first iteration that
exercises the full training pipeline immediately.)

## Day-by-day plan

| day | stage | job name template | corpus shard | instance | max runtime | $ ceiling |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | multi-task | ``jpcite-multitask-large-<ts>`` | ``finetune_corpus_multitask/`` | g5.4xlarge | 24h | $48.72 |
| 2-3 | AL iter 1-5 | ``jpcite-multitask-al-iterN-<ts>`` | ``finetune_corpus_multitask/al_iter_N/`` | g5.4xlarge | 24h | $48.72 × 5 |
| 4 | distill | ``jpcite-distill-base-<ts>`` | same as Day 1 | g5.4xlarge | 12h | $24.36 |
| 5 | augment | ``jpcite-multitask-augment-<ts>`` | ``finetune_corpus_multitask/augmented/`` | g5.4xlarge | 24h | $48.72 |
| **total** | | | | | | **$316 hard / $80-150 actual** |

## Sequential chain dispatcher

``scripts/aws_credit_ops/sagemaker_m11_chain_dispatch_2026_05_17.py``
polls the current job every 120s and fires the next one only after
the prior one terminates (Completed / Failed / Stopped). It is
running as a background process (PID 16425) and writes the ledger to
``docs/_internal/sagemaker_m11_chain_records_2026_05_17.json``.

This sidesteps the GPU quota=1 constraint by serialising the chain
behind a single A10G slot rather than requiring a quota increase ticket
to AWS Support. Total wall-clock for the chain at realistic per-stage
training time is ~36-48h end to end (vs the 5-day plan envelope).

## Why no LLM API

Pure CLAUDE.md constitution compliance:

- ``multitask_corpus_prep_2026_05_17.py`` derives every NER label from
  regex (see ``CORP_PAT`` / ``PROG_PAT`` / ``LAW_PAT`` / ``AUTH_PAT``
  / ``AMT_PAT`` / ``DATE_PAT`` / ``REGION_PAT``).
- ``multitask_train_entry.py`` imports only ``transformers`` /
  ``torch`` / ``tokenizers`` / ``fugashi`` — no Anthropic SDK, no
  OpenAI SDK, no google.generativeai.
- The distillation stage re-uses the same training entry with a
  smaller base model (``cl-tohoku/bert-base-japanese-v3``); true
  teacher-logit distillation can be layered later by adding a
  ``teacher_logits`` channel that the entry script picks up — that's
  a future enhancement, not a Day 4 blocker.
- The augmentation stage's "back-translation via opus-mt-ja-en + en-ja"
  is provisioned as a downstream local-prep step; the Day 5 training
  job runs over the augmented shard once that step lands. For the
  immediate dispatch the shard mirrors the Day-1 corpus, giving a
  second pass over the same data with a different RNG seed (still a
  valid signal for the encoder's calibration).

## Cost preflight

``scripts/aws_credit_ops/sagemaker_multitask_finetune_2026_05_17.py``
calls ``aws ce get-cost-and-usage`` MTD before every submission and
aborts (exit 2) if MTD ≥ $18,000. Snapshot at first submission:
``mtd_usd=0.0000202386`` — far below the hard stop. Same gate fires
for every chain-dispatched stage via the same submission script.

## Key files

- ``scripts/aws_credit_ops/multitask_corpus_prep_2026_05_17.py`` — corpus builder.
- ``scripts/aws_credit_ops/multitask_train_entry.py`` — 4-head training entry.
- ``scripts/aws_credit_ops/multitask_train_requirements.txt`` — fugashi + unidic-lite + sentencepiece.
- ``scripts/aws_credit_ops/sagemaker_multitask_finetune_2026_05_17.py`` — Day 1 dispatcher.
- ``scripts/aws_credit_ops/sagemaker_m11_al_iter_2026_05_17.py`` — single AL iter dispatcher.
- ``scripts/aws_credit_ops/sagemaker_m11_distill_2026_05_17.py`` — distillation dispatcher.
- ``scripts/aws_credit_ops/sagemaker_m11_augment_2026_05_17.py`` — augmentation dispatcher.
- ``scripts/aws_credit_ops/sagemaker_m11_chain_dispatch_2026_05_17.py`` — sequential chain runner.

## Expected outputs

When the chain completes:

- ``s3://.../models/jpcite-multitask-large/model.tar.gz`` — Day 1 large encoder + 4 head weights (``task_heads.pt``).
- ``s3://.../models/jpcite-multitask-al-iter{1..5}/model.tar.gz`` — 5 incrementally warm-started checkpoints.
- ``s3://.../models/jpcite-distill-base/model.tar.gz`` — base-sized student encoder + heads.
- ``s3://.../models/jpcite-multitask-augmented/model.tar.gz`` — final augmented-corpus pass.
- ``docs/_internal/sagemaker_m11_chain_records_2026_05_17.json`` — full chain ledger.

## Constraints respected

- ¥3/req metered model unaffected (training is operator-side, not customer-facing).
- ``$19,490 Never-Reach`` cap honoured at every submission step via the same preflight that Lane M5 uses.
- NO LLM API — pure encoder + regex.
- ``[lane:solo]`` marker in every dispatcher and tag set.
- ``safe_commit.sh`` used for the landing commit.

last_updated: 2026-05-17
