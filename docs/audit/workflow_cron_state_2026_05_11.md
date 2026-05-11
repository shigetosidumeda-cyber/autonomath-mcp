# Workflow + Cron 全棚卸し (2026-05-11)

audit owner: jpcite ops (info@bookyou.net)
audit date: 2026-05-11
scope: `.github/workflows/*.yml` (100 files), `scripts/cron/*.py|*.sh` (75 files),
`gh run list -L 300`, `gh workflow list --all`.
sampling: `runs=2..100/workflow` (varies by trigger frequency).

> 注意: action のみの audit。disable/delete は user 承認案件として top-5 提案で留める。
> 旧 brand 露出は SEO 移行用 marker としてのみ最小表記。

---

## 0. Headline

| 指標 | 値 |
| --- | --- |
| workflow files (.yml) | **100** |
| GHA に register された workflows | **99** (+ Dependabot Updates) |
| 連続 failure 3 回以上 | **9** workflow |
| 直近 run = failure | **18** workflow |
| 過去 100 run 内に登場せず (sample 範囲) | **~50** workflow (大半は schedule 待ち、正常) |
| `NEVER_RAN` (gh API) | **13** workflow |
| stale (>7 日 run なし) | **4** workflow |
| 必要 secrets (workflow yml で参照) | **39** 種 |
| 実際に repo に設定されている secrets | **8** 種 |
| **不足 secrets** | **35** 種 (うち `GITHUB_TOKEN` は GHA 自動付与で実害なし) |

---

## A. 全 workflow list + 状態 (要点)

### A-1. 連続 failure 中 (3 回以上)

| workflow | streak | latest_fail | 主因 (1 行要約) |
| --- | --- | --- | --- |
| `acceptance-criteria-ci` | **22 回** | 2026-05-11 | `automation_ratio=0.2287 (target 0.795)` — DEEP-59 自動化 gate を超えていない (16/61 passed) |
| `narrative-sla-breach-hourly` | **15 回** | 2026-05-11 02:58 | flyctl ssh で `TG_BOT_TOKEN` / `TG_CHAT_ID` 空 → `exec: "export": executable file not found` |
| `distribution-manifest-check` | **12 回** | 2026-05-11 | `forbidden:¥3/req` が `site/pricing.html` 等 5 か所で `DRIFT` (forbidden token を pricing UI に残してしまった) |
| `pages-deploy-main` | **11 回** | 2026-05-11 04:17 | `[check_geo_readiness] FAIL  site/_redirects contains loop-prone rule` — 本セッションの mkdocs nav + CF secret 修正は完了したが、別 gate (_redirects regex `(?m)^/[^\s]+\s+/[^\s]*\.html`) で fail。**残課題** |
| `fingerprint-sot-guard` | **11 回** | 2026-05-11 | `ModuleNotFoundError: No module named 'fastapi'` (conftest.py が fastapi import するが workflow が install していない) |
| `refresh-sources-daily` | (本日 1 件) | 2026-05-10 | `refresh_sources.py: error: unrecognized arguments: --enrich` (CLI 引数 drift) |
| `refresh-sources-weekly` | (本日 1 件) | 2026-05-10 | 同上 |
| `kokkai-shingikai-weekly` | (本日 1 件) | 2026-05-10 | `FATAL: autonomath.db missing` (CI runner に DB を hydrate していない) |
| `municipality-subsidy-weekly` | (本日 1 件) | 2026-05-10 | `FATAL: jpintel.db missing` (同上、別 DB) |

### A-2. 直近 run = failure (上記含む 18 件)

A-1 の 9 件に加え、以下 9 件:

| workflow | latest | 主因 |
| --- | --- | --- |
| `egov-pubcomment-daily` | 2026-05-11 | `FATAL: autonomath.db missing` |
| `alias-expansion-weekly` | 2026-05-09 | `fatal: invalid refspec 'alias-expansion/$(date -u +%Y-%m-%d)'` (shell expansion がそのまま branch 名に embed) |
| `practitioner-eval-publish` | 2026-05-09 | `ERROR: JPCITE_API_KEY missing` (secret 未設定) |
| `production-gate-dashboard-daily` | 2026-05-10 | `Input required and not supplied: apiToken` + `Credentials could not be loaded` (CLOUDFLARE_API_TOKEN / AWS 未設定) |
| `publish_text_guard` | 2026-05-10 | exit 1 (詳細未取得、scheduled でなく workflow_dispatch のみ) |
| `health-drill-monthly` | **2026-05-01** | `flyctl auth login` — FLY_API_TOKEN 経路は通っているが workflow 側で別 token 経路 |
| `ingest-monthly` | **2026-05-01** | 同上 (flyctl ssh fail) |
| `nta-bulk-monthly` | **2026-05-01** | 同上 |
| `ingest-weekly` | 2026-05-10 | `ModuleNotFoundError: No module named 'scripts'` (fly app 内 PYTHONPATH ずれ) |

