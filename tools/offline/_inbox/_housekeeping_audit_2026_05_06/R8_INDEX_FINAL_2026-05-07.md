---
title: R8 audit doc FINAL master index v2 (jpcite v0.3.4 / 5/7 deep audit + fix round, 87 R8 doc)
generated: 2026-05-07
type: housekeeping audit / FINAL master cross-reference index v2 / single-doc index
audit_method: read-only static catalog + live HTTPS GET (write 1 file: this v2 INDEX + 1 closure doc; LLM API 0)
session_window: 2026-05-06 + 2026-05-07 統合 (前 v1 INDEX_FINAL 39 doc snapshot は cycle 後 stale; 本 doc は deep audit + fix round 後 87 doc final v2)
internal_hypothesis: 87 R8 doc + 7 R7 doc を 1 surface に折り畳む final master index v2。 数値主張は内部 session window 計測値、 production deploy + 外部 review は image deployment-eabe358 まで反映 (run 25481404553 SHA b1de8b2 は失敗で 5/7 hardening 未反映)。 Fly api side LIVE / Cloudflare Pages frontend LIVE / Stripe live mode UI activate 残 + 公開 OAuth UI 残 という 4 軸 framing 維持。
no_go_warning: production deploy 視点 — Fly api side LIVE (image deployment-eabe358-25481404553、 OpenAPI v0.3.4 paths=182、 sentry_active=true 観測); Cloudflare Pages frontend LIVE (commit eabe358 jpcite frontend LIVE on Cloudflare Pages); Stripe live mode UI activate 残 (5 secret 投入済); 公開 OAuth UI 残 (Google secret 投入済 / GitHub secret 投入済だが route 未配線)。
prior_index: R8_INDEX_2026-05-07.md (24 doc, stale, read-only) + R8_INDEX_FINAL_2026-05-07.md v1 (39 doc, stale 但し 上書き せず Edit で v2 に置換) — 旧 v1 は本 doc で in-place update された (新 file は別途 R8_DEEP_AUDIT_CLOSURE_2026-05-07.md として coexist)
---

# R8 audit doc FINAL master index v2 (jpcite v0.3.4)

R8 round (2026-05-06 dusk → 2026-05-07 frontend retry baton → 5/7 deep audit
batch + fix batch) で生成された **87 R8 doc + 7 R7 doc** を 1 surface に
統合する FINAL master index v2。 旧 v1 INDEX_FINAL は 39 doc snapshot で
deep audit 14 doc + fix batch 8 doc + 公開 launch ops 残 26 doc を含まず
stale。 本 v2 は in-place update で 5/7 終端 fence の確定版 として立てる。
LLM API 0、 destructive 上書き 0 (本 file 自身の Edit は許容、 他 86 file
read-only)、 内部仮説 framing 維持。

axis 分割: **(1) Fly api side LIVE 達成** (OpenAPI v0.3.4 paths=182 live、
sentry_active=true、 image eabe358) + **(2) Cloudflare Pages frontend LIVE**
(commit eabe358 baton 完了) + **(3) Stripe live mode UI activate 残** (5
secret 投入済、 Dashboard activation pending) + **(4) 公開 OAuth UI 残**
(Google + GitHub secret 投入済、 GitHub route は未配線)、 と framing。
「launched (= 商用稼働)」 とは call せず。

---

## §1. R8 doc 全 87 file 1 表 (key finding 1 行)

6 thematic cluster (C1-C6) で table 化。 status は (READY / READY operator-step
/ NO-GO surface / launch ops / SUPERSEDED partial / HISTORICAL note / DEEP
AUDIT FINDING / FIX LANDED) の 8 種。

