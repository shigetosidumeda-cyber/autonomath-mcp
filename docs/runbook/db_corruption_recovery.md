---
title: SQLite DB Corruption Recovery Runbook
updated: 2026-05-07
operator_only: true
category: dr
---

# SQLite DB Corruption Recovery Runbook (G1)

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Last reviewed**: 2026-05-07
**Related**: `docs/runbook/disaster_recovery.md` §3.1 (the canonical restore
flow this runbook narrows in on), `docs/runbook/litestream_setup.md` (PITR
sidecar — supersedes hourly snapshots once enabled), `docs/runbook/sentry_alert_escalation.md` (this runbook is the destination of the `database_corruption_detected` alert rule).

This is the actionable single-operator playbook for **detecting and recovering
from SQLite-level corruption** on either of the two production databases:

| DB              | Live path             | Size at 2026-05-07 | Source of truth                          |
|-----------------|-----------------------|---------------------|------------------------------------------|
| `jpintel.db`    | `/data/jpintel.db`    | ~352 MB             | hourly R2 backup (`backup_jpintel.py`)   |
| `autonomath.db` | `/data/autonomath.db` | ~12.4 GB            | daily R2 backup (`backup_autonomath.py`) |

Cross-cuts: **disk-full on the 40 GB Fly volume** (autonomath.db + WAL +
backups-pre-restore can saturate it). This runbook covers that case in §4.

## 1. Detection

The runbook is triggered by **any** of:

```text
A. Sentry issue with one of:
   - "sqlite3.DatabaseError: database disk image is malformed"
   - "sqlite3.DatabaseError: database is locked" (sustained > 5 min)
   - "sqlite3.OperationalError: disk I/O error"
   - "FOREIGN KEY constraint failed" surge (> 50 events / 5 min)
B. /v1/am/health/deep returns 500 or `pragma_integrity_check != "ok"`.
C. UptimeRobot `api.jpcite.com/v1/health` flatlines for > 3 consecutive checks.
D. Operator-driven: `PRAGMA integrity_check;` reports anything other than `ok`.
```

**Pre-state self-check** (60 sec — confirm corruption is real, not a transient lock):

```bash
flyctl ssh console -a autonomath-api
sqlite3 /data/jpintel.db "PRAGMA integrity_check;" | head -5
sqlite3 /data/autonomath.db "PRAGMA integrity_check;" | head -5
df -h /data
exit
```

`PRAGMA integrity_check` returning `ok` ⇒ **STOP**, this is a different
incident (likely a deadlock or a hung writer — escalate per
`docs/runbook/sentry_alert_escalation.md` §4).

`integrity_check` returns specific corruption rows (e.g. `*** in database main
*** Page 1234: btree corrupted`) ⇒ proceed to §2.

`df -h` shows `/data` ≥ 95% full ⇒ jump to §4 (disk-full path) **before**
attempting restore.

## 2. Restore from R2 backup (jpintel.db, RTO 30 min)

```bash
# 1. Stop writers so the swap doesn't race ongoing transactions.
flyctl scale count 0 -a autonomath-api
# Wait ~10s for in-flight requests to drain.

# 2. SSH onto a fresh machine (Fly auto-provisions when count returns to 1).
flyctl scale count 1 -a autonomath-api
flyctl ssh console -a autonomath-api

# 3. Restore. The script auto-snapshots /data/<live>.db to
#    /data/backups/pre-restore/pre-restore-jpintel-<ts>.db.gz BEFORE overwriting
#    so this step is reversible.
python /app/scripts/restore_db.py --db jpintel --yes

# 4. Confirm.
sqlite3 /data/jpintel.db "PRAGMA integrity_check;" | head -2
# Expect: ok
sqlite3 /data/jpintel.db "SELECT COUNT(*) FROM programs WHERE excluded=0;"
# Expect: 11,601 ± delta-since-last-snapshot (NOT 0, NOT < 11,000).
exit
```

## 3. Restore from R2 backup (autonomath.db, RTO 2 h)

