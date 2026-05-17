---
title: "月次決算 jpcite call sequence (税理士)"
segment: tax
recipe: recipe_tax_monthly_closing
cost_estimate_jpy: 39
billable_units: 13
parallel: true
duration_seconds: 60
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "月次決算 jpcite call sequence (税理士)", "description": "§52 (税理士法) — 候補リスト/参考資料のみ提供。最終的な月次決算判定は税理士が責任を負う。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 39}, "totalTime": "PT60S", "step": [{"@type": "HowToStep", "name": "enum_values_am", "text": "vocabulary canonicalize", "position": 1}, {"@type": "HowToStep", "name": "search_tax_incentives", "text": "適用候補 surface", "position": 2}, {"@type": "HowToStep", "name": "evaluate_tax_applicability", "text": "rule x profile bulk 判定", "position": 3}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "当月までの改正/通達 diff", "position": 4}, {"@type": "HowToStep", "name": "prepare_kessan_briefing", "text": "月次 briefing", "position": 5}, {"@type": "HowToStep", "name": "check_exclusions", "text": "排他 / 併給", "position": 6}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "登記/適格/採択 整合性", "position": 7}, {"@type": "HowToStep", "name": "search_invoice_registrants", "text": "適格事業者 status", "position": 8}, {"@type": "HowToStep", "name": "list_tax_sunset_alerts", "text": "sunset alerts", "position": 9}, {"@type": "HowToStep", "name": "compose_audit_workpaper", "text": "workpaper PDF + audit_seal", "position": 10}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 11}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典 + license", "position": 12}, {"@type": "HowToStep", "name": "deep_health_am", "text": "snapshot pin", "position": 13}]}
</script>

# 月次決算 jpcite call sequence (税理士)

> **Cost**: ¥39 (13 billable units, ¥3/req) ·
> **Duration**: 60s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §52 (税理士法) — 候補リスト/参考資料のみ提供。最終的な月次決算判定は税理士が責任を負う。

## Preconditions

- `client_id`
- `houjin_bangou`
- `fiscal_year_month (YYYY-MM)`
- `target_ruleset_ids (optional)`
- `business_profile`

## Steps

1. **enum_values_am** — vocabulary canonicalize
2. **search_tax_incentives** — 適用候補 surface
3. **evaluate_tax_applicability** — rule x profile bulk 判定
4. **track_amendment_lineage_am** — 当月までの改正/通達 diff
5. **prepare_kessan_briefing** — 月次 briefing
6. **check_exclusions** — 排他 / 併給
7. **cross_check_jurisdiction** — 登記/適格/採択 整合性
8. **search_invoice_registrants** — 適格事業者 status
9. **list_tax_sunset_alerts** — sunset alerts
10. **compose_audit_workpaper** — workpaper PDF + audit_seal
11. **jpcite_route** — outcome route
12. **get_provenance** — 出典 + license
13. **deep_health_am** — snapshot pin

## Output artifact

- Type: `monthly_closing_packet`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_tax_monthly_closing"},
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
