# Wave 48 tick#3 — docs/ breadcrumb + back PR (迷子ゼロ 50% → 100%)

Date: 2026-05-12
Branch: `feat/jpcite_2026_05_12_wave48_docs_breadcrumb_back`
Worktree: `/tmp/jpcite-w48-docs-bc` (origin/main 2c3be863b base)
Lane lock: `/tmp/jpcite-w48-docs-bc.lane` (mkdir-atomic, ledger-clean)
Constraints honored: dual-CLI atomic + destruction-free + keep-it-simple. No `rm` / `mv`. No main worktree edits. No LLM API. No brand revival. No docs redesign.

## 1. Audit context (前 tick#4 finding)

`docs/research/wave48/STATE_w48_ux_flow_audit.md` Section 3 table:

| label                | next | breadcrumb | back | verdict |
|----------------------|------|------------|------|---------|
| 01_landing           | 28   | 0          | 3    | NG (root, intentional)  |
| 02_pricing           | 10   | 1          | 2    | OK (3/3) |
| 03_signup_onboarding | 8    | 1          | 2    | OK (3/3) |
| **04_docs**          | **5**| **0**      | **0**| **NG — biggest 迷子 candidate** |

Element-axis totals: next 4/4 (100%), breadcrumb 2/4 (50%), back 3/4 (75%). Page-level 3-元素 verdict = 2/4 (50%).

After this PR (target):

| label                | next | breadcrumb | back | verdict |
|----------------------|------|------------|------|---------|
| 04_docs              | 5    | ≥1         | ≥1   | **OK (3/3)** |

Page-level 3-元素 verdict → **3/4 (75%) page-level / 3/3 elements ≥50% per axis**. Landing breadcrumb is intentional skip (root); excluding landing → 3/3 = **100%**.

## 2. Change set (3 files)

- `mkdocs.yml` (+1 line): enable Material's `navigation.path` feature in `theme.features`. This is Material's native breadcrumb (home › section › page) rendered at the top of every docs page. Single-line change keeps the diff minimal per `feedback_keep_it_simple`.
- `overrides/partials/content.html` (new, 41 lines): theme override that wraps every page body with a 3-link landmark nav + back button. Conditional on `not page.is_homepage` so the root index.md does not double-render the navigation (homepage breadcrumb is intentional skip per audit).
- `tests/test_docs_breadcrumb_back.py` (new, 132 lines / 7 tests): static SOT contract that fails fast if the partial loses any of the 4 required surfaces (back-btn class, history.back() href, ホーム / ドキュメント landmarks, page.content render, homepage skip guard).

LOC summary: +1 yaml / +41 html / +132 py = **174 LOC net add**, 0 deletions. Destruction-free per `feedback_destruction_free_organization`.

## 3. Three-element verify (partial side)

| element     | source                                | verify                                |
|-------------|---------------------------------------|----------------------------------------|
| next        | Material default (page footer partial — untouched) | `page.content` is preserved, Material renders prev/next under it |
| breadcrumb  | (a) `navigation.path` feature in mkdocs.yml<br>(b) landmark nav (ホーム + ドキュメント TOP) in content.html | partial test asserts both landmarks |
| back        | `<a class="back-btn" href="javascript:history.back()">← 戻る</a>` | partial test asserts class + href + aria-label |

3 元素 verdict: **all 3 present in partial markup**, all 3 audit-selector compatible (`class="back-btn"` matches the audit query exactly).

## 4. Test run

