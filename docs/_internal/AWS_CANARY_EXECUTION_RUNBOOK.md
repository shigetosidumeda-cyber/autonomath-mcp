# AWS Canary 実行手順書 (Stream I)

> **本書は明文化された runbook であり、実行指示ではない。** 2026-05-16 時点で
> `site/releases/rc1-p0-bootstrap/preflight_scorecard.json.state =
> AWS_BLOCKED_PRE_FLIGHT` のため、本書 step 1 以降の **live 実行は禁止**。
> operator 承認 + state 遷移 (`AWS_CANARY_READY`) 後に 1 step ずつ呼び出すこと。

last_updated: 2026-05-16
companion: `docs/_internal/aws_canary_execution_checklist.yaml`
companion (kill switch): `docs/_internal/launch_kill_switch.md`
companion (teardown): `scripts/teardown/run_all.sh`
companion (CF rollback): `scripts/ops/cf_pages_emergency_rollback.sh`
memory back-link: `project_jpcite_rc1_2026_05_16` (RC1 SOT) / `feedback_loop_promote_concern_separation` (Stream W 概念分離) / `feedback_18_agent_10_tick_rc1_pattern` (18 並列着地パターン)

---

## 0. 本書の射程

本書は AWS クレジット (target USD 19,490) の live canary 実行を 7 step に
分解した「operator が 1 つずつ承認しながら進行」する手順書である。各 step は
**承認待ち = default、進行 = 明示承認後のみ**。途中で `cash_bill_guard` ・
preflight gate ・ smoke 失敗 ・ 残額 USD threshold 突破のいずれかが発生した
時点で **即 step 進行中断 + rollback 手順** へ分岐する。

本書は AWS API 呼び出しを **行わない**。本書を読んだ AI agent / operator が
canary を回す際の **実行台本** にすぎず、本ファイルの追加自体は AWS への
side effect ゼロである。

---

## 1. 前提条件 (preflight)

以下が **全て揃った状態** で初めて step 1 以降に進める。1 つでも欠ければ
**進行禁止**、即 §7「中断判定」へ。

| # | 前提 | 確認方法 | 期待値 |
| --- | --- | --- | --- |
| P-1 | preflight_scorecard が `AWS_CANARY_READY` | `cat site/releases/rc1-p0-bootstrap/preflight_scorecard.json` | `.state == "AWS_CANARY_READY"` |
| P-2 | `live_aws_commands_allowed` は **Stream W unlock 前は false、unlock 後 true** | 同上 | unlock 前: `.live_aws_commands_allowed == false`、Stream W `--unlock-live-aws-commands` 実行後: `.live_aws_commands_allowed == true` (operator authority による明示 unlock) |
| P-3 | `cash_bill_guard_enabled` | 同上 | `.cash_bill_guard_enabled == true` |
| P-4 | 5 budget guards (live deploy 済み) | `aws budgets describe-budgets --account-id $ACCT` (確認のみ; 本書では未実行) | 5 件 (watch 17K / slowdown 18.3K / no-new-work 18.9K / absolute 19.3K / target 19.49K) |
| P-5 | teardown scripts 30/30 PASS | `pytest tests/test_teardown_*.py` | 30 PASS 0 fail |
| P-6 | CF Pages rollback scripts 11/11 PASS | `pytest tests/test_cf_pages_rollback*.py` | 11 PASS 0 fail |
| P-7 | production gate 7/7 PASS | Wave 50 tick 4 完了確認 | 7/7 PASS |
| P-8 | `JPCITE_TEARDOWN_LIVE_TOKEN` **未設定** (canary 投入前) | `env | grep JPCITE_TEARDOWN` | 空 (step 3 で初めて設定) |
| P-9 | `JPCITE_EMERGENCY_TOKEN` **未設定** (kill switch も未武装) | `env | grep JPCITE_EMERGENCY` | 空 (緊急時のみ手動 export) |
| P-10 | aws_budget_canary_attestation schema 存在 | `ls schemas/jpcir/aws_budget_canary_attestation.schema.json` | exists |
| P-11 | operator unlock 公開鍵が repo にコミット済 | `ls keys/operator_unlock_pubkey.pem` (想定 path) | exists、SHA256 が release_capsule_manifest と一致 |
| P-12 | RUN_ID 確定 | `RUN_ID=rc1-p0-bootstrap` (固定) | `rc1-p0-bootstrap` |

