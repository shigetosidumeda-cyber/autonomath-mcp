# TEST_CATALOG (jpcite/tests)

Generated 2026-05-05. Read-only audit. **No `.pytest_cache` durations available** (cache dir is empty / CACHEDIR.TAG only) — duration column omitted.

## Headline counts
- **330 `test_*.py` files** (Bash: `find tests/ -name "test_*.py" | wc -l`).
- **2,714 `def test_*` functions total** across the suite.
- **17 files** in the **release gate** (`PYTEST_TARGETS` in `.github/workflows/release.yml` line 23 + `test.yml` line 25 — identical lists).
- **9 files** in `tests/e2e/` driven by `e2e.yml` (`pytest tests/e2e/ -v`, Playwright + chromium, NOT in release gate).
- **1 file** in `tests/eval/` (`tests/eval/test_tier_a_seeds.py`) driven by `eval.yml` nightly cron 19:45 UTC + on PR change.
- All other 303 files are **ad-hoc** (only invoked by full-suite `pytest` runs locally / pre-commit; no CI gate).

## Release gate (17 files / matched verbatim across `release.yml` + `test.yml`)
| File | Tests | Subject (heuristic from filename + import grep) |
|---|---:|---|
| tests/test_program_rss_feeds.py | 5 | `scripts/etl/generate_program_rss_feeds.py` per-program RSS |
| tests/test_distribution_manifest.py | 4 | `scripts/distribution_manifest.py` (CC-BY etc. license bundle) |
| tests/test_static_public_reachability.py | 6 | static `site/` HTML reachability |
| tests/test_enforcement.py | 24 | `api.enforcement` 行政処分 routes |
| tests/test_rate_limit.py | 11 | `api.middleware.rate_limit` (anon + auth) |
| tests/test_source_manifest.py | 11 | `data/source_manifest.json` ingest provenance |
| tests/test_extract_prefecture.py | 6 | `ingest.extract_prefecture` JIS code mapper |
| tests/test_no_llm_in_production.py | 2 | CI guard against `anthropic`/`openai` imports under `src/` (CLAUDE.md non-negotiable) |
| tests/test_openapi_export.py | 6 | `scripts/export_openapi.py` parity vs `docs/openapi/v1.json` |
| tests/test_openapi_agent.py | 2 | OpenAPI `x-agent-*` extension fields |
| tests/test_billing.py | 39 | Stripe metered billing core |
| tests/test_billing_webhook_signature.py | 13 | Stripe webhook HMAC verification |
| tests/test_programs_batch.py | 13 | `/v1/programs:batch` envelope |
| tests/test_usage_billing_idempotency.py | 8 | usage→Stripe idempotency keys |
| tests/test_self_cap.py | 12 | per-customer self-imposed spending cap |
| tests/test_cost_preview.py | 15 | `/v1/cost-preview` for ¥3/billable unit calc |
| tests/test_trial_signup.py | 16 | `/v1/auth/signup` trial path |
| tests/test_device_flow.py | 5 | OAuth-style device flow |

Sum = **196 release-gate tests** (~7% of 2,714 total). The other ~2,500 tests run **only** via the developer-side `.venv/bin/pytest` (CLAUDE.md "Quality gates"), never on CI.

## E2E gate (9 files / `tests/e2e/`)
Uses `tests/e2e/conftest.py` with Playwright + `playwright install chromium`. `e2e.yml` runs on push + workflow_dispatch (the `--run-production` switch toggles `@pytest.mark.production`).

| File | Tests | Path tested |
|---|---:|---|
| tests/e2e/test_anon_rate_limit.py | 1 | anon 3 req/day rate-limit UI banner |
| tests/e2e/test_api_docs_browse.py | 1 | `/docs/api/` mkdocs |
| tests/e2e/test_dashboard_alerts_ui.py | 1 | dashboard alerts panel |
| tests/e2e/test_dashboard_flow.py | 5 | login → /dashboard → API key reveal |
| tests/e2e/test_landing_flow.py | 3 | `/` landing → CTA |
| tests/e2e/test_onboarding_flow.py | 7 | signup → trial → first call |
| tests/e2e/test_public_pages.py | 2 | per-program SEO pages |
| tests/e2e/test_success_flow.py | 4 | Stripe success redirect |

## Eval gate (1 file / `tests/eval/`)
- `tests/eval/test_tier_a_seeds.py` — 3 tests, drives `tests/eval/run_eval.py` against `tier_a_seed.yaml` / `tier_c_adversarial.yaml`. Cron 19:45 UTC nightly + on PR touching `src/jpintel_mcp/**`. Bootstraps a ~10MB slice via `scripts/bootstrap_eval_db.sh` (full 8.29 GB autonomath.db cannot ride CI).

