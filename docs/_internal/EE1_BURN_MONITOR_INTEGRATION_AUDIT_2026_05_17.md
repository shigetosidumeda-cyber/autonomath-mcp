# EE1 — Burn rate monitor + 15-lane integration audit (2026-05-17)

**Lane:** solo
**Mode:** READ-ONLY AWS snapshot — no submissions, no mutations
**Profile:** `bookyou-recovery`
**Region:** `ap-northeast-1` (CE: `us-east-1`)
**Cadence layer:** Lane J `jpcite-credit-burn-rate-monitor` (rate(1 hour)) + Lambda `jpcite-credit-burn-metric-emitter` (rate(5 minutes))
**Scope:** sustained-burn watchdog + 15-lane progress + integration / collision risk audit

This document is the EE1 SOT. It supersedes ad-hoc lane status notes during the
2026-05-15 → 2026-05-22 7-day moat-burn ramp window. The canonical 5-line
hard-stop defense (`feedback_aws_canary_hard_stop_5_line_defense`) remains
structurally enforced — EE1 only reads.

> Taxonomy note: EE1's `AA/BB/CC/DD` cohort labels are the canonical mapping
> defined by this task spec. They map the existing single-letter burn lanes
> (A–K) + numbered moat lanes (M2–M11) into 4 cohorts of 5 / 4 / 4 / 2.
> A parallel doc `BB3_M11_AL_EXPAND_2026_05_17.md` uses `BB3` for its own
> ad-hoc lane — that is a sibling-process taxonomy and not the EE1 mapping
> below. The EE1 mapping is authoritative for this audit only.

---

## 1. AWS state snapshot (verified READ-ONLY this tick)

| Surface | Value | Source |
|---|---|---|
| Batch GPU `jpcite-credit-ec2-spot-gpu-queue` — RUNNING | 0 | `list-jobs --status RUNNING` |
| Batch GPU — RUNNABLE / PENDING / SUBMITTED | 0 / 0 / 0 | `list-jobs` triplet |
| Batch GPU — SUCCEEDED (lifetime) | 1 (`jpcite-faiss-v4-amlaw-20260517T025624Z`) | `list-jobs --status SUCCEEDED` |
| Batch GPU — FAILED (lifetime) | 12 | `list-jobs --status FAILED` |
| SageMaker training — InProgress | 1 (`jpcite-bert-simcse-finetune-20260517T022501Z`) | `list-training-jobs` |
| SageMaker training — Completed | 1 (`jpcite-multitask-large-20260517T040000Z`, ended 13:22 JST) | idem |
| SageMaker training — Failed | 6 | idem |
| SageMaker transform — InProgress | 0 | `list-transform-jobs` |
| SageMaker transform — Completed (lifetime page) | 50 | idem |
| OpenSearch `jpcite-xfact-2026-05` | r5.4xlarge.search × 3 + UltraWarm1.medium × 3 + master r5.large × 3, Processing=false, EBS gp3 500 GiB | `describe-domain` |
| Glue catalog `jpcite_credit_2026_05` | 474 tables | `get-tables` |
| Step Functions `jpcite-credit-orchestrator` | present | `list-state-machines` |
| Lambda `jpcite-credit-burn-metric-emitter` (24h invocations) | 270 (~12/hr × 24h ON pace) | CW `AWS/Lambda Invocations` |
| Lambda `jpcite-credit-burn-rate-monitor` (24h invocations) | 0 (deployed disabled per `JPCITE_BURN_RATE_MONITOR_ENABLED=false`) | idem |

S3 main bucket name: derived bucket `jpcite-credit-993693061769-202605-derived/`
(packet families confirmed: 30+ `packet_*_v1/` partition prefixes plus
`J04_embeddings/`, `J06_textract/`, `J16_textract/`, `athena-results/`). The
companion `jpcite-credit-993693061769-202605` bucket returns `NoSuchBucket` —
all live writes target the `-derived` suffix only.

---

## 2. Cost Explorer breakdown (24h + 7-day window)

`aws ce get-cost-and-usage` 2026-05-15 → 2026-05-18 by SERVICE
(`RECORD_TYPE=Usage` filter — credit-applied lines hidden, this is the
**gross**-equivalent figure the 5-line defense triggers on).