**P-1 〜 P-3 のいずれかが期待値外** の場合、本 runbook の以降の step は
**実行不可**。preflight scorecard を `AWS_CANARY_READY` に flip させる作業は
Wave 50 Stream Q の担当範疇であり、本書 step 1 では行わない。

---

## 1.5. Stream W: `--unlock-live-aws-commands` 操作 (canary 実行 path の解錠)

**背景**: Wave 50 tick 8-A の Stream W で、`scripts/ops/run_preflight_simulations.py`
は scorecard 状態の `AWS_CANARY_READY` への promotion と `live_aws_commands_allowed`
の `false → true` flip を **分離** している。promotion は 5/5 preflight gate
PASS を受けて自動進行するが、`live_aws_commands_allowed` の flip は
**operator authority 明示 token** 必須の別 step。これは、scorecard 状態が
"ready" になっても、実 AWS API call は operator が「やる」と明言した瞬間まで
許可しないという 2-stage 設計。

### 前提

- 環境変数 `JPCITE_LIVE_AWS_UNLOCK_TOKEN` を **同シェル内で** export
  (1 回限り、シェル終了で消える)
- token の生成は operator 手元 (`uuidgen` で 1 回 + 紙片メモ程度の運用)
- scorecard.state が **既に** `AWS_CANARY_READY` に flip 済
  (それ未満の状態で本 step を叩いても reject される)

### 実行コマンド

```bash
# step 0: operator が token を export (AI agent は触らない)
export JPCITE_LIVE_AWS_UNLOCK_TOKEN="$(uuidgen)"

# step 1: 5/5 preflight + scorecard promote が既に通っていることを確認
cat site/releases/rc1-p0-bootstrap/preflight_scorecard.json | jq -r '.state, .live_aws_commands_allowed'
# 期待値:
#   AWS_CANARY_READY
#   false   <-- これを true に flip するのが本 step

# step 2: --unlock-live-aws-commands で flip
.venv/bin/python3.12 scripts/ops/run_preflight_simulations.py --unlock-live-aws-commands

# step 3: flip 後の確認
cat site/releases/rc1-p0-bootstrap/preflight_scorecard.json | jq -r '.live_aws_commands_allowed'
# 期待値: true
```

### 効果

- `preflight_scorecard.json.live_aws_commands_allowed`: `false → true`
- `preflight_scorecard.json.live_aws_commands_unlock_authority`: `operator` 追記
- `preflight_scorecard.json.live_aws_commands_unlocked_at`: ISO8601 timestamp 追記
- 本 flip は **1 方向のみ** (revert は別途 operator が手動で false に書き戻す
  か、teardown 完了後の attestation 段で zero 化する)

### 引き換え条件 (本 unlock を発火する gate)

以下が **全て真** の時のみ unlock を許可:

1. **5/5 preflight READY** (`spend_simulation` + `teardown_simulation` 両方
   `pass_state: true` + 3 sibling gate も READY)
2. **scorecard.state == `AWS_CANARY_READY`** (本 runbook P-1 と同義)
3. **operator_signed_unlock 提示** (Ed25519 で署名された `{run_id, intent:
   "live_aws_unlock", expires_at}` payload を `keys/operator_unlock_pubkey.pem`
   で検証 PASS)
4. **JPCITE_LIVE_AWS_UNLOCK_TOKEN 同シェル export 済** (env チェック PASS)

1 つでも欠ければ runner は exit 非 0 で abort、`live_aws_commands_allowed`
は false のまま。

---

## 1.6. AWS canary smoke test 設計 (Stream W unlock 後の実行台本)

Stream W で `live_aws_commands_allowed` が `true` に flip された **後にのみ**
実行可能。本節は実行台本であり、AI agent は本ファイル追加時に AWS API を
**叩かない**。

### Step 1 — Stream W unlock 後の状態確認

