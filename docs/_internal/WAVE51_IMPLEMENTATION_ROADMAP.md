# Wave 51 Implementation Roadmap — L1-L5 timing + deps + blocker tree

**SOT marker**: `docs/_internal/WAVE51_IMPLEMENTATION_ROADMAP.md` (this file)
**status**: ROADMAP ONLY (実装禁止、roadmap doc のみ)
**作成日**: 2026-05-16
**author**: jpcite ops
**precedes**: Wave 51 tick 0 着手 (Wave 50 → Wave 51 transition gate 4 軸 all-clear 後)

---

## 0. 位置付け

Wave 51 は Wave 50 RC1 contract layer (19 Pydantic + 20 JSON Schema + 14 outcome contract + production gate 7/7 PASS + AWS_CANARY_READY) の上に積む **5 軸並列実装** の roadmap doc。本 doc は 3 source design doc を統合し、Day 1-28 の 4 week 範囲で **timing + dependencies + blocker tree** を一望化する。実装着手は Wave 50 → Wave 51 transition gate 4 軸 all-clear 後とし、本 doc では一切実装しない。

破壊なき整理整頓ルール準拠 — 既存 doc 上書き禁止、append-only。Wave 50 historical markers (§Overview の `11,547 programs` / `139 tools` / `146 runtime` / 旧 Wave 21-23/48/49 cohort framing) は引き続き authoritative。

---

## 1. Wave 50 → Wave 51 transition gate

Wave 51 着手は以下 **4 前提** all-clear で start。1 軸でも欠ければ Wave 50 axis の対応 stream へ差し戻す。

| 軸 | 前提条件 | 担当 | 解放 trigger |
| --- | --- | --- | --- |
| A | **Stream G commit landed** — 累計 staged 587+ file (Wave 50 tick 9 時点) が 3 PR (PR1+PR2+PR3 / PR4+PR5 / PR6 final) で commit + push + CI green 一気通貫済、drift 0 化、`.gitignore` 整備済 | user action | git log で 3 PR 着地確認 |
| B | **Stream I AWS canary 実行完了** — Wave 50 tick 9 で flip-ready 化した `AWS_CANARY_READY` scorecard.state を Stream W `--unlock-live-aws-commands` flag 経由で実 side-effect 化、USD 19,490 credit を S3 artifact lake + Batch Playwright drain + Bedrock OCR 実走で消費完了、teardown attestation emit 済 | operator unlock | `aws_budget_canary_attestation` schema emit |
| C | **Wave 49 G1 organic 3 連続 uniq>=10 達成** — Wave 49 G1 aggregator production smoke 後の RUM beacon 実流入計測で **3 営業日連続 uniq visitor >=10** を確認、Discoverability 軸の真の流入 base が立ち上がった signal | organic data | RUM aggregator daily dashboard |
| D | **production gate 7/7 維持** — mypy strict 0 errors + pytest 0 fail + ruff 0 errors + coverage >=75% + preflight 5/5 READY + AWS_CANARY_READY + 7 gate 全 PASS | 自動 (CI) | `release.yml` job green |

**all-clear 判定**: 4 軸全 PASS の朝、`docs/_internal/WAVE51_plan.md` を tick 1 で起票し本 roadmap を baseline として参照する。

---

## 2. 5 軸並列実行計画 (Day 1-28)

### L1: P1 source expansion (Day 1-14)

14 outcome × source family の全 cross product 展開。現 84 entry (14 × 6 family) → **354 entry** (14 × 30 family) に拡張。`outcome_source_crosswalk` 354 entry + `am_source_family_metadata` (migration 105) 30 row seed + 9 新規 cron (月次 6 + 週次 2 + 既存延伸 1) + S3 artifact lake bind で source receipt lake **100K row** 到達。`policy_decision_catalog` も 5 → 30+ entry に拡張、各業法 disclaimer envelope を schema 化。

### L2: 数学エンジン (Day 1-7)

`composed_tools/` dir 直下に sweep / pareto / monte carlo 3 個の MCP tool を追加配備。`src/jpintel_mcp/services/math_engine/` に sweep.py (full-factorial grid + LHS + Sobol) + pareto.py (NSGA-II 風 non-dominated sorting) + montecarlo.py (empirical bootstrap、Bayesian 不使用) + `_common.py` + `_validators.py` + `_scorers/` sub-package。`MathEngineRequest` / `MathEngineResult` / `RankedCandidate` Pydantic を `contracts.py` に追加、egress validation 契約化。tool count 139 → **142** (intentional bump、runtime 146 → 149)、5 manifest surface 同時 v0.4.0 bump。

