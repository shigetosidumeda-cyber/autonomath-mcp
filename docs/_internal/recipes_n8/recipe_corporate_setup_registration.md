# recipe_corporate_setup_registration - 会社設立登記一式 jpcite call sequence (司法書士)

**Segment**: 司法書士 (shihoshoshi) / **Disclaimer**: §3 (司法書士法) — 登記申請書面 独占業務。

## Pre-conditions

## Steps (13 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `enum_values_am` | target_type |
| 2 | `get_law_article_am` | 会社法 §25-§103 |
| 3 | `get_law_article_am` | 商業登記法 §17-§24 |
| 4 | `search_certifications` | 設立後 補助金 |
| 5 | `similar_cases` | 設立後 採択事例 |
| 6 | `search_invoice_registrants` | 同名 chip |
| 7 | `check_enforcement_am` | 代表者 履歴 |
| 8 | `prerequisite_chain` | 設立 前提 chain |
| 9 | `bundle_application_kit` | scaffold |
| 10 | `deadline_calendar` | 設立後 calendar |
| 11 | `track_amendment_lineage_am` | 会社法 改正 |
| 12 | `get_provenance` | 出典 |
| 13 | `jpcite_route` | outcome route |

## Duration / cost
- Expected duration: 90 seconds
- Parallel calls supported: True
- Cost: ¥39 (13 billable units x ¥3)

## Output artifact
- type: `corporate_setup_kit`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_corporate_setup_registration.yaml`](../../../data/recipes/recipe_corporate_setup_registration.yaml).
