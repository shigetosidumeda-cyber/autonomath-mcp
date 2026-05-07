# R8 — GHA Release/Deploy Path Audit (2026-05-07)

Read-only audit of `.github/workflows/{release.yml, deploy.yml}` to confirm whether
GitHub Actions provides an automated Fly deploy path that can replace / re-trigger
a hand-run `flyctl deploy --remote-only` after the depot builder timeout reported
upstream.

Internal hypothesis framing only — no triggers fired by this audit.

## 1. Trigger / secrets / build matrix

| Workflow | Triggers | Required secrets | Build flow | Concurrency |
|---|---|---|---|---|
| `release.yml` | `push: tags ['v*']` + `workflow_dispatch` | OIDC trusted publishing for PyPI (no `PYPI_API_TOKEN` secret); `GITHUB_TOKEN` (release upload) | test → build sdist+wheel → publish-pypi (OIDC) → github-release. **Does NOT deploy to Fly.** | none |
| `deploy.yml` | `workflow_run` (after `test` completes on main, only when `conclusion == 'success'`) + `workflow_dispatch` (manual, bypass guard) | `FLY_API_TOKEN` (set 2026-05-02), `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` (required), `SLACK_WEBHOOK_URL` (optional notifier) | Hydrate seed DB via `flyctl ssh sftp get` → `flyctl deploy --remote-only -e SENTRY_RELEASE=<pkg+sha>` → post-deploy smoke probes (`/healthz`, `/v1/am/health/deep`, `/v1/programs/search`) | `deploy-${{ github.ref }}`, `cancel-in-progress: false` |

`release.yml` is PyPI-only; the Fly rollout path is exclusively `deploy.yml`. There
is no third "fly-only" workflow.

## 2. `deploy.yml` step skeleton (line refs)

1. Checkout commit at `workflow_run.head_sha || github.sha` (line 39-44).
2. Check `FLY_API_TOKEN` non-empty; emit `available=true` (46-53).
3. Setup Python 3.12 + `pip install -e ".[dev,site]"` (55-67).
4. Materialize `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` to runner temp (69-82).
5. Run `scripts/ops/pre_deploy_verify.py` + `scripts/ops/production_deploy_go_gate.py` (84-90).
6. `superfly/flyctl-actions/setup-flyctl@…` (92-94).
7. **Hydrate seed DB**: `flyctl ssh console -a autonomath-api … sqlite3 .backup` →
   `flyctl ssh sftp get` → assert `≥100MB` and `programs/jpi_programs ≥ 10,000`
   (96-153). NOTE: this step requires the live prod app already responding to SSH;
   if Fly is partially down, hydrate fails and deploy never starts.
8. Extract `SENTRY_RELEASE = autonomath-mcp@<pyproject_ver>+<short_sha>` (155-167).
9. **`flyctl deploy --remote-only -e SENTRY_RELEASE=…`** (169-174).
10. **Post-deploy smoke (HARD gate)** with 25s sleep + 3 curl probes (176-236).
11. Slack notify on failure (only if webhook secret set) (238-251).

## 3. Latest 5 run history (`gh run list -w deploy.yml -L 5`)

| run id | conclusion | commit / branch | trigger | duration | started |
|---|---|---|---|---|---|
| 25433013183 | **failure** | main | workflow_run | 5m34s | 2026-05-06 11:39 UTC |
| 25376962823 | failure | main | workflow_run | 4m47s | 2026-05-05 12:41 UTC |
| 25376649205 | skipped | main | workflow_run | 2s | 2026-05-05 12:34 UTC |
| 25365633289 | skipped | main | workflow_run | 1s | 2026-05-05 08:21 UTC |
| 25365570879 | skipped | main | workflow_run | 1s | 2026-05-05 08:20 UTC |

**Critical correction to upstream framing**: run 25433013183 (most recent) did NOT
fail at the depot builder. Per `gh run view 25433013183`, the failure step is
**"Post-deploy smoke (hard gate)"** with annotation
`POST-DEPLOY FAIL: /healthz expected 200 got 000000` — i.e. `flyctl deploy
--remote-only` (step 9) returned ✓, the new machine ran, but `curl
https://api.jpcite.com/healthz` from the GHA runner could not reach the host
(000000 = curl exit + no HTTP). Build/push/release succeeded inside Fly; the
external probe blew up. Three reads:

- the new release machine never came up despite flyctl reporting ✓ (Fly bug or
  immediate-strategy race shorter than 25s sleep);
- DNS / Cloudflare in front of `api.jpcite.com` was unreachable from
  GHA's eastus runner during that 25-second window (transient CF outage); or
- a prior deploy left the app in a "no machines" state and `flyctl deploy
  --remote-only` returned ✓ for the build but didn't start a machine (volume
  attach race).

