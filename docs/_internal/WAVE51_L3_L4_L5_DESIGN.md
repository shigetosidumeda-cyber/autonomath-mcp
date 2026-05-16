# Wave 51 L3 + L4 + L5 設計 doc

**作成日**: 2026-05-16
**status**: DESIGN ONLY (実装は Wave 51 W3-W4 以降)
**前提**: Wave 50 完了 (AX Layer 5 5 cron LIVE / Smithery+Glama xrea 24h gate 通過)
**SOT**: `docs/_internal/WAVE51_L3_L4_L5_DESIGN.md` (this file)

---

## L3: AX Layer 6 cron (predictive merge + cross-outcome routing)

### 目的
Wave 50 の AX Layer 5 (5 cron: curated federated MCP / composed_tools / time-machine / anonymized stats / verified facts) に、より上位の予測統合・横串 routing 層として Layer 6 を追加する。Layer 5 が「データ品質」中心、Layer 6 は「予測 + 配信」中心。

### 新 5 cron

| cron 名 | 担当 dim | 役割 | 頻度 |
|---|---|---|---|
| `predictive_merge_daily` | Dim K + Dim Q | Dim K (predictive houjin_watch / program_window / amendment_diff) と Dim Q (time-machine as_of 月次 snapshot) を merge し、24h 先 prediction を生成。stale な prediction は as_of で時間軸補正 | daily 02:00 JST |
| `cross_outcome_routing` | 全 14 outcome | 14 outcome (補助金 / 取引先 / 法令 / 判例 / 入札 / 税務 ruleset / 助成 / 認定 / 適格事業者 / 法人登記 / 商標 / 特許 / 監査 / コンプラ) 間の関連性を pairwise score 化。e.g., 「補助金 → 取引先 → 法令」の chain 推薦 | daily 03:00 JST |
| `notification_fanout` | Dim K + Dim L | predictive results を email / Slack / webhook の 3 channel に fanout。subscriber view ベース、PII redact 通過後のみ。24h delivery SLA | daily 04:00 JST |
| `as_of_snapshot_5y` | Dim Q | 月次 snapshot を 5 年分 (60 snapshot) 時系列保管。Wave 51 では CF R2 cold archive に逃がす (L4 と連動) | monthly 第 1 日曜 05:00 JST |
| `federated_partner_sync` | Dim R | freee / MF / Notion / Slack / GitHub / Linear 6 partner の curated MCP registry を pull sync。gap → 推奨 handoff JSON を更新 | daily 06:00 JST |

### 配置
- workflow: `.github/workflows/ax-layer-6-predictive-merge-daily.yml` 他 × 5
- script: `scripts/cron/ax_layer_6_predictive_merge.py` 他 × 5
- shared lib: `scripts/cron/_ax_layer_6_common.py` (PII redact / subscriber view / k=5 anonymity)
- 設計原則: LLM API 呼出 0 (memory: `feedback_no_operator_llm_api`)、Claude Code Max Pro 経由のみ

---

## L4: PostgreSQL + Edge KV split

### 目的
9.7 GB `autonomath.db` (legacy 名、現 `jpcite.db`) を boot 時 `quick_check` で 15+ 分 hang させない (memory: `feedback_no_quick_check_on_huge_sqlite`)。Fly grace 60s 内に収めるため hot/cold を物理分離する。

### 分割設計

| Layer | store | 内容 | size 見積 |
|---|---|---|---|
| **hot path** | PostgreSQL (Fly Postgres or Supabase) | 1M entity 統計層 (Dim N) / recent 30 day cohort / active subscriptions / wallet balance / API key | 1.2-1.8 GB |
| **cold archive** | CF KV (small key) + CF R2 (large blob) | 5M facts archive / 5 年 as_of snapshot 60 本 / historical event log / audit log | 7.5-8.5 GB |

### migration
- `scripts/migrations/300_postgresql_split.sql` (DDL + ALTER + index)
- `scripts/migrations/301_postgresql_seed_hot.py` (SQLite → PG bulk copy, recent 30d)
- `scripts/migrations/302_cf_r2_seed_cold.py` (SQLite → R2, archive)
- index: 全 hot table に `(created_at, entity_id)` 複合 index、cohort query 最適化

### dual-write phase
- 7 day 並行書き込み (SQLite + PG 両方に write)
- read は PG 優先、failure 時 SQLite fallback
- diff monitor: 1h ごとに `count(*)` / checksum 比較、drift>0.1% で alert
- 7 day clean なら cutover commit

### fallback (degraded mode)
- PG read failure → SQLite 直 read (read-only)
- R2 read failure → SQLite archive table fallback
- 全 fallback で `X-Degraded-Mode: true` header 返却、observability に metric

---

## L5: 顧客 pipeline

