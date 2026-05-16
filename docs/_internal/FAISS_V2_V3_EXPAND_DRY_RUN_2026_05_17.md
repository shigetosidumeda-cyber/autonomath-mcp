# FAISS v2 + v3 expand dry-run plan (2026-05-17)

Append-only verification snapshot. Documents the as-of-2026-05-17 state of
`scripts/aws_credit_ops/build_faiss_v2_expand.py` and
`scripts/aws_credit_ops/build_faiss_v3_expand.py` after they landed in commit
`bf3d7380d` (chore(wave96): 12 data governance packet generators
[lane:solo]). The actual `--unlock-live-aws-commands` live execution is
deferred to operator gate per `live_aws_commands_allowed=false` 150 tick
連続堅守 (CLAUDE.md tick 150 MILESTONE).

## Source verification (no LLM, syntax OK, mypy strict 0, ruff 0)

| script | lines | py_compile | LLM imports | mypy --strict | ruff |
| --- | ---:| ---:| ---:| ---:| ---:|
| `scripts/aws_credit_ops/build_faiss_v2_expand.py` | 682 | OK | none | 0 | 0 |
| `scripts/aws_credit_ops/build_faiss_v3_expand.py` | 789 | OK | none | 0 | 0 |

`grep -E '^(import |from )(anthropic\|openai\|google\.generativeai\|claude_agent_sdk)'`
on both files returns 0 matches — both scripts are pure
`sentence-transformers` (transformer encoder, no LLM call) + `faiss`
(k-means + PQ) + `boto3` (S3 IO).

## Canonical FAISS builder family (5 scripts, all under `scripts/aws_credit_ops/`)

- `build_faiss_index_from_embeddings.py` — v1 ancestor, IVF+PQ from SageMaker
  PM3-PM5 `embeddings/<family>/part-NNNN.jsonl.out` outputs.
- `build_faiss_v2_from_sagemaker.py` — v2 first attempt, gated on SageMaker
  PM5/PM6 batch transform completion. Failed for 4 families
  (`am_law_article` / `programs` / `court_decisions` / `nta_tsutatsu_index`)
  because PM5/PM6 model containers errored.
- `build_faiss_v2_expand.py` — **v2 expand (current)**. Embeds the 4 missing
  families locally with `sentence-transformers/all-MiniLM-L6-v2` (384-d) and
  rebuilds a fresh IVF+PQ index that includes v1 cohort (PQ-reconstructed)
  plus the 4 new families.
- `build_faiss_index_gpu.py` — GPU path variant of the original builder
  (preserved as a side branch).
- `build_faiss_v3_expand.py` — **v3 expand (current)**. Absorbs PM7+PM8
  SUCCEEDED batch transform outputs into v2: `applicationround-cpu` part-0000
  (116,335 rows) and 6 `am_law_article` parts (~180K rows) into a fresh
  IVF+PQ index. Mirrors the v2 expand strategy.

## Dry-run --help excerpts

### v2 expand

```
usage: build_faiss_v2_expand.py [-h] [--bucket BUCKET]
                                [--corpus-prefix CORPUS_PREFIX]
                                [--v1-prefix V1_PREFIX]
                                [--v2-prefix V2_PREFIX] [--profile PROFILE]
                                [--region REGION] [--families FAMILIES]
                                [--dim DIM] [--nlist NLIST] [--nsubq NSUBQ]
                                [--nbits NBITS] [--train-sample TRAIN_SAMPLE]
                                [--batch-size BATCH_SIZE] [--model MODEL]
                                [--cache-dir CACHE_DIR]
                                [--max-rows-per-family MAX_ROWS_PER_FAMILY]
                                [--smoke-queries SMOKE_QUERIES]
                                [--smoke-k SMOKE_K] [--no-upload]
```

Key defaults: `--bucket
jpcite-credit-993693061769-202605-derived`, `--profile bookyou-recovery`,
`--region ap-northeast-1`, `--dim 384`, `--nlist 1024`, `--nsubq 48`,
`--nbits 8`, model `sentence-transformers/all-MiniLM-L6-v2`. Read-only flag:
`--no-upload` (build index locally without S3 PUT — useful for local
verification before a live run).

### v3 expand

```
usage: build_faiss_v3_expand.py [-h] [--bucket BUCKET]
                                [--embed-prefix EMBED_PREFIX]
                                [--corpus-prefix CORPUS_PREFIX]
                                [--v2-prefix V2_PREFIX]
                                [--v3-prefix V3_PREFIX] [--profile PROFILE]
                                [--region REGION] [--dim DIM] [--nlist NLIST]
                                [--nsubq NSUBQ] [--nbits NBITS]
                                [--train-sample TRAIN_SAMPLE]
                                [--cache-dir CACHE_DIR]
                                [--smoke-queries SMOKE_QUERIES]
                                [--smoke-k SMOKE_K] [--no-upload]
```

