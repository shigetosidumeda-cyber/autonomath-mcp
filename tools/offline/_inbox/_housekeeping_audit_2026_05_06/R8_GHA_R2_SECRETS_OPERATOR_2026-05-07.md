# R8 GHA R2 secrets operator gap — 2026-05-07

**Scope**: jpcite v0.3.4 — close the GHA repository secret gap that
keeps off-site DR upload red despite Fly secret quartet being
deployed. **Doc + workflow-message-only change** (no production secret
value lands in the repo; operator-side `gh secret set` is required to
activate the fix).

Companion to: `R8_BACKUP_FIX_2026-05-07.md` (the prior R8 backup-step
shell-wrap fix), `R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md` (the
broader DR audit that surfaced both defects).

Runbook landed: `docs/runbook/ghta_r2_secrets.md`.

---

## 1. Gap recap (one-line)

The `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_ENDPOINT` /
`R2_BUCKET` quartet is deployed in the **Fly secret store**
(`autonomath-api` app) but absent from the **GitHub repository secret
store** (`shigetosidumeda-cyber/autonomath-mcp`). The two stores are
independent — a `flyctl secrets set` does not propagate to GHA, and a
`gh secret set` does not propagate to Fly.

Symptom: `nightly-backup.yml` workflow run `25477213040` failed
fail-closed at the "Upload to Cloudflare R2 and rotate" step with the
post-2026-05-03 hardening error
`::error::R2 secrets not fully configured`. `weekly-backup-autonomath.yml`
silently warning-skipped its R2 upload step on the same root cause
(autonomath.db 8.3 GB has no off-site mirror beyond the on-Fly local
14-day retention). `restore-drill-monthly.yml` cannot talk to R2 either.

## 2. Why AI cannot fix this end-to-end

- `flyctl secrets list -a autonomath-api` confirms the four names exist
  but **does not echo values** — Fly never emits secret content via CLI.
- `flyctl ssh tunnel` to read the values out of the running container's
  env (the only programmatic exfil path) hit a wireguard timeout this
  session — repeated retries did not succeed before the session budget.
- Cloudflare's R2 dashboard is OAuth-gated; minting or rotating an R2
  API token requires interactive operator login.
- `gh secret set` accepts stdin but the only safe input is the operator
  pasting the value directly — there is no source on the AI side.

Net: the operator must run §3 of the runbook from a machine where they
are logged into both Cloudflare and GitHub. The AI's deliverable is the
runbook + the improved error message that points at the runbook.

## 3. Deliverables this audit landed

### 3.1 Operator runbook — `docs/runbook/ghta_r2_secrets.md`

5-section operator-only playbook (`category: secret`). Headline sections:

- **§1 Root cause** — table contrasting Fly app secrets vs GHA
  repository secrets. Captures the 2026-05-07 status snapshot
  (Fly = 4 deployed, GHA = R2 quartet absent + only `FLY_API_TOKEN`
  + `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` present).
- **§2 R2 token acquisition** — two paths. **Path A** re-uses the
  existing token from the operator password manager (preferred — keeps
  Fly + GHA stores on the same credential, single rotation deadline).
  **Path B** mints a fresh Object Read & Write scoped token at the
  Cloudflare dashboard for `autonomath-backups` bucket only (least
  privilege).
- **§3 GHA secret set — four commands** — bare `gh secret set <NAME>`
  + stdin paste (avoids `--body` shell-history leak, avoids GitHub UI
  no-audit-trail path). Repo scope is implicit from cwd; explicit
  `--repo shigetosidumeda-cyber/autonomath-mcp` form documented for
  out-of-tree invocation.
- **§4 Verify** — five steps: `gh secret list` shows fresh `Updated`
  date for the quartet; `gh workflow run nightly-backup.yml` triggers
  immediate run; `gh run watch` sees Upload step go green inside 5-10
  min; `aws s3 ls` confirms artifact triplet (`.db.gz` + `.sha256` +
  `.manifest.json`) landed; optional weekly autonomath dispatch.
  Three failure-mode triage branches (secret-empty / token-scope-403 /
  endpoint-typo).
- **§5 Ongoing rotation** — 90-day cadence (Cloudflare Object-scope
  token max TTL). Operator ritual is "mint new + set both stores in
  the same session + verify + revoke old at Cloudflare dashboard".
  Forgot-and-expired recovery path is identical to first-time setup
  because the on-machine `/data/backups/` carries 14-day local
  retention as the bridge.
