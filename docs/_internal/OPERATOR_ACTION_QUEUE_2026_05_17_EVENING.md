# Operator Action Queue — 2026-05-17 Evening (yes/no SOT)

> 翌朝起きた瞬間 paste/click で flip できる single SOT. すべての項目は **yes/no 二択 only** (`feedback_no_priority_question` 厳守). 優先順位 / 工数 / コスト / スケジュール質問は一切無し.
>
> Lane: `[lane:solo]` / Author: Claude Opus 4.7 / Sources: 11 audit doc (CL6/CL7/CL8/CL10/CL11/CL12/CL14/CL16/CL17/CL18/CL19) consolidated 2026-05-17 evening.
> Posture: READ-ONLY scan; this is the queue. Apply lanes are separate.

---

## Section 1 — 翌朝起きた時の "最初に flip" 5 件 (即実行可能)

5 件すべて yes/no 二択. 回答後 CodeX に Step 0-10 自走指示できる構造.

| # | Action | Effect on yes | Source | yes/no |
|--:|---|---|---|:-:|
| F1 | `preflight_scorecard.json` を **re-lock** (`live_aws_commands_allowed=false`) し 7/7 production gate 復元? | gate Fail #2 + #7 が **同時 PASS** (1 JSON edit). Fly prod deploy 解禁. | CL6 §"Single-shot resolution path" / CL12 §"Section 4 #1" | ☐ yes / ☐ no |
| F2 | 6 migration を autonomath.db に LIVE apply + 2 boot_manifest 追記? | CL7 §1 6 dormant table が 1 cycle で復活, fresh DB boot で再現可能. | CL7 §"Generic apply template" / CL12 §"Section 4 #5" | ☐ yes / ☐ no |
| F3 | M5 SimCSE 10h+ stuck job を **wait** (kill しない)? | yes = `M6 watcher auto-fire`. no = StopTrainingJob + v2 cycle. | CL10 §(d) / CL8 §10 | ☐ yes / ☐ no |
| F4 | A5 PR #245 を **Option A cherry-pick** (A5+P4+P5 のみ、A6 pricing_v2 skip) で carve-out? | A5 product + P4 freshness sweep + P5 scorer が main LIVE. 42 main commit 保全. | CL1 §"Recommended Path Forward A" / CL17 §"Section 5 #1" / CL18 §"D-P4-MERGE" | ☐ yes / ☐ no |
| F5 | CF Pages deploy drift gate (`openapi exporter + discovery resync`) を CodeX に実行依頼? | 6 surface (`llms.txt` stale / `agents.json` stale / `justifiability` 404 / `why` 404 / `federated-mcp-12` 404 / `sitemap-structured` 404) が 200 OK 復帰. | CL19 §"Step 0 — REQUIRED" / CL14 §"Section 2" | ☐ yes / ☐ no |

---

## Section 2 — P0–P4 priority sorted (yes/no + 1-2 行 + SOT ref)

### P0 SAFETY (hard-stop integrity / production gate / DB recovery)

| # | Action | yes-flip effect | SOT |
|--:|---|---|---|
| P0-1 | `preflight_scorecard.json` re-lock = Option A (1-line JSON edit)? `yes/no` | gate 7/7 PASS. canary 完了後 invariant 戻る. | CL6 §Fail1 |
| P0-2 | `wave24_206_am_placeholder_mapping.sql` を live schema から再構築 + 2 manifest 追加? `yes/no` | fresh autonomath.db boot で 207 placeholder 行 reproducible. N9 cold-start 解除. | CL12 §Section 4 #4 / D1 CRITICAL |
| P0-3 | 5-line defense `CostFilters=null` の現状維持で OK? `yes/no` | yes = no change (audit 結論 LOW risk). no = CodeX に filter narrowing 検討依頼. | CL16 §"6. CL16 verdict" |
| P0-4 | M3 KG `RotatE/ComplEx/ConvE` 3 model fail 再 submit (TransE 単独運用に降格させない)? `yes/no` | yes = 4-model ensemble 復活 (M7 KG completion 完全形). no = TransE のみで v1 着地. | CL10 §(c) |

### P1 MOAT depth unblock (migration apply / real executor / CF deploy)

| # | Action | yes-flip effect | SOT |
|--:|---|---|---|
| P1-1 | 6 migration apply を **Claude lane** に任せる? `yes/no` | yes = Claude が DRY_RUN → apply → manifest 2 file 追記 → safe_commit. no = CodeX に委任. | CL10 §9 (a) / CL7 §"5. Responsibility split" |
| P1-2 | AA1+AA2 real-executor (NTA shitsugi/saiketsu/bunsho + Textract bulk) を **今夜実行** ($10K burn)? `yes/no` | yes = 11,155 + 4,072 行 real corpus + $10K AWS spend. no = wait. | CL10 §9 (b) / CL10 §(b) |
| P1-3 | CF Pages `pages-deploy-main` drift gate を **CodeX が修正** (Step 0 = `export_openapi.py` + `export_agent_openapi.py` + discovery resync)? `yes/no` | yes = 100 連続 failure run の root cause 解消, 6 stale surface 200 復帰. no = 公開面 stale 継続. | CL19 §Section 4 / CL14 §Section 2 |
| P1-4 | OpenAPI exporter `ensure_ascii` policy を **escape (ASCII)** に固定? `yes/no` | yes = JSON serializer drift 永続停止. no = literal CJK 維持 (再 drift リスク). | CL6 §Fail2 prescription #4 / CL19 §Section 3 primary cause |

