# Disaster Recovery / Backup Runbook (Cloudflare R2)

**Owner**: 梅田茂利 (info@bookyou.net)
**Last reviewed**: 2026-04-26

Operator-only — do not link from public docs. Excluded from mkdocs build via
`exclude_docs: _internal/` (`mkdocs.yml:140`).

This runbook covers nightly backup of the AutonoMath SQLite databases to
Cloudflare R2 + the three documented restore scenarios that
`scripts/cron/health_drill.py` exercises monthly.

## What we back up

| DB | path on Fly | size | backed up via | RPO |
|---|---|---|---|---|
| `jpintel.db` | `/data/jpintel.db` | ~316 MB | nightly GHA `nightly-backup.yml` (18:17 UTC daily, --keep 14, R2 14-day window) | 24h |
| `autonomath.db` | `/data/autonomath.db` | ~8.3 GB | weekly GHA `weekly-backup-autonomath.yml` (19:00 UTC Sunday, --keep 28, R2 4-snapshot window) + Fly machine cron real-time | 7 days (off-site) |

Two distinct GHA workflows, two distinct on-machine output directories
(`/data/backups` vs `/data/backups-autonomath`), two distinct R2 prefixes
(`autonomath-api/` vs `autonomath-api/autonomath-db/`) so the retention
windows do not collide. **Weekly cadence for autonomath.db** is a
deliberate cost trade-off: daily would push ~60 GB/week of R2 PUT traffic
+ SFTP egress for a slow-changing entity-fact corpus where write traffic
is bulk-ingest only (not request-path), so RPO=7d is acceptable —
anything newer than the last weekly snapshot can be replayed via ingest
scripts.

Historical note: `jpintel.db` was previously bundled into the container
image at `/seed/jpintel.db` and sync'd via `DATA_SEED_VERSION`. After
migration 032 unified the two DBs (autonomath.db became the primary,
jpintel tables mirrored as `jpi_*`), jpintel.db remains live in `/data/`
for the legacy code paths that still read it directly, and is backed up
nightly as the smaller, faster-changing surface.

## R2 setup (one-time)

### 1. Create the bucket

1. Cloudflare dashboard → **R2** → **Create bucket**.
2. Bucket name: `autonomath-backup`.
3. Location hint: `Asia-Pacific (APAC)` for proximity to Fly Tokyo.
4. **Public access**: leave **off**. We never serve backups publicly —
   restore goes through API token auth.

### 2. Mint an API token

1. R2 → **Manage R2 API Tokens** → **Create API Token**.
2. Permission: **Object Read & Write**.
3. Specify bucket: `autonomath-backup` (NOT account-wide — least
   privilege; if the token leaks the blast radius is one bucket).
4. TTL: 1 year. Calendar reminder for rotation 60 days before expiry.
5. Copy **Access Key ID**, **Secret Access Key**, **Endpoint URL**
   (looks like `https://<acct>.r2.cloudflarestorage.com`).

### 3. Push secrets to Fly

Names only — values stay in 1Password / operator's password manager,
never in this repo:

```bash
flyctl secrets set \
  R2_ENDPOINT='<from step 2>' \
  R2_ACCESS_KEY_ID='<from step 2>' \
  R2_SECRET_KEY='<from step 2>' \
  R2_BUCKET='autonomath-backup' \
  R2_BACKUP_PREFIX='nightly/' \
  -a autonomath-api
```

### 4. Bootstrap chain secrets (read by `entrypoint.sh`)

Once the **first** backup is uploaded, hash it and pin:

```bash
SHA="$(curl -sS <signed-url-to-r2-object> | sha256sum | awk '{print $1}')"
flyctl secrets set \
  AUTONOMATH_DB_URL='https://<acct>.r2.cloudflarestorage.com/autonomath-backup/nightly/autonomath-<YYYYMMDD>.db' \
  AUTONOMATH_DB_SHA256="$SHA" \
  -a autonomath-api
```

`entrypoint.sh:15-17` reads these. SHA mismatch → re-download
(scenario 2 below). Without `AUTONOMATH_DB_SHA256`, the entrypoint will
log a warning and **accept any blob** — never deploy without it.

The bootstrap chain is already wired and well-documented inline at
`entrypoint.sh:75-130`.

## Backup cadence (canonical)

Two GitHub Actions workflows handle the durable, redeploy-survivable
backup paths. The Fly machine cron path described in the legacy section
below is retained as a real-time secondary, but the **GHA workflows are
the primary path** for DR — they survive Fly redeploys, which the
machine crontab does not.

### `nightly-backup.yml` — jpintel.db (daily)

- Trigger: `cron: "17 18 * * *"` (18:17 UTC = 03:17 JST).
- `flyctl ssh console` → `scripts/backup.py --db /data/jpintel.db --out /data/backups --keep 14 --gzip`.
- Also runs `DELETE FROM anon_rate_limit WHERE date < date('now', '-90 days')`.
- SFTP pull → sha256 verify → R2 upload to prefix `autonomath-api/`.
- R2 retention: KEEP=14 (lex-sorted by timestamp, prune the rest).

