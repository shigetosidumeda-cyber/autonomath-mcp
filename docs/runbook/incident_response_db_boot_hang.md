---
title: DB Boot Hang Incident Response Runbook
updated: 2026-05-12
operator_only: true
category: incident
related_postmortem: docs/postmortem/2026-05-11_integrity_check_outage.md
related_memory: feedback_no_quick_check_on_huge_sqlite
---

# DB Boot Hang Incident Response Runbook

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Last reviewed**: 2026-05-12 (post 2026-05-11 5h12m outage)

This runbook covers the case where the Fly Tokyo machine running
`autonomath-api` boots, sits in `started` state with `CHECKS: 0/1`,
and the Fly proxy returns `could not find a good candidate within 40
attempts at load balancing` to `api.jpcite.com`. The canonical
signature is a multi-GB SQLite full-scan op (PRAGMA integrity_check /
quick_check / VACUUM / REINDEX / ANALYZE) running at boot against
the 9.7 GB `autonomath.db`, exceeding the 60s Fly health-grace.

Related:

- Post-mortem: `docs/postmortem/2026-05-11_integrity_check_outage.md` (5h12m down, Wave 18 §4 root fix).
- `entrypoint.sh` §2 (size-based SHA skip) and §4 (size-based integrity_check skip, Wave 18 commit `81922433f`).
- `docs/runbook/db_corruption_recovery.md` — branch off here if Phase 2 diagnosis shows actual corruption (rare).
- `docs/runbook/fly_machine_oom.md` — branch off here if Phase 2 shows `exit_code=137`.

## Phase 1 — Detection (0–5 min)

**You are here** if any of these fire:

```text
A. UptimeRobot 502/504 alert on api.jpcite.com/healthz (3 × 60s).
B. Fly proxy log: "could not find a good candidate within 40 attempts at load balancing".
C. Cron alert from scripts/cron/db_boot_hang_alert.py (Telegram).
D. flyctl status -a autonomath-api shows CHECKS: 0/1 with instance_state=started.
```

**Immediate triage** (60s, do not skip):

```bash
flyctl status -a autonomath-api
flyctl logs -a autonomath-api --no-tail | grep -E "integrity_check|quick_check|VACUUM|REINDEX|ANALYZE" | tail -20
```

If you see `running integrity_check on /data/autonomath.db` (or any
other full-scan op) **without** a follow-up `ok` / `size-based skip`
line, you are in the DB boot hang state. Continue to Phase 2.

If you see `Out of memory` / `Killed process` / `exit_code=137`, **stop
here** and re-route to `docs/runbook/fly_machine_oom.md`.

If you see `SHA256 mismatch` / `R2 re-download` looping, **stop here**
and re-route to `docs/runbook/db_corruption_recovery.md`.

If logs are silent (no entrypoint output at all), the machine may not
have started — `flyctl machine list` to confirm instance state.

## Phase 2 — Diagnosis (5–15 min)

Confirm machine + image SHA so you know whether the Wave 18 §4 fix is
even on the running image:

```bash
# Machine state
flyctl status -a autonomath-api
flyctl machine list -a autonomath-api

# Current main HEAD for entrypoint.sh
git -C /Users/shigetoumeda/jpcite log -1 --format='%H %s' -- entrypoint.sh

# Wave 18 §4 fix should appear in `git log entrypoint.sh`
git -C /Users/shigetoumeda/jpcite log --oneline entrypoint.sh | grep -i 'wave 18\|integrity_check'
# Expect: 81922433f fix(boot): apply size-based skip to §4 integrity_check (Wave 18) (#35)
```

If the running image **predates** `81922433f`, the fix is not on the
box and you need to ship a new image (Phase 3 Option A).

If the running image **includes** `81922433f` but `integrity_check`
log line still appears without size-based skip, check the env var
state on the machine — `BOOT_ENFORCE_INTEGRITY_CHECK=1` would force
the legacy path. The skip should print:

```text
size-based integrity_check skip for /data/autonomath.db (size=NNN >= threshold=5000000000) — schema_guard remains structural probe (set BOOT_ENFORCE_INTEGRITY_CHECK=1 to override)
```

If `BOOT_ENFORCE_INTEGRITY_CHECK=1` is set and you didn't set it for a
DR drill, unset it (Phase 3 Option B).

Confirm the DB size (for the audit trail):

```bash
flyctl ssh console -a autonomath-api -C 'ls -la /data/autonomath.db'
# Expect: ~9.7 GB (≥ 5 GB threshold)
```

## Phase 3 — Mitigation (15–30 min)

Pick **one** option. Do not run more than one in parallel — each one
restarts the machine and rolling restarts collide.

### Option A — Ship a new image (preferred when fix is not on box)

This is the path that recovered the 2026-05-11 outage. Use when the
running image predates `81922433f`, OR when the GHA `deploy.yml` chain
is failing on Checkout / sftp hydrate / Deploy / smoke and you need to
escape it.

```bash
# Run from /Users/shigetoumeda/jpcite local checkout, on a clean main HEAD.
git -C /Users/shigetoumeda/jpcite status
git -C /Users/shigetoumeda/jpcite log -1 --format='%H %s'

# Local deploy via depot builder, bypass GHA. ≈10–18 min.
flyctl deploy --remote-only --strategy rolling -a autonomath-api
```

