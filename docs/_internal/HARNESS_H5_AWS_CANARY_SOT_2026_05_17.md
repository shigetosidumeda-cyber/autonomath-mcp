# Harness H5 — AWS Canary Single Source of Truth (2026-05-17)

> **canonical_live_state**: [`site/releases/rc1-p0-bootstrap/preflight_scorecard.json`](../../site/releases/rc1-p0-bootstrap/preflight_scorecard.json) — the **only** authority for AWS canary live values (`state`, `live_aws_commands_allowed`, `cash_bill_guard_enabled`, `unlocked_at`). Any markdown copy in this repo is **descriptive narrative**, not normative live state.

last_updated: 2026-05-17

memory back-link: `project_jpcite_aws_canary_infra_live_2026_05_16` (Phase 1-8 snapshot) /
`project_jpcite_canary_burn_phase_by_phase_2026_05_16` (Phase trajectory) /
`feedback_aws_canary_hard_stop_5_line_defense` (5-line defense) /
`feedback_loop_promote_concern_separation` (Stream W unlock_step)

---

## 0. Why this doc exists

README + `docs/_internal/AWS_CANARY*.md` + scorecard で `live_aws_commands_allowed` の値が
不整合だった (false / true 両説併存)。原因:

1. 2026-05-16 PM までは `live_aws_commands_allowed=false` が 12-150 tick 連続絶対堅守状態。
2. 2026-05-17 03:11:48Z に operator が commit `974a5f3cb` で scorecard を unlock
   (`true` flip)。
3. README + 一部 AWS_CANARY*.md が **flip 前の状態を hard-code** したまま残存。
4. 結果: doc 上 `false` / scorecard 上 `true` の split-brain 化。

本書は **scorecard を唯一の SOT** と確定させ、markdown 側は narrative + historical snapshot
として位置づけることで split-brain を恒久解消する。

---

## 1. Canonical authority chain

```
site/releases/rc1-p0-bootstrap/preflight_scorecard.json   ← canonical SOT (machine-readable)
        │
        ├── written by: scripts/promote_scorecard.py (preflight_runner authority)
        ├── unlock-only by: --unlock-live-aws-commands flag (operator authority gate)
        └── reflected in:
            ├── README.md §"Wave 50 RC1 final state" — points to scorecard, no hard-code
            ├── docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md §0 preamble — references scorecard
            ├── docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md §"前提" — references scorecard
            └── docs/_internal/AWS_CANARY_*_2026_05_16.md — historical markers (frontmatter)
```

Scorecard fields (`jpcite.preflight_scorecard.p0.v1` schema):

| field | type | authority |
| --- | --- | --- |
| `state` | enum (`AWS_BLOCKED_PRE_FLIGHT` / `AWS_CANARY_READY`) | `preflight_runner` writes |
| `live_aws_commands_allowed` | bool | `operator` flips via `--unlock-live-aws-commands` |
| `cash_bill_guard_enabled` | bool | `preflight_runner` ensures `true` before flip |
| `target_credit_conversion_usd` | int (= 19490) | static |
| `unlocked_at` | iso8601 | written on each unlock event |
| `scorecard_promote_authority` | string (= `preflight_runner`) | static, asserts authority |
| `unlock_authority` | string (= `operator`) | static, asserts authority |

---

## 2. Live snapshot (read-time, NOT canonical)

Read-time snapshot at 2026-05-17 (informational only — re-read scorecard for live):

```json
{
  "capsule_id": "rc1-p0-bootstrap-2026-05-15",
  "schema_version": "jpcite.preflight_scorecard.p0.v1",
  "state": "AWS_CANARY_READY",
  "live_aws_commands_allowed": true,
  "cash_bill_guard_enabled": true,
  "target_credit_conversion_usd": 19490,
  "unlocked_at": "2026-05-17T03:11:48Z",
  "scorecard_promote_authority": "preflight_runner",
  "unlock_authority": "operator"
}
```

Do **not** quote this block as if it were normative. Re-read scorecard before acting.

---

## 3. Identity 統一 (canonical)

All AWS canary code paths converge on the following identity tuple:

| key | canonical value | enforced by |
| --- | --- | --- |
| AWS profile | `bookyou-recovery` | `tests/test_agent_runtime_contracts.py:134` + every `scripts/aws_credit_ops/*.sh:export AWS_PROFILE` default |
| AWS account | `993693061769` | `tests/test_agent_runtime_contracts.py:135` + attestation schema `aws_account_id` |
| billing region (CW/SNS/Lambda/Budgets) | `us-east-1` | `INFRA_LIVE.md §3` + 5-line defense doc + recovery procedure |
| operational region (Batch/CE/queues) | `ap-northeast-1` | recovery procedure + 5-line defense `JPCITE_BATCH_REGION` env-var |

Dual region is **by design** (us-east-1 for global billing primitives, ap-northeast-1 for
compute close to Japan source corpora). Do not collapse to one region — would break
SNS publish parity, CW alarm region, and Step Functions invariants
(`feedback_aws_cross_region_sns_publish`).

Historical inconsistency in `AWS_CANARY_INFRA_LIVE_2026_05_16.md §5` referenced a separate
`jpcite-canary` profile; this has been resolved to `bookyou-recovery` (the dual-account
plan was abandoned during the 2026-05-16 PM burn ramp). Tests + scripts are canonical.

---

## 4. Hard-stop guard chain ($19,490 5-line defense)

Canonical guard threshold ladder:

