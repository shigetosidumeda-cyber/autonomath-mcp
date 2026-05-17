---
historical: true
superseded_by: site/releases/rc1-p0-bootstrap/preflight_scorecard.json (as of 2026-05-17T03:11:48Z)
canonical_live_state: site/releases/rc1-p0-bootstrap/preflight_scorecard.json
---

# AWS Canary Run Closeout (2026-05-16 PM, Phase 1-7 LANDED + Phase 8 IN_PROGRESS)

> **Historical snapshot — 2026-05-16 PM cut.** Live phase/state values drift; **always read**
> `site/releases/rc1-p0-bootstrap/preflight_scorecard.json` for the canonical SOT.
> Status at this snapshot: Phase 1-7 LANDED / Phase 8 ramp IN_PROGRESS.
> Phase 3 smoke: 7/7 J0X SUCCEEDED, 82 artifacts (4.3 MB), **$0 actual cost**
> (Fargate Spot tiny job below billing threshold).
> Phase 4 (deep + ultradeep, 2026-05-16 13:30 JST): 7 deep J0X (2,726 URL) +
> 7 ultradeep J0X (19,792 URL) + EventBridge schedule LIVE `rate(10 minutes)` +
> SNS apne1 cross-region fix + SF Catch → CloudWatch metric (no email
> dependency) + SageMaker GPU smoke on `ml.g4dn.xlarge` + EC2 Spot CE active
> via `jpcite-crawl-ec2-cpu` job def.
> Phase 5 (smart analysis, 2026-05-16 14:00 JST): J08-J16 manifests
> (官報 / 裁判所 / 法務局 / e-Stat / 議事録 / EDINET XBRL / JPO 公報 / 環境省 /
> canonical 公的 PDF) + 8 packet pipeline sharding ready (法人360 166K [86,849
> packets local gen 33 sec landing] / 制度lineage 11,601 / 採択確率 cohort 225K +
> 5 Wave 53 generators) + ETL raw → derived Parquet executed (**3 Glue table /
> 47 partitions / 1,029 source_receipts** in Athena) + 5 big Athena cross-join
> queries + outcome catalog **14 → 30 → 52** + 30 sample HTML at site/packets/
> + 6 SageMaker batch transform jobs.
> Phase 6 (cost burn ramp, 2026-05-16 16:00 JST): **J16 PDF Textract live run**
> (200+ canonical 一次資料 PDF URL) + **EC2 Spot GPU sustained burn**
> (FAISS / fine-tune) + **CloudFront mirror + bandwidth load test** +
> **Athena real burn** (3 packet tables + 16 Wave 53 tables + 3 new big queries:
> cross_packet / time_series / entity_resolution_full) + Wave 53.3 + Wave 54
> FULL-SCALE 36 generator packets to S3.
> Phase 7 (hard-stop 5-line defense ARMED, 2026-05-16 PM): CW $14K warn +
> Budget $17K alert + Budget $18.3K slowdown + CW $18.7K **Lambda direct stop**
> (`JPCITE_AUTO_STOP_ENABLED=true`) + Budget Action **$18.9K deny IAM**
> STANDBY + $590 margin + teardown scripts line 0 READY. **$19,490 never
> reach 設計**, Cost Explorer 8-12hr lag を CW alarm seconds latency で吸収。
> Phase 8 (ramp IN_PROGRESS, 2026-05-16 PM): **Wave 55 10 cross-3-source
> packets** (catalog 52→62 in flight) + **Mega Athena 39 table cross-join**
> ($2.5K-$5K burn 想定) + **Long-running EC2 GPU 6 jobs × 20h sustained**
> (120 GPU-hour, $1.4K-$2.2K) + **CloudFront 5M req bandwidth burn**
> ($200-$500). 39 packet tables aggregate at Phase 8 close.

