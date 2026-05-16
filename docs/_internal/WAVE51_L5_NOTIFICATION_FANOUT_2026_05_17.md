# Wave 51 L5 — notification_fanout module landed (2026-05-17)

Status: **LANDED — module green**
Lane: `[lane:solo]`
Wave: 51 L5 (third of five AX Layer 6 cron lanes; follows L3
`cross_outcome_routing` + L4 `predictive_merge_daily`)

## Files landed

| Path | Role |
|------|------|
| `src/jpintel_mcp/notification_fanout/__init__.py` | Public surface — 15 re-exports |
| `src/jpintel_mcp/notification_fanout/models.py` | Pydantic envelopes |
| `src/jpintel_mcp/notification_fanout/fanout.py` | Channel registry + planner |
| `tests/test_notification_fanout.py` | 36 tests (>=20 mandated) |

## Channel registry (4 channels supported)

| `DeliveryChannel` | Address shape |
|---|---|
| `email`   | RFC 5322 ASCII address |
| `slack`   | `https://hooks.slack.com/services/...` |
| `webhook` | generic `https://...` URL (no plaintext HTTP) |
| `in_app`  | 32-hex-char session_context token |

Planner only calls `registry.has(channel)`. Runtime adapters call
`registry.get(channel)`. `FakeChannelAdapter` records calls without
I/O.

## Fanout formula

For each event (sorted by `(severity_rank, scheduled_at, event_id)`):
1. SLA gate: drop if `horizon_hours > plan.sla_hours` (24h default).
2. No-target gate: drop if no active matching `ChannelTarget`.
3. Per-target loop: adapter availability + per-channel rate cap.

Defaults: 24h SLA, caps {email: 1000, slack: 500, webhook: 1000,
in_app: 5000}, severity_order {critical: 0, warning: 1, info: 2}.

## 4 defer reasons

- `sla_overflow` — event past SLA window.
- `no_target` — no matching active ChannelTarget row.
- `adapter_unavailable` — channel adapter not in registry.
- `rate_capped` — channel exceeded per-run cap.

## Verification

- pytest: **36 passed**
- mypy --strict: **0 errors**
- ruff: **All checks passed**
- tests/test_no_llm_in_production.py: **10/10 PASS** (CI guard intact)

## Invariants

1. No LLM SDK import.
2. No live HTTP / SMTP / Slack call (planner never invokes adapters).
3. Pure deterministic (run_at mandatory, byte-identical re-runs).
4. Pydantic strict-by-default (extra='forbid' + frozen=True).
5. Append-only contract preserved.

## Cross-reference

- Parent design: `docs/_internal/WAVE51_L3_L4_L5_DESIGN.md`
- L3 sibling: `docs/_internal/WAVE51_L3_CROSS_OUTCOME_ROUTING_2026_05_17.md`
- L4 sibling: `docs/_internal/WAVE51_L4_PREDICTIVE_MERGE_2026_05_17.md`
- Upstream Dim K: `src/jpintel_mcp/predictive_service/`
- Upstream Dim L: `src/jpintel_mcp/session_context/`

## Next (separate landings)

- AX Layer 6 cron + GHA workflow (DISABLED default).
- MCP wrapper tool `schedule_notifications`.
- Production adapters (slack webhook / httpx / session_context writer).
- Remaining L3 lanes: `as_of_snapshot_5y` / `federated_partner_sync`.

last_updated: 2026-05-17
