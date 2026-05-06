---
title: Litestream Setup Runbook
updated: 2026-05-04
operator_only: true
category: dr
---

# Litestream Setup Runbook — Continuous SQLite Replication to R2

**Owner**: 梅田茂利 (info@bookyou.net) — solo zero-touch
**Operator**: Bookyou株式会社 (T8010001213708)
**Status**: DRAFT — sidecar deploy not yet wired. This runbook is the
manual procedure for the operator to enable continuous replication when
ready.
**Related**: `docs/runbook/disaster_recovery.md` (point-in-time restore
target), `MASTER_PLAN_v1.md` chapter 8 M8.
**Last reviewed**: 2026-05-04

## Why litestream

The current backup posture is point-in-time snapshots:

  * `scripts/cron/backup_jpintel.py` — hourly online backup, 24h RPO
    ceiling for jpintel.db (316 MB).
  * `scripts/cron/backup_jpcite.py` — daily online backup, 24h RPO
    ceiling for jpcite.db (~9.5 GB).
  * Both upload gzip + sha256 to Cloudflare R2 with tiered retention.

Failure modes the snapshot pipeline does NOT cover:

  1. **Sub-hour data loss** on jpintel.db (a volume crash 50 minutes
     after the last hourly snapshot loses 50 minutes of customer
     activity, 信用 events, and webhook dedup rows).
  2. **Sub-day data loss** on jpcite.db (a deploy-time SIGTERM
     between the daily snapshot and a bulk-ingest commit can lose a
     full ingest run; replay from `data/ingest_logs/` is doable but
     slow).
  3. **Continuous shipping with PITR** — restoring "the DB as it was
     at 14:23:07" requires WAL replay, which snapshots cannot give us.

Litestream solves all three. It tails SQLite's WAL, ships every
checkpoint segment to R2 in real time, and offers point-in-time restore
to any wall-clock moment in the retention window. RPO drops from
hours/days to seconds.

## What we deploy

Two surfaces, both new:

1. **`litestream` binary** baked into the Fly machine. Runs as a sidecar
   process inside the same Fly app (`autonomath-api`), tailing the
   live DB files at `/data/jpintel.db` and `/data/jpcite.db`.
2. **`litestream.yml` config file** at `/etc/litestream.yml` mounted
   from a Fly secret or templated by `entrypoint.sh`. Specifies which
   DBs to replicate, where in R2 to ship them, and retention windows.

We deliberately do NOT remove the existing snapshot crons. Litestream
gives PITR; the snapshot crons give cold-storage-only "I can boot a
fresh DB tomorrow" disaster recovery. They are complementary surfaces;
removing snapshots would couple our DR posture to litestream itself.

## Pre-flight checklist

- [ ] R2 bucket `jpintel-backup` (or `JPINTEL_BACKUP_BUCKET`) exists and
      has > 50 GB free room. Litestream WAL ships add ~5-10% on top of
      raw write traffic; for jpcite.db's bulk-ingest pattern that
      is ~1 GB/month sustained.
- [ ] Fly secrets set: `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`,
      `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`. (Same set used by the
      snapshot crons — verify with `flyctl secrets list`.)
- [ ] Fly machine size: litestream sidecar adds ~20 MB RAM + < 1% CPU
      sustained. Current `shared-cpu-2x` / 2 GB has plenty of headroom.
- [ ] Sentry DSN set so litestream errors (R2 timeout, WAL corruption)
      surface in the operator inbox.

## Step 1 — Install litestream binary in the Fly image (15 min)

In `Dockerfile` add **at the end of the build stage** (do NOT rebuild
the layer that installs `pip install -e .[dev,site]` — that layer is
expensive and unrelated):

```Dockerfile
# Litestream — continuous SQLite replication to Cloudflare R2.
# Installed as a static binary so we do not pull in a Go runtime.
ARG LITESTREAM_VERSION=0.3.13
RUN curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C /usr/local/bin litestream \
 && chmod 0755 /usr/local/bin/litestream \
 && /usr/local/bin/litestream version
```

Verify post-deploy:

```bash
flyctl ssh console -a autonomath-api -C "litestream version"
# expected: v0.3.13 (or pinned version)
```