### A-3. stale (>7 日 run なし)

| workflow | last_run | streak |
| --- | --- | --- |
| `health-drill-monthly` | 2026-05-01 | monthly cron `15 18 1 * *` だが次回まで未着火 |
| `ingest-monthly` | 2026-05-01 | monthly cron `20 21 1 * *` |
| `nta-bulk-monthly` | 2026-05-01 | monthly cron `10 18 1 * *` |
| `sdk-publish` | 2026-04-30 | push trigger のみ、対象 path 変更なし |

### A-4. `NEVER_RAN` (gh API: 1 件も run 履歴がない)

cron 設定済だが一度も発火していない / dispatch 待ち。

```
acceptance_check                  schedule '0 18 * * 0'  # 週次日曜
brand-signals-weekly              schedule '0 21 * * 1'  # 月曜
evolution-dashboard-weekly        schedule '0 3 * * 2'   # 火曜
geo_eval                          schedule '0 0 * * 1'   # 月曜
industry-journal-mention-monthly  schedule '0 21 15 * *' # 月 15 日
loadtest                          workflow_dispatch のみ (OK)
narrative-audit-monthly           schedule '0 0 1 * *'   # 月初
og-images                         schedule '17 18 * * 0' # 日曜
organic-outreach-monthly          schedule '0 21 1 * *'  # 月初
populate-calendar-monthly         schedule '0 18 5 * *'  # 月 5 日
precompute-recommended-monthly    schedule '0 18 1 * *'  # 月初
quarterly-reports-cron            schedule '0 0 1 1,4,7,10 *' # 四半期
rebrand-notify-once               workflow_dispatch のみ (OK)
```

判定: `loadtest` / `rebrand-notify-once` は dispatch-only で正常。
他 11 件は cron 設定済なのに着火していない → **cron schedule 次回到来待ち** (weekly/monthly が多く、新規追加されたばかりで初回未到達)。GitHub Actions は repo が 60 日 inactive で cron disable する仕様だが、本 repo は毎日 push があるため該当しない。

### A-5. 主な健全 workflow (直近成功、参考)

```
CodeQL                                  2026-05-11 success
data-integrity                          2026-05-11 success
e2e                                     2026-05-11 success
eval                                    2026-05-11 success
lane-enforcer                           2026-05-11 success
openapi                                 2026-05-11 success
release-readiness-ci                    2026-05-11 success
dispatch-webhooks-cron (10min cron)     2026-05-11 success
ingest-offline-inbox-hourly             2026-05-11 success
idempotency-sweep-hourly                2026-05-11 success
same-day-push-cron (30min cron)         2026-05-11 success
stripe-version-check-weekly             2026-05-11 success
amendment-alert-cron / fanout-cron      2026-05-10 success
nightly-backup                          2026-05-10 success
ingest-daily                            2026-05-10 success
```

---

## B. secret 不足 list

### B-1. 設定済 secrets (8 種)

```
CF_ACCOUNT_ID                  2026-05-11 (本セッション設定)
CF_API_TOKEN                   2026-05-11 (本セッション設定)
FLY_API_TOKEN                  2026-05-02
PRODUCTION_DEPLOY_OPERATOR_ACK_YAML 2026-05-07
R2_ACCESS_KEY_ID               2026-05-07
R2_BUCKET                      2026-05-07
R2_ENDPOINT                    2026-05-07
R2_SECRET_ACCESS_KEY           2026-05-07
```

### B-2. 不足 secrets (35 種, 用途別)