> Doc rewritten on 2026-05-16 PM to integrate Phase 6+7+8 scope expansion.
> §1-§5 = Phase 3 smoke historical anchor, §6-§9 = Phase 4-5 progression,
> §10 = Phase 6 cost burn ramp, §11 = Phase 7 hard-stop 5-line defense,
> §12 = Phase 8 ramp IN_PROGRESS.

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
   - **LANDED 2026-05-16** — full local generation + S3 sync 完了。
     `am_entities.record_kind='corporate_entity'` は 166,969 行だが、
     `json_extract(raw_json,'$.houjin_bangou') IS NOT NULL` は 87,093 行
     (残 79,876 行は raw_json に houjin_bangou 欠落、houjin_master ingest
     遅延と整合)。total_houjin=87,093 / packets_written=**86,849** /
     skipped_empty=244 / schema_errors=0 / coverage_score_mean=0.4714、
     bytes_total=**252,463,349 (~241 MB)**、S3 PUT cost~$0.43、
     elapsed=local 31s + S3 sync ~9m (64 並列)。S3 verify =
     `aws s3 ls s3://jpcite-credit-993693061769-202605-derived/houjin_360/`
     → 86,849 objects, 252,463,349 bytes。AWS Batch shard 化 (167 shard ×
     1,000 row) は不要、local single-host で完走可と確定。run manifest +
     credit_run_ledger は `out/houjin_360_full_run/` (gitignore) に保存。
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

---

## 10. Phase 6 cost burn ramp LANDED (2026-05-16 16:00 JST)

Phase 5 smart analysis LANDING 後の Phase 6 として **real cost burn 軸を実 cost で取りに行く** 段。Cost Explorer 8-12hr lag が支配的、Phase 7 5-line hard-stop ARMED の上で安全に burn する設計。

### 10.1 J16 PDF Textract live run (200+ canonical 一次資料 PDF URL)

- J16 manifest: `data/aws_credit_jobs/J16_canonical_official_pdfs.json` (200+ canonical 一次資料 PDF URL, ministry / 自治体 / 裁判所 / JPO 各源)
- Textract OCR live: per-page $0.0015 × N pages、async API + S3 multi-part upload で `s3://*/runs/J16/` 配下に artifact 展開
- crawler container reuse + Textract async API + page-level retry の 3 層で long-tail saturation を吸う

### 10.2 EC2 Spot GPU sustained burn (FAISS / fine-tune)

- `ml.g4dn.12xlarge` 4 GPU を Spot Fleet で投入、FAISS index build + small fine-tune workload を **sustained burn** モードで回す
- 1 job 数時間 × 数 job で **数百 GPU-hour** を実 cost burn に変換、Cost Explorer 反映を Phase 7 alarm で観測
- Spot 割引で実効 $2-$3/hr × N hr、Phase 8 ramp で 6 jobs × 20h scale-up の前段検証

### 10.3 CloudFront mirror + bandwidth load test

- packet HTML preview (site/packets/ 30 sample + Wave 53 全 generator output) を CloudFront distribution に bind
- bandwidth load test で **egress 軸の cost burn** を観測、edge cache miss / origin pull / Lambda@Edge invocation 軸で実効 burn 取得
- egress 単価 $0.085/GB、Phase 8 で 5M req scale 5M × 100KB = 500GB = $42.5 base、edge miss / origin pull で **$200-$500 burn** 想定

### 10.4 Athena real burn (3 packet tables + 16 Wave 53 tables + 3 new big queries)

- Phase 5 で ready だった **5 big query** を populated table 上で re-run、ETL Glue 47 partitions / 1,029 source_receipts 後の実 scan 量で実 cost burn
- **3 new big queries** 追加: `cross_packet` (packet 横断結合) / `time_series` (時系列軸) / `entity_resolution_full` (法人ID横断解決)
- bytes scanned + $5/TB で **$XX 〜 数百 $** burn を Cost Explorer 反映で観測、`athena_real_burn_2026_05_16.md` に doc 化

### 10.5 Wave 53.3 + Wave 54 全 FULL-SCALE packet generator → S3

- **36 generator** が S3 に landing: Wave 53 5 + Wave 53.2 11 + Wave 53.3 10 + Wave 54 10
- packet catalog **14 → 30 → 52** に成長、各 packet `JPCIR OutcomeContract` envelope reuse
- `estimated_price_jpy` band ¥900-¥1,800 で Stripe metered ¥3/req billing path に bind

