# recipe_tax_year_end_adjustment - 年末調整一括処理 jpcite call sequence (税理士)

**Segment**: 税理士 (tax) / **Disclaimer**: §52 (税理士法) — 年末調整事務の補助のみ。最終判定は税理士。

## Pre-conditions

## Steps (14 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `enum_values_am` | tax_rule_kind closed-set |
| 2 | `list_tax_sunset_alerts` | 当年末 cliff |
| 3 | `search_tax_incentives` | 年末調整 候補 |
| 4 | `get_am_tax_rule` | rule 詳細 |
| 5 | `track_amendment_lineage_am` | YoY 改正 |
| 6 | `bundle_application_kit` | 扶養控除等 scaffold |
| 7 | `prepare_kessan_briefing` | 確定申告 briefing |
| 8 | `compose_audit_workpaper` | 顧問先別 PDF |
| 9 | `dispatch_audit_seal_webhook` | audit_seal 配信 |
| 10 | `get_provenance` | 出典 |
| 11 | `check_exclusions` | 控除併用可否 |
| 12 | `jpcite_route` | outcome route |
| 13 | `deep_health_am` | snapshot pin |
| 14 | `jpcite_preview_cost` | 予算試算 |

## Duration / cost
- Expected duration: 90 seconds
- Parallel calls supported: True
- Cost: ¥42 (14 billable units x ¥3)

## Output artifact
- type: `year_end_adjustment_packet`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_tax_year_end_adjustment.yaml`](../../../data/recipes/recipe_tax_year_end_adjustment.yaml).