### 目的
Wave 49 G4/G5 で観測した first txn を実際の revenue ¥10K-¥100K/month に育てる。tier 無し、¥3/req 完全従量 (memory: `project_autonomath_business_model`)。

### organic only (広告/営業ゼロ)
memory `feedback_organic_only_no_ads` 厳守。

| 流入経路 | 達成条件 | 期待 uniq/day |
|---|---|---|
| Smithery listed | G2 (xrea 24h gate 通過後) | 5-20 |
| Glama listed | G2 (同上) | 3-15 |
| RUM beacon 3 連続 uniq>=10 | G1 達成後 | 10-30 |
| x402 first USDC txn | G4 達成後 | 1-5 paying |
| Wallet first ¥ topup | G5 達成後 | 1-5 paying |
| AI mention (Claude/ChatGPT/Perplexity) 引用 | Wave 48 cost saving v2 calculator 経由 | 計測中 |

### funnel metrics (memory: `feedback_agent_funnel_6_stages`)
- daily uniq visitor (target: 50/day by Wave 51 end)
- signup conversion rate (target: 5%)
- first paid call conversion rate (target: 20% of signup)
- 30 day retention rate (target: 60% of paying)
- ASR (Agent Success Rate) (target: >=95%)
- TTFP (Time To First Paid call) (target: <=30 min from signup)

### tier なし / solo zero-touch
- memory: `feedback_zero_touch_solo` + `feedback_autonomath_business_model`
- 営業 / CS / 法務 / onboarding call 等の人的介在ゼロ
- 価格は ¥3/req 一本、Free 3 req/day (DAU 目的の daily reset)
- billing frictionless 4 step + 迷子ゼロ (memory: `feedback_billing_frictionless_zero_lost`)

---

## W3-W4 implementation roadmap

| Week | tick 目安 | 対象 | gate |
|---|---|---|---|
| **W3 前半** | tick#1-#3 | L4 PG migration DDL + seed_hot script (実装) | seed 後 PG row count >= SQLite hot 95% |
| **W3 後半** | tick#4-#6 | L4 dual-write phase 開始 (7 day) + L3 predictive_merge_daily cron 1 本実装 | dual-write drift <0.1% / cron green 3 連続 |
| **W4 前半** | tick#7-#9 | L3 残 4 cron 実装 + L5 funnel metrics 計測基盤 (RUM beacon + signup tracker) | 5 cron 全 green / funnel daily uniq>=10 |
| **W4 後半** | tick#10-#12 | L4 cutover + L5 Smithery/Glama 流入実観測 | PG-only operation 3 day stable / first paid >=1 |

### gate 設計原則
memory `feedback_completion_gate_minimal` 準拠、最小 blocker のみ gate 化:
- L3: 5 cron green 3 day 連続
- L4: dual-write drift <0.1% × 7 day → cutover
- L5: first paid call >=1 + 30 day retention 測定開始

---

## Wave 50 → Wave 51 続行性

| 軸 | Wave 50 状態 | Wave 51 で延伸 |
|---|---|---|
| AX Layer | Layer 5 (5 cron LIVE) | Layer 6 (5 cron 追加、Layer 5 と非干渉) |
| storage | SQLite 9.7 GB monolith | PG hot + R2 cold split |
| revenue | x402+Wallet PROD LIVE / first txn 観測 | 実 revenue ¥10K-¥100K/month |
| funnel | G1-G5 gate 設計済 | G2 (Smithery/Glama) + G4/G5 (paid) 実観測 |
| dim K-S | 19/19 mig 完成 (Wave 47) / ETL 16/19 | Dim K + Dim Q merge cron / Dim N 統計層を hot PG に物理分離 |

Wave 50 の AX Layer 5 cron 群はそのまま稼働継続、L4 split 後も hot path 経由で参照。L3 Layer 6 は Layer 5 の出力を input として消費する単方向依存、双方向 coupling は禁止。

---

## SOT marker
- **このファイルが Wave 51 L3/L4/L5 設計の SOT**
- 実装着手時は本 doc を参照、差分は本 doc を更新 (古い state は overwrite、memory `feedback_overwrite_stale_state`)
- 実装完了時に `WAVE51_L3_L4_L5_COMPLETE.md` を作成、本 doc は `historical/` 移管せず superseded marker のみ追記
- 関連 memory: `project_jpcite_wave48_plan` / `project_jpcite_wave49` / `feedback_organic_only_no_ads` / `feedback_autonomath_business_model` / `feedback_no_operator_llm_api` / `feedback_no_quick_check_on_huge_sqlite` / `feedback_completion_gate_minimal` / `feedback_zero_touch_solo`

---

**設計のみ。実装は Wave 51 W3-W4 で別 doc にて開始する。**