| # | doc | cluster | key finding (1 行) | status |
|---|---|---|---|---|
| 1 | `R8_33_SPEC_RETROACTIVE_VERIFY.md` | C1 | DEEP-22..54 33 spec 283 acceptance criteria を YAML + pytest で retroactive verify、 286 assertion 全 PASS | READY |
| 2 | `R8_ACCEPTANCE_CRITERIA_CI_GUARD.md` | C1 | 33 DEEP spec の 250+ criteria を CI guard で per-PR 自動 verify する設計 (LLM 0 / paid 0 / phase 0 / zero-touch) | READY |
| 3 | `R8_ACCESSIBILITY_DEEP_2026-05-07.md` | C6 | WCAG 2.1 AA + mobile responsive deep audit、 site/ 全ページの a11y 軸検証 | DEEP AUDIT FINDING |
| 4 | `R8_AI_CONSUMER_AUDIT_2026-05-07.md` | C6 | AI consumer (MCP / SDK / agent) 視点の OpenAPI / tag / q-alias 一貫性 deep audit、 root tags + q/query alias 統合 提案 | DEEP AUDIT FINDING |
| 5 | `R8_AUDIT_LOG_DEEP_2026-05-07.md` | C6 | audit log + traceability deep audit、 ULID 統一 + request_id 整合 | DEEP AUDIT FINDING |
| 6 | `R8_BACKUP_FIX_2026-05-07.md` | C6 | nightly backup defect A resolution、 backup script 修正 + verify | FIX LANDED |
| 7 | `R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md` | C6 | backup + restore drill audit、 disaster recovery readiness 評価 | DEEP AUDIT FINDING |
| 8 | `R8_BILLING_FAIL_CLOSED_VERIFY.md` | C2 | 課金 fail-closed 4 修正点 (usage_events.status 実 HTTP / paid 2xx strict_metering=True / cap final / strict 漏れ 0) 全 PASS | READY |
| 9 | `R8_BRAND_CONSISTENCY_DEEP_2026-05-07.md` | C6 | jpcite vs autonomath vs jpintel-mcp brand drift deep audit、 user-facing surface の名称統一 | DEEP AUDIT FINDING |
| 10 | `R8_CI_COVERAGE_MATRIX_2026-05-07.md` | C2 | release.yml + test.yml + 3 hardening workflow を Wave hardening 軸に対し coverage matrix 化、 真 gap 列挙 | READY |
| 11 | `R8_CLOSURE_FINAL_2026-05-07.md` | C5 | 累積 25+ R8 doc + 7 R7 doc を 1 closure surface に折り畳み、 30+ commit / ~3,160 file change / 8 軸 gate / 33 DEEP spec で CODE-SIDE READY 到達 | READY (closure) |
| 12 | `R8_CODEX_LANE_REVIEW_2026-05-07.md` | C4 | codex CLI lane review、 dormant 状態確認 + ledger 整合 | READY |
| 13 | `R8_CRON_RELIABILITY_DEEP_2026-05-07.md` | C6 | cron + worker reliability deep audit、 11 cron workflow の retry / dedup / idempotency 検証 | DEEP AUDIT FINDING |
| 14 | `R8_DB_INTEGRITY_AUDIT_2026-05-07.md` | C6 | database integrity audit、 jpintel.db + autonomath.db FK / unique / check constraint 軸 | DEEP AUDIT FINDING |
| 15 | `R8_DEEP_CROSS_REFERENCE_MATRIX.md` | C1 | DEEP-22..57 33 spec + DEEP-31/32 variant = 36 file の dependencies front matter から static dep graph + 5 cluster + circular detection + production critical path 1 surface 化 | READY |
| 16 | `R8_DEPLOY_ATTEMPT_AUDIT_2026-05-07.md` | C3 | 5/7 02:50-03:50 UTC 16 deploy attempt timeline、 attempt 5 が origin/main (f3679d6) 再 deploy で 5/7 hardening unshipped、 後 v95 deploy で 0.3.4 paths=182 LIVE | launch ops |
| 17 | `R8_DEPLOY_RUN_25482086637_2026-05-07.md` | C3 | GHA deploy.yml run 25482086637 verification、 build + push + deploy step 完走確認 | launch ops |
| 18 | `R8_DISCLAIMER_LIVE_VERIFY_2026-05-07.md` | C6 | 業法 disclaimer cohort live envelope verify、 §52 / §72 / §47条の2 / 行政書士法 §1 / 司法書士法 §3 / 社労士法 §2 全 17 sensitive route の `_disclaimer` field 包絡確認 | READY |
| 19 | `R8_DOC_GAP_DEEP_2026-05-07.md` | C6 | documentation gap + runbook completeness deep audit、 4 front-matter + 4 rollback/verify section 補完 | FIX LANDED |
| 20 | `R8_DRY_RUN_VALIDATION_REPORT.md` | C4 | _executable_artifacts_2026_05_06/ 配下 3 task / 33 file を 静的検証 + :memory: dry-run、 LLM API import 0 件、 全 PASS で codex pickup 待機 | READY |
| 21 | `R8_DXT_BUNDLE_EXPORT_2026-05-07.md` | C2 | DXT (.mcpb) bundle export health verify、 post-launch publish prep の Smithery / MCP registry 整合 | READY |
| 22 | `R8_ERROR_MESSAGE_CLARITY_2026-05-07.md` | C6 | error envelope user_message / user_message_en / suggested_paths / documentation 4 軸 clarity audit | DEEP AUDIT FINDING |
| 23 | `R8_FINAL_IMPLEMENTATION_MANIFEST_2026-05-07.md` | C5 | 33 spec implementation 1 session window 完走、 累積 19+ commit / ~1,956+ file change で code-side blocker 0、 残 operator manual 3 件 | READY |
| 24 | `R8_FINAL_INTEGRATION_SMOKE_2026-05-07.md` | C6 | post-secret-injection final integration smoke、 5 Fly secret 投入後の OAuth route 503→405 promotion + sentry_active=true 確認 | DEEP AUDIT FINDING |
| 25 | `R8_FINAL_METRIC_SNAPSHOT_2026-05-07.md` | C5 | session 2026-05-06 + 2026-05-07 で 28 commit / ~3,160 file change / +305,052/-45,975 行 の最終 gate metric を 1 doc 集約 | READY (snapshot) |
| 26 | `R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md` | C3 | depot deadline_exceeded 1431s 後の代替 path 評価、 17GB working tree / 12GB autonomath.db dockerignore 確認、 depot=false retry rationale | launch ops |
| 27 | `R8_FLY_DEPLOY_READINESS_2026-05-07.md` | C3 | fly.toml syntax / Dockerfile multi-stage / entrypoint.sh bash / SECRETS_REGISTRY §0.1 boot gate 4 軸 readiness check 全 PASS、 4 件 non-blocking drift | READY (deploy precondition) |
| 28 | `R8_FLY_EDGE_ROUTING_FIX_2026-05-07.md` | C6 | Fly edge routing SJC 経由問題、 CF orange-cloud mitigation 提案 (Tokyo region 直接ルーティング) | DEEP AUDIT FINDING |
| 29 | `R8_FLY_HEALTH_CHECK_TUNING_2026-05-07.md` | C3 | Fly health check + machine config tuning、 grace period + interval + timeout 軸チューニング | launch ops |
| 30 | `R8_FLY_SECRET_SETUP_GUIDE.md` | C3 | autonomath-api Fly app 用 5 production-required secret 投入 step-by-step、 operator 介在前提、 token 値は .env.local | READY (operator step) |
| 31 | `R8_FRONTEND_LAUNCH_STATUS_2026-05-07.md` | C3 | HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP baton 継承、 3 dirty file + mkdocs/manifest/link checker PASS、 Pages deploy 未実行 | launch ops (frontend pending) |
| 32 | `R8_FRONTEND_LAUNCH_SUCCESS_2026-05-07.md` | C3 | Cloudflare Pages frontend LIVE 達成、 commit eabe358 jpcite frontend LIVE、 site/ 全 12,592 file deploy | launch ops (frontend LIVE) |
| 33 | `R8_GHA_DEPLOY_PATH_2026-05-07.md` | C3 | release.yml = PyPI-only、 deploy.yml = workflow_run + workflow_dispatch (Fly のみ)、 FLY_API_TOKEN + ACK_YAML required、 第 3 fly-only workflow なし | launch ops |
| 34 | `R8_GHA_R2_SECRETS_OPERATOR_2026-05-07.md` | C6 | GHA R2 secrets operator gap、 nightly-backup workflow 用 R2 access key 投入手順 | DEEP AUDIT FINDING |
| 35 | `R8_HIGH_RISK_PENDING_LIST.md` | C2 | production deploy 確定 NO-GO 4 blocker (dirty_tree:821 / workflow targets 13 untracked / operator_ack:not_provided / release readiness 1 fail / 9) を CRITICAL severity で並べる | NO-GO surface |
| 36 | `R8_I18N_DEEP_AUDIT_2026-05-07.md` | C6 | i18n / English-translation endpoint completeness audit、 12 EN page + body_en bulk ETL gap 列挙 | DEEP AUDIT FINDING |
| 37 | `R8_INDEX_2026-05-07.md` | C5 | (旧 INDEX、 24 doc 時点 snapshot、 SUPERSEDED) | SUPERSEDED |
| 38 | `R8_INDEX_FINAL_2026-05-07.md` | C5 | (本 doc v2、 87 R8 + 7 R7 final master、 v1 from 39 doc を in-place update) | READY (master) |
| 39 | `R8_INDUSTRY_PACK_LIVE_AUDIT_2026-05-07.md` | C6 | Wave 23 industry pack (construction / manufacturing / real_estate) live audit、 NTA saiketsu 137 row thin upstream 確認 | DEEP AUDIT FINDING |
| 40 | `R8_LANE_GUARD_DESIGN_2026-05-07.md` | C4 | 1-CLI solo vs 2-CLI resume 政策設計、 codex dormant 確認、 reason_min_chars=24 文字 ergonomic friction 1 件のみ | READY |
| 41 | `R8_LANE_LEDGER_AUDIT_2026-05-07.md` | C4 | dual-CLI lane claim atomic verify + AGENT_LEDGER append-only audit、 3 ledger artifact append-only intact、 format drift 0、 1-CLI solo 確認 | READY |
| 42 | `R8_LANE_POLICY_REVERIFY_2026-05-07.md` | C4 | lane policy solo lane re-verify、 codex dormant 継続 + ledger drift 0 | READY |
| 43 | `R8_LAUNCH_LIVE_STATUS_2026-05-07.md` | C3 | jpcite v0.3.4 が Fly.io Tokyo に既 LIVE 発覚、 健康 healthz/readyz/deep 全 200、 stripe live key + DNS 経由完了、 但し当初は 5/6 image (f3679d6) | launch ops (live discovery) |
| 44 | `R8_LAUNCH_OPS_TIMELINE_2026-05-07.md` | C3 | 5/7 02:50-04:20 UTC ≈90 分の 16 attempt timeline、 ACK PASS 8/8、 production_deploy_go_gate 5/5、 depot/depot=false 失敗を経て GHA dispatch | launch ops |
| 45 | `R8_LAUNCH_SUCCESS_FINAL_2026-05-07.md` | C3 | Fly api side LIVE 達成、 GHA deploy.yml run 25475753541 14 step SUCCESS、 image deployment-01KR0AGKRFD39QZZJ10VWYZXS5 bind、 OpenAPI v0.3.4 paths=182 live | launch ops (api side LIVE) |
| 46 | `R8_LIVE_API_SHAPE_2026-05-07.md` | C3 | live API shape verify、 OpenAPI 182 path topology + tag 整合 + 業法 17 sensitive route 確認 | launch ops |
| 47 | `R8_LIVE_FINAL_VERIFY_2026-05-07.md` | C3 | 5/7 hardening LIVE smoke + 5/6 baseline diff、 image eabe358 反映確認 | launch ops |
| 48 | `R8_LIVE_OBSERVATORY_2026-05-07T0700Z.md` | C3 | 07:00Z 時点 live observatory snapshot、 healthz/readyz/deep 全 200 + paths=182 + sentry_active=true | launch ops |
| 49 | `R8_MANIFEST_BUMP_EVAL_2026-05-07.md` | C2 | manifest 139→146 bump 評価、 7 post-manifest tool 全 READY だが sample_arguments 欠落、 v0.3.5 patch bump 候補 (operator decision 待ち) | READY (operator decision) |
| 50 | `R8_MANIFEST_SYNC_VERIFY_2026-05-07.md` | C2 | 5 manifest (pyproject + server.json + dxt/manifest.json + smithery + mcp-server.json) × 6 axis sync verify、 hold-at-139 全件 SYNC | READY |
| 51 | `R8_MCP_FULL_COHORT_2026-05-07.md` | C2 | mcp.list_tools() runtime 146 (139 manifest floor + 7 post-manifest) を full cohort flag set で実証、 +36協定 で 148 | READY |
| 52 | `R8_NEXT_SESSION_2026-05-07.md` | C5 | 次 session queue (Step 3-4 未実行)、 累積 28 commit / ~2,369 file change / +302,269 / -44,279 行、 NO-GO 維持 | READY (forward plan) |
| 53 | `R8_OBSERVABILITY_LIVE_2026-05-07.md` | C6 | observability live audit、 sentry / OpenTelemetry / structured log 軸の本番出力検証 | DEEP AUDIT FINDING |
| 54 | `R8_OPERATOR_UI_PACKAGE_2026-05-07.md` | C3 | operator UI package、 公開 OAuth client 登録 + Stripe Dashboard 操作 + DNS sender domain の 1 surface package | launch ops |
| 55 | `R8_PAGES_DEPLOY_GHA_2026-05-07.md` | C3 | Cloudflare Pages direct deploy via GHA workflow、 wrangler-direct 経由ではなく pages-deploy.yml workflow_dispatch path | launch ops |
| 56 | `R8_PERF_BASELINE_2026-05-07.md` | C6 | production performance baseline + p99 latency audit、 healthz / openapi / programs/search 軸 latency 計測 | DEEP AUDIT FINDING |
| 57 | `R8_POST_DEPLOY_SMOKE_FULL_2026-05-07.md` | C2 | post_deploy_smoke.py 5 module 全 GREEN (health / routes 240/240 / mcp 148 tools / disclaimer 17/17 / stripe SKIP)、 local boot 確認 | READY |
| 58 | `R8_POST_DEPLOY_SMOKE_LOCAL_2026-05-07.md` | C2 | DEEP-61 smoke gate を local uvicorn boot 上で dry-run、 5 module gate 自体の verify 完走、 production 未点 | READY |
| 59 | `R8_PRE_DEPLOY_LIVE_BASELINE_2026-05-07.md` | C3 | 2026-05-07 02:54 UTC 時点 jpcite.com stale-token grep、 14 line tokens (`11,684 programs` / `本文 154` / `¥3/リクエスト`) baseline 固定 | launch ops (baseline) |
| 60 | `R8_PRECOMMIT_FINAL_16_2026-05-07.md` | C2 | pre-commit run --all-files exit=0、 16/16 hooks PASS、 LLM 0 / destructive 0、 全 fix deterministic | READY |
| 61 | `R8_PRECOMMIT_VERIFY_2026-05-07.md` | C2 | .pre-commit-config.yaml 全 hook inventory + per-hook detail audit、 構成 / version pin / exclude pattern verify | READY |
| 62 | `R8_PRIVACY_COMPLIANCE_DEEP_2026-05-07.md` | C6 | 個人情報保護法 + GDPR Art.13 privacy compliance deep audit、 privacy router enable 残 + DSAR フロー確認 | DEEP AUDIT FINDING |
| 63 | `R8_PROD_SMOKE_5_6_IMAGE_2026-05-07.md` | C3 | 5/6 image (f3679d6) 上の prod smoke 5 module、 mcp_tools_list 107/139 fail 但し runtime probe 146 PASS で gate-flag delta 説明、 他 4 module PASS | launch ops |
| 64 | `R8_PROD_SMOKE_5_7_LIVE_2026-05-07.md` | C3 | 5/7 v95 LIVE post deploy smoke、 OpenAPI paths 179→174 (env-flag drift) + /v1/privacy/* 2 path 新設、 healthz/readyz/deep 200 | launch ops |
| 65 | `R8_PRODUCTION_GATE_DASHBOARD_SUMMARY_2026-05-07.md` | C2 | aggregate_production_gate_status.py + 13/13 test PASS、 4 blocker pane で 3 RESOLVED + 1 BLOCKED (operator_ack の --dry-run 期待 rc=1) | READY |
| 66 | `R8_PUBLISH_PREP_AUDIT_2026-05-07.md` | C2 | post-launch SDK / DXT / Smithery / MCP-Registry sync publish-prep audit、 5 manifest × 6 axis 整合確認 | READY |
| 67 | `R8_PYPI_PUBLISH_DRY_2026-05-07.md` | C2 | PyPI publish dry build verify、 dist sdist + wheel + .mcpb 3 artifact build 整合 | READY |
| 68 | `R8_PYTEST_BASELINE_FAIL_AUDIT_2026-05-07.md` | C2 | pytest baseline 4476 collect / 2502 pass / 200 fail (--maxfail=200 stop) / 11 skip、 cluster A route_not_found regression 確認 | NO-GO partial (test debt) |
| 69 | `R8_PYTEST_CLUSTER_A_FIX_2026-05-07.md` | C6 | pytest cluster A fix audit、 pollution conftest 残 + envelope contract / lambda mock / banned phrase の trivial 修正完了 | FIX LANDED |
| 70 | `R8_R2_KEY_MINT_2026-05-07.md` | C6 | R2 key mint audit、 GHA secret installation for nightly-backup workflow | DEEP AUDIT FINDING |
| 71 | `R8_R2_TOKEN_ROTATION_2026-05-07.md` | C6 | R2 token rotation post chat-share leak protocol、 緊急ローテ済 + 新キー再投入 | FIX LANDED |
| 72 | `R8_RESTORE_DRILL_FIRST_RUN_2026-05-07.md` | C6 | restore drill first run、 manual trigger 2026-05-07、 9.7GB autonomath.db restore は不可 (GHA 制限) で jpintel.db のみ実行 | DEEP AUDIT FINDING |
| 73 | `R8_SECURITY_DEEP_SCAN_2026-05-07.md` | C6 | bandit + pip-audit + npm audit + Docker base scan + live CSP/CORS audit + gitleaks、 fastapi 0.119.1→0.120.4 + starlette CVE-2025-62727 + python-multipart CVE-2026-42561 close | FIX LANDED |
| 74 | `R8_SENTRY_DSN_PATH_2026-05-07.md` | C6 | sentry DSN path audit、 placeholder DSN safety + GlitchTip / self-hosted 代替 path 設計 | FIX LANDED |
| 75 | `R8_SEO_DRIFT_DEEP_DIVE_2026-05-07.md` | C6 | SEO drift deep dive、 jsonld Offer ¥500→¥3 schema drift fix + cohort desc trim + canonical drift 軸 | FIX LANDED |
| 76 | `R8_SEO_LIVE_SMOKE_2026-05-07.md` | C6 | post-launch SEO live smoke (jpcite.com)、 sitemap + robots + canonical + structured data の live 反映確認 | READY |
| 77 | `R8_SESSION_CLOSURE_2026-05-07.md` | C5 | session 累積 25+ commit / ~2,100+ file change / 33 spec / 14+ R7-R8 doc 最終 verification + operator manual 3 step 残 | READY (session close) |
| 78 | `R8_SESSION_LAUNCH_CLOSURE_2026-05-07.md` | C5 | session launch closure、 5/7 frontend LIVE + api LIVE 後の closure surface | READY (session close) |
| 79 | `R8_SITE_COPY_PROOFREAD_2026-05-07.md` | C6 | site copy proofread + SEO clarity audit、 site/ 全コピー文章の 法令文言 + 過剰約束 + brand 統一 検査 | DEEP AUDIT FINDING |
| 80 | `R8_SITE_HTML_AUDIT_2026-05-07.md` | C2 | site/ HTML 12,592 file doctype + UTF-8 整合、 JS 22 file node --check pass、 業法 sensitive 4 page legal-note envelope 整合、 secret leak 0 | READY (Cloudflare Pages publish) |
| 81 | `R8_SMOKE_FULL_GATE_2026-05-07.md` | C2 | AUTONOMATH_36_KYOTEI_ENABLED=1 で 36協定 pair を mandatory promote、 smoke gate 17/17 mandatory PASS / missing=0 / gated_off=0 | READY |
| 82 | `R8_SMOKE_GATE_FLAGS_2026-05-07.md` | C2 | smoke gate env-flag accounting、 36協定 pair gated_off_expected 仕様 (default OFF、 社労士法 review 待ち) と mcp_tools_list 107/139 false-negative 説明 | READY |
| 83 | `R8_STRIPE_WEBHOOK_LIVE_2026-05-07.md` | C6 | Stripe webhook live readiness audit、 webhook signing secret + idempotency + retry policy + signature verify 確認 | DEEP AUDIT FINDING |
| 84 | `R8_TEST_COVERAGE_DEEP_AUDIT_2026-05-07.md` | C6 | test coverage + flaky test deep audit、 mcp/server.py 低 coverage + 4476 collect / 2502 pass の cluster 化 | DEEP AUDIT FINDING |
| 85 | `R8_UX_AUDIT_2026-05-07.md` | C6 | live site UX audit (jpcite.com)、 12,592 page の navigation / form / CTA / mobile 軸 review | DEEP AUDIT FINDING |
| 86 | `R8_VERIFY_SCRIPTS_2026-05-07.md` | C2 | verify scripts inventory + 整合確認、 production_improvement_preflight + aggregate_production_gate_status + post_deploy_smoke + smoke_gate の 4 verify 軸 | READY |
| 87 | `R8_WRANGLER_LOCAL_ABANDONED_2026-05-07.md` | C3 | wrangler local CF Pages deploy 5 retry abandoned、 operator pages-deploy-main.yml workflow path 確定 | launch ops |

R8 doc 計 **87 file** (旧 v1 INDEX で 39 doc + deep audit batch 22 doc +
fix batch 8 doc + 公開 launch ops 補完 18 doc 増分)。 cluster 分布 →
C1=3 / C2=18 / C3=20 / C4=4 / C5=8 / C6=34 (deep audit + fix batch)。

---

## §2. cluster 別 grouping (5 旧 thematic + 新 C6 deep audit cluster)

### §2.1 C1 readiness audit (spec / acceptance / dep graph) — 3 doc

DEEP-22..57 33 spec の retroactive verify + CI guard 設計 + dep graph。
production gate spec verify axis に 寄与する readiness 軸。

- `R8_33_SPEC_RETROACTIVE_VERIFY.md` (286 assertion 全 PASS)
- `R8_ACCEPTANCE_CRITERIA_CI_GUARD.md` (CI guard 設計、 zero-touch)
- `R8_DEEP_CROSS_REFERENCE_MATRIX.md` (33 spec + 36 file dep graph)

### §2.2 C2 implementation verification (smoke / mcp / gate / billing / publish) — 18 doc

post_deploy_smoke 5-module + mcp cohort + manifest sync + 課金 fail-closed
+ pre-commit + production gate dashboard + publish prep。 implementation
完走の verify 軸。

- `R8_BILLING_FAIL_CLOSED_VERIFY.md` (4 修正点 全 PASS)
- `R8_CI_COVERAGE_MATRIX_2026-05-07.md` (5 workflow × hardening axis matrix)
- `R8_DXT_BUNDLE_EXPORT_2026-05-07.md` (.mcpb bundle health)
- `R8_HIGH_RISK_PENDING_LIST.md` (4 blocker NO-GO surface)
- `R8_MANIFEST_BUMP_EVAL_2026-05-07.md` (139→146 bump 評価)
- `R8_MANIFEST_SYNC_VERIFY_2026-05-07.md` (5 manifest sync)
- `R8_MCP_FULL_COHORT_2026-05-07.md` (146 floor 実証)
- `R8_POST_DEPLOY_SMOKE_FULL_2026-05-07.md` (5 module 全 GREEN)
- `R8_POST_DEPLOY_SMOKE_LOCAL_2026-05-07.md` (DEEP-61 dry-run)
- `R8_PRECOMMIT_FINAL_16_2026-05-07.md` (16/16 hook PASS)
- `R8_PRECOMMIT_VERIFY_2026-05-07.md` (hook inventory)
- `R8_PRODUCTION_GATE_DASHBOARD_SUMMARY_2026-05-07.md` (13/13 test PASS、 3 RESOLVED + 1 BLOCKED)
- `R8_PUBLISH_PREP_AUDIT_2026-05-07.md` (5 manifest × 6 axis)
- `R8_PYPI_PUBLISH_DRY_2026-05-07.md` (sdist + wheel + .mcpb 3 artifact)
- `R8_PYTEST_BASELINE_FAIL_AUDIT_2026-05-07.md` (200 fail / 2502 pass / 4476 collect)
- `R8_SITE_HTML_AUDIT_2026-05-07.md` (Cloudflare Pages publish readiness)
- `R8_SMOKE_FULL_GATE_2026-05-07.md` (36協定 ENABLED=1 で 17/17 mandatory)
- `R8_SMOKE_GATE_FLAGS_2026-05-07.md` (env flag accounting、 false-negative 説明)
- `R8_VERIFY_SCRIPTS_2026-05-07.md` (4 verify script inventory)

### §2.3 C3 launch ops (5/7 launch ops timeline / Fly deploy / frontend) — 20 doc

5/7 02:50-04:20 UTC ≈90 分の deploy attempt timeline + Fly readiness + GHA path
+ secret setup + Pre/Post-deploy smoke + frontend baton + 後続 deploy run。
Fly api side LIVE 達成 / Cloudflare Pages frontend LIVE 達成 後の launch ops
全 surface。

- `R8_DEPLOY_ATTEMPT_AUDIT_2026-05-07.md` (16 attempt 時系列、 origin/main 再 deploy 訂正)
- `R8_DEPLOY_RUN_25482086637_2026-05-07.md` (run 25482086637 verify)
- `R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md` (depot=false retry rationale)
- `R8_FLY_DEPLOY_READINESS_2026-05-07.md` (4 軸 readiness 全 PASS)
- `R8_FLY_HEALTH_CHECK_TUNING_2026-05-07.md` (grace + interval + timeout チューニング)
- `R8_FLY_SECRET_SETUP_GUIDE.md` (operator 5 secret 投入)
- `R8_FRONTEND_LAUNCH_STATUS_2026-05-07.md` (HANDOFF baton 継承、 deploy 未実行)
- `R8_FRONTEND_LAUNCH_SUCCESS_2026-05-07.md` (Pages frontend LIVE 達成)
- `R8_GHA_DEPLOY_PATH_2026-05-07.md` (release.yml + deploy.yml audit)
- `R8_LAUNCH_LIVE_STATUS_2026-05-07.md` (live discovery、 5/6 image 当初)
- `R8_LAUNCH_OPS_TIMELINE_2026-05-07.md` (16 attempt timeline、 ACK 8/8 PASS)
- `R8_LAUNCH_SUCCESS_FINAL_2026-05-07.md` (api side LIVE 達成、 v0.3.4 paths=182 live)
- `R8_LIVE_API_SHAPE_2026-05-07.md` (OpenAPI 182 path topology)
- `R8_LIVE_FINAL_VERIFY_2026-05-07.md` (5/7 hardening LIVE smoke)
- `R8_LIVE_OBSERVATORY_2026-05-07T0700Z.md` (07:00Z snapshot)
- `R8_OPERATOR_UI_PACKAGE_2026-05-07.md` (公開 OAuth + Stripe + DNS package)
- `R8_PAGES_DEPLOY_GHA_2026-05-07.md` (pages-deploy-main.yml path 確定)
- `R8_PRE_DEPLOY_LIVE_BASELINE_2026-05-07.md` (stale-token baseline)
- `R8_PROD_SMOKE_5_6_IMAGE_2026-05-07.md` (5/6 image smoke)
- `R8_PROD_SMOKE_5_7_LIVE_2026-05-07.md` (5/7 v95 LIVE post deploy smoke)
- `R8_WRANGLER_LOCAL_ABANDONED_2026-05-07.md` (wrangler local 5 retry 失敗、 GHA path 採用)

### §2.4 C4 manifest/sync (lane / ledger / executable artifacts) — 4 doc

dual-CLI lane atomic + AGENT_LEDGER append-only + executable_artifacts dry-run
+ codex lane review。 1-CLI solo override の policy ergonomic 軸。

- `R8_CODEX_LANE_REVIEW_2026-05-07.md` (codex CLI dormant 確認)
- `R8_DRY_RUN_VALIDATION_REPORT.md` (33 file dry-run、 LLM 0)
- `R8_LANE_GUARD_DESIGN_2026-05-07.md` (1-CLI solo vs 2-CLI policy)
- `R8_LANE_LEDGER_AUDIT_2026-05-07.md` (3 ledger append-only intact)
- `R8_LANE_POLICY_REVERIFY_2026-05-07.md` (solo lane re-verify、 codex dormant 継続)

### §2.5 C5 closure / synthesis / post-launch — 8 doc

最終 closure + final metric snapshot + final implementation manifest +
session closure (旧 + launch) + next session forward + 旧 INDEX (read-only
reference) + 本 v2 INDEX。 集約 / hub doc。

- `R8_CLOSURE_FINAL_2026-05-07.md` (25+ R8 + 7 R7 closure surface)
- `R8_FINAL_IMPLEMENTATION_MANIFEST_2026-05-07.md` (33 spec 完走、 19+ commit)
- `R8_FINAL_METRIC_SNAPSHOT_2026-05-07.md` (28 commit / ~3,160 file change)
- `R8_INDEX_2026-05-07.md` (旧 INDEX 24 doc、 SUPERSEDED、 read-only reference)
- `R8_INDEX_FINAL_2026-05-07.md` (本 v2、 87 R8 + 7 R7 final master)
- `R8_NEXT_SESSION_2026-05-07.md` (次 session forward plan)
- `R8_SESSION_CLOSURE_2026-05-07.md` (累積 verification + 3 operator step)
- `R8_SESSION_LAUNCH_CLOSURE_2026-05-07.md` (frontend LIVE + api LIVE 後 closure)

### §2.6 C6 deep audit (新 cluster、 deep audit batch + fix batch) — 34 doc

5/7 deep audit round 10 並列 で発見された finding + fix batch 8 並列 で
landed 修正。 旧 v1 INDEX には 不在 の 新 cluster (deep audit subdomain
で a11y / privacy / db integrity / cron reliability / observability /
disclaimer envelope / brand consistency / industry pack live audit /
restore drill / R2 key mint+rotation / sentry DSN path / SEO drift /
i18n / fly edge / perf baseline / error message clarity / audit log /
backup / security 多軸の cohort)。 finding doc は launch 後 1 week / 1
month / quarterly の backlog 入り (§5.x)。 fix batch 7 doc は production
LIVE 反映済 (image eabe358 取り込み)。

DEEP AUDIT FINDING (22 doc):
- `R8_ACCESSIBILITY_DEEP_2026-05-07.md` (WCAG 2.1 AA + mobile)
- `R8_AI_CONSUMER_AUDIT_2026-05-07.md` (OpenAPI / tag / q-alias 一貫性)
- `R8_AUDIT_LOG_DEEP_2026-05-07.md` (ULID + traceability)
- `R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md` (DR readiness)
- `R8_BRAND_CONSISTENCY_DEEP_2026-05-07.md` (jpcite vs autonomath drift)
- `R8_CRON_RELIABILITY_DEEP_2026-05-07.md` (11 cron retry/dedup)
- `R8_DB_INTEGRITY_AUDIT_2026-05-07.md` (FK/unique/check constraint)
- `R8_DISCLAIMER_LIVE_VERIFY_2026-05-07.md` (17 sensitive route _disclaimer 包絡)
- `R8_ERROR_MESSAGE_CLARITY_2026-05-07.md` (envelope clarity 4 軸)
- `R8_FINAL_INTEGRATION_SMOKE_2026-05-07.md` (post-secret 503→405 promotion)
- `R8_FLY_EDGE_ROUTING_FIX_2026-05-07.md` (SJC tax mitigation 提案)
- `R8_GHA_R2_SECRETS_OPERATOR_2026-05-07.md` (R2 secret operator gap)
- `R8_I18N_DEEP_AUDIT_2026-05-07.md` (12 EN page + body_en gap)
- `R8_INDUSTRY_PACK_LIVE_AUDIT_2026-05-07.md` (Wave 23 NTA saiketsu thin)
- `R8_OBSERVABILITY_LIVE_2026-05-07.md` (sentry / OTel / structured log)
- `R8_PERF_BASELINE_2026-05-07.md` (p99 latency baseline)
- `R8_PRIVACY_COMPLIANCE_DEEP_2026-05-07.md` (個人情報保護法 + GDPR Art.13)
- `R8_R2_KEY_MINT_2026-05-07.md` (GHA R2 secret install)
- `R8_RESTORE_DRILL_FIRST_RUN_2026-05-07.md` (manual trigger first run)
- `R8_SITE_COPY_PROOFREAD_2026-05-07.md` (法令文言 + 過剰約束)
- `R8_STRIPE_WEBHOOK_LIVE_2026-05-07.md` (signing secret + idempotency)
- `R8_TEST_COVERAGE_DEEP_AUDIT_2026-05-07.md` (mcp/server.py 低 coverage)
- `R8_UX_AUDIT_2026-05-07.md` (12,592 page navigation/CTA/mobile)

FIX LANDED (8 doc):
- `R8_BACKUP_FIX_2026-05-07.md` (defect A nightly backup 修正)
- `R8_DOC_GAP_DEEP_2026-05-07.md` (4 front-matter + 4 rollback section)
- `R8_PYTEST_CLUSTER_A_FIX_2026-05-07.md` (envelope/lambda/banned phrase trivial)
- `R8_R2_TOKEN_ROTATION_2026-05-07.md` (chat-share leak protocol post 緊急)
- `R8_SECURITY_DEEP_SCAN_2026-05-07.md` (3 CVE close、 fastapi+starlette+multipart bump)
- `R8_SENTRY_DSN_PATH_2026-05-07.md` (placeholder DSN safety + GlitchTip)
- `R8_SEO_DRIFT_DEEP_DIVE_2026-05-07.md` (jsonld Offer ¥500→¥3 + brand fix)
- `R8_SEO_LIVE_SMOKE_2026-05-07.md` (post-launch jpcite.com sitemap+robots)

READY (3 doc; deep audit cluster 内で finding 不在で READY のもの):
(C6 cluster 内に純 READY doc は無し — 全 doc が finding or fix を含む)

---

## §3. cross-reference graph (87 R8 doc 間 + R7 doc + handoff)

旧 v1 INDEX で確定した R7→R7 / R8→R7 / R8→R8 graph は全保持 (旧 v1 read-only
reference)。 v2 で追加される edge は **C6 cluster 内 fix→deep finding 関係**
+ **C3 → C6 (launch ops × deep audit) 関係**。

### §3.1 C6 deep audit cluster 内部参照 (新)

```
R8_FINAL_INTEGRATION_SMOKE   →  R8_DISCLAIMER_LIVE_VERIFY   (17 sensitive route 包絡 同一 surface)
R8_FINAL_INTEGRATION_SMOKE   →  R8_SECURITY_DEEP_SCAN       (CVE 3 close 後 deploy)
R8_FINAL_INTEGRATION_SMOKE   →  R8_OBSERVABILITY_LIVE       (sentry_active=true 観測)
R8_AUDIT_LOG_DEEP            →  R8_DB_INTEGRITY_AUDIT       (ULID 統一 + FK)
R8_BACKUP_RESTORE_DRILL      →  R8_BACKUP_FIX               (defect A → drill)
R8_BACKUP_RESTORE_DRILL      →  R8_RESTORE_DRILL_FIRST_RUN  (manual trigger 結果)
R8_BACKUP_RESTORE_DRILL      →  R8_R2_KEY_MINT              (R2 secret 投入)
R8_BACKUP_RESTORE_DRILL      →  R8_R2_TOKEN_ROTATION        (post-leak 再投入)
R8_PRIVACY_COMPLIANCE_DEEP   →  R8_AUDIT_LOG_DEEP           (個人情報 + audit trail)
R8_AI_CONSUMER_AUDIT         →  R8_ERROR_MESSAGE_CLARITY    (envelope 4 軸)
R8_AI_CONSUMER_AUDIT         →  R8_LIVE_API_SHAPE           (OpenAPI 182 path topology)
R8_BRAND_CONSISTENCY_DEEP    →  R8_SEO_DRIFT_DEEP_DIVE      (brand drift × SEO)
R8_BRAND_CONSISTENCY_DEEP    →  R8_SITE_COPY_PROOFREAD      (brand × copy)
R8_I18N_DEEP_AUDIT           →  R8_SITE_COPY_PROOFREAD      (12 EN page 軸 overlap)
R8_DISCLAIMER_LIVE_VERIFY    →  R8_INDUSTRY_PACK_LIVE_AUDIT (§52/§72 sensitive 17 route)
R8_PERF_BASELINE             →  R8_FLY_EDGE_ROUTING_FIX     (p99 × SJC tax)
R8_FLY_EDGE_ROUTING_FIX      →  R8_FLY_HEALTH_CHECK_TUNING  (Tokyo 直ルート × grace tuning)
R8_TEST_COVERAGE_DEEP        →  R8_PYTEST_CLUSTER_A_FIX     (mcp/server.py × cluster A)
R8_TEST_COVERAGE_DEEP        →  R8_PYTEST_BASELINE_FAIL     (200 fail × coverage)
R8_CRON_RELIABILITY_DEEP     →  R8_BACKUP_FIX               (nightly-backup × cron)
R8_CRON_RELIABILITY_DEEP     →  R8_R2_KEY_MINT              (GHA secret × cron)
R8_STRIPE_WEBHOOK_LIVE       →  R8_BILLING_FAIL_CLOSED      (4 修正点 × webhook)
R8_UX_AUDIT                  →  R8_ACCESSIBILITY_DEEP       (UX × WCAG)
R8_UX_AUDIT                  →  R8_SITE_COPY_PROOFREAD      (UX × copy)
R8_GHA_R2_SECRETS_OPERATOR   →  R8_R2_KEY_MINT              (operator gap × mint)
R8_GHA_R2_SECRETS_OPERATOR   →  R8_R2_TOKEN_ROTATION        (operator gap × rotate)
```

### §3.2 C3 launch ops → C6 deep audit (新)

```
R8_LIVE_OBSERVATORY_0700Z    →  R8_FINAL_INTEGRATION_SMOKE  (07:00Z snapshot × post-secret)
R8_OPERATOR_UI_PACKAGE       →  R8_FINAL_INTEGRATION_SMOKE  (5 secret 投入後 verify)
R8_LAUNCH_SUCCESS_FINAL      →  R8_DISCLAIMER_LIVE_VERIFY   (api LIVE × 17 sensitive route)
R8_LAUNCH_SUCCESS_FINAL      →  R8_LIVE_API_SHAPE           (api LIVE × 182 path topology)
R8_FRONTEND_LAUNCH_SUCCESS   →  R8_SEO_LIVE_SMOKE           (frontend LIVE × jpcite.com SEO)
R8_FRONTEND_LAUNCH_SUCCESS   →  R8_UX_AUDIT                 (frontend LIVE × 12,592 page UX)
R8_FRONTEND_LAUNCH_SUCCESS   →  R8_BRAND_CONSISTENCY_DEEP   (frontend LIVE × brand)
R8_PROD_SMOKE_5_7_LIVE       →  R8_PERF_BASELINE            (5/7 LIVE × p99 baseline)
R8_PROD_SMOKE_5_7_LIVE       →  R8_OBSERVABILITY_LIVE       (5/7 LIVE × sentry/OTel/log)
```

### §3.3 R8 doc → R7 doc 上流参照 (旧 v1 から保持)

旧 v1 INDEX で確定した: R8_FINAL_IMPLEMENTATION_MANIFEST + R8_SESSION_CLOSURE
が R7 全 7 doc を inputs として consume。 5/7 launch ops cluster + C6 deep
audit cluster は R7 doc を直接参照しない (launch operational scope / deep
audit subdomain scope のため)。

### §3.4 closure cluster (C5) → 全 cluster 参照 (v2 拡張)

```
R8_CLOSURE_FINAL              →  R8_INDEX (旧 v1)
R8_CLOSURE_FINAL              →  R8_FINAL_METRIC_SNAPSHOT
R8_CLOSURE_FINAL              →  R8_HIGH_RISK_PENDING_LIST
R8_CLOSURE_FINAL              →  R8_FINAL_IMPLEMENTATION_MANIFEST
R8_CLOSURE_FINAL              →  R8_SESSION_CLOSURE
R8_CLOSURE_FINAL              →  R8_LAUNCH_SUCCESS_FINAL (C3 hub)
R8_INDEX_FINAL (本 v2)        →  R8_INDEX (旧 v1, SUPERSEDED, read-only)
R8_INDEX_FINAL                →  R8_DEEP_AUDIT_CLOSURE_2026-05-07 (新、 別 file)
R8_INDEX_FINAL                →  R8_FINAL_INTEGRATION_SMOKE
R8_INDEX_FINAL                →  R8_SESSION_LAUNCH_CLOSURE
R8_INDEX_FINAL                →  HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP
R8_DEEP_AUDIT_CLOSURE         →  R8_INDEX_FINAL
R8_DEEP_AUDIT_CLOSURE         →  C6 全 34 doc
R8_SESSION_LAUNCH_CLOSURE     →  R8_LAUNCH_SUCCESS_FINAL
R8_SESSION_LAUNCH_CLOSURE     →  R8_FRONTEND_LAUNCH_SUCCESS
```

### §3.5 circular detection

graph 全体に **循環参照は検出されず**。 R7→R7 / R8→R7 / R8→R8 / C3 内部
/ C6 内部 / C3↔C6 全て DAG。 hub doc (R7_SYNTHESIS / R8_CLOSURE_FINAL /
R8_INDEX_FINAL / R8_LAUNCH_SUCCESS_FINAL / R8_DEEP_AUDIT_CLOSURE) は 出次数
大 / 入次数 小 で source 側に立つ。

---

## §4. 5/7 LIVE state (4 軸 framing 維持)

| axis | state | source doc |
|---|---|---|
| **Fly api side** | LIVE 達成、 image deployment-eabe358-25481404553 (machine 85e273f4e60778, nrt v100)、 OpenAPI v0.3.4 paths=182 live、 healthz/readyz/deep 全 200、 sentry_active=true | R8_LAUNCH_SUCCESS_FINAL §1, R8_FINAL_INTEGRATION_SMOKE §4, R8_LIVE_OBSERVATORY_0700Z |
| **Cloudflare Pages frontend** | LIVE 達成、 commit eabe358 jpcite frontend LIVE on Cloudflare Pages、 site/ 12,592 file deploy 完了 | R8_FRONTEND_LAUNCH_SUCCESS, R8_SEO_LIVE_SMOKE |
| **GHA deploy run (latest)** | run 25481404553 (SHA b1de8b2) は失敗、 image は eabe358 で stable | R8_FINAL_INTEGRATION_SMOKE §1, R8_DEPLOY_RUN_25482086637 |
| **anonymous rate limit** | LIVE — 3/day per IP、 JST 翌 00:00 reset 観測 | R8_LAUNCH_LIVE_STATUS §1 |
| **Stripe live mode** | live keys deployed (5 secret) — 但し Dashboard UI activate 残 | R8_LAUNCH_LIVE_STATUS §1, R8_STRIPE_WEBHOOK_LIVE |
| **Google OAuth** | secret 投入済 (5 secret 全て injection 確認)、 503→405 promotion で route 配線確認 | R8_FINAL_INTEGRATION_SMOKE §2 |
| **GitHub OAuth** | secret 投入済 (GITHUB_OAUTH_CLIENT_ID/SECRET) だが **route 未配線** (`/v1/auth/github/start` not found in OpenAPI) | R8_FINAL_INTEGRATION_SMOKE §2 |
| **Sentry** | DSN 投入済、 sentry_active=true on /v1/am/health/deep | R8_FINAL_INTEGRATION_SMOKE §3, R8_SENTRY_DSN_PATH |
| **OpenAPI live drift** | local 227 vs live 179→182 (env-flag gating、 deploy bug ではない) | R8_LAUNCH_LIVE_STATUS §1, R8_LIVE_API_SHAPE |
| **mcp_tools_list smoke** | 107/139 FAIL gate (gate-flag delta、 runtime probe 146 PASS で false-negative) | R8_PROD_SMOKE_5_6_IMAGE / R8_SMOKE_GATE_FLAGS |

framing: 「launched (= 商用稼働)」 とは 呼ばず、 **「Fly api side LIVE +
Cloudflare Pages frontend LIVE / Stripe live mode UI activate 残 + GitHub
OAuth route 配線残」**。 数値主張は 内部 session window 計測値、 forward
production verify (実 customer flow / 実 Stripe live charge) は未実施。

---

## §5. 残 backlog (launch 後 1 week / 1 month / quarterly)

deep audit cluster (C6) で発見した finding を時間軸 backlog として整理。
production deploy verify サイクル後の operator 介在前提。

### §5.1 launch 後 1 week 以内 fix (4 件)

1. **pollution conftest 残** — pytest cluster A は trivial 修正完了 (R8_PYTEST_CLUSTER_A_FIX)、 200 fail / 11 skip の cluster B/C は test pollution conftest 残で baseline は依然 fail (R8_PYTEST_BASELINE_FAIL_AUDIT)。 1 week で test pollution conftest を分離 → cluster B/C fail 数 200 → 50 以下 期待
2. **cron reliability 残** — nightly-backup defect A は landed (R8_BACKUP_FIX)、 残 11 cron workflow の retry / dedup / idempotency 検証 (R8_CRON_RELIABILITY_DEEP)、 dispatch_webhooks.py + run_saved_searches.py 軸の retry policy hardening
3. **privacy router enable** — privacy compliance deep audit (R8_PRIVACY_COMPLIANCE_DEEP) で `/v1/privacy/*` 2 path は live 反映済 (R8_PROD_SMOKE_5_7_LIVE) だが DSAR フロー router enable は operator decision 待ち、 1 week 以内に enable + 個人情報保護法 §28 開示請求対応 path 確立
4. **am_region FK** — DB integrity audit (R8_DB_INTEGRITY_AUDIT) で am_region (1,966 rows) の 5-digit code FK 整合は full coverage、 但し `programs` 側の prefecture/municipality 欠損 9,509/11,350 (legacy) と FK link rebuild 残

### §5.2 launch 後 1 month 以内 fix (4 件)

1. **GDPR Art.13 individual rights** — privacy compliance deep audit で個人情報保護法 §28 + GDPR Art.13/15-22 の DSAR 通知文言 + email template 整備、 1 month で `/v1/privacy/dsar/request` + `/v1/privacy/dsar/status` の self-service path 確立
2. **mcp/server.py coverage** — test coverage deep audit (R8_TEST_COVERAGE_DEEP_AUDIT) で `mcp/server.py` 低 coverage (推定 65%)、 1 month で 4220 行 server.py の 139 tool 各 happy-path test 追加 → 85%+ 到達
3. **body_en bulk ETL** — i18n deep audit (R8_I18N_DEEP_AUDIT) で migration 090 で `law_articles.body_en` 列追加済、 batch_translate_corpus.py で foreign FDI cohort 用 9,484 row × 上位 1,500 row 翻訳バッチ実行、 1 month で foreign FDI cohort 公開
4. **EN site translation 12 page** — i18n deep audit で site/ 12 EN page (audiences/foreign-investor/* + lawyer-foreign-tax/*) の翻訳整備、 1 month で site/_templates/program_en.html + 上位 program 50 件 EN 翻訳

### §5.3 quarterly 以内 fix (3 件)

1. **Fly edge SJC mitigation (CF orange-cloud)** — Fly edge routing fix (R8_FLY_EDGE_ROUTING_FIX) で SJC tax (Tokyo→SJC→Tokyo round-trip 200ms+) の mitigation 提案、 quarterly で Cloudflare orange-cloud + Fly Tokyo 直接ルーティング設計、 p99 latency 改善目標 -150ms
2. **am_region table rebuild** — DB integrity audit で am_region 1,966 rows の 5-digit code 完全 (47都道府県 × 1,919 市区町村) だが am_entity_facts × am_region join hot path が緩い、 quarterly で am_region rebuild + am_entity_facts.region_id index hardening
3. **dev npm vitest 4.x major** — security deep scan (R8_SECURITY_DEEP_SCAN) で npm dev-only 5 CVE は vitest 3.x で全 close、 但し vitest 4.x major bump で SDK plugin 4 件 (freee / mf / kintone / slack) の test surface 整理、 quarterly で vitest 4.x major bump

---

## §6. cross-link to handoff + R7 prior cycle

### §6.1 5/7 baton: HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md

`/Users/shigetoumeda/jpcite/tools/offline/_inbox/HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md`
(151 line, 11:51 JST、 prior codex CLI が Pages deploy 直前で停止) を
本 INDEX § §2.3 C3 cluster + §5.1 で参照。 引き継ぎ 3 dirty file は
R8_FRONTEND_LAUNCH_SUCCESS で deploy LIVE 反映済、 baton は完了。

### §6.2 R7 prior cycle: 旧 INDEX §2 R7 doc 7 file

旧 `R8_INDEX_2026-05-07.md` §2 で確定した R7 doc 7 file (R7_03_codex_rewatch
/ R7_04_loop_closure_surface / R7_AI_DOABLE / R7_ARR_SIGNALS / R7_FAILURE_MODES
/ R7_OPERATOR_ACTIONS / R7_SYNTHESIS) は本 v2 INDEX でも全保持。 `R7_SYNTHESIS`
が R7 round central hub、 SOT v0.3.4 / 227 OpenAPI / 139 MCP の 3 軸主張を
旧 INDEX §6 で 1 表 化。 5/7 LIVE state では `139 manifest floor` が
依然有効 (manifest hold-at-139 維持)、 runtime 146/148 は post-manifest cohort。

### §6.3 prior INDEX as historical baseline

旧 v1 `R8_INDEX_FINAL_2026-05-07.md` (39 doc snapshot) は本 v2 で
in-place update された (Edit、 destructive 上書き 0 規則は本 doc 自身の
update 1 件は許容、 他 86 file read-only)。 cycle 後 48 doc (C6 deep
audit 34 + C3 launch ops 補完 8 + C2 publish 補完 3 + C4 補完 2 + C5
closure 系 1) 増分が本 INDEX で吸収。 旧 `R8_INDEX_2026-05-07.md` (24 doc)
は SUPERSEDED marker のみ (read-only)、 LLM API 0、 内部仮説 framing 維持。

---

## §7. operator next step (5/7 LIVE state v2 後の確定版)

1. **Stripe live mode UI activate** (Dashboard billing portal config + tax enabled flip、 R8_LAUNCH_LIVE_STATUS §1 + R8_STRIPE_WEBHOOK_LIVE。 secret は投入済、 UI activation 残)
2. **公開 OAuth UI 追加配線** (Google は LIVE、 GitHub は secret 投入済だが route 未配線。 R8_FINAL_INTEGRATION_SMOKE §2 — `/v1/auth/github/start` + `/v1/auth/github/callback` を api/main.py に追加)
3. **deploy run 25481404553 retry** (SHA b1de8b2 image bump 失敗、 GHA dispatch retry または image rebuild)
4. operator action 後 verify cycle (post-Stripe-UI + post-GitHub-route + post-image-bump) を loop 回し、 frontend 軸 5xx=0 / OAuth flow round-trip / Stripe live mode test charge 全 PASS で **商用稼働 GO**
5. v0.3.5 manifest bump (139→146、 R8_MANIFEST_BUMP_EVAL §3 publish flow) を operator decision で打つか hold
6. backlog §5.1 (1 week) → §5.2 (1 month) → §5.3 (quarterly) で漸次 fix サイクル
7. R7_OPERATOR_ACTIONS から 46 item 主要カテゴリ (旧 v1 §5.2 維持) — A. OAuth/鍵 custody / B. 商業登記 / C. 財務/法的判断 / D. organic outreach / E. DNS/sender domain

---

(end of FINAL master index v2)
