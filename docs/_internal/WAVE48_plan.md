# WAVE 48 PLAN

> Status: ACTIVE
> Started: 2026-05-12 18:08 JST
> Cadence: 1 分 / 12 並列 / 永遠ループ
> Author: jpcite operator (Claude Code Max Pro 経由のみ、API 直叩き禁止)

---

## § 1. Header

Wave 48 は Wave 47 Phase 2 完了直後に開始する後継 wave。
Wave 47 Phase 2 で確立した 5 dim × ingest 基盤 / 静的 doc 配備 / agent funnel 整備の上に、
本番経済化 (x402 / Credit Wallet / Smithery / AX Layer 4) を 1 セッションで積み増す。

スコープ宣言:
- main code 大規模 refactor なし
- 旧 brand (税務会計AI / AutonoMath legacy / zeimu-kaikei.ai) 表面化なし
- rm/mv 禁止、整理は banner + index のみ
- Phase / MVP / 工数試算 / スケジュール質問なし (AI が全て回す)
- 完了 gate は最小 5 本 (G1-G5) のみ、それ以上は漸次

---

## § 2. SOT references

Wave 47 系 SOT (上書き禁止、参照のみ):
- `docs/_internal/WAVE47_PHASE2_COMPLETE.md` — Wave 47 Phase 2 終端 state
- `docs/_internal/WAVE47_PHASE2_PROGRESS.md` — Phase 2 進行ログ (plan 相当)
- `docs/_internal/INDEX.md` — 全 wave doc index
- `docs/_internal/_INDEX.md` — 補助 index
- `docs/_internal/INDEX_2026-05-05.md` — 5/5 時点 snapshot
- `docs/_internal/MIGRATION_INDEX.md` — brand migration 履歴

外部 / 横断 SOT (memory 由来):
- `project_jpcite_2026_05_07_state.md` — v95 b1de8b2 LOCKED, 14/14 SUCCESS, openapi v0.3.4 paths=182
- `feedback_destruction_free_organization` — rm/mv 禁止
- `feedback_completion_gate_minimal` — gate 5-8 本上限
- `feedback_no_mvp_no_workhours` — MVP / 工数禁止
- `feedback_no_priority_question` — 「どれから?」「フェーズ」「◯時間」禁句
- `feedback_loop_never_stop` — 永遠ループ停止禁止

---

## § 3. Wave 48 主題 (5 軸)

### 3.1 10K+ row 大規模 ingest (5 dim 全着地)

対象 dim:
- Dim D: Predictive snapshot (houjin_watch + program_window + amendment_diff)
- Dim E: Session state (state token 24h TTL + saved_context)
- Dim F: Rule tree eval (条件分岐 tree JSON + path inject)
- Dim I: Anonymized query (k=5 anonymity + PII redact + audit)
- Dim J: Composed tools (atomic → wrapped, 7 call → 1 call)

着地基準:
- 各 dim row count ≥ 10,000
- 全 row に source_doc + extracted_at + verified_by + confidence の 4 軸 metadata 必須
- Ed25519 sign 付与 (Explainable Knowledge Graph 原則)

実行方式:
- ingest worker は subagent 推論で完結 (Operator-LLM API 呼出禁止)
- batch size 1,000 row × 10 wave、各 wave 完了で metadata sign + audit log

### 3.2 x402 protocol endpoint live (5 endpoint)

対象 endpoint (REST → HTTP 402 → USDC payment → 200 chain):
- `POST /x402/houjin/lookup`     — 法人 1 件 ¥3 相当 USDC
- `POST /x402/program/match`     — 制度 match ¥3
- `POST /x402/case/cite`         — 判例引用 ¥3
- `POST /x402/tax/ruleset/eval`  — 税務 ruleset 評価 ¥3
- `POST /x402/bid/search`        — 入札検索 ¥3

実装仕様:
- 402 response に `X-PAYMENT-REQUIRED: USDC, amount=0.02, chain=base` header
- payment proof header 検証 → 200 + JSON body
- decision 2 秒未満、API キー不要、$0.001 単位許容
- Stripe ACS / MPP と並走 (1 protocol 絞り禁止 — `feedback_agent_monetization_3_payment_rails`)

### 3.3 Credit Wallet endpoint live (3 threshold + Stripe)

