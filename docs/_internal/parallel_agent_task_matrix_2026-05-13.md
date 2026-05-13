# Parallel Agent Task Matrix (2026-05-13)

Purpose: split the current jpcite cleanup / hardening / deploy-readiness loop into parallel-safe work packets that other agents can pick up without stepping on each other.

Current state:

- OpenAPI drift: pass (`297 / 34 / 30` paths; discovery metadata current).
- MCP drift: pass (`151` runtime tools; public manifests sanitized).
- pre-deploy verify: pass locally after x402 seed and perf-smoke fix.
- Wave 5 impact suite: pass (`230` tests).
- focused safety tests: pass for x402, MCP manifest sanitizer, perf smoke, edge reliability, programs/export, semantic search, payment rail, and foundation routes.
- public leak/static reachability suite: pass after syncing `site/openapi/v1.json` with `site/docs/openapi/v1.json`.
- x402 contract: `/v1/programs/search` is no longer a canonical x402 path; default/minimal anonymous discovery stays 200, `fields=full` remains route-level paid-only, stale DB x402 rows are ignored by middleware and disabled by the seeder.
- production deploy: still no-go until dirty worktree review and operator ACK are completed. Latest GO gate blockers are only `dirty_tree_present` and `operator_ack`.

## Practical Parallel Limit

Recommended concurrent worker count: 8.

Hard upper bound before quality drops: 12, but only if at least 4 are read-only auditors. More than 12 is likely worse because the repo has many generated files and shared gates.

Why not unlimited:

- Generated files collide easily: OpenAPI, MCP manifests, `site/llms-full.txt`, sitemap/feed outputs.
- Deploy gates must be run serially after all code edits.
- x402/auth/security code needs one owner at a time.
- Broad "fix all pages" prompts cause agents to edit the same HTML and overwrite copy decisions.

Best pattern:

1. Run 6-8 write workers with disjoint file ownership.
2. Run 2-4 read-only auditors in parallel.
3. Merge outputs.
4. Run one serial gate owner for drift, tests, and deploy readiness.

## Do Not Parallelize

These tasks should stay single-owner:

| Task | Reason |
|---|---|
| Production deploy | Needs one final state, operator ACK, and rollback plan. |
| `git status` cleanup / commit shaping | Dirty tree is large; parallel cleanup risks deleting user/agent work. |
| x402 verification semantics | Security-critical; one owner should make or reject the cryptographic design. |
| OpenAPI + discovery regeneration | Generated files must be one coherent set. |
| MCP manifest regeneration | Runtime tool order/count and sanitized descriptions must match one run. |
| Global search/replace across `site/**` | Easy to corrupt generated pages or duplicate copy. |

## Parallel-Safe Work Packets

### A1. Public HTML Leak Cleanup

Type: write worker.

Write scope:

- `site/status/*.html`
- `site/audiences/**/*.html`
- `site/en/audiences/**/*.html`
- `site/connect/**/*.html`

Do not edit:

- `scripts/sync_mcp_public_manifests.py`
- `mcp-server*.json`
- OpenAPI files

Goal:

- Remove internal env names, script paths, job names, table names, internal strategy terms, and secret-shaped placeholders.
- Replace with public-safe terms like "scheduled update", "usage summary", "public corpus", "weekly benchmark".

Validation:

```bash
rg -n --pcre2 "TG_BOT_TOKEN|tools/offline|aggregate_status_alerts_hourly|audit_runner|analytics/|cost_ledger|api_keys|usage_events|jpintel\\.db|autonomath\\.db|\\bARR\\b|\\bROI\\b|Wave [0-9]|migration [0-9]|CLAUDE\\.md|\\{\\{|\\{%" site/status site/audiences site/en/audiences site/connect
```

### A2. LLM/GEO Public Text Cleanup

Type: write worker.

Write scope:

- `site/llms.txt`
- `site/llms.en.txt`
- `site/llms-full.txt`
- `site/feed.atom`
- `site/feed.rss`

