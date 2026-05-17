---
title: "不動産売買登記 jpcite call sequence (司法書士)"
segment: shihoshoshi
recipe: recipe_real_estate_transfer
cost_estimate_jpy: 33
billable_units: 11
parallel: true
duration_seconds: 60
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "不動産売買登記 jpcite call sequence (司法書士)", "description": "§3 (司法書士法) — 登記申請 独占業務。紛争性ある場合 §72 弁護士業務。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 33}, "totalTime": "PT60S", "step": [{"@type": "HowToStep", "name": "get_law_article_am", "text": "不動産登記法 §16-§30", "position": 1}, {"@type": "HowToStep", "name": "get_law_article_am", "text": "民法 §555-§585", "position": 2}, {"@type": "HowToStep", "name": "search_acceptance_stats_am", "text": "類似 判例", "position": 3}, {"@type": "HowToStep", "name": "get_houjin_360_am", "text": "法人当事者 360", "position": 4}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "履歴 chip", "position": 5}, {"@type": "HowToStep", "name": "search_tax_incentives", "text": "登録免許税 軽減", "position": 6}, {"@type": "HowToStep", "name": "get_am_tax_rule", "text": "不動産取得税", "position": 7}, {"@type": "HowToStep", "name": "bundle_application_kit", "text": "所有権移転登記 scaffold", "position": 8}, {"@type": "HowToStep", "name": "deadline_calendar", "text": "税務 calendar", "position": 9}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "不登法/民法 改正", "position": 10}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 11}]}
</script>

# 不動産売買登記 jpcite call sequence (司法書士)

> **Cost**: ¥33 (11 billable units, ¥3/req) ·
> **Duration**: 60s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §3 (司法書士法) — 登記申請 独占業務。紛争性ある場合 §72 弁護士業務。

## Preconditions

- `seller_profile`
- `buyer_profile`
- `property_address`
- `sale_price_yen`
- `contract_date`

## Steps

1. **get_law_article_am** — 不動産登記法 §16-§30
2. **get_law_article_am** — 民法 §555-§585
3. **search_acceptance_stats_am** — 類似 判例
4. **get_houjin_360_am** — 法人当事者 360
5. **check_enforcement_am** — 履歴 chip
6. **search_tax_incentives** — 登録免許税 軽減
7. **get_am_tax_rule** — 不動産取得税
8. **bundle_application_kit** — 所有権移転登記 scaffold
9. **deadline_calendar** — 税務 calendar
10. **track_amendment_lineage_am** — 不登法/民法 改正
11. **get_provenance** — 出典

## Output artifact

- Type: `real_estate_transfer_kit`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_real_estate_transfer"},
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
