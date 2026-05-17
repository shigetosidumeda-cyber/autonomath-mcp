# Current SOT 2026-05-17

Generated: 2026-05-17 JST. Non-destructive — `CURRENT_SOT_2026-05-06.md` remains valid as historical-state reference.

## Headline (2026-05-17)
- Wave 50 RC1 LANDED. 7/7 gate. preflight 5/5 READY. scorecard AWS_CANARY_READY. live_aws_commands_allowed=false 150-tick.
- Wave 51 tick 0 closeout: 9/9 dim K-S + L1+L2.
- PERF-1..32 landed. pytest 10,966 / 9.24s.
- Harness H3 (AGENTS.md shrink), H7 (runbook index 33/33), H8 (jpcite resources wired + 30 schemas).

## Runtime Counts
| surface | snapshot |
| --- | ---: |
| MCP tools (mcp-server.json) | 184 |
| inputSchema coverage | 30 / 184 (Harness H8 P1.1) |
| `_meta.resource_count` | 37 |
| `_meta.prompt_count` | 15 |
| MCP resources live | 42 (37 autonomath + 5 mcp://jpcite/*) |
| pytest | 10,966 / 9.24s |
| mypy --strict | 0 |
| ruff | 0 |
| production gate | 7/7 PASS |

## Canonical Pointers
- AGENTS.md (canonical), CLAUDE.md (Claude-shim).
- docs/_internal/WAVE51_plan.md §8 + WAVE52_HINT_2026_05_16.md (execution plan).
- docs/runbook/README.md (33-runbook index).
- docs/_internal/HARNESS_H7_H8_2026_05_17.md (this sweep).
- docs/_internal/REPO_HYGIENE_TRIAGE_2026-05-06.md (still current).
- docs/_internal/AWS_CANARY_INFRA_LIVE_2026_05_16.md (canary state).

## Next packet
- Wave 51 transition via WAVE51_plan.md §8 + WAVE52_HINT.
- AWS canary EventBridge DISABLED until explicit operator wet-run unlock.
- inputSchema residual 154 can be deepened in a future sweep.
