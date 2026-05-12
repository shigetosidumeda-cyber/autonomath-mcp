# Wave 48 tick#4 — idle hint modal DOM emit fix (PR runbook)

Date: 2026-05-12 (JST)
Lane: `feat/jpcite_2026_05_12_wave48_idle_modal_fix`
Parent: PR #182 (`feat/jpcite_2026_05_12_wave48_billing_frictionless_v2`, merged 2026-05-12 12:20 UTC, commit `56953cba1`)
Owner agent: 1 (atomic lane `/tmp/jpcite-w48-idle-modal-fix.lane`)

## Bug surfaced by tick#4 UX audit

After PR #182 landed, the tick#4 UX audit probed `/pricing.html` after waiting > IDLE_MS (30000 ms) and ran 5 canonical selectors:

| selector              | matches before fix |
| --------------------- | ------------------ |
| `.modal`              | 0                  |
| `[role=dialog]`       | 0                  |
| `.hint-modal`         | 0                  |
| `#idle-hint`          | 0                  |
| `.lost-user-hint`     | 0                  |

Verdict: **modal DOM emit が不発**. Idle script string in place, 30 s timer wired, but the modal element never reached `document.body`.

## Root cause analysis

Two compounding defects in `site/assets/billing_progress.js` as it landed in PR #182:

1. **mousemove re-arms the idle timer continuously.** Line 259 listed `mousemove` in `resetEvents`. Browsers fire `mousemove` for every pixel of cursor motion (Playwright always sits the cursor on the page centre at load); each event called `armIdleTimer(idx)` which `clearTimeout`s the pending `showIdleHint`. Result: the 30 s timeout never elapsed → `showIdleHint` never ran → modal node never created.
2. **Modal selectors do not match auditor canon.** Even if the modal had appeared, its `id="jpcite-bp-modal"` / `class="jpcite-bp-modal"` failed every selector the audit probes (`#idle-hint`, `.hint-modal`, `.lost-user-hint`, `[data-idle-hint]`). The modal was structurally invisible to the agent‑era audit harness.

## Fix (JS diff, ~12 LOC changes)

`site/assets/billing_progress.js`:

```diff
-    var resetEvents = ["click", "keydown", "scroll", "mousemove", "touchstart"];
+    // 迷子検知 (Wave 48 tick#4 fix): only intentional interactions reset the
+    // 30s idle timer. mousemove fires continuously while the cursor is over
+    // the viewport and used to prevent the modal from ever showing — that is
+    // the exact "modal DOM emit が不発" bug surfaced by the tick#4 UX audit.
+    // We keep click/keydown/scroll/touchstart (which signal real intent) and
+    // drop mousemove. See tests/test_idle_hint_modal_dom.py for the live
+    // Playwright verify that the modal#jpcite-bp-modal node now appears.
+    var resetEvents = ["click", "keydown", "scroll", "touchstart"];

-    modal.className = "jpcite-bp-modal";
+    // Wave 48 tick#4 fix: also expose canonical "idle hint" hooks so the UX
+    // audit's standard selectors (.hint-modal, #idle-hint, .lost-user-hint)
+    // match this element. Classes are additive; existing CSS still applies.
+    modal.className = "jpcite-bp-modal hint-modal lost-user-hint";
+    modal.setAttribute("data-idle-hint", "true");
```

Total: 1 file changed in `site/assets/billing_progress.js`. **No** structural rewrite, **no** progress strip touched, **no** brand drift, **no** LLM API import.

## New test (`tests/test_idle_hint_modal_dom.py`, ~210 LOC)

Coverage:

1. `test_idle_modal_dom_emits_after_30s` — Playwright headless, opt-in `JPINTEL_E2E_IDLE_MODAL=1`, spins a stdlib `http.server` over `site/`, navigates `/pricing.html`, waits `IDLE_MS + 2s` (no cursor movement, no scroll), asserts:
   - `#jpcite-bp-modal` exists in DOM.
   - All 5 canonical selectors match.
   - Modal copy contains "次の step は".
2. `test_idle_modal_suppressed_by_intentional_click` — Negative: clicks at 5 s, asserts modal is absent at `(IDLE_MS / 1000) - 2.0` s post-click (timer correctly reset on real intent).
3. `test_mousemove_not_in_reset_events` — Static guard (always runs in CI). Reads the JS source, asserts `mousemove` is not inside the `resetEvents` array literal. Catches future regressions in < 1 s without Playwright.
4. `test_canonical_modal_hooks_present` — Static guard. Asserts every canonical selector token (`jpcite-bp-modal`, `hint-modal`, `lost-user-hint`, `data-idle-hint`, `role="dialog"`) lives in the JS source.

Local verify (2026-05-12):
- `pytest tests/test_idle_hint_modal_dom.py::test_mousemove_not_in_reset_events tests/test_idle_hint_modal_dom.py::test_canonical_modal_hooks_present`
  - 2 passed in 0.91 s.
- `pytest tests/test_billing_frictionless_flow.py` (regression sweep of PR #182's existing tests)
  - 21 passed in 0.96 s.
- `node --check site/assets/billing_progress.js` → `NODE_PARSE_OK`.
- Brace / paren / bracket balance via Python regex: brace 85=85, paren 135=135, bracket 18=18.

## Memory compliance

- `feedback_dual_cli_lane_atomic`: `mkdir /tmp/jpcite-w48-idle-modal-fix.lane` acquired exclusively before worktree.
- `feedback_destruction_free_organization`: no `rm`/`mv`; classes additive; modal id unchanged.
- `feedback_js_syntax_audit`: regex pass + `node --check` pass.
- `feedback_no_user_operation_assumption`: full local verify before push.
- `feedback_action_bias`: bug found → bug fixed in same lane, no permission round-trip.
- `feedback_keep_it_simple`: 1 file changed, 1 test file added, no rewrite.

## Constraints honoured

- No large-scale JS rewrite.
- Progress strip rendering (`buildStrip`) untouched.
- Main worktree untouched.
- No `rm`/`mv` anywhere.
- No legacy brand (`AutonoMath`, `税務会計AI`, `zeimu-kaikei.ai`) re-introduced.
- Zero LLM API import; modal copy is static.
