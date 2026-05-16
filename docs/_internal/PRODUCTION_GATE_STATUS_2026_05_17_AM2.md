# Production gate status 2026-05-17 AM2

7/7 production deploy readiness gate re-verify after Wave 89-94
(+60 new packet generators, catalog 282 -> 432) and the PERF-27..32
cascade (import-time gate + sqlite ANALYZE + mkdocs parallel + slug
lazy-load + autonomath_tools chain lazy + ruff project-wide 25 -> 0).

Lane: [lane:solo]. Honest findings; nothing claimed PASS without
verification. All seven gates the user listed are reported live below
against current HEAD `4ad27cea6`.

## Gate matrix

Single-runner: `scripts/ops/production_deploy_readiness_gate.py`
(read-only, no mutation, no deployed endpoints, no secret values).

| # | Gate | Result |
|---|---|---|
| 1 | functions_typecheck (`npm run --prefix functions typecheck`) | PASS |
| 2 | release_capsule_validator (`scripts/ops/validate_release_capsule.py`) | PASS — release capsule validator: ok |
| 3 | agent_runtime_contracts (`scripts/check_agent_runtime_contracts.py`) | PASS — agent runtime contracts: ok |
| 4 | openapi_drift (`scripts/check_openapi_drift.py`) | PASS — 307 paths in [290,330], all surfaces match regenerated export, no banned leak patterns |
| 5 | mcp_drift (`scripts/check_mcp_drift.py`) | PASS — tools=184 in [130,200], registry tool counts match runtime, version=0.4.1 across 8 manifests |
| 6 | release_capsule_route (functions/release/[[path]].ts + site/_routes.json + site/_headers) | PASS — ACTIVE_CAPSULE_ID=rc1-p0-bootstrap-2026-05-15, all required tokens + headers present |
| 7 | aws_blocked_preflight_state (fixture + preflight_scorecard) | PASS — fixture_gate_state=AWS_BLOCKED_PRE_FLIGHT, scorecard.state=AWS_CANARY_READY, **live_aws_commands_allowed=false** |

Summary: `{"pass": 7, "fail": 0, "total": 7}`, top-level `ok: true`,
generated_at = `2026-05-16T16:03:49+00:00` (local probe; UTC stamp).

`live_aws_commands_allowed = false` is maintained as the absolute
condition (Wave 50 tick 1 から 150+ tick 連続堅守). Scorecard.state is
`AWS_CANARY_READY` per `AWS_PREFLIGHT_ALLOWED_STATES` (Stream W concern
separation 確立: scorecard を AWS_CANARY_READY に進めても live_aws は
operator authority flip 必須).

## Blockers found and fixed

None at the canonical CI scope. No source-code edits were required to
satisfy the seven gates. The readiness gate completed end-to-end on
first run from HEAD `4ad27cea6` with no fixture rebuilds, no manifest
re-stamps, and no regenerated artifacts.

### Wave 89-94 cohort delta (no gate regression)

- Wave 89-94 packet generators: **+60** (catalog 282 -> 432, +50%
  growth in 1 session window). Generator code under `Wave9X_*/` is
  data-pipeline only (Parquet/JSON output), no schema migrations and no
  MCP tool surface change at default gates.
- PERF-27 import-time gate landed (CI dimension verifying cold-start
  module import budget); does not introduce a deploy-time gate.
- PERF-28 `sqlite ANALYZE` on 3 critical tables (NO VACUUM) — pure
  statistics update, no schema drift, no row-count change.
- PERF-29 mkdocs parallel build; build is invoked by CI not the
  readiness gate, but `--strict` still green.
- PERF-30 slug generation lazy-load; pre-import test surface unchanged.
- PERF-31 `autonomath_tools` chain lazy-load — cold start <1s target.
  MCP tool count unchanged at 184 (matches all 8 manifests).
- PERF-32 ruff project-wide 25 -> 0 (commits `f66e89ac0` + `e965ed218`
  bundled 48 fixes across tools/offline/, pdf-app/, sdk/, tools/
  integrations/). This removes the AM1 doc's listed out-of-scope ruff
  findings — they are now eliminated entirely, not just excluded from
  CI target list.

## openapi drift evidence

`docs/openapi/v1.json`: 307 paths (2 preview, 305 stable). Bounds
gate `[290,330]` PASS. `site/openapi/v1.json` matches regenerated.
`site/openapi.agent.json`: 34 paths in `[25,50]` (agent tier). GPT-3.0
slim: 30 paths in `[25,50]`. All `.well-known/openapi-discovery.json`
tier metadata (full / agent / gpt30) current. No banned leak patterns
across all 8 inspected surfaces.

## mcp drift evidence

`server.json` + `mcp-server.json` + `mcp-server.full.json` +
`site/server.json` + `site/mcp-server.json` + `site/mcp-server.full.json`
all at `tools=184`, bounds gate `[130,200]` PASS. `mcp-server.core.json`
39-tool subset, `mcp-server.composition.json` 58-tool subset — both
fully resolve into runtime. `dxt/manifest.json` v0.4.1. Runtime tool
list matches manifest tool list (184).

## preflight scorecard evidence

- fixture: `tests/fixtures/aws_credit/blocked_default.json` →
  `gate_state=AWS_BLOCKED_PRE_FLIGHT`, `live_aws_commands_allowed=false`.
- scorecard: `site/releases/rc1-p0-bootstrap/preflight_scorecard.json` →
  `state=AWS_CANARY_READY`, `live_aws_commands_allowed=false`,
  `cash_bill_guard_enabled=true`.
- Allowed preflight states (Stream W concern separation):
  `{"AWS_BLOCKED_PRE_FLIGHT", "AWS_CANARY_READY"}`.

## release capsule route evidence

`functions/release/[[path]].ts` carries all 12 required source tokens
(ACTIVE_POINTER_PATH, ACTIVE_CAPSULE_ID=`rc1-p0-bootstrap-2026-05-15`,
ACTIVE_CAPSULE_DIR=`rc1-p0-bootstrap`, live_aws_commands_allowed flip
guard, capsule_pointer_invalid path, GET/HEAD-only enforcement, and 4
release-relative URL prefixes). `site/_routes.json` includes
`/release/*`. `site/_headers` covers `/release/current/*`,
`/release/rc1-p0-bootstrap/*`, `/releases/current/*`, and
`/releases/rc1-p0-bootstrap/*`.

## Continuous invariants reaffirmed

- production deploy readiness gate: **7/7 PASS**.
- `live_aws_commands_allowed`: **false** (continuous; absolute condition
  held since Wave 50 tick 1, 150+ tick streak).
- AWS canary: mock smoke only this session; no live submission.
- No new schema migrations applied in this re-verify.
- No MCP tool surface change in this re-verify (Wave 89-94 added packet
  generators only; PERF-27..32 are read-mostly + ANALYZE + lazy-load +
  CI gate + ruff cleanup).
- Catalog at 432 packet generators (post Wave 94). PERF-27..32 cascade
  fully merged.

## Files touched in this re-verify

- `docs/_internal/PRODUCTION_GATE_STATUS_2026_05_17_AM2.md` (this file)

No source-code, schema, manifest, or workflow file was modified to
satisfy the seven gates this session.

last_updated: 2026-05-17