### P2 PRODUCT (PR #245 / page slug / cohort tools)

| # | Action | yes-flip effect | SOT |
|--:|---|---|---|
| P2-1 | PR #245 を **Option A cherry-pick (A5 + P4 + P5 のみ)** で main land? `yes/no` | yes = A5 司法書士 product + freshness cron + 245-fixture scorer LIVE on main. A6 pricing_v2 deliberately drop (V3 superseded). no = PR draft 維持. | CL1 §Option A / CL18 §D-P4-MERGE / CL17 §1 |
| P2-2 | Site product page A3/A4/A5 を **server tool A3/A4/A5 cohort と整合 rename** (subsidy/shuugyou-kisoku/kaisha-setsuritsu)? `yes/no` | yes = page slug が server tool 名と 1:1 一致. no = 現状 mismatch 維持 (A3 site=行政書士, A3 tool=subsidy_roadmap). | CL17 §Section 5 #2 |
| P2-3 | 11 cohort tools (`agent_briefing_pack` + 10 `agent_cohort_*`) を **public manifest に維持** (drift ceiling 200→250 bump)? `yes/no` | yes = MCP runtime 231 = manifest 231 整合. no = core 限定 gate (公開数 184 維持). | CL6 §Fail3 #4 / CL12 §Section 5 #2 |
| P2-4 | 3 D-bin tool (`query_snapshot_as_of_v2` / `counterfactual_diff_v2` / `semantic_search_legacy_am`) を gate-off? `yes/no` | yes = 公開 surface 284→281, agent が deprecated path 試行停止. no = legacy alias 残置. | CL11 §F3 #8 / §6 #3 |

### P3 polish (docstring / persona dir / recipe slot)

| # | Action | yes-flip effect | SOT |
|--:|---|---|---|
| P3-1 | `products/__init__.py` docstring を V3 価格に patch (¥1000/¥200/¥500/¥300/¥800 → ¥30/¥30/¥30/¥30/¥30)? `yes/no` | yes = docstring drift 0 (behavior 不変). no = stale comment 残置. | CL17 §3 #3 |
| P3-2 | `site/personas/` を `site/compare/<persona>.html` への symlink で創設? `yes/no` | yes = A7 spec 完全充足. no = sitemap rewrite で compare/ を persona role に. | CL17 §Section 5 #4 |
| P3-3 | Cookbook r04-r08 / r12-r15 slot を **予約 (reserve)** (compact-renumber しない)? `yes/no` | yes = 22 recipe 現状維持, future v3 用 slot. no = 1..22 連番 compact rename. | CL17 §Section 5 #5 |
| P3-4 | 5 dormant duplicate file (`src/jpintel_mcp/mcp/autonomath_tools/` 内の moat_lane_tools shadow) を `git rm`? `yes/no` | yes = 7 latent name shadow eliminated. no = 不活性のまま放置 (future import で boot brick リスク). | CL12 §Section 5 #5 |

### P4 future (Opus fixture / persona pivot / 3-month structural)

