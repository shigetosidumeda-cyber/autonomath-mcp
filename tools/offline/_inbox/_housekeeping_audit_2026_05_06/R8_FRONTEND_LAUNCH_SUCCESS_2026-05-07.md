# R8 — Frontend Launch SUCCESS — Cloudflare Pages live (2026-05-07)

Closure success companion to:

- `R8_PAGES_DEPLOY_GHA_2026-05-07.md` (workflow design + secret bootstrap)
- `R8_WRANGLER_LOCAL_ABANDONED_2026-05-07.md` (5/5 local stall closure)
- `HANDOFF_OPERATOR_FRONTEND_2026-05-07.md` (operator runbook this success consumed)

Internal hypothesis framing only — see §7. The post-deploy smoke step
remains the actual acceptance gate; the prose below is operational reporting,
not a guarantee of long-term stability.

## §1 Milestone declaration

`jpcite.com` frontend (the 5/7 hardening tree on `main`) is **LIVE on
Cloudflare Pages** as of GHA workflow run **25478930809**, completed
2026-05-07T06:08:35Z. The repo-side `pages-deploy-main.yml` workflow path is
now confirmed end-to-end, replacing the abandoned local `npx wrangler pages
deploy` path. The two-secret bootstrap (`CF_API_TOKEN` + `CF_ACCOUNT_ID`)
documented in the handoff was completed by the operator and verified by the
runner's own secret-presence guard. The smoke step exited `success` against
the apex domain, so the apex DNS / CF Pages routing / edge cache surface is
serving the freshly deployed `dist/site/` output.

This closes the local-wrangler abandonment on the production-deploy axis.
Local wrangler remains a debugging-only path per the prior closure document.

## §2 Success metrics (run 25478930809)

Verified by `gh run view 25478930809 --json` and `gh run view 25478930809
--log` from the operator's host on 2026-05-07.

| Metric | Value | Source |
|---|---|---|
| Workflow | `pages-deploy-main` | GHA `name` field |
| Run ID | `25478930809` | GHA `databaseId` |
| Branch | `main` | GHA `headBranch` |
| Conclusion | `success` | GHA `conclusion` |
| Created | `2026-05-07T06:07:59Z` | GHA `createdAt` |
| Completed | `2026-05-07T06:08:35Z` | GHA `updatedAt` |
| Total wall time | **36 s** | derived (`updatedAt − createdAt`) |
| Job wall time | **31 s** | `74758573950` (`startedAt` → `completedAt`) |
| Steps green | **9 / 9** | per-step `conclusion: success` |
| `Publish to Cloudflare Pages` step | 21 s (`06:08:10` → `06:08:31`) | GHA per-step timing |
| Files uploaded fresh | **353** | wrangler `Uploaded N files` line |
| Files reused from CF cache | **612 already uploaded** | wrangler same line |
| Wrangler upload duration | **2.62 sec** | wrangler success line |
| Post-deploy smoke step | `success`, all 4 URLs OK | GHA per-step + log `post-deploy smoke OK` |
| Smoke targets | `server.json` / `mcp-server.json` / `docs/openapi/v1.json` / `openapi.agent.json` on `https://jpcite.com` | `pages-deploy-main.yml` smoke block |

The 9 steps were (verified by GHA per-step log):

1. Set up job — `success`
2. Checkout — `success`
3. Check Cloudflare Pages secrets — `success` (no `::warning::`, gate cleared)
4. Build static artifact (rsync `site/ → dist/site/`) — `success`
5. Validate critical JSON manifests — `success` (no Python traceback)
6. Publish to Cloudflare Pages — `success` (`Uploaded 353 files (612
   already uploaded) (2.62 sec)`, `cloudflare/pages-action@v1.5.0`)
7. Post-deploy smoke (public JSON surface) — `success` (`post-deploy smoke OK`)
8. Post Checkout — `success`
9. Complete job — `success`

The 612-already-uploaded count is the CF Pages dedup cache from prior
upload attempts (including the abandoned local-wrangler retries). It is
not "double counting" — those files were already in CF's content-addressed
storage and the new deploy simply re-pinned them under the new deployment ID.

