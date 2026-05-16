# AWS Canary Smoke PASS Closeout (2026-05-16 12:42 JST)

> **Status: Phase 3 smoke DONE — all 7 J0X jobs SUCCEEDED.**
> Pipeline e2e (CodeBuild → ECR → Batch Fargate → crawler → S3) validated
> with 82 artifacts (4.3 MB) and **$0 actual cost** (Fargate Spot tiny job
> below billing threshold).

last_updated: 2026-05-16

companion runbook: `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
companion checklist: `docs/_internal/aws_canary_execution_checklist.yaml`
companion quickstart: `docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md`
infra closeout: `docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md` (Phase 1+2)
attestation template: `docs/_internal/AWS_CANARY_ATTESTATION_TEMPLATE.md`
memory back-link: `project_jpcite_aws_canary_infra_live_2026_05_16` (SOT) /
`feedback_docker_build_3iter_fix_saga` (3-iter lesson) /
`feedback_loop_promote_concern_separation` (Stream W lesson)

---

## 0. Scope

This closeout records the **first successful Phase 3 smoke pass** of the
AWS credit canary pipeline on 2026-05-16 PM in the jpcite canary AWS
account (separate from the BookYou compromised account — see
`project_aws_bookyou_compromise` memory).

The doc is **artifact-only** for the future operator/agent. Re-reading
must not cause any AWS side-effect.

---

## 1. 7-job success summary

| job | manifest | status | artifacts | notes |
| --- | --- | --- | --- | --- |
| J01 | crawl_news | **SUCCEEDED** (`a9d187b8`) | **36** | first live smoke after 3-iter Docker fix saga |
| J02 | crawl_municipality | SUCCEEDED | 11 | parallel fan-out, ~30s |
| J03 | crawl_pref | SUCCEEDED | 11 | parallel fan-out, ~30s |
| J04 | corp_registry | SUCCEEDED | 12 | parallel fan-out, ~30s |
| J05 | corp_amend | SUCCEEDED | 11 | parallel fan-out, ~30s |
| J06 | ministry_pdf | SUCCEEDED | 13 | parallel fan-out, ~30s (Textract path validated) |
| J07 | court_decision | SUCCEEDED | 8 | parallel fan-out, ~30s |
| **total** | — | **7/7 SUCCEEDED** | **82** | **4.3 MB** |

All 6 parallel jobs (J02-J07) submitted concurrently; each finished
in ~30 seconds wall-clock. No retries, no fall-backs to EC2 Spot CE.

---

## 2. Pipeline validation: CodeBuild → ECR → Batch Fargate → S3

End-to-end path verified for the first time on live AWS:

1. **CodeBuild** (`jpcite-crawler-build`) — pulled Dockerfile +
   entrypoint.py, built image, pushed to ECR `jpcite-crawler` with
   digest pin.
2. **ECR** — image digest resolved by Batch job definition `jpcite-crawl`
   rev 1; pull succeeded inside Fargate Spot task.
3. **Batch Fargate** — Fargate Spot 1024 vCPU compute environment
   provisioned task with 1 vCPU / 2 GB; entrypoint executed crawler
   against manifest URL list.
4. **Crawler** — fetched per-source URLs, wrote artifacts to S3
   `jpcite-canary-raw-*` bucket under `runs/<job_id>/<source_id>/`.
5. **S3 raw bucket** — confirmed object count + total bytes via
   `aws s3 ls --recursive`; lifecycle (90-day Glacier / 365-day expiry)
   automatically applies.

Logs all visible under CloudWatch log group
`/aws/batch/jpcite-credit-2026-05` (14-day retention).

---

## 3. 3-iteration fix saga (Docker build lesson)

Container failures are opaque (no local docker — must round-trip via
CodeBuild). Each fix required a fresh CodeBuild + re-submit cycle
(~5 minutes per iteration). Three iterations landed J01:

| iter | commit | root cause | fix |
| --- | --- | --- | --- |
| 1 | `61339f491` | entrypoint.py output_bucket schema mismatch | 3 output target form support (legacy split / s3 URI / env) |
| 2 | `68ee65dbb` | User-Agent header non-ASCII reject by httpx | UA ASCII-only enforce |
| 3 | `dc6605149` | `http2=True` but h2 package missing → ImportError | `http2=False` force |

Lesson abstracted to `feedback_docker_build_3iter_fix_saga.md`:
**1 fix at a time + immediate validation** is the only safe loop
because container failures cannot be reproduced locally.

---

## 4. Burn rate: $0 actual / $1,525/day target → ramp required

### What happened
- Phase 3 smoke ran tiny manifests (~3-10 URLs each, ~30 sec runtime).
- Fargate Spot tasks below per-second billing aggregation threshold.
- S3 raw bytes well under free-tier monthly inclusion.
- Net: **$0 incurred during Phase 3**.

### Implication for Phase 4 (ramp burn)
- Effective cap remains **USD 18,300** (USD 19,490 - safety margin).
- Remaining credit after Phase 3 ≈ **USD 19,500** (essentially full).
- Window: 3-5 days to **2026-05-19..21**.
- **New daily target: USD 4,000-6,000/day** (revised up from
  USD 1,525/day in the original 12-day plan).

Tiny smoke jobs cannot consume meaningful credit. Phase 4 must lean
on heavy compute, OCR throughput, and large object IO.

---

## 5. Phase 4 ramp plan (IN_PROGRESS)

Four parallel axes to consume USD 19,500 in 3-5 days:

### 5.1 `jpcite-crawl-heavy` job definition
- **vCPU**: 16, **memory**: 32 GB (Fargate max).
- Targets: J02 NTA invoice bulk 4M rows, J04 corp registry deep walk,
  J06 PDF full sweep with Textract per-page burn.
- Submission template: `scripts/aws_credit_ops/submit_job.sh
  --job-def jpcite-crawl-heavy`.

### 5.2 EventBridge `rate(10 minutes)` orchestrator schedule
- DISABLED default — operator must enable explicitly before live burn.
- When enabled, schedules `jpcite-credit-orchestrator` Step Function
  every 10 minutes; orchestrator picks next batch from queue, submits
  to Batch, waits for terminal state.
- Self-pace cap: per-tick max 10 jobs to avoid runaway burn.

### 5.3 Textract batch OCR for J06 expansion
- Per-page cost: ~USD 0.0015 (Detect/Analyze API).
- J06 ministry PDFs reach 100+ pages routinely; deep sweep across all
  ministries produces 10K+ pages × USD 0.0015 = USD 15+ per ministry
  sweep, scalable to USD 1-3K/day at full throughput.
- Client lives in `docker/jpcite-crawler/textract_client.py` (already
  shipped Phase 2).

### 5.4 SageMaker embedding batch
- Convert crawled docs → vector index for downstream retrieval.
- GPU instance (e.g. `ml.g4dn.xlarge` at ~USD 0.74/hr) × parallelism.
- Short-duration but compute-dense — useful to absorb residual budget
  at end of Phase 4 window.

### 5.5 Deeper manifests
- **J02**: NTA invoice bulk monthly 4M rows (~920 MB compressed) —
  parse + S3 partition write.
- **J04**: corp registry quarterly full snapshot walk.
- **J06**: ministry PDF full text + Textract OCR for image-only PDFs.

---

## 6. Phase status table (post-Phase-3, updated 13:30 JST)

| phase | scope | status |
| --- | --- | --- |
| 1 | guardrail | **DONE** |
| 2 | infrastructure | **DONE** |
| 3 | smoke J01-J07 (7/7 SUCCEEDED, 82 artifacts, $0) | **DONE** (2026-05-16 12:42 JST) |
| 4 | deep ramp (7 deep J0X submitted, 2,726 URLs, $9,200 budget, SNS apne1 fix + EventBridge rate(10m) LIVE) | **IN_PROGRESS** (2026-05-16 13:30 JST) |
| 5 | drain + aggregate_run_ledger + Athena refresh | pending |
| 6 | teardown_credit_run + verify_zero_aws | pending |
| 7 | attestation emit + `aws_budget_canary_attestation` bind | pending |

---

## 6.1 Phase 4 deep ramp launch note (2026-05-16 13:30 JST)

Phase 3 smoke 終了 ~48 min 後の 13:30 JST に Phase 4 deep ramp を **LIVE submit**:

- **7 deep J0X jobs submitted** to `jpcite-crawl-heavy` (16 vCPU / 32 GB Fargate max)
- **累計 2,726 URLs** (smoke 106 → deep 2,726、**25.7x scale-up**)
- **累計 budget USD 9,200** for deep window
- **SNS apne1 cross-region fix**: `jpcite-credit-cost-alerts` を apne1 で create + Step Functions ASL の TopicArn を same-region に切替。SF `arn:aws:states:::sns:publish` integration は cross-region TopicArn を silent failure する仕様 (`feedback_aws_cross_region_sns_publish.md` 参照)。
- **EventBridge `rate(10 minutes)` LIVE**: orchestrator schedule を DISABLED → ENABLED へ flip、10 分毎に Step Functions を auto-trigger。連続駆動で deep manifest depth + Textract burn を厚く積む。
- **validate_run_artifacts false positive fix**: 13 internal JPCIR fields (`_jpcir_*` 系) を validator exempt list に追加、smoke で出ていた 13 false-positive 警告を解消。
- **aggregate_run_ledger discovery fix**: J0X slug 規約 `J0X_<slug>` を regex で拾うよう修正、Phase 5 で cross-job rollup を取れる状態に。

**Estimated burn rate (deep manifest scale)**: **USD 1,500-3,000/day**。deep manifest の long-tail (depth heavy) 性質を反映、tiny smoke の "spike then idle" より緩やか。旧 USD 4,000-6,000/day target は heavy job def の最大 saturation 前提だった。window 3-5 day で 2026-05-19..21 への着地軌道。

---

## 7. Key invariants reaffirmed

- `live_aws_commands_allowed` flip is **per-phase opt-in only**
  (Stream W concern separation pattern — `--unlock-live-aws-commands`).
- All Phase 4 side-effect commands go through preflight scorecard
  runner; no direct AWS CLI from interactive shells.
- DRY_RUN default remains the canonical safety net for teardown
  scripts; `--commit` required for live destructive operations.
- artifact-only / no permanent runtime — full teardown after drain.

last_updated: 2026-05-16