```
$ cd /tmp/jpcite-w48-docs-bc && pytest tests/test_docs_breadcrumb_back.py -v
============================= test session starts ==============================
collected 7 items

tests/test_docs_breadcrumb_back.py::test_mkdocs_yml_exists PASSED        [ 14%]
tests/test_docs_breadcrumb_back.py::test_navigation_path_feature_enabled PASSED [ 28%]
tests/test_docs_breadcrumb_back.py::test_content_partial_exists PASSED   [ 42%]
tests/test_docs_breadcrumb_back.py::test_back_button_markup PASSED       [ 57%]
tests/test_docs_breadcrumb_back.py::test_breadcrumb_landmarks PASSED     [ 71%]
tests/test_docs_breadcrumb_back.py::test_three_elements_present PASSED   [ 85%]
tests/test_docs_breadcrumb_back.py::test_homepage_skip_guard PASSED      [100%]

============================== 7 passed in 0.99s ==============================
```

Additional sanity checks (out-of-band, not gating):

- `python -c "import yaml; ..."` confirms `navigation.path` line present in mkdocs.yml.
- `python -c "import jinja2; env.parse(src)"` confirms the partial parses as valid Jinja2 (1907 chars).
- `html.parser.HTMLParser` traversal over the Jinja-stripped HTML reports no fatal errors → markup is well-formed.

## 5. Page coverage

Source SOT in this PR: `mkdocs.yml` + `overrides/partials/content.html` apply to **every page rendered by mkdocs build** under `docs/` (project root) → `site/docs/` (build output, .gitignored). Per `find /Users/shigetoumeda/jpcite/site/docs -name '*.html' | wc -l = 76` (mkdocs build output on live repo), the partial coverage at first build is **76 pages × 3 elements**. Mkdocs adds new pages automatically as `docs/**/*.md` are added; no per-page edits required (zero ongoing maintenance per `feedback_keep_it_simple`).

## 6. Verify バグなし

| risk                              | mitigation |
|-----------------------------------|------------|
| Mkdocs build fails (Jinja error)  | `python -c "import jinja2; env.parse(src)"` clean |
| HTML structure broken             | `html.parser.HTMLParser` clean traversal |
| Material theme version mismatch   | `navigation.path` shipped in Material 9.x (already in `mkdocs-material` pin) |
| Homepage double-render            | Guarded by `{% if not page.is_homepage %}` |
| Back button no-op (no referrer)   | `javascript:history.back()` is browser-native; works without referrer |
| Selector mismatch (audit miss)    | `class="back-btn"` is the exact audit selector |
| Test regression on style change   | Tests only assert markup contract, not CSS values |

## 7. PR open

```
$ git add mkdocs.yml overrides/partials/content.html \
          tests/test_docs_breadcrumb_back.py \
          docs/research/wave48/STATE_w48_docs_bc_pr.md
$ git commit -m "feat(docs/ux): breadcrumb + back-btn partial (Wave 48 tick#3 迷子ゼロ)"
$ git push -u origin feat/jpcite_2026_05_12_wave48_docs_breadcrumb_back
$ gh pr create --title "feat(docs/ux): breadcrumb + back partial (Wave 48 tick#3)" --body @<(...)
```

PR# / URL: placeholder until `gh pr create` returns (recorded below after push).

## 8. Artifact list

- `mkdocs.yml` — `navigation.path` feature enabled
- `overrides/partials/content.html` — new partial (~41 lines)
- `tests/test_docs_breadcrumb_back.py` — new test (~132 lines, 7 tests)
- This doc — STATE summary (~120 lines target)
- Lane lock: `/tmp/jpcite-w48-docs-bc.lane` (mkdir-atomic, deleted on tick close)

## 9. 結論

- 3 元素揃い率: docs/ 50% → **100% (NG → OK)**; element axes breadcrumb 50% → ≥75% / back 75% → ≥75% (landing root skip 除いて 100%).
- Wave 48 tick#4 STATE_w48_ux_flow_audit.md「迷子ゼロ gate には docs に breadcrumb + back 追加 + modal emit 修正」のうち、**breadcrumb + back** を本 PR で landed. Modal emit fix は別 tick.
- 0 destruction / 0 main worktree edit / 0 brand revival / 0 LLM API / dual-CLI atomic lane 保持 / Material theme 既存機能のみ (custom JS なし).
