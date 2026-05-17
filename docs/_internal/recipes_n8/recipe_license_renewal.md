# recipe_license_renewal - 許認可更新 jpcite call sequence (行政書士)

**Segment**: 行政書士 (gyousei) / **Disclaimer**: §1 (行政書士法) — 許認可申請書面作成 独占業務。

## Pre-conditions

## Steps (11 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `enum_values_am` | license_type closed-set |
| 2 | `search_certifications` | 該当 認証/許認可 |
| 3 | `program_full_context` | 更新要件 詳細 |
| 4 | `prerequisite_chain` | 更新 前提 chain |
| 5 | `check_enforcement_am` | 履歴 chip |
| 6 | `cross_check_jurisdiction` | jurisdiction |
| 7 | `bundle_application_kit` | 更新 scaffold |
| 8 | `deadline_calendar` | 更新期限 |
| 9 | `track_amendment_lineage_am` | 業法 改正 |
| 10 | `get_provenance` | 出典 |
| 11 | `jpcite_route` | outcome route |

## Duration / cost
- Expected duration: 60 seconds
- Parallel calls supported: True
- Cost: ¥33 (11 billable units x ¥3)

## Output artifact
- type: `license_renewal_kit`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_license_renewal.yaml`](../../../data/recipes/recipe_license_renewal.yaml).