| secret | 使用 workflow | 影響度 |
| --- | --- | --- |
| `GITHUB_TOKEN` | 全般 | OK (GHA 自動付与、設定不要) |
| `JPCITE_API_KEY` | practitioner-eval-publish | **HIGH** (本番 API 呼び weekly fail) |
| `JPCITE_ACCEPTANCE_KEY` | acceptance_check (NEVER_RAN) | HIGH (週次 acceptance 走らせる前提) |
| `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` | production-gate-dashboard-daily, pages-regenerate, など多数 | **HIGH** (`CF_API_TOKEN` だけ別名で設定済、変数名不一致) |
| `CF_ZONE_ID` | tls-check, index-now-cron | MEDIUM |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | production-gate-dashboard-daily, S3 系 | MEDIUM (代替で R2 使用済の可能性) |
| `TG_BOT_TOKEN` / `TG_CHAT_ID` | narrative-sla-breach-hourly | **HIGH** (15 連続失敗の直接原因) |
| `SENTRY_DSN` | narrative-sla-breach-hourly, 他多数 | MEDIUM (alert 経路、無いと skipped notice 出すだけで fail にはならない設計箇所も) |
| `POSTMARK_TOKEN` / `POSTMARK_API_TOKEN` / `POSTMARK_FROM_TX` / `POSTMARK_FROM_REPLY` | egov-pubcomment-daily, billing-health-cron, trial-expire-cron | MEDIUM |
| `OPERATOR_EMAIL_TO` | egov-pubcomment-daily | LOW |
| `NPM_TOKEN` | sdk-publish, sdk-publish-agents, sdk-republish, mcp-registry-publish | HIGH (publish blocked) |
| `PYPI_API_TOKEN` | sdk-publish (python lane) | HIGH |
| `JPCITE_BRAND_GITHUB_TOKEN` / `CROSS_REPO_PAT` / `GH_PAT_WATCH` | rebrand-notify-once, weekly-digest | LOW |
| `GSC_TOKEN` | refresh-sources, brand-signals | LOW |
| `BING_TOKEN` | refresh-sources, brand-signals | LOW |
| `INDEXNOW_HOST` / `INDEXNOW_KEY` | index-now-cron | LOW (warning-only path 設計) |
| `JPINTEL_DB_R` | municipality-subsidy-weekly, jpintel 系 | HIGH |
| `LOADTEST_PRO_KEY` / `LOADTEST_WEBHOOK_SECRET` | loadtest | LOW (workflow_dispatch のみ) |
| `SLACK_WEBHOOK_URL` / `SLACK_WEBHOOK_OPS` / `SLACK_WEBHOOK_INGEST` / `SLACK_WEBHOOK_COMPETITIVE` | 通知 hop 全般 | LOW (warning-only path) |
| `CODECOV_TOKEN` | test (codecov upload) | LOW |
| `STAGING_URL` | e2e | LOW (defaults to prod) |
| `R` | (誤検出: yml の `${{ secrets.R… }}` パターンに `R` 単体が混入) | NOOP |

### B-3. secret 経路 mismatch (yml の env_var 名 ≠ 設定済 secret 名)

`pages-deploy-main` などで `CLOUDFLARE_API_TOKEN` を参照しているが、repo には `CF_API_TOKEN` のみ。
**改名 or aliasing 必要**:

```
yml が要求: CLOUDFLARE_API_TOKEN        現存: CF_API_TOKEN
yml が要求: CLOUDFLARE_ACCOUNT_ID       現存: CF_ACCOUNT_ID
```

→ workflow yml を `CF_API_TOKEN` に統一する PR、または secret を両名で重複設定する運用。

---

## C. cron job 健全性

cron 設定 workflow 計 **64 本**。

### C-1. 高頻度 cron (>= 1 時間に 1 回)

| workflow | schedule (UTC) | 状態 |
| --- | --- | --- |
| `status_update` | `*/5 * * * *` (5 分) | scheduled (まだ run 履歴未取得、要 verify) |
| `dispatch-webhooks-cron` | `*/10 * * * *` (10 分) | **OK** (success 2026-05-11 01:27) |
| `same-day-push-cron` | `*/30 * * * *` (30 分) | OK |
| `stripe-backfill-30min` | `5,35 * * * *` | scheduled (queued) |
| `idempotency-sweep-hourly` | `15 * * * *` | OK |
| `sunset-alerts-cron` | `20 * * * *` | OK |
| `ingest-offline-inbox-hourly` | `25 * * * *` | OK |
| `narrative-sla-breach-hourly` | `0 * * * *` | **FAIL** (15 連続失敗) |

### C-2. daily / weekly / monthly cron の最終成功時刻

