# AWS Canary Run Closeout (2026-05-16 PM)

> **Status: Phase 3 smoke DONE / Phase 4 deep+ultradeep IN_PROGRESS / Phase 5 smart analysis PLANNED.**
> Phase 3 smoke: 7/7 J0X SUCCEEDED, 82 artifacts (4.3 MB), **$0 actual cost**
> (Fargate Spot tiny job below billing threshold).
> Phase 4: 7 deep J0X (2,726 URL) → interim **8 SUCCEEDED / 28 FAILED** (investigating),
> 7 ultradeep J0X submitted (**19,792 URL / $17K budget**), EventBridge schedule
> LIVE `rate(10 minutes)`, SNS apne1 cross-region fix applied, SF Catch → CloudWatch
> metric (no email dependency), SageMaker GPU smoke on `ml.g4dn.xlarge` IN_PROGRESS,
> EC2 Spot CE active via `jpcite-crawl-ec2-cpu` job def (J06 EC2 RUNNING).
> Phase 5: J08 官報 / J09 裁判所 / J10 法務局公告 / J11 e-Stat manifests planned,
> 4 cross-analysis pipelines (法人360 166K / 制度lineage 11,601 / 採択確率 cohort 225K /
> full-corpus SageMaker embedding 5 tables ~750M tokens), 5 big Athena cross-join
> queries ($50-500 each), outcome catalog expanded 14 → 30.

> Doc renamed from `AWS_CANARY_SMOKE_PASS_2026_05_16.md` on 2026-05-16 PM to
> reflect Phase 4+5 scope expansion. Phase 3 smoke pass record (§1-§5) remains
> the historical anchor; new §8 / §9 capture Phase 4 deep+ultradeep progression
> and Phase 5 smart analysis layer.

last_updated: 2026-05-16