```bash
# 必須: live_aws_commands_allowed が true になっていること
cat site/releases/rc1-p0-bootstrap/preflight_scorecard.json | jq -r .live_aws_commands_allowed
# 期待値: true

# 必須: 必要な 2 token + AWS CLI profile が同シェル内に揃っていること
test -n "${JPCITE_LIVE_AWS_UNLOCK_TOKEN:-}" || { echo "abort: unlock token missing"; exit 1; }
test -n "${JPCITE_TEARDOWN_LIVE_TOKEN:-}" || { echo "abort: teardown token missing"; exit 1; }
aws sts get-caller-identity --profile jpcite-canary || { echo "abort: aws CLI/profile missing"; exit 1; }
```

### Step 2 — Identity / Budget inventory を **DRY_RUN=false** で実行

```bash
# 注意: 本 step が **初の実 side-effect 段**。
DRY_RUN=false \
JPCITE_TEARDOWN_LIVE_TOKEN="$JPCITE_TEARDOWN_LIVE_TOKEN" \
  bash scripts/teardown/01_identity_budget_inventory.sh
```

**狙い**: AWS account 内の identity (sts get-caller-identity) と budget 4 guard
が **本当に live 反映されている** ことを 1 度だけ実 call で確認する。本 script
は本来 teardown 5 連の §1 だが、`DRY_RUN=false` でも destructive 操作は
行わない (read-only inventory + attestation 生成のみ)。

### Step 3 — small AWS Batch job 1 個 submit ($1 以内)

```bash
# 1 job のみ、最小負荷 (job definition: jpcite-canary-1m)
JOB_ID=$(aws batch submit-job \
  --job-name "canary-smoke-$(date +%Y%m%dT%H%M%S)" \
  --job-queue jpcite-canary-q \
  --job-definition jpcite-canary-1m \
  --query 'jobId' --output text)
echo "Submitted job: $JOB_ID"

# 必須: $5 ceiling を環境変数で gate
test -n "$JOB_ID" || { echo "abort: submit failed"; exit 1; }
```

### Step 4 — 1 hour observe (cash_bill_guard 発火確認)

```bash
# 1 時間後の確認 (実時計 sleep、agent は別 task に切り替え可)
sleep 3600

# spend を分離取得
aws ce get-cost-and-usage \
  --time-period Start=$(date -u -v-1H +%Y-%m-%dT%H:%M:%S),End=$(date -u +%Y-%m-%dT%H:%M:%S) \
  --granularity HOURLY \
  --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"USAGE_TYPE_GROUP","Values":["AWS Credits"]}}'

# non-credit exposure が $0 (= credit のみで消化) を確認
# cash_bill_guard SNS subscriber log を CloudWatch Logs から取得
aws logs filter-log-events \
  --log-group-name /aws/sns/jpcite-control-plane \
  --start-time $(($(date +%s) - 3600))000 \
  --filter-pattern "cash_bill_guard"
```

**期待値**:
- credit consumption < $5 (smoke 想定値)
- non-credit exposure = $0
- `cash_bill_guard` 偽発火なし (watch 17K threshold に届かないため未発火が正常)

### Step 5 — terminate + cleanup

```bash
# 残存 job が 0 件であることを確認
aws batch list-jobs --job-queue jpcite-canary-q --job-status RUNNING \
  --query 'length(jobSummaryList)'
# 期待値: 0

# canary 完了 attestation 生成 (本書 §7 / step 7 で run_all.sh DRY_RUN=false 経由)
DRY_RUN=false RUN_ID=rc1-p0-bootstrap \
  bash scripts/teardown/run_all.sh
bash scripts/teardown/verify_zero_aws.sh
```

---

## 1.7. canary 実行不可な条件 (abort triggers)

以下のいずれか 1 つでも観測されたら **canary smoke の全 step は実行不可**。
`live_aws_commands_allowed` が true でも、本リストの 1 つに該当した時点で
即 step 進行停止 + §3 rollback chain に分岐。

| # | abort trigger | 観測点 | 分岐先 |
| --- | --- | --- | --- |
| A-1 | `live_aws_commands_allowed == false` (Stream W unlock 未完) | smoke Step 1 入口 | abort、本書 §1.5 の Stream W operation へ戻る |
| A-2 | `JPCITE_LIVE_AWS_UNLOCK_TOKEN` 不在 (env unset) | smoke Step 1 入口 | abort、operator が token を再 export してやり直し |
| A-3 | `JPCITE_TEARDOWN_LIVE_TOKEN` 不在 (env unset) | smoke Step 2 入口 | abort、本書 step 3 へ戻る |
| A-4 | `aws` CLI 不在 / profile 設定不在 (`aws sts get-caller-identity` exit 非 0) | smoke Step 1 入口 | abort、operator が `~/.aws/credentials` 修正 |
| A-5 | `cash_bill_guard_enabled == false` (preflight scorecard) | smoke Step 1 入口 | abort、本書 P-3 へ戻り、guard を arm し直し |