| line | threshold | mechanism | armed by |
| --- | --- | --- | --- |
| 0 | n/a | teardown scripts (`scripts/aws_credit_ops/teardown_credit_run.sh`) | always READY (DRY_RUN default) |
| 1 | $14,000 | CW alarm `jpcite-credit-cost-warn-14k` → SNS notify | provisioned 2026-05-16 PM |
| 2 | $17,000 | AWS Budget envelope `jpcite-credit-soft-alert-17k` | provisioned 2026-05-16 PM |
| 3 | $18,300 | AWS Budget envelope `jpcite-credit-slowdown-18300` → effective cap | provisioned 2026-05-16 PM |
| 4 | $18,700 | CW alarm `jpcite-credit-cost-stop-187k` → Lambda `jpcite-credit-auto-stop` direct invoke (no email) | `JPCITE_AUTO_STOP_ENABLED=true` |
| 5 | $18,900 | AWS Budget envelope `jpcite-credit-hard-ceiling-189k` → Budget Action `APPLY_IAM_POLICY` deny-new-spend on `bookyou-recovery-admin` | STANDBY (auto-attach on breach) |
| ceiling | $19,490 | never-reach by design ($590 margin) | absorbed by Cost Explorer 8-12hr lag buffer |

Verify armed state at any time:

```bash
AWS_PROFILE=bookyou-recovery aws cloudwatch describe-alarms --region us-east-1 \
  --alarm-names jpcite-credit-cost-warn-14k jpcite-credit-cost-stop-187k
AWS_PROFILE=bookyou-recovery aws budgets describe-budgets --account-id 993693061769 \
  --query 'Budgets[].BudgetName'
# expected: jpcite-credit-soft-alert-17k / jpcite-credit-slowdown-18300 / jpcite-credit-hard-ceiling-189k
AWS_PROFILE=bookyou-recovery aws budgets describe-budget-actions-for-account \
  --account-id 993693061769 --region us-east-1 \
  --query 'Actions[].{name:ActionId,status:Status,threshold:ActionThreshold.ActionThresholdValue}'
# expected: STANDBY @ $18,900 (i.e. 100% of jpcite-credit-hard-ceiling-189k)
```

CloudWatch alarms (5 total) + Budget Actions (1 deny IAM) are the canonical armed surface.

---

## 5. Historical markers added (this doc landing, 2026-05-17)

The following 2026-05-16-dated docs received a `historical: true` frontmatter pointing to
the canonical scorecard SOT (their narrative content is preserved as snapshot):

- `docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md`
- `docs/_internal/AWS_CANARY_RUN_2026_05_16.md`
- `docs/_internal/AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md`
- `docs/_internal/AWS_CANARY_RECOVERY_PROCEDURE_2026_05_16.md`

Forward-looking runbooks (un-dated, live procedure) received preamble updates to point at
the scorecard SOT instead of hard-coding state:

- `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
- `docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md`

`docs/_internal/AWS_CANARY_ATTESTATION_TEMPLATE.md` is a schema template (not a state
record), retained as-is.

README §"Wave 50 RC1 final state" hard-coded `live_aws_commands_allowed: false` line
replaced with a SOT pointer to the scorecard. The `2026-05-16 What's new` narrative section
retains the historical "flipped for the first time today" wording (it describes the
2026-05-16 unlock event, not current state).

---

## 6. Constitutional invariants (do NOT violate)

1. **scorecard runner authority is exclusive** for `live_aws_commands_allowed` flip. No
   other code path may write the field. `scripts/promote_scorecard.py` requires
   `--unlock-live-aws-commands` flag explicitly; default `--promote-scorecard` keeps
   the field at its existing value.
2. **All LIVE AWS jobs currently running** (4 GPU + SageMaker + OpenSearch + Lambda
   attestation chain + CW burn-metric + 129 Glue tables + Athena Q1-Q47) **MUST NOT** be
   touched by this SOT consolidation. This is a docs-only change.
3. **No LLM imports** in src/ / scripts/cron/ / scripts/etl/ / tests/ — H5 docs are
   markdown only, no code added.
4. **mypy --strict 0 maintained** — no code touched.
5. **`tests/test_agent_runtime_contracts.py` invariant preserved**: the contract-layer
   noop plan (`build_noop_aws_command_plan`) intentionally asserts
   `plan.live_aws_commands_allowed is False` regardless of live scorecard — this is the
   **default contract** for any new agent session before it reads scorecard. The test is
   structural (does an unconditional noop survive), not state-mirroring. Test stays as-is.

---

## 7. Verify procedure (any agent / operator, any time)

```bash
# 1. Read canonical SOT
jq '.state, .live_aws_commands_allowed, .cash_bill_guard_enabled, .unlocked_at' \
  site/releases/rc1-p0-bootstrap/preflight_scorecard.json

# 2. Compare against doc claims (should match scorecard for un-marker'd docs)
grep -rn "live_aws_commands_allowed" docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md \
  docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md README.md

# 3. Confirm historical-marker'd docs are flagged
head -5 docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md
# expected: --- / historical: true / superseded_by: ...preflight_scorecard.json ...
```

If un-marker'd doc disagrees with scorecard: **scorecard wins**, update the doc to either
reference scorecard or add `historical: true` marker.

---

## 8. References (absolute paths)

- `/Users/shigetoumeda/jpcite/site/releases/rc1-p0-bootstrap/preflight_scorecard.json`
- `/Users/shigetoumeda/jpcite/scripts/promote_scorecard.py`
- `/Users/shigetoumeda/jpcite/scripts/aws_credit_ops/`
- `/Users/shigetoumeda/jpcite/schemas/jpcir/aws_budget_canary_attestation.schema.json`
- `/Users/shigetoumeda/jpcite/tests/test_agent_runtime_contracts.py`
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_OPERATOR_QUICKSTART.md`
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md` (historical)
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_RUN_2026_05_16.md` (historical)
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_HARD_STOP_5_LINE_DEFENSE_2026_05_16.md` (historical)
- `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_RECOVERY_PROCEDURE_2026_05_16.md` (historical)
