# R8 Amendment Alert Subscription Feed (2026-05-07)

**Status:** shipped — jpcite v0.3.4
**Owner:** R8 housekeeping audit follow-up
**LLM call:** 0
**Spec ID:** R8_AMENDMENT_ALERT_FEED_2026-05-07

## Why

`am_amendment_diff` carries 12,116 rows of cron-live (since 2026-05-02) per-field
法令改正 / 制度改正 deltas. The legacy `/v1/me/alerts` surface (mig 038)
matches single (filter_type, filter_value) pairs against `am_amendment_snapshot`,
which is a different cadence shape and does not surface "the law that backs my
program just changed" as a primary cohort key.

Tax accountants and 補助金 consultants need a multi-watch feed: one subscription
that watches a list of (program_id, law_id, industry_jsic) entries at once.
That was the missing path between the cron-live diff log and the customer.

## What ships

| Surface | Path | Method | Cost |
| --- | --- | --- | --- |
| Subscribe | `/v1/me/amendment_alerts/subscribe` | POST | FREE |
| Feed | `/v1/me/amendment_alerts/feed` | GET (json / atom) | FREE |
| Unsubscribe | `/v1/me/amendment_alerts/{subscription_id}` | DELETE | FREE |

All three are under `require_key` — anonymous tier 401s. Subscribe + feed +
delete are FREE retention features (no ¥3/req surcharge).
project_autonomath_business_model keeps the unit price immutable; the alert
fan-out cost is ours to absorb.

## Files

- `src/jpintel_mcp/api/amendment_alerts.py` — router (3 endpoints) +
  multi-watch validator + atom renderer + 90-day diff matcher.
- `scripts/migrations/wave24_194_amendment_alert_subscriptions.sql`
  (target_db: jpintel) + companion `*_rollback.sql`.
- `scripts/cron/amendment_alert_fanout.py` — daily fan-out
  (am_amendment_diff × subscription watches → webhook + email).
- `.github/workflows/amendment-alert-fanout-cron.yml` — daily 21:00 UTC
  (06:00 JST), spaced 30min after the legacy amendment-alert-cron.
- `tests/test_amendment_alerts.py` — 13 tests (auth, validation, atom
  format, soft-delete, cron dry-run smoke).
- `src/jpintel_mcp/api/main.py` — added `amendment_alerts_router`
  import + `app.include_router(amendment_alerts_router)`.
- `docs/openapi/v1.json` — regenerated (paths 195 → 198).

## Schema

```sql
CREATE TABLE IF NOT EXISTS amendment_alert_subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id      INTEGER,
    api_key_hash    TEXT NOT NULL,
    watch_json      TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    deactivated_at  TEXT,
    last_fanout_at  TEXT
);
```

`watch_json` is a JSON array of `{type, id}` entries where `type` ∈
`{program_id, law_id, industry_jsic}`. The router enforces:

- `min_length=1`, `max_length=50` per subscription
- no duplicate (type, id) pairs
- per-entry id length 1..200

Indexes:

- `idx_amendment_alert_sub_key` on `(api_key_hash, deactivated_at)` — feed
  hot path.
- `idx_amendment_alert_sub_active` on `(deactivated_at, last_fanout_at)` —
  cron sweep ordering (oldest cursor first).

## Why a new table (not an ALTER on `alert_subscriptions`)

1. Mig 038 schema commits to single (filter_type, filter_value) pairs with a
   CHECK constraint that cannot coexist with multi-watch JSON.
2. The new fan-out cron reads `am_amendment_diff` (per-field deltas) instead
   of `am_amendment_snapshot` — different source ⇒ different subscription
   table avoids cross-cron interference.
3. Decoupling lets the legacy cron and the new cron run on independent
   schedules (05:30 JST vs 06:00 JST) without lock contention.

## Cron behaviour

`scripts/cron/amendment_alert_fanout.py`:

1. Open jpintel.db, read active subscriptions ordered by oldest
   `last_fanout_at` first.
