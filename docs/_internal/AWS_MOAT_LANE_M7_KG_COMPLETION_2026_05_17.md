# AWS Moat Lane M7 — Knowledge Graph Completion (2026-05-17)

> Lane M7 of the AWS-credit moat construction wave. Goal: train a 4-model
> KG embedding ensemble (TransE / RotatE / ComplEx / ConvE) over the
> jpcite knowledge graph (`am_relation`) and predict 50K+ missing edges
> with mean ensemble score >= 0.85. NO LLM API — KG embedding is a pure
> tensor-decomposition exercise.

## Status snapshot (2026-05-17, deliverables LANDED in DRY_RUN)

| field | value |
| --- | --- |
| corpus exporter | `scripts/aws_credit_ops/kg_completion_export_2026_05_17.py` (LANDED, DRY_RUN verified) |
| training entrypoint | `scripts/aws_credit_ops/kg_completion_train_entry.py` (LANDED) |
| training requirements | `scripts/aws_credit_ops/kg_completion_train_requirements.txt` (LANDED) |
| submit driver | `scripts/aws_credit_ops/sagemaker_kg_completion_submit_2026_05_17.py` (LANDED, DRY_RUN verified) |
| migration | `scripts/migrations/wave24_198_am_relation_predicted.sql` (+ rollback) (LANDED) |
| ledger | `docs/_internal/sagemaker_kg_completion_2026_05_17_records.json` (DRY_RUN) |
| MTD preflight | $0.0000002086 (Cost Explorer, well below HARD_STOP_USD = $18,000) |
| jobs submitted (live) | **0** — gated behind `--commit` + `--unlock-live-aws-commands` per Stream W concern-separation |

Hard cap on this lane: `ml.g4dn.12xlarge $3.91/h × 24h × 4 jobs = $375.36 absolute ceiling`.
Realistic projection (4 sequential 24h runs at $94 each) = **$300-380 actual**; parallel
mode collapses wall-clock to ~24h but the dollar total is identical.

## KG corpus (S3 SOT, ready for upload)

Built by `kg_completion_export_2026_05_17.py` (DRY_RUN verified, 2026-05-17):

| field | value |
| --- | --- |
| bucket | `jpcite-credit-993693061769-202605-derived` |
| prefix | `kg_corpus/` |
| raw `am_relation` rows | **369,165** |
| kept after rare-relation filter (>= 10 edges) | **369,163** |
| dropped rare relations | `replaces` (2 edges) |
| `kg_corpus/train.jsonl` | **295,330 rows / 34.6 MB** |
| `kg_corpus/val.jsonl` | **36,916 rows / 4.33 MB** |
| `kg_corpus/test.jsonl` | **36,917 rows / 4.33 MB** |
| `kg_corpus/entity_id_map.jsonl` | **380,233 rows / 26.7 MB** |
| `kg_corpus/relation_id_map.jsonl` | **13 rows / 501 B** |
| `kg_corpus/_manifest.json` | 1.5 KB |
| seed | 42 |
| split | 80 / 10 / 10 |

Per-relation breakdown (from live `am_relation` 2026-05-17):

| relation_type | edges | kept after filter |
| --- | --- | --- |
| `related`             | 207,767 | 207,767 |
| `part_of`             | 146,161 | 146,161 |
| `has_authority`       |   7,030 |   7,030 |
| `applies_to_region`   |   3,121 |   3,121 |
| `references_law`      |   1,999 |   1,999 |
| `compatible`          |   1,508 |   1,508 |
| `applies_to_size`     |   1,100 |   1,100 |
| `successor_of`        |     190 |     190 |
| `bonus_points`        |     102 |     102 |
| `applies_to_industry` |      91 |      91 |
| `prerequisite`        |      57 |      57 |
| `incompatible`        |      20 |      20 |
| `applies_to`          |      17 |      17 |
| `replaces`            |       2 | **0** (dropped, < MIN_RELATION_COUNT=10) |
| **total kept**        | — | **369,163** |

