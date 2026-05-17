---
title: "会社設立登記一式 jpcite call sequence (司法書士)"
segment: shihoshoshi
recipe: recipe_corporate_setup_registration
cost_estimate_jpy: 39
billable_units: 13
parallel: true
duration_seconds: 90
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "会社設立登記一式 jpcite call sequence (司法書士)", "description": "§3 (司法書士法) — 登記申請書面 独占業務。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 39}, "totalTime": "PT90S", "step": [{"@type": "HowToStep", "name": "enum_values_am", "text": "target_type", "position": 1}, {"@type": "HowToStep", "name": "get_law_article_am", "text": "会社法 §25-§103", "position": 2}, {"@type": "HowToStep", "name": "get_law_article_am", "text": "商業登記法 §17-§24", "position": 3}, {"@type": "HowToStep", "name": "search_certifications", "text": "設立後 補助金", "position": 4}, {"@type": "HowToStep", "name": "similar_cases", "text": "設立後 採択事例", "position": 5}, {"@type": "HowToStep", "name": "search_invoice_registrants", "text": "同名 chip", "position": 6}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "代表者 履歴", "position": 7}, {"@type": "HowToStep", "name": "prerequisite_chain", "text": "設立 前提 chain", "position": 8}, {"@type": "HowToStep", "name": "bundle_application_kit", "text": "scaffold", "position": 9}, {"@type": "HowToStep", "name": "deadline_calendar", "text": "設立後 calendar", "position": 10}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "会社法 改正", "position": 11}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 12}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 13}]}
</script>

# 会社設立登記一式 jpcite call sequence (司法書士)

> **Cost**: ¥39 (13 billable units, ¥3/req) ·
> **Duration**: 90s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §3 (司法書士法) — 登記申請書面 独占業務。

## Preconditions

- `founder_profile`
- `new_company_name`
- `business_purpose (array)`
- `prefecture`
- `capital_yen`

## Steps

1. **enum_values_am** — target_type
2. **get_law_article_am** — 会社法 §25-§103
3. **get_law_article_am** — 商業登記法 §17-§24
4. **search_certifications** — 設立後 補助金
5. **similar_cases** — 設立後 採択事例
6. **search_invoice_registrants** — 同名 chip
7. **check_enforcement_am** — 代表者 履歴
8. **prerequisite_chain** — 設立 前提 chain
9. **bundle_application_kit** — scaffold
10. **deadline_calendar** — 設立後 calendar
11. **track_amendment_lineage_am** — 会社法 改正
12. **get_provenance** — 出典
13. **jpcite_route** — outcome route

## Output artifact

- Type: `corporate_setup_kit`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_corporate_setup_registration"},
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
