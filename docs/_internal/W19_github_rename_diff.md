---
title: W19 — GitHub repo rename impact + diff
updated: 2026-05-05
operator_only: true
category: brand
companion: docs/_internal/W19_github_rename_runbook.md
---

# W19 — GitHub repo rename impact + diff

Companion to `W19_github_rename_runbook.md`. Lists every canonical
configuration / manifest / README occurrence of
`shigetosidumeda-cyber/autonomath-mcp` (the GitHub URL slug) and the
exact replacement to `shigetosidumeda-cyber/jpcite-mcp`.

> Scope: **canonical files only** (manifest / config / README). 68
> additional docs / launch-asset / SDK / site files that mention the
> slug are listed at the end and swept post-rename via the single sed
> command in the runbook.

## Replacement rule

```
old: shigetosidumeda-cyber/autonomath-mcp
new: shigetosidumeda-cyber/jpcite-mcp
```

Every occurrence of the old slug — whether inside a URL, a registry
namespace string (`io.github.shigetosidumeda-cyber/autonomath-mcp`), or
a path segment — collapses to a single global string replacement. The
PyPI distribution name `autonomath-mcp` (no owner prefix) stays as-is.

## Canonical files (13 occurrences across 9 files)

### pyproject.toml (lines 146, 147)

```diff
-Repository = "https://github.com/shigetosidumeda-cyber/autonomath-mcp"
-Issues = "https://github.com/shigetosidumeda-cyber/autonomath-mcp/issues"
+Repository = "https://github.com/shigetosidumeda-cyber/jpcite-mcp"
+Issues = "https://github.com/shigetosidumeda-cyber/jpcite-mcp/issues"
```

> Note: `pyproject.toml:145` `# TODO(org-claim): switch back to
> github.com/jpcite/autonomath-mcp once the jpcite GitHub org is
> claimed.` — leave the TODO comment unchanged. It refers to a future
> org migration, not the current rename.

### server.json (lines 3, 7)

```diff
-  "name": "io.github.shigetosidumeda-cyber/autonomath-mcp",
+  "name": "io.github.shigetosidumeda-cyber/jpcite-mcp",
...
-    "url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp",
+    "url": "https://github.com/shigetosidumeda-cyber/jpcite-mcp",
```

### README.md (lines 7, 276)

```diff
-mcp-name: io.github.shigetosidumeda-cyber/autonomath-mcp
+mcp-name: io.github.shigetosidumeda-cyber/jpcite-mcp
...
-[![License](https://img.shields.io/github/license/shigetosidumeda-cyber/autonomath-mcp)](./LICENSE)
+[![License](https://img.shields.io/github/license/shigetosidumeda-cyber/jpcite-mcp)](./LICENSE)
```

### mcp-server.json (line 13)

```diff
-    "url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp",
+    "url": "https://github.com/shigetosidumeda-cyber/jpcite-mcp",
```

### mcp-server.composition.json (line 13)

```diff
-    "url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp",
+    "url": "https://github.com/shigetosidumeda-cyber/jpcite-mcp",
```

### mcp-server.core.json (line 13)

```diff
-    "url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp",
+    "url": "https://github.com/shigetosidumeda-cyber/jpcite-mcp",
```

### mcp-server.full.json (line 13)

```diff
-    "url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp",
+    "url": "https://github.com/shigetosidumeda-cyber/jpcite-mcp",
```

### smithery.yaml (line 55)

```diff
-  repository: "https://github.com/shigetosidumeda-cyber/autonomath-mcp"
+  repository: "https://github.com/shigetosidumeda-cyber/jpcite-mcp"
```

### dxt/manifest.json (line 48)

```diff
-    "url": "https://github.com/shigetosidumeda-cyber/autonomath-mcp"
+    "url": "https://github.com/shigetosidumeda-cyber/jpcite-mcp"
```

### One-shot sed (covers all 13 occurrences above)

```bash
git ls-files \
  pyproject.toml server.json README.md \
  mcp-server.json mcp-server.composition.json mcp-server.core.json mcp-server.full.json \
  smithery.yaml dxt/manifest.json \
  | xargs sed -i '' 's|shigetosidumeda-cyber/autonomath-mcp|shigetosidumeda-cyber/jpcite-mcp|g'
```

