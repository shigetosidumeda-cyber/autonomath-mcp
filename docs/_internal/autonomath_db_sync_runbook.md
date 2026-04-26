# autonomath.db production sync runbook — AutonoMath

Operator-only. Use when the local `autonomath.db` (data 収集 CLI 産出物) needs to be promoted to the Fly volume at `/data/autonomath.db`.

Scope: 8.3 GB SQLite file. Fly app `autonomath-api`, machine `85e273f4e60778` (region nrt), volume `vol_4ojk82zk7xzeqxpr` mounted at `/data` (20 GB total, ~19 GB free at v0.2.0).

Touched in production: `/data/autonomath.db`. Untouched: `/data/jpintel.db` (managed via `DATA_SEED_VERSION` baked seed in `entrypoint.sh`).

---

## When to run

- After a meaningful batch of `data 収集 CLI` writes (rule of thumb: ≥1% row growth in `am_entities`, or new record_kind appears).
- Before a launch milestone (T-7d, T-1d, post-launch weekly).
- After migration (`migration 0XX` that reshapes `am_*` tables).

Frequency target: weekly cron once 1000h cadence stabilises. Until then, manual.

---

## Pre-flight (5 min)

```bash
# 1. Stop any in-flight ingest that writes to autonomath.db.
#    (data 収集 CLI sessions → quit them; cron jobs → comment out the line.)

# 2. WAL checkpoint to consolidate writes into the main DB file.
sqlite3 autonomath.db "PRAGMA wal_checkpoint(TRUNCATE);"

# 3. Take a consistent snapshot to /tmp (cheap APFS clone, ~5s).
cp autonomath.db /tmp/autonomath_snapshot.db
ls -la /tmp/autonomath_snapshot.db
sqlite3 /tmp/autonomath_snapshot.db "PRAGMA integrity_check;" | head -1   # must print 'ok'
sqlite3 /tmp/autonomath_snapshot.db "SELECT COUNT(*) FROM am_entities;"

# 4. Resume local ingest immediately — snapshot is decoupled from the live file.
```

Why snapshot: the data 収集 CLI may be holding a write handle. `cp` of an in-flight WAL DB risks shearing. `wal_checkpoint(TRUNCATE)` then `cp` of just the main file is the safe minimum.

---

## Upload via flyctl ssh sftp put (recommended, ~30–60 min)

`flyctl ssh sftp shell` panics on multi-container container selection (observed 2026-04-25). Use `put` directly with `--machine`.

```bash
# Verify machine ID first — it changes on volume migrations.
flyctl machines list -a autonomath-api

# Upload (foreground; resume strategy = re-run).
flyctl ssh sftp put /tmp/autonomath_snapshot.db /data/autonomath.db \
  -a autonomath-api --machine 85e273f4e60778
```

Notes:

- The Fly tunnel saturates at ~3–5 MB/s outbound from Tokyo office Wi-Fi. 8.3 GB ≈ 30–50 min.
- `flyctl ssh console` (and any other ssh-based check) **fails while sftp is mid-upload** — the tunnel is single-flight per session. Don't poll. Open a second terminal only if you absolutely must.
- If the upload aborts, the partial file at `/data/autonomath.db` is left behind. Delete it (`flyctl ssh console -a autonomath-api -C "rm /data/autonomath.db"`) before re-running.
- Do **not** stop the machine. sftp requires SSH; SSH requires the machine running. Live-write contention is not a concern: the API process opens autonomath.db read-only, and `put` uses a temp+rename style that is atomic from the app's POV when the file is closed by readers (it isn't, but read-only handles tolerate replacement on Linux).

---

## Post-upload verification (5 min)

```bash
# Size + integrity on the volume.
flyctl ssh console -a autonomath-api -C "ls -la /data/autonomath.db"
flyctl ssh console -a autonomath-api -C \
  "sqlite3 /data/autonomath.db 'PRAGMA integrity_check;' | head -1"   # 'ok'

# Row spot-check (compare against local snapshot).
flyctl ssh console -a autonomath-api -C \
  "sqlite3 /data/autonomath.db 'SELECT record_kind, COUNT(*) FROM am_entities GROUP BY record_kind ORDER BY 2 DESC LIMIT 5;'"

# MCP smoke (autonomath_enabled=true required).
flyctl ssh console -a autonomath-api -C \
  "sqlite3 /data/autonomath.db \"SELECT COUNT(*) FROM am_law WHERE law_name LIKE '%租税特別措置法%';\""
```

REST `/v1/am/*` endpoints are **not mounted yet** (see `src/jpintel_mcp/api/main.py` — single-line activation deferred per CLAUDE.md). Smoke against MCP tools or direct sqlite. Once mounted:

```bash
curl https://api.autonomath.ai/v1/am/tax_incentives?q=設備投資&limit=2
curl https://api.autonomath.ai/v1/am/by_law?law=租税特別措置法&limit=2
```

Expect 200 + non-empty `items[]`.

---

## Rollback

There is no in-place rollback once `/data/autonomath.db` is replaced. The previous file is gone. Mitigation:

1. Keep the prior `/tmp/autonomath_snapshot_YYYY-MM-DD.db` for ≥7 days locally.
2. If a regression is observed, re-upload the prior snapshot using the same `put` command. Same downtime budget.

For catastrophic corruption, fall back to `data/jpintel.db`-only mode by setting `AUTONOMATH_ENABLED=false`:

```bash
flyctl secrets set AUTONOMATH_ENABLED=false -a autonomath-api
```

This disables the 17 autonomath MCP tools and (when mounted) the `/v1/am/*` REST routes. Core 38 tools keep serving.

---

## Why not Cloudflare R2 (Option A)

`entrypoint.sh` already supports R2 bootstrap (`AUTONOMATH_DB_URL` + `AUTONOMATH_DB_SHA256`). It is the right answer once we cross either threshold:

- DB ≥ 15 GB (volume headroom < 25%).
- Sync cadence ≥ daily (reproducibility + audit trail matter).

Until then, direct sftp `put` is faster end-to-end (no third-party round-trip, no R2 egress to populate, no SHA bookkeeping). Re-evaluate at v0.3.0.

---

## Cleanup

```bash
rm /tmp/autonomath_snapshot.db   # only after smoke passes
```

Keep one prior snapshot (rename to `/tmp/autonomath_snapshot_$(date +%F).db`) for the 7-day rollback window.
