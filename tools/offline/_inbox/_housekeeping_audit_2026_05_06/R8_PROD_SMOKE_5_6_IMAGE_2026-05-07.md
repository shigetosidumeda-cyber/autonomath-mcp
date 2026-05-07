# R8 PROD SMOKE — 5/6 live image verify (2026-05-07)

`jpcite v0.3.4` / read-only HTTP GET / LLM 0.

## context

- 5/6 deploy was completed locally up to commit `7ee0b08` (HEAD)。
- Fly deploy on 5/7 failed mid-build, so the live image stayed at the
  5/6 build of commit `f3679d6` ("housekeeping: brand drift sweep …")。
- This audit is **only** to verify that the still-running 5/6 image is
  serving traffic correctly — it is not a green-light for a re-deploy。

## summary table

| module               | prod (5/6 image)                | local (HEAD `7ee0b08`)         |
|----------------------|---------------------------------|--------------------------------|
| health_endpoints     | PASS — 3/3 200                  | (not run; live focus)          |
| routes_500_zero      | PASS — 240/240, 5xx=0           | (not run; live focus)          |
| mcp_tools_list       | FAIL gate — 107 vs floor 139    | initial smoke 109; follow-up runtime probe PASS — 146 vs floor 139 |
| disclaimer_emit_17   | PASS — 15/15 (gated_off=2)      | PASS — 17/17 (gated_off=0)     |
| stripe_webhook       | SKIPPED (--skip-stripe)         | SKIPPED                        |

Files of record:

- `/tmp/jpcite_smoke_2026_05_07/prod_smoke.json`     (health + routes + skipped stripe)
- `/tmp/jpcite_smoke_2026_05_07/prod_mcp.json`       (107 tools)
- `/tmp/jpcite_smoke_2026_05_07/prod_disclaimer.json` (15/15)
- `/tmp/jpcite_smoke_2026_05_07/local_mcp.json`      (109 tools, flag ON)
- `/tmp/jpcite_smoke_2026_05_07/local_disclaimer.json` (17/17, flag ON)

## module-by-module findings

### 1. health_endpoints — PASS (3/3)

```
[PASS] health_endpoints        1.59s  3/3 healthy
  /healthz       200
  /readyz        200
  /v1/am/health/deep  200
```

`/v1/am/health/deep` reports all 10 sub-checks `ok` (db_jpintel,
db_autonomath, am_entities_freshness, license_coverage,
fact_source_id_coverage, entity_id_map_coverage, annotation_volume,
validation_rules_loaded, static_files_present, wal_mode)。

### 2. routes_500_zero — PASS (240/240, 5xx=0)

- 240 paths walked, **zero 5xx**。
- Sample status: healthz=200, readyz=200, deep=200, /openapi.json=308 (redirect to /v1/openapi.json), /docs=200。
- /openapi.json (after follow) reports `info.version = 0.3.4`,
  179 `paths` with 187 ops。
- The 178→187 ops drift vs internal note (227) is explained by
  the OpenAPI count being **operations**, not raw routes — the FastAPI
  router has additional non-OpenAPI mounts。

### 3. mcp_tools_list — FAIL gate on prod 5/6 image; initial local smoke env was incomplete

| env  | tools | floor | delta |
|------|-------|-------|-------|
| prod | 107   | 139   | -32   |
| local smoke harness (partial flag ON) | 109 | 139 | -30 |
| local follow-up runtime probe (production-equivalent cohort flags) | 146 | 139 | +7 |

- The still-running prod 5/6 image falls below the manifest floor of 139。
- Follow-up debug corrected the local reading: `.venv/bin/python scripts/probe_runtime_distribution.py`
  sets the production-equivalent MCP cohort flags and reports
  `runtime route_count=226, tool_count=146 satisfies manifest floor=139`。
  Therefore the local HEAD does **not** require lowering the manifest floor; the
  earlier 109 reading came from a smoke command that did not enable the full
  cohort surface。
- Prod is 2 fewer than local because the 36協定 flag is
  `AUTONOMATH_36_KYOTEI_ENABLED=0` in production (see disclaimer
  module: `skipped_gated=[render_36_kyotei_am, get_36_kyotei_metadata_am]`)。
- Sample names (identical heads in both envs):
  `search_programs / get_program / batch_get_programs /
   list_exclusion_rules / check_exclusions / get_meta /
   get_usage_status / enum_values`。
- **Correction to initial hypothesis**: the 139 floor is still valid for local
  HEAD when the production-equivalent cohort flags are enabled。 Do not use this
  smoke result as evidence to lower the manifest。

### 4. disclaimer_emit_17 — PASS in both envs (gating delta is expected)