Do not edit:

- sitemap files
- OpenAPI files
- MCP manifests

Goal:

- Make agent-facing text direct, accurate, non-internal, and scanner-clean.
- Keep examples using `<YOUR_JPCITE_API_KEY>` only.
- Remove internal DB/table names and ROI/ARR claims.

Validation:

```bash
xmllint --noout site/feed.atom site/feed.rss
rg -n --pcre2 "am_x+|Authorization: Bearer am_|usage_events|jpintel\\.db|autonomath\\.db|\\bARR\\b|\\bROI\\b|Wave [0-9]|migration [0-9]|CLAUDE\\.md" site/llms.txt site/llms.en.txt site/llms-full.txt site/feed.atom site/feed.rss
```

### A3. MCP Manifest Sanitizer

Type: write worker.

Write scope:

- `scripts/sync_mcp_public_manifests.py`
- `tests/test_mcp_public_manifest_sync.py`
- generated `mcp-server*.json`
- generated `site/mcp-server*.json`
- generated `server.json`
- generated `site/server.json`

Do not edit:

- runtime tool implementations unless a description source is impossible to sanitize safely.

Goal:

- Prevent regenerated manifests from leaking internal table names, DB filenames, old brand names, migration/wave terms, secret-shaped examples, or ROI/ARR wording.

Validation:

```bash
uv run python scripts/sync_mcp_public_manifests.py
python3 scripts/check_mcp_drift.py
uv run pytest -q tests/test_mcp_public_manifest_sync.py --tb=short
rg -n --pcre2 "jpintel\\.db|autonomath\\.db|usage_events|api_keys|cost_ledger|am_x+|Authorization: Bearer am_|\\bARR\\b|\\bROI\\b|Wave [0-9]|migration [0-9]|CLAUDE\\.md" mcp-server*.json site/mcp-server*.json server.json site/server.json
```

### A4. OpenAPI Discovery Consistency

Type: write worker.

Write scope:

- `docs/openapi/*.json`
- `site/docs/openapi/*.json`
- `site/openapi*.json`
- `site/.well-known/openapi-discovery.json`
- tests directly asserting OpenAPI discovery metadata

Do not edit:

- API runtime code unless drift proves runtime schema is wrong.
- MCP manifests.

Goal:

- Keep public, agent, and gpt30 OpenAPI specs in sync with discovery metadata.
- Ensure `site/openapi/v1.json` exists if discovery advertises it.

Validation:

```bash
uv run python scripts/export_openapi.py --out docs/openapi/v1.json --site-out site/docs/openapi/v1.json
uv run python scripts/export_agent_openapi.py --out docs/openapi/agent.json --site-root-out site/openapi.agent.json --site-out site/docs/openapi/agent.json
uv run python scripts/export_openapi.py --profile gpt30 --out site/openapi.agent.gpt30.json
python3 scripts/check_openapi_drift.py
uv run pytest -q tests/test_openapi_export.py tests/test_static_public_reachability.py::test_openapi_discovery_tiers_match_committed_public_specs --tb=short
```

### A5. x402 Edge Verification

Type: one write worker only.

Write scope:

- `functions/x402_handler.ts`
- x402 edge tests
- x402 payment tests

Do not edit:

- unrelated billing routes
- MCP/OpenAPI/public copy

Goal:

- Either implement reviewed EIP-191/EIP-712 payer signature verification or keep a documented fail-closed path.
- Verify signed quote binding, receipt settlement, ERC20 transfer topic/from/to/amount, replay protection, and origin `issue_key`.

Validation:

```bash
npx --yes esbuild functions/x402_handler.ts --bundle --format=esm --platform=browser --outfile=/tmp/x402_handler.js
uv run pytest -q tests/test_x402_edge_verify_restoration.py tests/test_payment_rail_3.py tests/test_x402_payment_chain.py --tb=short
```

Risk note:

- Do not fake cryptographic verification. If signature recovery cannot be implemented confidently, fail closed and document the residual P1.

