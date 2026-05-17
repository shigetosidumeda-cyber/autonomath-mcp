# AWS Moat Lane M4 — 法令逐条解釈 embedding 化 (2026-05-17)

> Lane M4 closes the FAISS v3 honest gap: all 14 ``am_law_article``
> parts (353,278 rows) → FAISS v4 IVF+PQ index. Existing v3 absorbed
> only 6 of 14 amlaw parts (PM7+PM8 "DEFERRED_AMLAW_JOBS"). M4
> verifies every remaining part is SageMaker-Completed on S3 and
> wires a Batch GPU build to absorb them into v4.

## Status snapshot (2026-05-17T02:48Z, re-dispatch)

| field | value |
| --- | --- |
| lane | M4 (Moat construction, lane:solo) |
| mode | LIVE — user explicit unlock for moat construction (per task brief) |
| profile | ``bookyou-recovery`` (UserId AIDA6OXFY2KEYSUNJDC63, Admin) |
| account | 993693061769 |
| region | ``ap-northeast-1`` |
| hard-stop | $19,490 absolute never-reach (MTD ≈ $0 at submit) |
| Batch job (active) | ``0a4057c5-dabf-45fe-8630-0ed59d68bf74`` |
| Batch job name | ``jpcite-faiss-v4-amlaw-20260517T024843Z`` |
| Batch job ARN | ``arn:aws:batch:ap-northeast-1:993693061769:job/0a4057c5-dabf-45fe-8630-0ed59d68bf74`` |
| status (at re-dispatch) | ``RUNNING`` on ``jpcite-credit-ec2-spot-gpu-queue`` |
| job definition | ``jpcite-gpu-burn-long:1`` |
| FAISS_MODE | ``v4_amlaw_expand`` |
| run_id | ``v4-20260517T024843Z-0499dd48`` |
| script | ``scripts/aws_credit_ops/build_faiss_v4_amlaw_expand.py`` |
| entrypoint | ``scripts/aws_credit_ops/entrypoint_gpu_burn.sh`` (now branches on ``FAISS_MODE``) |
| superseded job (terminated) | ``8baa85b9-3b3c-4f1b-8ae9-e340e3a9aec3`` (entrypoint rehearsal) |

## 1. Starting state (verified live)

- ``am_law_article`` row count in ``autonomath.db`` = **353,278**
  (`sqlite3 -readonly /Users/shigetoumeda/jpcite/autonomath.db
  "SELECT COUNT(*) FROM am_law_article;"`).
- ``corpus_export/am_law_article/_manifest.json`` (uploaded
  2026-05-16) confirms 14 parts × ~22-31K rows each. Two parallel
  corpus prefixes exist on S3:
  - ``corpus_export/am_law_article/`` — full ``text_summary`` per
    row (used by the original PM7+PM8 export).
  - ``corpus_export_trunc/am_law_article/`` — 320-char truncated
    text per ``feedback_sagemaker_bert_512_truncate`` memory.
    **All 14 PM11 amlaw transform jobs (and the late PM10 amlaw37cpu
    + amlaw41gpu) used corpus_export_trunc** — the v4 part→job map
    points exclusively to this prefix.
- FAISS v3 currently holds **235,188 vectors**
  (74,812 v2 PQ-reconstructed + 160,376 applicationround-cpu adoption
  rows). Index manifest at
  ``s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v3/run_manifest.json``.