- prod: 15/15 mandatory emit `_disclaimer`, 2 gated off
  (`render_36_kyotei_am`, `get_36_kyotei_metadata_am`)。
- local (with `AUTONOMATH_36_KYOTEI_ENABLED=1`): 17/17 mandatory,
  0 gated。
- This delta is **by design**: production has 36協定 disabled until
  legal review completes (per template_tool startup banner)。 The
  smoke harness counts a gated tool as "skipped_gated", not a miss,
  so prod still passes its module gate。

### 5. stripe_webhook — SKIPPED

- Skipped via `--skip-stripe` per task constraint (read-only)。

## anonymous rate limit confirm — LIVE

| call                                            | status |
|------------------------------------------------|--------|
| `curl /v1/meta` (no header)                    | 429 with `code=rate_limit_exceeded` |
| `curl -H "X-Api-Key: dev" /v1/meta`            | 429 with same body |

Live response payload (excerpt):

```
{"code":"rate_limit_exceeded",
 "limit":3,
 "resets_at":"2026-05-08T00:00:00+09:00",
 "upgrade_url":"https://jpcite.com/upgrade.html?from=429",
 "trial_terms":{"duration_days":14,"request_cap":200,"card_required":false}}
```

Findings:

- The anonymous 3/day cap is **active** on the live 5/6 image。
- The cap is **already exhausted** for the egress IP used by this
  smoke run (the routes module walked 240 paths)。 This is an expected
  side-effect of the smoke — not a production issue。
- The token literal `dev` is **not whitelisted** in production (also
  hit 429)。 If a stable bypass key is needed for ops smokes it should
  be issued via the standard key flow rather than a hard-coded `dev`
  string。

## prod vs local diff (summary)

| dimension                | prod (5/6)              | local (HEAD)            |
|--------------------------|-------------------------|-------------------------|
| OpenAPI version          | 0.3.4                   | 0.3.4                   |
| OpenAPI ops count        | 187 (179 paths)         | (not walked here)       |
| MCP tools                | 107                     | 146 via runtime probe (109 in partial smoke harness) |
| Disclaimer mandatory     | 15/15 (2 gated)         | 17/17 (0 gated)         |
| 36協定 flag              | OFF                     | ON (test)               |
| Anonymous cap            | 3/day, live             | (not exercised)         |
| Commit served            | `f3679d6` (5/6 housekeeping) | `7ee0b08` (5/7 codex handoff) |

The 5/7 commits not yet served by prod (per `git log` between
`f3679d6..7ee0b08`):

```
7ee0b08  inherit codex handoff: broken-link fix + billing terminology + practitioner-eval static URL
c3b6e57  ruff wider 109→0 + pre-commit 16/16 + 5 manifest sync + fly readiness + site audit + R8 closure
e419f61  bandit 79→0 final + lane solo + 33 verify shells + ruff wider 238→100 + workflow README 82
48a8604  mypy strict 69→0 final + pre-commit 13/16 PASS + bandit 932→79 + R8 INDEX 24 doc
2953db1  mypy strict 172→69 + lint 14→5 + smoke 5/5 ALL GREEN + manifest hold + lane ledger append
```

These 5 commits represent hardening (lint/typing/security) + doc, no
behavioural API changes that would re-shape the prod smoke result。

## verdict

The 5/6 live image is **serving traffic in a healthy state**:

- health 3/3, routes 240/240 5xx=0, disclaimer 15/15 (with documented
  gating), anonymous cap live and returning the correct upgrade
  payload。
- The single open gate on the still-running 5/6 image is the manifest `139`
  floor for `mcp_tools_list`。 Follow-up debug shows local HEAD satisfies this
  floor (`146 >= 139`) when probed with the correct production-equivalent MCP
  cohort flags, so this is a prod-old-image / smoke-env issue, not a reason to
  lower the manifest floor。

No live regression detected by this audit。 Re-deploy can proceed via
the remaining lanes (depot retry / local docker / GHA dispatch) when
the operator chooses。

## notes / honesty

- Smoke harness `--json` flag does not exist; `--report-out PATH` is
  the correct switch (verified)。 The original task command was
  adjusted to use `--report-out` + `tail` of the human output — same
  data。
- The `autonomath-mcp` binary is in `.venv/bin/`; the harness needs
  either an activated venv or `--mcp-cmd /abs/path` (used here)。
- The 240-route walk consumed prod anonymous quota; subsequent
  external anonymous calls until 2026-05-08 00:00 JST will see 429。
  This is functioning-as-intended, not a defect。
- Read-only constraint honoured: only HTTP GET against prod。 No
  POST/PUT/DELETE issued。