## Step 2 — Create `litestream.yml` config (10 min)

Litestream reads `/etc/litestream.yml` by default. We template it from
`entrypoint.sh` so the R2 credentials inject from Fly secrets at boot
without baking them into the image.

Add this block to `entrypoint.sh` BEFORE the existing `exec uvicorn`
line (or wherever the main app starts):

```bash
# === Litestream config templating ===
# Generated at boot from Fly secrets so credentials never land in the
# Docker image layer. Indempotent — overwrites each boot.
cat > /etc/litestream.yml <<EOF
# Litestream config — managed by entrypoint.sh, do not hand-edit.
access-key-id: "${R2_ACCESS_KEY_ID}"
secret-access-key: "${R2_SECRET_ACCESS_KEY}"

dbs:
  - path: ${JPINTEL_DB_PATH:-/data/jpintel.db}
    replicas:
      - type: s3
        endpoint: "${R2_ENDPOINT}"
        bucket: "${R2_BUCKET}"
        path: litestream/jpintel
        region: auto
        # Retention: 7 days WAL + checkpoints. Reads PITR back 7 days;
        # older history rolls into the snapshot tier (backup_jpintel.py).
        retention: 168h
        retention-check-interval: 1h
        sync-interval: 1s
        # Snapshot interval: full DB checkpoint every 6 hours so the
        # restore time stays bounded (longer interval = larger WAL
        # replay on restore).
        snapshot-interval: 6h
  - path: ${AUTONOMATH_DB_PATH:-/data/jpcite.db}
    replicas:
      - type: s3
        endpoint: "${R2_ENDPOINT}"
        bucket: "${R2_BUCKET}"
        path: litestream/jpcite
        region: auto
        # jpcite.db is ~9.5 GB. Retention: 3 days WAL + checkpoints
        # (snapshot tier covers daily / weekly beyond that). Snapshot
        # interval: 24h so the daily checkpoint aligns with low-write
        # window.
        retention: 72h
        retention-check-interval: 1h
        sync-interval: 1s
        snapshot-interval: 24h
EOF
```

## Step 3 — Run litestream as a sidecar (10 min)

Two deploy patterns; pick one.

### Option A: Background process inside the same machine (simpler)

Modify `entrypoint.sh` to start litestream in the background BEFORE
launching uvicorn:

```bash
# === Start litestream sidecar ===
# Logs go to stdout so Fly's log shipper picks them up; structured
# log integration via `--exec=` would force litestream to manage the
# Python process lifecycle, which we do not want.
litestream replicate -config /etc/litestream.yml &
LITESTREAM_PID=$!
echo "litestream started pid=${LITESTREAM_PID}"

# Trap SIGTERM so we shut litestream down gracefully on Fly redeploy.
trap "kill -TERM ${LITESTREAM_PID:-} 2>/dev/null || true" TERM INT

# === Start API ===
exec /opt/venv/bin/uvicorn jpintel_mcp.api.main:app --host 0.0.0.0 --port 8080
```

Pros: zero new Fly machine, single deploy artifact.
Cons: if litestream crashes, no auto-restart inside the container; we
detect via Sentry (litestream emits to stdout, the alert rule needs
`logger:litestream level:[error,fatal]` added to
`monitoring/sentry_alert_rules.yml`).

### Option B: Separate Fly machine (more isolated)

Deploy a second tiny Fly machine running ONLY litestream, mounting the
SAME volume read-write. Fly volumes do not support multi-attach, so
this requires moving DBs to a Fly Volumes-backed shared filesystem
(NFS or LiteFS) — significant infra change. **Not recommended** until
we hit a real isolation problem; option A is the launch posture.

## Step 4 — Verify replication (5 min)

