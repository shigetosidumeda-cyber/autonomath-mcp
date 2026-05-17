# recipe_compliance_dashboard - Compliance dashboard 統合 (AX エンジニア / FDE)

**Segment**: AX エンジニア / FDE (ax_fde) / **Disclaimer**: ¥3/req metered。多顧客 compliance kpi を 1 dashboard に集約。

## Pre-conditions

## Steps (12 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `deep_health_am` | snapshot pin |
| 2 | `check_enforcement_am` | 全顧問先 行政処分 |
| 3 | `search_invoice_registrants` | 適格 status batch |
| 4 | `track_amendment_lineage_am` | 直近 改正 |
| 5 | `list_tax_sunset_alerts` | sunset / cliff |
| 6 | `cross_check_jurisdiction` | 整合性 |
| 7 | `get_houjin_360_am` | 法人 360 batch |
| 8 | `forecast_program_renewal` | renewal cadence |
| 9 | `dispatch_audit_seal_webhook` | webhook 配信 |
| 10 | `get_provenance` | 出典 chain |
| 11 | `jpcite_preview_cost` | cost preview |
| 12 | `jpcite_route` | outcome route |

## Duration / cost
- Expected duration: 90 seconds
- Parallel calls supported: True
- Cost: ¥60 (20 billable units x ¥3)

## Output artifact
- type: `compliance_dashboard_packet`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_compliance_dashboard.yaml`](../../../data/recipes/recipe_compliance_dashboard.yaml).