### L3: AX Layer 6 cron (Day 8-14)

Wave 50 で landed の AX Layer 5 (curated federated MCP + composed_tools + time-machine + anonymized stats + verified facts) の上に Layer 6 = predictive merge + cross-outcome routing を積む。5 cron 配備: (a) `predictive_merge_daily` (Dim K + Dim Q 統合、24h 先 prediction) / (b) `cross_outcome_routing` (14 outcome 間 pairwise score) / (c) `notification_fanout` (email/Slack/webhook 3 channel、PII redact 通過後) / (d) `as_of_snapshot_5y` (月次 60 snapshot、L4 cold archive 連動) / (e) `federated_partner_sync` (freee/MF/Notion/Slack/GitHub/Linear 6 partner curated MCP)。

### L4: PostgreSQL split (Day 15-21)

9.7 GB autonomath.db を PostgreSQL (hot 1M entity 統計層 + recent 30d cohort + active subscriptions + wallet balance + API key、1.2-1.8 GB) + Cloudflare KV/R2 (cold archive 5M facts + 5 年 as_of snapshot 60 本 + historical event log + audit log、7.5-8.5 GB) に物理分離。boot grace 60s 内に収まるよう migration 300 (DDL) + 301 (seed_hot bulk copy) + 302 (R2 seed_cold) + 7 day dual-write phase (drift<0.1% 監視) + cutover commit + fallback (PG fail → SQLite read-only 自動切替)。

### L5: 顧客 pipeline (Day 22-28)

Wave 49 G4/G5 で観測した first txn を real revenue **¥10K-¥100K/month** に育てる。tier 無し、¥3/req 完全従量、Free 3 req/日 (DAU 目的の daily reset)。流入経路 = Smithery/Glama listed + RUM beacon 3 連続 uniq>=10 + x402 first USDC txn + Wallet first ¥ topup + AI mention (Claude/ChatGPT/Perplexity)。funnel metrics: daily uniq visitor 50/day + signup conversion 5% + first paid 20% of signup + 30d retention 60% + ASR>=95% + TTFP<=30min。organic only (memory: feedback_organic_only_no_ads)、tier 制 SaaS / 営業 / DPA / onboarding call 一切提案禁止 (memory: feedback_zero_touch_solo)。

---

## 3. Gantt chart (5 軸 × 4 week ASCII)

```
       Day:  1   3   5   7   9  11  13  15  17  19  21  23  25  27  28
            +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
L1 source   |##########################| (Day 1-14, 30 family + 354 entry + 9 cron + 100K row)
L2 math     |#############|                                            (Day 1-7, sweep/pareto/MC)
L3 AX L6    |             |#############|                              (Day 8-14, 5 cron)
L4 PG split |                            |#############|                (Day 15-21, dual-write 7d → cutover)
L5 revenue  |                                          |##############| (Day 22-28, first ¥10K-100K/mo)
            +---+---+---+---+---+---+---+---+---+---+---+---+---+---+---+
            Week 1        | Week 2        | Week 3        | Week 4
            (L1+L2 並列)   (L1 終盤+L3)   (L4 cutover)    (L5 revenue)
```

凡例:
- `#` = 実行中 / `|` = phase 境界
- L1+L2 = Day 1-7 並列、L1 は Day 8-14 まで延長 (cron smoke + 100K row 達成)
- L3 は L2 着地後の Day 8 開始 (Layer 5 出力を input として消費)
- L4 は L1 全 cron green 後の Day 15 開始 (PG 経由 read への切替)
- L5 は L1/L2/L3/L4 + Wave 49 G1/G2/G4/G5 全達成後の Day 22 開始

---

## 4. Blocker tree (depth 3)

