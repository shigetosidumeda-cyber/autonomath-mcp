# recipe_director_change_registration - 役員変更登記 jpcite call sequence (司法書士)

**Segment**: 司法書士 (shihoshoshi) / **Disclaimer**: §3 (司法書士法) — 登記申請 独占業務。

## Pre-conditions

## Steps (9 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `get_law_article_am` | 会社法 §329-§341 |
| 2 | `get_law_article_am` | 商業登記法 §54 |
| 3 | `get_houjin_360_am` | 法人 360 |
| 4 | `check_enforcement_am` | 新役員 履歴 |
| 5 | `cross_check_jurisdiction` | 法務局 jurisdiction |
| 6 | `bundle_application_kit` | 変更登記 scaffold |
| 7 | `deadline_calendar` | 2週間以内 |
| 8 | `track_amendment_lineage_am` | 会社法 改正 |
| 9 | `get_provenance` | 出典 |

## Duration / cost
- Expected duration: 45 seconds
- Parallel calls supported: True
- Cost: ¥27 (9 billable units x ¥3)

## Output artifact
- type: `director_change_kit`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_director_change_registration.yaml`](../../../data/recipes/recipe_director_change_registration.yaml).
