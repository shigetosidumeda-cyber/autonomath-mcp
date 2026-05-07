---
title: R8 audit doc FINAL master index (jpcite v0.3.4 / 5/7 dusk → frontend retry, 39 R8 doc)
generated: 2026-05-07
type: housekeeping audit / FINAL master cross-reference index / single-doc index
audit_method: read-only static catalog (write 1 file: this FINAL master index only; LLM API 0)
session_window: 2026-05-06 + 2026-05-07 統合 (R8_INDEX_2026-05-07.md は 24 doc 時点 snapshot で stale; 本 doc は cycle 後 39 doc final)
internal_hypothesis: 39 R8 doc + 7 R7 doc を 1 surface に折り畳む final master index。 数値主張は内部 session window 計測値、 production deploy + 外部 review 未経由。 Fly api side LIVE / Cloudflare Pages frontend pending という 軸分割 framing 維持。
no_go_warning: production deploy 視点 — Fly api side は 5/7 hardening 反映済 (image deployment-01KR0AGKRFD39QZZJ10VWYZXS5、 OpenAPI 0.3.4 paths=182 観測); Cloudflare Pages frontend は HANDOFF baton 受け継ぎ後 deploy 未実行、 OAuth UI / Stripe live mode UI activate も operator manual。
prior_index: R8_INDEX_2026-05-07.md (24 doc, stale, read-only reference として保持; 本 doc は新 file で coexist)
---

# R8 audit doc FINAL master index (jpcite v0.3.4)

R8 round (2026-05-06 dusk → 2026-05-07 frontend retry baton) で生成された
**39 R8 doc + 7 R7 doc** を 1 surface に統合する FINAL master index。
旧 `R8_INDEX_2026-05-07.md` は 24 doc 時点 snapshot で 5/7 launch ops
+ frontend retry の 15 doc を含まず stale。 本 doc は新 file (read-only
reference として旧 INDEX 保持) として 5/7 dusk fence の確定版 として
立てる。 LLM API 0、 destructive 上書き 0、 内部仮説 framing 維持。

axis 分割: **Fly api side launch 達成** (OpenAPI 0.3.4 paths=182 live)
+ **Cloudflare Pages frontend pending** (HANDOFF baton 受け継ぎ + 公開
OAuth UI / Stripe live mode UI activate 残)、 と framing。 「launched
(= 商用稼働)」 とは call せず。

---

## §1. R8 doc 全 39 file 1 表 (key finding 1 行)

5 thematic cluster (C1-C5) + 1 新 cluster (C3 = launch ops) で table 化。
status は (READY / READY operator-step / NO-GO surface / launch ops /
SUPERSEDED partial / HISTORICAL note) の 6 種。