### A6. Edge Rate Limit Reliability

Type: write worker.

Write scope:

- `functions/anon_rate_limit_edge.ts`
- `src/jpintel_mcp/api/anon_limit.py`
- edge/origin anon limiter tests

Do not edit:

- x402 handler
- API billing routes

Goal:

- Keep edge and origin IP bucket semantics aligned.
- Document that KV is advisory if Durable Object / atomic limiter is not implemented.
- Avoid trusting junk auth headers.

Validation:

```bash
uv run pytest -q tests/test_anon_rate_limit.py tests/test_anon_fingerprint.py tests/test_edge_reliability_p1_static.py --tb=short
npx --yes esbuild functions/anon_rate_limit_edge.ts --bundle --format=esm --platform=browser --outfile=/tmp/anon_rate_limit_edge.js
```

Residual P1 if not solved:

- Workers KV read-modify-write is not atomic. A Durable Object or origin-only authoritative limiter is needed for strict concurrent burst control.

### A7. Performance Smoke / Deploy Gate Semantics

Type: write worker.

Write scope:

- `scripts/ops/perf_smoke.py`
- `scripts/ops/pre_deploy_verify.py`
- `tests/test_perf_smoke*.py`
- `tests/test_pre_deploy_verify.py`

Do not edit:

- endpoint implementation code unless a real 5xx is found.

Goal:

- Distinguish "endpoint is broken" from "paid endpoint correctly returns 402 without auth".
- Keep pre-deploy gates read-only and deterministic.

Validation:

```bash
uv run pytest -q tests/test_perf_smoke.py tests/test_perf_smoke_ci_skip.py tests/test_pre_deploy_verify.py --tb=short
PYTHONDONTWRITEBYTECODE=1 JPCITE_PREFLIGHT_ALLOW_MISSING_DB=1 .venv/bin/python scripts/ops/pre_deploy_verify.py
```

### A8. Programs / Export Performance Guard

Type: write worker.

Write scope:

- `src/jpintel_mcp/api/programs.py`
- `src/jpintel_mcp/api/export.py`
- `tests/test_programs.py`
- `tests/test_export_perf_guards.py`

Do not edit:

- x402 middleware unless a test proves the route is unreachable.

Goal:

- Bound expensive offsets, filter lists, XLSX memory use, and huge anonymous outputs.
- Ensure local tests use explicit dev x402 schema fail-open when route validation is the subject.

Validation:

```bash
JPCITE_X402_SCHEMA_FAIL_OPEN_DEV=1 uv run pytest -q tests/test_programs.py tests/test_export_perf_guards.py --tb=short
```

### A9. Semantic Search Performance Safety

Type: write worker.

Write scope:

- `src/jpintel_mcp/api/semantic_search_v2.py`
- semantic search tests
- embedding ETL tests only if needed

Do not edit:

- unrelated search endpoints
- OpenAPI generated files

Goal:

- Bound query time, vector overfetch, model load failures, and stale model circuit behavior.

Validation:

```bash
uv run pytest -q tests/test_dimension_a_semantic.py tests/test_semantic_search_perf_safety.py --tb=short
```

Residual P1 if not solved:

- Local model inference cannot be hard-aborted after it starts unless moved into a separate process or provider with true timeout cancellation.

### A10. SEO/GEO Navigation and No-Index Hygiene

Type: write worker.

Write scope:

- `site/sitemap*.xml`
- `site/robots.txt`
- `site/**/*.html` only for canonical/noindex/nav fixes
- reachability tests

Do not edit:

- feed files if A2 owns them
- OpenAPI files

Goal:

- Remove missing/noindex URLs from sitemaps.
- Ensure important public pages are reachable and not internally contradictory.

Validation:

```bash
xmllint --noout site/sitemap.xml site/sitemap-cases.xml site/sitemap-structured.xml
uv run pytest -q tests/test_static_public_reachability.py --tb=short
```

### A11. Security Headers / CSP

