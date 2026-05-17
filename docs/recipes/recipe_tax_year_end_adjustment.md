---
title: "年末調整一括処理 jpcite call sequence (税理士)"
segment: tax
recipe: recipe_tax_year_end_adjustment
cost_estimate_jpy: 42
billable_units: 14
parallel: true
duration_seconds: 90
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "年末調整一括処理 jpcite call sequence (税理士)", "description": "§52 (税理士法) — 年末調整事務の補助のみ。最終判定は税理士。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 42}, "totalTime": "PT90S", "step": [{"@type": "HowToStep", "name": "enum_values_am", "text": "tax_rule_kind closed-set", "position": 1}, {"@type": "HowToStep", "name": "list_tax_sunset_alerts", "text": "当年末 cliff", "position": 2}, {"@type": "HowToStep", "name": "search_tax_incentives", "text": "年末調整 候補", "position": 3}, {"@type": "HowToStep", "name": "get_am_tax_rule", "text": "rule 詳細", "position": 4}, {"@type": "HowToStep", "name": "track_amendment_lineage_am", "text": "YoY 改正", "position": 5}, {"@type": "HowToStep", "name": "bundle_application_kit", "text": "扶養控除等 scaffold", "position": 6}, {"@type": "HowToStep", "name": "prepare_kessan_briefing", "text": "確定申告 briefing", "position": 7}, {"@type": "HowToStep", "name": "compose_audit_workpaper", "text": "顧問先別 PDF", "position": 8}, {"@type": "HowToStep", "name": "dispatch_audit_seal_webhook", "text": "audit_seal 配信", "position": 9}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 10}, {"@type": "HowToStep", "name": "check_exclusions", "text": "控除併用可否", "position": 11}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 12}, {"@type": "HowToStep", "name": "deep_health_am", "text": "snapshot pin", "position": 13}, {"@type": "HowToStep", "name": "jpcite_preview_cost", "text": "予算試算", "position": 14}]}
</script>

# 年末調整一括処理 jpcite call sequence (税理士)

> **Cost**: ¥42 (14 billable units, ¥3/req) ·
> **Duration**: 90s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §52 (税理士法) — 年末調整事務の補助のみ。最終判定は税理士。

## Preconditions

- `client_id`
- `tax_year (YYYY)`
- `profile_ids (顧問先 client_profiles 配列)`

## Steps

1. **enum_values_am** — tax_rule_kind closed-set
2. **list_tax_sunset_alerts** — 当年末 cliff
3. **search_tax_incentives** — 年末調整 候補
4. **get_am_tax_rule** — rule 詳細
5. **track_amendment_lineage_am** — YoY 改正
6. **bundle_application_kit** — 扶養控除等 scaffold
7. **prepare_kessan_briefing** — 確定申告 briefing
8. **compose_audit_workpaper** — 顧問先別 PDF
9. **dispatch_audit_seal_webhook** — audit_seal 配信
10. **get_provenance** — 出典
11. **check_exclusions** — 控除併用可否
12. **jpcite_route** — outcome route
13. **deep_health_am** — snapshot pin
14. **jpcite_preview_cost** — 予算試算

## Output artifact

- Type: `year_end_adjustment_packet`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_tax_year_end_adjustment"},
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
