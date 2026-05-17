# recipe_subsidy_application_draft - 補助金申請書 draft jpcite call sequence (行政書士)

**Segment**: 行政書士 (gyousei) / **Disclaimer**: §1 (行政書士法) — 申請書面作成は行政書士の独占業務。本レシピは scaffold + 一次 URL のみ。

## Pre-conditions

## Steps (13 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `enum_values_am` | closed-set |
| 2 | `search_programs` | 候補 FTS5 |
| 3 | `program_full_context` | 詳細 + 法令 + 通達 |
| 4 | `program_lifecycle` | active period |
| 5 | `prerequisite_chain` | 前提 chain |
| 6 | `similar_cases` | 採択事例 |
| 7 | `rule_engine_check` | eligibility |
| 8 | `check_exclusions` | 併給 |
| 9 | `bundle_application_kit` | scaffold + checklist |
| 10 | `check_enforcement_am` | 履歴 chip |
| 11 | `deadline_calendar` | 申請期限 |
| 12 | `get_provenance` | 出典 |
| 13 | `jpcite_route` | outcome route |

## Duration / cost
- Expected duration: 75 seconds
- Parallel calls supported: True
- Cost: ¥39 (13 billable units x ¥3)

## Output artifact
- type: `application_kit_scaffold`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_subsidy_application_draft.yaml`](../../../data/recipes/recipe_subsidy_application_draft.yaml).