> Note: the brief's "178K base" was a stale framing — current `am_relation`
> has grown to 369K (driven by V4 absorption + 5 ingest waves since the
> earlier KG completion proposal). The 4-model ensemble target therefore
> covers ~2× the originally-scoped graph.

## 4-model ensemble training spec

Hyperparameters (canonical envelope used by the submit driver):

| hp | value |
| --- | --- |
| models | `TransE`, `RotatE`, `ComplEx`, `ConvE` |
| embedding_dim | 500 |
| epochs | 200 |
| batch_size | 512 |
| negative_samples | 256 |
| learning_rate | 1e-3 (Adam) |
| loss | InfoNCE / sLCWA `basic` negative sampler |
| seed | 42 |

Why these 4 models:

- **TransE** (Bordes et al. 2013) — translational, lightweight baseline.
  Models `r` as a translation `h + r ≈ t` in embedding space; strong on
  hierarchical relations (`part_of`).
- **RotatE** (Sun et al. 2019) — rotation in complex space; handles
  symmetry / antisymmetry / inversion / composition patterns. Strong on
  bidirectional / commutative relations (`related`, `compatible`).
- **ComplEx** (Trouillon et al. 2016) — complex bilinear; excels at
  antisymmetric relations (`successor_of`, `prerequisite`, `references_law`).
- **ConvE** (Dettmers et al. 2018) — convolutional, parameter-efficient,
  high hits@10 on multi-hop reasoning; complementary signal to the 3
  algebraic baselines.

Ensemble averaging the 4 scoring functions yields strictly better hits@10
than any single model on FB15K-237 / WN18RR; same dynamic expected here
given the relational diversity (13 relation types spanning hierarchical /
spatial / regulatory / temporal axes).

## SageMaker job spec

- Instance: `ml.g4dn.12xlarge` × 1 (4× T4 GPU, 192 GiB RAM, $3.91/h on-demand)
- Volume: 200 GB EBS
- Max runtime: 24h (`MaxRuntimeInSeconds=86400`)
- Training image: `763104351884.dkr.ecr.ap-northeast-1.amazonaws.com/pytorch-training:2.1.0-gpu-py310-cu121-ubuntu20.04-sagemaker`
- Role: `arn:aws:iam::993693061769:role/jpcite-sagemaker-execution-role`
- Output prefix: `s3://jpcite-credit-993693061769-202605-derived/models/jpcite-kg-completion-v1/{transe,rotate,complex,conve}/`

Sequential vs parallel:

- **Sequential** (default): driver submits one model, prints
  `[seq] re-run driver after <job_name> completes` and exits. Operator
  re-runs the driver with `--models=RotatE,ComplEx,ConvE` etc. Respects
  the 64-vCPU default quota (g4dn.12xlarge = 48 vCPU, two in parallel
  would already trip 96 vCPU).
- **Parallel** (`--parallel`): driver submits all 4 simultaneously.
  Requires 256-vCPU quota approval (4 × 48 = 192 vCPU + buffer).

Live-mode gate:

```text
DRY_RUN by default.
Live submission requires BOTH:
  --commit
  --unlock-live-aws-commands   (Stream W operator-token gate)
Either flag missing → script prints would-be spec only.
```

This mirrors `feedback_loop_promote_concern_separation` /
`feedback_no_user_operation_assumption` in MEMORY.md: a flag flip in
isolation never triggers a live AWS side-effect — both gates must be
explicit.

## Predicted-edge migration

Migration `wave24_198_am_relation_predicted.sql` adds:

- Table `am_relation_predicted`:
  - `id`, `source_entity_id`, `target_entity_id`, `relation_type`
  - `model` ∈ `{'ensemble', 'TransE', 'RotatE', 'ComplEx', 'ConvE'}`
  - `score`, `rank_in_top_k`, `train_run_id`, `predicted_at`, `notes`
  - FK on `source_entity_id` → `am_entities(canonical_id)` ON DELETE CASCADE
- 4 indexes: src / tgt / score / model+score (last is the canonical hot path)
- Unique index `ux_am_relation_predicted_hrtm` to prevent same `(h, r, t, model)` re-insert
- View `v_am_relation_predicted_top` — ensemble + score >= 0.85, ready
  for downstream MCP `predict_related_entities` lookup

