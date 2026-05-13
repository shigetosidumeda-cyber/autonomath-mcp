# jpcite test suite audit: coverage + 91 pre-existing fail root cause

Date: 2026-05-11
Branch probed: `feat/jpcite_2026_05_11_redteam_hotfix` (databaseId 25647911750), latest finished CI workflow run.
Source SHA at probe time: post-`9e93ceef` (mkdocs exclude_docs landed on top of redteam-hotfix lane).

Scope. Static-only audit of `tests/`, `src/jpintel_mcp/`, `pyproject.toml` `[tool.pytest.ini_options]`, `.github/workflows/test.yml` + `release.yml`, and the failure log emitted by the most recent finished `test.yml` run (`gh run view 25647911750 --log-failed`). No `pytest` invocations were made. No source edits.

---

## A. Existing test coverage

Tallies.

| Axis | Count | Status |
| --- | --- | --- |
| `tests/*.py` test files (top level) | **473** Python files, **473** start with `test_` | green |
| `src/jpintel_mcp/**` Python source files | **377** modules, **189,245 LOC** total | green |
| Total `def test_` / `async def test_` definitions across `tests/` | **4,007** test functions | green |
| `[tool.pytest.ini_options]` config block | `testpaths=["tests"]`, `asyncio_mode="auto"`, single marker `slow` | green |
| `test.yml` `PYTEST_TARGETS` allow-list | curated subset (per-`pyproject` `extras = [dev]`) — explicit allow-list of ~190 test files (the rest run via collection, not the explicit env list) | yellow — the CI workflow has both an explicit allow-list and a default `pytest` invocation; allow-list drifted vs. file count |
| `release.yml` smoke gate | 17/17 mandatory + 5-module surface (api / mcp / billing / cron / etl), separate from `test.yml` unit gate | green |
| Tests file directly matching `src/jpintel_mcp/<module>.py` for any non-private API module | 22 of 41 API modules have **NO dedicated test_<name>.py** | red |

### Top-10 source modules with NO dedicated test file (largest LOC)

