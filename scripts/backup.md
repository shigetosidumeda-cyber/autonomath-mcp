# jpintel-mcp backup runbook

Placed under `scripts/` (not `docs/`) because another agent owns `docs/`.

## Local smoke test

```bash
.venv/bin/python scripts/backup.py \
    --db data/jpintel.db \
    --out /tmp/jpintel-backups \
    --keep 14 \
    --gzip
```

Output:
- `/tmp/jpintel-backups/jpintel-YYYYMMDD-HHMMSS.db.gz`
- `/tmp/jpintel-backups/jpintel-YYYYMMDD-HHMMSS.db.gz.sha256`

## Restore

```bash
.venv/bin/python scripts/restore.py \
    /path/to/jpintel-YYYYMMDD-HHMMSS.db.gz \
    --target data/jpintel.db \
    --yes
```

Verifies sha256 before overwriting. Removes `*-wal` / `*-shm` so SQLite
re-opens cleanly.

## Fly.io deployment — two options

### Option 1: on-machine systemd timer (NOT RECOMMENDED)

- Pros: no extra infra.
- Cons: if the volume or machine is lost, the backup is lost with it.
- Only useful as a stopgap. Backup must be copied off the machine.

Rough sketch (place under `/etc/systemd/system/` on the Fly machine):

```ini
# jpintel-backup.service
[Unit]
Description=jpintel-mcp online SQLite backup

[Service]
Type=oneshot
WorkingDirectory=/app
ExecStart=/app/.venv/bin/python /app/scripts/backup.py \
    --db /data/jpintel.db --out /data/backups --keep 14 --gzip \
    --log /data/backups/backup.log
```

```ini
# jpintel-backup.timer
[Unit]
Description=Run jpintel-mcp backup nightly

[Timer]
OnCalendar=*-*-* 03:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

Enable with `systemctl enable --now jpintel-backup.timer`.

### Option 2: external GitHub Actions runner -> Fly SSH -> R2/S3 (RECOMMENDED)

Off-box copy protects against volume corruption, accidental deletion, and Fly
app/machine loss. This is the pattern to use.

Template workflow (place at `.github/workflows/nightly-backup.yml`; only the
wiring sketch is shown, secrets management is your responsibility):

```yaml
name: nightly-backup
on:
  schedule:
    - cron: "0 18 * * *"   # 03:00 JST
  workflow_dispatch: {}

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Install fly CLI
        uses: superfly/flyctl-actions/setup-flyctl@master

      - name: Run backup on machine
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        run: |
          flyctl ssh console -a jpintel-mcp -C \
            "/app/.venv/bin/python /app/scripts/backup.py \
              --db /data/jpintel.db \
              --out /data/backups \
              --keep 7 --gzip"

      - name: Copy latest backup off machine
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
        run: |
          LATEST=$(flyctl ssh console -a jpintel-mcp -C \
              "ls -1t /data/backups/jpintel-*.db.gz | head -1" | tr -d '\r\n')
          flyctl ssh sftp get "$LATEST" -a jpintel-mcp
          flyctl ssh sftp get "${LATEST}.sha256" -a jpintel-mcp

      - name: Verify sha256 locally
        run: shasum -a 256 -c jpintel-*.db.gz.sha256

      - name: Upload to R2
        env:
          AWS_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          AWS_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
          AWS_DEFAULT_REGION: auto
          R2_ENDPOINT: ${{ secrets.R2_ENDPOINT }}
          R2_BUCKET: ${{ secrets.R2_BUCKET }}
        run: |
          aws s3 cp jpintel-*.db.gz "s3://$R2_BUCKET/jpintel-mcp/" \
              --endpoint-url "$R2_ENDPOINT"
          aws s3 cp jpintel-*.db.gz.sha256 "s3://$R2_BUCKET/jpintel-mcp/" \
              --endpoint-url "$R2_ENDPOINT"
```

Recommended retention policy:
- R2: 30 daily + 12 monthly.
- On-machine: 7 days (scratch/fast-restore tier).

## Why this design

- `sqlite3.Connection.backup(...)` is online-safe, no need to stop writers.
- sha256 sidecar catches any bitrot in transit or at rest.
- Gzip halves size (empirically ~60% smaller on current 144 MB DB).
- Atomic `Path.replace()` after staging in same directory avoids partial files.
- Prune by mtime so a bad upload run cannot instantly wipe history.