### 10.6 Phase 6 actual burn snapshot

- 実 cost: Cost Explorer 8-12hr lag が支配、Phase 6 burn 軸 (J16 Textract / EC2 GPU sustained / CloudFront / Athena real) が反映を待つ
- CW alarm seconds latency で Phase 7 line 1 ($14K) / line 2 ($17K) 到達観測の主要 driver
- Phase 7 5-line hard-stop ARMED で $19,490 物理的踏み越え不能、Phase 6 / 8 ramp の絶対保護

---

## 11. Phase 7 hard-stop 5-line defense ARMED (2026-05-16 PM)

詳細は `docs/_internal/AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md` (canonical SOT) に集約。本 doc では index のみ:

- **line 0** teardown scripts: `scripts/aws_credit_ops/stop_drill.sh` + `teardown_credit_run.sh` (DRY_RUN default + live token gated)
- **line 1** $14K CW alarm warn → SNS → Lambda log (visibility)
- **line 2** $17K Budget alert → SNS → Lambda log (awareness)
- **line 3** $18.3K Budget slowdown → Lambda log + CW alarm dual fire
- **line 4** $18.7K CW alarm → **Lambda direct invoke** (no email confirm) → queues DISABLED + jobs cancelled/terminated + CE DISABLED. Lambda `jpcite-credit-auto-stop` ARMED (`JPCITE_AUTO_STOP_ENABLED=true`)
- **line 5** $18.9K **Budget Action deny IAM policy** auto-attached to operator role → no new resources. STANDBY (Budget Action attached at LIMIT_AMOUNT $18,900)
- **ceiling $19,490**: never reach 設計, $590 margin

CW alarm seconds latency が Cost Explorer 8-12hr lag を吸収、email confirm pending でも line 4 direct Lambda + line 5 Budget Action deny IAM の 2 軸 modal hard-stop で物理的に止まる。

---

## 12. Phase 8 ramp IN_PROGRESS (2026-05-16 PM)

Phase 7 hard-stop 5-line defense ARMED の上で、**real burn 軸を Phase 7 line 1 ($14K) / line 2 ($17K) / line 3 ($18.3K) の各閾値に到達させる** 段。Lambda armed + Budget Action STANDBY が ramp 中の絶対 hard-stop として 24/7 監視。

### 12.1 Wave 55: 10 cross-3-source analytics packets (catalog 52 → 62)

- Wave 54 10 cross-source pattern を **3-source 連結に拡張**、各 packet が 3 軸 cross-join を 1 packet で展開
- packet catalog **52 → 62 in flight**、`estimated_price_jpy` band ¥1,200-¥1,800 で billing 軸の高付加価値 outcome
- JPCIR `OutcomeContract` envelope reuse、`scripts/check_schema_contract_parity.py` で 0 drift gate

### 12.2 Mega Athena cross-join 39 tables

- Phase 5 5 big + Phase 6 3 new + Phase 8 で **39 packet tables 累計の mega cross-join**
- data scan 量 **500 GB - 1 TB band**, Athena $5/TB 単価で **$2.5K - $5K burn 予定**
- Phase 8 中の最大単一 burn 軸、Cost Explorer 反映で Phase 7 line 1 ($14K) 到達の主要 driver

### 12.3 Long-running EC2 GPU 6 jobs (20h each)

- **6 jobs × 20h sustained on EC2 Spot GPU**、FAISS index build + fine-tune 系 calculation-dense workload **120 GPU-hour** 投入
- `ml.g4dn.12xlarge` 4 GPU × $7.45/hr base、Spot 割引で実効 $2-$3/hr × 120h = **$240-$360 per job**, 6 job で **$1.4K-$2.2K 累計**
- Phase 6 sustained burn pattern を 6 並列に拡張、Phase 7 line 2 ($17K) 到達想定

### 12.4 CloudFront 5M req bandwidth burn

