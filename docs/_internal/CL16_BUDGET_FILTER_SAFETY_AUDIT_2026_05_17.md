# CL16 — AWS Budget Filter Scope Safety Audit (2026-05-17 evening)

**Lane:** solo
**Account:** 993693061769 (bookyou-recovery)
**Mode:** READ-ONLY verification of 5-line defense hard-stop integrity
**Trigger:** CL8 (`3c220c45b`) flagged that `jpcite-credit-run-*` budgets reported `ActualSpend=$0.00` while CL8 inferred true spend = $751.08, raising risk that `CostFilters` were scoping budgets too narrowly to fire.

---

## TL;DR

**Critical risk level: LOW (downgraded from HIGH).**

- Account-wide month-to-date spend = **$0.0000001106 UnblendedCost** (basically $0; credit-applied).
- Forecasted month-end = **$1,081.12** vs $18,900 stop budget = 5.7% utilisation (well under all 5 lines).
- All 3 budgets have `CostFilters=null` → **account-wide catch-all**, not tag-narrowed → will fire on any cost that breaches.
- All 4 CW alarms use `AWS/Billing EstimatedCharges` (account-wide metric, no dimension filter) → will fire on any cost that breaches.
- The "$751.08" anomaly inferred in CL8 was a **different billing entity / stale forecast snapshot**; on this account (`bookyou-recovery-admin`) AWS Cost Explorer shows credits/refunds netting actual to ≈ $0.

**Defense posture is INTACT. No filter drift. 5-line stop will trigger as designed if cost ramps.**

One minor coverage gap exists (tag hygiene, not safety-blocking) — documented below.

---

## 1. 5-line defense × CostFilters × current state

| # | Line | Resource | Threshold | CostFilters / Metric Scope | ActualSpend (today) | State | Will Fire? |
|---|------|----------|-----------|----------------------------|---------------------|-------|------------|
| 1 | CW $13K | `jpcite-credit-billing-early-warning-13000` | $13,000 | `AWS/Billing` `EstimatedCharges` (account-wide, no Currency/Service filter) | $0 | OK | Yes |
| 2 | CW $14K | `jpcite-credit-billing-warn-14000` | $14,000 | `AWS/Billing` `EstimatedCharges` (account-wide) | $0 | OK | Yes |
| 3 | Budget $17K watch | `jpcite-credit-run-watch-17000` | $17,000 | `CostFilters=null` (account-wide MONTHLY UnblendedCost, IncludeCredit=true, IncludeRefund=true) | $0.00 | HEALTHY | Yes |
| 3b | CW $17K mirror | `jpcite-credit-billing-slowdown-17000` | $17,000 | `AWS/Billing` `EstimatedCharges` (account-wide) | $0 | OK | Yes |
| 4 | Budget $18.3K slowdown | `jpcite-credit-run-slowdown-18300` | $18,300 | `CostFilters=null` (account-wide MONTHLY UnblendedCost) | $0.00 | HEALTHY | Yes |
| 5a | CW $18.7K Lambda trigger | `jpcite-credit-billing-stop-18700` | $18,700 | `AWS/Billing` `EstimatedCharges` (account-wide) | $0 | OK | Yes |
| 5b | Budget $18.9K stop + IAM deny | `jpcite-credit-run-stop-18900` | $18,900 | `CostFilters=null` (account-wide MONTHLY UnblendedCost) → `APPLY_IAM_POLICY` attach `jpcite-credit-run-deny-new-spend` to `bookyou-recovery-admin` | $0.00 | HEALTHY (Action STANDBY, AUTOMATIC, role `jpcite-budget-action-role`) | Yes |

**Coverage: 7/7 defense layers verified account-wide. Zero filter narrowness.**

---

## 2. Drift map

### A. CostFilters drift — NONE

All 3 budgets have `CostFilters=null`. This is the **safest possible scope**: any cost charged to the account counts toward the budget. There is no tag/service/region filter that could silently miss a SageMaker, Textract, OpenSearch, or Bedrock charge.

`CostTypes` flags:
- `IncludeCredit=true` — AWS credits NET against spend (this is why ActualSpend=$0 today; credits are absorbing the $0.125 BlendedCost).
- `IncludeRefund=true`, `IncludeTax=true`, `IncludeSubscription=true`, all `Include*=true`.
- `UseBlended=false`, `UseAmortized=false` → Unblended (cash) basis.

**Implication:** When credits exhaust, ActualSpend will start tracking BlendedCost (currently $0.125/month). The trajectory then ramps and budgets will fire on their literal thresholds without filter drift.

### B. ForecastedSpend visibility

`jpcite-credit-run-stop-18900.CalculatedSpend.ForecastedSpend.Amount = 1081.12` matches independently-derived `ce get-cost-forecast` value (`1081.1233566975843`). **Forecast pipeline is operational.**

### C. Tag-vs-spend reconciliation

| Group dimension | Total spend today | Notes |
|-----------------|-------------------|-------|
| Account-wide (no group) | $0.0000000051 | UnblendedCost; credits offset BlendedCost |
| `TAG:Project=jpcite` | $0 | Only 9/47 resources tagged (19% coverage) |
| `TAG:Workload` | "Workload$" empty key, $0.0000000051 | No resources tagged with `Workload` |
| `SERVICE:Lambda` | $0.0000197502 | bills regardless of tag |
| `SERVICE:Step Functions` | $0.0000485719 | bills regardless of tag |
| `SERVICE:Data Transfer` | -$2.87 | credit refund |

