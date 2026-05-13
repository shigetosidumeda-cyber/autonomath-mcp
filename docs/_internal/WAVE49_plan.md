# Wave 49 plan — jpcite

Status: OPEN (start 2026-05-12 21:21 JST)
Author: Claude (Wave 48 tick#10)
Wave 48: COMPLETE (Phase 1 + Phase 2 closed)
Next session: organic funnel measure + listing finalization + AX Layer 5 + first transaction observation

---

## § 1. Header

Wave 49 は Wave 48 の Phase 3 後継として 2026-05-12 21:21 JST に開始。
Wave 48 までで Layer 1 (Access) / Layer 2 (Context) / Layer 3 (Tools) / Layer 4 (Orchestration) の AX 4 柱配備、課金導線 4 step (Stripe ACS + x402 + MPP + Wallet)、Predictive/Session/Composed/Time-machine/Anonymized の Dim K-S 設計完了。
Wave 49 は配備済みインフラに対する **実 user/agent 流入 + 第 1 トランザクション観測 + AX Layer 5 統合 cron** を主題とする。

破壊なき整理整頓ルール準拠 — 既存 doc 上書き禁止、新規 doc のみで前進。

---

## § 2. SOT references

- Wave 48 Phase 2 完了 SOT: [WAVE48_PHASE2_COMPLETE.md](./WAVE48_PHASE2_COMPLETE.md)
- Wave 48 Phase 1 完了 SOT: [WAVE48_PHASE1_COMPLETE.md](./WAVE48_PHASE1_COMPLETE.md)
- Wave 48 plan (original): [WAVE48_plan.md](./WAVE48_plan.md)
- Wave 48 Phase 2 plan: [WAVE48_PHASE2_plan.md](./WAVE48_PHASE2_plan.md)
- Index (master TOC): [INDEX.md](./INDEX.md)
- AX 4 柱 reference: feedback_ax_4_pillars
- agent funnel 6 段: feedback_agent_funnel_6_stages
- Dim K-S 設計: feedback_predictive_service_design / feedback_session_context_design / feedback_composable_tools_pattern / feedback_time_machine_query_design / feedback_anonymized_query_pii_redact / feedback_explainable_fact_design / feedback_federated_mcp_recommendation / feedback_copilot_scaffold_only_no_llm

---

## § 3. Wave 49 主題 5 軸

### 3.1 organic funnel measure (Discoverability → Justifiability → Trustability → Accessibility → Payability)

Wave 48 で課金導線 4 step (landing → docs → /pricing → /signup → /api-keys → first call → topup → x402 first txn) を配備済。
Wave 49 ではこの導線を実 user/agent 流入 で計測 — agent funnel 6 段の conversion rate を初観測。

実施:
- CF Pages RUM beacon (lightweight, no PII) injection in landing + docs + /pricing
- daily aggregator: am_funnel_event_log → am_funnel_conversion_rate
- 6 段別 drop-off heatmap (Discoverability=PV / Justifiability=docs read time / Trustability=/pricing scroll / Accessibility=/signup OAuth / Payability=first topup / Retainability=2nd call)
- SEO/GEO 検索 → AI agent landing → API key issue の流入経路別分解

成功基準: G1 (§ 4.1) 参照。

### 3.2 Smithery + Glama listing finalization (24h gate 残 ~14h)

Wave 48 Phase 2 で Smithery + Glama の listing 申請 form 提出済 (24h moderation gate 中、残 ~14h)。
Wave 49 では user manual click 後の listing 確認 + メタデータ完全性検証。

実施:
- Smithery listing URL 確認 + jpcite tool 151 個 表示確認
- Glama directory entry 確認 + MCP discoverability score 計測
- listing page 内 description / pricing / OAuth flow / x402 endpoint の整合性 audit
- listed 後 first agent invocation log を am_mcp_invocation_log で観測

成功基準: G2 (§ 4.2) 参照。

### 3.3 AX Layer 5 — 統合 cron 5 本配備

Layer 1-4 までは個別配備。Layer 5 は Dim K-S を統合的に駆動する cron infra。

実施:
- cron-1: predictive_window_refresh (Dim K) — 24h 前倒し houjin_watch + program_window 通知 push
- cron-2: session_state_gc (Dim L) — 24h TTL expired session token 廃棄 + saved_context vacuum
- cron-3: composed_tools_metrics (Dim P) — server-side composition 7→1 call 率の daily snapshot
- cron-4: time_machine_snapshot (Dim Q) — 月次 as_of snapshot 取得 (5 年保持の月次 tick)
- cron-5: anonymized_cohort_rebuild (Dim N) — k=5 anonymity cohort 再構築 + PII strip audit

各 cron は Fly machines schedule で 24h green を target。

成功基準: G3 (§ 4.3) 参照。

### 3.4 x402 + Wallet 第 1 トランザクション観測

Wave 48 Phase 2 で x402 PROD endpoint LIVE + Credit Wallet (auto-topup + 50/80/100% alert) 配備済。
Wave 49 では第 1 USDC payment + 第 1 ¥ topup 観測を主題化。

実施:
- am_x402_payment_log を 1 分 cadence で監視 (row count > 0 で alert)
- Stripe webhook → am_credit_transaction_log 連携の end-to-end 検証
- first txn 観測後、txn metadata (amount / source agent / latency / settlement time) を analytics dashboard 化
- 50/80/100% throttle alert の actual fire timing 観測

成功基準: G4 + G5 (§ 4.4 + 4.5) 参照。

### 3.5 残 dim sub-criterion 強化 (Dim N + Dim O)

Wave 48 までは Dim K-S 全体の枠組み配備。Wave 49 では特に network effect 寄与の大きい 2 dim を強化。

実施:
- Dim N (anonymized cohort): k=5 anonymity を k=10 へ厳格化、PII redact regex 拡張 (法人番号 + 個人番号 + 銀行口座 + メールローカル部)
- Dim O (explainable fact): 全 fact metadata に source_doc + extracted_at + verified_by + confidence 4 軸を強制、Ed25519 sign を全 row backfill
- Dim O sign 後の fact 検証 endpoint /v1/fact/verify を新設、agent 側で fact 信頼性を programmatic 検証可能化

成功基準: 5 主題内のサブ KPI として G3 cron + G4 トランザクション層に統合 (個別 gate なし、§ 4 5 gate で評価)。

---

## § 4. 完了 criteria — gate 5 (最低 blocker のみ)

memory feedback_completion_gate_minimal 準拠 — 全項目 green を gate にせず、launch readiness 最低 5 本のみ。

### G1: organic 流入 ≥ 10 unique session/day

CF Pages RUM beacon ログから 24h 連続 で unique session ≥ 10/day を 3 日連続で観測。
SEO/GEO + AI agent landing どちらでも可。bot filter は user-agent + IP heuristic で除外。

### G2: Smithery + Glama listed

Smithery listing page と Glama directory entry 両方で jpcite が公開可視化。
listing URL を docs/_internal/listing_urls.md に追記 (新規)。

### G3: AX Layer 5 cron 5 本 24h green

cron-1 ~ cron-5 全てが 24h 連続成功。失敗 0 回 / retry 0 回。
Fly machines schedule log で確認。

### G4: x402 first USDC payment 観測

am_x402_payment_log の row 数 > 0 (本番 DB)。
amount ≥ $0.001 + settlement < 2 秒 + USDC 着金確認 の 3 条件全 green。

### G5: Wallet first ¥ topup 観測

am_credit_transaction_log の row 数 > 0 (本番 DB)。
Stripe webhook 成功 + topup amount > 0 + balance reflected の 3 条件全 green。

---

## § 5. SOP — 1 分 cadence × 12 並列 永遠ループ継続

memory feedback_max_parallel_subagents + feedback_loop_never_stop + feedback_loop_no_permission 準拠。

- 並列数: 常に最大 (12+ 必須)、狙い 12-20、8 以下は下回り扱い
- cadence: 1 分 tick、ScheduleWakeup 連打必須
- 停止条件: user 明示 stop 指示のみ。完了/エラー/全 source done でも停止禁止
- 戦略判断: user 追認確認せず memory から推論して選択
- 整理: rm/mv 禁止、banner + index で追加配備
- 報告: 380 字以内 で簡潔に、tick 番号 + 主題 + path を必ず含む

---

## § 6. Out of scope (Wave 49 ではやらない)

- Phase 分け / MVP / 工数試算 (memory feedback_no_priority_question + feedback_no_mvp_no_workhours)
- LLM API 直叩き (memory feedback_no_operator_llm_api + feedback_autonomath_no_api_use)
- 旧 brand 露出 (税務会計AI / AutonoMath legacy / zeimu-kaikei.ai) — citation marker 最小のみ (memory feedback_legacy_brand_marker)
- 商標出願 (memory feedback_no_trademark_registration)
- 広告 / 営業投資 (memory feedback_organic_only_no_ads)
- tier 制 SaaS / DPA / 専用 Slack / onboarding call (memory feedback_zero_touch_solo)
- 大規模 refactor / main code 書き換え / 既存 doc 上書き (memory feedback_destruction_free_organization)

---

End of Wave 49 plan.
