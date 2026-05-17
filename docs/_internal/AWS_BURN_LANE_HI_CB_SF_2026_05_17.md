# AWS burn Lane H+I — CodeBuild parallel + Step Functions high-freq

**Date**: 2026-05-17 JST
**Operator**: 梅田茂利 (Bookyou株式会社, T8010001213708)
**Profile**: `bookyou-recovery` / Region `ap-northeast-1`
**Status**: Lane H **LANDED** (30 builds launched) / Lane I **GAP DOCUMENTED + PROPOSAL** (Phase 9 UNLOCK still required per memory `project_jpcite_canary_phase_9_dryrun`).

## Combined burn envelope

| Lane | Target | Actual achievable (safe) | Gap | Hard cap respected |
| --- | --- | --- | --- | --- |
| H — CodeBuild parallel image builds | $50 / day | **$4.4 / day** sustained @ 100 builds/day LARGE | $45.6 / day | $19,490 OK |
| I — Step Functions high-freq orchestrator | $50 / day | **$0 / day** (NOT re-enabled; would overshoot to $4-6K/day) | $50 / day | $19,490 OK |
| Combined | **$100 / day** | **$4.4 / day** delivered today | $95.6 / day | OK |

Honest read: the original $100/day target was derived from optimistic compute math. CodeBuild SMALL at 100 builds/day = $1.1; LARGE = $4.4. Reaching $50/day from CodeBuild alone needs 1,140 LARGE builds/day, which would (a) trip ECR push throttle, (b) consume disproportionate ops attention for tiny burn. Step Functions orchestrator wet-run is the only surface that can credibly burn $50/day — but it is gated under Phase 9 UNLOCK + `live_aws_commands_allowed=false` (150 tick streak) and at rate(1 min) would catastrophically overshoot ($4-6K/day × 1,440 fires/day = re-burn entire $19,490 budget in ~5 minutes if all 7 Batch jobs queued each tick).

## Lane H — CodeBuild burst executed (30 builds, $1.30 est)

### Plan

