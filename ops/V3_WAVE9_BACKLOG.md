# Wave 9 Backlog — 本番 launch 後 漸次品質債務

> 2026-05-11 作成 / Wave 1-8 完了 + 本番 deploy (commit 6bf378ab) 後の最小 blocker 7 本。
> 全項目 Claude AUTO で実装可、USER 操作は `ops/USER_RUNBOOK_v4_launch.md` に分離。
>
> memory: 「完了条件は最低 blocker に絞れ」「優先順位質問禁止」「スケジュール/工数禁止」「AI が全部やる」「Solo zero-touch」「Organic only」「LLM API import 禁止」

---

## 採用 blocker 一覧 (7 本)

| ID | Priority | Title | Touch files | Done criteria 概要 |
|---|---|---|---|---|
| W9-01 | P0 | OAuth + Stripe UI 完成 — dashboard 払出経路 close-loop | site/dashboard.html, src/jpintel_mcp/api/me/, billing.py, auth_github.py | login_request/verify 200 + portal mint button 動作 + Playwright e2e green |
| W9-02 | P0 | CF Pages wrangler 残 87% upload 戦略 — pages-deploy-main.yml 1-pass | .github/workflows/pages-deploy-main.yml, site/_redirects | GHA run < 30min, 12 URL parity 200 |
| W9-03 | P0 | post-launch SDK republish (Option B) | sdk/python/pyproject.toml, sdk/typescript/package.json, .github/workflows/sdk-republish.yml (新規) | PyPI/npm homepage = jpcite.com |
| W9-04 | P1 | 91 pre-existing test fail の 3 カテゴリ別 root-cause fix | tests/conftest.py, tests/test_wave24_*.py, tests/test_rest_search_*.py, api/programs.py | pytest -q fail 0 |
| W9-05 | P1 | 21 ruff noqa file-level → line-level refactor | scripts/ × 12, src/jpintel_mcp/api/ × 5, tests/ × 4 | grep "^# ruff: noqa" → 0、ruff rc=0 |
| W9-06 | P2 | GEO bench 5 surface 本実装 (stub→real) | tools/offline/geo_bench_runner.py (新規), tests/geo/bench_harness.py, geo_eval.yml | 500 verify 走、W4 平均 ≥ 1.2 |
| W9-07 | P2 | status_probe.py 残 stub component 実装 | scripts/ops/status_probe.py, monitoring/sla.yml (新規) | components[].note=stub 0 件 |

---

## W9-01 [P0] OAuth + Stripe UI 完成

**Why**: 5/7 SOT の最後の残課題。`api/me/login_verify.py` が JWT 24h を発行するが `site/dashboard.html` 側に GitHub/Google OAuth ボタン + Stripe Customer Portal mint button が未配線。LIVE checkout → 課金開始は走るが、新規 user が「契約後に key + 利用量を見る」UI loop が閉じない。

**How**: `auth_github.py` (393 行、impl 済) と `me/login_request|verify.py` を `dashboard.html` の login section に wire-up。`/v1/billing/portal` を mint button から呼んで Stripe-hosted portal にリダイレクト。Magic-link + GitHub の 2 path、共通 `Bearer` storage は localStorage `jpcite_session`。

**Touch files**:
- `site/dashboard.html` (1820 行、`/v1/me/*` 既存 13 ヒット)
- `src/jpintel_mcp/api/auth_github.py` (393 行)
- `src/jpintel_mcp/api/me/{login_request,login_verify}.py` (191 行 total)
- `src/jpintel_mcp/api/billing.py` (`POST /v1/billing/portal` 既存)
- `site/en/dashboard.html` (i18n mirror)

**Done criteria**:
- `curl -X POST https://api.jpcite.com/v1/me/login_request -d '{"email":"info@bookyou.net"}'` → `{"ok":true}` + Postmark 配信
- `curl -H "Cookie: jpcite_session=$JWT" https://api.jpcite.com/v1/billing/portal` → `{"portal_url":"https://billing.stripe.com/..."}`
- Playwright walk `tests/e2e/test_dashboard_auth.py`: OAuth ボタン click → callback → key + portal link 表示

---

## W9-02 [P0] CF Pages wrangler 残 87% upload 戦略

**Why**: 4th retry 1734/13010 (13%) で停滞。`.github/workflows/pages-deploy-main.yml` (188 行) が GHA Linux runner + `cloudflare/pages-action@v1.5.0` 経路に作られているが、operator workflow と並走している。残 87% (≈11,276 file) を GHA 経路 1 回で完走させる必要。

**How**:
1. `pages-deploy-main.yml` の rsync filter を `--exclude='_archive/'` `--exclude='generated/dev_*'` 追加で artifact を < 25MB に絞る
2. `workflow_dispatch` で empty-commit を `[skip wrangler-local]` tag 付きで主導、operator macOS 経路を一時 OFF
3. post-deploy smoke 4 JSON を 12 URL に拡張 (artifact / playground / dashboard / status 4 page を追加)

