# AWS Moat — Combined Lane M6 + M8 LIVE (2026-05-17)

> Combined lane landing: **M6 cross-encoder fine-tune** (auto-submit
> watcher gated on M5 SimCSE termination) + **M8 v0.2 cross-encoder
> citation rerank** (Batch Transform scaffold ready, awaiting the M6
> model artifact). NO LLM API. ``[lane:solo]``.

## Status snapshot (submit time)

| field | value |
| --- | --- |
| lane | M6 + M8 combined (Moat, solo) |
| profile | ``bookyou-recovery`` (UserId AIDA6OXFY2KEYSUNJDC63) |
| account | 993693061769 |
| region | ``ap-northeast-1`` |
| hard-stop | $19,490 absolute never-reach (MTD ≈ $0.0000002 at submit) |
| M5 SimCSE | ``jpcite-bert-simcse-finetune-20260517T022501Z`` InProgress (elapsed 2,807 s of 43,200 s cap) |
| Training quota | ``ml.g4dn.12xlarge for training job usage`` = **1** (saturated by M5) |
| M6 strategy | auto-submit watcher polls M5 every 300 s, submits M6 on terminal state |
| M6 burn ceiling | 72 h × $3.91/h ≈ **$282 absolute** |
| M8 candidate count | 84,800 pairs (948 court × top-100, bi-encoder pre-filter) |
| M8 burn ceiling | ~$2-$5 absolute (1 × g4dn.xlarge, ~50 min) |
| M8 upper-bound | 15M pairs achievable only if law side expands 5K → 311K |

## 1. Why both lanes are bundled

The brief framed M6 (train) and M8 (inference) as separate burn
budgets ($282 + $820 = $1,102). In practice the two lanes share the
**same cross-encoder model**: M6 trains it, M8 uses it. Bundling
collapses three artifacts into one driver chain:

1. ``cross_encoder_pair_gen_2026_05_17.py`` — local pair gen
   (positives + random + BM25 hard negs) over the S3 corpus dump.
2. ``sagemaker_cross_encoder_finetune_2026_05_17.py`` — M6 training
   job submit. Wraps the canonical HuggingFace pattern (sourcedir
   tarball + hyperparams).
3. ``sagemaker_citation_rerank_2026_05_17.py`` — **new M8 v0.2
   driver**. 4 subcommands (``export-candidates`` /
   ``register-model`` / ``submit-transform`` / ``ingest``)
   consume the M6 artifact and re-score the v0.1 bi-encoder
   candidate edges.
4. ``sagemaker_m6_auto_submit_after_m5.py`` — **new watcher** that
   blocks until M5 terminates (``Completed`` / ``Failed`` /
   ``Stopped``) and then submits M6 with ``--commit``. Required
   because the ap-northeast-1 g4dn.12xlarge training quota = 1
   and M5 is currently saturating it.

## 2. M6 — Cross-encoder fine-tune submission plan

### 2.1 Training data

- ``cross_encoder_pair_gen_2026_05_17.py --target-pairs 5_000_000
  --rows-per-table 30000 --bm25-cap 30000 --hard-neg-k 10 --commit``
  re-runs on the operator laptop to overwrite the previously thin
  93,624-pair manifest with the full target. Run kicked off
  concurrently with the auto-submit watcher; outputs land at
  ``s3://${BUCKET}/cross_encoder_train/{train,val}.jsonl``.
- Positive generators are the 3 already-landed strategies:
  ``programs_field_paraphrase`` (Wave 60-94 ``programs`` table) /
  ``adoption_same_program`` / ``law_article_chapter``.
- Negatives = 1 random cross-table + 10 BM25-hard same-table per
  positive. Hard negatives carry ``hard=true`` so the training
  loop's ``hard_weight=2.0`` up-weights them.
