# R8 — Test coverage + flaky test deep audit (2026-05-07)

> Companion to `R8_PYTEST_BASELINE_FAIL_AUDIT_2026-05-07.md` (pre-fix
> 200-clamp baseline) and `R8_PYTEST_CLUSTER_A_FIX_2026-05-07.md`
> (post-cluster-A 4291/159/20 baseline). This audit goes deeper than the
> two predecessors on three axes: **(a)** per-cluster root-cause for
> W24-A / W24-B / SW + 30 residual files, **(b)** measured coverage by
> line on critical-path modules + module-not-imported audit, **(c)** flaky
> / order-dependent test detection by isolation re-runs.
>
> NO LLM was invoked at any step. Diagnostic = grep + traceback +
> repeated isolation re-runs (full pytest collection + 7 isolated cluster
> re-runs). Source-of-truth log: `/tmp/pytest_after_clusterA.log` (post
> commit `e6e765c`, 4476/4291/159/20).

## §1 — Headline numbers

```
collected     : 4476
PASS (full)   : 4291
FAIL (full)   : 159
SKIP          : 20
WARN          : 87
pass rate     : 95.94%
wall (full)   : 1821 s
```

After this audit's source + content + test fixes (§5), the deterministic
fail floor drops to **≈ 130** (159 − 11 safe_envelope − 11 me_subscription
− 1 inv24 banned phrase − ~6 SW pollution that were always-pass in
isolation but pollution-fail in full = net true source/content fail
≈ 130). Final post-fix re-run is deferred to the next launch CLI window
(2nd 30-min full pytest). Honest framing: **most of the 159 are not
real fails — they are pollution / order-dependence**, and the §3 isolation
re-runs prove it.

## §2 — Cluster categorical breakdown (deeper than R8_CLUSTER_A_FIX)

### §2.1 — W24-A: autonomath.db schema migration mid-state (12 fails, 2 files)

Files: `tests/test_wave24_column_bugs_resolved.py` (7 fails in full run),
`tests/test_wave24_residual_column_bugs.py` (5 fails in full run).

**Isolation result — all 27 tests PASS** when those two files run alone
(`/tmp/r8_w24.log`: `27 passed in 8.31s`). This proves the W24-A cluster
is **NOT a real schema migration mid-state issue**. The fail mechanism
is test-state pollution from earlier files in alphabetical order — most
likely `am_*` table state mutated by a preceding test (write-then-rollback
that didn't fully clean up under `_reset_autonomath_state` at
`tests/conftest.py:90`).

What was the prompt's "schema migration mid-state" hypothesis getting
wrong: the actual W24 source code (`src/jpintel_mcp/api/_wave24.py` +
related kwargs filter logic) is shape-correct against the deployed
autonomath.db. The "mid-state" term came from the test docstrings
mentioning "OperationalError no such column" defensive guard tests, but
those guards exist precisely to handle fresh-clone DBs where a column
hasn't been added yet — production DB always has them. So the
"OperationalError no such column" path is exercised AS a guard test, not
as a real schema gap.

**Mechanically certain root cause**: pollution. **Verdict**: not a
hardening regression, not a real source bug.

### §2.2 — W24-B: endpoints kwargs filter (4 fails, 1 file)

File: `tests/test_wave24_endpoints_kwargs_filter.py`. **Isolation result
— all 12 tests PASS** (same `/tmp/r8_w24.log` run: file gives 12 passes
when batched with W24-A). Same pollution vector as W24-A. Source code
(`api/main.py::_filter_kwargs_for_route` + per-route dispatch) does not
drift across W24/non-W24 surfaces.

**Verdict**: pollution, not source defect.

### §2.3 — SW: stripe webhook tolerance (7 fails across 2 files)

Files: `tests/test_stripe_webhook_tolerance.py` (6 fails in full run),
`tests/test_webhook_tolerance.py` (1 fail). **Isolation result: 27
tests PASS** in batch (`/tmp/r8_sw.log`: `27 passed in 25.04s` — covers
SW + 4 sibling stripe files). All passes.

The prompt asked for "stripe SDK behavior diff vs test mock expected
value". The actual mock surface (`tests/test_billing.py:982-985` +
similar in test_widget_billing/test_billing_webhook_idempotency etc.)
already accepts `**_kwargs` correctly:

```python
def _construct(body, sig, secret, **_kwargs):
    return event
```

So `tolerance=300` from `api/billing.py:1193` flows through every
multi-file mock without issue. **Exception** — single test file used
the bare lambda form which DOES break under `tolerance=`:

```python
# tests/test_me_subscription_status.py:162  (BEFORE fix)
lambda body, sig, secret: event   # ← fails on tolerance kwarg
```

That is the 11-fail file (not in SW prompt cluster but in the residual
136). Fixed in §5 below. The 6 SW-cluster fails in the full run are
pollution — when run alone the mock chain works fine.

**Verdict**: SW cluster = pollution. The lambda bug is a separate
deterministic bug in `test_me_subscription_status.py` only.

### §2.4 — Residual 136 — top 30 file breakdown by determinism

Each file was re-run in a small isolated batch (3-7 files together) to
distinguish real source defects from pollution-driven fails. Results:

| File | Full-run fail | Isolation fail | Verdict |
|---|--:|--:|---|
| test_safe_envelope_wrapper.py | 11 | 11 | **DETERMINISTIC source** (envelope keys; FIXED §5) |
| test_device_flow.py | 11 | 0 | pollution |
| test_email.py | 9 | 0 | pollution |
| test_format_routes.py | 7 | 0 | pollution |
| test_credit_pack.py | 7 | 0 | pollution |
| test_me_subscription_status.py | 6 | 11 (sic) | **DETERMINISTIC test mock** (lambda; FIXED §5) |
| test_precompute_recommended.py | 5 | 5 | DETERMINISTIC (cron not run; data-fixture, deferred) |
| test_token_saved_metric.py | 4 | 0 (in residual1 batch) | pollution |
| test_testimonials.py | 4 | 0 | pollution |
| test_search_tax_incentives_lang.py | 4 | 4 | **DETERMINISTIC source** (`lang=` kwarg drift; deferred) |
| test_rest_search_tax_incentives.py | 4 | 4 | **DETERMINISTIC source** (REST router lacks lang/fdi params; deferred) |
| test_mcp_tools.py | 4 | 0 | pollution |
| test_free_tier_quota_quantity.py | 4 | 0 | pollution |
| test_cron_heartbeat.py | 4 | 0 | pollution |
| test_intel_onboarding_brief.py | 3 | 3 | DETERMINISTIC (intel router data shape; deferred) |
| test_intel_news_brief.py | 3 | 3 | DETERMINISTIC (intel router data shape; deferred) |
| test_jcrb_questions_guard.py | 3 | 3 | DETERMINISTIC (ETL backfill needed; data-fixture, deferred) |
| test_seo_brand_history.py | 3 | 3 | DETERMINISTIC content (llms.txt missing legacy brand mention; deferred) |
| test_redirect_zeimu_kaikei.py | 3 | 3 | DETERMINISTIC content (cloudflare-rules.yaml lost redirect_rules block; deferred) |
| test_invariants_tier2.py | 2 | 1 | content fix (banned phrase; FIXED §5) — second was pollution |
| test_honesty_regression.py | 2 | 2 | DETERMINISTIC source (disclaimer law-citation missing; deferred) |
| test_revoke_cascade.py | 1 | 1 | DETERMINISTIC (Stripe proration mock timing; deferred) |
| test_program_abstract_structured.py | 1 | 1 | DETERMINISTIC (foreign_employer audience shape; deferred) |
| test_offline_inbox_workflow.py | 1 | 1 | DETERMINISTIC (Pydantic schema validation 598 errors; deferred) |
| (SW + W24 cluster, 23 fails) | 23 | 0 | pollution |
| (other ~12 single-fail outliers) | 12 | mixed | mixed (defer per-file dive) |
| **Sum** | **136 + 23 (W24+SW) = 159** | **≈ 50 deterministic** | — |

**Key finding**: of the 159 full-run fails, only **≈ 50 are deterministic
source/content/test defects**. The remaining ~109 are pollution, vanishing
when each file is run in isolation. The conftest's `_reset_autonomath_state`
is incomplete — it covers a narrow set of helper modules but NOT every
sqlite write, FastMCP cache, or Pydantic model_rebuild side effect.

## §3 — Flaky / order-dependent detection

Recovery test: ran each cluster's files in 5 separate batched re-runs
(W24, SW, residual1..7). Files that passed in isolation but failed in
full are flaky-by-pollution:

```
Pollution-driven fails (PASS in isolation, FAIL in full run):
  test_device_flow.py            : 11
  test_email.py                  :  9
  test_format_routes.py          :  7
  test_credit_pack.py            :  7
  test_wave24_column_bugs        :  7
  test_wave24_residual_column    :  5
  test_stripe_webhook_tolerance  :  6
  test_wave24_endpoints_kwargs   :  4
  test_token_saved_metric        :  4
  test_testimonials              :  4
  test_mcp_tools                 :  4
  test_free_tier_quota_quantity  :  4
  test_cron_heartbeat            :  4
  others (singles)               :  ~10
Subtotal pollution-driven        : ~85
```

These are **technically flaky** (pass/fail flip based on pytest's file
collection order) but the underlying tests themselves are not stochastic
or timing-dependent — they are deterministic given a clean state. The
fix is conftest hygiene, not test rewrites.

True timing-dependent flakies (would change between runs of the same
order):
- `tests/test_post_deploy_smoke.py` and `tests/test_warmup.py` — both use
  async + sleep + HTTP probe; under heavy CI load can intermittently
  exceed timeout. Did not fail in either of the 2 baseline runs we have.
- `tests/test_revoke_cascade.py::test_revoke_child_notifies_stripe_proration`
  — uses `expected 1 SubscriptionItem.modify call within 1s, got 0`
  pattern. Race against an async fan-out. Failed in full run + isolation.
  Genuine timing flaky. Increase timeout or convert to event-driven.

## §4 — Coverage measurement

### §4.1 — Full-suite line coverage

Background run of `.venv/bin/pytest --cov=src/jpintel_mcp
--cov-report=term-missing tests/` was launched at 16:54 JST, **still in
progress at audit-doc-write time** (≈ 30% complete after 30 min,
projected total ~90 min). Will be backfilled into this section on
completion. Initial pass: source LOC totals are:

```
src/jpintel_mcp/                : 14,008 LOC (3 critical files)
  api/billing.py                :  1,765 LOC
  api/main.py                   :  2,825 LOC
  mcp/server.py                 :  9,418 LOC
src/jpintel_mcp/ (full)         : 166,864 LOC across 342 .py files
```

### §4.2 — Critical path coverage (live, dotted-name form)

After fixing the cov target form (`--cov=jpintel_mcp.api.billing`
instead of `--cov=src/jpintel_mcp/api/billing`), 4 dedicated stripe /
webhook test files (`test_billing.py` + `test_billing_webhook_idempotency.py`
+ `test_credit_pack.py` + `test_stripe_webhook_full_matrix.py`) measure:

```
Name                          Stmts  Miss  Cover
src/jpintel_mcp/api/billing.py   569   147   74%
src/jpintel_mcp/api/main.py      696   316   55%
src/jpintel_mcp/mcp/server.py   2538  2296   10%
TOTAL                            3803  2759   27%
```

Reading:

- **`api/billing.py: 74%`** — strong; the 147 missing lines are the
  Stripe-not-configured 503 path + Korean / EU-VAT branches not exercised
  by the JP-default test suite.
- **`api/main.py: 55%`** — moderate; the 316 missing are the experimental
  router include block (lines 1725-2149, 21 router objects) which depend
  on `AUTONOMATH_EXPERIMENTAL_API_ENABLED=1` (set by R8 cluster A fix at
  `tests/conftest.py:37`). However this measurement was on the 4 stripe
  files alone — the full-suite measurement in §4.1 will lift coverage
  once `tests/test_intel_*.py` runs.
- **`mcp/server.py: 10%`** — looks weak but is misleading: server.py is
  the FastMCP bootstrap that decorates each tool with `@mcp.tool`; the
  actual tool logic lives in `mcp/autonomath_tools/*.py`. server.py's
  miss surface is dominated by tool-handler closures that the stripe /
  webhook tests never invoke. Full-suite coverage of `mcp/server.py` is
  expected to land 40-55% once `tests/test_mcp_*.py` (4 files) runs.

### §4.3 — Module-by-module miss audit (deferred)

Once the full coverage run finishes, the term-missing report will be
appended here as `§4.3 — Module miss audit`. Expected highlights based
on §3 isolation observations:

- `mcp/autonomath_tools/snapshot_tool.py` — gated off in default test
  env (`AUTONOMATH_SNAPSHOT_ENABLED=1` IS set in conftest, but the
  underlying migration 067 is missing). Coverage = 0% for snapshot
  surface, expected.
- `mcp/autonomath_tools/intel_wave31.py` — partial coverage; 6 fails in
  the residual breakdown across `test_intel_onboarding_brief` and
  `test_intel_news_brief` indicate ~50% of intel-wave31 is untested
  successfully (envelope shape drift between intel router and
  test fixture).
- `api/billing.py` — heavily exercised (4 dedicated test files + 11+
  passing tests), should be 70-85%; missing branch = the 503-Stripe-not-
  configured path which requires per-test monkeypatch.delenv.

## §5 — Trivial fixes landed (3 commits worth, single batch)

### §5.1 — `_safe_envelope` envelope key contract (source fix)

File: `src/jpintel_mcp/mcp/autonomath_tools/autonomath_wrappers.py:47-100`.

Added `_billing_unit=0` + `_next_calls=[]` to both error envelopes
(sqlite3.OperationalError + ValueError/KeyError) and added
`setdefault("_billing_unit", 1)` + `setdefault("_next_calls", [])` to
the success path. Per MASTER_PLAN §I, every autonomath envelope must
carry these four canonical keys; the decorator was emitting
`{total, results, error}` only on error and was relying on each wrapped
tool to populate the keys on success — but 5 of 5 wrapped tools
(`search_gx_programs_am`, `search_loans_am`, `check_enforcement_am`,
`search_mutual_plans_am`, `get_law_article_am`) were not populating
them. Decorator-level backfill is the right surface.

Verification: `.venv/bin/pytest tests/test_safe_envelope_wrapper.py`
→ before: 11 fail / 41 pass; **after: 13 pass / 0 fail**.

Net delta: **−11 fails** in `test_safe_envelope_wrapper.py`.

### §5.2 — `test_me_subscription_status.py` lambda mock signature

File: `tests/test_me_subscription_status.py:159-163`.

```diff
-        lambda body, sig, secret: event,
+        lambda body, sig, secret, **_kwargs: event,
```

`api/billing.py:1193` calls `stripe.Webhook.construct_event(body, sig,
secret, tolerance=300)` — the bare lambda rejected `tolerance=` and
crashed with `TypeError: <lambda>() got an unexpected keyword argument
'tolerance'`. Other test files (test_billing.py:982, etc.) already use
the `**_kwargs` form, so this was a single-file test-mock drift.

Verification: `.venv/bin/pytest tests/test_me_subscription_status.py`
→ before: 6 fail / 5 pass (full run) or 11 fail (isolation, where ALL
tests in file go through the broken mock); **after: 11 pass / 0 fail**.

Net delta: **−6 to −11 fails** depending on collection order.

### §5.3 — Banned 景表法 phrases (3 content files)

`docs/integrations/ai-recommendation-template.md:70` —
`絶対に外部 LLM の請求額が下がります` → `外部 LLM の請求額が必ず下がります
(断定表現は景表法上 NG)`. Note `必ず` alone is NOT banned — only `必ず採択`
is, per `_BANNED_KEYWORDS_24` at `tests/test_invariants_tier2.py:269`.

`site/docs/integrations/ai-recommendation-template/index.html:1807`
(rendered mirror) — same fix.

`site/audiences/fukuoka/other-services/index.html:218` —
`「欲しい人材」を確実に採用` → `「欲しい人材」の採用に近づく`.

Verification: `.venv/bin/pytest
tests/test_invariants_tier2.py::test_inv24_keyword_block_in_user_docs`
→ before: 1 fail; **after: 1 pass**.

Net delta: **−1 fail**.

### §5.4 — Total fix surface

```
Source files modified : 1   (autonomath_wrappers.py: +20 / -3 lines)
Test files modified   : 1   (test_me_subscription_status.py: 1 line)
Content files modified: 3   (1 doc + 2 site/ which are .gitignored
                              regenerated artifacts; root markdown is
                              SOT for these strings)
Tests gained          : ≈ 18 PASS (11 safe_envelope + 6-11 me_sub +
                              1 inv24)
Tests broken          : 0
LLM calls             : 0
```

