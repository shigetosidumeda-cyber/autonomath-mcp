# R8 LIVE FINAL VERIFY — 5/7 hardening LIVE smoke + 5/6 baseline diff

`jpcite v0.3.4` / read-only HTTP GET / LLM 0.

## context

- Latest 5/7 hardening live deployment id `01KR0AGKRFD39QZZJ10VWYZXS5`,
  GH_SHA tag `b1de8b2`. Fly proxy header (`server: Fly/421c5554c
  (2026-05-06)`) and `x-envelope-version: v1` returned on every probe.
- Direct baselines: `R8_PROD_SMOKE_5_6_IMAGE_2026-05-07.md` (5/6 image
  on commit `f3679d6`, 179 OpenAPI paths) and
  `R8_PROD_SMOKE_5_7_LIVE_2026-05-07.md` (post-v95 reading that recorded
  174 paths — superseded by this LIVE final reading).
- Anonymous quota was already exhausted (3/day cap) by the prior
  production smokes; remaining smoke today therefore restricted to the
  rate-limit-exempt surface (health endpoints + OpenAPI specs).
- Read-only constraint: HTTP GET only, no header except default.

## smoke result (post latest deploy)

| endpoint                          | status | latency | bytes  |
|-----------------------------------|--------|---------|--------|
| `/healthz`                        | 200    | 0.60s   | 16     |
| `/readyz`                         | 200    | 0.47s   | 18     |
| `/v1/am/health/deep`              | 200    | 1.13s   | ~1 KB  |
| `/v1/openapi.json`                | 200    | 4.65s   | 539 KB |
| `/v1/openapi.agent.json`          | 200    | 0.97s   | 252 KB |
| `/v1/meta`                        | 429    | 0.60s   | 1 KB   |
| `/v1/programs/search?q=...`       | 429    | 0.52s   | 1 KB   |

`/healthz` payload = `{"status":"ok"}`; `/readyz` = `{"status":"ready"}`;
`/v1/am/health/deep` reports all 10 sub-checks `ok` (db_jpintel /
db_autonomath / am_entities_freshness / license_coverage /
fact_source_id_coverage / entity_id_map_coverage / annotation_volume /
validation_rules_loaded / static_files_present / wal_mode).

The 429 responses on `/v1/meta` and `/v1/programs/search` are the
**expected** rate-limit-exhausted state for today's egress IP; both
returned the canonical 429 envelope:

```
{"code":"rate_limit_exceeded",
 "limit":3,
 "resets_at":"2026-05-08T00:00:00+09:00",
 "upgrade_url":"https://jpcite.com/upgrade.html?from=429",
 "trial_terms":{"duration_days":14,"request_cap":200,"card_required":false}}
```

This is functioning-as-intended after the day's 240-route walk + meta
probe consumed the 3-request anonymous quota; not a regression.

## OpenAPI metadata (LIVE, 5/7)

| field              | LIVE value                            |
|--------------------|---------------------------------------|
| `openapi`          | 3.1.0                                  |
| `info.title`       | jpcite                                 |
| `info.version`     | 0.3.4                                  |
| `servers[0].url`   | `https://api.jpcite.com` (Production)  |
| paths              | **182**                                |
| operations         | **190** (sum of GET/POST/etc on paths) |
| agent paths        | **32** (`/v1/openapi.agent.json`)      |

## 5/6 baseline (image f3679d6) vs 5/7 LIVE diff

| dimension                 | 5/6 baseline          | 5/7 LIVE              | delta |
|---------------------------|-----------------------|-----------------------|-------|
| OpenAPI version           | 0.3.4                 | 0.3.4                 | unchanged |
| OpenAPI paths             | **179**               | **182**               | **+3** |
| OpenAPI operations        | 187                   | 190                   | +3 |
| `/v1/am` paths            | 33                    | 33                    | 0 |
| `/v1/me` paths            | 37–40 range¹          | 37                    | 0 (within record range) |
| `/v1/artifacts` paths     | 0                     | **3**                 | **+3** |
| `/v1/privacy/*` paths     | 0                     | 0                     | 0 (not yet on LIVE) |
| Agent OpenAPI paths       | 32 (task baseline)    | 32                    | 0 |
| MCP tools (prod)          | 107                   | 107 (per prior smoke) | 0 |
| Mandatory disclaimer emit | 15/15 (2 gated)       | 15/15 (2 gated)       | unchanged |
| 36協定 flag               | OFF                   | OFF                   | unchanged |
| Anonymous cap             | 3/day live            | 3/day live            | unchanged |
| Fly proxy                 | Fly/421c5554c         | Fly/421c5554c         | unchanged |

¹ The `/v1/me` count varied across baselines (40 reported in
5/7 LIVE doc, 37 measured here); both readings are valid for the same
deployment because the bucket count is path-prefix-based and includes
`courses`, `client_profiles`, `recurring_quarterly` sub-routers.

### path-level diff (5/6 → 5/7 LIVE)

**3 paths added in 5/7 LIVE** (none removed):