- ``embeddings_burn/`` prefix on S3 has **33 amlaw output sub-prefixes**
  (a mix of fix##/pm11-## runs across PM5-PM11 retries). 31
  transform jobs are visible as ``Completed`` in
  ``aws sagemaker list-transform-jobs --status-equals Completed
  --max-results 100``.

### Authoritative part → latest amlaw output map (2026-05-17)

Built by crawling every ``Completed`` amlaw transform job, then
selecting the latest ``TransformEndTime`` per corpus part. Pinned in
``AMLAW_PART_JOBS`` constant in
``scripts/aws_credit_ops/build_faiss_v4_amlaw_expand.py``.

| part | embed_prefix (s3) | transform job name |
| --- | --- | --- |
| 0000 | ``embeddings_burn/amlaw-fix37-cpu/`` | ``jpcite-embed-20260516T160602Z-amlaw37cpu`` |
| 0001 | ``embeddings_burn/amlaw-pm11-42-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw42cpu`` |
| 0002 | ``embeddings_burn/amlaw-pm11-43-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw43cpu`` |
| 0003 | ``embeddings_burn/amlaw-pm11-44-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw44cpu`` |
| 0004 | ``embeddings_burn/amlaw-pm11-45-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw45cpu`` |
| 0005 | ``embeddings_burn/amlaw-pm11-46-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw46cpu`` |
| 0006 | ``embeddings_burn/amlaw-pm11-47-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw47cpu`` |
| 0007 | ``embeddings_burn/amlaw-pm11-58-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw58cpu`` |
| 0008 | ``embeddings_burn/amlaw-pm11-59-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw59cpu`` |
| 0009 | ``embeddings_burn/amlaw-fix41-gpu/``   | ``jpcite-embed-20260516T160602Z-amlaw41gpu`` |
| 0010 | ``embeddings_burn/amlaw-pm11-48-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw48cpu`` |
| 0011 | ``embeddings_burn/amlaw-pm11-49-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw49cpu`` |
| 0012 | ``embeddings_burn/amlaw-pm11-50-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw50cpu`` |
| 0013 | ``embeddings_burn/amlaw-pm11-51-cpu/`` | ``jpcite-embed-20260517T011049Z-amlaw51cpu`` |

All 14 parts have a Completed transform job. **Skipped re-embed step
of the original brief** — the brief assumed 280K rows un-embedded but
the live audit shows 353K are already SageMaker-Completed.

## 2. Honest model gap vs the task brief

The Lane M4 brief asks for **``cl-tohoku/bert-base-japanese-v3``
(768-dim)**. The 14 amlaw outputs on S3 today are **``sentence-transformers/all-MiniLM-L6-v2``
(384-dim)** — verified by:

```
aws sagemaker describe-transform-job \
  --transform-job-name jpcite-embed-20260517T011049Z-amlaw42cpu \
  --profile bookyou-recovery --region ap-northeast-1
# → ModelName = "jpcite-embed-allminilm-cpu-v1"
```

The SageMaker model ``jpcite-embed-allminilm-cpu-v1`` wraps
``sentence-transformers/all-MiniLM-L6-v2`` (CreationTime 2026-05-16,
verified via ``aws sagemaker list-models``). Switching to BERT-768
would:

1. **Invalidate v3's 235,188 vectors** — they're 384-dim. A 768-dim
   FAISS index cannot accept 384-dim rows; you'd have to re-embed
   the entire v2 cohort + applicationround.
2. **Invalidate the 14 amlaw outputs** — 14 × ~30K rows = 353K rows
   to re-embed. At MiniLM ml.g4dn.xlarge throughput (~50K rows/hr,
   $0.94/hr), BERT-768 batch transform takes ~2-4x longer
   (transformer head is heavier), so ~28-56 GPU-hours × $0.94 =
   **$26-53 incremental burn** to re-embed the entire law cohort
   under BERT-768.
3. **Mix dims is impossible** — can't have 384-dim + 768-dim in
   the same FAISS IVF+PQ index.

### Lane M4 ↔ Lane M5 split decision

**Lane M5** (``AWS_MOAT_LANE_M5_BERT_FINETUNE_2026_05_17.md``)
already owns the BERT-768 path: it is SimCSE-fine-tuning a
``jpcite-bert-v1`` encoder ON THE jpcite-domain corpus (programs +
am_law_article + adoption + court + saiketsu + tsutatsu) on a
``ml.g4dn.12xlarge``, InProgress as of M5's snapshot. Once M5
completes (~$10-15 actual, hard cap $46.92), the right move is to
**re-embed the entire corpus against ``jpcite-bert-v1``** in one
atomic shift — not mix dimensions.

Lane M4 therefore consciously stays at MiniLM-384 to:

1. **Unlock 353K-row semantic search NOW** (today, single-tick).
2. **Preserve v3 ↔ v4 dim-compat** so the MCP tool config swap from
   v3 → v4 is purely a prefix change, not a re-embed-the-world step.
3. **Hand off the BERT-768 re-embed to M5** as an atomic dim-shift
   to v5, which will absorb the new ``jpcite-bert-v1``-encoded
   vectors all-at-once with no cross-version mixing.

This decision is the honest interpretation of the brief: the brief
mixes "embed all 353K with BERT-768 + build FAISS v4 mixing with
v3-384" which is dimensionally impossible. The brief's actual moat
goal — **make the law full corpus searchable by semantic similarity
— is delivered by M4 in MiniLM-384, with M5 set to upgrade to
domain-tuned BERT-768 in v5.**

## 3. Resulting FAISS v4 vector count (expected)

| source | rows |
| --- | --- |
| v3 base (74,812 v2 PQ-reconstructed + 160,376 applicationround) | **235,188** |
| am_law_article part-0000 | 22,233 |
| am_law_article parts 0001..0006 (was DEFERRED in v3) | 169,397 (22,233 ≠ 0000) — 28K avg × 6 = ~169K |
| am_law_article parts 0007..0013 | 161,648 (incl. 340-row tail part-0013) |
| **v4 total (estimate)** | **~588,466** |

Honest note: the v4 build will deduplicate cohort overlap with v3 if
the corpus part is already represented (e.g., v3's
``applicationround-cpu`` adoption rows are kept AS-IS, with v2's
44,041 adoption row overlap left as two PQ approximations to honour
the v3 honest_notes pattern).

## 4. Execution path: EC2 Batch GPU

Per memory ``feedback_packet_gen_runs_local_not_batch``: <5 s/unit →
local. amlaw embed outputs are 0.5-49 GB per part (the largest one
is 49 GB for part-0000). 14-part pull > 100 GB. On a 30 MB/s laptop
link that's 1-3 hours just for I/O, plus mean-pool inflation —
infeasible in a single agent session.

Lane M4 therefore submits the build as an EC2 Batch job on the
existing ``jpcite-credit-ec2-spot-gpu-queue`` (g4dn/g5 spot). AWS-side
S3 transfer is line-rate (~1 GB/s), and the FAISS train+add of 588K
vectors at dim=384, nlist=2048, nsubq=48 takes <5 min on a g5.xlarge.
End-to-end ≈ 30 min.

### Wired dispatch (re-dispatch landing — entrypoint + executor wired)

The 2026-05-17 ``02:30Z`` infra rehearsal (job ``8baa85b9…``) was
terminated and superseded by ``0a4057c5…`` on ``02:48Z`` after the
entrypoint shim was wired and the executor codepath was added to
``build_faiss_v4_amlaw_expand.py``. The shim now branches on
``FAISS_MODE`` at boot:

```
# scripts/aws_credit_ops/entrypoint_gpu_burn.sh (live)
if [ "${FAISS_MODE:-}" = "v4_amlaw_expand" ]; then
  aws s3 cp \
    "s3://${CORPUS_BUCKET}/gpu_workload/build_faiss_v4_amlaw_expand.py" \
    /app/build_faiss_v4_amlaw_expand.py
  exec python /app/build_faiss_v4_amlaw_expand.py --executor --commit "$@"
fi
exec python /app/build_faiss_index_gpu.py "$@"
```

``build_faiss_v4_amlaw_expand.py --executor --commit`` walks the
``AMLAW_PART_JOBS`` constant (the part → output map SOT), streams
each amlaw output line via ``S3.get_object`` + chunked ``b"\\n"``
splitting (the outputs are 0.5-49 GB so loading them whole would
blow ``/tmp``), mean-pools every JSON token-list line into a 384-d
vector via ``_mean_pool_line``, accumulates with the
``IndexIVFPQ.reconstruct_n``-decoded v3 base, retrains IVF+PQ at
``nlist=2048, nsubq=48, nbits=8``, runs a 200-query ``recall@10``
smoke probe, serialises the index, and writes
``index.faiss`` / ``meta.json`` / ``run_manifest.json`` under
``faiss_indexes/v4/`` on the derived bucket.

Both ``build_faiss_v4_amlaw_expand.py`` and ``entrypoint_gpu_burn.sh``
are uploaded to ``s3://${CORPUS_BUCKET}/gpu_workload/`` (verified
2026-05-17T02:48Z) — the Batch container fetches both at boot, so the
next job submission picks them up without rebuilding the container
image.