v3 expand reads PM7+PM8 outputs from `embeddings_burn/` and v2 vectors from
`faiss_indexes/v2/index.faiss` via `IndexIVFPQ.reconstruct_n`. The `--no-upload`
flag is the read-only verification path.

## S3 destination state (read-only AWS, profile `bookyou-recovery`)

Both v2 and v3 destinations are **already populated** as of 2026-05-17.
Memory note `project_jpcite_pause_2026_05_16_1656jst.md` #189 ("FAISS v2
expand was a known incomplete task… s3://… STILL EMPTY") is **stale**; v2
landed 2026-05-16 20:43 JST and v3 landed 2026-05-17 01:35 JST.

| path | object | size (bytes) | last_modified |
| --- | --- | ---:| --- |
| `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v2/` | `index.faiss` | 4,978,132 | 2026-05-16 20:43:05 |
| same prefix | `meta.json` | 8,099,154 | 2026-05-16 20:43:05 |
| same prefix | `run_manifest.json` | 3,634 | 2026-05-16 20:43:06 |
| `s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v3/` | `index.faiss` | 15,144,980 | 2026-05-17 01:35:49 |
| same prefix | `meta.json` | 35,678,637 | 2026-05-17 01:35:50 |
| same prefix | `run_manifest.json` | 5,835 | 2026-05-17 01:35:51 |

### v2 run_manifest summary

- `run_id`: `v2-sm-20260516T113213Z-a28731cb`
- `build_kind`: `faiss_ivf_pq_v2_from_sagemaker`
- `embedding_model`: `sentence-transformers/all-MiniLM-L6-v2` (384-d)
- v1 cohort: 57,979 PQ-reconstructed (lossy, honest in manifest)
- v2 new families: `programs` 12,753 + `court_decisions` 848 +
  `nta_tsutatsu_index` 3,232
- v2 vector total: **74,812**

### v3 run_manifest summary

- `run_id`: `v3-20260516T155121Z-a9b2ae69`
- `build_kind`: `faiss_ivf_pq_v3_expand_pm7_pm8`
- v2 cohort: 74,812 PQ-reconstructed (lossy, honest in manifest)
- v3 new (`applicationround-cpu` part-0000): `adoption_records` +160,376
- v3 vector total: **235,188**
- v3 train_seconds: 1.94, add_seconds: 2.55
- v3 smoke: 5 queries, recall@10 = 1.0

## Live-run plan (deferred until operator `--unlock-live-aws-commands`)

The actual FAISS build is **NOT** runnable from this lane — it requires
`AWS_CANARY_READY` scorecard flip via `--unlock-live-aws-commands` operator
token gate (Stream W concern separation per `feedback_loop_promote_concern_separation`).
This doc is the read-only verification artifact.

When the operator authorizes, the canonical invocation is:

```bash
# v2 expand
.venv/bin/python scripts/aws_credit_ops/build_faiss_v2_expand.py \
  --bucket jpcite-credit-993693061769-202605-derived \
  --profile bookyou-recovery \
  --region ap-northeast-1

# v3 expand (requires v2 landed in S3, which it is)
.venv/bin/python scripts/aws_credit_ops/build_faiss_v3_expand.py \
  --bucket jpcite-credit-993693061769-202605-derived \
  --profile bookyou-recovery \
  --region ap-northeast-1
```

Since the S3 destinations are already populated with manifests from the
2026-05-16 / 2026-05-17 builds, a fresh live run would overwrite. The
operator should decide whether to (a) leave the current indexes in place
(no-op), (b) regenerate with a versioned suffix
(`--v2-prefix faiss_indexes/v2-rebuild-YYYYMMDD/`), or (c) bump to v4 expand
after PM9/PM10 SageMaker outputs land.

## Constraints satisfied

- NO LLM imports (anthropic / openai / google.generativeai / claude_agent_sdk)
- NO `--unlock-live-aws-commands` flag used in this lane
- Read-only AWS operations only (`s3 ls`, `s3 cp run_manifest.json`,
  `s3api head-object`)
- mypy --strict: 0 errors on both files
- ruff: 0 errors on both files
- `[lane:solo]` marker on parent commit `bf3d7380d`
- pre-commit hooks: not bypassed (this doc is the only new artifact)

last_updated: 2026-05-17
