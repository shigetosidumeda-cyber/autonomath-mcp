# STATE — Wave 49 G1 CF Pages RUM funnel collector PR

**Wave:** 49
**Tick:** #4
**Lane:** `feat/jpcite_2026_05_12_wave49_cf_pages_rum`
**Date (JST):** 2026-05-12
**Status:** PR open, awaiting CI green + admin merge

## Acceptance target (Wave 49 G1)

10 unique `session_id`/day × 3 consecutive days on the organic funnel
(landing → free → signup → topup). See `docs/_internal/WAVE49_plan.md`
axis #1.

## Files added / extended (3 + 1 doc)

| File                                              | LOC | Purpose                                                    |
| ------------------------------------------------- | --: | ---------------------------------------------------------- |
| `functions/api/rum_beacon.ts`                     | 194 | CF Pages Function: POST receiver, R2 append, CORS, 4KB cap |
| `site/assets/rum_funnel_collector.js`             | 145 | Browser collector: sendBeacon emit on view / cta / done    |
| `tests/test_cf_pages_rum_beacon.py`               | 130 | 10 structural invariants (steps / events / wiring / cap)   |
| `docs/research/wave49/STATE_w49_cf_rum_pr.md`     |  ~  | this status doc                                            |

Plus 1-line `<script>` injection into 3 funnel pages:

- `site/index.html`     → +1 line near existing feedback-widget script
- `site/onboarding.html` → +1 line near existing feedback-widget script
- `site/pricing.html`   → +1 line near existing feedback-widget script

Destruction-free: no rm/mv, no rewrite of existing rum.js / rum_aggregator.

## Funnel 4-step wiring (verify)

| Step      | Page path        | Auto-event emitted    | Verified |
| --------- | ---------------- | --------------------- | -------- |
| landing   | `/index.html`    | `view`                | yes      |
| free      | `/onboarding`    | `view`                | yes      |
| signup    | `/pricing`       | `view` + `cta_click`  | yes      |
| topup     | `/topup`, `/checkout` | (server-side via Stripe webhook; client-side `cta_click` from `data-funnel-cta`) | server-side downstream |

`inferStep()` resolves the path → step mapping client-side; the same set
is gate-checked server-side by `ALLOWED_STEPS` in `rum_beacon.ts`. The
test `test_collector_handles_all_4_steps` enforces full coverage.

## Verification run

```
$ python3 -m pytest tests/test_cf_pages_rum_beacon.py -q
..........                                                               [100%]
10 passed in 0.90s

$ node -e "new Function(require('fs').readFileSync('site/assets/rum_funnel_collector.js','utf8'))"
SYNTAX OK (146 lines)

$ python3 -m html.parser site/{index,onboarding,pricing}.html
all 3 parseable, collector_refs = 1 each (no double inject)
```

Brace / paren / bracket parity in `rum_beacon.ts`:
`{} 31/31, () 91/91, [] 3/3` — matched.

## Forbidden controls observed

- No large `site/` rewrite — only +1 line per page.
- No main worktree changes — all work in
  `/tmp/jpcite-w49-cf-rum` worktree on
  `feat/jpcite_2026_05_12_wave49_cf_pages_rum`.
- No `rm` / `mv` of any existing asset.
- No `LLM API` import (TS file uses `crypto.subtle` for UA hash only).
- No SaaS-style high-feature dashboard — the function is single-purpose,
  R2-append-and-204.
- No legacy brand reintroduction in source (only `jpcite_funnel_sid` /
  `jpcite:funnel:complete` namespacing).

## Downstream (out of scope for this PR)

- Day-3 acceptance verify (`scripts/ops/rum_aggregator.py` extension to
  read `funnel/` R2 prefix and roll up daily uniq session_id) lives in
  a sibling Wave 49 G1 PR.
- CF Pages dashboard binding of `CF_RUM_R2` bucket — operator action.
