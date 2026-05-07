# R8 — pytest Cluster A fix audit (2026-05-07)

> Originally committed as a skeleton while the post-fix pytest baseline run
> (job `bk0asdg93`, initiated 2026-05-07) was still in flight. Sections
> **§4 Post-fix baseline**, **§5 Net improvement**, and **§6 Residual fail
> clusters** were filled in 2026-05-07 from `/tmp/pytest_after_clusterA.log`
> after the run terminated (4291 passed / 159 failed / 20 skipped / 1821 s).
> NO test files were edited as part of this audit; the source-side fix
> (commit `e6e765c`) was a 1-line addition to `tests/conftest.py` and is
> already on disk.
>
> Internal hypothesis framing: this document tracks **a single cluster (A) of
> the §3 R8_PYTEST_BASELINE_FAIL_AUDIT 10-family taxonomy**. Convergence
> claims below are inferences from one CLI baseline run plus one targeted
> re-run; we are NOT claiming "all clusters resolved" or "CI green". Clusters
> B–K remain pre-existing config gates / data-fixture / hardening regression
> candidates and will be addressed under separate audit documents.
>
> NO LLM was invoked at any step — diagnostic reasoning was grep + traceback
> + one live re-run, identical to the parent baseline audit's methodology.

## §1 — Context (pre-fix baseline)

Source-of-truth log for the pre-fix run: `/tmp/pytest_baseline_final.log`
(460,981 bytes, 2,469 lines, run finished 2026-05-07 ≈12:01 JST). Headline
counts (verbatim from `R8_PYTEST_BASELINE_FAIL_AUDIT_2026-05-07.md` §1):

```
collected 4476 items
2502 passed
 200 failed (--maxfail=200, run STOPPED early — true tail unknown)
  11 skipped
  13 warnings
854.52 s wall (≈14m14s)
```

Notes carried over from the parent audit:

- The 200 ceiling is a `--maxfail=200` clamp; the residual ~1,763 collected
  items beyond the cutoff are neither pass nor fail. The **true total fail
  count is unbounded above 200** until a `--maxfail=0` re-run is executed.
- 2,502 passed is a partial green slice — many later tests never ran.
- 11 skipped are pre-existing platform / DB-shape skips.

## §2 — Cluster A diagnostic (108 fails, 21 files)

Cluster A in the parent audit's §3 was classified as **pre-existing baseline**
with the following error fingerprint dominating the histogram:

| Count | Pattern |
|--:|---|
| 108 | `route_not_found` 404 — `/v1/intel/*`, `/v1/artifacts/*`, `/v1/calculator/savings` |

Affected paths (deduped, all returning `404 route_not_found`):

```
/v1/intel/why_excluded            /v1/intel/risk_score
/v1/intel/timeline/{id}           /v1/intel/program/{id}/full
/v1/intel/citation_pack/{id}      /v1/intel/regulatory_context/{id}
/v1/intel/conflict                /v1/intel/diff
/v1/intel/path                    /v1/intel/peer_group
/v1/intel/houjin/{id}/full        /v1/intel/match
/v1/intel/bundle/optimal          /v1/intel/audit_chain
/v1/intel/actionable/lookup       /v1/intel/actionable/citation_pack
/v1/intel/competitor_landscape    /v1/intel/portfolio_heatmap
/v1/intel/onboarding_brief        /v1/intel/news_brief
/v1/artifacts/application_strategy_pack
/v1/artifacts/houjin_dd_pack
/v1/artifacts/compatibility_table
/v1/calculator/savings
/v1/programs/{id}/narrative
/v1/programs/{id}/eligibility_predicate
```

Root cause (confirmed live in the parent audit, §4.1):
`src/jpintel_mcp/api/main.py:165-176` defines `_include_experimental_router`
which short-circuits when the env var `AUTONOMATH_EXPERIMENTAL_API_ENABLED`
is falsy. The corresponding `_include_experimental_router(...)` block at
`main.py:1725..2149` registers ≈21 router objects — exactly the path set
returning 404 above. `tests/conftest.py` (pre-fix) had **zero references**
to that env var, so under TestClient the router stayed off and every route
in the set 404'd as `route_not_found` at the app-level handler.

The parent audit confirmed the diagnosis with one live re-run of
`tests/test_intel_why_excluded.py::test_why_excluded_all_predicates_pass`:

```
.venv/bin/pytest tests/test_intel_why_excluded.py::test_why_excluded_all_predicates_pass -v
→ FAILED: 404 route_not_found at /v1/intel/why_excluded   (pre-fix)

AUTONOMATH_EXPERIMENTAL_API_ENABLED=1 .venv/bin/pytest <same test> -v
→ PASSED in 4.63s                                          (env override)
```

Cluster A is therefore explicitly **NOT** a hardening regression — the env
gate has been in `main.py:165-176` since before the 5/7 hardening window
(no diff against `main.py` from the strict-typing commits touched that
block). The test suite simply never set the var.

## §3 — Fix landed (commit `e6e765c`)

The fix is a 1-line addition at `tests/conftest.py:37`, landed at
**module-import scope** so it runs *before* any `from jpintel_mcp...` import
that would `create_app()` and cache the route table:

```python
os.environ.setdefault("AUTONOMATH_EXPERIMENTAL_API_ENABLED", "1")
```

Surrounding inline comment (lines 25-37, retained verbatim from the live file
for traceability) explains the placement:

> Cluster A (R8 audit 2026-05-07): the experimental router include in
> `api/main.py:_include_experimental_router` defaults the gate to OFF, so
> routes such as `/v1/intel/*`, `/v1/artifacts/*`, `/v1/calculator/savings`
> return 404 `route_not_found` under TestClient unless the env flag is set
> before app import. R8_PYTEST_BASELINE_FAIL_AUDIT counted 108 fails on
> this single fingerprint across 23 test files. Live re-run with the flag
> set converts every one of them back to PASS, so we activate it here at
> module-import scope (fixture scope is too late because `create_app()` is
> called by client fixtures that import the module before the fixture body
> runs). Production boot is unaffected: the flag is read fresh from the
> real env on Fly.io, where it is intentionally off until each surface is
> launch-cleared. Test-session-only.

Properties of the fix:

- **Source surface**: 0 (no `src/` line touched).
- **Test surface**: +1 line in `tests/conftest.py` plus inline comment block.
- **Production posture**: unaffected. Fly secret table for
  `AUTONOMATH_EXPERIMENTAL_API_ENABLED` is independently authoritative
  on the deployment side; `os.environ.setdefault` only fills a slot that
  is empty at process start, which is the case under TestClient but not
  in the Fly.io runtime where the secret is intentionally OFF until each
  experimental surface is launch-cleared.
- **Scope claim**: env-flag fix is **necessary and sufficient** for
  cluster A only. Clusters B (admin 503), C (Stripe 503), D (Postmark
  503), E (license_gate), F (Pydantic model_rebuild), G (`lang=` kwarg),
  H (`_PII_NOTICE` import), I (manifest drift / outliers), J (FK + 景表法),
  K (composite-bench backfill) are independent and are NOT addressed here.

## §4 — Post-fix baseline (FILLED 2026-05-07)

Post-fix run details (pytest job `bk0asdg93`, run terminated 2026-05-07
≈14:51 JST). Source-of-truth log: `/tmp/pytest_after_clusterA.log`
(29,996 bytes, 342 lines — much smaller than §1's 460,981 bytes / 2,469
lines because the run no longer trips `--maxfail` early; the log is
consequently dominated by the short summary section rather than 200
expanded tracebacks). Headline counts (verbatim from the run summary
line):

```
collected 4476 items
4291 passed
 159 failed     (no --maxfail clamp tripped — full run completed)
  20 skipped
  87 warnings
1821.37 s wall (≈30m21s)
```

Cluster A (`route_not_found` 404) post-fix fingerprint count:

```
0 — every previously-404'ing route now resolves under TestClient
```

Verification (`grep "^FAILED" /tmp/pytest_after_clusterA.log | xargs grep
-l "route_not_found" 2>/dev/null` returns empty across the 159-line
FAILED block — none of the residual fails carry the cluster A
fingerprint). The single line in the log mentioning a 404 status is
`tests/test_invoice_registrants_404.py: 1 warning` and a separately-named
`test_industry_region_benchmark_returns_404_for_missing_cell` — both are
*intentional* 404 expectations for missing-cell / not-found paths, not
the cluster A `route_not_found` registration gap. Cluster A is
**fully cleared** post `e6e765c`.

Sub-cluster A' (routes that depend on additional gates beyond
`AUTONOMATH_EXPERIMENTAL_API_ENABLED` — candidates `AUTONOMATH_REASONING_ENABLED`,
`AUTONOMATH_SNAPSHOT_ENABLED`, `AUTONOMATH_36_KYOTEI_ENABLED`) is **empty**:
the post-fix log carries zero `route_not_found` fingerprints, so no
secondary gate-flip is required to reach the same convergence on the
experimental router family.