## Subdirectory roll-up (ad-hoc, not gated)
- `tests/api/` (2 files, 22 tests) — `test_health_deep.py` 7, `test_search_fts5.py` 15. Tests `api/_health_deep.py` + FTS5 trigram tokenizer surface.
- `tests/mcp/` (2 files, 12 tests) — `test_http_fallback_all_120.py` 5 (legacy 120-tool fallback survey, name now stale post Wave 23 89→96 tools), `test_static_resources.py` 7.
- `tests/models/` (1, 21) — `test_premium_response.py` Pydantic shape.
- `tests/sdk/` (1, 14) — `test_python_parity.py` SDK ↔ REST parity.
- `tests/templates/` (1, 11) — `test_saburoku_kyotei.py` 36協定 template (gate `AUTONOMATH_36_KYOTEI_ENABLED`, default off in prod).
- `tests/utils/` (3, 77) — `test_jp_constants.py` 11, `test_jp_money.py` 42, `test_wareki.py` 24. Pure helpers.
- `tests/format_consistency/` — empty (no test_*.py).
- `tests/bench/` — `baseline_2026_04_24.py` (no `test_` prefix → not collected; reference baseline only).
- `tests/smoke/` — `smoke_pre_launch.py` + `verify_120_tools.py` + `pre_launch_2026_04_24.md` (no `test_` prefix; ops scripts, not pytest collected).

## Top-of-the-tail (largest by test count)
- `test_autonomath_tools.py` 57 (module-level skip if `autonomath.db` absent)
- `test_endpoint_smoke.py` 57 (broad endpoint smoke)
- `test_envelope_cs_features.py` 46
- `test_mcp_tools.py` 45
- `test_evidence_packet.py` 43
- `tests/utils/test_jp_money.py` 42
- `test_billing.py` 39 (release gate)
- `test_validation_tools.py` 29 / `test_excel_addin_smoke.py` 29 / `test_me.py` 28 / `test_api.py` 28

## Conditional-skip families (`allow_module_level=True`)
**23 files** skip the entire module when an upstream artifact is missing — these are silently invisible in CI runs that don't have the artifact. See list:
`test_annotation_tools.py`, `test_autonomath_tools.py`, `test_combined_compliance_extension.py`, `test_corporate_layer_tools.py`, `test_dr_roundtrip.py`, `test_english_wedge.py`, `test_gbiz_ingest_integrity.py`, `test_get_law_article_lang.py`, `test_graph_traverse.py`, `test_houjin_endpoint.py`, `test_industry_packs.py`, `test_industry_packs_billing.py`, `test_industry_packs_envelope_compat.py`, `test_intent_of_no_token_leak.py`, `test_lifecycle_calendar.py`, `test_prerequisite_chain.py`, `test_program_lifecycle.py`, `test_provenance_tools.py`, `test_rule_engine.py`, `test_search_tax_incentives_lang.py`, `test_validation_tools.py`, `test_wave22_graceful_empty.py`, `test_wave22_tools.py`. Common gate: `autonomath.db` (~9.4 GB) presence at repo root.

## Dead / suspect tests
- **`tests/test_corporate_layer_tools.py`** — 0 collected `def test_*`. File is a docstring + module-level skip + setup; either tests are defined via `pytest.mark.parametrize` on imported helpers, or the suite is **stub-only**. Verify before next refactor.
- **`tests/test_probe_geps_feasibility.py`** — 0 collected `def test_*`. Pure helper file (says "Fixture-driven tests for scripts/etl/probe_geps_feasibility.py"). Likely tests are defined elsewhere; investigate.
- **`tests/test_redirect_zeimu_kaikei.py`** — has at least one `@pytest.mark.skip(...)` and references the legacy `zeimu-kaikei.ai` domain (per CLAUDE.md, brand renamed to **jpcite** 2026-04-30; file naming is now stale). Re-evaluate whether the redirect SEO behaviour is still in scope (CLAUDE.md says yes — 6-month 301 plan).
- **`tests/mcp/test_http_fallback_all_120.py`** — name asserts **120 tools** but production reports **96 tools** at default gates (CLAUDE.md). Either the test intentionally exercises every gate-on tool (96 actual + 24 gated-off = 120) or the constant is stale. Audit numerator.
- **`tests/test_intent_of_no_token_leak.py`** — covers `intent_of` MCP tool which is currently **gated off pending fix** (`AUTONOMATH_REASONING_ENABLED`, broken per CLAUDE.md Architecture). Test still runs only when env flag flipped.
- Several `test_b*` / `test_d*` / `test_a*` files reference plan/preflight scripts (`bulk_acquisition_plan`, `axis_key_migration_plan`, `analyze_source_logs`, etc.) that may be **one-shot ETL planners**. If their script counterparts have already executed and been retired, the tests may be testing dead code paths. Spot-check before any large clean-up.

