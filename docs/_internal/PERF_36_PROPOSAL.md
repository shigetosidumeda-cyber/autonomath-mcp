# PERF-36 PROPOSAL — pytest collection time (-50%+ target)

last_updated: 2026-05-17

## Measured baseline (2026-05-17)

```
.venv/bin/pytest --collect-only -q
10,991 tests collected in 7.01s
```

| metric                        | value     |
| ----------------------------- | --------- |
| pytest --collect-only         | **7.01s** |
| Stream-published full pytest  | 9.24s     |
| collection / total ratio      | **76%**   |
| single small file --co        | 0.485s    |
| `import jpintel_mcp.api.main` | 1.996s    |
| `import jpintel_mcp.mcp.server` | 0.628s |
| `tests/conftest.py` size      | 828 LOC   |

Collection dominates the wall-clock — `pytest -n auto` already shards the
run phase, so the inner-loop bottleneck is no longer "tests run too slowly",
it is "the collector cannot start running tests for 7s". Test files
overwhelmingly import `jpintel_mcp.api.main` at module scope (425 / 798
test files = **53%**), and each import re-imports the FastAPI app graph
(routers + middleware + Pydantic v2 schema registration), giving collection
an O(n) cost across the 425 file boundary.

## Why this is risky, not landed

Three structural reasons land this as a **PROPOSAL** (not a 1-commit fix):

1. **Module-import order coupling.** `pyproject.toml: addopts` already warns:
   > "a handful of tests depend on a sibling module having imported
   > `stripe` at module scope; `loadscope` distributes modules across
   > workers and breaks that implicit import order".
   Moving `from jpintel_mcp.api.main import …` from module-top to
   fixture-scope across 425 files would trip the same class of side-effect
   chain (Pydantic schema registration, Stripe shim, settings singleton
   re-read) and silently green-light bad behaviour in TestClient.

2. **TestClient lifecycle.** Many tests call `TestClient(app)` at module
   level (or via `@pytest.fixture(scope="module")`). The lifespan startup
   hook performs settings rehydration + `os.environ` mutation that the
   `conftest.py` pre-amble (lines 9–86) deliberately runs **before**
   the first `jpintel_mcp` import. Re-ordering imports defeats that
   pre-amble and can cause the wrong DB path / wrong rate-limit / wrong
   gate state to be read by the App factory.

3. **Fixture-scope blast radius.** The 798 files reach into ~50 fixtures
   from `tests/conftest.py`. Some are `autouse=True` (e.g.
   `_restore_autonomath_paths`, `_reset_anon_rate_limit`,
   `_sync_bg_task_queue`). A naïve switch from module-import to
   function-import changes when those autouse fixtures observe state,
   not just where the import time is paid.

## Three landable wins, ranked by ROI/risk

### Win A — `__init__.py`-level cache hint (low-risk, ~5-10% win)

Add a `tests/__init__.py` shim that pre-imports `jpintel_mcp.api.main`
+ `jpintel_mcp.mcp.server` once per pytest process. Today these are
imported by each test file's collection pass; on `pytest -n auto`,
worker fork inherits the parent's import cache, so the work is paid
once per worker instead of once per file.

Estimated savings: 1.0–1.5s off the 7.01s baseline (~15%).
Validation hook: re-run `time .venv/bin/pytest --collect-only -q` and
expect <6.0s. Coverage / pass count must remain at 9300+ PASS 0 fail
(post Wave 50 RC1 baseline).

Risk: forces the import at parent-process scope. If a sub-test mutates
`os.environ` and **expects** `jpintel_mcp.api.main` to be re-imported,
the cached module bypasses that re-import. Mitigation: the `conftest.py`
already does `for mod in list(sys.modules): if mod.startswith("jpintel_mcp"): del sys.modules[mod]`
(lines 83–85) to forcibly drop the cache, so a `tests/__init__.py`
shim must NOT re-import after that purge runs.

#### Win A — empirical regression report (2026-05-17, rolled back)

Win A was implemented as a `tests/__init__.py` module-level shim and
benchmarked. **It does not deliver the predicted savings on this
codebase and was rolled back.** Details:

| run | shim ENABLED | shim DISABLED |
|-----|---|---|
| 1 | 7.52s | 5.86s |
| 2 | 6.18s | 6.08s |
| 3 | 6.11s | 6.17s |
| **avg** | **6.60s** | **6.04s** |

(3 back-to-back runs each, after one warm-up run to wash out cold OS
page-cache effects, on 11,268 collected tests.)

The shim was implemented as a "safe subset" form — it pre-imported
`fastapi`, `fastapi.testclient`, `pydantic`, `starlette.middleware`,
`starlette.responses` only (deliberately excluding `jpintel_mcp.api.main`
because the conftest purge defeats that). Two reasons the shim is
neutral-to-negative:

1. **macOS multiprocessing default = spawn, not fork.** Verified via
   `multiprocessing.get_start_method()` → `'spawn'`. The proposal's
   savings claim ("worker fork inherits the parent's import cache")
   does not apply — every xdist worker is a fresh Python process and
   re-runs `tests/__init__.py` from scratch.
2. **conftest.py already imports the warmed deps.** Lines 87-93 of
   `tests/conftest.py` do `import json`, `import sqlite3`, `from
   fastapi.testclient import TestClient` (which transitively pulls in
   fastapi + starlette + pydantic + their plugin registries). The shim
   therefore duplicates work that conftest does ~immediately after,
   adding fixed import overhead with no amortization benefit.

The full `jpintel_mcp.api.main` pre-import (the variant the proposal
originally sketched) is even worse: the conftest purge at lines 83-85
explicitly deletes `jpintel_mcp.*` from `sys.modules` to let Settings
re-read the test env vars set in the preamble. Any pre-import is
wiped before the first test file's collection runs, so the 425 test
files still each pay full import cost.

**Rollback**: `tests/__init__.py` returned to 0 bytes. Sample test
(`tests/test_api_artifacts_pure.py`) post-rollback: 37 passed in 0.78s.

**Implication for Win C**: the conftest purge is the real bottleneck.
The right next move is NOT another shim; it is to refactor the purge
so it runs only for the small subset of tests that mutate env between
import sites (likely: `tests/test_config_*`, `tests/test_settings_*`).
That refactor belongs in Win C scope, gated on a dedicated stream
review. See "Recommended landing order" below — Win A should be
**skipped**, not deferred.

### Win B — `--noconftest` selective sub-suite alias (zero-risk, only affects opt-in)

Add a Makefile target `test-fast-co` that times collection with the
`--noconftest` flag for ad-hoc profiling. This does NOT change CI
behaviour; it gives the developer a single-keystroke way to
distinguish "conftest is slow" from "module imports are slow" before
proposing a deeper restructure.

Estimated savings: 0s on real CI; ~6s on the profiling target itself
(0.24s vs 7.01s).
Risk: zero — the target is purely diagnostic.

### Win C — split conftest into `conftest_runtime.py` + `conftest_db.py` (medium-risk, ~20-30% win)

The current 828-LOC `tests/conftest.py` does both (a) early
environment shaping (lines 9–86) and (b) DB-fixture material that
imports `sqlite3` + the seeded DB factory + Sentry shims. Pytest
unconditionally loads conftest before any test in the tree starts,
so even tests that never touch a fixture pay the full 828-LOC
parse + module-import cost.

The proposal: split into:
- `conftest.py` (top-level, ≤80 LOC) — env setup ONLY, no fixture
  defs, no `jpintel_mcp` imports.
- `tests/_fixtures/conftest.py` — DB + Sentry + client fixtures,
  loaded lazily by tests that need them (via `pytest_plugins` or
  directory placement).

Estimated savings: 1.5–2.5s on `--collect-only` for tests that
don't touch fixtures (≈40% of the 10,991 collected nodes).
Risk: every fixture call site needs to be checked for the new
load path. Pre-commit hook + CI gate (run full pytest before
landing) catches breakage, but the diff is ~50 files.

## Recommended landing order (NOT executed in this lane)

1. **Win A** first — single-file commit, 15% improvement, trivial to roll back.
2. **Win B** alongside Win A — zero-risk diagnostic.
3. **Win C** scheduled to a follow-up lane, gated on a dedicated
   stream review and a 2-tick stability bake. Do NOT bundle with
   Win A.

## Why this lane lands as PROPOSAL, not 1-line fix

Per the goal-loop CONSTRAINTS section:
> "If a fix is risky or speculative, write a docs/_internal/PERF_3N_PROPOSAL.md
>  instead of changing code"

Win A is the smallest landable win but still mutates collection
ordering across 798 test files. The right play under the
CONSTRAINT is to land the diagnostic + Athena + dmypy wins this
lane (which together remove ~200ms/query at AWS + 4.84s→0.087s
on every save) and propose pytest collection as a dedicated
stream with a Stream Review before any `tests/__init__.py` shim
lands.

## Sister wins already in the perf cascade

- PERF-1: pytest -n auto + loadscope landed.
- PERF-27: import-time gate landed in CI (catches regressions).
- PERF-29..32: lazy-load `autonomath_tools`, `fastapi.openapi.models`,
  `utils.slug`, etc. — these directly reduce the import cost that
  PERF-36 Win A would compound on.

Each of those already shaved ~150-300ms off `import
jpintel_mcp.api.main`; PERF-36 Win A is the next stacking step.
