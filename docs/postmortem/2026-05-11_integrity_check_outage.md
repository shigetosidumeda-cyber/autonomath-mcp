---
title: 2026-05-11 integrity_check Outage Post-Mortem
incident_id: pm-2026-05-11-01
severity: SEV1
status: resolved
duration_minutes: 312
brand_surface: jpcite
operator: Bookyou株式会社 (T8010001213708)
owner: 梅田茂利 (info@bookyou.net)
related_runbook: docs/runbook/incident_response_db_boot_hang.md
related_commit: 81922433f
related_memory: feedback_no_quick_check_on_huge_sqlite
---

# 2026-05-11 integrity_check Outage Post-Mortem (Wave 25)

`api.jpcite.com` served 5xx for ~5h12m on 2026-05-11 (~11:40 UTC start → ~16:52 UTC restored)
because `entrypoint.sh` §4 ran `PRAGMA integrity_check` against the 9.7 GB
`autonomath.db` on every machine boot. Each boot wedged for 30+ min,
exceeded the Fly health-check grace, and the proxy could not find a
"good candidate" in 40 load-balancing attempts. Wave 13 §2 had already
size-skipped the SHA256 path; the parallel §4 integrity_check path was
left running by design ("structural correctness probe"). 2026-05-11
proved that even one residual full-scan boot op turns the multi-GB DB
into an outage trap.

## TL;DR

- **Trigger**: machine `85e273f4` cold-boot ran `PRAGMA integrity_check` on `/data/autonomath.db`.
- **Hang**: 30+ min per attempt on a 9.7 GB DB; Fly grace 60s ⇒ machine flagged unhealthy ⇒ proxy refused traffic.
- **Cascade**: every redeploy attempt landed the same boot path; sftp hydrate / Deploy step / Checkout step in `deploy.yml` failed in turn while we tried to push the fix through.
- **Resolution**: local `flyctl deploy --remote-only` (depot builder) bypassed the failing GHA chain; new image with Wave 18 §4 fix (`81922433f`) booted with size-based skip log evidence; healthz 200 restored.
- **Net change**: `entrypoint.sh` §4 integrity_check now obeys the same `AUTONOMATH_DB_MIN_PRODUCTION_BYTES` (≥5 GB) threshold as §2 SHA256; `BOOT_ENFORCE_INTEGRITY_CHECK=1` restores the legacy path for DR drills.

## Timeline (UTC)

| Time | Event | Source |
| --- | --- | --- |
| 11:40 | Machine `85e273f4` cold-boot; `entrypoint.sh` §4 logs `running integrity_check on /data/autonomath.db before schema_guard (autonomath)`. | `flyctl logs` |
| 11:40–12:10 | `sqlite3 ... 'PRAGMA integrity_check;'` reading 9.7 GB; no process output. | volume IO profile |
| 12:18 | First external 5xx detected; Fly proxy returns `could not find a good candidate within 40 attempts at load balancing`. | uptime probe |
| 12:25 | CHECKS state for the machine = `0/1` even though instance state = `started`. | `flyctl status` |
| 13:00 | First mitigation attempt — push Wave 18 §4 size-based-skip fix to `main` (commit `81922433f`). GHA `deploy.yml` Checkout step transient fail. | GHA run log |
| 13:30 | Re-trigger. `deploy.yml` `hydrate` step fails — `flyctl ssh sftp get` refuses to overwrite the 1.3 MB dev fixture. | run 25475311823 |
| 14:00 | Re-trigger. `deploy.yml` Deploy step times out on remote builder; depot recovery cycle restarts. | run 25475753541 (precursor) |
| 14:30–16:00 | Multiple GHA `deploy.yml` re-runs cascading on `hydrate` rm + smoke sleep race; production stays down. | GHA history |
| 16:15 | Decision: switch to **local `flyctl deploy --remote-only --strategy rolling`** (depot builder) to bypass the GHA chain — escape path. | session log |
| 16:30 | Local depot build completes; new image SHA pushed; rolling restart begins. | flyctl output |
| 16:48 | First machine in new image logs `size-based integrity_check skip for /data/autonomath.db (size=9722236928 >= threshold=5000000000) — schema_guard remains structural probe`. | `flyctl logs` |
| 16:50 | `schema_guard` returns OK; uvicorn binds 0.0.0.0:8080. | `flyctl logs` |
| 16:52 | `healthz` returns 200; UptimeRobot recovers; rolling restart completes. | uptime probe |
| 17:00 | 5-min stability hold met; declare incident resolved. | session log |

Total customer-visible downtime: **~312 minutes** (12:18 → 17:30 inclusive stability hold).

## Root cause

### Primary

`entrypoint.sh` §4 invoked `sqlite3 "$DB_PATH" 'PRAGMA integrity_check;'`
on the live autonomath volume DB at every boot. `autonomath.db` is
9.7 GB; the pragma walks every page sequentially. On the Fly Tokyo
shared-CPU `[[vm]]` with `memory_mb=4096`, the walk takes 30+ minutes,
exceeding the 60s Fly health-grace by orders of magnitude.

