---
title: Fly Machine OOM Diagnosis Runbook
updated: 2026-05-07
operator_only: true
category: incident
---

# Fly Machine OOM Diagnosis Runbook (G2)

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Last reviewed**: 2026-05-07
**Related**: `fly.toml` (current `[[vm]]` block — `cpu_kind="shared", cpus=2, memory_mb=4096`), `docs/runbook/sentry_alert_escalation.md` §4 (this runbook is the destination of the `machine_oomkill` alert), `docs/runbook/db_corruption_recovery.md` (OOM during a write can leave the WAL in a state that blocks restart).

This runbook covers the case where the Fly Tokyo machine running
`autonomath-api` is killed by the Linux OOM killer and the API serves 502 to
all clients until Fly auto-restarts it (typically 25–60 s on the rolling
strategy).

## 1. Detection

Triggers, in priority order:

```text
A. Sentry alert `machine_oomkill` (rule: log line "Out of memory: Killed process").
B. UptimeRobot 502 alert for api.jpcite.com/v1/health
   (3 consecutive 60s checks fail).
C. flyctl status reports state="stopped" with exit_code=137 (SIGKILL).
D. Operator-driven: ad-hoc `flyctl logs -a autonomath-api | grep -i oom`.
```

**Pre-state self-check** (30 sec):

```bash
flyctl status -a autonomath-api
flyctl logs -a autonomath-api -n 200 | grep -E "(oom|out of memory|killed process|SIGKILL)" | tail -20
flyctl machine list -a autonomath-api
```

Confirmation that this is OOM (and not a different crash class — segfault,
boot-gate fail, deploy mid-flight):

* `Out of memory: Killed process <pid> (uvicorn|python)` in dmesg lines
* `exit_code=137` (SIGKILL — kernel) **not** `exit_code=139` (SIGSEGV) or
  `exit_code=1` (graceful BOOT FAIL — see `docs/runbook/secret_rotation.md`).

If exit_code is 1, **stop** — this is a boot gate, not OOM. Re-route to
`docs/runbook/secret_rotation.md` Verify section.

## 2. Memory budget reference

The current `fly.toml` `[[vm]]` block budgets 4096 MB total. The dominant
consumers, in production at the 2026-05-07 snapshot:

| Component                                | Steady-state | Peak    | Notes                                            |
|------------------------------------------|--------------|---------|--------------------------------------------------|
| Python interpreter + FastAPI + uvicorn   | ~250 MB      | ~350 MB | base image + 1 worker (single-process Fly)       |
| **autonomath.db mmap**                   | **~1200 MB** | ~1800 MB| 12.4 GB DB, page cache demand-paged into mmap    |
| jpintel.db mmap                          | ~150 MB      | ~250 MB | 352 MB DB, mostly hot                             |
| FTS5 trigram bloom + sqlite-vec scratch  | ~200 MB      | ~600 MB | sqlite-vec spills to RAM during top-k searches    |
| Stripe SDK + Sentry SDK                  | ~80 MB       | ~120 MB | small overhead                                    |
| 36協定 PDF render (when enabled)         | ~50 MB       | ~400 MB | reportlab spike per request, gated off by default |
| NTA monthly bulk ingest job              | ~600 MB      | ~1500 MB| 4 M-row zenken bulk on the 1st of the month 03:00 JST |
| Working headroom                         | ~600 MB      |    —    | response buffers + connection pool + TLS         |

**The autonomath.db mmap is the primary memory tax.** SQLite mmaps the
database file lazily, so cold starts look fine; under sustained search load
the page cache fills toward the working-set size (currently ~1.8 GB and
growing as the unified DB grows).

The 1st-of-month 03:00 JST `nta-bulk-monthly` workflow is the highest-risk
window — that job runs in the same machine and competes for the same 4 GB
budget. Most past OOMs land in that window.

## 3. Immediate mitigation (machine already crashed)

```bash
# 1. Confirm Fly's auto-restart picked up. Default rolling strategy retries
#    immediately; if exit code 137 happened twice in 5 min, Fly backs off.
flyctl status -a autonomath-api
# state="started" → API is back, move to §4 root-cause analysis.
# state="stopped" with restart_count >=3 → Fly is throttling, force a fresh start:
flyctl machine restart <machine-id> -a autonomath-api

# 2. Health-gate the restart. The deep-health probe imports both DBs and
#    forces SQLite to mmap pages — doing this once intentionally is faster
#    than the first live customer hitting it cold.
sleep 90
curl -fsS --max-time 30 https://api.jpcite.com/v1/am/health/deep | jq .

# 3. If health probe still 5xx after 90s, scale to 0 then back to 1 to clear
#    any stuck state — DO NOT do this if a deploy is mid-flight.
flyctl scale count 0 -a autonomath-api
flyctl scale count 1 -a autonomath-api
```

## 4. Root cause: which component spiked?

