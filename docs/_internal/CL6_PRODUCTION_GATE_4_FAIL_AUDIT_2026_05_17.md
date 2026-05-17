# CL6 — Production Gate 4/7 Fail Root-Cause Audit (READ-ONLY)

- Date: 2026-05-17
- Author: Claude Opus 4.7
- Lane: lane:solo
- Scope: read-only audit of `scripts/ops/production_deploy_readiness_gate.py` result `3/7 PASS, 4/7 FAIL`. Suggested fixes are documented here; **no fix is applied in this commit**.
- Gate runner: `.venv/bin/python scripts/ops/production_deploy_readiness_gate.py`
- Capsule: `rc1-p0-bootstrap-2026-05-15`

## Pass / Fail summary

| # | Check | Result | Exit / Issue |
|---|-------|--------|--------------|
| 1 | functions_typecheck                       | PASS | exit 0 |
| 2 | release_capsule_validator                 | FAIL | exit 1 — `live_aws_commands_allowed=true` |
| 3 | agent_runtime_contracts                   | PASS | exit 0 |
| 4 | openapi_drift                             | FAIL | exit 1 — 4 stale exports + 4 discovery hash mismatch |
| 5 | mcp_drift                                 | FAIL | exit 1 — runtime tools=231 vs manifests=184 (10 missing + count drift) |
| 6 | release_capsule_route                     | PASS | (in-process) |
| 7 | aws_blocked_preflight_state               | FAIL | `preflight_scorecard_allows_live_aws_commands` |