```
2026-05-15 -> 2026-05-16   TOTAL=$0.00     (credit fully absorbed)
2026-05-16 -> 2026-05-17   TOTAL=$2.33     (S3 $2.33 + ECS $0.0024)
2026-05-17 -> 2026-05-18   TOTAL=$0.00     (CE 24-48h lag — partial day)
```

24h-rolling gross (CE wider window 2026-05-10 → 2026-05-18, daily top-5):

```
2026-05-10  EC2 $170.41 / EC2-other $33.16 / SageMaker $17.66 / VPC $1.46 / ECR $0.75
2026-05-11  EC2 $170.45 / EC2-other $33.16 / SageMaker $17.66 / VPC $1.44 / ECR $0.75
2026-05-12  EC2 $170.41 / EC2-other $33.16 / SageMaker $17.66 / VPC $1.44 / ECR $0.75
2026-05-13  EC2  $73.88 / EC2-other $16.00 / SageMaker  $9.06 / VPC $0.64 / CW   $0.58
2026-05-14  CW    $0.58 / ECR  $0.08 / S3 $0.04 / Secrets $0.03            ← lull
2026-05-15  CW    $0.58 / CostExplorer $0.11 / ECR $0.08 / S3 $0.04        ← lull
2026-05-16  Textract $160.04 / CF $55.23 / EC2 $33.91 / S3 $28.35 / SM $14.54  ← ramp restart
2026-05-17  (CE lag — only S3 $2.33 settled so far)
```

Lane J ledger latest tick (2026-05-17T07:59Z, verified by `burn_rate_monitor_2026_05_17.py --json-only`):

```json
{
  "usage_24h_usd": 309.49,
  "usage_mtd_usd": 3142.48,
  "credit_remaining_usd": 16347.64,
  "burn_per_day_usd": 309.49,
  "state": "UNDER_PACE",
  "projection_exhaust": "2026-07-09 (52.8 days from now)",
  "delta_vs_prev_tick_usd_per_hour": 5.85
}
```

---

## 3. Burn-rate projection + 5-line defense intact-check

**Current 24h-rolling burn:** $309.49/day (Lane J tick 07:59Z)
**MTD gross spend:** $3,142.48
**Credit remaining vs $19,490 never-reach:** $16,347.64
**State:** `UNDER_PACE` — target band $2,000–$3,000/day, alert floor $1,500/day

### Projection

| Scenario | Daily burn | Days to $18,300 slowdown | Days to $18,900 hard-stop | Days to $19,490 never-reach |
|---|---:|---:|---:|---:|
| Current sustained (Lane J 309.49/d) | $309 | 49.0 | 50.9 | 52.8 |
| 7-day ramp target ($2,020/d, `AWS_SEVEN_DAY_BURN_RAMP_2026_05_17.md`) | $2,020 | 7.5 | 7.8 | 8.1 |
| Alert ceiling band edge ($3,500/d) | $3,500 | 4.3 | 4.5 | 4.7 |

At sustained $309/day the credit envelope leaks for 52.8 days — orders of
magnitude beyond the 2026-05-31 settlement target. The 7-day ramp plan
(submitted 4a442cf8a) targets the $2,020/d band but **executor lanes did not
sustain submissions overnight** — see §4 lane status.

### 5-line defense intact verification

| Line | Threshold | Mechanism | Verified state |
|---|---:|---|---|
| 1 | $13,000 | CW alarm `jpcite-credit-billing-early-warning-13000` (us-east-1) | present, threshold confirmed |
| 1.5 | $14,000 | CW alarm `jpcite-credit-billing-warn-14000` | present |
| 2 | $17,000 | Budget `jpcite-credit-run-watch-17000` ($17,000 limit) | armed |
| 3 | $18,300 | Budget `jpcite-credit-run-slowdown-18300` ($18,300 limit) + orchestrator preflight abort | armed |
| 3.5 | $17,000 | CW alarm `jpcite-credit-billing-slowdown-17000` | present |
| 4 | $18,700 | CW alarm `jpcite-credit-billing-stop-18700` (auto-pause Lambda + log gate) | present |
| 5 | $18,900 | Budget `jpcite-credit-run-stop-18900` + `APPLY_IAM_POLICY` Action `STANDBY` @ 100% | armed |