```bash
flyctl ssh console -a autonomath-api

# 4a. Process memory snapshot (post-restart, before traffic warms up).
ps aux --sort=-%mem | head -10

# 4b. SQLite memory consumers. Each value is bytes; sum should be ≤ memory_mb * 1MB.
sqlite3 /data/autonomath.db "SELECT name, value FROM pragma_compile_options() WHERE name LIKE '%MMAP%';"
sqlite3 /data/autonomath.db "PRAGMA mmap_size;"
sqlite3 /data/autonomath.db "PRAGMA cache_size;"

# 4c. Page-cache pressure — high "buffers + cached" with low "free" + high
#     "swap used" indicates the OOM was triggered by a single large alloc
#     spike (likely sqlite-vec top-k or PDF render), not steady leakage.
free -m
cat /proc/pressure/memory   # Linux PSI; "some" + "full" non-zero = pressure
exit
```

The four most common patterns and their fixes:

* **Bulk ingest collision** (`nta-bulk-monthly`, `incremental-law-load`,
  `precompute_refresh.py`): two cron jobs overlapped. Stagger crontabs in
  `entrypoint.sh` so no two memory-heavy jobs run within 30 min of each
  other. Audit by `flyctl logs ... | grep "started cron"` correlated with
  the OOM timestamp.
* **sqlite-vec top-k explosion** on autonomath: query against
  `am_entities_vec` with `LIMIT > 200` rebuilds the entire vector working
  set in RAM. Cap MCP tool call surface to `LIMIT ≤ 100`; verify in
  `src/jpintel_mcp/mcp/autonomath_tools/*.py`.
* **mmap working-set growth**: autonomath.db growing past 13 GB drives the
  hot page set past 2 GB. Long-term fix is the `[[vm]]` scale-up in §5;
  short-term mitigation is `PRAGMA mmap_size=536870912;` (512 MB cap) per
  connection in `db/conn.py` — costs latency on first cold queries but
  caps the spike.
* **Single-worker uvicorn re-entry**: a request handler pulled a 200 MB
  result set into Python (not via streaming). Grep the access log for the
  request URL just before the OOM and audit the handler for `.fetchall()`
  on a wide query — convert to `.iterdump()` or LIMIT-pagination.

## 5. Scale-up (when 4 GB is permanently insufficient)

The `fly.toml` block intentionally keeps `cpu_kind="shared", memory_mb=4096`
for cost control. Escalation to **`performance-2x` (4 cpus / 8 GB)** is the
next step — it carries +¥5–6k/month under launch pricing.

```bash
# 1. Edit fly.toml (or pass via flag).
#    Change to:
#      [[vm]]
#        cpu_kind = "performance"
#        cpus = 2
#        memory_mb = 8192
#
# 2. Deploy. Fly creates a fresh machine on the new size and rolls traffic.
flyctl deploy --remote-only --strategy rolling -a autonomath-api

# 3. Confirm. The "Memory" column in `flyctl status` should read 8192 MB.
flyctl status -a autonomath-api

# 4. Smoke. Deep-health forces both DB mmaps so the warm working-set lands now.
sleep 90
curl -fsS --max-time 30 https://api.jpcite.com/v1/am/health/deep | jq .
```

After scale-up, watch `flyctl metrics memory_used_bytes -a autonomath-api`
for a full week — if peak still exceeds ~6.5 GB during the monthly NTA bulk
window, the next escalation is `performance-4x` (16 GB, ~¥12k/mo extra) but
that should be a last resort and probably indicates an upstream leak rather
than legitimate working-set growth.

## 6. Verify (every OOM incident must complete this)

```bash
# 6a. The originating Sentry issue is resolved (note: scaled to 8192 MB OR
#     fixed sqlite-vec LIMIT OR staggered cron OR identified leak).
# 6b. /v1/am/health/deep returns 200 with all three "ok" booleans.
curl -fsS --max-time 30 https://api.jpcite.com/v1/am/health/deep | jq .

# 6c. UptimeRobot has a clean 60-min window (no 502 / no 5xx).
# 6d. Fly machine memory baseline returns to < 2.5 GB at idle.
flyctl metrics memory_used_bytes -a autonomath-api -p 5m
```

## 7. Rollback

The scale-up in §5 is reversible by changing `fly.toml` back to
`shared / 4096 MB` and redeploying. **Do NOT** roll back if the same
workload still OOMs on 4 GB — the rollback re-creates the incident.

If a `mmap_size` clamp was added in `db/conn.py` to mitigate the spike,
keep it on the rollback path (it's defense in depth; latency cost is small).

## 8. Failure modes

* **OOM repeats within 5 min after auto-restart**: Fly's machine watchdog
  enters exponential back-off. After 3 fast-fails the machine stays stopped
  for 60s. While stopped, the API is dark. Force-restart per §3 step 1.
* **OOM during deploy**: rare — happens when a deploy lands during the NTA
  bulk window. Fly's `strategy="rolling"` keeps the old machine alive
  briefly, but the new machine OOMs before traffic shifts and rolls back to
  the old. Re-deploy outside the bulk window (avoid 1st-of-month 03:00 JST).
* **OOM kills the cron itself**: the cron's checkpoint in
  `analytics/*.jsonl` won't get the success line. Re-run the cron manually
  via `flyctl ssh console -a autonomath-api -C "python /app/scripts/cron/<job>.py"`
  after the machine is healthy.

## 9. Items needing user action (one-time prerequisites)

* Sentry alert rule `machine_oomkill` registered in
  `monitoring/sentry_alert_rules.yml` (matches log message
  `Out of memory: Killed process`). Triage destination is this runbook.
* `[[vm]]` block in `fly.toml` review during quarterly DR drill.