The two AWS-related fails (#2 and #7) share **one underlying signal**: the unlocked scorecard now has `live_aws_commands_allowed: true`. The two drift fails (#4, #5) are independent.

---

## Fail 1 — `release_capsule_validator` (exit 1)

### stderr / tail
```
release capsule validator: failed
- preflight scorecard must set live_aws_commands_allowed=false
```

### Root cause
`scripts/ops/validate_release_capsule.py` line ~1567 calls `_require_false(preflight, "live_aws_commands_allowed", ...)`. The current scorecard
`site/releases/rc1-p0-bootstrap/preflight_scorecard.json` reads:

```json
{
  "state": "AWS_CANARY_READY",
  "live_aws_commands_allowed": true,
  "unlocked_at": "2026-05-17T03:11:48Z",
  "unlock_authority": "operator"
}
```

The validator allows `state` to be either `AWS_BLOCKED_PRE_FLIGHT` **or** `AWS_CANARY_READY` (Stream W concern separation), but treats `live_aws_commands_allowed=true` as a hard invariant violation, even though operator unlock (Stream I) is the documented way to flip it. The production deploy gate therefore refuses to greenlight any deploy while the operator unlock is still effective.

### Suggested fix (NOT APPLIED HERE)
Two policy options — operator decides:

- **Option A — keep invariant.** Re-lock the scorecard: set `live_aws_commands_allowed=false` (and either keep `state=AWS_CANARY_READY` or revert to `AWS_BLOCKED_PRE_FLIGHT`) **after** the AWS canary run completes. This is the simplest path and matches the original Stream W contract: "operator unlock opens AWS commands during the burn window only; production deploy gate stays closed during that window."
- **Option B — split AWS-burn-mode from production-deploy-mode.** Introduce a second flag (e.g. `production_deploy_allowed`) that the production gate consults instead of `live_aws_commands_allowed`. Update `validate_release_capsule.py:1567` and `production_deploy_readiness_gate.py:280` to use the new flag. Larger refactor; touches both validator scripts and the scorecard schema.

- **Effort:** Option A = small (1-line JSON edit + re-sign). Option B = medium (schema bump + 2 validator edits + downstream call sites).
- **Owner:** CodeX (Option A is a single JSON write; Option B is a schema refactor either side can carry).

---

## Fail 2 — `openapi_drift` (exit 1)

### stderr / tail
```
FAIL site/openapi/v1.json is stale; run the exporter and commit the result
FAIL site/openapi.agent.json is stale; run the exporter and commit the result
FAIL site/openapi/agent.json is stale; run the exporter and commit the result
FAIL site/openapi.agent.gpt30.json is stale; run the exporter and commit the result
FAIL site/.well-known/openapi-discovery.json: tier agent size_bytes=547936 does not match site/openapi.agent.json (560505)
FAIL site/.well-known/openapi-discovery.json: tier agent sha256_prefix='9a0ab17dfe015027' does not match site/openapi.agent.json ('0dae3d387feb212c')
FAIL site/.well-known/openapi-discovery.json: tier gpt30 size_bytes=384394 does not match site/openapi.agent.gpt30.json (380898)
FAIL site/.well-known/openapi-discovery.json: tier gpt30 sha256_prefix='b0f1303e6a9bcf3f' does not match site/openapi.agent.gpt30.json ('2029f23507d361d7')
```

### Root cause
1. **Stale exports.** The committed `site/openapi/v1.json`, `site/openapi.agent.json`, `site/openapi/agent.json`, and `site/openapi.agent.gpt30.json` differ from the freshly-regenerated exports. The diff in the failure tail shows two classes of change:
   - **Encoding drift.** Committed files contain literal CJK glyphs (e.g. `税理士法人`, `条文 lookup`); regenerated exports use `\uXXXX` escape form. The exporter is now writing `ensure_ascii=True`-style output, but the committed snapshots were written when `ensure_ascii=False` was in effect (or vice-versa).
   - **Content drift.** Schema descriptions like `BidOut`, `AttributionBlock` were edited upstream after the last commit-time export.

2. **Discovery hash mismatch.** `site/.well-known/openapi-discovery.json` records `size_bytes` and `sha256_prefix` for the `agent` and `gpt30` tiers. Those bytes/hashes are computed against the committed files, but the regenerated files now produce different bytes (because of the stale-exports drift above), so the discovery hashes are inconsistent with the on-disk artifacts.

### Suggested fix (NOT APPLIED HERE)
1. Re-run the OpenAPI exporter (likely `python scripts/ops/build_openapi.py` or similar; check `scripts/ops/` and `Makefile` for the exporter target — the drift script literally regenerates into `/tmp/jpcite-openapi-drift-*/`).
2. Commit the regenerated `site/openapi/v1.json`, `site/openapi.agent.json`, `site/openapi/agent.json`, `site/openapi.agent.gpt30.json` plus `site/docs/openapi/v1.json`, `site/docs/openapi/agent.json` mirrors.
3. Re-run the discovery refresh (likely `scripts/ops/refresh_openapi_discovery.py` or equivalent — `check_openapi_drift.py` knows the canonical computation) to rewrite `size_bytes` / `sha256_prefix` in `site/.well-known/openapi-discovery.json`.
4. **Lock down the JSON serializer** so `ensure_ascii` does not flip between regenerations (root cause of the literal-vs-escaped CJK mismatch).

- **Effort:** medium. Plain artifact regeneration is mechanical, but the `ensure_ascii` flag drift needs to be tracked down to the exporter source so the same encoding is reproducible.
- **Owner:** CodeX (export pipeline is on the OpenAPI surface CodeX has been driving).

---

## Fail 3 — `mcp_drift` (exit 1)

### stderr / tail
```
FAIL runtime: tools=231 not in [130,200]
FAIL mcp-server.json: tools list does not match runtime (manifest=184, runtime=231,
  missing=['agent_briefing_pack',
           'agent_cohort_deep_chusho_keieisha',
           'agent_cohort_deep_gyouseishoshi',
           'agent_cohort_deep_kaikeishi',
           'agent_cohort_deep_shihoshoshi',
           'agent_cohort_deep_zeirishi',
           'agent_cohort_ultra_chusho_keieisha',
           'agent_cohort_ultra_gyouseishoshi',
           'agent_cohort_ultra_kaikeishi',
           'agent_cohort_ultra_shihoshoshi'],
  extra=[])
FAIL mcp-server.json: _meta.tool_count=184 does not match runtime 231
FAIL mcp-server.full.json: ...same drift...
FAIL site/mcp-server.json / site/mcp-server.full.json: ...same drift...
FAIL server.json / site/server.json: _meta.tool_count=184 does not match runtime 231
```

(The "missing" list shown is truncated; runtime exposes 231 tools and the manifests carry 184 — a 47-tool delta.)

### Root cause
The MCP runtime tool registry has expanded from **184 → 231** tools (likely via the Wave 89-94 catalog growth — M&A/talent/brand/safety/real_estate/insurance plus `agent_briefing_pack` and 10 cohort tools listed above), but the published manifests were not re-emitted:

- `mcp-server.json`, `mcp-server.full.json`, `site/mcp-server.json`, `site/mcp-server.full.json` still carry the 184-tool snapshot, with stale `_meta.tool_count` and `publisher.tool_count` fields.
- `server.json` / `site/server.json` carry the same stale count.

Additionally, the drift script enforces a hard range `tools in [130,200]` on the runtime count. The runtime 231 now exceeds the upper bound, so the **range itself needs to be lifted** (or the cohort/briefing tools need to be gated out of the public manifest by category).

### Suggested fix (NOT APPLIED HERE)
1. Re-emit `mcp-server.json` / `mcp-server.full.json` (and the `site/` mirrors) from runtime. The drift script knows the canonical generation path; look for the equivalent of `scripts/ops/build_mcp_server_manifest.py` or `make mcp-manifest`.
2. Update `_meta.tool_count` and `publisher.tool_count` to 231 on all manifests (`mcp-server.json`, `mcp-server.full.json`, `site/server.json`, `server.json`).
3. Bump the upper bound in `check_mcp_drift.py` from 200 to a new policy ceiling (suggest 250 to give headroom for Wave 95-100), or split the runtime range from the manifest range.
4. Confirm with operator whether the 10 `agent_cohort_*` tools and `agent_briefing_pack` belong on the public surface or should be gated `core`/`composition`-only.

- **Effort:** medium. Tool list re-emission is mechanical, but the upper-bound bump and the public-vs-private gating decision need a policy call.
- **Owner:** CodeX (tool registry generator is on the CodeX side per AGENTS lane assignment; Claude can review the public/private gating decision before commit).

---

## Fail 4 — `aws_blocked_preflight_state` (`preflight_scorecard_allows_live_aws_commands`)

### Issue
`production_deploy_readiness_gate.py:280` enforces:

```python
if scorecard.get("live_aws_commands_allowed") is not False:
    issues.append("preflight_scorecard_allows_live_aws_commands")
```

The scorecard currently has `live_aws_commands_allowed: true` because the operator unlock at `2026-05-17T03:11:48Z` flipped it for the AWS canary burn.

### Root cause
**Same as Fail 1.** This is the same underlying signal — the production deploy gate (Stream W concern separation comment in lines 26-31 of the gate script) explicitly documents that:

> ``live_aws_commands_allowed`` MUST remain False until the operator unlock (Stream I) — that flip is what truly opens deploy risk.

The gate is doing exactly what it advertises: refusing to greenlight a Fly production deploy while AWS-live commands are unlocked.

### Suggested fix (NOT APPLIED HERE)
Two paths — same shape as Fail 1:

- **Option A — Re-lock after canary.** Operationally separate the AWS canary burn from a Fly production deploy. Re-lock `live_aws_commands_allowed=false` once the canary completes (or before the deploy). This is a 1-line scorecard edit. **Recommended.**
- **Option B — Split flags.** Decouple `live_aws_commands_allowed` from `production_deploy_allowed`. Modify `production_deploy_readiness_gate.py` line 280 and `validate_release_capsule.py` line 1567 to read `production_deploy_allowed` instead. Larger refactor.

- **Effort:** small (Option A) / medium (Option B).
- **Owner:** CodeX for Option A (JSON edit + scorecard re-sign). Claude can carry Option B as a small contract refactor if the operator asks to split the flags.

---

## Aggregated fix plan

| Fail | Effort | Owner | Required preconditions |
|------|--------|-------|------------------------|
| release_capsule_validator     | small  | CodeX | Operator decides Option A (re-lock) vs Option B (split flag). Recommend A. |
| openapi_drift                 | medium | CodeX | Identify exporter target; commit regenerated artifacts; refresh discovery hashes; pin `ensure_ascii` policy. |
| mcp_drift                     | medium | CodeX | Re-emit 6 manifests at runtime tool count = 231; bump `check_mcp_drift.py` upper bound; operator decides on public/private gating for cohort tools. |
| aws_blocked_preflight_state   | small  | CodeX | Same as Fail 1 — re-lock once canary finishes (Option A) or split flag (Option B). |

**Single-shot resolution path (recommended sequence):**
1. CodeX: re-lock `preflight_scorecard.json` (fixes Fail 1 + Fail 4 in one JSON edit). Run validator + production gate.
2. CodeX: regenerate OpenAPI exports + refresh discovery hashes (fixes Fail 2).
3. CodeX: re-emit MCP manifests + bump drift range (fixes Fail 3).
4. Re-run `scripts/ops/production_deploy_readiness_gate.py`; expect 7/7 PASS.

---

## What this audit did NOT do

- Did not modify any artifact (read-only).
- Did not run any AWS / live-deploy command.
- Did not edit the scorecard, manifests, or OpenAPI exports.
- Did not commit any `*.json` file — only this `docs/_internal/CL6_PRODUCTION_GATE_4_FAIL_AUDIT_2026_05_17.md` document.
- Did not push to remote (commit only; push deferred to operator/owner lane per audit scope).

## References

- Gate runner: `scripts/ops/production_deploy_readiness_gate.py`
- Capsule validator: `scripts/ops/validate_release_capsule.py:1557-1579`
- OpenAPI drift: `scripts/check_openapi_drift.py`
- MCP drift: `scripts/check_mcp_drift.py`
- Scorecard: `site/releases/rc1-p0-bootstrap/preflight_scorecard.json`
- Memory: `feedback_aws_canary_hard_stop_5_line_defense.md`, `project_jpcite_canary_phase_9_dryrun.md`, `project_jpcite_wave60_94_complete.md`
