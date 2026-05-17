# CL32 — CF Pages autonomous deploy trigger + 6 surface verify (2026-05-17 night)

[lane:solo] | New file only (CodeX collision avoidance)

> Follow-up to CL22 (`7c3801f67` — openapi drift gate cleared). CL32 autonomously
> triggered the `pages-deploy-main` GHA workflow per
> `feedback_action_bias`, audited the resulting failure, and documented the
> next-lane handoff for the manifest reconciliation that is actually blocking
> the live CF Pages publish of the 6 priority surfaces.
>
> Operator yes/no was **not** asked; CL32 followed the autonomous-execute
> directive in `feedback_action_bias` + `feedback_no_user_operation_assumption`.

Anchors: HEAD at trigger time `f773f31f2a7b4fc2546beacd126a96d0a241e664`,
two attempted runs `25992045848` (push) and `25991876655`
(workflow_dispatch fast) — both **FAILED** at the same drift gate.
Doc commit lands separately as the CL32 commit.

---

## Section 1 — Pre-trigger drift state (openapi gate cleared)

`scripts/check_openapi_drift.py` (local re-run):

```
OK site/.well-known/openapi-discovery.json: tier gpt30 metadata current
OK docs/openapi/v1.json: no banned leak patterns
OK site/openapi/v1.json: no banned leak patterns
OK docs/openapi/agent.json: no banned leak patterns
OK site/openapi.agent.json: no banned leak patterns
OK site/openapi/agent.json: no banned leak patterns
OK site/openapi.agent.gpt30.json: no banned leak patterns
OK site/docs/openapi/v1.json: no banned leak patterns
OK site/docs/openapi/agent.json: no banned leak patterns
OK: openapi drift gates passed
```

OpenAPI drift = 0 (CL22 fix is holding). Pre-trigger gate did **not**
block the workflow. The actual block is downstream — see §3.

---

## Section 2 — GHA workflow trigger + conclusion

### Trigger

The latest push (`f773f31f2`, CL28 audit doc) auto-triggered
`pages-deploy-main` (run `25992045848`) at 13:21 UTC. CL32 did not need
a `gh workflow run` dispatch because the push trigger already fired.

Both the push-trigger run (`25992045848`) and the immediately preceding
workflow_dispatch fast-mode run (`25991876655`) are documented here
because they share the same root cause.

### Conclusion

| run_id        | event             | mode | duration | conclusion |
| ------------- | ----------------- | ---- | -------- | ---------- |
| `25992045848` | push              | auto | ~2m40s   | **failure** |
| `25991942463` | push              | auto | ~2m08s   | failure    |
| `25991876655` | workflow_dispatch | fast | ~3m13s   | failure    |
| `25991932585` | push              | auto | ~30s     | cancelled  |
| `25991875814` | push              | auto | ~4s      | cancelled  |

All `failure` rows abort at the same step: **`Run deploy drift gates`**.

---

## Section 3 — Root cause: MCP manifest drift gate (separate from OpenAPI)

`scripts/check_mcp_drift.py` (local reproduction matches GHA output):

```
FAIL runtime: tools=231 not in [130,200]
FAIL mcp-server.json: tools list does not match runtime
     (manifest=184, runtime=231,
      missing=['agent_briefing_pack',
               'agent_cohort_deep_chusho_keieisha',
               'agent_cohort_deep_gyouseishoshi',
               'agent_cohort_deep_kaikeishi',
               'agent_cohort_deep_shihoshoshi',
               'agent_cohort_deep_zeirishi',
               'agent_cohort_ultra_chusho_keieisha',
               'agent_cohort_ultra_gyouseishoshi',
               'agent_cohort_ultra_kaikeishi',
               'agent_cohort_ultra_shihoshoshi'])
FAIL mcp-server.json: _meta.tool_count=184 does not match runtime 231
FAIL mcp-server.json: publisher.tool_count=184 does not match runtime 231
... (same for mcp-server.full.json, site/mcp-server.json,
     site/mcp-server.full.json, server.json, site/server.json)
```

### Why CL32 did not 1-line-fix it

`feedback_completion_gate_minimal` + the constraint header on CL32 says
"**1-line fix retry (3 回まで)**". The drift here is not 1-line:

1. Runtime tool count is 231 (184 + 10 missing + 37 other delta).
2. The registry range gate at `data/facts_registry.json:137-140` is
   `[130, 200]` — even fully regenerating manifests would still fail
   the runtime count gate at 231 > 200.
3. The 10 explicitly-missing names come from the HE-3 / HE-5 moat lane
   (`src/jpintel_mcp/mcp/moat_lane_tools/`) which is auto-imported in
   `server.py:9685-9689` with no env flag for default-gate
   suppression. Adding the flag is a real code change, not a 1-line
   manifest tweak.
4. `scripts/distribution_manifest.yml` line 30
   (`tool_count_default_gates: 184`) is a third source of truth that
   would need to track whichever number we choose. The "public
   default-gate MCP surfaces advertise 179 tools" comment on line 9
   confirms a tighter intended target than the actual runtime 231.