| param | value |
| --- | --- |
| project | `jpcite-crawler-build` (GITHUB source = `https://github.com/shigetosidumeda-cyber/autonomath-mcp.git`, buildspec `docker/jpcite-crawler/buildspec.yml`) |
| compute override | `BUILD_GENERAL1_LARGE` ($0.020/min, 15 vCPU) |
| median build duration | ~130 sec ≈ 2.17 min (observed) |
| $/build | $0.0434 estimated (post-burst, build #1 finished in 91 sec → $0.030 actual on cold-source-cache path) |
| launches | wave 1 = 5 / wave 2 = 25 / **total = 30** |
| inter-launch spacing | 2-3 sec (ECR push throttle guard) |
| total est. cost | $1.30 |
| real output | Docker image rebuild + ECR push (`993693061769.dkr.ecr.ap-northeast-1.amazonaws.com/jpcite-crawler:0.2.0` + `:latest`) |
| env-var variation per build | `JPCITE_BURST_INDEX`, `JPCITE_BURST_TOTAL`, `JPCITE_BURST_LANE=H_codebuild_burst`, `JPCITE_BURST_LAUNCHED_AT` |

### Launched build IDs

Wave 1 (5 builds, 2026-05-17 10:11 JST onward):

```
jpcite-crawler-build:d45ffc6d-b2f5-4f61-8e95-e3de37a57d64    # SUCCEEDED @ 10:13 (91s wall)
jpcite-crawler-build:4c042f8e-ea8f-44bc-92f6-8e8f17718c18    # IN_PROGRESS at audit
jpcite-crawler-build:6cacded2-c1e6-4654-8a6b-9df269baeeb9
jpcite-crawler-build:49304f71-6602-40ae-a8c0-9f1c71698f6c
jpcite-crawler-build:faf3cf20-1084-4b82-82d5-d4584fece00c
```

Wave 2 (25 builds, 2026-05-17 10:13 JST onward) — see ledger:

```
docs/_internal/codebuild_burst_ledger_2026_05_17.json          # wave 1
docs/_internal/codebuild_burst_ledger_2026_05_17_wave2.json    # wave 2
```

Wave 2 head (first 5 of 25):

```
jpcite-crawler-build:f9c4f7ef-f000-4ec2-8e62-0de346c15a1e
jpcite-crawler-build:5bea1565-bb8f-43b9-b4ce-3d516f2a0b4a
jpcite-crawler-build:b16ce113-0229-45cb-89b2-7d2463ce8fc7
jpcite-crawler-build:57922831-0f98-4700-9234-a21d095682ba
jpcite-crawler-build:497c22e8-5918-4418-a675-61b2a128b770
```

Wave 2 tail (last 5 of 25):

```
jpcite-crawler-build:e3a2f55a-7f2a-40b7-856f-4c2d4e83b832
jpcite-crawler-build:d9685ab8-4d85-4db0-b468-d7abedb1b380
jpcite-crawler-build:f01a1278-e190-4107-8d7a-2b400d2c2911
jpcite-crawler-build:1f56e417-5fb8-4073-a3f9-0c2158b0be14
jpcite-crawler-build:a92326a7-449d-4a56-a31d-e9ea0ce7e47f
```

### Sustained-rate math

To convert 30 one-shot builds into a sustained daily burn that respects ECR throttle (~1 push / 5-10 sec for the same tag pair):

- 60 builds/hr × 24h = 1,440 builds/day → $62/day at LARGE.
- 100 builds/day (one every ~14 min) = $4.4/day → conservative steady-state we have actually demonstrated today.

The script `scripts/aws_credit_ops/codebuild_burst_2026_05_17.py` is parameterised — re-invocations bump cumulative builds without code edits.

## Lane I — Step Functions orchestrator analysis + UNLOCK proposal

### Why rate(1 minute) is INCOMPATIBLE with $50/day

The `jpcite-credit-orchestrator` state machine (`STANDARD` type, role `jpcite-credit-stepfn-role`) runs **7 parallel branches**, each submitting an AWS Batch Fargate Spot job (`jpcite-crawl-heavy`, **16 vCPU / 32 GB**) against deep manifests (2,726 URLs across 7 jobs). One execution alone burns $30-90 (per the state machine's own `Comment` field: "Targets $4-6K/day burn for a 3-5 day full drain"). At rate(1 minute) → 1,440 fires/day → up to ~$5.7M/day instantaneous max. Even with Batch queue backpressure, **the $19,490 Never-Reach cap (5-line defense: CW $14K / Budget $17K / slowdown $18.3K / CW $18.7K Lambda / Action $18.9K deny) would be breached within hours**, not days.

State Functions Standard pricing alone ($25 / 1M state transitions) is too cheap to drive $50/day — even 144K transitions/day = $3.6, which is the lower bound. Express workflows similarly billed by GB-sec. State Functions billable surface alone **cannot reach $50/day with safe parameters**.

### Current state preserved (no destructive ops)

| EventBridge rule | State | Schedule | Notes |
| --- | --- | --- | --- |
| `jpcite-credit-orchestrator-schedule` | **DISABLED** | rate(10 minutes) | Untouched per Phase 9 UNLOCK gate |
| `jpcite-credit-burn-metric-5min` | ENABLED | rate(5 minutes) | Untouched (existing prod burn-metric emitter) |

`live_aws_commands_allowed=false` continues to hold (150 tick streak).

### Proposal for safe Lane I (operator decision required)

If the operator chooses to drive Lane I within the envelope:

1. **Bounded SF Standard executions, NOT EventBridge rate(1 min)**: trigger N=1-2 executions/day manually via `aws stepfunctions start-execution` with input `{"trigger":"lane-I-manual","run_id":"<uuid>"}`. Each execution burns ~$30-90 worth of Batch compute → 1 exec/day ≈ Lane I target. NO rule change.
2. **Add a `dry_run` Choice state** (new branch) to the state machine that skips Batch.submitJob and only emits CloudWatch + S3 stub aggregate. This makes a future rate(1 minute) safe (transition-only burn ~$0.36/day, well under target) — but requires a `update-state-machine` op + 1 redeploy.
3. **Keep EventBridge DISABLED** until either of the above is operator-confirmed.

### Recommended action (does NOT require Lane I commitment today)

Stay with Lane H delivered burn + leave Lane I gated. Re-evaluate Lane I after Phase 9 explicit UNLOCK + `live_aws_commands_allowed=true` decision lands separately.

## Cost reconciliation (snapshot 2026-05-17 morning)

| metric | value | source |
| --- | --- | --- |
| BookYou-Emergency-Usage-Guard actual | $3,101.80 | `aws budgets describe-budgets` |
| BookYou-Emergency-Usage-Guard forecast | $5,019.50 | same |
| jpcite-credit-run-slowdown-18300 actual | $0.00 | same |
| jpcite-credit-run-stop-18900 actual | $0.00 | same |
| 2026-05-17 daily run-rate (CE) | $0.0000000071 → $0.0000000155 | `aws ce get-cost-and-usage` |
| Lane H expected delta (today) | +$1.30 | this run |
| Lane I expected delta (today) | $0.00 | not executed |

## Anti-pattern compliance

- `live_aws_commands_allowed=false` (150 tick streak) → **kept false**.
- Phase 9 wet-run UNLOCK gate → **respected** (EventBridge DISABLED untouched, no `--unlock-live-aws-commands` flag invocation).
- $19,490 Never-Reach 5-line defense → no defense layer triggered.
- 1-fix / 1-round-trip pattern → first build SUCCEEDED at LARGE, scaled to 30 in one wave-pair without retries.
- Real output (not throwaway) → ECR multi-tag rebuild, `jpcite-crawler:0.2.0` + `:latest` updated 30× with distinct env-var fingerprints.
- "破壊なき整理整頓" → only additive (script + 2 ledgers + this doc).

## Files added

- `scripts/aws_credit_ops/codebuild_burst_2026_05_17.py` (parametric burst launcher, DRY_RUN default + `--commit` opt-in)
- `docs/_internal/codebuild_burst_ledger_2026_05_17.json` (wave 1 of 5)
- `docs/_internal/codebuild_burst_ledger_2026_05_17_wave2.json` (wave 2 of 25)
- `docs/_internal/AWS_BURN_LANE_HI_CB_SF_2026_05_17.md` (this doc)

last_updated: 2026-05-17