Verify with:

```bash
grep -rn "shigetosidumeda-cyber/autonomath-mcp" \
  pyproject.toml server.json README.md \
  mcp-server.json mcp-server.composition.json mcp-server.core.json mcp-server.full.json \
  smithery.yaml dxt/manifest.json
# Expected: zero matches.
```

## Out-of-scope occurrences (DO NOT change)

- `"autonomath-mcp"` as a **PyPI distribution name** in pyproject.toml,
  README, mcp-server.json (`identifier`), dxt/manifest.json
  (`entry_point`), smithery.yaml (`args:`), `uvx autonomath-mcp` /
  `pip install autonomath-mcp` — these are PyPI registry strings and
  console-script names, independent of the GitHub slug.
- `src/jpintel_mcp/` — internal package path, never renamed.
- `pyproject.toml:2` `name = "autonomath-mcp"` — PyPI dist name, stays.
- `pyproject.toml:136` `autonomath-mcp = "..."` — console-script binding.
- `_archive/`, `dist.bak/`, `dist.bak2/` — historical snapshots.

## Post-rename docs/site sweep (68 files, separate commit)

These do NOT block the rename — GitHub's permanent redirect keeps every
external link working. Sweep them in a follow-up commit after the
rename + canonical-file commit lands.

Files (categorized):

- **Docs** (5): `docs/getting-started.md`, `docs/faq.md`,
  `docs/long_term_strategy.md`, `docs/runbook/social_profile_setup.md`,
  plus the 12 docs/_internal/ items below.
- **docs/_internal** (12): `accessibility_audit.md`,
  `competitive_watch.md`,
  `exec_logs/exec_log_followup_A6_social_card_2026-05-04.md`,
  `handoff_2026-04-30.md`, `handoff_session_2026-05-01_for_deploy.md`,
  `mcp_registry_secondary_runbook.md`, plus the 6 entries under
  `mcp_registry_submissions/`.
- **Launch assets** (12): `docs/launch/{README,devto,hn,lobsters,note_com,reddit_claudeai,reddit_entrepreneur,reddit_japan,reddit_japanfinance,reddit_localllama,reddit_programming,reddit_sideproject,twitter_x_thread}.md`.
- **Scripts / registry submissions** (12):
  `scripts/check_registry_listings.py`,
  `scripts/distribution_manifest_README.md`,
  `scripts/distribution_manifest.yml`,
  `scripts/generate_compare_pages.py`,
  `scripts/mcp_registries_submission.json`,
  `scripts/mcp_registries.md`, plus 8 entries under
  `scripts/registry_submissions/`.
- **SDK** (4): `sdk/freee-plugin/marketplace/package.json`,
  `sdk/npm-package/package.json`, `sdk/python/pyproject.toml`,
  `sdk/starter/README.md`.
- **Site (rendered HTML)** (18): `site/index.html`, `site/support.html`,
  `site/mcp-server.json`, `site/server.json`,
  `site/docs/faq/index.html`, `site/docs/getting-started/index.html`,
  `site/docs/search/search_index.json`, plus the 12 files under
  `site/compare/<slug>/index.html`. Note: `site/` is regenerated from
  templates + docs, so re-running the site build will pick up the doc
  changes automatically — direct sed is only needed for the
  `mcp-server.json` / `server.json` mirrors.
- **Misc** (1): `MASTER_PLAN_v1.md` (line 723).

Single-pass sed (per runbook):

```bash
git ls-files docs/ scripts/ site/ pypi-jpcite-meta/ sdk/ content/ MASTER_PLAN_v1.md \
  | grep -v _archive \
  | grep -v 'dist\.bak' \
  | xargs grep -l 'shigetosidumeda-cyber/autonomath-mcp' 2>/dev/null \
  | xargs sed -i '' 's|shigetosidumeda-cyber/autonomath-mcp|shigetosidumeda-cyber/jpcite-mcp|g'
```