`autonomath.db` is 12.4 GB; the gzipped R2 object is ~3.3 GB. Download to
`/data` rather than `/tmp` because Fly machines have only 8 GB of overlay disk
and `/tmp` saturates before the gunzip finishes.

```bash
flyctl scale count 0 -a autonomath-api
flyctl scale count 1 -a autonomath-api
flyctl ssh console -a autonomath-api

# 1. Verify the volume has > 25 GB free for: live DB swap (12.4) + pre-restore
#    snapshot (12.4) + transient gunzip scratch. If not, jump to §4 first.
df -h /data

# 2. Restore. --staging-dir keeps gunzip scratch on the volume, not /tmp.
python /app/scripts/restore_db.py --db autonomath --yes \
  --staging-dir /data/restore-scratch

# 3. Confirm. autonomath.db lacks a stable canonical row count so use FTS.
sqlite3 /data/autonomath.db "SELECT COUNT(*) FROM am_entities;"
# Expect: 503,930 ± delta. If < 500,000 the snapshot is older than expected
#         — proceed to §5 to pick an earlier known-good key.
sqlite3 /data/autonomath.db "PRAGMA integrity_check;" | head -2

# 4. Bring traffic back via deep-health gate (NOT the 25s rolling-restart smoke).
exit
flyctl deploy --remote-only --strategy rolling -a autonomath-api
sleep 90
curl -fsS --max-time 30 https://api.jpcite.com/v1/am/health/deep | jq .
```

## 4. Disk-full path (special case of corruption trigger)

`/data` saturating ≥ 95% can itself manifest as `disk I/O error` or `database
disk image is malformed` because SQLite cannot complete a checkpoint when the
WAL has nowhere to grow.

```bash
flyctl ssh console -a autonomath-api
df -h /data
du -sh /data/* | sort -hr | head -10
# Likely top consumers in order:
#   /data/autonomath.db      ~12.4 GB
#   /data/backups            ~5-10 GB (60+ jpintel hourly snapshots)
#   /data/backups-autonomath ~10 GB (7 daily + 4 weekly autonomath snapshots)
#   /data/jpintel.db         ~352 MB
#   /data/jpintel.db-wal     up to ~10% of jpintel.db when writes are hot
```

**Triage in this order** (each step buys disk; STOP at first that frees
enough headroom for the corruption restore):

```bash
# 4a. Drop pre-restore snapshots older than 14 days (always disposable).
find /data/backups/pre-restore -type f -mtime +14 -delete

# 4b. Drop expired retention. The cron prune step may not have run if cron
#     itself is what crashed.
python /app/scripts/cron/backup_jpintel.py --prune-only
python /app/scripts/cron/backup_autonomath.py --prune-only

# 4c. VACUUM autonomath.db (reclaims any deleted rows' pages). Requires the
#     volume to have free space equal to the DB size — only works if 4a/4b
#     already cleared > 13 GB. Do NOT VACUUM jpintel.db unless writers are
#     stopped (it holds an exclusive lock for the whole operation).
flyctl scale count 0 -a autonomath-api
sqlite3 /data/autonomath.db "VACUUM;"
flyctl scale count 1 -a autonomath-api

# 4d. Last resort: extend the volume. This requires a machine restart and
#     ~5 min downtime. Volumes can grow but NEVER shrink — pick a target
#     that buys 12+ months of NTA bulk growth (~+11 GB/yr).
flyctl volumes list -a autonomath-api
flyctl volumes extend <volume-id> --size 80 -a autonomath-api
```

After 4a–4d, return to §2 or §3.

## 5. Picking an earlier snapshot (when the most recent one is also bad)

If `restore_db.py --yes` lands a snapshot that itself fails
`PRAGMA integrity_check`, the corruption window started before the most
recent backup. List candidates:

```bash
python /app/scripts/backup_manifest.py --list jpintel | head -30
# Output rows: <key>  <size>  <fetched_at>  <sha256>  <rpo_violated>

# Pick the newest key whose row passes integrity_check post-restore.
python /app/scripts/restore_db.py --db jpintel \
  --backup-key jpintel/jpintel-<ts>.db.gz --yes
sqlite3 /data/jpintel.db "PRAGMA integrity_check;" | head -2
```

