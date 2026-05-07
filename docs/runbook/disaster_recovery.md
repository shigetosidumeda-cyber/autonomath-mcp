---
title: Disaster Recovery Runbook
updated: 2026-05-07
operator_only: true
category: dr
---

# Disaster Recovery Runbook -- jpcite

**Owner**: 梅田茂利 (info@bookyou.net) -- solo zero-touch
**Last reviewed**: 2026-04-29
**Related**: `docs/disaster_recovery.md` (public-facing scenario matrix), `docs/_internal/dr_backup_runbook.md` (legacy R2 setup notes)

This is the actionable, single-operator playbook for recovering the two SQLite
databases of the jpcite / jpcite service. It supersedes the prior
runbook for the new tiered-backup pipeline (`scripts/cron/backup_*.py`).

## 1. What we back up

| DB              | Live path             | Size   | Cron                                    | RPO   | RTO    |
|-----------------|-----------------------|--------|------------------------------------------|-------|--------|
| jpintel.db      | `/data/jpintel.db`    | 316 MB | `backup_jpintel.py` hourly (`0 * * * *`) | 1 h   | 30 min |
| autonomath.db   | `/data/autonomath.db` | 8.3 GB | `backup_autonomath.py` daily (`0 4 * * *`) | 24 h  | 2 h    |

Backups are SHA256-pinned, gzipped, uploaded to Cloudflare R2 with
server-side encryption (R2 default), and retained:

- jpintel: 24 hourly + 30 daily + 12 monthly (~66 copies, ~7.7 GB on R2)
- autonomath: 7 daily + 4 weekly (~11 copies, ~33 GB on R2)

Total cold storage: ~40 GB at $0.045/GB-mo = **~$1.80 / month**.

## 2. Required environment

Set via `flyctl secrets set` (NEVER commit these to the repo):

```
R2_ENDPOINT             https://<account>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID        <token-access-key>
R2_SECRET_ACCESS_KEY    <token-secret>
R2_BUCKET               jpintel-backup        # or JPINTEL_BACKUP_BUCKET
SENTRY_DSN              <existing>
FLY_API_TOKEN           <existing>            # only needed for --restart
```

Optional (defaults shown):

```
JPINTEL_DB_PATH                 /data/jpintel.db
AUTONOMATH_DB_PATH              /data/autonomath.db
JPINTEL_BACKUP_LOCAL_DIR        /data/backups
AUTONOMATH_BACKUP_LOCAL_DIR     /data/backups-autonomath
JPINTEL_BACKUP_PREFIX           jpintel/
AUTONOMATH_BACKUP_PREFIX        autonomath/
BACKUP_MANIFEST_PATH            analytics/backups.jsonl
```

## 3. Recovery scenarios

### 3.1 Volume crash / DB file corruption

**Symptoms**: `sqlite3.DatabaseError: database disk image is malformed`,
`/v1/am/health/deep` returns 500, or `PRAGMA integrity_check` fails.

**Steps** (target RTO 30 min for jpintel, 2 h for autonomath):

```bash
# 1. Stop traffic so writers don't race the swap.
flyctl scale count 0 --app autonomath-api

# 2. SSH onto a fresh machine (Fly auto-provisions one when count=1 next).
flyctl ssh console --app autonomath-api

# 3. Restore from the latest R2 backup. --yes confirms overwrite.
#    Pre-restore safety snapshot is taken automatically into
#    /data/backups/pre-restore/.
python /app/scripts/restore_db.py --db jpintel --yes
python /app/scripts/restore_db.py --db autonomath --yes  # only if also corrupt

# 4. Bring traffic back.
flyctl scale count 1 --app autonomath-api

# 5. Smoke.
curl -fsS https://api.jpcite.com/v1/am/health/deep | jq .
```

**Reversibility**: The pre-restore snapshot is at
`/data/backups/pre-restore/pre-restore-<live-stem>-<ts>.db.gz`. To roll back:

```bash
python /app/scripts/restore_db.py --db jpintel \
  --local-file /data/backups/pre-restore/pre-restore-jpintel-<ts>.db.gz \
  --yes
```

### 3.2 Fly app deletion / total infra loss

**Symptoms**: `flyctl apps list` does not show `autonomath-api`, DNS resolves
to nothing, or the volume is unrecoverable (Fly support cannot restore).

**Steps** (RTO ~2 h):

