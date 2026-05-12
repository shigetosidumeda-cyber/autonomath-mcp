# Wave 47 — Dim W (AX Layer 3) migration PR — STATE

- **Date**: 2026-05-12 (Wave 47 Phase 2 永遠ループ tick#4)
- **Dim**: W — AX Layer 3 (WebMCP + A2A + Observability) per `feedback_ax_4_pillars`
- **Branch**: `feat/jpcite_2026_05_12_wave47_dim_w_migration`
- **Worktree**: `/tmp/jpcite-w47-dim-w-mig` (lane claim: `/tmp/jpcite-w47-dim-w-mig.lane`)
- **Base**: `origin/main` @ `cd5b7bbfb`
- **PR**: filled at push time

## Purpose

Storage substrate + 3-axis seed ETL for the Dim W "AX Layer 3" surface
— the third (and final) pillar of the AX 4-pillars framework per
`feedback_ax_4_pillars`. Layers 1+2 (Access / Context / Tools /
Orchestration discovery + metadata) are already complete; Layer 3
(WebMCP transports + A2A handshakes + Observability metrics) was the
only remaining pillar without a persistent substrate.

Three independent axes captured by three small tables:

- `am_webmcp_endpoint` — registry of WebMCP transport endpoints
  advertised by jpcite (HTTP transport variant of MCP for browser /
  in-page agent embeds). One row per (path, transport) with capability
  tag binding it to an AX pillar.
- `am_a2a_handshake_log` — append-only audit of agent-to-agent
  handshake attempts (capability negotiation). Drives the AX funnel
  "Trustability" rollup and debugs interop with partner agents.
- `am_observability_metric` — append-only metric stream (Layer 3
  observability piece). Pairs `metric_name + value + recorded_at`;
  downstream rollups read this for AX-Layer-3 dashboards.

**LLM-0 by construction** (per `feedback_no_operator_llm_api`): schema
is config + audit metadata only. ZERO columns imply LLM inference (no
`summary_text`, no `ai_explanation`). The handshake log records WHAT
was negotiated, not WHY. All natural-language explanation is rendered
customer-side by the customer's own agent.

## Deliverables

- **`scripts/migrations/283_ax_layer3.sql`** (~145 LOC including
  docstring): three tables + 5 indexes + 1 UNIQUE backstop + 2 helper
  views (`v_webmcp_endpoint_active`, `v_observability_recent`). All
  CHECK constraints enumerated (transport enum, capability_tag enum,
  path-must-be-rooted, handshake exclusive state CHECK, temporal
  ordering CHECK on `succeeded_at >= initiated_at`).
- **`scripts/migrations/283_ax_layer3_rollback.sql`** (~25 LOC): drops
  every table / index / view created.
- **`scripts/etl/seed_ax_layer3.py`** (~205 LOC): seeds 3 WebMCP
  endpoints + 2 A2A handshake templates + 8 observability metrics on a
  fresh autonomath.db. Idempotent under daily re-run (UNIQUE +
  date-of-day dedup); `--force` re-appends audit rows.
- **`tests/test_dim_w_ax_layer3.py`** (~310 LOC): 20 tests covering
  apply / idempotency / rollback / 7 CHECK constraints / ETL dry-run /
  apply-then-idempotent / `--force` audit append / both helper views /
  boot manifest registration in jpcite + autonomath mirror / LLM-0
  grep / brand hygiene grep / no LLM-coupled columns in schema.
- **Boot manifest entries** appended to BOTH
  `scripts/migrations/jpcite_boot_manifest.txt` and
  `scripts/migrations/autonomath_boot_manifest.txt` with full
  rationale block (transport enum + capability tag + handshake exclusive
  state + LLM-0 by construction + ¥3/req posture).

## 3-axis seed contents

### `am_webmcp_endpoint` (3 endpoints)
- `/v1/mcp/sse` × sse × tools — default MCP 2025-06-18 browser transport.
- `/v1/mcp/sse/health` × sse × access — transport liveness probe.
- `/v1/mcp/streamable_http` × streamable_http × tools — Wave 16 A8 long-poll fallback.

### `am_a2a_handshake_log` (2 templates, succeeded_at set)
- claude-3.5-sonnet → jpcite-mcp negotiating `tools/search_programs`.
- cursor-mcp-client → jpcite-mcp negotiating `resources/list`.

### `am_observability_metric` (8 seed metrics)
- 4 Layer-3-specific: `webmcp.endpoints_active`, `a2a.handshakes_total`,
  `a2a.handshake_success_rate`, `observability.metrics_emitted`.
- 4 AX pillar surface counts: `access.surfaces_active=12`,
  `context.surfaces_active=9`, `tools.surfaces_active=139`,
  `orchestration.surfaces_active=6`.

## Bug-free verify (4 axes)

- **pytest 20 / 20 GREEN** — `tests/test_dim_w_ax_layer3.py` runs
  cleanly against the local venv (`/Users/shigetoumeda/jpcite/.venv`).
  Covers migration apply / idempotency / rollback / CHECK constraints /
  ETL dry-run + apply + idempotent re-run / `--force` audit append /
  both helper views / boot manifest dual presence / LLM-0 grep / brand
  grep / no LLM-coupled columns in schema.
- **SQLite syntax check** — `sqlite3 :memory: < 283_ax_layer3.sql`
  parses cleanly (BEGIN/COMMIT wrap; PRAGMA foreign_keys=ON). Rollback
  also parses cleanly and drops every artefact.
- **3-axis seed verified** — fresh apply yields exactly 3
  am_webmcp_endpoint rows + 2 am_a2a_handshake_log rows + 8
  am_observability_metric rows; idempotent re-run is noop; `--force`
  re-append on audit tables grows handshake 2→4 and metric 8→16 while
  endpoint stays at 3 (UNIQUE backstop).
- **LLM-0 + brand hygiene** — grep guard inside the test suite asserts
  ZERO `import anthropic` / `import openai` / `google.generativeai` /
  `claude_agent_sdk` in `seed_ax_layer3.py` and ZERO legacy brand
  strings (`税務会計AI`, `zeimu-kaikei.ai`, `autonomath.ai`); also
  asserts ZERO `summary_text` / `ai_explanation` / `ai_summary`
  columns in the migration schema (non-comment lines only).

## Hard constraints honored

- **No existing AX 4 pillars overwrite** — confirmed no `am_webmcp*`
  / `am_a2a*` / `am_observability_metric` table existed before this
  migration; Layer 1+2 substrate (mcp.json / openapi / resources /
  prompts / discovery) is untouched.
- **No main worktree mutations** — all work performed inside
  `/tmp/jpcite-w47-dim-w-mig`; main worktree untouched.
- **No rm / mv** — purely additive (4 new files + 2 manifest appends).
- **No legacy brand** — only `jpcite`; zero `税務会計AI` /
  `zeimu-kaikei.ai` strings in any new file.
- **No LLM API import** — `seed_ax_layer3.py` imports only stdlib
  (`argparse / json / logging / sqlite3 / sys / pathlib`).

## Coexistence with parallel in-flight Dim worktrees

- Dim T (mig 280) — main HEAD, present in manifest above 283.
- Dim U (mig 281, credit_wallet) — in flight in
  `/tmp/jpcite-w47-dim-u-mig`. Migration number 281 already claimed in
  that worktree's tree; we leave 282 open for the next Dim worktree
  (likely dim-v).
- Dim G (in flight, separate task #255) — distinct dimension and
  distinct migration number. No collision with 283.

## PR diff scope

- `scripts/migrations/283_ax_layer3.sql` (new)
- `scripts/migrations/283_ax_layer3_rollback.sql` (new)
- `scripts/etl/seed_ax_layer3.py` (new)
- `tests/test_dim_w_ax_layer3.py` (new)
- `scripts/migrations/jpcite_boot_manifest.txt` (append-only)
- `scripts/migrations/autonomath_boot_manifest.txt` (append-only)
- `docs/research/wave46/STATE_w47_dim_w_pr.md` (this file)

## Next ticks

- Wire a daily cron after merge to read the runtime AX Layer 3 signals
  and append to `am_observability_metric` (replacing the 8-row seed
  with real telemetry).
- Wire `am_a2a_handshake_log` insert into the MCP session handler so
  every real handshake gets audited (currently only the 2 template
  seed rows exist).
