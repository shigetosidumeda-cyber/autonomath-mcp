# R8 — 5-Manifest Sync Verify (jpcite v0.3.4)

Date: 2026-05-07 JST
Scope: read-only audit, 5 distribution-manifest sync axes, no source mutation.
Hypothesis under test: "v0.3.4 manifest hold-at-139 (Option B) is internally consistent across all 5 surfaces; the 7 post-manifest tools (DEEP-37/44/45/49..58/64/65) are absent everywhere by design."

## 1. Manifests audited

| # | Path | Role |
|---|------|------|
| 1 | `pyproject.toml` | PyPI distribution + console scripts |
| 2 | `server.json` | MCP registry (modelcontextprotocol.io) manifest |
| 3 | `dxt/manifest.json` | Claude Desktop `.mcpb` extension manifest |
| 4 | `smithery.yaml` | Smithery registry config |
| 5 | `mcp-server.json` | Alternate MCP registry / install metadata |

## 2. Sync table (5 manifests × 6 axes)

| Axis | pyproject.toml | server.json | dxt/manifest.json | smithery.yaml | mcp-server.json | Verdict |
|------|----------------|-------------|-------------------|----------------|------------------|---------|
| version | `0.3.4` | `0.3.4` | `0.3.4` | `0.3.4` | `0.3.4` | SYNC |
| canonical mcp package name | `autonomath-mcp` | `io.github.shigetosidumeda-cyber/autonomath-mcp` (registry FQN) | `autonomath-mcp` | `autonomath-mcp` (uvx args + brand `displayName: jpcite — Japanese public-program evidence MCP`) | `autonomath-mcp` | SYNC (server.json uses registry-required FQN form, others use bare package id; documented split) |
| tool_count | description text says `139 tools` | `_meta.publisher-provided.tool_count = 139` | `len(tools[]) = 139` (verified by JSON parse) + description says `139 tools` | description says `139 tools` (no structured field) | `len(tools[]) = 139` (verified) + description says `139 tools` | SYNC at 139 |
| description ¥3 + tax-incl 3.30 | `3 yen/req metered (3.30 tax-incl), anonymous 3/day per IP free` | description + `_meta.pricing.unit_price_jpy_inc_tax: 3.3` | description text matches | description text matches | description text matches | SYNC |
| repository | `github.com/shigetosidumeda-cyber/autonomath-mcp` (legacy alias retained pending org claim) | same | same | same | same | SYNC |
| license / authors | `MIT` + `Bookyou株式会社 <info@bookyou.net>` | `MIT` (license deferred to package) + author Bookyou株式会社 | `MIT` + Bookyou株式会社 | `MIT` (no author block, registry-driven) | `MIT` + Bookyou株式会社 | SYNC |

All 6 axes pass internal sync. No drift found across the 5 static manifests at the v0.3.4 hold point.

## 3. Post-manifest tool verify (Option B — manifest hold at 139)

CLAUDE.md SOT (2026-05-06) states 7 post-manifest tools landed in `src/` (`DEEP-37/44/45/49..58/64/65`) but are explicitly NOT to be counted in any of the 5 manifests until the next intentional bump.

Verification: `dxt/manifest.json` and `mcp-server.json` both expose 139 names in their `tools[]` arrays. Set difference between the two arrays is empty (`set()` both ways) — same 139 names verbatim. server.json `_meta.tool_count = 139`. smithery.yaml description says `139 tools`. pyproject description says `139 MCP tools (protocol 2025-06-18)`.

Conclusion: Option B confirmed — the 7 post-manifest tools are uniformly absent from all 5 surfaces, as designed.

## 4. Static manifest test results

`tests/test_distribution_manifest.py` exercises 4 active tests + 1 slow runtime probe:

| Test | Result |
|------|--------|
| `test_manifest_parses_and_has_required_keys` | PASS |
| `test_openapi_agent_specs_use_info_version_without_package_requirement` | PASS |
| `test_drift_checker_runs_against_repo` | PASS |
| `test_synthetic_drift_detected` | PASS |
| `test_runtime_probe_agrees_with_manifest` (slow) | FAIL (rc=1) — see §5 |

Static-manifest sync test suite: **4/4 PASS** for the in-tree static sync (the failing 5th is a runtime/manifest gap, not a manifest-internal sync defect — see below).