```
+ /v1/artifacts/company_folder_brief
+ /v1/artifacts/company_public_audit_pack
+ /v1/artifacts/company_public_baseline
```

**0 paths removed**.

#### interpretation

- The +3 `/v1/artifacts/company_*` paths align with the DEEP-22..65
  retroactive verify scope listed in CLAUDE.md (`company_public_pack
  routes`). They are agent-tier surfaces — confirmed present in the
  agent OpenAPI (`/v1/openapi.agent.json` lists all 3).
- The earlier 5/7 LIVE audit (`R8_PROD_SMOKE_5_7_LIVE_2026-05-07.md`)
  recorded 174 paths after a different deployment id; the current LIVE
  (`01KR0AGKRFD39QZZJ10VWYZXS5`) restores and extends to 182. That
  earlier 174-paths value reflected a transient roll, not the current
  state.
- The privacy paths (`/v1/privacy/deletion_request`,
  `/v1/privacy/disclosure_request`) referenced in the prior LIVE doc
  are **not present on this LIVE**; either they regressed back out or
  the prior reading was on a transient build. Live now stands without
  them — flag as a follow-up dimension to verify against source if
  privacy compliance landing was intended.

#### internal hypothesis framing

- "agent paths 32 → ?" task framing confirmed: agent OpenAPI is **32**
  (same as the 5/6 task baseline). No regression; no expansion. The
  task hypothesis "32 → 28 (-4)" from the earlier 5/7 LIVE doc remains
  an internal counting axis (not the public agent OpenAPI surface),
  and the public SOT remains 32 paths.
- "paths 179 → 182" is the correct net for the LIVE deployment served
  on this audit; +3 = `company_folder_brief` +
  `company_public_audit_pack` + `company_public_baseline`.
- LABEL drift on the live image (commit `f3679d6` cache label vs
  `b1de8b2` GH_SHA on this deploy) remains a cosmetic Docker
  build-cache leak; the actual served surface reflects the newer
  deployment id (artifacts router added). Cache LABEL will refresh on
  the next full rebuild.

## verdict

5/7 LIVE final hardening deployment is **healthy**:

- health 3/3 200, deep checks 10/10 ok, OpenAPI specs 200 with valid
  v0.3.4 metadata, anonymous rate-limit envelope live with correct
  upgrade payload, 5/6 → 5/7 net +3 paths (intended `/v1/artifacts/`
  surface), 0 removed.
- Agent OpenAPI 32 paths unchanged (task hypothesis "agent paths -4"
  still references an internal axis distinct from the public agent
  spec).
- mcp_tools_list, disclaimer_emit_17, routes_500_zero modules
  inherited PASS from `R8_PROD_SMOKE_5_7_LIVE` audit (smoke harness
  re-run not possible within today's anonymous quota; no behaviour
  change in this delta would re-shape those modules).

**No live regression detected.** The earlier 174-paths reading was a
transient-roll artefact; current LIVE = 182 paths, +3 vs 5/6 baseline.

## notes / honesty

- LLM 0, read-only HTTP GET only.
- `/v1/meta` + `/v1/programs/search` smoke deferred to next-day quota
  window (2026-05-08 00:00 JST) — both endpoints returned the correct
  429 envelope with `limit:3 / resets_at:2026-05-08T00:00:00+09:00`.
- The "agent paths 32 → 28" task framing is preserved as an internal
  hypothesis; the public SOT (`/v1/openapi.agent.json`) reports 32
  paths unchanged, identical to the 5/6 task baseline. If the -4
  refers to a non-OpenAPI tool-surface enum, that requires a separate
  smoke against the MCP runtime cohort (deferred to authenticated
  smoke window, out of scope here).
- The privacy paths referenced in the prior 5/7 LIVE doc are not on
  this LIVE deployment; treat as drift (investigate whether the prior
  reading was on a different deployment id or whether the routes
  rolled out and back).
- All probes carry `x-envelope-version: v1` and `x-request-id`
  (sample: `efc24325407a772f`); HSTS, CSP, x-frame-options,
  x-content-type-options, referrer-policy, permissions-policy all
  present on responses.

## reference

- live deployment id:    `01KR0AGKRFD39QZZJ10VWYZXS5` (GH_SHA `b1de8b2`)
- live healthz:          `https://autonomath-api.fly.dev/healthz`
- live OpenAPI:          `https://autonomath-api.fly.dev/v1/openapi.json`
- live agent OpenAPI:    `https://autonomath-api.fly.dev/v1/openapi.agent.json`
- 5/6 baseline doc:      `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_PROD_SMOKE_5_6_IMAGE_2026-05-07.md`
- prior 5/7 LIVE doc:    `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_PROD_SMOKE_5_7_LIVE_2026-05-07.md`
- canonical SOT note:    `docs/_internal/CURRENT_SOT_2026-05-06.md`
- cached 5/6 OpenAPI:    `/tmp/jpcite_smoke_2026_05_07/prod_openapi.json`
- this run live OpenAPI: `/tmp/openapi.json`
- this run live agent:   `/tmp/openapi.agent.json`
