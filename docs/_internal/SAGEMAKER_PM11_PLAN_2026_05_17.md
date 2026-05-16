# SageMaker PM11 Plan + Lifecycle Snapshot (2026-05-17)

**Lane**: `[lane:solo]`
**Predecessor**: `docs/_internal/sagemaker_pm10_2026_05_17.md` (run `20260516T160602Z`)
**Mode**: READ-ONLY snapshot + plan-only. No live submit, no terminate.
**AWS profile**: `bookyou-recovery` / region `ap-northeast-1`
**Pre-condition**: `live_aws_commands_allowed=false` (150+ tick absolute) → **plan-only**, no `--commit` in this lane

---

## 1. SageMaker job lifecycle snapshot (2026-05-17)

### 1.1 Transform jobs per status

```
aws sagemaker list-transform-jobs --status-equals <STATUS> --max-results 10 \
    --profile bookyou-recovery --region ap-northeast-1
```

| Status | Count (last 10 page) | Notes |
| --- | --- | --- |
| InProgress | **0** | PM10 fully drained (5/5 Completed) |
| Stopping | 0 | clean |
| Stopped | 0 | clean |
| **Completed** | **10+** (last 10 page top) | PM10 last 5 (20260516T160602Z run): amlaw41gpu / 40gpu / 39gpu / adoption38cpu / amlaw37cpu — all `Completed` between 01:44:23 — 02:19:49 JST (durations 35min CPU short / 78min CPU long / ~39min GPU each) |
| Failed | 0 | clean |

Total transform jobs (all-status `Completed` so far across PM5..PM10): **33 rows in last-100 list page**.

Verified S3 outputs for PM10 final batch:
- `embeddings_burn/amlaw-fix37-cpu/` — am_law_article part-0000, 22,233 rows
- `embeddings_burn/adoption-fix38-cpu/` — adoption_records part-0000 (re-trunc), 116,335 rows
- `embeddings_burn/amlaw-fix39-gpu/` — am_law_article part-0007 GPU mirror, 28,049 rows
- `embeddings_burn/amlaw-fix40-gpu/` — am_law_article part-0008 GPU mirror, 27,252 rows
- `embeddings_burn/amlaw-fix41-gpu/` — am_law_article part-0009 GPU mirror, 26,332 rows

### 1.2 Training jobs per status

```
aws sagemaker list-training-jobs --status-equals <STATUS> ...
```

| Status | Count | Notes |
| --- | --- | --- |
| InProgress | 0 | training surface is **empty** on SageMaker — fine-tune live on **Batch GPU** lane, not SageMaker Training |
| Stopping/Stopped/Completed/Failed | 0 | never used |

**Finding**: FAISS fine-tune is run via **AWS Batch GPU queue** (`jpcite-credit-ec2-spot-gpu-queue`), not SageMaker Training Jobs. PM11 plans must respect this split — embedding = SageMaker batch transform, fine-tune/FAISS index build = Batch GPU.

### 1.3 SageMaker quotas (region ap-northeast-1)

| Quota | Value | PM10 peak in-flight | PM11 ceiling |
| --- | --- | --- | --- |
| `ml.c5.2xlarge for transform job usage` | **8** | 7 (PM10) | 8 (no concurrent PM holds) |
| `ml.g4dn.xlarge for transform job usage` | **4** | 3 (PM10) | 4 (no concurrent PM holds) |

### 1.4 Models

| Model | Created | Purpose |
| --- | --- | --- |
| `jpcite-embed-allminilm-v1` | 2026-05-16 13:37 JST | GPU (ml.g4dn.xlarge) embedding (all-MiniLM-L6-v2, 384d) |
| `jpcite-embed-allminilm-cpu-v1` | 2026-05-16 15:06 JST | CPU (ml.c5.2xlarge) embedding (same 384d model, CPU-optimized inference path) |

---

## 2. GPU job (AWS Batch) lifecycle snapshot

