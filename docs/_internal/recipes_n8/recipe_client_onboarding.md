# recipe_client_onboarding - Client onboarding 統合 (AX エンジニア / FDE)

**Segment**: AX エンジニア / FDE (ax_fde) / **Disclaimer**: ¥3/req metered。AX エンジニアは 5 分で integration 完了。

## Pre-conditions

## Steps (11 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `deep_health_am` | pre-flight |
| 2 | `list_recipes` | segment 別 recipe |
| 3 | `get_recipe` | 各 outcome の recipe |
| 4 | `jpcite_preview_cost` | 予算試算 |
| 5 | `get_usage_status` | 親 quota |
| 6 | `provision_child_api_key` | 顧客 sub-key |
| 7 | `create_credit_wallet` | 前払い wallet |
| 8 | `list_static_resources_am` | 静的 taxonomy |
| 9 | `list_example_profiles_am` | example profile |
| 10 | `jpcite_route` | outcome ごと route |
| 11 | `deep_health_am` | post-wire smoke |

## Duration / cost
- Expected duration: 60 seconds
- Parallel calls supported: True
- Cost: ¥27 (9 billable units x ¥3)

## Output artifact
- type: `onboarding_handoff_packet`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_client_onboarding.yaml`](../../../data/recipes/recipe_client_onboarding.yaml).
