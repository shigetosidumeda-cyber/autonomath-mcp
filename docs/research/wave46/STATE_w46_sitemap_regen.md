# Wave 46 tick2#10 — sitemap-companion-md regen + 17-gap fix

- Date: 2026-05-12 (UTC)
- Branch: `feat/jpcite_2026_05_12_wave46_sitemap_regen`
- Memory keys honored: `feedback_dual_cli_lane_atomic` (lane = `/tmp/jpcite-w46-sitemap.lane`),
  `feedback_destruction_free_organization` (no rm/mv; sitemap is overwritten via regen),
  `feedback_overwrite_stale_state` (new STATE doc; no historical edits).

## Reported delta

| signal                                              | before    |
|-----------------------------------------------------|-----------|
| `find site -type f -name '*.md' \| wc -l`           | **10,282** |
| `grep -c '<loc>' site/sitemap-companion-md.xml`     | **10,265** |
| nominal gap                                         | **17**    |

## Root-cause analysis

The "17 gap" headline is two off-by-one mismatches stacked on top of an
in-scope vs out-of-scope drift:

1. `grep -c '<loc>'` over `sitemap-companion-md.xml` matches the literal
   substring `<loc>` anywhere — including the XML comment header which
   contains the prose "Each `<loc>` points at …". That contributes **+1**
   to the headline count. The XML-pair regex `<loc>[^<]+</loc>` yields
   **10,264** real URL pairs.
2. `find site -type f -name '*.md'` returns every `.md` file under
   `site/`, including 18 non-companion files: top-level page companions
   (`about.html.md`, `pricing.html.md`, etc.), `press/*.md`, `legal/subprocessors.md`,
   `security/policy.md`, and two repo-internal docs (`README.md`,
   `assets/BRAND.md`). The existing generator
   (`scripts/generate_sitemap_companion_md.py`) only ever covered the
   `cases / laws / enforcement` directories per its docstring intent.
3. Disk inventory in those three companion categories is **10,264** —
   exactly matching the sitemap's real URL count. Diff `disk_md_urls -
   sitemap_urls` was 0 before the fix.

So the literal "17 gap" was a measurement artefact, not a missing-URL
problem inside the existing 3-category scope. But it surfaced a real
sitemap coverage hole: 16 first-class public companion `.md` surfaces
(about / pricing / facts / transparency / data-licensing / legal-fence /
compare / index `.html.md` plus the 6 `press/*.md` files plus
`legal/subprocessors.md` plus `security/policy.md`) were not exposed in
any sitemap. `README.md` and `assets/BRAND.md` are intentionally
repo-internal and stay out.

## Fix

`scripts/generate_sitemap_companion_md.py`:

- Added `ROOT_INCLUDE_GLOBS` (`*.html.md`, `press/*.md`, `legal/*.md`,
  `security/*.md`) + `ROOT_EXCLUDE_NAMES` (`README.md`, `BRAND.md`,
  `index.md`).
- New helper `_enumerate_root_page_urls()` emits a `("root", url)`
  entry per matched file.
- New flag pair `--include-root-pages` / `--no-include-root-pages`
  (default **ON**) wires the helper into `main()`.
- Promoted `--scan-md-only` to default **ON** (with explicit
  `--no-scan-md-only` opt-out) so the default sitemap matches the
  on-disk `.md` inventory (~10,264 across the 3 companion
  categories) rather than the legacy HTML-derived ~9,178 figure
  (which under-counts `cases` by 1,086).

## Post-regen verification

```text
$ python3 scripts/generate_sitemap_companion_md.py
[sitemap-companion-md] wrote site/sitemap-companion-md.xml
  (10280 URLs, 1877495 bytes, lastmod=2026-05-12)
        cases: 2286 URLs
        laws:  6493 URLs
  enforcement: 1485 URLs
        root:    16 URLs
```

| check                                                | result                |
|------------------------------------------------------|-----------------------|
| `xmllint --noout site/sitemap-companion-md.xml`      | **OK** (rc=0)         |
| `len(re.findall(r'<loc>[^<]+</loc>', xml))`          | **10,280** URL pairs  |
| disk in-scope .md count (3 cat + 4 root globs)       | **10,280**            |
| `disk - sitemap` gap                                 | **0**                 |
| `sitemap - disk` orphans                             | **0**                 |
| brand grep `税務会計AI \| AutonoMath \| zeimu-kaikei` | not introduced (none) |

The 2 disk files intentionally excluded (`README.md`, `assets/BRAND.md`)
are repo-internal and not part of the public companion-md surface.

## Files touched

- `scripts/generate_sitemap_companion_md.py` (~50 LOC added: 1 const
  block, 1 helper, 3 argparse args, 2 wire lines).
- `site/sitemap-companion-md.xml` (full regen; lastmod=2026-05-12;
  +16 root entries, +1086 cases entries vs HTML-derived legacy, total
  10,280 `<url>` blocks).
- `docs/research/wave46/STATE_w46_sitemap_regen.md` (this file).

## PR

To be filled by the push step (see git log / PR description).