主要 daily (UTC 18:00–22:00 JST 03:00–07:00 帯) はほぼ 2026-05-10 中に success。
weekly / monthly は A-3 / A-4 参照。

### C-3. memory `feedback_legacy_brand_marker` 関連で記録された
`narrative-sla-breach-hourly 20 連続失敗` audit:
**現在は 15 連続** (本日 1 回追加 fail)。原因は TG_BOT_TOKEN/TG_CHAT_ID 空。

### C-4. 他 cron で同様の長期失敗

* `narrative-sla-breach-hourly` (15h+ streak)
* `acceptance-criteria-ci` (22 run streak, push trigger も含む)
* `distribution-manifest-check` (12 run streak, push trigger)
* `pages-deploy-main` (11 run streak, push trigger)
* `fingerprint-sot-guard` (11 run streak, PR trigger)

これら 5 本のうち、`acceptance-criteria-ci` / `distribution-manifest-check` / `fingerprint-sot-guard` / `pages-deploy-main` は **scheduled cron ではなく push/PR trigger なので毎 commit fail を積み上げる** タイプ。

---

## D. 本セッション中 (2026-05-11) の deploy 関連状態

### D-1. deploy.yml
* run **25646632328** = hydrate 25min timeout → 本セッションで 60min 拡張 fix 済 (commit 801b3d3)
* 最新 run **25647402999** (02:38 JST) = `skipped`
  * 原因: `workflow_run` trigger で `if: github.event.workflow_run.conclusion == 'success'` ガード、test workflow がまだ in_progress / queued のため deploy 側が skip された (正常な gate 動作)
* 本セッション 4-fix (smoke sleep / preflight tolerance / hydrate size guard / sftp rm idempotency) は **5/7 v95 b1de8b2** で land 済 (memory `feedback_deploy_yml_4_fix_pattern`)

### D-2. pages-deploy-main.yml
* run **25648947116 / 25649456507 / 25649497063 / 25649497475 / 25650010977** = 5 連続 failure
* 本セッションで:
  1. mkdocs nav の `exclude_docs` 12 dir 追加 (commit 9e93cee)
  2. CF secret `CF_ACCOUNT_ID` / `CF_API_TOKEN` 設定 (上記 5/11 04:14-17)
* **残課題 (NEW)**: 最新 run **25650010977** で `[check_geo_readiness] FAIL site/_redirects contains loop-prone rule:(?m)^/[^\s]+\s+/[^\s]*\.html`
  → `site/_redirects` の `.html` 経由 redirect が無限 loop 警告に該当
  → 別 audit (`site_docs_orphan_2026_05_11.md` と関連) で扱う案件

---

## E. 重複 / 冗長 workflow

### E-1. 同機能 workflow 群

| 機能 | 重複 file | 提案 |
| --- | --- | --- |
| sdk publish | `sdk-publish.yml`, `sdk-publish-agents.yml`, `sdk-republish.yml`, `mcp-registry-publish.yml` | 4 本構成。`sdk-publish` (npm + pypi 一括) を canonical にして agents は別 channel のみ、`republish` は force re-publish workflow_dispatch のみで OK (整理不要) |
| refresh-sources | `refresh-sources.yml` (multi-cron), `refresh-sources-daily.yml`, `refresh-sources-weekly.yml` | `refresh-sources.yml` 内に daily/weekly/monthly cron が **全部入っている** のに別 file が 2 本存在 → **重複** |
| ingest | `ingest-daily.yml`, `ingest-weekly.yml`, `ingest-monthly.yml` | 構造は健全だが、Fly ssh 経由で同じ `ingest_tier.py` を呼ぶ pattern が違うバージョンで 3 本に散らばっている (drift 注意) |
| backup | `nightly-backup.yml` (daily), `weekly-backup-autonomath.yml` (weekly) | OK (頻度別) |
| drift v3 系 | `facts_registry_drift_v3.yml`, `fence_count_drift_v3.yml`, `mcp_drift_v3.yml`, `openapi_drift_v3.yml`, `sitemap_freshness_v3.yml`, `structured_data_v3.yml`, `publish_text_guard.yml` | 1 ファイル 1 チェックで分割。**まとめても OK** (1 workflow で matrix にできる) |
| precompute | `precompute-actionable-daily.yml`, `precompute-data-quality-daily.yml`, `precompute-recommended-monthly.yml`, `precompute-refresh-cron.yml` | 用途別、整理不要 |