- Phase 6 CloudFront mirror + bandwidth load test を本気で回す、**5M req scale**
- 1 req 平均 50KB-200KB の packet HTML 配信、egress $0.085/GB × 500GB base
- edge cache miss / origin pull / Lambda@Edge invocation で実効 **$200-$500 burn 予定**

### 12.5 39 packet tables aggregate (Phase 1-8 通じての packet 軸 SOT)

| 起源 phase | packet 軸 | 件数 |
| --- | --- | --- |
| Phase 5 法人360 | 86,849 packets (local gen 33 sec + S3 sync ~9 min, 64 並列) | 86,849 |
| Phase 5 制度 lineage | 11,601 packets | 11,601 |
| Phase 5 採択確率 cohort | 225K packets | 225,000 |
| Phase 5 Wave 53 (5 generator) | enforcement_heatmap / invoice_houjin_check / vendor_dd / regulatory_radar / subsidy_timeline | 5 generator |
| Phase 6 Wave 53.2 (11 generator) | 残 11 generator | 11 generator |
| Phase 6 Wave 53.3 (10 generator) | cross-source deep analysis | 10 generator |
| Phase 6 Wave 54 (10 generator) | cross-source packet | 10 generator |
| Phase 8 Wave 55 (10 in flight) | cross-3-source analytics | 10 generator |
| **計** | **39 packet tables aggregate** | **~323K packet rows + 56 generator** |

各 table が Athena Glue partitioned、CloudFront mirror 経由で配信可能、Stripe metered ¥3/req billing path に bind。

### 12.6 Phase 8 中の絶対 hard-stop status

| line | threshold | status | Phase 8 ramp との関係 |
| --- | --- | --- | --- |
| 0 (teardown) | n/a | READY (live token gated) | 緊急時 manual on-call |
| 1 ($14K warn) | $14,000 | ARMED | Mega Athena cross-join 39 table が反映で到達想定 |
| 2 ($17K alert) | $17,000 | ARMED | EC2 GPU 6 × 20h sustained で到達想定 |
| 3 ($18.3K slowdown) | $18,300 | ARMED | CloudFront 5M req + Wave 55 packet で到達想定 |
| 4 ($18.7K Lambda direct stop) | $18,700 | **ARMED** (`JPCITE_AUTO_STOP_ENABLED=true`) | Phase 8 ramp 中の真の hard-stop、email confirm 不要で即停止 |
| 5 ($18.9K Budget Action deny IAM) | $18,900 | **STANDBY** (Budget Action attached) | Phase 8 ramp で line 4 通過しても deny IAM で新規 resource 立ち上げ不可 |
| ceiling | $19,490 | never reach 設計 | $590 margin |

### 12.7 Phase 8 actual burn snapshot

- 実 cost: 依然 small (Cost Explorer 8-12hr lag、Phase 5-7 の compute は smoke / Fargate Spot tiny / SageMaker GPU smoke で実 burn small)
- Phase 8 ramp 完了後 12-24 hr で Cost Explorer 反映、CW alarm seconds latency で先に観測
- Lambda armed + Budget Action STANDBY が ramp 中の絶対 hard-stop として 24/7 監視
- 実 burn は Phase 8 完了後の attestation phase で確定、`aws_budget_canary_attestation` artifact に bind

### 12.8 Phase 8 における key learning (確立済)

- **local Python packet gen 300x faster** — 1 packet <1 sec の trivial compute は Fargate Spot startup ~30 sec が overhead で支配、local + `aws s3 sync --concurrent` が 167x speedup (`feedback_packet_local_gen_300x_faster`)
- **Cost Explorer 8-12hr lag が支配** — 実 cost burn は CW alarm seconds latency でしか観測不能、Cost Explorer は historical only
- **real burn 軸**: GPU 長時間 ($/hr × hour) / CloudFront egress ($/GB) / Textract per-page ($0.0015) / Athena scan ($5/TB) の 4 軸が支配、Fargate / S3 / Logs は noise
- **5-line defense は modal** — line 4 (resource state flip) と line 5 (IAM deny) が異なる効き方で並列、片方が失敗してももう片方が止める

---

last_updated: 2026-05-16
