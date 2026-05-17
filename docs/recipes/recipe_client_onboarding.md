---
title: "Client onboarding 統合 (AX エンジニア / FDE)"
segment: ax_fde
recipe: recipe_client_onboarding
cost_estimate_jpy: 27
billable_units: 9
parallel: true
duration_seconds: 60
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "Client onboarding 統合 (AX エンジニア / FDE)", "description": "¥3/req metered。AX エンジニアは 5 分で integration 完了。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 27}, "totalTime": "PT60S", "step": [{"@type": "HowToStep", "name": "deep_health_am", "text": "pre-flight", "position": 1}, {"@type": "HowToStep", "name": "list_recipes", "text": "segment 別 recipe", "position": 2}, {"@type": "HowToStep", "name": "get_recipe", "text": "各 outcome の recipe", "position": 3}, {"@type": "HowToStep", "name": "jpcite_preview_cost", "text": "予算試算", "position": 4}, {"@type": "HowToStep", "name": "get_usage_status", "text": "親 quota", "position": 5}, {"@type": "HowToStep", "name": "provision_child_api_key", "text": "顧客 sub-key", "position": 6}, {"@type": "HowToStep", "name": "create_credit_wallet", "text": "前払い wallet", "position": 7}, {"@type": "HowToStep", "name": "list_static_resources_am", "text": "静的 taxonomy", "position": 8}, {"@type": "HowToStep", "name": "list_example_profiles_am", "text": "example profile", "position": 9}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome ごと route", "position": 10}, {"@type": "HowToStep", "name": "deep_health_am", "text": "post-wire smoke", "position": 11}]}
</script>

# Client onboarding 統合 (AX エンジニア / FDE)

> **Cost**: ¥27 (9 billable units, ¥3/req) ·
> **Duration**: 60s ·
> **Parallel-safe**: True ·
> **Disclaimer**: ¥3/req metered。AX エンジニアは 5 分で integration 完了。

## Preconditions

- `client_org_id`
- `target_segment`
- `desired_outcome_slugs (array)`
- `mcp_client_runtime`

## Steps

1. **deep_health_am** — pre-flight
2. **list_recipes** — segment 別 recipe
3. **get_recipe** — 各 outcome の recipe
4. **jpcite_preview_cost** — 予算試算
5. **get_usage_status** — 親 quota
6. **provision_child_api_key** — 顧客 sub-key
7. **create_credit_wallet** — 前払い wallet
8. **list_static_resources_am** — 静的 taxonomy
9. **list_example_profiles_am** — example profile
10. **jpcite_route** — outcome ごと route
11. **deep_health_am** — post-wire smoke

## Output artifact

- Type: `onboarding_handoff_packet`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_client_onboarding"},
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