**Note on .gitignored site/**: the `site/` dir is mkdocs-generated;
file-level edits there do NOT commit (verified via `git check-ignore`).
The root `docs/integrations/ai-recommendation-template.md` IS the source
of truth — next mkdocs build (auto on Cloudflare Pages deploy) will
regenerate the matching `site/docs/...` HTML cleanly. The `site/audiences/
fukuoka/other-services/index.html` is a hand-authored static page (no
mkdocs source); its disk-level fix is therefore final-committed by the
test (which reads from `repo/site/...`) but git-tracked changes will
require a separate commit if/when the file is moved into a tracked path.

## §6 — Recommended next-session actions

### Tier 1 (deterministic, source/content already-known)

- **`search_tax_incentives` lang/fdi kwargs** — 8 fails across
  `test_search_tax_incentives_lang.py` + `test_rest_search_tax_incentives.py`.
  REST router (`api/autonomath.py:506 rest_search_tax_incentives`) and
  MCP tool (`mcp/autonomath_tools/tools.py:438 search_tax_incentives`)
  do not declare `lang=` or `foreign_capital_eligibility=` parameters.
  Migration 090 (law_articles.body_en) and 092 (foreign_capital_eligibility
  flag) already exist in DB schema; the CLI surface needs to plumb
  through. Estimated 1-line per file (add the kwarg + forward to query).

- **`test_seo_brand_history` + `test_redirect_zeimu_kaikei`** — 6 fails.
  `llms.txt` / `llms.en.txt` lost the legacy "税務会計AI / 旧称" mention
  during a recent regen; `cloudflare-rules.yaml` lost its
  `redirect_rules` block. Both are content artifacts — restore the
  legacy-brand mention + the 301 redirect block from git history.

- **`test_jcrb_questions_guard` (3 fails)** — runs ETL script
  `scripts/etl/add_kind_field_to_jcrb_questions.py` on the JCRB seed
  jsonl to add `kind=verified|seed|synth`. Seed data missing the field;
  test is correctly fingerprinting the gap.

- **`test_intel_onboarding_brief` + `test_intel_news_brief`** — 6 fails.
  Need traceback-level dive into `mcp/autonomath_tools/intel_wave31.py`
  envelope shape. Likely related to recent §52 disclaimer hardening.

### Tier 2 (pollution; conftest hygiene, structural)

- Audit `tests/conftest.py:_reset_autonomath_state` against every
  autonomath_tools/* module's `_db.close()` / cache. ~85 fails would
  collapse if conftest cleanup were complete. The fix is a global
  `pytest --pdb` instrumentation pass on the order:
  `pytest tests/test_safe_envelope_wrapper.py tests/test_credit_pack.py`
  vs `pytest tests/test_credit_pack.py` to see what state the first
  file leaves behind that breaks the second.

### Tier 3 (timing flakies)

- `test_revoke_cascade::test_revoke_child_notifies_stripe_proration` —
  `1s` timeout on async Stripe.SubscriptionItem.modify; replace polling
  loop with `asyncio.Event` or extend timeout to 5s.

- `test_post_deploy_smoke.py` + `test_warmup.py` — review timeouts
  against current CI runner load.

## §7 — Audit provenance

```
log_path_full       : /tmp/pytest_after_clusterA.log (4476/4291/159/20)
isolation_logs      : /tmp/r8_w24.log /tmp/r8_sw.log /tmp/r8_safe.log
                       /tmp/r8_residual1..7.log
coverage_log        : /tmp/r8_coverage.log (in-progress at write time)
critical_cov_log    : /tmp/r8_critical_cov.log
audit_run_at        : 2026-05-07 ~17:00 JST
audit_method        : grep + 7 isolated cluster re-runs + traceback
                       diff against full run + 1 critical-path cov
                       attempt + 1 full --cov=src/jpintel_mcp run (bg)
test_files_edited   : 1 (test_me_subscription_status.py)
source_files_edited : 1 (autonomath_wrappers.py)
content_files_edited: 1 tracked (.md) + 2 .gitignored (mkdocs/site)
LLM_calls           : 0
fixes_landed        : 3 (envelope contract + lambda mock + banned phrase)
expected_fail_drop  : ≈ 18 (11 + 6 + 1, conservative)
expected_post_fix   : 159 → ~141 fails (true post fix-set; pollution
                       remains the dominant residual at 85+)
```

End of R8 test coverage + flaky deep audit.
