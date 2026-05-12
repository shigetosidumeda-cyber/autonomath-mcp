# Wave 49 tick#3 — calculator LIVE 404 解消 PR (STATE)

`SCOPE`: 前 tick#11 finding `https://jpcite.com/tools/cost_saving_calculator.html = 404` の root cause
解消。PR #183 (Wave 48 tick#1) で repo root `tools/` + `docs/canonical/` に landing したが、
`pages-deploy-main.yml` rsync が `site/` のみを `dist/site/` に mirror するため CF Pages に
配信されず。

`memory`:
- `feedback_dual_cli_lane_atomic` — `/tmp/jpcite-w49-calc-live.lane` + worktree 排他
- `feedback_destruction_free_organization` — 元 `tools/` + `docs/canonical/` 削除/move 禁止、
  hard copy + workflow extend のみ
- `feedback_cost_saving_v2_quantified` — calculator + canonical examples が LIVE で
  再現可能であることが Wave 49 の cost-saving v2 の前提

---

## A. 着地済 (前 tick#11 で main HEAD=2c3be863b verify 済)

- `tools/cost_saving_calculator.html` (234 LOC) — PR #183 で main 着地
- `docs/canonical/cost_saving_examples.md` (272 LOC) — PR #183 で main 着地

## B. 本 PR 変更

### B-1. site/tools/ 配下 hard copy (destruction-free)
- `site/tools/cost_saving_calculator.html` ← `tools/cost_saving_calculator.html` (10,899 byte)
- `site/tools/cost_saving_examples.md` ← `docs/canonical/cost_saving_examples.md` (16,347 byte)

元 file は **触らない** (rm/mv なし、`cp` のみ)。`site/docs/` は MkDocs 出力で gitignored
なため `.md` も同一 `site/tools/` 配下に置く。

### B-2. workflow rsync filter 拡張 (.md 局所開放)
`.github/workflows/pages-deploy-main.yml` + `.github/workflows/pages-preview.yml` の rsync block に:

```diff
   rsync -a --delete \
     --exclude '_templates/' \
     --exclude '*.src.js' \
     --exclude '*.src.css' \
     --exclude '*.map' \
     --include 'press/*.md' \
     --include 'security/policy.md' \
+    --include 'tools/' \
+    --include 'tools/*.md' \
     --exclude '*.md' \
     site/ dist/site/
```

`*.html` は元から exclude されていないので追加不要。`tools/*.md` だけ
default `*.md` exclude を上書き。include が exclude より先に出現する rsync
first-match-wins 順序を守る (新規 test `test_rsync_include_ordered_before_md_exclude` で gate)。

### B-3. test (LOC ~165)
`tests/test_calculator_live_404_fix.py` — 10 軸:

| # | test | 目的 |
|---|------|------|
| A1 | `test_site_calculator_html_exists` | site/tools/ HTML 存在 |
| A2 | `test_site_calculator_html_valid` | doctype + closing tag |
| A3 | `test_site_calculator_is_hard_copy_not_empty` | サイズ一致 (元 == site/) |
| B1 | `test_site_examples_md_exists` | site/tools/ .md 存在 |
| B2 | `test_site_examples_md_valid` | H1 + use-case anchor |
| B3 | `test_site_examples_md_is_hard_copy_not_empty` | サイズ一致 |
| C1 | `test_pages_deploy_main_rsync_includes_canonical_md` | deploy.yml rule 存在 |
| C2 | `test_pages_preview_rsync_includes_canonical_md` | preview.yml rule 存在 (parity) |
| C3 | `test_rsync_include_ordered_before_md_exclude` | include が exclude より前 |
| D1 | `test_original_tools_and_docs_canonical_untouched` | 元 file 削除されていない |

全 10 件 PASS 確認 (`.venv/bin/python` 3.13.12, pytest 9.0.3, 0.92s)。

### B-4. rsync simulate 検証 (local)
`/tmp/_rsync_test/` に上記 filter で `site/` を mirror → `tools/cost_saving_calculator.html`
+ `tools/cost_saving_examples.md` 双方が landing 確認済。

---

## C. 期待 LIVE URL (PR merge + pages-deploy-main 完走後)

| URL | 配信元 |
|------|--------|
| https://jpcite.com/tools/cost_saving_calculator.html | `site/tools/` (.html, デフォ include) |
| https://jpcite.com/tools/cost_saving_examples.md | `site/tools/` (.md, 新 include rule) |
| (既存) https://jpcite.com/docs/canonical/cost_saving_examples/ | MkDocs build (`mkdocs build` で生成) |

---

## D. 禁止事項チェック

- [x] 元 `tools/cost_saving_calculator.html` 削除しない (hard copy のみ)
- [x] 元 `docs/canonical/cost_saving_examples.md` 削除しない
- [x] `rm` / `mv` 使用なし (`cp` のみ)
- [x] 旧 brand (zeimu-kaikei.ai / AutonoMath / 税務会計AI) 言及なし
- [x] LLM API import なし (test 内も pytest + pathlib のみ)
- [x] tier 階層 / SaaS UI 提案なし
- [x] 工数・スケジュール・優先順位質問なし

---

## E. PR open + status

| key | value |
|-----|-------|
| branch | `feat/jpcite_2026_05_12_wave49_calc_live_404_fix` |
| base | `main` (fe47fdd49) |
| 変更 file | 5 (site/tools/.html + site/tools/.md + 2 workflows + 1 test) |
| PR# | **#192** (https://github.com/shigetosidumeda-cyber/autonomath-mcp/pull/192) |
| 期待 LIVE | https://jpcite.com/tools/cost_saving_calculator.html |
| 期待 LIVE | https://jpcite.com/tools/cost_saving_examples.md |
| 配信方式 | (1) site/tools/ hard copy + (2) rsync filter `--include 'tools/*.md'` 拡張 |

---

## F. 次 tick 候補
- LIVE 200 verify (CF Pages propagation 60s+ 後)
- `_redirects` に `/tools/calc → /tools/cost_saving_calculator.html` 短縮 alias
- llms.txt + sitemap に `/tools/cost_saving_calculator.html` 登録 (citation surface)
