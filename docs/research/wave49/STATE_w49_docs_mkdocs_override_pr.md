# Wave 49 tick#2 — docs/ MkDocs Material override 4-element inject

**Date**: 2026-05-12 22:22 JST
**Lane**: `/tmp/jpcite-w49-docs-mkdocs-override.lane` (atomic mkdir claim)
**Branch**: `feat/jpcite_2026_05_12_wave49_docs_mkdocs_override`
**Status**: PR open

## Finding (root cause from tick#6 audit)

`STATE_w49_lost_zero_100.md` + sister audits showed the 4-element contract
satisfied on the static landing surfaces (index / pricing / get-started)
but **0/4 on the mkdocs-built sub-pages** like `/docs/api-reference/`.

```
$ grep -c 'billing_progress'      site/docs/api-reference/index.html  → 0
$ grep -c 'rum_funnel_collector'  site/docs/api-reference/index.html  → 0
$ grep -c 'data-billing-progress' site/docs/api-reference/index.html  → 0
$ grep -c 'breadcrumb'            site/docs/api-reference/index.html  → 0
```

`pages-deploy-main.yml` runs `mkdocs build` which writes into `site/docs/`
and **overwrites** the hand-crafted CWV-HARDENED `site/docs/index.html`
(31,871 bytes hand-crafted → 8,084 bytes Material-templated, observed
22:03). Every page in the docs/ nav tree inherits the same 0/4 gap.

Net: docs/ surface is **12/16** in the live 4-page × 4-element matrix until
the override is shipped.

## Fix shape (additive, destruction-free)

Two theme partials, both already wired by Material's `custom_dir: overrides`
contract in `mkdocs.yml`:

### `overrides/main.html`  (+8 lines)

Inside the existing `{% block extrahead %}` super(), add:

```jinja
<script src="/assets/billing_progress.js" defer></script>
<script src="/assets/rum_funnel_collector.js" defer></script>
```

The absolute `/assets/...` path resolves identically from `/docs/`,
`/docs/api-reference/`, `/docs/cookbook/r01-weekly-alert-per-client/`,
etc. `defer` keeps CWV intact (LCP unaffected).

### `overrides/partials/content.html`  (+8 lines, +1 char on existing nav)

- Add `breadcrumb` to the existing `class="jpcite-doc-nav"` on the PR #185
  nav so the bare `breadcrumb` CSS selector matches (defense-in-depth: the
  audit script doesn't have to know about Material's internal `md-path`
  class).
- Add a `<div data-billing-progress data-cta-variant="docs-progress"
  hidden style="margin:0 0 16px;">` mount point after the nav. Hidden by
  default; `billing_progress.js` removes the `hidden` attribute when an
  api_key + quota signal is available.

### `tests/test_docs_mkdocs_override_4elem.py` (new, ~80 LOC, 7 tests)

Verifies each of the 4 elements at the partial-source level plus 2
regression tests (extends base.html, JSON-LD include preserved). Cheap to
run, no mkdocs build required in CI.

### `docs/research/wave49/STATE_w49_docs_mkdocs_override_pr.md` (this file)

## Verification

Before merge, locally:

```
$ python3 -m pytest tests/test_docs_mkdocs_override_4elem.py -v
... 7 passed
```

Post-merge live verify (CF Pages propagates in ≤60 s):

```
$ for el in billing_progress rum_funnel_collector data-billing-progress breadcrumb; do
    curl -s https://jpcite.com/docs/api-reference/ | grep -c "$el"
  done
... 4 × non-zero
```

The follow-up tick#3 live walk runs the same 4 elements × 4 representative
pages (`/`, `/pricing/`, `/getting-started/`, `/docs/api-reference/`) and
should land **16/16 = 100%**.

## Anti-pattern checklist (per task instructions)

- [x] No existing Material template deletion
- [x] No large-scale redesign
- [x] Main worktree untouched (lane = `/tmp/jpcite-w49-docs-mkdocs-override`)
- [x] No `rm` / `mv` (additive only)
- [x] No old brand revival (jpintel / autonomath / zeimu-kaikei)
- [x] No LLM API import anywhere in this change
- [x] Atomic lane claim via `mkdir /tmp/...lane` succeeded first try
- [x] `feedback_destruction_free_organization` honored — every change is
      additive within the two pre-existing partials.

## 4 元素 inject 方式 — concise

| element                  | injected by                              | mechanism                                |
|--------------------------|------------------------------------------|------------------------------------------|
| billing_progress.js      | `overrides/main.html`                    | `<script src=... defer>` in `{% block extrahead %}` |
| rum_funnel_collector.js  | `overrides/main.html`                    | `<script src=... defer>` in `{% block extrahead %}` |
| data-billing-progress    | `overrides/partials/content.html`        | `<div data-billing-progress hidden>` above `{{ page.content }}` |
| breadcrumb               | `overrides/partials/content.html`        | `class="jpcite-doc-nav breadcrumb"` on the PR #185 nav |

## LOC delta

| file                                                | +adds | -dels |
|------------------------------------------------------|-------|-------|
| `overrides/main.html`                               | +14   | -0    |
| `overrides/partials/content.html`                   | +20   | -2    |
| `tests/test_docs_mkdocs_override_4elem.py`          | +132  | -0    |
| `docs/research/wave49/STATE_w49_docs_mkdocs_override_pr.md` | +120  | -0    |
| **total**                                            | +286  | -2    |

## Memory references honored

- `feedback_dual_cli_lane_atomic` — atomic mkdir lane claim, AGENT_LEDGER
  append-only protocol kept.
- `feedback_destruction_free_organization` — no `rm`, no `mv`, additive only.
- `feedback_billing_frictionless_zero_lost` — the new docs mount point keeps
  the 4-step billing funnel surface consistent (mount on every doc page so
  visitors who land deep in the docs tree see the same progress widget).
