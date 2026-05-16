# mkdocs + program-pages parallel perf — PERF-29 (Wave 51, 2026-05-17)

## Scope

PERF-29 follows PERF-15 (mkdocs audit). Two surfaces are timed:

1. **mkdocs** — recompute the cold-build baseline now that 372 catalog
   packets are in the tree and verify the 2026-05-16 numbers still hold.
2. **`scripts/generate_program_pages.py`** — the dominant `site/` writer
   (per PERF-15 docs: 22,659 HTML / 1.1 GB total). Per-row render+write is
   embarrassingly parallel; PERF-29 adds a `multiprocessing.Pool`-based
   parallel path with worker-local sqlite3 + Jinja2 state, **byte-identical
   HTML and sitemap output** to the legacy sequential path.

## mkdocs cold-build re-bench (2026-05-17)

Same flags as PERF-15: `MKDOCS_SOCIAL_ENABLED=false mkdocs build`
(social plugin OFF for arm64 mac compat; CI strict gate unchanged).

| Run | Wall time |
| --- | --- |
| Cold full (run 1) | **1.33 s** |
| Cold full (run 2) | **1.50 s** |

Mkdocs alone is already at the ~1-3 s floor; no further win is available
without retiring plugins, and that has acceptance cost (search plugin is
load-bearing for the docs site). Plugin scan via
`mkdocs build --verbose 2>&1 | grep -i "build\|plugin"` confirmed no new
slow plugins since PERF-15.

The 1.1 GB / 22,659 HTML in `site/` is not mkdocs output — it is the
program-pages SEO surface, addressed below.

## generate_program_pages parallelization

### Design

- New CLI flag `--workers N` (default = `os.cpu_count() or 1`; `0` or `1`
  forces sequential).
- `multiprocessing.Pool(spawn ctx)` with `_worker_init` initializer:
  - Per-worker `sqlite3.connect(jpintel.db)` (sqlite3.Connection is not
    fork-safe — must open inside child).
  - Per-worker `_build_env(template_dir)` Jinja2 environment.
  - Read-only broadcast state via `initargs`:
    `acceptance_map` (~88 programs), `publishable_slugs` (~1.4k strings),
    `domain`, `out_dir`, `structured_dir`, `site_root`.
- `_worker_render_row(row)` calls `_related_programs` → `render_row` →
  `_write_if_changed(html_path)` → optional `_write_jsonld_doc`, returns
  small metadata dict (status, slug, lastmod, tier, unified_id, paths).
- Parent collects results from `pool.imap_unordered(..., chunksize=64)`,
  re-sorts sitemap entries by the original DB order (tier rank,
  unified_id) so output is byte-stable against the sequential path.

### Bench results (M1 max, cold caches, `--tiers S,A`)

| Mode | Rows | Workers | Wall | Speedup |
| --- | --- | --- | --- | --- |
| Sequential (`--workers 1`) | 454 | 1 | **35.93 s** | baseline |
| Parallel (`--workers 8`) | 454 | 8 | **11.61 s** | **3.10x** |
| Sequential (`--workers 1`) | 1280 (S/A all) | 1 | **54.53 s** | baseline |
| Parallel (`--workers 8`) | 1280 (S/A all) | 8 | **17.30 s** | **3.15x** |

`user` and `sys` wall-summed across workers stays around 3x parent wall
(`user 33s` / `sys 36s` at 8 workers on 1280 rows), confirming linear
fan-out. The cap below 8x speedup is the sqlite3 contention on the shared
read-only `jpintel.db` page cache + per-row JSON encoding in pure Python.

### Parity verification

```
diff -rq /tmp/perf29_seq /tmp/perf29_par      # empty: every HTML byte-identical
diff /tmp/perf29_seq_sitemap.xml /tmp/perf29_par_sitemap.xml  # empty: sitemap identical
```

454 rows × 2 runs → both produce 454 HTML files with no diff. Sitemap
ordering is restored via the explicit `_row_order` re-sort using the
original DB `ORDER BY tier_rank, unified_id` shape.

## Result

| Metric | Before | After |
| --- | --- | --- |
| mkdocs cold full | 1.33 s | 1.33 s (already at floor) |
| program pages, 454 rows | 35.93 s | **11.61 s** (3.10x) |
| program pages, 1,280 rows | 54.53 s | **17.30 s** (3.15x) |
| HTML output | identical | **identical** (diff -rq empty) |
| sitemap output | sorted by DB order | **sorted by DB order** (identical) |
| mypy strict | 8 errors (all pre-existing) | 8 errors (pre-existing, no new) |
| ruff | clean | **clean** |

## Constraint checklist

- [x] HTML output bit-identical to sequential path (`diff -rq`).
- [x] Sitemap byte-stable: re-sorted by `(tier_rank, unified_id)` from
      `rows` (still in DB order) before `write_sitemap`.
- [x] mypy strict — no new errors introduced by PERF-29 code.
- [x] ruff — clean for `scripts/generate_program_pages.py`.
- [x] `[lane:solo]` marker on commit.
- [x] mkdocs CI strict gate (`pages-preview.yml`) untouched.
