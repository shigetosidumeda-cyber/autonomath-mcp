# R8 — post_deploy_smoke.py local app boot dry-run (2026-05-07)

**Spec**: DEEP-61 — `scripts/ops/post_deploy_smoke.py` 5-module gate
(`health` / `routes` / `mcp` / `disclaimer` / `stripe`).
**Goal**: verify the smoke gate itself before pointing it at production. No
production deploy was attempted; the gate ran against a local uvicorn boot.
**Constraint envelope**: `LLM API budget = 0` (forbidden import guard intact),
no destructive overwrite, local boot killed at end.

## Local app boot

| Field | Value |
| --- | --- |
| Command | `JPINTEL_APPI_DISABLED=1 .venv/bin/uvicorn jpintel_mcp.api.main:app --host 127.0.0.1 --port 18080` |
| PID | `50349` |
| Boot time-to-ready | ~20s (`Application startup complete.` line) |
| Healthz first 200 | `HTTP=200 {"status":"ok"}` |
| Shutdown | `kill 50349` → port 18080 released, no listener on `lsof -nP -iTCP:18080 -sTCP:LISTEN` |
| Boot log path | `/tmp/jpcite_local_boot.log` |
| Pre-launch warning | `saburoku_kyotei tools disabled (AUTONOMATH_36_KYOTEI_ENABLED=0)` — expected, gate intentional |

`aggregator_integrity_pass` + `bg_task_worker_started poll_interval_s=2.0` both
fired during boot, so the foreground request path was honest before the smoke
gate started its 240-route walk.

## Smoke invocation

```
PATH="/Users/shigetoumeda/jpcite/.venv/bin:$PATH" \
  .venv/bin/python scripts/ops/post_deploy_smoke.py \
  --base-url http://127.0.0.1:18080 \
  --skip-stripe \
  --mcp-cmd /Users/shigetoumeda/jpcite/.venv/bin/autonomath-mcp \
  --report-out /tmp/jpcite_smoke_local.json
```

`--skip-stripe` was passed because the local boot has no `whsec_TEST` signing
key — the gate's stripe path is a separate verify and is out of scope for an
"app boot dry-run". Stripe coverage is still resident in the smoke binary.

`--mcp-cmd` was needed because `bash -c` reset PATH and `autonomath-mcp`
console-script lives in `.venv/bin/`; the production runbook should ship with
the venv pre-activated, otherwise this exact `binary not found` failure is
the regression the gate flags first.

Process exit code = `1` (one or more module FAIL). JSON result file =
`/tmp/jpcite_smoke_local.json` (2,750 bytes).

## Per-module result table

| # | Module | Status | Elapsed | Summary | Notes |
| - | --- | --- | ---: | --- | --- |
| 1 | `health_endpoints` | PASS | 0.15s | 3/3 healthy | `/healthz`, `/readyz`, `/v1/am/health/deep` all 200 |
| 2 | `routes_500_zero` | PASS | 2.22s | 240/240 walked, 5xx=0 | `tests/fixtures/240_routes_sample.txt` 240 rows, no 5xx surface, sample shows `/openapi.json` 308 (redirect to canonical, expected) |
| 3 | `mcp_tools_list` | FAIL | 2.74s | 107 tools listed (floor=139) | Local MCP spawn returned 107 tools — 32 short of the 139 floor that matches the v0.3.4 manifests. Gate is doing its job: it caught a config gap. |
| 4 | `disclaimer_emit_17` | FAIL | 46.02s | 9/17 emit OK, 8 missing | 9 sensitive tools emit `_disclaimer` correctly. 8 misses surface real defects: 36協定 (gated off), `get_am_tax_rule`, `search_acceptance_stats_am`, `check_enforcement_am`, `search_loans_am`, `search_mutual_plans_am`, `apply_eligibility_chain_am`. |
| 5 | `stripe_webhook` | PASS (skipped) | 0s | `--skip-stripe` honoured | Skip is captured as PASS in the JSON to keep `ok: false` purely from real failures. |

Walked routes sample (first 5 of 240): `/healthz`, `/readyz`, `/v1/am/health/deep`,
`/openapi.json` (308), `/docs` (200).

Disclaimer hits (9/17): `match_due_diligence_questions`, `prepare_kessan_briefing`,
`cross_check_jurisdiction`, `bundle_application_kit`, `search_tax_incentives`,
`pack_construction`, `pack_manufacturing`, `pack_real_estate`, `rule_engine_check`.

Disclaimer misses (8/17, all real and worth fixing — not flaky):
1. `render_36_kyotei_am` / `get_36_kyotei_metadata_am` — gated off via
   `AUTONOMATH_36_KYOTEI_ENABLED=0`; expected, but the gate counts them as
   sensitive and the `tools/call` lookup returns `Unknown tool`. The smoke
   table at `tests/fixtures/17_sensitive_tools.json` should encode the gate
   awareness (or the gate should be flipped on for production CI runs).
2. `get_am_tax_rule` — disclaimer envelope wiring missing.
3. `search_acceptance_stats_am` — disclaimer envelope wiring missing.
4. `check_enforcement_am` — disclaimer envelope wiring missing.
5. `search_loans_am` — disclaimer envelope wiring missing.
6. `search_mutual_plans_am` — disclaimer envelope wiring missing.
7. `apply_eligibility_chain_am` — disclaimer envelope wiring missing.