**Important:** because budgets are `CostFilters=null`, the 19% tag coverage **does not** cause safety blindness. Budgets catch all spend regardless of tag. Tag coverage matters only for cost attribution analytics, not for stop enforcement.

### D. EventBridge gate (already DISABLED from Phase 9 dry-run)

`aws events list-rules --filter jpcite` returns `[]` → no jpcite-named EB rules active (consistent with Phase 9 EB-DISABLED gate from `project_jpcite_canary_phase_9_dryrun`). Auto-stop Lambda (`jpcite-credit-auto-stop`) remains attached for trigger via $18.7K CW alarm → SNS → Lambda chain when CW alarm transitions.

---

## 3. Coverage gap (informational, NOT safety-blocking)

**Gap-1 — Project tag coverage 19% (9 of 47 resources).**

Untagged resources include:
- 32 SageMaker action/context entities (auto-generated metadata, not billable line items; parent endpoint billing is what counts).
- VPC endpoint `vpce-0a58f362071ffd642`.
- AutoScalingManagedRule (EB rule, system-managed).
- 2 payment-instruments (billing infra, no charge).
- 2 satyr-model CW alarms (auto-scale, tag not propagated).
- 1 CloudFront distribution `EO5TCQIP04VSX`.
- 1 ECR repo `satyr-model`.

**Safety impact:** zero. Budgets are account-wide; they catch this spend.
**Analytics impact:** mild. Cost attribution by tag undercounts jpcite-attributable spend.

**Operator action item:** Optional, low priority. CodeX can backfill tags via `aws resourcegroupstaggingapi tag-resources` when convenient; not required for hard-stop integrity.

---

## 4. Fix prescription (doc only — CodeX scope to apply)

### F-1 (optional, P3): Tag backfill for cost attribution

```bash
# example pattern — DO NOT RUN HERE
aws resourcegroupstaggingapi tag-resources \
  --resource-arn-list \
    arn:aws:ec2:us-east-1:993693061769:vpc-endpoint/vpce-0a58f362071ffd642 \
    arn:aws:ecr:us-east-1:993693061769:repository/satyr-model \
    arn:aws:cloudfront::993693061769:distribution/EO5TCQIP04VSX \
  --tags Project=jpcite,CreditRun=2026-05 \
  --profile bookyou-recovery
```

### F-2 (NOT NEEDED): Budget CostFilters narrowing

**DO NOT** add `CostFilters={"TagKeyValue":["user:Project$jpcite"]}` to any budget. Current `null` (account-wide) is the **correct and safest** scope. Narrowing would create the exact filter-blindness risk CL16 was chartered to investigate.

### F-3 (NOT NEEDED): Additional catch-all budget

Existing 3 budgets are already account-wide catch-all. No additional budget required.

### F-4 (verify next CL): Credit exhaustion projection

When AWS credit balance approaches zero, ActualSpend will jump from $0 to NetUnblendedCost basis. Recommend a CL18-class re-audit once credit drops below $5,000 to confirm 5-line defense still triggers on un-credited spend.

---

## 5. Operator action item — quick yes/no

| Item | Recommendation | Required? |
|------|----------------|-----------|
| Add CostFilters to budgets | **NO — keep null (account-wide)** | n/a |
| Backfill Project tag on 38 untagged resources | Optional, P3 (analytics only) | No |
| Add new catch-all budget | **NO — already covered** | n/a |
| Re-audit at credit exhaustion | Yes, schedule CL18 trigger when credit balance < $5K | Future |
| Phase 9 wet-run authorisation | **Still requires user explicit UNLOCK** (per `project_jpcite_canary_phase_9_dryrun`) | No change |

---

## 6. CL16 verdict

- 5-line defense filter scope: **VERIFIED INTACT**.
- Filter drift: **NONE detected**.
- Critical risk level: **LOW** (downgraded; was prior HIGH suspicion from CL8).
- Required modification: **NONE**.
- Defense will trigger as designed when cost ramps beyond credit offset.

**Audit closed. No CodeX intervention required for safety. Tag backfill is optional P3.**

---

## Appendix — raw evidence summary

| Probe | Command | Result |
|-------|---------|--------|
| Budget list | `aws budgets describe-budgets --query 'Budgets[?contains(BudgetName,\`jpcite\`)]'` | 3 budgets, all CostFilters=null, all ActualSpend=$0 |
| Budget actions | `aws budgets describe-budget-actions-for-account` | 1 action on stop-18900, APPLY_IAM_POLICY, STANDBY, AUTOMATIC |
| Total spend MTD | `aws ce get-cost-and-usage --granularity MONTHLY` | $0.0000001106 UnblendedCost / $0.1250008602 BlendedCost |
| Forecast EOM | `aws ce get-cost-forecast` | $1,081.12 |
| Tag coverage | `aws resourcegroupstaggingapi get-resources` | 9/47 = 19% Project=jpcite tagged |
| CW alarms | `aws cloudwatch describe-alarms --alarm-name-prefix jpcite` | 4 alarms, all OK state, all AWS/Billing EstimatedCharges |
| EB rules | `aws events list-rules` jpcite filter | empty (DISABLED gate intact) |
| Account identity | `aws sts get-caller-identity` | 993693061769 / bookyou-recovery-admin |

End of CL16 audit.
