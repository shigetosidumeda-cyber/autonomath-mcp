# Staging deploy gotchas

Things that will bite if ignored. Read before the first `flyctl deploy`.

## SQLite on a Fly volume is single-machine

`/data/jpintel.db` lives on one volume attached to one machine. Any attempt
to scale horizontally (`flyctl scale count 2`) will create a second machine
with its OWN empty volume — reads and writes will diverge silently. To scale,
move to Postgres first or adopt LiteFS/WAL streaming. Until then, keep
`min_machines_running = 1` and do not scale count > 1.

### Do not increase `min_machines_running` to 2 without LiteFS first

Audit gap B5 flagged the current `min_machines_running = 1` + rolling deploy
strategy as a 30–60s outage risk on a bad deploy (one machine, in-place
replace). The obvious fix — flip to `2` so rolling can swap one machine at
a time — is **NOT SAFE on the current topology**. Reason: `[[mounts]]` in
`fly.toml` is a single-attach volume (`jpintel_data`). Adding a second
machine either (a) leaves the 2nd with no volume and a read-only empty FS,
or (b) provisions a 2nd empty volume → two writers against two divergent
SQLite files → silent data corruption. Neither is acceptable.

Upgrade path (in order):

1. Adopt LiteFS (primary/replica FUSE layer around SQLite) OR migrate
   `/data/jpintel.db` to Fly Postgres. LiteFS is lower-effort, keeps the
   SQLite code path, and gives a read replica "for free".
2. Verify the 2nd machine is marked `role = "replica"` and has
   `LITEFS_PRIMARY=false` (or equivalent write-guard) so only the leader
   writes.
3. Only then bump `min_machines_running = 2` and budget for the 2nd
   `shared-cpu-1x 256MB` machine (~+$1.9/mo in `nrt`).

Until step 1 is done, the 30–60s blip on a bad deploy is the accepted
trade; mitigate with a pre-deploy `/healthz` + `/readyz` smoke in CI and
fast rollback via `flyctl releases --json | jq` + `flyctl deploy --image
<prev-sha>`.

## Cold starts vs. uptime

`auto_stop_machines = "suspend"` + `min_machines_running = 1` means the
primary stays warm but any over-provisioned replicas suspend. A suspended
machine wakes on incoming HTTP, adding ~300-800ms to the first request. For
an MCP/API product that's acceptable only because `min_machines_running = 1`
keeps the primary hot. Do NOT set `min_machines_running = 0` thinking it
saves money — first request every idle window will stall and fail MCP
handshakes.

## Region + latency

`primary_region = "nrt"` gives ~5-20ms to Japan users and ~120-160ms to US
west coast. Acceptable for both MCP (non-chatty) and REST (single-shot
queries). Do not add a US region without moving DB off SQLite first.

## Filesystem is ephemeral outside `/data`

Anything written under `/app`, `/tmp`, etc. is lost on machine restart. This
includes logs — never write logs to disk; structlog already goes to stdout,
which Fly ingests. If you add Python `logging.FileHandler` somewhere, it
will silently vanish.

## Stripe webhook secret is PER ENDPOINT

`STRIPE_WEBHOOK_SECRET` for staging is generated when you create the
staging webhook endpoint in the Stripe dashboard. It is NOT the same as
prod's. Using prod's `whsec_*` on staging (or vice versa) will cause every
webhook to 400 with "signature mismatch". Keep them in separate Fly apps
(`jpintel-mcp` and `jpintel-mcp-staging`) OR separate Fly secrets scopes.

## `sentry-sdk` is not in `pyproject.toml`

`src/jpintel_mcp/api/main.py` imports `sentry_sdk` inside a try/except, so
if the package is missing the app starts but Sentry silently no-ops — you
lose observability without any warning. The Dockerfile installs it
explicitly at build time (`pip install "sentry-sdk[fastapi]==2.19.0"`) to
plug this hole. When pyproject is next editable, add
`sentry-sdk[fastapi]>=2.19` to `dependencies` and drop the explicit install.

## CORS default is dev-only

`JPINTEL_CORS_ORIGINS` defaults to `http://localhost:3000`. If you forget to
override it on Fly, every browser call from the staging frontend fails
preflight. Always set it via `flyctl secrets set`.

## `release_command` blocks the deploy

`python scripts/migrate.py` runs in a one-shot machine before traffic
shifts. If it errors, the deploy aborts with the new image never going live
— good for safety, bad if the error is a migration bug at 23:00 JST. Dry
run locally first: `JPINTEL_DB_PATH=/tmp/test.db python scripts/migrate.py --dry-run`.

## DB size vs. volume size

Current local DB is ~144 MB. Fly volume is provisioned at 1 GB. Growth
headroom is ~6x before resize is needed. Monitor with `flyctl ssh console
-C "du -sh /data"`. Resize with `flyctl volumes extend <id> --size 5`.

## Backups must go OFF the machine

`/data/backups/` on the same volume does NOT survive volume loss.
`scripts/backup.md` Option 2 (GitHub Actions → Fly SSH → R2) is the
intended path. Option 1 (on-machine systemd timer) is labeled as a
stopgap for a reason.

## Production seed gate must accept `programs` OR `jpi_programs`

Do not gate production deploys on `programs > 10000` alone while the catalog is
transitioning. The current observed production DB shape for the 2026-05-06 WAF
/ deploy handoff is `programs=0` and `jpi_programs=13578`; a `programs`-only
sentinel rejects a usable seed. The GitHub deploy gate should require:

```text
max(count(programs), count(jpi_programs)) >= 10000
```

Keep the post-deploy search smoke as a separate hard gate because it proves
the served `/v1/programs/search` path still returns results.

## Kill-switch smoke uses the API host

Production kill-switch and hard-gate smoke must use
`BASE_URL=https://api.jpcite.com`. The apex `https://jpcite.com` is the
public/docs surface and can remain green even when the API origin is unhealthy.