**全 abort 共通の挙動**:
- 1 つでも該当時点で smoke の以降 step は **実行禁止**
- AI agent が判定した場合は人間 operator にエスカレート、AI 単独で
  next-step を進めない
- attestation には `aborted_by: "<trigger-id>"` を残し、`abort_reason` を
  human-readable string で記録

---

## 2. 実行手順 7 step

各 step は **operator が口頭/チャットで明示承認を与えた後にのみ進む**。
AI agent は step 完了後に「次 step 進行可否」を operator に確認すること。

### Step 1 — AWS Budget 4 guard を live 作成

**目的**: 4 段階 (watch 17K / slowdown 18.3K / no-new-work 18.9K / absolute 19.3K)
の budget alarm + auto-action を AWS Budgets API で **実投入**。`cash_bill_guard`
の入口になる。

**コマンド (本書では実行禁止、operator が手動投入)**:

```bash
# 4 軸を逐次投入 (各 budget 投入後に `describe-budgets` で verify)
aws budgets create-budget --account-id "$ACCT" --budget file://budgets/watch_17000.json
aws budgets create-budget --account-id "$ACCT" --budget file://budgets/slowdown_18300.json
aws budgets create-budget --account-id "$ACCT" --budget file://budgets/no_new_work_18900.json
aws budgets create-budget --account-id "$ACCT" --budget file://budgets/absolute_19300.json
# 確認
aws budgets describe-budgets --account-id "$ACCT" --query 'Budgets[].BudgetName'
```

**verify gate**:
- 4 件全てが `describe-budgets` に出現
- `Notifications` が SNS topic にバインドされ、`cash_bill_guard` SNS subscriber
  に届く設定
- attestation を `site/releases/rc1-p0-bootstrap/aws_budget_canary_attestation.json`
  に追記

**中断条件**: `describe-budgets` で 4 件揃わない → §7 へ
**rollback**: 投入済の budget を `aws budgets delete-budget` で逆順削除
(side effect は cost 計測停止のみ、destructive ではない)

---

### Step 2 — operator_signed_unlock を生成 (Ed25519 signature)

**目的**: live AWS 実行を 1 回だけ許可する **operator-signed unlock token** を
生成する。Ed25519 秘密鍵で `{run_id, intent, expires_at}` を署名し、token を
attestation に貼る。秘密鍵は **operator の手元のみ**、AI agent は触らない。

**コマンド (operator のみ)**:

```bash
# Ed25519 sign (秘密鍵 ~/keys/operator_unlock.key は operator の機械にのみ存在)
PAYLOAD=$(printf '{"run_id":"rc1-p0-bootstrap","intent":"canary_smoke","expires_at":"2026-05-16T18:00:00Z"}')
SIG=$(printf '%s' "$PAYLOAD" | openssl pkeyutl -sign \
  -inkey ~/keys/operator_unlock.key -rawin | base64)
echo "OPERATOR_SIGNED_UNLOCK=${PAYLOAD}::${SIG}"
```

**verify gate**:
- 公開鍵 (`keys/operator_unlock_pubkey.pem`) で署名検証 PASS
- `expires_at` が 4 時間以内
- intent が `canary_smoke` (step 4 用) or `teardown` (step 7 用) のいずれか

**中断条件**: 署名検証 NG / expires 過ぎ → §7 へ
**rollback**: token を破棄 (env unset)、新規署名を生成し直し

---

### Step 3 — `JPCITE_TEARDOWN_LIVE_TOKEN` 環境変数を設定

**目的**: `scripts/teardown/run_all.sh` の 2 段ゲート (`DRY_RUN=false` +
`JPCITE_TEARDOWN_LIVE_TOKEN`) のうち、後者を arm する。**この時点でも実行
はしない**、変数 export のみ。

**コマンド**:

