# Wave 49 — 迷子ゼロ 100% 完遂 (4page x 4element)

- **date**: 2026-05-12 (Wave 49, tick#2 successor)
- **branch**: `feat/jpcite_2026_05_12_wave49_lost_zero_100`
- **PR**: (set after `gh pr create`; entered post-open)
- **base HEAD before**: `9cf1659a6` (PR #188 RUM funnel collector G1 — last main commit)
- **lane**: `/tmp/jpcite-w49-lost-zero-100.lane/` (atomic mkdir claim)
- **worktree**: `/tmp/jpcite-w49-lost-zero-100/`
- **memory anchors**:
  - `feedback_dual_cli_lane_atomic` — mkdir lane + ledger
  - `feedback_destruction_free_organization` — additive only, no rm/mv
  - `feedback_billing_frictionless_zero_lost` — 4 step linear + breadcrumb + 30s idle

## Goal

Close the gap from previous tick: 4 funnel page x 4 wiring element matrix from
8/16 (50%) to 16/16 (100%). Two pages (`pricing.html`, `onboarding.html`) were
already fully wired by PR #182 and PR #188. Two pages remained partial:

- `site/index.html` — had `rum_funnel_collector.js` (PR #188) but missing
  `billing_progress.js`, `data-billing-progress`, breadcrumb.
- `site/docs/index.html` — **did not exist** (5 templates linked to `/docs/`
  resulting in 404 broken-link drift). Created in this PR as the canonical
  docs hub with all 4 elements wired from the start.

## Matrix (after this PR)

| Page                          | billing_progress.js | rum_funnel_collector.js | data-billing-progress | breadcrumb | Row total |
|-------------------------------|:--------------------:|:------------------------:|:-----------------------:|:------------:|:---------:|
| site/index.html               | OK (new)            | OK (PR #188)            | OK (new)                | OK (new)   | 4/4       |
| site/pricing.html             | OK (PR #182)        | OK (PR #188)            | OK (PR #182)            | OK (PR #182)| 4/4      |
| site/onboarding.html          | OK (PR #182)        | OK (PR #188)            | OK (PR #182)            | OK (PR #182)| 4/4      |
| site/docs/index.html          | OK (new)            | OK (new)                | OK (new)                | OK (new)   | 4/4       |
| **Column total**              | **4/4**             | **4/4**                 | **4/4**                 | **4/4**    | **16/16** |

Net: 8/16 → **16/16 (100%)**. +8 cell coverage added in this PR.

## Files changed (additive only)

1. **`site/index.html`** (+10 lines)
   - Inserted breadcrumb `<nav class="breadcrumb">` after `</header>` (line ~365).
   - Inserted `<div data-billing-progress data-cta-variant="home-progress">`
     inside `<main>` at the top.
   - Inserted `<script src="/assets/billing_progress.js" defer>` before
     `<script src="/assets/feedback-widget.js" defer>` (matches Wave 48 PR #182
     ordering on pricing/onboarding so script eval order is consistent).

2. **`site/docs/index.html`** (NEW, 1 file, ~120 LOC)
   - Canonical docs hub. Fixes 5 pre-existing 404 broken links to `/docs/`
     from `site/index.html` (x2), `site/_templates/cross.html`,
     `site/_templates/prefecture.html`, `site/_templates/industry_program.html`.
   - Mirrors existing page chrome (header / breadcrumb / footer / scripts).
   - Links: `/docs/openapi/v1.json` (306 paths), `/docs/openapi/agent.json`
     (slim), `/.well-known/mcp.json`, `/llms.txt`, `/onboarding.html`,
     `/pricing.html`.
   - All 4 lost-zero elements wired from day-one.

3. **`tests/test_lost_zero_100_4page.py`** (NEW, ~110 LOC)
   - 23 parametric tests across the 4 x 4 matrix + dup-prevention +
     breadcrumb-link-back-to-home.
   - Verdict: 23/23 PASSED (Python 3.13, pytest 9.0.3, 0.98s).

4. **`docs/research/wave49/STATE_w49_lost_zero_100_pr.md`** (this file)

## Anti-bug / regression guards added

- **No-dup script** test: `billing_progress.js` and `rum_funnel_collector.js`
  must each appear at most 1x per page — prevents accidental double-wiring
  that would double-fire RUM beacons and inflate aggregator cost.
- **Breadcrumb-anchor** test: every non-home page must have an `href="/"`
  inside the breadcrumb region — guarantees back-to-home escape hatch.
- **HTML parseability**: stdlib `html.parser` runs cleanly on all 4 files
  (verified manually with 0 errors per page).

## Forbidden / declined

- **No rm/mv**: zero deletions, zero renames. Pure additive.
- **No main worktree**: all work in `/tmp/jpcite-w49-lost-zero-100/`.
- **No legacy brand**: zero references to autonomath / zeimu-kaikei.ai /
  AutonoMath in new content.
- **No LLM API import**: structural string-grep test only, no agent / SDK
  use. Verified by source inspection.
- **No SaaS UI / tier hierarchy / impersonation toggle**: 4 step linear
  funnel preserved.
- **No large-scale site rewrite**: only the 2 minimum pages touched in
  `site/` to close the gap.

## Verify commands (local)

```bash
cd /tmp/jpcite-w49-lost-zero-100

# 16-cell matrix
python3 -c "
from pathlib import Path
pages = ['site/index.html', 'site/pricing.html', 'site/onboarding.html', 'site/docs/index.html']
elements = {
    'billing_progress.js': 'src=\"/assets/billing_progress.js\"',
    'rum_funnel_collector.js': 'src=\"/assets/rum_funnel_collector.js\"',
    'data-billing-progress': 'data-billing-progress',
    'breadcrumb': 'class=\"breadcrumb\"',
}
ok = sum(1 for p in pages for n in elements.values() if n in Path(p).read_text())
print(f'matrix: {ok}/16')
"

# pytest (Python 3.11+; jpcite venv at /Users/shigetoumeda/jpcite/.venv)
/Users/shigetoumeda/jpcite/.venv/bin/python -m pytest tests/test_lost_zero_100_4page.py -v
```

Expected: `matrix: 16/16` and `23 passed`.

## Open items (out of scope of this tick)

- Wire `billing_progress.js` + `data-billing-progress` + breadcrumb into the
  English mirror `site/en/index.html` (Wave 49 W2 organic funnel — EN parity
  is a separate axis).
- Add `breadcrumb` (`home > industries > <X>`) into prefecture / industry
  generator templates so SEO long-tail pages also benefit. Out of scope: this
  tick targets only the 4 funnel-relevant pages.
- Live CF Pages propagation verify — runs after merge via the regular
  post-deploy smoke (60s+ propagation per `feedback_post_deploy_smoke_propagation`).
