# recipe_domain_expertise_transfer - Domain expertise transfer to client agent (AX / FDE)

**Segment**: AX エンジニア / FDE (ax_fde) / **Disclaimer**: ¥3/req metered。jpcite Evidence/Recipe を client agent に転送。

## Pre-conditions

## Steps (10 MCP calls)

| # | tool | purpose |
|---|------|---------|
| 1 | `list_recipes` | segment 全 recipe |
| 2 | `get_recipe` | 各 skill ごと recipe |
| 3 | `list_static_resources_am` | 静的 taxonomy |
| 4 | `list_example_profiles_am` | example profile |
| 5 | `deep_health_am` | snapshot pin |
| 6 | `get_provenance` | 出典 chain |
| 7 | `jpcite_route` | route 推奨 |
| 8 | `jpcite_preview_cost` | cost preview |
| 9 | `resolve_placeholder` | テンプレート placeholder 解決 |
| 10 | `get_artifact_template` | scaffold 取得 |

## Duration / cost
- Expected duration: 75 seconds
- Parallel calls supported: True
- Cost: ¥30 (10 billable units x ¥3)

## Output artifact
- type: `skill_transfer_handoff`
- format: `json`
- fields:

Machine-readable: [`data/recipes/recipe_domain_expertise_transfer.yaml`](../../../data/recipes/recipe_domain_expertise_transfer.yaml).
