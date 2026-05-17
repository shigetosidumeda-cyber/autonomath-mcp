# recipe_audit_consolidation - 連結手続書 jpcite call sequence (公認会計士)

**Segment**: 会計士 (audit) / **Disclaimer**: §47条の2 (公認会計士法) — 連結監査意見表明は会計士独占。

## Pre-conditions

## Steps (18 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `deep_health_am` | snapshot pin |
| 2 | `get_houjin_360_am` | 親法人 360 |
| 3 | `get_houjin_360_am` | 子法人 360 |
| 4 | `cross_check_jurisdiction` | 親子 jurisdiction |
| 5 | `check_enforcement_am` | 親子 履歴 |
| 6 | `get_tax_treaty` | treaty matrix |
| 7 | `check_foreign_capital_eligibility` | 外資要件 |
| 8 | `get_law_article_am` | 会計基準/J-SOX 引用 |
| 9 | `track_amendment_lineage_am` | 連結会計 改正 |
| 10 | `search_acceptance_stats_am` | ベンチマーク |
| 11 | `match_due_diligence_questions` | DD 連結軸 |
| 12 | `check_exclusions` | 親子 排他 |
| 13 | `prepare_kessan_briefing` | 連結決算 briefing |
| 14 | `get_provenance` | 出典 |
| 15 | `compose_audit_workpaper` | 連結調書 PDF |
| 16 | `dispatch_audit_seal_webhook` | audit_seal 配信 |
| 17 | `jpcite_route` | outcome route |
| 18 | `jpcite_preview_cost` | cost preview |

## Duration / cost
- Expected duration: 120 seconds
- Parallel calls supported: True
- Cost: ¥54 (18 billable units x ¥3)

## Output artifact
- type: `consolidation_evidence_packet`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_audit_consolidation.yaml`](../../../data/recipes/recipe_audit_consolidation.yaml).
