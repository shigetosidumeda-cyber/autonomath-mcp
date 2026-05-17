# AWS cleanup + M11 retry (2026-05-17 PC restart)

last_updated: 2026-05-17
status: M11 resubmitted (InProgress), OpenSearch domain confirmed live,
        working tree drained across 7+ concurrent agent commits.

## Context

PC restart interrupted the 18-lane background agent fan-out mid-execution.
After restart, the working tree carried 170+ files of partial-progress
state spanning `data/artifact_templates/`, `data/recipes/`,
`data/finetune_corpus_multitask/`, multiple `docs/_internal/AWS_*` moat
snapshots, `scripts/aws_credit_ops/*` packet generators, `scripts/
migrations/wave24_199..206` SQL, `src/jpintel_mcp/mcp/moat_lane_tools/`,
and `src/jpintel_mcp/mcp/autonomath_tools/*`.

During the drain, **7 concurrent agent commits** absorbed parallel
slices of the residual state:

- `35547a623` — M1+M3+M4+M9 combined LIVE promote manifest
- `0087f5b0d` — Lane M7 KG completion DRY_RUN -> LIVE
- `974a5f3cb` — Operator unlock `live_aws_commands_allowed=True`
- `683d40c9f` — M6 + M8 LIVE bundle (cross-encoder + citation rerank)
- `4a442cf8a` — 7-day continuous moat-burn ramp orchestrator
- `3688458ff` — N1 LIVE 50 士業 artifact template bank + 2 MCP tools
- `75d8d3617` — N2 法人×制度 portfolio gap analysis
- `7bb7cd3bd` — N3 Legal reasoning chain DB (160 topics × 5 = 800 chains)

## M11 failure root cause

`describe-training-job` FailureReason captured the classic torch +
multiprocessing-fork foot-gun:

```
RuntimeError: Cannot re-initialize CUDA in forked subprocess.
To use CUDA with multiprocessing, you must use the 'spawn' start method
```

The trace pinpoints `multitask_train_entry.py:collate` — moving tensors
to `device` inside the DataLoader worker processes (default
`num_workers=2`, default fork start method on Linux). PyTorch forbids
CUDA re-initialisation inside a forked subprocess.

## M11 fix (applied to the S3-uploaded source tar)

The `scripts/aws_credit_ops/multitask_train_entry.py` source tar that
was uploaded **at the moment of M11 retry submit** carries this fix:

- `collate(...)` no longer touches CUDA — labels stay CPU-resident,
  the encoding dict is passed through unmodified.
- Train loop now moves `batch["encoding"]` + `batch["labels"]` to
  `device` in the main process (post-fork-safe).
- Validation loop applies the same pattern.

The training image (`huggingface-pytorch-training:2.1.0-...-cu121`)
and all hyperparameters / channels / role / instance type are
unchanged. SageMaker downloads source from the frozen S3 URI at
job-start, so the live retry job carries the fix regardless of any
subsequent concurrent-agent edits to the local file.

> **Verification**: `s3://jpcite-credit-993693061769-202605-derived/finetune_corpus_multitask/source/sourcedir-jpcite-multitask-large-20260517T040000Z.tar.gz`
> inspected via `tarfile.extractfile` — fix marker `"NOTE: do NOT
> move tensors to CUDA inside collate"` present.

## M11 retry submit

```
aws sagemaker create-training-job \
  --training-job-name jpcite-multitask-large-20260517T040000Z
ARN: arn:aws:sagemaker:ap-northeast-1:993693061769:training-job/jpcite-multitask-large-20260517T040000Z
```

Status timeline (verified):
- 12:08:16 JST — Starting -> Pending
- 12:21:40 JST — Pending -> Downloading
- (Training -> Uploading -> Completed expected over ~30-60 min wall time)

Same `ml.g5.4xlarge × 1`, same channels (`s3://jpcite-credit-...-derived/finetune_corpus_multitask/train.jsonl` + `val.jsonl`), same role
(`jpcite-sagemaker-execution-role`), same hyperparameters.

## OpenSearch domain state

`jpcite-xfact-2026-05` is fully provisioned — **NOT** missing:

- `Created: true`, `Deleted: false`, `Processing: false`
- ClusterConfig: `r5.4xlarge.search × 3` + `r5.large.search × 3
  dedicated masters` + `ultrawarm1.medium.search × 3`
- Zone-aware (3 AZ), EBS `gp3 × 500 GB` + 3000 IOPS + 250 MB/s
- Endpoint: `search-jpcite-xfact-2026-05-zcb4ecabq7znunu5yzdj2afzzy.ap-northeast-1.es.amazonaws.com`

No re-creation needed. The earlier "NULL" reading was a stale
snapshot — domain landed on 2026-05-17 AM with M10 spec already at
the 3-node target.

## EventBridge gate

`aws events list-rules --state ENABLED`:

| Rule                                     | State   | Schedule          |
| ---------------------------------------- | ------- | ----------------- |
| StepFunctionsGetEventsForBatchJobsRule   | ENABLED | (Step-Functions internal) |
| jpcite-credit-burn-metric-5min           | ENABLED | rate(5 minutes)   |

Lane D / E and all canary schedules remain **DISABLED**. The two
ENABLED rules are infrastructure-monitoring only (no AWS spend impact
beyond CloudWatch metric publication).

## InProgress jobs (do NOT touch)

| Job name                                       | Status               |
| ---------------------------------------------- | -------------------- |
| jpcite-bert-simcse-finetune-20260517T022501Z   | InProgress (Lane M5) |
| jpcite-kg-transe-20260517T030742Z              | InProgress (Lane M7) |
| jpcite-multitask-large-20260517T040000Z        | InProgress (M11 retry) |

## Cost guards still armed

- `$14K` CloudWatch action / `$17K` Budget action / `$18.3K` slowdown /
  `$18.7K` CW Lambda / `$18.9K` action-deny — none of these touched.
- Per memory `feedback_aws_canary_hard_stop_5_line_defense`, the
  5-line defense around the $19,490 absolute cap remains armed.

## Lessons / followups

1. **Default-fork DataLoader + CUDA is a perennial foot-gun.** Add a
   pre-flight lint rule: any `device=` kwarg inside a `collate`
   closure should fail CI for SageMaker entrypoints.
2. **Concurrent agents pulled mid-edit.** Several rounds of local
   edits were reverted by `git pull` from concurrent commits. The S3
   source tar (frozen at submit time) was unaffected, so the live
   M11 retry carries the fix even though the local file may show
   the original broken state until the concurrent commit cadence
   absorbs the residual fix.