| # | doc | cluster | key finding (1 行) | status |
|---|---|---|---|---|
| 1 | `R8_33_SPEC_RETROACTIVE_VERIFY.md` | C1 | DEEP-22..54 33 spec 283 acceptance criteria を YAML + pytest で retroactive verify、 286 assertion 全 PASS | READY |
| 2 | `R8_ACCEPTANCE_CRITERIA_CI_GUARD.md` | C1 | 33 DEEP spec の 250+ criteria を CI guard で per-PR 自動 verify する設計 (LLM 0 / paid 0 / phase 0 / zero-touch) | READY |
| 3 | `R8_BILLING_FAIL_CLOSED_VERIFY.md` | C2 | 課金 fail-closed 4 修正点 (usage_events.status 実 HTTP / paid 2xx strict_metering=True / cap final / strict 漏れ 0) 全 PASS | READY |
| 4 | `R8_CI_COVERAGE_MATRIX_2026-05-07.md` | C2 | release.yml + test.yml + 3 hardening workflow を Wave hardening 軸に対し coverage matrix 化、 真 gap 列挙 | READY |
| 5 | `R8_CLOSURE_FINAL_2026-05-07.md` | C5 | 累積 25+ R8 doc + 7 R7 doc を 1 closure surface に折り畳み、 30+ commit / ~3,160 file change / 8 軸 gate / 33 DEEP spec で CODE-SIDE READY 到達 | READY (closure) |
| 6 | `R8_DEEP_CROSS_REFERENCE_MATRIX.md` | C1 | DEEP-22..57 33 spec + DEEP-31/32 variant = 36 file の dependencies front matter から static dep graph + 5 cluster + circular detection + production critical path 1 surface 化 | READY |
| 7 | `R8_DEPLOY_ATTEMPT_AUDIT_2026-05-07.md` | C3 | 5/7 02:50-03:50 UTC 16 deploy attempt timeline、 attempt 5 が origin/main (f3679d6) 再 deploy で 5/7 hardening unshipped、 後 v95 deploy で 0.3.4 paths=182 LIVE | launch ops |
| 8 | `R8_DRY_RUN_VALIDATION_REPORT.md` | C4 | _executable_artifacts_2026_05_06/ 配下 3 task / 33 file を 静的検証 + :memory: dry-run、 LLM API import 0 件、 全 PASS で codex pickup 待機 | READY |
| 9 | `R8_FINAL_IMPLEMENTATION_MANIFEST_2026-05-07.md` | C5 | 33 spec implementation 1 session window 完走、 累積 19+ commit / ~1,956+ file change で code-side blocker 0、 残 operator manual 3 件 | READY |
| 10 | `R8_FINAL_METRIC_SNAPSHOT_2026-05-07.md` | C5 | session 2026-05-06 + 2026-05-07 で 28 commit / ~3,160 file change / +305,052/-45,975 行 の最終 gate metric を 1 doc 集約 | READY (snapshot) |
| 11 | `R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md` | C3 | depot deadline_exceeded 1431s 後の代替 path 評価、 17GB working tree / 12GB autonomath.db dockerignore 確認、 depot=false retry rationale | launch ops |
| 12 | `R8_FLY_DEPLOY_READINESS_2026-05-07.md` | C3 | fly.toml syntax / Dockerfile multi-stage / entrypoint.sh bash / SECRETS_REGISTRY §0.1 boot gate 4 軸 readiness check 全 PASS、 4 件 non-blocking drift | READY (deploy precondition) |
| 13 | `R8_FLY_SECRET_SETUP_GUIDE.md` | C3 | autonomath-api Fly app 用 5 production-required secret 投入 step-by-step、 operator 介在前提、 token 値は .env.local | READY (operator step) |
| 14 | `R8_FRONTEND_LAUNCH_STATUS_2026-05-07.md` | C3 | HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP baton 継承、 3 dirty file (ai-recommendation / server.json / practitioner-eval) + mkdocs/manifest/link checker PASS、 Pages deploy 未実行 | launch ops (frontend pending) |
| 15 | `R8_GHA_DEPLOY_PATH_2026-05-07.md` | C3 | release.yml = PyPI-only、 deploy.yml = workflow_run + workflow_dispatch (Fly のみ)、 FLY_API_TOKEN + ACK_YAML required、 第 3 fly-only workflow なし | launch ops |
| 16 | `R8_HIGH_RISK_PENDING_LIST.md` | C2 | production deploy 確定 NO-GO 4 blocker (dirty_tree:821 / workflow targets 13 untracked / operator_ack:not_provided / release readiness 1 fail / 9) を CRITICAL severity で並べる | NO-GO surface |
| 17 | `R8_INDEX_2026-05-07.md` | C5 | (旧 INDEX、 24 doc 時点 snapshot、 5/7 launch ops + frontend retry 15 doc 未含。 本 FINAL index で superseded) | SUPERSEDED |
| 18 | `R8_LANE_GUARD_DESIGN_2026-05-07.md` | C4 | 1-CLI solo vs 2-CLI resume 政策設計、 codex dormant 確認、 reason_min_chars=24 文字 ergonomic friction 1 件のみ | READY |
| 19 | `R8_LANE_LEDGER_AUDIT_2026-05-07.md` | C4 | dual-CLI lane claim atomic verify + AGENT_LEDGER append-only audit、 3 ledger artifact append-only intact、 format drift 0、 1-CLI solo 確認 | READY |
| 20 | `R8_LAUNCH_LIVE_STATUS_2026-05-07.md` | C3 | jpcite v0.3.4 が Fly.io Tokyo に既 LIVE 発覚、 健康 healthz/readyz/deep 全 200、 stripe live key + DNS 経由完了、 但し当初は 5/6 image (f3679d6) | launch ops (live discovery) |
| 21 | `R8_LAUNCH_OPS_TIMELINE_2026-05-07.md` | C3 | 5/7 02:50-04:20 UTC ≈90 分の 16 attempt timeline、 ACK PASS 8/8、 production_deploy_go_gate 5/5、 depot/depot=false 失敗を経て GHA dispatch | launch ops |
| 22 | `R8_LAUNCH_SUCCESS_FINAL_2026-05-07.md` | C3 | Fly api side LIVE 達成、 GHA deploy.yml run 25475753541 14 step SUCCESS、 image deployment-01KR0AGKRFD39QZZJ10VWYZXS5 bind、 OpenAPI v0.3.4 paths=182 live | launch ops (api side LIVE) |
| 23 | `R8_MANIFEST_BUMP_EVAL_2026-05-07.md` | C2 | manifest 139→146 bump 評価、 7 post-manifest tool 全 READY だが sample_arguments 欠落、 v0.3.5 patch bump 候補 (operator decision 待ち) | READY (operator decision) |
| 24 | `R8_MANIFEST_SYNC_VERIFY_2026-05-07.md` | C2 | 5 manifest (pyproject + server.json + dxt/manifest.json + smithery + mcp-server.json) × 6 axis sync verify、 hold-at-139 全件 SYNC | READY |
| 25 | `R8_MCP_FULL_COHORT_2026-05-07.md` | C2 | mcp.list_tools() runtime 146 (139 manifest floor + 7 post-manifest) を full cohort flag set で実証、 +36協定 で 148 | READY |
| 26 | `R8_NEXT_SESSION_2026-05-07.md` | C5 | 次 session queue (Step 3-4 未実行)、 累積 28 commit / ~2,369 file change / +302,269 / -44,279 行、 NO-GO 維持 | READY (forward plan) |
| 27 | `R8_POST_DEPLOY_SMOKE_FULL_2026-05-07.md` | C2 | post_deploy_smoke.py 5 module 全 GREEN (health / routes 240/240 / mcp 148 tools / disclaimer 17/17 / stripe SKIP)、 local boot 確認 | READY |
| 28 | `R8_POST_DEPLOY_SMOKE_LOCAL_2026-05-07.md` | C2 | DEEP-61 smoke gate を local uvicorn boot 上で dry-run、 5 module gate 自体の verify 完走、 production 未点 | READY |
| 29 | `R8_PRE_DEPLOY_LIVE_BASELINE_2026-05-07.md` | C3 | 2026-05-07 02:54 UTC 時点 jpcite.com stale-token grep、 14 line tokens (`11,684 programs` / `本文 154` / `¥3/リクエスト`) baseline 固定 | launch ops (baseline) |
| 30 | `R8_PRECOMMIT_FINAL_16_2026-05-07.md` | C2 | pre-commit run --all-files exit=0、 16/16 hooks PASS、 LLM 0 / destructive 0、 全 fix deterministic | READY |
| 31 | `R8_PRECOMMIT_VERIFY_2026-05-07.md` | C2 | .pre-commit-config.yaml 全 hook inventory + per-hook detail audit、 構成 / version pin / exclude pattern verify | READY |
| 32 | `R8_PROD_SMOKE_5_6_IMAGE_2026-05-07.md` | C3 | 5/6 image (f3679d6) 上の prod smoke 5 module、 mcp_tools_list 107/139 fail 但し runtime probe 146 PASS で gate-flag delta 説明、 他 4 module PASS | launch ops |
| 33 | `R8_PROD_SMOKE_5_7_LIVE_2026-05-07.md` | C3 | 5/7 v95 LIVE post deploy smoke、 OpenAPI paths 179→174 (env-flag drift) + /v1/privacy/* 2 path 新設、 healthz/readyz/deep 200 | launch ops |
| 34 | `R8_PRODUCTION_GATE_DASHBOARD_SUMMARY_2026-05-07.md` | C2 | aggregate_production_gate_status.py + 13/13 test PASS、 4 blocker pane で 3 RESOLVED + 1 BLOCKED (operator_ack の --dry-run 期待 rc=1) | READY |
| 35 | `R8_PYTEST_BASELINE_FAIL_AUDIT_2026-05-07.md` | C2 | pytest baseline 4476 collect / 2502 pass / 200 fail (--maxfail=200 stop) / 11 skip、 cluster A route_not_found regression 確認 | NO-GO partial (test debt) |
| 36 | `R8_SESSION_CLOSURE_2026-05-07.md` | C5 | session 累積 25+ commit / ~2,100+ file change / 33 spec / 14+ R7-R8 doc 最終 verification + operator manual 3 step 残 | READY (session close) |
| 37 | `R8_SITE_HTML_AUDIT_2026-05-07.md` | C2 | site/ HTML 12,592 file doctype + UTF-8 整合、 JS 22 file node --check pass、 業法 sensitive 4 page legal-note envelope 整合、 secret leak 0 | READY (Cloudflare Pages publish) |
| 38 | `R8_SMOKE_FULL_GATE_2026-05-07.md` | C2 | AUTONOMATH_36_KYOTEI_ENABLED=1 で 36協定 pair を mandatory promote、 smoke gate 17/17 mandatory PASS / missing=0 / gated_off=0 | READY |
| 39 | `R8_SMOKE_GATE_FLAGS_2026-05-07.md` | C2 | smoke gate env-flag accounting、 36協定 pair gated_off_expected 仕様 (default OFF、 社労士法 review 待ち) と mcp_tools_list 107/139 false-negative 説明 | READY |

R8 doc 計 **39 file** (旧 INDEX で 24 doc + 5/7 launch ops cluster で
15 doc 増分)。 cluster 分布 → C1=3 / C2=14 / C3=12 / C4=3 / C5=7。

---

## §2. cluster 別 grouping (5 thematic + 新 C3 launch ops)

### §2.1 C1 readiness audit (spec / acceptance / dep graph) — 3 doc

DEEP-22..57 33 spec の retroactive verify + CI guard 設計 + dep graph。
production gate spec verify axis に 寄与する readiness 軸。

- `R8_33_SPEC_RETROACTIVE_VERIFY.md` (286 assertion 全 PASS)
- `R8_ACCEPTANCE_CRITERIA_CI_GUARD.md` (CI guard 設計、 zero-touch)
- `R8_DEEP_CROSS_REFERENCE_MATRIX.md` (33 spec + 36 file dep graph)

### §2.2 C2 implementation verification (smoke / mcp / gate / billing) — 14 doc

post_deploy_smoke 5-module + mcp cohort + manifest sync + 課金 fail-closed
+ pre-commit + production gate dashboard。 implementation 完走の verify 軸。

- `R8_BILLING_FAIL_CLOSED_VERIFY.md` (4 修正点 全 PASS)
- `R8_CI_COVERAGE_MATRIX_2026-05-07.md` (5 workflow × hardening axis matrix)
- `R8_HIGH_RISK_PENDING_LIST.md` (4 blocker NO-GO surface)
- `R8_MANIFEST_BUMP_EVAL_2026-05-07.md` (139→146 bump 評価)
- `R8_MANIFEST_SYNC_VERIFY_2026-05-07.md` (5 manifest sync)
- `R8_MCP_FULL_COHORT_2026-05-07.md` (146 floor 実証)
- `R8_POST_DEPLOY_SMOKE_FULL_2026-05-07.md` (5 module 全 GREEN)
- `R8_POST_DEPLOY_SMOKE_LOCAL_2026-05-07.md` (DEEP-61 dry-run)
- `R8_PRECOMMIT_FINAL_16_2026-05-07.md` (16/16 hook PASS)
- `R8_PRECOMMIT_VERIFY_2026-05-07.md` (hook inventory)
- `R8_PRODUCTION_GATE_DASHBOARD_SUMMARY_2026-05-07.md` (13/13 test PASS、 3 RESOLVED + 1 BLOCKED)
- `R8_PYTEST_BASELINE_FAIL_AUDIT_2026-05-07.md` (200 fail / 2502 pass / 4476 collect)
- `R8_SITE_HTML_AUDIT_2026-05-07.md` (Cloudflare Pages publish readiness)
- `R8_SMOKE_FULL_GATE_2026-05-07.md` (36協定 ENABLED=1 で 17/17 mandatory)
- `R8_SMOKE_GATE_FLAGS_2026-05-07.md` (env flag accounting、 false-negative 説明)

### §2.3 C3 launch ops (新 cluster、 5/7 launch ops timeline / Fly deploy / frontend) — 12 doc

5/7 02:50-04:20 UTC ≈90 分の deploy attempt timeline + Fly readiness + GHA path
+ secret setup + Pre/Post-deploy smoke + frontend baton。 旧 INDEX には不在の
新 cluster。 Fly api side LIVE 達成 / Cloudflare Pages frontend pending の
2 軸 framing 維持。

- `R8_DEPLOY_ATTEMPT_AUDIT_2026-05-07.md` (16 attempt 時系列、 origin/main 再 deploy 訂正)
- `R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md` (depot=false retry rationale)
- `R8_FLY_DEPLOY_READINESS_2026-05-07.md` (4 軸 readiness 全 PASS)
- `R8_FLY_SECRET_SETUP_GUIDE.md` (operator 5 secret 投入)
- `R8_FRONTEND_LAUNCH_STATUS_2026-05-07.md` (HANDOFF baton 継承、 deploy 未実行)
- `R8_GHA_DEPLOY_PATH_2026-05-07.md` (release.yml + deploy.yml audit)
- `R8_LAUNCH_LIVE_STATUS_2026-05-07.md` (live discovery、 5/6 image 当初)
- `R8_LAUNCH_OPS_TIMELINE_2026-05-07.md` (16 attempt timeline、 ACK 8/8 PASS)
- `R8_LAUNCH_SUCCESS_FINAL_2026-05-07.md` (api side LIVE 達成、 v0.3.4 paths=182 live)
- `R8_PRE_DEPLOY_LIVE_BASELINE_2026-05-07.md` (stale-token baseline)
- `R8_PROD_SMOKE_5_6_IMAGE_2026-05-07.md` (5/6 image smoke)
- `R8_PROD_SMOKE_5_7_LIVE_2026-05-07.md` (5/7 v95 LIVE post deploy smoke)

### §2.4 C4 manifest/sync (lane / ledger / executable artifacts) — 3 doc

dual-CLI lane atomic + AGENT_LEDGER append-only + executable_artifacts dry-run。
1-CLI solo override の policy ergonomic 軸。

- `R8_DRY_RUN_VALIDATION_REPORT.md` (33 file dry-run、 LLM 0)
- `R8_LANE_GUARD_DESIGN_2026-05-07.md` (1-CLI solo vs 2-CLI policy)
- `R8_LANE_LEDGER_AUDIT_2026-05-07.md` (3 ledger append-only intact)

### §2.5 C5 closure / synthesis / post-launch — 7 doc

最終 closure + final metric snapshot + final implementation manifest +
session closure + next session forward + 旧 INDEX (read-only reference)
+ 本 FINAL index。 集約 / hub doc。

- `R8_CLOSURE_FINAL_2026-05-07.md` (25+ R8 + 7 R7 closure surface)
- `R8_FINAL_IMPLEMENTATION_MANIFEST_2026-05-07.md` (33 spec 完走、 19+ commit)
- `R8_FINAL_METRIC_SNAPSHOT_2026-05-07.md` (28 commit / ~3,160 file change)
- `R8_INDEX_2026-05-07.md` (旧 INDEX 24 doc、 SUPERSEDED、 read-only reference)
- `R8_INDEX_FINAL_2026-05-07.md` (本 doc、 39 R8 + 7 R7 final master)
- `R8_NEXT_SESSION_2026-05-07.md` (次 session forward plan)
- `R8_SESSION_CLOSURE_2026-05-07.md` (累積 verification + 3 operator step)

---

## §3. cross-reference graph (39 R8 doc 間 + R7 doc + handoff)

5/7 launch ops 12 doc が 新 cluster なので 旧 INDEX graph に **C3 cluster
edge** を追加。 旧 INDEX §3.x で立てた R7→R7 / R8→R7 / R8→R8 graph は
全保持 (旧 INDEX read-only reference)。

### §3.1 R8 doc → R7 doc 上流参照 (5/7 launch ops の 24 R8 doc 増分以降)

旧 INDEX で確定した: R8_FINAL_IMPLEMENTATION_MANIFEST + R8_SESSION_CLOSURE
が R7 全 7 doc を inputs として consume。 5/7 launch ops cluster は
R7 doc を直接参照しない (launch operational scope のため)。

```
R8_LAUNCH_SUCCESS_FINAL              →  R7_OPERATOR_ACTIONS (公開 OAuth UI / Stripe live mode UI)
R8_FRONTEND_LAUNCH_STATUS            →  R7_OPERATOR_ACTIONS (DNS / sender domain)
R8_CLOSURE_FINAL                     →  R7_SYNTHESIS / R7_FAILURE_MODES / R7_AI_DOABLE
```

### §3.2 R8 5/7 launch ops cluster (C3) 内部参照

```
R8_LAUNCH_OPS_TIMELINE     →  R8_DEPLOY_ATTEMPT_AUDIT
R8_LAUNCH_OPS_TIMELINE     →  R8_FLY_DEPLOY_ALTERNATIVE
R8_LAUNCH_OPS_TIMELINE     →  R8_FLY_DEPLOY_READINESS
R8_LAUNCH_OPS_TIMELINE     →  R8_GHA_DEPLOY_PATH
R8_LAUNCH_LIVE_STATUS      →  R8_PRE_DEPLOY_LIVE_BASELINE
R8_LAUNCH_LIVE_STATUS      →  R8_FLY_SECRET_SETUP_GUIDE
R8_DEPLOY_ATTEMPT_AUDIT    →  R8_FLY_DEPLOY_ALTERNATIVE
R8_DEPLOY_ATTEMPT_AUDIT    →  R8_FLY_DEPLOY_READINESS
R8_DEPLOY_ATTEMPT_AUDIT    →  R8_GHA_DEPLOY_PATH
R8_DEPLOY_ATTEMPT_AUDIT    →  R8_FRONTEND_LAUNCH_STATUS
R8_LAUNCH_SUCCESS_FINAL    →  R8_DEPLOY_ATTEMPT_AUDIT
R8_LAUNCH_SUCCESS_FINAL    →  R8_LAUNCH_LIVE_STATUS
R8_LAUNCH_SUCCESS_FINAL    →  R8_LAUNCH_OPS_TIMELINE
R8_LAUNCH_SUCCESS_FINAL    →  R8_PROD_SMOKE_5_7_LIVE
R8_PROD_SMOKE_5_7_LIVE     →  R8_PROD_SMOKE_5_6_IMAGE
R8_FRONTEND_LAUNCH_STATUS  →  R8_LAUNCH_LIVE_STATUS
R8_FRONTEND_LAUNCH_STATUS  →  HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP (handoff 受け継ぎ)
```

`R8_LAUNCH_SUCCESS_FINAL` が C3 cluster 内 **central hub** で、
deploy attempt + live status + ops timeline + post-deploy smoke 4 doc を
統合参照する。

### §3.3 closure cluster (C5) → 全 cluster 参照

```
R8_CLOSURE_FINAL  →  R8_INDEX (旧)
R8_CLOSURE_FINAL  →  R8_FINAL_METRIC_SNAPSHOT
R8_CLOSURE_FINAL  →  R8_HIGH_RISK_PENDING_LIST
R8_CLOSURE_FINAL  →  R8_FINAL_IMPLEMENTATION_MANIFEST
R8_CLOSURE_FINAL  →  R8_SESSION_CLOSURE
R8_CLOSURE_FINAL  →  R8_LAUNCH_SUCCESS_FINAL (C3 hub)
R8_INDEX_FINAL    →  R8_INDEX (旧 stale, read-only)
R8_INDEX_FINAL    →  R8_CLOSURE_FINAL
R8_INDEX_FINAL    →  R8_LAUNCH_SUCCESS_FINAL
R8_INDEX_FINAL    →  R8_FRONTEND_LAUNCH_STATUS
R8_INDEX_FINAL    →  HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP
```

### §3.4 circular detection

graph 全体に **循環参照は検出されず**。 R7→R7 / R8→R7 / R8→R8 / C3 内部
全て DAG。 hub doc (R7_SYNTHESIS / R8_CLOSURE_FINAL / R8_INDEX_FINAL /
R8_LAUNCH_SUCCESS_FINAL) は 出次数 大 / 入次数 小 で source 側に立つ。

---

## §4. 5/7 LIVE state (Fly api + frontend pending)

| axis | state | source doc |
|---|---|---|
| **Fly api side** | LIVE 達成、 image deployment-01KR0AGKRFD39QZZJ10VWYZXS5 bind、 OpenAPI v0.3.4 paths=182 live、 healthz/readyz/deep 全 200 | R8_LAUNCH_SUCCESS_FINAL §1, R8_PROD_SMOKE_5_7_LIVE |
| **GHA deploy run** | 25475753541 14 step SUCCESS、 v94 → v95 rolled | R8_LAUNCH_SUCCESS_FINAL §1 |
| **anonymous rate limit** | LIVE — 3/day per IP、 JST 翌 00:00 reset 観測 | R8_LAUNCH_LIVE_STATUS §1 |
| **Stripe live mode** | live keys deployed (5 secret) — 但し UI activate 残 | R8_LAUNCH_LIVE_STATUS §1 |
| **Cloudflare Pages frontend** | HANDOFF baton 受け継ぎ、 mkdocs/manifest/link checker PASS、 但し **deploy 未実行** | R8_FRONTEND_LAUNCH_STATUS §1 |
| **公開 OAuth UI** | 残 operator manual | R8_LAUNCH_SUCCESS_FINAL §1 |
| **OpenAPI live drift** | local 227 vs live 179→182 (env-flag gating、 deploy bug ではない) | R8_LAUNCH_LIVE_STATUS §1 |
| **mcp_tools_list smoke** | 107/139 FAIL gate (gate-flag delta、 runtime probe 146 PASS で false-negative) | R8_PROD_SMOKE_5_6_IMAGE / R8_SMOKE_GATE_FLAGS |

framing: 「launched (= 商用稼働)」 とは 呼ばず、 **「Fly api side launch
達成 / frontend & 公開接点 残」**。 数値主張は 内部 session window 計測値、
forward production verify (実 customer flow / 実 Stripe live charge) は
未実施。

---

## §5. 残 operator step (OAuth UI / Stripe live UI / frontend deploy)

5/7 LIVE state 確定後、 真の operator manual で残るのは以下。 旧 INDEX
§5 critical 3 step は code-side 完走で superseded、 残るは UI side のみ。

### §5.1 critical 3 step (UI side、 5/7 LIVE state 後の確定版)

1. **Cloudflare Pages frontend deploy** — `wrangler pages deploy` または GHA `pages-deploy.yml` workflow_dispatch で 5/7 hardening artifact を publish (R8_FRONTEND_LAUNCH_STATUS §3 next-step plan)
2. **公開 OAuth client UI registration** — Stripe live mode dashboard / GitHub OAuth app / Google OAuth client の operator UI 登録 (R8_LAUNCH_SUCCESS_FINAL §3)
3. **Stripe live mode UI activate** — Dashboard 上で billing portal config + tax enabled flip (R8_LAUNCH_LIVE_STATUS §1 secret は 投入済、 UI activation 残)

### §5.2 R7_OPERATOR_ACTIONS から 46 item 主要カテゴリ (旧 INDEX §5.2 維持)

- A. OAuth / 鍵 custody (Stripe / npm / Postmark / SendGrid / Sentry / Cloudflare R2)
- B. 商業登記 / 法人 attestation (tokushoho.html 一致、 印鑑カード / 法人実印 物理保管)
- C. 財務 / 法的判断 (refund decision、 abuse-driven API key revoke)
- D. organic outreach (X / Hacker News / ProductHunt JP)
- E. DNS / sender domain (Postmark sender domain DKIM / SPF for info@bookyou.net + noreply@jpcite.com)

### §5.3 R8_MANIFEST_BUMP_EVAL operator decision

- manifest 139→146 bump 判断 (v0.3.5 patch bump 候補、 7 sample_arguments + dist rebuild + PyPI/npm/smithery publish)

### §5.4 R8_PYTEST_BASELINE_FAIL_AUDIT 200 fail (test debt 軸)

- 4476 collect / 2502 pass / 200 fail (--maxfail=200 stop) で 真 tail unknown、 cluster A route_not_found regression 1 件確認、 hardening regression vs baseline 切り分け要

operator action 合計 (5/7 LIVE 後): **critical 3 UI step + R7 46 item + manifest bump 1 + test debt 1 = 約 51 item**。 critical 3 UI step が **frontend / 商用稼働 GO** の hard blocker。

---

## §6. cross-link to handoff + R7 prior cycle

### §6.1 5/7 baton: HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md

`/Users/shigetoumeda/jpcite/tools/offline/_inbox/HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md`
(151 line, 11:51 JST、 prior codex CLI が Pages deploy 直前で停止) を
本 INDEX § §2.3 C3 cluster + §5.1 critical 3 step #1 で参照。 引き継ぎ
3 dirty file (ai-recommendation-template.md / server.json / practitioner-eval/index.html)
は R8_FRONTEND_LAUNCH_STATUS §1 で再 ground 済。 next CLI が
production write authority 引き継ぎ後 Pages deploy 実行で frontend 軸 LIVE。

### §6.2 R7 prior cycle: 旧 INDEX §2 R7 doc 7 file

旧 `R8_INDEX_2026-05-07.md` §2 で確定した R7 doc 7 file (R7_03_codex_rewatch
/ R7_04_loop_closure_surface / R7_AI_DOABLE / R7_ARR_SIGNALS / R7_FAILURE_MODES
/ R7_OPERATOR_ACTIONS / R7_SYNTHESIS) は本 FINAL index でも全保持。 `R7_SYNTHESIS`
が R7 round central hub、 SOT v0.3.4 / 227 OpenAPI / 139 MCP の 3 軸主張を
旧 INDEX §6 で 1 表 化。 5/7 LIVE state では `139 manifest floor` が
依然有効 (manifest hold-at-139 維持)、 runtime 146/148 は post-manifest cohort。

### §6.3 prior INDEX as historical baseline

旧 `R8_INDEX_2026-05-07.md` (24 doc snapshot) は本 INDEX FINAL の
historical baseline として read-only reference 保持。 cycle 後 15 doc
(C3 launch ops 12 + C5 closure 系 3) 増分が本 INDEX で吸収され、
旧 INDEX は SUPERSEDED marker のみ。 destructive 上書き 0、 新 file
1 件 (本 INDEX) のみ、 LLM API 0、 内部仮説 framing 維持。

---

## §7. operator next step (5/7 LIVE state 後の確定版)

1. **Cloudflare Pages frontend deploy** 実行 (R8_FRONTEND_LAUNCH_STATUS §3 next-step plan、 wrangler pages deploy または GHA pages-deploy.yml workflow_dispatch)
2. **公開 OAuth UI** 登録 (Stripe live / GitHub OAuth / Google OAuth、 R8_LAUNCH_SUCCESS_FINAL §3)
3. **Stripe live mode UI activate** (Dashboard billing portal config + tax enabled flip、 R8_LAUNCH_LIVE_STATUS §1)
4. operator action 後 verify cycle (post-Pages-deploy + post-OAuth-UI + post-Stripe-UI) を loop 回し、 frontend 軸 5xx=0 / OAuth flow round-trip / Stripe live mode test charge 全 PASS で **商用稼働 GO**
5. v0.3.5 manifest bump (139→146、 R8_MANIFEST_BUMP_EVAL §3 publish flow) を operator decision で打つか hold
6. pytest 200 fail / 11 skip 軸の cluster 化 + hardening regression 切り分け (R8_PYTEST_BASELINE_FAIL_AUDIT §1)

---

(end of FINAL master index)
