# PERF-20: continuous perf bench + regression gate runbook (2026-05-16)

Status: LANDED 2026-05-16. Consolidates the existing perf gate tests
(PERF-7 / PERF-11) under `tests/perf/` and adds a CI workflow that
runs them on demand + weekly, captures a JSON ledger, and posts a
Markdown summary with regression detection vs the previous `main`
baseline.

`[lane:solo]` marker per CLAUDE.md dual-CLI lane convention.

## Why this exists

- Two perf gate tests already shipped (`tests/perf/test_api_p95_budget.py`
  from PERF-7, `tests/perf/test_packet_gen_perf.py` from PERF-11), but
  each was hand-run with `JPCITE_RUN_PERF_GATES=1` / `--runperf`. There
  was no continuous regression detection — a slowdown introduced in
  week N would only get caught when an operator remembered to re-run.
- The Wave 50 deploy-readiness gates + CLAUDE.md cost discipline call
  out "Don't run perf on every PR" — the suite drives 100+ sequential
  in-process calls + 5K synthetic packet renders per test and the GHA
  runner variance is wide enough that +20% gating on every PR yields
  flaky failures unrelated to the diff.
- PERF-20 is therefore explicitly **manual + weekly** only, with a
  Markdown summary post that lands on the workflow run page (and on the
  PR thread when triggered against a PR ref).

## Components

| Component | Path | Role |
| --- | --- | --- |
| Consolidated runner | `scripts/perf/run_all_benchmarks.py` | Drives every `tests/perf/test_*.py` with `--runperf`, parses pytest `--durations=0` output, writes `out/perf_bench_<ts>.json`, emits Markdown table. |
| Pytest opt-in plug | `tests/perf/conftest.py` | Registers `--runperf` as a known pytest flag so the existing PERF-7 / PERF-11 tests + the runner all share one CLI opt-in. Previously the flag was only recognized via `sys.argv` walk and broke `pytest --runperf` with argparse rejection. |
| GHA workflow | `.github/workflows/perf-bench.yml` | `workflow_dispatch` + cron `0 0 * * 1` (Mon 09:00 JST). Pulls the prior `main` baseline ledger artifact, runs the bench, uploads the new ledger, posts the Markdown summary. |
| Ledger schema | `jpcite.perf_bench.v1` | Stable JSON shape — see runner docstring. Schema name is in the ledger header so future v2 can be detected by downstream readers. |

## How to run locally

```bash
# Single test (existing PERF-7 / PERF-11 flow, unchanged):
JPCITE_RUN_PERF_GATES=1 .venv/bin/pytest tests/perf/test_api_p95_budget.py --runperf

# Full bench + summary (PERF-20):
.venv/bin/python scripts/perf/run_all_benchmarks.py \
    --md-out out/perf_bench_summary.md

# Full bench with regression detection vs an earlier ledger:
.venv/bin/python scripts/perf/run_all_benchmarks.py \
    --baseline out/perf_bench_20260509T000000Z.json \
    --regression-pct 20 \
    --md-out out/perf_bench_summary.md \
    --fail-on-regression
```

The runner exits 0 on clean, 1 on any pytest failure, 2 on a regression
when `--fail-on-regression` is passed. The workflow only sets that flag
when the operator opts in via `workflow_dispatch` input.

## Regression threshold

- Default: **+20%** slower than the most recent `main` baseline.
- Justified by the variance band measured in the PERF-7 + PERF-11
  warm/cold split — under +20% lives in CI runner noise + warmup
  variance and would yield false positives.
- Operator can override per-run via the `regression_pct` workflow input
  when probing a known-flaky path.

## Ledger lifecycle

1. Workflow run produces `out/perf_bench_<ts>.json` and uploads it as
   the `perf-bench-ledger` artifact.
2. The next run downloads the most recent `perf-bench-ledger` artifact
   from the `main` branch via `dawidd6/action-download-artifact` and
   passes its path to `--baseline`.
3. The Markdown summary on the new run includes the per-test delta
   percentage and a 🔴 / ✅ regression flag column.
4. Artifact retention follows the repo-default GHA retention (90 days
   at time of writing) — older ledgers fall off naturally.

## What to do when a regression fires

1. Open the workflow run page; the run summary tab will show the same
   Markdown table that was posted to the PR thread (if triggered from
   one).
2. Identify the slowest-relative test and diff its duration against
   the baseline (the table shows both).
3. Open the underlying test file (`tests/perf/test_*.py`) — both PERF-7
   and PERF-11 record the optimization landed and the budget headroom
   in the docstring, so the most likely root cause is a removed
   optimization (orjson swap reverted, `os.write` swapped back to
   buffered write, etc.).
4. If the regression is intentional (e.g. a larger payload landed and
   the +N% is structural), bump the budget in the test file (PERF-7:
   `P95_BUDGET_MS`, PERF-11: `BUDGET_S`) and add a comment with the new
   floor + commit SHA.

## Adding a new perf test

1. Drop `tests/perf/test_<feature>_perf.py` with the standard
   `pytest.mark.skipif` guarded by `JPCITE_RUN_PERF_GATES` / `--runperf`.
2. (Optional) Emit a structured `[perfbench] test_id=<id> p50_ms=... p95_ms=... p99_ms=...`
   line from inside the test so the runner can fill the p50/p95/p99
   columns. Without that emission only `duration_s` will be reliable
   — which is fine for regression detection but limits the Markdown
   table richness.
3. The next workflow run picks the file up automatically — no runner
   wiring needed.

## Cron cadence

- Schedule: `0 0 * * 1` = Monday 00:00 UTC = **09:00 JST**.
- Rationale: a regression introduced mid-week lands on the Monday
  morning summary before the next release window.
- The schedule can be disabled by commenting the `schedule` block in
  the workflow without touching the `workflow_dispatch` path.

## Related SOT

- `docs/_internal/api_perf_profile_2026_05_16.md` — PERF-7 SOT
  (orjson swap, p95 budgets, hot-function profile).
- `docs/_internal/PERFORMANCE_SOT_2026_05_16.md` — repo-wide perf SOT
  (PERF-1..PERF-19 status).
- `tests/perf/test_api_p95_budget.py` — PERF-7 test.
- `tests/perf/test_packet_gen_perf.py` — PERF-11 test.

last_updated: 2026-05-16
