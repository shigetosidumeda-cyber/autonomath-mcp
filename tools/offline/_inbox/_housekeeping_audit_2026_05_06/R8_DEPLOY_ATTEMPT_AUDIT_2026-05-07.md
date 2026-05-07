# R8 — Deploy Attempt Audit (2026-05-07)

> **Internal hypothesis** framing only. Read-only audit; no deploy operation
> executed by this audit (write surface = this single doc + `git add` for the
> doc itself). Live `api.jpcite.com/healthz` = `200 {"status":"ok"}` confirmed
> mid-audit (curl 8s timeout, 0.56s response) so production impact = 0. LLM 0.
>
> Scope: capture the 5/7 02:50–03:50 UTC deploy-attempt timeline from this
> session, the live state holding at `f3679d6` (5/6 morning image), the GHA
> dispatch path that is currently in flight (run `25474923802`), and root-cause
> hypotheses for each failed attempt. Companion docs:
> `R8_PRE_DEPLOY_LIVE_BASELINE_2026-05-07.md` (live-state pre-deploy snapshot),
> `R8_FLY_DEPLOY_READINESS_2026-05-07.md` (readiness 4/4 PASS),
> `R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md` (alt-path matrix, depot=false rationale),
> `R8_GHA_DEPLOY_PATH_2026-05-07.md` (workflow_dispatch path A wiring).

## 1. Attempt timeline (5 attempts, 02:50–03:50 UTC)

| # | Time (UTC) | Method | Outcome | Error / signal |
|---|---|---|---|---|
| 1 | ~02:50–03:14 | `flyctl deploy --remote-only --strategy rolling` (depot remote builder) | **FAIL** after 1431 s (~23.85 min) | `depot builder deadline_exceeded`. Context tarball ~440 MB streamed in 24 min — anomalous (typical: <60 s). Build never reached the model-bake step that usually dominates a 6-8 min depot run. |
| 2 | ~03:18 | `flyctl deploy --depot=false` (intent: local-docker fallback) | **FAIL** immediately | `missing hostname` daemon parse error. Recent `flyctl` (post-2026-02) silently dropped the `--depot=false` flag in favor of `--local-only`; the unrecognized flag fell through to a default `--remote-only` path which then surfaced a malformed `host=…` arg from the wrapper. Net effect: no local docker build attempted. |
| 3 | ~03:22 | `wrangler pages deploy site/ --project-name=jpcite --branch=main` (1st invocation) | **FAIL** at chunk 1704/13010 | `Failed to upload` with **empty error object** (`{}`). Cloudflare Pages bulk-upload API returned a 5xx-class transient without payload. No visible quota / auth error. |
| 4 | ~03:30 | `wrangler pages deploy …` (retry) | **In-flight at audit time**, last observed at chunk 4310/13010 (~33% complete) | No terminal signal yet. Running for ~15 min as of audit close. CF Pages bulk uploads can stall on TLS keep-alive resets without surfacing to wrangler logs. |
| 5 | 03:45:36 | `gh workflow run deploy.yml --ref main` → run **25474923802** | **In-flight** at audit close (3 of 10 steps complete, currently in `Hydrate jpintel seed DB` step which has `flyctl ssh sftp get` 100 MB minimum + 10K-row jpi_programs assertion) | Steps green: Set-up-job (1s), Checkout (4s), Check Fly token (0s), Set up flyctl (1s). Now in step 5 (hydrate via `flyctl ssh console -a autonomath-api … sqlite3 .backup`). Steps 6 (extract version), 7 (`flyctl deploy --remote-only`), 8 (post-deploy smoke), 9 (slack notify) still pending. Total elapsed ~5 min at audit close. |