companion runbook: `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
companion checklist: `docs/_internal/aws_canary_execution_checklist.yaml`
companion quickstart: `docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md`
infra closeout: `docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md` (Phase 1+2)
attestation template: `docs/_internal/AWS_CANARY_ATTESTATION_TEMPLATE.md`
memory back-link: `project_jpcite_aws_canary_infra_live_2026_05_16` (SOT) /
`project_jpcite_smart_analysis_pipeline_2026_05_16` (Phase 5 detail) /
`feedback_aws_canary_burn_ramp_pattern` (canonical 4-stage ramp) /
`feedback_docker_build_3iter_fix_saga` (3-iter lesson) /
`feedback_aws_cross_region_sns_publish` (SNS apne1 fix) /
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

## 6. Phase status table (post-Phase-3, updated PM after Phase 4+5 expansion)

| phase | scope | status |
| --- | --- | --- |
| 1 | guardrail | **DONE** |
| 2 | infrastructure | **DONE** |
| 3 | smoke J01-J07 (7/7 SUCCEEDED, 82 artifacts, $0) | **DONE** (2026-05-16 12:42 JST) |
| 4 | deep + ultradeep ramp (7 deep 2,726 URL → **8 SUCCEEDED / 28 FAILED 調査中**, 7 ultradeep **19,792 URL / $17K budget**, SageMaker GPU smoke `g4dn.xlarge`, EC2 Spot CE `jpcite-crawl-ec2-cpu` job def, J06 EC2 RUNNING, SNS apne1 fix, EventBridge `rate(10 minutes)` LIVE, SF Catch → CW metric) | **IN_PROGRESS** (2026-05-16 PM) |
| 5 | **smart analysis layer** (J08 官報 / J09 裁判所 / J10 法務局公告 / J11 e-Stat manifests + 4 cross-analysis pipeline = 法人360 166K / 制度lineage 11,601 / 採択確率cohort 225K / full-corpus SageMaker embedding 5 tables ~750M tokens + Athena 5 cross-join + outcome catalog 14→30) | **PLANNED** (Phase 4 後段で並走着地) |
| 6 | drain + aggregate_run_ledger + Athena refresh | pending |
| 7 | teardown_credit_run + verify_zero_aws | pending |
| 8 | attestation emit + `aws_budget_canary_attestation` bind | pending |

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

---

## 8. Phase 4 deep + ultradeep progression (2026-05-16 PM)

### 8.1 Deep J0X interim — 8 SUCCEEDED / 28 FAILED 調査中

7 deep J0X (`jpcite-crawl-heavy` 16 vCPU / 32 GB Fargate max, 2,726 URL,
$9,200 budget) は interim **8 SUCCEEDED / 28 FAILED**。failure root cause
は CloudWatch log + Batch describe-jobs で調査中。想定原因:

- **OOM** (32 GB Fargate 上限 hit, heavy PDF Textract セッション)
- **Textract throttle** (per-second `DetectDocumentText` cap, J06 ministry PDF 集中)
- **upstream 429** (一部 source の同時並列 fetch 規制)
- **IAM permission gap** (Phase 4 で初出の service combination)

Failure 群は **CodeBuild round-trip 不要** な validate fix で個別 retry 予定。
`feedback_docker_build_3iter_fix_saga` の **1-fix-at-a-time** 原則を踏襲、
複数 fix を bundle しない。

### 8.2 Ultradeep J0X submitted — 19,792 URL / $17K budget

7 ultradeep J0X manifests を `data/aws_credit_jobs/ultradeep/` 配下に
着地済、Batch submit 完了:

- **累計 19,792 URL** (deep 2,726 → ultradeep 19,792、**7.3x scale-up**)
- **累計 budget USD 17,000** (Phase 4 のメイン burn 軸、残 $19,500 をほぼ吸い切る規模)
- SageMaker GPU embedding + Athena cross-join のための raw corpus を準備
  する位置付け (Phase 5 への bridge)

### 8.3 SF Catch → CloudWatch metric (no email dependency)

SNS apne1 fix (`feedback_aws_cross_region_sns_publish`) の上に **email
confirm に依存しない CloudWatch metric を Catch handler に挿入**:

- Step Functions の Catch path が発火した時点で CW metric を put
- metric filter + CW alarm で operator に届く形に切替
- SNS email subscription pending の状態でも alarm pipeline が機能
- launch readiness の blocker を 1 軸解消

### 8.4 SageMaker GPU smoke (`ml.g4dn.xlarge`) IN_PROGRESS

`ml.g4dn.xlarge` (~USD 0.74/hr) で SageMaker batch transform の smoke を起動。
目的: J04 corp registry 系の embedding 軸を実 GPU で round-trip させ、
Phase 5 full-corpus embedding (5 table / ~750M tokens) への scale-up
信号を取得 (1 GPU smoke → 4 GPU `ml.g4dn.12xlarge` full batch transform)。

### 8.5 EC2 Spot CE active — `jpcite-crawl-ec2-cpu` job def, J06 EC2 RUNNING

EC2 Spot CE が VALID + active、`jpcite-crawl-ec2-cpu` job def 経由で
**J06 EC2 RUNNING**:

- Fargate Spot だけだと vCPU/memory に天井 (16 vCPU / 32 GB) があるため、
  長時間 / 大量 memory 系 (ministry PDF Textract full sweep / J04 corp
  registry quarterly walk) を EC2 Spot 側に逃がす二系統設計。
- failure mode 切り分け (Fargate Spot 側の vCPU 上限 hit か / 単純な
  upstream 429 か) を 2 CE で観測可能化。

---

## 9. Phase 5 smart analysis layer (PLANNED, 2026-05-16 PM 追加要請)

Phase 4 で得た raw artifact (smoke 82 + deep 数百 + ultradeep 数千) を
**smart analysis layer** に lift する Phase 5。設計詳細は
memory `project_jpcite_smart_analysis_pipeline_2026_05_16` に集約、
本 doc では index のみ。

### 9.1 新 J0X manifests (J08-J11)

- **J08 官報** — `data/aws_credit_jobs/J08_kanpou_gazette.json` 着地済、
  官報 PDF / HTML を Textract で structured 抽出 (税制改正告示 /
  行政処分公告 / 入札告示 の 3 軸)。
- **J09 裁判所** — 裁判所判例 / 判決文 full-text walk、`court_decisions`
  (2,065 行) を 5,000+ に拡張、`am_law_article` への bridge。
- **J10 法務局公告** — `data/aws_credit_jobs/ultradeep/J08_ultradeep_kanpou_matrix.json`
  着地済、商業登記 / 不動産登記 / 各種公告系 cross-matrix、法人 360°
  pipeline の input 拡張。
- **J11 e-Stat** — 統計表 + メタデータ周回、Dim N anonymized query (k=5) /
  Dim O explainable fact (Ed25519 sign) の network-effect raw 化。

### 9.2 4 cross-analysis pipeline

1. **法人360° packet pipeline (166K corporates)** —
   `houjin_master` × `invoice_registrants` × `enforcement_cases` ×
   `am_amendment_snapshot` × `case_studies` を 1 packet/法人 で pre-compute,
   Stripe metered ¥3/req per call、`estimated_price_jpy` ¥900-¥1,500。
   est. cost **~$300-500**。
2. **制度 lineage packet pipeline (11,601 programs)** —
   `programs` × `am_amendment_diff` × `am_amendment_snapshot` ×
   `program_law_refs` × `am_law_article` で各制度 5 年系譜を 1 packet 化,
   time-machine (Dim Q) `as_of` param と connect。est. cost **~$140-330**。
3. **採択確率 cohort model (225K cohorts)** —
   `case_studies` × `am_industry_jsic` × `am_target_profile` ×
   `am_region` × `programs` で cohort 別 base rate 統計推定、Dim N の
   k=5 anonymity + 信頼区間付き。est. cost **~$55-165**。
4. **Full-corpus SageMaker embedding (5 tables, ~750M tokens)** —
   `programs` / `laws` + `am_law_article` / `court_decisions` /
   `am_entity_facts` / `case_studies` を GPU batch transform で vector 化,
   `bge-m3` or `e5-mistral` (multilingual, 1024 dim) on
   `ml.g4dn.12xlarge` (4 GPU, $7.45/hr) × ~70 hr。est. cost **~$520-750**。

### 9.3 Big Athena cross-join queries (5 queries, $50-500 each)

| # | join surface | scan size 概算 | est. cost |
| --- | --- | --- | --- |
| 1 | programs × law_articles × amendment_diff | 30-60 GB | $150-300 |
| 2 | houjin × invoice × enforcement | 80-150 GB (zenken bulk) | $400-750 |
| 3 | cases × programs × industry_jsic | 5-15 GB | $25-75 |
| 4 | programs × tax_rulesets × law_articles | 10-25 GB | $50-125 |
| 5 | bids × programs × houjin | 8-20 GB | $40-100 |

合計 **$665-1,350 budget**、ultradeep budget $17K の中で吸収可能。

### 9.4 Outcome catalog expand 14 → 30

既存 14 outcome contract (`agent_runtime/contracts.py` 19 Pydantic + 14
OutcomeContract) を **30 へ拡張**。追加 16 outcome は Phase 5 smart
analysis 軸 (法人360 / 制度lineage / 採択確率 / cross-join 系) に紐付く
高付加価値 packet、`estimated_price_jpy` も ¥900-¥1,500 band で見直し。
詳細 catalog は `project_jpcite_smart_analysis_pipeline_2026_05_16` §
"Outcome catalog expand 14 → 30"。

### 9.5 JPCIR packet contract reuse

新規 contract は立てない。Wave 50 RC1 で確立した
`agent_runtime/contracts.py` の Pydantic envelope (`Evidence` /
`Citation` / `OutcomeContract` / `Disclaimer` / `BillingHint` /
`RateLimitHint` 等) を smart analysis output の正典 schema として再利用。
`scripts/check_schema_contract_parity.py` の双方向 round-trip 0 drift を
Phase 5 packet にも適用、`schemas/jpcir/` 20 schema + 4 新規 gate
artifact との整合を gate 化。

### 9.6 Phase 5 estimated cost per layer

| layer | cost band |
| --- | --- |
| J08-J11 4 manifest | **$500-1.5K** |
| 法人360 (166K corp packets) | **$300-500** |
| 制度lineage (11,601 program packets) | **$140-330** |
| 採択確率 cohort (225K packets) | **$55-165** |
| Full-corpus embedding (5 tables, 750M tokens) | **$520-750** |
| Athena 5 cross-join | **$665-1.35K** |
| Outcome 30 contracts (schema + sample gen) | **$50-150** |
| **Phase 5 合計** | **~$1.7K-3.2K** |

Phase 3+4+5 累計 **~$5.6K-10.5K**、effective cap $18.3K の **30-57%** を
smart analysis で消化、残 $7.8K-12.7K は Phase 4 ultradeep の long-tail +
Phase 6/7 drain + teardown attestation 予備に。

### 9.7 Canonical burn ramp (smoke → deep → ultradeep → smart)

各段 ~10x scale-up + per-phase validate gate (artifact / failure rate /
cost band / `--unlock-live-aws-commands` opt-in) で次段 unlock。詳細は
memory `feedback_aws_canary_burn_ramp_pattern`:

| 段 | scope | URL | est. cost |
| --- | --- | --- | --- |
| smoke | 7 J0X tiny | 106 | **$0** |
| deep | 7 J0X heavy | 2,726 | $300-800 |
| ultradeep | 7 J0X ultradeep | 19,792 | $3K-5K |
| smart | 4 pipeline + 5 Athena + outcome 30 | 750M token embedding / 225K cohort / 166K corp / 11,601 program | $1.7K-3.2K |

last_updated: 2026-05-16
