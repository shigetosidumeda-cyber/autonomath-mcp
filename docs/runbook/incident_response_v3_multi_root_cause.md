---
title: Multi-Root-Cause Deploy Incident Response Runbook v3
updated: 2026-05-12
operator_only: true
category: incident
supersedes: docs/runbook/incident_response_db_boot_hang_v2.md
related_postmortem: docs/postmortem/2026-05-11_18h_outage_v3.md
related_memory:
  - feedback_no_quick_check_on_huge_sqlite
  - feedback_pre_deploy_manifest_verify
  - feedback_deploy_yml_4_fix_pattern
  - feedback_post_deploy_smoke_propagation
  - feedback_dual_cli_lane_atomic
  - feedback_multi_root_cause_chain
---

# Multi-Root-Cause Deploy Incident Response Runbook v3

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Last reviewed**: 2026-05-12 (post Wave 45)

This runbook supersedes v2 (`incident_response_db_boot_hang_v2.md`).
v2 covered 4 RCs (RC1 integrity_check hang / RC2 depot builder
stall / RC3 manifest empty / RC4 GHA workflow_run skip — note the
v2 numbering treated the local Docker hang as a separate RC; v3
folds it under RC2). v3 adds the **fifth RC** (parallel-agent
branch contention) and reorganizes around the **multi-RC detection
flow** — incidents almost never have a single cause.

| RC | Signature | Mitigation | Strategy |
| -- | --- | --- | --- |
| RC1 | `flyctl logs` shows `running integrity_check on /data/autonomath.db` with no follow-up `ok` / `size-based skip` line (5+ min). `CHECKS: 0/1` while `instance_state: started`. | Wave 18 §4 size-based skip (commit `81922433f`). | A / B |
| RC2 | `flyctl deploy --remote-only` hangs in the depot builder build-context upload phase for ≥60 min, OR `docker build` on engineer laptop hangs in `apt unpack` step. | Wave 22 baked seed + Wave 24 .dockerignore audit. Switch to GHA `workflow_dispatch` (Strategy F). | F |
| RC3 | `flyctl logs` shows `autonomath: required migrations missing from schema_migrations: [...]` then non-zero exit. Restart-loop. | Wave 40 PR #75 manifest authorize + Wave 41 pre_deploy_manifest_verify.py gate. | G |
| RC4 | GHA `deploy.yml` runs green but `verify.yml` / `acceptance-criteria-ci.yml` show as **skipped** instead of green; healthz manually 200 but CI signal is "skipped". | Wave 41 direct-dispatch pattern: trigger each downstream workflow via explicit `gh workflow run`, never rely on `workflow_run` chains. | F-strict |
| RC5 | Two or more open PRs simultaneously show "conflict" on the same file in `scripts/migrations/autonomath_boot_manifest.txt`, `.github/workflows/deploy.yml`, `pyproject.toml`, or `server.json`. Strategy F retry pipeline stalls waiting for `main` to be linear. | Wave 44 worktree-isolation principle (memory `feedback_dual_cli_lane_atomic`): mkdir-atomic lane claim, AGENT_LEDGER append-only, single integrator pass for shared files. | W |

Related references:

- Post-mortem v3: `docs/postmortem/2026-05-11_18h_outage_v3.md` (18h+
  outage, 5 RCs, Wave 22-44 chain).
- Post-mortem v2: `docs/postmortem/2026-05-11_14h_outage_v2.md` (14h+
  outage, 4 RCs, Wave 22-40 segment).
- Post-mortem v1: `docs/postmortem/2026-05-11_integrity_check_outage.md`
  (5h12m outage, RC1 only).
- `entrypoint.sh` §2 (size-based SHA skip, Wave 13) and §4
  (size-based integrity_check skip, Wave 18 commit `81922433f`).