### E-2. 不要に分割された workflow (候補)

- v3 drift 系 7 本 → 1 workflow に統合可能 (matrix)
- `refresh-sources-daily.yml` / `refresh-sources-weekly.yml` は `refresh-sources.yml` と機能 overlap

---

## 即対処 top-5 (workflow 修復、user 承認案件)

1. **pages-deploy-main `_redirects` regex 修正**
   `site/_redirects` の `/foo /foo.html` パターンを `(?m)^/[^\s]+\s+/[^\s]*\.html` regex に一致しない書式へ書換 (e.g. status code 200 で内部 rewrite に統一)。本セッション最重要 (本番 docs site 5 連続 deploy fail 中)。

2. **secret name alias: `CLOUDFLARE_API_TOKEN` ↔ `CF_API_TOKEN`**
   pages-deploy-main 含め複数 yml が `CLOUDFLARE_API_TOKEN` 参照だが repo は `CF_API_TOKEN` のみ。
   → workflow 側を `CF_API_TOKEN` に統一する PR (1 commit、grep-replace)。同時に `CLOUDFLARE_ACCOUNT_ID` → `CF_ACCOUNT_ID`。

3. **narrative-sla-breach-hourly: `TG_BOT_TOKEN` / `TG_CHAT_ID` 設定**
   15 連続失敗、毎時 1 fail を積み上げ中。alert 配信 0 件。
   設定 1 件 + dispatch でリカバリ可。