- **Anti-patterns** — separate token per store (rotation deadline
  doubling), `--body` flag (history leak), weakening fail-closed
  check, committing the token to repo files.

### 3.2 Workflow error-message improvement

`.github/workflows/nightly-backup.yml` — fail-closed branch error message
upgraded to point at the runbook:

```diff
-            echo "::error::R2 secrets not fully configured — failing nightly-backup loudly." \
-              "Set R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_ENDPOINT / R2_BUCKET to restore off-site DR."
+            echo "::error::Missing R2_* GHA repository secrets — failing nightly-backup loudly." \
+              "Operator runbook: docs/runbook/ghta_r2_secrets.md (Fly secret store ≠ GHA secret store;" \
+              "set R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_ENDPOINT / R2_BUCKET via 'gh secret set'" \
+              "to restore off-site DR durability)."
```

`.github/workflows/weekly-backup-autonomath.yml` — fail-open warning
branch upgraded with the same runbook reference + the explicit
"Fly secret store ≠ GHA secret store" qualifier so the operator cannot
mistake a green Fly inventory for a complete fix.

`.github/workflows/restore-drill-monthly.yml` — no explicit
secret-missing branch; the workflow header comment already lists the
required secrets and will surface the missing-cred case via
`scripts/cron/restore_drill_monthly.py` exit code on first run. The
runbook covers the operator-side fix universally.

### 3.3 Runbook README index update

`docs/runbook/README.md` — new row in the **secret** category for
`ghta_r2_secrets.md`, plus a new node in the cross-runbook dependency
graph linking it to `disaster_recovery.md` §2 + `litestream_setup.md`
Step 2 + `secret_rotation.md` (lockstep 90-day rotation).

## 4. Honest constraints

- **LLM 0** — pure markdown + workflow YAML edit, no model call.
- **No destructive overwrite** — `nightly-backup.yml` /
  `weekly-backup-autonomath.yml` edited in-place via single-string
  replacement of the error / warning message; `docs/runbook/README.md`
  edited via additive table row + dependency-graph block; new file
  `docs/runbook/ghta_r2_secrets.md` created from scratch (no prior
  runbook with that name existed). All other repo state untouched.
- **Production secret value 0** — neither the runbook nor the audit
  doc nor the workflow message contains an R2 access key, secret key,
  endpoint URL with accountid filled in, or bucket name as a literal
  the AI could leak. Every secret value in the runbook is a
  `<placeholder>` token.
- **Pre-commit hook respected** — no `--no-verify`. If hook fails, fix
  + new commit per CLAUDE.md ban.

## 5. Verify chain (operator-side, post-runbook)

1. Operator runs §3 of `docs/runbook/ghta_r2_secrets.md` (four
   `gh secret set` commands + stdin paste).
2. `gh secret list` should show six entries — two pre-existing
   (`FLY_API_TOKEN`, `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML`) plus the
   new R2 quartet, all carrying today's `Updated` date.
3. `gh workflow run nightly-backup.yml` triggers an immediate run; the
   "Upload to Cloudflare R2 and rotate" step turns green in 5-10 min.
4. `aws s3 ls "s3://autonomath-backups/autonomath-api/" --endpoint-url
   "https://<accountid>.r2.cloudflarestorage.com"` shows today's
   artifact triplet — closes the 3-night R2 upload gap that
   `R8_BACKUP_FIX_2026-05-07.md` documented.
5. Once verified, set a calendar reminder ~80 days out for the next
   90-day rotation cycle (`docs/runbook/ghta_r2_secrets.md` §5).

## 6. Cross-references

- `R8_BACKUP_FIX_2026-05-07.md` — sibling fix (the `flyctl ssh -C`
  shell-wrap defect that broke the backup-locate step). Together, the
  pair of fixes restores end-to-end nightly off-site DR durability.
- `R8_BACKUP_RESTORE_DRILL_AUDIT_2026-05-07.md` §5 — the umbrella
  audit that triaged both defects.
- `R8_RESTORE_DRILL_FIRST_RUN_2026-05-07.md` — first manual
  workflow_dispatch of `restore-drill-monthly.yml` (will turn green
  once §3 of the runbook lands the GHA secret quartet).
- `docs/runbook/disaster_recovery.md` §2 — Fly-side R2 secret
  inventory (the other half of the same credential pair).
- `docs/runbook/litestream_setup.md` Step 2 — same R2 quartet shared
  with the (still-DRAFT) litestream sidecar.