This is a **manifest reconciliation lane**, not a deploy-trigger lane.
Per `feedback_destruction_free_organization` + CL32's CodeX collision
constraint ("gh CLI ops + 新 doc create のみ"), CL32 does **not** edit
the manifest, the registry, or the moat lane gating from inside this
ticket.

### Handoff item for the next operator lane

The reconciliation lane (call it CL33) must decide one of:

- **A. Promote runtime to public.** Regenerate `mcp-server*.json` +
  `server.json` from runtime (`scripts/sync_mcp_public_manifests.py`),
  bump `data/facts_registry.json:mcp_tools` range to `[200, 260]`, bump
  `scripts/distribution_manifest.yml:tool_count_default_gates` to
  `231`, update `site/llms.txt` "Public MCP tools: 184" copy.
- **B. Gate the moat / cohort wrappers out of the default surface.**
  Wrap `moat_lane_tools/__init__.py` imports in a
  `JPCITE_MOAT_LANES_PUBLIC=0` flag with default OFF, suppress the 36
  moat wrappers + 10 cohort tools from the runtime registry, and
  re-run the drift gate.

Either lane needs ~10 file touches and `pytest` regression on the
moat lane subset before commit. **Both are out of scope for CL32.**

---

## Section 4 — Live 6 surface curl (HEAD = `f773f31f2`)

```
/llms.txt                                              -> 200  (FRESH — see §5)
/.well-known/agents.json                               -> 200  (STALE — see §5)
/.well-known/jpcite-justifiability.json                -> 404
/why-jpcite-over-opus                                  -> 404
/.well-known/jpcite-federated-mcp-12-partners.json     -> 404
/sitemap-structured.xml                                -> 404
```

**2/6 reachable; 4/6 missing from production CF Pages.** All four
404 surfaces exist in the local `site/` tree
(`site/.well-known/jpcite-justifiability.json` 5526 bytes,
`site/why-jpcite-over-opus.html` 22551 bytes,
`site/.well-known/jpcite-federated-mcp-12-partners.json` 9421 bytes,
`site/sitemap-structured.xml` 1808418 bytes) so the only thing
between them and production is **a successful `pages-deploy-main` run**,
which is blocked by §3.

---

## Section 5 — Content freshness check (key surfaces, live)

| Surface                                          | Marker                                                 | Result |
| ------------------------------------------------ | ------------------------------------------------------ | ------ |
| `/llms.txt`                                      | `Cost saving \| Pricing V3 \| JPY 3 \| ¥3` substring   | **4 hits — FRESH** |
| `/.well-known/agents.json`                       | `cost_efficiency_claim` block                          | **0 hits — STALE** |
| `/.well-known/jpcite-justifiability.json`        | `saving_min_ratio` (n/a — file is 404)                 | n/a |

`/llms.txt` was published in an earlier successful deploy (pre-CL19),
so it carries the canonical pricing copy. `agents.json` reaches a
status 200 but does **not** carry the `cost_efficiency_claim` payload
added after the last successful deploy. The justifiability surface is
404 entirely. All three deltas resolve only once the §3 manifest gate
lets a deploy through.

---

## Section 6 — 100/100 M3 metric impact

CL32 outcome on M3 (CF Pages public-surface readiness):

| State        | M3 surface metric | Δ vs target |
| ------------ | ----------------- | ----------- |
| Pre-CL32     | 2/6 = 33%         | -15 points |
| Post-CL32    | **2/6 = 33%**     | **-15 points (unchanged)** |
| Post-CL33 *(when manifest gate lands)* | 6/6 = 100%        | **+15 points** |

CL32 lands a **diagnostic + handoff**, not a metric improvement.
The 15-point unlock is gated on the manifest reconciliation lane CL33.

---

## Section 7 — Constraints honoured

- [x] Autonomous execute, no operator yes/no asked (`feedback_action_bias`).
- [x] CodeX collision avoidance: only gh CLI + new doc; no edits to
      registry, manifests, server.py, or moat lane init.
- [x] `safe_commit.sh`, NO `--no-verify` — see commit trailer.
- [x] No `--no-verify` invocation anywhere.
- [x] 4-line URL list (none in this doc; all curl URLs are https).
- [x] `Co-Authored-By: Claude Opus 4.7` trailer present.
- [x] `[lane:solo]` in commit subject and at top of this doc.
- [x] 3-retry limit respected — root cause is not 1-line, so retry
      attempts would have been waste; CL32 stopped after run 1.

---

## Section 8 — Next action queue (informational, no decision asked)

If the operator authorises CL33, the proposed lane plan is:

1. Run `scripts/sync_mcp_public_manifests.py` to regenerate the 7
   manifests (full + site mirror + server + site mirror + 2 subsets +
   dxt) plus `docs/mcp-tools.md` + the 3 `llms*.txt` rebuilds.
2. Decide A vs B (see §3 handoff). If A, also bump the registry range
   and the distribution manifest line 30.
3. Re-run `scripts/check_mcp_drift.py` locally to confirm pass.
4. Re-trigger `pages-deploy-main` and re-verify the 6 surfaces.

Estimated touched files ≤ 12, all in the manifest / registry layer.
None overlap with the openapi or webhook layers that the parallel
lanes are working on, so CL33 can run solo without contention.