```bash
# 1. List R2 paths to confirm objects landed.
aws s3 ls "s3://${R2_BUCKET}/litestream/jpintel/" --endpoint-url "${R2_ENDPOINT}"
aws s3 ls "s3://${R2_BUCKET}/litestream/jpcite/" --endpoint-url "${R2_ENDPOINT}"

# 2. Confirm litestream is shipping WAL.
flyctl ssh console -a autonomath-api -C \
  "litestream replicate -config /etc/litestream.yml -no-expand-env" 2>&1 | head -30

# 3. Force a small write to jpintel.db, wait 5 seconds, list R2 again to
#    confirm the WAL segment grows.
flyctl ssh console -a autonomath-api -C \
  "sqlite3 /data/jpintel.db 'INSERT OR IGNORE INTO schema_migrations(id,checksum,applied_at) VALUES (\"litestream-smoke\",\"smoke\",datetime(\"now\"))'"
sleep 6
aws s3 ls "s3://${R2_BUCKET}/litestream/jpintel/" --endpoint-url "${R2_ENDPOINT}" --recursive | tail -5
```

## Step 5 — PITR restore drill (15 min, do once)

This is the litestream-equivalent of section 3.4 in `disaster_recovery.md`.

```bash
# Spin up a scratch machine.
flyctl machine clone --name jpcite-scratch <existing-machine-id>

# SSH in and replace /data/jpintel.db with a litestream restore at a
# specific timestamp.
flyctl ssh console -a autonomath-api --machine <scratch-machine-id>
mv /data/jpintel.db /data/jpintel.db.preserve
litestream restore \
  -config /etc/litestream.yml \
  -timestamp 2026-05-04T10:30:00Z \
  /data/jpintel.db
sqlite3 /data/jpintel.db "SELECT COUNT(*) FROM api_keys;"

# Tear down the scratch machine.
flyctl machine destroy <scratch-machine-id>
```

If the restored DB row counts match expectations for the chosen
timestamp, litestream is producing usable replicas.

## Step 6 — Update disaster_recovery.md to reference PITR (post-cutover)

Once steps 1-5 are green in production, edit `docs/runbook/disaster_recovery.md`:

  * Add a section 3.6 "Point-in-time restore via litestream" with the
    Step 5 commands.
  * Note that `litestream restore` is the FIRST recovery option for any
    incident with a known wall-clock window; snapshot-tier restore
    becomes the fallback for events older than the litestream retention
    window.

## Operational notes

- **Cost**: R2 PUT pricing is $4.50 / 1M writes. Litestream sync
  interval = 1s means worst-case 86,400 PUTs/day/DB = ~$0.40/day or
  ~$12/month. In practice the rate is much lower because litestream
  batches WAL segments. Budget headroom: ~$15/month above current
  snapshot pipeline (~$1.80/month → ~$17/month total).
- **Restore speed**: ~10-30s per GB of DB + WAL (R2 Tokyo → Fly Tokyo
  bandwidth is ~80 MB/s). jpcite.db restore: ~2-5 min plus WAL
  replay. jpintel.db restore: < 30s.
- **Monitoring**: litestream writes structured logs to stdout. Add to
  `monitoring/sentry_alert_rules.yml` after cutover:

  ```yaml
  - id: litestream_replication_lag
    name: "[HIGH] Litestream replication lag > 60s"
    severity: high
    filter:
      query: 'logger:litestream message:"replication lag" extra.lag_seconds:>60'
    threshold: 1
    window: 10m
    frequency: 5m
  ```

- **Rollback**: comment out the `litestream replicate` line in
  `entrypoint.sh`, redeploy. Snapshots continue working. R2 storage
  cost from prior litestream segments rolls off via the retention
  window automatically.

## Items needing user action

1. **Bake litestream binary** into the Docker image (Step 1).
2. **Edit `entrypoint.sh`** to template `/etc/litestream.yml` and
   start the sidecar (Steps 2 + 3, option A).
3. **Run the verify drill** (Step 4) to confirm R2 is receiving WAL.
4. **Run the PITR restore drill** (Step 5) on a scratch machine.
5. **Update `disaster_recovery.md`** to reference PITR as the primary
   recovery path (Step 6).
6. **Add the litestream Sentry rule** (Operational notes) to alert on
   replication lag.

This runbook does NOT touch `Dockerfile` / `entrypoint.sh` / fly.toml
— per MASTER_PLAN_v1.md ch. 8 M8, those edits are explicitly out of
scope for this PR. The runbook is the operator's checklist for the
manual cutover.
