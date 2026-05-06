---
title: W19 — GitHub repo rename runbook (autonomath-mcp -> jpcite-mcp)
updated: 2026-05-05
operator_only: true
category: brand
status: ready_to_execute (awaits operator confirm)
---

# W19 — GitHub repo rename runbook

> Operator-only. Companion to `docs/runbook/github_rename.md` (the longer
> hand-written runbook). This W19 document is the **scriptable** condensed
> version produced for Wave 19's deploy gate. It does NOT execute the
> rename — the rename runs only after the operator confirms.

## Pre-flight

- Repo: `https://github.com/shigetosidumeda-cyber/autonomath-mcp`
- New name: `jpcite-mcp`
- gh CLI authenticated as `shigetosidumeda-cyber` (verified 2026-05-05).
- Current `git remote -v`:
  ```
  origin	https://github.com/shigetosidumeda-cyber/autonomath-mcp.git (fetch)
  origin	https://github.com/shigetosidumeda-cyber/autonomath-mcp.git (push)
  ```
- 13 canonical files referencing the slug (manifest / config / README only).
  Full list and patches: `docs/_internal/W19_github_rename_diff.md`.
- 68+ launch / docs / SDK / site files also reference the slug; these are
  swept post-rename via a single sed pass (covered at the bottom).

## Execution (three commands)

```bash
# Step 1: rename on GitHub
gh repo rename jpcite-mcp --yes

# Step 2: refresh local origin URL (keeps redirect path off the hot loop)
NEW_URL="$(gh repo view --json url --jq .url).git"
git remote set-url origin "$NEW_URL"
git remote -v   # verify both fetch+push point at .../jpcite-mcp.git

# Step 3: apply the canonical-file diff
#   See docs/_internal/W19_github_rename_diff.md for the 13 file patches.
#   Sed sweep that satisfies the diff in one pass:
git ls-files \
  pyproject.toml server.json README.md \
  mcp-server.json mcp-server.composition.json mcp-server.core.json mcp-server.full.json \
  smithery.yaml dxt/manifest.json \
  | xargs sed -i '' 's|shigetosidumeda-cyber/autonomath-mcp|shigetosidumeda-cyber/jpcite-mcp|g'
```

## Post-rename verification

```bash
# 1. Old URL still resolves (GitHub permanent redirect — non-breaking for consumers).
git ls-remote https://github.com/shigetosidumeda-cyber/autonomath-mcp.git | head -1

# 2. New URL resolves directly.
git ls-remote https://github.com/shigetosidumeda-cyber/jpcite-mcp.git | head -1

# 3. Confirm gh CLI sees the new name.
gh repo view --json owner,name,url

# 4. Verify no stale slug remains in canonical config + manifest files.
grep -rn "shigetosidumeda-cyber/autonomath-mcp" \
  pyproject.toml server.json README.md \
  mcp-server.json mcp-server.composition.json mcp-server.core.json mcp-server.full.json \
  smithery.yaml dxt/manifest.json
# Expected: zero matches.
```

## Post-rename docs / launch / site sweep (separate commit)

68 docs / launch-asset / SDK / site files still carry the old slug. They
keep working via GitHub's permanent redirect, but should be cleaned up so
the rendered site does not show a stale URL. Single-pass sed:

```bash
git ls-files docs/ scripts/ site/ pypi-jpcite-meta/ sdk/ content/ MASTER_PLAN_v1.md \
  | grep -v _archive \
  | grep -v 'dist\.bak' \
  | xargs grep -l 'shigetosidumeda-cyber/autonomath-mcp' 2>/dev/null \
  | xargs sed -i '' 's|shigetosidumeda-cyber/autonomath-mcp|shigetosidumeda-cyber/jpcite-mcp|g'
```

Commit separately so the manifest-bump diff stays clean.

## What does NOT change

- PyPI distribution name `autonomath-mcp` stays. PyPI / GitHub registries
  are independent — `pip install autonomath-mcp` keeps working.
- Source directory `src/jpintel_mcp/` stays. Console-script entry point
  `autonomath-mcp` stays.
- `_archive/`, `dist.bak/`, `dist.bak2/` are intentionally left untouched
  (historical snapshots).
- `pyproject.toml:145` has `# TODO(org-claim): switch back to
  github.com/jpcite/autonomath-mcp once the jpcite GitHub org is
  claimed.` — this TODO comment stays as-is; the rename moves to
  `shigetosidumeda-cyber/jpcite-mcp`, not the unclaimed `jpcite` org.

## Rollback

```bash
gh repo rename autonomath-mcp --yes
git remote set-url origin https://github.com/shigetosidumeda-cyber/autonomath-mcp.git
git revert <sed-sweep-commit-sha>
```

## Cross-references

- `docs/runbook/github_rename.md` — long-form operator runbook (132 lines).
- `docs/_internal/W19_github_rename_diff.md` — exact per-file diffs.
- `docs/_internal/sdk_republish_after_rename.md` — SDK metadata republish
  after the rename takes effect.
- memory `project_jpcite_rename` — brand history + 301 plan.
- memory `feedback_no_trademark_registration` — rename-only posture.