**Touch files**:
- `.github/workflows/pages-deploy-main.yml` (188 行、rsync 既存)
- `tools/offline/_inbox/HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md` (operator path 停止メモ追記)
- `site/_redirects` (CF chunk 境界に合わせて静的 redirect 整理)

**Done criteria**:
- `gh workflow run pages-deploy-main.yml` → run 完走 (< 30min timeout)、`Publish to Cloudflare Pages` step success
- `curl -fsSL https://jpcite.com/dashboard.html` + 11 他 URL すべて 200
- `wrangler pages deployment list --project-name autonomath | head -3` で最新 deploy id が GHA 由来

---

## W9-03 [P0] post-launch SDK republish (Option B)

**Why**: `sdk/python/pyproject.toml` + `sdk/typescript/package.json` は jpcite metadata 反映済だが、PyPI `autonomath` / npm `@autonomath/sdk` の registry page は AutonoMath brand のまま。agent 経由の SDK 発見が autonomath.ai 旧ドメインに誘導される。

**How**: GitHub Actions `sdk-republish.yml` を作成 — `workflow_dispatch` で:
1. `cd sdk/python && python -m build && twine upload dist/* --skip-existing`
2. `cd sdk/typescript && npm publish --access public`

secret = `PYPI_TOKEN`, `NPM_TOKEN`。Option B per `docs/_internal/sdk_republish_after_rename.md` (version 据置 → 拒否なら patch bump)。

**Touch files**:
- 新規 `.github/workflows/sdk-republish.yml` (~60 行)
- `sdk/python/pyproject.toml` (version 0.1.0 → 0.1.1 fallback)
- `sdk/typescript/package.json` (version 0.3.2 → 0.3.3 fallback)
- `docs/_internal/sdk_republish_after_rename.md` (実行ログ追記)

**Done criteria**:
- `curl -s https://pypi.org/pypi/autonomath/json | jq '.info.home_page'` → `"https://jpcite.com"`
- `npm view @autonomath/sdk homepage` → `https://jpcite.com`
- GHA `sdk-republish` workflow status = success

---

## W9-04 [P1] 91 pre-existing test fail の 3 カテゴリ別 root-cause fix

**Why**: Tasks #18-22 で個別 5 件 fix 済だが、CI baseline log 上 91 fail が main にも同じ pattern で残る。`data drift` / `lang propagate` / `tool stub` の 3 カテゴリ。漸次扱いだが root-cause を 3 fix 入れないと再生する。

**How**:
- (a) `data_drift`: `tests/test_wave24_*.py` 系で `freeze_time` + golden snapshot fixture 化
- (b) `lang_propagate`: `tests/test_rest_search_tax_incentives.py` の `Accept-Language` → tool kwargs `lang=` 引渡しを `api/programs.py` で完備
- (c) `tool_stub`: `tests/conftest.py` に `_real_tool_marker` fixture を入れて stub 検出時 xfail

**Touch files**:
- `tests/conftest.py` (新 fixture)
- `tests/test_wave24_endpoints_kwargs_filter.py`
- `tests/test_rest_search_tax_incentives.py`
- `tests/test_mcp_tools.py`
- `src/jpintel_mcp/api/programs.py` (lang propagate fix)

**Done criteria**:
- `.venv/bin/pytest -q 2>&1 | tail -1` → `passed` のみ、fail 0
- `git diff main -- tests/ | grep -c "^+def test_"` ≥ 3 (新 regression test)
- CI `pytest` job green on PR

---

## W9-05 [P1] 21 ruff noqa file-level → line-level refactor

**Why**: 21 file が `# ruff: noqa: N803,N806,SIM115,SIM117,BLE001,E501,F401,F841,PTH123,S301,S314,S603,UP017` で 13 ルール一括 suppress。新規バグ (S314 = XML parse / S301 = pickle / BLE001 = bare except) が紛れても検出されない。

参照: `docs/audit/ruff_noqa_cleanup_plan_2026_05_11.md` (実発火 3 種のみ、残 10 はコピペ)

**How**:
1. 21 file を file-level → line-level `# noqa: <rule>` に展開
2. `scripts/ops/refactor_noqa.py` で各 violation 行に必要最小 rule 名のみ残す
3. 残った真の違反は code 修正 (BLE001 → `except SpecificError`、S314 → `defusedxml`)

**Touch files** (17 file):
- `scripts/{check_fence_count,check_publish_text,inject_a11y_baseline,inject_jsonld,check_openapi_drift,scan_publish_surface,validate_jsonld,generate_og_images,check_sitemap_freshness,generate_favicon,check_mcp_drift}.py`
- `scripts/ops/status_probe.py`
- `src/jpintel_mcp/api/{billing_webhook_idempotency,playground_stream,me/__init__,me/login_request,me/login_verify}.py`
- `tests/test_{me_auth,playground_stream,stripe_webhook_idempotency,a11y_baseline}.py`

