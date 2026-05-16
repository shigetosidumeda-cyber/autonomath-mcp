# R23 (P0) — 5 Preflight Gate の通し方

> AI agent 向け recipe。jpcite の **production deploy readiness gate** は 7/7 で 1 つだけ通過判定だが、その入力となる **5 preflight gate** が独立に評価される。`run_preflight_simulations.py` が 5 gate を順序付き simulation で走らせ、全 PASS で **`AWS_BLOCKED_PRE_FLIGHT → AWS_CANARY_READY`** に scorecard.state が flip する。各 gate は artifact 化され、`release_capsule_manifest.json` に `gate_artifacts[]` として bind。

- **Audience**: 運用者 + AI agent builder (deploy pipeline 経由で起動する agent)
- **Cost**: simulation は dry-run, ¥0
- **Sensitive**: AWS budget canary は実 side-effect を伴うので `--unlock-live-aws-commands` operator token gate 経由でのみ live 化

## TL;DR

```
1. policy_trust_csv_boundaries         → CSV overlay の policy egress 境界が schema 通り
2. accepted_artifact_billing_contract  → 14 outcome の pricing band と ledger contract 整合
3. aws_budget_cash_guard_canary        → AWS budget canary の attestation 存在 + envelope OK
4. spend_simulation_pass_state         → 30 日 spend 想定が cap 内 (SpendSim schema)
5. teardown_simulation_pass_state      → teardown 7 script が dry-run で 30/30 PASS
                          ↓ 全 PASS
preflight_scorecard.state: AWS_BLOCKED_PRE_FLIGHT → AWS_CANARY_READY
                          ↓ operator unlock_step
live_aws_commands_allowed: false → true (user 明示指示のみ)
```

## 5 gate の判定 logic

### Gate 1: `policy_trust_csv_boundaries`

CSV intake preview (R19) から `csv_overlay_public_check` / `cashbook_csv_subsidy_fit_screen` outcome に流す際の egress 境界を check。

- 入力: `schemas/jpcir/csv_private_overlay_contract.schema.json` 準拠の overlay contract
- PASS 条件: column-level egress flag が `raw_value_retained=false` + `public_claim_support=false` + `source_receipt_compatible=false` で 3 軸固定 / PII redact + audit log 必須 column が 11 列以上 enumerate
- FAIL: contract に raw column 1 つでも記載 → `blocked_privacy_taint` 派生

### Gate 2: `accepted_artifact_billing_contract`

14 outcome の `pricing_posture` × `accepted_artifact_pricing` × `billing_event_ledger` の三辺整合 (R18 + R21 + R24)。

- 入力: `outcome_catalog.json` + `schemas/jpcir/accepted_artifact_pricing.schema.json` + `schemas/jpcir/billing_event_ledger.schema.json`
- PASS 条件: ¥300 / ¥600 / ¥900 三段に 14 outcome 全件が分類される / ledger schema が consent_id + scoped_cap_token_id + idempotency_key_sha256 の triple 必須
- FAIL: 14 outcome の `estimated_price_jpy` が price band 外 / ledger row が triple のいずれか欠

### Gate 3: `aws_budget_cash_guard_canary`

AWS budget canary が "発火しても自動 teardown まで届く" 体制を attestation で証明。

- 入力: `schemas/jpcir/aws_budget_canary_attestation.schema.json` 準拠の attestation
- PASS 条件: budget envelope 設定 / SNS topic / teardown role / DRY_RUN smoke 30/30 PASS / `aws_budget_canary_attestation` artifact が capsule に bind / `release_capsule_manifest.json` の `gate_artifacts[]` に登録
- FAIL: attestation 欠 → `AWS_BLOCKED_PRE_FLIGHT` 維持

### Gate 4: `spend_simulation_pass_state`

30 日 spend を **simulate** して cap (Fly + CF + Stripe + AWS canary) 内に収まることを確認。

- 入力: `schemas/jpcir/spend_simulation.schema.json` 準拠 (期間 / projected_yen / cap_yen / 内訳)
- PASS 条件: `projected_total_jpy <= cap_total_jpy` / 各 service ごと cap 内 / 異常 cohort (anonymous 3 req/day 暴走 / cron loop) を含めた worst-case でも cap 越え無し
- FAIL: 1 service でも cap 越え → `blocked_paid_leakage` / `blocked_mosaic_risk` 派生

### Gate 5: `teardown_simulation_pass_state`