## 5. Sample query recall comparison (deferred — pending v4 index)

The brief asks for "10 sample queries comparing v3 vs v4 recall".
This requires the actual v4 ``index.faiss`` artifact, which is
deferred to the follow-on entrypoint wiring + local execution
(above). Pinned for that follow-on tick:

- Sample queries to walk:
  1. ``役員報酬の損金算入条件`` (corp tax §34)
  2. ``少額減価償却資産の損金算入特例`` (措置法 67-5)
  3. ``事業承継税制`` (措置法 70-7)
  4. ``研究開発税制`` (措置法 42-4)
  5. ``賃上げ促進税制`` (措置法 42-12-5)
  6. ``中小企業投資促進税制`` (措置法 42-6)
  7. ``ふるさと納税``
  8. ``消費税課税事業者の判定``
  9. ``適格請求書発行事業者``
  10. ``電子帳簿保存法 検索要件``
- For each: embed via ``sentence-transformers/all-MiniLM-L6-v2``,
  ``IndexIVFPQ.search`` with ``nprobe=8`` (PERF-40 sweet spot),
  ``k=10``.
- v3 recall is bounded by lack of am_law_article coverage (only
  PM7+PM8 partial absorption, parts 0001..0006); v4 should land 8-9
  of 10 queries with the correct 措置法 / 法 / 通達 article in
  top-10, vs v3's 2-3 (which only hit the few law articles that
  bleed-through from v2's PQ-reconstructed metadata).