```bash
# 1. Re-create the app + volume from scratch.
flyctl apps create autonomath-api
flyctl volumes create jpintel_data --region nrt --size 20 --app autonomath-api
flyctl secrets set R2_ENDPOINT=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... \
  R2_BUCKET=jpintel-backup SENTRY_DSN=... STRIPE_SECRET_KEY=... \
  STRIPE_WEBHOOK_SECRET=... API_KEY_SALT=... JPINTEL_CORS_ORIGINS=... \
  --app autonomath-api

# 2. Push the image.
flyctl deploy --app autonomath-api

# 3. Restore both DBs onto the new volume.
flyctl ssh console --app autonomath-api -C "python /app/scripts/restore_db.py --db jpintel --yes"
flyctl ssh console --app autonomath-api -C "python /app/scripts/restore_db.py --db autonomath --yes"

# 4. Verify.
curl -fsS https://api.jpcite.com/v1/am/health/deep | jq .

# 5. Reattach DNS at Cloudflare (api.jpcite.com -> Fly IP).
```

### 3.3 R2 bucket compromise / accidental deletion

**Symptoms**: `aws s3 ls` against the bucket fails with 403, OR backups
appear deleted by an attacker, OR a compromised R2 token is found in logs.

**Steps** (RTO instant for read path; ~1 h to restore backup capability):

1. Live API keeps serving from the Fly volume -- DB is local. There is no
   immediate user-facing impact.
2. Cloudflare dashboard -> R2 -> revoke the compromised token.
3. Mint a new token (Object Read & Write, scoped to the bucket only).
4. `flyctl secrets set R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=...`
5. Run an immediate snapshot to seed the new bucket / verify auth:
   ```bash
   flyctl ssh console --app autonomath-api -C \
     "python /app/scripts/cron/backup_jpintel.py"
   flyctl ssh console --app autonomath-api -C \
     "python /app/scripts/cron/backup_autonomath.py"
   ```
6. If the attacker deleted prior backups: nothing to recover from R2, but the
   live volume is unaffected. Treat this as a "single-copy" warning -- next
   volume corruption becomes catastrophic until daily cadence rebuilds.

### 3.4 Human error -- `DELETE FROM` or migration gone wrong

**Symptoms**: row counts crash, customers can't log in, or stripe webhooks
start emitting "subscriber not found".

**Steps** (RTO ~30 min):

```bash
# 1. Identify the most recent good hourly snapshot.
flyctl ssh console --app autonomath-api -C \
  "python /app/scripts/backup_manifest.py && cat /app/analytics/backups.jsonl | head"

# 2. Choose a key from BEFORE the bad event.
python /app/scripts/restore_db.py --db jpintel \
  --backup-key jpintel/jpintel-20260429-040000.db.gz --yes

# 3. Re-run any forward operations that should NOT be lost (e.g. legitimate
#    Stripe webhooks since the snapshot can be reconstructed via
#    scripts/replay_stripe_usage.py -- see scripts/stripe_reconcile.py).
```

The pre-restore snapshot makes the DELETE itself recoverable in case the
selected backup is also wrong:

```bash
python /app/scripts/restore_db.py --db jpintel \
  --local-file /data/backups/pre-restore/pre-restore-jpintel-<ts>.db.gz --yes
```

### 3.5 Backup integrity drill failure (Sentry alert)

**Trigger**: weekly `test_backup_integrity.py` cron emits a Sentry warning
("backup integrity: PRAGMA failed", "row count mismatch", or "size drift").

**Steps**:

1. SSH and re-run the drill manually to capture the full stderr:
   ```bash
   flyctl ssh console --app autonomath-api -C \
     "python /app/scripts/test_backup_integrity.py"
   ```
2. If `sha mismatch`: the backup file in R2 is corrupted. Take a fresh
   manual snapshot (`backup_jpintel.py`), then re-run the drill.
3. If `PRAGMA integrity_check` fails: do NOT roll back to that snapshot
   under any circumstance. Take a fresh snapshot, roll the broken one out
   of the retention window manually, alert on it via Sentry comment.
4. If `row count mismatch`: usually a hot-table drift between snapshot and
   live (within the RPO window). Acceptable up to 10%. If larger, check
   ingest logs in `data/ingest_logs/` for the relevant hour.
5. If `size drift`: a recent ingest may have doubled the DB size.
   Recompute retention math; consider compacting via VACUUM in a
   maintenance window.

## 4. Monitoring

- `analytics/backups.jsonl` -- written daily by `backup_manifest.py`.
  Each row has `rpo_violated: true/false`. Pipe into your dashboard tool of
  choice or grep for violations:
  ```bash
  jq -r 'select(.rpo_violated) | "\(.db_id) \(.age_hours)h"' analytics/backups.jsonl
  ```