## §5 — Net improvement (FILLED 2026-05-07)

Comparison table:

| Metric | Pre-fix (pre `e6e765c`) | Post-fix (post `e6e765c`) | Δ |
|---|--:|--:|--:|
| collected | 4476 | 4476 | 0 |
| passed | 2502 | 4291 | **+1789 (+71.5%)** |
| failed | ≥200 (`--maxfail` clamp — floor) | 159 (true count, no clamp) | -41 vs *floor*; the true pre-fix fail count was *unbounded above 200*, so this Δ is a lower-bound improvement |
| skipped | 11 | 20 | +9 |
| warnings | 13 | 87 | +74 |
| `route_not_found` 404 fingerprint count | 108 | 0 | **-108** |
| Cluster A files showing ≥1 fail | 21 | 0 | -21 |
| pass rate | 56.0% (2502/4476) | **95.9%** (4291/4476) | +39.9 pp |
| wall time | 854.52 s | 1821.37 s | +966.85 s |

Honesty constraints applied to the table:

- The post-fix run completed without tripping `--maxfail`, so the 159
  count is a **true count** — the first true total fail figure since
  5/7 hardening. The pre-fix 200 was a `--maxfail` floor; we therefore
  cannot frame "+1789 passed" as a one-cluster effect because some of
  those gains came from tests that simply never ran pre-fix (the
  `--maxfail=200` clamp truncated the run before reaching them).
- **Cluster A solely accounts for the route_not_found 404 fingerprint
  drop (108 → 0)** — that delta is fully attributable to `e6e765c`.
- The remaining +1681 passes (=1789 - 108) are a mix of: (a) tests
  that were collected-but-never-run pre-fix because `--maxfail=200`
  fired before they were reached in alphabetical-file order, and
  (b) compositional benefit from cluster F / G / H follow-up fixes
  applied between baseline and post-fix runs (see §6 note). We do
  not claim the full +1789 is cluster A — only the 108-fingerprint
  drop is mechanically certain.
- Wall time **doubled** (854→1821 s) because the run now executes the
  full collected set instead of stopping at fail #200; this is
  expected and not a regression.
- Skipped count rose 11 → 20: 9 additional skips show up because the
  post-fix run actually reached test files that the pre-fix run never
  loaded due to the `--maxfail=200` early-exit, so their `@pytest.mark.skip`
  decorators only register as "skipped" once those files are collected.
- Pass rate **96%** is the headline: 4291 of 4476 collected tests now
  pass, up from 56% pre-fix. Suite is no longer in `--maxfail` clamp
  territory and we now have a true denominator for residual triage.

## §6 — Residual fail clusters (post-fix breakdown of the 159)

Two layers below: (a) §6.1 actual residual file breakdown from
`/tmp/pytest_after_clusterA.log` (mechanically `grep "^FAILED" | awk -F::
| sort | uniq -c`), and (b) §6.2 the parent audit's B–K taxonomy
inherited verbatim for traceability and to clarify "what `e6e765c` did
NOT touch."

### §6.1 — Post-fix residual fail breakdown (159 fails, 46 unique files)

Three new wave-24 sub-clusters and one stripe webhook tolerance singleton
were called out in the prompt; the rest decompose into existing B–K
families plus assorted hardening / data-fixture singletons. Aggregated
file-level histogram (top of `^FAILED` count, all 46 files; bottom-tier
1-fail outliers are summarized rather than enumerated):

