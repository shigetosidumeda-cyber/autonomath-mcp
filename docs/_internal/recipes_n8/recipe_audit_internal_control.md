# recipe_audit_internal_control - 内部統制評価 jpcite call sequence (公認会計士)

**Segment**: 会計士 (audit) / **Disclaimer**: §47条の2 (公認会計士法) + 金商法 J-SOX — IT/業務 統制評価補助のみ。

## Pre-conditions

## Steps (12 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `deep_health_am` | snapshot pin |
| 2 | `match_due_diligence_questions` | DD 統制軸 |
| 3 | `check_enforcement_am` | 履歴 |
| 4 | `cross_check_jurisdiction` | 整合性 |
| 5 | `search_invoice_registrants` | 適格 status |
| 6 | `search_acceptance_stats_am` | ベンチマーク |
| 7 | `track_amendment_lineage_am` | 金商法/会社法 改正 |
| 8 | `forecast_program_renewal` | renewal cadence |
| 9 | `get_provenance` | 出典 |
| 10 | `compose_audit_workpaper` | 統制評価 workpaper |
| 11 | `dispatch_audit_seal_webhook` | audit_seal 配信 |
| 12 | `jpcite_route` | outcome route |

## Duration / cost
- Expected duration: 90 seconds
- Parallel calls supported: True
- Cost: ¥36 (12 billable units x ¥3)

## Output artifact
- type: `internal_control_evaluation_packet`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_audit_internal_control.yaml`](../../../data/recipes/recipe_audit_internal_control.yaml).
