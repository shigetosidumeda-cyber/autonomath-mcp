# AWS Canary Operator Quickstart (1 page)

> operator が AWS canary を回す 7 step 実行台本。詳細・rollback・trigger 表は back-link 540 行 runbook 参照。version: 2026-05-16 final / back-link: `docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md` / companion: `docs/_internal/aws_canary_execution_checklist.yaml` / memory: `project_jpcite_rc1_2026_05_16` + `feedback_loop_promote_concern_separation`

## 前提 (READY 条件)
- `site/releases/rc1-p0-bootstrap/preflight_scorecard.json`: `.state == "AWS_CANARY_READY"` (Stream Y 達成済) + `.live_aws_commands_allowed == false` (絶対、step 2 直前維持) + `.cash_bill_guard_enabled == true`
- teardown 30/30 + CF rollback 11/11 + production gate 7/7 全 PASS / `~/.aws/credentials` の `jpcite-canary` profile 設定 / Ed25519 公開鍵 `keys/operator_unlock_pubkey.pem` commit 済 / 推定 **70-100 分** (うち step 5 で 60 分 observe)

## 7 step (copy-paste 用)

```bash
# ---- Step 1: 2 token を同シェル export (シェル終了で消える) ----
export JPCITE_LIVE_AWS_UNLOCK_TOKEN="$(uuidgen)"
export JPCITE_TEARDOWN_LIVE_TOKEN="$(uuidgen)"
```
```bash
# ---- Step 2: live_aws_commands_allowed を false → true へ flip ----
.venv/bin/python3.12 scripts/ops/run_preflight_simulations.py --unlock-live-aws-commands
cat site/releases/rc1-p0-bootstrap/preflight_scorecard.json | jq -r .live_aws_commands_allowed
# 期待値: true
```
```bash
# ---- Step 3: AWS Budget 4 guard を live 作成 (cash_bill_guard 入口) ----
DRY_RUN=false JPCITE_TEARDOWN_LIVE_TOKEN="$JPCITE_TEARDOWN_LIVE_TOKEN" \
  bash scripts/teardown/01_identity_budget_inventory.sh
aws budgets describe-budgets --account-id "$ACCT" --query 'Budgets[].BudgetName'
# 期待値: 4 件 (watch 17K / slowdown 18.3K / no-new-work 18.9K / absolute 19.3K)
```
```bash
# ---- Step 4: canary smoke 1 job submit (最小負荷、< $1 想定) ----
JOB_ID=$(aws batch submit-job --job-name "canary-smoke-$(date +%Y%m%dT%H%M%S)" \
  --job-queue jpcite-canary-q --job-definition jpcite-canary-1m \
  --query 'jobId' --output text)
echo "Submitted job: $JOB_ID"
```
```bash
# ---- Step 5: 1 hour observe + cash_bill_guard 確認 ----
sleep 3600
aws ce get-cost-and-usage \
  --time-period Start=$(date -u -v-1H +%Y-%m-%dT%H:%M:%S),End=$(date -u +%Y-%m-%dT%H:%M:%S) \
  --granularity HOURLY --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"USAGE_TYPE_GROUP","Values":["AWS Credits"]}}'
# 期待値: credit < $5, non-credit exposure = $0, cash_bill_guard 偽発火なし
```
```bash
# ---- Step 6: 4 threshold ENABLED 確認 (17K/18.3K/18.9K/19.3K) ----
for B in watch_17000 slowdown_18300 no_new_work_18900 absolute_19300; do
  aws budgets describe-notifications-for-budget --account-id "$ACCT" --budget-name "$B" \
    --query 'Notifications[].NotificationState'
done
# 期待値: 全 budget 4 件で ENABLED + SNS topic = jpcite-control-plane
```
```bash
# ---- Step 7: teardown (planned shutdown、冪等) ----
DRY_RUN=false RUN_ID=rc1-p0-bootstrap bash scripts/teardown/run_all.sh
bash scripts/teardown/verify_zero_aws.sh
# 期待値: run_all.sh exit 0 + verify_zero_aws.sh で全 service 残存 0 件
```

## abort 条件 (即停止 → emergency kill switch 発火)
以下のいずれか 1 つでも観測したら次 step 進行禁止: (a) `live_aws_commands_allowed` の意図せぬ true [各 step 入口] / (b) smoke job が FAILED / TIMEOUT [step 4] / (c) spend > $5 (credit + non-credit 合算) [step 4-6] / (d) cash_bill_guard 偽発火 (threshold 未達で alarm) [step 5 SNS log] / (e) budget Notification < 4 件 / DISABLED [step 3 / 6]

```bash
JPCITE_EMERGENCY_TOKEN="$(uuidgen)" DRY_RUN=false \
  bash scripts/ops/emergency_kill_switch.sh both
# AWS panic stop (Batch/ECS/Bedrock/OpenSearch/S3 freeze) + CF Pages rollback 同時発火
```

## post-teardown attestation (非 AWS 環境で生成)
1. `site/releases/rc1-p0-bootstrap/teardown_attestation/` を local pull
2. `.venv/bin/python3.12 scripts/check_agent_runtime_contracts.py` で `aws_budget_canary_attestation.json` verify (canonical parity script)
3. SHA256 を `release_capsule_manifest.json.attestations.aws_budget_canary` に追記 → `git commit -s`
4. `curl https://jpcite.com/.well-known/aws-budget-canary-attestation.json` で edge SHA256 一致確認

詳細・各 step rollback・kill switch 用法・進行中断条件・SOT 一覧は back-link 540 行 runbook §3-§8 参照。
