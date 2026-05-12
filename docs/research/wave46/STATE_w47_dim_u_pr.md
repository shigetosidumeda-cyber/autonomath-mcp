# Wave 47 — Dim U (Agent Credit Wallet) migration PR — STATE

- **Date**: 2026-05-12 (Wave 47 Phase 2 永遠ループ tick#7)
- **Dim**: U — Agent Credit Wallet (per `feedback_agent_credit_wallet_design`)
- **Branch**: `feat/jpcite_2026_05_12_wave47_dim_u_migration`
- **Worktree**: `/tmp/jpcite-w47-dim-u-mig` (lane claim: `/tmp/jpcite-w47-dim-u-mig.lane`)
- **Base**: `origin/main` @ `a557569f7`
- **PR**: filled at push time

## Purpose

Storage substrate for the Dim U "Agent Credit Wallet" surface backing
the ¥3/req call rail. Designed for CFO/CIO budget-predictability:

- **Pre-payment** (balance_yen prevents unbounded LLM-side spend)
- **Auto-topup** (auto_topup_threshold + auto_topup_amount)
- **Spending alert at 50% / 80% / 100%** of monthly_budget_yen

Per `feedback_agent_credit_wallet_design`. **No LLM API call**
operator-side (per `feedback_no_operator_llm_api`); the ETL is pure
SQL aggregation + threshold evaluation.

## Files (4 new + 2 manifest edits)

| Path | LOC | Role |
| ---- | --- | ---- |
| `scripts/migrations/281_credit_wallet.sql` | 119 | schema (3 tables + 1 view) |
| `scripts/migrations/281_credit_wallet_rollback.sql` | 26 | rollback (drops only Dim U surface) |
| `scripts/etl/process_credit_wallet_alerts.py` | 168 | hourly cron — 50/80/100 pct firing |
| `tests/test_dim_u_credit_wallet.py` | 357 | 24 cases (mig + ETL + thresholds + LLM-0) |
| `scripts/migrations/jpcite_boot_manifest.txt` | +14 | register 281 |
| `scripts/migrations/autonomath_boot_manifest.txt` | +14 | register 281 mirror |

## Schema (migration 281)

### `am_credit_wallet`
One row per agent owner (token-hashed via sha256, raw never stored).

| Column | Type | Notes |
| ------ | ---- | ----- |
| `wallet_id` | INTEGER PK AUTOINCREMENT | |
| `owner_token_hash` | TEXT NOT NULL | UNIQUE, sha256 hex (length=64) |
| `balance_yen` | INTEGER NOT NULL DEFAULT 0 | >= 0 CHECK |
| `auto_topup_threshold` | INTEGER NOT NULL DEFAULT 0 | trigger threshold (¥) |
| `auto_topup_amount` | INTEGER NOT NULL DEFAULT 0 | top-up size (¥) |
| `monthly_budget_yen` | INTEGER NOT NULL DEFAULT 0 | soft cap for alerts (0 = disabled) |
| `enabled` | INTEGER NOT NULL DEFAULT 1 | 0/1 CHECK |
| `created_at`, `updated_at` | TEXT NOT NULL | ISO8601 strftime default |

### `am_credit_transaction_log` (append-only ledger)

| Column | Type | Notes |
| ------ | ---- | ----- |
| `txn_id` | INTEGER PK AUTOINCREMENT | |
| `wallet_id` | INTEGER NOT NULL | FK -> am_credit_wallet(wallet_id) |
| `amount_yen` | INTEGER NOT NULL | sign-rule CHECK |
| `txn_type` | TEXT NOT NULL | enum: topup \| charge \| refund |
| `occurred_at` | TEXT NOT NULL | ISO8601 strftime default |
| `note` | TEXT | optional human note |

**Sign-rule CHECK**:
- `topup` → amount_yen > 0
- `refund` → amount_yen > 0
- `charge` → amount_yen < 0

### `am_credit_spending_alert`

| Column | Type | Notes |
| ------ | ---- | ----- |
| `alert_id` | INTEGER PK AUTOINCREMENT | |
| `wallet_id` | INTEGER NOT NULL | FK -> am_credit_wallet(wallet_id) |
| `threshold_pct` | INTEGER NOT NULL | enum: 50 \| 80 \| 100 |
| `billing_cycle` | TEXT NOT NULL | 'YYYY-MM' (length=7) |
| `fired_at` | TEXT NOT NULL | ISO8601 strftime default |
| `spent_yen`, `budget_yen` | INTEGER NOT NULL | snapshot at firing |

**UNIQUE (wallet_id, threshold_pct, billing_cycle)** — guarantees a
single alert per threshold per cycle. The ETL relies on this for
natural idempotency (INSERT OR IGNORE pattern).

### `v_credit_wallet_topup_due` (helper view)

Wallets where `enabled = 1` AND `auto_topup_threshold > 0` AND
`auto_topup_amount > 0` AND `balance_yen < auto_topup_threshold`.
Used by a downstream operator script (out of scope for this PR) to
trigger Stripe top-up charges.

## ETL `process_credit_wallet_alerts.py` (hourly)

For each `enabled = 1` wallet with `monthly_budget_yen > 0`:
1. Compute `spent_yen` = |Σ charge.amount_yen WHERE substr(occurred_at,1,7) = cycle|.
2. Compute `pct = spent * 100 / budget`.
3. For each threshold in (50, 80, 100):
   - If `pct >= threshold`, attempt `INSERT OR IGNORE INTO am_credit_spending_alert`.
   - New rowcount = 1 → alert just fired; emit in JSON report.
   - Duplicate (already fired this cycle) → skip silently.
4. `--cycle YYYY-MM` overrides the current UTC month bucket.
5. `--dry-run` reports what would fire without writing.

Re-running within the same cycle = no-op (UNIQUE constraint).
In the next cycle, fresh alerts fire because `billing_cycle` differs.

## 3-threshold smoke (verified offline)

```
WALLET budget=¥10,000, charge=¥12,000 (120%), cycle=2026-05
ETL run → alerts_fired = [
  {threshold_pct: 50, spent: 12000, budget: 10000},
  {threshold_pct: 80, spent: 12000, budget: 10000},
  {threshold_pct: 100, spent: 12000, budget: 10000}
]
ETL re-run (same cycle) → alerts_fired = []   # idempotent
```

## Test plan — 24 cases (all green via `pytest`)

1. mig applies + idempotent re-apply (2)
2. rollback drops all artefacts (1)
3. CHECK constraint guards: owner_token_hash length, balance>=0,
   txn_type enum, txn sign-rule (topup-neg / charge-pos rejected),
   threshold_pct enum (25 rejected), billing_cycle length (6 rejected) (6)
4. UNIQUE constraints: owner_token_hash, (wallet,threshold,cycle) (2)
5. ETL threshold firing: 50% only, 50+80, 50+80+100, idempotent,
   re-fires in next cycle, dry-run, disabled wallet skipped, no-budget skipped (8)
6. helper view: includes low-balance enabled, excludes high / disabled (1)
7. boot manifest: jpcite + autonomath both list 281 (2)
8. LLM-0: no `anthropic|openai|google.generativeai` import in any new
   file. legacy brand (`税務会計AI` / `zeimu-kaikei.ai`) = 0 (2)

```
$ pytest tests/test_dim_u_credit_wallet.py -x -q
........................                                                 [100%]
24 passed in 2.24s
```

## Constraints respected (per task spec)

- **No Stripe Portal overwrite** — Dim U is a parallel ledger; Stripe
  Portal stays the human-CRM rail. Programmatic call billing reads
  from the wallet, not Stripe.
- **No main worktree** — branch created in
  `/tmp/jpcite-w47-dim-u-mig` worktree off `origin/main`.
- **No rm / mv** — only additive writes (4 new files + 2 manifest
  appends, no deletes).
- **No legacy brand** — `税務会計AI` / `zeimu-kaikei.ai` not present.
- **No LLM API** — pure SQL ETL, no `import anthropic` / `import openai`.

## Memory references

- `feedback_dual_cli_lane_atomic` (lane mkdir + worktree mkdir)
- `feedback_agent_credit_wallet_design` (50/80/100 + auto-topup)
- `feedback_no_operator_llm_api` (ETL LLM-0)
- `feedback_destruction_free_organization` (additive only)

## Post-merge follow-ups (out of scope for this PR)

- REST `/credit/wallet` GET (balance + recent transactions)
- REST `/credit/topup` POST (Stripe payment intent → topup txn)
- MCP tool `credit_wallet_status` for agents to introspect balance
- Cron workflow `credit-wallet-alerts-hourly.yml` (calls the ETL)
- Telegram/Slack hook on alert firing (out-of-band ops alert)
