# A7 Follow-up: Deprecate `site/structured/` + inline JSON-LD

Date: 2026-05-04
Status: complete
Owner: site/structured deprecate agent

## Context

Cloudflare Pages enforces a 20,000-file deploy limit. The site/ tree carried
22,896 tracked + generated files because `site/structured/` shipped 10,879
standalone `<unified_id>.jsonld` shards (one per program, ~42 MB total) as
an alt-format AI discovery surface. The shards duplicated content already
present in `/programs/<slug>.html` JSON-LD. To stay under the limit, the
GitHub Actions workflows used a `--exclude 'structured/'` rsync trick plus
a stub `sitemap-structured.xml` write at deploy time; this also blocked
direct `wrangler pages deploy` (no equivalent exclude flag inside `pages-deploy`).

## Pre-flight verification

- `site/_templates/program.html` already emits `<script type="application/ld+json">`
  inline. Spot-checked 10 generated pages under `site/programs/`: all 10
  carry inline JSON-LD (`grep -c 'application/ld+json' = 1`). No regeneration
  required — the `structured/` shards are pure duplicates.
- `site/structured/` and `site/sitemap-structured.xml` were **already
  gitignored** (`.gitignore` lines 56, 60), so removal is a local-cache
  cleanup, not a tracked-content deletion.

## Changes

### Local cache wipe (no git diff)

- `rm -rf site/structured/` — 10,879 files, ~42 MB.
- `rm site/sitemap-structured.xml`.
- File count: **22,896 → 12,016** (under the 20k Pages limit by ~8k).

### Generator (`scripts/generate_program_pages.py`)

- `--no-structured` is now the **default**. The `--structured-dir` and
  `--sitemap-structured` flags remain as opt-in escape hatches for local
  inspection (passing an explicit path resurrects legacy behavior for one
  run); both default to `None` instead of the in-tree paths so a vanilla
  invocation no longer regenerates the shards.
- Help text updated with `DEPRECATED 2026-05-03` markers.
- `build_standalone_json_ld` + `_write_structured_sitemap` retained
  (dormant — only fire when an explicit `--structured-dir` is passed).

### Workflows (`.github/workflows/pages-{preview,regenerate}.yml`)

- Removed `--exclude 'structured/'`, `--exclude 'sitemap-structured.xml'`,
  and the `cat > dist/site/sitemap-structured.xml <<XML ... XML` stub
  write. The rsync block now ships `site/` straight through, so wrangler
  can be invoked from any standard runner without a custom dist/ prep.

### Site assets

- `site/_headers` — removed the `/structured/*.jsonld` Content-Type +
  Cache-Control + CORS block. Inline JSON-LD inherits the HTML page's
  Content-Type, no separate header wiring needed.
- `site/robots.txt` — dropped `Allow: /structured/` and the
  `Sitemap: https://jpcite.com/sitemap-structured.xml` line.
- `site/sitemap-index.xml` — removed the `<sitemap><loc>.../sitemap-structured.xml</loc></sitemap>` entry.
- `site/_redirects` — added `/structured/* /404 404` (CF Pages doesn't
  support 410, so 404 per existing precedent in the same file) and
  `/sitemap-structured.xml /sitemap-index.xml 301` so legacy crawler URLs
  still find a live sitemap.
- `site/.well-known/mcp.json` — removed the `structured_sitemap` URL key
  from `trust_surfaces`.

### Sitemap generator (`scripts/sitemap_gen.py`)

- Dropped `sitemap-structured.xml` from `KNOWN_BASENAMES`.
- Module docstring updated with the 2026-05-03 retirement note.

### IndexNow cron (`scripts/cron/index_now_ping.py`)

- Comment for `SHARD_BASENAMES` updated — was already excluding
  `sitemap-structured.xml`, so the runtime behavior is unchanged.

### Tests (`tests/test_static_public_reachability.py`)

- `test_public_sitemap_controls_publish_structured_jsonld_shards` →
  inverted to `test_public_sitemap_controls_have_retired_standalone_jsonld_surface`,
  asserts the strings are now absent from robots/sitemap-index/_headers
  and that `/structured/* /404 404` is present in `_redirects`.
- `test_pages_artifact_excludes_standalone_structured_shards` →
  inverted to `test_pages_artifact_no_longer_carries_structured_exclude_workaround`,
  asserts none of the four legacy `--exclude` / stub snippets remain in
  the workflows.
- `test_public_docs_do_not_regress_to_internal_or_legacy_copy`
  banned-terms list (`"sitemap-structured"`, `"/structured/"`) left intact
  — the assertion is that those strings should NOT appear under
  `site/docs/`, which is still the desired guard.

## Verification

- `find site -type f | wc -l` → **12,016** (down from 22,896, well under 20k).
- `pytest tests/test_static_public_reachability.py` → **6/6 pass**.
- Wider sweep: `pytest -k "structured or sitemap or static_public or pages or jsonld or json_ld"` → **29 pass, 8 skip, 0 fail**.
- `ruff check` against the CLAUDE.md lint target → **All checks passed**.
- Generator smoke (`generate_program_pages.py --limit 3`):
  - default invocation → emits HTML only, no `structured/` directory
    created. JSON-LD verified inline (`grep -c application/ld+json = 1`).
  - explicit `--structured-dir /tmp/...` → still emits `.jsonld` shards
    on demand (escape hatch confirmed working).

## Wrangler deploy

Not executed in this session — Cloudflare Pages credentials are not
present in this sandbox. The `pages-preview.yml` / `pages-regenerate.yml`
diff demonstrates the workflows now ship straight through without the
exclude trick; on the next push to `main`, CF Pages will deploy the
12,016-file `site/` tree directly without `--exclude` gymnastics.

## Rollback

If standalone shards need to come back:
1. `git revert <commit>` restores the workflow excludes + assertions.
2. Re-run `scripts/generate_program_pages.py --structured-dir site/structured --sitemap-structured site/sitemap-structured.xml` to regenerate the shards locally (still gitignored).

## Files touched

- `.github/workflows/pages-preview.yml`
- `.github/workflows/pages-regenerate.yml`
- `scripts/cron/index_now_ping.py`
- `scripts/generate_program_pages.py`
- `scripts/sitemap_gen.py`
- `site/.well-known/mcp.json`
- `site/_headers`
- `site/_redirects`
- `site/robots.txt`
- `site/sitemap-index.xml`
- `tests/test_static_public_reachability.py`
- (untracked deletes) `site/structured/*.jsonld` × 10,879 + `site/sitemap-structured.xml`
