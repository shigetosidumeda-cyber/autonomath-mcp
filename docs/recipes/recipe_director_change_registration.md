---
title: "役員変更登記 jpcite call sequence (司法書士)"
segment: shihoshoshi
recipe: recipe_director_change_registration
cost_estimate_jpy: 27
billable_units: 9
parallel: true
duration_seconds: 45
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "役員変更登記 jpcite call sequence (司法書士)", "description": "§3 (司法書士法) — 登記申請 独占業務。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 27}, "totalTime": "PT45S", "step": [{"@type": "HowToStep", "name": "get_law_article_am", "text": "会社法 §329-§341", "position": 1}, {"@type": "HowToStep", "name": "get_law_article_am", "text": "商業登記法 §54", "position": 2}, {"@type": "HowToStep", "name": "get_houjin_360_am", "text": "法人 360", "position": 3}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "新役員 履歴", "position": 4}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "法務局 jurisdiction", "position": 5}, {"@type": "HowToStep", "name": "bundle_application_kit", "text": "変更登記 scaffold", "position": 6}, {"@type": "HowToStep", "name": "deadline_calendar", "text": "2週間以内", "position": 7}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "会社法 改正", "position": 8}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 9}]}
</script>

# 役員変更登記 jpcite call sequence (司法書士)

> **Cost**: ¥27 (9 billable units, ¥3/req) ·
> **Duration**: 45s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §3 (司法書士法) — 登記申請 独占業務。

## Preconditions

- `houjin_bangou`
- `change_type`
- `effective_date`
- `new_director_profile`

## Steps

1. **get_law_article_am** — 会社法 §329-§341
2. **get_law_article_am** — 商業登記法 §54
3. **get_houjin_360_am** — 法人 360
4. **check_enforcement_am** — 新役員 履歴
5. **cross_check_jurisdiction** — 法務局 jurisdiction
6. **bundle_application_kit** — 変更登記 scaffold
7. **deadline_calendar** — 2週間以内
8. **track_amendment_lineage_am** — 会社法 改正
9. **get_provenance** — 出典

## Output artifact

- Type: `director_change_kit`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_director_change_registration"},
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