## Duplicate test names across files (top set)
| Count | Function name | Likely files |
|---:|---|---|
| 3 | `test_dry_run_writes_no_rows` | several `test_a*` / `test_b*` ETL planners |
| 2 | `test_write_report_materializes_json`, `test_write_json_and_csv_reports` | ETL planner family |
| 2 | `test_webhook_rejects_oversize_content_length`, `test_webhook_503_without_secret` | webhook variants |
| 2 | `test_transparent_prober_uses_ua_respects_robots_and_get_fallback` | URL-prober variants |
| 2 | `test_subscribe_happy_path` | subscriber variants |
| 2 | `test_search_returns_all_seeded_rows`, `test_search_limit_clamp_upper_bound`, `test_search_is_sole_proprietor_bool_cast`, `test_search_filter_prefecture` | program-search vs autonomath-search forks |
| 2 | `test_mcp_rest_parity` | jpintel.db vs autonomath.db parity check (intentional) |
| 2 | `test_get_case_detail`, `test_get_case_404` | case_studies vs court_decisions |
| 2 | `test_empty_table_returns_empty_envelope_not_db_unavailable` | envelope contract on multiple tables |
| 2 | `test_cli_writes_json_without_mutating_database` | dry-run discipline on multiple ETL CLIs |
| 2 | `test_check_exclusions_no_conflict` | exclusion_rules variants |
| 2 | `test_anon_within_quota_returns_200`, `test_anon_over_quota_returns_429` | both `tests/test_anon_rate_limit.py` and `tests/e2e/test_anon_rate_limit.py` |

19 distinct duplicated names. Most look **intentional** (parallel coverage across two DBs / two routers); only the `tests/test_anon_rate_limit.py` ↔ `tests/e2e/test_anon_rate_limit.py` pair is true overlap (unit + Playwright).

## Flaky candidates
**Sleep-based (6 files)**: `test_billing.py`, `test_customer_webhooks.py`, `test_revoke_cascade.py`, `test_dispatch_webhooks.py`, `test_bg_task_queue.py`, `test_l4_cache_wire.py`. All exercise async background work / cache TTL — most likely safe but verify on overloaded CI.

**Network-touching (5 files outside testclient)**: `test_fetch_egov_law_fulltext_batch.py`, `test_integrations.py`, `test_redirect_zeimu_kaikei.py`, `test_bench_prefetch_probe.py`, `test_audience_examples.py` (also uses `bs4`). These can fail when the upstream returns 5xx / blocks UA / a domain is rebranded — none in release gate, so blast radius is contained but unit-test confidence is misleading.

**Order-dependent**: none detected via `_state =` / `GLOBAL_` / `globals()[…]` greps. Module-wide `pytestmark` only on `tests/test_mcp_integration.py` and `tests/e2e/test_anon_rate_limit.py` — both look like grouping markers, not state sharing.

**Module-level env mutation**: `tests/conftest.py` sets `JPINTEL_DB_PATH`, `API_KEY_SALT`, `RATE_LIMIT_FREE_PER_DAY=100`, `RATE_LIMIT_BURST_DISABLED=1` *before* import; this prevents the burst-throttle from 429-ing the 6th anon call across the whole suite. `tests/test_rate_limit.py` clears the burst-disabled flag inside its own fixture — anyone moving the burst-clear logic must keep that contract or every other anon test will start 429-ing under load.

## Markers in use (no custom `markers =` block in `pyproject.toml`)
`asyncio`, `parametrize`, `skipif`, `skip`, `e2e`, `production`, `slow`. **`asyncio_mode = "auto"`** is set in `pyproject.toml`, so plain `async def test_*` collection works without `@pytest.mark.asyncio`. Custom marker `production` is gated by the `--run-production` flag in `tests/e2e/conftest.py`.

## Gaps worth fixing
1. Release gate covers **196 / 2,714 tests (7.2%)**. Anything outside that list (the 23 conditional-skip suites, all `tests/api/`, all `tests/mcp/`, all `tests/eval/`, all utility helpers) is invisible to the tag-time gate. Per CLAUDE.md this is intentional ("HF exporters, e2e, sdk, eval seed-DB tests, bs4-dependent PDF extraction" need extras the release runner won't install) — but the audit asymmetry is large.
2. `tests/test_corporate_layer_tools.py` and `tests/test_probe_geps_feasibility.py` collect zero functions — confirm intent.
3. `tests/mcp/test_http_fallback_all_120.py` filename constant (120) drifts from the live tool count (96 default-gate, ≤120 with all gates flipped).
4. Empty `tests/format_consistency/` directory — either delete or wire.
