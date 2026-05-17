---
title: "許認可更新 jpcite call sequence (行政書士)"
segment: gyousei
recipe: recipe_license_renewal
cost_estimate_jpy: 33
billable_units: 11
parallel: true
duration_seconds: 60
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "許認可更新 jpcite call sequence (行政書士)", "description": "§1 (行政書士法) — 許認可申請書面作成 独占業務。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 33}, "totalTime": "PT60S", "step": [{"@type": "HowToStep", "name": "enum_values_am", "text": "license_type closed-set", "position": 1}, {"@type": "HowToStep", "name": "search_certifications", "text": "該当 認証/許認可", "position": 2}, {"@type": "HowToStep", "name": "program_full_context", "text": "更新要件 詳細", "position": 3}, {"@type": "HowToStep", "name": "prerequisite_chain", "text": "更新 前提 chain", "position": 4}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "履歴 chip", "position": 5}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "jurisdiction", "position": 6}, {"@type": "HowToStep", "name": "bundle_application_kit", "text": "更新 scaffold", "position": 7}, {"@type": "HowToStep", "name": "deadline_calendar", "text": "更新期限", "position": 8}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "業法 改正", "position": 9}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 10}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 11}]}
</script>

# 許認可更新 jpcite call sequence (行政書士)

> **Cost**: ¥33 (11 billable units, ¥3/req) ·
> **Duration**: 60s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §1 (行政書士法) — 許認可申請書面作成 独占業務。

## Preconditions

- `client_id`
- `houjin_bangou`
- `license_type`
- `license_expiry_date`
- `jurisdiction`

## Steps

1. **enum_values_am** — license_type closed-set
2. **search_certifications** — 該当 認証/許認可
3. **program_full_context** — 更新要件 詳細
4. **prerequisite_chain** — 更新 前提 chain
5. **check_enforcement_am** — 履歴 chip
6. **cross_check_jurisdiction** — jurisdiction
7. **bundle_application_kit** — 更新 scaffold
8. **deadline_calendar** — 更新期限
9. **track_amendment_lineage_am** — 業法 改正
10. **get_provenance** — 出典
11. **jpcite_route** — outcome route

## Output artifact

- Type: `license_renewal_kit`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_license_renewal"},
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