The "depot builder timeout" framing should not be carried forward — log
evidence is at the smoke probe, not the build step.

The two preceding `skipped` rows confirm `workflow_run` only deploys when the
prior `test` workflow concluded `success`; on those runs `test` was non-success
so the `if:` guard short-circuited.

## 4. Manual re-trigger paths

Two operator paths are wired:

```bash
# Path A — bypass workflow_run guard, deploy GitHub's remote main HEAD
gh workflow run deploy.yml --ref main

# Path B — re-run the failed run with the same SHA (old image; see caution below)
gh run rerun 25433013183 --failed
```

Both honor the `if:` guard:
- Path A satisfies `github.event_name == 'workflow_dispatch'` so it ALWAYS runs
  (operator-asserted commit-is-green).
- Path B re-uses `workflow_run.head_sha = f3679d6926…` and the original
  `workflow_run.conclusion=success` (the triggering test run was green; only the
  deploy job failed at smoke). Rerun should fire, but it redeploys that older
  SHA, not current HEAD.

**Current-head caution**: local HEAD observed during follow-up debug was
`7ee0b08`, while failed run `25433013183` targets `f3679d69`. Therefore Path B is
effectively an old-SHA redeploy / rollback path unless the operator explicitly
wants that exact commit. For normal forward deployment, use Path A after the
current reviewed tree is committed, pushed to GitHub `main`, and the ACK
fingerprint is current. `gh workflow run deploy.yml --ref main` does **not**
deploy local unpushed commits; it deploys `origin/main`.

`release.yml` `workflow_dispatch` path is also wired (`gh workflow run release.yml
--ref vX.Y.Z`) but it's PyPI-only and won't help with the Fly rollout.

## 5. Secrets check

`gh secret list` returns one repo-level secret: `FLY_API_TOKEN` (added
2026-05-02). `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` and `SLACK_WEBHOOK_URL` were
NOT visible in the unscoped listing — they are likely environment-scoped
(`environment: pypi` exists on `release.yml`; `deploy.yml` has no environment
declared, so an env-scoped secret would not bind here). If
`PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` is missing the deploy fails at step 4
(`refusing deploy`). Re-trigger MUST verify this secret is repo-scoped, not
env-scoped, before issuing Path A.

`PYPI_API_TOKEN` is intentionally absent (release.yml line 602-610 confirms
trusted-publishing OIDC migration); historical v0.3.1 / v0.3.2 were hand-published
with twine.

## 6. Inferred decision matrix

| Situation | Action |
|---|---|
| Need same-commit redeploy, healthcheck transient | `gh run rerun 25433013183 --failed` only if `f3679d69` is still the intended target; otherwise this is an old-SHA rollback |
| Need re-deploy of newer main HEAD | Commit and push the reviewed tree first, then `gh workflow run deploy.yml --ref main` (rebuilds GitHub's remote main via remote builder) |
| Need to publish a missed PyPI tag | `gh workflow run release.yml --ref v0.3.4` |
| Need to debug seed-hydrate failure | run hydrate locally from same flyctl version + check `/data/jpintel.db` quick_check on prod machine |
| Builder really did time out | Path A — `--remote-only` retries on Fly's builder VM, not depot |

## 7. Honest gaps

- `deploy.yml` does NOT declare `environment:` so any environment-scoped secret
  required by `pre_deploy_verify.py` / `production_deploy_go_gate.py` will
  silently fail-closed at runtime even though the secret exists in another env.
- The 25-second post-deploy sleep is below Fly's typical machine-swap p99
  (~30-45s) for SQLite-backed apps with `boot_grace_period`. Smoke probe race
  is structural.
- `--remote-only` returning ✓ does not guarantee a machine started; the workflow
  has no `flyctl status -a autonomath-api --json` polling step between the
  deploy and the smoke gate. Adding one would distinguish "build done, machine
  failed" from "machine up, network blip".
- Node.js 20 deprecation warning surfaces on every run (`actions/checkout`
  pinned to a Node.js 20 SHA); not breaking, but worth one batch update before
  September 2026.

## 8. Read-only conclusion (no triggers fired)

GHA-side automated Fly deploy IS wired and the path to deploy GitHub's current
remote main is `gh workflow run deploy.yml --ref main`. If the local repository is
ahead of `origin/main`, push first; otherwise GHA will redeploy the old remote
SHA. `gh run rerun 25433013183 --failed` is valid only for intentionally
re-deploying the older `f3679d69` SHA. The most recent failure was at the
post-deploy smoke gate, not the builder — operator should verify
`api.jpcite.com/healthz` reachability and Fly machine state BEFORE retrying,
otherwise the same smoke probe will fail again without surfacing a new signal.
Trigger is OUT OF SCOPE for this audit.
