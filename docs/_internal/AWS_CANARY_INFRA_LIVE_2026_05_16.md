# AWS Canary Infrastructure — LIVE State Closeout (2026-05-16 PM)

> **Status: Phase 1+2 DONE / Phase 3 IN_PROGRESS / Phase 4-7 pending.**
> `live_aws_commands_allowed` was flipped to **true** for the first time today
> via Stream W concern-separation flag `--unlock-live-aws-commands`. The
> preflight scorecard runner is the single authority for the flip; no other
> code path may set this flag.

last_updated: 2026-05-16

companion runbook: `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
companion checklist: `docs/_internal/aws_canary_execution_checklist.yaml`
companion quickstart: `docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md`
attestation template: `docs/_internal/AWS_CANARY_ATTESTATION_TEMPLATE.md`
memory back-link: `project_jpcite_aws_canary_infra_live_2026_05_16` (SOT) /
`project_jpcite_rc1_2026_05_16` (RC1 anchor) /
`feedback_loop_promote_concern_separation` (Stream W lesson)

---

## 0. Scope

This closeout doc records the LIVE state of the AWS canary infrastructure
provisioned today (2026-05-16 PM) in the jpcite canary AWS account
(separate from the BookYou compromised account — do **not** conflate the
two: see `project_aws_bookyou_compromise` memory for the BookYou bleed
which remains user-action-blocked).

The doc is **artifact-only** for the future operator/agent. Re-reading it
must not cause any AWS side-effect. Live execution still requires the
preflight runner + operator opt-in flags.

---

## 1. Stream W unlock_step honored

The first live opt-in flip of `live_aws_commands_allowed` was honored
per the Stream W concern-separation pattern:

- `--promote-scorecard` alone keeps `live_aws_commands_allowed=false`.
- An **additional** `--unlock-live-aws-commands` flag, passed by the
  operator during the promote call, is the single authority allowed to
  flip the flag from `false` → `true`.
- Today: scorecard state `AWS_CANARY_READY` was preserved; only the
  boolean flipped to `true`. The runner authority pattern survived its
  first live test.

Reference implementation: `scripts/promote_scorecard.py` + the unlock-
step bullet in `AWS_CANARY_EXECUTION_RUNBOOK.md` §1 (table row P-2).

---

## 2. Phase status

| # | Phase | Scope | Status |
| --- | --- | --- | --- |
| 1 | Guardrail | 3 AWS Budgets (USD 17K / 18.3K / 18.9K) + 3 CW billing alarms + 1 Batch failure metric filter + SNS topic | **DONE** |
| 2 | Infrastructure | 3 S3 buckets + IAM (SLR + 3 role) + ECR + image + Logs + 2 Batch CE + 2 queue + job def + Glue DB + Athena workgroup + Step Functions | **DONE** |
| 3 | Smoke J01 | First-run failure → entrypoint fix → 3rd CodeBuild | **IN_PROGRESS** |
| 4 | Fan-out J02-J07 | Batch parallel submit for 6 remaining jobs | pending |
| 5 | Drain | aggregate_run_ledger + Athena partition refresh | pending |
| 6 | Teardown | `teardown_credit_run.sh` + `verify_zero_aws.sh` | pending |
| 7 | Attestation | Emit + bind to `aws_budget_canary_attestation` schema artifact | pending |

---

## 3. Resources provisioned (Resource map, region us-east-1 unless noted)

### Guardrail
- **AWS Budgets** (3 envelopes against canary credit factory USD 19,490):
  - soft alert: USD 17,000
  - effective cap: USD 18,300 ← burn target reaches this in 12 days at USD 1,525/day
  - hard ceiling: USD 18,900
- **CloudWatch billing alarms** (3): aligned with the 3 budget envelopes
- **CloudWatch metric filter**: Batch job FAILED rollup
- **SNS topic**: `jpcite-credit-cost-alerts` (subscription pending email confirm)

### Storage (S3, region-locked, no public ACL)
- `s3://jpcite-canary-raw-*` — input manifests + scraped raw artifacts
- `s3://jpcite-canary-derived-*` — derived JSON/Parquet for Athena
- `s3://jpcite-canary-reports-*` — closeout reports + attestations
- All 3 buckets: SSE-S3 encryption + `aws:SecureTransport=true` policy + lifecycle (90-day Glacier, 365-day expiry)