```
L5 ¥10K-100K/month revenue (Day 22-28)
├── L4 cutover (Day 21)
│   ├── L1 全 cron 走行成功 = PG 経由 read (Day 14)
│   │   ├── 30 source_family_id seed (Day 2)
│   │   ├── outcome_source_crosswalk 354 entry (Day 3)
│   │   └── 9 新規 cron smoke (Day 13)
│   └── L3 cron 配置 = Layer 6 5 cron (Day 14)
│       └── L2 数学エンジン landed (Day 7)
│           ├── sweep.py (Day 1-3)
│           ├── pareto.py (Day 3-5)
│           └── montecarlo.py (Day 5-7)
├── L1 source 充実 (Day 14)
│   └── source receipt lake 100K row (Day 14)
└── Wave 49 全達成 (transition gate C 経由)
    ├── G1 organic 3 連続 uniq>=10
    ├── G2 Smithery+Glama listing LIVE
    ├── G4 x402 first USDC txn
    └── G5 Wallet first ¥ topup
```

depth 3 blocker tree。**最深枝**: L5 → L4 → L1 → 30 source_family_id seed (Day 2)。**根 blocker**: L1 Day 2 seed が遅延すると L4 cutover (Day 21) + L5 revenue (Day 28) 連鎖遅延。

---

## 5. 並列可能 vs 順次必須

| 区分 | 軸 | 根拠 |
| --- | --- | --- |
| **並列 OK** | L1 + L2 (Day 1-7) | 両軸とも RC1 contract layer に依存、相互依存無し。L1 = SQLite + ETL 純粋データ追加、L2 = numpy/scipy pure math、独立に進行可。 |
| **順次必須** | L3 ← L2 完了 (Day 8 開始) | L3 cross_outcome_routing は L2 composed math tools を input として消費する単方向依存。L2 5/5 PASS + composed_tools/ landed が gate。 |
| **順次必須** | L4 ← L1 完了 (Day 15 開始) | L4 PG hot path は L1 9 cron が SQLite 経由で 100K row を満たした後の物理分離。dual-write phase 中の drift<0.1% 監視は L1 cron の安定走行を前提。 |
| **順次必須** | L5 ← L1/L2/L3/L4 + Wave 49 全達成 (Day 22 開始) | L5 revenue は (i) source 網羅 (L1)、(ii) justifiable math (L2)、(iii) predictive notification (L3)、(iv) boot grace 60s (L4) + Wave 49 organic 流入 + first txn 観測の 6 軸 all-green が前提。1 軸でも欠けると ¥10K/month gate に到達しない。 |

---

## 6. Risk mitigation

| Risk | 軸 | mitigation |
| --- | --- | --- |
| **R1: 30 source の license 各個審査** | L1 | `am_source_family_metadata.license` 列で `cc_by_4.0` / `pdl_v1.0` / `gov_standard` / `proprietary` を宣言、proprietary は URL link only surface (本文再配信なし)。**5 day buffer** を Day 1-5 に確保し、商用配信は launch 直前再評価 (memory: feedback_data_collection_tos_ignore)。 |
| **R2: L4 cutover failure** | L4 | dual-write 7 day phase 中の drift>0.1% で alert + cutover halt、PG read failure → SQLite read-only **自動切替**、R2 read failure → SQLite archive table fallback、全 fallback で `X-Degraded-Mode: true` header + observability metric。 |
| **R3: L5 organic 不足** | L5 | tier 制 SaaS / 営業導入 **禁止** (memory: feedback_zero_touch_solo)、organic only (memory: feedback_organic_only_no_ads)、¥400k 撤退ライン廃止、評価軸は週 6h cap のみ、organic 流入が立ち上がるまで Wave 51 内では待機継続。Wave 52 持ち越し可。 |
| **R4: monte carlo n_samples=50000 で latency 超過** | L2 | numpy vectorize 徹底 + per-sample 計算を ndarray 演算化、5000 sample で 200ms 上限、50000 sample でも 1s 以内目標、SLA 超過時は `n_samples` を内部 down-sample + summary に `samples_actual` declare。 |
| **R5: 9.7GB DB に quick_check/integrity_check 禁止** | L4 | memory: feedback_no_quick_check_on_huge_sqlite を堅守、size-based skip 維持、`BOOT_ENFORCE_DB_SHA=1` / `BOOT_ENFORCE_INTEGRITY_CHECK=1` は DR drill 時のみ使用、boot grace 60s 内に必ず収める。 |

---

## 7. Exit criteria (Wave 51 closure 5 gate)