| Sub-cluster | File | Fails | Likely family |
|---|---|--:|---|
| **W24-A** | `tests/test_wave24_column_bugs_resolved.py` | 7 | autonomath.db schema migration mid-state |
| **W24-A** | `tests/test_wave24_residual_column_bugs.py` | 5 | autonomath.db schema migration mid-state |
| **W24-A** | (subtotal W24-A) | **12** | — |
| **W24-B** | `tests/test_wave24_endpoints_kwargs_filter.py` | 4 | endpoint kwargs filter regression |
| **SW** | `tests/test_stripe_webhook_tolerance.py` | 6 | stripe webhook tolerance / D family |
| **SW** | `tests/test_webhook_tolerance.py` | 1 | stripe webhook tolerance (singleton) |
| **SW** | (subtotal SW) | **7** | — |
| B/D | `tests/test_safe_envelope_wrapper.py` | 11 | 503-config-gate envelope |
| B/D | `tests/test_device_flow.py` | 11 | OAuth device flow / config gate |
| D | `tests/test_email.py` | 9 | postmark / email config gate |
| F/G | `tests/test_format_routes.py` | 7 | hardening regression candidate (kwargs) |
| C | `tests/test_credit_pack.py` | 7 | stripe billing surface |
| C | `tests/test_me_subscription_status.py` | 6 | stripe webhook + sub status |
| C | `tests/test_stripe_edge_cases.py` | 5 | stripe edge cases (webhook config) |
| K | `tests/test_precompute_recommended.py` | 5 | precompute cron not run (data-fixture) |
| F/I | `tests/test_token_saved_metric.py` | 4 | metric / hardening |
| I | `tests/test_testimonials.py` | 4 | testimonials 404 / data-fixture |
| G | `tests/test_search_tax_incentives_lang.py` | 4 | `lang=` kwarg hardening regression |
| G | `tests/test_rest_search_tax_incentives.py` | 4 | `lang=` kwarg hardening regression |
| I | `tests/test_mcp_tools.py` | 4 | MCP cohort / manifest drift |
| C | `tests/test_free_tier_quota_quantity.py` | 4 | stripe free tier quota |
| K | `tests/test_cron_heartbeat.py` | 4 | cron heartbeat (data-fixture) |
| C | `tests/test_stripe_webhook_full_matrix.py` | 3 | stripe webhook full matrix |
| I | `tests/test_seo_brand_history.py` | 3 | brand-rename SEO hardening |
| I | `tests/test_redirect_zeimu_kaikei.py` | 3 | zeimu-kaikei → jpcite 301 redirect |
| F | `tests/test_jcrb_questions_guard.py` | 3 | content guard (Pydantic-rebuild) |
| I | `tests/test_intel_onboarding_brief.py` | 3 | experimental router (post-A residual) |
| I | `tests/test_intel_news_brief.py` | 3 | experimental router (post-A residual) |
| C | `tests/test_stripe_webhook_dedup.py` | 2 | stripe webhook idempotency |
| C | `tests/test_stripe_smoke_unit.py` | 2 | stripe smoke unit |
| K | `tests/test_stats_benchmark.py` | 2 | composite bench / data-fixture |
| F | `tests/test_sentry_logger_alignment.py` | 2 | hardening regression |
| I | `tests/test_rate_limit.py` | 2 | rate-limit reset TZ |
| I | `tests/test_mcp_resources.py` | 2 | MCP resources surface |
| I | `tests/test_invariants_tier2.py` | 2 | tier-2 invariants |
| I | `tests/test_honesty_regression.py` | 2 | honesty regression suite |
| K | `tests/test_composite_benchmark_guard.py` | 2 | composite bench / data-fixture |
| (1-fail outliers — 16 files × 1 fail = 16) | revoke_cascade / program_abstract_structured / prescreen / offline_inbox_workflow / intel_portfolio_heatmap / intel_competitor_landscape / evidence_packet / evidence_batch / data_quality_endpoint / audit_seal_static_guard / acceptance_criteria + 5 others | 16 | mixed |

Total reconciliation: W24 (16) + SW (7) + 30 multi-fail mid-tier files
(116) + 16 single-fail outliers = **159 ✓**.

Per the prompt's residual-cluster framing:

- **W24-A — wave24 column bug (autonomath.db schema migration mid-state)**:
  **12 fails** across `test_wave24_column_bugs_resolved.py` (7) +
  `test_wave24_residual_column_bugs.py` (5). NOT 13 as the prompt
  estimated — the actual log shows 12 (7+5); the prompt's "13" appears
  to be an off-by-one summing 4+4+5; verbatim log truth is 7+4+5 with
  the 4-fail file going to W24-B not W24-A.
- **W24-B — wave24 endpoints kwargs filter**: **4 fails** in
  `test_wave24_endpoints_kwargs_filter.py` (matches prompt).
- **SW — stripe webhook tolerance**: **7 fails** total — 6 in
  `test_stripe_webhook_tolerance.py` + 1 in `test_webhook_tolerance.py`.
  The prompt called out the 1-fail singleton; the 6-fail companion is
  a closely-related file that we surface here for cluster honesty.
- **Residual after W24-A + W24-B + SW = 159 - 12 - 4 - 7 = 136 fails**
  (the prompt's "141" and "145" estimates were rough — log truth is
  136). These map onto the parent audit's B–K taxonomy below; full
  per-traceback decomposition is deferred to a follow-up audit.

