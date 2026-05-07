# Worktree cleanup notes 2026-05-02

## Current safety state

- `git diff --cached --name-only` is empty after unstaging the accidental broad index.
- No file contents were discarded.
- The dirty tree is still large and should not be committed with `git add .`.
- Large DB files are not currently part of the dirty/untracked set.

## Current counts

- status entries: about 826
- tracked modified: about 639
- tracked deleted: about 5
- untracked status entries: about 182
- untracked files when expanded: about 597

## Local cleanup commits created

- `1a806ac` — evidence prefetch context estimates
- `c0592ca` — API billing / idempotency / response safeguards
- `3c98315` — public docs and pricing copy cleanup
- `cae2d9a` — MCP sanitized error envelopes

## Commit groups

### 1. Deployed token/evidence funnel

Status: committed in `1a806ac`.

Keep together. This is the smallest product story that was deployed to
Cloudflare Pages and Fly API.

Representative paths:

- `src/jpintel_mcp/api/evidence.py`
- `src/jpintel_mcp/api/intelligence.py`
- `src/jpintel_mcp/services/evidence_packet.py`
- `src/jpintel_mcp/services/token_compression.py`
- `docs/api-reference.md`
- `docs/openapi/v1.json`
- `site/playground.html`
- `site/pricing.html`
- `site/llms.txt`
- `site/llms.en.txt`
- `site/en/llms.txt`
- `site/qa/llm-evidence/`
- `site/integrations/`
- `tests/test_evidence_packet.py`
- `tests/test_intelligence_api.py`
- `tests/test_bench_harness.py`
- `tools/offline/bench_harness.py`

Notes:

- Safe public claim is context-size reduction under caller-supplied baseline.
- Do not claim guaranteed LLM bill reduction.
- Production smoke confirmed:
  - `GET /v1/openapi.json` includes `source_tokens_basis` and `source_pdf_pages`.
  - `GET /v1/intelligence/precomputed/query?...source_pdf_pages=30` returned packet/source estimates.

### 2. Billing/idempotency hotfix

Status: committed in `c0592ca` as part of the API safety bundle.

Keep separate from token/evidence. This affects billing safety.

Representative paths:

- `src/jpintel_mcp/api/deps.py`
- `src/jpintel_mcp/api/idempotency_context.py`
- `src/jpintel_mcp/api/middleware/idempotency.py`
- `src/jpintel_mcp/billing/stripe_usage.py`
- `scripts/migrations/122_usage_events_billing_idempotency.sql`
- `tests/test_usage_billing_idempotency.py`
- relevant Stripe/backfill tests

Notes:

- This group prevents duplicate local usage rows under HTTP idempotency.
- Review with billing tests before committing.

### 3. Widget billing

Status: not committed. `tests/test_widget_billing.py` passes, but the code still
contains a widget-specific included-requests / overage model. Do not commit until
the pricing model conflict with public `¥3/billable unit` posture is resolved.

Separate from core billing even though it shares Stripe helpers.

Representative paths:

- `src/jpintel_mcp/api/widget_auth.py`
- `tests/test_widget_billing.py`
- widget overage queue/backfill paths

Notes:

- Keep `widget:{event_id}` dedup behavior visible in the commit.

### 4. MCP contract / sanitizer

Status: committed in `cae2d9a`.

Separate from REST/API commits.

Representative paths:

- `src/jpintel_mcp/mcp/server.py`
- `src/jpintel_mcp/mcp/_error_helpers.py`
- `src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py`
- MCP resource/static-resource tests

Notes:

- Some behavior changes from raising exceptions to returning sanitized error envelopes.

### 5. Scripts, migrations, and crons

Split by operational blast radius.

Suggested groups:

- subsidy-rate migration 121 and D5 tests
- billing health cron / Stripe reconcile / usage backfill
- customer delivery crons
- content/SEO/RSS crons
- ingest automation
- ETL report/plan/preflight/propose scripts
- ETL mutators/backfills

Notes:

- Migration 121 changes schema guard expectations and must be deployed with DB readiness.
- Migration 120 is manual/destructive and should not be swept into an automatic deploy commit.
- Some delivery crons treat logged-only delivery as delivered; review before enabling schedules.

### 6. SDK, marketplace, and distribution

Do not mix with core API deploy commits.

Representative paths:

- `server.json`
- `mcp-server.json`
- `smithery.yaml`
- `dxt/`
- `sdk/typescript/`
- `sdk/python/`
- `sdk/freee-plugin/`
- `sdk/mf-plugin/`
- `sdk/integrations/`
- `examples/`

Notes:

- Distribution manifest drift check was reported OK by the explorer.
- Commit by registry/SDK/marketplace target.

### 7. Generated static site

Review separately.

Representative paths:

- `site/docs/**`
- `site/enforcement/**`
- `site/rss/**`
- `site/sitemap*.xml`
- `site/programs/**`
- `site/prefectures/**`

Notes:

- Decide whether generated output is source-of-truth for Cloudflare Pages.
- If yes, commit with the generator script that produced it.
- If no, ignore or leave out of source commits.

### 8. Data / generated reports

Representative paths:

- `data/source_freshness_report.json`
- `data/sample_consultant_clients.csv`
- internal handoff/report docs

Notes:

- `data/source_freshness_report.json` appears to include timestamp-style churn.
- Check sample CSV for real PII before committing.

## Safe next commands

Do not run `git add .`.

Next safe targets:

- distribution / SDK manifests after running `python3 scripts/check_distribution_manifest_drift.py`
- subsidy-rate migration 121 with its D5 tests
- generated cross / enforcement / RSS pages only if their generators are staged too
- widget billing only after resolving the pricing-model conflict noted above
