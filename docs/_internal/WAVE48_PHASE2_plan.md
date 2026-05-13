# Wave 48 Phase 2 — 起案 (Plan)

> **Phase 2 plan SOT** for the Wave 48 永遠ループ.
> Hand-off from [`WAVE48_PHASE1_COMPLETE.md`](./WAVE48_PHASE1_COMPLETE.md) (Phase 1 terminal state) +
> [`WAVE48_plan.md`](./WAVE48_plan.md) (live original plan, **not 上書き**) +
> [`INDEX.md`](./INDEX.md) (全 wave doc index).
> 本 doc は **新規 append-only** で、Phase 1 完了宣言 / 元 plan は untouched.
> See [`feedback_destruction_free_organization`](file://~/.claude/projects/-Users-shigetoumeda/memory/feedback_destruction_free_organization.md)
> + [`feedback_overwrite_stale_state`](file://~/.claude/projects/-Users-shigetoumeda/memory/feedback_overwrite_stale_state.md)
> + [`feedback_loop_never_stop`](file://~/.claude/projects/-Users-shigetoumeda/memory/feedback_loop_never_stop.md).

| key | value |
| --- | --- |
| Phase ID | Wave 48 Phase 2 |
| Start (JST) | **2026-05-12 20:19 JST** |
| Predecessor freeze | [`WAVE48_PHASE1_COMPLETE.md`](./WAVE48_PHASE1_COMPLETE.md) |
| Live plan SOT | [`WAVE48_plan.md`](./WAVE48_plan.md) + 本 doc (Phase 2 differential) |
| Cadence | 1 分 cadence × 12 並列 永遠ループ継続 |
| Brand SOT | jpcite (legacy 税務会計AI / AutonoMath / zeimu-kaikei.ai / jpintel は marker 最小表記) |
| Stop condition | user 明示 stop 指示のみ (`feedback_loop_never_stop`) |

---

## § 1. Header

Wave 48 Phase 2 は **2026-05-12 20:19 JST 起動**。Phase 1 で着地した
ingest 軸 (Dim D/E/F/I/J 初期) + 静的 doc + agent funnel 整備 + minimal
gate 設計の上に、本番経済化 4 軸 (100K row scale / x402 LIVE / Wallet
LIVE / Listing 完遂) + AX Layer 4 cron 5 本 + perf_smoke CI gate
hardening を積み増す。

Phase 1 -> Phase 2 transition rule:
- Phase 1 doc は terminal state として freeze、retro-edit 禁止
- 本 plan は **append-only**、Phase 2 progress は別 doc
  (`WAVE48_PHASE2_PROGRESS.md`) で随時 append
- 元 `WAVE48_plan.md` の § 3 / § 4 主題 (G1-G5) を Phase 2 で
  完遂させる位置付け。Phase 1 では G1 (ingest 着地軸) を minimal 達成、
  Phase 2 で 100K row scale + 残 G2-G5 完遂

Phase 2 完了の定義 (`feedback_completion_gate_minimal` ベース):
- 最小 5 gate (G1-G5、§ 4 参照) green
- 40+ 項目 perfect ゲート禁止、漸次 surface は別 wave

---

## § 2. SOT references

Wave 48 Phase 2 系 SOT (参照のみ、上書き禁止):
- [`WAVE48_PHASE1_COMPLETE.md`](./WAVE48_PHASE1_COMPLETE.md) — Phase 1 terminal state, retro-edit 禁止
- [`WAVE48_plan.md`](./WAVE48_plan.md) — 元 plan, append のみ
- [`INDEX.md`](./INDEX.md) — 全 wave doc index
- [`_INDEX.md`](./_INDEX.md) — 補助 index
- [`INDEX_2026-05-05.md`](./INDEX_2026-05-05.md) — 5/5 snapshot
- [`MIGRATION_INDEX.md`](./MIGRATION_INDEX.md) — brand migration 履歴
- `wave48/STATE_*.md` — per-PR state files (現在 `STATE_w48_x402_payment_pr.md`)

外部 / memory SOT:
- `project_jpcite_2026_05_07_state.md` — v95 b1de8b2 LOCKED, 14/14 SUCCESS, openapi v0.3.4 paths=182
- `feedback_loop_never_stop` — 永遠ループ停止禁止
- `feedback_completion_gate_minimal` — gate 5-8 本上限
- `feedback_max_parallel_subagents` — 常に 10+ 並列必須
- `feedback_destruction_free_organization` — rm/mv 禁止、banner+index
- `feedback_dual_cli_lane_atomic` — mkdir 排他 + AGENT_LEDGER
- `feedback_no_priority_question` — 優先順位 / フェーズ / 工数 質問禁止 (Phase 2 marker は SOT 用に許容)
- `feedback_overwrite_stale_state` — historical は superseded marker、上書きせず差分

---

## § 3. Phase 2 主題 (5 軸)

### 3.1 100K row scale (Dim D/E/F/I/J で各 10K+ row 着地)

Phase 1 は ingest 着地軸の足場を作った段階。Phase 2 では 5 dim 全てが
**row count ≥ 10,000** を超え、合計 100K+ row を superseded-free な
real corpus で持つ。

対象 dim と着地基準:
- **Dim D (Predictive snapshot)** — houjin_watch + program_window +
  amendment_diff 結合 snapshot row ≥ 10,000
- **Dim E (Session state)** — state token + saved_context row ≥ 10,000
  (24h TTL 切れ purge 後の running 数)
- **Dim F (Rule tree eval)** — condition branch tree + evaluation
  trace row ≥ 10,000
- **Dim I (Anonymized query)** — k=5 anonymity 通過 query + PII redact
  audit row ≥ 10,000
- **Dim J (Composed tools)** — atomic → wrapped composition call log
  row ≥ 10,000

全 row 共通 metadata (Explainable Knowledge Graph 4 軸 + Ed25519 sign):
- `source_doc` — 一次資料 URL or doc id
- `extracted_at` — UTC isoformat
- `verified_by` — ingest worker id + commit sha
- `confidence` — 0.0-1.0 (heuristic は < 0.7、sourced は ≥ 0.85)
- `ed25519_sig` — Ed25519 sign (key rotation policy は別 doc)

実行 invariant:
- ingest worker は subagent 推論で完結、Operator-LLM API 直叩き禁止
- batch 1,000 row × 10 wave / dim、各 wave 完了で sign + audit log

### 3.2 PROD endpoint LIVE 完成 (x402 5 + Wallet 5 = 10 endpoint LIVE)

#### 3.2.1 x402 5 endpoint LIVE

元 plan § 3.2 の 5 endpoint を Phase 2 で **本番 chain LIVE** 化:
- `POST /x402/houjin/lookup`     — 法人 1 件
- `POST /x402/program/match`     — 制度 match
- `POST /x402/case/cite`         — 判例引用
- `POST /x402/tax/ruleset/eval`  — 税務 ruleset 評価
- `POST /x402/bid/search`        — 入札検索

LIVE 要件:
- 402 response に `X-PAYMENT-REQUIRED: USDC, amount=0.02, chain=base`
- payment proof header 検証 → 200 + JSON body
- decision < 2 秒、$0.001 単位許容、API キー不要
- Stripe ACS + MPP と並走 (`feedback_agent_monetization_3_payment_rails`)

#### 3.2.2 Wallet 5 endpoint LIVE

元 plan は 3 endpoint。Phase 2 で **5 endpoint** に拡張:
- `POST /wallet/topup`         — 前払い credit + auto-topup 設定
- `GET  /wallet/balance`       — 残高 + 直近消費 + 予算残量
- `POST /wallet/alert/config`  — 50% / 80% / 100% threshold
- `GET  /wallet/history`       — top-up + charge 履歴 (auditor 用)
- `POST /wallet/refund`        — over-charged credit の自動返却 / 異議申し立て

threshold 動作 (元 plan 継承):
- 50%: email + dashboard banner、throttle なし
- 80%: + agent header `X-WALLET-WARN: 80`
- 100%: hard throttle (HTTP 402 / `error.code = wallet_exhausted`)

Stripe integration:
- Customer + PaymentMethod + Webhook (charge.succeeded → credit grant)
- idempotency-key 必須、duplicate top-up 防止
- 参照: `feedback_agent_credit_wallet_design`

### 3.3 Smithery / Glama user form 完遂

元 plan § 3.4 は 24h reminder loop + manual click を SOP 化。
Phase 2 では **24h reminder 経過後の manual click 実行**:
- Smithery: jpcite MCP server listing 完了、URL 取得
- Glama: 同上、TTFP / ASR 指標 listing 内開示
- listing URL を `docs/_internal/listings.md` に append (新規 doc)

automation 限界 (再掲):
- form 入力自体 CLI 不可 (CAPTCHA + OAuth wall)
- 「user 操作必要と決めつけ禁止」(`feedback_no_user_operation_assumption`)
  に該当しない: gh CLI / curl / mcp publish では到達不能と verify 済み

### 3.4 AX Layer 4 daily cron 5 本 (Predictive / Session / Composed / Time-machine / Anon)

元 plan § 3.5 の 5 個を Phase 2 で **24h green 連続** 化:
- `cron/predictive_refresh.sh`   — Dim D snapshot 再構築 (24h notify 用)
- `cron/session_gc.sh`           — Dim E TTL 切れ state token purge
- `cron/composed_rebuild.sh`     — Dim J composed_tools/ 再生成
- `cron/time_machine_snap.sh`    — 月次 snapshot 生成 + 5 年保持 trim
- `cron/anon_audit.sh`           — Dim I k=5 anonymity 違反 row 検出

cron 配置:
- GHA schedule + Fly machine internal cron 二重化 (片肺 fail で生存)
- 失敗時 notify は subscription throttle 適用
  (`feedback_github_notification_throttle`)

green criteria:
- 5 cron 全て 24h × 1 周連続 green (= 5 schedule × 24 run = 120 green)
- 1 件でも red → Phase 2 G5 未達

### 3.5 perf_smoke CI gate hardening (deploy chain stability)

Phase 1 で minimal smoke (17/17 mandatory) は green。Phase 2 では
perf 軸を加えた gate hardening:
- p99 latency budget: 制度 search ≤ 350ms / x402 endpoint ≤ 2s /
  wallet endpoint ≤ 500ms
- deploy chain 5 fix 維持 (`feedback_deploy_yml_4_fix_pattern` の
  4 fix + sleep 60s propagation で 5 fix 化、smoke sleep / preflight /
  hydrate / sftp rm idempotency / post-deploy propagation)
- perf_smoke CI gate 失敗時は rollback 自動化、main にマージしない

参照:
- `feedback_post_deploy_smoke_propagation` — 60s+ sleep 必須
- `feedback_deploy_yml_4_fix_pattern` — CI runner 制約 vs prod build flow

---

## § 4. 完了 criteria (gate 5)

| Gate | 内容 | verify cmd / artifact |
|------|------|----------------------|
| G1 | 各 dim row ≥ 10,000 (5 dim 全着地) | `sqlite3 jpcite.db "SELECT dim, count(*) FROM ingest GROUP BY dim;"` 5 行全て ≥ 10000 |
| G2 | x402 5 endpoint LIVE (HTTP 402 chain) | 5 endpoint で `curl POST` → 402 + `X-PAYMENT-REQUIRED` → USDC proof retry → 200 |
| G3 | Wallet 5 endpoint LIVE (auth chain) | top-up / balance / alert / history / refund 全て 200 + Stripe Webhook 連携 |
| G4 | Smithery + Glama listed (2 件) | `docs/_internal/listings.md` に URL 2 本 append |
| G5 | AX Layer 4 cron 5 本 24h green | GHA schedule 5 本 24h 連続 green + Fly internal cron 5 本 log |

非 gate (Phase 2 範囲外、Wave 49+ 漸次):
- AX Layer 5 (federated MCP / embedded copilot scaffold)
- x402 endpoint 5 → 10+ 拡張
- Smithery rank 上位化
- 100K row → 1M row scale
- Time-machine 月次 snapshot 5 年累積

---

## § 5. SOP (1 分 cadence × 12 並列 永遠ループ継続)

ループ運用 (Phase 1 SOP 継承):
- 1 tick = 1 分、tick 毎に 12 subagent 並列着地
- tick 内訳 (例、Phase 2 用):
  - ingest worker × 5 (Dim D/E/F/I/J 各 1) — 100K scale 推進
  - x402 endpoint impl × 2 — 5 endpoint LIVE 化
  - wallet endpoint impl × 2 — 5 endpoint LIVE 化
  - cron impl × 1 — Layer 4 5 本
  - listing reminder × 1 — Smithery / Glama
  - perf_smoke / doc / audit / ledger × 1

停止条件:
- user 明示 stop 指示のみ
- 完了 / エラー / source done でも停止禁止 (`feedback_loop_never_stop`)
- `/loop` 中は ScheduleWakeup を必ず打ち続ける

並列度 (`feedback_max_parallel_subagents`):
- 常に最大数 (10+ 必須、狙い 12-20)
- 8 以下に下がったら下回り扱い、即 ramp-up

排他制御 (`feedback_dual_cli_lane_atomic`):
- mkdir 排他取得 + AGENT_LEDGER append-only

整理原則 (`feedback_destruction_free_organization`):
- rm/mv 禁止、整理は banner + index のみ
- Phase 1 doc は superseded marker 不要 (terminal state declaration 済み)
- 旧 brand (税務会計AI / AutonoMath legacy / zeimu-kaikei.ai / jpintel)
  の前面露出禁止、SEO marker は最小表記 (`feedback_legacy_brand_marker`)

報告:
- 各 tick 完了で memory 更新候補なし (本 plan + `WAVE48_PHASE2_PROGRESS.md` が SOT)
- gate G1-G5 達成毎に `WAVE48_PHASE2_PROGRESS.md` (新規) に append
- Phase 2 全 gate green → `WAVE48_PHASE2_COMPLETE.md` (新規) で freeze
- Wave 49 boot 時に本 doc も superseded marker (上書きせず差分)

---

EOF
