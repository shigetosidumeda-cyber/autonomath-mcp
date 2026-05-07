# R8 - Cloudflare Pages direct deploy via GHA workflow (2026-05-07)

## Why this doc exists

`npx wrangler pages deploy /tmp/jpcite-pages.H8G5Dc` from the operator's
macOS shell stalled four retries in a row. Symptom: artifact upload (~22 MB
artifact, but over 22 k files) hits a CF Pages API rate-limit on retry/resume,
and the wrangler process never returns. Three orphaned PIDs were left running
(94583 npm exec, 94598 wrangler shim, 94599 wrangler dist). All three were
killed at session start (`pkill -f "wrangler.*autonomath"`).

To unblock launch, the production push has been moved off the operator
laptop to a GitHub Actions Linux runner. New workflow:
`.github/workflows/pages-deploy-main.yml` (180 lines, lightweight - no Fly
fetch, no MkDocs rebuild, no DB regeneration).

## Secret state at file creation

`gh secret list` (repo: bookyou/jpcite, scope: actions) returned only:

```text
FLY_API_TOKEN                         2026-05-02T14:41:36Z
PRODUCTION_DEPLOY_OPERATOR_ACK_YAML   2026-05-07T03:45:34Z
```

Both Cloudflare Pages secrets needed by the workflow are absent:

- `CF_API_TOKEN` (Account scope: Cloudflare Pages → Edit)
- `CF_ACCOUNT_ID`

The new workflow fails closed with an explicit `::error::` log line if
either is missing, so a `gh workflow run pages-deploy-main.yml` dispatch
right now would short-circuit at the "Check Cloudflare Pages secrets"
step, *before* artifact build.

The naming convention (`CF_*`, not `CLOUDFLARE_*`) intentionally matches
the pre-existing `pages-preview.yml` and `pages-regenerate.yml`. Keeping
one canonical pair avoids fragmenting secret management between two
workflows that target the same CF Pages project.

## Operator-side, one-time setup (1 step)

```bash
# 1) Get the Cloudflare account ID from the right sidebar of any CF
#    dashboard page (https://dash.cloudflare.com/).
# 2) Mint an API token at https://dash.cloudflare.com/profile/api-tokens
#    with template "Edit Cloudflare Workers" or custom scope:
#      Account → Cloudflare Pages → Edit
#    Restrict to the autonomath account; no zone scopes needed.
# 3) Inject both into the repo:
gh secret set CF_API_TOKEN --body "<paste-token>"
gh secret set CF_ACCOUNT_ID --body "<paste-account-id>"

# 4) Verify both visible:
gh secret list
```

After step 4, run the dispatch:

```bash
gh workflow run pages-deploy-main.yml
gh run watch
```

Expected wall time: 2-4 min (rsync + JSON validate + wrangler upload from
GHA runner + 15 s smoke curl). The Linux runner has no rate-limit history
with CF Pages so the upload should complete without the macOS-side stall
pattern.

## Workflow shape

| Step | Purpose |
|------|---------|
| Checkout | shallow (`fetch-depth: 1`) |
| Check Cloudflare Pages secrets | fail-closed gate (errors if either missing) |
| Build static artifact | `rsync` site/ -> dist/site/ with same filter as `pages-preview.yml` |
| Validate critical JSON manifests | `python3 -m json.tool` on server.json, mcp-server.json, docs/openapi/v1.json, openapi.agent.json |
| Publish to Cloudflare Pages | `cloudflare/pages-action@v1.5.0`, project=autonomath, branch=main |
| Post-deploy smoke | curl + json.tool against jpcite.com for the same four manifests |

Triggers: `push` on main with `paths: [site/**, .github/workflows/pages-deploy-main.yml]` plus `workflow_dispatch: {}`. Concurrency group `pages-deploy-main` with `cancel-in-progress: false` so we never abort an upload mid-flight.

Permissions: `contents: read`, `deployments: write` (matches existing pages-* workflows).

## Constraints honored

- LLM 0: no anthropic/openai/gemini imports anywhere; only rsync, python3 -m json.tool, curl, and the official cloudflare/pages-action.
- destructive 上書き 禁止: created a new file `.github/workflows/pages-deploy-main.yml`, did not touch the existing `pages-preview.yml` / `pages-regenerate.yml` / `deploy.yml`.
- pre-commit hook 通る: YAML parses with `python3 -c "import yaml; yaml.safe_load(...)"`; no `--no-verify`.
- token 不在時は dispatch せず documented: confirmed via `gh secret list`; dispatch is parked on the operator. This R8 doc is the documentation hand-off.

## Local cleanup

- Killed wrangler PIDs 94583 / 94598 / 94599 with `pkill -f "wrangler.*autonomath"`.
- Reverified with `ps aux | grep -i wrangler` — empty result.
- The leaked artifact dir `/tmp/jpcite-pages.H8G5Dc` (22 MB, 22 k files) was left in place; macOS will GC `/tmp` on reboot, and there is no security risk to the operator. Do not `rm -rf` it manually unless disk pressure demands it (the directory is consistent with the operator handoff's rebuild instructions).

## Next-action checklist for the operator

1. Mint CF_API_TOKEN (Pages-edit scope) and copy CF_ACCOUNT_ID.
2. `gh secret set CF_API_TOKEN --body ...`
3. `gh secret set CF_ACCOUNT_ID --body ...`
4. `gh workflow run pages-deploy-main.yml`
5. Watch the run; confirm the post-deploy smoke step succeeds.
6. Spot-check `https://jpcite.com/server.json` from a browser to confirm the
   `billable_unit / ¥3/課金単位` change from the open uncommitted diff is live.

## Sibling references

- `.github/workflows/pages-deploy-main.yml` — the new workflow.
- `.github/workflows/pages-preview.yml` — heavier, on push branches main + release/* with paths filter on site/docs/.
- `.github/workflows/pages-regenerate.yml` — nightly cron + on-script-change push trigger; pulls Fly DB to regenerate per-program HTML.
- `tools/offline/_inbox/HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md` — the upstream operator handoff that this workflow turns into a CI substitute.
- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_FRONTEND_LAUNCH_STATUS_2026-05-07.md` — sibling R8 entry covering frontend launch state.