### IAM
- **Batch Service-Linked Role** (newly created in this account)
- **`ecsTaskExecutionRole`** — Fargate task pulls ECR + writes CW Logs
- **`jpcite-batch-job-role`** — job-runtime S3 + Textract + Athena (scope-locked, no admin)
- **`ecsInstanceRole`** — EC2 Spot CE cluster join

### Container / build
- **ECR repo**: `jpcite-crawler`
- **Container image digest**: `sha256:80a28540b...` (built today; ECR Public mirror Dockerfile fix landed in commit `c1dbd00e6` series)
- **CodeBuild project**: `jpcite-crawler-build`

### Logs
- **CloudWatch log group**: `/aws/batch/jpcite-credit-2026-05` (14-day retention)

### Compute (AWS Batch)
- **Compute Environment A**: Fargate Spot, 1024 vCPU max — VALID, status Healthy
- **Compute Environment B**: EC2 Spot, 512 vCPU max — VALID, status Healthy
- **Job Queue A**: priority 50, bound to CE A — VALID
- **Job Queue B**: priority 50, bound to CE B — VALID
- **Job Definition**: `jpcite-crawl` revision 1, uses `jpcite-batch-job-role`

### Analytics
- **Glue Data Catalog database**: `jpcite_credit_2026_05`
- **Athena Workgroup**: query-result S3 bound to reports bucket, per-query cost cap configured

### Orchestration
- **Step Functions state machine**: `jpcite-credit-orchestrator` (drives J01-J07 sequence + drain gate)

---

## 4. Job manifests (S3-staged)

7 manifests uploaded covering 106 source URLs and USD 9,200 of the
budget envelope:

- **J01** crawl_news (smoke target)
- **J02** crawl_municipality
- **J03** crawl_pref
- **J04** corp_registry
- **J05** corp_amend
- **J06** ministry_pdf (Textract path, no LLM)
- **J07** court_decision

Supporting artifacts:
- `source-to-job map` — 31 entries → 7 jobs (canonical resolver)
- Textract client: `src/jpintel_mcp/aws_credit_ops/textract_client.py`
- Safety scanners: `src/jpintel_mcp/safety_scanners/no_hit_regression.py` + `forbidden_claim.py`
- Cost preview + capability matrix: covers 165 MCP tools (155 base + Wave 51 dim K-S 10 wrappers)

---

## 5. Ops scripts (`scripts/aws_credit_ops/`)

| Script | Purpose |
| --- | --- |
| `stop_drill.sh` | Drill that shuts down Batch + CE without teardown of long-lived infra |
| `cost_ledger.sh` | Per-job credit-burn ledger emit |
| `burn_target.py` | Computes USD 1,525/day toward 12-day window → USD 18,300 effective cap |
| `submit_job.sh` | Single-manifest Batch submit (J0X argument) |
| `submit_all.sh` | Fan-out submitter (J01..J07 in order) |
| `monitor_jobs.sh` | RUNNING / SUCCEEDED / FAILED rollup |
| `teardown_credit_run.sh` | DRY_RUN default; `--commit` to teardown |
| `aggregate_run_ledger.sh` | Phase 5 (not yet landed) — drain-time ledger aggregator |

All scripts require `--profile jpcite-canary` (NOT `bookyou-recovery`; the
two profiles target different accounts).

---

## 6. J01 first smoke iteration

- **1st run**: J01 FAILED at startup. Root cause: `entrypoint.py` could
  not resolve the manifest's output target — the schema accepts 3 forms
  (legacy split / single s3 URI / env override) but only the legacy
  split was wired.