```bash
export JPCITE_TEARDOWN_LIVE_TOKEN="$(uuidgen)"   # 1 回限り、シェル終了で消える
# 同シェル内で step 7 まで進める。別シェルに移ると失効する。
```

**verify gate**:
- `env | grep JPCITE_TEARDOWN_LIVE_TOKEN` で 1 行 hit
- `JPCITE_EMERGENCY_TOKEN` は **未設定のまま** (kill switch は別系)

**中断条件**: 同シェル内に他の destructive token が混在 → §7 へ
**rollback**: `unset JPCITE_TEARDOWN_LIVE_TOKEN` でシェル状態を戻す

---

### Step 4 — canary smoke (small batch job 1 個だけ起動 → 成功確認 → terminate)

**目的**: 最小負荷 (1 job, 数分以内, 推定 < $1) で AWS Batch + Bedrock OCR の
pipeline 整合を実検証。フル投入前のスモーク。

**手順**:

1. AWS Batch に 1 job を submit (job queue は `jpcite-canary-q`、job
   definition は `jpcite-canary-1m`)。
2. CloudWatch Logs で `SUCCEEDED` を待つ (timeout 10 分)。
3. job 終了後、`aws batch terminate-job` で残存ジョブが 0 件であることを確認。
4. `cash_bill_guard` (step 5 で観測) と同期するための `RUN_ID` を attestation に記録。

**verify gate**:
- Batch job が `SUCCEEDED` で終わる
- 出力 artifact が S3 (`s3://jpcite-canary/${RUN_ID}/...`) に lands
- 推定 spend < $1 (`aws ce get-cost-and-usage` で粗確認、誤差込み)

**中断条件**: job が FAILED / TIMEOUT / spend > $5 → §7 へ
**rollback**: `scripts/teardown/00_emergency_stop.sh` (JPCITE_EMERGENCY_TOKEN
を arm) で全 batch / ECS / Bedrock を即停止 + CF Pages rollback

---

### Step 5 — observe 1 hour で `cash_bill_guard` トリガー確認

**目的**: step 4 の smoke job が課金イベント lake に届き、`cash_bill_guard`
SNS subscriber が予期通り (非 non-credit exposure では発火しない、non-credit
exposure では発火する) 動作することを確認。

**手順**:

1. 1 時間 sleep (実時計、agent は別 task に切り替えて良いが、本 step の verify は 1h 待つ)。
2. `aws ce get-cost-and-usage --filter '{"Type":"DIMENSION","Key":"USAGE_TYPE_GROUP",...}'` で
   credit / non-credit を分離して合計取得。
3. non-credit exposure が **$0** であることを確認 (credit のみで完結)。
4. SNS subscriber log を確認、`cash_bill_guard` が watch 17K に届かないため未発火が正常。

**verify gate**:
- non-credit exposure = $0
- credit consumption < $5 (smoke 想定値)
- SNS log に `cash_bill_guard` 偽陽性なし

**中断条件**: non-credit exposure > $0 (= credit が 効いていない / 既に枯渇) → §7 へ
**rollback**: step 4 と同じ (`00_emergency_stop.sh` + CF rollback)

---

### Step 6 — 残額 USD threshold 別の動作確認 (17K/18.3K/18.9K/19.3K)

**目的**: 4 段階 budget の状態遷移を **シミュレートではなく実装の挙動**で
確認する。本 step は live を進めるのではなく、**観測** に振る。

**手順**:

1. 各 threshold (17K / 18.3K / 18.9K / 19.3K) の Budgets Notification を
   `describe-notifications-for-budget` で取得、ENABLED 状態を確認。
2. 想定 spend 量から各 threshold までの残額を計算 (target 19,490 USD ベース)。
3. `slowdown` (18.3K) で job parallelism が 半減、`no_new_work` (18.9K) で
   新規 submit が拒否、`absolute_stop` (19.3K) で auto teardown trigger、の
   挙動を **仕様確認のみ** (本 step では実 spend を進めない)。

**verify gate**:
- 4 Budgets Notification 全て ENABLED
- 各 threshold の auto-action target が `jpcite-control-plane` SNS topic
- 残額 = target 19,490 − step 4 smoke spend (推定 < $5)