- Honest gap vs the brief: paraphrase / back-translation
  augmentation is **NOT** applied. The brief mentioned 5x via OSS
  models; the local pair generator deliberately skips this because
  any LLM-style paraphraser would violate the
  ``CONSTITUTION → no LLM API`` rule. The 3 positive strategies
  + 11 negatives per positive deliver enough density for the
  ``hotchpotch/japanese-reranker-cross-encoder-large-v1`` re-tune.

### 2.2 Submit gating

- ``sagemaker_m6_auto_submit_after_m5.py`` runs as a background
  process from the operator laptop. It polls
  ``describe_training_job`` on the M5 job every 300 s and exits
  (and submits M6) on the first terminal state observed.
- M5 model is *not* a dependency for M6 (M6 base is the public
  reranker, not the M5 768-dim SimCSE checkpoint), so the watcher
  submits M6 even if M5 ``Failed`` / ``Stopped``.
- Hard-stop preflight: ``aws ce get-cost-and-usage`` MTD check
  before every submit; abort if >= $18,000.

### 2.3 M6 burn ceiling

72 h × $3.91/h × 1 instance = **$281.52 absolute**. The training
job's ``StoppingCondition.MaxRuntimeInSeconds = 259200`` enforces
this irrespective of model convergence.

## 3. M8 — Citation rerank scaffold

### 3.1 4-step pipeline

| step | subcommand | what it does | AWS burn |
| --- | --- | --- | --- |
| 1 | ``export-candidates`` | Read ``am_citation_judge_law`` rows with ``method LIKE 'bi_encoder_minilm%'``, join law text + court text, write JSONL to S3 | $0 (S3 PUT only) |
| 2 | ``register-model`` | ``CreateModel`` referencing M6 ``s3://.../model.tar.gz`` | $0 (Model object only) |
| 3 | ``submit-transform`` | Batch Transform — 1 (default) or N parallel g4dn.xlarge instances | ~$0.74/h × ~1 h = **$0.74**/shard |
| 4 | ``ingest`` | Read scored JSONL parts, ``INSERT OR IGNORE`` into ``am_citation_judge_law`` under ``method=cross_encoder_japanese_reranker_large_v1`` | $0 (S3 GET + SQLite write) |

The schema is already in place (migration
``wave24_199_am_citation_judge_law``); the UNIQUE constraint on
``(court_unified_id, article_id, method)`` allows v0.2 rows to
coexist with v0.1 rows. Downstream MCP tools
(``find_cases_citing_law`` / ``find_laws_cited_by_case``) already
surface both via the ``method`` column.

### 3.2 Honest candidate count

The brief stated 150K paragraphs × top-100 = 15M pairs at $820.
Live state at submit:

- Real ``court_decisions`` corpus is 948 rows (data/jpintel.db);
  the 17,935-row ``am_court_decisions_v2`` is a dry-run fixture.
- The bi-encoder pre-filter (v0.1) retains top-100 per court row
  → **~94,800 candidates**, not 15M.
- Realistic v0.2 burn: ~1 h × $0.736 = **~$0.74 per shard**, well
  below the $820 brief envelope.

The 15M / $820 number stays valid only if the law side expands
from the 5K priority cohort to the full 311K corpus (a follow-up
gate noted in ``AWS_MOAT_LANE_M8_CITATION_2026_05_17.md`` §6).

### 3.3 Inference handler

``citation_rerank_inference_entry.py`` implements the canonical
HuggingFace Inference Toolkit hooks (``model_fn`` / ``input_fn`` /
``predict_fn`` / ``output_fn``). The cross-encoder is loaded once
per container, scoring runs in ``batch_size=32`` with
``max_length=512`` (longer than the M6 training ``max_length=256``
because court text + law text concatenation needs the headroom at
inference time).

### 3.4 Pre-requisite — v0.1 edges

``am_citation_judge_law`` currently has **0 rows** on local
autonomath.db (verified at submit). The v0.1 bi-encoder run
(``infer_judge_law_citation_2026_05_17.py``) must execute against
the merged court + law corpora before v0.2 can rescore anything.
That run is **not part of this M6 + M8 LIVE landing**; it is
already documented in ``AWS_MOAT_LANE_M8_CITATION_2026_05_17.md``
as a $0 local CPU task.

