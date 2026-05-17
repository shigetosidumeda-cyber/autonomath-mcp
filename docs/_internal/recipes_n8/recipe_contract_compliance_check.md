# recipe_contract_compliance_check - 契約 compliance check jpcite call sequence (行政書士)

**Segment**: 行政書士 (gyousei) / **Disclaimer**: §72 (弁護士法) / §1 (行政書士法) — 紛争性ある契約は弁護士業務。

## Pre-conditions

## Steps (11 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `enum_values_am` | contract_type closed-set |
| 2 | `search_by_law` | 該当 law surface |
| 3 | `get_law_article_am` | 条文 |
| 4 | `search_acceptance_stats_am` | 類似事例 |
| 5 | `track_amendment_lineage_am` | 法改正 |
| 6 | `check_enforcement_am` | 履歴 chip |
| 7 | `search_invoice_registrants` | 適格 status |
| 8 | `cross_check_jurisdiction` | jurisdiction |
| 9 | `rule_engine_check` | 禁止条項 detect |
| 10 | `get_provenance` | 出典 |
| 11 | `jpcite_route` | outcome route |

## Duration / cost
- Expected duration: 60 seconds
- Parallel calls supported: True
- Cost: ¥33 (11 billable units x ¥3)

## Output artifact
- type: `compliance_check_packet`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_contract_compliance_check.yaml`](../../../data/recipes/recipe_contract_compliance_check.yaml).
