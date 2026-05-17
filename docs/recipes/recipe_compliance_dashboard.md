---
title: "Compliance dashboard 統合 (AX エンジニア / FDE)"
segment: ax_fde
recipe: recipe_compliance_dashboard
cost_estimate_jpy: 60
billable_units: 20
parallel: true
duration_seconds: 90
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "Compliance dashboard 統合 (AX エンジニア / FDE)", "description": "¥3/req metered。多顧客 compliance kpi を 1 dashboard に集約。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 60}, "totalTime": "PT90S", "step": [{"@type": "HowToStep", "name": "deep_health_am", "text": "snapshot pin", "position": 1}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "全顧問先 行政処分", "position": 2}, {"@type": "HowToStep", "name": "search_invoice_registrants", "text": "適格 status batch", "position": 3}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "直近 改正", "position": 4}, {"@type": "HowToStep", "name": "list_tax_sunset_alerts", "text": "sunset / cliff", "position": 5}, {"@type": "HowToStep", "name": "cross_check_jurisdiction", "text": "整合性", "position": 6}, {"@type": "HowToStep", "name": "get_houjin_360_am", "text": "法人 360 batch", "position": 7}, {"@type": "HowToStep", "name": "forecast_program_renewal", "text": "renewal cadence", "position": 8}, {"@type": "HowToStep", "name": "dispatch_audit_seal_webhook", "text": "webhook 配信", "position": 9}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典 chain", "position": 10}, {"@type": "HowToStep", "name": "jpcite_preview_cost", "text": "cost preview", "position": 11}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 12}]}
</script>

# Compliance dashboard 統合 (AX エンジニア / FDE)

> **Cost**: ¥60 (20 billable units, ¥3/req) ·
> **Duration**: 90s ·
> **Parallel-safe**: True ·
> **Disclaimer**: ¥3/req metered。多顧客 compliance kpi を 1 dashboard に集約。

## Preconditions

- `client_org_id`
- `tracked_houjin_bangou_list`
- `kpi_axes`
- `refresh_cadence`

## Steps

1. **deep_health_am** — snapshot pin
2. **check_enforcement_am** — 全顧問先 行政処分
3. **search_invoice_registrants** — 適格 status batch
4. **track_amendment_lineage_am** — 直近 改正
5. **list_tax_sunset_alerts** — sunset / cliff
6. **cross_check_jurisdiction** — 整合性
7. **get_houjin_360_am** — 法人 360 batch
8. **forecast_program_renewal** — renewal cadence
9. **dispatch_audit_seal_webhook** — webhook 配信
10. **get_provenance** — 出典 chain
11. **jpcite_preview_cost** — cost preview
12. **jpcite_route** — outcome route

## Output artifact

- Type: `compliance_dashboard_packet`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_compliance_dashboard"},
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
