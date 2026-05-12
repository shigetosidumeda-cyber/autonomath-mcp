# Wave 47 — Dim G (realtime_signal subscriber + event_log) migration PR — STATE

- **Date**: 2026-05-12 (Wave 47 永遠ループ Phase 2 tick#7)
- **Dim**: G — realtime_signal subscriber + dispatcher (Wave 47 booster layer)
- **Branch**: `feat/jpcite_2026_05_12_wave47_dim_g_migration`
- **Worktree**: `/tmp/jpcite-w47-dim-g-mig` (lane claim: `/tmp/jpcite-w47-dim-g-mig.lane`)
- **Base**: `origin/main` @ `a557569f7` (PR #168 dim S merged)
- **PR**: filled at push time

## Purpose

Wave 47 layer-on for the Dim G "realtime_signal" surface. Migration 263
(Wave 43.2.7) already shipped `am_realtime_subscribers` +
`am_realtime_dispatch_history` with a per-(subscriber, target_kind,
signal_id) UNIQUE attempt log. Wave 47 adds a SECOND, signal-types-driven
write shape that supports webhook fan-out: a single contract that fires on
ANY of N signal types. Adds the actual delivery pipeline (dispatcher ETL +
event log) that the existing v2 REST API did not yet have a write-shape
for. Co-exists additively with the Wave 43 base; both can be queried in
parallel while customers migrate at their own pace.

## Files (4 new + 2 manifest edits + 1 STATE doc)

| Path | LOC | Role |
| ---- | --- | ---- |
| `scripts/migrations/286_realtime_signal.sql` | 102 | schema (subscriber + event_log + helper view) |
| `scripts/migrations/286_realtime_signal_rollback.sql` | 23 | rollback drops Wave 47 layer only |
| `scripts/etl/dispatch_realtime_signals.py` | 261 | pending event → webhook delivery, NO LLM |
| `tests/test_dim_g_realtime.py` | 372 | 17 cases (mig + checks + dispatcher + LLM-0 guard) |
| `scripts/migrations/jpcite_boot_manifest.txt` | +14 | register 286 |
| `scripts/migrations/autonomath_boot_manifest.txt` | +14 | register 286 mirror |
| `docs/research/wave46/STATE_w47_dim_g_pr.md` | this doc | tick#7 state |

## Schema (migration 286)

- `am_realtime_signal_subscriber` (PK=`subscriber_id` INTEGER AUTOINCREMENT)
  - `webhook_url` UNIQUE (length 12..512, https-only CHECK)
  - `signal_types` JSON-array TEXT (DEFAULT `'[]'`, CHECK `json_valid`, cap 4096)
  - `enabled` BOOLEAN (0/1)
  - `last_signal_at` (NULL until first 2xx delivery)
  - `created_at`, `updated_at`
  - Indexes: `enabled+subscriber_id`, `last_signal_at DESC`
- `am_realtime_signal_event_log` (PK=`event_id` INTEGER AUTOINCREMENT)
  - `subscriber_id` (soft FK)
  - `signal_type` (length 1..64 CHECK)
  - `payload` JSON TEXT (cap 8192, CHECK `json_valid`)
  - `status_code` (NULL while pending, HTTP 2xx/4xx/5xx after attempt)
  - `attempt_count` (DEFAULT 1, CHECK >= 1)
  - `error` (last error string, truncated to 256 chars)
  - `delivered_at` (NULL while pending, ISO8601 string after 2xx)
  - `created_at`
  - Indexes: `subscriber+created DESC`, `signal_type+created DESC`,
    partial `delivered_at IS NULL` (pending queue),
    partial `delivered_at IS NOT NULL` (billing reconcile scan)
- `v_realtime_signal_subscriber_enabled` helper view (enabled rows, sorted by subscriber_id)

## Why a parallel layer instead of extending 263

263 modeled one subscription per `target_kind` (with a filter_json
discriminator inside the same row). Wave 47 customers ask for fan-out: a
single webhook contract that fires on ANY of N signal types. Extending 263
in place would require a destructive DDL rewrite (CHECK constraint shape
change). A parallel layer is additive only and lets both subscriber models
co-exist while customers migrate at their own pace. The v2 REST surface
(`src/jpintel_mcp/api/realtime_signal_v2.py`, untouched here) keeps
serving the Wave 43 schema; a future PR can dual-write to the Wave 47
tables once we are ready to flip clients.

## Delivery design (`dispatch_realtime_signals.py`)

```
+----------------------------------------+
| am_realtime_signal_event_log           |   pending events (delivered_at IS NULL)
| WHERE delivered_at IS NULL             |
| JOIN am_realtime_signal_subscriber     |
|      s.enabled = 1                     |
+----------------------------------------+
                 |
                 v
 +------------------------------------+
 | _http_post(webhook_url, body, 5s)  |    plain urllib.request, NO LLM SDK
 +------------------------------------+
                 |
        +--------+--------+
        |                 |
   200..299           anything else
        |                 |
        v                 v
 mark delivered    attempt_count++
 +last_signal_at   +status_code
                   +error (cap 256 chars)
```

Envelope shape:

```json
{
  "schema": "jpcite.realtime_signal.v1",
  "event_id": 42,
  "subscriber_id": 7,
  "signal_type": "kokkai_bill",
  "attempt": 1,
  "payload": { "...source-specific..." }
}
```

Headers: `Content-Type: application/json`,
`User-Agent: jpcite-realtime-signal-dispatcher/1 (+https://jpcite.ai)`.
Timeout: 5 s/request default (CLI `--timeout`).

`post_fn` is injectable for testing — no monkeypatching of
`urllib.request.urlopen` needed; the dim G test injects a fake to assert
2xx delivers, non-2xx fails, dry-run skips, disabled subscriber skips.

## Pricing posture

One 2xx delivery row in `am_realtime_signal_event_log` = one ¥3 billable
unit (post-launch metering ingests via partial index
`idx_am_rt_sig_event_delivered`). Pre-delivery rows (`delivered_at IS NULL`)
and retry rows DO appear in the table but DO NOT count toward billing —
the reconciliation cron filters on `delivered_at IS NOT NULL AND status_code
BETWEEN 200 AND 299`.

## LLM-0 verify

```
$ grep -E "anthropic|openai" scripts/etl/dispatch_realtime_signals.py
# 0 hits (guarded by test_no_llm_import_in_new_files in test_dim_g_realtime.py)
```

Pure `urllib.request.urlopen` + `sqlite3` + `json`. No third-party SDK at
all (no `httpx`, no `requests`, no Anthropic, no OpenAI). Per
`feedback_no_operator_llm_api`.

## Local verify

```
$ cd /tmp/jpcite-w47-dim-g-mig
$ /Users/shigetoumeda/jpcite/.venv/bin/python -m pytest tests/test_dim_g_realtime.py -x -v
... 17 passed in 1.16s ...

$ /Users/shigetoumeda/jpcite/.venv/bin/python -m ruff check \
      scripts/etl/dispatch_realtime_signals.py tests/test_dim_g_realtime.py
All checks passed!
```

Test cases (all PASSED):

1. `test_mig_286_applies_clean` — fresh DB has subscriber + event_log + view
2. `test_mig_286_is_idempotent` — second `executescript` is a noop
3. `test_mig_286_rollback_drops_all` — rollback leaves zero Wave 47 objects
4. `test_check_webhook_url_https_only` — http:// rejected
5. `test_check_webhook_url_min_length` — `https://x` rejected (length 9 < 12)
6. `test_check_signal_types_must_be_json` — `'not-json'` rejected
7. `test_check_event_signal_type_not_empty` — empty signal_type rejected
8. `test_check_event_payload_must_be_json` — malformed payload rejected
9. `test_dispatcher_delivers_2xx` — 200 marks delivered_at + last_signal_at
10. `test_dispatcher_records_failure` — 503 attempt_count→2 + error captured
11. `test_dispatcher_dry_run_writes_nothing` — no network, no DB mutation
12. `test_dispatcher_skips_disabled_subscriber` — disabled subscriber → 0 attempts
13. `test_dispatcher_cli_dry_run` — `python dispatch_realtime_signals.py --dry-run` JSON
14. `test_manifest_jpcite_lists_286` — jpcite manifest registers 286
15. `test_manifest_autonomath_lists_286` — autonomath mirror manifest registers 286
16. `test_no_llm_import_in_new_files` — grep anthropic|openai = 0
17. `test_no_legacy_brand_in_new_files` — grep 税務会計AI|zeimu-kaikei.ai = 0

## Anti-pattern guards (per memory)

- **dual-CLI lane atomic** — claimed via `mkdir /tmp/jpcite-w47-dim-g-mig.lane`,
  AGENT_LEDGER append-only. Worktree at `/tmp/jpcite-w47-dim-g-mig`, never
  main worktree.
- **既存 PR 上書き禁止** — touches NO existing migration files, NO existing
  cron files. Only adds new 286 + new dispatch_realtime_signals.py +
  appends to manifests + adds STATE doc + new test file.
- **rm/mv 禁止** — no destructive operations.
- **legacy brand banned** — zero `税務会計AI` / `zeimu-kaikei.ai` in new files
  (test enforces).
- **LLM API 全禁** — dispatcher uses `urllib.request` only (test enforces).

## Push + PR plan

```
git add scripts/migrations/286_realtime_signal.sql \
        scripts/migrations/286_realtime_signal_rollback.sql \
        scripts/etl/dispatch_realtime_signals.py \
        tests/test_dim_g_realtime.py \
        scripts/migrations/jpcite_boot_manifest.txt \
        scripts/migrations/autonomath_boot_manifest.txt \
        docs/research/wave46/STATE_w47_dim_g_pr.md
git commit -m "feat(wave47-dim-g): realtime_signal subscriber + dispatcher (mig 286)"
git push -u origin HEAD
gh pr create --title "feat(wave47-dim-g): realtime_signal subscriber + dispatcher (mig 286)" \
             --body  "(see STATE_w47_dim_g_pr.md)"
```