- `scripts/migrations/autonomath_boot_manifest.txt` — boot allowlist
  (PR #75 lifted to 5 entries; Wave 43+ added 252-266).
- `scripts/schema_guard.py` — `AM_REQUIRED_MIGRATIONS` is the source
  of truth.
- `scripts/ops/pre_deploy_manifest_verify.py` — gate that asserts
  manifest superset of required migrations.
- `scripts/cron/db_boot_hang_alert.py` — daily watchdog (Wave 45
  extended to all 5 RC patterns).
- `docs/runbook/db_corruption_recovery.md` — branch here if Phase 2
  shows actual corruption (rare).
- `docs/runbook/fly_machine_oom.md` — branch here if Phase 2 shows
  `exit_code=137`.

## Phase 1 — Multi-RC Detection (0-5 min)

**You are here** if any of these fire:

```text
A. UptimeRobot 502/504 alert on api.jpcite.com/healthz (3 × 60s).
B. Fly proxy log: "could not find a good candidate within 40 attempts at load balancing".
C. Cron alert from scripts/cron/db_boot_hang_alert.py (Telegram).
D. flyctl status -a autonomath-api shows CHECKS: 0/1 with instance_state=started.
E. flyctl status shows restarts > 5 within the last 10 min on any machine.
F. GHA deploy.yml ran but verify.yml / acceptance-criteria-ci.yml show "skipped".
G. gh pr list --search 'is:open conflict' returns ≥2 open PRs during a deploy window.
```

**Immediate multi-RC triage** (90s, do not skip — covers all 5 RC
patterns):

```bash
# Probe 1 — RC1/RC3 boot signals
flyctl logs -a autonomath-api --no-tail -n 500 \
  | grep -E "integrity_check|schema_guard|required migrations|VACUUM|REINDEX|ANALYZE" \
  | tail -30

# Probe 2 — RC2 deploy infra signal (only relevant if mid-deploy)
gh run list --workflow=deploy.yml -L 3
flyctl agent ps 2>/dev/null | head -10 || true

# Probe 3 — RC4 CI chain signal
gh run list -L 5 --json status,conclusion,name \
  | jq '.[] | select(.conclusion == "skipped" and (.name | test("verify|acceptance|smoke")))' \
  | head -10

# Probe 4 — RC5 PR conflict signal
gh pr list --search 'is:open conflict' --json number,title,mergeable \
  | jq '.[] | select(.mergeable == "CONFLICTING")'
```

**Multi-RC pattern match** — map probe outputs to the RC table:

- **RC1 (integrity_check hang)**: Probe 1 shows `running
  integrity_check on /data/autonomath.db` with no follow-up `ok` /
  `size-based skip` line. Continue to Phase 2 → Strategy A / B.
- **RC3 (schema_guard FAIL on fresh volume)**: Probe 1 shows
  `autonomath: required migrations missing from schema_migrations:
  ['...']`. Continue to Phase 2 → Strategy G.
- **RC2 (deploy infra stuck)**: Probe 2 shows depot builder upload
  or local docker hang. See Phase 3 → Strategy F.
- **RC4 (CI chain skip)**: Probe 3 shows `skipped` conclusions on
  downstream verify workflows. See Phase 3 → Strategy F-strict.
- **RC5 (PR conflict storm)**: Probe 4 shows ≥2 open PRs marked
  CONFLICTING. See Phase 3 → Strategy W (worktree isolation).
- **Multiple RCs simultaneously**: Phase 3 is **NOT serial — apply
  strategies in parallel where they don't collide.** Specifically:
  Strategy W (RC5) must run first because PR conflicts block
  Strategy G (RC3 manifest fix) from merging.
- **Out of memory / Killed process / exit_code=137**: stop here and
  re-route to `docs/runbook/fly_machine_oom.md`.
- **SHA256 mismatch / R2 re-download looping**: stop here and
  re-route to `docs/runbook/db_corruption_recovery.md`.
- **Logs silent (no entrypoint output at all)**: machine may not
  have started — `flyctl machine list` to confirm instance state.

## Phase 2 — Diagnosis (5-15 min)

Confirm machine + image SHA so you know whether the Wave 18 (RC1)
and Wave 40 (RC3) fixes are even on the running image:

```bash
# Machine state
flyctl status -a autonomath-api
flyctl machine list -a autonomath-api

# Current main HEAD for entrypoint.sh and boot manifest
git -C /Users/shigetoumeda/jpcite log -1 --format='%H %s' -- entrypoint.sh
git -C /Users/shigetoumeda/jpcite log -1 --format='%H %s' -- scripts/migrations/autonomath_boot_manifest.txt

# Wave 18 §4 fix should appear in entrypoint.sh history
git -C /Users/shigetoumeda/jpcite log --oneline entrypoint.sh | grep -iE 'wave 18|integrity_check'
# Expect: 81922433f fix(boot): apply size-based skip to §4 integrity_check (Wave 18) (#35)

# Wave 40 manifest fix should appear in autonomath_boot_manifest.txt history
git -C /Users/shigetoumeda/jpcite log --oneline scripts/migrations/autonomath_boot_manifest.txt | head -5
# Expect a commit referencing Wave 40 / "authorize 5 missing migrations" / PR #75
```

Run the manifest superset gate locally to confirm `main` is in sync:

```bash
python3 /Users/shigetoumeda/jpcite/scripts/ops/pre_deploy_manifest_verify.py
# Expect: {"ok": true, ...}
# rc=0 — manifest contract holds
# rc=1 — manifest missing required migration; before re-deploy, fix manifest first
```

If the running image **predates** the relevant fix, the image is the
problem and you need to ship a new image — go to Phase 3 Strategy A
or F.

If the running image **includes** both fixes:

- **For RC1**: check the env on the machine —
  `BOOT_ENFORCE_INTEGRITY_CHECK=1` would force the legacy path.
  Unset it (Strategy B).
- **For RC3**: confirm the boot manifest on the **running image**
  matches `main` HEAD — operator may have deployed a stale image
  SHA:

```bash
flyctl ssh console -a autonomath-api -C 'cat /app/scripts/migrations/autonomath_boot_manifest.txt'
# Compare against scripts/migrations/autonomath_boot_manifest.txt on main HEAD.
```

If they diverge, the running image is stale — go to Strategy F to
push a fresh image from current `main`.

For RC5 (PR conflict storm), diagnose which PRs are conflicting on
which files:

```bash
gh pr list --search 'is:open conflict' --json number,title,files \
  | jq '.[] | {n: .number, t: .title, f: [.files[].path]}'
```

If multiple PRs all touch `scripts/migrations/autonomath_boot_manifest.txt`
or `.github/workflows/deploy.yml`, that is the canonical RC5
signature.

## Phase 3 — Mitigation (15-60 min)

**Multi-RC application rule**: pick one strategy per detected RC.
**Apply strategies in dependency order**, not in parallel:

1. **Strategy W (RC5 worktree-isolate)** must run FIRST if PR
   conflicts are open. Strategy F / G cannot land a fix until
   `main` is linear.
2. **Strategy G (RC3 manifest authorize)** runs SECOND. The manifest
   fix must be in the image being deployed; without it Strategy F
   ships a broken image.
3. **Strategy F (RC2 / RC4 deploy)** runs THIRD. Ships the image
   with G's fix to prod.
4. **Strategy A / B / C (RC1 boot)** runs FOURTH only if the running
   image still trips RC1 after the rolling restart. With Wave 18 on
   the image, this should be a no-op.

### Strategy W — Worktree-isolation (RC5 fix)

**Use when**: ≥2 open PRs marked CONFLICTING on the same shared
file (boot manifest / deploy.yml / version files).

Step 1 — list every conflicting PR:

```bash
gh pr list --search 'is:open conflict' --json number,title,files,headRefName \
  | jq '.[] | {n: .number, t: .title, b: .headRefName}'
```

Step 2 — for each conflicting PR, rebase from `main`:

```bash
# Example: PR #102 conflicts on boot manifest
git -C /Users/shigetoumeda/jpcite fetch origin main
git -C /Users/shigetoumeda/jpcite checkout <branch-of-pr-102>
git -C /Users/shigetoumeda/jpcite rebase origin/main
# Resolve manifest conflict by accepting both additions (the manifest
# is append-only — there is rarely a true semantic conflict).
git -C /Users/shigetoumeda/jpcite add scripts/migrations/autonomath_boot_manifest.txt
git -C /Users/shigetoumeda/jpcite rebase --continue
git -C /Users/shigetoumeda/jpcite push --force-with-lease origin <branch-of-pr-102>
```

Step 3 — for any new subagent work spinning up during the recovery
window, enforce worktree isolation per memory
`feedback_dual_cli_lane_atomic`:

```bash
# Each subagent claims its own worktree
LANE=wave45-postmortem-v3
mkdir -p tools/offline/_inbox/$LANE
mkdir tools/offline/_inbox/$LANE/agent-$$ 2>/dev/null || { echo "lane already claimed by another agent"; exit 1; }
echo "$(date -u +%FT%TZ) agent-$$ claim" >> tools/offline/_inbox/$LANE/AGENT_LEDGER.md

# Subagent branches from main, never from another agent's branch
git worktree add -b feat/jpcite_$(date +%Y_%m_%d)_$LANE /tmp/jpcite-$LANE main
```

Step 4 — once all conflicting PRs are rebased and merged in
dependency order (boot manifest last, then version bump, then
deploy.yml), confirm `main` is linear:

```bash
gh pr list --search 'is:open' --json number,mergeable \
  | jq '[.[] | select(.mergeable == "CONFLICTING")] | length'
# Expect 0.
```

### Strategy A — Local `flyctl deploy --remote-only` (RC1 fix path 1)

**Use when**: RC1 detected and image predates `81922433f`, AND your
local working tree is clean enough to upload (no >10 GB build
context).

```bash
git -C /Users/shigetoumeda/jpcite status
git -C /Users/shigetoumeda/jpcite log -1 --format='%H %s'

flyctl deploy --remote-only --strategy rolling -a autonomath-api
```

**Notes**:

- `--remote-only` forces the depot builder; GHA runner is bypassed.
- `--strategy rolling` keeps one machine serving while the other
  restarts.
- Local depot builds the image from your working tree, so the
  working tree must reflect main HEAD or a hotfix commit. Run
  `git status` first.

**Failure mode**: If the depot upload hangs ≥10 min without
progress, you are hitting RC2. Cancel and move to Strategy F.

### Strategy B — Env-injection (RC1 fix path 2)

**Use when**: RC1 detected, image **already includes** `81922433f`,
and the legacy path is being forced via
`BOOT_ENFORCE_INTEGRITY_CHECK=1`.

```bash
flyctl machine list -a autonomath-api
flyctl machine update --env BOOT_ENFORCE_INTEGRITY_CHECK=0 <machine_id> -a autonomath-api
flyctl machine status <machine_id> -a autonomath-api
flyctl machine restart <machine_id> -a autonomath-api
```

Repeat per machine.

### Strategy C — Machine destroy + clone (RC1 fix path 3, last resort)

**Use when**: Strategies A and B both fail for RC1.

**Warning**: This re-arms RC3 if the running image's boot manifest
is out of sync with `schema_guard`. Run
`python3 scripts/ops/pre_deploy_manifest_verify.py` FIRST. If it
returns non-zero, do **not** destroy/clone — go to Strategy F to
ship the manifest fix first.

```bash
flyctl machine clone <hung_machine_id> -a autonomath-api --region nrt
flyctl status -a autonomath-api
# Once clone healthy:
flyctl machine destroy <hung_machine_id> -a autonomath-api --force
```

### Strategy F — GHA `workflow_dispatch` deploy (RC2 / RC4 escape)

**Use when**: `flyctl deploy --remote-only` (Strategy A) hangs in
the depot upload phase for ≥10 min, OR engineer laptop Docker build
hangs.

This is the path that recovered the 2026-05-12 cascade. Strategy F
delegates the build to GitHub Actions runners, bypassing both depot
upload and local Docker Desktop.

```bash
# From local checkout, on a clean main HEAD.
git -C /Users/shigetoumeda/jpcite status
git -C /Users/shigetoumeda/jpcite log -1 --format='%H %s'

# Trigger the deploy workflow manually.
gh workflow run deploy.yml --ref main

# Watch progress.
gh run list --workflow=deploy.yml -L 3
gh run watch $(gh run list --workflow=deploy.yml -L 1 --json databaseId -q '.[0].databaseId')
```

The deploy workflow runs the full build + push + rolling restart on
a GHA runner with a stable build context. ETA 12-18 min.

**Watch for the deploy.yml 4-fix pattern**:

- `smoke_sleep_race` — post-deploy curl runs before Fly proxy
  propagation; fixed by `sleep 60` step.
- `preflight_ci_tolerance` — preflight script runs differently in
  CI vs prod; CI tolerates missing flyctl.
- `hydrate_size_guard` — sftp hydrate refuses to overwrite the
  baked seed; fixed by size guard.
- `sftp_rm_idempotency` — `flyctl ssh sftp` `rm` fails if file
  absent; fixed by `|| true`.

If GHA `deploy.yml` itself fails on one of those 4 axes, follow the
fix in commit `6e3307c` (memory `feedback_deploy_yml_4_fix_pattern`).

### Strategy F-strict — direct-dispatch every downstream workflow (RC4 fix)

**Use when**: Strategy F's parent `deploy.yml` ran green but
downstream `verify.yml` / `acceptance-criteria-ci.yml` /
`smoke.yml` show as **skipped** instead of green.

The `workflow_run` guard on these subsidiaries expects a `push`
event shape; `workflow_dispatch` from Strategy F evaluates as
"skip". Bypass the chain by dispatching each workflow directly:

```bash
# After Strategy F deploy completes:
gh workflow run verify.yml --ref main
gh workflow run acceptance-criteria-ci.yml --ref main
gh workflow run smoke.yml --ref main  # if separate
gh workflow run post-deploy-verify-v4.yml --ref main  # if separate

# Watch each in parallel
gh run list -L 5 --json status,conclusion,name | \
  jq '.[] | select(.name | test("verify|acceptance|smoke|post-deploy"))'
```

**Workflow audit task** (do once per recovery cycle): list every
workflow chained off `deploy.yml` via `workflow_run`, and confirm
each has its own `workflow_dispatch` trigger so this bypass works:

```bash
grep -lE '^on:\s*$' .github/workflows/*.yml | while read -r f; do
  if grep -q 'workflow_run:' "$f"; then
    if ! grep -q 'workflow_dispatch:' "$f"; then
      echo "MISSING workflow_dispatch trigger: $f"
    fi
  fi
done
```

Any workflow listed as MISSING is a candidate for the next preventive
PR — add an explicit `workflow_dispatch:` trigger so Strategy
F-strict works on it next time.

### Strategy G — Authorize required migrations in boot manifest (RC3 fix)

**Use when**: RC3 detected (`required migrations missing from
schema_migrations`).

Step 1 — Identify the missing migrations:

```bash
flyctl logs -a autonomath-api --no-tail -n 500 \
  | grep 'required migrations missing' | tail -1
```

The log line lists every missing migration filename.

Step 2 — Verify each missing migration is autonomath-target and
additive:

```bash
for f in $(echo "<paste filename list from step 1>"); do
  echo "=== $f ==="
  head -10 /Users/shigetoumeda/jpcite/scripts/migrations/$f
  grep -qE 'DROP|DELETE|ALTER.*DROP' /Users/shigetoumeda/jpcite/scripts/migrations/$f \
    && echo "*** DESTRUCTIVE *** — do not authorize without manual review" \
    || echo "(safe additive)"
done
```

Step 3 — Authorize in manifest (append filenames + comment header).
See PR #75 for the canonical pattern. **Append-only**; do not
rewrite the manifest body — append at EOF to minimize merge
conflicts with parallel agent branches (memory
`feedback_dual_cli_lane_atomic`).

Step 4 — Re-deploy via Strategy F (the boot manifest change must
ship in a new image).

Step 5 — After deploy, confirm `pre_deploy_manifest_verify.py`
returns ok and `schema_guard` PASS line in logs:

```bash
python3 /Users/shigetoumeda/jpcite/scripts/ops/pre_deploy_manifest_verify.py
flyctl logs -a autonomath-api --no-tail -n 200 | grep -E "schema_guard ok|am_schema_ok"
```

## Phase 4 — Verification (60-90 min)

After Phase 3 completes:

### 1. Run post-deploy smoke v4 (15 check, Wave 41)

```bash
bash /Users/shigetoumeda/jpcite/scripts/ops/post_deploy_verify_v4.sh
# Expect: 15/15 PASS
```

v4 includes:

- healthz 200
- openapi.json path-count floor (178)
- 30+ endpoint 200 sweep
- CF Pages parity (7 static endpoints)
- disclaimer envelope
- Stripe portal surface
- **manifest superset gate** (RC3 prevention)
- Fly machine state
- **schema_guard PASS evidence in boot log** (RC3 signal)
- **integrity_check size-skip evidence in boot log** (RC1 signal)
- MCP manifest accessibility
- audit discovery non-empty
- rate-limit header coherence
- multilingual lang param (en/zh/ko)
- **5-min stability window** (5× spaced 30s healthz)

### 2. 5-min stability hold

If running v4 manually, the final check is a 5-min stability window;
otherwise re-confirm spacing:

```bash
for i in $(seq 1 5); do
  date -u +%H:%M:%SZ
  curl --max-time 30 -fsSI https://api.jpcite.com/healthz | head -1
  sleep 60
done
```

### 3. Customer-facing surface walk (sample)

```bash
curl --max-time 30 -fsSI 'https://api.jpcite.com/v1/programs/search?q=ものづくり' | head -1
curl --max-time 30 -fsSI https://api.jpcite.com/v1/am/health/deep | head -1
curl --max-time 30 -fsSI https://jpcite.com/ | head -1
```

All must return `HTTP/2 200`.

### 4. CI chain sanity (RC4 prevention)

Confirm every downstream verify workflow ran green AFTER Strategy F:

```bash
gh run list -L 10 --json status,conclusion,name \
  | jq '.[] | select(.name | test("verify|acceptance|smoke|post-deploy")) | {n: .name, c: .conclusion}'
```

Any `skipped` is a RC4 reproduction. Re-dispatch via Strategy
F-strict.

### 5. PR conflict sweep (RC5 prevention)

```bash
gh pr list --search 'is:open conflict' --json number,title
```

Expect empty. If non-empty, the next deploy will stall on Strategy
F. Apply Strategy W to clear.

## Phase 5 — Post-incident (24h)

Within 24 hours of resolution:

1. Update `docs/postmortem/YYYY-MM-DD_<short>.md` with timeline +
   each RC that fired + any new failure-mode learnings. If the
   cause was a new full-scan boot op, add it to the foot-gun list
   in memory `feedback_no_quick_check_on_huge_sqlite`. If the cause
   was a new packaging change re-arming a latent boot invariant,
   add it to memory `feedback_pre_deploy_manifest_verify`. If the
   cause was a new CI chain anti-pattern, add it to memory
   `feedback_deploy_yml_4_fix_pattern`. If the cause was a new
   parallel-agent contention pattern, add it to memory
   `feedback_dual_cli_lane_atomic` + `feedback_multi_root_cause_chain`.
2. Confirm `scripts/cron/db_boot_hang_alert.py` is in the daily
   cron and that it would have caught this specific shape. The
   Wave 45 extension covers all 5 RC patterns.
3. If Strategy A (local deploy) was used, push any pending GHA
   `deploy.yml` fix so Strategy F also works next time — do not
   leave the GHA path broken.
4. Verify Phase 1 detection chain end-to-end (UptimeRobot →
   Telegram bot → operator phone) by sending a synthetic alert.
5. Re-run the workflow audit task in Strategy F-strict — any new
   workflow chained off deploy.yml without a `workflow_dispatch`
   trigger is a latent RC4 trap.

## Operator notes

- `flyctl ssh sftp get` from this runbook is read-only — it cannot
  corrupt the volume.
- Do **not** run `PRAGMA integrity_check` or `PRAGMA quick_check`
  interactively on `/data/autonomath.db` while diagnosing — it will
  cause the same hang you are trying to fix.
- `entrypoint.sh` is **not** rolled back by re-deploying an older
  image tag; the volume contents persist and the next boot runs
  whatever `entrypoint.sh` is in the new image. Hot-rollback via
  flyctl deploy with `--image registry.fly.io/...:<old-tag>` is
  only safe if you've confirmed the old image has BOTH the
  size-based skip AND the boot manifest containing all
  `AM_REQUIRED_MIGRATIONS`.
- Solo zero-touch ops — no escalation tree, no PagerDuty rotation.
  Detection chain: UptimeRobot → Telegram bot → operator phone.
- **A new boot foot-gun adds a strategy here, not a phase.** Phase
  1-5 shape stays stable; strategies A/B/C/F/F-strict/G/W can grow.
- **Recovery runs entirely on Claude Code Max Pro** (no LLM API
  calls) per memory `feedback_no_operator_llm_api`. No metered ¥0.5/req
  cost incurred during recovery.

## Quick reference — multi-RC strategy selection matrix

| Symptom | First strategy | Fallback |
| --- | --- | --- |
| RC1 + image stale | A | F |
| RC1 + env force | B | A |
| RC1 + Strategies A+B fail | C | (DR) |
| RC2 (depot hang) | F | (laptop, do not use) |
| RC3 (manifest gap) | G → F | (offline migration run via flyctl ssh — destructive, avoid) |
| RC4 (CI chain skip) | F-strict | manual `gh workflow run` per workflow |
| RC5 (PR conflict storm) | W (worktree isolate) | manual rebase loop |
| Multi-RC (RC3 + RC5 simultaneously) | W → G → F (dependency order) | (do not parallelize) |
| Multi-RC (RC2 + RC4) | F → F-strict | (do not skip F-strict — leaves CI confused) |

## Multi-RC dependency graph

```
RC5 (PR conflict)         ←  must clear first or no fix can merge
  ↓ (main is linear)
RC3 (manifest gap)        ←  must be in main HEAD before re-deploy
  ↓ (manifest superset gate passes)
RC2 (deploy infra)        ←  ship the image
  ↓ (Strategy F runs)
RC4 (CI chain skip)       ←  dispatch downstream verify explicitly
  ↓ (CI green)
RC1 (boot integrity)      ←  verify size-based skip on cold boot
  ↓ (5-min stability)
GREEN — incident closed
```

The graph is **strictly ordered when multiple RCs are open
simultaneously**. Skipping a level means the next level cannot land
its fix. v3's defining lesson: **multi-RC chains do not parallelize
— they serialize.**

---

_If this runbook didn't resolve the incident in 90 minutes, escape
to `docs/runbook/disaster_recovery.md` and treat as full DR._
