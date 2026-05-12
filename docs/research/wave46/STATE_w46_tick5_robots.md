# Wave 46 tick5 #8 — robots.txt sitemap-companion-md.xml direct entry

**Branch**: `feat/jpcite_2026_05_12_wave46_robots_sitemap_companion`
**Lane**: `/tmp/jpcite-w46-robots`
**Worktree base**: `origin/main @ 3aae4f345` (post #135 dim 19 FPQO merge)
**Date**: 2026-05-12

## Goal

Older / non-conformant crawlers and some AI bots ignore `sitemap-index.xml`
and only honor direct `Sitemap:` directives in `robots.txt`. The companion
`.md` shard (`sitemap-companion-md.xml`, 10,259+ `*.md` URL set, Wave 19
bulk) was previously discoverable **only via the index**. This patch adds
a direct top-level `Sitemap:` line so the companion shard is reachable at
every conformance level.

## Diff (site/robots.txt)

```diff
@@ -195,3 +195,4 @@ Sitemap: https://jpcite.com/sitemap-laws-en.xml
 Sitemap: https://jpcite.com/sitemap-llms.xml
 Sitemap: https://jpcite.com/docs/sitemap.xml
+Sitemap: https://jpcite.com/sitemap-companion-md.xml
```

**Single-line append** to the existing Sitemap block. Zero existing
`Sitemap:` lines deleted or reordered. Adherent to
`feedback_destruction_free_organization`.

## State delta

| Metric | Before | After | Δ |
|---|---|---|---|
| Total `Sitemap:` directives | 17 | 18 | +1 |
| `sitemap-companion-md.xml` direct entry | 0 | 1 | +1 |
| robots.txt total LOC | 197 | 198 | +1 |

## Test

**New file**: `tests/test_robots_sitemap_companion.py` (~95 LOC)

Three grep-based assertions, fully offline:

1. `test_companion_sitemap_directly_listed` — exact `Sitemap: https://jpcite.com/sitemap-companion-md.xml` substring present.
2. `test_companion_sitemap_not_duplicated` — regex match yields exactly 1 hit (regression guard against accidental double-append).
3. `test_existing_sitemaps_preserved` — 6 pre-existing canonical Sitemap URLs still present + total `Sitemap:` line count ≥ 18 (destruction-free invariant).

### pytest verdict

```
tests/test_robots_sitemap_companion.py::test_companion_sitemap_directly_listed PASSED [ 33%]
tests/test_robots_sitemap_companion.py::test_companion_sitemap_not_duplicated PASSED [ 66%]
tests/test_robots_sitemap_companion.py::test_existing_sitemaps_preserved PASSED [100%]

============================== 3 passed in 1.03s ===============================
```

**Verdict**: `3/3 green` on Python 3.13.12 / pytest 9.0.3.

## Completion gate (minimal)

Per `feedback_completion_gate_minimal`, only the 3 blocking checks:

1. [x] `Sitemap: https://jpcite.com/sitemap-companion-md.xml` literally present in `site/robots.txt`.
2. [x] No existing `Sitemap:` line deleted (17 → 18 monotonic).
3. [x] pytest `test_robots_sitemap_companion.py` 3/3 green.

Post-merge live verify (deferred until CF Pages propagation):

```bash
curl -sS https://jpcite.com/robots.txt | grep -c "sitemap-companion-md.xml"
# expect: 1
```

## Files touched

| File | Action | LOC delta |
|---|---|---|
| `site/robots.txt` | edit (append 1 line) | +1 |
| `tests/test_robots_sitemap_companion.py` | new | +95 |
| `docs/research/wave46/STATE_w46_tick5_robots.md` | new (this doc) | +~80 |

Total: ~+176 LOC, single concern, no LLM API, no operator-LLM call,
no destructive ops.