Type: write worker.

Write scope:

- Cloudflare Pages config files
- static header files
- security header tests
- individual HTML only if moving inline scripts/styles is scoped and tested

Do not edit:

- business copy
- generated OpenAPI/MCP

Goal:

- Tighten CSP and security headers without breaking public pages.
- Inventory remaining inline script/style debt if a full CSP cleanup is too large.

Validation:

```bash
rg -n "Content-Security-Policy|unsafe-inline|X-Frame-Options|Referrer-Policy|Permissions-Policy" .
uv run pytest -q tests/*security* tests/*headers* --tb=short
```

Risk note:

- Full `unsafe-inline` removal is high-churn. It should be a dedicated lane, not a side quest.

### A12. Final Deploy Gate Auditor

Type: read-only auditor.

Write scope:

- none

Goal:

- Run the final gate set after all write workers finish.
- Report GO/NO-GO with exact blockers.

Validation:

```bash
git status --porcelain=v1
python3 scripts/check_openapi_drift.py
python3 scripts/check_mcp_drift.py
uv run pytest -q tests/test_x402_edge_verify_restoration.py tests/test_payment_rail_3.py tests/test_x402_payment_chain.py tests/test_mcp_public_manifest_sync.py tests/test_perf_smoke.py tests/test_perf_smoke_ci_skip.py tests/test_pre_deploy_verify.py tests/test_edge_reliability_p1_static.py --tb=short
PYTHONDONTWRITEBYTECODE=1 JPCITE_PREFLIGHT_ALLOW_MISSING_DB=1 .venv/bin/python scripts/ops/pre_deploy_verify.py
```

## Read-Only Audit Packets

These are safe to run alongside write workers:

| Packet | Scope | Output |
|---|---|---|
| R1 public leak audit | `site/**`, public manifests, docs nav pages | P0/P1 leak list with exact paths |
| R2 security audit | x402, auth, anon limit, webhook, API proxy | exploitability + tests needed |
| R3 performance audit | programs, export, semantic, foundation, edge body parsing | slow paths + suggested caps |
| R4 deploy gate audit | workflows, pre-deploy, drift scripts, dirty tree | GO/NO-GO with command evidence |
| R5 SEO/GEO audit | sitemap, robots, feed, llms, canonical, noindex | broken/missing/duplicated discovery surfaces |

## Suggested Immediate Assignment

If we can run 8 agents now:

| Agent | Packet | Mode |
|---|---|---|
| 1 | A1 Public HTML leak cleanup | write |
| 2 | A2 LLM/GEO public text cleanup | write |
| 3 | A3 MCP sanitizer | write |
| 4 | A5 x402 edge verification | write, single-owner |
| 5 | A7 perf smoke / deploy gate semantics | write |
| 6 | A10 SEO/GEO navigation | write |
| 7 | R2 security audit | read-only |
| 8 | R4 deploy gate audit | read-only |

If we can run 12 agents, add:

| Agent | Packet | Mode |
|---|---|---|
| 9 | A6 edge rate limit reliability | write |
| 10 | A8 programs/export perf guard | write |
| 11 | R1 public leak audit | read-only |
| 12 | R3 performance audit | read-only |

## Stop Conditions

Do not deploy if any of these remain:

- OpenAPI drift fails.
- MCP drift fails.
- pre-deploy verify fails.
- x402 paid endpoint returns 5xx instead of a valid 402 challenge or authenticated success.
- Public leak grep finds real internal env names, DB filenames, script paths, table names, or secret-shaped placeholders.
- Worktree contains unexplained destructive changes.
- Operator ACK is missing.

Acceptable temporary residuals only if explicitly documented:

- x402 `payer_signature` cryptographic verification not implemented, as long as the path fails closed and on-chain receipt verification remains strict.
- Edge KV anon limiter is advisory, as long as origin limiter remains authoritative.
- Semantic local model inference lacks hard mid-call cancellation, as long as budgets/circuit breakers prevent repeated overload.
