# invoice_registrants — full-population bulk ingest runbook

Internal-only. Operator: Bookyou株式会社 (info@bookyou.net).

## Why this runbook exists

`/v1/invoice_registrants/{T...}` only mirrors a delta-only ~14k-row slice of
the ~4M-row 適格請求書発行事業者 universe at launch (2026-05-06). H8
audience walk surfaced that a Bookyou self-lookup (T8010001213708) returns
404 — that is correct behaviour given the partial mirror, but it reads as
"this service is broken" to a first-time evaluator hitting their own
法人番号. The endpoint now returns an enriched 404 body that points the
caller at NTA's official lookup as the immediate fallback (see
`src/jpintel_mcp/api/invoice_registrants.py`, the `get_invoice_registrant`
handler, and the contract test `tests/test_invoice_registrants_404.py`).

The longer-term fix — full population coverage — is the monthly bulk
ingest documented below. **Schedule: T+30d post-launch (≈2026-06-05)**.
Doing this on launch day is explicitly out of scope: the launch CLI is
running ¥3/req traffic and a 4M-row UPSERT during that window risks WAL
checkpoint stalls on the writer lock.

## Source contract

- URL base: `https://www.invoice-kohyo.nta.go.jp/download/`
- License: **公共データ利用規約 第1.0版 (PDL v1.0)**. Commercial
  redistribution + downstream API exposure permitted provided each
  rendered surface carries (a) 出典明記 and (b) 編集・加工注記. Both
  are emitted by `src/jpintel_mcp/api/invoice_registrants.py:_ATTRIBUTION`
  on every 2xx and the enriched 404.
- Data shape: corporation + sole_proprietor + other rows; ~4M total;
  monthly full snapshot + daily delta.
- Format options: CSV / XML / JSON. Existing ingest (`scripts/ingest/
  ingest_invoice_registrants.py`) accepts all three; CSV is the default.
- File size: ~500MB compressed (≈2GB uncompressed CSV) for the full
  monthly snapshot. Delta files are ~1–10MB.
- TOS gotcha: the **web-UI 検索 form is scrape-banned** by a separate
  TOS layer. Bulk-download-only path. Never hit the search UI from
  automation.

## Why we are NOT doing this at launch

1. WAL checkpoint risk. The writer lock is held in tens-of-second
   windows during chunked UPSERT; metered traffic readers can starve.
2. Disk pressure. `data/jpintel.db` grows from 188MB → ~600MB once the
   4M rows + their indexes land. Fly.io volume needs a `fly volume
   extend` before the first run, not after.
3. Storage cost. The full population grows the FTS-less mirror by
   ~3.2x. We confirmed the expansion is acceptable but it is a one-way
   commit — verify post-launch billing curve first.
4. Privacy guardrail. Sole-proprietor rows are personal data under
   NTA's own consent model. We have to publish a privacy / takedown
   path on `zeimu-kaikei.ai` **before** the full mirror lands; that work
   is launch-week-blocked because of the freeze.

## T+30d ingest procedure

Target window: weekend, JST 03:00–06:00 (lowest /v1 traffic per the
2026-04-25 perf baseline).

### Pre-flight

```bash
# 1. Confirm Fly volume has 1.5GB+ headroom
fly ssh console -C "df -h /data"

# 2. Snapshot the current DB so a bad UPSERT round-trip is reversible
fly ssh console -C "cp /data/jpintel.db /data/jpintel.db.bak.pre_inv_full_$(date +%Y%m%d)"

# 3. Confirm the ingest script is on the prod image
fly ssh console -C "ls /app/scripts/ingest/ingest_invoice_registrants.py"

# 4. Dry-run locally first against a fresh download (no DB writes)
.venv/bin/python scripts/ingest/ingest_invoice_registrants.py \
    --db data/jpintel.db \
    --mode full \
    --format csv \
    --dry-run \
    --limit 100000
```

### Production ingest

```bash
# 5. Run the full ingest against the prod volume. ~30–60 min on Fly's
#    shared-cpu-1x; consider scaling to dedicated-cpu-2x for the window.
fly ssh console -C "\
    cd /app && python scripts/ingest/ingest_invoice_registrants.py \
        --db /data/jpintel.db \
        --mode full \
        --format csv \
        --batch-size 5000 \
"

# 6. Verify row count landed (~4M ± a few percent week to week)
fly ssh console -C "sqlite3 /data/jpintel.db 'SELECT COUNT(*) FROM invoice_registrants;'"

# 7. Spot-check Bookyou's own row (the H8-walk regression target)
fly ssh console -C "sqlite3 /data/jpintel.db \"\
    SELECT invoice_registration_number, normalized_name, registered_date \
    FROM invoice_registrants \
    WHERE invoice_registration_number='T8010001213708';\""

# 8. Hit the live endpoint as a final check
curl -sS https://api.zeimu-kaikei.ai/v1/invoice_registrants/T8010001213708 | jq .
```

### Post-flight

- Update `CLAUDE.md` row count from `13,801 invoice_registrants` to the
  new full-population number (round to nearest 10k).
- Bump CHANGELOG.md with the date the full mirror landed.
- Update `_NEXT_BULK_REFRESH_HINT` in
  `src/jpintel_mcp/api/invoice_registrants.py` from
  "post-launch monthly (see operator runbook)" to the next scheduled
  delta run date.
- Drop the pre_inv_full_* backup after 7 days of clean traffic.

## Recurring schedule

- **Monthly full**: first weekend of each month, 03:00–06:00 JST.
- **Daily delta**: 04:00 JST cron from T+30d onward. Delta files are
  small (~1–10MB) so the WAL checkpoint risk is minimal; can run during
  business hours if needed but the cron stays off-peak.
- The existing `scripts/ingest/ingest_invoice_registrants.py` already
  supports `--mode delta`; wire it into the cron via
  `scripts/cron/precompute_refresh.py` (or a new top-level cron entry —
  precompute_refresh.py is the precompute window, not the ingest one).

## Failure modes & rollback

- **Partial UPSERT**: ingest is idempotent on
  `invoice_registration_number` PK. Re-run safely.
- **Corrupt download**: ingest exits with code 2 if reject rate >5%.
  Investigate the source file; do not retry against the same artifact.
- **Disk full mid-run**: `fly volume extend` first, then re-run from
  scratch. Partial writes are OK because of UPSERT idempotency.
- **Schema drift**: ingest exits with code 3. Run
  `scripts/migrate.py` to bring schema current, then re-run ingest.
- **Worst case rollback**: stop API, copy back the pre-ingest backup
  (`fly ssh console -C "cp /data/jpintel.db.bak.pre_inv_full_* /data/jpintel.db"`),
  restart API. Endpoint reverts to delta-only mirror behaviour.

## Open issues to revisit before T+30d

- [ ] Privacy / takedown landing page on zeimu-kaikei.ai for
      sole-proprietor rows under NTA's consent model.
- [ ] Fly volume extension PR (currently 3GB, needs ≥6GB headroom).
- [ ] Decide whether the `am_entities` mirror in `autonomath.db` (currently
      13.8k invoice_registrant rows) also expands to 4M, or stays as a
      delta-only sample. Coordinate with autonomath ingest CLI.
- [ ] FTS5 trigram on `normalized_name`: schema is currently no-FTS by
      design (4M-row trigram doubles disk). Re-evaluate after live
      query telemetry shows whether prefix LIKE is hitting its limits.