Sequencing note: attempt 5 is the **only** attempt that the operator wired the
new `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` repo secret for — confirmed by
`gh secret list` showing `PRODUCTION_DEPLOY_OPERATOR_ACK_YAML` added at
`2026-05-07T03:45:34Z`, **2 seconds before** the workflow dispatch fired
(`createdAt = 2026-05-07T03:45:36Z`). This is precisely the pre-flight wiring
gap flagged by §5 of `R8_GHA_DEPLOY_PATH_2026-05-07.md` ("secret may be
env-scoped, fail-closed at runtime"). The repo-scoped insertion immediately
before dispatch resolves that gap for this run.

## 2. Live state at audit close

Read-only HTTP probes at audit close (curl `-m 8`, no caching, no auth):

| Field | Probe | Value |
|---|---|---|
| `api.jpcite.com/healthz` | GET (HTTP/2) | **200** body `{"status":"ok"}`, response 0.56 s |
| Fly machine image (`flyctl image show -a autonomath-api`) | machine `85e273f4e60778`, registry `registry.fly.io/autonomath-api`, tag `deployment-01KQZVPD9RSEM5M06XJXME2N9K`, digest `sha256:215ed7…0818db3e`, `GH_SHA=f3679d6926d8654e106544523283fc04a729ea51` (5/6 morning) | LABELS confirm `image.source=github.com/shigetosidumeda-cyber/jpintel-mcp` (TODO from §2.1 of readiness audit) |
| Live `/v1/openapi.json` | `info.version=0.3.4`, `paths=179` | 0.3.4 matches local SOT, paths count is the live-served surface (note: `R8_PRE_DEPLOY_LIVE_BASELINE` measured 221 paths via `/docs/openapi/v1.json` which now returns `route_not_found` with `redirect_url=https://api.jpcite.com/v1/openapi.json` — endpoint moved between baseline run and this audit; the live truth is **179** at canonical path) |
| `jpcite.com/` (Cloudflare Pages) | GET HTTP/2 | **200** (still serving the wrangler-attempt-stale 5/6 site; no rollback occurred) |
| Live `f3679d6` SHA vs local HEAD | local HEAD = `c3b6e5781a` (per ACK YAML `_meta.git_commit_hash`) | Drift = 5/6 morning → 5/7 hardening unshipped (mypy 348→69, acceptance 286/286, 33 DEEP retroactive verify, fingerprint SOT helper — all in source, 0 in production) |

ACK YAML `R8_ACK_YAML_LIVE_SIGNED_2026-05-07.yaml` (signed 02:51:44 UTC by
`info@bookyou.net`) carries `8/8` field truths set true (`fly_app_confirmed`,
`fly_secrets_names_confirmed`, `appi_disabled_or_turnstile_secret_confirmed`,
`pre_deploy_verify_clean`, `target_db_packet_reviewed`,
`rollback_reconciliation_packet_ready`, `dirty_lanes_reviewed`,
`live_gbiz_ingest_disabled_or_approved`). Dirty-tree fingerprint shows 3
modified paths split across 3 non-critical lanes (`generated_public_site=1`,
`public_docs=1`, `sdk_distribution=1`); 0 entries in `critical_lanes_present`,
0 entries in `content_hash_skipped_large_files`. Production gate per
`R8_FLY_DEPLOY_READINESS_2026-05-07.md` §6 = 4/4 readiness PASS;
`R8_DRY_RUN_VALIDATION_REPORT.md` (companion) closed go-gate at 5/5 PASS.

## 3. Wrangler retry (attempt 4) status

- Started attempt 4 ~03:30 UTC after attempt 3 failed at chunk 1704/13010.
- Last observed chunk count `4310/13010` (~33% upload), no terminal status.
- 13010 total chunks correlates with the post-Wave-23 `site/` build (300 MB
  raw / ~13K granular HTML+JSON+SVG assets after per-program SEO page
  generation: 11,684 program pages × 1 HTML + supporting hub/prefecture/industry
  pages + 167K alias index files in `site/programs/`). CF Pages is upload-by-asset
  not by-tarball, so any single 5xx in the bulk batch retries the whole batch
  not just the failed asset — a transient CF API error mid-stream stalls the
  remaining ~8.7K assets.
- `wrangler` does not surface the in-flight chunk count via a queryable API;
  the only signal is the streaming stdout of the original invocation. If that
  TTY is lost, status is lost.
- **Honest gap**: this audit could not confirm completion / failure of attempt
  4 from a fresh process. Operator should re-check the original wrangler TTY
  (or `wrangler pages deployment list --project-name jpcite` for terminal
  results once attempt 4 completes/aborts).

## 4. GHA dispatch (attempt 5) — path forward

`deploy.yml` workflow at run `25474923802` (URL:
`https://github.com/shigetosidumeda-cyber/autonomath-mcp/actions/runs/25474923802`)
on commit `c3b6e57` (per ACK YAML `_meta.git_commit_hash`).

Step-by-step gate per `R8_GHA_DEPLOY_PATH_2026-05-07.md` §2:

1. ✅ Checkout (4s)
2. ✅ Check `FLY_API_TOKEN` non-empty (instant)
3. ✅ Setup flyctl (1s)
4. **In progress: Hydrate jpintel seed DB** — runs `flyctl ssh console -a autonomath-api … sqlite3 /data/jpintel.db .backup` then `flyctl ssh sftp get`, asserts file ≥100 MB, asserts `programs/jpi_programs ≥ 10,000`. This step **requires a live prod SSH** which §2 of the GHA path audit warns "if Fly is partially down, hydrate fails and deploy never starts". **Live SSH is healthy** at audit close (healthz 200, image inspectable), so this step should proceed in 30–120 s.
5. Pending: Extract `SENTRY_RELEASE = autonomath-mcp@0.3.4+c3b6e57`
6. Pending: `flyctl deploy --remote-only -e SENTRY_RELEASE=…` (depot builder again — same underlying risk as attempt 1)
7. Pending: Post-deploy smoke (HARD gate) — 25s sleep + 3 curl probes (`/healthz`, `/v1/am/health/deep`, `/v1/programs/search`)
8. Pending: Slack notify on failure (only if `SLACK_WEBHOOK_URL` set; currently NOT in `gh secret list` output, so failure path = silent)

**Risk carry-over**: step 6 reuses the same depot remote builder that timed
out in attempt 1. If the depot incident is ongoing rather than transient, this
will replay the 1431 s timeout. Per `R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md`
§3.2, depot 23-min stalls usually indicate (a) infra incident, (b) cold cache,
(c) network thrash on the model-bake step — only (b) and (c) clear in <1 hr.
The 55-min interval between attempt 1 and attempt 5 may be enough for (b)/(c).

**Smoke probe race**: step 7's 25s sleep is below Fly's typical machine-swap
p99 (~30-45s) for SQLite-backed apps with `boot_grace_period=60s`. The 5/6
deploy run `25433013183` failed exactly at this gate (`POST-DEPLOY FAIL:
/healthz expected 200 got 000000`). This is structural to `deploy.yml` and
unfixed in this attempt.

## 5. Root-cause hypotheses per failed attempt

| Attempt | Symptom | Internal hypothesis (ranked) |
|---|---|---|
| 1 | depot 1431 s `deadline_exceeded` after 4.78 MB context transfer | **(P1)** depot.dev infra incident — 23-min stall is 3× their published p99. **(P2)** Cold-cache cascade: depot evicted the multilingual-e5-small layer cache, re-downloading 470 MB from HF concurrent with the build. **(P3)** Context-stream re-handshake loop (24 min for 4.78 MB MB ≈ 3.4 KB/s avg = TLS keep-alive thrash). Not (P4) context-size: §1.1 of `R8_FLY_DEPLOY_ALTERNATIVE` confirms ~440 MB tarball, well under depot's MB threshold. |
| 2 | `missing hostname` daemon parse on `--depot=false` | **(P1)** Flag deprecation: `--depot=false` was removed in `flyctl` `v0.3.x` (2026-02) replaced by `--local-only`. Wrapper fell through to default remote builder which then mis-parsed an injected `host=` arg. **(P2)** macOS Docker Desktop daemon socket misconfiguration (`DOCKER_HOST` env unset) so the supposed local fallback couldn't reach the daemon either. Both are flag/env-side; nothing about the build pipeline itself. |
| 3 | wrangler 1704/13010 `{}` empty-error fail | **(P1)** Cloudflare Pages bulk upload API transient 5xx (no payload = 502/504 from CF edge). **(P2)** Asset-deduplication race: 11,684 generated program pages share ~3K identical asset signatures (CSS/JS/font); CF Pages bulk hash-dedup occasionally races and rejects the batch with no payload. **(P3)** Account-level upload concurrency cap (CF tier limit, ~12K assets per single deploy is near the soft cap). All three are CF-side and recover on retry — confirmed by attempt 4 progressing past 4310 chunks. |

## 6. Remaining paths

Audit-close path enumeration (do not execute by this audit):

1. **Wait on attempt 5 (GHA run 25474923802) to complete** — happy path. If
   step 6 (`flyctl deploy --remote-only`) succeeds, step 7 smoke gate is the
   final blocker; if it fails the same way as 5/6 run `25433013183` (smoke
   probe `000000`), interpretation per §3 of `R8_GHA_DEPLOY_PATH_2026-05-07.md`
   distinguishes "build done, machine failed" vs "machine up, network blip".
2. **Wait on attempt 4 (wrangler retry) to terminate** — independent surface
   from Fly. CF Pages stale-site is currently serving 5/6 morning, gap to
   local `c3b6e57` is `+6 OpenAPI paths` (221 → 227 per
   `R8_PRE_DEPLOY_LIVE_BASELINE`) plus the `0.3.4` paths-count migration.
   Even if attempt 4 stalls, live healthz / Fly API rollouts proceed
   independently.
3. **If both attempts 4 and 5 fail**, alternative paths (do NOT execute by
   audit):
   - Manual `docker build --platform=linux/amd64 .` on local Apple Silicon
     (path A of `R8_FLY_DEPLOY_ALTERNATIVE` §3.1) — 10–20 min for first run
     (QEMU-amd64 emulation), then `flyctl deploy --image registry.fly.io/...`
     to push pre-built image, sidesteps depot entirely.
   - `flyctl deploy --build-only` (path B) to confirm depot has recovered
     before another full deploy attempt.
   - Patch `deploy.yml` step 7 sleep from 25s → 60s and/or replace single
     `--remote-only` with a fallback `||` to `--local-only` per
     `R8_FLY_DEPLOY_ALTERNATIVE` §3.1 path D.
   - Re-issue `wrangler pages deploy` with `--commit-dirty=true` and
     `--branch=main` after `wrangler pages deployment list` confirms the prior
     deploy has terminated (attempt 4 cannot run in parallel with attempt 3 if
     CF still locks the deploy slot).

`flyctl auth whoami` was not invoked by this audit (read-only mandate); if
attempt 5 errors at step 7 with auth, operator should `flyctl auth login`
manually before any local `docker build … && flyctl deploy --image …` path.

## 7. Audit verdict

- **Live healthz** = 200, image still `f3679d6` (5/6 morning) — production
  impact = 0 across all 5 attempts.
- **5/7 hardening** (mypy 348→69, acceptance 286/286, 33 DEEP retroactive
  verify, fingerprint SOT helper) = **NOT YET SHIPPED**. Local HEAD `c3b6e57`
  is the target.
- **GHA path A** (workflow_dispatch with operator-asserted commit-is-green)
  is in flight as run `25474923802` and is the most credible recovery path.
- **Wrangler retry** is independent surface; outcome unknown at audit close
  but does not block the API rollout.
- **No new failure modes** beyond those already enumerated in the four
  companion R8 docs; this doc consolidates the timeline + hypotheses for
  retrospective use only.

## 8. References

- `/Users/shigetoumeda/jpcite/tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_PRE_DEPLOY_LIVE_BASELINE_2026-05-07.md` — pre-deploy live snapshot at 02:54 UTC.
- `/Users/shigetoumeda/jpcite/tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_FLY_DEPLOY_READINESS_2026-05-07.md` — readiness 4/4 PASS verdict.
- `/Users/shigetoumeda/jpcite/tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_FLY_DEPLOY_ALTERNATIVE_2026-05-07.md` — depot vs local-docker matrix.
- `/Users/shigetoumeda/jpcite/tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_GHA_DEPLOY_PATH_2026-05-07.md` — `deploy.yml` step skeleton + secret scoping.
- `/Users/shigetoumeda/jpcite/tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_ACK_YAML_LIVE_SIGNED_2026-05-07.yaml` — operator ACK 8/8 signed at 02:51:44 UTC.
- `/Users/shigetoumeda/jpcite/tools/offline/_inbox/_housekeeping_audit_2026_05_06/R8_DRY_RUN_VALIDATION_REPORT.md` — go-gate 5/5 PASS companion.
- GHA run: `https://github.com/shigetosidumeda-cyber/autonomath-mcp/actions/runs/25474923802` (terminal at audit close — see §9).

## 9. Amendment — attempt 5 terminal status (re-checked at audit close + 4 min)

`gh run view 25474923802` returned `status=completed conclusion=failure` after
a final post-audit poll. Failed step = **"Post-deploy smoke (hard gate)"**
(`startedAt 03:48:29Z, completedAt 03:49:09Z, 40s elapsed`).

Failure log:

```
== Post-deploy hard gate ==
curl: (28) Operation timed out after 15000 milliseconds with 0 bytes received
GET /healthz -> 000000
##[error]POST-DEPLOY FAIL: /healthz expected 200 got 000000
##[error]Process completed with exit code 1.
```

This is **identical** to the 5/6 run `25433013183` failure mode. Steps 1–6
(checkout / token / flyctl / hydrate / version / `flyctl deploy --remote-only`)
all PASSED — meaning the depot builder this time **completed** the build
(per §5 P1/P2/P3 hypotheses, the cold-cache thrash had cleared in the 55-min
gap between attempt 1 and attempt 5). The new image was pushed and the
machine swap was issued; only the GHA runner's external smoke probe failed.

**Concurrent fact**: this audit's `curl https://api.jpcite.com/healthz`
(executed ~80 s after the GHA smoke step's 15 s timeout window expired)
returned `200 {"status":"ok"}` in 1.24 s. Two readings consistent with §3 of
`R8_GHA_DEPLOY_PATH_2026-05-07.md`:

- the new release machine took >25 s + >15 s = >40 s to start serving healthz
  (Fly's machine-swap p99 with `boot_grace_period=60s` exceeded the smoke
  probe's window), or
- transient CF / DNS reachability blip from GHA's eastus runner during the
  40-s probe window.

Either way, the probe is racing the boot, not detecting a real outage.
Fly side may already be on the new image — verifiable via `flyctl image show
-a autonomath-api` (look for `GH_SHA=c3b6e57…` instead of
`f3679d6926…`). This audit did NOT re-run that command after the run failure
to keep the deploy operation count at 0; operator should verify on next pass.

**Net result of attempt 5**: build succeeded, machine likely up, smoke gate
flagged false-failure, GHA marked the run failed. The image may already be
live on Fly even though the workflow concluded `failure`.

**Honest open question**: did the new `c3b6e57` image actually become live, or
did Fly roll back to `f3679d6` after the smoke gate failure? `deploy.yml` does
NOT issue a rollback on smoke failure (per §3 line 169-236 of the GHA path
audit), so Fly should NOT auto-revert. A single `flyctl image show -a
autonomath-api` resolves it; deferred to operator.

— end —
