# recipe_audit_workpaper_compile - 監査調書編纂 jpcite call sequence (公認会計士)

**Segment**: 会計士 (audit) / **Disclaimer**: §47条の2 (公認会計士法) — 監査意見表明は会計士の独占業務。本レシピは調書補助のみ。

## Pre-conditions

## Steps (14 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `deep_health_am` | snapshot pin |
| 2 | `enum_values_am` | vocab |
| 3 | `search_tax_incentives` | 適用候補 |
| 4 | `get_am_tax_rule` | rule 詳細 |
| 5 | `evaluate_tax_applicability` | profile x rule |
| 6 | `track_amendment_lineage_am` | 期間中 改正 |
| 7 | `cross_check_jurisdiction` | 整合性 |
| 8 | `check_enforcement_am` | 履歴 |
| 9 | `match_due_diligence_questions` | DD 質問 deck |
| 10 | `get_provenance` | 出典 |
| 11 | `check_exclusions` | 排他 |
| 12 | `compose_audit_workpaper` | 調書 PDF |
| 13 | `dispatch_audit_seal_webhook` | audit_seal 配信 |
| 14 | `jpcite_route` | outcome route |

## Duration / cost
- Expected duration: 90 seconds
- Parallel calls supported: True
- Cost: ¥42 (14 billable units x ¥3)

## Output artifact
- type: `audit_workpaper_pdf`
- format: `pdf+json`
- fields:

Machine-readable: [`data/recipes/recipe_audit_workpaper_compile.yaml`](../../../data/recipes/recipe_audit_workpaper_compile.yaml).