- **Fix**: commit `61339f491` — `docker/jpcite-crawler/entrypoint.py`
  now resolves all 3 forms.
- **2nd CodeBuild**: emitted updated image.
- **3rd CodeBuild**: IN_PROGRESS (digest for J01 retry).

No teardown was triggered — the fix loop stays inside Phase 3 by design.

---

## 7. User actions remaining

| # | Action | Why |
| --- | --- | --- |
| U-1 | **Confirm SNS email subscription** for `jpcite-credit-cost-alerts` | Otherwise budget alarms route to unconfirmed endpoint |
| U-2 | Approve J01 smoke retry after the 3rd CodeBuild completes (`monitor_jobs.sh` will surface state) | Phase 3 closure requires operator-side go |
| U-3 | Approve Phase 4 fan-out (J02-J07 parallel submit) once J01 smoke is green | Stream W keeps each phase opt-in |
| U-4 | Approve Phase 6 teardown once drain ledger shows zero outstanding jobs | DRY_RUN default; `--commit` needs explicit opt-in |
| U-5 | Counter-sign Phase 7 attestation artifact | `aws_budget_canary_attestation.schema.json` binding |

---

## 8. Stop / teardown commands (DRY_RUN defaults)

```bash
# Inspect cost ledger so far (read-only)
./scripts/aws_credit_ops/cost_ledger.sh --profile jpcite-canary

# Show RUNNING / SUCCEEDED / FAILED rollup
./scripts/aws_credit_ops/monitor_jobs.sh --profile jpcite-canary

# Drill: stop Batch + CE without removing infra (recoverable)
./scripts/aws_credit_ops/stop_drill.sh --profile jpcite-canary --dry-run

# Full teardown (DRY_RUN default — verify diff first, then re-run with --commit)
./scripts/aws_credit_ops/teardown_credit_run.sh --profile jpcite-canary
./scripts/aws_credit_ops/teardown_credit_run.sh --profile jpcite-canary --commit
```

After `--commit` teardown, verify zero-AWS state via the canonical
`scripts/teardown/verify_zero_aws.sh` (built in Wave 50, 30/30 tests
PASS) before emitting the Phase 7 attestation.

---

## 9. Master plan invariants (don't violate)

- **Artifact-only**: outputs live in the 3 S3 buckets, no permanent
  runtime services. Step Functions exists only to orchestrate the
  12-day run.
- **No permanent compute**: both CEs are Spot. After drain + teardown
  both CEs go to zero capacity.
- **Full teardown post-drain**: Phase 6 is required before any new
  canary cycle. Reusing today's infra for a second run is not allowed.
- **Account separation**: this canary lives in the jpcite canary
  account. The BookYou compromised account remains user-action-blocked
  per `project_aws_bookyou_compromise`. Do not cross profiles.
- **`live_aws_commands_allowed`**: only the preflight scorecard runner
  may flip this flag, only with `--unlock-live-aws-commands`, one
  phase at a time.

---

## 10. Reference paths (absolute)

- `/Users/shigetoumeda/jpcite/docker/jpcite-crawler/entrypoint.py`
- `/Users/shigetoumeda/jpcite/scripts/aws_credit_ops/` (8 scripts; `aggregate_run_ledger.sh` lands in Phase 5)
- `/Users/shigetoumeda/jpcite/src/jpintel_mcp/aws_credit_ops/textract_client.py`
- `/Users/shigetoumeda/jpcite/src/jpintel_mcp/safety_scanners/no_hit_regression.py`
- `/Users/shigetoumeda/jpcite/src/jpintel_mcp/safety_scanners/forbidden_claim.py`
- `/Users/shigetoumeda/jpcite/schemas/jpcir/aws_budget_canary_attestation.schema.json`
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/aws_canary_execution_checklist.yaml`
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_ATTESTATION_TEMPLATE.md`

last_updated: 2026-05-16