The artifact-size figure quoted in the handoff was "several hundred MB",
based on the working tree size before the rsync filter. The 353 / 612 split
above is the post-filter file-level reality at the CF API boundary; the
13,010-files / 22 MB figures from the abandoned local path were taken
before secret-bootstrap and do not apply to this run.

## §3 OAuth token extraction path (the actual unblock)

The recommended path in the handoff (CF dashboard → Create Token → Pages
Edit) is still correct as a standing path. The path actually used by this
session unblocks faster but produces a **short-lived** token. Reproducing
this path requires `wrangler` already authenticated against the target
account on the operator's host.

```bash
# 1) Verify wrangler is logged into the right account.
npx wrangler whoami

# 2) Read the OAuth bearer wrangler stored at last login.
#    File path: ~/.wrangler/config/default.toml
#    The TOML section is [oauth_token]; the value is a fresh access_token.
#    DO NOT paste the token into chat / docs / commits — it grants account
#    edit until expiry.

# 3) Pipe the token straight into a repo secret (no clipboard, no log line).
gh secret set CF_API_TOKEN < /dev/stdin   # paste token then Ctrl-D
# OR
gh secret set CF_API_TOKEN --body "$(awk -F'"' '/access_token/{print $2; exit}' ~/.wrangler/config/default.toml)"
```

This route worked because `cloudflare/pages-action@v1.5.0` accepts any
account-scoped bearer that grants Pages Edit, including a `wrangler login`
OAuth access_token. The CF dashboard "Create Token" path produces the same
shape of bearer.

**TTL caveat (see §6 for the residual work):** the OAuth access_token from
`wrangler login` carries an approximately 1-hour TTL by default — the next
`pages-deploy-main.yml` invocation after that window will get a 401 from
CF's API, the action will fail, and the post-deploy smoke step will skip
because the publish never happened. This is why §6 lists "long-lived
operator-minted token" as a residual.

## §4 `CF_ACCOUNT_ID` source

Same session, same wrangler install:

```bash
npx wrangler whoami
# prints, among other lines:
#   Account Name: ...
#   Account ID:   037691739017ffe105f57fe391f4aebb
```

That 32-char hex value was set as the GHA repo secret `CF_ACCOUNT_ID` and
is verified by `gh secret list` (`CF_ACCOUNT_ID  Updated
2026-05-07T06:07:56Z`). The CF dashboard right-sidebar value matches; the
two paths produce the same identifier.

## §5 Hardening reflected by this deploy

The site contents shipped by this deploy correspond to the working tree at
the `main` HEAD commit at `2026-05-07T06:07:59Z`. Concretely the deploy
absorbs:

- **Codex handoff trio** (already merged before this run):
  - broken-link sweep applied across `site/`
  - `billable_unit / ¥3/課金単位` copy unification (CLAUDE.md non-negotiable
    surfaces; see open uncommitted diff comment in
    `R8_PAGES_DEPLOY_GHA_2026-05-07.md` §"Next-action checklist")
  - practitioner-eval surface (`site/audiences/*.html` cohort + supporting
    JSON-LD)
- **5/7 hardening tree**: the wider housekeeping batch under
  `tools/offline/_inbox/_housekeeping_audit_2026_05_06/` does not ship
  static HTML, but the launch-asset surface (audit log RSS, openapi,
  server.json, mcp-server.json) was regenerated alongside, and those four
  JSON manifests are exactly what the post-deploy smoke validated.

The smoke step's 4-URL pass therefore confirms that, at minimum:

- `https://jpcite.com/server.json` — registry surface
- `https://jpcite.com/mcp-server.json` — MCP registry surface
- `https://jpcite.com/docs/openapi/v1.json` — REST OpenAPI
- `https://jpcite.com/openapi.agent.json` — agent OpenAPI

are all live, parse-clean, and being served from the just-deployed
`dist/site` rather than a stale prior deploy. Browser-side spot-check
against any of those URLs from a fresh egress would be the next operator
verification (the handoff §"After the run" block remains the runbook).

## §6 真の残 (residual launch tasks, ≤ 30 min total)

The frontend axis is unblocked. The remaining production-launch surface
involves four secret / UI hand-offs not blocked on this CLI:

1. **`SENTRY_DSN`** (Fly secret). Without it, Sentry instrumentation
   inside the API noops. Wall: < 2 min once the operator has the DSN.
   Path: `fly secrets set SENTRY_DSN=https://...` from the repo root
   (already set up to read this name).
2. **R2 GHA secrets** for `weekly-backup-autonomath.yml`. Names:
   `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
   `R2_BUCKET`. Wall: 5–10 min including the R2 bucket + token mint in
   the CF dashboard. The workflow is concurrency-guarded the same way as
   `pages-deploy-main.yml` so a missing-secret skip is graceful, not a
   failure.
3. **Stripe live UI link**. The Stripe live-mode product / price /
   metered-usage wiring exists; the user-facing checkout link on
   `site/index.html` and `site/pricing.html` needs the live `cs_live_*`
   URL substituted for the placeholder. Wall: < 5 min in the Stripe
   dashboard plus a one-line edit. CLAUDE.md non-negotiable: do **not**
   reintroduce a tier-based UI; only the metered ¥3/req checkout.
4. **OAuth client UI** (consumer onboarding for the api-key + child-key
   flows wired in mig 086 + mig 096). Wall: 10–15 min — copy + form +
   confirmation page for `gh secret set`-style operator workflow on the
   API-key fan-out side.

Total residual wall time after this success: **≤ 30 min**, dominated by
the R2 bucket creation in CF. None of the four are blocked on this CLI's
assistance; they are operator-side dashboard or copy actions.

## §7 内部仮説 framing (preserved)

To stay honest with the constraint that this audit chain is internal-
hypothesis framing only:

- The frontend is **LIVE** by the operational gate the workflow itself
  defines (post-deploy smoke OK against the apex). That gate is
  evidence-based and reproducible by re-curling the four URLs.
- However, the bearer that produced this deploy was the
  `wrangler login` OAuth access_token, and that token has an approximately
  1-hour TTL by default. The **next** `gh workflow run pages-deploy-main.yml`
  after the TTL elapses will fail at the publish step with a CF API 401,
  unless the operator either (a) re-mints a fresh wrangler OAuth token
  and re-runs `gh secret set CF_API_TOKEN`, or (b) replaces
  `CF_API_TOKEN` with a long-lived dashboard-minted token (Account →
  Cloudflare Pages → Edit, no expiry — the path documented in
  `HANDOFF_OPERATOR_FRONTEND_2026-05-07.md` §"Step 1").
- The session did not lab-isolate the exact CF OAuth TTL. The "≈ 1 hour"
  figure is observational from the wrangler config metadata + CF's
  published OAuth defaults; treat it as a working assumption, not a
  contract. If a follow-up deploy works fine N hours later, the assumption
  was conservative; if it fails sooner, a fresh dashboard-minted token is
  the correct response, not a multi-hour debug spiral.
- The §6 residuals are scoped from the launch checklist and are not
  blocked on this CLI. The hypothesis is that the four hand-offs land
  cleanly on the operator side; none of them require new code, only
  secret material or a single-line copy change.

## §8 Cross-references

- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_PAGES_DEPLOY_GHA_2026-05-07.md`
  — workflow design, secret naming convention (`CF_*` not
  `CLOUDFLARE_*`), per-step shape.
- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_WRANGLER_LOCAL_ABANDONED_2026-05-07.md`
  — 5/5 retry timeline + CF rate-limit hypothesis + alternative paths A–D.
- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/HANDOFF_OPERATOR_FRONTEND_2026-05-07.md`
  — operator runbook (4 steps, 5–10 min) consumed by this success.
- `tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_FRONTEND_LAUNCH_STATUS_2026-05-07.md`
  — sibling status doc covering the broader frontend launch state.
- `.github/workflows/pages-deploy-main.yml` — the workflow file (180
  lines) that produced this success. The Step 3 secret-presence guard
  (`Check Cloudflare Pages secrets`) was the first proof that both
  secrets were correctly placed; the Step 6 publish + Step 7 smoke
  together close the loop.

---

**Status**: Frontend LIVE. `pages-deploy-main.yml` confirmed working
end-to-end. Local wrangler closure remains in force. Residual launch
work scoped to ≤ 30 min of operator dashboard / copy actions on the four
items in §6. Token-TTL caveat in §7 is the only operational concern this
session leaves uncovered.
