# Wave 51 plan — jpcite

Status: OPEN (planned start: Wave 50 RC1 launch 後)
Author: Claude (Wave 50 tick#9 transition)
Wave 50: RC1 contract layer complete + 7/7 production gate PASS + Stream A 5/5 preflight READY + AWS_CANARY_READY flip-ready
Next milestone: AWS factory 実走 + P1 source expansion + 数学エンジン + AX Layer 6 + PostgreSQL+Edge KV split + 顧客 pipeline 実 txn 観測

---

## § 1. Header

Wave 51 は Wave 50 RC1 launch 後の next milestone として開始される。
Wave 50 までで 19 Pydantic contracts + 20 JSON Schema + 14 outcome contracts + AWS teardown 7 script + CF Pages rollback 5 script + production deploy readiness gate 7/7 PASS + mypy strict 0 errors + coverage 76-77% + Stream A 5/5 preflight artifact READY + scorecard AWS_CANARY_READY を達成。
Wave 49 organic axis は G1 RUM beacon LIVE + G3 5 cron all SUCCESS + G4/G5 schema ready + first txn 待機。
Wave 51 は Wave 50 RC1 が launch 後、配備済み 19,490 USD AWS credit を実走させ、P1 source expansion を 14 outcome × source family 全 cross product で展開する。

破壊なき整理整頓ルール準拠 — 既存 doc 上書き禁止、新規 doc のみで前進、historical marker は append-only。

---

## § 2. SOT references

- Wave 50 SOT (RC1 contract layer + 5 preflight gate): `/Users/shigetoumeda/jpcite/CLAUDE.md` Wave 50 section + tick 1-9 completion log
- Wave 50 RC1 marker: `/Users/shigetoumeda/jpcite/docs/_internal/project_jpcite_rc1_2026_05_16.md`
- Wave 49 plan: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE49_plan.md`
- Wave 49 G1 operator runbook: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE49_G1_OPERATOR_RUNBOOK.md`
- Wave 49 G2 registry escalation draft: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE49_G2_REGISTRY_ESCALATION_DRAFT.md`
- AWS canary execution runbook: `/Users/shigetoumeda/jpcite/docs/_internal/AWS_CANARY_EXECUTION_RUNBOOK.md`
- AWS canary execution checklist: `/Users/shigetoumeda/jpcite/docs/_internal/aws_canary_execution_checklist.yaml`
- AWS credit acceleration plan: `/Users/shigetoumeda/jpcite/docs/_internal/aws_credit_acceleration_plan_2026-05-15.md`
- jpcir registry index: `/Users/shigetoumeda/jpcite/schemas/jpcir/_registry.json`
- contract parity check: `/Users/shigetoumeda/jpcite/scripts/check_agent_runtime_contracts.py` (canonical Pydantic ↔ JSON Schema round-trip parity script, formerly referenced as `check_schema_contract_parity.py`)
- AX 4 柱 + Dim K-S 設計: memory feedback_ax_4_pillars / feedback_predictive_service_design / feedback_session_context_design / feedback_composable_tools_pattern / feedback_time_machine_query_design / feedback_anonymized_query_pii_redact / feedback_explainable_fact_design / feedback_federated_mcp_recommendation

---

## § 3. 前提条件 (Wave 51 開始 gate)

Wave 51 は以下 4 条件を全て満たした時点で開始する:

1. **Stream G commit landed** — Wave 50 tick 9 までで累計 staged 587+ file が 3 PR (PR1+PR2+PR3 / PR4+PR5 / PR6 final) に分割 commit + push + CI green 一気通貫済。drift 0 化、`.gitignore` 整備済。
2. **Stream I AWS canary 実行完了** — Wave 50 tick 9 で flip-ready 化した `AWS_CANARY_READY` scorecard.state を Stream W `--unlock-live-aws-commands` flag 経由で実 side-effect 化、USD 19,490 credit を S3 artifact lake + Batch Playwright drain + Bedrock OCR 実走で消費完了。teardown attestation emit 済。
3. **Wave 49 G1 organic 3 連続 uniq>=10 達成** — Wave 49 G1 aggregator production smoke (tick 9) 後の RUM beacon 実流入計測で 3 営業日連続 uniq visitor >=10 を確認、Discoverability 軸の真の流入 base が立ち上がった signal。
4. **production gate 7/7 維持** — Wave 50 tick 6-9 で再達成した 7/7 production deploy readiness gate を Wave 51 開始時点でも維持、mypy strict 0 errors + pytest 0 fail + ruff 0 errors + coverage >=75%。

---

## § 4. Wave 51 主題 5 軸

### 4.1 L1: P1 source expansion (broad outcome × source family pairing)

14 outcome × source family の全 cross product 展開。Wave 50 で 14 outcome contracts (`estimated_price_jpy` ¥300-¥900 band) を確立、Wave 51 では各 outcome を source family と直交 pair 化し、broad outcome coverage を獲得する。
実施:
- 14 outcome × N source family の matrix 定義 (jpintel.db + autonomath.db 横断 source family)
- source receipt lake 100K row target (S3 artifact lake bind)
- outcome_source_crosswalk TKC 拡張 (Wave 50 tick 4 Stream P で base 確立済)
- cross product gap audit + 欠落 outcome × source pair backfill cron

### 4.2 L2: 数学エンジン (sweep / pareto / monte carlo)

Wave 50 で 5 高 impact module (intel_wave31 / composition_tools / pdf_report / intel_competitor_landscape / realtime_signal_v2) を coverage 加速、Wave 51 では数学エンジン 3 軸 (parameter sweep / Pareto frontier / Monte Carlo simulation) を composed_tools/ dir に追加配備、agent funnel 6 段の Justifiability/Trustability 軸の根拠強化。
実施:
- `composed_tools/sweep_param_grid.py` — outcome contract parameter space sweep
- `composed_tools/pareto_frontier.py` — multi-objective Pareto 抽出
- `composed_tools/monte_carlo_sim.py` — Monte Carlo eligibility/payoff sim (純 SQLite + Python、NO LLM 推論)

### 4.3 L3: AX Layer 6 cron (predictive merge / cross-outcome routing)

Wave 48 で AX Layer 1-4 (Access / Context / Tools / Orchestration) 配備、Wave 49 で Layer 5 (curated federated MCP + composed_tools + time-machine 統合)、Wave 51 で **Layer 6 = predictive merge + cross-outcome routing** へ進む。
実施:
- predictive merge cron — Dim K (predictive service) + Dim Q (time-machine) を 1 cron に merge、24h notification + as_of param fan-out
- cross-outcome routing — 14 outcome 間の handoff edge を server-side composition で expand、7→1 call 化

### 4.4 L4: PostgreSQL + Edge KV (autonomath.db 9.7 GB → split)

autonomath.db 9.7 GB は boot 時 quick_check 禁止 (memory: feedback_no_quick_check_on_huge_sqlite) で fly.toml 事前警告を踏み抜いた歴史を持つ。Wave 51 では PostgreSQL (hot 1M entity 統計層) + Edge KV (cold 5M facts archive) の 2 層 split を実施、boot grace 60s 内で起動可能化。
実施:
- PostgreSQL 移行対象 = 1M am_entities 統計層 + 6.12M am_entity_facts の hot path
- Edge KV (Cloudflare KV / R2) = cold archive (am_amendment_snapshot 14,596 + am_amount_condition 250,946 + 過去 5 年 snapshot)
- migration plan = read-only mirror から段階移行、production 破壊なし
- view + symlink + env 両併存 (memory: project_jpcite_internal_autonomath_rename pattern)

### 4.5 L5: 顧客 pipeline (Wave 49 G4/G5 real txn observation → 売上 ¥10K-¥100K/month)

Wave 49 G4/G5 schema (x402 micropayment + Credit Wallet topup ledger) を実流入計測 (Wave 49 G1 aggregator landing 後) に bind、first real txn 観測から ¥10K-¥100K/month 売上立ち上げ。Wave 51 終了時点で G5 first ¥10K/month revenue 達成を gate target。
実施:
- Wave 49 G1 RUM beacon production smoke → G2 listing 3 registry LIVE → G3 5 cron 連動 → G4 x402 first txn → G5 Wallet topup
- 課金導線 4 step + 迷子ゼロ (memory: feedback_billing_frictionless_zero_lost) 50% → 100% 化
- organic only (memory: feedback_organic_only_no_ads)、広告/投資ゼロ、tier 制 SaaS 提案禁止 (memory: feedback_zero_touch_solo)

---

## § 5. non-goal (Wave 51 で取り組まない)

以下は Wave 51 scope 外、明示的に **やらない**:

- **LLM API 自前呼出** — operator ETL も API 直叩き禁止、Claude Code Max Pro 経由のみ。memory: feedback_no_operator_llm_api。`tests/test_no_llm_in_production.py` の CI guard 維持。
- **tier 制 SaaS / 営業チーム / DPA / Slack Connect / onboarding call** — solo + zero-touch 原則、人的介在機能は提案禁止。memory: feedback_zero_touch_solo。¥3/req fully metered のみ。
- **広告 / 投資 / 有料獲得** — 100% organic、SEO/GEO のみ。memory: feedback_organic_only_no_ads。¥400k 撤退ライン廃止済、評価軸は週 6h キャップのみ。
- **「優先順位どれから?」「◯時間かかる」「フェーズ分け」「MVP」** — 全部禁句。memory: feedback_no_priority_question。AI が全部やるから時間関係ない、質問は「やる/やらない」の二択のみ。
- **巨大 SQLite に boot 時 quick_check / PRAGMA integrity_check / sha256sum** — memory: feedback_no_quick_check_on_huge_sqlite。L4 split で根本解消。

---

## § 6. 4 week deliverables

### Week 1 deliverables

- AWS factory 実走完了 — USD 19,490 credit を S3 artifact lake + Batch Playwright drain + Bedrock OCR 実走で消費、teardown attestation emit
- source receipt lake **100K row** 達成 (S3 artifact lake bind)
- 14 outcome × source family **全 cross product** 配備 (matrix gap 0)

### Week 2 deliverables

- P1 production deploy — 14 outcome × source family cross product を production OpenAPI + MCP に同時公開
- composed_tools/ dir に sweep / pareto / monte carlo 3 数学エンジン landed
- L3 AX Layer 6 cron (predictive merge + cross-outcome routing) production 配備

### Week 3 deliverables

- real customer onboarding (organic only) — Wave 49 G1 3 連続 uniq>=10 達成後の organic 流入を G2 listing LIVE 経由で API key issue → G4 first txn まで誘導
- L4 PostgreSQL 移行 hot path (1M entity 統計層) 完了
- L4 Edge KV cold archive 移行 (am_amendment_snapshot + am_amount_condition + 過去 5 年 snapshot) 完了

### Week 4 deliverables

- Dim N+O moat 完成 — 1M entity 統計層 anonymized query (k=5) + PII redact + audit log + Ed25519 sign + source_doc/extracted_at/verified_by/confidence 4 軸 metadata 全 fact 必須化
- G5 first ¥10K/month revenue 達成 (organic only、tier 制なし)
- production deploy readiness gate 7/7 維持 + canary teardown attestation 第 2 サイクル emit

---

## § 7. 5 gate (Wave 51 closure 判定)

Wave 51 closure は agent funnel 6 段の上位 5 軸 (Discoverability → Justifiability → Trustability → Accessibility → Payability) で gate する。Retainability は Wave 52 持ち越し。

### G1: Discoverability — organic 30+ uniq/day × 7 day

Wave 49 G1 RUM beacon LIVE + aggregator production smoke 後の organic 流入が **30+ uniq visitor/day × 7 営業日連続** で安定。SEO/GEO 検索 → AI agent landing → docs/pricing/signup 経路の funnel 第 1 段を真値計測で確認。

### G2: Justifiability — listing 3 registry LIVE

Smithery + Glama + 第 3 registry (PulseMCP / mcp.so / Awesome MCP 等) の **3 registry LIVE** + 各 registry での detail page 公開 + outcome contract 14 件の `estimated_price_jpy` 表示。docs/canonical/ 配下の正本 doc が AI agent から citation 可能。

### G3: Trustability — production gate 7/7 + canary teardown attestation

production deploy readiness gate **7/7 PASS 維持** (mypy strict 0 / pytest 0 fail / ruff 0 / coverage >=75% / contract parity 0 drift / OpenAPI sync / preflight scorecard `AWS_CANARY_READY` 以上)。AWS canary teardown attestation 第 1+第 2 サイクル emit、`aws_budget_canary_attestation` schema bind 維持。

### G4: Accessibility — 4 P0 facade 99.9% SLA

4 P0 facade tool (OpenAPI + `llms.txt` + `.well-known` 3 surface 同時公開) が **99.9% SLA** 維持、`scripts/sync_p0_facade.py` check が daily SUCCESS。Fly Tokyo + CF Pages + DNS の 3 層 cache window でも 60s+ propagation で false negative 0。

### G5: Payability — first ¥10K/month revenue

x402 micropayment + Credit Wallet topup 経由の **first ¥10K/month revenue 達成** (organic only、広告/営業ゼロ)。billing_event_ledger append-only contract で trace 可能、idempotency_cache + usage_events.client_tag double-entry 維持。tier 制なし、¥3/req fully metered のみ。

---

last_updated: 2026-05-16

---

## § 8. tick 0 COMPLETE 2026-05-16 (append-only)

Wave 51 tick 0 はこの日着地。Wave 50 RC1 LANDED (Stream G + Cleanup + FINAL closeout `d7f57d355`) の直後に、Wave 51 の足場として以下が同 session で連続着地した。`docs/_internal/WAVE51_DIM_K_S_CLOSEOUT_2026_05_16.md` (`e9b33583d`) が SOT、本節はそれを Wave 51 plan 側に bind するための index。

### tick 0 deliverables

- **9/9 dim K-S landed** — Dim K (predictive_service) / L (session_context) / M (rule_tree) / N (anonymized_query) / O (explainable_fact) / P (composable_tools) / Q (time_machine) / R (federated_mcp) / S (copilot_scaffold) 全 9 module が `src/jpintel_mcp/{module}/` 配下に landed。各 module は LLM API 呼出 0 (memory: `feedback_no_operator_llm_api`)、`¥3/req` 単価経済を破らない pure deterministic computation のみ。
- **L1/L2 foundational landed** — L1 = `src/jpintel_mcp/l1_source_family/` source-family catalog (`90c4be54f`)、L2 = `src/jpintel_mcp/services/math_engine/` sweep + applicability scoring (`b81839f69`)。`docs/_internal/WAVE51_IMPLEMENTATION_ROADMAP.md` の L1+L2 foundational (Day 1-7 範囲) の初期足場を着地、本格 cross-product 拡張 (L1 354 entry / L2 sweep+pareto+monte carlo) は L3-L5 着手前の延伸 stream。
- **416 tests PASS** — 11 module (9 dim + L1 + L2) の `tests/test_{module}.py` を `pytest -q` 一括で **416 PASS in 3.38s**。回帰 0、新 module の type-driven coverage 確立。
- **mypy strict 0 + no-LLM 9/9 PASS** — `mypy --strict src/jpintel_mcp/{11 modules}/` が **Success: no issues found in 41 source files**、`tests/test_no_llm_in_production.py` が **9/9 PASS** で `anthropic` / `openai` / `claude_agent_sdk` 等 LLM SDK import が 11 module 全件 0 を構造的に証明。Wave 50 で堅守した mypy strict 0 / no-LLM invariant を Wave 51 tick 0 でも継承。
- **All 6 smoke endpoints 200 (jpcite.com live)** — production smoke 6 endpoint (`/healthz` / `/v1/programs/search` / `/v1/laws/search` / `/v1/cases/search` / `/v1/loans/search` / `/v1/enforcement/search` 系統) が **6/6 = 200 LIVE** を `https://jpcite.com` apex で確認。CF Pages → Fly Tokyo の 2 hop が p99 60s+ propagation 内で安定、Wave 50 RC1 の production gate 7/7 を Wave 51 tick 0 でも維持。

### Wave 51 における tick 0 の位置付け

tick 0 は本 plan §4 の 5 軸 (L1 / L2 / L3 / L4 / L5) のうち L1 + L2 を foundational layer として先行着地し、Dim K-S (9 dimension) を **そこに plug-in する素地** を整える tick として設計された。本 plan §6 の Week 1-4 deliverables は tick 1 以降の本格走行で達成、tick 0 は roadmap §2 の Day 1-7 範囲 foundational layer に該当。

- L1 foundational landed → L1 P1 source expansion (`outcome_source_crosswalk` 354 entry 拡張) は tick 1+ で延伸
- L2 foundational landed → L2 数学エンジン (sweep + pareto + monte carlo 3 軸 full set) は tick 1+ で延伸
- Dim K-S 全 9 module landed → L3 AX Layer 6 cron (predictive merge + cross-outcome routing) の素材 ready、Wave 50 → Wave 51 transition gate 4 軸 all-clear 後に tick 1 で起票
- L4 / L5 は tick 0 では着手せず、roadmap §2 の Day 15-28 範囲で別 tick

### tick 0 で **やらない** (Wave 51 non-goal の再確認)

本 plan §5 の non-goal を tick 0 でも全件踏襲:

- **Wave 51 を tick 0 で「done」と宣言しない** — tick 0 は foundational layer 着地のみ。L1 cross-product 拡張 / L2 数学エンジン full set / L3 5 cron / L4 PG split / L5 ¥10K/月 revenue は tick 1+ で着地する別 tick の責務。
- **LLM API 自前呼出** — 11 module 全件で `anthropic` / `openai` / `claude_agent_sdk` import 0、`tests/test_no_llm_in_production.py` 9/9 PASS で構造保証 (memory: `feedback_no_operator_llm_api`)。
- **tier 制 SaaS / 営業 / DPA / Slack Connect / onboarding call** — solo + zero-touch 原則堅持 (memory: `feedback_zero_touch_solo`)、¥3/req fully metered のみ。
- **広告 / 投資 / 有料獲得** — 100% organic only、SEO/GEO のみ (memory: `feedback_organic_only_no_ads`)。
- **巨大 SQLite に boot 時 quick_check / PRAGMA integrity_check / sha256sum** — memory: `feedback_no_quick_check_on_huge_sqlite` 堅守、L4 split は tick 1+ で別軸対応。

### cross-reference (tick 0 SOT artifacts)

- **tick 0 SOT**: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE51_DIM_K_S_CLOSEOUT_2026_05_16.md` (`e9b33583d`)
- **L1 foundational commit**: `90c4be54f` (`feat(l1-source-family): catalog registry of public-program data sources`)
- **L2 foundational commit**: `b81839f69` (`feat(l2-math): implement L2 applicability + spending forecast scoring`)
- **9 dim landing commits**: `1421d3ea3` K / `387cc0f50` L / `dd90361ba` M / `fc20796f9` N / `2112e75a5` O / `6ec9232f7` P / `8b2ac08a9` Q / `f12c160e4` R / `7802e07de` S
- **AWS damage inventory** (Wave 50 closeout 後 follow-up): `docs/_internal/AWS_DAMAGE_INVENTORY_2026_05_16.md` (`a51c988e1`)
- **Wave 50 RC1 FINAL closeout**: `docs/_internal/WAVE50_RC1_FINAL_CLOSEOUT_2026_05_16.md` (`d7f57d355`)
- **roadmap**: `docs/_internal/WAVE51_IMPLEMENTATION_ROADMAP.md` (Day 1-28 Gantt + blocker tree)

### tick 0 metric snapshot

| metric | tick 0 着地値 |
| --- | --- |
| dim K-S landed | **9/9** |
| L1/L2 foundational | **2/2** (L1 catalog + L2 sweep/scoring) |
| pytest (11 module) | **416 PASS in 3.38s** |
| mypy --strict (41 source files) | **0 errors** |
| no-LLM invariant | **9/9 PASS** |
| production smoke endpoints | **6/6 = 200** (jpcite.com live) |
| commits landed this session | **~21 commits** |
| production gate 7/7 | **維持** (Wave 50 RC1 継承) |
| `live_aws_commands_allowed` | **false (絶対)** |

tick 0 は Wave 51 plan §4 の 5 軸を着地させる tick ではなく、5 軸を着地させるための **foundational substrate + dimension plug-in 素材** を揃える tick として位置付ける。本格走行は tick 1+ で別 plan / roadmap に沿って実施する。

last_updated: 2026-05-16
