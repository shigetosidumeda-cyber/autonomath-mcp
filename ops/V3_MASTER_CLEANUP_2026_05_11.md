# v3 Master Cleanup Plan — 2026-05-11

> jpcite repo「無駄にしていること + 弱い部分」を全て解決する整理整頠 master plan。
> 10 並列 audit agent (orphan / legacy codename / TODO stub / PR/branch / workflow/cron / DB table / site orphan / dependency / test coverage / master plan) の結果を統合。
> Bookyou株式会社 T8010001213708 / info@bookyou.net / solo + zero-touch + 100% organic.
>
> **重要原則 (memory enforce)**: 序列禁止 / 「やる・やらない」二択 / 営業/CS/法務チーム言及なし / 広告言及なし / 旧 brand (jpintel) user-facing 露出禁止 / 破壊なき整理整頠 (rm/mv なし、banner + `_archive/` index marker のみ)。

---

## Audit 入力 (10 agent の出力 file path)

- `docs/audit/orphan_artifacts_2026_05_11.md` — orphan 48 件 (scripts 21+27 / docs/_internal 16+22 / docs/public 1 / site 1 / workflows 2 / src 3)
- `docs/audit/legacy_codename_full_audit_2026_05_11.md` — Tier1 must-fix ~9行 / Tier2 公開 ~12行 / Tier3 keep (PR #25 後ほぼ clean)
- `docs/audit/todo_stub_audit_2026_05_11.md` — high-priority 9 hit (2× 501 endpoint / healthcare+real-estate sentinel 11 funcs / broken-tool gates 3 / operator playbook 7+)
- `docs/audit/pr_branch_git_state_2026_05_11.md` — Open PR 15 (CONFLICTING 1 / stale 11) / Local-only orphan branch 2 / dependabot stale 14
- `docs/audit/workflow_cron_state_2026_05_11.md` — 100 workflow / 連続失敗 9 / secret 不足 35 種
- `docs/audit/db_table_state_2026_05_11.md` — autonomath 505 table (51% empty) + jpintel 182 table (51% empty) / template-default majority 5 quality 問題 / FTS5 shadow 空 2 table
- `docs/audit/site_docs_orphan_2026_05_11.md` — orphan 25 / broken link **12,739** / 重複 1 / sitemap drift 120 / mkdocs phantom 19
- `docs/audit/dependency_dead_code_2026_05_11.md` — 未使用 dep 2 / 古い dep 5 / dead code 真 10+候補5 / 重複 envelope 5 / 循環 import 0 真
- `docs/audit/test_coverage_pre_existing_fail_2026_05_11.md` — 91 fail 内訳 (data drift 38 / lang propagate 6 / tool stub 12 / 他 35) / カバレッジ低 module top 3 (autonomath_tools/tools.py 3450 LOC・wave24×2 各 2500 LOC)
- `ops/V3_MASTER_CLEANUP_2026_05_11.md` — 本 plan (整合)

---

## Section A. やめる (deprecation = banner + `_archive/` index marker、本体 keep)

**原則**: file 本体は disk 上に保持。削除でなく `docs/_internal/_archive/_index_2026_05_11.md` に record + 該当 file 冒頭 banner。

| # | artifact | 由来 | 理由 | successor |
|---|---|---|---|---|
| A1 | `dist.bak/`, `dist.bak2/`, `dist.bak3/` | orphan | 旧 build artifact (v0.2.0/0.3.0/0.3.1) | `dist/` v0.3.4 |
| A2 | `pyproject.toml.bak` | orphan | brand rename 前 snapshot | 現行 `pyproject.toml` |
| A3 | site `analytics.src.js` | site orphan | minified `analytics.js` のみ配信 | `site/analytics.js` |
| A4 | `EXPECTED_OPENAPI_PATH_COUNT = 186` | test | live 219 と乖離 | `scripts/distribution_manifest.yml: 219` |
| A5 | 「11,547 programs / 416,375 entities / 55-59 tools / v0.2.0」 legacy 数値 string | codename | 歴史的 marker のみ、新規参照禁止 | CLAUDE.md §Overview 現行 |
| A6 | `tier-badge` / `Free tier` / `Pro plan` / `Starter plan` (UI 上) | codename + site | 完全従量 1 SKU 違反 (CLAUDE.md non-negotiable) | 完全従量 ¥3/req + 匿名 3 req/day |
| A7 | aggregator domain (`noukaweb` / `hojyokin-portal` / `biz.stayway`) source_url | db | 詐欺 risk (CLAUDE.md banned) | 一次 govt source 置換 |
| A8 | broken-tool 3 MCP (`query_at_snapshot` / `intent_of` / `reason_answer`) | db + test | 2026-04-29 smoke 100% broken、gate OFF | fix 完了まで gate 維持 |
| A9 | `release_command = "python scripts/migrate.py"` (fly.toml comment) | workflow | autonomath.db 破壊 risk | `entrypoint.sh §4` self-heal |
| A10 | `--depot=false` flag dead 分岐 | workflow + dep | flyctl 上流削除済 silent no-op | `--remote-only --strategy rolling` |
| A11 | USER-WEB-24 (Anthropic/Cursor/Cline 直接 submission) task | orphan + codename | 100% organic + cold outreach 禁止 | awesome-mcp + MCP registry 経由 |
| A12 | TODO/stub だけで caller 0 関数群 | stub | 死 code、import 不到達 | banner + `_archive/` record |
| A13 | open PR #1-#14 dependabot 6 ヶ月超 stale | pr/branch | rebase 不可、conflict 蓄積 | close (recreate のみ) |
| A14 | `safeskill-scan` branch (PR #14、badge 50/100) | pr/branch + codename | 旧 brand 露出含む可能性 | close 推奨 |
| A15 | `data/jpintel.db.bak-*` slip 候補 | db | `.gitignore` 適用前 slip | `.gitignore` lock |
| A16 | `cutlet` / `mojimoji` import (残存ある場合) | dep | macOS Rosetta コンパイル失敗 | `pykakasi` |
| A17 | LLM API import (`anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk`) が `src/` / `scripts/cron/` / `tests/` に紛れた行 | dep + test | `tests/test_no_llm_in_production.py` 違反 | `tools/offline/` 移送 |
| A18 | `consent_collection={"terms_of_service": "required"}` Stripe 旧 path | stub + dep | live mode 500 (CLAUDE.md gotcha) | `custom_text.submit.message` |
| A19 | CORS allowlist で `jpcite.com` apex+www 抜けの legacy 設定 | workflow + codename | 2026-04-29 walk で 403 再発 | `JPINTEL_CORS_ORIGINS` apex+www+api |
| A20 | `incremental-law-bulk-saturation-cron.yml` + `incremental-law-en-translation-cron.yml` | orphan + workflow | `incremental-law-load.yml` で superseded | unified workflow |

**やめる件数: 20 件** (全 banner + index、disk 削除 0)

---

## Section B. 残す + 改善する (active + 弱点修正)

| # | artifact | 改善方針 | 関連 file |
|---|---|---|---|
| B1 | `data/facts_registry.json` `guards.banned_terms` | context-aware regex、 63,153 → ≤50 違反 | facts_registry.json / check_publish_text.py |
| B2 | `.github/workflows/test.yml` + `release.yml` PYTEST_TARGETS/RUFF_TARGETS | 36 test + 9 ruff sync | sync_workflow_targets.py |
| B3 | `codeql.yml` + `pr-diff-range.yml` | `restrictAlertsTo(undefined,...)` 解消 (config-file 経由) | codeql-config.yml |
| B4 | 7 新 workflow (publish_text_guard 他) | B1 完了後 `on: pull_request` + `continue-on-error: false` で PR gate | `*_v3.yml` 6 個 |
| B5 | migration 196-204 (entity_id_bridge + 8 join table) | 9 DDL idempotent + `-- target_db: autonomath` + rollback companion | scripts/migrations/196-204 |
| B6 | `test_distribution_manifest.py` 定数 | 186 → 219 (canonical SOT) | distribution_manifest.yml |
| B7 | MCP runtime cohort 146 vs manifest 139 | 次の意図的 manifest bump で 139→146 同時 | pyproject/server/dxt/smithery/mcp-server.json |
| B8 | `site/playground.html` (2,650 行) | flow=evidence3 3 step + SSE stream + agent UA 切替 | playground.html |
| B9 | `site/dashboard.html` + `functions/dashboard.ts` | magic-link + Stripe portal mint + 9 widget | dashboard.html + auth_github.py + me/* |
| B10 | recipes 30 本 | 各 1,500-3,000 字 deep 化 + snippet 動作確認 + cross-link | docs/cookbook/*.md |
| B11 | GEO 100 問 bench harness | 5 surface × 100 問 = 500 verify、 W4 平均 ≥1.2 で acceptance | geo_questions.json + bench_harness.py |
| B12 | acceptance 50 item 自動実行 | 10 category 並列 → status_acceptance.json → 50/50 で v1.0-GA tag | acceptance_check.yml |
| B13 | 17 ruff `noqa` justification | `# noqa: <code> — <reason>` 形式、不要分は素直に fix | self_improve/ + mcp/server.py + autonomath_tools |
| B14 | `am_amount_condition` template-default majority | 外部 aggregate 露出停止、ETL 修復で promote | repromote_amount_conditions.py |
| B15 | `am_amendment_snapshot` 14,596 内 144 dated のみ | time-series 用 / 残り「captured but not yet diff'd」分離 | am_amendment_snapshot / am_amendment_diff |
| B16 | `am_source.last_verified` 94/95,000 (0.1%) | 残 94,906 fill via precompute_refresh.py | am_source |
| B17 | `am_entity_facts.source_id` 81,787/80,000 (target met) | 残 NULL を am_entity_source rollup forward-only | am_entity_facts |
| B18 | `programs` prefecture 6,011 / municipality 11,350 欠損 | 地域 enricher で fill | programs / am_region |
| B19 | open PR #1-#13 dependabot 13 本 | grouping rebase + green 順次 merge | dependabot.yml |
| B20 | open PR #23 (redteam_hotfix) | conflict 解消 → green → user 承認 merge or cherry-pick close | feat/jpcite_2026_05_11_redteam_hotfix |
| B21 | open PR #14 (SafeSkill 50/100) | 旧 brand 確認後 close or 再 scan | safeskill-scan.yml |
| B22 | CF Pages `autonomath-mcp` project | install path 200 化緑 → mkdocs strict clean → site lock | CF Pages + mkdocs.yml |
| B23 | SEO page 9,964 件 chunk push | 200 page/commit chunk、 CF queue 飽和回避 | site/cases / laws / enforcement |
| B24 | `entrypoint.sh §4` autonomath migration self-heal | 196-204 着地後 boot log `applied=N skipped=M` 確認 | entrypoint.sh |
| B25 | `JPINTEL_CORS_ORIGINS` Fly secret | jpcite apex+www+api 列挙確認 (USER-CLI-4) | fly.toml secret |
| B26 | `mkdocs.yml` `exclude_docs` (commit 9e93ceef 着地済) | strict mode warning fix を再 verify | mkdocs.yml |
| B27 | hydrate step 25→60min timeout (commit b12f133d 着地済) | 60min で再発したら 90min か sftp 並列分割 | deploy.yml |
| B28 | DEEP-22..65 retroactive 整合 (W23 で 0 inconsistency) | 新 DEEP 追加時 lookback diff を acceptance_check.yml に組込 | tests/test_acceptance_*.py |
| B29 | `site/status/*` 5 component | status_probe.py 実装 (stub のみ) → 60s update cron + badge | scripts/ops/status_probe.py |
| B30 | `site/artifact.html` + `functions/artifacts/[pack_id].ts` (G13) | CF Pages Function SSR 7 section | artifact.html + functions/ |
| B31 | OAuth UI 配線 (GitHub + Google) | API callback 既存、UI button + redirect 配線 | api/oauth_*.py / site/login.html |

**残す + 改善する件数: 31 件**

---

## Section C. 新規追加する

| # | 新規 | 目的 | path |
|---|---|---|---|
| C1 | `scripts/ops/status_probe.py` 本実装 | status.jpcite.com 5 component 60s probe | scripts/ops/status_probe.py |
| C2 | GEO bench 5 surface × 100 問 = 500 verify 本実装 | LLM 引用 evaluator weekly bench | tests/geo/bench_harness.py + geo_bench_w{N}.csv |
| C3 | OAuth UI 配線 (GitHub + Google) | dashboard.html 入口 magic-link 以外 | site/login.html button + redirect |
| C4 | `docs/_internal/_archive/_index_2026_05_11.md` | Section A 全 20 件 deprecation record (banner 文言 + successor path) | _archive/_index_2026_05_11.md |
| C5 | `acceptance_check.yml` + `scripts/acceptance/{run,aggregate}.js` | 50 item 自動実行 → v1.0-GA tag | acceptance_check.yml + scripts/acceptance/ |
| C6 | `scripts/acceptance/run.js` 10 category 並列 driver | acceptance 1 回 < 5min | acceptance/run.js |
| C7 | migration 196-204 (B5 と pair) | entity_id_bridge + 8 join table DDL | scripts/migrations/196-204 + rollback |
| C8 | recipes 30 本 deep 化 patch | 各 1,500-3,000 字 + 実 snippet | docs/cookbook/ 30 file |
| C9 | USER 24 task 実行支援 script | dry-run prepare (gh repo rename / PyPI version / Stripe JSON / Smithery PR) | scripts/ops/user_runbook_prepare.py |
| C10 | `data/sample_saved_searches.json` (9 × weekly、cohort #5) | run_saved_searches.py cron seed | sample_saved_searches.json |
| C11 | `site/openapi.agent.gpt30.json` 最新化 | USER-WEB-23 OpenAI Custom GPT Actions Import 元 | openapi.agent.gpt30.json + export_openapi.py |
| C12 | `tests/test_no_llm_in_production.py` 強化 | LLM import / API-key env var 検出 SOT 1 本化 (A17 を SOT で防ぐ) | test_no_llm_in_production.py |
| C13 | **per-record SEO page 9,964 件 commit + chunk push** | cases 2,286 + laws 6,493 + enforcement 1,185 を 200 page/commit で 50 chunk | site/cases / site/laws / site/enforcement |
| C14 | **Claude routine (CronCreate) SEO/GEO 強化 daily loop** | 毎日 1 回「調査 → 計画 → 実行 → 本番 deploy」自動実行 | CronCreate (session 内 7 日 auto-expire) |

**新規追加件数: 14 件**

---

## Section D. 整理整頠 sequence (並列 vs 順次)

### D-1. 並列 (file 競合なし)
- 並列群 α: A1-A20 banner 挿入 (20 file × 1 行 + _archive index ~200 行)
- 並列群 β: B1-B7, B11-B13, B22, B25-B27 (workflow / registry / manifest)
- 並列群 γ: B14-B18 (DB & migration)
- 並列群 δ: B8-B10, B23, B29-B31 (site UI)
- 並列群 ε: C1, C3, C8, C10-C14 (新規)
- 並列群 ζ: B19-B21, A13-A14 (open PR 整理)

→ **6 group / 推定 41 item 並列**

### D-2. 順次 (前段 depend)
- B1 (banned_terms regex) → B4 (publish_text_guard PR gate)
- B7 (manifest bump) → A4 / A6 (test 定数 lock)
- B5 / C7 (migration 196-204) → B24 (boot log 検証)
- B11 / C2 (GEO bench) → B12 / C5 (acceptance gate)
- C4 (_archive index) → Section A banner 挿入
- B22 (CF Pages 200) → B23 / C13 (SEO 9,964 push)
- B20 (#23 close) → B19 (dependabot rebase)
- A17 (LLM import 移送) → C12 (guard 強化)

→ **8 dependency chain**

---

## Section E. ループ脱出 path

| item | description |
|---|---|
| E1. CF Pages 復旧 | bg `bydvcy2sj` で 6/9 path 200 化、残 3 path (/connect/* + /openapi.agent.gpt30.json) は別調査 |
| E2. SEO page 9,964 件 chunk push | 200 page/commit chunk、CF queue 飽和回避 |
| E3. PR #23 close (機能 cherry-pick 済) | superseded by PR #25 |
| E4. 17 ruff noqa cleanup | 各 noqa に justification + 不要分 fix |
| E5. Wave 9 backlog 7 item → 本 plan の B/C で吸収済 | V3_WAVE9_BACKLOG.md |
| E6. USER_RUNBOOK 24 task Claude prepare 化 | C9 で dry-run script 提供 |
| E7. acceptance 50/50 → `v1.0-GA` tag 自動 trigger | B12 / C5 / C6 着地 → acceptance_check.yml 50/50 → release create |
| E8. Claude routine 化 (CronCreate) | C14 で SEO/GEO 強化 daily loop 自動化 |

---

## Section F. 集計

- やめる: 20 件
- 残す + 改善する: 31 件
- 新規追加: 14 件
- 並列実行可能: 6 group / 推定 41 item
- 順次必要: 8 dependency chain
- ループ脱出 path: 8 item

**総 item 数: 73** (20 + 31 + 14 + 8 = 73)

---

## Section G. SOT lock 規約

- 本 plan landing 後、`CURRENT_SOT_2026-05-06.md` に「v3 cleanup roadmap」section 1 行 reference
- 9 audit file landing 後、`<<< audit file 該当行 >>>` placeholder を実 path:line に置換
- 旧 brand (jpintel) は internal file path 限定保持。user-facing 露出新規発生 → Section A 追記
- 「Phase 1/2/3」「最初に/次に」「X 時間で完了」不出現 (memory enforce)
- 序列なし、「やる・やらない」二択、営業/CS/法務チーム なし、paid acquisition なし

---

## Critical Files

- /Users/shigetoumeda/jpcite/CLAUDE.md (SOT)
- /Users/shigetoumeda/jpcite/ops/V3_WAVE9_BACKLOG.md (7 backlog)
- /Users/shigetoumeda/jpcite/ops/USER_RUNBOOK_v4_launch.md (24 task)
- /Users/shigetoumeda/jpcite/docs/_internal/CURRENT_SOT_2026-05-06.md
- /Users/shigetoumeda/jpcite/docs/audit/*_2026_05_11.md × 10