## Smoke check kinds (categorisation)

| Kind | Module(s) | What it asserts |
| --- | --- | --- |
| Health | `health_endpoints` | The 3 long-lived health endpoints stay 200 — proxy/dependency liveness sanity. |
| Route surface | `routes_500_zero` | 240 sample routes from `tests/fixtures/240_routes_sample.txt` walk without a 5xx. (3xx + 4xx are intentionally allowed — gate is "no internal error", not "no auth"). |
| MCP surface | `mcp_tools_list` | `tools/list` returns ≥139 tools (default gates). |
| Sensitive disclaimer (業法) | `disclaimer_emit_17` | 17 sensitive tools (`tests/fixtures/17_sensitive_tools.json`) all emit `_disclaimer` envelope under §52 / §72 / §1 / 行政書士法 / 司法書士法 / 社労士法 / 景表法 fences. |
| Billing | `stripe_webhook` | webhook delivery + idempotency — first POST + replay POST return same status, both inside `{200, 202, 204, 400}`. Skippable via `--skip-stripe`. |

## Verdict on the gate itself

The gate **works**. It cleanly:
1. Loaded the 240-route fixture and produced a real 240/240 walk with zero 5xx.
2. Confirmed all 3 health endpoints liveness against the local boot.
3. Spawned the local MCP server and produced a tool-count delta against the
   manifest floor — exposing a real config drift (107 vs 139 floor; the 32
   missing tools are gated-off cohorts: V4 / Phase A / Wave 21 / Wave 22 /
   Wave 23 packs whose env flags weren't set in this bare-shell invocation).
4. Asserted the 17-sensitive-tool disclaimer envelope against actual
   `tools/call` round-trips, and surfaced 8 real wiring gaps.
5. Honoured `--skip-stripe` and emitted a clean JSON report (2,750 bytes).

The two real failures are **the value of the gate, not noise**:
- `mcp_tools_list 107 < 139` is the smoke gate version of the
  `len(await mcp.list_tools())` invariant the CLAUDE.md release checklist
  explicitly insists on. Production deploy must set the cohort env flags so
  `tools/list` returns 139+.
- `disclaimer_emit_17 9/17` exposes 7 sensitive tools with no `_disclaimer`
  envelope wiring — these are §52 / 業法 surfaces and must be fixed before
  the v0.3.4 deploy.

## What the gate did **not** prove

- It does not prove production-only middleware (Cloudflare, Stripe live
  signatures, Fly secret CORS list) — those still need a post-deploy run with
  `--base-url https://api.jpcite.com` and the live `JPCITE_SMOKE_STRIPE_SIGNATURE`.
- It does not prove anonymous-quota reset semantics (JST midnight) — that is
  a separate cron + clock test.
- It does not prove that the 32 tool-count gap is actually env-flag-only
  (vs. broken imports). A follow-up should run the gate with
  `AUTONOMATH_*_ENABLED=1` for every cohort and re-check the count.

## Constraint compliance

| Constraint | Status |
| --- | --- |
| LLM API budget = 0 | YES — `_FORBIDDEN_IMPORTS` guard at the top of `post_deploy_smoke.py` ran before any module; the run never imported `anthropic` / `openai` / `google.generativeai` / `claude_agent_sdk`. |
| Destructive overwrite forbidden | YES — only new files written: `/tmp/jpcite_local_boot.log`, `/tmp/jpcite_smoke_local.json`, this R8 doc. No source overwrite. |
| Local boot must terminate | YES — `kill 50349` returned, `lsof -iTCP:18080` shows no listener. |
| No production deploy | YES — `--base-url http://127.0.0.1:18080` only; no `fly deploy`, no PyPI / npm publish, no MCP registry push. |

## Artefacts

- Smoke JSON report: `/tmp/jpcite_smoke_local.json` (2,750 bytes)
- Local boot log: `/tmp/jpcite_local_boot.log`
- This doc: `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_POST_DEPLOY_SMOKE_LOCAL_2026-05-07.md`

## Recommended next steps (ordered)

1. Wire `_disclaimer` envelope on the 7 sensitive tools that missed
   (`get_am_tax_rule`, `search_acceptance_stats_am`, `check_enforcement_am`,
   `search_loans_am`, `search_mutual_plans_am`, `apply_eligibility_chain_am`,
   plus the 36協定 fixture exemption decision).
2. Add a `tests/fixtures/17_sensitive_tools.json` revision that either marks
   the 36協定 tools as gate-aware (skip when `AUTONOMATH_36_KYOTEI_ENABLED=0`)
   or wraps the smoke call in a flip.
3. Run the same gate against `https://api.jpcite.com` after the next deploy
   without `--skip-stripe`, with `JPCITE_SMOKE_STRIPE_SIGNATURE` exported.
4. Ensure the production runbook activates the venv (so
   `which autonomath-mcp` resolves) **before** invoking the smoke binary —
   otherwise modules 3 + 4 fail with the misleading
   `binary not found: autonomath-mcp` line that the bare shell produced first.
