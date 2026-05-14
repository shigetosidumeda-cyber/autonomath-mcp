---
title: DB Boot Failure Incident Response Runbook v2 (4-RC strategy)
updated: 2026-05-12
operator_only: true
category: incident
supersedes: docs/runbook/incident_response_db_boot_hang.md
related_postmortem: docs/postmortem/2026-05-11_14h_outage_v2.md
related_memory:
  - feedback_no_quick_check_on_huge_sqlite
  - feedback_pre_deploy_manifest_verify
  - feedback_deploy_yml_4_fix_pattern
  - feedback_post_deploy_smoke_propagation
---

# DB Boot Failure Incident Response Runbook v2

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Last reviewed**: 2026-05-12 (post 14h outage)

This runbook supersedes v1 (`incident_response_db_boot_hang.md`).
v1 covered only the RC1 shape (integrity_check hang). v2 covers all
four root causes that fired in the 2026-05-11/12 cascade:

| RC | Signature | Mitigation | Phase 3 strategy |
| -- | --- | --- | --- |
| RC1 | `flyctl logs` shows `running integrity_check on /data/autonomath.db` with no follow-up `ok` / `size-based skip` line (5+ min). `CHECKS: 0/1` while `instance_state: started`. | Wave 18 §4 size-based skip (commit `81922433f`). | A / B |
| RC2 | `flyctl deploy --remote-only` hangs in the depot builder build-context upload phase for ≥60 min. | Switch to GHA `workflow_dispatch`. | F |
| RC3 | `docker build` on engineer laptop hangs in `apt unpack` step. | Abandon local build; depend on remote builder. | (do not use) |
| RC4 | `flyctl logs` shows `autonomath: required migrations missing from schema_migrations: [...]` then non-zero exit. Restart-loop. | Wave 40 PR #75 manifest authorize. | G |

Related references:

- Post-mortem v2: `docs/postmortem/2026-05-11_14h_outage_v2.md` (14h+ outage, 4 RCs).
- Post-mortem v1: `docs/postmortem/2026-05-11_integrity_check_outage.md` (5h12m outage, RC1 only).
- `entrypoint.sh` §2 (size-based SHA skip, Wave 13) and §4 (size-based integrity_check skip, Wave 18 commit `81922433f`).
- `scripts/migrations/autonomath_boot_manifest.txt` — boot allowlist (PR #75 lifted to 5 entries).
- `scripts/schema_guard.py` — `AM_REQUIRED_MIGRATIONS` set is the source of truth.
- `scripts/ops/pre_deploy_manifest_verify.py` — gate that asserts manifest superset of required migrations.
- `scripts/cron/db_boot_hang_alert.py` — daily watchdog (Wave 41 extended to RC4 FAIL pattern).
- `docs/runbook/db_corruption_recovery.md` — branch here if Phase 2 shows actual corruption (rare).
- `docs/runbook/fly_machine_oom.md` — branch here if Phase 2 shows `exit_code=137`.

## Phase 1 — Detection (0–5 min)

**You are here** if any of these fire:

```text
A. UptimeRobot 502/504 alert on api.jpcite.com/healthz (3 × 60s).
B. Fly proxy log: "could not find a good candidate within 40 attempts at load balancing".
C. Cron alert from scripts/cron/db_boot_hang_alert.py (Telegram).
D. flyctl status -a autonomath-api shows CHECKS: 0/1 with instance_state=started.
E. flyctl status shows restarts > 5 within the last 10 min on any machine.
```

**Immediate triage** (60s, do not skip):

```bash
flyctl status -a autonomath-api
flyctl logs -a autonomath-api --no-tail -n 500 \
  | grep -E "integrity_check|schema_guard|required migrations|VACUUM|REINDEX|ANALYZE" \
  | tail -30
```

Pattern match the log output to determine which RC you are in:

- **RC1 (integrity_check hang)**: `running integrity_check on /data/autonomath.db` with no follow-up `ok` / `size-based skip` line. Continue to Phase 2 → 3-A or 3-B.
- **RC4 (schema_guard FAIL on fresh volume)**: `autonomath: required migrations missing from schema_migrations: ['...']`. Continue to Phase 2 → 3-G.
- **RC2 / RC3 (deploy infrastructure stuck)**: not visible from prod logs. You'd see this trying to deliver the fix, not on detection. See Phase 3-F.
- **Out of memory / Killed process / exit_code=137**: stop here and re-route to `docs/runbook/fly_machine_oom.md`.
- **SHA256 mismatch / R2 re-download looping**: stop here and re-route to `docs/runbook/db_corruption_recovery.md`.
- **Logs silent (no entrypoint output at all)**: machine may not have started — `flyctl machine list` to confirm instance state.

## Phase 2 — Diagnosis (5–15 min)

Confirm machine + image SHA so you know whether the Wave 18 (RC1) and
Wave 40 (RC4) fixes are even on the running image:

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
problem and you need to ship a new image — go to Phase 3 Option A or F.

If the running image **includes** both fixes:

- **For RC1**: check the env on the machine — `BOOT_ENFORCE_INTEGRITY_CHECK=1`
  would force the legacy path. Unset it (Option B).
- **For RC4**: confirm the boot manifest on the **running image** matches
  `main` HEAD — operator may have deployed a stale image SHA:

```bash
flyctl ssh console -a autonomath-api -C 'cat /app/scripts/migrations/autonomath_boot_manifest.txt'
# Compare against scripts/migrations/autonomath_boot_manifest.txt on main HEAD.
```

If they diverge, the running image is stale — go to Option F to push
a fresh image from current `main`.

Confirm the DB size for the audit trail:

```bash
flyctl ssh console -a autonomath-api -C 'ls -la /data/autonomath.db'
# Expect ≥ 5 GB (the size-based threshold).
```

## Phase 3 — Mitigation (15–60 min)

Pick **one** option per detected RC. Do not run multiple options in
parallel — each restarts machines and rolling restarts collide.

### Option A — Ship a new image via local `flyctl deploy --remote-only`

**Use when**: RC1 detected and image predates `81922433f`, AND your
local working tree is clean enough to upload (no >10 GB build context).

```bash
git -C /Users/shigetoumeda/jpcite status
git -C /Users/shigetoumeda/jpcite log -1 --format='%H %s'

flyctl deploy --remote-only --strategy rolling -a autonomath-api
```

**Notes**:

- `--remote-only` forces the depot builder; GHA runner is bypassed.
- `--strategy rolling` keeps one machine serving while the other restarts.
- Local depot builds the image from your working tree, so the working tree
  must reflect main HEAD or a hotfix commit. Run `git status` first.

**Failure mode**: If the depot upload hangs ≥10 min without progress,
you are hitting RC2. Cancel and move to Option F.

### Option B — Env-injection (when fix is on box, env override needed)

**Use when**: RC1 detected, image **already includes** `81922433f`, and
the legacy path is being forced via `BOOT_ENFORCE_INTEGRITY_CHECK=1`.

```bash
flyctl machine list -a autonomath-api
flyctl machine update --env BOOT_ENFORCE_INTEGRITY_CHECK=0 <machine_id> -a autonomath-api
flyctl machine status <machine_id> -a autonomath-api
flyctl machine restart <machine_id> -a autonomath-api
```

Repeat per machine.

### Option C — Machine destroy + clone (last resort for RC1 only)

**Use when**: Options A and B both fail for RC1.

**Warning**: This re-arms RC4 if the running image's boot manifest is
out of sync with `schema_guard`. Run `python3 scripts/ops/pre_deploy_manifest_verify.py`
FIRST. If it returns non-zero, do **not** destroy/clone — go to
Option F to ship the manifest fix first.

```bash
flyctl machine clone <hung_machine_id> -a autonomath-api --region nrt
flyctl status -a autonomath-api
# Once clone healthy:
flyctl machine destroy <hung_machine_id> -a autonomath-api --force
```

### Option F — GHA `workflow_dispatch` deploy (RC2 / RC3 escape)

**Use when**: `flyctl deploy --remote-only` (Option A) hangs in the
depot upload phase for ≥10 min, OR engineer laptop Docker build hangs.

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

The deploy workflow runs the full build + push + rolling restart on a
GHA runner with a stable build context. ETA 12-18 min.

**Watch for the deploy.yml 4-fix pattern**:

- `smoke_sleep_race` — post-deploy curl runs before Fly proxy propagation; fixed by `sleep 60` step.
- `preflight_ci_tolerance` — preflight script runs differently in CI vs prod; CI tolerates missing flyctl.
- `hydrate_size_guard` — sftp hydrate refuses to overwrite the baked seed; fixed by size guard.
- `sftp_rm_idempotency` — `flyctl ssh sftp` `rm` fails if file absent; fixed by `|| true`.

If GHA `deploy.yml` itself fails on one of those 4 axes, follow the
fix in commit `6e3307c` (memory `feedback_deploy_yml_4_fix_pattern`).

### Option G — Authorize required migrations in boot manifest (RC4 fix)

**Use when**: RC4 detected (`required migrations missing from
schema_migrations`).

Step 1 — Identify the missing migrations:

```bash
flyctl logs -a autonomath-api --no-tail -n 500 \
  | grep 'required migrations missing' | tail -1
```

The log line lists every missing migration filename.

Step 2 — Verify each missing migration is autonomath-target and additive:

```bash
for f in 049_provenance_strengthen.sql 075_am_amendment_diff.sql \
         090_law_article_body_en.sql 115_source_manifest_view.sql \
         121_jpi_programs_subsidy_rate_text_column.sql; do
  echo "=== $f ==="
  head -10 /Users/shigetoumeda/jpcite/scripts/migrations/$f
  grep -qE 'DROP|DELETE|ALTER.*DROP' /Users/shigetoumeda/jpcite/scripts/migrations/$f \
    && echo "*** DESTRUCTIVE *** — do not authorize without manual review" \
    || echo "(safe additive)"
done
```

Step 3 — Authorize in manifest (append filenames + comment header).
See PR #75 for the canonical pattern.

Step 4 — Re-deploy via Option F (the boot manifest change must ship in
a new image).

Step 5 — After deploy, confirm `pre_deploy_manifest_verify.py` returns
ok and `schema_guard` PASS line in logs:

```bash
python3 /Users/shigetoumeda/jpcite/scripts/ops/pre_deploy_manifest_verify.py
flyctl logs -a autonomath-api --no-tail -n 200 | grep -E "schema_guard ok|am_schema_ok"
```

## Phase 4 — Verification (60–90 min)

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
- **manifest superset gate** (RC4 prevention)
- Fly machine state
- **schema_guard PASS evidence in boot log** (RC4 signal)
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
curl --max-time 30 -fsSI https://api.jpcite.com/v1/programs/search?q=ものづくり | head -1
curl --max-time 30 -fsSI https://api.jpcite.com/v1/am/health/deep | head -1
curl --max-time 30 -fsSI https://jpcite.com/ | head -1
```

All must return `HTTP/2 200`.

## Phase 5 — Post-incident (24h)

Within 24 hours of resolution:

1. Update `docs/postmortem/YYYY-MM-DD_<short>.md` with timeline + each
   RC that fired + any new failure-mode learnings. If the cause was a
   new full-scan boot op, add it to the foot-gun list in memory
   `feedback_no_quick_check_on_huge_sqlite`. If the cause was a new
   packaging change re-arming a latent boot invariant, add it to
   memory `feedback_pre_deploy_manifest_verify`.
2. Confirm `scripts/cron/db_boot_hang_alert.py` is in the daily cron
   and that it would have caught this specific shape. The Wave 41
   extension covers both RC1 hang and RC4 FAIL patterns.
3. If Option A (local deploy) was used, push any pending GHA
   `deploy.yml` fix so Option F also works next time — do not leave
   the GHA path broken.
4. Verify Phase 1 detection chain end-to-end (UptimeRobot → Telegram
   bot → operator phone) by sending a synthetic alert.

## Operator notes

- `flyctl ssh sftp get` from this runbook is read-only — it cannot
  corrupt the volume.
- Do **not** run `PRAGMA integrity_check` or `PRAGMA quick_check`
  interactively on `/data/autonomath.db` while diagnosing — it will
  cause the same hang you are trying to fix.
- `entrypoint.sh` is **not** rolled back by re-deploying an older
  image tag; the volume contents persist and the next boot runs whatever
  `entrypoint.sh` is in the new image. Hot-rollback via flyctl deploy
  with `--image registry.fly.io/...:<old-tag>` is only safe if you've
  confirmed the old image has BOTH the size-based skip AND the boot
  manifest containing all `AM_REQUIRED_MIGRATIONS`.
- Solo zero-touch ops — no escalation tree, no PagerDuty rotation.
  Detection chain: UptimeRobot → Telegram bot → operator phone.
- **A new boot foot-gun adds a strategy here, not a phase.** Phase 1-5
  shape stays stable; strategies A/B/C/F/G can grow.

## Quick reference — strategy selection matrix

| Symptom | First strategy | Fallback |
| --- | --- | --- |
| RC1 + image stale | A | F |
| RC1 + env force | B | A |
| RC1 + Options A+B fail | C | (DR) |
| RC2 (depot hang) | F | (laptop) |
| RC3 (local docker hang) | F | (none — do not use Option A) |
| RC4 (manifest gap) | G + F | (offline migration run via flyctl ssh — destructive, avoid) |

---

_If this runbook didn't resolve the incident in 90 minutes, escape to
`docs/runbook/disaster_recovery.md` and treat as full DR._