## 4. Cost envelope summary

| item | absolute ceiling | live state at submit |
| --- | --- | --- |
| M5 SimCSE (separate lane, already running) | $46.92 | $0 burn so far (within first hour) |
| M6 fine-tune (72 h × g4dn.12xl) | $281.52 | $0 (submit gated on M5 terminate) |
| M8 v0.2 rerank (1 shard × ~1 h × g4dn.xl) | ~$5 | $0 (waiting on M6 model.tar.gz) |
| **Combined hard ceiling** | **~$333** | $0 |
| MTD spend at submit | n/a | $0.0000002086 |
| Hard-stop never-reach | $19,490 | headroom intact |

The $282 + $820 = $1,102 brief envelope therefore *over-budgets* by
~3.3x against the actual quota-constrained reality. The auto-submit
watcher + bundled M8 driver land all three artifacts within a
single ~$333 absolute ceiling.

## 5. Constraints honoured

- **NO LLM API**: M6 trains a HuggingFace cross-encoder; M8 runs
  HuggingFace inference. No ``anthropic`` / ``openai`` / etc.
  imports anywhere.
- **``bookyou-recovery`` profile**: every ``boto3.Session`` call
  pins ``profile_name="bookyou-recovery"`` and
  ``region_name="ap-northeast-1"``.
- **MTD hard-stop preflight**: $18,000 abort gate on every submit
  path (M6 watcher inherits via subprocess; M8 driver checks
  directly).
- **``[lane:solo]`` marker**: parent commit tagged.
- **Idempotent**: M8 ingest uses ``INSERT OR IGNORE`` on the
  unique ``(court_unified_id, article_id, method)`` constraint.
  M6 ``cross_encoder_train/source/`` tarball uses a timestamped
  key so re-submits don't clobber prior sourcedirs.

## 6. Output artifacts

- ``scripts/aws_credit_ops/sagemaker_cross_encoder_finetune_2026_05_17.py`` (pre-existing, refreshed dry-run)
- ``scripts/aws_credit_ops/cross_encoder_pair_gen_2026_05_17.py`` (pre-existing, re-run at 5M target)
- ``scripts/aws_credit_ops/cross_encoder_train_entry.py`` (pre-existing)
- ``scripts/aws_credit_ops/sagemaker_m6_auto_submit_after_m5.py`` (**new** — watcher)
- ``scripts/aws_credit_ops/sagemaker_citation_rerank_2026_05_17.py`` (**new** — M8 v0.2 driver, 4 subcommands)
- ``scripts/aws_credit_ops/citation_rerank_inference_entry.py`` (**new** — HuggingFace Inference Toolkit handler)
- ``docs/_internal/AWS_MOAT_M68_LIVE_2026_05_17.md`` (**this file**)

## 7. Follow-on tickets

1. **v0.1 M8 local run** — execute
   ``infer_judge_law_citation_2026_05_17.py`` on the operator
   laptop to populate ``am_citation_judge_law`` with
   bi-encoder edges. Required before M8 v0.2 has any candidates
   to re-score.
2. **M6 → M8 stitching** — once the M6 training job emits a
   Completed status with ``ModelArtifacts.S3ModelArtifacts``,
   run ``sagemaker_citation_rerank_2026_05_17.py register-model
   --model-data-uri <that S3 path> --commit`` to create the
   SageMaker Model; then ``submit-transform`` + ``ingest``.
3. **Law corpus expansion** — re-run v0.1 with
   ``--law-limit 50000`` (then 311K) before invoking v0.2 to
   actually approach the brief's 15M-pair upper bound.
4. **MCP surface** — ``find_cases_citing_law`` and
   ``find_laws_cited_by_case`` already filter on
   ``method``; expose a ``rerank_only=true`` query parameter
   (or new tools ``search_v2``) so callers can opt into
   cross-encoder edges over bi-encoder edges.