**中断条件**: Notification の ENABLED フラグが 1 つでも欠ける、SNS bind が
別 topic 化 → §7 へ
**rollback**: 該当 Notification を `update-notification` で正常状態に戻す

---

### Step 7 — teardown 実行 (scripts/teardown/run_all.sh DRY_RUN=false)

**目的**: canary phase の planned shutdown。01..05 の通常 teardown 順序で
attestation を取りつつ、AWS 残存リソースを 0 化する。

**コマンド**:

```bash
# step 3 で arm 済の JPCITE_TEARDOWN_LIVE_TOKEN を同シェルに保持
DRY_RUN=false RUN_ID=rc1-p0-bootstrap \
  bash scripts/teardown/run_all.sh
# 完了後の verify
bash scripts/teardown/verify_zero_aws.sh
```

**verify gate**:
- `run_all.sh` exit 0
- `verify_zero_aws.sh` で全 service の残存 0 件
- `site/releases/rc1-p0-bootstrap/teardown_attestation/run_all.json` の
  全 step exit 0
- 後段 §8 「attestation 取得」で非 AWS 環境からの確認 PASS

**中断条件**: `verify_zero_aws.sh` で残存 1 件以上 → §7 へ (再度 teardown を流す)
**rollback**: teardown は冪等なので **再実行** が rollback。S3 は freeze (DenyAll)
のため object は残るが、cost は 0 化する。完全 cleanup は §8 attestation 後の
operator 判断。

---

## 3. 各 step rollback 手順 (sum-up)

| Step | rollback 主体 | rollback コマンド |
| --- | --- | --- |
| 1 | AWS Budgets | `aws budgets delete-budget --account-id $ACCT --budget-name <name>` 逆順 |
| 2 | local | token 破棄 (env unset, 紙片廃棄) |
| 3 | local | `unset JPCITE_TEARDOWN_LIVE_TOKEN` |
| 4 | AWS Batch / S3 | `scripts/teardown/00_emergency_stop.sh` (要 `JPCITE_EMERGENCY_TOKEN`) + `scripts/ops/cf_pages_emergency_rollback.sh` |
| 5 | 同上 | 同上 (cost 起点で発覚した場合) |
| 6 | AWS Budgets | Notification を `update-notification` で正常化 |
| 7 | teardown 再実行 (冪等) | `DRY_RUN=false bash scripts/teardown/run_all.sh` |

**全 step 共通**:
- CF Pages edge は `scripts/ops/cf_pages_emergency_rollback.sh <prev_capsule>`
- AWS panic stop は `scripts/teardown/00_emergency_stop.sh`
- 両者は **別トークン** (`JPCITE_EMERGENCY_TOKEN` ≠ `JPCITE_TEARDOWN_LIVE_TOKEN`)
  なので、片方が leak しても他方は影響を受けない (2-stage gate 設計)

---

## 4. kill switch 用法

**arm 条件**:
1. `JPCITE_EMERGENCY_TOKEN` を export (1 回限り、シェル終了で消える)
2. `DRY_RUN=false` を明示

**発火コマンド**:

```bash
JPCITE_EMERGENCY_TOKEN="$(uuidgen)" DRY_RUN=false \
  bash scripts/teardown/00_emergency_stop.sh
# Cloudflare Pages も同時に rollback
JPCITE_EMERGENCY_TOKEN="$(uuidgen)" DRY_RUN=false \
  bash scripts/ops/cf_pages_emergency_rollback.sh <prev_capsule_id>
```

**側面効果**:
- AWS: Batch terminate, ECS scale-to-0, Bedrock 解約, OpenSearch 削除, S3 freeze (DenyAll), EC2 terminate
- CF: runtime_pointer.json を rollback 先 capsule に rewrite, edge cache purge, 60s propagation sleep, healthz probe
- 両 attestation は `site/releases/${RUN_ID}/teardown_attestation/` 配下に JSON で残る

**使い分け**:
- 通常 shutdown = step 7 の `run_all.sh` (01..05 ordered)
- panic stop = `00_emergency_stop.sh` (parallel, attestation 簡易)

**安全弁**:
- `00_emergency_stop.sh` は S3 object を **削除しない** (DenyAll で凍結のみ、
  provenance は保つ)。完全削除は別途 operator 判断。

---

## 5. 後片付け attestation 取得手順 (非 AWS 環境で生成)