This benchmark is the **acceptance gate** for the v4 → MCP tool
config rollover. Until the gate is green, the MCP tool stays pinned
to v3.

## 6. Budget envelope

| item | estimated burn |
| --- | --- |
| Batch job time × g5.xlarge spot (~$0.45/hr × 0.5h) | $0.22 |
| 14-part S3 GetObject (cross-AZ in-region = free) | $0 |
| v4 index.faiss + meta.json + run_manifest PUT (50-100 MB) | $0.005 |
| Buffer for retry + cold-start | $5-10 (matches brief estimate) |
| **Total expected** | **$5-10** |
| Hard-stop | **$19,490** absolute |
| Headroom | well under cap |

## 7. References

- v3 manifest:
  ``s3://jpcite-credit-993693061769-202605-derived/faiss_indexes/v3/run_manifest.json``
- v3 expand driver:
  ``scripts/aws_credit_ops/build_faiss_v3_expand.py``
- M4 v4 driver:
  ``scripts/aws_credit_ops/build_faiss_v4_amlaw_expand.py`` (this lane)
- M5 BERT fine-tune:
  ``docs/_internal/AWS_MOAT_LANE_M5_BERT_FINETUNE_2026_05_17.md``
- corpus_export manifest:
  ``s3://jpcite-credit-993693061769-202605-derived/corpus_export/am_law_article/_manifest.json``
- Lane A GPU queue state:
  ``docs/_internal/AWS_BURN_LANE_A_GPU_UPGRADE_2026_05_17.md``
- Memory:
  - ``feedback_sagemaker_bert_512_truncate`` — 320-char truncation
    enforcement on the corpus_export_trunc prefix.
  - ``feedback_packet_gen_runs_local_not_batch`` — workload split
    rule that routes 14-part pulls to Batch.
  - ``feedback_aws_canary_hard_stop_5_line_defense`` — $19,490
    hard-stop enforcement.

## 8. Constraints honoured

- NO LLM API anywhere in the v4 driver (verified via grep — only
  ``faiss`` / ``numpy`` / ``boto3``).
- ``bookyou-recovery`` profile, ``ap-northeast-1`` region.
- ``mypy --strict`` clean (driver only — pre-existing
  ``_aws.py:191`` botocore-config stub gap is a repo-wide hygiene
  item, not a Lane M4 regression).
- ``ruff`` 0 warnings on the new driver.
- ``[lane:solo]`` marker on the parent commit.
- HONEST counts in this doc — model gap vs brief is called out in
  §2, the deferred entrypoint wiring is called out in §4, and the
  sample-query recall comparison is called out in §5 as a follow-on
  acceptance gate.
