---
title: "Domain expertise transfer to client agent (AX / FDE)"
segment: ax_fde
recipe: recipe_domain_expertise_transfer
cost_estimate_jpy: 30
billable_units: 10
parallel: true
duration_seconds: 75
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "Domain expertise transfer to client agent (AX / FDE)", "description": "¥3/req metered。jpcite Evidence/Recipe を client agent に転送。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 30}, "totalTime": "PT75S", "step": [{"@type": "HowToStep", "name": "list_recipes", "text": "segment 全 recipe", "position": 1}, {"@type": "HowToStep", "name": "get_recipe", "text": "各 skill ごと recipe", "position": 2}, {"@type": "HowToStep", "name": "list_static_resources_am", "text": "静的 taxonomy", "position": 3}, {"@type": "HowToStep", "name": "list_example_profiles_am", "text": "example profile", "position": 4}, {"@type": "HowToStep", "name": "deep_health_am", "text": "snapshot pin", "position": 5}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典 chain", "position": 6}, {"@type": "HowToStep", "name": "jpcite_route", "text": "route 推奨", "position": 7}, {"@type": "HowToStep", "name": "jpcite_preview_cost", "text": "cost preview", "position": 8}, {"@type": "HowToStep", "name": "resolve_placeholder", "text": "テンプレート placeholder 解決", "position": 9}, {"@type": "HowToStep", "name": "get_artifact_template", "text": "scaffold 取得", "position": 10}]}
</script>

# Domain expertise transfer to client agent (AX / FDE)

> **Cost**: ¥30 (10 billable units, ¥3/req) ·
> **Duration**: 75s ·
> **Parallel-safe**: True ·
> **Disclaimer**: ¥3/req metered。jpcite Evidence/Recipe を client agent に転送。

## Preconditions

- `client_agent_runtime`
- `target_segment`
- `desired_skills (array)`

## Steps

1. **list_recipes** — segment 全 recipe
2. **get_recipe** — 各 skill ごと recipe
3. **list_static_resources_am** — 静的 taxonomy
4. **list_example_profiles_am** — example profile
5. **deep_health_am** — snapshot pin
6. **get_provenance** — 出典 chain
7. **jpcite_route** — route 推奨
8. **jpcite_preview_cost** — cost preview
9. **resolve_placeholder** — テンプレート placeholder 解決
10. **get_artifact_template** — scaffold 取得

## Output artifact

- Type: `skill_transfer_handoff`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_domain_expertise_transfer"},
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