The table is intentionally **separate from `am_relation`** so the canonical
KG never silently absorbs probabilistic edges. Downstream tools that wish
to surface predictions must JOIN explicitly and expose the `confidence` +
`model` provenance.

Idempotent (CREATE IF NOT EXISTS only); applied automatically on every
boot via `entrypoint.sh` §4 (autonomath self-heal migrations).

## Submit driver verification (DRY_RUN, 2026-05-17)

```
[preflight] mtd_usd=0.0000 < 18000.0
[DRY_RUN] would upload source tar (4,135 bytes) to
          s3://jpcite-credit-993693061769-202605-derived/kg_corpus/source/sourcedir-kg-completion-20260517T0830Z.tar.gz
[DRY_RUN] TransE   would submit jpcite-kg-transe-20260517T0830Z
[DRY_RUN] RotatE   would submit jpcite-kg-rotate-20260517T0830Z
[DRY_RUN] ComplEx  would submit jpcite-kg-complex-20260517T0830Z
[DRY_RUN] ConvE    would submit jpcite-kg-conve-20260517T0830Z
[ledger] docs/_internal/sagemaker_kg_completion_2026_05_17_records.json  (4/4 submitted; dry_run=True)
```

Run IDs reserved (placeholder until live `--commit` cycle):

| model | job_name (DRY_RUN) | output S3 prefix |
| --- | --- | --- |
| TransE  | `jpcite-kg-transe-20260517T0830Z`  | `models/jpcite-kg-completion-v1/transe/`  |
| RotatE  | `jpcite-kg-rotate-20260517T0830Z`  | `models/jpcite-kg-completion-v1/rotate/`  |
| ComplEx | `jpcite-kg-complex-20260517T0830Z` | `models/jpcite-kg-completion-v1/complex/` |
| ConvE   | `jpcite-kg-conve-20260517T0830Z`   | `models/jpcite-kg-completion-v1/conve/`   |

Re-running the driver under live mode will mint a fresh `--run-id` (UTC
timestamp) so the placeholder names above are not load-bearing — only the
spec shape and S3 layout are.

## Verification commands (post-live submission)

```bash
# Status (per job)
aws sagemaker describe-training-job \
  --training-job-name jpcite-kg-transe-<RUN_ID> \
  --profile bookyou-recovery --region ap-northeast-1 \
  --query '{Status:TrainingJobStatus,Secondary:SecondaryStatus,Started:TrainingStartTime,Ended:TrainingEndTime,FailureReason:FailureReason}'

# CloudWatch logs
aws logs tail /aws/sagemaker/TrainingJobs \
  --log-stream-name-prefix jpcite-kg-transe-<RUN_ID> \
  --profile bookyou-recovery --region ap-northeast-1 --follow
```

After each job completes (status = `Completed`):

```bash
# Download trained model
aws s3 cp \
  s3://jpcite-credit-993693061769-202605-derived/models/jpcite-kg-completion-v1/transe/jpcite-kg-transe-<RUN_ID>/output/model.tar.gz \
  /tmp/jpcite-kg-transe.tar.gz \
  --profile bookyou-recovery --region ap-northeast-1

mkdir -p data/_cache/jpcite-kg-transe
tar -xzf /tmp/jpcite-kg-transe.tar.gz -C data/_cache/jpcite-kg-transe
cat data/_cache/jpcite-kg-transe/training_summary.json
```

`training_summary.json` carries per-model `hits_at_1 / hits_at_3 /
hits_at_10 / mean_reciprocal_rank` on the held-out test split.

## Missing-edge inference (post-training aggregator)

The 4 trained models will be joined by a follow-up aggregator
(`kg_completion_aggregate_2026_05_17.py`, not part of this lane's commit
because it runs **after** at least one model checkpoint lands). The
aggregator will:

1. Load all 4 checkpoints (CPU-only — `torch.load`).
2. For each `(h, r)` pair appearing in train, score all candidate `t`
   entities under each model.