endpoint:
- `POST /wallet/topup`         — 前払い credit + auto-topup 設定
- `GET  /wallet/balance`       — 残高 / 直近消費
- `POST /wallet/alert/config`  — 50% / 80% / 100% threshold 設定

threshold 動作:
- 50%: email + dashboard banner (throttle なし)
- 80%: 同上 + agent header `X-WALLET-WARN: 80`
- 100%: hard throttle (HTTP 402 / `error.code = wallet_exhausted`)

Stripe integration:
- Stripe Customer + PaymentMethod + Webhook (charge.succeeded → credit grant)
- idempotency-key 必須、duplicate top-up 防止

参照: `feedback_agent_credit_wallet_design`

### 3.4 Smithery + Glama user form 完遂

- Smithery: jpcite MCP server を listing。manifest + screenshot + tagline 必須項目
- Glama: 同上、評価指標 (TTFP / ASR) を listing 内で開示

automation 限界:
- form 入力自体は CLI 不可 (CAPTCHA + OAuth wall)
- 24h reminder loop + manual click step を SOP 化
- form submit 後 listing URL を `docs/_internal/listings.md` (新規) に append

### 3.5 AX Layer 4 統合 cron (Predictive + Session + Composable + Time-machine)

Layer 4 = AX 4 柱の上に乗る統合 layer。daily cron 5 個:
- `cron/predictive_refresh.sh`   — Dim D snapshot 再構築 (24h notify 用)
- `cron/session_gc.sh`           — 24h TTL 切れ state token purge
- `cron/composed_rebuild.sh`     — composed_tools/ 再生成 (atomic 変更検知)
- `cron/time_machine_snap.sh`    — 月次 snapshot 生成 + 5 年保持 trim
- `cron/anon_audit.sh`           — k=5 anonymity 違反 row 検出 + alert

cron 配置: GitHub Actions schedule + Fly machine internal cron 二重化
失敗時: GHA notify (subscription throttle 適用 — `feedback_github_notification_throttle`)

---

## § 4. 完了 criteria (gate 5)

| Gate | 内容 | verify cmd / artifact |
|------|------|----------------------|
| G1 | 10K+ row × 5 dim 着地 | `sqlite3 jpcite.db "SELECT dim, count(*) FROM ingest GROUP BY dim;"` 全行 ≥ 10000 |
| G2 | x402 5 endpoint live (402 → payment → 200) | `curl -X POST /x402/houjin/lookup` で 402 → USDC proof header 付与 retry → 200 |
| G3 | Credit Wallet 3 threshold trigger | wallet balance を 50/80/100% 跨ぎ → event log 3 件記録 |
| G4 | Smithery + Glama listed (2 件) | listing URL 2 本を `docs/_internal/listings.md` に記録 |
| G5 | AX Layer 4 cron 5 個 daily run | GHA schedule 5 本 green 24h 連続 + Fly cron log 5 本 |

非 gate (漸次):
- 法令 / 判例 / 入札 / 税務 ruleset の row 質的拡充
- Smithery rank 上位化
- x402 endpoint 追加 (5 → 10+)
- AX Layer 5 (federated MCP / embedded copilot scaffold) は Wave 49+

---

## § 5. SOP (1 分 cadence × 12 並列 永遠ループ)

ループ運用:
- 1 tick = 1 分、tick 毎に 12 subagent 並列着地
- tick 内訳 (例):
  - ingest worker × 5 (Dim D/E/F/I/J 各 1)
  - x402 endpoint impl × 2
  - wallet endpoint impl × 1
  - listing form reminder × 1
  - cron impl × 2
  - doc + audit + ledger × 1

停止条件:
- user 明示 stop 指示のみ
- 完了 / エラー / source done でも停止禁止 (`feedback_loop_never_stop`)
- `/loop` 中は ScheduleWakeup を必ず打ち続ける

並列度:
- 常に最大数 (10+ 必須、狙い 12-20) — `feedback_max_parallel_subagents`
- 8 以下に下がったら下回り扱い、即 ramp-up

排他制御:
- mkdir 排他 + AGENT_LEDGER append-only — `feedback_dual_cli_lane_atomic`

整理原則:
- rm/mv 禁止、整理は banner + index — `feedback_destruction_free_organization`
- 旧 wave doc は superseded marker のみ、原本残置

報告:
- 各 tick 完了で memory 更新候補なし (本 plan が SOT)
- gate G1-G5 達成毎に WAVE48_PROGRESS.md (本 plan 後続) に append

---

EOF
