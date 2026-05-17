# recipe_tax_monthly_closing - 月次決算 jpcite call sequence (税理士)

**Segment**: 税理士 (tax) / **Disclaimer**: §52 (税理士法) — 候補リスト/参考資料のみ提供。最終的な月次決算判定は税理士が責任を負う。

## Pre-conditions

## Steps (13 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `enum_values_am` | vocabulary canonicalize |
| 2 | `search_tax_incentives` | 適用候補 surface |
| 3 | `evaluate_tax_applicability` | rule x profile bulk 判定 |
| 4 | `track_amendment_lineage_am` | 当月までの改正/通達 diff |
| 5 | `prepare_kessan_briefing` | 月次 briefing |
| 6 | `check_exclusions` | 排他 / 併給 |
| 7 | `cross_check_jurisdiction` | 登記/適格/採択 整合性 |
| 8 | `search_invoice_registrants` | 適格事業者 status |
| 9 | `list_tax_sunset_alerts` | sunset alerts |
| 10 | `compose_audit_workpaper` | workpaper PDF + audit_seal |
| 11 | `jpcite_route` | outcome route |
| 12 | `get_provenance` | 出典 + license |
| 13 | `deep_health_am` | snapshot pin |

## Duration / cost
- Expected duration: 60 seconds
- Parallel calls supported: True
- Cost: ¥39 (13 billable units x ¥3)

## Output artifact
- type: `monthly_closing_packet`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_tax_monthly_closing.yaml`](../../../data/recipes/recipe_tax_monthly_closing.yaml).