- Sentry: backup_*.py and test_backup_integrity.py call `sentry_sdk.init`
  if `SENTRY_DSN` is set -- failures show up under the `production`
  environment with tag `name=jpintel.backup_*`.
- UptimeRobot: nothing dedicated for backups (they're internal-only).

## 5. Cron registration

Fly does not have a native cron, so use one of:

### Option A: in-container cron (recommended for solo)

Add `cron` to the Dockerfile and to entrypoint.sh:
```Dockerfile
RUN apt-get install -y cron rclone
COPY ops/crontab /etc/cron.d/jpintel
RUN chmod 0644 /etc/cron.d/jpintel && crontab /etc/cron.d/jpintel
```

Crontab content (UTC):
```
0 * * * *  /app/.venv/bin/python /app/scripts/cron/backup_jpintel.py >> /data/backups/backup_jpintel.log 2>&1
0 4 * * *  /app/.venv/bin/python /app/scripts/cron/backup_autonomath.py >> /data/backups-autonomath/backup_autonomath.log 2>&1
30 4 * * * /app/.venv/bin/python /app/scripts/backup_manifest.py >> /data/backups/manifest.log 2>&1
0 6 * * 0  /app/.venv/bin/python /app/scripts/test_backup_integrity.py >> /data/backups/integrity.log 2>&1
```

Then `service cron start` from entrypoint.sh.

### Option B: GitHub Actions cron (current legacy path)

Pre-existing: `.github/workflows/nightly-backup.yml` and
`weekly-backup-autonomath.yml` already do this for the legacy `scripts/backup.py`.
Add new job entries pointed at the new tiered scripts (or leave both running
during cutover -- backups are idempotent and no-overwrite-collide).

## 6. R2 bucket setup (one-time, by user)

1. Cloudflare dashboard -> R2 -> Create bucket.
   - Name: `jpintel-backup`
   - Location hint: `Asia-Pacific (APAC)` (Tokyo proximity to Fly nrt)
   - Public access: **OFF**
   - Default encryption: SSE-S3 / AES-256 (default in R2 -- VERIFY in bucket
     settings -> "Encryption at rest")
2. R2 -> Manage R2 API Tokens -> Create Token.
   - Permission: **Object Read & Write**
   - Bucket scope: `jpintel-backup` only
   - TTL: 1 year (calendar reminder to rotate)
3. Save credentials into Fly secrets (see section 2).
4. Lifecycle policy (optional, defense in depth): R2 does not yet auto-expire
   objects beyond what `backup_jpintel.py` does. Our retention prune is the
   source of truth. Consider enabling Cloudflare's R2 lifecycle (when
   available) to mirror the same window as a belt-and-suspenders fallback.

## 7. Verifying SSE encryption

R2 encrypts all objects at rest by default (XTS-AES-256, transparent). To
confirm:

```bash
rclone --config /dev/null \
  --s3-endpoint $R2_ENDPOINT --s3-access-key-id $R2_ACCESS_KEY_ID \
  --s3-secret-access-key $R2_SECRET_ACCESS_KEY --s3-region auto \
  --s3-provider Cloudflare \
  lsd ":s3:jpintel-backup/"
```

Compare with the Cloudflare bucket dashboard -> Settings -> "Encryption at
rest" -> should read **Enabled (XTS-AES-256)**.

If a future R2 release adds customer-managed keys (CMEK), enable it via the
dashboard and rotate keys per the existing token TTL above.

## 8. Drill schedule (manual, calendar-set)

| Cadence  | Drill                               | Owner     |
|----------|-------------------------------------|-----------|
| Weekly   | `test_backup_integrity.py` (auto)   | cron      |
| Monthly  | Restore-jpintel-to-staging dry run  | 梅田      |
| Quarterly| Full DR drill (delete app, rebuild) | 梅田      |

## 9. Items needing user action

The pipeline is code-complete but cannot run end-to-end without the
following one-time manual steps:

1. **Cloudflare R2 bucket creation** (section 6 above).
2. **Fly secrets set** for `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`,
   `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` (or reuse `JPINTEL_BACKUP_BUCKET`).
3. **Cron registration** -- pick option A (in-container cron) or option B
   (GHA workflows). Until this is done, backups will not run on schedule.
4. **Verify SSE-AES-256 enabled** on the bucket (default is yes; confirm via
   dashboard).
5. **Calendar reminder** for token rotation (1 year) and quarterly DR drill.
6. **Optional: install `rclone` in the Docker image** if not already. Verify
   with `flyctl ssh console --app autonomath-api -C "rclone version"`.