2. For each subscription:
   - Compute scan window floor = max(last_fanout_at, now - 90d). Defaults
     to now - 24h when `last_fanout_at` is NULL. The 90-day cap stops a
     long-dormant subscription from re-delivering the entire backlog.
   - Resolve the watch list against `am_amendment_diff` via three
     OR'd clauses: `entity_id IN (…program_ids…) OR entity_id IN
     (…law_ids…) OR entity_id IN (SELECT entity_id FROM am_entity_facts
     WHERE field_name='industry_jsic' AND value IN (…))`.
   - If hits > 0: build a batched payload and try (a) the customer's first
     active `customer_webhooks` URL, then (b) the api_keys.email column.
     Both attempts are best-effort; failures are logged, never raised.
3. Advance `last_fanout_at` to run-start (NOT now() — that would skip
   diffs detected DURING the run).
4. Emit a JSON summary line for log scraping.

Webhook posture mirrors `amendment_alert.py`: HTTPS-only, 30s timeout, no
RFC1918. Email path uses Postmark template alias `amendment-alert-feed`.

## Honest gaps

- **industry_jsic resolution depends on `am_entity_facts` having
  `field_name='industry_jsic'`** populated for the affected entity. When
  it is not, the diff is silently excluded from the match. The cron logs
  the gap. We do not synthesize coverage.
- **First active customer webhook only.** The cron picks ONE webhook URL
  per delivery to keep fan-out cost flat at O(subscriptions). Customers
  who want N delivery targets register a single dispatcher endpoint and
  fan out themselves.
- **`api_keys.email` may be NULL** on legacy rows (column added in a
  later migration). Email path is silently skipped in that case;
  webhook delivery is the canonical channel.
- **Industry watch attribution in feed response** can only reverse-resolve
  to the FIRST industry watch in the user's list when the row matched
  via the `am_entity_facts` join. Acceptable trade-off vs running a
  per-row reverse lookup.

## Constraints honoured

- LLM call: 0. Pure SQLite + httpx + Pydantic.
- Destructive overwrite: none. New file `amendment_alerts.py`, new
  migration `wave24_194_*`, new cron `amendment_alert_fanout.py`, new
  workflow `amendment-alert-fanout-cron.yml`, new test file
  `test_amendment_alerts.py`. Existing `alerts.py` / `amendment_alert.py`
  / `amendment-alert-cron.yml` untouched.
- Migration `target_db: jpintel` marker on first line — entrypoint.sh §4
  skips it (its glob is autonomath-only). Applied via the standard
  `scripts/migrate.py` jpintel path.
- pre-commit: ruff clean, mypy clean (1 file), 13/13 tests green.

## Verification

```bash
.venv/bin/python -c "from jpintel_mcp.api.main import app; \
  print([r.path for r in app.routes if '/amendment_alerts' in getattr(r, 'path', '')])"
# ['/v1/me/amendment_alerts/subscribe', '/v1/me/amendment_alerts/feed',
#  '/v1/me/amendment_alerts/{subscription_id}']

.venv/bin/python -m pytest tests/test_amendment_alerts.py -x
# 13 passed in 30.74s

.venv/bin/ruff check src/jpintel_mcp/api/amendment_alerts.py \
  scripts/cron/amendment_alert_fanout.py tests/test_amendment_alerts.py
# All checks passed!

.venv/bin/mypy src/jpintel_mcp/api/amendment_alerts.py
# Success: no issues found in 1 source file

grep '"/v1/me/amendment_alerts' docs/openapi/v1.json | wc -l
# 3
```

## OpenAPI delta

`docs/openapi/v1.json` paths: 195 → **198** (+3). Surface count rises
when the manifest is bumped intentionally — this round adds 3 routes
without bumping the MCP tool count (no MCP tool wired for the feed —
it is a pure REST surface).

## Cohort hooks

This surface lights up two of the eight locked cohorts:

- **税理士 (kaikei pack)** — pairs with `client_profiles` (mig 096) +
  `api_keys` parent/child (mig 086): a parent key registers one
  subscription per 顧問先 with a per-client watch list, the daily
  fan-out emits one digest per client.
- **補助金 consultant** — same parent/child pattern; the subscription's
  `watch` array carries the consultant's list of UNI- ids per 顧問先.

No new pricing SKU. No tier UI. Subscribe / feed / delete are zero-touch
self-serve under the existing X-API-Key auth surface.
