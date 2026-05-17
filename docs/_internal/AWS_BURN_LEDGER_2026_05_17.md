# AWS Burn Ledger — Lane J (2026-05-17)

Append-only burn-rate ticks for jpcite credit run. Read-only against AWS.
Cadence: 1 tick / hour via EventBridge `jpcite-credit-burn-monitor-hourly`.
Target band: $2,000-$3,000/day × 7 days. Hard-stop $18,900 / Never-reach $19,490.

Each entry: JSON block + state markers (OVER_BUDGET / UNDER_PACE / OFF_TARGET / ON_TARGET).

---

## tick 2026-05-17T01:10:55Z — UNDER_PACE

- burn 24h: $270.22/day
- credit remaining: $16,388.20 / $19,490 never-reach
- projection: exhaust 2026-07-16 (60.6 days from now)
- reason: burn $270.22/day < $1,500/day (credit will not exhaust)

```json
{
  "ts": "2026-05-17T01:10:55Z",
  "window_24h": {
    "start": "2026-05-16",
    "end": "2026-05-17"
  },
  "usage_24h_usd": 270.22,
  "usage_today_partial_usd": 0.0,
  "usage_mtd_usd": 3101.92,
  "credit_applied_mtd_usd": 3101.8,
  "credit_remaining_usd": 16388.2,
  "burn_per_day_usd": 270.22,
  "burn_band_target": {
    "lo": 2000.0,
    "hi": 3000.0
  },
  "burn_band_alert": {
    "lo": 1500.0,
    "hi": 3500.0
  },
  "state": "UNDER_PACE",
  "reason": "burn $270.22/day < $1,500/day (credit will not exhaust)",
  "projection_exhaust": "2026-07-16 (60.6 days from now)",
  "credit_never_reach_usd": 19490.0,
  "credit_hard_stop_usd": 18900.0,
  "delta_vs_prev_tick_usd_per_hour": null,
  "ce_lag_disclaimer": "Cost Explorer carries 24-48h lag; today's partial figure under-represents real spend. Trust 24h rolling band only."
}
```
