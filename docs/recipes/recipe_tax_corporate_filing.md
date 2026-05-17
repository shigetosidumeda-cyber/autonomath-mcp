---
title: "法人税申告書作成 jpcite call sequence (税理士)"
segment: tax
recipe: recipe_tax_corporate_filing
cost_estimate_jpy: 54
billable_units: 18
parallel: true
duration_seconds: 120
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "法人税申告書作成 jpcite call sequence (税理士)", "description": "§52 (税理士法) — 申告書作成は税理士の独占業務。本レシピは参考資料のみ。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 54}, "totalTime": "PT120S", "step": [{"@type": "HowToStep", "name": "enum_values_am", "text": "closed-set", "position": 1}, {"@type": "HowToStep", "name": "search_tax_incentives", "text": "適用候補", "position": 2}, {"@type": "HowToStep", "name": "get_am_tax_rule", "text": "rule 詳細", "position": 3}, {"@type": "HowToStep", "name": "evaluate_tax_applicability", "text": "bulk 判定", "position": 4}, {"@type": "HowToStep", "name": "search_acceptance_stats_am", "text": "同業種 採択率", "position": 5}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "YoY 改正", "position": 6}, {"@type": "HowToStep", "name": "list_tax_sunset_alerts", "text": "FY 内 sunset", "position": 7}, {"@type": "HowToStep", "name": "search_loans_am", "text": "融資/特例", "position": 8}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "行政処分 履歴", "position": 9}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "整合性", "position": 10}, {"@type": "HowToStep", "name": "check_exclusions", "text": "排他", "position": 11}, {"@type": "HowToStep", "name": "prepare_kessan_briefing", "text": "確定申告 briefing", "position": 12}, {"@type": "HowToStep", "name": "compose_audit_workpaper", "text": "workpaper PDF", "position": 13}, {"@type": "HowToStep", "name": "bundle_application_kit", "text": "添付 scaffold", "position": 14}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 15}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 16}, {"@type": "HowToStep", "name": "deep_health_am", "text": "snapshot pin", "position": 17}, {"@type": "HowToStep", "name": "jpcite_execute_packet", "text": "route 実行", "position": 18}]}
</script>

# 法人税申告書作成 jpcite call sequence (税理士)

> **Cost**: ¥54 (18 billable units, ¥3/req) ·
> **Duration**: 120s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §52 (税理士法) — 申告書作成は税理士の独占業務。本レシピは参考資料のみ。

## Preconditions

- `client_id`
- `houjin_bangou`
- `fiscal_year_end (YYYY-MM-DD)`
- `business_profile`

## Steps

1. **enum_values_am** — closed-set
2. **search_tax_incentives** — 適用候補
3. **get_am_tax_rule** — rule 詳細
4. **evaluate_tax_applicability** — bulk 判定
5. **search_acceptance_stats_am** — 同業種 採択率
6. **track_amendment_lineage_am** — YoY 改正
7. **list_tax_sunset_alerts** — FY 内 sunset
8. **search_loans_am** — 融資/特例
9. **check_enforcement_am** — 行政処分 履歴
10. **cross_check_jurisdiction** — 整合性
11. **check_exclusions** — 排他
12. **prepare_kessan_briefing** — 確定申告 briefing
13. **compose_audit_workpaper** — workpaper PDF
14. **bundle_application_kit** — 添付 scaffold
15. **get_provenance** — 出典
16. **jpcite_route** — outcome route
17. **deep_health_am** — snapshot pin
18. **jpcite_execute_packet** — route 実行

## Output artifact

- Type: `corporate_filing_evidence_packet`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_tax_corporate_filing"},
).raise_for_status().json()
# returns recommended_tool, outcome_contract_id, deliverable_slug,
# estimated_price_jpy, execute_input_hash, next_action
```

## Related

- [Cookbook index](/docs/cookbook/)
- [API reference](/docs/api-reference/)
- [MCP tools](/docs/mcp-tools/)
- [Outcome catalog](https://jpcite.com/.well-known/jpcite-outcome-catalog.json)

---

*Operator: Bookyou株式会社 (T8010001213708) · Brand: jpcite · NO LLM inside · ¥3/req metered · 100% organic*