Wave 13 (2026-05-09) had already converted §2 from SHA256-of-the-volume
to size-based authoritative ("any /data/autonomath.db ≥ 5 GB is
authoritative without hashing"), specifically to stop a parallel
foot-gun on the same volume. The §2 work shipped with the explicit
note that **§4 `PRAGMA integrity_check` is intentionally retained as
the structural correctness probe** (see `CLAUDE.md` SOT line on
"Autonomath-target migrations land via entrypoint.sh"). That
retention assumed §4 was fast — for a multi-GB DB it is not.

### Contributing

1. **No size-cap on §4.** Wave 13 size-skip logic short-circuited §2
   only. §4 had no equivalent guard. The CLAUDE.md SOT line that
   warned about full-scan ops on multi-GB DBs (`feedback_no_quick_check_on_huge_sqlite`)
   already listed `PRAGMA integrity_check`, but §4 was not retrofitted
   when §2 was hardened.
2. **GHA `deploy.yml` is the only production deploy path.** Multiple
   sub-steps (Checkout / hydrate sftp / Deploy / smoke) failed in the
   span of one session, each independently. The lack of a documented
   escape path made the cascade feel longer than it needed to be.
3. **CI test gate (`release.yml`) coupling.** Tests that depend on
   production-DB-backed routes red-line when production is down. This
   made `release.yml` look like the blocker when in fact the boot path
   was the only thing standing between us and recovery.
4. **No automated alert when boot logs the integrity_check line.**
   We detected the outage from external uptime, not from the
   boot-log shape. A 5-min watchdog on `integrity_check` log lines
   would have raised before the proxy's 40-attempt rotation finished.

### What was NOT the cause

- DB corruption — no integrity_check ever completed, so the run carried no signal either way.
- R2 snapshot freshness — never relevant; size-based path skips R2 entirely.
- Migration backlog — §4 fires before §5 schema_guard; entrypoint never reached migrations.
- Code regression — `entrypoint.sh` was running the documented design; the design assumed §4 cost was negligible.

## Detection

External (uptime / customer-visible):

- UptimeRobot: 3 consecutive 60s `GET /healthz` failures at 12:18 UTC.
- Fly proxy log: `could not find a good candidate within 40 attempts at load balancing`.
- `flyctl status -a autonomath-api` showed `CHECKS: 0/1` while `instance_state: started` (the foot-gun signature — "running but not healthy").

Internal (post-detection diagnosis):

- `flyctl logs -a autonomath-api -n 200 | grep integrity_check` printed `running integrity_check on /data/autonomath.db` with no follow-up "ok" line — diagnostic confirmation.
- `flyctl machine list -a autonomath-api` confirmed the unhealthy machine's image SHA matched the pre-Wave-18 build (no §4 size-skip yet).

## Mitigation

### Code fix landed

Wave 18 §4 commit `81922433f` ("fix(boot): apply size-based skip to §4
integrity_check (Wave 18) (#35)") extends the §2 `AUTONOMATH_DB_MIN_PRODUCTION_BYTES`
threshold to §4 integrity_check. The diff (paraphrased):

```sh
# entrypoint.sh §4 (post-Wave-18)
integrity_threshold="${AUTONOMATH_DB_MIN_PRODUCTION_BYTES:-5000000000}"
if [ "$db_size_pre_check" -ge "$integrity_threshold" ] \
   && [ "${BOOT_ENFORCE_INTEGRITY_CHECK:-0}" != "1" ]; then
  log "size-based integrity_check skip for $DB_PATH ..."
elif trusted_stamp_match; then
  log "trusted stamp match — skipping full integrity_check"
else
  log "running integrity_check on $DB_PATH ..."
  integrity=$(sqlite3 "$DB_PATH" 'PRAGMA integrity_check;' ...)
fi
```

`schema_guard` remains as the structural correctness probe — it is a
cheap metadata-only check, not a full-page walk.

### Deploy escape path used

The GHA `deploy.yml` chain failed on three different steps in
sequence (Checkout, sftp hydrate `rm` race, Deploy remote builder
timeout). To stop the cascade, we **deployed locally**:

```bash
flyctl deploy --remote-only --strategy rolling -a autonomath-api
```

Local `flyctl` used the depot builder directly, bypassing the GHA
runner constraints (no 9.7 GB DB on the runner, no sftp dependency,
no smoke-sleep race). The new image pushed to Fly's registry, the
rolling restart began, and the first machine on the new image logged
the size-based skip line within ~18 minutes of the local command
finishing.

### Operator action taken during the incident

- Cancelled the in-flight smoke step on the failing GHA run to free the queue.
- Did **not** `flyctl machine destroy` — the volume contents were
  authoritative, and destroying would have re-armed the §2 R2
  re-download path (another 30+ min hazard).
- Did **not** set `BOOT_ENFORCE_INTEGRITY_CHECK=0` via `flyctl machine
  update --env` as a hot mitigation, because Wave 18 §4 was already
  landed on `main` and the local deploy was faster than per-machine env
  patches across 2 Tokyo machines.

## Impact

- **Customer-visible**: 5xx on `api.jpcite.com` for ~5h12m. MCP stdio + DXT
  surfaces unaffected (they read the bundled bundle, not the API).
- **CF Pages**: healthy throughout. `site/`, `llms.txt`, companion `.md`,
  OpenAPI JSON, MCP manifest all served normally — important for
  organic acquisition because Bing/Perplexity/ChatGPT crawls hit the
  static surface, not the API.
- **Stripe billing**: no metered events fired (no requests to bill).
  No customer was incorrectly charged.
- **Cron**: weekly / monthly cron didn't fire during the window;
  next morning `morning_briefing.py` confirmed all schedules re-armed
  cleanly on the new image.
- **Organic acquisition signal**: unknown. Sunday 11:40–16:52 UTC is
  Sunday 20:40 JST – Monday 01:52 JST. Japanese weekday cohort was
  mostly outside the window; APAC weekend traffic is comparatively
  thin. We do not have evidence of measurable lost-conversion impact,
  and we are not going to speculate further.

## Lessons learned

1. **Any single full-scan boot op on a multi-GB DB is a trap.** Wave 13
   killed the SHA256 trap; Wave 18 killed the `PRAGMA integrity_check`
   trap. The remaining boot-time scans must be audited the same way
   — `PRAGMA quick_check`, `VACUUM`, `REINDEX`, `ANALYZE` are all
   forbidden on autonomath.db at boot. See memory
   `feedback_no_quick_check_on_huge_sqlite`.

2. **The GHA `deploy.yml` chain is not the only deploy path — make
   that explicit.** Local `flyctl deploy --remote-only` worked as an
   escape hatch on 2026-05-11. The new runbook (`docs/runbook/incident_response_db_boot_hang.md`)
   documents it as Option A in Phase 3, with the depot builder note
   explicit so future operators don't waste minutes rediscovering it.

3. **A 5-min boot-log watchdog would have alerted us before customers
   noticed.** Wave 25 ships `scripts/cron/db_boot_hang_alert.py` to
   close that gap. It tails `flyctl logs` daily and pages Telegram if
   the `running integrity_check` line stays without a follow-up `ok` /
   `size-based skip` line for >5 min.

4. **CI tests that depend on prod-DB-backed routes are coupled to
   uptime.** When prod is down, `release.yml` red-lines for the wrong
   reason, masking the real signal. Future deploys should not gate
   their CI on production reachability — split smoke probes from
   contract tests, and let contract tests pass in a clean environment.

5. **Operators should not bypass the deploy chain reflexively.** Local
   `flyctl deploy` is an escape path, not the default. It bypasses
   the post-deploy smoke step that the GHA chain runs (commit `6e3307c`
   raised it to 60s sleep + 30s curl). After every local deploy,
   manually run the smoke walk against the new image SHA before
   declaring recovery.

## Action items

| ID | Action | Owner | Status |
| --- | --- | --- | --- |
| AI-1 | Land Wave 18 §4 size-based skip on `main`. | 梅田 / Claude | DONE (`81922433f`) |
| AI-2 | Add Phase-1/2/3/4 incident runbook. | Claude | DONE (`docs/runbook/incident_response_db_boot_hang.md`) |
| AI-3 | Update memory `feedback_no_quick_check_on_huge_sqlite` with the 5h-down evidence + the integrity_check log-pattern detection criterion. | Claude | DONE |
| AI-4 | Daily watchdog: alert if `integrity_check` log stays > 5 min without `ok` / `size-based skip`. | Claude | DONE (`scripts/cron/db_boot_hang_alert.py`) |
| AI-5 | Audit remaining boot-time SQLite ops (`quick_check`, `VACUUM`, `REINDEX`, `ANALYZE`) for the same trap on autonomath.db. | 梅田 | OPEN — next Wave |
| AI-6 | Split prod-reachability smoke probes out of `release.yml` so contract tests pass in a clean env. | 梅田 | OPEN — next Wave |
| AI-7 | Document local `flyctl deploy --remote-only` as a first-class escape path in `docs/runbook/disaster_recovery.md`. | 梅田 | OPEN — next Wave |

## References

- Wave 18 §4 fix commit: `81922433f` ("fix(boot): apply size-based skip to §4 integrity_check (Wave 18) (#35)")
- `entrypoint.sh` §2 / §4 (post-Wave-18 state on `main`)
- `CLAUDE.md` SOT line: "`entrypoint.sh` §2 AND §4 boot gates are SIZE-BASED, not SHA/integrity-based (2026-05-11 Wave 18 root fix)"
- Memory: `feedback_no_quick_check_on_huge_sqlite`
- Runbook: `docs/runbook/incident_response_db_boot_hang.md`
- Alert script: `scripts/cron/db_boot_hang_alert.py`

---

_Last reviewed: 2026-05-12. Solo zero-touch ops — no team rotation, no PagerDuty._