`scripts/teardown/*.sh` 7 本が DRY_RUN で 30/30 PASS、`--commit` で実 side-effect 可能な状態を確認。

- 入力: `schemas/jpcir/teardown_simulation.schema.json` 準拠
- PASS 条件: 7 script (`01_identity_budget_inventory.sh` / `02_artifact_lake_export.sh` / `03_batch_playwright_drain.sh` / `04_bedrock_ocr_stop.sh` / `05_teardown_attestation.sh` / `run_all.sh` / `verify_zero_aws.sh`) すべて DRY_RUN PASS、tests/test_teardown_*.py 30 件 GREEN
- FAIL: 1 script でも DRY_RUN error / test red → 即座に `AWS_BLOCKED_PRE_FLIGHT` 固定

## 状態遷移 (state machine)

```
                      ┌────────────────────────────┐
                      │  AWS_BLOCKED_PRE_FLIGHT    │  ← 初期状態 / どれか 1 gate FAIL
                      └────────────┬───────────────┘
                                   │ 5 gate 全 PASS
                                   ▼
                      ┌────────────────────────────┐
                      │  AWS_CANARY_READY          │  ← canary 実行可、ただし
                      └────────────┬───────────────┘     live_aws_commands_allowed=false
                                   │ operator: --unlock-live-aws-commands
                                   │ + token gate
                                   ▼
                      ┌────────────────────────────┐
                      │  live_aws=true (actual)    │  ← user 明示指示後のみ
                      └────────────────────────────┘
```

**絶対条件**: `live_aws_commands_allowed=false` は **scorecard.state とは独立軸**。`AWS_CANARY_READY` でも `live_aws=false` の限り実 side-effect は起きない。`--promote-scorecard` は scorecard.state のみ flip し、`live_aws=true` は別 flag で operator token gate 経由 (Wave 50 tick 7 で concern separation 完了)。

## run_preflight_simulations.py の使い方

```bash
# 1. Dry-run (default) — 5 gate 評価のみ、scorecard は触らない
.venv/bin/python scripts/run_preflight_simulations.py
# => stdout: 5 gate 各 PASS/FAIL + 集約 verdict (AWS_BLOCKED_PRE_FLIGHT or AWS_CANARY_READY)

# 2. Promote scorecard — 全 PASS なら state を AWS_CANARY_READY に flip
.venv/bin/python scripts/run_preflight_simulations.py --promote-scorecard
# 注: live_aws=true は flip しない (Wave 50 tick 7 concern separation 後)

# 3. Unlock live AWS commands — operator token gate (user 明示指示後のみ)
.venv/bin/python scripts/run_preflight_simulations.py \
    --promote-scorecard \
    --unlock-live-aws-commands \
    --operator-token "$OPERATOR_TOKEN"
# => live_aws_commands_allowed: false → true

# 4. Sequence check — 5 gate の順序整合性のみ確認
.venv/bin/python scripts/ops/preflight_gate_sequence_check.py
```

## Error handling

| FAIL gate | reject reason | 対処 |
|---|---|---|
| Gate 1 | `csv_overlay_raw_column_leak` | overlay contract から raw column 削除 |
| Gate 2 | `outcome_price_band_drift` | outcome の `estimated_price_jpy` を ¥300/¥600/¥900 に整合 |
| Gate 3 | `aws_canary_attestation_missing` | attestation artifact 生成 + capsule 登録 |
| Gate 4 | `spend_cap_exceeded` | cap 引き上げ or cohort throttle |
| Gate 5 | `teardown_dry_run_fail` | 該当 script の dry-run fix + 30 test 再実行 |

## 関連

- [R22 — Release Capsule Manifest](r22_release_capsule_manifest.md) (gate_artifacts[] の bind 先)
- [R24 — billing_event_ledger](r24_billing_event_ledger.md) (Gate 2 の ledger 軸)
- [R25 — Evidence + ClaimRef + SourceReceipt](r25_evidence_claim_receipt.md)
- [R20 — 17 PolicyState](r20_policy_state.md) (Gate 1 派生 policy)
- runner: `scripts/run_preflight_simulations.py`
- sequence check: `scripts/ops/preflight_gate_sequence_check.py`
- schemas: `schemas/jpcir/{spend_simulation,teardown_simulation,aws_budget_canary_attestation,csv_private_overlay_contract,billing_event_ledger}.schema.json`
- runbook: `docs/runbook/aws_canary_quickstart.md`