### `weekly-backup-autonomath.yml` — autonomath.db (weekly)

- Trigger: `cron: "0 19 * * 0"` (19:00 UTC Sunday = 04:00 JST Monday).
- `timeout-minutes: 90`; the SFTP pull step has its own 60-minute cap
  for the gzipped 8.3 GB artifact.
- `flyctl ssh console` → `scripts/backup.py --db /data/autonomath.db --out /data/backups-autonomath --keep 28 --gzip`.
- SFTP pull → sha256 verify → R2 upload to prefix `autonomath-api/autonomath-db/`.
- R2 retention: KEEP=4 (4 weekly snapshots = 28 days).

The two workflows share the same secrets (`FLY_API_TOKEN`, `R2_ENDPOINT`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`) and the same
fail-open behavior — if R2 secrets are missing, the on-machine snapshot
still completes and the off-site step logs `::warning::` then exits 0.

### Why backup.py is shared (no autonomath-specific script)

`scripts/backup.py` is db-agnostic in the actual backup operation
(`sqlite3.Connection.backup()`, `PRAGMA integrity_check`, gzip, sha256).
The only jpintel-specific surface is the hard-coded `jpintel-` artifact
prefix in `run_backup()` and the matching prefix filter in `_prune_old()`.
That is acceptable as long as the two workflows write to **different**
`--out` directories — otherwise the nightly job's `--keep 14` would
delete week-old autonomath snapshots before the next weekly run.
**Do not collapse the two `--out` directories** until backup.py is
updated to derive its prefix from `--db`.

## Legacy: Fly machine cron (real-time secondary)

`scripts/cron/r2_backup.sh` runs nightly. It:

1. `sqlite3 /data/autonomath.db .backup /tmp/autonomath-YYYYMMDD.db`
   (online consistent snapshot; safe with WAL).
2. `PRAGMA integrity_check;` — refuse to upload corrupt blobs.
3. SHA256 sidecar: `<filename>.sha256`.
4. `rclone copyto` to `:s3:autonomath-backup/nightly/`.
5. `rclone delete --min-age 90d` — 90-day retention.
6. Local cleanup of `/tmp/`.

### Scheduling

Two acceptable hosts for the cron:

#### A. Fly machine cron (preferred)

Add to the running app's crontab via `flyctl ssh console`:

```bash
flyctl ssh console -a autonomath-api
# inside the machine:
echo '20 18 * * * /app/scripts/cron/r2_backup.sh >> /var/log/r2_backup.log 2>&1' | crontab -
```

`18:20 UTC` = `03:20 JST` — well after Tokyo prime hours, before any
morning batch.

Caveat: Fly machines are ephemeral; the crontab does not survive a
re-deploy. Two ways to harden:
1. Bake the cron line into the Dockerfile (`COPY crontab /etc/cron.d/`).
2. Switch to GHA-based scheduling (B below) — more durable.

#### B. GitHub Actions schedule (backup-of-backup)

`.github/workflows/r2_backup.yml` (operator-managed; not in repo by
default to avoid leaking schedule into a public Action log):

```yaml
on:
  schedule:
    - cron: '20 18 * * *'   # 03:20 JST
jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - run: |
          flyctl ssh console -a autonomath-api -C "/app/scripts/cron/r2_backup.sh"
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

Both running concurrently is fine — `r2_backup.sh` writes one object per
date stamp; the second invocation overwrites with the same content + SHA.

## Restore scenarios

The three scenarios `scripts/cron/health_drill.py` exercises:

### Scenario 1 — VM crash (Fly auto-restart, ~30 sec)

**Trigger**: Fly health check fails 3x; Fly destroys + recreates the
machine. No operator action required. Volume + secrets persist.

**Verification on next deploy**:

```bash
flyctl status -a autonomath-api
curl -sS https://autonomath.fly.dev/healthz
```

**RTO**: ~30 seconds. **RPO**: 0 (no data loss; volume + R2 untouched).

If the auto-restart loops more than 3 times in 10 minutes, the bootstrap
chain is broken — escalate to scenario 2.

### Scenario 2 — Volume corruption (R2 bootstrap restore, ~30 min)

**Trigger**: `/data/autonomath.db` SHA mismatches `AUTONOMATH_DB_SHA256`,
OR `PRAGMA integrity_check` returns non-`ok`. `entrypoint.sh:80-130`
detects this, removes the corrupt file, re-downloads from
`AUTONOMATH_DB_URL`, verifies SHA, and proceeds.

**Manual force** (when the auto-detect path doesn't trip):

```bash
flyctl ssh console -a autonomath-api
rm -f /data/autonomath.db /data/autonomath.db-wal /data/autonomath.db-shm
exit
flyctl machine restart <machine_id> -a autonomath-api
```

The restart fires `entrypoint.sh`, which downloads + verifies + boots.

**RTO**: ~30 min (R2 → Fly Tokyo @ ~5 MB/s for 8.3 GB). **RPO**: <7 days
for the off-site GHA path (weekly cadence), <24h if the Fly machine cron
ran successfully more recently. Bulk-ingest scripts can replay anything
newer than the snapshot window, so the practical data-loss ceiling is
"the last successful ingest run" not "the last backup".

### Scenario 3 — R2 outage (cached `/data` keeps serving)

**Trigger**: Cloudflare R2 returns 5xx for the `AUTONOMATH_DB_URL`.

**Behavior**: `entrypoint.sh:80-130` only downloads when the local file
is missing OR SHA mismatches. With a healthy local copy, the boot path
skips R2 entirely. Existing customer requests continue normally.

**Operator action**: monitor R2 status page. **Do NOT** run
`r2_backup.sh` during the outage — failed uploads do not corrupt the
local DB but pile up Sentry warnings.

**Verification**:

```bash
flyctl ssh console -a autonomath-api -C "ls -la /data/autonomath.db"
flyctl ssh console -a autonomath-api -C "sqlite3 /data/autonomath.db 'PRAGMA integrity_check;'"
```

**RTO**: 0 (no service degradation). **RPO**: depends on R2 outage
duration — once R2 returns, the next nightly backup catches up.

## DR drill cadence

Run `scripts/cron/health_drill.py` on the 1st of each month. It does
**not** trigger any actual failover; it only verifies preconditions
(env vars set, R2 HEAD reachable, local DB integrity). Output:
`analysis_wave18/dr_drill_<YYYY-MM>.md` (markdown row-per-run, grep-able).

```bash
.venv/bin/python scripts/cron/health_drill.py
```

Exit code != 0 → at least one scenario reports `fail`. Fix before
month-end.

## Pruning + capacity planning

R2 storage at 90-day retention:
- ~8.3 GB × 90 days = **~750 GB**
- Cloudflare R2 list price: $0.015/GB/month → **~$11/month**
- Egress: only on actual restore (~once per quarter expected) → ~$0
  (R2 has no egress fees to the public internet OR Cloudflare network)

Adjust `BACKUP_RETENTION_DAYS` in `r2_backup.sh` if cost climbs.
30-day retention covers all realistic recovery windows; 90 was chosen
for the comfort margin before any first incident.

## Cross-references

- `entrypoint.sh` (lines 75-130) — bootstrap + integrity chain.
- `scripts/cron/r2_backup.sh` — nightly backup cron.
- `scripts/cron/health_drill.py` — monthly DR scenario dry-run.
- `docs/_internal/health_monitoring_runbook.md` — uptime probe wiring.
- `docs/_internal/cloudflare_deploy_log.md` — Cloudflare Pages history.
- CLAUDE.md "Pending follow-ups" — backfill items.

## Drill log

Append-only. Each row is a manual local-disk drill (cp + open + query) — independent of
`scripts/cron/health_drill.py` which only verifies preconditions on Fly.

| date | source backup | restore time | integrity_check | row count parity (programs) | service-sim | operator |
|---|---|---|---|---|---|---|
| 2026-04-26 | `data/jpintel.db.bak-tierx-review-1777179541` (339 MB, 4/26 13:59) | 6 sec (cp + 3 sqlite queries + 1 python open) | `ok` | 13,578 backup vs 13,578 live → match | `SELECT unified_id, primary_name, tier FROM programs WHERE excluded=0 LIMIT 1` returned `('UNI-000780f85e', '南相馬市中小企業賃上げ緊急一時支援金', 'C')` | shigetoumeda |

Verified table-row parity on the same restore (no live counts available for comparison row-by-row, but the 4/26 backup matches CLAUDE.md's stated v0.3.0 numbers): `case_studies` 2,286 / `loan_programs` 108 / `enforcement_cases` 1,185 / `laws` 9,484. All `am_*` tables live in `autonomath.db` at repo root (8.29 GB, 503,930 entities) — out of scope for this jpintel.db drill; covered by the weekly GHA workflow.

Findings (2026-04-26 drill):

1. All 14 jpintel.db backups present in `data/` returned `PRAGMA integrity_check = ok`. No corruption.
2. Local jpintel.db backups span 4/23 → 4/26. Row count grew 6,658 → 13,578 over 3 days, reflecting the legitimate Wave-7→9 ingest cadence.
3. autonomath.db has **no nightly backup at the repo root** other than ad-hoc `.bak.pre_*` snapshots from migration cuts. The R2 weekly path (`weekly-backup-autonomath.yml`) is the only durable off-site copy. Verify on next deploy that the GHA workflow last-run is < 7 days old.
4. Local disk pressure check: total `data/*.bak*` ~ 4.3 GB on jpintel side + 33 GB on autonomath side at repo root. Rotation candidates listed below the table.
