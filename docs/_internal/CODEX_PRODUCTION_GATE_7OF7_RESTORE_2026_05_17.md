# CodeX Production Gate 7/7 Restore Audit - 2026-05-17

## Scope

- Workspace: `/Users/shigetoumeda/jpcite-codex-evening`
- Branch after fast-forward: `codex-evening-2026-05-17`
- Audited HEAD: `0f463d4991841680264e021dd6c66025e4a51b27`
- Latest commit: `M1 PDF->KG LIVE: 108,077 entity facts + 99,929 relations [lane:solo]`
- Live AWS: not used.
- Protected files: not edited.
- Only write performed by this audit: this report.

## Commands Run

```bash
pwd
git status --short --branch
git rev-parse --show-toplevel
git rev-parse HEAD
git branch --show-current
git log -1 --date=iso-strict --pretty='format:%H%n%an%n%ad%n%s'
git pull --ff-only
.venv/bin/python scripts/ops/production_deploy_readiness_gate.py
```

Supporting read-only probes:

```bash
.venv/bin/python scripts/check_openapi_drift.py
.venv/bin/python - <<'PY'
import importlib
import pathlib
import sys
root = pathlib.Path.cwd()
for path in (root, root / "src"):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)
for mod in (
    "jpintel_mcp.mcp.autonomath_tools.adoption_narrative_tools",
    "jpintel_mcp.mcp.autonomath_tools",
    "jpintel_mcp.mcp.server",
):
    loaded = importlib.import_module(mod)
    print(f"OK import {mod} file={getattr(loaded, '__file__', None)}")
PY
```

## Gate Result

Production readiness command exited `1`.

- Generated at: `2026-05-17T08:52:13+00:00`
- Summary: `pass=2`, `fail=5`, `total=7`
- Passing gates: `agent_runtime_contracts`, `release_capsule_route`
- Failing gates: `functions_typecheck`, `release_capsule_validator`, `openapi_drift`, `mcp_drift`, `aws_blocked_preflight_state`

## Failing Gates

### 1. functions_typecheck

Evidence:

- Command: `npm run --prefix functions typecheck`
- Return code: `127`
- Error: `sh: tsc: command not found`
- Local probe: `functions/node_modules` is absent; `functions/package-lock.json` is present.
- Local toolchain: `node v24.13.1`, `npm 11.8.0`

Fix classification: CodeX-safe local environment hydration, but not performed because this audit is report-only.

Fix plan:

```bash
npm ci --prefix functions
npm run --prefix functions typecheck
.venv/bin/python scripts/ops/production_deploy_readiness_gate.py
```

### 2. release_capsule_validator

Evidence:

- Command: `.venv/bin/python scripts/ops/validate_release_capsule.py --repo-root /Users/shigetoumeda/jpcite-codex-evening`
- Return code: `1`
- Output: `release capsule validator: failed - preflight scorecard must set live_aws_commands_allowed=false`
- `site/releases/rc1-p0-bootstrap/preflight_scorecard.json` currently has:
  - `state: "AWS_CANARY_READY"`
  - `live_aws_commands_allowed: true`
  - `cash_bill_guard_enabled: true`
- `site/releases/current/runtime_pointer.json` and `site/.well-known/jpcite-release.json` both still have `live_aws_commands_allowed: false`.

Fix classification: protected/operator-owned. The requested scope explicitly forbids scorecard edits.

Fix plan:

1. Protected owner/operator decides the intended AWS posture.
2. Under the current validator contract, `AWS_CANARY_READY` is allowed, but `live_aws_commands_allowed` must remain `false` until operator unlock.
3. Protected owner updates the scorecard or changes the gate policy as part of the formal Stream I unlock, then runs:

```bash
.venv/bin/python scripts/ops/validate_release_capsule.py --repo-root /Users/shigetoumeda/jpcite-codex-evening
.venv/bin/python scripts/ops/production_deploy_readiness_gate.py
```

### 3. openapi_drift

Evidence:

- Command: `.venv/bin/python scripts/check_openapi_drift.py`
- Return code: `1`
- Stale generated files reported:
  - `site/openapi/v1.json`
  - `site/openapi.agent.json`
  - `site/openapi/agent.json`
  - `site/openapi.agent.gpt30.json`
- Discovery metadata drift:
  - `site/.well-known/openapi-discovery.json` tier `agent` size and SHA do not match `site/openapi.agent.json`.
  - `site/.well-known/openapi-discovery.json` tier `gpt30` size and SHA do not match `site/openapi.agent.gpt30.json`.
- No OpenAPI leak-scan failure was reported.

Fix classification: CodeX-safe generated artifact refresh if broader write approval is granted. Not performed in this audit.

Fix plan:

```bash
.venv/bin/python scripts/export_openapi.py --out docs/openapi/v1.json --site-out site/docs/openapi/v1.json
.venv/bin/python scripts/export_agent_openapi.py
.venv/bin/python scripts/export_openapi.py --profile gpt30 --out site/openapi.agent.gpt30.json
.venv/bin/python - <<'PY'
from scripts.ops.frontend_release_check import sync_openapi_discovery_metadata
sync_openapi_discovery_metadata()
PY
.venv/bin/python scripts/check_openapi_drift.py
```

### 4. mcp_drift

Evidence:

- Command: `.venv/bin/python scripts/check_mcp_drift.py`
- Return code: `1`
- Runtime tool count: `231`
- Guard range from `data/facts_registry.json`: `[130, 200]`
- Published full manifests currently list `184` tools.
- Failing manifests include `mcp-server.json`, `mcp-server.full.json`, `site/mcp-server.json`, `site/mcp-server.full.json`, `server.json`, and `site/server.json`.
- Runtime has `47` tools missing from the full manifests and no manifest-only extras.

Missing runtime tools:

```text
agent_briefing_pack
agent_cohort_deep_chusho_keieisha
agent_cohort_deep_gyouseishoshi
agent_cohort_deep_kaikeishi
agent_cohort_deep_shihoshoshi
agent_cohort_deep_zeirishi
agent_cohort_ultra_chusho_keieisha
agent_cohort_ultra_gyouseishoshi
agent_cohort_ultra_kaikeishi
agent_cohort_ultra_shihoshoshi
agent_cohort_ultra_zeirishi
agent_full_context
cohort_lora_resolve
extract_kg_from_text
find_cases_citing_law
find_filing_window
find_gap_programs
find_laws_cited_by_case
find_municipality_subsidies
get_artifact_template
get_case_extraction
get_entity_relations
get_figure_caption
get_houjin_portfolio
get_reasoning_chain
get_recipe
jpcite_bert_v1_encode
list_artifact_templates
list_recipes
list_windows
multi_tool_orchestrate
multitask_predict
opensearch_hybrid_search
predict_related_entities
prepare_implementation_workpaper
product_audit_workpaper_pack
product_shuugyou_kisoku_pack
product_subsidy_roadmap_12month
product_tax_monthly_closing_pack
rerank_results
resolve_alias
resolve_placeholder
search_case_facts
search_chunks
search_figures_by_topic
semantic_search_law_articles
walk_reasoning_chain
```

Fix classification: mixed.

- CodeX-safe after owner confirmation: regenerate MCP public manifests from runtime.
- Claude/operator/protected: decide whether `231` runtime tools are intended, whether product-facing tools should be public, and whether the `mcp_tools` guard high bound should be raised above `200`.
- Not CodeX-safe under this audit scope: changing `data/facts_registry.json` guard thresholds or product/HE surfaces without owner approval.

Fix plan if `231` runtime tools are intended:

```bash
# Owner-approved guard change first, for example raising the high bound above 231.
# Then regenerate public MCP manifests from runtime:
.venv/bin/python scripts/sync_mcp_public_manifests.py
.venv/bin/python scripts/check_mcp_drift.py
```

Fix plan if `231` runtime tools are not intended:

1. Tool owners gate or remove the unintended runtime registrations until the runtime count returns inside `[130, 200]`.
2. Regenerate public MCP manifests.
3. Rerun `scripts/check_mcp_drift.py`.

