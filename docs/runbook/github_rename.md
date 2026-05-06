---
title: GitHub repository rename
updated: 2026-05-04
operator_only: true
category: brand
---

# GitHub repository rename runbook — `autonomath-mcp` → `jpcite-mcp`

> **Operator-only.** This step is fully manual; GitHub does not expose
> rename via Actions, and you do not want it automated regardless (a
> one-shot rename per launch event, performed by the org admin).

The 2026-04-30 user-facing brand rename (memory `project_jpcite_rename`)
left the GitHub repository name `autonomath-mcp` untouched at the time
of launch. This runbook walks the operator through the rename + the
post-rename verifications. GitHub auto-creates a permanent
`autonomath-mcp` → `jpcite-mcp` redirect for HTTPS clones, web links,
and API requests, so the rename is non-breaking for existing consumers.

## When to run

After the brand 301 redirects on `zeimu-kaikei.ai` are live and stable
for at least 7 days, and after the `pypi-jpcite-meta` package has been
published. Renaming the repo earlier means the package's `Repository`
URL would 404 between the rename and the next meta-package re-publish.

## Pre-flight (5 min)

- [ ] Operator is logged in as a member with **Admin** permission on
      the repo (`Settings` tab visible).
- [ ] No long-running PRs are mid-merge (rename can race with
      `gh pr merge` / hooks).
- [ ] `.git/config` URL of every active local checkout is recorded.
      The remote URL keeps working after rename, but updating it is a
      good hygiene step (covered below).
- [ ] Open an incident-style note in `docs/_internal/handoff_2026-04-30.md`
      so the change is auditable.

## Rename via UI (recommended, ~3 min)

1. Open `https://github.com/<org>/autonomath-mcp/settings`.
2. Top section "**Repository name**" — change `autonomath-mcp` to
   **`jpcite-mcp`**, click "Rename".
3. GitHub displays "Repository renamed. The previous URL will continue
   to work as a redirect to <new URL>." — note that this redirect is
   permanent and not configurable.
4. Verify in the URL bar that `https://github.com/<org>/jpcite-mcp`
   loads the repo home, and that the old URL 301-redirects to it
   (open in incognito to bypass any browser cache).

## Rename via gh CLI (alternative, scriptable)

```bash
gh repo rename --repo <org>/autonomath-mcp jpcite-mcp
# prompts for confirmation
```

This is identical in effect to the UI path.

## Post-rename verifications (10 min)

Run these in order; each catches a real failure mode that the rename
itself does not fix.

```bash
# 1. Old HTTPS clone URL must redirect.
git ls-remote https://github.com/<org>/autonomath-mcp.git | head -1
# Expected: lists refs successfully (proves the redirect works).

# 2. New HTTPS clone URL must work directly.
git ls-remote https://github.com/<org>/jpcite-mcp.git | head -1

# 3. SSH clone URL — GitHub redirects these too, but tooling cache might
#    have the old hostname pinned.
git ls-remote git@github.com:<org>/autonomath-mcp.git | head -1
git ls-remote git@github.com:<org>/jpcite-mcp.git | head -1

# 4. Existing local checkouts: refresh remote URL (optional but cleaner).
cd /path/to/jpcite
git remote -v   # shows origin -> autonomath-mcp.git
git remote set-url origin git@github.com:<org>/jpcite-mcp.git
git remote -v   # confirm

# 5. README badges — re-render the GitHub Actions / coverage badges that
#    encode the repo path. Stale badges 404 silently.
grep -rn "autonomath-mcp" badges/ README.md | head -20
# If any matches surface, edit them to jpcite-mcp.

# 6. Webhooks pointing at github.com/<org>/autonomath-mcp/...
gh api repos/<org>/jpcite-mcp/hooks --jq '.[].config.url'

# 7. PyPI meta-package's Repository URL.
grep -n "github.com" pypi-jpcite-meta/pyproject.toml
# Expected: already `https://github.com/<org>/jpcite-mcp` per the
# meta-package commit. If not, re-publish following
# docs/runbook/pypi_jpcite_meta.md.
```

## What does NOT need updating

- **`pyproject.toml` (real autonomath-mcp distribution)**: keeps
  `Repository = https://github.com/<org>/jpcite-mcp` (already updated
  pre-rename via this same brand sweep).
- **PyPI distribution name `autonomath-mcp`**: stays. The PyPI name and
  the GitHub repo name are independent registries; renaming the repo
  does not affect `pip install autonomath-mcp`.
- **CI `actions/checkout@v4` steps**: GitHub-hosted runners auto-resolve
  the new repo name from `${{ github.repository }}`, so no workflow
  edits are needed for in-repo CI.
- **External CI (GitLab mirrors, Cloudflare Pages, Fly.io GitHub App,
  Sentry release sync)**: each integration may cache the old name in
  its own UI. Open each integration's settings page once and confirm
  the repo selector still resolves correctly. Most show the new name
  automatically; some (Cloudflare Pages) require unlinking/relinking
  to refresh the cached display.

## Rollback

GitHub allows re-renaming back to `autonomath-mcp` in the same UI flow.
The `jpcite-mcp` -> `autonomath-mcp` redirect would then take effect
in the reverse direction. There is no other rollback step needed.

## Cross-references

- `docs/runbook/pypi_jpcite_meta.md` — companion meta-package publish
  runbook.
- `cloudflare-rules.yaml` — `redirect_rules` block for the
  `zeimu-kaikei.ai` -> `jpcite.com` 301 chain.
- memory `project_jpcite_rename` — brand history + 301 plan.
- memory `feedback_no_trademark_registration` — rename-only posture, no
  TM filing.
