# recipe_tax_corporate_filing - 法人税申告書作成 jpcite call sequence (税理士)

**Segment**: 税理士 (tax) / **Disclaimer**: §52 (税理士法) — 申告書作成は税理士の独占業務。本レシピは参考資料のみ。

## Pre-conditions

## Steps (18 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `enum_values_am` | closed-set |
| 2 | `search_tax_incentives` | 適用候補 |
| 3 | `get_am_tax_rule` | rule 詳細 |
| 4 | `evaluate_tax_applicability` | bulk 判定 |
| 5 | `search_acceptance_stats_am` | 同業種 採択率 |
| 6 | `track_amendment_lineage_am` | YoY 改正 |
| 7 | `list_tax_sunset_alerts` | FY 内 sunset |
| 8 | `search_loans_am` | 融資/特例 |
| 9 | `check_enforcement_am` | 行政処分 履歴 |
| 10 | `cross_check_jurisdiction` | 整合性 |
| 11 | `check_exclusions` | 排他 |
| 12 | `prepare_kessan_briefing` | 確定申告 briefing |
| 13 | `compose_audit_workpaper` | workpaper PDF |
| 14 | `bundle_application_kit` | 添付 scaffold |
| 15 | `get_provenance` | 出典 |
| 16 | `jpcite_route` | outcome route |
| 17 | `deep_health_am` | snapshot pin |
| 18 | `jpcite_execute_packet` | route 実行 |

## Duration / cost
- Expected duration: 120 seconds
- Parallel calls supported: True
- Cost: ¥54 (18 billable units x ¥3)

## Output artifact
- type: `corporate_filing_evidence_packet`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_tax_corporate_filing.yaml`](../../../data/recipes/recipe_tax_corporate_filing.yaml).