teardown 完了後、attestation を AWS に依存しない手段で固める。

**手順**:

1. `site/releases/rc1-p0-bootstrap/teardown_attestation/` 配下を local に
   pull (Fly volume or repo に既に commit 済の場合は git pull)。
2. `scripts/check_agent_runtime_contracts.py` を回し、
   `aws_budget_canary_attestation.json` が schema に整合することを確認。
3. attestation JSON の SHA256 を計算し、`release_capsule_manifest.json` の
   `attestations.aws_budget_canary` に追記 (Stream M で 既に枠は用意済)。
4. `git commit -s` でコミット (operator 署名)。
5. Cloudflare Pages の `site/releases/current/runtime_pointer.json` に
   `attestation_sha256` を埋め込み、edge に publish。
6. 非 AWS 環境で `curl https://jpcite.com/.well-known/aws-budget-canary-attestation.json`
   を叩き、edge に流れている JSON と local の SHA256 が一致することを確認。

**verify gate**:
- schema parity check PASS
- SHA256 match between local file ↔ edge response
- operator 署名コミットが main に landed

---

## 6. 進行中断条件 (どの条件で 7 step を止めるか)

以下のいずれか 1 つでも観測されたら **即座に step 進行を停止**、§3 の rollback
へ分岐する。

| トリガー | 観測点 | 分岐先 |
| --- | --- | --- |
| preflight_scorecard が `AWS_CANARY_READY` 以外 | 各 step 入口 | §3 step 1 rollback (= live 投入そのものを止める) |
| `live_aws_commands_allowed == true` への意図せぬ flip | 各 step 入口 | 即 emergency stop |
| canary smoke job が FAILED / TIMEOUT | step 4 verify | step 4 rollback + emergency stop |
| canary spend > $5 | step 4 / 5 / 6 | emergency stop |
| non-credit exposure > $0 | step 5 verify | emergency stop |
| budget Notification が 4 件未満 / DISABLED | step 1 / 6 verify | step 1 rollback |
| `cash_bill_guard` SNS topic に偽発火 | step 5 observe | emergency stop |
| operator_signed_unlock の expires 超過 | 任意 step | step 2 で再発行、live 投入は中断 |
| `verify_zero_aws.sh` で残存 ≥ 1 | step 7 verify | step 7 再実行 (冪等)、3 回 失敗で emergency stop |
| schema parity check FAIL | §8 attestation | local revert + 再生成 |

**Wave 50 Stream Q 完了前** (= 現在 2026-05-16): **全 step が中断対象**。
本書は実行台本としては机上待機、preflight が `AWS_CANARY_READY` に flip
してから初めて step 1 を呼べる。

---

## 7. 関連 SOT

- `site/releases/rc1-p0-bootstrap/preflight_scorecard.json` (state, gates, cash_bill_guard)
- `schemas/jpcir/aws_budget_canary_attestation.schema.json` (attestation contract)
- `site/releases/rc1-p0-bootstrap/aws_budget_canary_attestation.json` (live artifact)
- `scripts/teardown/run_all.sh` (01..05 ordered teardown)
- `scripts/teardown/00_emergency_stop.sh` (panic stop)
- `scripts/teardown/verify_zero_aws.sh` (post-teardown verifier)
- `scripts/ops/cf_pages_emergency_rollback.sh` (edge rollback)
- `docs/_internal/launch_kill_switch.md` (kill switch policy)
- `docs/_internal/aws_canary_execution_checklist.yaml` (本書の機械可読 companion)

---

## 8. 改訂履歴

- 2026-05-16: 初版 (Wave 50 tick 4 直後、preflight = AWS_BLOCKED_PRE_FLIGHT 段階での明文化)
- 2026-05-16 (Wave 50 tick 8-A): Stream W `--unlock-live-aws-commands` 操作節
  (§1.5) + AWS canary smoke test 設計節 (§1.6) + canary 実行不可な条件節 (§1.7)
  を追加。P-2 の期待値を「false 維持」から「Stream W unlock 前 false、unlock
  後 true」に書き換え。scorecard promote と live_aws 解錠の 2-stage 分離を
  明文化。companion YAML に `unlock_step` ブロック + `canary_abort_triggers`
  + `aws_canary_smoke_design` セクション追加。