| # | Action | yes-flip effect | SOT |
|--:|---|---|---|
| P4-1 | 245 Opus 4.7 fixture (P5 benchmark) を **Claude Code Max Pro session 経由** で生成 (SDK 禁止)? `yes/no` | yes = `data/p5_benchmark/opus_4_7_outputs/` 5→250 充足, `site/benchmark/results.json` 公開 leaderboard 可. no = seed 5 のみで保留. | CL18 §D-P5-FIXTURES (memory `feedback_no_operator_llm_api`) |
| P4-2 | `.well-known/retention.json` + `/pricing/outcomes` 14-bundle page 今週内 ship? `yes/no` | yes = F5 Retainability + Payability bottleneck 解消. no = funnel Stage 5+6 thin 維持. | CL11 §6 Action 4 |
| P4-3 | 5 cohort composition tool (`monthly_intake_composed` 他 4 本) 今月内 author? `yes/no` | yes = F2 §3.2 18 N round-trip 業務 → 1 call 折りたたみ. no = round-trip 維持. | CL11 §6 Action 5 |
| P4-4 | autonomath.db → PostgreSQL + Edge KV split をこの四半期 trigger (Fly volume provisioning user-action 必要)? `yes/no` | yes = 9.7GB monolith 解消, latency baseline 改善. no = monolith 維持. | CL11 §4.2 F1 Q1-A |
| P4-5 | M5 SimCSE 完了後 cohort LoRA adapter 4 本を M5 jpcite-BERT 上に build (今月)? `yes/no` | yes = L2 cohort-specific inference head 実装 (F1 Gap #1 解消). no = generic head 維持. | CL11 §4.2 F1 M1-B |

---

## Section 3 — Loop kill switch (最大 1 件)

| # | Action | yes-flip effect | SOT |
|--:|---|---|---|
| L1 | ループ続行 (`/loop` ScheduleWakeup 60s cadence) 維持? `yes/no` | yes = Claude lane 並列 12-20 agent 自走継続. no = 明示 stop, Claude lane 全停止. | memory `feedback_loop_never_stop` |

> **default = yes**. 「明示 stop」と書かない限り loop 継続 (memory 最重要 feedback).

---

## Section 4 — CodeX hand-off items (Claude では実行できないもの)

下記 5 件は CodeX 専属レーン. Claude は触れない. operator が CodeX prompt に paste する.

| # | Action | Why CodeX-only | SOT |
|--:|---|---|---|
| X1 | `preflight_scorecard.json` re-lock (`live_aws_commands_allowed=false`) | site/releases/* は CodeX 書込領域 + capsule re-sign 必要 | CL6 Fail1 / CL12 Section 4 #1 |
| X2 | OpenAPI exporter 再実行 + `site/openapi*.json` 4 file + `openapi-discovery.json` byte-resync | OpenAPI 生成 pipeline は CodeX 領域 | CL6 Fail2 / CL19 Step 0 |
| X3 | `mcp-server.json` / `mcp-server.full.json` (+ site mirror 4 file) を runtime 231 tool で re-emit + `check_mcp_drift.py` 上限 200→250 bump | tool registry generator CodeX 担当 | CL6 Fail3 / CL12 Section 4 #3 |
| X4 | SageMaker `kg-rotate/complex/conve` 3 model 再 submit (script 修正済) + ConvE `batch_size 512→256` | SageMaker submit は CodeX 専属 (AGENTS lane) | CL10 §(c) |
| X5 | AA1+AA2 real-executor (`ingest_nta_corpus.py --target {shitsugi,saiketsu,bunsho} --commit` + `textract_bulk_submit_*.py`) | AWS Textract burn は CodeX 担当 ($10K $cost gate) | CL10 §(b) / CL8 §9.2 |

---

## Operator yes/no quick-fill (compact form)

```
F1=☐yes ☐no  | F2=☐yes ☐no  | F3=☐yes ☐no  | F4=☐yes ☐no  | F5=☐yes ☐no
P0-1=☐  P0-2=☐  P0-3=☐  P0-4=☐
P1-1=☐  P1-2=☐  P1-3=☐  P1-4=☐
P2-1=☐  P2-2=☐  P2-3=☐  P2-4=☐
P3-1=☐  P3-2=☐  P3-3=☐  P3-4=☐
P4-1=☐  P4-2=☐  P4-3=☐  P4-4=☐  P4-5=☐
L1=☐yes (default) ☐no
X1=hand-off  X2=hand-off  X3=hand-off  X4=hand-off  X5=hand-off
```

Total decisions = **5 (Section 1)** + **17 (P0-P4: 4+4+4+4+5)** + **1 (loop)** + **5 (CodeX hand-off)** = **28 items**.

---

## References (canonical SOT)

- CL6 — `docs/_internal/CL6_PRODUCTION_GATE_4_FAIL_AUDIT_2026_05_17.md`
- CL7 — `docs/_internal/CL7_MIGRATION_APPLY_5_AUDIT_2026_05_17.md`
- CL8 — `docs/_internal/CL8_AWS_BURN_FORECAST_2026_05_17_EVENING.md`
- CL10 — `docs/_internal/OPERATOR_BRIEF_2026_05_17_EVENING.md`
- CL11 — `docs/_internal/F_AUDIT_CONSOLIDATED_2026_05_17.md`
- CL12 — `docs/_internal/D_AUDIT_CONSOLIDATED_2026_05_17.md`
- CL14 — `docs/_internal/CL14_PUBLIC_DOCS_STATE_SOT_2026_05_17.md`
- CL16 — `docs/_internal/CL16_BUDGET_FILTER_SAFETY_AUDIT_2026_05_17.md`
- CL17 — `docs/_internal/A_SERIES_AUDIT_2026_05_17.md`
- CL18 — `docs/_internal/P_SERIES_AUDIT_2026_05_17.md`
- CL19 — `docs/_internal/CL19_CF_PAGES_DEPLOY_AUDIT_2026_05_17.md`
- CL1 — `docs/_internal/CL1_A5_A6_PR_MERGE_2026_05_17.md` (PR #245 blocking comment)
- Memory: `feedback_no_priority_question` / `feedback_loop_never_stop` / `feedback_no_operator_llm_api` / `feedback_aws_canary_hard_stop_5_line_defense`

---

**Queue compiled**: 2026-05-17 evening JST.
**Lane**: `lane:solo`.
**Mode**: READ-ONLY scan of 11 audit doc, no source artifact modified.
