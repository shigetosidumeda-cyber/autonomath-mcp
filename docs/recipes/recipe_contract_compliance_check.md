---
title: "契約 compliance check jpcite call sequence (行政書士)"
segment: gyousei
recipe: recipe_contract_compliance_check
cost_estimate_jpy: 33
billable_units: 11
parallel: true
duration_seconds: 60
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "契約 compliance check jpcite call sequence (行政書士)", "description": "§72 (弁護士法) / §1 (行政書士法) — 紛争性ある契約は弁護士業務。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 33}, "totalTime": "PT60S", "step": [{"@type": "HowToStep", "name": "enum_values_am", "text": "contract_type closed-set", "position": 1}, {"@type": "HowToStep", "name": "search_by_law", "text": "該当 law surface", "position": 2}, {"@type": "HowToStep", "name": "get_law_article_am", "text": "条文", "position": 3}, {"@type": "HowToStep", "name": "search_acceptance_stats_am", "text": "類似事例", "position": 4}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "法改正", "position": 5}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "履歴 chip", "position": 6}, {"@type": "HowToStep", "name": "search_invoice_registrants", "text": "適格 status", "position": 7}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "jurisdiction", "position": 8}, {"@type": "HowToStep", "name": "rule_engine_check", "text": "禁止条項 detect", "position": 9}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 10}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 11}]}
</script>

# 契約 compliance check jpcite call sequence (行政書士)

> **Cost**: ¥33 (11 billable units, ¥3/req) ·
> **Duration**: 60s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §72 (弁護士法) / §1 (行政書士法) — 紛争性ある契約は弁護士業務。

## Preconditions

- `client_id`
- `contract_type`
- `parties_houjin_bangou (array)`
- `jurisdiction`

## Steps

1. **enum_values_am** — contract_type closed-set
2. **search_by_law** — 該当 law surface
3. **get_law_article_am** — 条文
4. **search_acceptance_stats_am** — 類似事例
5. **track_amendment_lineage_am** — 法改正
6. **check_enforcement_am** — 履歴 chip
7. **search_invoice_registrants** — 適格 status
8. **cross_check_jurisdiction** — jurisdiction
9. **rule_engine_check** — 禁止条項 detect
10. **get_provenance** — 出典
11. **jpcite_route** — outcome route

## Output artifact

- Type: `compliance_check_packet`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_contract_compliance_check"},
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