| 軸 | gate | 数値目標 |
| --- | --- | --- |
| L1 | outcome × source 354 entry、9 cron 3 day green、`am_source_family_metadata` 30 row seeded、`policy_decision_catalog` 30+ entry | matrix gap 0、cron SUCCESS 3 日連続 |
| L2 | 3 composed tool (sweep / pareto / monte carlo) + tests 100% PASS、`MathEngineRequest/Result/RankedCandidate` round-trip 0 drift、coverage 90%+ | new tests +80、tool count 139 → 142 |
| L3 | 5 cron (predictive_merge / cross_outcome_routing / notification_fanout / as_of_snapshot_5y / federated_partner_sync) 3 day green | cron SUCCESS 3 日連続、PII redact 100% audit log |
| L4 | dual-write drift<0.1% × 7 day → cutover、PG hot 95% row 一致、R2 cold archive seed 完了 | cutover commit + 3 day stable on PG-only |
| L5 | first paid >=1 + 30d retention 開始 + first ¥10K/month revenue 到達 | organic only、tier 制なし、¥3/req fully metered のみ |

closure 後の Wave 52 持ち越し: G6 Retainability (agent funnel 6 段最終)、Dim N+O 1M entity 統計層 moat 化 (k=5 anonymity + Ed25519 sign)、AX Layer 7 (TBD)。

---

## 8. dependencies cross-reference (各軸の input/output)

| 軸 | input (前段) | output (次段) |
| --- | --- | --- |
| **L1** | RC1 contract layer (14 outcome × Wave 50) / `am_source_family_metadata` migration 105 起票 | `outcome_source_crosswalk` 354 entry / source receipt lake 100K row / 9 cron (S3 artifact lake bind) → L3/L4 input |
| **L2** | RC1 contract layer (`MathEngineRequest/Result` Pydantic round-trip) / numpy + scipy 既存依存 | `composed_tools/` 3 MCP tool / tool count 142 / coverage 78%+ → L3 cross_outcome_routing input |
| **L3** | L2 composed_tools/ landed / AX Layer 5 (Wave 50) 5 cron 出力 / Dim K + Dim Q + Dim N 統合 | 5 cron production 配備 / 24h prediction notification / handoff JSON → L5 funnel input |
| **L4** | L1 全 cron 走行成功 (SQLite 経由 100K row) / fallback design (memory: feedback_no_quick_check_on_huge_sqlite) | PG hot path 1.2-1.8 GB / R2 cold archive 7.5-8.5 GB / boot grace 60s 内達成 → L5 SLA 99.9% input |
| **L5** | L1 source 充実 + L2 math justifiability + L3 predictive + L4 SLA + Wave 49 G1/G2/G4/G5 all-green | first ¥10K-¥100K/month revenue / x402+Wallet PROD txn / Smithery+Glama organic flow |

---

## 9. SOT marker + back-link

- **本 doc**: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE51_IMPLEMENTATION_ROADMAP.md` (this file)
- **source doc 1 (Wave 51 plan)**: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE51_plan.md`
- **source doc 2 (L1+L2 design)**: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE51_L1_L2_DESIGN.md`
- **source doc 3 (L3+L4+L5 design)**: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE51_L3_L4_L5_DESIGN.md`
- **Wave 50 RC1 marker**: `/Users/shigetoumeda/jpcite/docs/_internal/project_jpcite_rc1_2026_05_16.md`
- **Wave 49 organic axis (並列)**: `/Users/shigetoumeda/jpcite/docs/_internal/WAVE49_plan.md`
- **canonical jpcir registry**: `/Users/shigetoumeda/jpcite/schemas/jpcir/_registry.json`
- **parity check**: `/Users/shigetoumeda/jpcite/scripts/check_schema_contract_parity.py`
- **memory bindings**: `feedback_composable_tools_pattern` / `feedback_no_operator_llm_api` / `feedback_data_collection_tos_ignore` / `feedback_organic_only_no_ads` / `feedback_zero_touch_solo` / `feedback_no_quick_check_on_huge_sqlite` / `feedback_completion_gate_minimal` / `feedback_destruction_free_organization` / `feedback_overwrite_stale_state` / `feedback_billing_frictionless_zero_lost` / `feedback_agent_funnel_6_stages` / `feedback_ax_4_pillars`

---

last_updated: 2026-05-16
status: roadmap only — implementation BLOCKED until Wave 50 → Wave 51 transition gate 4 軸 all-clear