**Done criteria**:
- `grep -rln "^# ruff: noqa" scripts/ src/ tests/ | wc -l` → `0`
- `uv run ruff check scripts/ src/ tests/` rc=0
- `git diff main --stat` で 17 file 全件 touch
- residual line-noqa ≤ 6

---

## W9-06 [P2] GEO bench 5 surface 本実装

**Why**: `tests/geo/bench_harness.py` 38 行は 100% stub。`STUB - Wave 6 で 5 surface 接続実装` placeholder のまま `.github/workflows/geo_eval.yml` weekly cron が走り、`score: 0` の noise を `reports/geo_bench_*.jsonl` に書き続ける。G18 acceptance gate "W4 平均 ≥ 1.2" が永久に未達。

**How**: 5 surface = `claude_desktop` / `chatgpt_gpts` / `codex_cli` / `cursor_mcp` / `agents_md` の各 entry point に対して MCP client 接続を harness 内に実装。

**重要制約**: LLM API 呼出は `tools/offline/` 内に隔離 (CI guard `tests/test_no_llm_in_production.py` 違反回避)。本番 API は呼ばない。100 問 × 5 surface = 500 verify。

参照: `scripts/ops/geo_weekly_bench_v3.py` (CSV import 方式、既に Wave 8 で作成済) と併存。

**Touch files**:
- `tools/offline/geo_bench_runner.py` (新規、~200 LOC、LLM 呼出 host)
- `tests/geo/bench_harness.py` (38 → ~120 行 stub 撤去 + surface dispatch)
- `data/geo_questions.json` (100 問 OK)
- `.github/workflows/geo_eval.yml` (env `ANTHROPIC_API_KEY` 追加、operator secret 化)

**Done criteria**:
- `python tools/offline/geo_bench_runner.py --surface claude_desktop --questions data/geo_questions.json` → `reports/geo_bench_*.jsonl` に non-zero score 行
- 5 surface × 100 = 500 行、`jq '.score' reports/geo_bench_*.jsonl | sort | uniq -c` で 0-4 分布が複数 bucket
- W1 平均 score ≥ 0.5 (baseline 確立)、W4 ≥ 1.2 (G18 gate)

---

## W9-07 [P2] status_probe.py 残 stub component 実装

**Why**: `scripts/ops/status_probe.py` (Wave 8 で 5 endpoint 実 fetch 化済) はあるが、深い business logic probe (Stripe events.list / 4 dataset MAX age / magic-link verify 完了率) は未実装。`status.jpcite.com` 60s cron が「全 operational」を返し続ける。

**How**:
1. `probe_billing`: Stripe `events.list({type:"invoice.payment_failed", created:{gte:now-86400}})` で 5xx rate 計算
2. `probe_data_freshness`: 4 dataset (`programs.updated_at`, `am_amendment_diff.captured_at`, `invoice_registrants.fetched_at`, `case_studies.updated_at`) の MAX age を SLA (24h/7d/30d/30d) と比較
3. `probe_dashboard`: magic-link `/v1/me/login_request` POST + 5min 内 verify 完了率 → 直近 24h で <50% → degraded

**Touch files**:
- `scripts/ops/status_probe.py` (236 行 → ~330 行、real probe 拡張)
- `site/status/status.json` (output 整合、schema_version 1.0 → 1.1)
- `.github/workflows/status-cron.yml` (60s cron 整合確認)
- 新規 `monitoring/sla.yml` (4 dataset SLA 定義)

**Done criteria**:
- `STRIPE_SECRET_KEY=$LIVE python scripts/ops/status_probe.py` → `components[].status` で `note: "stub..."` が 0 件
- `curl -s https://jpcite.com/status/status.json | jq '.components | length'` → `5`
- 意図的に DB age を 31d に書き換えて `data-freshness` が `degraded` になる

---

## 落とした候補 (3 つ、理由)

- **UI 実装 G13-G16** (artifact viewer + playground 3step + dashboard 9widget + status page): Wave 5 §E 既掲載、重複回避。W9-01 で dashboard 経路のみ subset として吸収。
- **業界紙 8 article publish 後 measure harness**: publish 自体が USER 操作 (Zenn / note アカウント手動 post)。AUTO 不可 — `USER_RUNBOOK_v4_launch.md` Phase 4 に分離継続。
- **recipes 30 本 deep 化** (Wave 5 §G): blocker でなく漸次品質、本番 launch 後 user 流入が無いと deep 化方向性が固まらない。Wave 10 で revisit。

---

## ロードマップ

W9-01 → W9-02 → W9-03 (P0 3 本、launch 後 close-loop) → W9-04 / W9-05 (P1 2 本、CI baseline 健全化) → W9-06 / W9-07 (P2 2 本、観測 loop)。全項目 Claude AUTO で並列実装可。