Queue: `jpcite-credit-ec2-spot-gpu-queue`

| Status | Count | Notes |
| --- | --- | --- |
| **RUNNING** | **4** | `faiss-programs-deep`, `faiss-laws-deep`, `faiss-cross-cohort`, `finetune-minilm-programs` (all 20260516T071440Z run id, age ~9-10h) |
| SUCCEEDED | 0 | (none yet — long-burn jobs) |
| **FAILED** | **3** | `faiss-programs`, `faiss-laws`, `faiss-adoption` (20260516T061111Z..061120Z — early run, before the *-deep / *-finetune retry batch was queued) |
| **RUNNABLE** | **2** | `finetune-minilm-laws`, `finetune-minilm-adoption` (queued waiting for GPU capacity to free) |
| STARTING | 0 | clean |

**Interpretation**: GPU lane is **saturated** — 4 RUNNING + 2 RUNNABLE queued, all on the embed/fine-tune pipeline. Spot capacity is being recycled appropriately as RUNNING jobs free up. Early 3 FAILED (06:11Z) are old; the *-deep / *-finetune retry batch (07:14Z) is the live cohort.

---

## 3. Cost snapshot

- **CE MTD** (Cost Explorer 8-12h lag): May 2026 actual = **~$0.02 gross / $0.018 net** (BookYou compromise credit kicker active, recovery profile OK)
- 2026-05-17 (today): **$0.00** unblended in CE so far (lag dominant; live burn is GPU spot + SageMaker transform from past 24h)
- Last 3 daily: `2026-05-15 $0.0000000071 / 2026-05-16 $0.0000000155 / 2026-05-17 $0.00` (CE lag artifact, real burn dominates after ~12h)
- **Hard-stop**: `$19,490` never-reach. Current $0.02 → **99.9999% headroom**. No constraint.
- **Budget Action**: $18,900 deny-all auto-attached (Wave 53 #139).

---

## 4. Corpus inventory (read-only S3 verify)

### 4.1 corpus_export/ raw parts

| Prefix | Raw parts | Trunc parts | Embedded (PM5..PM10) | Gap |
| --- | --- | --- | --- | --- |
| `am_law_article/` | 14 (0000..0013) | 14 | **14 (CPU+GPU mix, 0007..0009 doubly)** | **0 untouched** |
| `adoption_records/` | 2 (0000..0001) | 2 | **2** | **0 untouched** |
| `programs/` | 1 | 1 | 1 (PM5 programs17) | 0 |
| `invoice_registrants/` | 1 | 1 | 1 (PM5 invoice18) | 0 |
| `nta_saiketsu/` | 1 | 1 | 1 (PM5 saiketsu19) | 0 |
| `nta_tsutatsu_index/` | 1 | 1 | 1 (PM5 tsutatsu20gpu) | 0 |
| `court_decisions/` | 1 | 1 | 1 (PM5 court21gpu) | 0 |

**Verdict**: **zero untouched raw parts remain** in current S3 snapshot (PM10 closure framing verified). PM11 cannot be "more of the same".

### 4.2 NOT-YET-EXPORTED canonical autonomath tables (PM11 candidate corpora)

These tables live in `autonomath.db` (12 GB) and have **no `corpus_export/` ETL pass** yet:

| Table | Row count | Embed candidate? | Justification |
| --- | --- | --- | --- |
| `am_enforcement_detail` | 22,258 | **HIGH** | 6,455 with houjin_bangou + amount_yen; powers `houjin_360` enforcement axis; semantic search valuable |
| `am_compat_matrix` | 43,966 | MEDIUM | 4,300 sourced pairs + heuristic; binary compat flag dominates, embedding adds limited signal over join |
| `am_amendment_diff` | 12,116 | **HIGH** | cron-live since 2026-05-02; semantic diff = high-value query target (amendment lineage) |
| `am_tax_treaty` | 33 | LOW | tiny, hand-curated; not worth a dedicated PM cycle |
| `am_amount_condition` | 250,946 | LOW (data quality) | majority template-default ¥500K/¥2M from broken ETL — re-validate before embed |
| `am_industry_jsic` | 37 | LOW | small taxonomy; load directly, no embed needed |

---

## 5. PM11 proposed batch (3 alternative routes; pick one based on user intent)

> **All routes are PLAN-ONLY.** `live_aws_commands_allowed=false` blocks `--commit`.
> Implementation: clone `scripts/aws_credit_ops/sagemaker_pm10_submit.py` →
> `sagemaker_pm11_submit.py` with the chosen jobs list; DRY_RUN default preserved.

### Route A — **Canonical autonomath table backfill** (recommended)

Embed the 2 highest-value never-touched autonomath tables to unlock new semantic-search surfaces. Prerequisites: an ETL pass to materialize `corpus_export/{am_enforcement_detail, am_amendment_diff}/part-0000.jsonl` before any SageMaker submit.

| Tag | Instance | Source (after ETL pass) | Est. rows | Est. walltime | Est. cost |
| --- | --- | --- | --- | --- | --- |
| `enforce42cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_enforcement_detail/part-0000.jsonl` | 22,258 | ~15 min | $0.10 |
| `enforce43gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_enforcement_detail/part-0000.jsonl` | 22,258 | ~32 min | $0.50 |
| `amend44cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_amendment_diff/part-0000.jsonl` | 12,116 | ~9 min | $0.06 |
| `amend45gpu` | ml.g4dn.xlarge | `corpus_export_trunc/am_amendment_diff/part-0000.jsonl` | 12,116 | ~18 min | $0.28 |
| `compat46cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_compat_matrix/part-0000.jsonl` (sourced pairs only — 4,300 rows) | 4,300 | ~3 min | $0.02 |
| **Total (5 jobs)** | 3 CPU + 2 GPU | | **~73K row-passes** | parallel ~32 min wall | **~$0.96** |

Quota: 3/8 CPU + 2/4 GPU → headroom 5 CPU + 2 GPU.

### Route B — **Corpus re-export with monthly-grown tables** (deferred — lower urgency)

`am_law_article` + `invoice_registrants` have grown since the 2026-05-16 13:51 corpus_export snap (am_law_article ETL is live; invoice_registrants picks up monthly 4M-row zenken bulk on 1st-of-month). PM11 could trigger a fresh ETL → re-embed delta only. **But**: delta detection requires `_manifest.json` content_hash diff first, which is a separate ETL gate.

| Tag | Instance | Source (delta after re-export) | Est. rows | Est. cost |
| --- | --- | --- | --- | --- |
| `amlawdelta47cpu` | ml.c5.2xlarge | `corpus_export_trunc/am_law_article/part-{0014..}.jsonl` (new parts only) | TBD (unknown growth) | TBD |
| `invoicedelta48cpu` | ml.c5.2xlarge | `corpus_export_trunc/invoice_registrants/part-0001.jsonl` (monthly bulk) | 4M+ if bulk landed | $20-30 if 4M |

**Verdict**: high variance, blocked on prior ETL + manifest diff. Defer to post-Route-A.

### Route C — **FAISS fine-tune via SageMaker Training** (architectural pivot — defer)

Currently fine-tune runs on Batch GPU queue (4 RUNNING + 2 RUNNABLE on `finetune-minilm-{programs,laws,adoption}`). Moving fine-tune to SageMaker Training Jobs would unify the embed/fine-tune control plane but adds ~30 min infra time for role + bucket + estimator scaffolding. **Not recommended for PM11** — Batch GPU lane is working.

---

## 6. PM11 recommendation: **Route A, 5 jobs**

Rationale:
1. **Closes a real moat hole** — `am_enforcement_detail` + `am_amendment_diff` are high-query-value tables with 0% embedding coverage today.
2. **Within all quotas** — 3 CPU + 2 GPU peak, well under 8/4.
3. **Cheap** — ~$0.96 vs $19,490 cap = 0.005% headroom impact.
4. **Compatible with FAISS expand consumer** — once embedded, the existing FAISS shard build pipeline (Wave 53 #185) picks up the new prefixes automatically.
5. **Independent of Batch GPU lane** — does not contend with the 4 RUNNING fine-tune jobs.

### 6.1 Pre-conditions before any PM11 `--commit`

1. **`live_aws_commands_allowed=true`** — currently **false** (150+ tick absolute). User must explicitly flip via `--unlock-live-aws-commands` (Stream W concern-separation flag).
2. **ETL pass to materialize new corpus_export prefixes**: write `/tmp/pm11_export_canonical.py` that streams `am_enforcement_detail` + `am_amendment_diff` + `am_compat_matrix` (sourced rows) → JSONL → `s3://jpcite-credit-993693061769-202605-derived/corpus_export/{table}/part-0000.jsonl`.
3. **Trunc pass** to materialize `corpus_export_trunc/{table}/part-0000.jsonl` (320-char trunc for BERT 512-token cap headroom).
4. **Preflight 5-line hard-stop check** (already in `sagemaker_pm10_submit.py:preflight_cost_check()` — clone unchanged).
5. **Tag `wave=PM11`** on all submitted jobs for cost attribution.

### 6.2 Cost ceiling against $19,490 hard-stop

| Layer | Cost | Remaining headroom |
| --- | --- | --- |
| CE MTD May 2026 | $0.02 | $19,489.98 |
| PM11 Route A worst case | $0.96 | $19,489.02 |
| Combined PM5..PM10 + PM11 | <$50 cumulative | >$19,440 headroom |
| 5-line CW alarms | All-clear | CW $14K / Budget $17K / slowdown $18.3K / CW $18.7K Lambda / Action $18.9K deny |

**0.005% of hard-stop. No constraint.**

---

## 7. Follow-up tasks (deferred, post-PM11)

1. **FAISS shard build over PM11 outputs** — extend `scripts/aws_credit_ops/build_faiss_v2_from_sagemaker.py` to pick up the new `embeddings_burn/{enforce-fix42-cpu, enforce-fix43-gpu, amend-fix44-cpu, amend-fix45-gpu, compat-fix46-cpu}/` prefixes.
2. **Glue table registration** for the 3 new source families (`am_enforcement_detail`, `am_amendment_diff`, `am_compat_matrix`) → Athena join surface for cross-source queries (Wave 95+).
3. **Cross-corpus search benchmark** — once PM8 + PM9 + PM10 outputs all drain (already done) + PM11 lands, run a per-query cross-corpus search benchmark against the unified embedding substrate. This is the next strategic step framed in PM10 §followups #4.
4. **`am_amount_condition` data quality re-validation** before any embed run (current data is majority template-default from a broken ETL).
5. **Route B (corpus re-export delta)** — schedule after the next monthly NTA bulk landing (1st-of-month 03:00 JST cron) so that invoice_registrants delta is real.

---

## 8. Compliance gates verified

- READ-ONLY AWS only: **yes** (all `list-*` / `get-*` calls, zero `create-*` / `terminate-*`).
- `live_aws_commands_allowed=false`: **yes**, plan-only doc.
- `$19,490` never-reach: **yes**, current $0.02 → 99.9999% headroom.
- `[lane:solo]` marker: **yes**, header.
- `Co-Authored-By: Claude Opus 4.7`: **yes**, commit message will include.
- No `--no-verify`: **yes**, `scripts/safe_commit.sh` rejects defensively (validated 2026-05-17 task #264).

---

**Status**: PM11 plan DRAFTED. Awaiting user explicit unlock + ETL precondition before any submit.

last_updated: 2026-05-17
