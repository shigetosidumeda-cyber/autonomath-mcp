# v3 Wave 5 Backlog (post Wave 1-4 main merge)

> 2026-05-11 作成 / Wave 1-4 AUTO 102 task 完了後の Wave 5 残作業。
> 全項目 Claude AUTO で実装可、USER 操作は USER_RUNBOOK.md (24 task) に分離。

## A. registry tuning (publish_text_guard 63K → 50 violation)

現状: scripts/check_publish_text.py 試走で 63,153 violation 検出。大半は legitimate 用語:
- "完全従量" の "完全" (business model 用語、誤検出)
- "個人保証人" / "第三者保証人" の "保証" (融資 3 軸 enum、誤検出)
- "必ずご確認ください" の "必ず" (業法 disclaimer、誤検出)
- "No.1 を謳いません" の "No.1" (否定文脈、誤検出)

修正案: data/facts_registry.json の `guards.banned_terms` を context-aware regex 化:
```json
"banned_terms": [
  {"pattern": "完全(?!従量|な機能|に|に従量)", "context": "marketing claim"},
  {"pattern": "必ず(?!.*ご確認|.*専門家|.*税理士|.*弁護士)", "context": "absolute claim"},
  {"pattern": "保証(?!(人|料率|金額|協会))", "context": "marketing claim"},
  {"pattern": "No\\.1(?!\\s*を謳いません)", "context": "ranking claim"}
]
```
scripts/check_publish_text.py を context-aware 化、~50 violation に縮約。

## B. test.yml / release.yml PYTEST_TARGETS + RUFF_TARGETS 同期

現状: scripts/ops/sync_workflow_targets.py で 36 test file missing 検出。
- test.yml + release.yml の PYTEST_TARGETS env に新 36 test (tests/test_a11y_baseline.py 等) 追加
- RUFF_TARGETS は 34 desired (scripts/check_*.py + scripts/inject_*.py 9 file 追加)
- `Verify workflow targets in sync with git tree` workflow が pass 化

## C. CodeQL pr-diff-range workaround

現状: `codeql-action` の `pr-diff-range.yml:7-16` で `restrictAlertsTo(undefined, undefined, undefined)` エラー。

修正案: .github/workflows/codeql.yml (or 該当 file) で:
```yaml
- uses: github/codeql-action/init@v3
  with:
    config-file: ./.github/codeql/codeql-config.yml
    queries: security-and-quality
    # pr-diff-range を無効化
    enable-pr-diff-range: false  # or 該当オプション
```
または `paths-ignore` で大量 file 除外。

## D. 新 7 workflow を PR gate 化 (Wave 5 後段)

A 完了後:
- publish_text_guard.yml: `on: [pull_request]` 復活、`continue-on-error: false`
- *_v3.yml 6 個: 各 `on:` を gate 用に復活

## E. UI 実装 (G13-G16、HTML+JS 大規模)

| 章 | file | 範囲 |
|---|---|---|
| G13 artifact viewer | site/artifact.html + functions/artifacts/[pack_id].ts | /artifacts/{pack_id} (CF Pages Function SSR)、7 section、PDF/embed/JSON/regen/watch |
| G14 playground 3 step | site/playground.html 改修 (既存 2,650 行) | flow=evidence3 3 step、SSE stream、AI agent UA 切替 |
| G15 dashboard 9 widget | site/dashboard.html 改修 + functions/dashboard.ts | magic-link 認証、Stripe portal mint、9 section |
| G16 status page | site/status/{index,status.json,rss.xml,history,badge.svg}.* + scripts/ops/status_probe.py | 5 component、60s update cron、embed badge |

## F. migration 196+ (entity_id_bridge + 8 join table)

DDL は計画書 v2 章 P3 「9 突合 table DDL」に full spec あり:
- 196_source_document_v2.sql
- 197_extracted_fact_v2.sql
- 198_corpus_snapshot_v2.sql
- 199_entity_id_bridge.sql
- 200_public_funding_ledger.sql
- 201_permit_registry.sql
- 202_permit_event.sql
- 203_invoice_status_history.sql
- 204_enforcement_permit_event_layer.sql

各 `-- target_db: autonomath` 先頭行、IF NOT EXISTS、down.sql companion。

## G. recipes 30 本 deep 化

現状: 各 60-86 行の minimal viable。Wave 5 で各 1500-3000 字に deep 化:
- 実 curl/Python/TypeScript 動作確認済 snippet
- 実 artifact JSON 例 (3-5 件)
- 関連 recipe 3 個の cross-link 整合

## H. GEO 100 問 weekly bench harness

- data/geo_questions.json (100 問、ja 70 + en 30 = 100)
- tests/geo/bench_harness.py (5 surface × 100 = 500 verify、Playwright)
- .github/workflows/geo_eval.yml (weekly cron 月 09:00 JST)
- 結果 → data/geo_bench_w{N}.csv append、W4 平均 >= 1.2 を G18 acceptance gate

## I. acceptance_check.yml (50 item 自動実行)

- scripts/acceptance/run.js (10 category 並列)
- scripts/acceptance/aggregate.js (50 → status_acceptance.json)
- .github/workflows/acceptance_check.yml (weekly cron + workflow_dispatch)
- 50/50 達成で `gh release create v1.0-GA` + announce trigger

## J. USER_RUNBOOK 24 task 実行支援 script

Claude が prepare できる部分:
- gh repo rename の安全確認 (force=false で dry-run 表示)
- PyPI publish 前の version 整合 check (pyproject.toml + server.json)
- Stripe Checkout product 作成の JSON snapshot (USER が web で copy-paste)
- Smithery / awesome-mcp PR 投稿用 markdown final (docs/_internal/mcp_registry_submissions/ から)

## ロードマップ

Wave 5 全 10 項目を AUTO 並列で実装 → PR open → CI green → main merge → 本番 deploy → USER 24 task → 1-2 週で v1.0-GA 達成。