Repeat with progressively older keys until one is `ok`. Customer-side data
loss equals the gap between the chosen snapshot and the corruption time.
Document the gap in the post-incident note (see §8).

## 6. Verify (every restore must complete this)

```bash
# 6a. SQLite-level integrity.
sqlite3 /data/jpintel.db "PRAGMA integrity_check;"
sqlite3 /data/jpintel.db "PRAGMA foreign_key_check;"
sqlite3 /data/autonomath.db "PRAGMA integrity_check;"

# 6b. Application-level deep health.
curl -fsS --max-time 30 https://api.jpcite.com/v1/am/health/deep | jq .
# Expect: { "status": "ok", "jpintel_programs_searchable": 11601, ... }

# 6c. Smoke a metered call. Costs ¥3 — capture the audit_seal for the post-mortem.
curl -fsS -H "X-API-Key: $JPINTEL_OPERATOR_KEY" \
  https://api.jpcite.com/v1/programs?q=ものづくり | jq '.audit_seal'

# 6d. Sentry resolve.
#     - Mark the originating issue Resolved with note "restored from
#       jpintel/jpintel-<ts>.db.gz on <restore-ts>".
```

## 7. Rollback

The pre-restore snapshot makes every restore reversible:

```bash
ls -lh /data/backups/pre-restore/
# pre-restore-jpintel-20260507-143012.db.gz   (auto-named by restore_db.py)

python /app/scripts/restore_db.py --db jpintel \
  --local-file /data/backups/pre-restore/pre-restore-jpintel-<ts>.db.gz \
  --yes
```

Same shape for autonomath.db with `--db autonomath`. Pre-restore snapshots
are kept 14 days (see §4a — do **not** delete them within that window unless
explicitly running the disk-full triage and the restore in question is fully
verified by §6).

## 8. Post-incident

Within 24 h of recovery, write a one-page note to
`tools/offline/_inbox/incidents/db_corruption_<yyyy-mm-dd>.md`:

* trigger (Sentry issue ID, integrity_check stderr, df output)
* RPO violation (snapshot age vs corruption time)
* root cause candidate (volume hardware? deploy mid-write? VACUUM mid-run?)
* customer impact (rows lost, requests rejected, webhook delivery gap)
* whether to widen `am_entities`/`programs` row-count alerts in
  `monitoring/sentry_alert_rules.yml`

## 9. Failure modes

* **Both jpintel.db and autonomath.db corrupt simultaneously**: not
  recoverable to PITR — restore both from the most recent good R2 snapshot
  per §2 + §3 in series, accept the maximum RPO of the two (24 h on
  autonomath.db). Treat this as a Fly volume hardware loss and follow up
  with `docs/runbook/disaster_recovery.md` §3.2 (full infra rebuild).
* **R2 unreachable during restore** (Cloudflare outage): `restore_db.py`
  fails fast. Re-run when R2 returns; the live volume is untouched until the
  download succeeds. Do **not** improvise by uploading via `flyctl ssh sftp` —
  `flyctl ssh sftp get` refuses to overwrite, and a botched dev-fixture
  swap silently masks the production restore (see CLAUDE.md gotcha).
* **`pre-restore` snapshot itself corrupt**: trust the R2 path. Do NOT re-run
  `restore_db.py` against a `--local-file` whose `sha256sum` doesn't match
  the manifest entry — it propagates corruption.
* **Volume grew to > 80 GB and `flyctl volumes extend` fails**: contact Fly
  support. Do not attempt a `dd` clone — Fly's volume API is the only path
  and improvising risks the JPINTEL_DATA volume itself.

## 10. Items needing user action (one-time prerequisites)

This runbook assumes the §S2 boot gate (`R2_ENDPOINT`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, `R2_BUCKET`) is already set per
`docs/runbook/disaster_recovery.md` §2 and that hourly + daily backup crons
are running per the `nightly-backup` and `weekly-backup-autonomath` GHA
workflows. Without those, this runbook has nothing to restore from.
