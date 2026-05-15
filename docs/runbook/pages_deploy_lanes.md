---
title: Cloudflare Pages deploy lanes
updated: 2026-05-15
operator_only: true
category: deploy
---

# Cloudflare Pages deploy lanes

This runbook keeps public-site deploys predictable after frontend copy,
static asset, data-basis, or generated-page changes.

jpcite has two public deployment surfaces:

- Fly API origin: `api.jpcite.com`, deployed by the Fly workflow.
- Cloudflare Pages public surface: `jpcite.com`, deployed by
  `.github/workflows/pages-deploy-main.yml`.

The Pages workflow has three modes:

| Mode | Command | Use when | Cost |
|---|---|---|---|
| `fast` | `gh workflow run pages-deploy-main.yml --ref main -f deploy_mode=fast` | Copy, CSS, header/footer, docs, status JSON, functions, or committed public HTML changed. | Restores cached generated pages, rebuilds docs/assets, publishes. No Fly DB snapshot. |
| `full` | `gh workflow run pages-deploy-main.yml --ref main -f deploy_mode=full` | Generator, template, sitemap, llms, public-count, or DB-backed page shape changed. | Pulls latest Fly SQLite snapshot, regenerates generated pages, saves cache, publishes. |
| `auto` | Push to `main`, or `gh workflow run pages-deploy-main.yml --ref main -f deploy_mode=auto` | Normal push path. | Detects changed files. Falls back to `full` if cache is missing. |

## Fast lane

Use `fast` for:

- `site/styles.css`, `site/styles.src.css`
- Header, footer, logo, language switch, dark-mode contrast fixes in committed
  public HTML
- Pricing / terms / trust / legal copy
- `docs/**`, `mkdocs.yml`, `overrides/**`
- Cloudflare Functions changes under `functions/**`
- Status probe artifacts and status-bot commits

Fast deploy safety invariant:

- The workflow restores the latest generated-page cache for
  `site/programs`, `site/prefectures`, and `site/audiences`.
- It then re-applies Git-managed files from the current checkout so a cache
  cannot reintroduce stale committed pages.
- If no generated-page cache exists, the workflow warns and automatically
  runs `full` instead of publishing a site with missing sitemap targets.

## Full lane

Use `full` for:

- `site/_templates/**`
- `scripts/generate_program_pages.py`
- `scripts/generate_prefecture_pages.py`
- `scripts/generate_geo_industry_pages.py`
- `scripts/generate_cross_hub_pages.py`
- `scripts/generate_geo_program_pages.py`
- `scripts/generate_industry_hub_pages.py`
- `scripts/generate_industry_program_pages.py`
- `scripts/generate_compare_pages.py`
- `scripts/generate_public_counts.py`
- `scripts/generate_og_images.py`
- `scripts/regen_llms_full.py`
- `scripts/regen_llms_full_en.py`
- `scripts/regen_structured_sitemap_and_llms_meta.py`
- `scripts/sitemap_gen.py`
- Any change where generated page URLs, sitemap shards, llms metadata, or
  DB-backed public counts may change.

First run after this lane system lands will likely run `full` because the
cache is not populated yet. Let it finish; it seeds the cache for future
fast deploys.

## Local preflight

Before pushing frontend or public-copy changes:

```bash
.venv/bin/python -m pytest -q \
  tests/test_p1_workflow_deploy_blockers.py \
  tests/test_static_public_reachability.py::test_pages_artifacts_generate_source_backed_sitemap_targets_before_rsync \
  tests/test_sitemap_gen.py \
  --tb=short
git diff --check
```

Before a high-risk full deploy, also run the frontend release check if the
script is available in the checkout:

```bash
.venv/bin/python scripts/ops/frontend_release_check.py
```

## Post-deploy smoke

After Pages deploy succeeds:

```bash
curl -fsSI https://jpcite.com/ | sed -n '1,20p'
curl -fsSL "https://jpcite.com/?smoke=$(date +%s)" | grep -E "制度データ圧縮レイヤー|context-compression"
curl -fsSL https://jpcite.com/about.html | grep -E "/v1/evidence/packets|/v1/programs/by_region"
curl -fsSL https://jpcite.com/connect/ | grep -E "jpcite|JP|EN"
curl -fsSL https://jpcite.com/pricing.html | grep -E "¥3|Claude Agent SDK|tokens"
```

If a visual report is needed, run the Playwright smoke suite used in the
release loop and check at least:

- `/`
- `/about`
- `/connect/`
- `/pricing.html`
- `/audiences/kumamoto/manufacturing/`
- `/enforcement/act-12437`

## Failure handling

If `fast` falls back to `full`, do not cancel unless the workflow is clearly
stuck. It means the generated-page cache was missing or expired.

If Pages fails:

```bash
gh run list --workflow pages-deploy-main.yml --limit 5
gh run view <run-id> --log-failed
```

Then choose the narrowest fix:

- Missing Cloudflare secret: fix repository secret, rerun same mode.
- Missing Fly token during full generation: fix repository secret, rerun full.
- Generator failure: fix generator/template, rerun full.
- Public-copy/CSS failure only: fix committed asset, rerun fast.

Do not use local `wrangler pages deploy site/` for production unless GitHub
Actions is unavailable. The CI path is the canonical production path because
it has stable upload behavior and the drift gates.