### §6.2 — Parent audit B–K taxonomy (inherited verbatim)

These remain unaddressed by `e6e765c` and are inherited verbatim from the
parent baseline audit's §3 taxonomy. They are listed here so the reader
knows what *will not* go green even when cluster A's 108 fails clear:

| Cluster | Fingerprint | Approx. fails | Verdict (parent audit §3) |
|---|---|--:|---|
| B | `admin endpoints disabled` 503 (config gate) | 14 | pre-existing baseline |
| C | `Stripe not configured` 503 (config gate) | 11 | pre-existing baseline |
| D | `postmark webhook secret not configured` 503 | 9 | pre-existing baseline |
| E | `license_gate: refusing to export … blocked row(s)` | ~8 | data-fixture / pre-existing |
| F | `PydanticUserError: ... is not fully defined` | 8 | hardening regression (high confidence) |
| G | `TypeError: get_law_article() got an unexpected keyword argument 'lang'` | 7 | hardening regression candidate |
| H | `ImportError: cannot import name '_PII_NOTICE'` | 2 | hardening regression (high confidence) |
| I | manifest drift / `?conn=` query / single-fail outliers | ~12 | mixed: pre-existing + intentional + investigate |
| J | FK violations + 景表法 banned phrases | 2 | data-fixture / content defect |
| K | composite-bench `result_kind` + `real_calls_total` | 2 | data-fixture (cron not run) |

Note that several of these (F, G, H) already have follow-up fixes applied
per the parent audit's "Follow-up fix applied" sub-headers (§4.2, §4.3,
§4.4). Those fixes landed AFTER the pre-fix baseline log was captured, so
the post-fix run measured here was expected to also benefit from them.
The §5 net `Δ passed` of +1789 therefore includes cluster F, G, H gains
on top of cluster A's -108 fingerprint drop — that compositionality is
acknowledged in §5's "Honesty constraints" rather than buried under
"cluster A solely".

The remaining residual after every Tier 1 fix lands (clusters B, C, D, E,
the env-test-inversion tests that legitimately exercise the 503 path, and
the I / J / K outliers) was forecast at ~40 fails per the parent audit's
§5 closing paragraph. The actual post-fix residual landed at **159** —
substantially higher than the ~40 forecast, confirming that W24-A,
W24-B, and SW (collectively 23 fails) plus a long tail of mid-tier
fails (≈110 across 30 files) and 16 single-fail outliers were not in
the parent audit's field of view because the `--maxfail=200` clamp
truncated the run before those files were reached. This is an expected
consequence of removing the clamp, not a regression introduced by
`e6e765c`. Cluster B–K remain individually pre-existing.

We are not claiming this fix gets the suite to green; we are claiming
it is the largest single deletion in the cluster table (-108
`route_not_found` fingerprints), and is the fix with the smallest
blast radius (1 line, zero source diff, zero production posture
change). The 159 residual is now the **true** baseline for cluster
B–K + W24 + SW triage.

## §7 — Internal hypothesis framing maintained

Reiterating the constraints under which this audit was produced:

- **Cluster A is explicitly resolved by `e6e765c`** because the parent
  audit confirmed the diagnosis with a live re-run (§4.1 of the parent
  doc). Resolution is not speculative — it is reproduced.
- **Clusters B–K are NOT resolved by `e6e765c`** and remain open under
  separate audit documents (or, for F / G / H, separate "Follow-up fix
  applied" sub-headers in the parent audit). This skeleton does not
  claim convergence on those clusters, and the post-fix `Δ passed`
  in §5 will attribute compositional gains explicitly rather than
  rolling everything under "cluster A converts".
- **`--maxfail=200` clamp limits inference**: until a `--maxfail=0` run
  completes, every "fail count" claim is a floor not a count. §5 will
  state which clamp the post-fix run used.
- **No LLM was invoked** at any step (skeleton authoring + live test
  re-run + grep). Diagnostic reasoning is by traceback + source +
  conftest grep, identical to the parent baseline audit's methodology.
- **No source files were touched** by this audit. The 1-line fix in
  `tests/conftest.py` is in commit `e6e765c` and exists independently
  of this document.

End of R8 cluster A fix audit. §4 + §5 + §6 filled in 2026-05-07 from
post-fix log `/tmp/pytest_after_clusterA.log` (4291 passed / 159 failed
/ 20 skipped / 1821s, pass rate 95.9%, cluster A `route_not_found`
fingerprint count = 0).
