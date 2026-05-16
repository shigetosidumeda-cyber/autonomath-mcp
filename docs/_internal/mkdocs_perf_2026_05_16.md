# mkdocs build perf audit — PERF-15 (Wave 51, 2026-05-16)

## Scope

PERF-15 audits the cost of `mkdocs build` on the jpcite docs tree and adds a
fast incremental dev target. `site/` at the repo root mixes mkdocs output
with hand-written landing pages, generated SEO program pages, packet
samples, releases, and `.well-known/` JSON — only the `site/docs/` subtree
is owned by mkdocs.

## site/ topology

| Surface | Value |
| --- | --- |
| `find site -type f -name "*.html" \| wc -l` | **22,659** |
| `find site -type f -name "*.json" \| wc -l` | **104** |
| `du -sh site/` | **1.1 GB** |
| `du -sh site/docs/` (mkdocs-owned) | **9.9 MB** |
| `find docs -name "*.md" \| wc -l` (source) | **1,074** |
| Published pages (post `exclude_docs`) | ~250 |

The 22,659 HTML / 1.1 GB total is dominated by `site/programs/` (SEO
per-program pages from `scripts/generate_program_pages.py`) and other
non-mkdocs static surfaces. mkdocs itself only emits ~9.9 MB into
`site/docs/`.

## Baseline build time

| Mode | Command | Wall time |
| --- | --- | --- |
| Strict (CI-equivalent) | `mkdocs build --strict` | FAILS locally — cairo/social plugin needs arm64 lib that is x86_64 on this macOS box. CI Linux runner is unaffected. |
| Cold full (no strict, social OFF) | `MKDOCS_SOCIAL_ENABLED=false mkdocs build` | **2.74 s** (user 2.49s / cpu 73% / total 3.76 s) |
| Incremental (`--dirty`, hot cache, social OFF) | `MKDOCS_SOCIAL_ENABLED=false mkdocs build --dirty` | **0.28 s** (10x faster) |

`mkdocs build --strict` is the **CI gate** via `.github/workflows/pages-preview.yml`
on a Linux runner where cairo / pillow are healthy. Local macOS hits the
known `cairo arm64/x86_64` mismatch in the `social` plugin; the
`MKDOCS_SOCIAL_ENABLED` env var (already wired in `mkdocs.yml:154`) is
the documented escape hatch.

## Plugins audited (`mkdocs.yml:117..172`)

| Plugin | Status | Cost |
| --- | --- | --- |
| `search` (ja + en) | always on | cheap |
| `tags` | always on | cheap |
| `social` | gated by `MKDOCS_SOCIAL_ENABLED` env (default true) | **heavy** — OG card generation per page, needs cairo + pillow |
| `git-revision-date-localized` | already commented out for local Rosetta workaround; CI re-enables | medium |
| `algolia DocSearch` | staged (credentials pending) | n/a |

No additional slow plugins identified. The cold-build wall time is
already dominated by the 1,074 source files × 250 published pages × pymdownx
extensions, not plugin overhead, so further optimization yields are small.

## Optimization applied

1. **`make docs-fast`** — incremental `--dirty` build with social plugin OFF.
   Re-emits only pages whose markdown changed since the last build. Used by
   the local dev loop. Hot cache: **0.28 s**.
2. **`make docs`** — clean build without `--strict`. Honors
   `MKDOCS_SOCIAL_ENABLED` so the same target works on macOS and Linux.
3. **`make docs-strict`** — CI-equivalent (`--strict`). Recommended before
   merging doc changes that touch nav/links. On macOS arm64 boxes this needs
   `brew install cairo` for the arm64 build of libcairo.
4. **CI strict gate is unchanged** — `pages-preview.yml` keeps
   `mkdocs build --strict`; this audit only touches the dev-loop ergonomics.

## Why not more aggressive

- Material's HTML output is already minified; there is no `mkdocs-minify`
  payoff worth the maintenance burden.
- `mkdocs serve` already has built-in live-reload; we did not add a
  duplicate watch target.
- The 1.1 GB `site/` total is **not** an mkdocs problem — it is the
  generated SEO program pages emitted by `scripts/generate_program_pages.py`
  and tracked under separate perf budgets (the SEO surface is the value
  driver, not waste).

## Result

| Metric | Before | After |
| --- | --- | --- |
| Cold dev build (local, social OFF) | 2.74 s | 2.74 s (no change to cold path) |
| Hot dev build (local, social OFF) | 2.74 s (no incremental target) | **0.28 s** via `make docs-fast` |
| CI strict gate | passes via Linux runner | unchanged |
| Makefile targets | none for docs | **3 new** (`docs`, `docs-fast`, `docs-strict`) |

## Constraint checklist

- [x] CI `mkdocs build --strict` left intact (`pages-preview.yml` unchanged)
- [x] `[lane:solo]` marker on commit
- [x] No silent disabling of strict mode anywhere CI runs
