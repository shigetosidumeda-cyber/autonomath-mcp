# AutonoMath — Invariant Runbook

Tiered safety invariants. Per dd_v8_05 / v8 P5-θ++ plan.

- **Tier 1** (5 critical, runs on every deploy + on each pytest): see `tests/test_invariants_critical.py`. Failure blocks launch.
- **Tier 2** (13 weekly): runs every Monday 04:00 JST via `scripts/weekly_invariant_check.py`. Failure pages the operator (Sentry + email).
- **Tier 3** (4 monthly): runs first Monday of each month via `scripts/monthly_invariant_review.py`. Advisory only — writes a markdown audit.

## Tier mapping

| Tier | INV IDs | Runner | Failure path |
|------|---------|--------|--------------|
| 1 | INV-04, INV-21, INV-22, INV-23, INV-25 | `pytest tests/test_invariants_critical.py` (on every CI run + on lifespan startup) | Hard fail; deploy aborted |
| 2 | INV-03, INV-04, INV-09, INV-10, INV-18, INV-19, INV-21, INV-23, INV-24, INV-26, INV-27, INV-28, INV-29 | `scripts/weekly_invariant_check.py` (cron, weekly) | Sentry alert + non-zero exit |
| 3 | INV-30, INV-31, INV-32, INV-33 | `scripts/monthly_invariant_review.py` (cron, monthly) | Markdown artifact + operator email |

INV-04/21/23 appear in both Tier 1 and Tier 2 by design — Tier 1 catches the bad state at deploy, Tier 2 re-checks after a week of nightly ingest so a regression that slips through pytest still fires within 7 days.

## Weekly cron — manual run

```bash
.venv/bin/python scripts/weekly_invariant_check.py
# JSON artifact at analysis_wave18/invariant_runs/<YYYY-MM-DD>.json
# Exit 1 if any invariant failed
```

Useful flags:

- `--dry-run` — run probes but skip writing the JSON artifact
- `--json` — also dump the summary to stdout

## Monthly review — manual run

```bash
.venv/bin/python scripts/monthly_invariant_review.py
# Markdown artifact at analysis_wave18/invariant_monthly/<YYYY-MM>.md
# Defaults to the current UTC month; --month YYYY-MM to override
```

## Cron / scheduler setup

### Option A — crontab (simplest, recommended for solo ops)

Edit `crontab -e` on the Fly machine via `fly ssh console -a autonomath-api`, or run on the operator workstation:

```cron
# Weekly Tier 2 check — Monday 04:00 JST = 19:00 UTC Sunday
0 19 * * 0 cd /app && .venv/bin/python scripts/weekly_invariant_check.py >> /var/log/autonomath/weekly_invariant.log 2>&1

# Monthly Tier 3 review — 1st of month, 05:00 JST = 20:00 UTC last day prev month
0 20 1 * * cd /app && .venv/bin/python scripts/monthly_invariant_review.py >> /var/log/autonomath/monthly_invariant.log 2>&1
```

Note: Fly Tokyo machines run UTC by default. Convert JST schedules to UTC before installing.

### Option B — systemd timer (Fly machine, when crontab is not desired)

`/etc/systemd/system/autonomath-weekly-invariant.service`:

```ini
[Unit]
Description=AutonoMath Weekly Invariant Check
After=network-online.target

[Service]
Type=oneshot
User=app
WorkingDirectory=/app
ExecStart=/app/.venv/bin/python /app/scripts/weekly_invariant_check.py
EnvironmentFile=/etc/autonomath/env
StandardOutput=append:/var/log/autonomath/weekly_invariant.log
StandardError=append:/var/log/autonomath/weekly_invariant.log
```

`/etc/systemd/system/autonomath-weekly-invariant.timer`:

```ini
[Unit]
Description=Run AutonoMath Weekly Invariant Check every Monday 04:00 JST

[Timer]
OnCalendar=Sun 19:00:00 UTC
Persistent=true
Unit=autonomath-weekly-invariant.service

[Install]
WantedBy=timers.target
```

Enable: `systemctl enable --now autonomath-weekly-invariant.timer`.

The monthly review uses an analogous pair (`autonomath-monthly-invariant.{service,timer}`) with `OnCalendar=*-*-01 20:00:00 UTC`.

### Option C — GitHub Actions (no infra)

`.github/workflows/weekly-invariant.yml`:

```yaml
name: Weekly invariant check
on:
  schedule:
    - cron: "0 19 * * 0"  # Mon 04:00 JST
  workflow_dispatch:

jobs:
  invariant:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: python scripts/weekly_invariant_check.py
        env:
          SENTRY_DSN: ${{ secrets.SENTRY_DSN }}
      - if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: invariant-run
          path: analysis_wave18/invariant_runs/
```

Failure emails go through GitHub's "send notifications for failed workflows" setting.

## False-positive policy

Goal: < 1% false-positive rate. Thresholds were tuned conservatively:

- **INV-09** (quarantine share) trips at 30% — a healthy DB sits ~3-7%
- **INV-10** (source_fetched_at NULL) trips at 1% — backfilled DB sits at 0
- **INV-19** (5xx rate) trips at 0.5% — healthy prod sits at <0.1%
- Latency invariants (INV-26/27) skip rather than fail on thin telemetry

If a Tier 2 check fires repeatedly with no real regression, raise the skip threshold rather than the fail threshold. Hidden green is worse than a noisy skip.

## On-call response

When the operator gets a Sentry / GitHub alert from a Tier 2 failure:

1. Read the JSON artifact: `analysis_wave18/invariant_runs/<YYYY-MM-DD>.json`
2. Inspect the failed invariant's `measured` block
3. Most failures resolve via:
   - INV-04 / INV-10 — re-run nightly ingest
   - INV-19 — check Sentry for a single bad endpoint
   - INV-09 — re-run tier scoring pass
   - INV-23/24 — code regression in api/billing or a docs PR
4. Re-run the cron manually after fixing: `python scripts/weekly_invariant_check.py`

## Related

- Tier 1 tests: `tests/test_invariants_critical.py`
- Tier 2 tests: `tests/test_invariants_tier2.py`
- Tier 3 tests: `tests/test_invariants_tier3.py`
- Monitoring runbook: `docs/monitoring.md`
- Plan: dd_v8_05 P5-θ++
