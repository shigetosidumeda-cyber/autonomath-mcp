# Wave 49 tick#2: ALLOWED_STEPS calc_engaged extension

**Date**: 2026-05-12
**Branch**: `feat/jpcite_2026_05_12_wave49_allowed_steps_calc_engaged`
**PR**: (to be filled after push)
**Base**: `main` @ `8fe65074d`

## Context

Wave 49 G1 organic funnel is a 5-stage cohort:

```
landing → free → signup → topup → calc_engaged
```

Prior PRs landed the 4-step baseline (PR #4) plus the client-side
wiring of the 5th step (PR #195) — the cost-saving calculator page
`site/tools/cost_saving_calculator.html` loads
`/assets/rum_funnel_collector.js`, which `inferStep()` maps
`/tools/cost_saving_calculator*` → `"calc_engaged"`.

The previous tick (#8) observed:

```
POST /api/rum_beacon  body={step:"calc_engaged",...}  → HTTP 400
Response: "Invalid beacon shape"
```

Root cause: server-side gate `ALLOWED_STEPS` in
`functions/api/rum_beacon.ts` still listed only the 4 baseline steps.
`isValidBeacon()` returned `false` because `b.step` was not in the
Set, dropping every calc_engaged beacon at the edge and collapsing
the 5-stage funnel to a 4/5 observable state.

## Change

Additive 1-line server-side extension. The `ALLOWED_STEPS` `Set` adds
a 5th member.

### Diff (1 file, +1 line)

```diff
--- a/functions/api/rum_beacon.ts
+++ b/functions/api/rum_beacon.ts
@@ -73,6 +73,7 @@ const ALLOWED_STEPS = new Set([
   "landing",
   "free",
   "signup",
   "topup",
+  "calc_engaged",
 ]);
```

The validator (`isValidBeacon`) and all other gates remain unchanged —
the 4KB payload cap, bot-UA filter, CORS apex regex, and 400/413 paths
behave identically.

## Test

New file: `tests/test_rum_beacon_calc_engaged.py` (~120 LOC, 4 tests).

Structural rather than runtime (workerd spin-up would add 60-90s for
no incremental class of bug — companion test
`tests/test_cf_pages_rum_beacon.py` already covers wire shape):

1. `test_allowed_steps_now_includes_calc_engaged` — verifies the new
   `"calc_engaged"` entry is in the `ALLOWED_STEPS` literal.
2. `test_allowed_steps_preserves_4_baseline` — destruction-free
   (memory `feedback_destruction_free_organization`): the 4 original
   steps remain accepted. A regression here would silently zero out
   4 weeks of Wave 49 G1 baseline data.
3. `test_validator_still_rejects_unknown_steps` — the gate must still
   call `ALLOWED_STEPS.has(b.step)`. Without this assertion a future
   refactor could accept arbitrary strings without test failure,
   polluting the R2 funnel jsonl.
4. `test_allowed_steps_has_exactly_5_entries` — pins cardinality so a
   future 6th step (e.g. embedded SDK widget) is added deliberately
   with downstream aggregator awareness.

### Verify

```
============================== 18 passed in 1.12s ==============================
tests/test_rum_beacon_calc_engaged.py::test_allowed_steps_now_includes_calc_engaged PASSED
tests/test_rum_beacon_calc_engaged.py::test_allowed_steps_preserves_4_baseline PASSED
tests/test_rum_beacon_calc_engaged.py::test_validator_still_rejects_unknown_steps PASSED
tests/test_rum_beacon_calc_engaged.py::test_allowed_steps_has_exactly_5_entries PASSED
(+ 8 in test_cf_pages_rum_beacon.py — 4-baseline structural)
(+ 4 in test_calc_rum_wire.py — calc client wire structural)
```

All 4 new + 8 baseline + 4 calc-wire = **18 PASS** with the additive
change in place.

## Impact

- 5-stage funnel: calc_engaged now reaches R2 + CF Analytics (previously
  dropped at 400). Downstream `scripts/ops/rum_aggregator.py` will start
  rolling up the 5th step on the next daily aggregation pass.
- Server-side gate remains load-bearing: unknown step names still 400.
- Wave 49 G1 acceptance target — 10 unique session_ids/day × 3 days — is
  now measurable at the 5-stage cohort granularity, completing the
  measurement layer.

## Constraints honored

- **No rm/mv** (memory `feedback_destruction_free_organization`).
- **No main worktree** (memory `feedback_dual_cli_lane_atomic`).
- **No tier SKU / no SaaS UI** (this is a measurement-only change).
- **No LLM API import** (this is a CF Pages Function in TypeScript).
- **Brand**: no legacy autonomath / zeimu-kaikei.ai strings touched.
- **TypeScript validity**: `ALLOWED_STEPS` is still `new Set<string>`,
  the validator still returns the same boolean, and no other line in
  the file is changed.

## Files

- `functions/api/rum_beacon.ts` (+1 line, additive)
- `tests/test_rum_beacon_calc_engaged.py` (new, ~120 LOC)
- `docs/research/wave49/STATE_w49_allowed_steps_ext_pr.md` (this doc)