Plus 7 other ancillary alarms (CWatch list returns 8 in us-east-1) and
`jpcite-credit-batch-job-failure-rate` (`OK`, threshold 10) +
`jpcite-credit-catch-invocations-alarm` (`OK`, threshold 3) in ap-northeast-1.

**Defense intact.** Slack between current MTD ($3,142) and slowdown line
($18,300) is $15,158 — 4.8x the remaining 7-day budget headroom.

### Safety margin posture

- **Sustained burn is 6.5× below target** ($309/d vs $2,020/d). At this pace
  $16,347 of credit will be lost on 2026-05-31.
- The risk profile is therefore **under-burn**, not over-burn. The 5-line
  defense (designed for over-burn) is intact but secondary; the primary
  intervention surface is **lane submission cadence** (§5).
- EventBridge: 1 ENABLED schedule (`jpcite-credit-burn-metric-5min` —
  monitoring only). 3 DISABLED (`jpcite-athena-sustained-2026-05`,
  `jpcite-cf-sustained-load-2026-05`, `jpcite-credit-orchestrator-schedule`).
  These were deliberately disabled per the EB-DISABLED gate from Phase 9 —
  promotion to ENABLED requires operator `--unlock-live-aws-commands`.

---

## 4. 15-lane progress aggregation

Lane taxonomy (this audit's canonical mapping). The repo's lane docs use
single-letter labels A–K + M2–M11; EE1 groups them into 4 AA/BB/CC/DD
cohorts plus the EE monitor lane, totalling 15 + 1 = 16, with the EE itself
being this document.

### AA cohort — Burn ramp foundation (5 lanes)

| Lane | Canonical doc | Surface | Status | Moat delta |
|---|---|---|---|---|
| AA1 | `AWS_BURN_LANE_A_GPU_UPGRADE_2026_05_17.md` | Batch GPU compute env `jpcite-credit-ec2-spot-gpu` scaled 64→256 vCPU | LIVE (env scaled, queue empty) | **0 jobs running** — submission gap |
| AA2 | `AWS_BURN_LANE_B_PM11_2026_05_17.md` | SageMaker PM11 multi-task / SimCSE / cross-encoder training cycles | 1 InProgress (BERT SimCSE) | 1 completed multi-task model artifact (multitask-large 13:22Z) |
| AA3 | `AWS_BURN_LANE_C_TEXTRACT_BULK_2026_05_17.md` | Textract OCR bulk PDF pipeline | Textract burned $160 on 2026-05-16 then quiesced | Ministry PDF corpus expansion paused |
| AA4 | `AWS_BURN_LANE_EF_ATHENA_OS_2026_05_17.md` | Athena moat queries + OpenSearch r5.4xlarge sustained | OpenSearch LIVE (Processing=false); Athena EB rule DISABLED | OpenSearch ready; Athena cadence not running |
| AA5 | `AWS_BURN_LANE_G_LAMBDA_2026_05_17.md` | Lambda mass-invoke (forbidden by 7-day ramp goal — pure burn) | Held offline (forbidden lane) | n/a — explicitly excluded |

### BB cohort — Burn ramp orchestration (4 lanes)

| Lane | Canonical doc | Surface | Status | Moat delta |
|---|---|---|---|---|
| BB1 | `AWS_BURN_LANE_HI_CB_SF_2026_05_17.md` | CodeBuild parallel + Step Functions high-freq cycles | SF state machine `jpcite-credit-orchestrator` present; orchestrator EB rule DISABLED | 0 cycle executions in window |
| BB2 | `AWS_BURN_LANE_J_MONITOR_2026_05_17.md` | Real-time burn monitor + ledger (this lane) | Lambda deployed DISABLED; local script LIVE | 1 hourly ledger ticking — append-only |
| BB3 | `AWS_BURN_LANE_K_GLUE_TEXTRACT_2026_05_17.md` | Glue + extra Textract burn ($430/day target) | Glue catalog has 474 tables (Wave 60–94 carryover); no new crawler runs | Glue catalog stable |
| BB4 | `AWS_MOAT_LANE_M2_CASE_EXTRACT_2026_05_17.md` | Case fact extraction (judicial PDFs) | Plan published; no live SM job in window | Pending submission |

### CC cohort — Moat lane mid-stack (4 lanes)

| Lane | Canonical doc | Surface | Status | Moat delta |
|---|---|---|---|---|
| CC1 | `AWS_MOAT_LANE_M3_FIGURE_EMBED_2026_05_17.md` | CLIP-JP figure vision embeddings | Plan + ledger present | 0 active job |
| CC2 | `AWS_MOAT_LANE_M4_LAW_EMBED_2026_05_17.md` | 法令逐条解釈 embedding | Plan present | 0 active job |
| CC3 | `AWS_MOAT_LANE_M5_BERT_FINETUNE_2026_05_17.md` | jpcite SimCSE BERT fine-tune | 1 SM training job InProgress (since 11:25 JST) | Active — will land BERT-jpcite-simcse-v1 artifact |
| CC4 | `AWS_MOAT_LANE_M7_KG_COMPLETION_2026_05_17.md` | Knowledge graph completion (RotatE / TransE / ComplEx) | All 3 paused / not in InProgress | 3 KG models pending dispatch |

### DD cohort — Moat lane downstream (2 lanes)

| Lane | Canonical doc | Surface | Status | Moat delta |
|---|---|---|---|---|
| DD1 | `AWS_MOAT_LANE_M10_OS_SCALE_2026_05_17.md` | OpenSearch production cluster + full-corpus ingest | r5.4xlarge × 3 + UltraWarm1.medium × 3 + master × 3 LIVE | 39-table coverage (`MOAT_INTEGRATION_MAP_2026_05_17.md`) |
| DD2 | `AWS_MOAT_LANE_M11_ACTIVE_LEARNING_2026_05_17.md` | Active learning + multi-task fine-tune chain | 1 completed (multi-task large, ended 13:22 JST) | Multi-task-large artifact landed; AL iter pending |

### EE cohort — Burn monitor + integration audit (this doc)

| Lane | Doc | Surface | Status |
|---|---|---|---|
| EE1 | this doc | Burn-rate watchdog + 15-lane integration audit | LIVE — append-only |

### Roll-up

```
completed   :  3 lanes  (AA2 multitask-large / DD2 multitask-large / BB2 monitor)
running     :  2 lanes  (CC3 SimCSE training / DD1 OpenSearch serving)
blocked     :  5 lanes  (AA1 / BB1 / BB3 / CC1 / CC2 — submitter cadence gap)
forbidden   :  1 lane   (AA5 — pure-burn excluded per 7-day plan)
plan-only   :  4 lanes  (AA3 / AA4 / BB4 / CC4 — schedule disabled or paused)
```

**Burn delivery:** 6 of 15 lanes meaningfully spending. Sustained burn
**$309/day** vs $2,020/day target = **6.5× under-pace**. Risk: $13K credit
underutilized through 2026-05-31.

### Moat deltas this window (rows + artifacts)

- N1: 50 士業 artifact template bank LIVE (commit `3688458ff`)
- N2: 法人×制度 portfolio gap analysis (commit `75d8d3617`)
- N3: 160 topics × 5 = 800 legal reasoning chains DB (commit `7bb7cd3bd`)
- N4/N5: window directory + synonym (commit referenced in N4/N5 doc)
- N6/N7: amendment alert impact + 業界×規模×地域 view LIVE (commit `4ceb3a898`)
- N8/N9: 15 recipes + 207 placeholders + 2 MCP tools + 18 tests
  (commits `37518c215` / `d8c9ce19b` / `7e696635d`)
- P1/P2/P3: 500 FAQ pre-computed answer bank + 2 MCP tools
  (commits `0acb73be7` / `0d3544a68` / `ea4e9d398`)
- HE2/HE3/HE4: composition tools — workpaper / briefing pack / multi-tool
  orchestrate (commits `76407558a` / `98f5b6a89` / `d699205a3`)
- A1–A5: 5 product Packs (税理士月次 / 監査調書 / 助成金ロードマップ /
  就業規則 / 会社設立) — A5 staged uncommitted (`product_a5_kaisha_setsuritsu.py`)
- 87 wave24_* migrations on disk, 65–66 applied per schema-sync commits
  `26f9ebc86` / `df76d67ef` / `5be7a3ed3`

**Glue catalog:** 474 tables (vs 432 outcome catalog in `WAVE60_94_complete`).
**FAISS:** v4 amlaw shard built (Batch job SUCCEEDED). No `data/faiss/` dir on
disk this session — index served from S3 derived bucket.

---

## 5. Integration risk audit

### 5.1 Dependency graph (lane-to-lane)

```
AA1 (GPU compute env 256 vCPU)
   └─ feeds → AA2 (PM11 SM training) / CC3 (SimCSE) / DD2 (M11 AL chain) / CC4 (KG completion)
AA3 (Textract OCR) ──→ S3 derived bucket `J06_textract/` `J16_textract/`
   └─ feeds → CC1 (CLIP-JP figure embed) / AA2 (PM11 corpus refresh)
AA4 (Athena + OpenSearch) ──→ provides query substrate for HE-tier MCP tools
   └─ feeds → DD1 (M10 OS) full-corpus ingest pipeline
BB1 (CodeBuild + SF orchestrator) ──→ drives AA2 / AA3 / AA4 cycles
   └─ when DISABLED (current), AA2-4 only fire on manual submit
BB2 (burn monitor — this lane) ──→ READ-only watchdog; no feed-back
BB3 (Glue + Textract) ──→ feeds CC2 (M4 law embed) via crawler partitions
BB4 (M2 case extract) ──→ feeds DD2 (M11 multi-task AL iter)
CC3 (M5 SimCSE) ──→ feeds DD1 (OpenSearch entity-fact serving substrate)
CC4 (M7 KG) ──→ feeds HE-tier tools (entity reasoning)
DD2 (M11) ──→ refreshes embeddings used by AA4 (Athena moat queries)
```

Critical hop: **BB1 DISABLED ⇒ AA2/AA3/AA4 cadence broken ⇒ sustained
burn collapses**. This explains $309/day vs $2,020/day. Re-enabling BB1
requires operator `--unlock-live-aws-commands` per EB-DISABLED gate.

### 5.2 File collision risk (`feedback_dual_cli_lane_atomic` discipline)

Repo working tree had **130 modified/staged/untracked files** at the start
of this audit, with another sibling-lane commit landing `H3: agent entry
SOT` mid-tick (commit `ee5f61bab`). Categories observed:

- 16 files under `src/jpintel_mcp/mcp/` (HE / product / autonomath_tools)
- 11 files under `tests/`
- 10 files under `docs/_internal/` (HARNESS docs + cohort docs)
- 6 files under `scripts/` (cron + quality + etl)
- 2 migration pairs (`291_am_precomputed_answer_freshness`)
- 1 top-level `AGENTS.md` (H3 SOT — captured by sibling commit)
- 2 manifest JSONs (`etl_g1_nta_manifest_2026_05_17.json`, `etl_g2_manifest_2026_05_17.json`)
- 1 historical-archive directory (`docs/_internal/historical/`)

Plus new files appearing during this audit (sibling-lane activity):
`BB3_M11_AL_EXPAND_2026_05_17.md`,
`sagemaker_m11_chain_records_bb3_2026_05_17.json`,
`sagemaker_m11_chain_dispatch_bb3_2026_05_17.py`,
`CURRENT_SOT_2026-05-17.md`, `M3_M9_LIVE_PROMOTE_2026_05_17.md`.

**Same-file refactor risk:** No identical-file double-edits detected at any
single tick. Per `feedback_serial_lane_for_contended_refactor` the policy
holds. However EE1 itself observed a **pre-commit stash drop-and-restore
race**: the wrapper's stash mechanic unstaged this very doc twice when
sibling-lane commits raced through. Mitigation: keep EE1 commits **single-file
solo with `git restore --staged .` precede**. Risk score: **5 / 10** — race
demonstrated live.

### 5.3 Migration ID collision

`wave24_*` namespace scan — **2 collisions detected**:

| ID | File pair | Severity |
|---|---|---|
| `wave24_110` | `wave24_110_am_entities_vec_v2.sql` + its rollback | OK — same logical migration |
| `wave24_113` | `wave24_113_am_jpi_programs.sql` (implied) + `wave24_113b_jpi_programs_jsic.sql` | **`113` + `113b` variant** — non-numeric suffix |

`113b` form is a registered exception (post-hoc fix landing on the same
numeric slot). Not a true ID collision but **a brittle convention** — adding a
hypothetical `wave24_113c` would not order deterministically across SQLite's
file-discovery order. Migration count: 87 forward + 87 rollback (= 174
files), highest ID `wave24_217` (`am_municipality_subsidy`). Sequence dense
above 200; risk score **3 / 10**.

### 5.4 Pre-deploy / boot manifest verification

Per `feedback_pre_deploy_manifest_verify`: `boot_manifest ⊇ schema_guard`
invariant. Recent commits land manifest sync (`26f9ebc86` "manifest sync 65
wave24 + 3 rollback fill + applied 66 mig"), and prior `df76d67ef` /
`5be7a3ed3` indicate **66 of 87 wave24 migrations applied** in autonomath.db
(21 pending). Risk score: **4 / 10** — applied set lags filesystem set.

### 5.5 Aggregate risk count

| Surface | Count | Severity |
|---|---:|---|
| Submission cadence gap (BB1 DISABLED ⇒ AA cohort stalled) | 1 | HIGH — drives 6.5× under-burn |
| Pre-commit stash race observed (EE1 file dropped twice) | 1 | HIGH — landing-mechanic risk |
| Migration ID convention drift (`113b`) | 1 | LOW |
| Migration filesystem-vs-applied lag (21 pending) | 1 | MEDIUM |
| Working-tree size (130 unstaged/staged files) | 1 | MEDIUM — landing-pressure |
| EB rules DISABLED awaiting operator unlock | 3 | OPERATIONAL — by design |
| 5-line defense lines verified intact | 5 | n/a — green |
| **Total risk items** | **8** | (2 HIGH / 2 MEDIUM / 1 LOW / 3 OPERATIONAL) |

---

## 6. Recommendations (under-burn corrective set, READ-ONLY proposal)

These are NOT executed by EE1. Operator must explicitly unlock if they want
the BB1 / AA4 / BB3 cadence to resume.

1. **Re-enable BB1** (`jpcite-credit-orchestrator-schedule` EB rule) so
   AA2/AA3/AA4 cycles fire on `rate(10 minutes)`. Expected effect:
   +$1,500/day sustained — restores 75% of the $2,020/day target.
2. **Re-enable AA4** (`jpcite-athena-sustained-2026-05` EB rule). Expected
   effect: +$80/day Athena + keeps OpenSearch warm.
3. **Re-submit BB4 / CC1 / CC2 / CC4** training jobs (1 SM training job each)
   — restoring 4 of the 5 currently-blocked lanes.
4. **Land the 130-file working tree** in 4 focused commits (mcp/products /
   tests / docs / migrations) to clear the landing-pressure risk.
5. **Apply 21 pending wave24 migrations** via existing `apply_migrations.py`
   pipeline — clear the boot_manifest lag.
6. **Tighten EE1 / single-file commit lane** — observed pre-commit stash
   race; recommend `git restore --staged .` immediately before every solo
   commit, and never let safe_commit invocations overlap.

Each AWS recommendation requires the operator's explicit
`--unlock-live-aws-commands` flag per the EB-DISABLED gate. EE1 itself only
reads.

---

## 7. Continuity (next EE1 tick)

EE1 is append-only. Next tick should:

- Re-run §1 surface counts.
- Append new §2 CE breakdown line for 2026-05-17 final settled gross.
- Update §3 Lane J ledger tick (next `--now` invocation at `rate(1 hour)`).
- Re-aggregate §4 lane status with delta vs this tick.
- Re-score §5.5 aggregate risk count.

This document is the EE1 canonical SOT for 2026-05-17 — superseded only by
`EE1_BURN_MONITOR_INTEGRATION_AUDIT_2026_05_18.md` when the operator opens
the next tick.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