Notes:

- `--remote-only` forces the depot builder; GHA runner is bypassed.
- `--strategy rolling` keeps one machine serving while the other restarts.
- The `flyctl ssh sftp` hydrate step from `deploy.yml` is NOT replicated locally — the image embeds `data/jpintel.db` at build time and reads `autonomath.db` from the volume. The local depot build is closer to the legacy production path than current `deploy.yml`.
- After the deploy completes, **manually run the smoke walk** (the local path skips the post-deploy smoke that GHA runs):

```bash
sleep 60
curl --max-time 30 -fsS https://api.jpcite.com/healthz | jq .
curl --max-time 30 -fsS https://api.jpcite.com/v1/openapi.json | jq '.paths | length'
```

### Option B — Env-injection (when fix is on box, env override needed)

Use when the image **already includes** `81922433f` but the legacy
path is being forced via `BOOT_ENFORCE_INTEGRITY_CHECK=1`, OR you need
to temporarily skip integrity_check on a DR drill machine.

```bash
# List machines, pick the hung one's ID.
flyctl machine list -a autonomath-api

# Disable legacy integrity_check enforcement on the specific machine.
flyctl machine update --env BOOT_ENFORCE_INTEGRITY_CHECK=0 <machine_id> -a autonomath-api

# Verify env is set, then restart.
flyctl machine status <machine_id> -a autonomath-api
flyctl machine restart <machine_id> -a autonomath-api
```

Repeat for each affected machine (Tokyo region typically has 2).

### Option C — Machine destroy + clone (last resort)

Use only if Option A and B both fail. Volume is preserved across clone.

```bash
flyctl machine clone <hung_machine_id> -a autonomath-api --region nrt
# Verify the clone is healthy.
flyctl status -a autonomath-api
# Once clone is healthy and serving, destroy the hung one.
flyctl machine destroy <hung_machine_id> -a autonomath-api --force
```

**Warning**: clone re-runs entrypoint from scratch. If the §2 SHA path
runs (BOOT_ENFORCE_DB_SHA=1) it will trigger the R2 re-download (30+
min). Do NOT clone without verifying BOOT_ENFORCE_DB_SHA is unset.

## Phase 4 — Verification (30–60 min)

After Phase 3 completes:

1. **healthz 200**:

```bash
curl --max-time 30 -fsS https://api.jpcite.com/healthz | jq .
```

Expect HTTP 200 + JSON body. Re-run 3× spaced 60s apart.

2. **5-min stability hold**: log every 60s for 5 min; require all green.

```bash
for i in $(seq 1 5); do
  date -u +%H:%M:%SZ
  curl --max-time 30 -fsSI https://api.jpcite.com/healthz | head -1
  sleep 60
done
```

3. **Size-based skip log evidence** on every machine in the rolling restart:

```bash
flyctl logs -a autonomath-api --no-tail | grep "size-based integrity_check skip" | tail -5
```

Expect at least 1 line per machine in the new image.

4. **OpenAPI path count parity** (the prod contract probe):

```bash
curl --max-time 30 -fsS https://api.jpcite.com/v1/openapi.json | jq '.paths | length'
# Expect: 219 (current SOT — re-verify against scripts/distribution_manifest.yml)
```

5. **Customer-facing surface walk** (the cohort sample):

```bash
curl --max-time 30 -fsSI https://api.jpcite.com/v1/programs/search?q=ものづくり | head -1
curl --max-time 30 -fsSI https://api.jpcite.com/v1/am/health/deep | head -1
curl --max-time 30 -fsSI https://jpcite.com/ | head -1
```

All must return `HTTP/2 200`.

## Phase 5 — Post-incident (24h)

Within 24 hours of resolution:

1. Update `docs/postmortem/YYYY-MM-DD_<short>.md` with the timeline and
   any new failure-mode learnings. If the cause was a new full-scan op,
   add it to the foot-gun list in memory `feedback_no_quick_check_on_huge_sqlite`.
2. Confirm `scripts/cron/db_boot_hang_alert.py` is in the daily cron
   and that it would have caught this specific shape (test fixture line:
   `running integrity_check on /data/autonomath.db before schema_guard`).
3. If Option A (local deploy) was used, push the GHA `deploy.yml` fix
   so the chain works next time — do not leave the GHA path broken.

## Operator notes

- `flyctl ssh sftp get` from this runbook is read-only — it cannot
  corrupt the volume.
- Do not run `PRAGMA integrity_check` or `PRAGMA quick_check`
  interactively on `/data/autonomath.db` while diagnosing — it will
  cause the same hang you are trying to fix.
- `entrypoint.sh` is **not** rolled back by re-deploying an older image
  tag; the volume contents persist and the next boot will run whatever
  `entrypoint.sh` is in the new image. Hot-rollback via flyctl deploy
  with `--image registry.fly.io/...:<old-tag>` is only safe if you've
  confirmed the old image has the size-based skip.
- Solo zero-touch ops — no escalation tree, no PagerDuty rotation.
  The detection chain is: UptimeRobot → Telegram bot → operator phone.

---

_If this runbook didn't resolve the incident in 60 minutes, escape to
`docs/runbook/disaster_recovery.md` and treat as full DR._