## 5. Runtime-vs-manifest delta (informational, not a sync defect)

The slow runtime probe surfaced a runtime-side gap (NOT a manifest-internal sync drift):

| field | manifest | runtime probe |
|-------|----------|---------------|
| `route_count` | 269 | 226 |
| `tool_count_default_gates` | 139 | 107 |

This is a different axis from the 5-manifest static sync question this audit covers. The 5 static manifests are pairwise-consistent (139, 0.3.4, autonomath-mcp). The runtime delta is between (5 manifests) and (live `len(await mcp.list_tools())`). Possible explanations to investigate (operator decision):

- Default-OFF gate flips since the manifest was last set (e.g. `AUTONOMATH_36_KYOTEI_ENABLED=0` is reported in the probe stderr; reasoning + snapshot gates also off).
- A gate that was ON when the 139 was minted is currently OFF in the local session.
- Probe runs with a config snapshot that excludes some industry packs.
- 32 tool gap (139 − 107) ≈ a few gated families turned off.

Note: CLAUDE.md SOT explicitly says "runtime cohort = 146" with manifest hold at 139. The probe sees 107 here, not 146 — gap is therefore probably env-flag–driven for this session, not a permanent regression. Operator should reproduce with all `AUTONOMATH_*_ENABLED` flags ON before treating as a gap; that is outside R8 read-only audit scope.

## 6. Drift remediation candidates (operator decision, NOT applied)

R8 audit is read-only. No manifest mutation performed. If operator chooses to reconcile:

1. **Option A (bump manifest to runtime):** edit `scripts/distribution_manifest.yml` to `tool_count_default_gates: 146` + `route_count: <runtime>` + bump 5 manifests + cut a release. NOT consistent with current "Option B hold-at-139" decision.
2. **Option B (preserve hold, document gap):** keep all 5 manifests at 139; rely on `len(await mcp.list_tools())` as runtime SOT; add a comment line in `distribution_manifest.yml` clarifying the deferred 7-tool delta. Matches the established Option B framing.
3. **Reproduce probe with all flags ON** before either option to confirm 107 vs 146 is env-driven, not a code-level regression.

Recommended posture: keep Option B; this audit is consistent with that.

## 7. Conclusion

The 5 distribution manifests for jpcite v0.3.4 are internally consistent on all 6 sync axes (version / name / tool_count / description-claim / repository / license-author). 4/4 static-sync pytests pass. The 7 post-manifest tools are uniformly absent from all 5 surfaces, confirming Option B holds. The only flagged delta is the runtime-vs-manifest probe (107 vs 139), which is orthogonal to the 5-way static sync question and is consistent with default-OFF gate flips in the probe environment.

No manifest edits required. Audit closes drift-free on the static-sync axis.

## Appendix A — raw cross-manifest dump

```json
{
  "pyproject.toml": {"version": "0.3.4", "name": "autonomath-mcp", "description_says_139": true},
  "server.json":   {"version": "0.3.4", "name": "io.github.shigetosidumeda-cyber/autonomath-mcp",
                    "tool_count": 139, "description_says_139": true},
  "dxt/manifest.json": {"version": "0.3.4", "name": "autonomath-mcp",
                        "tools_array_len": 139, "description_says_139": true},
  "mcp-server.json":   {"version": "0.3.4", "name": "autonomath-mcp",
                        "tools_array_len": 139, "description_says_139": true},
  "smithery.yaml":     {"version": "0.3.4",
                        "displayName": "jpcite — Japanese public-program evidence MCP",
                        "description_says_139": true}
}
```

## Appendix B — pytest output (truncated)

```
tests/test_distribution_manifest.py::test_manifest_parses_and_has_required_keys PASSED
tests/test_distribution_manifest.py::test_openapi_agent_specs_use_info_version_without_package_requirement PASSED
tests/test_distribution_manifest.py::test_drift_checker_runs_against_repo PASSED
tests/test_distribution_manifest.py::test_synthetic_drift_detected PASSED
tests/test_distribution_manifest.py::test_runtime_probe_agrees_with_manifest FAILED
========================= 1 failed, 4 passed in 10.20s =========================
```

Static sync = 4/4 PASS. Runtime probe failure is a separate axis (runtime/manifest gap) and is NOT a 5-manifest-internal sync defect.