3. Mean-pool the 4 scores into an ensemble score.
4. Emit `(h, r, t, score)` tuples with `score >= 0.85` and `(h, r, t)`
   not already in `am_relation`.
5. Bulk-insert into `am_relation_predicted` with `model='ensemble'`
   plus 4 separate `model='<individual>'` rows for provenance.

Expected output: **50K-100K new edges** with ensemble score >= 0.85,
biased toward the high-density relations (`related`, `part_of`,
`has_authority`) where the embedding space has enough signal.

## Follow-up MCP tool

A new MCP tool `predict_related_entities` (gated by
`AUTONOMATH_KG_PREDICTION_ENABLED`) will surface the
`v_am_relation_predicted_top` view to callers:

```python
@mcp.tool
def predict_related_entities(
    entity_id: str,
    relation_type: str | None = None,
    min_score: float = 0.85,
    limit: int = 20,
) -> dict:
    """Top-N predicted related entities under the ensemble KG model."""
```

The tool is **separate** from the existing `related_programs` (which walks
the canonical `am_relation` only) — call sites that want probabilistic
edges must explicitly opt in. The gate defaults to OFF until at least one
trained model lands and the aggregator backfills.

## Constraints honoured

- `$19,490 Never-Reach` absolute: preflight gate enforces $18,000 hard
  stop; ensemble hard-capped at <$400 ($94 × 4 jobs).
- NO LLM API anywhere (`anthropic` / `openai` / `gemini` / etc.).
- DRY_RUN default on submit driver + corpus exporter; live-mode gate
  requires `--commit` AND `--unlock-live-aws-commands` (Stream W token
  gate).
- `[lane:solo]` marker on all 4 scripts.
- mypy / ruff friendly.
- `safe_commit.sh` wrapper used for the landing commit.

## Honest gap

- This commit lands the **deliverables** (exporter + entry + driver +
  migration + doc); it does **not** flip `live_aws_commands_allowed` to
  `true`. The current absolute lock state (150+ tick `live_aws=false`
  堅守 in MEMORY.md) is preserved. Real GPU submissions remain pending
  the operator's explicit unlock.
- Per-model `hits@10` cannot be reported until at least one job completes.
  Once the live cycle runs, this doc's status table will be amended with
  the metric quadruple per model.
- The 50K+ predicted-edge count is a **projection** based on FB15K-237
  ensemble benchmarks; actual yield depends on the long tail of relation
  distributions. The aggregator emits whatever score >= 0.85 yields,
  with no padding.
- `ConvE` requires a 2D reshape over `embedding_dim`; PyKEEN handles
  this automatically when `embedding_dim` factorises evenly (500 = 20×25).
  If a future run uses an awkward dim, ConvE will fail at construction
  time — the script will surface the PyKEEN error verbatim.

## Run-once command reference (operator copy-paste)

```bash
# 1. Build + upload KG corpus to S3 (DRY_RUN by default).
.venv/bin/python scripts/aws_credit_ops/kg_completion_export_2026_05_17.py
.venv/bin/python scripts/aws_credit_ops/kg_completion_export_2026_05_17.py --commit

# 2. DRY_RUN the submit driver (no AWS side-effect).
.venv/bin/python scripts/aws_credit_ops/sagemaker_kg_completion_submit_2026_05_17.py

# 3. Live submit — both flags REQUIRED.
.venv/bin/python scripts/aws_credit_ops/sagemaker_kg_completion_submit_2026_05_17.py \
    --commit \
    --unlock-live-aws-commands

# 4. Sequential mode (default): re-run with --models=<next> after each completes.
.venv/bin/python scripts/aws_credit_ops/sagemaker_kg_completion_submit_2026_05_17.py \
    --commit --unlock-live-aws-commands --models RotatE

# 5. Parallel mode (only if 256-vCPU quota approved).
.venv/bin/python scripts/aws_credit_ops/sagemaker_kg_completion_submit_2026_05_17.py \
    --commit --unlock-live-aws-commands --parallel
```

last_updated: 2026-05-17
