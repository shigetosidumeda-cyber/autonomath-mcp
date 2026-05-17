# recipe_real_estate_transfer - 不動産売買登記 jpcite call sequence (司法書士)

**Segment**: 司法書士 (shihoshoshi) / **Disclaimer**: §3 (司法書士法) — 登記申請 独占業務。紛争性ある場合 §72 弁護士業務。

## Pre-conditions

## Steps (11 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `get_law_article_am` | 不動産登記法 §16-§30 |
| 2 | `get_law_article_am` | 民法 §555-§585 |
| 3 | `search_acceptance_stats_am` | 類似 判例 |
| 4 | `get_houjin_360_am` | 法人当事者 360 |
| 5 | `check_enforcement_am` | 履歴 chip |
| 6 | `search_tax_incentives` | 登録免許税 軽減 |
| 7 | `get_am_tax_rule` | 不動産取得税 |
| 8 | `bundle_application_kit` | 所有権移転登記 scaffold |
| 9 | `deadline_calendar` | 税務 calendar |
| 10 | `track_amendment_lineage_am` | 不登法/民法 改正 |
| 11 | `get_provenance` | 出典 |

## Duration / cost
- Expected duration: 60 seconds
- Parallel calls supported: True
- Cost: ¥33 (11 billable units x ¥3)

## Output artifact
- type: `real_estate_transfer_kit`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_real_estate_transfer.yaml`](../../../data/recipes/recipe_real_estate_transfer.yaml).
