# R8 — Wrangler Local CF Pages Deploy Abandoned (2026-05-07)

Closure document for the local-machine `npx wrangler pages deploy site/` path
attempted from this CLI's host (macOS, single residential IP). After 5
consecutive retries — including one shrunk-artifact attempt — the local path is
declared unrecoverable for this session and the workflow path
(`pages-deploy-main.yml`) is the recommended substitute.

Internal hypothesis framing only — the conclusions below are derived from this
session's observed timing / progress counters and the existing repo-side
workflow design. They are not lab-isolated reproductions.

## 1. 5-retry timeline

All retries targeted CF Pages project `autonomath` (verified
`pages-deploy-main.yml:132`) on `branch=main`, deploying the same `site/` tree
(or its rsync'd subset). Progress counters quoted are the wrangler upload
progress line (`uploaded N/M files`).

| # | Artifact | Files | Stop point | Symptom | Wall time before stall |
|---|---|---|---|---|---|
| 1 | `site/` raw | 13,010 | **1,704 / 13,010** | `error: {}` (empty JSON body from CF API; client surfaced an empty error object) | ≈ 4 min |
| 2 | `site/` raw | 13,010 | **4,310 / 13,010** | hang at progress line, no further file commits, no error | ≈ 8 min |
| 3 | `site/` raw | 13,010 | **1,709 / 13,010** | hang shortly after resume, no progress for ≥ 6 min | ≈ 6 min |
| 4 | `site/` raw | 13,010 | **1,734 / 13,010** | very slow incremental progress (single-digit files / minute), effectively stalled | ≈ 10 min |
| 5 | rsync subset (`/tmp/jpcite-pages.*`) | 871 | **26 / 871** | hang within first minute despite ~15× smaller artifact | ≈ 5 min |

Between retry 4 and retry 5 the session also `kill -9`'d four lingering
`wrangler` / `node` processes and re-ran `npx wrangler whoami` to confirm the
session token was still valid. Retry 5 used a fresh `mktemp -d` artifact built
with the canonical rsync filter (mirroring `pages-preview.yml` and the operator
runbook in `tools/offline/_inbox/HANDOFF_2026_05_07_FRONTEND_DEPLOY_STOP.md`).

## 2. Root cause — internal hypothesis

The collapse of retry 5 (smaller artifact, same egress IP, same token) rules
out artifact size as the dominant factor. The leading hypothesis is a
**Cloudflare Pages bulk upload rate-limit window** keyed on
`(api_token, source_ip)` rather than per-file count:

- Retry 1's first stall produced `error: {}` rather than a structured error,
  consistent with an upstream gateway returning an empty body once the token's
  upload budget for that window is exhausted.
- Retries 2–4 from the same IP/token never re-cleared the window before the
  client gave up; each attempt resumed from cache, made a partial dent, then
  hung again.
- Retry 5's stall at 26 / 871 — well below any size-based concern — strongly
  suggests the limiter still considered this token+IP "in penalty" from
  preceding burst traffic.

Supporting circumstantial evidence:

- The host is on a single residential IP (no rotation possible without
  network-level changes).
- The token used is the same long-lived account-scoped token used for the
  prior `npx wrangler` calls in this session, so the limiter accumulated burst
  credits across attempts.
- `wrangler pages deploy` does not currently expose a back-off knob for the
  bulk upload phase; it relies on CF's own server-driven pacing.

This remains a hypothesis. A fully rigorous root cause would require capturing
the `cf-ray` headers + 4xx/5xx mix from the CF API edge during a stall, which
this session did not pursue (no further capacity to burn, and a workflow path
exists). The closure decision below does not depend on isolating CF's exact
limiter formula.

## 3. Workarounds attempted in this session

| Workaround | Outcome |
|---|---|
| Wait + plain retry (retry 2 → 4) | Same / different stall point each time, no convergence |
| Shrink artifact via canonical rsync filter (retry 5) | Stalled even faster proportional to file count → not size-bound |
| Kill all lingering `wrangler` / `node` PIDs, fresh `whoami`, fresh artifact | Retry 5 still stalled → not a stale local-process issue |
| Retry from a different shell session | Same egress IP / token → same rate-limit envelope, no benefit |

Workarounds **not** attempted in this session (deferred — out of scope for the
closure decision):

- VPN / different egress IP from the same host
- Mint a fresh CF API token narrowly scoped to Pages upload only
- `wrangler pages deploy --no-bundle` flags (some bulk-upload bypasses exist,
  but the canonical path under the workflow does not use them, so changing
  client knobs locally would diverge from the audited deploy path)

The workflow path side-steps all four by changing both the egress IP (GHA
ubuntu-latest runner pool) and the client invocation (action-pinned
`cloudflare/pages-action@v1.5.0`), so investing further in the local
workarounds was judged low-value.

## 4. Real frontend deploy path — `pages-deploy-main.yml`

The repo already ships a Linux-side production deploy workflow specifically
authored to dodge this exact local-machine failure mode. Header comment lines
3–8 document the intent verbatim:

> Why this workflow exists (2026-05-07): Local `npx wrangler pages deploy
> site/` from macOS stalled 4 retries in a row — the >100MB artifact upload hit
> Cloudflare Pages API rate-limit on retry/resume, leaving the wrangler
> process hung. GHA Linux runners have stable network paths and CF API
> rate-limit windows reset between runs, so we move the production push to
> CI to keep launch unblocked.

(The header was already authored before retry 5 happened. The 5th data point
above strengthens — but does not invalidate — that framing.)

Workflow shape:

- Trigger: `push` on `main` paths-filtered to `site/**` and the workflow file
  itself, plus `workflow_dispatch` for manual runs.
- Concurrency group `pages-deploy-main`, no cancel-in-progress.
- Steps (verified by re-reading `pages-deploy-main.yml`):
  1. Checkout (sha-pinned `actions/checkout@11bd71...` v4.2.2).
  2. Secret presence guard (`CF_API_TOKEN`, `CF_ACCOUNT_ID`); missing →
     graceful skip with `::warning::`.
  3. rsync `site/ → dist/site/` with the canonical exclude/include filter.
  4. JSON validate `server.json`, `mcp-server.json`, `docs/openapi/v1.json`,
     `openapi.agent.json`.
  5. `cloudflare/pages-action@f0a1cd5...` v1.5.0 publishes `dist/site` to
     project `autonomath`, `branch: main`.
  6. Post-deploy smoke against the four public JSON surfaces on
     `https://jpcite.com` with up to 6 retries × exponential sleep.
- Required GitHub repository secrets (canonical names — header explicitly
  forbids introducing `CLOUDFLARE_*` aliases):
  - `CF_API_TOKEN` — token scope **Account → Cloudflare Pages → Edit**, mint
    at `https://dash.cloudflare.com/profile/api-tokens`.
  - `CF_ACCOUNT_ID` — account ID from any CF dashboard right sidebar.

## 5. Alternative paths considered

| Path | Description | Verdict |
|---|---|---|
| **A. CF Pages dashboard direct git integration** | Bind the GitHub repo to the `autonomath` Pages project in the CF dashboard and let CF's own builder pull from `main` on push. Operator-only UI action; no CI secret needed inside this repo. | Viable fallback if the workflow secret path is blocked. Trade-off: build settings and the rsync filter live in the CF dashboard instead of versioned YAML, which is harder to audit from this repo. Documented here for completeness; **not** the recommended path. |
| **B. GitHub Pages mirror** | Publish `dist/site` to a `gh-pages` branch and serve via GitHub Pages, then DNS-cut `jpcite.com` / `www.jpcite.com` to GH Pages. | Requires DNS edits at the registrar + 24 h propagation + drops Cloudflare's edge cache and CF Workers wiring. Disproportionate disruption for a temporary upload-path workaround. **Not recommended.** |
| **C. Continue local wrangler on the same host** | Same token / same IP / same client. | Already enumerated above; 5/5 fails. **Not viable.** |
| **D. Local wrangler from a different egress (VPN / hotspot)** | Same client + token, new IP. | Not attempted this session. Would change the rate-limit identity tuple but does not move the deploy path into CI; one-off, not durable. **Not recommended as the standing path.** |

## 6. Recommendation

**Adopt `pages-deploy-main.yml` as the standing production frontend deploy
path.** The two-secret bootstrap (CF_API_TOKEN + CF_ACCOUNT_ID) is the only
remaining gap; once those are populated, both `push:main` and `workflow_dispatch`
deploys are unblocked, and this CLI session can stop retrying the local path.

Operator runbook for the bootstrap is shipped alongside this closure as
`HANDOFF_OPERATOR_FRONTEND_2026-05-07.md`. Estimated wall time for the
operator-side handoff: 5–10 min.

Local wrangler should be retained as a **debugging-only** path (handy for
inspecting upload diffs against a scratch project), not as the production
deploy path.

## 7. Hypothesis framing (preserved)

To stay honest with the constraint that this audit is internal-hypothesis
framing only:

- The CF rate-limit attribution in §2 is the leading hypothesis given the
  observed evidence in §1, but is **not** lab-isolated. We did not capture
  `cf-ray` IDs, did not run a paired "fresh token + same IP" or "same token +
  fresh IP" control, and did not get a structured 4xx/5xx mix to confirm
  which limiter window applied. The closure stands on the operational
  evidence (5/5 fails on this host, plus an existing CI workflow purpose-built
  to bypass it), not on a confirmed root cause.
- The `pages-deploy-main.yml` recommendation rests on the workflow's existing
  design intent + GHA's well-documented rotating runner egress pool; it is
  **not** a guarantee that GHA will not also be rate-limited under sustained
  bulk burst. The post-deploy smoke step in the workflow is the actual
  acceptance gate.
- Once the operator path completes successfully, this document should be
  cross-linked from the next R8 closure surface so the framing is not
  re-litigated. If the operator path also fails, this hypothesis must be
  revisited (likely escalation paths: CF support ticket with `cf-ray` capture,
  or alternative path A above).

---

**Status**: Local wrangler path closed for this session. Operator runbook in
`HANDOFF_OPERATOR_FRONTEND_2026-05-07.md`. Workflow file unchanged.
