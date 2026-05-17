---
title: "補助金申請書 draft jpcite call sequence (行政書士)"
segment: gyousei
recipe: recipe_subsidy_application_draft
cost_estimate_jpy: 39
billable_units: 13
parallel: true
duration_seconds: 75
---

<!-- structured data -->
<script type="application/ld+json">
{"@context": "https://schema.org", "@type": "HowTo", "name": "補助金申請書 draft jpcite call sequence (行政書士)", "description": "§1 (行政書士法) — 申請書面作成は行政書士の独占業務。本レシピは scaffold + 一次 URL のみ。", "estimatedCost": {"@type": "MonetaryAmount", "currency": "JPY", "value": 39}, "totalTime": "PT75S", "step": [{"@type": "HowToStep", "name": "enum_values_am", "text": "closed-set", "position": 1}, {"@type": "HowToStep", "name": "search_programs", "text": "候補 FTS5", "position": 2}, {"@type": "HowToStep", "name": "program_full_context", "text": "詳細 + 法令 + 通達", "position": 3}, {"@type": "HowToStep", "name": "program_lifecycle", "text": "active period", "position": 4}, {"@type": "HowToStep", "name": "prerequisite_chain", "text": "前提 chain", "position": 5}, {"@type": "HowToStep", "name": "similar_cases", "text": "採択事例", "position": 6}, {"@type": "HowToStep", "name": "rule_engine_check", "text": "eligibility", "position": 7}, {"@type": "HowToStep", "name": "check_exclusions", "text": "併給", "position": 8}, {"@type": "HowToStep", "name": "bundle_application_kit", "text": "scaffold + checklist", "position": 9}, {"@type": "HowToStep", "name": "check_enforcement_am", "text": "履歴 chip", "position": 10}, {"@type": "HowToStep", "name": "deadline_calendar", "text": "申請期限", "position": 11}, {"@type": "HowToStep", "name": "get_provenance", "text": "出典", "position": 12}, {"@type": "HowToStep", "name": "jpcite_route", "text": "outcome route", "position": 13}]}
</script>

# 補助金申請書 draft jpcite call sequence (行政書士)

> **Cost**: ¥39 (13 billable units, ¥3/req) ·
> **Duration**: 75s ·
> **Parallel-safe**: True ·
> **Disclaimer**: §1 (行政書士法) — 申請書面作成は行政書士の独占業務。本レシピは scaffold + 一次 URL のみ。

## Preconditions

- `client_id`
- `houjin_bangou`
- `target_program_id (or keyword)`
- `applicant_profile`

## Steps

1. **enum_values_am** — closed-set
2. **search_programs** — 候補 FTS5
3. **program_full_context** — 詳細 + 法令 + 通達
4. **program_lifecycle** — active period
5. **prerequisite_chain** — 前提 chain
6. **similar_cases** — 採択事例
7. **rule_engine_check** — eligibility
8. **check_exclusions** — 併給
9. **bundle_application_kit** — scaffold + checklist
10. **check_enforcement_am** — 履歴 chip
11. **deadline_calendar** — 申請期限
12. **get_provenance** — 出典
13. **jpcite_route** — outcome route

## Output artifact

- Type: `application_kit_scaffold`
- Format: JSON (mirrored to PDF on `artifact_pack` package_kind)

## SDK invocation

```python
import httpx, os
JPCITE = "https://api.jpcite.com"
key = os.environ["JPCITE_API_KEY"]
resp = httpx.post(
    f"{JPCITE}/v1/jpcite/route",
    headers={"X-API-Key": key},
    json={"intent": "recipe_subsidy_application_draft"},
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