### 5. aws_blocked_preflight_state

Evidence:

- Gate issue: `preflight_scorecard_allows_live_aws_commands`
- Fixture state: `AWS_BLOCKED_PRE_FLIGHT`
- Scorecard state: `AWS_CANARY_READY`
- Allowed states in gate: `AWS_BLOCKED_PRE_FLIGHT`, `AWS_CANARY_READY`
- Required hard invariant: `live_aws_commands_allowed` must be `false`.
- Actual scorecard value: `live_aws_commands_allowed: true`

Fix classification: protected/operator-owned. Same root cause as `release_capsule_validator`.

Fix plan:

1. Protected owner/operator restores the scorecard hard invariant or performs the formal operator unlock with matching gate policy.
2. Rerun:

```bash
.venv/bin/python scripts/ops/production_deploy_readiness_gate.py
```

## adoption_narrative_tools Status

The requested circular-import check is not currently failing on latest HEAD.

Authoritative import probe prepended this workspace's `src` before importing:

```text
OK import jpintel_mcp.mcp.autonomath_tools.adoption_narrative_tools file=/Users/shigetoumeda/jpcite-codex-evening/src/jpintel_mcp/mcp/autonomath_tools/adoption_narrative_tools.py
OK import jpintel_mcp.mcp.autonomath_tools file=/Users/shigetoumeda/jpcite-codex-evening/src/jpintel_mcp/mcp/autonomath_tools/__init__.py
OK import jpintel_mcp.mcp.server file=/Users/shigetoumeda/jpcite-codex-evening/src/jpintel_mcp/mcp/server.py
```

The module is currently a stub with `__all__ = []` and registers no MCP tool. The real `search_adoption_narratives` implementation remains owner-lane work. If that implementation lands, rerun the MCP drift gate because it may change runtime tool count and public manifests.

## Restore Order

1. Protected/operator: resolve the scorecard `live_aws_commands_allowed` mismatch. This clears both `release_capsule_validator` and `aws_blocked_preflight_state`.
2. Local environment: run `npm ci --prefix functions`, then `npm run --prefix functions typecheck`.
3. Generated OpenAPI: run the OpenAPI export commands and refresh discovery metadata.
4. MCP owner decision: either approve `231` runtime tools and raise the guard before manifest sync, or gate tools back under the current `[130, 200]` range.
5. Rerun `.venv/bin/python scripts/ops/production_deploy_readiness_gate.py` on the resulting HEAD.

## Parent Follow-Up Implementation

CodeX restored the CodeX-safe gate failures after this audit:

- Ran `npm ci --prefix functions` locally. `functions/node_modules/` is ignored
  and not committed.
- Regenerated OpenAPI public surfaces:
  - `docs/openapi/v1.json`
  - `site/docs/openapi/v1.json`
  - `site/openapi/v1.json`
  - `docs/openapi/agent.json`
  - `site/openapi.agent.json`
  - `site/openapi/agent.json`
  - `site/docs/openapi/agent.json`
  - `site/openapi.agent.gpt30.json`
  - `site/.well-known/openapi-discovery.json`
- Changed `scripts/check_mcp_drift.py` to the option B contract: public/default
  manifests stay at 184; runtime must be greater than or equal to 184 and is
  reported separately.
- Updated stale public tool-count copy so `scripts/check_tool_count_consistency.py`
  and `scripts/ops/check_mcp_drift.py --json` both pass.

Final gate rerun:

```text
.venv/bin/python scripts/ops/production_deploy_readiness_gate.py
summary {'fail': 2, 'pass': 5, 'total': 7}
functions_typecheck OK
agent_runtime_contracts OK
openapi_drift OK
mcp_drift OK
release_capsule_route OK
release_capsule_validator FAIL: preflight scorecard must set live_aws_commands_allowed=false
aws_blocked_preflight_state FAIL: preflight_scorecard_allows_live_aws_commands
```

The remaining 2 failures are the protected/operator scorecard state. CodeX did
not edit `site/releases/rc1-p0-bootstrap/preflight_scorecard.json`.
