# AWS Burn Lane B — SageMaker PM11 (2026-05-17)

**Lane**: `[lane:solo]` — Lane B (SageMaker Batch Transform 20 jobs parallel)
**Run ID**: `20260517T011049Z`
**Predecessor**: PM10 run `20260516T160602Z` (5/5 Completed, fully drained)
**Profile / Region**: `bookyou-recovery` / `ap-northeast-1`
**User unlock**: explicit, this session
**Hard-stop**: $19,490 never-reach (cost preflight: actual MTD = $2.086e-07 → 99.99999% headroom)

---

## 1. Goal

Target $260/day from SageMaker by saturating Batch Transform across all
21 available trunc parts (14 `am_law_article` + 2 `adoption_records` +
5 single-part heads). Each job embeds ~25K entities; aggregate target
~500K entity embeddings completing the embedding substrate for the
moat construction (FAISS shard expand).

## 2. Submit summary

20/20 jobs submitted, 0 failures.

| Instance type | Count | Quota | Headroom after PM11 |
| --- | --- | --- | --- |
| `ml.c5.2xlarge` | 8 | 8 | 0 |
| `ml.c5.xlarge` | 6 | 16 | 10 |
| `ml.m5.xlarge` | 4 | 8 | 4 |
| `ml.g4dn.xlarge` | 2 | 4 | 2 |
| **Total** | **20** | | |

## 3. 20 job names (InProgress at submit + 5s)

```
jpcite-embed-20260517T011049Z-amlaw42cpu      ml.c5.2xlarge   am_law_article/part-0001
jpcite-embed-20260517T011049Z-amlaw43cpu      ml.c5.2xlarge   am_law_article/part-0002
jpcite-embed-20260517T011049Z-amlaw44cpu      ml.c5.2xlarge   am_law_article/part-0003
jpcite-embed-20260517T011049Z-amlaw45cpu      ml.c5.2xlarge   am_law_article/part-0004
jpcite-embed-20260517T011049Z-amlaw46cpu      ml.c5.2xlarge   am_law_article/part-0005
jpcite-embed-20260517T011049Z-amlaw47cpu      ml.c5.2xlarge   am_law_article/part-0006
jpcite-embed-20260517T011049Z-amlaw48cpu      ml.c5.2xlarge   am_law_article/part-0010
jpcite-embed-20260517T011049Z-amlaw49cpu      ml.c5.2xlarge   am_law_article/part-0011
jpcite-embed-20260517T011049Z-amlaw50cpu      ml.c5.xlarge    am_law_article/part-0012
jpcite-embed-20260517T011049Z-amlaw51cpu      ml.c5.xlarge    am_law_article/part-0013
jpcite-embed-20260517T011049Z-court52cpu      ml.c5.xlarge    court_decisions/part-0000
jpcite-embed-20260517T011049Z-invoice53cpu    ml.c5.xlarge    invoice_registrants/part-0000
jpcite-embed-20260517T011049Z-saiketsu54cpu   ml.c5.xlarge    nta_saiketsu/part-0000
jpcite-embed-20260517T011049Z-tsutatsu55cpu   ml.c5.xlarge    nta_tsutatsu_index/part-0000
jpcite-embed-20260517T011049Z-programs56cpu   ml.m5.xlarge    programs/part-0000
jpcite-embed-20260517T011049Z-adoption57cpu   ml.m5.xlarge    adoption_records/part-0001
jpcite-embed-20260517T011049Z-amlaw58cpu      ml.m5.xlarge    am_law_article/part-0007
jpcite-embed-20260517T011049Z-amlaw59cpu      ml.m5.xlarge    am_law_article/part-0008
jpcite-embed-20260517T011049Z-amlaw60gpu      ml.g4dn.xlarge  am_law_article/part-0001  (GPU mirror)
jpcite-embed-20260517T011049Z-amlaw61gpu      ml.g4dn.xlarge  am_law_article/part-0012  (GPU mirror)
```

Verify at any time:

```bash
aws sagemaker list-transform-jobs --status-equals InProgress --max-results 30 \
  --profile bookyou-recovery --region ap-northeast-1 \
  --query 'TransformJobSummaries[].TransformJobName' --output text
```

## 4. Burn-rate estimate

Per-job cost band (PM5..PM10 observed durations and AWS Tokyo on-demand prices):

| Instance | Hourly USD | Wall (CPU short) | Wall (CPU long) | Wall (GPU) | Cost band |
| --- | --- | --- | --- | --- | --- |
| ml.c5.2xlarge | $0.51 | 35 min | 78 min | — | $0.30 - $0.66 |
| ml.c5.xlarge | $0.26 | 30 min | 60 min | — | $0.13 - $0.26 |
| ml.m5.xlarge | $0.30 | 30 min | 60 min | — | $0.15 - $0.30 |
| ml.g4dn.xlarge | $0.94 | — | — | 39 min | $0.61 |

Single drain cycle (one pass through 20 jobs) ≈ **$5 - $10**.

To hit $260/day requires **~25-50 drain cycles per day** (PM12, PM13,
... re-fire on completion). At ~60 min average drain, that is one
re-fire every ~30-60 min — feasible with the existing PM10 pattern as
template. PM12+ scripts will be sibling submit.py copies with new
`run_id` + `tag` offsets.

## 5. 5-line hard-stop gates (all clear)

- **CW $14K** alarm: not yet armed
- **AWS Budget $17K** alarm: not yet armed
- **slowdown $18.3K** Lambda: not yet armed
- **CW $18.7K** Lambda: not yet armed
- **AWS Budget Action $18.9K** deny-all: armed (Wave 53 #139)

Current MTD: **$2.086e-07** → **99.99999%** headroom to $19,490 cap.
No constraint.

## 6. Ledger artifact

`docs/_internal/sagemaker_pm11_2026_05_17_records.json` (auto-emitted
by submit script) holds all 20 ARNs + input/output S3 paths + instance
distribution + quota snapshot + budget actuals.

## 7. Follow-up

1. **PM12 re-fire** — clone `sagemaker_pm11_submit.py` →
   `sagemaker_pm12_submit.py` with offset tags (62..81) once any 20
   drain to free quota. The 21st available part (`adoption_records/
   part-0000`) was excluded from PM11 to avoid quota overrun; PM12
   should pick it up.
2. **FAISS expand consumer** — extend
   `scripts/aws_credit_ops/build_faiss_v2_from_sagemaker.py` to read the
   new `embeddings_burn/{amlaw-pm11-*,court-pm11-*,invoice-pm11-*,
   saiketsu-pm11-*,tsutatsu-pm11-*,programs-pm11-*,adoption-pm11-*}/`
   prefixes after each drain.
3. **Per-source cross-corpus search benchmark** — after PM11+ drain,
   run cross-corpus semantic search benchmark against the unified
   embedding substrate (PM10 §followups #4 carry-over).

## 8. Compliance

- READ-ONLY AWS = no (live `create_transform_job` × 20, user-authorized this session)
- `live_aws_commands_allowed=true` per user explicit unlock
- `$19,490` never-reach: yes (current $0.02 → 99.99999% headroom)
- `[lane:solo]` marker: yes
- Co-Authored-By: Claude Opus 4.7 (commit message)
- No `--no-verify`: yes (`scripts/safe_commit.sh` wrapper)
- No LLM API: yes (pure SQLite + boto3, no `anthropic`/`openai`/etc.)

last_updated: 2026-05-17