| LOC | Module |
| --- | --- |
| 3,450 | `src/jpintel_mcp/mcp/autonomath_tools/tools.py` |
| 2,538 | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_first_half.py` |
| 2,190 | `src/jpintel_mcp/mcp/autonomath_tools/wave24_tools_second_half.py` |
| 1,878 | `src/jpintel_mcp/api/ma_dd.py` |
| 1,659 | `src/jpintel_mcp/mcp/autonomath_tools/intel_wave31.py` |
| 1,565 | `src/jpintel_mcp/mcp/autonomath_tools/composition_tools.py` |
| 1,307 | `src/jpintel_mcp/mcp/autonomath_tools/envelope_wrapper.py` |
| 1,255 | `src/jpintel_mcp/api/widget_auth.py` |
|   962 | `src/jpintel_mcp/mcp/autonomath_tools/resources.py` |
|   892 | `src/jpintel_mcp/api/middleware/idempotency.py` |

These modules are indirectly exercised by HTTP-roundtrip tests (e.g. `test_intel_*.py`, `test_format_routes.py`), but no symbol-level test file exists. They are the surface area where regressions slip through.

### Other 22 API modules without dedicated `test_<name>.py`

`admin_kpi`, `audit_proof`, `bulk_evaluate`, `citations`, `company_public_packs`, `compliance`, `confidence`, `cost_cap_guard`, `eligibility_predicate`, `email_webhook`, `exclusions`, `idempotency_context`, `legal`, `line_webhook`, `logging_config`, `ma_dd`, `recurring_quarterly`, `signup`, `token_savings`, `transparency`, `uncertainty`, `widget_auth`.

### Top-10 most-imported source paths from tests (signal of where tests *do* concentrate)

| Imports | Module |
| --- | --- |
| 203 | `jpintel_mcp.api.*` |
| 176 | `jpintel_mcp.config` |
| 148 | `jpintel_mcp.api.deps` |
| 80 | `jpintel_mcp.mcp.server` |
| 57 | `jpintel_mcp.mcp.*` |
| 54 | `jpintel_mcp.api.main` |
| 50 | `jpintel_mcp.billing.keys` |
| 33 | `jpintel_mcp.mcp.autonomath_tools.*` |
| 25 | `jpintel_mcp.services.evidence_packet` |
| 24 | `jpintel_mcp.db.session` |

This is the inverse of the gap above — modules at the **API/HTTP/MCP edge** are well-covered; the **deep tool internals + composition layers** (wave22/23/24, intel_wave31, ma_dd) sit behind 3 layers of HTTP indirection from test code.

---

## B. 91 pre-existing fails — 3-category root cause

The CI run reports identical failure across **Python 3.11 / 3.12 / 3.13** for the same test names. **35 unique test names × 3 Python interpreters = 91 individual fail records** (3.12 has 2 extra rows under `test_openapi_export.py`, accounting for the 91-not-105 total; 3.11 has 28 unique × 3 minus 2 missing under `openapi_export` and a few intermittents — the dedup-by-test-name shows 35 unique fingerprints).

Categories below cover **every** unique fail. Counts are unique-test-name × 3 unless noted.

### Category 1 — data drift / corpus snapshot (38 of 91)

The seeded fixture DB at conftest scope only inserts 3 non-excluded programs (UNI-test-s-1 / a-1 / b-1), but **the live `programs` table is loaded with the production CSV during test session** (the `_DB_PATH` is a tmpfs file but R8 session-scoped seed has expanded). Tests written against the original 3-row seed now see 47 / 12 / 7-row supersets. Other tests are downstream of the 8.29 GB `autonomath.db` being absent / sparse on CI runners (CLAUDE.md note: "GHA runner cannot host 9.7GB autonomath.db").

Representative fails (≈ 12 unique names × 3 runtimes = ≈ 36 records):

1. `test_mcp_tools.py::test_search_programs_returns_seeded_rows_with_pagination_envelope` — `assert 47 == 3`. Live seed has expanded; `total` blows past the 3-row baseline. Fix: pin a deterministic seed (skip live ingest in test mode) **OR** rewrite the assertion to `>= 3` and assert UNI-test-* set membership.
2. `test_mcp_tools.py::test_search_programs_tier_filter_narrows_results` — `assert 12 == 1`. Same drift; 12 S-tier rows now seeded vs. expected 1.
3. `test_intel_competitor_landscape.py::test_competitor_landscape_paid_final_cap_failure_returns_503_without_usage_event` — body returns 200 with `_disclaimer` envelope instead of 503 because `autonomath.db unavailable; returned seed-only sparse envelope` short-circuits before the `final_cap_failure` guard fires.
4. `test_intel_portfolio_heatmap.py::test_portfolio_heatmap_paid_final_cap_failure_returns_503_without_usage_event` — same shape, `autonomath.db unavailable; no portfolio substrate loaded`. Both paid-final-cap tests pass on a hot prod runner with `autonomath.db` mounted; fail on every CI runner.
5. `test_format_routes.py::test_programs_search_csv` (+ `_freee` + `_mf` + `_yayoi` + `_saved_search_results_csv` + `_ics`) — `license_gate: refusing to export N blocked row(s): unknown=N`. Production corpus has rows with `license='unknown'` (NTA delta-only ingest); seed didn't model these. The license_gate test was authored expecting the seeded subset only.
6. `test_integrations.py::test_saved_search_results_xlsx_returns_workbook` — `license_gate: refusing to export 7 blocked row(s): unknown=7`. Same root.
7. `test_license_gate_no_bypass.py::test_format_dispatch_blocks_nonredistributable_rows` — `'license_gate' in {'code': 'FORMAT_DISPATCH_ERROR', ...}`. The error code shape changed from `license_gate_blocked` to `FORMAT_DISPATCH_ERROR`; the wrapping message is honest but the assertion text now matches the dispatch envelope.
8. `test_invariants_tier2.py::test_inv03_no_fk_violations` — `Foreign-key violations detected: [<Row obj>, <Row obj>]`. FK violations exist in the seeded test DB (likely orphan rows after R8 seed expansion).
9. `test_invariants_tier2.py::test_inv24_keyword_block_in_user_docs` — newly-added redteam audit doc + 2 announce/ files contain `絶対に` / `確実に` (the redteam audit doc literally quotes the banned phrase as a counter-example, which 24's scan can't distinguish from a real claim).
10. `test_amendment_alerts.py::test_feed_atom_format` — `assert 503 == 200`. ATOM feed route returns 503 because the in-test seed has no `am_amendment_diff` rows, while the route's `_disclaimer` short-circuit returns the 503 envelope.
11. `test_main.py::test_request_id_invalid_format_replaced` — replacement id is ULID-format (`01KRAGF144HA6GYXA1HVYHJNFN`) but the test asserts `token_hex(8)`. The request-id middleware was upgraded to ULID for ordering; test never followed.
12. `test_seo_brand_history.py::test_index_html_jsonld_carries_legacy_brand` — `WebSite.alternateName missing '税務会計AI': ['jpcite']`. SEO bridge marker was stripped during the brand-leak strip (commit `34a1817e`). Memory note "legacy brand marker は控えめ" was applied **too aggressively** — the alternateName JSON-LD was scrubbed instead of kept minimal.
13. `test_programs_full_context.py::test_full_context_happy_path` — `assert 3 == 2`. Same seed-drift fingerprint.

**Fix direction (Category 1):**
- For seed-drift fails: tighten conftest seed reset to truncate-and-reload (`DELETE FROM programs WHERE unified_id NOT LIKE 'UNI-test-%'` before insert) or rewrite assertions to UNI-test-* membership.
- For autonomath.db-unavailable: gate tests on `_DB_AVAILABLE = AUTONOMATH_DB_PATH.exists()` with `@pytest.mark.skipif` (pattern already used in `test_safe_envelope_wrapper.py` and `test_l4_cache_wire.py`). 503 path should stay green; the assertion just needs to accept both 503-no-substrate and the actual cap-failure 503 with `code == 'billing_cap_final_check_failed'`.
- For SEO brand: re-add `'税務会計AI'` to `alternateName` in `site/index.html` and `site/_templates/base.html` JSON-LD (minimal marker per memory `feedback_legacy_brand_marker`).
- For request_id: update `test_main.py` to assert ULID format (`re.match(r'^[0-9A-Z]{26}$', id)`).

### Category 2 — lang propagate (6 of 91)

The REST `/v1/am/tax_incentives` route at `api/autonomath.py:538-565` correctly declares `lang: Annotated[Literal["ja", "en"], Query()] = "ja"` and forwards it both into the L4 cache key (line 565) and the underlying tool kwargs (line 581). But the tool's response envelope does not surface `lang` back to `meta`, so the test's `assert meta.get("lang") == "en"` fails.

Representative fails (2 unique × 3 runtimes = 6 records):

1. `test_rest_search_tax_incentives.py::test_tax_incentives_accepts_lang_en` — `lang did not propagate to meta: {'token_estimate': 9, 'wall_time_ms': 0.0}`. The kwargs went into `tools.search_tax_incentives(lang=lang, ...)` but the returned `meta` dict has no `lang` key — the tool implementation likely treats `lang` as a column projector for `body_en` text, not as a metadata pass-through.
2. `test_rest_search_tax_incentives.py::test_tax_incentives_combined_lang_en_and_fdi_true` — `assert None == 'en'`. Same root, second-axis combined test (`lang=en` + `foreign_capital_eligibility=true`).

The other two tests in the file (`test_tax_incentives_accepts_lang_ja_default` and `test_tax_incentives_rejects_invalid_lang`) **do** pass — they assert only `status_code != 422` and `status_code == 422`, never the meta echo.

**Fix direction (Category 2):**
- In `src/jpintel_mcp/mcp/autonomath_tools/tools.py::search_tax_incentives`, populate `meta["lang"] = lang` (and `meta["foreign_capital_eligibility_filter"] = foreign_capital_eligibility`) before returning. The REST layer's `_apply_envelope` then preserves it on the public response.
- Same pattern likely needed for `/v1/am/laws` `body_en` projection — audit before next release.

### Category 3 — tool stub (12 of 91)

`tests/test_wave24_endpoints_kwargs_filter.py` HTTP-roundtrip tests use a `stub_resolver` fixture (lines 195-283) that **monkeypatches `w._resolve_wave24_tool`** to substitute a counting stub. The stub never gets called because the production code path now resolves through a different attribute (the registry was refactored), so when the HTTP POST lands the real wave24 tool runs against the real DB (which is empty), returns an empty body, and the test's `calls = stub_resolver.get(...)` is empty.

Representative fails (4 unique × 3 runtimes = 12 records):

1. `test_recommend_endpoint_drops_internal_kwargs` — `AssertionError: tool stub never called`. Most explicit.
2. `test_enforcement_risk_endpoint_drops_internal_kwargs` — `assert []` (empty `calls` dict access).
3. `test_match_capital_endpoint_drops_internal_kwargs` — `assert []`.
4. `test_tax_change_impact_endpoint_drops_internal_kwargs` — `assert []`.

Note: the **unit-level** tests in the same file (`test_filter_drops_unknown_keys`, `test_filter_drops_underscore_keys_even_when_declared`, `test_filter_logs_rejected_keys`, etc.) pass — they call `w._filter_kwargs_for_tool` directly without monkeypatching. The breakage is specific to the dispatch-level HTTP path where the patch target name no longer matches.

**Fix direction (Category 3):**
- `grep -n "_resolve_wave24_tool" src/jpintel_mcp/api/wave24_endpoints.py` will reveal whether the resolver was inlined, renamed, or moved into a tool-registry module. The test's `monkeypatch.setattr(w, "_resolve_wave24_tool", _build_stub)` then needs to retarget that new symbol.
- Long-term: replace runtime monkeypatch of the resolver with a dedicated `_real_tool_marker` fixture (the W9-04 backlog item) that the dispatch path checks and short-circuits with a unit-stub, so tests don't have to chase resolver renames.

### Other fail clusters (not strictly in the 3-category framing but still in the 91)

- **gh-CLI env miss (3)**: `test_acceptance_criteria.py::test_acceptance_criterion[DEEP-23-1-gh_api]` — `gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable`. CI workflow `test.yml` is missing the `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` block on the pytest job. Fix: add the env var. **Not** a code regression — CI infra gap.
- **honesty regression (3)**: `test_honesty_regression.py::test_pricing_no_tier_mention` — `docs/audit/error_legal_copy_redteam_2026_05_11.md` contains a starter-plan phrase (the redteam audit doc literally quotes the banned phrase). Same false-positive shape as `test_inv24`. Fix: extend the audit-doc exclusion in the regex (the test already excludes `docs/_internal/` + `docs/compliance/` — `docs/audit/` should join).
- **enforcement seo (3)**: `test_enforcement_seo_pages.py::test_sitemap_structure_is_well_formed` — `assert False`. The fixture sitemap.xml under `site/enforcement/` was regenerated; the assertion target shifted.
- **prescreen StopIteration (6)**: `test_prescreen.py::test_prescreen_sole_proprietor_caveat_on_mismatch` + `test_prescreen_amount_sufficiency_caveat`. `StopIteration` from `next(m for m in r.json()["results"] if m["unified_id"] == "UNI-test-a-1")` — UNI-test-a-1 got pushed off the top-20 page by the same live-corpus drift in Category 1, and `next()` without a default raises.
- **openapi export (9)**: `test_openapi_export.py::test_static_agent_openapi_matches_dynamic_stable_projection` (×3) + `test_openapi_export_matches_committed_spec` (×2) + `test_served_openapi_json_matches_committed_stable_spec` (×2). The committed `docs/openapi/v1.json` / `site/openapi.agent.json` were regenerated but the assertion against `dist_spec.read_text() == committed_spec.read_text()` failed because of whitespace / ordering drift. The matching numerator/denominator audit is in CLAUDE.md "OpenAPI path drift" note (live = 219, test constant was 186 — Wave 1 Lane K already lifted the test constant to 219, so this is a separate file-equality drift).
- **mcp manifest registry (3)**: `test_openapi_cache_headers.py::test_mcp_server_manifest_returns_registry_payload` — `assert 'jpcite-mcp' == 'autonomath-mcp'`. The manifest payload migration is in progress: server.json carries the new `jpcite-mcp` id while the test still expects `autonomath-mcp`. Fix: update test, **not** the manifest (the PyPI package keeps `autonomath-mcp`, but the MCP-registry name is the rename target).
- **line_bot template (3)**: `test_line_bot.py::test_flow_revenue_to_results_renders_programs` — template now lists production programs (新創業融資 / 建設業 DX) instead of the UNI-test-* fixture rows. Seed-drift fingerprint again.

Bucket totals:

| Bucket | Records | Bucket share |
| --- | --- | --- |
| Category 1 — data drift | 38 | 41.8% |
| Category 2 — lang propagate | 6 | 6.6% |
| Category 3 — tool stub | 12 | 13.2% |
| Other (gh env / honesty / seo / prescreen StopIter / openapi / mcp manifest / line template) | 35 | 38.4% |
| **Total** | **91** | **100%** |

---

## C. Mock-heavy tests (top 5)

Memory CLAUDE.md SOT: "Never mock the database in integration tests — a past incident had mocked tests pass while a production migration failed."

The audit scans for `MagicMock` / `Mock()` / `@patch` / `mock.patch` directly (the `monkeypatch` pattern is acceptable when scoped to non-DB symbols). Top 5 by raw mock-construct count:

| Mocks | File | Risk |
| --- | --- | --- |
| 4 | `tests/test_pubcomment.py` | yellow — mocks HTTP client (acceptable, no DB) |
| 4 | `tests/test_post_deploy_smoke.py` | yellow — mocks `flyctl` subprocess (acceptable, no DB) |
| 4 | `tests/test_kokkai_shingikai.py` | yellow — mocks RSS HTTP fetcher (acceptable, no DB) |
| 3 | `tests/test_ingest_nta_invoice_bulk.py` | red — mocks ingest-side DB cursor; production migration drift would not be caught (CLAUDE.md "Never mock the database in integration tests" violated) |
| 3 | `tests/test_aggregate_production_gate_status.py` | yellow — mocks Fly status, deploy gate (acceptable, no DB) |

Beyond raw constructs, the more pervasive `monkeypatch.setattr` pattern (12,000+ uses across the suite) is the **larger production-divergence surface**. The `stub_resolver` in `test_wave24_endpoints_kwargs_filter.py` (Category 3) is the canonical example: it monkeypatches `_resolve_wave24_tool` so deeply that a resolver rename or refactor silently disables the test. Best fix is a `_real_tool_marker` fixture (W9-04 backlog item, **not yet added** in conftest.py — `grep _real_tool_marker tests/` returns 0 hits).

---

## D. Skip / xfail (top 5 dead-test risks)

Total `@pytest.mark.skip` or `@pytest.mark.xfail`: **14 sites**.

Of these, **8 are `skipif`** with a live runtime condition (`weasyprint installed`, `bs4 installed`, `pykakasi available`, `autonomath.db exists`, `AUTONOMATH_VEC0_PATH set`) — these are environmental gates and **not dead tests**.

The **5 unconditional `@pytest.mark.skip`** are the dead-test risk:

| File | Reason text | Re-open trigger |
| --- | --- | --- |
| `tests/test_revoke_cascade.py:189` | "billing-rewire blocker (R8 round 3, 2026-05-07): billing.keys.revoke_child_by_id does NOT spawn the daemon" | rewrite revoke_child_by_id to spawn daemon (open backlog) |
| `tests/test_offline_inbox_workflow.py:14` | "data-fix gate (R8 round 3, 2026-05-07): the 598-row source-profile JSONL backlog at tools/offline/_inbox/public_source_foundation/" | data-fix lands or backlog is closed (open) |
| `tests/test_redirect_zeimu_kaikei.py:173` | "Live HTTP probe — opt-in only. Requires the operator to have applied cloudflare-rules.yaml to the zeimu-kaikei.ai zone" | manual opt-in for live probe (not a defect; intentional opt-in marker) |
| `tests/test_consultant_monthly_pack.py:382` (`skipif` on `weasyprint`) | "WeasyPrint not installed in this environment" | install weasyprint locally |
| `tests/test_l4_cache_wire.py:340` + `:365` (`skipif` on `_AUTONOMATH_AVAILABLE`) | "autonomath.db not present or AUTONOMATH_ENABLED disabled" | autonomath.db mount on CI |

Of the 5 hard skips:
- 2 (`test_revoke_cascade.py`, `test_offline_inbox_workflow.py`) are **stale-since-2026-05-07** and tagged with a specific blocker — both have a re-open path through outstanding R8 work, but no one has reopened them.
- 1 (`test_redirect_zeimu_kaikei.py`) is **intentional opt-in** — keep skipped.
- 2 (`test_consultant_monthly_pack.py`, `test_l4_cache_wire.py`) are environmental — should be `skipif` not `skip` (one is already), and the CI workflow could install weasyprint to flip the consultant_monthly_pack one back to green.

---

## E. Tests added in the current session

Direct grep of `tests/conftest.py` for `_real_tool_marker` (the W9-04 backlog fixture): **0 hits**. The backlog item has not been added.

Comparing the test file count (`473`) against the test file count from the 2026-05-07 SOT (`tests/test_mcp_server_coverage.py` is the new 184-test file from R8_TEST_COVERAGE_DEEP commit `26e7397c`), the only post-5/07 test additions appear to be:

- `tests/test_a11y_baseline.py` — created 2026-05-11 10:34 (timestamp on `ls`). 1 test inferred from file size 1316 bytes.

No hotfix-driven test additions are visible on the redteam-hotfix branch or the critical-hotfix branch. The hotfix work appears to have been **production code only**, with tests untouched.

---

## Summary

- **Coverage hot-spots**: 22 API modules + 9 of the 10 largest source files have **no dedicated `test_<name>.py`**. The deep tool-internal layer (wave22/23/24 / intel_wave31 / ma_dd / composition_tools / envelope_wrapper) is 3 HTTP-layers away from any unit assertion. This is where any silent regression will hide.
- **91 fails fingerprint**: 35 unique × 3 Python runtimes ≈ 91. Three named categories cover 56 of 91 records (61.5%); the residual 35 break into 7 sub-clusters detailed above. The **largest single root cause is seeded-DB drift** (Category 1, 38 of 91, 41.8%) — fix order should be (a) lock conftest seed to UNI-test-* only, (b) flag autonomath.db-dependent tests with `skipif`, (c) cap the resolver-rename damage in wave24 tests with a marker fixture, (d) fix the legacy brand SEO bridge regression.
- **Mock risk**: only 1 file (`test_ingest_nta_invoice_bulk.py`) directly mocks the DB cursor; the broader risk is the 12k+ `monkeypatch.setattr` sites which couple tests to private symbol names. W9-04 `_real_tool_marker` fixture is the canonical mitigation and is **not yet added**.
- **Dead test budget**: 3 of 5 hard-`skip` tests are tagged with a specific re-open trigger (R8-2026-05-07) but no reopen activity is visible — these are slowly accruing as dead-test debt.