4. **acceptance-criteria-ci `automation_ratio` 0.2287 → ≥0.795 引き上げ**
   22 連続 fail。push gate なので毎 PR 赤バッジ。
   `acceptance_criteria.yaml` の 61 件中 16 件しか automated 化されておらず、未自動化 45 件を逐次自動化するか、target を一時的に lower すべき (本セッション task #24 で 46 件分の修正案は別 audit に landed)。

5. **fingerprint-sot-guard: `fastapi` install を CI に追加**
   11 連続 fail。`pip install -e ".[dev,test,api]"` 等で fastapi を入れる step が抜けている。
   `requirements-test.txt` か workflow の `pip install` 行に `fastapi` 追加で復旧。

---

## 付録: workflow ごと一覧 (last 5 conclusions + status)

過去 100 run 内で 1 回以上 run 履歴のあった workflow のみ。Last 5 conclusions は古い→新しい順ではなく、新→古 (column 1 が最新)。

```
acceptance-criteria-ci          [F F F F F]  push/PR        22-streak FAIL
check-workflow-target-sync      [- F F F S]  PR/dispatch    最新 pending、3 streak FAIL
data-integrity                  [S S S S S]  PR/schedule    OK
deploy                          [skip F]     workflow_run   gate OK (skip 正常)
dispatch-webhooks-cron          [S]          schedule       OK
distribution-manifest-check     [F F F F F]  push/PR        12-streak FAIL (¥3/req drift)
e2e                             [S S S S S]  PR/schedule    OK
egov-pubcomment-daily           [F]          schedule       FAIL (db missing)
eval                            [S S S S S]  PR/schedule    OK
fingerprint-sot-guard           [F F F F]    PR/dispatch    11-streak FAIL (fastapi)
lane-enforcer                   [S S F F F]  push/PR        recent recovery
narrative-sla-breach-hourly     [F]          schedule       15-streak FAIL (TG token)
openapi                         [S F]        push/dispatch  recent recovery
pages-deploy-main               [F F F F F]  push/dispatch  11-streak FAIL (_redirects)
pages-preview                   [- C]        push/dispatch  cancelled
pages-regenerate                [C]          schedule       cancelled (本日 manual stop)
release-readiness-ci            [S S S S S]  PR/push        OK
same-day-push-cron              [S]          schedule       OK
stripe-backfill-30min           [queued]     schedule       in flight
stripe-version-check-weekly     [S]          schedule       OK
test                            [- - - - -]  push/PR        pending (CI 走行中)
adoption-program-join-weekly    success      schedule       OK
alias-expansion-weekly          failure      schedule       FAIL (date refspec bug)
amendment-alert-cron            success      schedule       OK
amendment-alert-fanout-cron     success      schedule       OK
analytics-cron                  success      schedule       OK
billing-health-cron             success      schedule       OK
brand-signals-weekly            NEVER_RAN    schedule       (週次未到来)
competitive-watch               success      schedule       OK
eligibility-history-daily       success      schedule       OK
evolution-dashboard-weekly      NEVER_RAN    schedule       (週次未到来)
facts_registry_drift_v3         success      dispatch       OK
fence_count_drift_v3            success      dispatch       OK
geo_eval                        NEVER_RAN    schedule       (週次未到来)
health-drill-monthly            failure      schedule       FAIL (flyctl auth)
idempotency-sweep-hourly        success      schedule       OK
incremental-law-bulk-saturation success      schedule       OK
incremental-law-en-translation  success      schedule       OK
incremental-law-load            success      schedule       OK
index-now-cron                  success      schedule       OK
industry-journal-mention-monthly NEVER_RAN   schedule       (月次未到来)
ingest-daily                    success      schedule       OK
ingest-monthly                  failure      schedule       FAIL 2026-05-01 (flyctl)
ingest-offline-inbox-hourly     success      schedule       OK
ingest-weekly                   failure      schedule       FAIL (scripts module)
kokkai-shingikai-weekly         failure      schedule       FAIL (autonomath.db)
kpi-digest-cron                 success      schedule       OK
loadtest                        NEVER_RAN    dispatch only  OK
mcp_drift_v3                    success      dispatch       OK
meta-analysis-daily             success      schedule       OK
morning-briefing-cron           success      schedule       OK
municipality-subsidy-weekly     failure      schedule       FAIL (jpintel.db)
narrative-audit-monthly         NEVER_RAN    schedule       (月次未到来)
news-pipeline-cron              success      schedule       OK
nightly-backup                  success      schedule       OK
nta-bulk-monthly                failure      schedule       FAIL 2026-05-01 (flyctl)
nta-corpus-incremental-cron     success      schedule       OK
og-images                       NEVER_RAN    schedule       (週次未到来)
openapi_drift_v3                success      dispatch       OK
organic-outreach-monthly        NEVER_RAN    schedule       (月次未到来)
populate-calendar-monthly       NEVER_RAN    schedule       (月次未到来)
post-award-monitor-cron         success      schedule       OK
practitioner-eval-publish       failure      schedule       FAIL (JPCITE_API_KEY)
precompute-actionable-daily     success      schedule       OK
precompute-data-quality-daily   cancelled    schedule       (本日 manual stop)
precompute-recommended-monthly  NEVER_RAN    schedule       (月次未到来)
precompute-refresh-cron         cancelled    schedule       (本日 manual stop)
production-gate-dashboard-daily failure      schedule       FAIL (CLOUDFLARE token)
publish_text_guard              failure      dispatch       FAIL
quarterly-reports-cron          NEVER_RAN    schedule       (四半期未到来)
rebrand-notify-once             NEVER_RAN    dispatch only  OK
refresh-amendment-diff-history  success      schedule       OK
refresh-sources-daily           failure      schedule       FAIL (--enrich drift)
refresh-sources-weekly          failure      schedule       FAIL (--enrich drift)
refresh-sources                 success      schedule       OK (multi-cron canonical)
release                         (なし)       push           対象 path 変更待ち
restore-drill-monthly           (なし)       schedule       (月次未到来)
saved-searches-cron             (なし)       schedule       OK
sbom-publish-monthly            (なし)       schedule       (月次未到来)
sdk-publish-agents              (なし)       push           NPM_TOKEN 必要
sdk-publish                     失敗 2026-04-30 push        FAIL (NPM_TOKEN)
sdk-republish                   (なし)       dispatch       OK
self-improve-loop-h-daily       (なし)       schedule       OK
self-improve-weekly             (なし)       schedule       OK
sitemap_freshness_v3            (なし)       dispatch       OK
status_update                   (なし)       schedule       (5min cron 要 verify)
sunset-alerts-cron              success      schedule       OK
sync-workflow-targets-monthly   (なし)       schedule       (月次未到来)
tls-check                       success      schedule       OK
trial-expire-cron               success      schedule       OK
trust-center-publish            (なし)       schedule       (週次未到来)
weekly-backup-autonomath        (なし)       schedule       (週次未到来)
weekly-digest                   (なし)       schedule       (週次未到来)
CodeQL                          success      push/schedule  OK
Dependabot Updates              success      dynamic        OK
```

凡例: `S=success, F=failure, C=cancelled, skip=skipped, -=pending`

---

## END
